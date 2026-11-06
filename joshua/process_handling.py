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


import os
import subprocess

import psutil

VAR_NAME = "OF_HOUSE_JOSHUA"


# Add an environment variable to the given dictionary with
# this processes PID.
def mark_environment(env, pid=str(os.getpid())):
    env2 = dict(env)
    env2[VAR_NAME] = pid
    return env2


# Get all processes started by this process, by looking for those with the
# correct Joshua ID in their environment. Unlike walking the process tree,
# this also finds descendants that were orphaned and re-parented to init.
def retrieve_children(pid=str(os.getpid())):
    children = []
    for process in psutil.process_iter():
        try:
            if process.pid != os.getpid() and process.environ().get(VAR_NAME) == pid:
                children.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            # Already gone (or a zombie), or not our process.
            pass
    return children


# A zombie is dead, but can't be reaped by us if it isn't our direct child
# (e.g. it was orphaned and re-parented to init).
def _is_alive(process):
    try:
        return process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


# Kills all the processes spun off from the current process.
def kill_all_children(pid=str(os.getpid())):
    children = retrieve_children(pid)

    if len(children) == 0:
        return True

    for child in children:
        try:
            child.kill()
        except psutil.NoSuchProcess:
            pass

    # Reaps those which are our direct children.
    # Note: psutil 7.x waits on processes with pidfd_open(), it can get EINVAL and raise it up
    # instead of treating process as gone. https://github.com/giampaolo/psutil/issues/2715
    _, alive = psutil.wait_procs(children, timeout=5)
    stragglers = [p for p in alive if _is_alive(p)]

    if stragglers:
        # Could not kill everything. Raise an error to force restart.
        raise OSError("Not all of the child processes could be killed during cleanup.")

    # As a final check, retrieve all child PIDs. If there's anything
    # here, it means that there are still some processes were started
    # up after we identified those that were to be killed.
    if retrieve_children(pid):
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
            lambda x: "<defunct>" in x and "health_check" not in x,
            out.decode("utf-8").split("\n"),
        )
    )
