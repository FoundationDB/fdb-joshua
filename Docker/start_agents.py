#!/usr/bin/env python3
#
# start_agents.py
#
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
import logging
import os
import psutil
import subprocess
import random
import time
import errno
import signal
import sys
from joshua import joshua_agent, joshua_model
from threading import Thread, Lock, current_thread
import datetime

mutex = Lock()
agents_desired = 0
joshua_stopfile = None
start_time = datetime.datetime.now(datetime.timezone.utc)


def receiveSignal(signalNumber, frame):
    print('Received signal:', signalNumber)
    return


def terminateProcess(signalNumber, frame):
    global joshua_stopfile
    global agents_desired
    print('(SIGTERM) terminating the process')
    agents_desired = 0
    if joshua_stopfile:
        open(joshua_stopfile, 'a').close()


def signal_registration():
    signal.signal(signal.SIGHUP, receiveSignal)
    signal.signal(signal.SIGINT, terminateProcess)
    signal.signal(signal.SIGQUIT, receiveSignal)
    signal.signal(signal.SIGILL, receiveSignal)
    signal.signal(signal.SIGTRAP, receiveSignal)
    signal.signal(signal.SIGABRT, receiveSignal)
    signal.signal(signal.SIGBUS, receiveSignal)
    signal.signal(signal.SIGFPE, receiveSignal)
    signal.signal(signal.SIGCHLD, signal.SIG_IGN)
    #signal.signal(signal.SIGKILL, receiveSignal)
    signal.signal(signal.SIGUSR1, receiveSignal)
    signal.signal(signal.SIGSEGV, receiveSignal)
    signal.signal(signal.SIGUSR2, receiveSignal)
    signal.signal(signal.SIGPIPE, receiveSignal)
    signal.signal(signal.SIGALRM, receiveSignal)
    signal.signal(signal.SIGTERM, terminateProcess)
    joshua_agent.reap_children()
    return 0


# Reap any dead children
def reap_deadchildren():
    dead_children = 0
    try:
        # This will raise an exception most of the time because
        # there are very often no children. That's ok.
        # We just want to check, reap if any, and leave
        pid, exit_code = os.waitpid(0, os.WNOHANG)
        if pid:
            if exit_code == 0:
                exit_status = 'passed'
            elif exit_code == 15:
                exit_status = 'killed'
            else:
                exit_status = 'failed'
            logger.info('Child PID {} {} with exit code: {}'.format(
                pid, exit_status, exit_code))
            dead_children += 1
    except OSError as e:
        # Raise error unless complaint about no more children
        if e.errno != 10:
            logger.info('OS error reaping children: {}'.format(e))
    except:
        logger.info('Undefined error reaping children')
        raise
    return dead_children


def rename_failed_agent_dir(agent_id, run_dir):
    work_dir = os.path.join(run_dir, str(agent_id))
    if os.path.exists(work_dir):
        os.rename(work_dir, '{}.failed'.format(work_dir))


def determine_agents_needed(current_agents, max_agents, free_cpus, total_cpus):
    load_average = psutil.getloadavg()
    # Allow for some noise to count as a cpu
    cpus_used = int(load_average[0] + 0.8) if load_average is not None else 0
    available_cpus = total_cpus - cpus_used - free_cpus
    agents_needed = min(max_agents - current_agents,
                        available_cpus) if available_cpus > 0 else max(
                            -current_agents, available_cpus)
    return agents_needed if agents_needed <= int(
        100.0 / args.growth_rate) else int(
            round(agents_needed * args.growth_rate / 100.0))


def agent_thread(work_dir,
                 agent_timeout=None,
                 save_on='FAILURE',
                 sanity_period=None,
                 agent_idle_timeout=None,
                 stop_file=None,
                 log_file=None,
                 thread_array=None):
    global agents_desired
    exit_status = None
    exit_code = 0
    threads_left = -1
    rename_dir = False
    thread_id = current_thread().ident
    thread_name = current_thread().name
    try:
        joshua_agent.agent(agent_timeout=agent_timeout,
                           save_on=save_on,
                           sanity_period=sanity_period,
                           agent_idle_timeout=agent_idle_timeout,
                           stop_file=stop_file,
                           log_file=log_file,
                           work_dir=work_dir)
        exit_status = 'passed'
    except OSError as e:
        logger.info(
            'OS error running agent: {}  exit code: {} because {}'.format(
                thread_id, e.errno, e))
        exit_code = e.errno
        if exit_code == 10:
            exit_status = 'killed'
        else:
            exit_status = 'failed'
            rename_dir = True

    if thread_array:
        mutex.acquire()
        agent_id = thread_array.pop(thread_id)
        threads_left = len(thread_array)
        mutex.release()
        if threads_left > agents_desired:
            if not joshua_agent.stop_agent:
                joshua_agent.stop_agent = True
                logger.info(
                    '%-13s Enabled stopping of agent threads  %2d > %2d' %
                    (thread_name, threads_left, agents_desired))
        elif joshua_agent.stop_agent:
            joshua_agent.stop_agent = False
            logger.info('%-13s Disabled stopping of agent threads  %2d <= %2d' %
                        (thread_name, threads_left, agents_desired))
    logger.info('%-13s %-6s  %2d of %2d threads left' %
                (thread_name, exit_status, threads_left, agents_desired))

    if rename_dir:
        rename_failed_agent_dir(agent_id, args.dir)

    return


