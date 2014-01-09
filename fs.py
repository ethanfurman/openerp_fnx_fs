import logging
import os
import re
from fnx import check_company_settings
from fnx.path import Path
from openerp import SUPERUSER_ID as SUPERUSER
from osv import osv, fields
from pwd import getpwuid
from tempfile import NamedTemporaryFile
import threading

_logger = logging.getLogger(__name__)

CONFIG_ERROR = "Configuration not set; check Settings --> Configuration --> FnxFS --> %s."

#PERMISSIONS = (
#    ('read_only', 'Read Only'),
#    ('read_write', 'Read/Write'),
#    )
#
#class fnx_fs_permissions(osv.Model):
#    '''
#    permissions for shared files (currently RO or RW)
#    '''
#
#    _name = 'fnx.fs.permissions'
#    _description = 'file sharing permissions'
#    _columns = {
#        'user_id': fields.many2many(
#            'res.users',
#            'fnx_fs_perm_users_rel',
#            'pid',
#            'uid',
#            'User',
#            ),
#        'fnx_fs_file_permission': fields.selection(PERMISSIONS, 'File Permission'),
#        }
#    _defaults = {
#        'fnx_fs_file_permission': lambda *a: 'read_only',
#        }
#fnx_fs_permissions()

READONLY_TYPE = (
    ('all', 'All FnxFS Users'),
    ('selected', 'Seleceted FnxFS Users'),
    )

class fnx_fs_folders(osv.Model):
    '''
    virtual folders for shared files to appear in
    '''

    def _pdb(self, cr, uid, ids, field_name, arg, context=None):
        import pdb
        pdb.set_trace()
        xyz = 'bubba'

    _name = 'fnx.fs.folders'
    _description = 'where shared files show up'
    _columns = {
        'name': fields.char('Folder Name', size=64, required=True),
        'description': fields.text('Description'),
        'file_ids': fields.one2many(
            'fnx.fs.files',
            'folder_id',
            'Files shared via this folder',
            ),
        }
fnx_fs_folders()


