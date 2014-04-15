#!/usr/local/bin/suid-python

from collections import defaultdict
from errno import *
from os import getlogin as get_login
from pwd import getpwnam as get_pw_entry
from scription import Command, FLAG, OPTION, Run
from stat import S_ISDIR as is_dir
from sys import argv, exit
from time import time
from VSS.paramiko import SSHClient
from VSS.paramiko.client import AutoAddPolicy
from VSS.paramiko.ssh_exception import SSHException
from VSS.path import Path
from VSS.xfuse import FUSE, Operations, FuseOSError, LoggingMixIn

permission_file = Path('/var/openerp/fnx_fs.permissions')
client_root = Path('/home/')
user = get_login()

@Command(
        config=('location of configuration file', OPTION, 'c', Path),
        mount_point=('where to attach FnxFS file system', OPTION, 'm', Path),
        foreground=('remain in foreground', FLAG, 'f'),
        threads=('use threads', FLAG, 't'),
        )
def fnxfs(
        config=Path('/etc/openerp/fnx_fs'),
        mount_point=client_root/user/'fnx_fs',
        foreground=True,
        threads=False,
        ):

    client_pass = None
    server_user = None
    server_pass = None
    openerp = None

    execfile(config)

    class FnxFS(Operations):
        """
        A simple SFTP filesystem. Requires paramiko:
                http://www.lag.net/paramiko/
               
           You need to be able to login to remote host without entering a password.
        
        A file-system to be used with OpenERP FnxFS file system module.
        """
        def __init__(self, host, server_user, server_pass, user):
            self._host = host
            self._client = SSHClient()
            self._client.load_system_host_keys()
            self._client.set_missing_host_key_policy(AutoAddPolicy())
            self._client.connect(host, username=server_user, password=server_pass)
            self._sftp = self._client.open_sftp()
            self._root = Path('/var/openerp/fnx_fs/')
            self._user = user
            pwd_entry = get_pw_entry(self._user)
            self._uid = pwd_entry.pw_uid
            self._gid = pwd_entry.pw_gid
            self._permission_state = None
            self._file_permissions = {}
            self._visible_files = defaultdict(set)
            self._check_permissions()
       
        def __call__(self, op, path, *args):
            self._check_permissions()
            try:
                return super(FnxFS, self).__call__(op, self._root/path, *args)
            except IOError, exc:
                raise FuseOSError(exc.errno)

        def _check_permissions(self):
            try:
                current_state = self._sftp.stat(permission_file)
            except SSHException:
                try:
                    print 'connection dropped, attempting to reestablish'
                    self._client.connect(self._host)
                    self._sftp = self._client.open_sftp()
                    current_state = self._sftp.stat(permission_file)
                except (SSHException, EOFError):
                    raise FuseOSError(ENOLINK)
            if current_state != self._permission_state:
                with self._sftp.open(permission_file) as data:
                    permissions = data.readlines()
                self._file_permissions = {}
                self._visible_files = defaultdict(set)
                target = self._user + ':'
                for line in permissions:
                    if not line.startswith((target, 'all:')):
                        continue
                    user, perm, fn = line.strip().split(':')
                    fn = Path(fn)
                    file = fn.lstrip('/')
                    path = fn.path.strip('/')
                    if perm == 'write':
                        self._file_permissions[file] = 0o600
                    elif perm == 'read':
                        self._file_permissions[file] = 0o400
                    else:
                        raise FuseOSError('Corrupted permissions file')
                    self._visible_files[path].add(file.filename)
                self._permission_state = current_state
       
        def getattr(self, path, fh=None):
            remote_st = self._sftp.lstat(path)
            local_st = dict((key, getattr(remote_st, key)) for key in (
                'st_atime', 'st_mode', 'st_mtime', 'st_size',
                ))
            local_st['st_uid'] = self._uid
            local_st['st_gid'] = self._gid
            try:
                mask = self._file_permissions[path-self._root]
                mode = remote_st.st_mode
                print 'st_mode: %o' % mode
                mode = mode & 0o777000 | mask
                print 'st_mode: %o' % mode
            except KeyError:
                if is_dir(remote_st.st_mode):
                    mode = remote_st.st_mode & 0o777000 | 0o500
                else:
                    mode = remote_st.st_mode & 0o777000 | 0o400
                    local_st['st_uid'] = 0
                    local_st['st_gid'] = 0
            local_st['st_mode'] = mode
            return local_st

        def read(self, path, size, offset, fh):
            f = self._sftp.open(path)
            f.seek(offset, 0)
            buf = f.read(size)
            f.close()
            return buf

        def readdir(self, path, fh):
            files = self._sftp.listdir_attr(path)
            allowed_dirs = self._visible_files.keys()
            if path == self._root:
                names = [f.filename for f in files if (not is_dir(f.st_mode) or f.filename in allowed_dirs)]
            else:
                path -= self._root
                allowed_files = self._visible_files[path]
                names = [f.filename for f in files if (f.filename in allowed_files or f.filename in allowed_dirs)]
            return ['.', '..'] + names

        def readlink(self, path):
            return self._sftp.readlink(path)

        def truncate(self, path, length, fh=None):
            pf = (path - self._root).lstrip('/')
            mode = self._file_permissions[pf]
            if mode != 0o600:
                raise FuseOSError(EACCES)
            return self._sftp.truncate(path, length)

        def utimens(self, path, times=None):
            return self._sftp.utime(path, times)

        def write(self, path, data, offset, fh):
            f = self._sftp.open(path, 'r+')
            f.seek(offset, 0)
            f.write(data)
            f.close()
            return len(data)

    if foreground:
        FnxFS.__bases__ = LoggingMixIn, Operations

    fuse = FUSE(
                FnxFS(host=openerp, server_user=server_user, server_pass=server_pass, user=user),
                mount_point,
                foreground=foreground,
                nothreads=not threads)

if __name__ == "__main__":
    Run()
