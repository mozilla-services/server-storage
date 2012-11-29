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
Application entry point.
"""
from webob.exc import HTTPServiceUnavailable

from services.baseapp import set_app, SyncServerApp
from services.wsgiauth import Authentication
from syncstorage.controller import StorageController
from syncstorage.storage import get_storage

try:
    from pylibmc import Client
except ImportError:
    Client = None       # NOQA

_EXTRAS = {'auth': True}


def _url(url):
    for pattern, replacer in (('_API_', '{api:1.0|1|1.1}'),
                              ('_COLLECTION_',
                               '{collection:[a-zA-Z0-9._-]+}'),
                              ('_USERNAME_',
                               '{username:[a-zA-Z0-9._-]+}'),
                              ('_ITEM_',
                              r'{item:[\\a-zA-Z0-9._?#~-]+}')):
        url = url.replace(pattern, replacer)
    return url


urls = [('GET', _url('/_API_/_USERNAME_/info/collections'),
         'storage', 'get_collections', _EXTRAS),
        ('GET', _url('/_API_/_USERNAME_/info/collection_counts'),
         'storage', 'get_collection_counts', _EXTRAS),
        ('GET', _url('/_API_/_USERNAME_/info/quota'), 'storage', 'get_quota',
          _EXTRAS),
        ('GET', _url('/_API_/_USERNAME_/info/collection_usage'), 'storage',
         'get_collection_usage', _EXTRAS),
        # XXX empty collection call
        ('PUT', _url('/_API_/_USERNAME_/storage/'), 'storage', 'get_storage',
         _EXTRAS),
        ('GET', _url('/_API_/_USERNAME_/storage/_COLLECTION_'), 'storage',
        'get_collection', _EXTRAS),
        ('GET', _url('/_API_/_USERNAME_/storage/_COLLECTION_/_ITEM_'),
         'storage', 'get_item', _EXTRAS),
        ('PUT', _url('/_API_/_USERNAME_/storage/_COLLECTION_/_ITEM_'),
         'storage', 'set_item', _EXTRAS),
        ('POST', _url('/_API_/_USERNAME_/storage/_COLLECTION_'), 'storage',
        'set_collection', _EXTRAS),
        ('PUT', _url('/_API_/_USERNAME_/storage/_COLLECTION_'), 'storage',
        'set_collection', _EXTRAS),
        ('DELETE', _url('/_API_/_USERNAME_/storage/_COLLECTION_'), 'storage',
        'delete_collection', _EXTRAS),
        ('DELETE', _url('/_API_/_USERNAME_/storage/_COLLECTION_/_ITEM_'),
         'storage', 'delete_item', _EXTRAS),
        ('DELETE', _url('/_API_/_USERNAME_/storage'), 'storage',
         'delete_storage', _EXTRAS)]

controllers = {'storage': StorageController}


class StorageServerApp(SyncServerApp):
    """Storage application"""
    def __init__(self, urls, controllers, config=None,
                 auth_class=Authentication):
        super(StorageServerApp, self).__init__(urls, controllers, config,
                                               auth_class)
        self.config = config

        # Collecting the host-specific config and building connectors.
        self.storages = {'default': get_storage(config)}
        hostnames = set()
        host_token = 'host:'
        for cfgkey in config:
            if cfgkey.startswith(host_token):
                # Get the hostname from the config key.  This assumes
                # that host-specific keys have two trailing components
                # that specify the setting to override.
                # E.g: "host:localhost.storage.sqluri" => "localhost"
                hostname = cfgkey[len(host_token):].rsplit(".", 2)[0]
                hostnames.add(hostname)
        for hostname in hostnames:
            host_cfg = self._host_specific(hostname, config)
            self.storages[hostname] = get_storage(host_cfg)

        # If we need to check node status, then we need to
        # obtain a memcache client object.
        self.cache = None
        self.check_node_status = \
                self.config.get('storage.check_node_status', False)
        if self.check_node_status:
            if Client is None:
                raise ValueError('The "check_node_status" option '
                                 'needs a memcached server')
            servers = self.config.get('storage.cache_servers',
                                      '127.0.0.1:11211')
            self.cache = Client(servers.split(','))

    def get_storage(self, request):
        host = request.host
        if host not in self.storages:
            host = 'default'
        return self.storages[host]

    def _before_call(self, request):
        headers = {}

        # If configured to do so, this function can check memcache for
        # the status of the target node and possibly avoid calling out
        # to the storage backend.  It looks for a memcache key named
        # "status:<hostname>" with one of the following values:
        #
        #    "down":   the node is explicitly marked as down
        #    "draining":   the node is being decommissioned
        #    "unhealthy":  the node has not responded to health checks
        #    "backoff" or "backoff:NN":  the node is under heavy load and
        #                                clients should back off for a while.

        if self.check_node_status:

            # Helper function to create a HTTPServiceUnavailable response.
            # This takes care of some fiddly details in the API.
            def resp_service_unavailable(msg):
                body = "server issue: " + msg
                headers["Retry-After"] = str(self.retry_after)
                headers["X-Weave-Backoff"] = str(self.retry_after)
                raise HTTPServiceUnavailable(headers=headers,
                                             body_template=body)

            # Get the node name from host header,
            # and check that it's one we know about.
            node = request.host
            if not node:
                msg = "host header not received from client"
                raise resp_service_unavailable(msg)

            if node not in self.storages:
                msg = "database lookup failed"
                raise resp_service_unavailable(msg)

            status = self.cache.get('status:%s' % request.host)
            if status is not None:

                # If it's marked as draining then send a 503 response.
                # XXX TODO: consider sending a 401 to trigger migration?
                if status == "draining":
                    msg = "node reassignment"
                    raise resp_service_unavailable(msg)

                # If it's marked as being down then send a 503 response.
                if status == "down":
                    msg = "database marked as down"
                    raise resp_service_unavailable(msg)

                # If it's marked as being unhealthy then send a 503 response.
                if status == "unhealthy":
                    msg = "database is not healthy"
                    raise resp_service_unavailable(msg)

                # If it's marked for backoff, proceed with the request
                # but set appropriate headers on the response.
                if status == "backoff" or status.startswith("backoff:"):
                    try:
                        backoff = status.split(":", 1)[1]
                    except IndexError:
                        backoff = str(self.retry_after)
                    headers["X-Weave-Backoff"] = backoff

        return headers

    def _debug_server(self, request):
        res = []
        storage = self.get_storage(request)
        res.append('- backend: %s' % storage.get_name())
        if storage.get_name() in ('memcached',):
            cache_servers = ['%s:%d' % (server.ip, server.port)
                             for server in storage.cache.servers]
            res.append('- memcached servers: %s</li>' %
                       ', '.join(cache_servers))

        if storage.get_name() in ('sql', 'memcached'):
            res.append('- sqluri: %s' % storage.sqluri)
        return res


make_app = set_app(urls, controllers, klass=StorageServerApp,
                   auth_class=Authentication)
