#!/usr/bin/env python3
#
# fdb_util.py
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

import joshua_model
import argparse


def queue_size(**args):
    """
    Prints the number of ensembles that have not finished running to be captured by agent-scaler.sh.
    """

    ensemble_list = joshua_model.list_active_ensembles()
    desired_count = 0
    for e, props in ensemble_list:
        max_runs = 0
        ended = 0
        if "max_runs" in props:
            max_runs = props["max_runs"]
        if "ended" in props:
            ended = props["ended"]
        if max_runs - ended >= 0:
            desired_count += max_runs - ended
    print(desired_count, end="")


def get_agent_image_tag(**args):
    """
    Prints the joshua agent image tag to be captured by agent-scaler.sh
    """

    print(joshua_model.get_agent_image_tag().decode("utf-8"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="How about a nice game of chess?")
    parser.add_argument(
        "-C",
        "--cluster-file",
        "--cluster_file",
        dest="cluster_file",
        help="Cluster file for Joshua database",
    )
    parser.add_argument(
        "-D",
        "--dir-path",
        nargs="+",
        default=("joshua",),
        help="top-level directory path in which joshua operates",
    )

    subparsers = parser.add_subparsers(help="sub-command help")
    parser_count = subparsers.add_parser(
        "get_ensemble_count", help="print out number of remaining ensembles"
    )
    parser_count.set_defaults(cmd=queue_size)

    parser_tag = subparsers.add_parser(
        "get_agent_tag", help="print out joshua agent image tag"
    )
    parser_tag.set_defaults(cmd=get_agent_image_tag)

    arguments = parser.parse_args()
    joshua_model.open(arguments.cluster_file, dir_path=arguments.dir_path)
