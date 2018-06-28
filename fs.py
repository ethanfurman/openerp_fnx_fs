from antipathy import Path
from dbf import DateTime, Time, Date
from VSS.utils import  float
from VSS.constants import Weekday
from fnx.oe import get_user_login, get_user_timezone, AttrDict
from openerp import CONFIG_DIR, SUPERUSER_ID as SUPERUSER
from openerp.exceptions import ERPError
from osv import osv, fields
from pytz import timezone
from scription import Execute, OrmFile
from subprocess import check_output, CalledProcessError
from xaml import Xaml
import errno
import logging
import os
import pwd
import socket
import threading
import time

_logger = logging.getLogger(__name__)

openerp_ids = tuple(pwd.getpwnam('openerp')[2:4])

CONFIG_ERROR = "Configuration not set; check Settings --> Configuration --> FnxFS --> %s."

fs_root = Path(u'/var/openerp/fnxfs/')
archive_root = Path(u'/var/openerp/fnxfs_archive/')
permissions_file = Path(u'/var/openerp/fnxfs.permissions')
mount_file = Path(u'%s/fnxfs.mount' % CONFIG_DIR)

config = OrmFile('%s/fnx.ini' % CONFIG_DIR, section='fnxfsd')

PERMISSIONS_TYPE = (
    ('inherit', 'Inherited from parent folder'),
    ('custom', 'Custom'),
    )

READONLY_TYPE = (
    ('all', 'All FnxFS Users'),
    ('selected', 'Selected FnxFS Users'),
    )

FOLDER_TYPE = (
    ('virtual', 'Virtual'),
    ('reflective', 'Mirrored'),
    ('shared', 'Shared'),
    )

FILE_TYPE = (
    ('auto', 'Auto-Publish'),   # OpenERP cron job updates the file
    ('manual', 'Publish'),      # user manually updates the file
    ('normal', 'Editable'),   # normal FS usage
    )

PERIOD_TYPE = (
    ('hourly', 'Hourly'),
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('monthly', 'Monthly'),
    )

permissions_lock = threading.Lock()
mount_lock = threading.Lock()


def _folder_access(self, cr, uid, folder):
    '''return user access to folder

    folder -> fnx.fs.folder browse object
    return -v
            0 - no access
            1 - read access
            2 - write access
            4 - create/delete access
    '''
    access = 0
    if any(u.id == uid for u in folder.readonly_ids):
        access = 1
    if any(u.id == uid for u in folder.readwrite_ids):
        access = 2
        if folder.collaborative:
            access = 3
    if access and folder.parent_id:
        # check all parents to make sure user can see this folder
        folder = folder.parent_id
        if not any(u.id == uid for u in (folder.readonly_ids + folder.readwrite_ids)):
            return 0
    return access

def _remote_locate(user, file_name, context=None):
    if context is None:
        context = {}
    client = context.get('__client_address__')
    if client is None:
        raise ERPError('Error','Unable to locate remote copy because client ip is missing')
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((client, 8068))
    sock.sendall('service:find_path\nuser:%s\nfile_name:%s\n' % (user, file_name))
    data = sock.recv(1024)
    sock.close()
    status, result = data.split(':', 1)
    if status == 'error':
        error = getattr(errno, result, None)
        if error is None:
            raise OSError(result)
        raise OSError(error)
    elif status == 'exception':
        raise Exception(result)
    return Path(result.strip())

def _user_level(obj, cr, uid, context=None):
    user = obj.pool.get('res.users').browse(cr, SUPERUSER, uid, context=context)
    if user.has_group('fnx_fs.manager'):
        return 'manager'
    elif user.has_group('fnx_fs.creator'):
        return 'creator'
    elif user.has_group('fnx_fs.consumer'):
        return 'consumer'
    else:
        raise ERPError('Programming Error', 'Cannot find FnxFS group for %r' % user.login)

def write_mount(oe, cr):
    return
    fnxfs_folder = oe.pool.get('fnx.fs.folder')
    with mount_lock:
        lines = []
        for folder in fnxfs_folder.browse(cr, SUPERUSER, fnxfs_folder.search(cr, SUPERUSER, [])):
            if folder.folder_type == 'virtual':
                continue
            elif folder.folder_type == 'reflective':
                mount_point = fs_root/folder.path
                if not mount_point.exists():
                    mount_point.makedirs()
                mount_options = folder.mount_options
                mount_from = folder.mount_from
            elif folder.folder_type == 'shared':
                mount_point = fs_root/folder.path
                if not mount_point.exists():
                    mount_point.makedirs()
                mount_options = 'ssh'
                mount_from = folder.file_folder_name
            else:
                raise ERPError('Programmer Error', 'Unknown folder type: %s' % folder.folder_type)
            lines.append('%s\t%s\t%s\n' % (mount_point, mount_options, mount_from))
        with open(mount_file, 'w') as data:
            data.write(''.join(lines))

