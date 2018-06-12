# -*- coding: utf-8 -*-

import logging
import werkzeug
from openerp.addons.web.http import Controller, httprequest
from openerp.addons.web.controllers.main import content_disposition
from antipathy import Path
from fnx_fs.server import permissions
from mimetypes import guess_type

_logger = logging.getLogger(__name__)
fnx_root = Path('/var/openerp/fnxfs/')

class FnxFS(Controller):

    _cp_path = Path('/fnxfs')

    def __getattr__(self, name):
        return self.get_file

    # TODO: get_file needs to figure out who is asking, and check that s/he has permission

    @httprequest
    def get_file(self, request):
        target_file = Path(request.httprequest.path[7:])
        target_path_file = fnx_root/target_file
        if not target_path_file.exists() or target_path_file.isdir():
            return request.not_found('%s is not available at this time.' % (target_file,))
        master_session_id = request.httprequest.cookies['instance0|session_id'].replace('%22','')
        if master_session_id:
            try:
                master_session = request.httpsession[master_session_id]
                login = master_session._login
                perms = permissions[target_file]
                access = perms.write_users + perms.read_users
                if login in access or 'all' in access:
                    with (target_path_file).open('rb') as fh:
                        file_data = fh.read()
                    return request.make_response(
                            file_data,
                            headers=[
                                ('Content-Disposition',  content_disposition(target_file.filename, request)),
                                ('Content-Type', guess_type(target_file.filename)[0] or 'octet-stream'),
                                ('Content-Length', len(file_data)),
                                ],
                            )
            except Exception:
                _logger.exception('error accessing %r', target_file)
                return werkzeug.exceptions.InternalServerError('An error occured attempting to access %r; please let IT know.' % (str(target_file),))
        return werkzeug.exceptions.Forbidden(
                'You do not have permission to access %s.\n\n'
                'Please see a supervisor to grant permission, or IT '
                'if you do but are still getting this error.'
                % target_file)

    @httprequest
    def download(self, request, path, folder, file):
        target_path_file = fnx_root
        target_path_file /= path
        target_path_file /= folder.replace('/', '%2f')
        target_path_file /= file.replace('/', '%2f')
        try:
            with (target_path_file).open('rb') as fh:
                file_data = fh.read()
            res = request.make_response(
                    file_data,
                    headers=[
                        ('Content-Disposition',  content_disposition(target_path_file.filename, request)),
                        ('Content-Type', guess_type(file)[0] or 'octet-stream'),
                        ('Content-Length', len(file_data)),
                        ],
                    )
            return res
        except Exception:
            _logger.exception('error accessing %r', file)
            return werkzeug.exceptions.InternalServerError(
                    'An error occured attempting to access %r; please let IT know.' % (str(file),)
                    )
