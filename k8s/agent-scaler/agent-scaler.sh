#!/usr/bin/env bash

# This script acts as a Kubernetes agent scaler for Joshua test jobs.
# Its primary responsibilities are:
# 1. Periodically cleaning up completed or failed Joshua agent jobs specific
#    to the AGENT_NAME it's configured for (e.g., joshua-agent, joshua-rhel9-agent).
# 2. Monitoring the queue of pending test ensembles (via /tools/ensemble_count.py).
# 3. Provisioning new Joshua agent jobs of its configured AGENT_NAME type if there
#    is demand and the total number of active Joshua jobs (of any type) in the
#    namespace is below the global MAX_JOBS limit.
# It uses kubectl for all Kubernetes interactions and is configured via
# environment variables such as BATCH_SIZE, MAX_JOBS, CHECK_DELAY, AGENT_NAME,
# FDB_CLUSTER_FILE, and AGENT_TAG (for the job template).
#
# This script is intended to work for joshua-agent and for joshua-rhel9-agent.

batch_size=${BATCH_SIZE:-1}
max_jobs=${MAX_JOBS:-10}
check_delay=${CHECK_DELAY:-10}
# Kubernetes 1.21 supports jobs TTL controller, which cleans up jobs automatically
# see https://kubernetes.io/docs/concepts/workloads/controllers/ttlafterfinished/
use_k8s_ttl_controller=${USE_K8S_TTL_CONTROLLER:-false}
restart_agents_on_boot=${RESTART_AGENTS_ON_BOOT:-false}

namespace=$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)

# Default AGENT_NAME to "joshua-agent" if not set or empty
export AGENT_NAME=${AGENT_NAME:-"joshua-agent"}

# if AGENT_TAG is not set through --build-arg,
# use the default agent image and tag
export AGENT_TAG=${AGENT_TAG:-"foundationdb/joshua-agent:latest"}

# Path to the FoundationDB cluster file
# This should be available within the pod, e.g., mounted from a ConfigMap
export FDB_CLUSTER_FILE=${FDB_CLUSTER_FILE:-"/etc/foundationdb/fdb.cluster"}

if [ $restart_agents_on_boot == true ]; then
    # mark existing jobs to exit after the current test completes
    kubectl -n ${namespace} label pods -l app=joshua-agent last_test=true --overwrite=true
fi

