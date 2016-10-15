#!/usr/local/bin/suid-python
from __future__ import print_function
import pandaemonium
from collections import defaultdict
from dbf import DateTime
from getpass import getpass
from pandaemonium import Daemon, PidLockFile, FileTracker, STDOUT, STDERR
from antipathy import Path
from openerplib import AttrDict
from pandaemonium import PidLockFile
from pwd import getpwuid, getpwnam
from scription import *
from subprocess import Popen, PIPE, STDOUT
import commands
import errno
import logging
import os
import pwd
import sys
import time

FileTracker.install()

VERSION = 'server 0.9.beta10'

CLIENT_IP = None  # set if run from an ssh connection
SETTINGS = None
AS_ROOT = False
AS_USER = getpwuid(os.getuid()).pw_name
if AS_USER == 'root':
    AS_ROOT = True
    AS_USER = None



@Script()
def main():
    print('running as', AS_USER or 'root')
    print('entering main()')
    global CLIENT_IP, LOGGER, CONFIG
    CONFIG = OrmFile('/etc/openerp/fnx.ini', section='fnxfsd')
    log_file = Path('/var/log/openerp/fnxfs.log')
    fnxfs_lock = PidLockFile('/var/run/fnxfs.pid', timeout=60)
    with open(log_file, 'a') as logger:
        pass
    LOGGER = logging.getLogger()
    LOGGER.setLevel(logging.DEBUG)
    FH = logging.FileHandler(
            filename=log_file,
            encoding='utf8',
            )
    FH.setLevel(logging.WARNING)
    FH.setFormatter(logging.Formatter("%(asctime)-30s %(name)-40s %(message)s"))
    LOGGER.addHandler(FH)
    client_ip = os.environ.get('SSH_CONNECTION')
    if client_ip is not None:
        CLIENT_IP = client_ip.split()[0]
        print('CLIENT_IP: %s' % CLIENT_IP)
    with fnxfs_lock:
        print('getting current settings')
        if not USERS.exists():
            USERS.open('w').close()
        if not FILES.exists():
            FILES.open('w').close()
        if not FOLDERS.exists():
            FOLDERS.open('w').close()
        for file in USERS, FILES, FOLDERS, PERMISSIONS:
            file.chown(*OPENERP_IDS)
            file.chmod(0660)
        get_settings()
        print('calling %s' % script_command_name)
        script_command()


@Command(
        src=('file to archive', REQUIRED, 'f', Path),
        )
def archive(src):
    "copy existing FnxFS file into the archive"
    if not src.exists():
        abort('source file does not exist')
    if archive_needed(src):
        archive_dst = ARCHIVE_ROOT / (src - FS_ROOT)
        if not archive_dst.exists():
            archive_dst.makedirs() #owner=openerp_ids)
        with PidLockFile(archive_dst/'locked.pid'):
            archive_dst = next_archive_name(archive_dst)
            src.copy(archive_dst)
            # src.chown(*openerp_ids)


# @Command(
#         )
# def clean_slate():
#     """
#     Removes all files entries from OpenERP, leaves folders in place but removes permissions.
#     Does not touch files on disk.
#     """
#     connect_oe(host, db, user, pw)
#     file_ids = OE.fs_file.search([(1,'=',1)])
#     OE.fs_file.unlink(file_ids, context={'keep_files':True})


@Command(
        src=('file to copy', REQUIRED, 's', Path),
        dst=('where to put it (and possibly new name)', REQUIRED, 'd', Path),
        timeout=('how long to wait for lock', OPTION, 't', int),
        force=('make copy even if no record of file exists in OpenERP', FLAG),
        )
def cp(
        src,
        dst,
        timeout=10,
        force=False
        ):
    "copy file/folder into FnxFS structure, also archiving it"
    os.setuid(0)
    os.setgid(0)
    # remove leading /var/openerp/fnxfs from dst
    if dst.startswith(FS_ROOT):
        dst = dst - FS_ROOT
    elif dst.startswith(FS_ROOT[1:]):
        dst = dst - FS_ROOT[1:]
    if not src.isdir():
        if not (FS_ROOT/dst).exists() and not force:
            abort('destination file does not exist (use --force to copy anyway)')
        print('copying %s to %s' % (src, FS_ROOT/dst))
        copy(src, FS_ROOT/dst, timeout)
        (FS_ROOT/dst).chown(*OPENERP_IDS)
        (FS_ROOT/dst).chmod(0770)
    else:
        for dirpath, dirnames, filenames in src.walk():
            for fn in filenames:
                fn_lower = fn.filename.lower()
                if (
                        '\\' in fn_lower or
                        'touch' in fn_lower or
                        fn_lower.startswith('backup') and fn_lower.endswith('.log') or
                        fn_lower == 'thumbs.db'
                    ):
                    continue
                new_fn = fn.filename
                if new_fn.startswith('.'):
                    if new_fn[1] in '0123456789':
                        new_fn = '0' + new_fn
                    else:
                        continue
                new_fn = new_fn.replace('%20', ' ')
                new_fn = ''.join([ch for ch in new_fn if ord(ch) < 128])
                new_fn = fn.path / new_fn
                copy(dirpath/fn, FS_ROOT/dst/dirpath/new_fn, timeout)


