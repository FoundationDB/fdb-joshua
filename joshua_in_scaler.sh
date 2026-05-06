#!/bin/bash
# joshua_in_scaler.sh - Run joshua commands against EKS cluster
#
# This script enables Joshua CLI access when Joshua is not installed locally on remote pod.
# It uses the agent-scaler pod as a proxy: copies your local joshua.py source
# to the pod (which has database access) and executes commands there, remotely.
#
# Usage: joshua_remote_cli.sh --context <context> [--joshua-dir <dir>] [--rhel9] <command> [args...]

# Environment variables with expected values:
# JOSHUA_CONTEXT: kubectl context name or EKS ARN (e.g., "arn:aws:eks:us-west-2:123456789:cluster/my-cluster")
# JOSHUA_SCALER: scaler type - "regular" (default) or "rhel9"
CONTEXT="${JOSHUA_CONTEXT:-}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JOSHUA_CHECKOUT="${JOSHUA_DIR:-$SCRIPT_DIR}"
SCALER_TYPE="${JOSHUA_SCALER:-regular}"

# Parse named arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --context|-c)
            CONTEXT="$2"
            shift 2
            ;;
        --rhel9)
            SCALER_TYPE="rhel9"
            shift
            ;;
        *)
            break
            ;;
    esac
done

if [ -z "$CONTEXT" ]; then
    echo "Error: --context is required (or set JOSHUA_CONTEXT env var)"
    echo "Usage: $0 --context <k8s-context> [--rhel9] <command> [args...]"
    exit 1
fi

JOSHUA_PY=$(find ${JOSHUA_CHECKOUT} -name "joshua.py" -print)
if [ -z "$JOSHUA_PY" ]; then
    echo "Error: Could not find joshua.py in ${JOSHUA_CHECKOUT}"
    exit 1
fi

if [ "$SCALER_TYPE" = "rhel9" ]; then
    SCALER_POD=$(kubectl --context "${CONTEXT}" get pods -l app=agent-scaler-rhel9 -o jsonpath='{.items[0].metadata.name}')
else
    SCALER_POD=$(kubectl --context "${CONTEXT}" get pods -l app=agent-scaler -o jsonpath='{.items[0].metadata.name}')
fi

if [ -z "$SCALER_POD" ]; then
    echo "Error: Could not find agent-scaler pod (type: $SCALER_TYPE)"
    exit 1
fi

# Copy joshua.py with patched imports (remove lxml dependency, fix relative imports for pod environment)
TEMP_J=$(mktemp)
sed -e 's/import lxml.etree as le/le = None/' \
    -e 's/from \. import joshua_model/import joshua_model/' \
    "$JOSHUA_PY" >"$TEMP_J"

# write it and run it in one remote-exec
kubectl --context "$CONTEXT" exec -i "$SCALER_POD" -- /bin/sh -c \
    'J=$(mktemp /tmp/joshua.XXXXXX.py) && cat >$J && PYTHONPATH=/tools python3 $J -C /etc/foundationdb/fdb.cluster "$@"' -- "$@" \
    <"$TEMP_J"

STATUS=$?
rm "$TEMP_J"
exit $STATUS
