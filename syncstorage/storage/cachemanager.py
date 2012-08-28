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
"""
Memcached + SQL backend

- User tabs are stored in one single "user_id:tabs" key
- The total storage size is stored in "user_id:size"
- The meta/global wbo is stored in "user_id"
- The info/collections timestamp mapping is stored in "user_id:stamps"
"""
import threading
import cPickle

from metlog.holder import CLIENT_HOLDER

from services.util import BackendError

from syncstorage.storage.sql import _KB
from syncstorage.mcclient import MemcachedClient

USER_KEYS = ('size', 'size:ts', 'meta:global', 'tabs', 'stamps')


def _key(*args):
    return ':'.join([str(arg) for arg in args])


class CacheManager(object):
    """ Helpers on the top of MemcachedClient class.
    """
    def __init__(self, *args, **kw):
        self._client = PicklingMemcachedClient(*args, **kw)
        # using a locker to avoid race conditions
        # when several clients for the same user
        # get/set the cached data
        self._locker = threading.RLock()

    @property
    def logger(self):
        return CLIENT_HOLDER.default_client

    def get(self, key):
        with self.logger.timer("syncstorage.storage.cachemanager.get"):
            return self._client.get(key)

    def delete(self, key):
        with self.logger.timer("syncstorage.storage.cachemanager.delete"):
            return self._client.delete(key)

    def incr(self, key, size=1):
        size = int(size)
        with self.logger.timer("syncstorage.storage.cachemanager.incr"):
            res = self._client.incr(key, size)
            if res is None:
                res = self._client.set(key, size)

    def set(self, key, value):
        with self.logger.timer("syncstorage.storage.cachemanager.set"):
            self._client.set(key, value)

    def get_set(self, key, func):
        res = self.get(key)
        if res is None:
            res = func()
            self.set(key, res)
        return res

    #
    # Tab managment
    #
    def get_tab(self, user_id, tab_id):
        tabs = self.get_tabs(user_id)
        if tabs is None:
            return None
        return tabs.get(tab_id)

    def get_tabs_size(self, user_id):
        """Returns the size of the tabs from memcached in KB"""
        tabs = self.get_tabs(user_id)
        size = sum([len(tab.get('payload', '')) for tab in tabs.values()])
        if size != 0:
            size = size / _KB
        return size

    def get_tabs_timestamp(self, user_id):
        """returns the max modified"""
        tabs_stamps = [tab.get('modified', 0)
                       for tab in self.get_tabs(user_id).values()]
        if len(tabs_stamps) == 0:
            return None
        return max(tabs_stamps)

    def _filter_tabs(self, tabs, filters):
        for field, value in filters.items():
            if field not in ('id', 'modified', 'sortindex'):
                continue

            operator, values = value

            # removing entries
            for tab_id, tab_value in tabs.items():
                if ((operator == 'in' and tab_id not in values) or
                    (operator == '>' and tab_value[field] <= values) or
                    (operator == '<' and tab_value[field] >= values)):
                    del tabs[tab_id]

    def get_tabs(self, user_id, filters=None):
        with self._locker:
            key = _key(user_id, 'tabs')
            tabs = self.get(key)
            if tabs is None:
                # memcached down ?
                tabs = {}
            if filters is not None:
                self._filter_tabs(tabs, filters)

        return tabs

    def set_tabs(self, user_id, tabs, merge=True):
        with self._locker:
            key = _key(user_id, 'tabs')
            if merge:
                existing_tabs = self.get(key)
                if existing_tabs is None:
                    existing_tabs = {}
            else:
                existing_tabs = {}
            for tab_id, tab in tabs.items():
                existing_tabs[tab_id] = tab
            self.set(key, existing_tabs)

    def delete_tab(self, user_id, tab_id):
        with self._locker:
            key = _key(user_id, 'tabs')
            tabs = self.get_tabs(user_id)
            if tab_id in tabs:
                del tabs[tab_id]
                self.set(key, tabs)
                return True
            return False

    def delete_tabs(self, user_id, filters=None):
        def _filter(tabs, filters, field, to_keep):
            operator, stamp = filters[field]
            if operator == '>':
                for tab_id, tab in list(tabs.items()):
                    if tab[field] <= stamp:
                        kept[tab_id] = tabs[tab_id]
            elif operator == '<':
                for tab_id, tab in list(tabs.items()):
                    if tab[field] >= stamp:
                        kept[tab_id] = tabs[tab_id]

        with self._locker:
            key = _key(user_id, 'tabs')
            kept = {}
            tabs = self.get(key)
            if tabs is None:
                # memcached down ?
                tabs = {}

            if filters is not None:
                if 'id' in filters:
                    operator, ids = filters['id']
                    if operator == 'in':
                        for tab_id in list(tabs.keys()):
                            if tab_id not in ids:
                                kept[tab_id] = tabs[tab_id]
                if 'modified' in filters:
                    _filter(tabs, filters, 'modified', kept)
                if 'sortindex' in filters:
                    _filter(tabs, filters, 'sortindex', kept)

            self.set(key, kept)
            return len(kept) < len(tabs)

    def tab_exists(self, user_id, tab_id):
        tabs = self.get_tabs(user_id)
        if tabs is None:
            # memcached down ?
            return None
        if tab_id in tabs:
            return tabs[tab_id]['modified']
        return None

    #
    # misc APIs
    #
    def flush_user_cache(self, user_id):
        """Removes all cached data."""
        for key in USER_KEYS:
            try:
                self.delete(_key(user_id, key))
            except BackendError:
                self.logger.error('Could not delete user cache (%s)' % key)

    #
    # total managment
    #
    def set_total(self, user_id, total):
        # we store the size in bytes in memcached
        total = int(total * _KB)
        key = _key(user_id, 'size')
        # if this fail it's not a big deal
        try:
            self.set(key, total)
        except BackendError:
            self.logger.error('Could not write to memcached')

    def get_total(self, user_id):
        try:
            total = self.get(_key(user_id, 'size'))
            if total != 0 and total is not None:
                total = total / _KB
        except BackendError:
            total = None
        return total