@Command(
        src=Spec('[ip_addr:]/path/to/filename', type=Path, abbrev=None),
        dst=Spec('folder[/folder[/...]][/share_as_filename]', type=Path, abbrev=None),
        styp=Spec('share type', OPTION, choices=['live', 'publish', 'auto-publish'], abbrev=None, default='live'),
        ptyp=Spec('permission type', OPTION, choices=['custom', 'inherit'], abbrev=None, default='inherit'),
        ro_users=Spec('users with read-only access', MULTI, abbrev=None),
        rw_users=Spec('users with read-write access [only for "live" files]', MULTI, abbrev=None),
        desc=Spec('short description of file', OPTION, abbrev=None, default=''),
        freq=Spec('how often to republish file [only for "auto-publish" files]', OPTION, abbrev=None, default=''),
        as_user=('user to run command as', OPTION),
        )
def create_file(src, dst, styp, ptyp, ro_users, rw_users, desc, freq, as_user):
    "create new shared file, specifying share and permission types, user access, description, etc."
    # get names for source and destination
    print('source file ->', src)
    src_filename = src.filename
    # add in CLIENT_IP if available and requested
    if CLIENT_IP and src.startswith('client:'):
        src = CLIENT_IP + src[6:]
    # check that folder is specified and exists
    # - first check if entire dst is a folder
    print('destination file ->', dst)
    if dst not in SETTINGS.folders:
        print('  not in SETTINGS.folders')
        if dst.path not in SETTINGS.folders:
            abort('missing folder: <%s> does not exist (use "tree" to see all folders/files)' % dst.path)
        print('  but %s is' % dst.path)
    if not dst.filename:
        # dst was a path, so add the filename
        dst /= src_filename
    print('destination file ->', dst)
    # check for a valid filename
    if is_tempfile(src_filename):
        abort('invalid filename: filename cannot start with a period (.) or end with a tilde (~)')
    # check that filename isn't already shared
    if dst in SETTINGS.files:
        abort('file <%s> already shared (use "show" for details)' % dst)
    # check that read-write users only specified on 'live' share type
    if rw_users and styp != 'live':
        help('cannot specify rw_users with non-live share type')
    # check that frequency only specified on 'auto-publish' share type
    if freq and styp != 'auto-publish':
        help('cannot specify freq with non-auto-publish share type')
    # check that specified users exist
    non_users = []
    if ro_users + rw_users:
        ptyp = 'custom'
    for user in ro_users + rw_users:
        if user == 'all':
            continue
        elif user not in SETTINGS.users:
            non_users.append(user)
    if non_users:
        abort('following users do not exist: %s (use "show --all-users" to see users)' % ', '.join(non_users))
    # ensure no tabs in description
    desc = desc.replace('\t',' ')
    # check that user has privilege
    if as_user and not AS_ROOT:
        abort('must be root to specify a different user')
    user = as_user or AS_USER
    if user is not None:
        print('user is', user)
        if dst.path == '/':
            if SETTINGS.users[user].level not in ('creator', 'manager'):
                abort('invalid folder: files must be shared in a virtual folder')
        elif SETTINGS.folders[dst.path].share_type != 'virtual':
            abourt('invalid folder: files must be shared in a virtual folder')
        elif user not in SETTINGS.folders[dst.path].create_delete_users:
            abort('permission denied')
    # okay, let's do this!
    # step 0: copy file into fnxfs directory structure
    print('executing:', 'scp', '-o', 'StrictHostKeyChecking=no', src, FS_ROOT/dst)
    attempt = Execute(['scp', '-o', 'StrictHostKeyChecking=no', src, FS_ROOT/dst], pty=True, password=CONFIG.server_root)
    if attempt.stdout:
        print(attempt.stdout.rstrip())
    if attempt.stderr:
        print(attempt.stderr.rstrip(), file=stderr)
    if attempt.returncode or attempt.stderr:
        raise SystemExit(attempt.returncode)
    (FS_ROOT/dst).chown(*OPENERP_IDS)
    (FS_ROOT/dst).chmod(0660)
    # step 1: update SETTINGS.files
    SETTINGS.files[dst] = AttrDict(
            share_type=styp,
            permissions_type=ptyp,
            read_users=ro_users,
            write_users=rw_users,
            description=desc,
            source=src,
            frequency=freq,
            )
    # step 2: update files and permissions file
    SETTINGS.write_files()
    SETTINGS.write_permissions()


