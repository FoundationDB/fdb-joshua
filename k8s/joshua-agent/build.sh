#!/bin/bash

set -euo pipefail

usage() {
  echo "Usage: $0 [--minikube] <tag>"
}

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  usage
  exit 0
fi

tag=
if [ $# -eq 2 ]; then
  if [ "$1" == "--minikube" ]; then
    eval $(minikube docker-env)
    shift
  else
    usage
    exit 0
  fi
fi
tag=$1

# build the base image
cd ../../Docker
./build_docker.sh 1
cd -

# build k8s joshua-agent image
docker build --network host -t "${tag}" .
rc=$?
if [ $rc -ne 0 ]; then
  echo "Error: docker build failed $rc"
  exit $rc
fi

docker images

exit 0
