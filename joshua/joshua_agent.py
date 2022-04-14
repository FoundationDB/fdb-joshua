"""
    joshua_agent.py
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

import argparse
import errno
import os
import queue
import random
import re
import shutil
import sys
import tarfile
import tempfile
import threading
import time
import traceback
import datetime

import subprocess32 as subprocess
import fdb
from . import joshua_model
from . import process_handling

try:
    import childsubreaper
except ImportError:
    print(
        "Unable to import module childsubreaper. Orphaned grandchildren will re-parent to init."
    )

# basepath = os.getcwd()
mutex = threading.Lock()
job_mutex = threading.Lock()
threadlocal = threading.local()
job_queue = queue.Queue()
jobs_pass = 0
jobs_fail = 0
stop_agent = False


# This is thrown by Joshua to indicate that there was an error.
class JoshuaError(Exception):
    def __init__(self, msg):
        self.msg = msg

    def __str__(self):
        return repr(self)

    def __repr__(self):
        return "JoshuaError(" + repr(self.msg) + ")"


# This is used to handle waiting for a given amount of time.
class TimeoutFuture(object):
    def __init__(self, timeout):
        self.cb_list = []
        self.timer = threading.Timer(timeout, self._do_on_ready)
        self.fired = False
        self.timer.start()

    def _do_on_ready(self):
        # Update the state synchronously.
        mutex.acquire()
        self.fired = True
        mutex.release()

        # Call all callbacks.
        for cb in self.cb_list:
            cb(None)

    def on_ready(self, callback):
        # Acquire a lock so that self.fired isn't changed in the middle
        # of this operation.
        mutex.acquire()

        if not self.fired:
            # Not fired yet. Add the element to the list, then release our lock.
            self.cb_list.append(callback)
            mutex.release()
        else:
            # Already fired. Call the callback immediately after releasing the lock.
            mutex.release()
            callback()


def getFileHandle():
    output_fd = getattr(threadlocal, "output_fd", None)
    return output_fd if output_fd else sys.stdout


def stopAgent():
    global stop_agent
    return stop_agent


def trim_jobqueue(cutoff_date, remove_jobs=True):
    global job_queue
    jobs_pass = 0
    jobs_fail = 0
    cutoff_string = joshua_model.format_datetime(cutoff_date)

    for job_record in list(job_queue.queue):
        (result, job_date) = fdb.tuple.unpack(job_record)
        if job_date <= cutoff_string:
            if remove_jobs:
                old_record = job_queue.get_nowait()
        elif result == 0:
            jobs_pass += 1
        else:
            jobs_fail += 1

    return (jobs_pass + jobs_fail, jobs_pass, jobs_fail)


def log(outputText, newline=True):
    return (
        print(outputText, file=getFileHandle())
        if newline
        else getFileHandle().write(outputText)
    )


def agent_init(work_dir):
    if not work_dir:
        raise JoshuaError(
            "Unable to run function since work_dir is not defined. Exiting. (CWD="
            + os.getcwd()
            + ") (PATH = "
            + os.getenv("PATH")
            + ")"
        )
    os.makedirs(ensemble_dir(basepath=work_dir), mode=0o755, exist_ok=True)
    return True


def sanitize_for_file_name(name):
    """
    >>> sanitize_for_file_name('joshua')
    'joshua'
    >>> sanitize_for_file_name('joshua/joshua')
    'joshua-joshua'
    """
    return "".join(a if a != "/" else "-" for a in name)


def ensemble_dir(ensemble_id=None, basepath=None):
    if not basepath:
        raise JoshuaError(
            "Unable to run function since basepath is not defined. Exiting. (CWD="
            + os.getcwd()
            + ") (PATH = "
            + os.getenv("PATH")
            + ")"
        )
    return os.path.join(
        *(
            (basepath, "ensembles")
            + ((sanitize_for_file_name(ensemble_id),) if ensemble_id else ())
        )
    )


def check_archive_path(name):
    path = os.path.normpath(name)
    if path.startswith("/"):
        return False
    if path.startswith(".."):
        return False
    return True


def ensure_state_test_delay():
    """
    In testing this can be overriden to introduce a delay to simulate a large
    ensemble that takes a long time to download.
    """
    pass


def ensure_state(ensemble_id, where, properties, basepath=None):
    ensure_state_test_delay()  # noop outside of testing
    if not basepath:
        raise JoshuaError(
            "Unable to run function since basepath is not defined. Exiting. (CWD="
            + os.getcwd()
            + ") (PATH = "
            + os.getenv("PATH")
            + ")"
        )
    if os.path.exists(where):
        return False

    log("Unpacking" + where)

    tmpdir = where + ".part"
    os.mkdir(tmpdir)

    with tempfile.SpooledTemporaryFile(max_size=200e6) as temp_file:
        joshua_model.get_ensemble_data(ensemble_id, temp_file)
        temp_file.seek(0)
        tarf = tarfile.open(fileobj=temp_file)

        members = tarf.getmembers()
        tarf.extractall(
            path=tmpdir,
            members=[m for m in tarf.getmembers() if check_archive_path(m.name)],
        )

    os.symlink(
        os.path.join(basepath, "global_data"), os.path.join(tmpdir, "global_data")
    )

    try:
        # Create a temporary directory within the "where" directory.
        os.mkdir(os.path.join(tmpdir, "tmp"))
    except OSError as e:
        if e.errno == errno.EEXIST:
            # The directory already exists, so no need to make it again.
            pass
        else:
            raise e

    # The rename should be atomic.  Since we haven't fsync()'d, previous operations may not be durable,
    # but the filesystem may still provide ordering.  If we are still worried about this, the easiest
    # solution is to just wipe out the ensemble_dir() on boot if we are running joshua on bare metal
    os.rename(tmpdir, where)

    return True


# Tars and gzips the contents of the sources together in a file in dest.


def tar_artifacts(ensemble, seed, sources, dest, work_dir=None):
    if not work_dir:
        raise JoshuaError(
            "Unable to run function since basepath is not defined. Exiting. (CWD="
            + os.getcwd()
            + ") (PATH = "
            + os.getenv("PATH")
            + ")"
        )
    try:
        # Create a temporary directory in the destination where we will store the results.
        out_name = "joshua-run-{0}-{1}".format(ensemble, seed)
        tmpdir = os.path.join(work_dir, out_name)
        os.makedirs(tmpdir)

        for source in sources:
            # Verify that the file exists.
            if os.path.exists(source):
                if os.path.isdir(source):
                    shutil.copytree(
                        source, os.path.join(tmpdir, os.path.basename(source))
                    )
                else:
                    shutil.copy(source, tmpdir)

        # Tar and gzip the copied files.
        with open(tmpdir + ".tar.gz", "wb") as tar_file_obj:
            tarf = tarfile.open(fileobj=tar_file_obj, mode="w:gz")
            tarf.add(tmpdir, arcname=os.path.basename(tmpdir))
            tarf.close()

        # Copy the .tar.gz file to its final destination.
        shutil.move(tmpdir + ".tar.gz", dest)

        shutil.rmtree(tmpdir)
    except Exception as e:
        # Non-critical if this fails. Just print the error and move on.
        log(e)


# Clear a directory without removing it. (i.e., "rm -rf path/*" rather than "rm -rf path")
def clear_directory(path):
    try:
        shutil.rmtree(path)
        os.mkdir(path)
    except Exception as e:
        # Non-critical if this fails. Just print the error and move on.
        log(e)


# Look for core files that might be generated by the process.
def find_cores(work_dir=None):
    if not work_dir:
        raise JoshuaError(
            "Unable to run function since work_dir is not defined. Exiting. (CWD="
            + os.getcwd()
            + ") (PATH = "
            + os.getenv("PATH")
            + ")"
        )
    cores = []
    core_pattern = re.compile(r"^core\..*$")

    for root, dirs, files in os.walk(work_dir):
        for file in files:
            if core_pattern.match(file) is not None:
                cores.append(os.path.join(root, file))

    return cores


# Removes all of the artifacts that are older than a certain limit.
# The default age to check is 24 hours.
def remove_old_artifacts(path, age=24 * 60 * 60):
    for artifact in list(os.listdir(path)):
        try:
            if time.time() - os.path.getmtime(os.path.join(path, artifact)) >= age:
                os.unlink(os.path.join(path, artifact))
        except Exception as e:
            # Non-critical. Print an error message and move on.
            log(e)


# Returns whether the artifacts should be saved based on run state.
def should_save(retcode, save_on="FAILURE"):
    return save_on == "ALWAYS" or save_on == "FAILURE" and retcode != 0


# Removes artifacts from the current run, saving them if necessary.
def cleanup(ensemble, where, seed, retcode=0, save_on="FAILURE", work_dir=None):
    if not work_dir:
        raise JoshuaError(
            "Unable to run function since work_dir is not defined. Exiting. (CWD="
            + os.getcwd()
            + ") (PATH = "
            + os.getenv("PATH")
            + ")"
        )
    # Save the results of the operation if we are supposed to do so.
    core_files = find_cores(work_dir=work_dir)
    if should_save(retcode, save_on):
        tar_artifacts(
            ensemble,
            seed,
            [os.path.join(where, "tmp")] + core_files,
            os.path.join(work_dir, "runs"),
            work_dir=work_dir,
        )

    # Delete the core files.
    for core_file in core_files:
        os.unlink(core_file)

    killing_error = None

    # Do this up to 10 times to handle processes that take longer than we would like to shutdown.
    problem_killing = False
    for i in range(10):
        problem_killing = False

        try:
            # Now that the process has ended, kill any child processes that it has
            # spawned.
            process_handling.kill_all_children()
        except Exception as e:
            problem_killing = True
            killing_error = e

        if not problem_killing:
            break

    getFileHandle().write("\n")

    # Something abnormal happened. Raise to restart machine.
    if problem_killing:
        if killing_error is None:
            raise JoshuaError(
                "Could not kill main process in a reasonable amount of time."
            )
        else:
            raise killing_error

    # Clear the temporary directory.
    clear_directory(os.path.join(where, "tmp"))


class AsyncEnsemble:
    def __init__(self):
        self._lock = threading.Lock()
        self._m_cancelled = False  # protected by lock
        self._retcode = None  # Owned by run_ensemble thread until joined, then owned by calling thread.

    def cancel(self):
        with self._lock:
            self._m_cancelled = True

    def _cancelled(self):
        with self._lock:
            return self._m_cancelled

    def run_ensemble(
        self,
        ensemble,
        seed,
        save_on="FAILURE",
        sanity=False,
        work_dir=None,
        timeout_command_timeout=60,
    ):
        try:
            self._run_ensemble(
                ensemble,
                seed,
                save_on=save_on,
                sanity=sanity,
                work_dir=work_dir,
                timeout_command_timeout=timeout_command_timeout,
            )
        except BaseException as e:
            print(e)
            self._retcode = e

    def _run_ensemble(
        self,
        ensemble,
        seed,
        save_on="FAILURE",
        sanity=False,
        work_dir=None,
        timeout_command_timeout=60,
    ):
        """
        Actually run the ensemble's test script.
        :param ensemble: ensemble ID
        :param save_on:
        :param sanity:
        :return: 0 for success
        """
        global jobs_pass, jobs_fail
        if not work_dir:
            raise JoshuaError(
                "Unable to run function since work_dir is not defined. Exiting. (CWD="
                + os.getcwd()
                + ") (PATH = "
                + os.getenv("PATH")
                + ")"
            )

        # Get its properties
        properties = joshua_model.get_ensemble_properties(ensemble)
        compressed = properties.get("compressed", False)
        command = properties.get("test_command", "./joshua_test")
        timeout_command = properties.get("timeout_command", "./joshua_timeout")
        timeout_time = properties.get("timeout", None)
        fail_fast = properties.get("fail_fast", 0)
        max_runs = properties.get("max_runs", 0)

        env = process_handling.mark_environment(os.environ)
        # Copy any env=NAME1=VALUE:NAME2=VALUE into the environment
        # We do this first so that it can't overwrite anything below.
        if "env" in properties and properties["env"]:
            env_settings = [x.split("=", 1) for x in properties["env"].split(":")]
            for k, v in env_settings:
                env[k] = v
        for k, v in properties.items():
            if k == "env":
                continue
            env["JOSHUA_" + k.upper()] = str(v)
        env["JOSHUA_SEED"] = str(seed).rstrip("L")
        # process_handling.ensure_path(env)

        #    print('{} Running ensemble in dir: {}'.format(threading.current_thread().name, work_dir),file=getFileHandle())

        # Ensure its local state exists
        where = ensemble_dir(ensemble, basepath=work_dir)
        ensure_state(ensemble, where, properties, basepath=work_dir)

        # Set environment variable to use the created temporary directory as its temporary directory.
        env["TMP"] = os.path.join(where, "tmp")

        log("{} {} {}".format(ensemble, seed, command))

        # Run the test and log output
        process = subprocess.Popen(
            command,
            cwd=where,
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        start_time = time.time()
        if timeout_time:
            timeout_time = float(timeout_time) + start_time

        output = b""
        retcode = 0

        while True:
            getFileHandle().flush()
            try:
                output, _ = process.communicate(timeout=1)
                retcode = process.poll()
                log("exit code: {}".format(retcode))
                # output = output.decode('utf-8')

                break
            except subprocess.TimeoutExpired:
                if self._cancelled():
                    log("<cancelled>")
                    retcode = -1
                    output = b""
                    break
                if timeout_time and time.time() > timeout_time:
                    log("<timed out>")
                    retcode = -2
                    output = b""
                    break
                getFileHandle().write(".")

        duration = max(1, time.time() - start_time)
        done_timestamp = joshua_model.format_datetime(datetime.datetime.now(datetime.timezone.utc))

        if retcode == -2 and time.time() > timeout_time:
            if os.path.isfile(os.path.join(where, timeout_command)):
                log("Summarizing timeout...")
                try:
                    process = subprocess.Popen(
                        timeout_command,
                        cwd=where,
                        env=env,
                        shell=True,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                    )
                    output, _ = process.communicate(timeout=timeout_command_timeout)
                    log("done")
                except Exception as e:
                    log("failed")
                    output = joshua_model.wrap_message(
                        {
                            "Error": "JoshuaTimeout",
                            "TimeoutCommandRun": "true",
                            "PythonError": str(e),
                            "PythonStack": traceback.format_exc(),
                            "Severity": "40",
                            "Ensemble": str(ensemble),
                            "Seed": str(seed),
                            "Sanity": str(sanity),
                            "TimeoutSeconds": str(timeout_command_timeout),
                        }
                    )

            else:
                output = joshua_model.wrap_message(
                    {
                        "Error": "JoshuaTimeout",
                        "TimeoutCommandRun": "false",
                        "Severity": "40",
                    }
                )

        # Write the output to the tmp directory so that it is picked up when we save (if we do so).
        if should_save(retcode, save_on):
            try:
                to_write = os.path.join(where, "tmp", "console.log")

                i = 0
                while os.path.exists(to_write):
                    to_write = os.path.join(where, "tmp", "console-{0}.log".format(i))
                    i += 1

                with open(to_write, "wb") as fout:
                    fout.write(output)

            except OSError as e:
                # Could not write. Not fatal. Log and move on.
                log("Could not write console output.")
                log(traceback.format_exc())
                log("Moving on...")

        cleanup(ensemble, where, seed, retcode, save_on, work_dir=work_dir)

        try:
            joshua_model.insert_results(
                ensemble,
                seed,
                retcode,
                output,
                compressed,
                sanity,
                fail_fast,
                max_runs,
                duration,
            )
        except joshua_model.FDBError as e:
            # Since insert_results is wrapped by the @fdb.transactional, e is non-retryable.
            joshua_model.insert_results(
                ensemble,
                seed,
                e.code,
                bytes(joshua_model.wrap_error(e.description), encoding="utf-8"),
                compressed,
                sanity,
                fail_fast,
                max_runs,
                duration,
            )

        # Add the result to the job queue
        job_queue.put(fdb.tuple.pack((retcode, done_timestamp)))

        # Update the job counts
        job_mutex.acquire()
        if retcode == 0:
            jobs_pass += 1
        else:
            jobs_fail += 1
        job_mutex.release()

        self._retcode = retcode


def run_ensemble(
    ensemble, save_on="FAILURE", sanity=False, work_dir=None, timeout_command_timeout=60
):
    seed = random.getrandbits(63)

    if not joshua_model.try_starting_test(ensemble, seed, sanity):
        log("<job stopped>")
        return -3

    # At this point we've acquired a run of this ensemble in the sense that we
    # have incremented `started`, so we need to heartbeat until we increment
    # `ended` or get stopped

    asyncEnsemble = AsyncEnsemble()
    asyncEnsembleThread = threading.Thread(
        target=asyncEnsemble.run_ensemble,
        args=(ensemble, seed),
        kwargs={
            "save_on": save_on,
            "sanity": sanity,
            "work_dir": work_dir,
            "timeout_command_timeout": timeout_command_timeout,
        },
    )
    asyncEnsembleThread.setDaemon(True)
    asyncEnsembleThread.start()
    while True:
        asyncEnsembleThread.join(timeout=1)  # heartbeating frequency
        if asyncEnsembleThread.is_alive():
            if not joshua_model.heartbeat_and_check_running(ensemble, seed, sanity):
                asyncEnsemble.cancel()
        else:
            assert asyncEnsemble._retcode is not None
            if not isinstance(asyncEnsemble._retcode, int):
                raise asyncEnsemble._retcode
            return asyncEnsemble._retcode


def agent(
    agent_timeout=None,
    save_on="FAILURE",
    sanity_period=None,
    agent_idle_timeout=None,
    timeout_command_timeout=60,
    stop_file=None,
    log_file=None,
    work_dir=None,
):
    if not work_dir:
        raise JoshuaError(
            "Unable to run function since work_dir is not defined. Exiting. (CWD="
            + os.getcwd()
            + ") (PATH = "
            + os.getenv("PATH")
            + ")"
        )
    if log_file:
        threadlocal.output_fd = open(log_file, "w+")
    # Make sure "ensembles" directory exists.
    os.makedirs(ensemble_dir(basepath=work_dir), mode=0o755, exist_ok=True)

    start = time.time()  # Used later to limit time agent runs.
    idle_start = start  # Used to determine idle duration

    try:
        # Run all of the sanity tests first, and if any of them fail, exit.
        sanity_ensembles = joshua_model.list_sanity_ensembles()
        for ensemble, _ in sanity_ensembles:
            retcode = run_ensemble(
                ensemble,
                save_on,
                sanity=True,
                work_dir=work_dir,
                timeout_command_timeout=timeout_command_timeout,
            )

            if retcode != 0:
                raise JoshuaError(
                    "Unable to run sanity test successfully as machine started up. Exiting. (PATH = "
                    + os.getenv("PATH")
                    + ")"
                )

        # Keep track of the last time the sanity tests were run so we know if it's time to do another.
        last_sanity = time.time()

        watch = None
        sanity_watch = None

        while True:
            # Break if the stop file is defined and present
            if stop_file and os.path.exists(stop_file):
                log("Exiting due to existing stopfile: {}".format(stop_file))
                break
            # Break if requested
            if stopAgent():
                log("Exiting due to global request")
                break

            if (not watch) or watch.is_ready():
                ensembles, watch = joshua_model.list_and_watch_active_ensembles()

            # Run sanity tests now (before clearing).
            if sanity_watch and sanity_watch.is_ready():
                (
                    sanity_ensembles,
                    sanity_watch,
                ) = joshua_model.list_and_watch_sanity_ensembles()

                # One or more of the sanity tests changed. Re-run them.
                for ensemble in sanity_ensembles:
                    retcode = run_ensemble(
                        ensemble,
                        save_on,
                        sanity=True,
                        work_dir=work_dir,
                        timeout_command_timeout=timeout_command_timeout,
                    )

                    if retcode != 0:
                        raise JoshuaError(
                            "Unable to run sanity test successfully after new test uploaded. Exiting. (PATH = "
                            + os.getenv("PATH")
                            + ")"
                        )

                last_sanity = time.time()
                continue

            elif not sanity_watch:
                (
                    sanity_ensembles,
                    sanity_watch,
                ) = joshua_model.list_and_watch_sanity_ensembles()

            # If we haven't run the sanity tests in the specified amount of time; run them again.
            if sanity_period is not None and time.time() - last_sanity >= sanity_period:
                for ensemble in sanity_ensembles:
                    retcode = run_ensemble(
                        ensemble,
                        save_on,
                        sanity=True,
                        work_dir=work_dir,
                        timeout_command_timeout=timeout_command_timeout,
                    )

                    if retcode != 0:
                        raise JoshuaError(
                            "Unable to run sanity test successfully during periodic run. Exiting. (PATH = "
                            + os.getenv("PATH")
                            + ")"
                        )

                last_sanity = time.time()
                continue

            # Before beginning, look for zombies.
            # zombies = process_handling.any_zombies()
            # if zombies:
            #    print('\n'.join(zombies))
            #    raise JoshuaError('Zombie process (' + str(zombies) + ') present (before beginning)!')

            # FIXME: Temporarily disabling this. Probably we should decide whether we are doing this or not.
            # As part of routine maintenance, get rid of artifacts.
            # remove_old_artifacts(os.path.join(basepath, 'runs'))

            # Throw away local state for ensembles that are no longer active
            local_ensemble_dirs = set(os.listdir(ensemble_dir(basepath=work_dir)))
            for e in (local_ensemble_dirs - set(ensembles)) - set(sanity_ensembles):
                log("removing {} {}".format(e, ensemble_dir(e, basepath=work_dir)))
                shutil.rmtree(
                    ensemble_dir(e, basepath=work_dir), True
                )  # SOMEDAY: this sometimes throws errors, but we don't know why and it isn't that important

            ensembles_can_run = None
            if ensembles:
                ensembles_can_run = list(
                    filter(joshua_model.should_run_ensemble, ensembles)
                )
                if not ensembles_can_run:
                    # All the ensembles have enough runs started for now. Don't
                    # time the agent out, just wait until there are no
                    # ensembles or the other agents might have died.
                    time.sleep(1)
                    continue
            else:
                # No ensembles at all. Consider timing this agent out.
                try:
                    watch.wait_for_any(watch, sanity_watch, TimeoutFuture(1.0))
                except Exception as e:
                    log("watch error: {}".format(e))
                    watch = None
                    time.sleep(1.0)

                # End the loop if we have exceeded the time given.
                now = time.time()
                if (agent_timeout is not None and now - start >= agent_timeout) or (
                    agent_idle_timeout is not None
                    and now - idle_start >= agent_idle_timeout
                ):
                    log("Agent timed out")
                    break
                else:
                    continue

            assert ensembles_can_run

            # Pick an ensemble to run. Weight by amount of time spent on each one.

            #            print('{} Picking from {} ensembles'.format(threading.current_thread().name, len(ensembles)))
            durations = joshua_model.get_ensemble_mean_durations(ensembles_can_run)
            priorities = joshua_model.get_ensemble_priorities(ensembles_can_run)
            buckets = [(en, priorities[en] / durations[en]) for en in ensembles_can_run]
            choice = random.random() * sum([width for _, width in buckets])
            chosen_ensemble = None
            so_far = 0.0
            #            print('{} Running {} ensembles'.format(threading.current_thread().name, len(buckets)))
            for ensemble, width in buckets:
                so_far += width
                if so_far >= choice:
                    chosen_ensemble = ensemble
                    break
            assert chosen_ensemble is not None
            retcode = run_ensemble(
                chosen_ensemble,
                save_on,
                work_dir=work_dir,
                timeout_command_timeout=timeout_command_timeout,
            )
            # Exit agent gracefully via stopfile on probable zombie process
            if retcode == -1 or retcode == -2:
                if stop_file is None:
                    stop_file = sys.executable
                    log(
                        "Defining exiting stopfile: {} to prevent zombie ({})".format(
                            stop_file, retcode
                        )
                    )
                elif not os.path.exists(stop_file):
                    log(
                        "Creating stopfile: {} to prevent zombie ({})".format(
                            stop_file, retcode
                        )
                    )
                    open(stop_file, "a").close()
                else:
                    log(
                        "Happy for existing stopfile: {} preventing zombie ({})".format(
                            stop_file, retcode
                        )
                    )

            # reset idle timer
            idle_start = time.time()

            # Look for zombies after running.
            # zombies = process_handling.any_zombies()
            # if zombies:
            #    print('\n'.join(zombies))
            #    raise JoshuaError('Zombie process (' + str(zombies) + ') present (after end)!')
    except:
        joshua_model.log_agent_failure(traceback.format_exc())
        raise


def reap_children():
    # Call prctl(PR_SET_CHILD_SUBREAPER) so that grandchildren re-parent to this process instead of init.
    if "childsubreaper" in dir():
        retcode = childsubreaper.set_child_subreaper()

        if retcode != 0:
            print(
                "Call prctl(PR_SET_CHILD_SUBREAPER) returned non-zero error code ",
                retcode,
            )
            print("Orphaned grandchildren may re-parent to init.")


if __name__ == "__main__":
    reap_children()

    stop_file = os.environ.get("AGENT_STOPFILE", None)

    name_space = os.environ.get("JOSHUA_NAMESPACE", "joshua")
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-C", "--cluster-file", default=None, help="Cluster file for Joshua database"
    )
    parser.add_argument(
        "-D",
        "--dir-path",
        nargs="+",
        default=(name_space,),
        help="top-level directory path in which joshua operates",
    )
    parser.add_argument(
        "--apoptosis",
        type=int,
        default=None,
        help="A pseudo-randomized amount of time (in seconds) to wait before the agent "
        "kills itself in order to prevent agent decay. It is fuzzed to avoid mass "
        "destruction, and it is never the case that the box is shut down during a "
        "test. Default behavior is to never purposefully die.",
    )
    parser.add_argument(
        "--save-on",
        choices=["ALWAYS", "FAILURE", "NEVER"],
        default="FAILURE",
        help="How often Joshua should save the artifacts "
        "of a run. The default is to save on FAILURE (when a test fails), but other "
        "options are ALWAYS (every run) or NEVER (no runs).",
    )
    parser.add_argument(
        "--sanity-period",
        type=int,
        default=None,
        help="The period between runs of the sanity test in seconds. In other words, "
        "if 3600 is provided as an argument to this, every hour (more or less), the "
        "agent will run all of the sanity tests again.",
    )
    parser.add_argument(
        "--agent-idle-timeout",
        type=int,
        default=None,
        help="An amount of time (in seconds) the agent waits for a new ensemble "
        "to arrive. If it does not discover a new ensemble within this period, "
        "it will exit. The default is to never timeout.",
    )
    parser.add_argument(
        "--timeout-command-timeout",
        type=int,
        default=60,
        help="An amount of time (in seconds) the agent waits for the timeout "
        "script to complete. If it does not complete within this period, "
        "it will exit. The default is 60 seconds.",
    )
    parser.add_argument(
        "-W",
        "--work_dir",
        default=None,
        help="Specify work directory to run the agent.",
    )
    parser.add_argument(
        "-S",
        "--stop_file",
        default=stop_file,
        help="Specify file whose existence will cause agent to stop.",
    )
    arguments = parser.parse_args()

    if arguments.apoptosis is not None:
        # Timeout is equal to the given argument with a random fuzz up to 50% of the argument.
        # This is added to avoid having 500+ Mesos boxes suddenly crying out in terror and
        # being suddenly silenced.
        agent_timeout = int(arguments.apoptosis * (1 + 0.5 * random.random()))
    else:
        agent_timeout = None

    joshua_model.open(arguments.cluster_file, arguments.dir_path)
    agent_init(arguments.work_dir)

    # Running everything (esp ctypes blocking calls) in a thread makes the program much more responsive to KeyboardInterrupt
    t = threading.Thread(
        target=agent,
        args=(),
        kwargs={
            "agent_timeout": agent_timeout,
            "save_on": arguments.save_on,
            "sanity_period": arguments.sanity_period,
            "agent_idle_timeout": arguments.agent_idle_timeout,
            "timeout_command_timeout": arguments.timeout_command_timeout,
            "stop_file": arguments.stop_file,
            "work_dir": arguments.work_dir,
        },
    )
    t.daemon = True
    t.start()
    while t.is_alive():
        t.join(6000)