@Command(
        name=Spec('name of new folder', type=Path, abbrev=None),
        styp=Spec('share type', OPTION, choices=['mirror', 'share', 'virtual'], abbrev=None, default='virtual'),
        ptyp=Spec('permission type', OPTION, choices=['custom', 'inherit'], abbrev=None, default='inherit'),
        ro_users=Spec('users with read-only access', MULTI, abbrev=None),
        rw_users=Spec('users with read-write access [only for "virtual" folders', MULTI, abbrev=None),
        cd_users=Spec('users with create/delete access [only for "virtual" folders]', MULTI, abbrev=None),
        desc=Spec('short description of folder', OPTION, abbrev=None, default=''),
        as_user=('user to run command as', OPTION),
        )
def create_folder(name, styp, ptyp, ro_users, rw_users, cd_users, desc, as_user):
    "create a new folder, specifying share and permission types, user access, and description"
    # check that folder doesn't already exist
    name = name.rstrip('/')
    if name in SETTINGS.folders:
        abort('folder <%s> already exists (use "show" for details)' % name)
    # check that parent folders exist
    parent = name.path
    if parent and parent not in SETTINGS.folders:
        abort('parent folder <%s> does not exist (use "tree" to see all folders/files)' % parent)
    # check that specified users exist
    non_users = []
    found = False
    for check_user in ro_users + rw_users + cd_users:
        if check_user == as_user:
            found = True
        if check_user == 'all':
            continue
        elif check_user not in SETTINGS.users:
            non_users.append(check_user)
    if non_users:
        abort('following users do not exist: %s (use "users" to see all users)' % ', '.join(non_users))
    if as_user is not None and not found:
        rw_users += (as_user, )
    # ensure no tabs in description
    desc = desc.replace('\t',' ')
    # if primary directory, permission type is 'custom'
    if '/' not in name or ro_users + rw_users + cd_users:
        ptyp = 'custom'
    # check that user is creator/managor and has privilege
    if as_user and not AS_ROOT:
        abort('must be root to specify a different user')
    user = as_user or AS_USER
    if user is not None:
        # if '/' not in name:
        if SETTINGS.users[user].level not in ('creator', 'manager'):
            abort('permission denied: only creator and manager can create folders')
        elif ('/' in name
              and user not in SETTINGS.folders[name.path].create_delete_users
              # and user not in SETTINGS.folders[name.path].write_users
              ):
            abort('permission denied: write or create permission needed on parent folder')
    # okay, let's do this!
    # step 0: create folder in fnxfs directory structure
    dst = FS_ROOT/name
    if not dst.exists():
        dst.mkdir()
        dst.chown(*OPENERP_IDS)
        dst.chmod(0770)
    elif not dst.isdir():
        abort('%s already exists but is not a directory' % dst)
    # step 1: update SETTINGS.folders
    SETTINGS.folders[name] = AttrDict(
            share_type=styp,
            permissions_type=ptyp,
            read_users=ro_users,
            write_users=rw_users,
            create_delete_users=cd_users,
            description=desc,
            )
    # step 2: update folders and permissions files
    SETTINGS.write_folders()
    SETTINGS.write_permissions()


@Command(
        login=('user to create', ),
        level=Spec('privilege level', choices=['consumer', 'creator', 'manager'], default='consumer'),
        )
def create_user(login, level):
    "create a new user, and assign privilege level"
    if not AS_ROOT:
        abort('must be root')
    # TODO: allow specification of permissions for folders and files
    if login in SETTINGS.users:
        abort('user <%s> already exists (use "show" for details)' % login)
    SETTINGS.users[login] = AttrDict(level=level)
    SETTINGS.write_users()
    SETTINGS.write_permissions()


@Command(
        name=Spec('path/name of file to remove', type=Path),
        as_user=('user to run command as', OPTION),
        )
def delete_file(name, as_user):
    "remove a file from FnxFS"
    if name not in SETTINGS.files:
        abort('file <%s> not in FnxFS (use "tree" to see folders/files' % name)
    if as_user and not AS_ROOT:
        abort('must be root to specify a different user')
    user = as_user or AS_USER
    if user is not None:
        if user not in SETTINGS.files[name].write_users:
            abort('permission denied')
        elif user not in SETTINGS.folders[name.path].create_delete_users:
            abort('permission denied')
    print('removing file %s' % FS_ROOT/name)
    (FS_ROOT/name).unlink()
    if (FS_ROOT/name).exists():
        abort('file not deleted')
    del SETTINGS.files[name]
    SETTINGS.write_files()
    SETTINGS.write_permissions()


@Command(
        folder=Spec('path/folder to remove', type=Path),
        as_user=('user to run command as', OPTION),
        )
