#!/usr/bin/env bash

batch_size=${BATCH_SIZE:-1}
max_jobs=${MAX_JOBS:-10}
check_delay=${CHECK_DELAY:-10}

namespace=$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)

AGENT_TEMPLATE_YAML=/template/joshua-agent.yaml.template

# run forever
while true; do
    # cleanup finished jobs (status 1/1)
    for job in $(kubectl get jobs -n "${namespace}" | grep -E -e 'joshua-agent-[0-9-]*\s*1/1' | awk '{print $1}'); do
        echo "=== Job $job Completed ==="
        kubectl delete job "$job" -n "${namespace}"
    done

    # cleanup failed jobs
    # pod name is always prefixed with the job name
    # e.g. "joshua-agent-XXXXXXXXXXXX-XX-yyyyy"
    for job in $(kubectl get pods -n "${namespace}" | grep -E -e "Completed" -e "Error" | cut -f 1-4 -d '-') ; do
        echo "=== Deleting Job $job ==="
        kubectl delete job "$job" -n "${namespace}"
    done

    # get the current ensembles
    num_ensembles=$(python3 /tools/fdb_util.py get_ensemble_count)

    # get the current jobs
    num_jobs=$(kubectl get jobs -n "${namespace}" | wc -l)

    # provision more jobs
    if [ "${num_ensembles}" -gt "${num_jobs}" ]; then
        current_timestamp="$(date +%y%m%d%H%M%S)"
        new_jobs=$((num_ensembles - num_jobs))

        if [ ${new_jobs} -gt $((max_jobs - num_jobs)) ]; then
            new_jobs=$((max_jobs - num_jobs))
        fi

        # does nothing if using joshua-agent:latest
        if $(cat $AGENT_TEMPLATE_YAML | grep -q "joshua-agent:${AGENT_TAG}")
        then
            AGENT_TAG=$(python3 /tools/fdb_util.py get_agent_tag)
        fi

        idx=0
        while [ $idx -lt ${new_jobs} ]; do
            if [ -e /tmp/joshua-agent.yaml ]; then
                rm -f /tmp/joshua-agent.yaml
            fi
            i=0
            while [ $i -lt "${batch_size}" ]; do
                export JOBNAME_SUFFIX="${current_timestamp}-${idx}"
                echo "=== Adding $JOBNAME_SUFFIX ==="
                envsubst < $AGENT_TEMPLATE_YAML >>/tmp/joshua-agent.yaml
                # add a separator
                echo "---" >>/tmp/joshua-agent.yaml
                ((idx++))
                ((i++))
                if [ "${idx}" -ge ${new_jobs} ]; then
                    break
                fi
            done
            # /tmp/joshua-agent.yaml contains up to $batch_size entries
            kubectl apply -f /tmp/joshua-agent.yaml -n "${namespace}"
        done
    fi

    # check every check_delay seconds
    sleep "${check_delay}"
done
exit 0
