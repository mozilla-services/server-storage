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

from services.tests.support import make_request
from syncstorage.wsgiapp import make_app


class TestMetlog(unittest.TestCase):

    def setUp(self):
        config_file = os.path.join(os.path.dirname(__file__), "sync.conf")
        self.app = make_app({"configuration": "file:" + config_file}).app

    def test_timer_and_incr_msgs_are_firing(self):
        username = 'arfoo'
        path = '/1.1/%s/info/collections' % username
        environ = {'REMOTE_USER': username}
        request = make_request(path, environ)
        self.app(request)
        sender = self.app.logger.sender
        self.assertEqual(len(sender.msgs), 2)
        msg0 = json.loads(sender.msgs[0])
        self.assertEqual(msg0.get('type'), 'timer')
        msg1 = json.loads(sender.msgs[1])
        self.assertEqual(msg1.get('type'), 'counter')
