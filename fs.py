from fnx import check_company_settings, get_user_login, get_user_timezone, DateTime, Time, Date, float, Weekday
from fnx.path import Path
from fnx.utils import xml_quote, xml_unquote
from openerp import SUPERUSER_ID as SUPERUSER
from osv import osv, fields
from pwd import getpwuid
from pytz import timezone
from subprocess import check_output, CalledProcessError
from tempfile import NamedTemporaryFile
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

PERIOD_TYPE = (
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('monthly', 'Monthly'),
    )
#
#class fnx_fs_schedule(osv.Model):
#    '''
#    schedule of files to automatically publish
#    '''
#    _name = 'fnx.fs.schedule'
#    _description = 'file update schedule'
#
#    _columns = {
#        file_id = fields.one2many(
#            'fnx.fs.files',
#            'schedule_id',
#            'File',
#            ),


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
                raise osv.except_osv('Error', 'Current parent assignment creates a loop!')
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
                        raise osv.except_osv('Error', '%r already exists.' % new_path)
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

    def fnx_fs_publish_file(self, cr, uid, ids, context):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res_users = self.pool.get('res.users')
        records = self.browse(cr, uid, ids, context=context)
        if uid != SUPERUSER and not any(uid == rw.id for rw in rec.readwrite_ids for rec in records):
            raise osv.except_osv('Error', 'You do not have write permission for this file.')
        raise osv.except_osv('Not Implemented', 'This feature is not yet implemented.')

    def fnx_fs_publish_times(self, cr, uid, ids=None, context=None):
        if ids is None:
            ids = self.search(cr, uid, [('file_type','=','auto')], context=context)
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = self.browse(cr, uid, ids, context=context)
        res.sort(key=lambda rec: rec.scheduled_at)
        return res

    def fnx_fs_scheduled_publish(self, cr, uid, context=None):
        publishable_files = self.fnx_fs_publish_times(cr, uid, context=context)
        for rec in publishable_files:
            if rec.scheduled_at < DateTime.now():
                break
            self._get_remote_file(cr, uid, {},
                    owner_id=rec.user_id.id, file_path=rec.full_name, ip=rec.ip_addr,
                    shared_as=rec.shared_as, folder_id=rec.folder_id.id,
                    context=context)
            if rec.schedule_period == 'daily':
                next_date = Date.today().replace(delta_day=1).date()
                self.write(cr, uid, [rec.id], {'schedule_date':next_date}, context=context)
            elif rec.schedule_period == 'weekly':
                scheduled_day = Weekday.from_date(rec.schedule_date)
                today = Weekday.from_date(Date.today())
                delta = today.next(scheduled_day)
                next_date = Date.today().replace(delta_day=delta).date()
                self.write(cr, uid, [rec.id], {'schedule_date':next_date}, context=context)
            elif rec.schedule_period == 'monthly':
                if rec.schedule_date.day >= 28:
                    next_date = Date(rec.schedule_date).replace(delta_month=2, day=1).replace(delta_day=-1).date()
                else:
                    next_date = Date(rec.schedule_date).replace(delta_month=1).date()
                self.write(cr, uid, [rec.id], {'schedule_date':next_date}, context=context)
        return True        

    def _calc_scheduled_at(self, cr, uid, ids, _field=None, _arg=None, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = {}
        user_tz = timezone(get_user_timezone(self, cr, uid)[uid])
        records = self.browse(cr, uid, ids, context=context)
        for rec in records:
            res[rec.id] = False
            date = rec.schedule_date
            time = rec.schedule_time or 0.0
            if date:
                dt = DateTime.combine(Date(date), Time.fromfloat(time)).datetime()
                dt = user_tz.localize(dt)
                res[rec.id] = dt
        return res

    def _get_remote_file(self, cr, uid, values,
            owner_id=None, file_path=None, ip=None, shared_as=None, folder_id=None,
            context=None):
        fnx_fs_folders = self.pool.get('fnx.fs.folders')
        if folder_id is None:
            folder_id = values['folder_id']
        if shared_as is None:
            shared_as = values['shared_as']
        if ip is None:
            ip = context['__client_address__']
        if owner_id is None:
            owner_id = values['user_id']
        if file_path is None:
            file_name = values['file_name']
        login = get_user_login(self, cr, uid, owner_id)
        folder = fnx_fs_folders.browse(cr, uid, folder_id, context=context).path
        new_env = os.environ.copy()
        new_env['SSHPASS'] = client_pass
        if file_path is None:
            remote_cmd = [
                    '/usr/bin/sshpass', '-e',
                    '/usr/bin/ssh', 'root@%s' % ip, '/bin/grep',
                    '%s' % xml_quote(file_name), '/home/%s/.local/share/recently-used.xbel' % login,
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
            file_path = values['full_name'] = xml_unquote(matches[0][1])
        copy_cmd = [
                '/usr/bin/sshpass', '-e',
                '/usr/bin/scp', 'root@%s:"%s"' % (ip, file_path),
                fs_root/folder/shared_as,
                ]
        try:
            output = check_output(copy_cmd, env=new_env)
        except CalledProcessError, exc:
            raise osv.except_osv('Error','Unable to copy file.\n\n%s\n\n%s' % (exc, exc.output))

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
                    if file.file_type == 'normal':
                        lines.append('%s:write:%s' % (user.login, path))
                    else:
                        lines.append('%s:read:%s' % (user.login, path))
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
    _rec_name = 'shared_as'
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
        'schedule_period': fields.selection(PERIOD_TYPE, 'Frequency'),
        'schedule_date': fields.date('Next publish date'),
        'schedule_time': fields.float('Next publish time'),
        'scheduled_at': fields.function(
            _calc_scheduled_at,
            type='datetime',
            string='Scheduled Date/Time',
            store={
                'fnx.fs.files': (_calc_scheduled_at, ['schedule_date', 'schedule_time'], 10),
                },
            ),
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
        shared_as = Path(values['shared_as'])
        if values['file_type'] == 'normal':
            if not shared_as.ext:
                osv.except_osv('Error', 'Shared name should have an extension indicating file type.')
            open(fs_root/current.folder_id.path/current.shared_as, 'w').close()
        else:
            values['ip_addr'] = context['__client_address__']
            source_file = Path(values['file_name'])
            if shared_as.ext != '.' and shared_as.ext != source_file.ext:
                values['shared_as'] = shared_as + source_file.ext
            self._get_remote_file(cr, uid, values, context=context)
        new_id = super(fnx_fs_files, self).create(cr, uid, values, context=context)
        self._write_permissions(cr, uid, context=context)
        current = self.browse(cr, uid, new_id)
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
            source_file = Path(values.get('file_name', rec.file_name or ''))
            sfe = source_file and source_file.ext
            shared_as = Path(values.get('shared_as', rec.shared_as))
            folder_id = values.get('folder_id', rec.folder_id.id)
            old_path = fs_root/rec.folder_id.path/rec.shared_as
            if shared_as.ext not in ('.', sfe):
                shared_as += source_file.ext
                values['shared_as'] = shared_as
            if 'shared_as' in values or 'folder_id' in values:
                if 'folder_id' in values:
                    folder_rec = fnx_fs_folders.browse(cr, uid, folder_id, context=context)
                    folder = folder_rec.path
                else:
                    folder = rec.folder_id.path
                name = shared_as
                new_path = fs_root/folder/name
                old = old_path.exists()
                new = new_path.exists()
                if old and new:
                    raise osv.except_osv('Error', '%r already exists.' % new_path)
                elif old and not new:
                    old_path.move(new_path)
                else:
                    raise osv.except_osv('Error', 'Neither %r nor %r exist!' % (old_path, new_path))
            if 'user_id' in values:
                owner_id = values['user_id']
            else:
                owner_id = rec.user_id.id
            if 'file_name' in values:
                self._get_remote_file(cr, uid, values, owner_id=owner_id, folder_id=folder_id, shared_as=shared_as, context=context)
        success = super(fnx_fs_files, self).write(cr, uid, ids, values, context=context)
        self._write_permissions(cr, uid, context=context)
        return True

fnx_fs_files()
