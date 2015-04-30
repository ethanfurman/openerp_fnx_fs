from __future__ import print_function
from antipathy import Path
from openerplib import get_connection, get_records, AttrDict
from random import sample
from scription import Execute
from string import ascii_letters
from time import sleep
from unittest import TestCase, main


class TestFnxFS(TestCase):

    def test_consumer_create_virtual_folder_fails(self):
        pass

    def test_consumer_create_mirror_folder_fails(self):
        pass

    def test_consumer_create_shared_folder_succeeds(self):
        pass

    def test_creator_create_virtual_folder_succeeds(self):
        pass

    def test_creator_create_mirror_folder_fails(self):
        pass

    def test_creator_create_shared_folder_succeeds(self):
        pass

    def test_manager_create_virtual_folder_succeeds(self):
        pass

    def test_manager_create_mirror_folder_succeeds(self):
        pass

    def test_manager_create_shared_folder_succeeds(self):
        pass

    def test_consumer_create_file_fails(self):
        self.assertRaises(Exception, create_file, consumer1, 'some_file.txt', 'test_virtual')

    def test_creator_create_file__succeeds(self):
        pass

    def test_manager_create_file_succeeds(self):
        pass

    def test_consumer_no_access_list_fails(self):
        pass

    def test_consumer_no_access_read_fails(self):
        pass

    def test_consumer_no_access_write_fails(self):
        pass

    def test_creator_no_access_list_fails(self):
        pass

    def test_creator_no_access_read_fails(self):
        pass

    def test_creator_no_access_write_fails(self):
        pass

    def test_manager_no_access_list_fails(self):
        pass

    def test_manager_no_access_read_fails(self):
        pass

    def test_manager_no_access_write_fails(self):
        pass

    def test_consumer_read_access_list_succeeds(self):
        pass

    def test_consumer_read_access_read_succeeds(self):
        pass

    def test_consumer_read_access_write_fails(self):
        pass

    def test_creator_read_access_list_succeeds(self):
        pass

    def test_creator_read_access_read_succeeds(self):
        pass

    def test_creator_read_access_write_fails(self):
        pass

    def test_manager_read_access_list_succeeds(self):
        pass

    def test_manager_read_access_read_succeeds(self):
        pass

    def test_manager_read_access_write_fails(self):
        pass



def login(user):
    'return an OE instance for USER'
    OE = AttrDict()
    OE.conn = get_connection(hostname=config.openerp, database=config.database, login=user.login, password=user.password)

def create_file(user, file, folder, share_as=None, permission_type=None, read_users=None, write_users=None, note=None):
    params = ['fnxfsd', 'create-file', file, folder]
    if share_as:
        params.append('--share-as=%s' % share_as)
    if permission_type:
        params.append('--permissions=%s' % permission_type)
    if read_users:
        params.append('--read_users=%s' % ','.join(read_users))
    if write_users:
        params.append('--write_users=%s' % ','.join(write_users))
    if note:
        params.append('--note=%r' % note)
    params.append('--as-user=%s' % user.login)
    attempt = Execute(params)
    print('stdout:', attempt.stdout)
    print('stderr:', attempt.stderr)
    print('rtncd: ', attempt.returncode)
    if attempt.returncode:
        raise Exception('need better failure message')
    else:
        return True


# def create_folder(user, folder, type=None, description=None, parent=None, collaborative=False, readonly_users=[], readedit_users=[]):
#     params = [folder]
# 
#     attempt = Execute('fnxfsd create-folder %s')

host = '192.168.2.244'
dbse = 'wholeherb'
user = 'admin'
pswd = 'fnx243tu'

conn = get_connection(hostname=host, database=dbse, login=user, password=pswd)
res = AttrDict()
res.groups = conn.get_model('res.groups')
res.users = conn.get_model('res.users')

fnxfs = AttrDict()
[consumer] = get_records(conn, 'ir.model.data', domain=[('module','=','fnx_fs'),('model','=','res.groups'),('name','=','consumer')])
[creator] = get_records(conn, 'ir.model.data', domain=[('module','=','fnx_fs'),('model','=','res.groups'),('name','=','creator')])
[manager] = get_records(conn, 'ir.model.data', domain=[('module','=','fnx_fs'),('model','=','res.groups'),('name','=','manager')])
[fnxfs.consumer] = get_records(res.groups, domain=[('id','=',consumer.res_id)])
[fnxfs.creator] = get_records(res.groups, domain=[('id','=',creator.res_id)])
[fnxfs.manager] = get_records(res.groups, domain=[('id','=',manager.res_id)])
fnxfs.file = conn.get_model('fnx.fs.file')
fnxfs.folder = conn.get_model('fnx.fs.folder')

folders = []

passwords = {
    'consumer1': ''.join(sample(ascii_letters, 10)),
    'consumer2': ''.join(sample(ascii_letters, 10)),
    'creator1':  ''.join(sample(ascii_letters, 10)),
    'creator2':  ''.join(sample(ascii_letters, 10)),
    'manager1':  ''.join(sample(ascii_letters, 10)),
    'manager2':  ''.join(sample(ascii_letters, 10)),
    }

consumer1 = AttrDict(name='FnxFS Test Consumer 1', login='fnxfs_consumer1', password=passwords['consumer1'], groups_id=[(4, fnxfs.consumer.id)])
consumer2 = AttrDict(name='FnxFS Test Consumer 2', login='fnxfs_consumer2', password=passwords['consumer2'], groups_id=[(4, fnxfs.consumer.id)])
creator1 = AttrDict(name='FnxFS Test Creator 1', login='fnxfs_creator1', password=passwords['creator1'], groups_id=[(4, fnxfs.creator.id)])
creator2 = AttrDict(name='FnxFS Test Creator 2', login='fnxfs_creator2', password=passwords['creator2'], groups_id=[(4, fnxfs.creator.id)])
manager1 = AttrDict(name='FnxFS Test Manager 1', login='fnxfs_manager1', password=passwords['manager1'], groups_id=[(4, fnxfs.manager.id)])
manager2 = AttrDict(name='FnxFS Test Manager 2', login='fnxfs_manager2', password=passwords['manager2'], groups_id=[(4, fnxfs.manager.id)])



def setup():
    for user in (consumer1, consumer2, creator1, creator2, manager1, manager2):
        print('creating user', user.name)
        if not Path('/home/%s' % user.login).exists():
            Path.mkdir('/home/%s' % user.login)
            Path.mkdir('/home/.shadow/%s' % user.login)
            Path.symlink('/home/.shadow/%s/FnxFS' % user.login, '/home/%s/FnxFS' % user.login)
        user.id = res.users.create(dict(user))
    folders.append(fnxfs.folder.create({'name':'test_virtual', 'readonly_type':'all', 'share_owner_id':1}))
    raw_input("... I'm waiting! ...")

def takedown():
    for user in (consumer1, consumer2, creator1, creator2, manager1, manager2):
        Path.rmdir('/home/.shadow/%s' % user.login)
        Path.unlink('/home/%s/FnxFS' % user.login)
        Path.rmdir('/home/%s' % user.login)
        if 'id' in user:
            print('removing user', user.name)
            user.id = res.users.unlink([user.id])
    if folders:
        fnxfs.folder.unlink(folders)

# TODO: fix auto-symlinking to /home/.shadow/[user]/FnxFS
#       fix fs.py using owner instead of logged in user when trying to locate files
#       fix unique file names to use path as well as filename
#       double-check that files in the user's home dir can be shared

if __name__== '__main__':
    try:
        setup()
        main()
    except:
        takedown()
        raise
