from antipathy import Path
import logging
import re
from openerp.exceptions import ERPError
from osv import fields
from pdfrw import PdfReader
from requests.utils import quote
from xaml import Xaml

_logger = logging.getLogger(__name__)

empty_list = re.compile('^<div>\s*<a href=')
empty_image = re.compile('^<div>\s*</div>')

fields.PUBLIC_FIELD_ATTRIBUTES.append('path')

class files(fields.function):
    "shows files at a certain location"

    def __init__(self, path, style='list', sort='alpha', **kwds):
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
        if style == 'list':
            func = self.show_list
        elif style == 'static_list':
            func = self.show_static_list
        elif style == 'images':
            func = self.show_images
        else:
            raise ERPError('Configuration Error', 'valid choices for style are "list" and "images", not %r' % (style, ))
        if sort in ('alpha', 'alpha asc'):
            self.sort = lambda f: f.filename
            self.reverse = False
        elif sort in ('alpha desc', ):
            self.sort = lambda f: f.filename
            self.reverse = True
        elif sort in ('time', 'time desc', 'newest'):
            self.reverse = False
            self.sort = lambda f: f.stat().st_mtime
        elif sort in ('time asc', 'oldest'):
            self.sort = lambda f: -f.stat().st_mtime
            self.reverse = True
        elif sort is None:
            raise ERPError(
                    "sort must be 'alpha' or a function that takes a fully-qualified file name as an argument (not %r)"
                    % (sort, )
                    )
        else:
            self.sort = sort
            self.reverse = False
        super(files, self).__init__(False, readonly=True, type='html', fnct_search=self._search_files, **kwds)
        self.path = path
        self.style = func

    def _search_files(self, model, cr, uid, obj=None, name=None, domain=None, context=None):
        """
        support searching file names
        """
        leaf_path = Path(model._fnxfs_path)/self.path           # model path / field path
        base_path = model._fnxfs_root / leaf_path               # anchored path / model path / field path
        records = model.read(
                cr, uid, [(1,'=',1)],
                fields=['id', 'fnxfs_folder'],
                context=context,
                )
        # records = model.read(cr, uid, [(1,'=',1)], fields=['id', name], context=context)
        field, op, criterion = domain[0]
        ids = []
        for rec in records:
            folder = rec['fnxfs_folder']
            if not folder:
                data = ''
            else:
                disk_folder = folder.replace('/', '%2f')
                files = self.get_and_sort_files(base_path/disk_folder)
                data = ' '.join(["%s=%s" % (f, k) for f, k in files])
            if criterion is False:
                # is set / is not set
                if not data or empty_list.match(data) or empty_image.match(data):
                    data = False
            else:
                # = and != don't make sense, convert to contains
                if op == '=':
                    op = 'ilike'
                elif op == '!=':
                    op = 'not ilike'
            if op == '=' and data == criterion:
                ids.append(rec['id'])
            elif op == '!=' and data != criterion:
                ids.append(rec['id'])
            elif op == 'ilike' and (criterion.lower() in data.lower()):
                ids.append(rec['id'])
            elif op == 'not ilike' and criterion.lower() not in data.lower():
                ids.append(rec['id'])
        return [('id','in',ids)]

    def show_images(self, model, cr, uid, ids, base_url, context=None):
        """
        construct html fragment to show files as images
        """
        res = {}
        #
        # get on-disk file path
        template = Xaml(image_list).document.pages[0]
        leaf_path = Path(model._fnxfs_path)/self.path           # model path / field path
        base_path = model._fnxfs_root / leaf_path               # anchored path / model path / field path
        folder_names = model.read(
                cr, uid, ids,
                fields=['fnxfs_folder'],
                context=context,
                )
        #
        # get user permissions for the table
        perms = None
        ir_model_access = model.pool.get('ir.model.access')
        if ir_model_access.check( cr, uid, model._name, 'unlink', False, context):
            perms = 'unlink'
        #
        # put it all together
        for record in folder_names:
            id = record['id']
            res[id] = False
            folder = record['fnxfs_folder']
            if not folder:
                continue
            disk_folder = folder.replace('/', '%2f')
            try:
                web_folder = quote(folder.encode('utf-8'), safe='')
            except KeyError:
                _logger.exception('bad name: %s( %r )', type(folder), folder)
                raise
            #
            website_delete = (
                    base_url
                    + '/delete?model=%s&field=%s&rec_id=%s'
                    % (model._name, self._field_name, id)
                    )
            #
            display_files = [
                    t[0]
                    for t in self.get_and_sort_files(
                            base_path/disk_folder, keep=lambda f: f.ext.endswith(('.png','.jpg','.img'))
                            )]
            safe_files = [quote(f, safe='') for f in display_files]
            res[id] = template.string(
                    download=base_url + '/image',
                    path=leaf_path,
                    folder=web_folder,
                    web_images=safe_files,
                    delete=website_delete,
                    permissions=perms,
                    )
        return res

    def show_list(self, model, cr, uid, ids, base_url, context=None):
        """
        construct html fragment to show files as file names (allow uploading/deletion)
        """
        res = {}
        #
        template = Xaml(file_list).document.pages[0]
        leaf_path = Path(model._fnxfs_path)/self.path           # model path / field path
        base_path = model._fnxfs_root / leaf_path               # anchored path / model path / field path
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
            try:
                web_folder = quote(folder.encode('utf-8'), safe='')
            except KeyError:
                _logger.exception('bad name: %s( %r )', type(folder), folder)
                raise
            website_select = (
                    base_url
                    + '/select_files?model=%s&field=%s&rec_id=%s'
                    % (model._name, self._field_name, id)
                    )
            display_files = self.get_and_sort_files(base_path/disk_folder)
            safe_files = [quote(f, safe='') for (f, k) in display_files]
            res[id] = template.string(
                    download=base_url + '/download',
                    path=leaf_path,
                    folder=web_folder,
                    display_files=display_files,
                    web_files=safe_files,
                    select=website_select,
                    permissions=perms,
                    )
        return res

    def show_static_list(self, model, cr, uid, ids, base_url, context=None):
        """
        construct html fragment to show files as file names (do not allow uploading/deletion)
        """
        res = {}
        #
        template = Xaml(static_file_list).document.pages[0]
        leaf_path = Path(model._fnxfs_path)/self.path           # model path / field path
        base_path = model._fnxfs_root / leaf_path               # anchored path / model path / field path
        folder_names = model.read(
                cr, uid, ids,
                fields=['fnxfs_folder'],
                context=context,
                )
        #
        for record in folder_names:
            id = record['id']
            res[id] = False
            folder = record['fnxfs_folder']
            if not folder:
                continue
            disk_folder = folder.replace('/', '%2f')
            try:
                web_folder = quote(folder.encode('utf-8'), safe='')
            except KeyError:
                _logger.exception('bad name: %s( %r )', type(folder), folder)
                raise
            website_select = (
                    base_url
                    + '/select_files?model=%s&field=%s&rec_id=%s'
                    % (model._name, self._field_name, id)
                    )
            display_files = self.get_and_sort_files(base_path/disk_folder)
            safe_files = [quote(f, safe='') for (f, k) in display_files]
            res[id] = template.string(
                    download=base_url + '/download',
                    path=leaf_path,
                    folder=web_folder,
                    display_files=display_files,
                    web_files=safe_files,
                    select=website_select,
                    )
        return res

    def get(self, cr, model, ids, name, uid=False, context=None, values=None):
        """
        return appropriate html fragment
        """
        if isinstance(ids, (int, long)):
            ids = [ids]
        if not ids:
            return {}
        base_url = '/fnxfs'
        return self.style(model, cr, uid, ids, base_url=base_url, context=context)

    def get_and_sort_files(self, folder, keep=None):
        if not folder.exists():
            return []
        files = filter(keep, folder.glob('*'))
        files.sort(key=self.sort, reverse=self.reverse)
        sorted_files = []
        for target in files:
            current = target/'current'
            if target.isfile():
                sorted_files.append((target.filename, self._get_keywords(target)))
            elif not target.isdir():
                _logger.error('unable to handle disk entry %r', target)
            elif current.exists():
                sorted_files.append((target.filename, self._get_keywords(current)))
        return sorted_files

    def _get_keywords(self, filename):
        """
        return keywords stored in pdf files (other file types ignored)
        """
        keywords = ''
        if filename.ext.lower() == '.pdf' or filename.dirs.ext.lower() == '.pdf':
            try:
                keywords = PdfReader(filename)['/Info'].get('/Keywords') or ''
                if keywords == '()':
                    keywords = ''
            except Exception:
                _logger.exception('unable to extract keywords from %r', filename)
        return keywords