def write_permissions(oe, cr):
    return
    # write a file in the form of:
    #
    # rgiannini:read:/Q&A/*
    # cso:write:/Q&A/*
    # ethan:read:/Q&A/cashews.ods
    # emile:write:/Q&A/cashews.ods
    # ethan:write:/Q&A/almonds.ods
    # emile:write:/IT/ip_address.txt
    # tony:read:/IT/ip_address.txt
    # all:read:/IT/uh-oh.txt
    # all:read:/IT/Printers/FAQ.pdf
    #
    fnxfs_folder = oe.pool.get('fnx.fs.folder')
    fnxfs_file = oe.pool.get('fnx.fs.file')
    res_users = oe.pool.get('res.users')
    with permissions_lock:
        # ids = []
        mode = 'w'
        folders = fnxfs_folder.browse(cr, SUPERUSER)
        files = fnxfs_file.browse(cr, SUPERUSER)
        fnx_fs_users = [u.login for u in res_users.browse(cr, SUPERUSER, [('groups_id.category_id.name','=','FnxFS')])]
        lines = []
        root = Path(u'/')
        for folder in folders:
            seen = set()
            if folder.collaborative:
                max_perm = 'create'
            else:
                max_perm = 'write'
            # default is deny all
            lines.append('all:none:%s/*' % (root/folder.path))
            perm_folder = folder
            while perm_folder.perm_type != 'custom':
                # search parents until 'custom' found
                perm_folder = folder.parent_id
                if perm_folder in (False, None):
                    # reached the end, nothing found -- skip
                    break
            else:
                if perm_folder.readonly_type == 'all':
                    lines.append('all:read:%s/*' % (root/folder.path))
                elif perm_folder.readonly_type != 'selected':
                    raise ERPError('Programming Error', 'unknown readonly type: %r' % perm_folder.readonly_type)
                for user in (perm_folder.readwrite_ids or []):
                    seen.add(user.id)
                    lines.append('%s:%s:%s/*' % (user.login, max_perm, root/folder.path))
                for user in perm_folder.readonly_ids:
                    if user.id not in seen:
                        lines.append('%s:read:%s/*' % (user.login, root/folder.path))
                if folder.share_owner_id not in seen and folder.share_owner_id.login not in (None, 'openerp'):
                    lines.append('%s:read:%s/*' % (folder.share_owner_id.login, root/folder.path))
        for file in files:
            if file.perm_type == 'inherit':
                continue
            folder = file.folder_id.path
            path = Path(u'/')/folder/file.shared_as
            read_write = set()
            # default is deny all
            lines.append('all:none:%s' % path)
            for user in (file.readwrite_ids + [file.user_id]):
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
        with open(permissions_file, mode) as data:
            data.write(','.join(fnx_fs_users) + '\n')
            data.write('\n'.join(lines) + '\n')


