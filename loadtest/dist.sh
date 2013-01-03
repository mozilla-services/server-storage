#!/bin/sh

workers="client12.scl2.svc.mozilla.com client13.scl2.svc.mozilla.com client14.scl2.svc.mozilla.com client15.scl2.svc.mozilla.com client16.scl2.svc.mozilla.com"

dest_dir="$HOME/syncstorage-loadtest"
source_dir=$(dirname $0)

trap "echo '==> killing bench runs'; xapply 'ssh %1 killall make' $workers ; xapply 'ssh %1 killall fl-run-bench' $workers" EXIT

echo "==> killing existing bench runs"
xapply "ssh %1 killall make \; killall fl-run-bench" $workers

echo "==> syncing files to workers"
xapply "rsync $source_dir/{StressTest.conf,stress.py,Makefile} %1:$dest_dir/" $workers

echo "==> building virtualenvs"
xapply "ssh %1 cd $dest_dir \; find . -name 'loadtest*' | xargs rm; make build" $workers

echo "==> running load"
while :; do
    xapply -xP10 "ssh %1 cd $dest_dir \; make bench" $workers
done
