# -*- coding: utf-8 -*-

import openerp
import werkzeug
from openerp.addons.web.http import Controller, httprequest
from openerp.addons.web.controllers.main import content_disposition
from antipathy import Path
from fnx_fs.server import permissions
from mimetypes import guess_type

fnx_root = Path('/var/openerp/fnxfs/')

class FnxFS(Controller):

    _cp_path = Path('/fnxfs')

    def __getattr__(self, name):
        return self.get_file

    # TODO: get_file needs to figure out who is asking, and check that s/he has permission

    @httprequest
    def get_file(self, request):
        target_file = Path(request.httprequest.path[7:])
        if not (fnx_root/target_file).exists():
            return request.not_found('unable to find %s' % (fnx_root/target_file,))
        master_session_id = request.httprequest.cookies['instance0|session_id'].replace('%22','')
        if master_session_id:
            master_session = request.httpsession[master_session_id]
            login = master_session._login
            perms = permissions[target_file]
            access = perms.create_delete_users + perms.write_users + perms.read_users
            if login in access or 'all' in access:
                with (fnx_root/target_file).open('rb') as fh:
                    file_data = fh.read()
                return request.make_response(
                        file_data,
                        headers=[
                            ('Content-Disposition',  content_disposition(target_file.filename, request)),
                            ('Content-Type', guess_type(target_file.filename)[0] or 'octet-stream'),
                            ('Content-Length', len(file_data)),
                            ],
                        )
        return werkzeug.exceptions.Forbidden(
                '<p>You do not have permission to access %s.</p>'
                '<p>Please see a supervisor to grant permission, or IT '
                'if you do but are still getting this error.</p>'
                % target_file)