def delete_folder(folder, as_user):
    "remove a folder from FnxFS"
    f_plain = folder.rstrip('/')
    f_slash = f_plain / ''
    if f_plain not in SETTINGS.folders:
        abort('folder <%s> not in FnxFS' % f_plain)
    if as_user and not AS_ROOT:
        abort('must be root to specify a different user')
    user = as_user or AS_USER
    if user is not None:
        if '/' not in f_plain:
            if SETTINGS.users[user].level not in ('creator', ):
                abort('permission denied')
        if user not in SETTINGS.folders[f_plain].create_delete_users:
            abort('permission denied')
    # if folder is a mirror or share, we can just remove it
    rec = SETTINGS.folders[f_plain]
    # mirror and share type folders can simply be deleted
    # virtual folders have to be checked for content
    if rec.share_type == 'virtual':
        empty = True
        # verify no virtual folders or files still in this folder
        for f in SETTINGS.folders:
            if f.startswith(f_slash):
                empty = False
                print('found', f)
        for f in SETTINGS.files:
            if f.startswith(f_slash):
                empty = False
                print('found', f)
        if not empty:
            abort('folder <%s> not empty (use "tree" to see folders/files)' % f_plain)
    (FS_ROOT/f_plain).rmdir()
    del SETTINGS.folders[f_plain]
    SETTINGS.write_folders()
    SETTINGS.write_permissions()


@Command(
        login=('user to delete', ),
        )
def delete_user(login):
    "remove a user from FnxFS"
    if not AS_ROOT:
        abort('must be root')
    if login not in SETTINGS.users:
        abort('user <%s> does not exist in FnxFS' % login)
    del SETTINGS.users[login]
    for file in SETTINGS.files:
        ro_users = SETTINGS.files[file].read_users
        rw_users = SETTINGS.files[file].write_users
        if login in ro_users:
            ro_users.remove(login)
        if login in rw_users:
            rw_users.remove(login)
    for folder in SETTINGS.folders:
        ro_users = SETTINGS.folders[folder].read_users
        rw_users = SETTINGS.folders[folder].write_users
        cd_users = SETTINGS.folders[folder].create_delete_users
        if login in ro_users:
            ro_users.remove(login)
        if login in rw_users:
            rw_users.remove(login)
        if login in cd_users:
            cd_users.remove(login)
    SETTINGS.write_users()
    SETTINGS.write_folders()
    SETTINGS.write_files()
    SETTINGS.write_permissions()


@Command(
        name=('file/folder/user to modify', ),
        level=Spec('new privilege level for user (for users)', OPTION, choices=['consumer', 'creator', 'manager']),
        ro_users=('new list of read-only users (for files/folders)', MULTI, 'r'),
        rw_users=('new list of read-write users (for files/folders)', MULTI, 'w'),
        cd_users=('new list of read-write-create users (for folders', MULTI, 'c'),
        del_user=('users whose access to remove (for files/folders)', MULTI),
        add_read_user=('users to add as read-only (for files/folders)', MULTI, None),
        add_write_user=('users to add as read-write (for files/folders)', MULTI, None),
        add_create_user=('users to add as read-write-create (for folders)', MULTI, None),
        )
def modify(
        name, level,
        ro_users, rw_users, cd_users,
        del_user,
        add_read_user, add_write_user, add_create_user,
        ):
    "change permissions for users, files, or folders"
    if not (
            level or
            ro_users or rw_users or cd_users or
            del_user or
            add_read_user or add_write_user or add_create_user
            ):
        help('nothing to do')
    if name in SETTINGS.users:
        if not level:
            help('only level can be specified for users')
        if (
            ro_users or rw_users or cd_users or
            del_user or
            add_read_user or add_write_user or add_create_user
            ):
            abort("only level can be specified for users")
        if not AS_ROOT:
            abort("must be root to change a user's settings")
        SETTINGS.users[name].level = level
        SETTINGS.write_users()
        SETTINGS.write_permissions()
        return
    elif name in SETTINGS.files:
        type = 'file'
        settings = SETTINGS.files[name]
        if cd_users:
            help('create-users is only for folders, not files')
        if add_create_user:
            help('add-create-user is only for folders, not files')
    elif name in SETTINGS.folders:
        type = 'folder'
        settings = SETTINGS.folders[name]
    else:
        abort('<%s> not found' % name)
    # verify users are in system
    for group in (ro_users, rw_users, cd_users, add_read_user, add_write_user, add_create_user, del_user):
        for user in group:
            if user == 'all':
                continue
            elif user not in SETTINGS.users:
                abort('user <%s> not in FnxFS' % user)
    for user in del_user + add_read_user + add_write_user + add_create_user + ro_users + rw_users + cd_users:
        if user in settings.read_users:
            settings.read_users.remove(user)
        if user in settings.write_users:
            settings.write_users.remove(user)
        if 'create_delete_users' in settings:
            if user in settings.create_delete_users:
                settings.create_delete_users.remove(user)
    if ro_users:
        settings.read_users = list(ro_users)
    if rw_users:
        settings.write_users = list(rw_users)
    if cd_users:
        settings.create_delete_users = list(cd_users)
    for user in add_read_user:
        settings.read_users.append(user)
    for user in add_write_user:
        settings.write_users.append(user)
    for user in add_create_user:
        settings.create_delete_users.append(user)
    settings.permissions_type = 'custom'
    SETTINGS.write_files()
    SETTINGS.write_folders()
    SETTINGS.write_permissions()


@Command()
def refresh():
    "rewrite permissions file from current settings"
    SETTINGS.write_permissions()


