"""
    joshua_model.py
"""
# This source file is part of the FoundationDB open source project
#
# Copyright 2013-2020 Apple Inc. and the FoundationDB project authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import datetime
import hashlib
import heapq
import logging
import os
import random
import re
import socket
import struct
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import zlib
from collections import defaultdict
from io import BytesIO
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import fdb
import fdb.tuple


logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

fdb.api_version(630)
FDBError = fdb.FDBError

ONE = b"\x01" + b"\x00" * 7
TIMESTAMP_FMT = "%Y%m%d-%H%M%S"

TIMEDELTA_REGEX1 = re.compile(
    r"(?P<days>[-\d]+) day[s]*, (?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d[\.\d+]*)"
)
TIMEDELTA_REGEX2 = re.compile(
    r"(?P<hours>\d+):(?P<minutes>\d+):(?P<seconds>\d[\.\d+]*)"
)

# A random instance ID as the seed for Joshua agent
instanceid = os.urandom(8)

BLOB_KEY_LIMIT = 8192
BLOB_TRANSACTION_LIMIT = 128 * 1024

INSTANCE_ID_ENV_VAR = "PLATFORM_SHORT_INSTANCE_ID"
OLD_INSTANCE_ID_ENV_VAR = "SHORT_TASK_ID"
HOSTNAME_ENV_VAR = "HOSTNAME"

db = None
dir_top = None
dir_ensembles = None
dir_active = None
dir_sanity = None
dir_all_ensembles = None
dir_ensemble_data = None
dir_ensemble_results = None
dir_ensemble_results_pass = None
dir_ensemble_results_fail = None
dir_ensemble_incomplete = None
dir_ensemble_results_large = None
dir_active_changes = None
dir_sanity_changes = None
dir_failures = None


def open(cluster_file=None, dir_path=("joshua",)):
    global db, dir_top, dir_ensembles, dir_active, dir_sanity, dir_all_ensembles, dir_ensemble_data, dir_ensemble_results
    global dir_ensemble_results_pass, dir_ensemble_results_fail, dir_ensemble_incomplete, dir_ensemble_results_large
    global dir_active_changes, dir_sanity_changes, dir_failures

    db = fdb.open(cluster_file)
    dir_top = create_or_open_top_path(db, dir_path)
    dir_ensembles = dir_top.create_or_open(db, "ensembles")
    dir_active = dir_ensembles.create_or_open(db, "active")
    dir_sanity = dir_ensembles.create_or_open(db, "sanity")
    dir_all_ensembles = dir_ensembles.create_or_open(db, "all")
    dir_ensemble_data = dir_ensembles.create_or_open(db, "data")
    dir_ensemble_incomplete = dir_ensembles.create_or_open(db, "incomplete")
    dir_ensemble_results = dir_ensembles.create_or_open(db, "results")
    dir_ensemble_results_pass = dir_ensemble_results.create_or_open(db, "pass")
    dir_ensemble_results_fail = dir_ensemble_results.create_or_open(db, "fail")
    dir_ensemble_results_large = dir_ensemble_results.create_or_open(db, "large")
    dir_failures = dir_top.create_or_open(db, "failures")

    dir_active_changes = dir_active
    dir_sanity_changes = dir_sanity


def create_or_open_top_path(db, dir_path):
    dir_so_far = fdb.directory.create_or_open(db, dir_path[0])

    for path_entry in dir_path[1:]:
        dir_so_far = dir_so_far.create_or_open(db, path_entry)

    return dir_so_far


def get_dir_changes(sanity=False):
    dir = dir_sanity if sanity else dir_active
    changes = dir_sanity_changes if sanity else dir_active_changes

    return dir, changes


def get_hash(file):
    hash = hashlib.sha256()
    hash.update(file.read())
    file.seek(0)
    return hash.hexdigest()


def transactional(func):
    f1 = fdb.transactional(func)

    def helper(*args, **kw):
        return f1(db, *args, **kw)

    helper.__name__ = f1.__name__ = func.__name__
    return helper


