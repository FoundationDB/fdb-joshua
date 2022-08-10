import io
import joshua.joshua as joshua
import joshua.joshua_agent as joshua_agent
import joshua.joshua_model as joshua_model
import math
import os
import pathlib
import pytest
import random
import shutil
import socket
import subprocess
import tarfile
import tempfile
import threading
import threading
import time

from typing import BinaryIO

import fdb

fdb.api_version(630)


#################### Fixtures ####################
# https://docs.pytest.org/en/stable/fixture.html


def getFreePort():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    addr = s.getsockname()
    result = addr[1]
    s.close()
    return result

class EnsembleFactory:
    def __init__(self, tmp_path):
        self.file_name = os.path.join(tmp_path, "ensemble.tar.gz")
        self.ensemble = tarfile.open(self.file_name, "w:gz")

    @staticmethod
    def with_script(tmp_path, script_contents):
        factory = EnsembleFactory(tmp_path)
        factory.add_bash_script("joshua_test", script_contents)
        factory.add_bash_script("joshua_timeout", script_contents)
        return factory

    def add_bash_script(self, name, contents):
        script = "#!/bin/bash\n{}".format(contents).encode("utf-8")
        entry = tarfile.TarInfo(name)
        entry.mode = 0o755
        entry.size = len(script)
        self.ensemble.addfile(entry, io.BytesIO(script))

    def add_executable(self, name, f: BinaryIO):
        contents: bytes = f.read()
        entry = tarfile.TarInfo(name)
        entry.mode = 0o755
        entry.size = len(contents)
        self.ensemble.addfile(entry, io.BytesIO(contents))

    def done(self) -> None:
        self.ensemble.close()

def empty_ensemble_factory(tmp_path, script_contents):
    """
    Returns a filename whose contents is a tarball containing a joshua_test (with script_contents) and joshua_timeout
    """
    factory = EnsembleFactory.with_script(tmp_path, script_contents)
    factory.done()
    return factory.file_name


@pytest.fixture
def empty_ensemble(tmp_path):
    """
    Returns a filename whose contents is a tarball containing a passing joshua_test and joshua_timeout
    """
    yield empty_ensemble_factory(tmp_path, "true")


@pytest.fixture
def empty_ensemble_timeout(tmp_path):
    """
    Returns a filename whose contents is a tarball containing a joshua_test that will hang forever
    """
    yield empty_ensemble_factory(tmp_path, "sleep 100000")


@pytest.fixture
def empty_ensemble_fail(tmp_path):
    """
    Returns a filename whose contents is a tarball containing a failing joshua_test and joshua_timeout
    """
    yield empty_ensemble_factory(tmp_path, "false")

@pytest.fixture
def empty_ensemble_joshua_done(tmp_path):
    factory = EnsembleFactory.with_script(tmp_path, "true")
    factory.add_bash_script('joshua_done', './joshua_done_test.py $2 $6')
    with pathlib.Path(__file__).parent.joinpath('joshua_done_test.py').open('rb') as f:
        factory.add_executable("joshua_done_test.py", f)
    factory.done()
    yield factory.file_name


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
        "joshua/joshua", {"max_runs": 1}, open(empty_ensemble, "rb")
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
    joshua.tail_ensemble(ensemble_id, username="joshua/joshua")
    agent.join()


def test_stop_ensemble(tmp_path, empty_ensemble):
    """
    :tmp_path: https://docs.pytest.org/en/stable/tmpdir.html
    """
    assert len(joshua_model.list_active_ensembles()) == 0
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1e12}, open(empty_ensemble, "rb")
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
    while len(joshua_model.show_in_progress(ensemble_id)) == 0:
        time.sleep(0.001)
    joshua.stop_ensemble(ensemble_id, username="joshua")
    assert joshua_model.show_in_progress(ensemble_id) == []
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

    # simulate another agent dying after starting a test
    assert joshua_model.try_starting_test(ensemble_id, 12345)

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


def test_delete_ensemble(tmp_path, empty_ensemble_timeout):
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 10, "timeout": 1}, open(empty_ensemble_timeout, "rb")
    )
    agents = []
    for rank in range(10):
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
    time.sleep(0.5)  # Give the agents some time to start
    joshua_model.delete_ensemble(ensemble_id)
    time.sleep(1)  # Wait for long enough that agents timeout
    assert len(joshua_model.list_all_ensembles()) == 0

    for agent in agents:
        agent.join()


@fdb.transactional
def verify_application_state(tr, ensemble, num_runs):
    dir_path = joshua_model.get_application_dir(ensemble)
    print('dir_path = ({})'.format(",".join(list(dir_path))))
    ensemble_dir = fdb.directory.open(tr, dir_path)
    count = 0
    for _, _ in tr[ensemble_dir.range()]:
        count += 1
    assert count == num_runs


def test_joshua_done_ensemble(tmp_path, empty_ensemble_joshua_done):
    max_runs: int = random.randint(1, 32)
    ensemble_id = joshua_model.create_ensemble('joshua', {"max_runs": max_runs},
                                               open(empty_ensemble_joshua_done, 'rb'))
    agents = []
    for rank in range(10):
        agent = threading.Thread(
            target=joshua_agent.agent,
            args=(),
            kwargs={
                "work_dir": os.path.join(tmp_path, str(rank)),
                "agent_idle_timeout": 1,
            },)
        agent.start()
        agents.append(agent)
    # wait for agents to finish
    for agent in agents:
        agent.join()
    verify_application_state(joshua_model.db, ensemble_id, max_runs)


class ThreadSafeCounter:
    def __init__(self):
        self.lock = threading.Lock()
        self.counter = 0

    def increment(self):
        with self.lock:
            self.counter += 1

    def get(self):
        with self.lock:
            return self.counter


def test_two_agents_large_ensemble(monkeypatch, tmp_path, empty_ensemble):
    """
    :monkeypatch: https://docs.pytest.org/en/stable/monkeypatch.html
    :tmp_path: https://docs.pytest.org/en/stable/tmpdir.html
    """

    # Make downloading an ensemble take an extra second, and increment
    # downloads_started at the beginning of downloading
    downloads_started = ThreadSafeCounter()

    def ensure_state_test_delay():
        downloads_started.increment()
        time.sleep(1)

    monkeypatch.setattr(
        joshua_agent, "ensure_state_test_delay", ensure_state_test_delay
    )

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
        while True:
            # Wait until the first agent has begun downloading before starting the second agent
            if downloads_started.get() > 0:
                break
            time.sleep(0.01)

    joshua.tail_ensemble(ensemble_id, username="joshua")

    @fdb.transactional
    def get_started(tr):
        return joshua_model._get_snap_counter(tr, ensemble_id, "started")

    assert get_started(joshua_model.db) == 1

    for agent in agents:
        agent.join()
