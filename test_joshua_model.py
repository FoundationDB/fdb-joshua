import hashlib
import io
import math
import os
import pathlib
import random
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
from typing import BinaryIO

import boto3
import psutil
import pytest
from moto import mock_s3

import fdb

import joshua.joshua as joshua
import joshua.joshua_agent as joshua_agent
import joshua.joshua_model as joshua_model
import joshua.process_handling as process_handling


fdb.api_version(710)


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
        script = f"#!/bin/bash\n{contents}".encode("utf-8")
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
        f.write(f"abdcefg:abcdefg@127.0.0.1:{port}")
    proc = subprocess.Popen(
        ["fdbserver", "-p", f"auto:{port}", "-C", cluster_file], cwd=tmp_dir
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


@pytest.fixture
def agents_in_threads(monkeypatch):
    """
    For running multiple agents as threads in this process: mark subprocesses
    per thread instead of per process, so one agent's cleanup doesn't kill the
    subprocesses of another agent's run. (Each run marks its environment and
    cleans up in the same thread.)
    """
    mark_environment = process_handling.mark_environment
    kill_all_children = process_handling.kill_all_children

    def marker():
        return f"{os.getpid()}-{threading.get_ident()}"

    monkeypatch.setattr(
        process_handling, "mark_environment", lambda env: mark_environment(env, pid=marker())
    )
    monkeypatch.setattr(
        process_handling, "kill_all_children", lambda: kill_all_children(pid=marker())
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


@pytest.mark.parametrize("stop", ["cli", "quiet-cli", "model"])
def test_stop_ensembles_by_owner(stop, monkeypatch):
    owned = joshua_model.create_ensemble("custom-id", {"username": "alice"}, io.BytesIO())
    other = joshua_model.create_ensemble("alice", {"username": "bob"}, io.BytesIO())

    monkeypatch.setenv("JOSHUA_USER", "")
    with pytest.raises(Exception, match="unspecified user"):
        if stop == "model":
            joshua_model.stop_user_ensembles("")
        else:
            joshua.stop_ensemble(printable=stop == "cli")
    assert {name for name, _ in joshua_model.list_active_ensembles()} == {owned, other}

    if stop == "model":
        joshua_model.stop_user_ensembles("alice")
    else:
        joshua.stop_ensemble(username="alice", printable=stop == "cli")

    assert [name for name, _ in joshua_model.list_active_ensembles()] == [other]
    assert "stopped" in joshua_model.get_ensemble_properties(owned)
    assert "stopped" not in joshua_model.get_ensemble_properties(other)


def test_prepared_ensemble_invisible_until_activated():
    properties = {}
    contents = b"prepared ensemble data"
    ensemble = joshua_model.prepare_ensemble("joshua", properties, io.BytesIO(contents))
    assert joshua_model.list_all_ensembles() == []
    result = io.BytesIO()
    joshua_model.get_ensemble_data(ensemble, result)
    assert result.getvalue() == contents

    joshua_model._create_ensemble(joshua_model.db, ensemble, properties)
    assert [name for name, _ in joshua_model.list_active_ensembles()] == [ensemble]


def test_create_stop_one_transaction():
    properties = {"submitted": "20000101-000000"}
    ensemble = joshua_model.prepare_ensemble("joshua", properties, io.BytesIO())

    @fdb.transactional
    def createAndStop(tr):
        joshua_model._create_ensemble(tr, ensemble, properties)
        joshua_model._stop_ensemble(tr, ensemble)

    createAndStop(joshua_model.db)
    assert joshua_model.list_active_ensembles() == []
    stopped = joshua_model.get_ensemble_properties(ensemble)
    expected_runtime = joshua_model.load_datetime(stopped["stopped"]) - joshua_model.load_datetime(properties["submitted"])
    assert joshua_model.load_timedelta(stopped["runtime"]) == expected_runtime


@pytest.mark.parametrize(
    ("properties", "expected_weight"),
    [
        ({"priority": 5}, 0.05),
        ({}, 1.0),
        ({"priority": 0}, 1.0),
        ({"priority": "invalid"}, 1.0),
    ],
    ids=["submitted", "omitted", "nonpositive", "malformed"],
)
def test_scheduler_uses_submitted_priority_or_default(properties, expected_weight):
    ensemble_id = joshua_model.create_ensemble("joshua", properties, io.BytesIO())
    assert joshua_model.get_ensemble_priorities([ensemble_id]) == {
        ensemble_id: expected_weight
    }


def test_invalid_claim_shard_count_does_not_upload_data():
    @fdb.transactional
    def get_ensemble_data_keys(tr):
        return list(tr[joshua_model.dir_ensemble_data.range()])

    with pytest.raises(ValueError):
        joshua_model.create_ensemble(
            "joshua",
            {
                "max_runs": 1,
                joshua_model.CLAIM_SHARD_COUNT_PROPERTY: "bogus",
            },
            io.BytesIO(b"unused tarball data"),
        )

    assert get_ensemble_data_keys(joshua_model.db) == []
    assert joshua_model.list_active_ensembles() == []


def test_remote_tarball_url_detection():
    assert joshua_model.is_remote_tarball_url("s3://bucket/path/to/tarball.tar.gz")
    assert joshua_model.is_remote_tarball_url(
        "https://account.blob.core.windows.net/container/tarball.tar.gz?sig=abc"
    )
    assert not joshua_model.is_remote_tarball_url("/tmp/tarball.tar.gz")


def test_validate_ensemble(tmp_path, empty_ensemble):
    outfile = str(tmp_path) + "/" + "outfile"
    assert len(joshua_model.list_active_ensembles()) == 0

    # create ensemble
    with open(empty_ensemble, "rb") as fin:
        orighash = joshua_model.get_hash(fin)
        assert orighash
        print(orighash)
        ensemble_id = joshua_model.create_ensemble("joshua", {}, fin)
        assert len(joshua_model.list_active_ensembles()) > 0

    # get ensemble
    with open(outfile, "wb") as fout:
        joshua_model.get_ensemble_data(ensemble_id=ensemble_id, outfile=fout)
    with open(outfile, "rb") as fout:
        newhash = joshua_model.get_hash(fout)
    assert newhash
    print(newhash)
    assert orighash == newhash

@mock_s3
def test_validate_ensemble_s3(tmp_path, empty_ensemble):
    bucket="test_bucket"
    ensemble_path="tests" + "/" + empty_ensemble
    s3url="s3://" + bucket + "/" + ensemble_path
    outfile = str(tmp_path) + "/" + "outfile"

    with open(empty_ensemble, "rb") as fin:
        orighash = joshua_model.get_hash(fin)
        assert orighash
        print(orighash)

    # upload ensemble to s3
    s3 = boto3.resource("s3")
    s3.create_bucket(Bucket="test_bucket")
    client = boto3.client("s3")
    _ = client.upload_file(empty_ensemble, bucket, ensemble_path)

    # create ensemble
    assert len(joshua_model.list_active_ensembles()) == 0
    ensemble_id = joshua_model.create_ensemble("joshua", {}, s3url, False, True)
    assert len(joshua_model.list_active_ensembles()) > 0

    # get ensemble
    with open(outfile, "wb") as fout:
        joshua_model.get_ensemble_data(ensemble_id=ensemble_id, outfile=fout)
    with open(outfile, "rb") as fout:
        newhash = joshua_model.get_hash(fout)
    assert newhash
    print(newhash)
    assert orighash == newhash


def test_validate_ensemble_azure_blob(monkeypatch, tmp_path, empty_ensemble):
    azure_blob_url = (
        "https://testaccount.blob.core.windows.net/test-container/tests/ensemble.tar.gz"
    )
    outfile = str(tmp_path) + "/" + "outfile"

    with open(empty_ensemble, "rb") as fin:
        contents = fin.read()
        fin.seek(0)
        orighash = joshua_model.get_hash(fin)
        assert orighash

    class FakeContentSettings:
        content_md5 = hashlib.md5(contents).digest()

    class FakeBlobProperties:
        content_settings = FakeContentSettings()
        etag = '"unused-etag"'

    class FakeDownload:
        def readall(self):
            return contents

    class FakeBlobClient:
        def get_blob_properties(self):
            return FakeBlobProperties()

        def download_blob(self):
            return FakeDownload()

    monkeypatch.setattr(
        joshua_model, "_get_azure_blob_client", lambda blob_url: FakeBlobClient()
    )

    assert len(joshua_model.list_active_ensembles()) == 0
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {}, azure_blob_url, False, True
    )
    assert len(joshua_model.list_active_ensembles()) > 0

    with open(outfile, "wb") as fout:
        joshua_model.get_ensemble_data(ensemble_id=ensemble_id, outfile=fout)
    with open(outfile, "rb") as fout:
        newhash = joshua_model.get_hash(fout)
    assert newhash
    assert orighash == newhash
    assert (
        joshua_model.get_ensemble_properties(ensemble_id)["azure_blob_url"]
        == azure_blob_url
    )


def test_azure_blob_client_uses_workload_identity(monkeypatch):
    import azure.identity
    from azure.storage.blob import BlobClient

    blob_url = "https://testaccount.blob.core.windows.net/test-container/test.tar.gz"
    expected_credential = object()
    captured = {}

    def fake_credential(**kwargs):
        captured["credential_kwargs"] = kwargs
        return expected_credential

    def fake_blob_client(url, **kwargs):
        captured["url"] = url
        captured["blob_kwargs"] = kwargs
        return object()

    monkeypatch.setenv("AZURE_TENANT_ID", "tenant-id")
    monkeypatch.setenv("AZURE_CLIENT_ID", "client-id")
    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/var/run/secrets/azure/token")
    monkeypatch.setattr(azure.identity, "WorkloadIdentityCredential", fake_credential)
    monkeypatch.setattr(BlobClient, "from_blob_url", staticmethod(fake_blob_client))

    joshua_model._get_azure_blob_client(blob_url)

    assert captured["credential_kwargs"] == {
        "tenant_id": "tenant-id",
        "client_id": "client-id",
        "token_file_path": "/var/run/secrets/azure/token",
    }
    assert captured["url"] == blob_url
    assert captured["blob_kwargs"] == {"credential": expected_credential}


def test_azure_blob_client_preserves_url_credentials(monkeypatch):
    from azure.storage.blob import BlobClient

    blob_url = (
        "https://testaccount.blob.core.windows.net/test-container/test.tar.gz"
        "?sv=test&sig=test-signature"
    )
    captured = {}

    def fake_blob_client(url, **kwargs):
        captured["url"] = url
        captured["blob_kwargs"] = kwargs
        return object()

    monkeypatch.setenv("AZURE_FEDERATED_TOKEN_FILE", "/var/run/secrets/azure/token")
    monkeypatch.setattr(BlobClient, "from_blob_url", staticmethod(fake_blob_client))

    joshua_model._get_azure_blob_client(blob_url)

    assert captured == {"url": blob_url, "blob_kwargs": {}}


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
    agent.daemon = True
    agent.start()
    joshua.tail_ensemble(ensemble_id, username="joshua/joshua")
    agent.join()


def test_agent_timeout_with_all_runs_claimed(tmp_path, empty_ensemble):
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(empty_ensemble, "rb")
    )
    assert joshua_model.try_starting_test(ensemble_id, 12345)
    assert not joshua_model.should_run_ensemble(ensemble_id)

    stop_file = tmp_path / "stop"
    errors = []

    def run_agent():
        try:
            joshua_agent.agent(
                work_dir=tmp_path, agent_timeout=1, stop_file=stop_file
            )
        except Exception as error:
            errors.append(error)

    agent = threading.Thread(target=run_agent, daemon=True)
    agent.start()
    try:
        agent.join(timeout=5)
        assert not errors
        assert not agent.is_alive()
        assert [eid for eid, _ in joshua_model.list_active_ensembles()] == [ensemble_id]
        assert [run["seed"] for run in joshua_model.show_in_progress(ensemble_id)] == [12345]
        assert joshua_model.get_ensemble_properties(ensemble_id).get("ended", 0) == 0
    finally:
        stop_file.touch()
        agent.join(timeout=5)


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
    agent.daemon = True
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
    agent.daemon = True
    agent.start()

    # Ensemble should still eventually end
    joshua.tail_ensemble(ensemble_id, username="joshua")
    agent.join()


