#!/bin/sh

workers="client12.scl2.svc.mozilla.com client13.scl2.svc.mozilla.com client14.scl2.svc.mozilla.com client15.scl2.svc.mozilla.com client16.scl2.svc.mozilla.com"

echo "==> killing existing bench runs"
xapply "ssh %1 killall make" $workers
xapply "ssh %1 killall fl-run-bench" $workers
