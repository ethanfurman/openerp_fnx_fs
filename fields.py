from antipathy import Path
import logging
import re
from osv import fields
from requests.utils import quote
from xaml import Xaml

_logger = logging.getLogger(__name__)

empty = re.compile('^<div>\s*<a href=')

class files(fields.function):
    "shows files at a certain location"

    def __init__(self, path, **kwds):
        for setting in (
                'fnct_inv', 'fnct_inv_arg', 'type', 'fnct_search', 'obj',
                'store', 'multi', 'readonly', 'manual', 'required', 'domain',
                'states', 'change_default', 'size', 'translate',
            ):
            if setting in kwds:
                raise KeyError(
                        '%s: setting %r is not allowed'
                        % (kwds.get('string', '<unknown>'), setting)
                        )
        super(files, self).__init__(False, readonly=True, type='html', fnct_search=self._search_files, **kwds)
        self.path = path

    def _search_files(self, model, cr, uid, obj=None, name=None, domain=None, context=None):
        records = model.read(cr, uid, [(1,'=',1)], fields=['id', name], context=context)
        field, op, criterion = domain[0]
        ids = []
        for rec in records:
            data = rec[field]
            if criterion is False:
                # is set / is not set
                if empty.match(data):
                    data = False
            else:
                # = and != don't make sense, convert to contains
                if op == '=':
                    op = 'ilike'
                else:
                    op = 'not ilike'
            if op == '=' and data == criterion:
                ids.append(rec['id'])
            elif op == '!=' and data != criterion:
                ids.append(rec['id'])
            elif op == 'ilike' and criterion.lower() in data.lower():
                ids.append(rec['id'])
            elif op == 'not ilike' and criterion.lower() not in data.lower():
                ids.append(rec['id'])
        return [('id','in',ids)]

    def get(self, cr, model, ids, name, uid=False, context=None, values=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = {}
        if not ids:
            return res
        #
        # get on-disk file path
        ir_config_parameter = model.pool.get('ir.config_parameter')
        website = ir_config_parameter.browse(
                cr, uid,
                [('key','=','web.base.url')],
                context=context,
                )[0]
        website_download = website.value + '/fnxfs/download'
        template = Xaml(file_list).document.pages[0]
        leaf_path = Path(model._fnxfs_path)/self.path
        base_path = model._fnxfs_root / leaf_path
        folder_names = model.read(
                cr, uid, ids,
                fields=['fnxfs_folder'],
                context=context,
                )
        #
        # get user permissions for the table
        perms = []
        ir_model_access = model.pool.get('ir.model.access')
        if ir_model_access.check( cr, uid, model._name, 'write', False, context):
            perms.append('write')
        if ir_model_access.check( cr, uid, model._name, 'unlink', False, context):
            perms.append('unlink')
        perms = '/'.join(perms)
        #
        # put it all together
        for record in folder_names:
            id = record['id']
            res[id] = False
            folder = record['fnxfs_folder']
            if not folder:
                continue
            disk_folder = folder.replace('/', '%2f')
            web_folder = quote(folder, safe='')
            website_select = (
                    website.value
                    + '/fnxfs/select_files?model=%s&field=%s&rec_id=%s'
                    % (model._name, self._field_name, id)
                    )
            display_files = []
            if base_path.exists(disk_folder):
                display_files = sorted((base_path/disk_folder).listdir())
            safe_files = [quote(f, safe='') for f in display_files]
            res[id] = template.string(
                    download=website_download,
                    path=leaf_path,
                    folder=web_folder,
                    display_files=display_files,
                    web_files=safe_files,
                    select=website_select,
                    permissions=perms,
                    )
        return res

    def set(self, cr, obj, id, name, value, user=None, context=None):
        pass

file_list = '''
~div
    ~ul
        -for wfile, dfile in zip(args.web_files, args.display_files):
            -path = '%s?path=%s&folder=%s&file=%s' % (args.download, args.path, args.folder, wfile)
            ~li
                ~a href=path target='_blank': =dfile
    ~br
    -if args.permissions == 'write/unlink':
        ~a href=args.select target='_blank': Add/Delete files...
    -elif args.permissions == 'write':
        ~a href=args.select target='_blank': Add files...
    -elif args.permissions == 'unlink':
        ~a href=args.select target='_blank': Delete files...
'''