class fnx_fs_files(osv.Model):
    '''
    Tracks files and restricts access.
    '''

    def _scan_fs(self, cr, uid, *args):
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

    def _split_file(self, cr, uid, ids, field_names, arg, context=None):
        '''
        192.168.11.31/home/<user>/path/to/file.odt

        ip_address: 192.168.11.31
        file_path:  /home/<user>/path/to/
        file_name:  file.odt
        '''
        if context is None:
            context = {}
        if len(ids) > 1:
            raise ValueError('can only process one file at a time')
        client_address = getattr(threading.current_thread(), 'clientip', None)
        if client_address is None:
            client_address = context.get('__client_address__')
        if client_address is None:
            raise ValueError('unable to retrieve __client_address__ from thread nor context')
        values = {}
        records = self.browse(cr, SUPERUSER, ids)
        for rec in records:
            values[rec.id] = {}
            values[rec.id]['ip_addr'] = client_address
            #import pdb; pdb.set_trace()
            src_file = Path(rec.source_file)
            filename = src_file.filename
            if filename.startswith("\\x"):
                filename = filename[2:].decode('hex')
            virtual_folder = rec.folder_id.name
            values[rec.id]['file_path'] = src_file.path
            values[rec.id]['file_name'] = filename
            values[rec.id]['edit_url'] = 'file:///~/Public/%s/%s' % (virtual_folder, filename)
            values[rec.id]['share_url'] = 'file:///home/oeshare/%s/%s' % (virtual_folder, filename)
        #print "in _split_file -- values = ",repr(values)
        return values

    def create(self, cr, uid, values, context=None):
        if not values.get('shared_as'):
            values['shared_as'] = Path(values['source_file']).filename
        new_id = super(fnx_fs_files, self).create(cr, uid, values, context=context)
        self._write_fnx_fs_request(cr, uid, [new_id], context=context)
        return new_id

    def unlink(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        success = super(fnx_fs_files, self).unlink(cr, uid, ids, context=context)
        if success:
            context['remove_file'] = True
            self._write_fnx_fs_request(cr, uid, ids, context=None)
        return success

    def write(self, cr, uid, ids, values, context=None):
        for id in ids:
            if not values.get('shared_as'):
                if values.get('source_file'):
                    source_file = Path(values['source_file'])
                else:
                    record = self.browse(cr, uid, id)
                    source_file = Path(record.source_file)
                values['shared_as'] = source_file.filename
        success = super(fnx_fs_files, self).write(cr, uid, ids, values, context=context)
        if success:
            self._write_fnx_fs_request(cr, uid, ids, context=context)
        return True

    def _write_fnx_fs_request(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        deleted = context.get('remove_file', False)
        fnx_fs_folders = self.pool.get('fnx.fs.folders')
        for id in ids:
            lines = []
            record = self.browse(cr, uid, [id], context=context)[0]
            ip_addr = record.ip_addr
            user = record.user_id.alias_name
            shared_as = record.shared_as
            entire_folder = record.entire_folder
            file_path = Path(record.file_path)
            file_name = Path(record.file_name)
            source = file_path / file_name
            target = Path('/') / record.folder_id.name / ''
            lines.append( 'ipaddr=%s'    % ip_addr)
            lines.append( 'source=%s'    % source)
            lines.append( 'target=%s'    % target)
            lines.append( 'user=%s'      % user)
            lines.append( 'all_files=%s' % entire_folder)
            lines.append( 'shared_as=%s' % shared_as)
            if not deleted:
                if record.readonly_type == 'all':
                    lines.append( 'shareto=all,permission=r')
                else:
                    for ro_user in record.readonly_ids:
                        lines.append( 'shareto=%s,permission=r' % ro_user.login)
                for rw_user in record.readwrite_ids:
                    lines.append( 'shareto=%s,permission=w' % rw_user.login)
            with NamedTemporaryFile(dir='/var/oeshare/requests', prefix='shr', delete=False) as file:
                file.write('\n'.join(lines))


    _name = 'fnx.fs.files'
    _description = 'tracked files'
    #_inherits = {'fnx.fs.permissions':'perm_id'}
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
        #'perm_id': fields.many2many(
            #'fnx.fs.permissions',
            #'fnx_file_perm_rel',
            #'fid',
            #'pid',
            #'Permissions',
            #required=True,
            #ondelete='cascade',
            #select=True,
            #),
        'folder_id': fields.many2one(
            'fnx.fs.folders',
            'Folder',
            help='Folder to present document in.',
            required=True,
            ondelete='restrict',
            ),
        # simple path/file.ext of file (no IP address)
        # I'm creating a binaryname field type to allow client file selection but transferring only the file name
        'source_file': fields.binaryname('Source File', type='char', size=256, required=True),
        # next four specify where the source file lives
        'edit_url': fields.function(
            _split_file,
            type='char',
            string='URL of editable source file',
            multi='file',
            store=True,
            ),
        'share_url': fields.function(
            _split_file,
            type='char',
            string='URL of read-only file',
            multi='file',
            store=True,
            ),
        'ip_addr': fields.function(
            _split_file,
            type='char',
            string='IP Address of source machine',
            multi='file',
            store=True,
            #store={
            #    'fnx_fs_files': (lambda s, c, u, ids, ctx={}: ids, ['src_file'], 10)
            #    },
            ),
        'file_path': fields.function(
            _split_file,
            type='char',
            string='File Path',
            multi='file',
            store=True,
            #store={
            #    'fnx_fs_files': (lambda s, c, u, ids, ctx={}: ids, ['src_file'], 10)
            #    },
            ),
        'file_name': fields.function(
            _split_file,
            type='char',
            string='File Name',
            multi='file',
            store=True,
            #store={
            #    'fnx_fs_files': (lambda s, c, u, ids, ctx={}: ids, ['src_file'], 10)
            #    },
            ),
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
        }
fnx_fs_files()