def test_two_agents(tmp_path, empty_ensemble, agents_in_threads):
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
        agent.daemon = True
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


def test_concurrent_claims_preserve_max_runs(empty_ensemble):
    @fdb.transactional
    def get_started(tr):
        return joshua_model._get_snap_counter(tr, ensemble_id, "started")

    max_runs = 33
    claimant_count = 128
    ensemble_id = joshua_model.create_ensemble(
        "joshua",
        {
            "max_runs": max_runs,
            # Exercise uneven shard quotas: 9 + 8 + 8 + 8 == 33.
            joshua_model.CLAIM_SHARD_COUNT_PROPERTY: 4,
        },
        open(empty_ensemble, "rb"),
    )
    try:
        barrier = threading.Barrier(claimant_count)
        results = []
        errors = []
        lock = threading.Lock()

        def claim(seed):
            try:
                barrier.wait()
                result = joshua_model.try_starting_test(ensemble_id, seed)
                with lock:
                    results.append(result)
            except Exception as e:
                with lock:
                    errors.append(e)

        claimants = [
            threading.Thread(target=claim, args=(seed,))
            for seed in range(claimant_count)
        ]
        for claimant in claimants:
            claimant.start()
        for claimant in claimants:
            claimant.join(timeout=10)

        assert not [claimant for claimant in claimants if claimant.is_alive()]
        assert not errors
        assert sum(results) == max_runs
        assert get_started(joshua_model.db) == max_runs
        assert len(joshua_model.show_in_progress(ensemble_id)) == max_runs
    finally:
        joshua_model.delete_ensemble(ensemble_id)


