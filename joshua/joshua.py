#!/usr/bin/env python3
#
# joshua.py
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

from . import joshua_model
import argparse
import dateutil.parser, time
from datetime import datetime, timedelta, timezone
import os, pwd, sys
import threading
import lxml.etree as le

JOSHUA_USER_ENV = 'JOSHUA_USER'


def get_username():
    return os.environ.get(JOSHUA_USER_ENV, pwd.getpwuid(os.getuid())[0])


def format_ensemble(e, props):
    return "  %-50s %s" % (e, " ".join(
        '{}={}'.format(k, v) for k, v in sorted(props.items())))


def timestamp_of(time_string):
    # FIXME: Right now this only uses local time. It should probably handle timezones/DST better.
    return int(time.mktime(dateutil.parser.parse(
        time_string).timetuple())) if time_string is not None else None


def get_active_ensembles(stopped, sanity=False, username=None):
    return joshua_model.get_active_ensembles(stopped, sanity, username)


def list_active_ensembles(stopped, sanity=False, username=None, show_in_progress=None, **args):
    ensemble_list = get_active_ensembles(stopped, sanity, username)
    if stopped:
        print('All ensembles:')
    elif sanity:
        print('Currently active sanity ensembles:')
    else:
        print('Currently active ensembles:')
    for e, props in ensemble_list:
        print(format_ensemble(e, props))
        if show_in_progress:
            print('\tCurrently active tests:')
            for props in joshua_model.show_in_progress(e):
                print('\t{}'.format(' '.join('{}={}'.format(k, v) for k, v in sorted(props.items()))))

    return ensemble_list


def start_ensemble(tarball,
                   command,
                   properties,
                   username,
                   compressed,
                   allow_multiple=False,
                   sanity=False,
                   timeout=5400,
                   no_timeout=False,
                   fail_fast=10,
                   no_fail_fast=False,
                   max_runs=100000,
                   no_max_runs=False,
                   priority=100,
                   env=[],
                   printable=True,
                   **args):
    if not allow_multiple:
        stop_ensemble(username=username, sanity=sanity, printable=True)
    properties = dict(p.split("=", 1) for p in properties)
    properties['username'] = username
    properties['compressed'] = compressed
    properties['sanity'] = sanity
    properties['priority'] = priority
    if env:
        # omit 'env' property if nothing is set
        properties['env'] = ':'.join(env)

    if not no_timeout:
        properties['timeout'] = timeout

    if fail_fast > 0 and not no_fail_fast:
        print('Note: Ensemble will complete after {} failed results.'.format(
            fail_fast))
        properties['fail_fast'] = fail_fast

    if max_runs > 0 and not no_max_runs:
        print('Note: Ensemble will complete after {} runs.'.format(max_runs))
        properties['max_runs'] = max_runs

    if command:
        properties['test_command'] = command
    print('Starting ensemble')
    with open(tarball, "rb") as tarfile:
        tarfile.seek(0, os.SEEK_END)
        size = tarfile.tell()
        tarfile.seek(0, os.SEEK_SET)
        properties['data_size'] = size

        ensemble_id = joshua_model.create_ensemble(username, properties,
                                                   tarfile, sanity)
    print(format_ensemble(ensemble_id, properties))
    return str(ensemble_id)


def stop_ensemble(ensemble=None,
                  username=None,
                  sanity=False,
                  printable=True,
                  **args):
    if ensemble:
        if printable:
            print("Stopping ensemble", ensemble)
        joshua_model.stop_ensemble(ensemble, sanity)
    else:
        # Stop all active ensembles for the given username
        if not username:
            username = get_username()
        if printable:
            ensemble_list = joshua_model.list_sanity_ensembles(
            ) if sanity else joshua_model.list_active_ensembles()
        else:
            ensemble_list = get_active_ensembles(False, sanity, username)

        for e, props in ensemble_list:
            if "-" + username + "-" in str(e):
                if printable:
                    print("Stopping ensemble", e)
                joshua_model.stop_ensemble(e, sanity)


