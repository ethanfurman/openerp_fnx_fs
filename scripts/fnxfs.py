#!/usr/local/bin/python

from __future__ import print_function

import os
import pandaemonium
import traceback

from collections import defaultdict
from errno import *
from pandaemonium import PidLockFile
from path import Path
from pwd import getpwuid, getpwnam as get_pw_entry
from scription import Command, FLAG, OPTION, Run, Int
from stat import S_ISDIR as is_dir, ST_MODE, ST_UID, ST_GID
from threading import Lock
from time import time

logging = False
pid_file = Path('/var/openerp/%s.pid' % user)
fs_root = Path('/var/openerp/fnx_fs')
archive_root = Path('/var/openerp/fnx_fs_archive')

READ_PERM = os.O_RDONLY | os.O_RDWR
WRITE_PERM = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

@Command(
        src=('file to copy', REQUIRED, 's', Path),
        dst=('where to put it (and possibly new name', REQUIRED, 'd', Path),
        timeout=('how long to wait for lock', OPTION, 't', Int),
        )
def cp(
        src,
        dst,
        timeout=10,
        ):
    """
    copy file into FnxFS structure, also archiving it
    """
    if not dst.exists():
        raise SystemExit('destination file does not exist')
    with PidLockFile(pid_file % dst.filename, timeout=timeout):
        archive_dst = archive_root / (dst - fs_root)
        archive_dst = next_archive_name(archive_dst)
        archive_dst.mkdirs()
        src.copy(archive_dst)
        src.copy(dst)
    
def next_archive_name(archive_path):
    """
    archive_path is the folder holding the archive copies

    if the source file is

      /fs_root/Production/Q_ALL.ods

    then the archive path and file name will be

      /archive_root/Production/Q_ALL.ods/[time_stamp]

    if a file already exists with the current time stamp, sleep for one second and grab
    the next one
    """
    while True:
        time_stamp = DateTime.now().strftime('%Y-%m-%d_%H:%M:%S')
        archive_name = archive_path/time_stamp
        if archive_name.exists():
            time.sleep(1)
        else:
            return archive_name
            

if __name__ == "__main__":
    Run()
