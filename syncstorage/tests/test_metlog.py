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
#   Rob Miller (rmiller@mozilla.com)
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
import json
import os
import unittest
import base64

from services.tests.support import make_request
from syncstorage.wsgiapp import make_app


class TestMetlog(unittest.TestCase):

    def setUp(self):
        config_file = os.path.join(os.path.dirname(__file__), "sync.conf")
        self.app = make_app({"configuration": "file:" + config_file}).app
        # set up a test user account
        self.auth = self.app.auth.backend
        self.username = 'arfoo'
        self.password = 'arpwd'
        self.auth.create_user(self.username, self.password, "test@moz.com")
        self.userid = self.auth.get_user_id(self.username)
        authz_token = base64.b64encode(self.username + ':' + self.password)
        self.authorization = 'Basic ' + authz_token

    def tearDown(self):
        self.auth.delete_user(self.userid)

    def test_stats_go_out(self):
        path = '/1.1/%s/info/collections' % self.username
        environ = {'HTTP_AUTHORIZATION': self.authorization}
        request = make_request(path, environ)
        self.app(request)
        sender = self.app.logger.sender
        msgs = list(sender.msgs)[-3:]
        msg0 = json.loads(msgs[0])
        self.assertEqual(msg0.get('type'), 'timer')
        msg1 = json.loads(msgs[1])
        self.assertEqual(msg1.get('type'), 'counter')
        msg2 = json.loads(msgs[2])
        self.assertEqual(msg2.get('type'), 'services')
        self.assertEqual(msg2['fields']['userid'], self.userid)
        self.assertTrue('req_time' in msg2['fields'])

    def test_addl_services_data(self):
        path = '/1.1/%s/info/collections' % self.username
        environ = {'HTTP_AUTHORIZATION': self.authorization}
        request = make_request(path, environ)
        request.user_agent = 'USER_AGENT'
        controller = self.app.controllers['storage']
        wrapped_method = controller._get_collections_wrapped
        orig_inner = wrapped_method._fn._fn._fn
        data = {'foo': 'bar'}

        def services_data_wrapper(fn):
            from services.metrics import update_metlog_data

            def new_inner(*args, **kwargs):
                update_metlog_data(data)
                return fn(*args, **kwargs)

            return new_inner

        wrapped_method._fn._fn._fn = services_data_wrapper(orig_inner)
        self.app(request)
        sender = self.app.logger.sender
        msgs = list(sender.msgs)[-3:]
        msg2 = json.loads(msgs[2])
        self.assertEqual(msg2.get('type'), 'services')
        expected = data.copy()
        expected['userid'] = self.userid
        expected['req_time'] = msg2['fields']['req_time']
        self.assertEqual(msg2['fields'], expected)
        wrapped_method._fn._fn._fn = orig_inner
