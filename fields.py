from antipathy import Path
import logging
from osv import fields
from requests.utils import quote
from xaml import Xaml

_logger = logging.getLogger(__name__)


class files(fields.function):
    "shows files at a certain location"

    def __init__(self, path, **kwds):
        for setting in (
                'fnct_inv', 'fnct_inv_arg', 'type', 'fnct_search', 'obj',
                'store', 'multi', 'readonly', 'manual', 'required', 'domain',
                'states', 'change_default', 'size', 'translate',
            ):
            if setting in kwds:
                raise KeyError('%s: setting %r is not allowed' % (kwds.get('string', '<unknown>'), setting))
        super(files, self).__init__(False, readonly=True, type='html', **kwds)
        self.path = path

    def get(self, cr, model, ids, name, uid=False, context=None, values=None):
        if isinstance(ids, (int, long)):
            ids = [ids]
        res = {}
        if not ids:
            return res
        ir_config_parameter = model.pool.get('ir.config_parameter')
        website = ir_config_parameter.browse(cr, uid, [('key','=','web.base.url')], context=context)[0]
        website_download = website.value + '/fnxfs/download'
        template = Xaml(file_list).document.pages[0]
        leaf_path = Path(model._fnxfs_path)/self.path
        base_path = model._fnxfs_root / leaf_path
        folder_names = model.read(cr, uid, ids, fields=['fnxfs_folder'], context=context)
        for record in folder_names:
            id = record['id']
            folder = record['fnxfs_folder']
            disk_folder = folder.replace('/', '%2f')
            web_folder = quote(folder, safe='')
            res[id] = False
            website_select = website.value + '/fnxfs/select_files?path=%s&folder=%s' % (leaf_path, web_folder)
            if not base_path.exists(disk_folder):
                # create missing folder
                _logger.warning('%r missing, creating', (base_path/disk_folder))
                base_path.mkdir(disk_folder)
            display_files = sorted((base_path/disk_folder).listdir())
            safe_files = [quote(f, safe='') for f in display_files]
            # if files:
            res[id] = template.string(
                    download=website_download,
                    path=leaf_path,
                    folder=web_folder,
                    display_files=display_files,
                    web_files=safe_files,
                    select=website_select,
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
    ~a href=args.select target='_blank': Add files...
'''
