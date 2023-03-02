# -*- coding: utf-8 -*-

import logging
import os
import werkzeug
from openerp import ROOT_DIR
from openerp.addons.web.http import Controller, httprequest
from openerp.addons.web.controllers.main import content_disposition
from antipathy import Path
from datetime import datetime, timedelta
from mimetypes import guess_type
from operator import div
from tempfile import mkstemp
from xaml import Xaml

_logger = logging.getLogger(__name__)
fnx_root = Path('%s/var/openerp/fnxfs/' % ROOT_DIR)
base = Path(__file__).dirname
template = base/'/static/lib/file_upload.xaml'


class FnxFS(Controller):

    _cp_path = Path('/fnxfs')

    def _get_template(self):
        current_timestamp = template.stat()[-3:]
        if not self._template_timestamp or self._template_timestamp != current_timestamp:
            with open(template) as t:
                upload_template = t.read()
            self._template = Xaml(upload_template).document.pages[0]
        return self._template

    def __init__(self, *args, **kwds):
        super(FnxFS, self).__init__(*args, **kwds)
        self._template_timestamp = None

    @httprequest
    def static(self, request, *args, **kwds):
        target_file = Path(request.httprequest.path[7:])
        target_path_file = base/target_file
        if not target_path_file.exists() or target_path_file.isdir():
            return request.not_found('%s is not available at this time.' % (target_file,))
        try:
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
            return werkzeug.exceptions.InternalServerError(
                    'An error occured attempting to access %r; please let IT know.'
                    % (str(target_file),))

    @httprequest
    def download(self, request, path, folder, file):
        target_path_file = fnx_root
        target_path_file /= path
        target_path_file /= folder.replace('/', '%2f')
        target_path_file /= file.replace('/', '%2f')
        filename = target_path_file.filename
        if target_path_file.isdir():
            target_path_file /= 'current'
        try:
            with (target_path_file).open('rb') as fh:
                file_data = fh.read()
            return request.make_response(
                    file_data,
                    headers=[
                        ('Content-Disposition',  content_disposition(filename, request)),
                        ('Content-Type', guess_type(file)[0] or 'octet-stream'),
                        ('Content-Length', len(file_data)),
                        ],
                    )
        except Exception:
            _logger.exception('error accessing %r as %r', file, target_path_file)
            return werkzeug.exceptions.InternalServerError(
                    'An error occured attempting to access %r; please let IT know.' % (str(file),)
                    )

    @httprequest
    def delete(self, request, model, field, rec_id, file):
        try:
            master_session_id = request.httprequest.cookies['instance0|session_id'].replace('%22','')
            master_session = request.httpsession[master_session_id]
        except Exception:
            _logger.exception('unauthorized attempt to delete %r', file)
            return werkzeug.exceptions.Forbidden()
        oe_model = master_session.model(model)
        perms, (root, trunk, branch, leaf) = oe_model.fnxfs_field_info(rec_id, field)
        if 'unlink' not in perms:
            _logger.exception('unauthorized attempt to delete %r', file)
            return werkzeug.exceptions.Forbidden()
        target_path_file = reduce(div, [p for p in [root, trunk, branch] if p])
        target_path_file /= leaf.replace('/', '%2f')
        target_path_file /= file.replace('/', '%2f')
        try:
            _logger.info("user: %r; action: delete; file: '%s'", master_session._login, target_path_file)
            if not self.use_archive(target_path_file):
                # file doesn't exist
                return request.not_found()
            else:
                target_path_file /= 'current'
                target_path_file.unlink()
                return request.make_response(
                        '<i>file deleted</i>',
                        headers=[
                            ('Content-Type', 'text/html'),
                            ('Content-Length', 19),
                            ],
                        )
        except Exception:
            _logger.exception('error deleting %r as %r', file, target_path_file)
            return werkzeug.exceptions.InternalServerError()

    @httprequest
    def image(self, request, path, folder, file, **kw):
        target_path_file = fnx_root
        target_path_file /= path
        target_path_file /= folder.replace('/', '%2f')
        target_path_file /= file.replace('/', '%2f')
        filename = target_path_file.filename
        if target_path_file.isdir():
            target_path_file /= 'current'
        try:
            with (target_path_file).open('rb') as fh:
                file_data = fh.read()
            return request.make_response(
                    file_data,
                    headers=[
                        ('Content-Disposition',  content_disposition(filename, request)),
                        ('Content-Type', guess_type(file)[0] or 'octet-stream'),
                        ('Content-Length', len(file_data)),
                        ],
                    )
        except Exception:
            _logger.exception('error accessing %r as %r', file, target_path_file)
            return werkzeug.exceptions.InternalServerError(
                    'An error occured attempting to access %r; please let IT know.' % (str(file),)
                    )

    @httprequest
    def select_files(self, request, model, field, rec_id):
        try:
            master_session_id = request.httprequest.cookies['instance0|session_id'].replace('%22','')
            master_session = request.httpsession[master_session_id]
        except Exception:
            _logger.error('cookies: %r', request.httprequest.cookies)
            _logger.exception('unauthorized attempt to access %r', file)
            return werkzeug.exceptions.Forbidden()
        oe_model = master_session.model(model)
        perms, (root, trunk, branch, leaf) = oe_model.fnxfs_field_info(rec_id, field)
        target_path = reduce(div, [p for p in [root, trunk, branch] if p])
        target_path /= leaf.replace('/', '%2f')
        files = []
        if target_path.exists():
            files = target_path.listdir()
        template = self._get_template()
        page = template.string(
                model=model,
                field=field,
                files=files,
                folder=leaf,
                rec_id=rec_id,
                create='write' in perms,
                unlink='unlink' in perms,
                )
        try:
            return request.make_response(
                    page,
                    headers=[
                        ('Content-Type', 'text/html; charset=UTF-8'),
                        ('Content-Length', len(page)),
                        ],
                    )
        except Exception:
            _logger.exception('error processing %r', self.path)
            return werkzeug.exceptions.InternalServerError()

    @httprequest
    def upload(self, request, model, field, rec_id, file):
        try:
            master_session_id = request.httprequest.cookies['instance0|session_id'].replace('%22','')
            master_session = request.httpsession[master_session_id]
        except Exception:
            _logger.exception('unauthorized attempt to upload %r', file)
            return werkzeug.exceptions.Forbidden()
        oe_model = master_session.model(model)
        perms, (root, trunk, branch, leaf) = oe_model.fnxfs_field_info(rec_id, field)
        target_path= reduce(div, [p for p in [root, trunk, branch] if p])
        target_path/= leaf.replace('/', '%2f')
        if not target_path.exists():
            target_path.mkdir()
        target_path_file = target_path / file.filename.replace('/', '%2f')
        if not self.use_archive(target_path_file):
            # brand-new file, use name as-is
            file.save(target_path_file)
            return "%s successfully uploaded" % file.filename
        else:
            current = target_path_file / 'current'
            now = target_path_file / datetime.now().strftime('%Y-%m-%d_%H:%M:%S')
            _logger.info("user: %r; action: upload; file: '%s'", master_session._login, target_path_file)
            file.save(now)
            if current.exists():
                current.unlink()
            now.filename.symlink(current)
            return "%s successfully uploaded" % file.filename

    def use_archive(self, path):
        if not path.exists():
            # clean slate, no archive needed
            return False
        elif not path.isdir():
            # simple file exists, need to convert to a directory structure
            nfd, new_name = mkstemp(suffix='.tmp', prefix=path.filename, dir=path.dirname)
            os.close(nfd)
            new_name = Path(new_name)
            path.move(new_name)
            path.mkdir()
            timestamp = datetime(1970, 1, 1) + timedelta(seconds=new_name.stat().st_mtime)
            target = path / timestamp.strftime('%Y-%m-%d_%H:%M:%S')
            new_name.move(target)
            current = path / 'current'
            target.filename.symlink(current)
        # at this point, an archive structure exists
        return True

