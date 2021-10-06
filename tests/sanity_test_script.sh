#!/bin/bash

one_agent() {
    python -m joshua.joshua_agent -C ${FDB_CLUSTER_FILE} --work_dir /tmp/work --agent-idle-timeout 5
}

two_agent() {
    python -m joshua.joshua_agent -C ${FDB_CLUSTER_FILE} --work_dir /tmp/work/1 --agent-idle-timeout 5 &
    pid1=$!
    python -m joshua.joshua_agent -C ${FDB_CLUSTER_FILE} --work_dir /tmp/work/2 --agent-idle-timeout 5 &
    pid2=$!
    wait $pid1 $pid2
}

two_agent_kill_one() {
    python -m joshua.joshua_agent -C ${FDB_CLUSTER_FILE} --work_dir /tmp/work/1 --agent-idle-timeout 5 &
    pid1=$!
    python -m joshua.joshua_agent -C ${FDB_CLUSTER_FILE} --work_dir /tmp/work/2 --agent-idle-timeout 5 &
    pid2=$!
    sleep 5
    kill $pid1
    wait $pid2
}

source /opt/rh/rh-python38/enable

# get latest fdb version
fdbver=$(curl --silent https://www.foundationdb.org/downloads/version.txt)

# fdb_binaries
curl --silent https://www.foundationdb.org/downloads/${fdbver}/linux/fdb_${fdbver}.tar.gz -o fdb_${fdbver}.tar.gz
tar xzf fdb_${fdbver}.tar.gz
export PATH=$(pwd)/fdb_binaries:${PATH}

# libfdb_c.so
curl --silent https://www.foundationdb.org/downloads/${fdbver}/linux/libfdb_c_${fdbver}.so -o libfdb_c.so
chmod +x libfdb_c.so
export LD_LIBRARY_PATH=$(pwd):${LD_LIBRARY_PATH}

# python binding
curl --silent https://www.foundationdb.org/downloads/${fdbver}/bindings/python/foundationdb-${fdbver}.tar.gz -o foundationdb-${fdbver}.tar.gz
tar xzf foundationdb-${fdbver}.tar.gz
export PYTHONPATH=$(pwd)/foundationdb-${fdbver}

# generate fdb.cluster
echo "joshua:joshua@$(hostname -I | tr -d ' '):4500" > fdb.cluster
export FDB_CLUSTER_FILE=$(pwd)/fdb.cluster

# start fdb
mkdir data logs
fdbserver \
    --datadir $(pwd)/data/4500 \
    --listen_address public \
    --logdir $(pwd)/logs \
    --public_address auto:4500 \
    --trace_format json > fdb.log 2>&1 &
fdbpid=$!
sleep 1
fdbcli --exec 'configure new single ssd'


# create joshua test package
cat > joshua_test <<EOF
#!/bin/bash

for i in \$(seq 3); do
  echo "hello \$i"
  sleep 1
done
EOF

cat > joshua_timeout <<EOF
#!/bin/bash

echo "timeout"
EOF

chmod +x joshua_test joshua_timeout

tar czf test.tar.gz joshua_test joshua_timeout

mkdir /tmp/work

total_tests=0
total_passed=0
total_failed=0

for test in one_agent two_agent two_agent_kill_one; do
    (( total_tests++ ))
    echo "=== TEST: ${test} ==="
    python -m joshua.joshua start --tarball test.tar.gz --max-runs 6
    python -m joshua.joshua list
    ensemble=$(python -m joshua.joshua list | awk '{print $1}')
    eval $test
    python -m joshua.joshua list --stopped
    pass=0
    ended=0
    max_runs=0
    for kv in $(python -m joshua.joshua list --stopped | tail -1); do
	if [[ $kv =~ pass= ]]; then
	    pass=$(echo $kv | cut -d '=' -f 2)
	elif [[ $kv =~ ended= ]]; then
	    ended=$(echo $kv | cut -d '=' -f 2)
	elif [[ $kv =~ max_runs= ]]; then
	    max_runs=$(echo $kv | cut -d '=' -f 2)
	fi
    done
    if [ $pass -eq $ended ] && [ $ended -eq $max_runs ]; then
	echo "Pass: pass:$pass ended:$ended max_runs:$max_runs"
	(( total_passed++ ))
    else
	echo "Fail: pass:$pass ended:$ended max_runs:$max_runs"
	(( total_failed++ ))
    fi
    python -m joshua.joshua delete -y ${ensemble}
done

# timeout test
for test in two_agent; do
    (( total_tests++ ))
    echo "=== TEST: ${test} TIMEOUT ==="
    python -m joshua.joshua start --tarball test.tar.gz --max-runs 6 --timeout 2
    python -m joshua.joshua list
    ensemble=$(python -m joshua.joshua list | awk '{print $1}')
    eval $test
    python -m joshua.joshua list --stopped
    fail=0
    ended=0
    for kv in $(python -m joshua.joshua list --stopped | tail -1); do
	if [[ $kv =~ fail= ]]; then
	    fail=$(echo $kv | cut -d '=' -f 2)
	elif [[ $kv =~ ended= ]]; then
	    ended=$(echo $kv | cut -d '=' -f 2)
	fi
    done
    if [ $fail -eq $ended ] && [ $fail -eq 2 ]; then
	echo "Pass: fail:$fail == ended:$ended"
	(( total_passed++ ))
    else
	echo "Fail: fail:$fail != ended:$ended or fail:$fail != 2"
	(( total_failed++ ))
    fi
    python -m joshua.joshua delete -y ${ensemble}
done

kill -9 ${fdbpid}

echo "${total_passed} / ${total_tests} passed"

exit $total_failed