def wrap_error(description):
    root = ET.Element("Test")
    ET.SubElement(root, "JoshuaError", {"Severity": "40", "ErrorMessage": description})
    return ET.tostring(root) + "\n"


def wrap_message(info={}):
    root = ET.Element("Test")
    attribs = {"Severity": "10"}
    attribs.update(info)
    ET.SubElement(root, "JoshuaMessage", attribs)
    return ET.tostring(root) + "\n"


def get_hostname():
    if INSTANCE_ID_ENV_VAR in os.environ:
        return os.environ[INSTANCE_ID_ENV_VAR]
    elif OLD_INSTANCE_ID_ENV_VAR in os.environ:
        return os.environ[OLD_INSTANCE_ID_ENV_VAR]
    elif HOSTNAME_ENV_VAR in os.environ:
        return os.environ[HOSTNAME_ENV_VAR]
    else:
        return socket.gethostname()


def is_message(text):
    # Hmm...perhaps this could be better.
    return text.startswith("<Test><JoshuaMessage")


def unwrap_message(text):
    root = ET.fromstring(text)
    return root.getchildren()[0].attrib


def load_datetime(string):
    #    print( 'string: {}  now: {}'.format(string, format_datetime(datetime.datetime.now(timezone.utc))) )
    return datetime.datetime.strptime(string, TIMESTAMP_FMT).replace(tzinfo=datetime.timezone.utc)


def load_timedelta(string):
    if "day" in string:
        m = TIMEDELTA_REGEX1.match(string)
    else:
        m = TIMEDELTA_REGEX2.match(string)
    parse_info = {key: float(val) for key, val in m.groupdict().items()}
    #    print( 'string: {}  parsed: {}'.format(string, parse_info) )
    return datetime.timedelta(**parse_info)


def format_timedelta(timedelta_obj):
    return str(timedelta_obj).split(".", 2)[0]


def format_datetime(dt_obj):
    return dt_obj.strftime(TIMESTAMP_FMT)


def _list_and_watch_ensembles(tr: fdb.Transaction, dir, changes):
    ensembles = []
    for k, v in tr[dir.range()]:
        (ensemble,) = dir.unpack(k)
        ensembles.append(ensemble)

    return ensembles, tr.watch(changes.key())


@transactional
def identify_existing_ensembles(tr, ensembles):
    return list(filter(lambda eid: tr[dir_all_ensembles[eid]] != None, ensembles))


@transactional
def list_and_watch_active_ensembles(tr) -> Tuple[List[str], fdb.Future]:
    return _list_and_watch_ensembles(tr, dir_active, dir_active_changes)


@transactional
def list_and_watch_sanity_ensembles(tr):
    return _list_and_watch_ensembles(tr, dir_sanity, dir_sanity_changes)


def _get_ensemble_properties(tr, ensemble, snapshot=False):
    props = {}
    r = dir_all_ensembles[ensemble].range()
    prop_kvs = (tr.snapshot if snapshot else tr).get_range(
        r.start, r.stop, streaming_mode=fdb.StreamingMode.want_all
    )
    for key, value in prop_kvs:
        _unpack_property(ensemble, key, value, props)

    return props


@transactional
def get_ensemble_properties(tr, ensemble, snapshot=False):
    return _get_ensemble_properties(tr, ensemble, snapshot=snapshot)


def _unpack_property(ensemble, key, value, into):
    t = dir_all_ensembles[ensemble].unpack(key)
    if t[0] == "properties":
        into[t[1]] = fdb.tuple.unpack(value)[0]
    elif t[0] == "count":
        into[t[1]] = struct.unpack("<Q", value)[0]


def _list_ensembles(tr, dir) -> List[Tuple[str, Dict]]:
    prop_reads = []
    for k, v in tr[dir.range()]:
        (ensemble,) = dir.unpack(k)
        r = dir_all_ensembles[ensemble].range()
        prop_reads.append(
            (
                ensemble,
                tr.get_range(
                    r.start, r.stop, streaming_mode=fdb.StreamingMode.want_all
                ),
            )
        )
    ensembles = []
    for ensemble, prop_kvs in prop_reads:
        props = {}
        for k, v in prop_kvs:
            _unpack_property(ensemble, k, v, props)
        ensembles.append((ensemble, props))
    return ensembles


