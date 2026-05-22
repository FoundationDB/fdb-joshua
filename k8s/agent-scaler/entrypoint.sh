#!/bin/sh
case "${SCALER_IMPL:-bash}" in
  go) exec /usr/local/bin/agent-scaler ;;
  *)  exec /tools/agent-scaler.sh ;;
esac