def test_dead_claim_releases_shard(empty_ensemble):
    @fdb.transactional
    def expire_heartbeat(tr):
        tr[
            joshua_model.dir_ensemble_incomplete[ensemble_id]["heartbeat"][seed]
        ] = fdb.tuple.pack((0,))

    @fdb.transactional
    def get_started(tr):
        return joshua_model._get_snap_counter(tr, ensemble_id, "started")

    max_runs = 2
    shard_count = 2
    properties = {
        "max_runs": max_runs,
        joshua_model.CLAIM_SHARD_COUNT_PROPERTY: joshua_model.CLAIM_SHARD_MAX,
    }
    ensemble_id = joshua_model.create_ensemble(
        "joshua",
        properties,
        open(empty_ensemble, "rb"),
    )
    assert properties[joshua_model.CLAIM_SHARD_COUNT_PROPERTY] == shard_count
    try:
        assert joshua_model.try_starting_test(ensemble_id, 0)  # fills shard 0
        seed = 2  # must claim shard 1 because shard 0 is full
        assert joshua_model.try_starting_test(ensemble_id, seed)
        assert get_started(joshua_model.db) == max_runs

        expire_heartbeat(joshua_model.db)
        assert joshua_model.should_run_ensemble(ensemble_id)
        assert get_started(joshua_model.db) == max_runs - 1

        # Reclaim the recorded shard, which differs from the seed's initial shard.
        assert joshua_model.try_starting_test(ensemble_id, seed + shard_count)
        assert get_started(joshua_model.db) == max_runs
        assert {
            run["seed"]: run["claim_shard"]
            for run in joshua_model.show_in_progress(ensemble_id)
        } == {0: 0, seed + shard_count: 1}
        assert not joshua_model.try_starting_test(ensemble_id, seed + 2 * shard_count)
    finally:
        joshua_model.delete_ensemble(ensemble_id)


