#!/bin/bash

docker run -t --rm --name joshua-test -u root:root -v $(pwd):/joshua foundationdb/joshua-agent:latest /joshua/sanity_test_script.sh
rc=$?
if [ $rc -eq 0 ]; then
    echo "PASSED!"
else
    echo "FAILED!"
fi
exit $rc
