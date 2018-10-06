var file_upload = function () {
    var rootdomain = window.location.origin
    var formFileCatcher = document.getElementById('file_catcher');
    var inputFile = document.getElementById('file_input');
    var divAddFile = document.getElementById('add_file_div');
    var pNoNewFiles = document.getElementById('no_new_files');
    var ulYesNewFiles = document.getElementById('yes_new_files');
    var pNoOldFiles = document.getElementById('no_old_files');
    var ulYesOldFiles = document.getElementById('yes_old_files');
    var divExistingFile = document.getElementById('existing_file_div');
    //
    var writePermission = document.getElementById('perm_write').value == 'True';
    var unlinkPermission = document.getElementById('perm_unlink').value == 'True';
    // 
    var existingFileNames = new Set();
    var incomingFileNames = new Set();
    var incomingFiles = [];
    //
    var oldChildren = ulYesOldFiles.children;
    for (var i = 0; i < oldChildren.length; i++) {
        existingFileNames.add(oldChildren[i].children[1].innerHTML);
    };
    //
    inputFile.value = '';
    //
    formFileCatcher.addEventListener('submit', function (e) {
        e.preventDefault();
        incomingFiles.forEach(function (file) {
            sendFile(file);
        });
    });
    //
    inputFile.addEventListener('change', function (e) {
        for (var i = 0; i < inputFile.files.length; i++) {
            var file = inputFile.files[i];
            lowerName = file.name.toLowerCase()
            if (incomingFileNames.has(lowerName)) {
                alert('File '+file.name+' already queued');
            } else if (existingFileNames.has(lowerName)) {
                alert('File '+file.name+' already exists');
            } else {
                incomingFileNames.add(file.name);
                incomingFiles.push(file);
            };
        };
        renderFileList(incomingFiles, pNoNewFiles, ulYesNewFiles, true);
    });
    //
    divAddFile.addEventListener('click', function (e) {
        if (e.target.tagName=='BUTTON' && e.target.className=='icons') {
            var garbage = e.target.parentElement
            var fileName = garbage.children[1].innerHTML
            incomingFiles.forEach(function (file) {
                if (file.name == fileName) {
                    incomingFiles.splice(incomingFiles.indexOf(file), 1);
                    incomingFileNames.delete(file.name);
                    return;
                };
            });
            garbage.remove();
        };
    });
    //
    divExistingFile.addEventListener('click', function (e) {
        if (e.target.tagName=='BUTTON' && e.target.className=='icons') {
            var garbage = e.target.parentElement
            var fileName = garbage.children[1].innerHTML
            var request = new XMLHttpRequest();
            request.onreadystatechange = function() {
                if (request.readyState == 4) {
                    if (request.status != 200) {
                        spanError = document.createElement('span');
                        spanError.innerHTML = '-->'+request.statusText;
                        spanError.style.color = 'red';
                        garbage.appendChild(spanError);
                    } else {
                        garbage.remove()
                        existingFiles.delete(fileName);
                        if (ulYesOldFiles.children.length == 0) {
                            pNoOldFiles.style.display = '';
                            ulYesOldFiles.style.display = 'none';
                        };
                    };
                };
            };
        var formData = new FormData();
        formData.append('file', fileName);
        formData.append('field', document.getElementById('field_name').value);
        formData.append('model', document.getElementById('model_name').value);
        formData.append('rec_id', document.getElementById('record_id').value);
        request.open("POST", rootdomain+"/fnxfs/delete");
        request.send(formData);
        };
    });
    //
    var renderFileList = function (files, para, list, includeStatus) {
        if (!files.length) {
            para.style.display = '';
            list.style.display = 'none';
        } else {
            para.style.display = 'none';
            list.innerHTML = '';
            files.forEach(function (file, index) {
                list.style.display = '';
                var fileButton = document.createElement('button');
                fileButton.innerHTML = 'd';
                fileButton.className = 'icons';
                var fileName = document.createElement('span');
                fileName.innerHTML = file.name;
                var fileDisplay = document.createElement('li');
                fileDisplay.appendChild(fileButton);
                fileDisplay.appendChild(fileName);
                if (includeStatus) {
                    var tracking = document.createElement('span');
                    tracking.innerHTML = '--> Ready';
                    fileDisplay.appendChild(tracking);
                };
                list.appendChild(fileDisplay);
            });
        };
    };
    //
    var sendFile = function (file, index) {
        var fileDisplay = (function () {
            var children = ulYesNewFiles.children
            for (var i = 0; i < children.length; i++) {
                var liFile = children[i]
                var fileName = liFile.children[1].innerHTML;
                if (fileName == file.name) {
                    return liFile;
                };
            };
        })();
        var unlinkButton = fileDisplay.children[0];
        var fileName = fileDisplay.children[1];
        var spanTracking = fileDisplay.children[2];
        var request = new XMLHttpRequest();
        request.onreadystatechange = function() {
            if (request.readyState == 1) {
                spanTracking.innerHTML = '--> Sending...';
            } else if (request.readyState == 4) {
                if (request.status != 200) {
                    spanTracking.innerHTML = '-->'+request.statusText;
                    spanTracking.style.color = 'red';
                } else {
                    spanTracking.innerHTML = '--> Done';
                    pNoOldFiles.style.display = 'none';
                    ulYesOldFiles.style.display = '';
                    spanTracking.remove()
                    fileEl = fileDisplay.children[1]
                    if (existingFileNames.has(fileEl.innerHTML)) {
                        fileDisplay.remove();
                    } else {
                        if (!unlinkPermission) {
                            unlinkButton.remove();
                            var listLeader = document.createElement('span');
                            listLeader.innerHTML = 'U';
                            listLeader.className = 'icons';
                            fileDisplay.insertBefore(listLeader, fileName0;
                        };
                        ulYesOldFiles.appendChild(fileDisplay);
                    };
                    incomingFiles.splice(incomingFiles.indexOf(file), 1);
                    incomingFileNames.delete(file.name);
                    if (ulYesNewFiles.children.length == 0) {
                        pNoNewFiles.style.display = '';
                        ulYesNewFiles.style.display = 'none';
                    };
                };
            };
        };
        var formData = new FormData();
        formData.append('file', file);
        formData.append('field', document.getElementById('field_name').value);
        formData.append('model', document.getElementById('model_name').value);
        formData.append('rec_id', document.getElementById('record_id').value);
        request.open("POST", rootdomain+"/fnxfs/upload");
        request.send(formData);
    };
};
