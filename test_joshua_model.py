import io
import joshua.joshua as joshua
import joshua.joshua_agent as joshua_agent
import joshua.joshua_model as joshua_model
import os
import pytest
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import threading
import time

import fdb

fdb.api_version(520)


#################### Fixtures ####################
# https://docs.pytest.org/en/stable/fixture.html


def getFreePort():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    addr = s.getsockname()
    result = addr[1]
    s.close()
    return result


def empty_ensemble_factory(tmp_path, succeed):
    """
    Returns a filename whose contents is a tarball containing a no-op joshua_test and joshua_timeout
    """
    ensemble_file_name = os.path.join(tmp_path, "ensemble.tar.gz")
    ensemble = tarfile.open(ensemble_file_name, "w:gz")
    script = "#!/bin/bash\n{}".format("true" if succeed else "false").encode("utf-8")
    joshua_test = tarfile.TarInfo("joshua_test")
    joshua_test.mode = 0o755
    joshua_test.size = len(script)
    joshua_timeout = tarfile.TarInfo("joshua_timeout")
    joshua_timeout.mode = 0o755
    joshua_timeout.size = len(script)
    ensemble.addfile(joshua_test, io.BytesIO(script))
    ensemble.addfile(joshua_timeout, io.BytesIO(script))
    ensemble.close()
    return ensemble_file_name


@pytest.fixture
def empty_ensemble(tmp_path):
    """
    Returns a filename whose contents is a tarball containing a passing joshua_test and joshua_timeout
    """
    yield empty_ensemble_factory(tmp_path, True)


@pytest.fixture
def empty_ensemble_fail(tmp_path):
    """
    Returns a filename whose contents is a tarball containing a failing joshua_test and joshua_timeout
    """
    yield empty_ensemble_factory(tmp_path, False)


@pytest.fixture(scope="session", autouse=True)
def fdb_cluster():
    """
    Provision an fdb cluster for the entire test session, and call
    joshua_model.open() Tear down when the test session ends.
    """
    # Setup
    tmp_dir = tempfile.mkdtemp()
    port = getFreePort()
    cluster_file = os.path.join(tmp_dir, "fdb.cluster")
    with open(cluster_file, "w") as f:
        f.write("abdcefg:abcdefg@127.0.0.1:{}".format(port))
    proc = subprocess.Popen(
        ["fdbserver", "-p", "auto:{}".format(port), "-C", cluster_file], cwd=tmp_dir
    )

    subprocess.check_output(
        ["fdbcli", "-C", cluster_file, "--exec", "configure new single ssd"]
    )

    joshua_model.open(cluster_file)
    yield cluster_file

    # Teardown
    proc.kill()
    proc.wait()
    shutil.rmtree(tmp_dir)


@pytest.fixture(scope="function", autouse=True)
def clear_db(fdb_cluster):
    """
    Clear the db before each test
    """
    subprocess.check_output(
        ["fdbcli", "-C", fdb_cluster, "--exec", 'writemode on; clearrange "" \xff']
    )


#################### Tests ####################
# Each function starting with `test_` will get
# run by pytest, with an empty db.


@fdb.transactional
def get_passes(tr: fdb.Transaction, ensemble_id: str) -> int:
    return joshua_model._get_snap_counter(tr, ensemble_id, "pass")


@fdb.transactional
def get_fails(tr: fdb.Transaction, ensemble_id: str) -> int:
    return joshua_model._get_snap_counter(tr, ensemble_id, "fail")


def test_create_ensemble():
    assert len(joshua_model.list_active_ensembles()) == 0
    ensemble_id = joshua_model.create_ensemble("joshua", {}, io.BytesIO())
    assert len(joshua_model.list_active_ensembles()) > 0


def test_agent(tmp_path, empty_ensemble):
    """
    :tmp_path: https://docs.pytest.org/en/stable/tmpdir.html
    """
    assert len(joshua_model.list_active_ensembles()) == 0
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(empty_ensemble, "rb")
    )
    agent = threading.Thread(
        target=joshua_agent.agent,
        args=(),
        kwargs={
            "work_dir": tmp_path,
            "agent_idle_timeout": 1,
        },
    )
    agent.setDaemon(True)
    agent.start()
    joshua.tail_ensemble(ensemble_id, username="joshua")
    agent.join()


