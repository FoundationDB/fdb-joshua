#!/usr/bin/env bash
set -Eeuo pipefail

RUN_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd -P)
COMMIT_HASH=$(git rev-parse --short=10  HEAD)
DATE_STR=$(date +"%Y%m%d%H%M%S")
FDB_VERSION=$(curl -Ls https://www.foundationdb.org/downloads/version.txt)

################################################################################
# joshua-agent
################################################################################
docker build \
  --build-arg REPOSITORY=foundationdb/build \
  --build-arg FDB_VERSION="${FDB_VERSION}" \
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
  --build-arg FDB_VERSION="${FDB_VERSION}" \
  --tag foundationdb/agent-scaler:"${DATE_STR}-${COMMIT_HASH}" \
  --tag foundationdb/agent-scaler:latest \
  .