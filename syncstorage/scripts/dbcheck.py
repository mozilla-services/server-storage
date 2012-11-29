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
#   Ryan Kelly (rfkelly@mozilla.com)
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

Database health monitoring script for SyncStorage.

This script is designed to be run as a daemon, and will periodically ping
each storage backend to check whether it is still up.  If a backend is
found to be down then this fact is recorded in memcache so that the webapp
can avoid sending traffic to it.

Run it by specifing the path to the configuration file, like so::

  python dbcheck.py /etc/mozilla-services/sync.conf

"""

import os
import sys
import time
import signal
import logging
import optparse
import contextlib

from pylibmc import Client

import syncstorage.wsgiapp

logger = logging.getLogger("syncstorage.scripts.dbcheck")


def monitor_backends(config_file, check_interval=60, backend_timeout=30):
    """Monitor the health of all storage backends in the given config file.

    This function runs an endless loop that periodically pings each storage
    backend found in the given config file.  If the backend errors out or
    fails to respond within a certain time, then it is considered to be
    unhealthy and is marked as such in memcache.

    The actual checking logic is implemented in the check_backends() function.
    This function just adds a simple control loop.
    """
    logger.info("Entering storage backend monitor")

    # Sanity-check the app config file.
    logger.debug("Using config file %r", config_file)
    app = load_app_from_config(config_file)
    logger.debug("Using memcache servers %r", app.cache_servers)

    # Loop forever, periodically pinging the storage backends.
    try:
        while True:
            start_time = time.time()
            logger.debug("Beginning monitor loop at %s", start_time)

            # The app is reloaded from config file on each iteration.
            # This makes it easier to account for added/removed nodes.
            check_backends(config_file, backend_timeout)

            end_time = time.time()
            logger.debug("Finishing monitor loop at %s", end_time)
            sleep_time = check_interval - (end_time - start_time)
            if sleep_time > 0:
                logger.debug("Sleeping for %s seconds", sleep_time)
                time.sleep(sleep_time)

    finally:
        logger.info("Exiting storage backend monitor")


def check_backends(config_file, backend_timeout=30):
    """Check the health of all storage backends in the given config file.

    This pings each storage backend found in the given config file.  If the
    backend errors out or fails to respond within a certain time, then it is
    considered to be unhealthy and is marked as such in memcache.

    To prevent uncooperative backends from locking up the monitoring loop,
    this function forks a new child process to ping each individual backend.
    Any that do not exit within the specified timeout are unceremoniously
    killed.
    """
    app = load_app_from_config(config_file)

    # These dicts will hold the pids of any child processes that we fork.
    # A try-finally is used to ensure they're cleaned up at function exit.
    running_procs = {}
    hung_procs = {}

    try:
        # Dicts to hold the old and new statuses of each backend.
        # New statuses are written into memcache using an atomic
        # compare-and-swap against the old status, to prevent race
        # conditions with other admin tools.
        old_statuses = {}
        new_statuses = {}

        # For each backend host, read its current status from memcache.
        # If it's either "ok" or "unhealthy" then we can send it a ping.
        # If it's any other state then we shouldn't mess with it, as it
        # will have been manually set to e.g. "down" by the ops team.
        with memcache_client(app.cache_servers) as cache:
            for host in app.storages:
                status, casid = cache.gets("status:" + host)
                if status is None:
                    status = "ok"
                logger.debug("Current status of %r: %s", host, status)
                if status in ("ok", "unhealthy"):
                    # Remember the casid so we can do atomic replace later.
                    old_statuses[host] = status, casid

        # For each backend host that we want to monitor, fork a child
        # process to do the actual ping.  This makes it easy for us to
        # recover if it times out, goes haywire etc.
        for host, backend in app.storages.iteritems():
            if host in old_statuses:
                pid = os.fork()
                if pid:
                    # We're in the parent process.
                    # Just record the pid for monitoring.
                    running_procs[pid] = host
                else:
                    # We're in the child process.
                    # Ping the backend to see if it's active.
                    # Note that os._exit is the recommended way to
                    # exit a child process after a fork().
                    try:
                        if backend.is_healthy():
                            os._exit(0)
                        else:
                            os._exit(1)
                    except Exception:
                        os._exit(2)

        # Set a SIGALRM to interrupt us after the timeout has passed.
        # Any child processes that haven't completed by this time
        # are considered hung and the host will be marked as down.
        def on_alarm(signum, frame):
            hung_procs.update(running_procs)
            running_procs.clear()
        signal.signal(signal.SIGALRM, on_alarm)
        signal.alarm(backend_timeout)

        # Wait for all child processes to complete, or for the SIGALRM.
        # If the alarm triggers, it will interrupt os.wait() with an OSError.
        while running_procs:
            try:
                pid, code = os.wait()
                host = running_procs.pop(pid)
                logger.debug("Check completed for %r, code=%s", host, code)
                new_statuses[host] = "unhealthy" if code else "ok"
            except OSError:
                pass
        signal.alarm(0)

        # Reap any child processes that have hung.
        for pid, host in hung_procs.iteritems():
            logger.info("Check timed out for %r", host)
            reap_child_proc(pid)
            new_statuses[host] = "unhealthy"
        hung_procs.clear()

        # Update the status of each host in memcache.
        # Using CAS prevents us overwriting updates made by other scripts.
        with memcache_client(app.cache_servers) as cache:
            for host, new_status in new_statuses.iteritems():
                old_status, casid = old_statuses[host]
                logger.debug("New status for %r is %s", host, new_status)
                if old_status != new_status:
                    logger.info("Status change for %r: %s => %s",
                                host, old_status, new_status)
                    if casid is None:
                        cache.add("status:" + host, new_status)
                    else:
                        cache.cas("status:" + host, new_status, casid)

    finally:
        # Ensure that all child procs are cleaned up on exit.
        for pid in running_procs:
            reap_child_proc(pid)
        for pid in hung_procs:
            reap_child_proc(pid)


def load_app_from_config(config_file):
    """Load a SyncStorage app object from the given config file.

    This emulates how paster would load it from the .ini file and ensures
    that we get the same set of storage backends as the webapp.
    """
    global_conf = {
      "here": os.path.dirname(config_file),
    }
    settings = {
      "configuration": "file:" + config_file,
    }
    app = syncstorage.wsgiapp.make_app(global_conf, **settings).app
    cache_servers = app.config.get("storage.cache_servers", "localhost:11211")
    app.cache_servers = cache_servers.split(",")
    return app


@contextlib.contextmanager
def memcache_client(servers):
    """Context-manager for creating connections to memcache.

    Unfortunately pylibmc doesn't seem to play nicely with os.fork(),
    so we can't create a single connection and use it for all queries.
    Instead we must create one when needed and tear it down when done.
    """
    client = Client(servers, behaviors={"cas": 1})
    try:
        yield client
    finally:
        client.disconnect_all()


def reap_child_proc(pid):
    """Helper function that reaps hung child processes.

    This can be used to cleanup a rogue child process without erroring
    out if it does something funny.
    """
    try:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    except OSError:
        pass


def main(args=None):
    """Main entry-point for running this script.

    This function parses command-line arguments and passes them on
    to the monitor_backends() function.
    """
    usage = "usage: %prog [options] config_file"
    parser = optparse.OptionParser(usage=usage)
    parser.add_option("", "--check-interval", type="int", default=60,
                      help="The interval between checks, in seconds")
    parser.add_option("", "--backend-timeout", type="int", default=30,
                      help="How long to wait for a response, in seconds")
    parser.add_option("", "--oneshot", action="store_true",
                      help="Run a single check and then exit")
    parser.add_option("-v", "--verbose", action="count", dest="verbosity",
                      help="Control verbosity of log messages")

    opts, args = parser.parse_args(args)
    if len(args) != 1:
        parser.print_usage()
        return 1

    if not opts.verbosity:
        loglevel = logging.WARNING
    elif opts.verbosity == 1:
        loglevel = logging.INFO
    else:
        loglevel = logging.DEBUG
    logging.basicConfig(level=loglevel)

    config_file = os.path.abspath(args[0])

    if opts.oneshot:
        check_backends(config_file,
                       backend_timeout=opts.backend_timeout)
    else:
        monitor_backends(config_file,
                         check_interval=opts.check_interval,
                         backend_timeout=opts.backend_timeout)
    return 0


if __name__ == "__main__":
    exitcode = main()
    sys.exit(exitcode)
