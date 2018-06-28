# -*- coding: utf-8 -*-

import logging
import werkzeug
from openerp.addons.web.http import Controller, httprequest
from openerp.addons.web.controllers.main import content_disposition
from antipathy import Path
from fnx_fs.server import permissions
from mimetypes import guess_type
from xaml import Xaml

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
                return werkzeug.exceptions.InternalServerError(
                        'An error occured attempting to access %r; please let IT know.'
                        % (str(target_file),))
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
            return request.make_response(
                    file_data,
                    headers=[
                        ('Content-Disposition',  content_disposition(target_path_file.filename, request)),
                        ('Content-Type', guess_type(file)[0] or 'octet-stream'),
                        ('Content-Length', len(file_data)),
                        ],
                    )
        except Exception:
            _logger.exception('error accessing %r', file)
            return werkzeug.exceptions.InternalServerError(
                    'An error occured attempting to access %r; please let IT know.' % (str(file),)
                    )

    @httprequest
    def select_files(self, request, path, folder):
        target_path = fnx_root
        target_path /= path
        target_path /= folder.replace('/', '%2f')
        files = target_path.listdir()
        template = Xaml(upload_template).document.pages[0]
        page = template.string(files=files, folder=folder, path=path)
        try:
            return request.make_response(
                    page,
                    headers=[
                        ('Content-Type', 'text/html; charset=UTF-8'),
                        ('Content-Length', len(page)),
                        ],
                    )
        except Exception:
            _logger.exception('error processing %r', folder)
            return werkzeug.exceptions.InternalServerError(
                    'An error occured attempting to access %r; please let IT know.' % (str(folder),)
                    )

    @httprequest
    def upload(self, request, path, folder, file):
        target_path_file = fnx_root
        target_path_file /= path
        target_path_file /= folder.replace('/', '%2f')
        target_path_file /= file.filename.replace('/', '%2f')
        _logger.info('receiving: %r', target_path_file)
        file.save(target_path_file)
        return "%s successfully uploaded" % file.filename


upload_template = """\
~h3:  =args.folder
~form #file-catcher method='post'
    ~input #file-input type='file' multiple style='width: 75px;'
    ~input #folder-name type='hidden' name='folder' value=args.folder
    ~input #path-name type='hidden' name='path' value=args.path
    ~button type='submit'
        Submit
    ~button type='button' onclick="window.open('','_self','');window.close()": close

~div #add-file-list-display
    ~h4:  Files to add
    ~p #no-new-files: None selected.
    ~ul #yes-new-files style='display: none;'
~br
~div #existing-file-list-display
    ~h4:  Existing files
    -if not args.files:
        ~p #no-old-files: None
        ~ul #yes-old-files style='display: none;'
    -else:
        ~p #no-old-files style='display: none;': None
        ~ul #yes-old-files
            -for f in args.files:
                ~li: =f

:javascript
    (function () {
        var rootdomain = "http://"+window.location.host
        var fileCatcher = document.getElementById('file-catcher');
        var fileInput = document.getElementById('file-input');
        var addFileListDisplay = document.getElementById('add-file-list-display');
        var noNewFiles = document.getElementById('no-new-files');
        var yesNewFiles = document.getElementById('yes-new-files');
        var noOldFiles = document.getElementById('no-old-files');
        var yesOldFiles = document.getElementById('yes-old-files');
        var existingFileListDisplay = document.getElementById('existing-file-list-display');
        var existingFileNames = new Set();
        var fileList = [];
        var fileListNames = new Set();
        var renderFileList, sendFile;
        //
        fileInput.value = '';
        oldChildren = yesOldFiles.children;
        for (var i = 0; i < oldChildren.length; i++) {
            existingFileNames.add(oldChildren[i].innerHTML);
            };
        //
        fileCatcher.addEventListener('submit', function (e) {
            e.preventDefault();
            var index = 0
            fileList.forEach(function (file) {
                sendFile(file, index);
                index += 1
                });
            });
        //
        fileInput.addEventListener('change', function (e) {
            for (var i = 0, proceed = false; i < fileInput.files.length; i++) {
                var file = fileInput.files[i];
                if (!fileListNames.has(file.name)) {
                    fileListNames.add(file.name);
                    fileList.push(file);
                    proceed = true;
                    } else {
                    alert('File '+file.name+' already queued');
                    };
                };
            if (proceed) {
                renderFileList();
                };
            });
        //
        renderFileList = function () {
            noNewFiles.style.display = 'none';
            yesNewFiles.innerHTML = '';
            fileList.forEach(function (file, index) {
                yesNewFiles.style.display = '';
                var fileDisplayEl = document.createElement('li');
                fileDisplayEl.innerHTML = file.name;
                fileDisplayEl.id = 'file-'+index;
                var tracking = document.createElement('span');
                tracking.id = 'file-span-'+index;
                fileDisplayEl.appendChild(tracking);
                yesNewFiles.appendChild(fileDisplayEl);
                });
            };
        //
        sendFile = function (file, index) {
            var formData = new FormData();
            var request = new XMLHttpRequest();
            var fileSpanEl = document.getElementById('file-span-'+index);
            fileSpanEl.innerHTML = '>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;Ready';
            //
            request.onreadystatechange = function() {
                if (request.readyState == 1) {
                    fileSpanEl.innerHTML = '&nbsp;&nbsp;&nbsp;&nbsp;--->&nbsp;&nbsp;&nbsp;&nbsp;Sending...';
                } else if (request.readyState == 4) {
                    if (request.status != 200) {
                        fileSpanEl.innerHTML = '&nbsp;&nbsp;&nbsp;&nbsp;--->&nbsp;&nbsp;'+request.statusText;
                        fileSpanEl.style.color = 'red';
                    } else {
                        fileSpanEl.innerHTML = '&nbsp;&nbsp;&nbsp;&nbsp;--->&nbsp;&nbsp;&nbsp;&nbsp;Done';
                        noOldFiles.style.display = 'none';
                        yesOldFiles.style.display = '';
                        trackingEl = document.getElementById('file-span-'+index);
                        trackingEl.id = '';
                        trackingEl.remove();
                        fileEl = document.getElementById('file-'+index)
                        fileEl.id = '';
                        if (existingFileNames.has(fileEl.innerHTML)) {
                            fileEl.remove();
                        } else {
                            yesOldFiles.appendChild(fileEl);
                        };
                        fileList.splice(fileList.indexOf(file), 1);
                        fileListNames.delete(file.name);
                        if (yesNewFiles.children.length == 0) {
                            noNewFiles.style.display = '';
                            yesNewFiles.style.display = 'none';
                        };
                    };
                }
            }
            formData.append('file', file);
            formData.append('folder', document.getElementById('folder-name').value);
            formData.append('path', document.getElementById('path-name').value);
            request.open("POST", rootdomain+"/fnxfs/upload");
            request.send(formData);
            };
        })();
"""