@Command(
        subcommand=(
            'start | stop | restart shares from a client machine, or [in]active to list all [in]active shares',
            REQUIRED,
            'c',
            str,
            ['start', 'stop', 'restart', 'active', 'inactive'],
            ),
        share=('mount point, ip address of shares, "ssh", "smb", or "all",', REQUIRED)
        )
def shares(subcommand, share=''):
    "work with FnxFS mounts"
    # we support two different types of mounts: smb and sshfs
    # the smb (un)mount must be done with uid of root
    # the sshfs unmount must be done with uid of root
    # the sshfs mount must be done with uid of openerp
    print(' uid =', os.getuid(), verbose=2)
    print('euid =', os.geteuid(), verbose=2)
    print(' gid =', os.getgid(), verbose=2)
    print('egid =', os.getegid(), verbose=2)
    if not share:
        if subcommand in ('active', 'inactive'):
            share = 'all'
        else:
            share = 'ssh'
    print('command =', subcommand, verbose=2)
    print('share =', share, verbose=2)
    target_shares = parse_mount_file(share)
    print('target =', target_shares, verbose=2)
    if not target_shares:
        if share == 'all':
            abort('no shares listed in %s' % FNXFS_MOUNT)
        else:
            abort('share not found')
    active = AttrDict(default=dict)
    inactive = AttrDict(default=dict)
    shares = {}
    # get mounted shares known about in /proc/mounts
    with open('/proc/mounts') as proc:
        mounted_shares = proc.read()
    for typ, params in target_shares:
        source, mount = params[0], params[-1]
        if (mount.replace(' ', '\\040') + ' ') in mounted_shares:
            print('active: %s' % mount, verbose=2)
            active[typ][mount] = source
        else:
            print('inactive: %s' % mount, verbose=2)
            inactive[typ][mount] = source
        shares[mount] = params
    if subcommand == 'active':
        for typ in ('smb', 'ssh'):
            for mnt, src in sorted(active[typ].items()):
                print('%5s: %-40s %-40s' % (typ, mnt, src), verbose=0)
    if subcommand == 'inactive':
        for typ in ('smb', 'ssh'):
            for mnt, src in sorted(inactive[typ].items()):
                print('%5s: %-40s %-40s' % (typ, mnt, src), verbose=0)
    for typ, stop_cmd, start_cmd in (('smb', stop_smb, start_smb), ('ssh', stop_sshfs, start_sshfs)):
        if subcommand in ('restart', 'stop'):
            for mnt in sorted(shares.keys()):
                if mnt in active[typ]:
                    print('stopping ', mnt, '. . . ', end='')
                    print(stop_cmd(mnt))
                    inactive[typ][mnt] = active[typ].pop(mnt)
                elif mnt in inactive[typ]:
                    print('%s already stopped' % mnt)
        if subcommand in ('restart', 'start'):
            #if os.getuid() == 0 and typ == 'ssh':
            #    os.initgroups('openerp', openerp_ids[1])
            #    os.setuid(openerp_ids[0])
            for mnt in sorted(shares.keys()):
                if mnt in inactive[typ]:
                    print('starting ', mnt, '. . . ', end='')
                    print(start_cmd(*shares[mnt]))
                elif mnt in active[typ]:
                    print('%s already started' % mnt)


@Command(
        name=Spec('name of file/folder/user to show', default=''),
        all_users=Spec('list all users', FLAG, 'u'),
        all_files=Spec('list all files', FLAG, 'f'),
        all_folders=Spec('list all folders', FLAG, 'd'),
        )
def show(name, all_users, all_files, all_folders):
    "display information about a user/file/folder"
    if not (name or all_users or all_files or all_folders):
        help('nothing to do')
    if all_users:
        for user in SETTINGS.users:
            attrs = SETTINGS.users[user]
            print('user: %-25s %s' % (user, attrs.level), verbose=0)
    if all_files:
        for file in SETTINGS.files:
            attrs = SETTINGS.files[file]
            print('file:', file,
                    attrs.share_type, attrs.permissions_type, attrs.source, attrs.frequency,
                    attrs.read_users, attrs.write_users, attrs.description,
                    sep='\t', verbose=0)
    if all_folders:
        for folder in SETTINGS.folders:
            attrs = SETTINGS.folders[folder]
            print('folder:', folder,
                    attrs.share_type, attrs.permissions_type,
                    attrs.read_users, attrs.write_users, attrs.create_delete_users,
                    attrs.description,
                    sep='\t', verbose=0)
    if name:
        found = False
        res = SETTINGS.files.get(name)
        if res is not None:
            found = True
            print('file:', name,
                    res.share_type, res.permissions_type, res.source, res.frequency,
                    res.read_users, res.write_users, res.description,
                    sep='\t', verbose=0)
        res = SETTINGS.folders.get(name)
        if res is not None:
            found = True
            print('folder:', name,
                    res.share_type, res.permissions_type,
                    res.read_users, res.write_users, res.create_delete_users,
                    res.description,
                    sep='\t', verbose=0)
        res = SETTINGS.users.get(name)
        if res is not None:
            found = True
            print('user:', name, res.level, sep='\t', verbose=0)
        if not found:
            print('unable to find', name, verbose=0)