# These are the flags are used by pylibmc to determine how the
# stored data has been serialized.
MC_FLAG_NONE = 0
MC_FLAG_PICKLE = (1 << 0)
MC_FLAG_INTEGER = (1 << 1)
MC_FLAG_LONG = (1 << 2)
MC_FLAG_ZLIB = (1 << 3)
MC_FLAG_BOOL = (1 << 4)


class DefaultSerializer(object):
    """Default serializer object for PicklingMemcachedClient.

    Instances of this class provide dumps() and loads() method that use
    cPickle with protocol set to -1.
    """

    def dumps(self, value):
        return cPickle.dumps(value, -1)

    def loads(self, data):
        return cPickle.loads(data)


class PicklingMemcachedClient(MemcachedClient):
    """Memcached client that is compatible with pylibmc's pickling scheme.

    The pylibmc and python-memcached modules use a customized serialization
    scheme that stores strings and integers as simple values, but complex
    python types as pickled data.  The memcached "flags" value is used to
    differenciate between them.

    This subclasses adds matching functionality to our umemcache client.
    """

    def __init__(self, cache_servers, serializer=None, **kwds):
        if serializer is None:
            serializer = DefaultSerializer()
        self._serializer = serializer
        super(PicklingMemcachedClient, self).__init__(cache_servers, **kwds)

    def dumps(self, value):
        if isinstance(value, str):
            return value, MC_FLAG_NONE
        if isinstance(value, bool):
            return "1" if value else "0", MC_FLAG_BOOL
        if isinstance(value, int):
            return str(value), MC_FLAG_INTEGER
        if isinstance(value, long):
            return str(value), MC_FLAG_LONG
        return self._serializer.dumps(value), MC_FLAG_PICKLE

    def loads(self, data, flags):
        if flags & MC_FLAG_ZLIB:
            # We could support zlib-compressed data if necessary, but
            # I don't think it's used anywhere in our setup.
            raise BackendError("zlib-compressed data is not supported")
        if flags & MC_FLAG_NONE:
            return data
        if flags & MC_FLAG_PICKLE:
            return self._serializer.loads(data)
        if flags & MC_FLAG_INTEGER:
            return int(data)
        if flags & MC_FLAG_LONG:
            return long(data)
        if flags & MC_FLAG_BOOL:
            return bool(int(data))
        raise BackendError("Unknown serialization flag %d" % (flags,))