def start_agent(i, run_dir, thread_array):
    work_dir = os.path.join(run_dir, str(i))
    stop_file = os.path.join(run_dir, '{}.stop'.format(i))
    log_file = os.path.join(run_dir, '{}.log'.format(i))

    # Initialize the agent
    joshua_agent.agent_init(work_dir)

    # Start the agent thread
    t = Thread(target=agent_thread,
               args=(),
               kwargs={
                   'thread_array': thread_array,
                   'agent_timeout': None,
                   'save_on': 'FAILURE',
                   'sanity_period': None,
                   'agent_idle_timeout': None,
                   'stop_file': stop_file,
                   'log_file': log_file,
                   'work_dir': work_dir
               })

    # Start the thead
    t.start()

    return t


def create_agents(new_amount, children_array, nextAgentId, max_agents):
    if new_amount > 0:
        logger.info('Spawning %2d new agents  %2d => %2d (max %2d)' %
                    (new_amount, len(children_array),
                     new_amount + len(children), max_agents))
        for i in range(new_amount):
            t = start_agent(nextAgentId, args.dir, children_array)
            logger.info('Spawned #%2d of %2d: (%s) %s' %
                        (i + 1, new_amount, t.ident, t.name))
            mutex.acquire()
            children_array[t.ident] = nextAgentId
            mutex.release()
            nextAgentId += 1
    return max(0, new_amount)


def get_free_space(data_dir):
    statvfs = os.statvfs(data_dir)
    free_space = statvfs.f_bsize * statvfs.f_bavail / (1024 * 1024 * 1024)
    return free_space


# Return the number of active ensembles
def get_ensemble_total():
    ensembles, watch = joshua_model.list_and_watch_active_ensembles()
    return len(ensembles)


def joshua_report(total_cpus, max_agents, children_array):
    global agents_desired
    jobs_pass = joshua_agent.jobs_pass
    jobs_fail = joshua_agent.jobs_fail

    # Display Agent informaton
    logger.info(
        'Total Cpus    :%5d  free:   %6d  time: %s' %
        (total_cpus, args.free_cpus,
         joshua_model.format_timedelta(
             datetime.datetime.now(datetime.timezone.utc) - start_time)))

    # Display Agent informaton
    logger.info('Agents current:%5d  desired:%6d  max: %8d' %
                (len(children_array), agents_desired, max_agents))

    # Display Job informaton
    logger.info('Jobs   active:%6d  pass:%9d  fail:%8d' %
                (get_ensemble_total(), jobs_pass, jobs_fail))

    # Trim the job queue to the last hour
    hour_ago = datetime.datetime.now(
        datetime.timezone.utc) - datetime.timedelta(hours=1)
    (hour_done, hour_pass,
     hour_fail) = joshua_agent.trim_jobqueue(hour_ago, True)

    # Display Rate informaton
    hour_fraction = 1.0 if hour_ago >= start_time else (
        (datetime.datetime.now(datetime.timezone.utc) -
         start_time).total_seconds() / 3600)
    logger.info('Hourly done:%8.2f  pass:%9.2f  fail:%8.2f' %
                (hour_done / hour_fraction, hour_pass / hour_fraction,
                 hour_fail / hour_fraction))

    # Display free space report every so often
    logger.info('Free space: %8.2f GB   > %8.2f GB' %
                (get_free_space(args.dir), args.free_space))


