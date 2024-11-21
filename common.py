from antipathy import Path
from datetime import datetime, timedelta
from tempfile import mkstemp

import logging
import os
import sys

_logger = logging.getLogger(__name__)

def use_archive(path):
    # returns False if path does not exist
    # if path is a file, creates an archive structure
    # otherwise, an archive structure already existed
    # returns True
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

def delete_file(path):
    if use_archive(path):
        (path/'current').unlink()

def read_file(path, bin_size=False, binary=False):
    r = ''
    if path.isdir():
        path /= 'current'
    try:
        if bin_size:
            r = os.path.getsize(path)
        else:
            r = open(path,'rb').read()
            if not binary:
                r = r.encode('base64')
    except IOError:
        type, exc, traceback = sys.exc_info()
        _logger.error("%s:%s during _read_file reading %s", type, exc, path)
    return r

def write_file(path, data, binary=False):
    # data should be base64 encoded unless binary is True
    if not binary:
        data = data.decode('base64')
    if path.exists():
        # check if current file's contents are the same as the new one's
        existing = read_file(path, binary=True)
        if data == existing:
            return
    if not use_archive(path):
        # brand-new file, use name as-is
        with open(path, 'wb') as fh:
            fh.write(data)
    else:
        current = path / 'current'
        now = path / datetime.now().strftime('%Y-%m-%d_%H:%M:%S')
        with open(now, 'wb') as fh:
            fh.write(data)
        if current.exists():
            current.unlink()
        now.filename.symlink(current)

