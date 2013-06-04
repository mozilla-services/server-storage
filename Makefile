APPNAME = server-storage
DEPS = server-core
CHANNEL = dev
VIRTUALENV = virtualenv
NOSE = bin/nosetests -s --with-xunit
TESTS = syncstorage/tests
PYTHON = bin/python
EZ = bin/easy_install
COVEROPTS = --cover-html --cover-html-dir=html --with-coverage --cover-package=keyexchange
COVERAGE = bin/coverage
PYLINT = bin/pylint
PKGS = syncstorage
EZOPTIONS = -U -i $(PYPI)
PYPI = http://pypi.python.org/simple
PYPI2RPM = bin/pypi2rpm.py --index=$(PYPI)
PYPIOPTIONS = -i $(PYPI)
BUILDAPP = bin/buildapp
BUILDRPMS = bin/buildrpms
BUILD_TMP = /tmp/server-storage-build.${USER}
PYPI = http://pypi.python.org/simple
PYPI2RPM = bin/pypi2rpm.py --index=$(PYPI)
PYPIOPTIONS = -i $(PYPI)
CHANNEL = dev
RPM_CHANNEL = prod
INSTALL = bin/pip install
INSTALLOPTIONS = -U -i $(PYPI)

ifdef PYPIEXTRAS
	PYPIOPTIONS += -e $(PYPIEXTRAS)
	INSTALLOPTIONS += -f $(PYPIEXTRAS)
endif

ifdef PYPISTRICT
	PYPIOPTIONS += -s
	ifdef PYPIEXTRAS
		HOST = `python -c "import urlparse; print urlparse.urlparse('$(PYPI)')[1] + ',' + urlparse.urlparse('$(PYPIEXTRAS)')[1]"`

	else
		HOST = `python -c "import urlparse; print urlparse.urlparse('$(PYPI)')[1]"`
	endif

endif

INSTALL += $(INSTALLOPTIONS)

.PHONY: all build test cover build_rpms mach update

all:	build

build:
	$(VIRTUALENV) --no-site-packages --distribute .
	$(INSTALL) Distribute
	$(INSTALL) MoPyTools
	$(INSTALL) nose
	$(INSTALL) coverage
	$(INSTALL) WebTest
	$(BUILDAPP) -c $(CHANNEL) $(PYPIOPTIONS) $(DEPS)
	# py-scrypt doesn't play nicely with pypi2rpm
	# so we can't list it in the requirements files.
	mkdir -p ${BUILD_TMP}
	cd ${BUILD_TMP}; tar -xzvf $(CURDIR)/upstream-deps/py-scrypt-0.6.0.tar.gz
	$(INSTALL) ${BUILD_TMP}
	rm -rf ${BUILD_TMP}

update:
	$(BUILDAPP) -c $(CHANNEL) $(PYPIOPTIONS) $(DEPS)

test:
	$(NOSE) $(TESTS)

cover:
	$(NOSE) --with-coverage --cover-html --cover-package=syncstorage $(TESTS)

build_rpms:
	rm -rf rpms
	mkdir -p ${BUILD_TMP}
	$(BUILDRPMS) -c $(RPM_CHANNEL) $(PYPIOPTIONS) $(DEPS)
	# py-scrypt doesn't play nicely with pypi2rpm.
	cd ${BUILD_TMP}; tar -xzvf $(CURDIR)/upstream-deps/py-scrypt-0.6.0.tar.gz
	cd ${BUILD_TMP}; python setup.py  --command-packages=pypi2rpm.command bdist_rpm2 --binary-only --name=python26-scrypt --dist-dir=$(CURDIR)/rpms
	# PyMySQL doesn't play nicely with gevent timeouts.
	# Patch it to fix, until the fix gets in upstream.
	#   https://github.com/petehunt/PyMySQL/pull/148
	# The PyPI SSL certificate is wonky, so check md5sum of file by hand.
	wget -O ${BUILD_TMP}/PyMySQL-0.5.tar.gz --no-check-certificate https://pypi.python.org/packages/source/P/PyMySQL/PyMySQL-0.5.tar.gz
	if [ `md5sum ${BUILD_TMP}/PyMySQL-0.5.tar.gz | cut -d ' ' -f 1` != '125e8a3449e05afcb04874a19673426b' ]; then false; fi
	cd ${BUILD_TMP}; tar -xzvf PyMySQL-0.5.tar.gz
	patch ${BUILD_TMP}/PyMySQL-0.5/pymysql/cursors.py ./upstream-deps/pymysql-no-bare-except-clauses.patch
	cd ${BUILD_TMP}/PyMySQL-0.5; python setup.py  --command-packages=pypi2rpm.command bdist_rpm2 --binary-only --name=python26-pymysql --dist-dir=$(CURDIR)/rpms
	# Meliae doesn't play nicely with pypi2rpm.
	# It also eneds to be patched to work with ctypes.
	# Ergo, we have to build it by hand.
	$(INSTALL) cython
	wget -O ${BUILD_TMP}/meliae-0.4.0.tar.gz https://launchpad.net/meliae/trunk/0.4/+download/meliae-0.4.0.tar.gz
	cd ${BUILD_TMP}; tar -xzvf meliae-0.4.0.tar.gz
	patch ${BUILD_TMP}/meliae-0.4.0/meliae/_scanner_core.c ./upstream-deps/meliae-scanner-assertion-fix.patch
	$(INSTALL) ${BUILD_TMP}/meliae-0.4.0
	cd ${BUILD_TMP}/meliae-0.4.0; python setup.py  --command-packages=pypi2rpm.command bdist_rpm2 --binary-only --name=python26-meliae --dist-dir=$(CURDIR)/rpms
	rm -rf ${BUILD_TMP}

mock: build build_rpms
	mock init
	mock --install python26 python26-setuptools
	cd rpms; wget http://mrepo.mozilla.org/mrepo/5-x86_64/RPMS.mozilla-services/libmemcached-devel-0.50-1.x86_64.rpm
	cd rpms; wget http://mrepo.mozilla.org/mrepo/5-x86_64/RPMS.mozilla-services/libmemcached-0.50-1.x86_64.rpm
	cd rpms; wget http://mrepo.mozilla.org/mrepo/5-x86_64/RPMS.mozilla-services/gunicorn-0.11.2-1moz.x86_64.rpm
	cd rpms; wget http://mrepo.mozilla.org/mrepo/5-x86_64/RPMS.mozilla/nginx-0.7.65-4.x86_64.rpm
	mock --install rpms/*
	mock --chroot "python2.6 -m syncstorage.run"
