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
import os

from syncstorage.storage import SyncStorage
from services.auth import ServicesAuth

import services.tests.support


def initenv(config=None, **env_args):
    """Reads the config file and instantiates an auth and a storage.
    """
    # pre-registering plugins
    from syncstorage.storage.sql import SQLStorage
    SyncStorage.register(SQLStorage)
    try:
        from syncstorage.storage.memcachedsql import MemcachedSQLStorage
        SyncStorage.register(MemcachedSQLStorage)
    except ImportError:
        pass

    from services.auth.sql import SQLAuth
    ServicesAuth.register(SQLAuth)
    try:
        from services.auth.ldapsql import LDAPAuth
        ServicesAuth.register(LDAPAuth)
    except ImportError:
        pass
    from services.auth.dummy import DummyAuth
    ServicesAuth.register(DummyAuth)

    env_args['ini_path'] = config
    env_args.setdefault('ini_dir', os.path.dirname(__file__))
    env_args.setdefault('load_sections', ['auth', 'storage'])
    testenv = services.tests.support.TestEnv(**env_args)
    return testenv.ini_dir, testenv.config, testenv.storage, testenv.auth


def cleanupenv(config=None, **env_args):
    env_args.setdefault('ini_dir', os.path.dirname(__file__))
    return services.tests.support.cleanupenv(config, **env_args)
