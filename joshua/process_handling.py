"""
    process_handling.py

    This is a collection of utility functions that are useful for handling
    processes. They include the tools necessary to determine which processes
    are subprocesses of the current Joshua process by looking at the appropriate
    environment variables.
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


import errno
import os
import re
import signal
import subprocess
import threading
import time

VAR_NAME = "OF_HOUSE_JOSHUA"


# Create an alarm handler that is used to do timeouts.
class TimeoutError(RuntimeError):
    pass


def alarm_handler(*args):
    raise TimeoutError


signal.signal(signal.SIGALRM, alarm_handler)


# Determines if there is a running process with a given PID. The PID
# should be given in integer form.
def check_alive(pid):
    try:
        # Sends signal 0 (which is ignored) to the given process.
        os.kill(pid, 0)
        return True
    except OSError as e:
        if e.errno == errno.ESRCH:
            # No such process exists. The process is dead.
            return False
        elif e.errno == errno.EPERM:
            # Process exists, but we don't have permission to kill it.
            return True
        else:
            # A more serious error. Propagate the error upwards.
            raise e


# Add an environment variable to the given dictionary with
# this processes PID.
def mark_environment(env, pid=str(os.getpid())):
    env2 = dict(env)
    env2[VAR_NAME] = pid
    return env2


# This gets all of the currently running process IDs. They are returned
# as a list of strings.
# NOTE: This only runs on Linux--NOT macOS.
# (There is a library, psutil, that works cross-platform, and
# maybe we should consider going to that at some point, but for now,
# this is sufficient, and it doesn't require downloading more open-
# source software.)
def get_all_process_pids():
    pids = os.listdir("/proc")
    is_number = re.compile(r"^\d+$")
    return filter(lambda x: is_number.match(x) is not None, pids)


# Given the PID, this returns the environment of the running process.
def get_environment(pid):
    # Make sure the PID is an integer.
    if type(pid) is int:
        pid = str(pid)

    try:
        # Read the environment information and convert it into a dictionary.
        with open(os.path.join("/proc", pid, "environ"), "rb") as env_file:
            env_str = env_file.read()
            var_strs = filter(lambda x: len(x) > 0, env_str.split(b"\x00"))
            return dict(
                map(
                    lambda var_str: (
                        var_str[: var_str.find(b"=")],
                        var_str[var_str.find(b"=") + 1 :],
                    ),
                    var_strs,
                )
            )
    except IOError:
        # This is not our process, so we can't open the file.
        return dict()


# Get all child processes by looking for those with the correct
# Joshua ID.
def retrieve_children(pid=str(os.getpid())):
    def check(candidate):
        env = get_environment(candidate)
        return VAR_NAME in env and env[VAR_NAME] == pid

    return filter(check, get_all_process_pids())


# Waits for the death of a process, but no longer than timeout. It returns
# true if the process ended and false if it timed out or if there was some
# kind of error. This is probably caused by the process not existing, but
# good to return this was an error instead.
#     <i>Because death could not stop for me -- I kindly stopped for him.</i>
#                                           -- Emily Dickinson
def wait_for_death(pid, timeout=5):
    def wait_helper(p):
        try:
            os.waitpid(p, 0)
        except OSError as e:
            if e.errno == errno.ECHILD:
                # No process exists. Most likely, the process has already exited.
                pass
            else:
                raise e

    try:
        # Create a threading object and to wait for the pid to die.
        t = threading.Thread(target=wait_helper, args=(pid,))
        t.start()

        # Actually wait for death, only going as far as timeout.
        t.join(timeout=timeout)

        # Success.
        ret_val = True
    except Exception:
        # Something bad happened. Assume this failed.
        ret_val = False

    sys.stdout.write(">")
    sys.stdout.flush()

    return ret_val


# Kills all the processes spun off from the current process.
def kill_all_children(pid=str(os.getpid())):
    child_pids = list(sorted(map(int, retrieve_children(pid))))

    if len(child_pids) == 0:
        return True

    # Send the terminate signal to each.
    for child_pid in child_pids:
        try:
            # Kill, then wait for death for each process.
            os.kill(child_pid, signal.SIGKILL)
            wait_for_death(child_pid)
        except OSError:
            # We couldn't kill the current process (possibly
            # because it is already dead).
            pass

    # Because os.waitpid still has issues..
    # FIXME: This may actually be unnecessary.
    time.sleep(1)

    stragglers = len(filter(check_alive, child_pids))

    if stragglers > 0:
        # Could not kill everything. Raise an error to force restart.
        raise OSError("Not all of the child processes could be killed during cleanup.")

    # As a final check, retrieve all child PIDs. If there's anything
    # here, it means that there are still some processes were started
    # up after we identified those that were to be killed.
    new_child_pids = len(retrieve_children(pid))
    if new_child_pids > 0:
        raise OSError("New processes were begun after children were identified.")

    return True


# Check all running subprocesses to see if a zombie was created.
def any_zombies():
    out, err = subprocess.Popen(["ps", "-ef"], stdout=subprocess.PIPE).communicate()

    if err is not None:
        raise OSError(
            "Process list information was not successfully retrieved. Error number = "
            + str(err)
        )

    # Look for the string "<defunct>" in the process listing and return true if anything contains it.
    # Ignore any that contain "health_check" as those are currently being injected into the
    # environment but are not from us:
    #   <rdar://problem/42791356> Healthcheck agent is leaving zombie processes visible to application
    return list(
        filter(
            lambda x: "<defunct>" in x and not "health_check" in x,
            out.decode("utf-8").split("\n"),
        )
    )


# UNIT TESTS
import unittest
import sys


class TestProcessHandling(unittest.TestCase):
    def test_check_alive(self):
        # Start long-running process.
        process = subprocess.Popen(
            ["sleep", "100"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )

        self.assertTrue(check_alive(process.pid))
        os.kill(process.pid, signal.SIGKILL)
        process.communicate()  # Wait for kill
        self.assertFalse(check_alive(process.pid))

    def test_mark_env(self):
        env = mark_environment(dict())
        self.assertEquals(os.getpid(), int(env[VAR_NAME]))

    def test_get_all_pids(self):
        if sys.platform != "linux2":
            self.fail("This platform is not supported.")
        else:
            pids = get_all_process_pids()
            self.assertTrue(len(pids) > 0)  # More than 1 running process.

            # Each should be a number.
            try:
                pid_nums = map(int, pids)
            except ValueError:
                self.fail("Does not return only integers.")

            # Each should be a directory in the given file.
            for pid in pids:
                self.assertTrue(os.path.isdir(os.path.join("/proc", pid)))

            # This should contain a number of processes, but this one is a
            # good starting point to check.
            self.assertTrue(str(os.getpid()) in pids)

    def test_get_environment(self):
        if sys.platform != "linux2":
            self.fail("This platform is not supported")
        else:
            # Make sure the environment for this process is the same
            # as we know it to be.
            env = get_environment(str(os.getpid()))
            self.assertEquals(env, os.environ)
            env = get_environment(os.getpid())
            self.assertEquals(env, os.environ)

    def test_retrieve_children(self):
        if sys.platform != "linux2":
            self.fail("This platform is not supported")
        else:
            env = mark_environment(os.environ)
            for i in range(10):
                subprocess.Popen(
                    ["sleep", "2"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            pids = retrieve_children()
            self.assertEquals(len(pids), 10)

    def test_kill_all_children(self):
        if sys.platform != "linux2":
            self.fail("This platform is not supported")
        else:
            env = mark_environment(os.environ)
            for i in range(10):
                subprocess.Popen(
                    ["sleep", "100"],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            self.assertTrue(kill_all_children())
            self.assertEquals(len(retrieve_children()), 0)

    def test_wait_for_death(self):
        process = subprocess.Popen(
            ["sleep", "2"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        # self.assertFalse(wait_for_death(process.pid, timeout=1))
        process = subprocess.Popen(
            ["sleep", "1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        self.assertTrue(wait_for_death(process.pid))

    def test_any_zombies(self):
        self.assertFalse(any_zombies())
        # Ideally, this unit test would also have a "false" case, but making a zombie is risky business
        # so is probably best avoided.


if __name__ == "__main__":
    unittest.main()
