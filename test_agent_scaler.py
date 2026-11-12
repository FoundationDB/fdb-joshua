import json
import os
import pathlib
import subprocess

import pytest


@pytest.mark.parametrize("mode", ["cleanup", "ttl", "api-error", "invalid-timestamp"])
def testCleanupUsesTerminalJobConditions(mode):
    def job(name, status, created="1970-01-01T00:00:00Z"):
        return {
            "metadata": {"name": name, "creationTimestamp": created},
            "status": status,
        }

    complete = {"conditions": [{"type": "Complete", "status": "True"}]}
    failed = {"conditions": [{"type": "Failed", "status": "True"}]}
    jobs = [
        job("joshua-agent-100-0", {"active": 3, "succeeded": 1}),
        job("joshua-agent-100-1", {"active": 3, "failed": 1}),
        job("joshua-agent-100-2", {"succeeded": 4, **complete}),
        job("joshua-agent-100-3", failed, "1970-01-03T00:00:00Z"),
        job("joshua-agent-100-4", failed),
        job("joshua-rhel9-agent-100-5", complete),
        job("joshua-agent-100-6", {"conditions": [{"type": "Complete", "status": "False"}]}),
        job("joshua-agent-100-7-extra", complete),
        job("joshua-agent-101", complete),
        job("joshua-agent-102", {}),
    ]
    if mode == "invalid-timestamp":
        jobs.append(job("joshua-agent-103", failed, "invalid"))

    # Run one scaler cycle; only the Kubernetes API, FDB tools and clock are replaced.
    result = subprocess.run(
        [
            "bash", "-c", r'''
                cat() { printf 'test-namespace\n'; }
                date() { printf '172800\n'; }
                python3() { :; }
                sleep() { exit 0; }
                kubectl() {
                    case "$*" in
                        "get jobs -n test-namespace -o json")
                            printf '%s\n' "$JOBS_JSON"
                            return "$KUBECTL_EXIT"
                            ;;
                        "get jobs "*) ;;
                        "delete job "*) printf 'DELETE %s\n' "$3" ;;
                        *) echo "Unexpected kubectl call: $*" >&2; exit 1 ;;
                    esac
                }
                source "$1"
            ''',
            "test-agent-scaler",
            str(pathlib.Path(__file__).parent / "k8s/agent-scaler/agent-scaler.sh"),
        ],
        env={
            **os.environ,
            "AGENT_NAME": "joshua-agent",
            "USE_K8S_TTL_CONTROLLER": str(mode == "ttl").lower(),
            "RESTART_AGENTS_ON_BOOT": "false",
            "FDB_CLUSTER_FILE": "/dev/null",
            "JOBS_JSON": json.dumps({"items": jobs}),
            "KUBECTL_EXIT": "1" if mode == "api-error" else "0",
        },
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    deleted = [line.removeprefix("DELETE ") for line in result.stdout.splitlines() if line.startswith("DELETE ")]
    assert deleted == (["joshua-agent-100-2", "joshua-agent-100-4", "joshua-agent-101"] if mode == "cleanup" else [])
    if mode in ("api-error", "invalid-timestamp"):
        assert "skipping cleanup" in result.stderr