@Command(
        path=Spec('path to examine', REQUIRED, default=Path('/')),
        include_files=Spec('display files', FLAG, 'f'),
        )
def tree(path, include_files, _prefix='', _files=defaultdict(list), _pool={}):
    "display a tree of the folder/file structure in FnxFS"
    if not _pool:
        print('entering tree()')
    # transform settings
    path = path.rstrip('/')
    if not path.startswith('/'):
        path = '/' + path
    if include_files and not _files:
        print('getting files')
        for file in SETTINGS.files:
            print('adding', file, verbose=2)
            _files[file.path].append(file.filename)
    if not _pool:
        print('calculating pool')
        _pool['/'] = ([], [])
        for key in sorted(SETTINGS.folders):
            f = _files.get(key, [])
            if '/' not in key:
                current = '/'
                leaf = key
            else:
                current, leaf = key.rsplit('/', 1)
                current = '/' + current
            _pool[current][0].append(leaf)
            _pool['/' + key] = ([], f)
        print('_pool:', _pool, verbose=2)
    if not _prefix:
        print(path/'', verbose=0)
    def walk(path='/'):
        # emulate os.walk on _pool
        print('walk', path, _pool.get(path, ([], [])), verbose=2)
        current = path
        dirs, files = _pool.get(current, ([], []))
        yield current, dirs, files
        for d in dirs:
            for current, dirs, files in walk(d):
                print('subwalk', path/current, dirs, files, verbose=2)
                yield path/current, dirs, files
    # now do the display
    for current, dirs, files in walk(path):
        if not current.startswith(path):
            print('skipping', current, verbose=2)
            continue
        last_dir = last_file = None
        if files and not dirs:
            last_file = files.pop()
        if dirs:
            last_dir = dirs.pop()
        for file in files:
            print(_prefix, '|-- ', file, sep='', verbose=0)
        if last_file:
            print(_prefix, '`-- ', last_file, sep='', verbose=0)
        if (files or last_file) and dirs:
            print(_prefix, '|', sep='', verbose=0)
        for dir in dirs:
            print(_prefix, '|-- ', dir, '/', sep='', verbose=0)
            tree(current/dir, include_files, _prefix=_prefix+'|  ')
        if last_dir:
            print(_prefix, '`-- ', last_dir, '/', sep='', verbose=0)
            tree(current/last_dir, include_files, _prefix=_prefix+'   ')
        dirs[:] = []


def archive_needed(src):
    """
    return True if the metadata on src differs from the latest archive version's
    """
    # use st_size, st_atime, st_mtime
    archive = ARCHIVE_ROOT / (src - FS_ROOT)
    try:
        arc = sorted(archive.glob('/*'))[-1]
    except IndexError:
        return True
    src_meta = src.stat()[6:9]
    arc_meta = arc.stat()[6:9]
    return src_meta != arc_meta

def copy(src, dst, timeout):
    archive_dst = ARCHIVE_ROOT / (dst - FS_ROOT)
    if not archive_dst.exists():
        print('creating archive folder:', archive_dst, verbose=2)
        archive_dst.makedirs() #owner=openerp_ids)
    if not dst.path.exists():
        print('creating destination folder:', dst.path, verbose=2)
        dst.path.makedirs() #owner=openerp_ids)
    with PidLockFile(archive_dst/'locked.pid', timeout=timeout):
        print('copying...', verbose=2)
        src.copy(dst)
        # dst.chown(*openerp_ids)
        if archive_needed(dst):
            archive_dst = next_archive_name(archive_dst)
            src.copy(archive_dst)
            archive_dst.chown(*OPENERP_IDS)
            archive_dst.chmod(0644)