def manage_agents(total_cpus, max_agents, joshua_stopfile, children_array):
    global agents_desired
    nextAgentId = 1
    stop_processed = False
    watch = None
    cycles = 0
    death_cycles = 0

    while True:
        cycles += 1
        stopping = False
        agents_needed = None

        # Determine the number of active ensembles
        ensembles_total = get_ensemble_total()

        # Check for stop file
        if not stop_processed and not stopping and os.path.exists(
                joshua_stopfile):
            logger.info(
                'Encountered stop file: %s  stopping all agents  %2d => %2d (max %2d)'
                % (joshua_stopfile, len(children_array), 0, max_agents))
            agents_needed = -len(children_array)
            stopping = True

        # Check the disk space
        if not stop_processed and not stopping:
            # Get the amount of free space
            free_space = get_free_space(args.dir)
            if free_space < args.free_space:
                logger.info(
                    'Stopping joshua with %2d agents because lack of free disk space %6.2f GB < %6.2f GB'
                    % (len(children_array), free_space, args.free_space))
                agents_needed = -len(children_array)
                stopping = True

        # Determine the number of desired agents
        if not stop_processed and not stopping:
            # Use the cpu calculation, if ensembles are present
            if ensembles_total > 0:
                agents_needed = determine_agents_needed(len(children_array),
                                                        max_agents,
                                                        args.free_cpus,
                                                        total_cpus)

            # If no ensembled but still agents desired, stop
            # stop all agents
            elif agents_desired > 0:
                logger.info(
                    'Stopping all %2d agents because no ensembles found' %
                    (len(children_array)))
                agents_needed = -len(children_array)

            # Let's make sure that we get to our desired goal
            else:
                agents_needed = -len(children_array)

        # Process Agent changes
        #
        # Do nothing, if amount of agent's needed was
        # not defined
        if not agents_needed:
            pass

        # Create new agents, if needed
        elif agents_needed > 0:
            # Update the desired number of agents
            agents_desired = len(children_array) + agents_needed
            if joshua_agent.stop_agent:
                joshua_agent.stop_agent = False
                logger.info('Disabled stopping of agent threads  %2d < %2d' %
                            (len(children_array), agents_desired))
            nextAgentId += create_agents(agents_needed, children_array,
                                         nextAgentId, max_agents)

        # Stop existing agents, if needed
        elif agents_needed < 0:
            # Update the desired number of agents
            agents_desired = len(children_array) + agents_needed
            logger.info('Stopping %2d agents  %2d => %2d (max %2d)' %
                        (-agents_needed, len(children_array), agents_desired,
                         max_agents))
            if not joshua_agent.stop_agent:
                joshua_agent.stop_agent = True
                logger.info('Enabled stopping of agent threads  %2d > %2d' %
                            (len(children_array), agents_desired))

        # If we have the perfect number but are still stopping
        # agents, disable the stop request
        elif joshua_agent.stop_agent:
            joshua_agent.stop_agent = False
            logger.info('Disabled stopping of agent threads  %2d == %2d' %
                        (len(children_array), agents_desired))

        # Display report on its frequency
        if not (cycles - 1) % int(args.report_freq * 60 / args.mgr_sleep):
            joshua_report(total_cpus, max_agents, children_array)

        # Process Waits
        #

        # Always reap any dead children
        reap_deadchildren()

        # Sleep for a while, if not stopping
        if not stop_processed and not stopping:
            time.sleep(args.mgr_sleep)

        # Stop if all agents are dead
        elif not children_array:
            break

        # Process the first stop, if not processed
        elif not stop_processed:
            stop_processed = True
            time.sleep(args.death_wait)
            death_cycles += 1

        # If we have gone through more than 5 death cycles
        # and there are no ensembles, exit
        elif death_cycles > 5 and ensembles_total == 0:
            logger.info(
                'Exiting with %2d agents waiting for empty ensemble queue' %
                (len(children_array)))
            break

        # If we have not exceeded are max death wait, wait
        elif death_cycles < (args.max_death_wait / args.death_wait):
            logger.info('Waiting for %2d agents before exiting' %
                        (len(children_array)))
            time.sleep(args.death_wait)
            death_cycles += 1

        # We have exceeded the max death wait, so exit
        else:
            logger.info(
                'Exiting with %2d agents serving %2d ensembles after waiting %2d seconds'
                % (len(children_array), ensembles_total,
                   args.death_wait * death_cycles))
            break

    # Display a final report
    joshua_report(total_cpus, max_agents, children_array)