def test_legacy_claims_keep_exact_max_runs(empty_ensemble):
    @fdb.transactional
    def get_started(tr):
        return joshua_model._get_snap_counter(tr, ensemble_id, "started")

    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(empty_ensemble, "rb")
    )
    try:
        assert joshua_model.try_starting_test(ensemble_id, 12345)
        assert not joshua_model.try_starting_test(ensemble_id, 12346)
        assert get_started(joshua_model.db) == 1
    finally:
        joshua_model.delete_ensemble(ensemble_id)


def test_reclaims_expired_run_without_scanning_all_heartbeats(
    monkeypatch, empty_ensemble
):
    @fdb.transactional
    def get_started(tr):
        return joshua_model._get_snap_counter(tr, ensemble_id, "started")

    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 2}, open(empty_ensemble, "rb")
    )
    assert joshua_model.try_starting_test(ensemble_id, 12345)
    assert joshua_model.try_starting_test(ensemble_id, 12346)
    assert get_started(joshua_model.db) == 2

    def heartbeats(_ensemble_id, _tr):
        yield 12345, time.time() - 11
        raise AssertionError("scanned past the first expired heartbeat")

    monkeypatch.setattr(joshua_model, "_get_seeds_and_heartbeats", heartbeats)

    assert joshua_model.should_run_ensemble(ensemble_id)
    assert get_started(joshua_model.db) == 1
    assert {
        run["seed"] for run in joshua_model.show_in_progress(ensemble_id)
    } == {12346}
    assert joshua_model.try_starting_test(ensemble_id, 12347)


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
    agent.daemon = True
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
    agent.daemon = True
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
    agent.daemon = True
    agent.start()
    joshua.tail_ensemble(ensemble_id, username="joshua")
    agent.join()

    assert get_passes(joshua_model.db, ensemble_id) == 0
    assert get_fails(joshua_model.db, ensemble_id) >= 1


