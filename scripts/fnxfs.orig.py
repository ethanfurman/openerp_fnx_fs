#!/usr/local/bin/python
import os,glob
from commands import getstatusoutput
import pyinotify

class Identity(pyinotify.ProcessEvent):
    def process_default(self, event):
        if event.path <> event.pathname:
            if os.path.isfile(event.pathname):
                request = parameterize(event.pathname)
                fqRequest = qualify(request)
                import pdb; pdb.set_trace()
                os.rename(event.pathname,event.pathname.replace("/requests/","/priorrequests/"))


def on_loop(notifier):
    s_inst = notifier.proc_fun().nested_pevent()
    print repr(s_inst), '\n', s_inst, '\n'


wm = pyinotify.WatchManager()
s = pyinotify.Stats()
notifier = pyinotify.Notifier(wm, default_proc_fun=Identity(s), read_freq=5)
wm.add_watch('/var/oeshare/requests/', pyinotify.ALL_EVENTS, rec=True, auto_add=True)


def qualify(request):
    # Connect to sharing host, grep recent files for name match and confirm recent access to FQN
    # return None if not in result
    rcmd = '''/usr/bin/sshpass 
             -p "ftc42Sa" 
             /usr/bin/ssh root@%(ipaddr)s 
             /bin/grep %(source)s /home/%(user)s/.local/share/recently-used.xbel /home/%(user)s/.recently-used.xbel
             2>/dev/null
            ''' % request
    result = getstatusoutput(rcmd)[1]
    fname=request['source']
    request['fqsource'] = None
    if fname in result:
        startp = result.find('///')+1
        endp = result.find(fname)+len(fname)
        fqName = result[startp:endp]
        request['fqsource'] = fqName 


def parameterize(requestfile):
    data = [rec.strip() for rec in open(requestfile,'r').readlines() if rec.strip()]
    vals = [ ii for ii in data if "," not in ii ]
    perms = [ ii for ii in data if "," in ii ]
    result = dict((ii.split("=")) for ii in vals)
    result['permissions'] = D = {}
    for line in perms:
        shareto,permission = [ ii.split("=")[-1] for ii in line.split(",") ]
        D[shareto] = permission
    result['filenodes'] = filenodes = [ ii for ii in result['source'].split('/') if ii.strip() ]
    result['filename'] = filenodes[-1]
    return result


def makedirs(name,perms=0777):
    print "Name = '%s' (%s)" % (name,name.split("/")[1:-1])
    if not(name.endswith("/")):
        name = "/"+"/".join(name.split("/")[1:-1])
    print "    >= '%s' " % (name,)
    try:
        os.makedirs(name,perms)
    except:
        pass


def makeLink(srce,dest):
    print "--Linking %s to %s" % (srce,dest)
    result = getstatusoutput('/bin/ln -s "%s" "%s"' % (srce,dest))
    print result


def setPerms(target,user,permission):
    permgrp = 'fnxfsr'
    if permission in 'Ww':
        permgrp = 'fnxfsw'
    result = getstatusoutput('/bin/chown -h %s:%s "%s"' % (user,permgrp,target))
    #print '/bin/chown -h %s:%s "%s" \n%s' % (user,permgrp,target,result)
    #result = getstatusoutput('/bin/chmod %s "%s"' % (perms,target))
    #print '/bin/chmod %s "%s" \n%s"' % (perms,target,result)


def linkin(requestfile):
    PARAMS = parameterize(requestfile)
    makedirs("/mnt/oeshare/%(ipaddr)s/" % PARAMS)
    result = getstatusoutput("""/bin/echo ftc42Sa | \
         /usr/bin/sshfs -o allow_other \
        -o kernel_cache \
        -o StrictHostKeyChecking=no \
        -o auto_cache \
        -o reconnect \
        -o password_stdin \
        -o compression=no \
        -o cache_timeout=600 \
        -o ServerAliveInterval=15 \
        -o idmap=user \
        root@%(ipaddr)s:// /mnt/oeshare/%(ipaddr)s """ % PARAMS)
    #now link in the share
    srce = "/mnt/oeshare/%(ipaddr)s%(source)s" % PARAMS
    dest = "/var/oeshare/SHAREDBY/%(user)s%(filename)s" % PARAMS
    makedirs(srce)
    makedirs(dest)
    makeLink(srce,dest)
    #
    targetsrce = '/mnt/oeshare/%(ipaddr)s%(source)s' % PARAMS
    for user,permission in PARAMS['permissions'].items():
        PARAMS['user'] = user
        targetdest = '/var/oeshare/SHAREDTO/%(user)s%(target)s%(filename)s' % PARAMS
        if PARAMS['target'].strip():
            makedirs(targetsrce)
            makedirs(targetdest)
            makeLink(targetsrce,targetdest)
            setPerms(targetdest,user,permission)


for requestfile in glob.glob("/var/oeshare/fqRequests/*"):
    linkin(requestfile)


from fs.osfs import OSFS
fs = OSFS('/var/oeshare/SHAREDTO')
from fs.expose import fuse
dummy = getstatusoutput('/bin/umount /var/oeshare/sharedto')     #to ensure it can be cleanly mounted
mp = fuse.mount(fs,"/var/oeshare/sharedto",nonempty=True)

notifier.loop(callback=on_loop,daemonize=False)  # Note: daemonizing forks the process and exits python