def default_ensemble(sanity=False, **args):
    username = args.get('username') or get_username()
    all_ensembles = [
        e for e, props in get_active_ensembles(True, False, False)
        if props.get('username', None) == username and
        props.get('sanity', False) == sanity
    ]
    if not all_ensembles:
        raise Exception('No tests have ever run for username ' + username)
    return all_ensembles[-1]


def resume_ensemble(ensemble, sanity=False, **args):
    if not ensemble:
        ensemble = default_ensemble(sanity, **args)

    if joshua_model.resume_ensemble(ensemble, sanity):
        print("Resumed: ", ensemble)
    else:
        print("Already running: ", ensemble, sanity)


def tail_ensemble(ensemble,
                  raw=False,
                  errors_only=False,
                  xml=False,
                  sanity=False,
                  simple=False,
                  stopped=False,
                  username=None,
                  **args):
    if simple:
        xml = True
    if not ensemble:
        if not username:
            username = args.get('username') or get_username()
        ensembles = [
            e for e, props in get_active_ensembles(stopped, sanity, username)
        ]
        ensemble = ensembles[-1] if ensembles else None
        if not ensemble:
            sys.stderr.write("No active ensembles\n")
            return

    properties = joshua_model.get_ensemble_properties(ensemble)
    compressed = properties[
        'compressed'] if 'compressed' in properties else False

    sys.stderr.write("Results for test ensemble: %s\n" % ensemble)
    if xml:
        sys.stdout.write("<Trace>")
    for rec in joshua_model.tail_results(ensemble,
                                         errors_only=errors_only,
                                         compressed=compressed):
        if len(rec) == 5:
            versionstamp, result_code, host, seed, output = rec
        elif len(rec) == 4:
            versionstamp, result_code, host, output = rec
            seed = None
        elif len(rec) == 3:
            versionstamp, result_code, output = rec
            host = None
            seed = None
        elif len(rec) == 2:
            versionstamp, seed = rec
            output = str(joshua_model.fdb.tuple.unpack(seed)[0]) + "\n"
            result_code = None
            host = None
            seed = None
        else:
            raise Exception("Unknown result format")

        if simple:
            try:
                doc = le.fromstring('<Dummy>' + output + '</Dummy>')
                for elem in doc.xpath('//CodeCoverage'):
                    elem.getparent().remove(elem)
                for elem in doc.xpath('//BuggifySection'):
                    elem.getparent().remove(elem)
                for elem in doc.xpath('//*[(@Severity="30")]'):
                    elem.getparent().remove(elem)
                output = le.tostring(doc).decode("utf-8")[7:-8]
                parsed = True
            except Exception as e:
                print('Could not parse xml output ({}) {} on {} because {}'.
                      format(result_code, seed, host, e))
                raise

        if raw or xml:
            sys.stdout.write(output)
            sys.stdout.flush()
        else:
            print(hex(versionstamp), result_code, host, seed, repr(output))
    if xml:
        sys.stdout.write("</Trace>")
    sys.stderr.write('Ensemble stopped\n')


def agent_failures(start=None, end=None, **args):
    # Parse date times.
    time_start = timestamp_of(start) if start is not None else int(time.time() -
                                                                   60 * 60 *
                                                                   24 * 7)
    time_end = timestamp_of(end)

    # Get the list of failures from the database.
    failures = joshua_model.get_agent_failures(time_start, time_end)

    if len(failures) == 0:
        print('No failures found in specified date range.')

    for failure in failures:
        print('   '.join(failure[0]))
        print('\n'.join(
            map(lambda x: (b'    ' + x).decode("utf-8"), failure[1].split(b'\n')
               )))  # This indents the the string for visual appealingness.


