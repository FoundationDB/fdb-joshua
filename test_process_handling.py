import os
import subprocess

import psutil

import joshua.process_handling as process_handling


def test_mark_environment():
    env = process_handling.mark_environment({"FOO": "bar"})
    assert env == {"FOO": "bar", process_handling.VAR_NAME: str(os.getpid())}


def test_kill_all_children():
    env = process_handling.mark_environment(os.environ)
    marked = [subprocess.Popen(["sleep", "100"], env=env) for _ in range(3)]
    # A marked grandchild which is orphaned when its parent shell exits
    orphan_pid = int(
        subprocess.check_output(["sh", "-c", "sleep 100 >/dev/null & echo $!"], env=env)
    )
    unmarked = subprocess.Popen(["sleep", "100"])
    try:
        children = {p.pid for p in process_handling.retrieve_children()}
        assert children == {p.pid for p in marked} | {orphan_pid}

        assert process_handling.kill_all_children()
        assert process_handling.retrieve_children() == []
        assert all(p.poll() is not None for p in marked)
        assert not psutil.pid_exists(orphan_pid) or (
            psutil.Process(orphan_pid).status() == psutil.STATUS_ZOMBIE
        )
        assert unmarked.poll() is None
    finally:
        unmarked.kill()
        unmarked.wait()


def test_kill_all_children_none():
    assert process_handling.retrieve_children() == []
    assert process_handling.kill_all_children()
