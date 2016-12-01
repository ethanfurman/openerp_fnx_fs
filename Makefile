INSTALL_DIR= /usr/local/sbin

help:
	@echo "install-server" - installs fnxfs
	@echo "install-client" - installs fnxfs/fnxfsd
	@echo "uninstall"      - remove installed components
	@echo ---
	@echo NB: Do not run both installs on the same machine

install: help

install-server:
	cp server/fnxfs /usr/local/sbin/fnxfs
	chown root: /usr/local/sbin/fnxfs
	chmod 6755 /usr/local/sbin/fnxfs

install-client:
	cp client/fnxfs /usr/local/bin/fnxfs
	cp client/fnxfsd /usr/local/sbin/fnxfsd
	chown root: /usr/local/bin/fnxfs /usr/local/sbin/fnxfsd
	chmod 755 /usr/local/bin/fnxfs
	chmod 740 /usr/local/sbin/fnxfsd

uninstall:
	-rm /usr/local/bin/fnxfs 2> /dev/null || true
	-rm /usr/local/sbin/fnxfs 2> /dev/null || true
	-rm /usr/local/sbin/fnxfsd 2> /dev/null || true
	