# run forever
while true; do

    if [ $use_k8s_ttl_controller == false ] ; then
      # cleanup finished jobs (status 1/1)
      # Filter by AGENT_NAME and check 3rd column for "1/1" (completions)
      for job in $(kubectl get jobs -n "${namespace}" --no-headers | { grep -E -e "^${AGENT_NAME}-[0-9]+(-[0-9]+)?\\s" || true; } | awk '$3 == "1/1" {print $1}'); do
          echo "=== Job $job Completed (1/1) - deleting from get jobs === (AGENT_NAME: ${AGENT_NAME})"
          kubectl delete job "$job" -n "${namespace}"
      done

      # cleanup failed/completed jobs by looking at pods for the current AGENT_NAME
      # pod name is always prefixed with the job name
      # e.g. "joshua-agent-XXXXXXXXXXXXXX-XX-yyyyy" or "joshua-rhel9-agent-XXXXXXXXXXXXXX-XX-yyyyy"
      # Filter pods by AGENT_NAME first, then by status, then extract job prefix
      # The number of fields to cut for the job prefix depends on the number of hyphens in AGENT_NAME itself, plus one for the timestamp part.
      num_hyphen_fields_in_agent_name=$(echo "${AGENT_NAME}" | awk -F'-' '{print NF}')
      job_prefix_fields=$((num_hyphen_fields_in_agent_name + 1))
      for job_prefix_from_pod in $(kubectl get pods -n "${namespace}" --no-headers | { grep -E "^${AGENT_NAME}-[0-9]+(-[0-9]+)?-" || true; } | { grep -E -e "Completed" -e "Error" || true; } | cut -f 1-${job_prefix_fields} -d '-'); do
          if [ -n "$job_prefix_from_pod" ]; then
            # Validate that the derived job_prefix_from_pod actually matches the expected format for this agent's jobs
            if [[ "${job_prefix_from_pod}" =~ ^${AGENT_NAME}-[0-9]+(-[0-9]+)?$ ]]; then
              echo "=== Deleting Job based on pod status: $job_prefix_from_pod === (AGENT_NAME: ${AGENT_NAME})"
              kubectl delete job "$job_prefix_from_pod" -n "${namespace}" --ignore-not-found=true
            else
              # This case can occur if AGENT_NAME is unusual (e.g., 'foo-bar' and a pod 'foo-bar-baz-TIMESTAMP-...' exists)
              # or if the pod naming doesn't strictly follow AGENT_NAME-TIMESTAMP-SUFFIX.
              # The initial grep on pods already ensures it starts with AGENT_NAME-TIMESTAMP_LIKE_PATTERN-,
              # so this condition means the 'cut' command resulted in a prefix not matching AGENT_NAME-TIMESTAMP.
              echo "=== WARNING: Pod for AGENT_NAME ${AGENT_NAME} yielded job prefix candidate '${job_prefix_from_pod}' that does not match expected pattern '^${AGENT_NAME}-[0-9]+(-[0-9]+)?$'. Skipping delete. ==="
            fi
          fi
      done
    fi

    # get the current ensembles
    # Pass the cluster file to the ensemble_count.py script
    if [ ! -f "${FDB_CLUSTER_FILE}" ]; then
        echo "ERROR: FDB Cluster File ${FDB_CLUSTER_FILE} not found! Cannot count ensembles. Assuming 0."
        num_ensembles=0
    else
        num_ensembles=$(python3 /tools/ensemble_count.py -C "${FDB_CLUSTER_FILE}")
    fi
    echo "${num_ensembles} ensembles in the queue (global)"

    # Calculate the number of all active Joshua jobs (any type)
    # Active jobs are those with .status.active > 0 (i.e., pods are running/pending but not yet succeeded/failed overall for the job)
    num_all_active_joshua_jobs=$(kubectl get jobs -n "${namespace}" -o 'jsonpath={range .items[?(@.status.active > 0)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep -Ec '^joshua-(rhel9-)?agent-[0-9]+(-[0-9]+)?$')
    echo "${num_all_active_joshua_jobs} total active joshua jobs any type are running. Global max_jobs: ${max_jobs}."

    new_jobs=0 # Initialize jobs to start this cycle for this scaler

    # Provision more jobs if global ensembles exist and the global max_jobs limit is not reached.
    if [ "${num_ensembles}" -gt 0 ] && [ "${num_all_active_joshua_jobs}" -lt "${max_jobs}" ]; then
        current_timestamp="$(date +%y%m%d%H%M%S)"

        # How many slots are available globally before hitting max_jobs
        slots_available_globally=$((max_jobs - num_all_active_joshua_jobs))

        # Determine how many jobs this scaler instance will attempt to start in this cycle
        num_to_attempt_this_cycle=${batch_size} # Start with batch_size as the base

        # If MAX_NEW_JOBS is set and is smaller than current num_to_attempt_this_cycle, respect it
        if [ -n "${MAX_NEW_JOBS}" ]; then
            if [ "${MAX_NEW_JOBS}" -lt "${num_to_attempt_this_cycle}" ]; then
                num_to_attempt_this_cycle=${MAX_NEW_JOBS}
            fi
        fi

        # The actual number of new jobs for this scaler is the minimum of what it wants to attempt 
        # and what's available globally.
        if [ "${num_to_attempt_this_cycle}" -gt "${slots_available_globally}" ]; then
            actual_new_jobs_for_this_scaler=${slots_available_globally}
        else
            actual_new_jobs_for_this_scaler=${num_to_attempt_this_cycle}
        fi
        
        # Ensure we are trying to start a positive number of jobs
        if [ "${actual_new_jobs_for_this_scaler}" -gt 0 ]; then
            new_jobs=${actual_new_jobs_for_this_scaler}
        fi

        idx=0
        if [ "${new_jobs}" -gt 0 ]; then
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
    fi
    # Standardized log message based on new_jobs calculated for this iteration for this agent type
    echo "${new_jobs} jobs of type ${AGENT_NAME} were targeted for starting in this iteration."

    # check every check_delay seconds
    sleep "${check_delay}"
done
exit 0