def test_dead_agent(tmp_path, empty_ensemble):
    """
    :tmp_path: https://docs.pytest.org/en/stable/tmpdir.html
    """
    assert len(joshua_model.list_active_ensembles()) == 0
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1, "timeout": 1}, open(empty_ensemble, "rb")
    )
    # simulate another agent dying after incrementing started but before incrementing ended
    @fdb.transactional
    def incr_start(tr):
        joshua_model._increment(tr, ensemble_id, "started")

    incr_start(joshua_model.db)

    agent = threading.Thread(
        target=joshua_agent.agent,
        args=(),
        kwargs={
            "work_dir": tmp_path,
            "agent_idle_timeout": 1,
        },
    )
    agent.setDaemon(True)
    agent.start()

    # Ensemble should still eventually end
    joshua.tail_ensemble(ensemble_id, username="joshua")
    agent.join()


def test_two_agents(tmp_path, empty_ensemble):
    """
    :tmp_path: https://docs.pytest.org/en/stable/tmpdir.html
    """

    @fdb.transactional
    def get_started(tr):
        return joshua_model._get_snap_counter(tr, ensemble_id, "started")

    assert len(joshua_model.list_active_ensembles()) == 0
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1, "timeout": 1}, open(empty_ensemble, "rb")
    )

    agents = []
    for rank in range(2):
        agent = threading.Thread(
            target=joshua_agent.agent,
            args=(),
            kwargs={
                "work_dir": os.path.join(tmp_path, str(rank)),
                "agent_idle_timeout": 1,
            },
        )
        agent.setDaemon(True)
        agent.start()
        agents.append(agent)
        # before starting agent two, wait until agent one has started on this ensemble
        while get_started(joshua_model.db) != 1:
            time.sleep(0.001)

    joshua.tail_ensemble(ensemble_id, username="joshua")

    @fdb.transactional
    def get_started(tr):
        return joshua_model._get_snap_counter(tr, ensemble_id, "started")

    # The second agent won't have started this ensemble (unless somehow > 10
    # seconds passed without the first agent completing the ensemble)
    assert get_started(joshua_model.db) == 1

    for agent in agents:
        agent.join()


def test_two_ensembles_memory_usage(tmp_path, empty_ensemble):
    """
    :tmp_path: https://docs.pytest.org/en/stable/tmpdir.html
    """
    assert len(joshua_model.list_active_ensembles()) == 0
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1, "timeout": 1}, open(empty_ensemble, "rb")
    )
    agent = threading.Thread(
        target=joshua_agent.agent,
        args=(),
        kwargs={
            "work_dir": tmp_path,
            "agent_idle_timeout": 1,
        },
    )
    agent.setDaemon(True)
    agent.start()

    # Ensemble one should eventually end
    joshua.tail_ensemble(ensemble_id, username="joshua")

    # Start ensemble two
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1, "timeout": 1}, open(empty_ensemble, "rb")
    )

    # inserting the second ensemble should remove the in-memory state for the first one
    assert len(joshua_model._ensemble_progress_tracker._last_ensemble_progress) == 1

    # Ensemble two should eventually end
    joshua.tail_ensemble(ensemble_id, username="joshua")
    agent.join()


def test_ensemble_passes(tmp_path, empty_ensemble):
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1, "timeout": 1}, open(empty_ensemble, "rb")
    )
    agent = threading.Thread(
        target=joshua_agent.agent,
        args=(),
        kwargs={
            "work_dir": tmp_path,
            "agent_idle_timeout": 1,
        },
    )
    agent.setDaemon(True)
    agent.start()
    joshua.tail_ensemble(ensemble_id, username="joshua")
    agent.join()

    assert get_passes(joshua_model.db, ensemble_id) >= 1
    assert get_fails(joshua_model.db, ensemble_id) == 0


def test_ensemble_fails(tmp_path, empty_ensemble_fail):
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1, "timeout": 1}, open(empty_ensemble_fail, "rb")
    )
    agent = threading.Thread(
        target=joshua_agent.agent,
        args=(),
        kwargs={
            "work_dir": tmp_path,
            "agent_idle_timeout": 1,
        },
    )
    agent.setDaemon(True)
    agent.start()
    joshua.tail_ensemble(ensemble_id, username="joshua")
    agent.join()

    assert get_passes(joshua_model.db, ensemble_id) == 0
    assert get_fails(joshua_model.db, ensemble_id) >= 1