@fdb.transactional
def get_counter(tr, ensemble_id, counter):
    return joshua_model._get_snap_counter(tr, ensemble_id, counter)


@fdb.transactional
def get_claim_shard_counter(tr, ensemble_id, shard):
    return joshua_model._get_claim_shard_counter(tr, ensemble_id, shard)


@fdb.transactional
def get_result_codes(tr, ensemble_id, results_dir):
    # Result keys are (versionstamp, result_code, hostname, seed)
    return [r[1] for r in joshua_model._read_results(tr, results_dir, ensemble_id, 0)]


def test_release_test_returns_claim(empty_ensemble):
    ensemble_id = joshua_model.create_ensemble(
        "joshua",
        {"max_runs": 1, joshua_model.CLAIM_SHARD_COUNT_PROPERTY: 1},
        open(empty_ensemble, "rb"),
    )
    try:
        assert joshua_model.try_starting_test(ensemble_id, 12345)
        assert not joshua_model.try_starting_test(ensemble_id, 12346)

        assert joshua_model.release_test(ensemble_id, 12345)
        # Already released: no-op, and the counters aren't touched again
        assert not joshua_model.release_test(ensemble_id, 12345)
        assert get_counter(joshua_model.db, ensemble_id, "started") == 0
        assert get_counter(joshua_model.db, ensemble_id, "interrupted") == 1
        assert get_claim_shard_counter(joshua_model.db, ensemble_id, 0) == 0
        assert joshua_model.show_in_progress(ensemble_id) == []

        # The released claim (and its shard) can be taken by another run
        assert joshua_model.try_starting_test(ensemble_id, 12346)
        # Results for the released run are no longer accepted
        assert not joshua_model._insert_results(ensemble_id, 12345, 1, b"")
    finally:
        joshua_model.delete_ensemble(ensemble_id)


