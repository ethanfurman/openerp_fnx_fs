Installing FnxFS
================


On the Server
-------------

The server needs to have the server fnxfs script and suid-python binary
installed, and the tree created for storing the shared files and the
archive of the shared files::

  - /usr/local/sbin/suid-python
  - /usr/local/sbin/fnxfs

  - /var/openerp
  - /var/openerp/fnxfs (mode: 6755)
  - /var/openerp/fnxfs_archive

The supporting files are::

  - /etc/openerp/fnx.ini [1]

  - /var/openerp/fnxfs.files
  - /var/openerp/fnxfs.folders
  - /var/openerp/fnxfs.mount
  - /var/openerp/fnxfs.permissions

All (except the first) should be created automatically by fnxfs.


On the Client
-------------

Similarly to the server, the client also needs the suid-python binary
installed, along with the client fnxfs script, the fnxfsd script, and
the startup fnxfsd.py script (along with a symlink to it)::

  - /usr/local/sbin/suid-python
  - /usr/local/bin/fnxfs (mode: 6755)
  - /usrlocal/sbin/fnxfsd
  - /usr/local/etc/init.d/fnxfsd.py
  - /etc/init.d/fnxfsd.py -> /usr/local/etc/init.d/fnxfsd.py

The supporting files/folders are::

  - /usr/local/etc/fnxfs_credentials [2]
  - /home/.shadow [3]


Foot notes
----------

1.  `fnx.ini` should have a section that looks like::

    [fnxfsd]
    server_root = '...'
    server_user = 'openerp'
    server_pass = '...'
    openerp = 'ip.address'


2.  The contents of `fnxfs_credentials`::

    root = '...'            # root password for this machine (in quotes)
    server_user = 'root'
    server_pass = '...'     # root password for server user (in quotes)
    openerp = '...'         # ip address of openerp server (in quotes)

3.  The .shadow folder will be created when `fnxfs sweep` is run for the
    first time, or `fnxfsd` is run the first time.
