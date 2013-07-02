# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Sync Server
#
# The Initial Developer of the Original Code is the Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2010
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#   Tarek Ziade (tarek@mozilla.com)
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisions above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****
import unittest
import time
from decimal import Decimal
from tempfile import mkstemp
import os

try:
    import pylibmc  # NOQA
except ImportError:
    MEMCACHED = False
else:
    MEMCACHED = True
    from syncstorage.storage.memcachedsql import MemcachedSQLStorage
    from syncstorage.storage.memcachedsql import QUOTA_RECALCULATION_PERIOD
    from syncstorage.storage.cachemanager import _KB

from nose import SkipTest

from syncstorage.storage import SyncStorage
from syncstorage.controller import _ONE_MEG

# This establishes the MOZSVC_UUID environment variable.
import syncstorage.tests.support  # NOQA

from services.util import BackendError, round_time
from services.config import Config
from services.pluginreg import load_and_configure

_UID = 1
_PLD = '*' * 500

# manual registration
if MEMCACHED:
    SyncStorage.register(MemcachedSQLStorage)


class TestMemcachedSQLStorage(unittest.TestCase):

    STORAGE_CONFIG = {
        'use_quota': True,
        'quota_size': 5120,
        'create_tables': True,
    }

    def setUp(self):
        if not MEMCACHED:
            raise SkipTest

        # Ensure we have heka loaded so the timers will work.
        config_file = os.path.join(os.path.dirname(__file__), "sync.conf")
        config = Config(cfgfile=config_file)
        load_and_configure(config, "heka_loader")

        fd, self.dbfile = mkstemp()
        os.close(fd)

        self.fn = 'syncstorage.storage.memcachedsql.MemcachedSQLStorage'

        kwds = self.STORAGE_CONFIG.copy()
        kwds['sqluri'] = 'sqlite:///%s' % self.dbfile
        self.storage = SyncStorage.get(self.fn, **kwds)

        # make sure we have the standard collections in place

        for name in ('client', 'crypto', 'forms', 'history'):
            self.storage.set_collection(_UID, name)

    def tearDown(self):
        self.storage.cache.flush_all()
        self.storage.delete_user(_UID)
        if os.path.exists(self.dbfile):
            os.remove(self.dbfile)

    def _is_up(self):
        try:
            self.storage.cache.set('test', 1)
        except BackendError:
            return False
        return self.storage.cache.get('test') == 1

    def test_basic(self):
        if not self._is_up():
            raise SkipTest
        # just make sure calls goes through
        self.storage.set_user(_UID, email='tarek@ziade.org')
        self.storage.set_collection(_UID, 'col1')
        self.storage.set_item(_UID, 'col1', '1', payload=_PLD)

        # these calls should be cached
        res = self.storage.get_item(_UID, 'col1', '1')
        self.assertEquals(res['payload'], _PLD)

        # this should remove the cache
        self.storage.delete_items(_UID, 'col1')
        items = self.storage.get_items(_UID, 'col1')
        self.assertEquals(len(items), 0)

    def test_meta_global(self):
        if not self._is_up():
            raise SkipTest
        self.storage.set_user(_UID, email='tarek@ziade.org')
        self.storage.set_collection(_UID, 'meta')
        self.storage.set_item(_UID, 'meta', 'global', payload=_PLD)

        # these calls should be cached
        res = self.storage.get_item(_UID, 'meta', 'global')
        self.assertEquals(res['payload'], _PLD)

        # we should find in the cache these items:
        #   - the "global" wbo for the "meta" collection
        #   - the size of all wbos
        if self._is_up():
            meta = self.storage.cache.get('1:meta:global')
            self.assertEquals(meta['id'], 'global')
            size = self.storage.cache.get('1:size')
            self.assertEquals(size, len(_PLD))

        # this should remove the cache for meta global
        self.storage.delete_item(_UID, 'meta', 'global')

        if self._is_up():
            meta = self.storage.cache.get('1:meta:global')
            self.assertEquals(meta, None)
            size = self.storage.cache.get('1:size')
            self.assertEquals(size, len(_PLD))

        # let's store some items in the meta collection
        # and checks that the global object is uploaded
        items = [{'id': 'global', 'payload': 'xyx'},
                {'id': 'other', 'payload': 'xxx'},
                ]
        self.storage.set_items(_UID, 'meta', items)

        if self._is_up():
            global_ = self.storage.cache.get('1:meta:global')
            self.assertEquals(global_['payload'], 'xyx')

        # this should remove the cache
        self.storage.delete_items(_UID, 'meta')
        items = self.storage.get_items(_UID, 'col')
        self.assertEquals(len(items), 0)

        if self._is_up():
            meta = self.storage.cache.get('1:meta:global')
            self.assertEquals(meta, None)

    def test_tabs(self):
        if not self._is_up():  # no memcached == no tabs
            raise SkipTest

        self.storage.set_user(_UID, email='tarek@ziade.org')
        self.storage.set_collection(_UID, 'tabs')
        self.storage.set_item(_UID, 'tabs', '1', payload=_PLD)

        # these calls should be cached
        res = self.storage.get_item(_UID, 'tabs', '1')
        self.assertEquals(res['payload'], _PLD)
        tabs = self.storage.cache.get('1:tabs')
        self.assertEquals(tabs['1']['payload'], _PLD)

        # this should remove the cache
        self.storage.delete_item(_UID, 'tabs', '1')
        tabs = self.storage.cache.get('1:tabs')
        self.assertFalse('1' in tabs)

        #  adding some stuff
        items = [{'id': '1', 'payload': 'xxx'},
                {'id': '2', 'payload': 'xxx'}]
        self.storage.set_items(_UID, 'tabs', items)
        tabs = self.storage.cache.get('1:tabs')
        self.assertEquals(len(tabs), 2)

        # this should remove the cache
        self.storage.delete_items(_UID, 'tabs')
        items = self.storage.get_items(_UID, 'tabs')
        self.assertEquals(len(items), 0)
        tabs = self.storage.cache.get('1:tabs')
        self.assertEquals(tabs, {})

    def test_size(self):
        # make sure we get the right size
        if not self._is_up():  # no memcached == no size
            raise SkipTest

        # storing 2 WBOs
        self.storage.set_user(_UID, email='tarek@ziade.org')
        self.storage.set_collection(_UID, 'tabs')
        self.storage.set_collection(_UID, 'foo')
        self.storage.set_item(_UID, 'foo', '1', payload=_PLD)
        self.storage.set_item(_UID, 'tabs', '1', payload=_PLD)

        # value in KB (around 1K)
        wanted = len(_PLD) * 2 / 1024.
        self.assertEquals(self.storage.get_total_size(_UID), wanted)

        # removing the size in memcache to check that we
        # get back the right value
        self.storage.cache.delete('%d:size' % _UID)
        self.assertEquals(self.storage.get_total_size(_UID), wanted)

        # adding an item should increment the cached size.
        self.storage.set_item(_UID, 'foo', '2', payload=_PLD)
        wanted += len(_PLD) / 1024.
        self.assertEquals(self.storage.get_total_size(_UID), wanted)

        # if we suffer a cache clear, then get_size_left should not
        # fall back to the database, while get_total_size should.
        quota_size = self.storage.quota_size
        self.storage.cache.delete('%d:size' % _UID)
        self.assertEquals(self.storage.get_size_left(_UID), quota_size)
        self.assertEquals(self.storage.get_total_size(_UID), wanted)
        # that should have re-populated the cache.
        self.assertEquals(self.storage.get_size_left(_UID),
                          quota_size - wanted)

    def test_collection_stamps(self):
        if not self._is_up():
            return

        self.storage.set_user(_UID, email='tarek@ziade.org')
        self.storage.set_collection(_UID, 'tabs')
        self.storage.set_collection(_UID, 'foo')
        self.storage.set_collection(_UID, 'baz')

        self.storage.set_item(_UID, 'tabs', '1', payload=_PLD * 200)
        self.storage.set_item(_UID, 'foo', '1', payload=_PLD * 200)

        stamps = self.storage.get_collection_timestamps(_UID)  # pump cache
        if self._is_up():
            cached_stamps = self.storage.cache.get('1:stamps')
            self.assertEquals(stamps['tabs'], cached_stamps['tabs'])

        stamps2 = self.storage.get_collection_timestamps(_UID)
        self.assertEquals(len(stamps), len(stamps2))
        if self._is_up():
            self.assertEquals(len(stamps), 2)
        else:
            self.assertEquals(len(stamps), 1)

        # checking the stamps
        if self._is_up():
            stamps = self.storage.cache.get('1:stamps')
            keys = stamps.keys()
            keys.sort()
            self.assertEquals(keys, ['foo', 'tabs'])

        # adding a new item should modify the stamps cache
        now = round_time()
        self.storage.set_item(_UID, 'baz', '2', payload=_PLD * 200,
                              storage_time=now)

        # checking the stamps
        if self._is_up():
            stamps = self.storage.cache.get('1:stamps')
            self.assertEqual(stamps['baz'], now)

        stamps = self.storage.get_collection_timestamps(_UID)
        if self._is_up():
            _stamps = self.storage.cache.get('1:stamps')
            keys = _stamps.keys()
            keys.sort()
            self.assertEquals(keys, ['baz', 'foo', 'tabs'])

        # deleting the item should also update the stamp
        time.sleep(0.2)    # to make sure the stamps differ
        now = round_time()
        cached_size = self.storage.cache.get('1:size')
        self.storage.delete_item(_UID, 'baz', '2', storage_time=now)
        stamps = self.storage.get_collection_timestamps(_UID)
        self.assertEqual(stamps['baz'], now)

        # that should have left the cached size alone.
        self.assertEquals(self.storage.cache.get('1:size'), cached_size)

        # until we force it to be recalculated.
        size = self.storage.get_collection_sizes(1)
        self.assertEqual(self.storage.cache.get('1:size') / 1024.,
                         sum(size.values()))

    def test_collection_sizes(self):
        if not self._is_up():  # no memcached
            return

        fd, dbfile = mkstemp()
        os.close(fd)

        kw = {'sqluri': 'sqlite:///%s' % dbfile,
              'use_quota': True,
              'quota_size': 5120,
              'create_tables': True}

        try:
            storage = SyncStorage.get(self.fn, **kw)

            # setting the tabs in memcache
            tabs = {'mCwylprUEiP5':
                    {'payload': '*' * 1024,
                    'id': 'mCwylprUEiP5',
                    'modified': Decimal('1299142695.76')}}
            storage.cache.set_tabs(1, tabs)
            size = storage.get_collection_sizes(1)
            self.assertEqual(size['tabs'], 1.)
        finally:
            os.remove(dbfile)

    def test_flush_all(self):
        if not self._is_up():
            return
        # just make sure calls goes through
        self.storage.set_user(_UID, email='tarek@ziade.org')
        self.storage.set_collection(_UID, 'col1')
        self.storage.set_item(_UID, 'col1', '1', payload=_PLD)

        # these calls should be cached
        res = self.storage.get_item(_UID, 'col1', '1')
        self.assertEquals(res['payload'], _PLD)

        # this should remove the cache for that collection.
        self.storage.delete_items(_UID, 'col1')
        items = self.storage.get_items(_UID, 'col1')
        self.assertEquals(len(items), 0)

        # populate it again, along with some data that gets
        # special treatment by memcache.
        self.storage.set_item(_UID, 'col1', '1', payload=_PLD)
        self.storage.set_item(_UID, 'col1', '2', payload=_PLD)
        self.storage.set_item(_UID, 'col1', '3', payload=_PLD)
        self.storage.set_item(_UID, 'meta', 'global', payload=_PLD)
        self.storage.set_item(_UID, 'tabs', 'home', payload=_PLD)

        items = self.storage.get_items(_UID, 'col1')
        self.assertEquals(len(items), 3)

        self.storage.delete_storage(_UID)
        items = self.storage.get_items(_UID, 'col1')
        self.assertEquals(len(items), 0)
        items = self.storage.get_items(_UID, 'meta')
        self.assertEquals(len(items), 0)
        items = self.storage.get_items(_UID, 'tabs')
        self.assertEquals(len(items), 0)

        stamps = self.storage.get_collection_timestamps(_UID)
        self.assertEquals(len(stamps), 0)

    def test_get_max_timestamp_of_empty_collection(self):
        if not self._is_up():
            return
        # This tests for the error behind Bug 693893.
        # Max timestamp for an empty collection should be None.
        ts = self.storage.get_collection_max_timestamp(_UID, "meta")
        self.assertEquals(ts, None)

    def test_recalculation_of_cached_quota_usage(self):
        if not self._is_up():
            return
        storage = self.storage
        sqlstorage = self.storage.sqlstorage

        # Create a large BSO, to ensure that it's close to quota size.
        payload_size = storage.quota_size - _ONE_MEG + 1
        payload = "X" * int(payload_size * _KB)

        # After writing it, size in memcached and sql should be the same.
        storage.set_item(_UID, 'foo', '1', payload=payload)
        self.assertEquals(sqlstorage.get_total_size(_UID), payload_size)
        self.assertEquals(storage.get_total_size(_UID, recalculate=True),
                          payload_size)

        # Deleting the BSO in the database won't adjust the cached size.
        sqlstorage.delete_item(_UID, 'foo', '1')
        self.assertEquals(sqlstorage.get_total_size(_UID), 0)
        self.assertEquals(storage.get_total_size(_UID, recalculate=True),
                          payload_size)

        # Adjust the cache to pretend that hasn't been recalculated lately.
        last_recalc_key = str(_UID) + ":size:ts"
        last_recalc = storage.cache.get(last_recalc_key)
        last_recalc -= QUOTA_RECALCULATION_PERIOD + 1
        storage.cache.set(last_recalc_key, last_recalc)

        # Now it should recalculate when asked for the size.
        self.assertEquals(sqlstorage.get_total_size(_UID), 0)
        self.assertEquals(storage.get_total_size(_UID, False),
                          payload_size)
        self.assertEquals(storage.get_total_size(_UID, True), 0)



# This tests the MirroredCacheManager functionality by double-writing to
# the same memcache instance.  It's much easier than arranging for two
# memcache servers to be present, but it means that sizes can get incremeted
# twice.  So we have to disable a couple of tests.

class TestMirroredMemcachedSQLStorage(TestMemcachedSQLStorage):

    STORAGE_CONFIG = {
        'use_quota': True,
        'quota_size': 5120,
        'create_tables': True,
        'cache_servers': ['localhost:11211'],
        'mirrored_cache_servers': ['localhost:11211'],
    }

    def test_meta_global(self):
        pass

    def test_size(self):
        pass


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(TestMemcachedSQLStorage))
    suite.addTest(unittest.makeSuite(TestMirroredMemcachedSQLStorage))
    return suite

if __name__ == "__main__":
    unittest.main(defaultTest="test_suite")