def test_release_test_not_owned(monkeypatch, empty_ensemble):
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 2}, open(empty_ensemble, "rb")
    )
    try:
        # Never claimed
        assert not joshua_model.release_test(ensemble_id, 1)

        # Claimed by another agent
        monkeypatch.setattr(joshua_model, "instanceid", os.urandom(8))
        assert joshua_model.try_starting_test(ensemble_id, 2)
        monkeypatch.undo()
        assert not joshua_model.release_test(ensemble_id, 2)

        assert get_counter(joshua_model.db, ensemble_id, "started") == 1
        assert get_counter(joshua_model.db, ensemble_id, "interrupted") == 0
        assert len(joshua_model.show_in_progress(ensemble_id)) == 1
    finally:
        joshua_model.delete_ensemble(ensemble_id)


def test_agent_shutdown_returns_test_to_pool(tmp_path, empty_ensemble_timeout):
    """
    Simulate a node shutdown with an in-process agent: the test process gets
    SIGTERM, and then so does the agent. The test must be returned to the pool,
    not recorded as a failure.
    """
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(empty_ensemble_timeout, "rb")
    )
    agent = threading.Thread(
        target=joshua_agent.agent,
        args=(),
        kwargs={
            "work_dir": tmp_path,
            "agent_idle_timeout": 1,
        },
    )
    agent.daemon = True
    try:
        agent.start()
        while not any(p.name() == "sleep" for p in process_handling.retrieve_children()):
            time.sleep(0.01)
        assert len(joshua_model.show_in_progress(ensemble_id)) == 1

        for p in process_handling.retrieve_children():
            p.send_signal(signal.SIGTERM)
        time.sleep(0.1)
        joshua_agent.stop_agent.set()

        agent.join(timeout=30)
        assert not agent.is_alive()
        assert get_passes(joshua_model.db, ensemble_id) == 0
        assert get_fails(joshua_model.db, ensemble_id) == 0
        assert get_counter(joshua_model.db, ensemble_id, "started") == 0
        assert get_counter(joshua_model.db, ensemble_id, "interrupted") == 1
        assert joshua_model.show_in_progress(ensemble_id) == []
        assert process_handling.retrieve_children() == []
    finally:
        joshua_agent.stop_agent.clear()
        joshua_model.delete_ensemble(ensemble_id)


#### Agent subprocess tests: signals are delivered to a process, so these run
#### the agent as a real process, in its own process group so a whole
#### "container" can be signalled with killpg().


def start_agent_process(cluster_file, work_dir, **env):
    return subprocess.Popen(
        [
            sys.executable, "-m", "joshua.joshua_agent",
            "-C", cluster_file,
            "--work_dir", str(work_dir),
            "--agent-idle-timeout", "1",
        ],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        start_new_session=True,
        env={**os.environ, "JOSHUA_AGENT_HEARTBEAT_INTERVAL": "0.1", **env},
    )