@transactional
def list_active_ensembles(tr) -> List[Tuple[str, Dict]]:
    return _list_ensembles(tr, dir_active)


@transactional
def list_sanity_ensembles(tr) -> List[Tuple[str, Dict]]:
    return _list_ensembles(tr, dir_sanity)


def list_all_ensembles() -> List[Tuple[str, Dict]]:
    ensembles: List[Tuple[str, Dict]] = []
    r = dir_all_ensembles.range()
    start = r.start
    tr = db.create_transaction()
    while True:
        prev_start = start
        try:
            for k, v in tr.get_range(
                start, r.stop, streaming_mode=fdb.StreamingMode.want_all
            ):
                start = k + b"\x00"
                t = dir_all_ensembles.unpack(k)
                if len(t) == 1:
                    ensembles.append((t[0], {}))
                else:
                    _unpack_property(ensembles[-1][0], k, v, ensembles[-1][1])
            return ensembles
        except FDBError as e:
            # If we get transaction_too_old and we made progress with the current transaction,
            # continue where we left off with a new transaction.
            if e.code == 1007 and start != prev_start:
                tr = db.create_transaction()
            else:
                tr.on_error(e).wait()


@transactional
def get_ensemble_mean_durations(tr, ensembles=None):
    if not ensembles:
        ensembles = map(lambda x: x[0], list_active_ensembles(tr))

    duration_map = {}
    for ensemble in ensembles:
        duration = _get_snap_counter(tr, ensemble, "duration")
        ended = _get_snap_counter(tr, ensemble, "ended")

        if ended == 0:
            duration_map[ensemble] = 1.0
        else:
            duration_map[ensemble] = max(1.0, duration * 1.0 / ended)

    return duration_map


@transactional
def get_ensemble_priorities(tr, ensembles=None):
    if not ensembles:
        ensembles = map(lambda x: x[0], list_active_ensembles(tr))

    priority_map = {}
    for ensemble in ensembles:
        priority = _get_snap_counter(tr, ensemble, "priority")
        if priority == 0:
            priority = 100
        priority_map[ensemble] = priority / float(100)

    return priority_map


@fdb.transactional
def _insert_blobpart(tr, subspace, offset, data):
    for rel_offs in range(0, min(BLOB_TRANSACTION_LIMIT, len(data)), BLOB_KEY_LIMIT):
        tr[subspace[offset + rel_offs]] = data[rel_offs : rel_offs + BLOB_KEY_LIMIT]


def _insert_blob(db, subspace, file, offset=0, verbose=False):
    if verbose:
        sys.stderr.write("Uploading: .=%d: " % BLOB_TRANSACTION_LIMIT)
    file.seek(offset)
    while True:
        data = file.read(BLOB_TRANSACTION_LIMIT)
        if not data:
            if verbose:
                sys.stderr.write(" DONE! Total=%d\n" % offset)
            break
        _insert_blobpart(db, subspace, offset, data)
        if verbose:
            sys.stderr.write(".")
        offset += len(data)


@fdb.transactional
def _read_blobpart(tr, subspace, offset):
    data = []
    for k, v in tr[subspace[offset] : subspace[offset + BLOB_TRANSACTION_LIMIT]]:
        # print( len(data), offset, len(v), repr(k), repr(subspace[offset].key()) )
        assert subspace[offset].key() == k
        data.append(v)
        offset += len(v)
        if not v:
            break
    return b"".join(data)


def _read_blob(db, subspace, file):
    offset = 0
    while True:
        data = _read_blobpart(db, subspace, offset)
        if not data:
            break
        file.write(data)
        offset += len(data)


@fdb.transactional
def _delete_blob(tr, subspace):
    del tr[subspace.range()]


