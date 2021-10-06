#!/bin/bash

tag=latest
if [ $# -eq 1 ]; then
    tag=$1
fi
docker run -t --rm --name joshua-test -u root:root -v $(pwd):/joshua foundationdb/joshua-agent:${tag} /joshua/sanity_test_script.sh
rc=$?
if [ $rc -eq 0 ]; then
    echo "PASSED!"
else
    echo "FAILED!"
fi
exit $rc
