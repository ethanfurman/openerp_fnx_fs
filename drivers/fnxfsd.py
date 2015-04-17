#!/usr/bin/env python
from __future__ import print_function

### BEGIN INIT INFO
# Provides: fnxfsd_init
# Required-Start: $remote_fs $syslog
# Required-Stop: $remote_fs $syslog
# Default-Start: 2 3 4 5
# Default-Stop: 0 1 6
# Short-Description: fnxfs filesystem daemon
# Description: fnxfs filesystem daemon
### END INIT INFO

from antipathy import Path
from pandaemonium import PidLockFile, AlreadyLocked
from scription import *
import os
import traceback

os.environ['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
os.environ['HOME'] = '/root'

SHADOW = Path('/home/.shadow')
MIRROR = Path('/home/.fnxfs_shadow')
if Path.exists('/run'):
    PIDFILE = Path('/run/fnxfsd.pid')
else:
    PIDFILE = Path('/var/run/fnxfsd.pid')

@Command()
def start():
    _start()

@Command()
def stop():
    _stop()

@Command()
def restart():
    _stop()
    _start()

def _start():
    # ideal setup
    #   /home/.shadow has user data
    #   /home/.fnxfs_mirror does not exist
    # recoverable setups
    #   /home/.shadow doesn't exist or is empty
    #   /home/.fnxfs_mirror does exist, and has data
    # unrecoverable setup
    #   /home/.shadow exists with data
    #   /home/.fnxfs_mirror exists
    #   (hopefully this means the daemon is already running!)
    lock = PidLockFile(PIDFILE)
    try:
        lock.acquire()
    except AlreadyLocked:
        abort('fnxfsd already running')
    lock.release()
    if MIRROR.exists() and SHADOW.exists() and SHADOW.listdir():
        abort('both %s and %s already exist!' % (SHADOW, MIRROR))
    if SHADOW.exists() and SHADOW.listdir():
        print('moving %s to %s...' % (SHADOW, MIRROR))
        SHADOW.rename(MIRROR)
    if not SHADOW.exists():
        print('creating %s mount point...' % SHADOW)
        SHADOW.mkdir()
    print('mounting: fnxfsd %s %s' % (MIRROR, SHADOW))
    result = Execute('fnxfsd %s %s' % (MIRROR, SHADOW))
    if result.returncode:
        print(result.stdout, verbose=1)
        print(result.stderr, file=stderr)
        raise SystemExit(result.returncode)
    tries = wait_and_check(5)
    while tries:
        exc = None
        try:
            found = SHADOW.listdir()
        except Exception, exc:
            pass
        else:
            if found:
                break
    else:
        if exc:
            print(traceback.format_exc(exc))
        print('problem mounting %s!  reverting...' % SHADOW)
        _stop()

def _stop():
    print('unmounting %s...' % SHADOW)
    result = Execute('umount %s' % SHADOW)
    if result.returncode:
        print(result.stdout, verbose=0)
        print(result.stderr, file=stderr)
        raise SystemExit(result.returncode)
    exc = None
    retries = wait_and_check(10)
    while retries:
        try:
            found = SHADOW.listdir()
            if not found:
                break
        except Exception, exc:
            pass
    else:
        if exc is not None:
            raise exc
        raise SystemExit('unable to unmount %s' % SHADOW)
    print('removing %s...' % SHADOW)
    SHADOW.rmdir()
    print('moving %s to %s' % (MIRROR, SHADOW))
    MIRROR.rename(SHADOW)

Run()
