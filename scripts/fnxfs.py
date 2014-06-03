#!/usr/local/bin/suid-python
from __future__ import print_function

# this must happen first!
import pandaemonium
from pandaemonium import Daemon, FileTracker
FileTracker.install()

# this must happen second!
import sys
target = 'python%s.%s' % sys.version_info[:2]
try:
    sys.path.remove('/usr/local/lib/%s/dist-packages' % target)
except ValueError:
    pass
sys.path.insert(0, '/usr/local/lib/%s/dist-packages' % target)

# okay

import os
import traceback

from collections import defaultdict
from errno import *
from pwd import getpwuid, getpwnam as get_pw_entry
from scription import Command, FLAG, OPTION, Run
from stat import S_ISDIR as is_dir, ST_MODE, ST_UID, ST_GID
from threading import Lock
from time import time
from VSS.paramiko import SSHClient
from VSS.paramiko.client import AutoAddPolicy
from VSS.paramiko.ssh_exception import SSHException
from VSS.path import Path
from VSS.xfuse import FUSE, Operations, FuseOSError, ENOTSUP
from VSS.xfuse import fuse_get_context as context

def logger(*words):
    if not words:
        words = ('', )
    text = ' '.join(str(w) for w in words)
    print(text, file=error_log)
    error_log.flush()
    if print_to_screen:
        print(text)
    if stdout_log:
        print(text, file=stdout_log)
        stdout_log.flush()

logging = False
permission_file = Path('/var/openerp/fnx_fs.permissions')
pwd_entry = getpwuid(os.getuid())
user = pwd_entry.pw_name
uid = pwd_entry.pw_uid
gid = pwd_entry.pw_gid
user_home = Path('/home/%s' % user)
user_home_redirect = user_home.path / 'fnxfs_'+user_home.filename
pid_file = Path('/var/run/fnxfs-%s.pid' % user)
remote_root = Path('/var/openerp/fnx_fs')

READ_PERM = os.O_RDONLY | os.O_RDWR
WRITE_PERM = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC

@Command(
        config=('location of configuration file', OPTION, 'c', Path),
        foreground=('remain in foreground', FLAG, 'f'),
        threads=('use threads', FLAG, 't'),
        log=('information logging', FLAG),
        log_file=('file for logging output', OPTION, 'lf', Path),
        )
def fnxfs(
        config=Path('/usr/local/etc/fnx_fs'),
        foreground=False,
        threads=False,
        log=False,
        log_file=False,
        ):

    global logging, print_to_screen
    print_to_screen = foreground
    logging = foreground or log
    pandaemonium._verbose = logging

    execfile(config, globals())

    global error_log, stdout_log
    error_log = open('/var/log/fnxfs-%s.log' % user, 'w')
    if log_file:
        stdout_log = open(log_file, 'w')
    else:
        stdout_log = False

    if not user_home_redirect.exists():
        user_home.move(user_home_redirect)
        user_home.mkdir()
        user_home.chmod(0o755)
        user_home.chown(uid, gid)

    fuse_kwargs = dict(
            foreground=True,
            allow_other=True,
            atime=True,
            nonempty=True,
            nothreads=not threads,
            )

    if logging:
        logger('uid/gid:', uid, gid)

    if foreground:
        print('PID:', os.getpid())
        FUSE(
            FnxFS(host=openerp, server_user=server_user, server_pass=server_pass, user=user),
            user_home,
            **fuse_kwargs)
    else:
        daemon = Daemon()
        daemon.stdout = error_log
        daemon.stderr = error_log
        daemon.inherit_files = [FileTracker.active('/dev/urandom')]
        daemon.pid_file = pid_file
        daemon.uid = 0
        daemon.gid = 0
        with daemon:
            daemon.target = FUSE
            daemon.args = (
                    FnxFS(host=openerp, server_user=server_user, server_pass=server_pass, user=user),
                    user_home,
                    )
            daemon.kwargs = fuse_kwargs
    
    if user_home_redirect.exists():
        if user_home.listdir():
            user_home.move('/home/oops')
            print('saving user mount point as oops')
        else:
            user_home.rmdir()
            print('removed user mount point')
        user_home_redirect.rename(user_home)

def _auto_success(*args, **kwds):
    return 0

def _no_access(*args, **kwds):
    raise OSError(EACCES, 'permission denied')

def _no_support(*args, **kwds):
    raise OSError(ENOTSUP, 'operation not supported')

