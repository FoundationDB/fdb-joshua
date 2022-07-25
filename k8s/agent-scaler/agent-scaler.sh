#!/usr/bin/env bash

batch_size=${BATCH_SIZE:-1}
max_jobs=${MAX_JOBS:-10}
check_delay=${CHECK_DELAY:-10}
# Kubernetes 1.21 supports jobs TTL controller, which cleans up jobs automatically
# see https://kubernetes.io/docs/concepts/workloads/controllers/ttlafterfinished/
use_k8s_ttl_controller=${USE_K8S_TTL_CONTROLLER:-false}

namespace=$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)

# run forever
while true; do

    if [ $use_k8s_ttl_controller == false ] ; then
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
    fi

    # get the current ensembles
    num_ensembles=$(python3 /tools/ensemble_count.py)
    echo "${num_ensembles} ensembles in the queue"

    # get the current jobs
    num_jobs=$(kubectl get jobs -n "${namespace}" | wc -l)
    echo "${num_jobs} jobs are running"

    # provision more jobs
    if [ "${num_ensembles}" -gt "${num_jobs}" ]; then
        current_timestamp="$(date +%y%m%d%H%M%S)"
        new_jobs=$((num_ensembles - num_jobs))

        if [ ${new_jobs} -gt $((max_jobs - num_jobs)) ]; then
            new_jobs=$((max_jobs - num_jobs))
        fi

        if [ -n "${MAX_NEW_JOBS}" ]; then
            if [ "${new_jobs}" -gt "${MAX_NEW_JOBS}" ]; then
                new_jobs=${MAX_NEW_JOBS}
            fi
        fi

        idx=0
        echo "Starting ${new_jobs} jobs"
        while [ $idx -lt ${new_jobs} ]; do
            if [ -e /tmp/joshua-agent.yaml ]; then
                rm -f /tmp/joshua-agent.yaml
            fi
            i=0
            while [ $i -lt "${batch_size}" ]; do
                export JOBNAME_SUFFIX="${current_timestamp}-${idx}"
                echo "=== Adding $JOBNAME_SUFFIX ==="
                envsubst </template/joshua-agent.yaml.template >>/tmp/joshua-agent.yaml
                # add a separator
                echo "---" >>/tmp/joshua-agent.yaml
                ((idx++))
                ((i++))
                if [ "${idx}" -ge ${new_jobs} ]; then
                    break
                fi
            done
            # /tmp/joshua-agent.yaml contains up to $batch_size entries
            echo "Starting a batch of ${i} jobs"
            kubectl apply -f /tmp/joshua-agent.yaml -n "${namespace}"
        done
    fi
    echo "${new_jobs} jobs started"

    # check every check_delay seconds
    sleep "${check_delay}"
done
exit 0
