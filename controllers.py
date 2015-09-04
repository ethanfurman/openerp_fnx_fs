# -*- coding: utf-8 -*-

import openerp
from openerp.addons.web.http import Controller, httprequest
from openerp.addons.web.controllers.main import content_disposition
from antipathy import Path
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
            raise Exception('unable to find <%s>' % (fnx_root/target_file,))
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
