import hashlib
import logging
import os

from openerp import VAR_DIR
from openerp.exceptions import ERPError
from openerp.osv import osv

from antipathy import Path
from common import delete_file, read_file, write_file

_logger = logging.getLogger(__name__)

class ir_attachment(osv.osv):
    _name = 'ir.attachment'
    _inherit = 'ir.attachment'

    #
    # 'data' field implementation
    #

    def _full_path(self, cr, uid, attachment, location, filename):
        # location = 'file://filestore'
        if not location.startswith('file://'):
            raise ERPError("Unhandled filestore location %r" % location)
        filename = filename.replace('/', '%2f')
        path_file = os.path.join(location[7:], cr.dbname, attachment.res_model, filename)
        if path_file[0] not in "/\\":
            path_file = os.path.join(VAR_DIR, path_file)
        return Path(path_file)

    def _file_read(self, cr, uid, attachment, location, fname, bin_size=False):
        full_path = self._full_path(cr, uid, attachment, location, fname)
        return read_file(full_path, bin_size) 

    def _file_write(self, cr, uid, attachment, location, value):
        datas_value = value.decode('base64')
        file_hash = hashlib.sha512(datas_value).hexdigest()
        fname = '_'.join(attachment.datas_fname.split())
        full_path = self._full_path(cr, uid, attachment, location, fname)
        try:
            dirname = os.path.dirname(full_path)
            if not os.path.isdir(dirname):
                os.makedirs(dirname)
            write_file(full_path, datas_value, binary=True)
        except IOError as e:
            _logger.error("_file_write: %s", e)
            raise
        return file_hash, fname

    def _file_delete(self, cr, uid, attachment, location, fname):
        count = self.search(cr, 1, [('store_fname','=',fname)], count=True)
        if count <= 1:
            full_path = self._full_path(cr, uid, attachment, location, fname)
            try:
                delete_file(full_path)
            except OSError as e:
                _logger.error("_file_delete: %s", e)
            except IOError as e:
                # Harmless and needed for race conditions
                _logger.warning("_file_delete: %s", e)

