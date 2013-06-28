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
Load test for the Storage server
"""
import os
import base64
import random
import time

from loads import TestCase
VERSION = '1.1'

# The collections to operate on.
# Each operation will randomly select a collection from this list.
# The "tabs" collection is not included since it uses memcache; we need
# to figure out a way to test it without overloading the server.
collections = ['bookmarks', 'forms', 'passwords', 'history', 'prefs']

# The distribution of GET operations to meta/global per test run.
# 40% will do 0 GETs, 60% will do 1 GET, etc...
metaglobal_count_distribution = [40, 60, 0, 0, 0]

# The distribution of GET operations per test run.
# 71% will do 0 GETs, 15% will do 1 GET, etc...
get_count_distribution = [71, 15, 7, 4, 3]

# The distribution of POST operations per test run.
# 67% will do 0 POSTs, 18% will do 1 POST, etc...
post_count_distribution = [67, 18, 9, 4, 2]

# The distribution of DELETE operations per test run.
# 99% will do 0 DELETEs, 1% will do 1 DELETE, etc...
delete_count_distribution = [99, 1, 0, 0, 0]

# The probability that we'll try to do a full DELETE of all data.
# Expressed as a float between 0 and 1.
deleteall_probability = 1 / 100.


class StressTest(TestCase):

    def __init__(self, *args, **kwds):
        self._pick_node()
        super(StressTest, self).__init__(*args, **kwds)

    def set_auth(self, username, password='password'):
        self.session.auth = (username, password)

    def test_storage_session(self):
        username = self._pick_user()
        self.set_auth(username)

        # Always GET /username/info/collections
        url = "/%s/%s/info/collections" % (VERSION, username)
        response = self.app.get(url, status=[200, 404])

        # GET requests to meta/global.
        num_requests = self._pick_weighted_count(metaglobal_count_distribution)
        for x in range(num_requests):
            url = "/%s/%s/storage/meta/global" % (VERSION, username)
            response = self.app.get(url, status=[200, 404])
            if response.status_code == 404:
                metapayload = "This is the metaglobal payload which contains"\
                              " some client data that doesnt look much"\
                              " like this"
                self.app.put_json(url,
                                  {"id": "global", "payload": metapayload})

        # GET requests to individual collections.
        num_requests = self._pick_weighted_count(get_count_distribution)
        cols = random.sample(collections, num_requests)
        for x in range(num_requests):
            url = "/%s/%s/storage/%s" % (VERSION, username, cols[x])
            newer = int(time.time() - random.randint(3600, 360000))
            response = self.app.get(url, {"full": "1", "newer": str(newer)},
                                    status=[200, 404])

        # PUT requests with 10 WBOs batched together
        num_requests = self._pick_weighted_count(post_count_distribution)
        cols = random.sample(collections, num_requests)
        for x in range(num_requests):
            url = "/%s/%s/storage/%s" % (VERSION, username, cols[x])
            items_per_batch = 10
            wbos = []
            for i in range(items_per_batch):
                id = base64.b64encode(os.urandom(10))
                id += str(time.time() % 100)
                payload = username * random.randint(50, 200)
                wbos.append({'id': id, 'payload': payload})

            response = self.app.post_json(url, wbos)
            self.assertTrue(response.body != '')

            result = response.json
            self.assertEquals(len(result["success"]), items_per_batch)
            self.assertEquals(len(result["failed"]), 0)

        # DELETE requests.
        # We might choose to delete some individual collections, or to do
        # a full reset and delete all the data.  Never both in the same run.
        num_requests = self._pick_weighted_count(delete_count_distribution)
        if num_requests:
            cols = random.sample(collections, num_requests)
            for x in range(num_requests):
                url = "/%s/%s/storage/%s" % (VERSION, username, cols[x])
                self.app.delete(url)
        else:
            if random.random() <= deleteall_probability:
                url = "/%s/%s/storage" % (VERSION, username)
                self.app.delete(url, headers={"X-Confirm-Delete", "true"})

    def _pick_node(self):
        # If we have not been told a specific server node,
        # randomly pick one of the stage server URLs.
        if getattr(self, 'server_url', None) is None:
            node = None
            # If a DB is down, add its number in here; e.g. down_dbs = [3,6]
            down_dbs = []
            while True:
                node = random.randint(1, 80)
                # Hosts 1 through 10 map to DB 1, 11 through 20 DB db 2, etc.
                # This maps the node number back to the db number.
                if ((node - 1) / 10) + 1 not in down_dbs:
                    break

            uri = "https://stage-sync%i.services.mozilla.com" % node
            self.server_url = uri

    def _pick_user(self):
        user = "cuser%i" % random.randint(1, 1000000)
        return user

    def _pick_weighted_count(self, weights):
        i = random.randint(1, sum(weights))
        count = 0
        base = 0
        for weight in weights:
            base += weight
            if i <= base:
                break
            count += 1

        return count