@fdb.transactional
def _create_ensemble(tr, ensemble_id, properties, sanity=False):
    dir, changes = get_dir_changes(sanity)

    if tr[dir_all_ensembles[ensemble_id]] != None:
        print("{} already inserted".format(ensemble_id))
        return  # Already inserted
    tr[dir_all_ensembles[ensemble_id]] = b""
    for k, v in properties.items():
        tr[dir_all_ensembles[ensemble_id]["properties"][k]] = fdb.tuple.pack((v,))
    tr[dir[ensemble_id]] = b""
    tr.add(changes, ONE)


def create_ensemble(userid, properties, tarball, sanity=False):
    hash = get_hash(tarball)
    timestamp = format_datetime(datetime.datetime.now(datetime.timezone.utc))
    ensemble_id = timestamp + "-" + userid + "-" + hash[:16]
    if "submitted" not in properties:
        properties["submitted"] = timestamp
    _insert_blob(db, dir_ensemble_data[ensemble_id], tarball, 0, True)
    _create_ensemble(db, ensemble_id, properties, sanity)
    logger.debug(
        "created ensemble {}, properties: {}, sanity: {}".format(
            ensemble_id, properties, sanity
        )
    )
    return ensemble_id


def stop_user_ensembles(username, sanity=False):
    if not username:
        raise Exception("Unable to stop ensembles belonging to unspecified user.")
    ensemble_list = get_active_ensembles(False, sanity, username)
    for e, props in ensemble_list:
        if "-" + username + "-" in str(e):
            stop_ensemble(e, sanity)


def get_active_ensembles(
    stopped, sanity=False, username=None
) -> List[Tuple[str, Dict]]:
    if stopped:
        ensemble_list = list_all_ensembles()
    elif sanity:
        ensemble_list = list_sanity_ensembles()
    else:
        ensemble_list = list_active_ensembles()
    # Filter by username, if specified
    if username:
        ensemble_list = list(
            filter(lambda i: i[1].get("username", None) == username, ensemble_list)
        )
    # Determine the runtime, if not defined
    for e, props in ensemble_list:
        if props.get("runtime", None) is None:
            if props.get("submitted", None) is not None:
                props["runtime"] = format_timedelta(
                    datetime.datetime.now(datetime.timezone.utc) - load_datetime(props["submitted"])
                )
        if props.get("stopped", None) is not None:
            props["remaining"] = "0"
        elif props.get("runtime", None) is not None:
            if props.get("ended", None) is not None:
                jobs_done = int(props.get("ended", 1))
                if props.get("max_runs", None) is None:
                    props["remaining"] = "no_max"
                elif int(props.get("max_runs", 0)) < jobs_done:
                    props["remaining"] = "stopping"
                else:
                    props["remaining"] = format_timedelta(
                        datetime.timedelta(
                            seconds=load_timedelta(props["runtime"]).total_seconds()
                            * (int(props["max_runs"]) - jobs_done)
                            / jobs_done
                        )
                    )
            else:
                props["remaining"] = "not_started"
        else:
            props["remaining"] = "old_version"
    return ensemble_list


@fdb.transactional
def _stop_ensemble(tr, ensemble_id, sanity=False):
    dir, changes = get_dir_changes(sanity)

    # print(dir, dir_all_ensembles[ensemble_id], ensemble_id, dir[ensemble_id])
    if tr[dir_all_ensembles[ensemble_id]] == None:
        raise Exception("Ensemble " + ensemble_id + " does not exist")

    # Set the stopped and runtime, if not set
    if tr[dir[ensemble_id]] is not None:
        # Get the current time
        stoptime = datetime.datetime.now(datetime.timezone.utc)
        # Get the ensemble properties
        properties = get_ensemble_properties(ensemble_id)
        # Get the ensemble submission time, if not defined use now
        submitted = (
            load_datetime(
                fdb.tuple.unpack(
                    tr[dir_all_ensembles[ensemble_id]["properties"]["submitted"]]
                )[0]
            )
            if "submitted" in properties
            else stoptime
        )

        # Set the stoptime of the ensemble
        tr[dir_all_ensembles[ensemble_id]["properties"]["stopped"]] = fdb.tuple.pack(
            (format_datetime(stoptime),)
        )
        # Set the runtime of the ensemble
        tr[dir_all_ensembles[ensemble_id]["properties"]["runtime"]] = fdb.tuple.pack(
            (format_timedelta(stoptime - submitted),)
        )

    del tr[dir[ensemble_id]]
    del tr[dir_ensemble_incomplete[ensemble_id]]
    del tr[dir_ensemble_incomplete[ensemble_id].range()]
    tr.add(changes, ONE)


