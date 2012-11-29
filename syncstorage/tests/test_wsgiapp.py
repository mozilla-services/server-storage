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
#   Ryan Kelly (rkelly@mozilla.com)
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
import os

from webtest import TestApp

from syncstorage import wsgiapp

# This establishes the MOZSVC_UUID environment variable.
import syncstorage.tests.support  # NOQA


class FakeMemcacheClient(object):

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key, None)

    def set(self, key, value):
        self.values[key] = value


class TestWSGIApp(unittest.TestCase):

    def setUp(self):
        config_file = os.path.join(os.path.dirname(__file__), "sync.conf")
        config_dict = {"configuration": "file:" + config_file}
        self.app = wsgiapp.make_app(config_dict).app

    def tearDown(self):
        for storage in self.app.storages.itervalues():
            sqlfile = storage.sqluri.split('sqlite:///')[-1]
            if os.path.exists(sqlfile):
                os.remove(sqlfile)

    def test_host_specific_config(self):
        class request:
            host = "localhost"
        sqluri = self.app.get_storage(request).sqluri
        assert sqluri.startswith("sqlite:////tmp/test-sync-storage")

        request.host = "some-test-host"
        sqluri = self.app.get_storage(request).sqluri
        assert sqluri.startswith("sqlite:////tmp/test-storage-host1")

        request.host = "another-test-host"
        sqluri = self.app.get_storage(request).sqluri
        assert sqluri.startswith("sqlite:////tmp/test-storage-host2")

    def test_dependant_options(self):
        config = dict(self.app.config)
        config['storage.check_node_status'] = True
        old_client = wsgiapp.Client
        wsgiapp.Client = None
        # make sure the app cannot be initialized if it's asked
        # to check node status and memcached is not present
        try:
            self.assertRaises(ValueError, wsgiapp.make_app, config)
        finally:
            wsgiapp.Client = old_client

    def test_checking_node_status_in_memcache(self):
        app = self.app
        app.cache = FakeMemcacheClient()
        app.check_node_status = True
        testclient = TestApp(self.app, extra_environ={
            "HTTP_HOST": "some-test-host",
        })

        # With no node data in memcache, requests to known nodes should
        # succeed while requests to unknown nodes should fail.
        testclient.get("/__heartbeat__", headers={"Host": "some-test-host"},
                       status=200)
        testclient.get("/__heartbeat__", headers={"Host": "unknown-host"},
                       status=503)

        # Marking the node as "backoff" will succeed, but send backoff header.
        app.cache.set("status:some-test-host", "backoff")
        r = testclient.get("/__heartbeat__", status=200)
        self.assertEquals(r.headers["X-Weave-Backoff"], str(app.retry_after))

        app.cache.set("status:some-test-host", "backoff:100")
        r = testclient.get("/__heartbeat__", status=200)
        self.assertEquals(r.headers["X-Weave-Backoff"], "100")

        # Marking the node as "down", "draining" or "unhealthy" will result
        # in a 503 response with backoff header.
        app.cache.set("status:some-test-host", "down")
        r = testclient.get("/__heartbeat__", status=503)
        self.assertEquals(r.headers["X-Weave-Backoff"], str(app.retry_after))
        self.assertEquals(r.headers["Retry-After"], str(app.retry_after))

        app.cache.set("status:some-test-host", "draining")
        r = testclient.get("/__heartbeat__", status=503)
        self.assertEquals(r.headers["X-Weave-Backoff"], str(app.retry_after))
        self.assertEquals(r.headers["Retry-After"], str(app.retry_after))

        app.cache.set("status:some-test-host", "unhealthy")
        r = testclient.get("/__heartbeat__", status=503)
        self.assertEquals(r.headers["X-Weave-Backoff"], str(app.retry_after))
        self.assertEquals(r.headers["Retry-After"], str(app.retry_after))

        # A nonsense node status will be ignored.
        app.cache.set("status:some-test-host", "nonsensical-value")
        r = testclient.get("/__heartbeat__", status=200)
        self.assertTrue("X-Weave-Backoff" not in r.headers)

        # Node status only affects the node that it belongs to.
        app.cache.set("status:some-test-host", "unhealthy")
        r = testclient.get("/__heartbeat__",
                           headers={"Host": "another-test-host"},
                           status=200)
        self.assertTrue("X-Weave-Backoff" not in r.headers)
