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
import socket
import json
import time

from funkload.FunkLoadTestCase import FunkLoadTestCase
from funkload.utils import Data

VERSION = '1.1'
collections = ['bookmarks', 'forms', 'passwords', 'history', 'prefs', 'tabs']
get_count_distribution = [0, 71, 15, 7, 4, 3] # 0% 0 GETs, 71% 1 GET, etc.
post_count_distribution = [67, 18, 9, 4, 2]   # 67% 0 POSTs, 18% 1 POST, etc.

class StressTest(FunkLoadTestCase):

    def setUp(self):
        pass

    def test_storage_session(self):
        username = self._pick_user()
        password = "password"
        node = self._pick_node()
        self.logd("choosing node %s" % (node))
        self.setBasicAuth(username, password)

        # GET /username/info/collections
        self.setOkCodes([200, 404])
        url = node + "/%s/%s/info/collections" % (VERSION, username)
        response = self.get(url)

        c = collections[:]
        random.shuffle(c)

        # GET requests
        self.setOkCodes([200, 404])
        # we subtract 1 because we already did a GET on info/collections
        for x in range(self._pick_weighted_count(get_count_distribution) - 1):
            url = node + "/%s/%s/storage/%s" % \
                  (VERSION, username, collections[x])
            newer = int(time.time() - random.randint(3600, 360000))
            params = {"full": "1", "newer": str(newer)}
            self.logd("about to GET (x=%d) %s" % (x, url));
            response = self.get(url, params)

        # PUT requests with 100 WBOs batched together
        self.setOkCodes([200])
        for x in range(self._pick_weighted_count(post_count_distribution)):
            url = node + "/%s/%s/storage/%s" % \
                  (VERSION, username, collections[x])
            payload = username * random.randint(50, 200)
            data = []
            for i in range(100):
                id = base64.b64encode(os.urandom(10))
                id += str(time.time() % 100)
                wbo = {'id': id, 'payload': payload}
                data.append(wbo)
            data = json.dumps(data)
            data = Data('application/json', data)
            self.logd("about to POST (x=%d) %s" % (x, url));
            response = self.post(url, params=data)
            body = response.body
            self.assertTrue(body != '')

    def _pick_node(self):
        node = None
        # 41 <= node <= 50 sync5.db.scl2.stage down
        while node is None or (node >= 41 and node <= 50):
            node = random.randint(1, 80)
        return "https://stage-sync%i.services.mozilla.com" % node

    def _pick_user(self):
        return "cuser%i" % random.randint(1, 1000000)

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