class FnxFS(object):
    """
    A simple SFTP filesystem. Requires paramiko:
            http://www.lag.net/paramiko/

    A file-system to be used with OpenERP FnxFS file system module.
    """
    def __init__(self, host, server_user, server_pass, user):
        self._host = host
        self._client = SSHClient()
        self._client.load_system_host_keys()
        self._client.set_missing_host_key_policy(AutoAddPolicy())
        if logging:
            logger('connecting as', server_user, 'to', host)
        self._client.connect(host, username=server_user, password=server_pass)
        self._sftp = self._client.open_sftp()
        self._local_root = user_home_redirect
        self._remote_root = remote_root
        self._user = user
        pwd_entry = get_pw_entry(self._user)
        self._uid = uid
        self._gid = gid
        self._permission_state = None
        self._file_permissions = {}
        self._visible = defaultdict(set)
        self._check_permissions()
        self.rwlock = Lock()
   
    def __call__(self, op, path, *args):
        if logging:
            logger('-->', op, path, repr(args)[:200])
            ret = '[unhandled exception]'
        try:
            if op not in ('init','destroy','statfs'):
                if path == '/fnx_fs' or path.startswith('/fnx_fs/'):
                    self._check_permissions()
                    path = path[7:]
                    if path:
                        path = self._remote_root/path
                    else:
                        path = self._remote_root
                    op = 'remote_' + op
                else:
                    path = self._local_root/path
                    op = 'local_' + op
            func = getattr(self, op)
            if func is None:
                raise OSError(EFAULT)
            logger('---', path)
            ret = func(path, *args)
            return ret
        except OSError:
            exc = sys.exc_info()[1]
            ret = str(exc)
            raise
        except Exception:
            exc = sys.exc_info()[1]
            ret = str(exc)
            if logging:
                logger(traceback.format_exc(exc))
            raise
        finally:
            if logging:
                logger('<--', op, repr(ret)[:200])
                logger()

    def __getattr__(self, name):
        """
        Return True if a local_ or remote_ version of `name` is found.
        """
        local = self.__class__.__dict__.get('local_'+name)
        remote = self.__class__.__dict__.get('remote_'+name)
        if local or remote:
            return True
        raise AttributeError('no attribute %r' % name)

    def _check_permissions(self):
        try:
            current_state = self._sftp.stat(permission_file)
        except SSHException:
            try:
                if logging:
                    logger('connection dropped, attempting to reestablish')
                self._client.connect(self._host)
                self._sftp = self._client.open_sftp()
                current_state = self._sftp.stat(permission_file)
            except (SSHException, EOFError):
                raise OSError(ENOLINK)
        if current_state != self._permission_state:
            with self._sftp.open(permission_file) as data:
                permissions = data.readlines()
            self._file_permissions = {}
            self._visible = defaultdict(set)
            target = self._user + ':'
            for line in permissions:
                if logging:
                    logger(line, )
                if not line.startswith((target, 'all:')):
                    if logging:
                        logger('  [skipping]')
                    continue
                #if logging:
                #    logger('')
                user, perm, fn = line.strip().split(':')
                fn = Path(fn)
                file = fn.lstrip('/')
                path = fn.path.strip('/')
                ep = self._file_permissions.get(file, 0)
                if perm == 'write':
                    self._file_permissions[file] = ep | 0o600
                elif perm == 'read':
                    self._file_permissions[file] = ep | 0o400
                else:
                    raise FuseOSError('Corrupted permissions file')
                self._visible[path].add(file.filename)
                dirs = path.dir_pieces
                if dirs:
                    stem = dirs.pop(0)
                    for dir in dirs:
                        self._visible[stem].add(dir)
                        stem /= dir
                    self._visible[stem].add(path.filename)
            if logging:
                logger('')
                for key, paths in sorted(self._visible.items()):
                    logger(key, '-->', paths)
                logger('')
            self._permission_state = current_state

    def _access(self, path, mode):
        uid, gid, pid = context()
        if uid == 0:
            return uid, gid
        file_stat = os.stat(path)
        sticky_dir = file_stat[ST_MODE] & 0o2000
        file_perm = file_stat[ST_MODE] & 0o777
        user, group, other = 0, 0, 0
        if uid == file_stat[ST_UID]:
            user = (file_perm & 0o700) >> 6
        if gid == file_stat[ST_GID]:
            group = (file_perm & 0o070) >> 3
        other = file_perm & 0o007
        if logging:
            logger('---       -uid-  -gid-')
            logger('--- file  %5o  %5o' % (file_stat[ST_UID], file_stat[ST_GID]))
            logger('--- user  %5o  %5o' % (uid, gid))
        for perm in (os.R_OK, os.W_OK, os.X_OK):
            if perm & mode:
                for level in (user, group, other):
                    if perm & level:
                        # this break means success
                        break
                else:
                    # this break means failure
                    break
        else:
            return uid, gid, sticky_dir, file_stat[ST_GID]
        _no_access()

    def init(self, path):
       pass

    def destroy(self, path):
        """
        called on file system destruction; path is always /
        """
        pass

    bmap = mknode = None

    getxattr = listxattr = removexattr = setxattr = None

    def statfs(self, path):
        stv = os.statvfs(self._local_root)
        return dict(
                (key, getattr(stv, key))
                for key in (
                    'f_bavail', 'f_bfree', 'f_blocks',
                    'f_bsize', 'f_favail', 'f_ffree',
                    'f_files', 'f_flag', 'f_frsize', 'f_namemax',
                    ))
   
    def local_access(self, path, mode):
        self._access(path, mode)

    def local_chmod(self, path, mode):
        self._access(path, os.W_OK)
        os.chmod(path, mode)

    def local_chown(self, path, uid, gid):
        self._access(path, os.W_OK)
        os.chown(path, uid, gid)

    def local_create(self, path, mode):
        dirname = os.path.dirname(path)
        uid, gid, sticky_dir, sgid = self._access(dirname, os.W_OK)
        if sticky_dir:
            gid = sgid
        fh = os.open(path, os.O_WRONLY | os.O_CREAT, mode)
        os.chown(path, uid, gid)
        return fh

    def local_flush(self, path, fh):
        return os.fsync(fh)

    def local_fsync(self, path, datasync, fh):
        return os.fsync(fh)

    local_fsyncdir = _auto_success

    def local_getattr(self, path, fh=None):
        st = os.lstat(path)
        return dict(
                (key, getattr(st, key))
                for key in
                    ('st_atime', 'st_ctime', 'st_gid', 'st_mode',
                     'st_mtime', 'st_nlink', 'st_size', 'st_uid')
                )

    def local_link(self, target, source):
        # TODO: check for cross-fnx_fs boundaries
        if source == '/fnx_fs' or source.startswith('/fnx_fs/'):
            _no_access()
        source = self._local_root/source
        return os.link(source, target)

    local_lock = _auto_success      # TODO: make this actually work

    def local_mkdir(self, path):
        dirname = os.path.dirname(path)
        self._access(dirname, os.W_OK)
        os.mkdir(path)

    def local_open(self, file, flags, mode=None):
        perms = 0
        if READ_PERM & flags:
            perms |= os.R_OK
        if WRITE_PERM & flags:
            perms |= os.W_OK
        self._access(file, perms)
        if mode is None:
            return os.open(file, flags)
        else:
            return os.open(file, flags, mode)

    def local_opendir(self, path):
        self._access(path, os.R_OK)
        return 0

    def local_read(self, path, size, offset, fh):
        with self.rwlock:
            os.lseek(fh, offset, 0)
            return os.read(fh, size)
   
    def local_readdir(self, path, fh):
        return ['.', '..'] + os.listdir(path)

    local_readlink = os.readlink
   
    def local_release(self, path, fh):
        return os.close(fh)

    local_releasedir = _auto_success

    def local_rename(self, old, new):
        # TODO: check if logic needed to ensure renames don't cross
        # fnx_fs boundary
        #
        # old has already been adjusted, so we just need to adjust
        # new
        if new == '/fnx_fs' or new.startswith('/fnx_fs/'):
            _no_access()
        old_dirname = os.path.dirname(old)
        self._access(old_dirname, os.W_OK)
        new = self._local_root / new
        new_dirname = os.path.dirname(new)
        self._access(new_dirname, os.W_OK)
        os.rename(old, new)

    def local_rmdir(self, path):
        parent_dir = os.path.dirname(path)
        self._access(parent_dir, os.W_OK)
        os.rmdir(path)

    def local_symlink(self, target, source):
        if source == '/fnx_fs' or source.startswith('/fnx_fs/'):
            # TODO: may want to enable this someday
            _no_access()
        source = self._local_root/source
        dirname = os.path.dirname(target)
        self._access(dirname, os.W_OK)
        return os.symlink(source, target)
   
    def local_truncate(self, path, length):
        dirname = os.path.dirname(path)
        self._access(dirname, os.W_OK|os.R_OK)
        with open(path, 'r+') as f:
            f.truncate(length)
   
    def local_unlink(self, path):
        dirname = os.path.dirname(path)
        self._access(dirname, os.W_OK)
        self._access(path, os.W_OK)
        os.unlink(path)

    def local_utimens(self, path, times):
        self._access(path, os.W_OK)
        os.utime(path, times)

    def local_write(self, path, data, offset, fh):
        with self.rwlock:
            os.lseek(fh, offset, 0)
            return os.write(fh, data)

    def remote_acess(self, path, mode):
        self._access(path, mode)

    remote_chmod = _no_access

    remote_chown = _no_access

    remote_create = _no_access

    remote_flush = _auto_success

    remote_fsync = _auto_success

    remote_fsyncdir = _auto_success

    def remote_getattr(self, path, fh=None):
        # TODO: add caching
        remote_st = self._sftp.lstat(path)
        local_st = dict((key, getattr(remote_st, key)) for key in (
            'st_atime', 'st_mode', 'st_mtime', 'st_size',
            ))
        local_st['st_uid'] = self._uid
        local_st['st_gid'] = self._gid
        try:
            mask = self._file_permissions[path-self._remote_root]
            mode = remote_st.st_mode
            mode = mode & 0o777000 | mask
        except KeyError:
            if is_dir(remote_st.st_mode):
                mode = remote_st.st_mode & 0o777000 | 0o500
            else:
                mode = remote_st.st_mode & 0o777000 | 0o400
                local_st['st_uid'] = 0
                local_st['st_gid'] = 0
        local_st['st_mode'] = mode
        return local_st

    remote_link = _no_access

    remote_lock = None
    
    remote_mkdir = _no_access

    remote_mknod =  _no_access

    def remote_open(self, path, flags, mode):
        perms = 0
        if READ_PERM & flags:
            perms |= os.R_OK
        if WRITE_PERM & flags:
            perm |= os.W_OK
        self._access(file, perm)

    def remote_opendir(self, path):
        return _auto_success()
        #self._access(path, os.R_OK)

    def remote_read(self, path, size, offset, fh):
        f = self._sftp.open(path)
        f.seek(offset, 0)
        buf = f.read(size)
        f.close()
        return buf

    def remote_readdir(self, path, fh):
        files = self._sftp.listdir_attr(path)
        allowed_dirs = self._visible.keys()
        if logging:
            for f in files:
                logger(f)
            logger('')
            for d in allowed_dirs:
                logger(d)
        if path == self._remote_root:
            names = [f.filename for f in files if (not is_dir(f.st_mode) or f.filename in allowed_dirs)]
        else:
            path -= self._remote_root
            allowed_files = self._visible[path]
            allowed_files.add(Path('README'))
            if logging:
                logger('readdir\n=======')
                logger('    allowed files:')
                for f in allowed_files:
                    logger('\t', f)
                logger('    found files:')
                for f in files:
                    logger('\t', f)
            names = [f.filename for f in files if (f.filename in allowed_files or f.filename in allowed_dirs)]
        return ['.', '..'] + names

    def remote_readlink(self, path):
        raise OSError(ENOENT)

    remote_release = _auto_success

    remote_releasedir = _auto_success

    remote_rename = _no_access

    remote_rmdir = _no_access

    remote_symlink = _no_access

    def remote_truncate(self, path, length, fh=None):
        self._access(path, os.R_OK|os.W_OK)
        # pf = (path - self._remote_root).lstrip('/')
        #mode = self._file_permissions[pf]
        #if mode != 0o600:
        #    raise IOAccess(EACCES)
        return self._sftp.truncate(path, length)

    def remote_unlink(self, path):
        _no_access()

    def remote_utimens(self, path, times=None):
        self._access(path, os.W_OK)
        self._sftp.utime(path, times)

    def remote_write(self, path, data, offset, fh):
        f = self._sftp.open(path, 'r+')
        f.seek(offset, 0)
        f.write(data)
        f.flush()
        f.close()
        return len(data)

            
if __name__ == "__main__":
    Run()