@transactional
def stop_ensemble(tr, ensemble_id, sanity=False):
    _stop_ensemble(tr, ensemble_id, sanity)


@transactional
def resume_ensemble(tr, ensemble_id, sanity=False):
    dir, changes = get_dir_changes(sanity)

    # print(tr[ dir_all_ensembles[ensemble_id] ], tr[dir[ensemble_id]], ensemble_id, dir)
    if tr[dir_all_ensembles[ensemble_id]] == None:
        raise Exception("Ensemble " + ensemble_id + " does not exist")
    if tr[dir[ensemble_id]] == None:
        tr[dir[ensemble_id]] = b""
        tr.add(changes, ONE)
        return True
    return False


@transactional
def _delete_ensemble_data(tr, ensemble_id, sanity=False):
    dir, changes = get_dir_changes(sanity)

    # Only delete if present.
    if tr[dir_all_ensembles[ensemble_id]] == None:
        print("Ensemble", ensemble_id, "already deleted.")
        return

    # Remove results stored using BlobVersion = 2.
    del db[dir_ensemble_results_large[ensemble_id].range()]

    # Delete the results.
    del tr[dir_ensemble_results_pass[ensemble_id].range()]
    del tr[dir_ensemble_results_fail[ensemble_id].range()]

    # Delete record that the ensemble is running if present.
    if tr[dir[ensemble_id]] != None:
        del tr[dir[ensemble_id]]

    # Delete the record that this ensemble exists.
    _delete_blob(tr, dir_ensemble_data[ensemble_id])
    del tr[dir_all_ensembles[ensemble_id].range()]
    del tr[dir_all_ensembles[ensemble_id]]

    tr.add(changes, ONE)


def delete_ensemble(ensemble_id, compressed=True, sanity=False):
    # Only delete if present.
    if db[dir_all_ensembles[ensemble_id]] == None:
        print("Ensemble", ensemble_id, "already deleted.")
        return
    _delete_ensemble_data(ensemble_id, sanity)


def get_ensemble_data(ensemble_id, outfile=None):
    if not outfile:
        outfile = BytesIO()
    _read_blob(db, dir_ensemble_data[ensemble_id], outfile)
    return outfile


def set_versionstamped_key(tr, prefix, suffix, value):
    tr.set_versionstamped_key(
        prefix
        + b"\x1d\x0b\x01"
        + b"." * 10
        + suffix
        + struct.pack("<I", len(prefix) + 3),
        value,
    )


def _increment(tr: fdb.Transaction, ensemble_id: str, counter: str) -> None:
    tr.add(dir_all_ensembles[ensemble_id]["count"][counter], ONE)


def _add(tr: fdb.Transaction, ensemble_id: str, counter: str, value: int) -> None:
    byte_val = struct.pack("<Q", value)
    tr.add(dir_all_ensembles[ensemble_id]["count"][counter], byte_val)


def _get_snap_counter(tr: fdb.Transaction, ensemble_id: str, counter: str) -> int:
    value = tr.snapshot.get(dir_all_ensembles[ensemble_id]["count"][counter])
    if value == None:
        return 0
    else:
        return struct.unpack("<Q", b"" + value)[0]


def _get_seeds_and_heartbeats(
    ensemble_id: str, tr: fdb.Transaction
) -> List[Tuple[int, float]]:
    result = []
    for k, v in tr.snapshot[dir_ensemble_incomplete[ensemble_id]["heartbeat"].range()]:
        (seed,) = dir_ensemble_incomplete[ensemble_id]["heartbeat"].unpack(k)
        (heartbeat,) = fdb.tuple.unpack(v)
        result.append((seed, heartbeat))
    return result


