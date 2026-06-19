#!/usr/bin/env python3
"""
stop_completed_ensembles.py - Stop ensembles that have reached max_runs.

Catches the race condition where concurrent agents all read a stale
'ended' count via snapshot reads and none triggers _stop_ensemble.
"""

import os
import sys
import argparse
import joshua_model

if __name__ == "__main__":
    name_space = os.environ.get("JOSHUA_NAMESPACE", "joshua")
    parser = argparse.ArgumentParser(description="Stop completed ensembles")
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
        default=(name_space,),
        help="top-level directory path in which joshua operates",
    )

    arguments = parser.parse_args()
    joshua_model.open(arguments.cluster_file, arguments.dir_path)
    stopped = joshua_model.stop_completed_ensembles()
    for ensemble_id in stopped:
        print(f"Stopped completed ensemble: {ensemble_id}", file=sys.stderr)