class fnx_fs_folder(osv.Model):
    '''
    virtual folders for shared files to appear in
    '''

    def change_permissions(self, cr, uid, ids, perm_type, parent_id, called_from, context=None):
        res = {}
        if called_from == 'folder' and perm_type == 'custom' or not parent_id:
            return res
        # assuming only one id
        parent_folder = self.browse(cr, uid, parent_id, context=context)
        value = res['value'] = {}
        value['readonly_type'] = parent_folder.readonly_type
        value['readonly_ids'] = [rec.id for rec in parent_folder.readonly_ids]
        value['readwrite_ids'] = [rec.id for rec in parent_folder.readwrite_ids]
        return res

    def _construct_path(self, cr, uid, ids, field_name, arg, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        records = self.browse(cr, uid, ids, context=context)
        res = {}
        for rec in records:
            res[rec.id] = self._get_path(cr, uid, rec.parent_id.id, rec.name, context=context) - fs_root
        return res

    def _get_default_folder_type(self, cr, uid, context=None):
        if self.pool.get('res.users').has_group(cr, uid, 'fnx_fs.creator', context=context):
            return 'virtual'
        else:
            return 'shared'

    def _get_path(self, cr, uid, parent_id, name, id=None, context=None):
        records = self.browse(cr, uid, self.search(cr, uid, [], context=context), context=context)
        folders = {}
        for rec in records:
            folders[rec.id] = rec
        path = [name]
        while parent_id:
            rec = folders[parent_id]
            if id is not None and id == rec.id:
                raise ERPError('Error', 'Current parent assignment creates a loop!')
            parent = folders[parent_id]
            path.append(parent.name)
            parent_id = parent.parent_id.id
        folder = fs_root
        while path:
            folder /= path.pop()
        return folder

    def _get_remote_path(self, cr, uid, file_name, context=None):
        if uid == SUPERUSER:
            raise ERPError('Not Implemented', 'Only normal users can create user shares')
        uid = context.get('uid')
        user = self.pool.get('res.users').browse(cr, SUPERUSER, uid, context=context).login
        try:
            path = _remote_locate(user, file_name, context=context)
        except Exception, exc:
            raise ERPError("Error", "Error trying to locate folder.\n\n%s" % exc)
        elements = path.elements
        if len(elements) < 3 or elements[2] != user:
            raise ERPError(
                    'Unshareable Folder',
                    'Only folders in your home directory or its subfolders can be shared.',
                    )
        elif len(elements) > 3 and elements[3] == 'FnxFS':
            raise ERPError(
                    'Unshareable Folder',
                    'Cannot share folders directly from the FnxFS shared directory.',
                    )
        return path

    _name = 'fnx.fs.folder'
    _description = 'FnxFS folder'
    _rec_name = 'path'
    _order = 'path asc'
    _columns = {
        'id': fields.integer('ID'),
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
            'fnx.fs.file',
            'folder_id',
            'Files shared via this folder',
            ),
        'parent_id': fields.many2one(
            'fnx.fs.folder',
            'Parent Folder',
            ondelete='restrict',
            domain="[('folder_type','=','virtual')]"
            ),
        'child_ids': fields.one2many(
            'fnx.fs.folder',
            'parent_id',
            'Sub-Folders',
            ),
        'perm_type': fields.selection(
            PERMISSIONS_TYPE,
            'Permissions type',
            required=True
            ),
        'readonly_type': fields.selection(
            READONLY_TYPE,
            'Read-Only Users',
            ),
        'readonly_ids': fields.many2many(
            'res.users',
            'fnx_folder_readonly_perm_rel',
            'fid',
            'uid',
            'Read Only Access',
            domain="[('groups_id.category_id.name','=','FnxFS'),('id','!=',1),('login','!=','openerp')]",
            ),
        'readwrite_ids': fields.many2many(
            'res.users',
            'fnx_folder_readwrite_perm_rel',
            'fid',
            'uid',
            'Read/Edit Access',
            domain="[('groups_id.category_id.name','=','FnxFS'),('id','!=',1),('login','!=','openerp')]",
            ),
        'folder_type': fields.selection(
            FOLDER_TYPE,
            'Folder Type',
            ),
        'mount_from': fields.char('Mirrored from', size=256),
        'mount_options': fields.char('Mount options', size=64),
        'file_folder_name': fields.binaryname('File in Folder', type='char', size=256),
        'share_owner_id': fields.many2one(
            'res.users',
            'Share Owner',
            domain="[('groups_id.category_id.name','=','FnxFS'),('id','!=',1),('login','!=','openerp')]",
            required=True,
            ),
        'collaborative': fields.boolean(
            'Create/Delete for Read/Edit users?',
            help="These users have complete control over all files in this folder",
            ),
        }
    _sql_constraints = [
        ('folder_path_uniq', 'unique(path)', 'Folder already exists in system.'),
        ]
    _defaults = {
        'readonly_type': lambda *a: 'selected',
        'folder_type': _get_default_folder_type,
        'mount_options': lambda *a: '-t cifs',
        'share_owner_id': lambda s, c, u, ctx=None: u != 1 and u or '',
        'perm_type': lambda *a: 'custom',
        }

    def create(self, cr, uid, values, context=None):
        if _user_level(self, cr, uid, context=context) == 'consumer':
            raise ERPError('Permission Denied', 'consumers cannot create folders')
        if '/' in values['name']:
            raise ERPError('Error', 'Cannot have "/" in the folder name.')
        parent_id = values.get('parent_id')
        if parent_id:
            parent_folder = self.browse(cr, uid, parent_id, context=context)
            if parent_folder.folder_type != 'virtual':
                raise ERPError('Incompatible Folder', 'Only Virtual folders can have subfolders')
        folder = self._get_path(cr, uid, parent_id, values['name'], context=context)
        if values['folder_type'] != 'shared':
            user_type = _user_level(self, cr, uid, context=context)
            if (
                user_type == 'consumer' or
                user_type == 'creator' and values['folder_type'] == 'mirrored'
                ):
                raise ERPError('User Error', 'You cannot create folders of that type.')
        if values.get('file_folder_name'):
            target = values['file_folder_name']
            values['file_folder_name'] = '%s:%s' % (
                context['__client_address__'],
                self._get_remote_path(cr, uid, target, context=context),
                )
        if not folder.exists():
            folder.mkdir()
        if 'description' in values and values['description'] and values['folder_type'] == 'virtual':
            with open(folder/'README', 'w') as readme:
                readme.write(values['description'])
        new_id = super(fnx_fs_folder, self).create(cr, uid, values, context=context)
        write_permissions(self, cr)
        if values['folder_type'] != 'virtual':
            write_mount(self, cr)
            self.fnx_start_share(cr, uid, [new_id], context=context)
        return new_id

    def fnx_start_share(self, cr, uid, ids, share_name=None, context=None):
        if share_name is not None and not isinstance(ids, (int, long)) and len(ids) > 1:
            raise ERPError('Programming Error', 'Cannot specify a share name and more than one record')
        if isinstance(ids, (int, long)):
            ids = [ids]
        if share_name is not None:
            share_names = [share_name]
        else:
            share_names = []
            for share in self.browse(cr, uid, ids, context=context):
                share_names.append(share.path)
        for share_name in share_names:
            share_cmd = ['/usr/local/bin/fnxfs', 'shares', 'start', share_name]
            try:
                check_output(share_cmd)
            except Exception:
                _logger.exception('Unable to start share: %s', share_name)
                return False
        return True

    def fnx_stop_share(self, cr, uid, ids, share_name=None, context=None):
        if share_name is not None and not isinstance(ids, (int, long)) and len(ids) > 1:
            raise ERPError('Programming Error', 'Cannot specify a share name and more than one record')
        if isinstance(ids, (int, long)):
            ids = [ids]
        if share_name is not None:
            share_names = [share_name]
        else:
            share_names = []
            for share in self.browse(cr, uid, ids, context=context):
                share_names.append(share.path)
        for share_name in share_names:
            share_cmd = ['/usr/local/bin/fnxfs', 'shares', 'stop', share_name]
            _logger.info('%s', ' '.join(share_cmd))
            result = Execute(share_cmd)
            if result.returncode or result.stderr:
                for line in (result.stdout + '\n' + result.stderr).split('\n'):
                    line = line.strip()
                    if line:
                        _logger.error(line)
                return False
            # try:
            #     output = check_output(share_cmd, stderr=STDOUT)
            # except Exception, exc:
            #     print(exc)
            #     _logger.warning(exc.output)
            #     _logger.exception('Unable to stop share: %s', share_name)
            #     return False
        return True

    def write(self, cr, uid, ids, values, context=None):
        if 'name' in values and '/' in values['name']:
            raise ERPError('Error', 'Cannot have "/" in the folder name.')
        remount = []
        if ids:
            if isinstance(ids, (int, long)):
                ids = [ids]
            for folder in self.browse(cr, uid, ids, context=context):
                parent_id = values.get('parent_id', folder.parent_id.id)
                name = values.get('name', folder.name)
                new_path = self._get_path(cr, uid, parent_id, name, id=folder.id, context=context)
                if 'folder_type' in values:
                    raise ERPError('Not Implemented', 'Cannot change the folder type.')
                if 'parent_id' in values or 'name' in values:
                    old_path = self._get_path(cr, uid, folder.parent_id.id, folder.name, context=context)
                    old = old_path.exists()
                    new = new_path.exists()
                    if old and new:
                        raise ERPError('Error', '%r already exists.' % new_path)
                    if folder.folder_type != 'virtual':
                        folder.fnx_stop_share()
                        attempts = 0
                        while "mount is still active" and attempts < 3:
                            attempts += 1
                            if old_path.listdir():
                                _logger.warning('mount still being shared')
                                time.sleep(1)
                            else:
                                break
                    if old and not new:
                        if not old_path.listdir():
                            old_path.move(new_path)
                    if not new_path.exists():
                        new_path.mkdir()
                    if folder.folder_type != 'virtual':
                        remount.append(folder)
                if 'description' in values:
                    with open(new_path/'README', 'w') as readme:
                        readme.write(values['description'] or '')
        res = super(fnx_fs_folder, self).write(cr, uid, ids, values, context=context)
        write_permissions(self, cr)
        if values.get('mount_from') or values.get('mount_options') or remount:
            write_mount(self, cr)
        for folder in remount:
            time.sleep(3)
            folder.refresh()
            folder.fnx_start_share()
        return res

    def unlink(self, cr, uid, ids, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        user_type = _user_level(self, cr, uid, context=context)
        to_be_deleted = []
        to_be_unmounted = []
        folders = self.browse(cr, uid, ids, context=context)
        for folder in folders:
            # TODO: check for files and issue nice error message
            path = self._get_path(cr, uid, folder.parent_id.id, folder.name, context=context)
            if folder.folder_type == 'shared':
                if user_type != 'manager' and folder.share_owner_id.id != uid:
                    raise ERPError('Error', 'Only %s or a manager can delete this share' % folder.share_owner_id.name)
                to_be_unmounted.append((folder.id, path))
            elif folder.folder_type == 'reflective':
                if user_type != 'manager':
                    raise ERPError('Error', 'Only managers can remove Mirrored folders')
                to_be_unmounted.append((folder.id, path))
            elif folder.folder_type == 'virtual':
                if user_type != 'manager':
                    raise ERPError('Error', 'Only managers can remove Virtual folders')
                to_be_deleted.append(path)
            else:
                raise ERPError('Programming Error', 'Unknown folder type: %s' % folder.folder_type)
        res = super(fnx_fs_folder, self).unlink(cr, uid, ids, context=context)
        if res:
            write_permissions(self, cr)
            for fp in to_be_deleted:
                if fp.exists():
                    fp.rmtree()
            for id, fp in to_be_unmounted:
                _logger.info('stopping share %s', fp)
                if not self.fnx_stop_share(cr, uid, id, share_name=(fp-fs_root), context=context):
                    raise ERPError('Error', 'Unable to stop share "%s"' % (fp-fs_root))
                _logger.info('removing mount point %s', fp)
                attempts = 0
                while "mount is active" and attempts < 3:
                    attempts += 1
                    if fp.listdir():
                        _logger.warning('mount still being shared')
                        time.sleep(1)
                    else:
                        fp.rmdir()
                        break
            write_mount(self, cr)
        return res


class fnx_fs_file(osv.Model):
    '''
    Tracks files and restricts access.
    '''

    copy_lock = threading.Lock()

    def fnx_fs_publish_file(self, cr, uid, ids, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        # res_users = self.pool.get('res.users')
        records = self.browse(cr, uid, ids, context=context)
        if uid != SUPERUSER:
            for rec in records:
                if uid in [rw.id for rw in rec.readwrite_ids]:
                    break
            else:
                raise ERPError('Error', 'You do not have write permission for this file.')
        self._get_remote_file(cr, uid, {},
                owner_id=rec.user_id.id, file_path=rec.full_name, ip=rec.ip_addr,
                shared_as=rec.shared_as, folder_id=rec.folder_id.id,
                context=context)
        return True

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
            scheduled = DateTime(rec.scheduled_at)
            now = DateTime.now()
            if scheduled > now:
                break
            self._get_remote_file(cr, uid, {},
                    owner_id=rec.user_id.id, file_path=rec.full_name, ip=rec.ip_addr,
                    shared_as=rec.shared_as, folder_id=rec.folder_id.id,
                    context=context)
            if rec.schedule_period == 'hourly':
                next_date = now.replace(
                        delta_hour=1,
                        minute=scheduled.minute,
                        second=scheduled.second,
                        microsecond=scheduled.microsecond,
                        )
                if float(next_date - now) > 1.25:
                    # if wait is longer that 1 hour 15 minutes, bump it up
                    next_date = next_date.replace(delta_hour=-1)
            if rec.schedule_period == 'daily':
                next_date = now.replace(
                        delta_day=1,
                        hour=scheduled.hour,
                        minute=scheduled.minute,
                        second=scheduled.second,
                        microsecond=scheduled.microsecond,
                        )
                if float(next_date - now) > 26:
                    next_date = now.replace(delta_day=-1)
            elif rec.schedule_period == 'weekly':
                scheduled_day = Weekday.from_date(scheduled)
                today = Weekday.from_date(Date.today())
                delta = today.next(scheduled_day)
                next_date = now.replace(
                        delta_day=delta,
                        hour=scheduled.hour,
                        minute=scheduled.minute,
                        second=scheduled.second,
                        microsecond=scheduled.microsecond,
                        )
                if float(next_date - now) > 170:
                    next_date = next_date.replace(delta_day=-7)
            elif rec.schedule_period == 'monthly':
                if scheduled.day >= 28:
                    if now.day < 28:
                        next_date = scheduled.replace(month=now.month)
                    else:
                        next_date = now.replace(
                                delta_month=2,
                                day=1).replace(
                                        delta_day=-1,
                                        hour=scheduled.hour,
                                        minute=scheduled.minute,
                                        second=scheduled.second,
                                        microsecond=scheduled.microsecond,
                                        )
                else:
                    if now.day < scheduled.day:
                        # ran because system was down and playng catch-up
                        # run again this month at the normal time
                        next_date = scheduled.replace( month=now.month)
                    else:
                        next_date = now.replace(
                                delta_month=1,
                                day=scheduled.day,
                                hour=scheduled.hour,
                                minute=scheduled.minute,
                                second=scheduled.second,
                                microsecond=scheduled.microsecond,
                                )
            self.write(cr, uid, [rec.id], {'schedule_date':next_date}, context=context)
        return True

    def _calc_scheduled_at(self, cr, uid, ids, _field=None, _arg=None, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = {}
        user_tz = timezone(get_user_timezone(self, cr, uid, context=context)[uid])
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
        with self.copy_lock:
            fnx_fs_folder = self.pool.get('fnx.fs.folder')
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
            else:
                file_path = Path(file_path)
                values['file_name'] = values.get('file_name', file_path.filename)
            user = get_user_login(self, cr, SUPERUSER, owner_id, context=context)
            folder = fnx_fs_folder.browse(cr, uid, folder_id, context=context).path
            new_env = os.environ.copy()
            new_env['SSHPASS'] = config.server_root
            if file_path is None:
                uid = context.get('uid')
                # res_users = self.pool.get('res.users')
                try:
                    path = _remote_locate(user, file_name, context=context)
                except Exception, exc:
                    raise ERPError("Error", "Error trying to locate file.\n\n%s" % exc)
                file_path = values['full_name'] = path/file_name
            elements = file_path.dir_elements
            if len(elements) < 3 or elements[2] != user:
                raise ERPError(
                        'Unshareable File',
                        'Only files in your home directory or its subfolders can be shared.\n(%s)' % file_path,
                        )
            elif len(elements) > 3 and elements[3] == 'FnxFS':
                raise ERPError(
                        'Unshareable File',
                        'Cannot share files directly from the FnxFS shared directory.\n(%s)' % file_path,
                        )
            copy_cmd = [
                    '/usr/bin/sshpass', '-e',
                    '/usr/bin/scp', '-o', 'StrictHostKeyChecking=no', 'root@%s:"%s"' % (ip, file_path),
                    fs_root/folder/shared_as,
                    ]
            try:
                check_output(copy_cmd, env=new_env)
            except CalledProcessError, exc:
                raise ERPError('Error','Unable to retrieve file.\n\n%s\n\n%s' % (exc, exc.output))
            try:
                (fs_root/folder/shared_as).chown(*openerp_ids)
            except OSError:
                pass
            archive_cmd = ['/usr/local/bin/fnxfs', 'archive', fs_root/folder/shared_as]
            try:
                check_output(archive_cmd, env=new_env)
            except Exception, exc:
                raise ERPError('Error','Unable to archive file:\n\n%s' % (exc, ))

    def change_file_type(self, cr, uid, ids, file_type, context=None):
        res = {}
        res['value'] = values = {}
        if uid == SUPERUSER or file_type != 'normal':
            values['user_id'] = self.pool.get('res.users').browse(cr, SUPERUSER, [('login','=','openerp')], context=context)[0].id
        else:
            values['user_id'] = uid
        return res

    def change_permissions(self, cr, uid, ids, perm_type, folder_id, called_from, context=None):
        res = {}
        if called_from == 'folder' and perm_type == 'custom' or not folder_id:
            return res
        # assuming only one id
        folder = self.pool.get('fnx.fs.folder').browse(cr, uid, folder_id, context=context)
        value = res['value'] = {}
        value['readonly_type'] = folder.readonly_type
        value['readonly_ids'] = [rec.id for rec in folder.readonly_ids]
        value['readwrite_ids'] = [rec.id for rec in folder.readwrite_ids]
        return res

    _name = 'fnx.fs.file'
    _description = 'FnxFS file'
    _rec_name = 'shared_as'
    _columns = {
        'id': fields.integer('ID'),
        'user_id': fields.many2one(
            'res.users',
            'Owner',
            ondelete='set null',
            domain="[('groups_id.category_id.name','=','FnxFS'),('id','!=',1)]",
            help='the owner of a file always has edit privileges',
            ),
        'perm_type': fields.selection(
            PERMISSIONS_TYPE,
            'Permissions Type',
            required=True,
            ),
        'readonly_type': fields.selection(
            READONLY_TYPE,
            'Read-Only Users',
            ),
        'readonly_ids': fields.many2many(
            'res.users',
            'fnx_file_readonly_perm_rel',
            'fid',
            'uid',
            'Read Only Access',
            domain="[('groups_id.category_id.name','=','FnxFS'),('id','!=',1),('login','!=','openerp')]",
            ),
        'readwrite_ids': fields.many2many(
            'res.users',
            'fnx_file_readwrite_perm_rel',
            'fid',
            'uid',
            'Read/Edit Access',
            domain="[('groups_id.category_id.name','=','FnxFS'),('id','!=',1),('login','!=','openerp')]",
            ),
        'folder_id': fields.many2one(
            'fnx.fs.folder',
            'Folder',
            required=True,
            ondelete='restrict',
            domain="[('folder_type','=','virtual')]",
            ),
        # simple path/file.ext of file (no IP address)
        # Emile has created a binaryname field type to allow client file selection but transferring only the file name
        'file_type': fields.selection(
            FILE_TYPE,
            'Share Type',
            help=
                "Auto Publish --> OpenERP will update the file.\n"
                "Publish --> User updates the file via OpenERP.\n"
                "Editable --> Normal write access via the FnxFS file system.",
            required=True,
            ),
        'file_name': fields.binaryname('Source File', type='char', size=256),
        'full_name': fields.char('Full path and file name', size=512),
        'ip_addr': fields.char('IP Address of source machine', size=15),
        'shared_as': fields.char(
            string='Shared As',
            size=64,
            ),
        # other miscellanea
        'indexed_text': fields.text('Indexed content (TBI)'),
        'notes': fields.text('Notes'),
        'schedule_period': fields.selection(PERIOD_TYPE, 'Frequency'),
        #'schedule_date': fields.date('Next publish date'),
        #'schedule_time': fields.float('Next publish time'),
        'scheduled_at': fields.datetime('Next publishing at'),
        }

    _sql_constraints = [
            ('full_name_uniq', 'unique(full_name)', 'Path/File already exists in system.'),
            # ('file_uniq', 'unique(file_name)', 'File already exists in system.'),
            # ('shareas_uniq', 'unique(shared_as)', 'Shared As name already exists in system.'),
            ]
    _defaults = {
        'user_id': lambda s, c, u, ctx={}: u != 1 and u or '',
        'perm_type': lambda *a: 'inherit',
        'readwrite_ids': lambda s, c, u, ctx={}: u != 1 and [u] or [],
        'readonly_type': lambda *a: 'all',
        'file_type': lambda *a: 'normal',
        }

    def create(self, cr, uid, values, context=None):
        folders = self.pool.get('fnx.fs.folder')
        if isinstance(values['folder_id'], basestring):
            target = folders.browse(self, cr, SUPERUSER, [('full_path','=',values['folder_id'])], context=context)
            if not target:
                raise ERPError('Folder Missing', 'folder %r does not exist' % values['folder_id'])
            folder = target[0]
        else:
            folder = folders.browse(cr, SUPERUSER, values['folder_id'], context=context)
        if folder.folder_type != 'virtual':
            raise ERPError('Invalid Folder', 'files can only be saved into Virtual folders')
        elif _user_level(self, cr, uid, context=context) != 'manager' and _folder_access(self, cr, uid, folder) != 3:
            raise ERPError('Permission Denied', 'no create access to folder')
        vals = AttrDict(values)
        if vals.perm_type == 'inherit':
            vals.pop('readonly_ids', None)
            vals.readwrite_ids = [uid]
        elif vals.perm_type != 'custom':
            # unknown type
            raise ERPError('Invalid Permissions Type', 'Permission type should be "inherit" or "custom", not %r' % vals.perm_type)
        if not vals.get('shared_as'):
            vals.shared_as = vals.file_name
        shared_as = Path(vals.shared_as)
        if vals.file_name:
            vals.ip_addr = context['__client_address__']
            source_file = Path(vals.file_name)
            if shared_as.ext != '.' and shared_as.ext != source_file.ext:
                vals.shared_as = shared_as + source_file.ext
            self._get_remote_file(cr, uid, vals, file_path=vals.pop('file_path'), context=context)
        elif vals.file_type == 'normal':
            if not shared_as.ext:
                raise ERPError('Error', 'Shared name should have an extension indicating file type.')
        new_id = super(fnx_fs_file, self).create(cr, SUPERUSER, dict(vals), context=context)
        write_permissions(self, cr)
        current = self.browse(cr, SUPERUSER, new_id, context=context)
        if vals.file_type == 'normal' and not vals.file_name:
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
            full_name = fs_root / rec.folder_id.path / rec.shared_as
            to_be_deleted.append(full_name)
            _logger.info('file to be deleted: %s', full_name)
        res = super(fnx_fs_file, self).unlink(cr, uid, ids, context=context)
        write_permissions(self, cr)
        if res and not context.get('keep_files', False):
            for fn in to_be_deleted:
                _logger.info('deleting file: %s', fn)
                if fn.exists():
                    fn.unlink()
                else:
                    _logger.info('file already deleted?')
        return res

    def write(self, cr, uid, ids, values, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        fnx_fs_folder = self.pool.get('fnx.fs.folder')
        records = self.browse(cr, uid, ids, context=context)
        for rec in records:
            source_file = Path(values.get('file_name', rec.file_name or ''))
            sfe = source_file and source_file.ext
            shared_as = Path(values.get('shared_as', rec.shared_as))
            folder_id = values.get('folder_id', rec.folder_id.id)
            folder = fnx_fs_folder.browse(cr, uid, folder_id, context=context)
            if folder.folder_type != 'virtual':
                raise ERPError('Invalid Folder', 'Files can only be saved into Virtual folders')
            old_path = fs_root/rec.folder_id.path/rec.shared_as
            if source_file and shared_as.ext not in ('.', sfe):
                shared_as += source_file.ext
                values['shared_as'] = shared_as
            if 'shared_as' in values or 'folder_id' in values:
                if 'folder_id' in values:
                    folder_rec = fnx_fs_folder.browse(cr, uid, folder_id, context=context)
                    folder = folder_rec.path
                else:
                    folder = rec.folder_id.path
                name = shared_as
                new_path = fs_root/folder/name
                old = old_path.exists()
                new = new_path.exists()
                if old and new:
                    raise ERPError('Error', '%r already exists.' % new_path)
                elif old and not new:
                    old_path.move(new_path)
                else:
                    raise ERPError('Error', 'Neither %r nor %r exist!' % (old_path, new_path))
            if 'user_id' in values:
                owner_id = values['user_id']
            else:
                owner_id = rec.user_id.id
            if 'file_name' in values:
                self._get_remote_file(cr, uid, values, owner_id=owner_id, folder_id=folder_id, shared_as=shared_as, context=context)
        success = super(fnx_fs_file, self).write(cr, uid, ids, values, context=context)
        write_permissions(self, cr)
        return success


class res_users(osv.Model):
    _inherit = 'res.users'

    def unlink(self, cr, uid, ids, context=None):
        result = super(res_users, self).unlink(cr, uid, ids, context=context)
        if ids:
            write_permissions(self, cr)
        return result


class fnx_fs(osv.AbstractModel):
    _name = 'fnx_fs.fs'

    _fnxfs_path = ''
    _fnxfs_path_fields = []

    def __init__(self, pool, cr):
        super(fnx_fs, self).__init__(pool, cr)
        if not self._fnxfs_path_fields:
            self._fnxfs_path_fields = [self._rec_name]
        if self.__class__.__name__ != 'fnx_fs':
            missing = [
                    f
                    for f in self._fnxfs_path_fields
                    if f not in self._columns
                    ]
            if missing:
                _logger.error('the fnx_fs path fields %r are not present in %r', missing, self._name)

    def _auto_init(self, cr, context=None):
        super(fnx_fs, self)._auto_init(cr, context)
        if not fs_root.exists(self._fnxfs_path):
            fs_root.makedirs(self._fnxfs_path)

    def _fnxfs_files(self, cr, uid, ids, name, args, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = {}
        if not ids:
            return res
        ir_config_parameter = self.pool.get('ir.config_parameter')
        website = ir_config_parameter.browse(cr, uid, [('key','=','web.base.url')], context=context)[0]
        website = website.value + '/fnxfs/download'
        template = Xaml(file_list).document.pages[0]
        base_path = fs_root / self._fnxfs_path
        folder_names = self.read(cr, uid, ids, fields=['fnxfs_folder'], context=context)
        for record in folder_names:
            id = record['id']
            folder = record['fnxfs_folder']
            res[id] = False
            folder = folder.replace('/', '%2f')
            if not base_path.exists(folder):
                # create missing folder
                _logger.warning('%r missing, creating', (base_path/folder))
                base_path.mkdir(folder)
            files = sorted((base_path/folder).listdir())
            if files:
                res[id] = template.string(root=website, path=self._fnxfs_path, folder=folder, files=files)
        return res

    def _set_fnxfs_folder(self, cr, uid, ids, context=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        base_path = fs_root / self._fnxfs_path
        records = self.read(cr, uid, ids, fields=['fnxfs_folder']+self._fnxfs_path_fields, context=context)
        folder_names = self.fnxfs_folder_name(records)
        for rec in records:
            actual = rec['fnxfs_folder']
            should_be = folder_names[rec['id']]
            if not actual:
                # initial record creation
                self.write(cr, uid, rec['id'], {'fnxfs_folder': should_be}, context=context)
                should_be = should_be.replace('/','%2f')
                if base_path.exists(should_be):
                    _logger.warning('%r already exists', should_be)
                else:
                    try:
                        base_path.mkdir(should_be)
                    except Exception:
                        _logger.exception('failure creating %s/%s' % (base_path, should_be))
            elif actual != should_be:
                # modifying existing record and changing folder-name elements
                self.write(cr, uid, rec['id'], {'fnxfs_folder': should_be}, context=context)
                actual = actual.replace('/','%2f')
                should_be = should_be.replace('/','%2f')
                if base_path.exists(should_be):
                    raise ERPError('Error', 'New path "%s" already exists' % should_be)
                try:
                    base_path.rename(actual, should_be)
                except Exception:
                    _logger.exception('failure renaming "%s" to "%s"', actual, should_be)
                    raise

    _columns = {
        'fnxfs_folder': fields.char('Folder Name', size=128),
        'fnxfs_files': fields.function(
            _fnxfs_files,
            string='Available Files',
            type='html',
            ),
        }

    def create(self, cr, uid, values, context=None):
        id = super(fnx_fs, self).create(cr, uid, values, context=context)
        if id:
            missing = [f for f in self._fnxfs_path_fields if f not in values]
            if missing:
                raise ERPError('Missing Data', 'Fields %r are required' % (missing, ))
            self._set_fnxfs_folder(cr, uid, [id], context=context)
        return id

    def write(self, cr, uid, ids, values, context=None):
        success = super(fnx_fs, self).write(cr, uid, ids, values, context=context)
        if success:
            presence = [f for f in self._fnxfs_path_fields if f in values]
            if presence:
                self._set_fnxfs_folder(cr, uid, ids, context=context)
        return success

    def unlink(self, cr, uid, ids, context=None):
        in_danger = [
                r['fnxfs_folder']
                for r in self.read(cr, uid, ids, fields=['fnxfs_folder'], context=context)
                ]
        if super(fnx_fs, self).unlink(cr, uid, ids, context=context):
            # figure out which folders should still exist
            should_exist = set([
                    r['fnxfs_folder']
                    for r in self.read(cr, uid, ids, fields=['fnxfs_folder'], context=context)
                    ])
            should_not_exist = [
                    f
                    for f in in_danger
                    if f not in should_exist
                    ]
            base_path = fs_root / self._fnxfs_path
            for dead in should_not_exist:
                dead = dead.replace('/','%2f')
                try:
                    base_path.rmtree(dead)
                except Exception:
                    _logger.exception('failure deleting %s/%s' % (base_path, dead))
        return True

    def fnxfs_folder_name(self, records):
        res = {}
        rec_name = self._rec_name
        for record in records:
            res[record['id']] = record[rec_name]
        return res

    def fnxfs_menu_upload(self, cr, uid, ids, context=None):
        if all([k in context for k in ('active_model', 'active_ids', 'active_id')]):
            if len(ids) != 1:
                raise ERPError('Invalid Selection', 'Can only upload files to one document at a time')
            id = context.get('active_id')
            record = self.browse(cr, uid, id, context=context)
            ir_config_parameter = self.pool.get('ir.config_parameter')
            website = ir_config_parameter.browse(cr, uid, [('key','=','web.base.url')], context=context)[0]
            website = website.value + '/fnxfs/select_files'
            path = self._fnxfs_path
            folder = record.fnxfs_folder.replace('/','%2f')
            url = '%s?path=%s&folder=%s' % (website, path, folder)
            return {
                    'type': 'ir.actions.act_url',
                    'url' : url,
                    'target': 'current',
                    }
        raise ERPError('Missing Data', "At least one of active_model, active_id, or active_ids was not set")

file_list = '''\
~div
    -folder = xmlify(args.folder).replace('/','%2f')
    ~ul
        -for file_name in args.files:
            -file_name = xmlify(file_name).replace('/','%2f')
            -path = '%s?path=%s&folder=%s&file=%s' % (args.root, args.path, folder, file_name)
            ~li
                ~a href=path target='_blank': =file_name
'''