def _delete_helper(to_delete, yes=False, dryrun=False, sanity=False):
    print('Found the following ensembles to delete:')
    for ensemble in to_delete:
        print(ensemble)

    print()

    if not yes and not dryrun:
        response = input('Do you want to delete these ensembles [y/n]? ')
        if response.strip().lower() not in set(['y', 'yes']):
            print('Negative response received. Not performing deletion.')
            return

    # Actually delete these ensembles.
    for ensemble in to_delete:
        properties = joshua_model.get_ensemble_properties(ensemble)
        compressed = properties[
            'compressed'] if 'compressed' in properties else False
        ensemble_sanity = properties[
            'sanity'] if 'sanity' in properties else False

        if not ensemble_sanity or sanity:
            if not dryrun:
                joshua_model.delete_ensemble(ensemble,
                                             compressed=compressed,
                                             sanity=ensemble_sanity)
                print('Ensemble', ensemble, 'deleted')
            else:
                print('Ensemble', ensemble, 'not deleted (dry-run).')
        else:
            print(
                'Ensemble', ensemble,
                'is a sanity ensemble and the sanity flag is not set. Skipping.'
            )


def delete_ensembles(ensembles, yes=False, dryrun=False, sanity=False, **args):
    # Only delete ensembles that we have a record exist.
    to_delete = joshua_model.identify_existing_ensembles(ensembles)

    if len(to_delete) == 0:
        print(
            'None of the specified ensembles currently exist. Not deleting any runs.'
        )
        return

    _delete_helper(to_delete, yes, dryrun, sanity)


def delete_ensemble_range(before=None,
                          after=None,
                          yes=False,
                          dryrun=False,
                          sanity=False,
                          **args):
    time_before = timestamp_of(before)
    time_after = timestamp_of(after)

    if time_before is None and time_after is None:
        print('Empty range specified. Not deleting any runs.')
        return

    to_delete = []
    all_ensembles = joshua_model.list_all_ensembles()
    for ensemble, _ in all_ensembles:
        # Parse the date to see if the ensemble is within the given range.
        try:
            timestamp = time.mktime(
                datetime.strptime(''.join(ensemble.split('-')[:2]),
                                  '%Y%m%d%H%M%S').timetuple())
            if (time_before is None or
                    timestamp < time_before) and (time_after is None or
                                                  timestamp > time_after):
                to_delete.append(ensemble)
        except Exception as e:
            print('Could not parse datetime from ensemble:', ensemble,
                  'Skipping.')

    if len(to_delete) == 0:
        print('No ensembles found to delete in specified range.')
        return

    _delete_helper(to_delete, yes, dryrun, sanity)


def download_ensemble(ensemble, out=None, force=False, sanity=False, **args):
    if ensemble is None:
        ensemble = default_ensemble(sanity=sanity)

    if out is None:
        out_file = os.path.abspath(
            os.path.join(os.getcwd(), '{}.tar.gz'.format(ensemble)))
    elif os.path.isdir(out):
        out_file = os.path.abspath(
            os.path.join(out, '{}.tar.gz'.format(ensemble)))
    else:
        out_file = os.path.abspath(out)
        if not os.path.isdir(os.path.dirname(out_file)):
            os.makedirs(os.path.dirname(out_file))

    if not force and not out_file.endswith('.tar.gz'):
        resp = input(
            'File {} does not end with .tar.gz. Are you sure you want to continue? (Y/n) '
            .format(out_file))
        if resp.lower() != 'y' and resp.lower() != 'yes':
            print('Not continuing')
            return

    if not force and os.path.isfile(out_file):
        print('File {} already exists. Refusing to overwrite file.'.format(
            out_file))
        return

    print('Downloading ensemble {} into {}...'.format(ensemble, out_file))
    with open(out_file, 'wb') as fout:
        joshua_model.get_ensemble_data(ensemble_id=ensemble, outfile=fout)
    print('Download completed')


