from __future__ import print
from random import shuffle
from scription import Execute
from string import ascii_letters
from openerplib import get_connection, get_records, AttrDict

host = '192.168.11.16'
dbse = 'sunridgefarms'
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

passwords = {
    'consumer1': shuffle(ascii_letters, 10),
    'consumer2': shuffle(ascii_letters, 10),
    'creator1':  shuffle(ascii_letters, 10),
    'creator2':  shuffle(ascii_letters, 10),
    'manager1':  shuffle(ascii_letters, 10),
    'manager2':  shuffle(asciii_letters, 10),
    }

consumer1 = AttrDict(name='FnxFS Test Consumer 1', login='fnxfs_consumer1', password=passwords['consumer1'], groups_id=[(4, fnxfs.consumer.id)])
consumer2 = AttrDict(name='FnxFS Test Consumer 2', login='fnxfs_consumer2', password=passwords['consumer2'], groups_id=[(4, fnxfs.consumer.id)])
creator1 = AttrDict(name='FnxFS Test Creator 1', login='fnxfs_creator1', password=passwords['creator1'], groups_id=[(4, fnxfs.creator.id)])
creator2 = AttrDict(name='FnxFS Test Creator 2', login='fnxfs_creator2', password=passwords['creator2'], groups_id=[(4, fnxfs.creator.id)])
manager1 = AttrDict(name='FnxFS Test Manager 1', login='fnxfs_manager1', password=passwords['manager1'], groups_id=[(4, fnxfs.manager.id)])
manager2 = AttrDict(name='FnxFS Test Manager 2', login='fnxfs_manager2', password=passwords['manager2'], groups_id=[(4, fnxfs.manager.id)])

for user in (consumer1, consumer2, creator1, creator2, manager1, manager2):
    user.id = res.users.create(dict(user))


class TestFnxFS(TestCase):

    def test_consumer_create_virtual_folder_fails(self):
        OE = login(consumer1)
        self.assertRaises(Exception, create_folder
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
        pass

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

def create_folder(user, name, type='virtual', description=None, parent=None, collaborative=False, readonly_users=[], readedit_users=[]):
    pass