def _get_hostname(ensemble_id: str, seed: int, tr: fdb.Transaction) -> Optional[str]:
    v = tr.snapshot[dir_ensemble_incomplete[ensemble_id][seed]["hostname"]]
    if v != None:
        return fdb.tuple.unpack(v)[0]
    return None


@transactional
def should_run_ensemble(tr: fdb.Transaction, ensemble_id: str) -> bool:
    """
    Return True if this agent should start a run for this ensemble. The
    policy tries not to overshoot max_runs by too much, but also accounts
    for the possibility that agents might die.
    """
    props = _get_ensemble_properties(tr, ensemble_id, snapshot=True)
    started = props.get("started", 0)
    max_runs = props.get("max_runs", 0)
    # max_runs == 0 means run forever
    if max_runs > 0 and started >= max_runs:
        current_time = time.time()
        max_seed = None
        max_heartbeat_age = None
        for seed, heartbeat in _get_seeds_and_heartbeats(ensemble_id, tr):
            assert type(seed) == int
            if max_seed is None or current_time - heartbeat > max_heartbeat_age:
                max_seed = seed
                max_heartbeat_age = current_time - heartbeat
        if max_heartbeat_age is None:
            # No other agents are running a test for this ensemble (is this possible?)
            return True
        if max_heartbeat_age > 10:
            print(
                "Agent {} presumed dead. Attempting to steal its work.".format(
                    _get_hostname(ensemble_id, max_seed, tr)
                )
            )

            # If we read at snapshot isolation then an arbitrary number of agents could steal this run/seed.
            # We only want one agent to succeed in taking over for the dead agent's run/seed.
            tr.add_read_conflict_key(
                dir_ensemble_incomplete[ensemble_id]["heartbeat"][max_seed]
            )
            del tr[dir_ensemble_incomplete[ensemble_id][max_seed]]
            del tr[dir_ensemble_incomplete[ensemble_id][max_seed].range()]
            del tr[dir_ensemble_incomplete[ensemble_id]["heartbeat"][max_seed]]
            return True
        return False
    else:
        # max_runs == 0 or started < max_runs
        return True


@transactional
def show_in_progress(tr: fdb.Transaction, ensemble_id: str) -> List[Tuple[int, Dict]]:
    """
    Returns a list of properties for in progress tests
    """
    result = defaultdict(dict)
    for k, v in tr[dir_ensemble_incomplete[ensemble_id].range()]:
        property = dir_ensemble_incomplete[ensemble_id].unpack(k)
        if property[0] == "heartbeat":
            seed = property[1]
            result[seed]["heartbeat"] = fdb.tuple.unpack(v)[0]
            result[seed]["seed"] = seed
        elif len(property) > 1:
            seed = property[0]
            result[seed][property[1]] = fdb.tuple.unpack(v)[0]
            result[seed]["seed"] = seed
            if property[1] == "began_at":
                result[seed]["running_for"] = time.time() - fdb.tuple.unpack(v)[0]
    return list(result.values())


@transactional
def try_starting_test(tr, ensemble_id, seed, sanity=False) -> bool:
    """Return true if we should continue executing this test"""
    dir, _ = get_dir_changes(sanity)

    if tr[dir[ensemble_id]] == None:
        # Ensemble is stopped
        return False
    if tr[dir_ensemble_incomplete[ensemble_id][seed]] != None:
        # Don't run the same seed twice simultaneously
        return tr[dir_ensemble_incomplete[ensemble_id][seed]] == instanceid

    _increment(tr, ensemble_id, "started")
    tr[dir_ensemble_incomplete[ensemble_id][seed]] = instanceid
    current_time = time.time()
    tr[dir_ensemble_incomplete[ensemble_id][seed]["began_at"]] = fdb.tuple.pack(
        (current_time,)
    )
    tr[dir_ensemble_incomplete[ensemble_id][seed]["hostname"]] = fdb.tuple.pack(
        (get_hostname(),)
    )
    tr[dir_ensemble_incomplete[ensemble_id]["heartbeat"][seed]] = fdb.tuple.pack(
        (current_time,)
    )
    return True


