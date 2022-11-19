#!/usr/bin/env bash

batch_size=${BATCH_SIZE:-1}
max_jobs=${MAX_JOBS:-10}
check_delay=${CHECK_DELAY:-10}
# Kubernetes 1.21 supports jobs TTL controller, which cleans up jobs automatically
# see https://kubernetes.io/docs/concepts/workloads/controllers/ttlafterfinished/
use_k8s_ttl_controller=${USE_K8S_TTL_CONTROLLER:-false}

# when enable_dynamic_agent_tag is true,
# scaler will poll the joshua_model for any dynamic tag changes
enable_dynamic_agent_tag=${ENABLE_DYNAMIC_AGENT_TAG:-false}
initial_agent_tag=${AGENT_TAG}

# when restart_scaler_at_agent_update is true,
# scaler will exit and restart when a new agent tag is set
restart_scaler_at_agent_update=${RESTART_SCALER_AT_AGENT_UPDATE:-false}

namespace=$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)

# set the current agent tag
if [ $enable_dynamic_agent_tag == true ]; then
    new_tag=$(python3 /tools/get_agent_tag.py)
    if [ ! -z "${new_tag}" ]; then
        export AGENT_TAG=${new_tag}
    fi
fi

# mark existing jobs to exit
kubectl -n ${namespace} label pods -l app=joshua-agent last_test=true --overwrite=true

# run forever
while true; do

    if [ $use_k8s_ttl_controller == false ] ; then
      # cleanup finished jobs (status 1/1)
      for job in $(kubectl get jobs -n "${namespace}" --no-headers | grep -E -e 'joshua-agent-[0-9-]*\s*1/1' | awk '{print $1}'); do
          echo "=== Job $job Completed ==="
          kubectl delete job "$job" -n "${namespace}"
      done

      # cleanup failed jobs
      # pod name is always prefixed with the job name
      # e.g. "joshua-agent-XXXXXXXXXXXX-XX-yyyyy"
      for job in $(kubectl get pods -n "${namespace}" --no-headers | grep -E -e "Completed" -e "Error" | cut -f 1-4 -d '-') ; do
          echo "=== Deleting Job $job ==="
          kubectl delete job "$job" -n "${namespace}"
      done
    fi

    # check agent image updates
    if [ $enable_dynamic_agent_tag == true ]; then
        tag_changed=false
        new_tag=$(python3 /tools/get_agent_tag.py)

	# check if the tag is cleared
        if [ -z "${new_tag}" ]; then
	    # if the initial tag is already used, do nothing
            if [ ! "${AGENT_TAG}" == "${initial_agent_tag}" ]; then
                # restore the original tag baked in the image
                export AGENT_TAG=${initial_agent_tag}
		tag_changed=true
	    fi
        # check if the tag has changed
        elif [ ! "${AGENT_TAG}" == "${new_tag}" ]; then
            # update the agent tag
            export AGENT_TAG=${new_tag}
            tag_changed=true
        fi

        if [ $tag_changed == true ]; then
            if [ $restart_scaler_at_agent_update == true ]; then
                # restart by itself
                # agents will be stopped during the next startup
                kubectl -n "${namespace}" delete pod ${HOSTNAME}
                exit 0
            else
               # stop current agents
               kubectl -n ${namespace} label pods -l app=joshua-agent last_test=true --overwrite=true
            fi
        fi
    fi

    # get the current ensembles
    num_ensembles=$(python3 /tools/ensemble_count.py)
    echo "${num_ensembles} ensembles in the queue"

    # get the current jobs
    num_jobs=$(kubectl get jobs -n "${namespace}" --no-headers | wc -l)
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
