import logging
import subprocess
import oe_xid as xid
from dbf import DateTime
from datetime import datetime
from ipaddress import IPv4Network, IPv4Address
import os
from osv import osv, fields
from openerp import tools, SUPERUSER_ID as SUPERUSER
import re
from base64 import b64decode
from pwd import getpwuid
from VSS.path import Path, listdir

_logger = logging.getLogger(__name__)

CONFIG_ERROR = "Configuration not set; check Settings --> Configuration --> File System --> %s."


class fnx_fs(osv.Model):
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
        prefix = xid.check_company_settings(self, cr, uid, ('prefix', 'File System', CONFIG_ERROR))['prefix']
        regex = xid.check_company_settings(self, cr, uid, ('pattern', 'File System', CONFIG_ERROR))['pattern']
        # get known pcs
        current_files = []
        results = []
        for rec in self.browse(cr, uid, self.search(cr, uid, [(1,'=',1)])):
            filename = Path(rec.filepath) / rec.filename
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
            values['filepath'] = branch.path
            values['filename'] = branch.filename
            self.create(cr, SUPERUSER, values)
        return

    _name = 'fnx_fs.files'
    _description = 'tracked files'
    #_inherits = {'file_system.permissions':'perm_id'}
    _columns = {
        'user_id': fields.many2one('res.users', 'User', required=True),
        'filepath': fields.char('File Path', size=64, required=True),
        'filename': fields.char('File Name', size=64),
        #'perm_id': fields.many2one('file_system.files', 'Permissions', required=True, ondelete='cascade'),
        'indexed_text': fields.text('Indexed content (TBI)'),
        'notes': fields.text('Notes'),
        }
    _sql_constraints = [('file_uniq', 'unique(filepath,filename)', 'File already exists in system.')]
fnx_fs()