if __name__ == "__main__":
    # Register the signals
    signal_registration()

    cluster_file = os.environ.get('CLUSTER_FILE', '/opt/joshua/fdb.cluster')
    work_dir = os.environ.get('AGENT_WORK_DIR', '/tmp/joshua_agent')
    max_agents = int(os.environ.get('AGENT_TOTAL', '0'))
    priority = int(os.environ.get('AGENT_PRIORITY', '0'))
    free_cpus = int(os.environ.get('AGENT_FREECPUS', '0'))
    mgr_sleep = int(os.environ.get('AGENT_MGRSLEEP', '30'))
    report_freq = float(os.environ.get('AGENT_REPORTFREQ', '10.0'))
    free_space = float(os.environ.get('AGENT_FREESPACE', '10.0'))
    death_wait = int(os.environ.get('AGENT_DEATHWAIT', '10'))
    name_space = os.environ.get('AGENT_NAMESPACE', 'joshua')
    max_death_wait = int(os.environ.get('AGENT_DEATHWAITMAX', '600'))
    growth_rate = float(os.environ.get('AGENT_GROWTHRATE', '50.0'))

    parser = argparse.ArgumentParser()
    parser.add_argument('-C',
                        '--cluster-file',
                        default=cluster_file,
                        help='Cluster file for Joshua database')
    parser.add_argument(
        '-D',
        '--dir',
        default=work_dir,
        help='top-level working directory in which joshua agents run')
    parser.add_argument(
        '-L',
        '--name-space',
        default=name_space,
        help='Database directory layer in which joshua operates')
    parser.add_argument(
        '-f',
        '--free-space',
        type=float,
        default=free_space,
        help='Amount of free disk space to preserve within working directory')
    parser.add_argument(
        '-F',
        '--free-cpus',
        type=int,
        default=free_cpus,
        help='Number of free cpus to leave available.  0 means use all cpus.')
    parser.add_argument('-g',
                        '--growth-rate',
                        type=float,
                        default=growth_rate,
                        help='Rate of growth for agents')
    parser.add_argument(
        '-N',
        '--number',
        type=int,
        default=max_agents,
        help='Number of agent processes to spawn. 0 means one per CPU.')
    parser.add_argument(
        '-P',
        '--priority',
        type=int,
        default=priority,
        help=
        'Nice priority for the agent process. (-20 - +19) -> (highest to lowest priority)'
    )
    parser.add_argument('-r',
                        '--report-freq',
                        type=float,
                        default=report_freq,
                        help='Frequency (in minutes) to give reports')
    parser.add_argument(
        '-S',
        '--mgr-sleep',
        type=int,
        default=mgr_sleep,
        help='Number of seconds for agent manager to sleep between checks.')
    parser.add_argument('-w',
                        '--death-wait',
                        type=int,
                        default=death_wait,
                        help='Amount of seconds to wait for agents to die.')
    parser.add_argument(
        '-W',
        '--max-death-wait',
        type=int,
        default=max_death_wait,
        help='Maximum amount of seconds to wait for agents to die.')

    args = parser.parse_args()

    # Enforce ranges
    args.growth_rate = min(args.growth_rate, 100.0)
    args.growth_rate = max(1.0, args.growth_rate)
    args.free_space = max(0.0, args.free_space)
    args.report_freq = max(0.1, args.report_freq)
    args.mgr_sleep = max(1, args.mgr_sleep)
    args.death_wait = max(1, args.death_wait)

    if not os.path.exists(args.dir):
        os.makedirs(args.dir)
    os.chdir(args.dir)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)-8s] [%(levelname)-5s] %(message)s",
        handlers=[
            logging.FileHandler(os.path.join(args.dir, "start_agent.log")),
            logging.StreamHandler()
        ])
    logger = logging.getLogger()
    logging.logThreads = 1

    total_cpus = os.cpu_count() if os.cpu_count() is not None else 1
    joshua_stopfile = os.path.join(args.dir, 'STOP_AGENTS')

    if args.free_cpus < 0:
        logger.info('Hey slick, free CPUs must be positive: {}'.format(
            args.free_cpus))
        args.free_cpus = 0
    elif args.free_cpus > 0:
        if args.free_cpus > total_cpus:
            logger.info(
                'Hey slick, you cannot maintain more free CPUs: {} than system CPUs: {}'
                .format(args.free_cpus, total_cpus))
            args.free_cpus = total_cpus
        if total_cpus == 1:
            logger.info(
                'Maintaining {} free CPUs is questionable with only 1 CPU'.
                format(args.free_cpus))

    # Use the number of available cpus as the maximum number
    # for agents, if not specified
    max_agents = args.number if args.number > 0 else total_cpus - args.free_cpus
    # Warn if person requested more agents than CPUs
    if total_cpus - args.free_cpus < args.number:
        logger.info(
            'You have requested more Agents: {} than available CPUs: {} for system with {} CPUs and {} free CPUs.'
            .format(args.number, total_cpus - args.free_cpus, total_cpus,
                    args.free_cpus))

    if args.mgr_sleep <= 0:
        logger.info(
            'Hey slick, you must sleep some between checks: {} -> {}'.format(
                args.mgr_sleep, 1))
        args.mgr_sleep = 1

    if args.priority != 0:
        agent_pid = os.getpid()
        agent_process = psutil.Process(agent_pid)
        logger.info('Agent PID %6d  updating priority: %2d -> %2d ' %
                    (agent_pid, agent_process.nice(), args.priority))
        agent_process.nice(args.priority)

    # Initialize the agent variables
    children = {}

    # Initialize the joshua model
    joshua_model.open(args.cluster_file, (args.name_space,))

    # Manage and launch the agents
    manage_agents(total_cpus, max_agents, joshua_stopfile, children)

    # Always reap any dead children
    reap_deadchildren()

    sys.exit()
