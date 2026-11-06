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

# batch_size is how many joshua runs each pod instance is expected to do before the pod completes.
batch_size=${BATCH_SIZE:-1}
max_jobs=${MAX_JOBS:-10}
check_delay=${CHECK_DELAY:-10}
# Kubernetes 1.21 supports jobs TTL controller, which cleans up jobs automatically
# see https://kubernetes.io/docs/concepts/workloads/controllers/ttlafterfinished/
use_k8s_ttl_controller=${USE_K8S_TTL_CONTROLLER:-false}
restart_agents_on_boot=${RESTART_AGENTS_ON_BOOT:-false}

namespace=$(cat /var/run/secrets/kubernetes.io/serviceaccount/namespace)

# Default AGENT_NAME to "joshua-agent" if not set or empty
# Its 'joshua-rhel9-agent' for rockylinux9 instances.
export AGENT_NAME=${AGENT_NAME:-"joshua-agent"}

# Scaling configuration for large test suites
# For very large queues (>1000 ensembles), scale more aggressively
# For smaller queues, use normal scaling to be fair to other users

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

    # Let the Kubernetes TTL controller own finished-job retention and cleanup
    # when enabled, instead of scanning every job in the namespace here.
    if [ "$use_k8s_ttl_controller" == false ] ; then
        # Pod failures can be retried, and parallel Jobs may still have running pods.
        if jobs_to_delete=$(
            set -o pipefail
            kubectl get jobs -n "${namespace}" -o json | \
                jq -r --arg agent "${AGENT_NAME}" --argjson now "$(date +%s)" '
                    .items[]
                    | select(.metadata.name | startswith($agent + "-"))
                    | select(.metadata.name | ltrimstr($agent + "-") | test("^[0-9]+(-[0-9]+)?$"))
                    | select(
                        any(.status.conditions[]?; .type == "Complete" and .status == "True")
                        or (
                            any(.status.conditions[]?; .type == "Failed" and .status == "True")
                            and (.metadata.creationTimestamp | fromdateiso8601) < ($now - 86400)
                        )
                    )
                    | .metadata.name
                '
        ); then
            while IFS= read -r job; do
                [ -z "$job" ] && continue
                echo "Deleting terminal Job ${job}"
                kubectl delete job "$job" -n "${namespace}" --ignore-not-found=true
            done <<< "$jobs_to_delete"
        else
            echo "Failed to list terminal Jobs for ${AGENT_NAME}; skipping cleanup" >&2
        fi
    fi

    # Stop any ensembles that reached max_runs but weren't stopped due to
    # the snapshot read race in _insert_results.
    echo "$(date -Iseconds) Checking for stale completed ensembles ..."
    python3 /tools/stop_completed_ensembles.py -C "${FDB_CLUSTER_FILE}"

    # Get the current ensembles
    # Pass the cluster file to the ensemble_count.py script
    if [ ! -f "${FDB_CLUSTER_FILE}" ]; then
        echo "ERROR: FDB Cluster File ${FDB_CLUSTER_FILE} not found! Cannot count ensembles. Assuming 0."
        num_ensembles=0
    else
        num_ensembles=$(python3 /tools/ensemble_count.py -C "${FDB_CLUSTER_FILE}")
    fi
    echo "$(date -Iseconds) ${num_ensembles} ensembles in the queue (global)"

    # Calculate the number of all active Joshua jobs (any type) -- 'jobs' are effectively pod instances (a pod instance usually does batch_size joshua runs and then completes).
    # Active jobs are those with .status.active > 0 (i.e., pods are running/pending but not yet succeeded/failed overall for the job)
    num_all_active_joshua_jobs=$(kubectl get jobs -n "${namespace}" -o 'jsonpath={range .items[?(@.status.active > 0)]}{.metadata.name}{"\n"}{end}' 2>/dev/null | grep -Ec '^joshua-(rhel9-)?agent-[0-9]+(-[0-9]+)?$')
    echo "$(date -Iseconds) ${num_all_active_joshua_jobs} total active joshua jobs of any type that are running. Global max_jobs: ${max_jobs}."

    new_jobs=0 # Initialize jobs to start this cycle for this scaler

    # Provision more jobs if global ensembles exist and the global max_jobs limit is not reached.
    if [ "${num_ensembles}" -gt 0 ] && [ "${num_all_active_joshua_jobs}" -lt "${max_jobs}" ]; then
        current_timestamp="$(date +%y%m%d%H%M%S)"

        # How many slots are available globally before hitting max_jobs
        slots_available_globally=$((max_jobs - num_all_active_joshua_jobs))

        # Determine how many jobs to create. The goal is to create enough jobs to
        # process the entire queue, where each job is assumed to handle 'batch_size'
        # ensembles. This is then capped by various limits.

        # 1. Calculate the ideal number of jobs needed to clear the queue.
        #    This is ceil(num_ensembles / batch_size).
        if [ "${batch_size}" -gt 0 ]; then
            num_to_attempt=$(( (num_ensembles + batch_size - 1) / batch_size ))
        else
            # Avoid division by zero; fall back to one job per ensemble if batch_size is 0.
            num_to_attempt=${num_ensembles}
        fi

        # 2. The number of new jobs cannot exceed the globally available slots.
        if [ "${num_to_attempt}" -gt "${slots_available_globally}" ]; then
            num_to_attempt=${slots_available_globally}
        fi

        # 3. The number of new jobs cannot exceed the per-cycle limit, if one is set.
        # Simple scaling: 1000 jobs for very large queues, 100 for smaller queues
        if [ -n "${MAX_NEW_JOBS}" ]; then
            if [ "${num_ensembles}" -gt 1000 ]; then
                # For very large queues (>1000), allow up to 1000 jobs per cycle
                # This helps clear large test suites quickly while being fair
                large_queue_limit=1000
                if [ "${num_to_attempt}" -gt "${large_queue_limit}" ]; then
                    num_to_attempt=${large_queue_limit}
                fi
            else
                # For smaller queues, use normal MAX_NEW_JOBS to be fair to other users
                if [ "${num_to_attempt}" -gt "${MAX_NEW_JOBS}" ]; then
                    num_to_attempt=${MAX_NEW_JOBS}
                fi
            fi
        fi

        if [ "${num_to_attempt}" -gt 0 ]; then
            new_jobs=${num_to_attempt}
            if [ "${num_ensembles}" -gt 1000 ]; then
                echo "Large queue detected: ${num_ensembles} ensembles, targeting ${new_jobs} new jobs (large queue mode)"
            else
                echo "Normal scaling: ${num_ensembles} ensembles, targeting ${new_jobs} new jobs"
            fi
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
                    printf '\n---\n' >>/tmp/joshua-agent.yaml
                    ((idx++))
                    ((i++))
                    if [ "${idx}" -ge ${new_jobs} ]; then
                        break
                    fi
                done
                # /tmp/joshua-agent.yaml contains up to $batch_size entries
                echo "Starting ${i} jobs"
                kubectl apply -f /tmp/joshua-agent.yaml -n "${namespace}"
            done
        fi
    fi
    # Standardized log message based on new_jobs calculated for this iteration for this agent type
    echo "$(date -Iseconds) ${new_jobs} jobs of type ${AGENT_NAME} were targeted for starting in this iteration."

    # Use consistent check delay for all queue sizes
    adaptive_delay=${check_delay}
    
    # check every adaptive_delay seconds
    sleep "${adaptive_delay}"
done
exit 0

