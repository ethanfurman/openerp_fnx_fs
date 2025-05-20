from antipathy import Path
from datetime import datetime
from fields import files
from openerp import CONFIG_DIR, VAR_DIR, SUPERUSER_ID as SUPERUSER
from openerp.exceptions import ERPError
from osv import osv, fields
from scription import OrmFile
from textwrap import dedent
from xaml import Xaml
import logging
import os
import pwd

_logger = logging.getLogger(__name__)

openerp_ids = tuple(pwd.getpwnam('openerp')[2:4])

CONFIG_ERROR = "Configuration not set; check Settings --> Configuration --> FnxFS --> %s."

SCAN_TICKET_PATH = "/home/openerp/sandbox/var/scans"

fs_root = Path(u'%s/openerp/fnxfs/' % VAR_DIR)

config = OrmFile('%s/fnx.ini' % CONFIG_DIR, section='fnxfsd')

## tables

class fnx_fs(osv.AbstractModel):
    _name = 'fnx_fs.fs'

    # to use this in other tables:
    #
    # _inherit = [fnx_fs.fs]
    # _fnxfs_path = '...'
    # _fnxfs_path_fields = []
    #
    # if _fnxfs_path_fields includes any thing besides 'name':
    # def fnxfs_folder_name(self, records): ...

    _fnxfs_path = ''
    _fnxfs_path_fields = []
    _fnxfs_root = fs_root
    _fnxfs_tables = set()

    # to support auto scan attachments
    # _columns = {
    #       'fnxfs_scans': files('<path>', '<Display Name>'),
    #       }

    def __init__(self, pool, cr):
        super(fnx_fs, self).__init__(pool, cr)
        if not self._fnxfs_path_fields:
            self._fnxfs_path_fields = [self._rec_name]
        if self.__class__.__name__ != 'fnx_fs':
            # record table
            self.__class__._fnxfs_tables.add(self._name)
            # check if path is set
            if not self._fnxfs_path:
                _logger.error('No path is set for %r' % self._name)
            # check if fields defined directly in (super)class
            missing = [
                    f
                    for f in self._fnxfs_path_fields
                    if f not in self._columns
                    ]
            # check if fields defined in _inherits (combined) class
            for table_name in self._inherits:
                partial_table = self.pool.get(table_name)
                missing = [
                        f
                        for f in missing
                        if f not in partial_table._columns
                        ]
            if missing:
                _logger.error('the fnx_fs path fields %r are not present in %r', missing, self._name)
        field_paths = set()
        for name, column in self._columns.items():
            if isinstance(column, files):
                if not column.path:
                    field_paths.add(name)
        if len(field_paths) > 1:
            _logger.error('%s : too many files fields have no path: %s', self._name, ', '.join(sorted(field_paths)))

    def _auto_init(self, cr, context=None):
        res = super(fnx_fs, self)._auto_init(cr, context)
        if not self._fnxfs_root.exists(self._fnxfs_path):
            self._fnxfs_root.makedirs(self._fnxfs_path)
        if self.__class__.__name__ != 'fnx_fs':
            found = False
            for name, column_info in self._all_columns.items():
                column = column_info.column
                if isinstance(column, files):
                    found = True
                    path = self._fnxfs_root/self._fnxfs_path/column.path
                    if not path.exists():
                        path.mkdir()
            if not found:
                _logger.error('table %r inherits from model <fnx_fs.fs> but has no <files> fields' % self._name)
        return res

    def _set_fnxfs_folder(self, cr, uid, ids, context=None):
        "calculate and save leaf folder name; possibly rename existing folder"
        if isinstance(ids, (int, long)):
            ids = [ids]
        context = context or {}
        field_names = []
        columns = []
        for name, column in self._columns.items():
            if isinstance(column, files):
                field_names.append(name)
                columns.append(column)
        records = self.read(cr, uid, ids, fields=['fnxfs_folder']+self._fnxfs_path_fields, context=context)
        folder_names = self.fnxfs_folder_name(records)
        for rec in records:
            actual = rec['fnxfs_folder']
            should_be = folder_names[rec['id']]
            if not should_be:
                raise ERPError(
                        'Missing Data',
                        'Unable to create folder name from:\n\n' +
                            '\n'.join(['%s: %r' % (f, rec[f]) for f in self._fnxfs_path_fields])
                            )
            if not actual or actual != should_be:
                super(fnx_fs, self).write(cr, uid, rec['id'], {'fnxfs_folder': should_be}, context=context)
            for field_name, field_column in zip(field_names, columns):
                base_path = self._fnxfs_root / self._fnxfs_path / field_column.path
                if actual and actual != should_be:
                    # modifying existing record and changing folder-name elements
                    src = base_path/(actual.replace('/','%2f'))
                    dst = base_path/(should_be.replace('/','%2f'))
                    if dst.exists() and not context.get('fis_maintenance'):
                        raise ERPError('Error', 'New path "%s" already exists' % dst)
                    if src.exists():
                        try:
                            Path.rename(src, dst)
                        except Exception:
                            _logger.exception('failure renaming "%s" to "%s"', src, dst)
                            raise ERPError('Failure', 'Unable to rename %r to %r' % (src, dst))
        return True

    def _get_storage(self, cr, uid, ids, field_name, args, context=None):
        fields = {}
        for column_name, column in sorted(self._columns.items()):
            if isinstance(column, files):
                fields[column_name] = {
                        'display': column.string,
                        'path': (self._fnxfs_root)/self._fnxfs_path/column.path,
                        }
        table_xaml = dedent("""\
                ~html
                    ~table style='padding=15px;'
                        ~tr
                            ~th style='text-align: left; min-width: 150px;': Field
                            ~th style='text-align: left; min-width: 150px;': Path
                        -for name, path in sorted(args.values.items()):
                            ~tr
                                ~td style='text-align: left; min-width: 150px;': =name
                                ~td style='text-align: left; min-width: 150px;': =path
                """)
        res = {}
        for rec in self.read(cr, uid, ids, fields=['fnxfs_folder'], context=context):
            values = {}
            for name, column in fields.items():
                display = column['display']
                path = column['path']
                values[display] = '%s/%s' % (path, rec['fnxfs_folder'])
            doc = Xaml(table_xaml).document.pages[0]
            html = doc.string(values=values)
            res[rec['id']] = html
        return res

    _columns = {
        'fnxfs_folder': fields.char('Folder Name', size=128, help='name of leaf folder'),
        'fnxfs_queue_scan': fields.boolean('Update with scans'),
        'fnxfs_storage': fields.function(
            _get_storage,
            type='html',
            string='Storage location',
            help='current directories used for external files'),
        }

    def create(self, cr, uid, values, context=None):
        queue_scans = False
        if 'queue_scan' in values:
            queue_scans = values.pop('queue_scan')
        id = super(fnx_fs, self).create(cr, uid, values, context=context)
        if id:
            self._set_fnxfs_folder(cr, uid, [id], context=context)
        if queue_scans:
            self.write_scan_ticket(cr, uid, id, context)
        return id
    

    def write(self, cr, uid, ids, values, context=None):
        queue_scans = False
        if 'queue_scan' in values:
            queue_scans = values.pop('queue_scan')
            if queue_scans and isinstance(ids, (list, tuple)) and len(ids) > 1:
                raise ERPError(
                        'Invalid Option',
                        'cannot select "Update with scans" when editing multiple records',
                        )
        success = super(fnx_fs, self).write(cr, uid, ids, values, context=context)
        if success:
            presence = [f for f in self._fnxfs_path_fields if f in values]
            if presence:
                self._set_fnxfs_folder(cr, uid, ids, context=context)
        if queue_scans:
            self.write_scan_ticket(cr, uid, ids, context)
        return success

    def write_scan_ticket(self, cr, uid, ids, context):
        context = (context or {}).copy()
        if isinstance(ids, (int, long)):
            ids = [ids]
        if len(ids) > 1:
            raise ERPError(
                    'Invalid Option',
                    'cannot select "Update with scans" when editing multiple records',
                    )
        user = self.pool.get('res.users').browse(cr, uid, uid)
        for id in ids:
            # only one id, this only loops once
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S%f')
            perms, [root, trunk, branch, leaf] = self.fnxfs_field_info(cr, uid, id, 'fnxfs_scans')
            record = self.browse(cr, uid, id)
            name = self.fnxfs_folder_name([record]).pop(id)
            comp_name = name.replace(' ', '')
            context['login'] = user.login
            context['destination_file'] = '%s_%s.pdf' % (comp_name, timestamp)
            context['destination_folder'] = os.path.join(root, trunk, branch, leaf)
            context['fnxfs_scan_reference'] = name
            filename = '%s_%s' % (timestamp, comp_name)
            with open(os.path.join(SCAN_TICKET_PATH, filename), 'w') as fh:
                fh.write('{\n')
                for key, value in context.items():
                    fh.write('"%s": "%s",\n' % (key, value))
                fh.write('}\n')

    def unlink(self, cr, uid, ids, context=None):
        "remove any on-disk files for deleted records"
        in_danger = [
                r['fnxfs_folder']
                for r in self.read(cr, uid, ids, fields=['fnxfs_folder'], context=context)
                ]
        if super(fnx_fs, self).unlink(cr, uid, ids, context=context):
            # figure out which folders should still exist (multiple records may have been using the same folder)
            should_exist = set([
                    r['fnxfs_folder']
                    for r in self.read(cr, uid, [('fnxfs_folder','in',in_danger)], fields=['fnxfs_folder'], context=context)
                    ])
            should_not_exist = [
                    f
                    for f in in_danger
                    if f not in should_exist
                    ]
            base_path = self._fnxfs_root / self._fnxfs_path
            subdirs = []
            for fn, fd in self._columns.items():
                if isinstance(fd, files):
                    subdirs.append(base_path/fd.path)
            for dead in should_not_exist:
                dead = dead.replace('/','%2f')
                for sd in subdirs:
                    if sd.exists(dead):
                        try:
                            sd.rmtree(dead)
                        except Exception:
                            _logger.exception('failure deleting %s/%s' % (base_path, dead))
        return True

    def fnxfs_folder_name(self, records):
        "default leaf folder name is the record's name"
        res = {}
        rec_name = self._rec_name
        for record in records:
            res[record['id']] = record[rec_name].replace(' ','_')
        return res

    def fnxfs_get_paths(self, cr, uid, ids, fields, context=None):
        if not fields:
            raise ERPError('Programmer Error', 'no fields specified')
        base_paths = {}
        for f in fields:
            if f not in self._all_columns:
                raise ERPError('Programmer Error', '%r not in table %s' % (f, self._name))
            column = self._all_columns[f].column
            if not isinstance(column, files):
                raise ERPError('Programmer Error', 'column %r is not an fnxfs files field')
            base_paths[f] = Path(self._fnxfs_root)/self._fnxfs_path/column.path
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = []
        for id, name in self.fnxfs_folder_name(
                self.read(
                    cr, uid, ids, fields=self._fnxfs_path_fields, context=context
            )).items():
            paths = {'id': id}
            res.append(paths)
            for f in fields:
                column = self._all_columns[f].column
                paths[f] = base_paths[f] / name.replace('/','%2f')
        return res


    def fnxfs_field_info(self, cr, uid, ids, field_name, context=None):
        "return (permissions, [(root, trunk, branch, leaf), ...]) for each record id"
        res = []
        multi = True
        if isinstance(ids, basestring):
            ids = int(ids)
        if isinstance(ids, (int, long)):
            multi = False
            ids = [ids]
        root = self._fnxfs_root
        trunk = self._fnxfs_path
        branch = self._columns[field_name].path
        perms = []
        ir_model_access = self.pool.get('ir.model.access')
        if ir_model_access.check(cr, uid, self._name, 'write', False, context):
            perms.append('write')
        if ir_model_access.check(cr, uid, self._name, 'unlink', False, context):
            perms.append('unlink')
        perms = '/'.join(perms)
        for record in self.read(cr, SUPERUSER, ids, fields=['id', 'fnxfs_folder'], context=context):
            leaf = record['fnxfs_folder']
            res.append((record['id'], root, trunk, branch, leaf))
        if multi:
            return perms, res
        else:
            return perms, res[0][1:]

    def fnxfs_table_info(self, cr, uid, context=None):
        """
           return {
                   'db_name': {
                        'display': field_string,
                        'path': root/trunk/branch/stem/leaf,
                        'name': field.name,
                        '_rec_name': db_name._rec_name,
                            },
                       'db_name': {...},
                   },
        """
        res = {}
        if self._name == 'fnx_fs.fs':
            tables = self._fnxfs_tables
        else:
            tables = [self]
        for table_name in sorted(tables):
            info = res[table_name] = {}
            table = self.pool.get(table_name)
            info['_rec_name'] = table._rec_name
            for column_name, column in sorted(table._columns.items()):
                if isinstance(column, files):
                    info[column_name] = {
                            'name': column_name,
                            'display': column.string,
                            'path':(table._fnxfs_root)/table._fnxfs_path/column.path,
                            }
        return res


try:
    if not os.path.exists(SCAN_TICKET_PATH):
        _logger.error('SCAN_TICKET_PATH %r does not exist', SCAN_TICKET_PATH)
        _logger.info('creating SCAN_TICKET_PATH %r', SCAN_TICKET_PATH)
        os.makedirs(SCAN_TICKET_PATH)
except Exception:
    _logger.exception('unable to create %r', SCAN_TICKET_PATH)