file_list = '''
~div
    -if args.display_files:
        ~ul
            -for wfile, (dfile, dkeys) in zip(args.web_files, args.display_files):
                -path = '%s?path=%s&folder=%s&file=%s' % (args.download, args.path, args.folder, wfile)
                ~li
                    ~a href=path target='_blank' title=dkeys: =dfile
        ~br
    -if args.permissions == 'write/unlink':
        ~a href=args.select target='_blank': Add/Delete files...
    -elif args.permissions == 'write':
        ~a href=args.select target='_blank': Add files...
    -elif args.permissions == 'unlink':
        ~a href=args.select target='_blank': Delete files...
'''

static_file_list = '''
~div
    -if args.display_files:
        ~ul
            -for wfile, (dfile, dkeys) in zip(args.web_files, args.display_files):
                -path = '%s?path=%s&folder=%s&file=%s' % (args.download, args.path, args.folder, wfile)
                ~li
                    ~a href=path target='_blank' title=dkeys: =dfile
'''

image_list = '''
~div
    -if args.web_images:
        -for wfile in args.web_images:
            -path = '%s?path=%s&folder=%s&file=%s' % (args.download, args.path, args.folder, wfile)
            ~div style='display:inline-block;align:left;'
                ~img src=path width='90%'
            -if args.permissions == 'unlink':
                ~div style='display:inline-block; align:right;'
                    -delete = '%s&file=%s' % (args.delete, wfile)
                    ~a href=delete: delete image
            ~br
            ~hr
'''