def next_archive_name(archive_path):
    """
    archive_path is the folder holding the archive copies
    if the source file is
      /FS_ROOT/Production/Q_ALL.ods
    then the archive path and file name will be
      /ARCHIVE_ROOT/Production/Q_ALL.ods/[time_stamp]
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

def parse_mount_file(share):
    """
    return all matching entry for share
    """
    print('parse_mount_file:', verbose=2)
    shares = []
    with open(FNXFS_MOUNT) as data:
        mounts = data.readlines()
    for line in mounts:
        line = line.strip()
        print('   ' + line, verbose=2)
        if not line:
            continue
        mount_point, options, source = line.split('\t')
        if ':/home/' in source:
            source = source.replace(':/home/', ':/home/.fnxfs_shadow/')
        if (
            share == 'all' or
            options == 'ssh' and share == 'ssh' or
            options == 'smb' and share != 'ssh' or
            FS_ROOT/share == mount_point or
            share == source.split(':', 1)[0].strip('/')
            ):
                if options == 'ssh':
                    shares.append(('ssh', (source, Path(mount_point))))
                else:
                    shares.append(('smb', (source, options, Path(mount_point))))
    return shares

def get_settings():
    print('entering get_settings()')
    global SETTINGS
    SETTINGS = Permissions()
    print('returning from get_settings()')
    return SETTINGS

def is_tempfile(filename):
    "returns True if filename looks like a temp"
    return filename.startswith('.') or filename.endswith('~') or not filename

def start_smb(source, options, mount):
    """
    start a normal mount
    """
    source = '"%s"' % source
    mount = '"%s"' % mount
    command = ['/bin/mount', ] + options.split() + [source, mount]
    command =  ' '.join(command)
    with open('/var/log/fnxfs_debug', 'a+') as debug:
        debug.write(command + '\n')
    # return commands.getoutput(command)
    output = Execute(command, password=CONFIG.server_root, pty=True)
    result = ''
    if output.stdout or output.returncode:
        print(output.stdout) #, verbose=0)
        print(output.stderr) #, file=stderr)
        raise SystemExit(output.returncode)
    return result.replace('Password:','').strip()

def start_sshfs(source, mount):
    """
    start an sshfs session to make a share available
    """
    source = 'root@%s' % source
    cmd = Popen(['/usr/bin/sshfs'] + SSHFS_OPTIONS + [source, mount], stdin=PIPE, stdout=PIPE, stderr=STDOUT)
    cmd.stdin.write(CONFIG.server_root + '\r\n')
    output = cmd.stdout.read()
    return output

def stop_smb(mount):
    """
    unmounts a mount
    """
    #commands.getoutput('umount "/var/openerp/fnxfs/IT Share/Requests/newShare5"') # this one works from python shell
    output = commands.getoutput('/bin/umount "%s"' % mount)
    open('/var/log/fnxfs_debug','a+').write('/bin/umount "%s"\n' % mount)
    return output

def stop_sshfs(mount):
    """
    unmounts an sshfs share and stop sshfs process
    """
    command = ['/usr/local/bin/fusermount', '-u', mount]
    output = Execute(command)
    result = ''
    if output.stdout:
        result += output.stdout
    return result


# SETTINGS = AttrDict(files=AttrDict(), folders=AttrDict(), users=AttrDict())
class Permissions(object):

    users_stamp = None
    folders_stamp = None
    files_stamp = None

    def __init__(self):
        self.files = AttrDict()
        self.folders = AttrDict()
        self.users = AttrDict()
        self.refresh()

    def __getitem__(self, name):
        self.refresh()
        # searches self.files for an exact match, then self.folders for an ancestral match
        key = name.strip('/')
        if key in self.files:
            return self.files[key]
        elif key in self.folders:
            return self.folders[key]
        else:
            dirs = Path(key).dir_elements
            last = None
            path = Path()
            for dir in dirs:
                dir = (path / dir).strip('/')
                if dir not in self.folders:
                    break
                last = dir
            if last is None:
                raise KeyError('%s not found' % name)
            return self.folders[last]

    def load_users(self):
        with open(USERS) as users:
            print('reading user file')
            next(users, None)
            for line in users:
                try:
                    line = line.strip()
                    user, level = line.split('\t')
                    self.users[user] = AttrDict(level=level)
                except ValueError:
                    LOGGER.exception('unable to parse fnxfs.users: %r', line)

    def load_folders(self):
        with open(FOLDERS) as folders:
            print('reading folders file')
            next(folders, None)
            for line in folders:
                print('  ->', line)
                try:
                    line = line.strip()
                    pieces = line.split('\t')
                    pieces += [''] * (7-len(pieces))
                    name, share, perm, read, write, create_delete, desc = pieces
                    if '/' not in name:
                        # this is a root folder, do not allow 'inherit'
                        perm = 'custom'
                    self.folders[Path(name)] = AttrDict(
                            share_type=share,
                            permissions_type=perm,
                            read_users=read and read.split(',') or [],
                            write_users=write and write.split(',') or [],
                            create_delete_users=create_delete and create_delete.split(',') or [],
                            description=desc,
                            )
                except ValueError:
                    LOGGER.exception('unable to parse fnxfs.folders: %r', line)
        print('inheriting permissions')
        for name in sorted(self.folders.keys()):
            print('  checking %s' % name, verbose=2)
            # XXX: possible optimization -- only check previous folder as it should have been set
            #      by the previous iteration
            vals = perms = self.folders[name]
            while perms.permissions_type == 'inherit':
                print('    ', perms, verbose=2)
                name = name.path
                perms = self.folders[name]
            if vals is not perms:
                vals.read_users = perms.read_users
                vals.write_users = perms.write_users
                vals.create_delete_users = perms.create_delete_users

    def load_files(self):
        with open(FILES) as files:
            print('reading files file')
            next(files, None)
            for line in files:
                try:
                    line = line.strip()
                    pieces = line.split('\t')
                    pieces += [''] * (8-len(pieces))
                    name, share, perm, read, write, desc, source, freq = pieces
                    self.files[Path(name)] = AttrDict(
                            share_type=share,
                            permissions_type=perm,
                            read_users=read and read.split(',') or [],
                            write_users=write and write.split(',') or [],
                            description=desc,
                            source=source,
                            frequency=freq,
                            )
                except ValueError:
                    LOGGER.exception('unable to parse fnxfs.files: %r', line)
        print('inheriting permissions')
        for name in sorted(self.files.keys()):
            print('checking %s' % name, verbose=2)
            # XXX: possible optimization -- only check containing folder as it should have been
            #      set by the previous loop
            vals = perms = self.files[name]
            folder = name.path
            print(repr(perms), verbose=3)
            while perms.permissions_type == 'inherit':
                perms = self.folders[folder]
                folder = folder.path
            if vals is not perms:
                vals.read_users = perms.read_users
                vals.write_users = perms.write_users + perms.create_delete_users

    def refresh(self):
        'reread any stale permissions files'
        current = USERS.stat()
        if current != self.users_stamp:
            self.users_stamp = current
            self.load_users()
        current = FOLDERS.stat()
        if current != self.folders_stamp:
            self.folders_stamp = current
            self.load_folders()
        current = FILES.stat()
        if current != self.files_stamp:
            self.files_stamp = current
            self.load_files()

    def write_files(self):
        with open(FILES, 'w') as files:
            files.write('# path\tshare-type\tpermission-type\tread\twrite\tdescription\tsource\tfrequency\n')
            for name in sorted(self.files.keys()):
                v = self.files[name]
                files.write(('%(name)s\t%(styp)s\t%(ptyp)s\t%(ro_users)s\t%(rw_users)s\t%(desc)s\t%(src)s\t%(freq)s' % dict(
                        name=name,
                        styp=v.share_type,
                        ptyp=v.permissions_type,
                        ro_users=','.join(v.read_users),
                        rw_users=','.join(v.write_users),
                        desc=v.description,
                        src=v.source,
                        freq=v.frequency,
                        )).strip() + '\n')

    def write_folders(self):
        with open(FOLDERS, 'w') as folders:
            folders.write('# path\tshare-type\tpermission-type\tread\twrite\tcreate/delete\tdescription\n')
            for name in sorted(self.folders.keys()):
                v = self.folders[name]
                folders.write(('%(name)s\t%(styp)s\t%(ptyp)s\t%(ro_users)s\t%(rw_users)s\t%(cd_users)s\t%(desc)s' % dict(
                        name=name,
                        styp=v.share_type,
                        ptyp=v.permissions_type,
                        ro_users=','.join(v.read_users),
                        rw_users=','.join(v.write_users),
                        cd_users=','.join(v.create_delete_users),
                        desc=v.description,
                        )).strip() + '\n')
    # XXX: add write_mount functionality

    def write_permissions(self):
        with open(PERMISSIONS, 'w') as perm:
            perm.write('%s\n' % ','.join(self.users.keys()))
            for name in sorted(self.folders.keys()):
                vals = self.folders[name]
                perm.write('all:none:/%s/*\n' % name)
                seen = set()
                for user in vals.create_delete_users:
                    seen.add(user)
                    perm.write('%s:create:/%s/*\n' % (user, name))
                for user in vals.write_users:
                    if user in seen:
                        continue
                    seen.add(user)
                    perm.write('%s:write:/%s/*\n' % (user, name))
                for user in vals.read_users:
                    if user in seen:
                        continue
                    seen.add(user)
                    perm.write('%s:read:/%s/*\n' % (user, name))
            for name in sorted(self.files.keys()):
                vals = self.files[name]
                perm.write('all:none:/%s\n' % name)
                seen = set()
                for user in vals.write_users:
                    seen.add(user)
                    perm.write('%s:write:/%s\n' % (user, name))
                for user in vals.read_users:
                    if user in seen:
                        continue
                    seen.add(user)
                    perm.write('%s:read:/%s\n' % (user, name))

    def write_users(self):
        with open(USERS, 'w') as users:
            users.write('# user\tprivilege\n')
            for name in sorted(self.users.keys()):
                level = self.users[name].level
                users.write('%s\t%s\n' % (name, level))


# try umount for ssh
stop_sshfs = stop_smb

FS_ROOT = Path('/var/openerp/fnxfs')
ARCHIVE_ROOT = Path('/var/openerp/fnxfs_archive')
FNXFS_MOUNT = Path('/var/openerp/fnxfs.mount')
USERS = Path('/var/openerp/fnxfs.users')
FILES = Path('/var/openerp/fnxfs.files')
FOLDERS = Path('/var/openerp/fnxfs.folders')
PERMISSIONS = Path('/var/openerp/fnxfs.permissions')

OPENERP_IDS = getpwnam('openerp')[2:4]

SSHFS_OPTIONS = [
        '-o','allow_other',
        '-o','StrictHostKeyChecking=no',
        '-o','password_stdin',
        '-o','reconnect',
        '-o','compression=no',
        '-o','cache_timeout=0',
        '-o','ServerAliveInterval=5',
        '-o','workaround=rename',
        ]


Main()