def wait_for_test_process(agent, ensemble_id, timeout=20):
    """Wait until the agent has a test running; returns the agent's direct children."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        assert agent.poll() is None, "agent exited before starting the test"
        children = psutil.Process(agent.pid).children()
        if children and len(joshua_model.show_in_progress(ensemble_id)) == 1:
            return children
        time.sleep(0.05)
    raise AssertionError("test process never started")


def group_alive(pgid):
    alive = []
    for p in psutil.process_iter():
        try:
            if os.getpgid(p.pid) == pgid and p.status() != psutil.STATUS_ZOMBIE:
                alive.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ProcessLookupError):
            pass
    return alive


def kill_agent_group(agent):
    try:
        os.killpg(agent.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    agent.wait()


def assert_interrupted(agent, ensemble_id):
    assert agent.wait(timeout=30) == 0
    assert get_passes(joshua_model.db, ensemble_id) == 0
    assert get_fails(joshua_model.db, ensemble_id) == 0
    assert get_counter(joshua_model.db, ensemble_id, "started") == 0
    assert get_counter(joshua_model.db, ensemble_id, "interrupted") == 1
    assert joshua_model.show_in_progress(ensemble_id) == []
    assert get_result_codes(joshua_model.db, ensemble_id, joshua_model.dir_ensemble_results_fail) == []
    assert get_result_codes(joshua_model.db, ensemble_id, joshua_model.dir_ensemble_results_pass) == []
    # The test's processes are gone too
    deadline = time.time() + 5
    while group_alive(agent.pid) and time.time() < deadline:
        time.sleep(0.05)
    assert group_alive(agent.pid) == []


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_agent_signal_drain(tmp_path, fdb_cluster, empty_ensemble_timeout, sig):
    """Kubernetes drain: only the agent (PID 1) gets the signal, the test keeps running."""
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(empty_ensemble_timeout, "rb")
    )
    agent = start_agent_process(fdb_cluster, tmp_path)
    try:
        wait_for_test_process(agent, ensemble_id)
        agent.send_signal(sig)
        assert_interrupted(agent, ensemble_id)
    finally:
        kill_agent_group(agent)
        joshua_model.delete_ensemble(ensemble_id)


def test_agent_signal_reclaim(tmp_path, fdb_cluster, empty_ensemble_timeout):
    """Spot reclaim: systemd sends SIGTERM to every process in the container at once."""
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(empty_ensemble_timeout, "rb")
    )
    agent = start_agent_process(fdb_cluster, tmp_path)
    try:
        wait_for_test_process(agent, ensemble_id)
        os.killpg(agent.pid, signal.SIGTERM)
        assert_interrupted(agent, ensemble_id)
    finally:
        kill_agent_group(agent)
        joshua_model.delete_ensemble(ensemble_id)


def test_agent_signal_race(tmp_path, fdb_cluster, empty_ensemble_timeout):
    """The test dies from SIGTERM before the agent's own signal arrives."""
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(empty_ensemble_timeout, "rb")
    )
    agent = start_agent_process(fdb_cluster, tmp_path, JOSHUA_AGENT_SIGNAL_WAIT="5")
    try:
        for p in wait_for_test_process(agent, ensemble_id):
            p.send_signal(signal.SIGTERM)
        time.sleep(0.5)
        agent.send_signal(signal.SIGTERM)
        assert_interrupted(agent, ensemble_id)
    finally:
        kill_agent_group(agent)
        joshua_model.delete_ensemble(ensemble_id)


def test_agent_signal_race_test_catches_sigterm(tmp_path, fdb_cluster):
    """
    Like test_agent_signal_race, but the test catches SIGTERM and exits with a
    normal error code instead of dying from the signal.
    """
    pid_file = tmp_path / "test.pid"
    ensemble = empty_ensemble_factory(
        tmp_path, f'echo $$ > {pid_file}; trap "exit 1" TERM; sleep 100000 & wait'
    )
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(ensemble, "rb")
    )
    agent = start_agent_process(fdb_cluster, tmp_path / "work", JOSHUA_AGENT_SIGNAL_WAIT="5")
    try:
        wait_for_test_process(agent, ensemble_id)
        deadline = time.time() + 10
        while not pid_file.exists() and time.time() < deadline:
            time.sleep(0.05)
        os.kill(int(pid_file.read_text()), signal.SIGTERM)
        time.sleep(0.5)
        agent.send_signal(signal.SIGTERM)
        assert_interrupted(agent, ensemble_id)
    finally:
        kill_agent_group(agent)
        joshua_model.delete_ensemble(ensemble_id)


def test_agent_signal_ctrl_c(tmp_path, fdb_cluster, empty_ensemble_timeout):
    """
    Ctrl-C in a terminal sends SIGINT to the whole foreground process group, so
    the test dies with -2 (the same value as the agent's timeout sentinel). The
    ensemble has no timeout property, which used to raise TypeError.
    """
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(empty_ensemble_timeout, "rb")
    )
    agent = start_agent_process(fdb_cluster, tmp_path)
    try:
        wait_for_test_process(agent, ensemble_id)
        os.killpg(agent.pid, signal.SIGINT)
        assert_interrupted(agent, ensemble_id)
    finally:
        kill_agent_group(agent)
        joshua_model.delete_ensemble(ensemble_id)


