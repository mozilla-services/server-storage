#!/bin/sh
#
# Build a server-storage webhead node for AWS deployment.

set -e

YUM="yum --assumeyes --enablerepo=epel"

$YUM update
$YUM install python-pip mercurial

# Checkout and build latest server-storage.

python-pip install virtualenv

useradd syncstorage

UDO="sudo -u syncstorage"

cd /home/syncstorage
$UDO hg clone https://hg.mozilla.org/services/server-storage
cd ./server-storage

$YUM install openssl-devel libmemcached-devel libevent-devel python-devel gcc
$UDO make build
$UDO ./bin/pip install gunicorn

# Write the configuration files.

cat > production.ini << EOF
[DEFAULT]
debug = false

[server:main]
use = egg:Paste#http
host = 0.0.0.0
port = 5000

[app:main]
use = egg:SyncStorage
configuration = file:%(here)s/sync.conf
EOF
chown syncstorage:syncstorage production.ini

cat > sync.conf << EOF
[storage]
backend = syncstorage.storage.sql.SQLStorage
sqluri = pymysql://sync:syncerific@db1.rfkelly.allizomaws.net/sync
standard_collections = true
use_quota = false
pool_size = 2
pool_overflow = 5
pool_recycle = 3600
reset_on_return = true
create_tables = true

[auth]
backend = services.user.loadtest.LoadTestUser

[cef]
use = true
file = syslog
vendor = mozilla
version = 0
device_version = 1.3
product = weave

[host:sync1.rfkelly.allizomaws.net]
storage.sqluri = pymysql://sync:syncerific@db1.rfkelly.allizomaws.net/sync

[host:sync2.rfkelly.allizomaws.net]
storage.sqluri = pymysql://sync:syncerific@db2.rfkelly.allizomaws.net/sync

[host:sync3.rfkelly.allizomaws.net]
storage.sqluri = pymysql://sync:syncerific@db3.rfkelly.allizomaws.net/sync
EOF
chown syncstorage:syncstorage sync.conf


# Write a circus config script.

cd ../
cat > sync.ini << EOF
[watcher:syncstorage]
working_dir=/home/syncstorage/server-storage
cmd=bin/gunicorn_paster -k gevent -w 4 production.ini
numprocesses = 1
EOF
chown syncstorage:syncstorage sync.ini

# Launch the server via circus on startup.

$YUM install czmq-devel zeromq

python-pip install circus

cat > /etc/rc.local << EOF
su -l syncstorage -c '/usr/bin/circusd --daemon /home/syncstorage/sync.ini'
exit 0
EOF


# Setup nginx as proxy.

$YUM install nginx

/sbin/chkconfig nginx on
/sbin/service nginx start

cat << EOF > /etc/nginx/nginx.conf
user  nginx;
worker_processes  1;
events {
    worker_connections  20480;
}
http {
    include       mime.types;
    default_type  application/octet-stream;
    log_format xff '\$remote_addr - \$remote_user [\$time_local] "\$request" '
                   '\$status \$body_bytes_sent "\$http_referer" '
                   '"\$http_user_agent" XFF="\$http_x_forwarded_for" '
                   'TIME=\$request_time ';
    access_log /var/log/nginx/access.log xff;
    server {
        listen       80 default;
        location / {
            proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
            proxy_set_header Host \$http_host;
            proxy_redirect off;
            proxy_pass http://localhost:5000;
        }
    }
}
EOF
