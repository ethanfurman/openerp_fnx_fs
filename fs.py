from fnx import check_company_settings, get_user_login, DateTime
from fnx.path import Path
from openerp import SUPERUSER_ID as SUPERUSER
from osv import osv, fields
from pwd import getpwuid
from subprocess import check_output, CalledProcessError
from tempfile import NamedTemporaryFile
from urllib import quote
import logging
import os
import re
import shutil
import threading

_logger = logging.getLogger(__name__)

CONFIG_ERROR = "Configuration not set; check Settings --> Configuration --> FnxFS --> %s."

fs_root = Path('/var/openerp/fnx_fs/')
permissions_file = Path('/var/openerp/fnx_fs.permissions')

execfile('/etc/openerp/fnx_fs')

READONLY_TYPE = (
    ('all', 'All FnxFS Users'),
    ('selected', 'Selected FnxFS Users'),
    )

FILE_TYPE = (
    ('auto', 'Auto-Publish'),   # OpenERP cron job updates the file
    ('manual', 'Publish'),      # user manually updates the file
    ('normal', 'Read/Write'),   # normal FS usage
    )

class fnx_fs_folders(osv.Model):
    '''
    virtual folders for shared files to appear in
    '''

    def _construct_path(self, cr, uid, ids, field_name, arg, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        records = self.browse(cr, uid, ids, context=context)
        res = {}
        for rec in records:
            res[rec.id] = self._get_path(cr, uid, rec.parent_id.id, rec.name, context=context) - fs_root
        return res

    _name = 'fnx.fs.folders'
    _description = 'where shared files show up'
    _rec_name = 'path'
    _columns = {
        'name': fields.char('Folder Name', size=64, required=True),
        'path': fields.function(
            _construct_path,
            type='char',
            string='Full Path',
            store=True,
            method=True,
            ),
        'description': fields.text('Description'),
        'file_ids': fields.one2many(
            'fnx.fs.files',
            'folder_id',
            'Files shared via this folder',
            ),
        'parent_id': fields.many2one(
            'fnx.fs.folders',
            'Parent Folder',
            ondelete='restrict',
            ),
        'child_ids': fields.one2many(
            'fnx.fs.folders',
            'parent_id',
            'Sub-Folders',
            ),
        }
    _sql_constraints = [
            ('folder_uniq', 'unique(name)', 'Folder already exists in system.'),
            ]

    def _get_path(self, cr, uid, parent_id, name, id=None, context=None):
        records = self.browse(cr, uid, self.search(cr, uid, [], context=context), context=context)
        folders = {}
        for rec in records:
            folders[rec.id] = rec
        path = [name]
        while parent_id:
            rec = folders[parent_id]
            if id is not None and id == rec.id:
                raise osv.osv_except('Error', 'Current parent assignment creates a loop!')
            parent = folders[parent_id]
            path.append(parent.name)
            parent_id = parent.parent_id.id
        folder = fs_root
        while path:
            folder /= path.pop()
        return folder

    def create(self, cr, uid, values, context=None):
        parent_id = values.get('parent_id')
        folder = self._get_path(cr, uid, parent_id, values['name'], context=context)
        if not folder.exists():
            folder.mkdir()
        if 'description' in values and values['description']:
            with open(folder/'README', 'w') as readme:
                readme.write(values['description'])
        return super(fnx_fs_folders, self).create(cr, uid, values, context=context)

    def write(self, cr, uid, ids, values, context=None):
        if ids:
            if isinstance(ids, (int, long)):
                ids = [ids]
            records = self.browse(cr, uid, ids, context=context)
            for rec in records:
                parent_id = values.get('parent_id', rec.parent_id.id)
                name = values.get('name', rec.name)
                new_path = self._get_path(cr, uid, parent_id, name, id=rec.id, context=context)
                if 'parent_id' in values or 'name' in values:
                    old_path = self._get_path(cr, uid, rec.parent_id.id, rec.name, context=context)
                    old = old_path.exists()
                    new = new_path.exists()
                    if old and new:
                        raise osv.osv_except('Error', '%r already exists.' % new_path)
                    elif old and not new:
                        old_path.move(new_path)
                    elif not new:
                        new_path.mkdir()
                if 'description' in values:
                    with open(new_path/'README', 'w') as readme:
                        readme.write(values['description'])
        return super(fnx_fs_folders, self).write(cr, uid, ids, values, context=context)

    def unlink(self, cr, uid, ids, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        to_be_deleted = []
        records = self.browse(cr, uid, ids, context=context)
        for rec in records:
            path = self._get_path(cr, uid, rec.parent_id.id, rec.name, context=context)
        res = super(fnx_fs_folders, self).unlink(cr, uid, ids, context=context)
        if res:
            for fp in to_be_deleted:
                if fp.exists():
                    fp.rmtree()
        return res

fnx_fs_folders()


class fnx_fs_files(osv.Model):
    '''
    Tracks files and restricts access.
    '''

    # TODO: when a file is created or updated to have 'entire_folder' as True, scan all files
    #       and set any others in the same source folder to have 'entire_folder' as True

    permissions_lock = threading.Lock()

    def _scan_fs(self, cr, uid, *args):
        return 1
        '''
        scans the file system for new documents
        '''
        _logger.info('status._scan_fs starting...')
        res_users = self.pool.get('res.users')
        # get networks to scan
        prefix = check_company_settings(self, cr, uid, ('prefix', 'File System', CONFIG_ERROR))['prefix']
        regex = check_company_settings(self, cr, uid, ('pattern', 'File System', CONFIG_ERROR))['pattern']
        # get known pcs
        current_files = []
        results = []
        for rec in self.browse(cr, uid, self.search(cr, uid, [(1,'=',1)])):
            filename = Path(rec.file_path) / rec.file_name
            current_files.append(filename)
        current_files = set(current_files)
        print current_files
        # generate list of files on disk
        disk_files = []
        good_dir = re.compile(regex)
        prefix = Path(prefix)/''
        for path, dirs, files in os.walk(prefix):
            if path == prefix:
                new_dirs = dirs[:]
                for d in new_dirs:
                    if not good_dir.search(d):
                        dirs.remove(d)
                continue
            path/''     # make sure path ends with slash
            for f in files:
                branch = path/f-prefix
                if branch not in current_files:
                    disk_files.append(branch)
                else:
                    print 'skipping', branch
        print disk_files
        logins = {}
        for branch in disk_files:
            values = {}
            login = getpwuid(os.stat(prefix/branch)[4]).pw_name
            oe_login = logins.get(login)
            if oe_login is None:
                oe_login = res_users.browse(cr, SUPERUSER, res_users.search(cr, SUPERUSER, [('login','=',login)]))[0].id
                logins[login] = oe_login
            values['user_id'] = oe_login
            values['file_path'] = branch.path
            values['file_name'] = branch.filename
            self.create(cr, SUPERUSER, values)
        return

    def _get_remote_file(self, cr, uid, values, context):
        fnx_fs_folders = self.pool.get('fnx.fs.folders')
        folder = fnx_fs_folders.browse(cr, uid, values['folder_id'], context=context).name
        ip_addr = values['ip_addr'] = context['__client_address__']
        file_name = values['file_name']
        shared_as = values['shared_as']
        login = get_user_login(self, cr, uid, context['uid'])
        new_env = os.environ.copy()
        new_env['SSHPASS'] = client_pass
        remote_cmd = [
                '/usr/bin/sshpass', '-e',
                '/usr/bin/ssh', 'root@%s' % ip_addr, '/bin/grep',
                '%s' % quote(file_name), '/home/%s/.local/share/recently-used.xbel' % login,
                #'/home/%s/.recently-used.xbel' % login,
                ]
        # <bookmark href="file:///home/ethan/plain.txt" added="2014-04-09T22:11:34Z" modified="2014-04-11T19:37:48Z" visited="2014-04-09T22:11:35Z">
        try:
            output = check_output(remote_cmd, env=new_env)
        except CalledProcessError, exc:
            raise osv.except_osv('Error','Unable to locate file.\n\n%s\n\n%s' % (exc, exc.output))
        matches = []
        for line in output.split('\n'):
            if not line:
                continue
            _, href, added, modied, visited = line.split()
            file_path = href.partition('://')[2].strip('"')
            added = DateTime(added.split('"')[1])
            modied = DateTime(modied.split('"')[1])
            matches.append((modied, file_path))
        matches.sort(reverse=True)
        file_path = values['full_name'] = matches[0][1]
        copy_cmd = [
                '/usr/bin/sshpass', '-e',
                '/usr/bin/scp', 'root@%s:%s' % (ip_addr, file_path),
                fs_root/folder/shared_as,
                ]
        try:
            output = check_output(copy_cmd, env=new_env)
        except CalledProcessError:
            raise osv.except_osv('Error','Unable to copy file.')

    def _write_permissions(self, cr, uid, context=None):
        # write a file in the form of:
        #
        # ethan:read:/Q&A/cashews.ods
        # emile:write:/Q&A/cashews.ods
        # ethan:write:/Q&A/almonds.ods
        # emile:write:/IT/ip_address.txt
        # tony:read:/IT/ip_address.txt
        # all:read:/IT/uh-oh.txt
        # all:read:/IT/Printers/FAQ.pdf
        # 
        with self.permissions_lock:
            files = self.browse(cr, uid, self.search(cr, uid, [],))
            lines = []
            for file in files:
                folder = file.folder_id.path
                path = Path('/')/folder/file.shared_as
                read_write = set()
                for user in file.readwrite_ids:
                    read_write.add(user.id)
                    lines.append('%s:write:%s' % (user.login, path))
                if file.readonly_type == 'all':
                    lines.append('all:read:%s' % path)
                else:
                    for user in file.readonly_ids:
                        if user.id not in read_write:
                            lines.append('%s:read:%s' % (user.login, path))
            with open(permissions_file, 'w') as data:
                data.write('\n'.join(lines) + '\n')

    _name = 'fnx.fs.files'
    _description = 'tracked files'
    _columns = {
        'user_id': fields.many2one(
            'res.users',
            'Owner',
            ondelete='set null',
            ),
        'readonly_type': fields.selection(
            READONLY_TYPE,
            'Read-Only Users',
            ),
        'readonly_ids': fields.many2many(
            'res.users',
            'fnx_readonly_perm_rel',
            'fid',
            'uid',
            'Read Only Access',
            domain="[('groups_id.category_id.name','=','FnxFS')]",
            ),
        'readwrite_ids': fields.many2many(
            'res.users',
            'fnx_readwrite_perm_rel',
            'fid',
            'uid',
            'Read/Write Access',
            domain="[('groups_id.category_id.name','=','FnxFS')]",
            ),
        'folder_id': fields.many2one(
            'fnx.fs.folders',
            'Folder',
            help='Folder to present document in.',
            required=True,
            ondelete='restrict',
            ),
        # simple path/file.ext of file (no IP address)
        # Emile has created a binaryname field type to allow client file selection but transferring only the file name
        'file_type': fields.selection(FILE_TYPE, 'Share Type', help=
            "Auto Publish --> OpenERP will update the file.\n"
            "Publish --> User updates the file via OpenERP.\n"
            "Read/Write --> Normal write access via the FnxFS file system."
            ),
        'file_name': fields.binaryname('Source File', type='char', size=256),
        'full_name': fields.char('Full path and file name', size=512),
        'ip_addr': fields.char('IP Address of source machine', size=15),
        'shared_as': fields.char(
            string='Shared As',
            size=64,
            ),
        # other miscellanea
        'entire_folder': fields.boolean('All files in this folder?'),
        'indexed_text': fields.text('Indexed content (TBI)'),
        'notes': fields.text('Notes'),
        }
    _sql_constraints = [
            ('file_uniq', 'unique(file_name)', 'File already exists in system.'),
            ('shareas_uniq', 'unique(shared_as)', 'Shared As name already exists in system.'),
            ]
    _defaults = {
        'user_id': lambda s, c, u, ctx={}: u,
        'readwrite_ids': lambda s, c, u, ctx={}: [u],
        'readonly_type': lambda s, c, u, ctx={}: 'all',
        'file_type': lambda s, c, u, ctx={}: 'manual',
        }

    def create(self, cr, uid, values, context=None):
        if not values.get('shared_as'):
            values['shared_as'] = values['file_name']
        if values['file_type'] != 'normal':
            self._get_remote_file(cr, uid, values, context)
        new_id = super(fnx_fs_files, self).create(cr, uid, values, context=context)
        self._write_permissions(cr, uid, context=context)
        current = self.browse(cr, uid, new_id)
        if current.file_type == 'normal':
            open(fs_root/current.folder_id.path/current.shared_as, 'w').close()
        return new_id

    def unlink(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        if isinstance(ids, (int, long)):
            ids = [ids]
        to_be_deleted = []
        records = self.browse(cr, uid, ids, context=context)
        for rec in records:
            full_name = fs_root / rec.folder_id.name / rec.shared_as
            to_be_deleted.append(full_name)
        res = super(fnx_fs_files, self).unlink(cr, uid, ids, context=context)
        self._write_permissions(cr, uid, context=context)
        if res:
            for fn in to_be_deleted:
                if fn.exists():
                    fn.unlink()
        return res

    def write(self, cr, uid, ids, values, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        fnx_fs_folders = self.pool.get('fnx.fs.folders')
        records = self.browse(cr, uid, ids, context=context)
        for rec in records:
            if 'shared_as' in values or 'folder_id' in values:
                if 'folder_id' in values:
                    folder_rec = fnx_fs_folders.browse(cr, uid, values['folder_id'], context=context)
                    folder = folder_rec.path
                else:
                    folder = rec.folder_id.path
                name = values.get('shared_as', rec.shared_as)
                old_path = fs_root/rec.folder_id.path/rec.shared_as
                new_path = fs_root/folder/name
                old = old_path.exists()
                new = new_path.exists()
                if old and new:
                    raise osv.osv_except('Error', '%r already exists.' % new_path)
                elif old and not new:
                    old_path.move(new_path)
                else:
                    raise osv.osv_except('Error', 'Neither %r nor %r exist!' % (old_path, new_path))
        success = super(fnx_fs_files, self).write(cr, uid, ids, values, context=context)
        self._write_permissions(cr, uid, context=context)
        return True

fnx_fs_files()
