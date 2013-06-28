.PHONY: build test bench

# build virtualenv
build:
	virtualenv --no-site-packages .
	bin/pip install https://github.com/mozilla-services/loads/archive/master.zip

# run a single test, for sanity-checking
test:
	bin/loads-runner stress.StressTest.test_storage_session

# run actual bench (called from dist.sh over ssh)
bench:
	while :; do bin/loads-runner -u 50 -c 100 stress.StressTest.test_storage_session; done