@transactional
def heartbeat_and_check_running(tr, ensemble_id, seed, sanity=False):
    dir, _ = get_dir_changes(sanity)
    result = (
        tr[dir[ensemble_id]] != None
        and tr[dir_ensemble_incomplete[ensemble_id][seed]] == instanceid
    )
    if result:
        tr[dir_ensemble_incomplete[ensemble_id]["heartbeat"][seed]] = fdb.tuple.pack(
            (time.time(),)
        )
    return result


@transactional
def _insert_results(
    tr,
    ensemble_id,
    seed,
    result_code,
    output,
    sanity=False,
    fail_fast=0,
    max_runs=0,
    duration=0,
):
    dir, _ = get_dir_changes(sanity)

    if tr[dir[ensemble_id]] == None:
        # Don't insert any more results for stopped ensembles
        return False

    if tr[dir_ensemble_incomplete[ensemble_id][seed]] == None:
        # Test already completed
        return False
    del tr[dir_ensemble_incomplete[ensemble_id][seed]]
    del tr[dir_ensemble_incomplete[ensemble_id][seed].range()]
    del tr[dir_ensemble_incomplete[ensemble_id]["heartbeat"][seed]]

    _increment(tr, ensemble_id, "ended")

    if result_code:
        _increment(tr, ensemble_id, "fail")
        results = dir_ensemble_results_fail

        if fail_fast > 0:
            # This is a snapshot read so that two insertions don't conflict.
            failures = _get_snap_counter(tr, ensemble_id, "fail")
            if failures >= fail_fast:
                _stop_ensemble(tr, ensemble_id, sanity)

    else:
        _increment(tr, ensemble_id, "pass")
        results = dir_ensemble_results_pass

    if max_runs > 0:
        # This is a snapshot read so that two insertions don't conflict.
        ended = _get_snap_counter(tr, ensemble_id, "ended")
        if ended >= max_runs:
            _stop_ensemble(tr, ensemble_id, sanity)

    if duration:
        _add(tr, ensemble_id, "duration", int(duration))

    set_versionstamped_key(
        tr,
        results[ensemble_id].key(),
        fdb.tuple.pack((result_code, get_hostname(), seed)),
        output,
    )
    return True


def insert_results(
    ensemble_id,
    seed,
    result_code,
    output,
    compress,
    sanity=False,
    fail_fast=0,
    max_runs=0,
    duration=0,
):
    # Compress the results first.
    if compress:
        output = zlib.compress(output)

    if len(output) > BLOB_KEY_LIMIT:
        # Insert a message into the regular results stating where we are placing the actual results.
        blob_key = str(seed)
        msg = wrap_message(
            {"Message": "value_in_blob", "BlobKey": blob_key, "BlobVersion": "2"}
        )
        if compress:
            msg = zlib.compress(msg)
        inserted = _insert_results(
            ensemble_id, seed, result_code, msg, sanity, fail_fast, max_runs, duration
        )

        if inserted:
            _insert_blob(
                db, dir_ensemble_results_large[ensemble_id][blob_key], BytesIO(output)
            )
    else:
        # Small enough to place in a single key.
        _insert_results(
            ensemble_id,
            seed,
            result_code,
            output,
            sanity,
            fail_fast,
            max_runs,
            duration,
        )


def _read_results(tr, results_dir, ensemble_id, begin_versionstamp):
    for k, v in tr[
        results_dir[ensemble_id][begin_versionstamp] : results_dir[ensemble_id]
        .range()
        .stop
    ]:
        yield results_dir[ensemble_id].unpack(k) + (v,)