@pytest.mark.parametrize("sig,signum", [("TERM", 15), ("KILL", 9)])
def test_test_killed_by_itself_is_recorded(tmp_path, fdb_cluster, sig, signum):
    """
    A test killed by a signal when the agent gets no signal (e.g. it kills itself,
    or the OOM killer) is a real failure, recorded after the signal wait.
    """
    ensemble = empty_ensemble_factory(tmp_path, f"kill -{sig} $$")
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": 1}, open(ensemble, "rb")
    )
    agent = start_agent_process(fdb_cluster, tmp_path / "work", JOSHUA_AGENT_SIGNAL_WAIT="0.5")
    try:
        assert agent.wait(timeout=30) == 0
        assert get_passes(joshua_model.db, ensemble_id) == 0
        assert get_fails(joshua_model.db, ensemble_id) == 1
        assert get_counter(joshua_model.db, ensemble_id, "interrupted") == 0
        # -signum if /bin/sh execs the test command (bash), 128 + signum if it
        # stays as the test's parent (dash).
        assert get_result_codes(
            joshua_model.db, ensemble_id, joshua_model.dir_ensemble_results_fail
        ) in ([-signum], [128 + signum])
    finally:
        kill_agent_group(agent)
        joshua_model.delete_ensemble(ensemble_id)


def test_passing_tests_are_not_delayed(tmp_path, fdb_cluster, empty_ensemble):
    """
    Only tests killed by a signal wait for the agent's own signal. A huge
    JOSHUA_AGENT_SIGNAL_WAIT must not slow down tests that exit normally, and
    there must be no fixed per-test sleep either.
    """
    max_runs = 16
    ensemble_id = joshua_model.create_ensemble(
        "joshua", {"max_runs": max_runs}, open(empty_ensemble, "rb")
    )
    agent = start_agent_process(fdb_cluster, tmp_path / "work", JOSHUA_AGENT_SIGNAL_WAIT="30")
    try:
        deadline = time.time() + 25
        first = None
        while time.time() < deadline:
            passes = get_passes(joshua_model.db, ensemble_id)
            if passes >= 1 and first is None:
                first = time.time()
            if passes >= max_runs:
                break
            time.sleep(0.05)
        assert get_passes(joshua_model.db, ensemble_id) >= max_runs
        # 15 runs after the first; a fixed 1s sleep per test would take >= 15s
        assert time.time() - first < 12
    finally:
        kill_agent_group(agent)
        joshua_model.delete_ensemble(ensemble_id)


def test_delete_ensemble(tmp_path, empty_ensemble_timeout, agents_in_threads):
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
        agent.daemon = True
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
    # count can be larger than max_runs: joshua can run more tests
    # than max_runs. In addition, a test might finish but not report
    # back
    assert count >= num_runs


@fdb.transactional
def verify_application_state_deleted(tr, ensemble):
    assert not fdb.directory.exists(tr, joshua_model.get_application_dir(ensemble))


def test_joshua_done_ensemble(tmp_path, empty_ensemble_joshua_done, agents_in_threads):
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
    deadline = time.time() + 120
    for agent in agents:
        while agent.is_alive():
            assert time.time() < deadline, "agents did not exit"
            joshua_model.stop_completed_ensembles()
            agent.join(0.5)
    verify_application_state(joshua_model.db, ensemble_id, max_runs)
    joshua_model.delete_ensemble(ensemble_id)
    verify_application_state_deleted(joshua_model.db, ensemble_id)


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


def test_two_agents_large_ensemble(monkeypatch, tmp_path, empty_ensemble, agents_in_threads):
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
        agent.daemon = True
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