if __name__ == "__main__":
    name_space = os.environ.get('JOSHUA_NAMESPACE', 'joshua')
    parser = argparse.ArgumentParser(
        description='How about a nice game of chess?')
    parser.add_argument('-C',
                        '--cluster-file',
                        '--cluster_file',
                        dest="cluster_file",
                        help="Cluster file for Joshua database")
    parser.add_argument(
        '-D',
        '--dir-path',
        nargs='+',
        default=(name_space,),
        help='top-level directory path in which joshua operates')

    subparsers = parser.add_subparsers(help='sub-command help')

    parser_list = subparsers.add_parser('list', help='list test ensembles')
    parser_list.add_argument('--stopped',
                             action='store_true',
                             help='include stopped ensembles')
    parser_list.add_argument('--sanity',
                             action='store_true',
                             help='list sanity ensembles instead')
    parser_list.add_argument('--username',
                             metavar='user',
                             help='username of user who launched the test',
                             default=None)
    parser_list.add_argument('--show-in-progress',
                             action='store_true',
                             help='If set, show the progress of currently running tests',
                             default=None)
    parser_list.set_defaults(cmd=list_active_ensembles)

    parser_start = subparsers.add_parser('start', help='start a test ensemble')
    parser_start.add_argument(
        '--tarball',
        required=True,
        metavar='filename',
        help='.tar.gz file containing the binaries and data for the test')
    parser_start.add_argument('--command',
                              metavar='command',
                              help='command to execute within the tarball')
    parser_start.add_argument('--property',
                              metavar='name=value',
                              dest='properties',
                              action='append',
                              default=[])
    parser_start.add_argument('--username',
                              metavar='user',
                              help='username of user launching the test',
                              default=get_username())
    parser_start.add_argument(
        '--allow-multiple',
        action='store_true',
        help='allow previous ensembles launched by this user to keep running')
    parser_start.add_argument('--not-compressed',
                              dest='compressed',
                              action='store_false',
                              default=True,
                              help='')
    parser_start.add_argument(
        '--sanity',
        action='store_true',
        help=
        'mark this ensemble as a sanity test (i.e., joshua exits if this test fails'
    )
    parser_start.add_argument(
        '--timeout',
        metavar='timeout',
        type=int,
        default=5400,
        help=
        'number of seconds to wait before killing an ensemble (default is 5400 s)'
    )
    parser_start.add_argument(
        '--no-timeout',
        action='store_true',
        help='indicate that this test should be run without any kind of timeout'
    )
    parser_start.add_argument(
        '-F',
        '--fail-fast',
        required=False,
        type=int,
        metavar='FAILURES',
        default=10,
        help='number of failures after to which to terminate the job')
    parser_start.add_argument(
        '--no-fail-fast',
        action='store_true',
        help=
        'do not limit the number of failures for this ensemble (causes --fail-fast to be ignored)'
    )
    parser_start.add_argument(
        '--max-runs',
        required=False,
        type=int,
        metavar='MAX_RUNS',
        default=100000,
        help='maximum number of runs after which to terminate the job')
    parser_start.add_argument(
        '--no-max-runs',
        action='store_true',
        help='do not limit the number of runs of this job')
    parser_start.add_argument(
        '--priority',
        required=False,
        type=int,
        metavar='PRIORITY',
        default=100,
        help='percent adjustment of CPU time allocated to this job')
    parser_start.add_argument(
        '--env',
        metavar='name=value',
        dest='env',
        action='append',
        default=[],
        help="environment variable to add to the job's execution")
    parser_start.set_defaults(cmd=start_ensemble)

    parser_stop = subparsers.add_parser('stop', help='stop a test ensemble')
    parser_stop.add_argument('--id',
                             dest='ensemble',
                             help='stop the given ensemble by ID')
    parser_stop.add_argument('--username',
                             metavar='user',
                             help='stop all ensembles with the given username')
    parser_stop.add_argument('--sanity',
                             action='store_true',
                             help='stop only sanity ensembles')
    parser_stop.set_defaults(cmd=stop_ensemble)

    parser_resume = subparsers.add_parser('resume',
                                          help='resume a stopped test ensemble')
    parser_resume.add_argument('ensemble',
                               nargs='?',
                               metavar='id',
                               help='ensemble to resume')
    parser_resume.add_argument('--sanity',
                               action='store_true',
                               help='ensemble to resume is a sanity ensemble')
    parser_resume.set_defaults(cmd=resume_ensemble)

    parser_tail = subparsers.add_parser('tail', help='tail test results')
    parser_tail.add_argument('ensemble',
                             nargs='?',
                             metavar='id',
                             help='ensemble to get results from')
    parser_tail.add_argument('--username',
                             metavar='user',
                             help='username of user launching the test')
    parser_tail.add_argument('--raw',
                             action='store_true',
                             help='Test output only')
    parser_tail.add_argument('--errors',
                             dest="errors_only",
                             action='store_true',
                             help='Errors only')
    parser_tail.add_argument('--xml',
                             dest="xml",
                             action='store_true',
                             help='wrap raw output in <Trace> tags')
    parser_tail.add_argument('--simple',
                             dest="simple",
                             action='store_true',
                             help='display simple raw output in <Trace> tags')
    parser_tail.add_argument('--sanity',
                             action='store_true',
                             help='get output from sanity ensembles')
    parser_tail.set_defaults(cmd=tail_ensemble)

    parser_failures = subparsers.add_parser('failures',
                                            help='list agent failures')
    parser_failures.add_argument(
        '--start',
        default=None,
        help=
        'start date time (in most standard date formats) for failures to report, the default of which is one week ago'
    )
    parser_failures.add_argument(
        '--end',
        default=None,
        help=
        'end date time for failures to report, the default of which is no limit'
    )
    parser_failures.set_defaults(cmd=agent_failures)

    parser_delete = subparsers.add_parser('delete', help='delete old runs')
    parser_delete.add_argument('ensembles',
                               nargs='+',
                               metavar='id',
                               help='ensembles to delete')
    parser_delete.add_argument('-y',
                               '--yes',
                               action='store_true',
                               default=False,
                               help='don\'t prompt the user before deleting')
    parser_delete.add_argument(
        '--dryrun',
        action='store_true',
        default=False,
        help=
        'don\'t actually delete (just list what would be deleted); this overrides the -y flag'
    )
    parser_delete.add_argument(
        '--sanity',
        default=False,
        action='store_true',
        help='delete sanity tests along with regular ensembles')
    parser_delete.set_defaults(cmd=delete_ensembles)

    parser_delete_range = subparsers.add_parser('deleterange',
                                                help='delete range of old runs')
    parser_delete_range.add_argument(
        '--before',
        default=None,
        help=
        'latest date time (in most standard date formats) for results to be deleted; this endpoint is exclusive'
    )
    parser_delete_range.add_argument(
        '--after',
        default=None,
        help=
        'earliest date time (in most standard date formats) for results to be deleted; this endpoint is exclusive'
    )
    parser_delete_range.add_argument(
        '-y',
        '--yes',
        action='store_true',
        default=False,
        help='don\'t prompt the user before deleting')
    parser_delete_range.add_argument(
        '--dryrun',
        action='store_true',
        default=False,
        help=
        'don\'t actually delete (just list what would be deleted); this overrides the -y flag'
    )
    parser_delete_range.add_argument(
        '--sanity',
        default=False,
        action='store_true',
        help='delete sanity tests along with regular ensembles')
    parser_delete_range.set_defaults(cmd=delete_ensemble_range)

    parser_download = subparsers.add_parser(
        'download', help='download the ensemble for a given run')
    parser_download.add_argument('ensemble',
                                 nargs='?',
                                 metavar='id',
                                 help='ensemble to download')
    parser_download.add_argument(
        '-o',
        '--out',
        default=None,
        help=
        'file or directory to write ensemble tar.gz file to (default is current working directory with ensemble name)'
    )
    parser_download.add_argument(
        '-f',
        '--force',
        default=False,
        action='store_true',
        help='overwrite existing files and directories when downloading')
    parser_download.add_argument(
        '--sanity',
        default=False,
        action='store_true',
        help='ensemble in question is a sanity ensemble')
    parser_download.set_defaults(cmd=download_ensemble)

    arguments = parser.parse_args()
    joshua_model.open(arguments.cluster_file, dir_path=arguments.dir_path)

    if 'cmd' not in arguments:
        parser.print_usage()
        exit(-1)

    # Running everything (esp ctypes blocking calls) in a thread makes the program much more responsive to KeyboardInterrupt
    t = threading.Thread(target=arguments.cmd, args=(), kwargs=vars(arguments))
    t.daemon = True
    t.start()
    while t.is_alive():
        t.join(6000)