@fdb.transactional
def _read_and_watch_results(tr, results_dirs, ensemble_id, begin_versionstamp):
    result_stream = heapq.merge(
        *(_read_results(tr, rd, ensemble_id, begin_versionstamp) for rd in results_dirs)
    )

    stopAt = time.time() + 0.250
    results = []
    for r in result_stream:
        results.append(r)
        if time.time() >= stopAt:
            # Return the results, and come back for more immediately
            return results, [], True

    # We've exhausted the results.  If the ensemble is no longer active, we are completely done
    if tr[dir_active[ensemble_id]] == None:
        return results, [], False

    # otherwise wait for more results to be added or the ensemble to be stopped
    return (
        results,
        [
            tr.watch(dir_all_ensembles[ensemble_id]["count"]["ended"]),
            tr.watch(dir_active[ensemble_id]),
        ],
        True,
    )


def tail_results(ensemble_id, errors_only=False, compressed=True):
    result_dirs = [dir_ensemble_results_fail]
    if not errors_only:
        result_dirs.append(dir_ensemble_results_pass)

    begin_versionstamp = 0
    more = True
    while more:
        block, watches, more = _read_and_watch_results(
            db, result_dirs, ensemble_id, begin_versionstamp
        )
        if block:
            begin_versionstamp = block[-1][0] + 1
            for item in block:
                text = item[-1] if not compressed else zlib.decompress(item[-1])
                text = text.decode(encoding="utf-8", errors="backslashreplace")
                new_item = item[:-1] + (text,)

                if is_message(text):
                    try:
                        msg = unwrap_message(text)

                        if "Message" in msg and msg["Message"] == "value_in_blob":
                            # Unpack the value from the blob.
                            key = msg["BlobKey"]
                            blob_output = BytesIO()
                            blob_version = (
                                "1" if "BlobVersion" not in msg else msg["BlobVersion"]
                            )

                            if blob_version == "1":
                                _read_blob(
                                    db, dir_ensemble_results_large[key], blob_output
                                )
                            elif blob_version == "2":
                                _read_blob(
                                    db,
                                    dir_ensemble_results_large[ensemble_id][key],
                                    blob_output,
                                )
                            else:
                                raise ValueError("Unknown BlobVersion " + blob_version)
                            decompressed = (
                                zlib.decompress(blob_output.getvalue())
                                if compressed
                                else blob_output.getvalue()
                            )
                            yield item[:-1] + (
                                decompressed.decode(
                                    encoding="utf-8", errors="backslashreplace"
                                ),
                            )
                        else:
                            yield new_item
                    except Exception as e:
                        # Could not parse the message. Just yield the item.
                        traceback.print_exc(e)
                        yield new_item
                else:
                    yield new_item
        if watches:
            fdb.Future.wait_for_any(*watches)
            for w in watches:
                w.cancel()


@transactional
def _log_agent_failure(tr, timestamp, hostname, random_bytes, error_message):
    tr[dir_failures[timestamp][hostname][random_bytes]] = error_message


def log_agent_failure(error_message):
    """Log agent failure message in the database, along with timestamp and hostname.
    :param error_message is of type string
    """
    timestamp = int(time.time())
    hostname = get_hostname()
    random_bytes = bytes(bytearray([random.getrandbits(8) for _ in range(32)]))
    _log_agent_failure(
        timestamp, hostname, random_bytes, bytes(error_message, encoding="utf-8")
    )


@transactional
def get_agent_failures(tr, time_start=None, time_end=None):
    if time_start is None:
        start_key = dir_failures.range().start
    else:
        start_key = dir_failures[time_start].pack()

    if time_end is None:
        stop_key = dir_failures.range().stop
    else:
        stop_key = dir_failures[time_end].pack()

    raw_failures = tr.get_range(start_key, stop_key)
    failures = []

    for raw_failure in raw_failures:
        raw_info = dir_failures.unpack(raw_failure.key)[
            :-1
        ]  # Last element is a random seed.
        info = (
            datetime.datetime.fromtimestamp(raw_info[0]).strftime("%Y-%b-%d (%a) %I:%M:%S %p"),
        ) + raw_info[1:]
        msg = raw_failure.value

        failures.append((info, msg))

    return failures
