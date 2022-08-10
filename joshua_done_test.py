#!/usr/bin/env python3
import argparse
import fdb
import fdb.tuple
import os
import random

fdb.api_version(630)

from typing import List

@fdb.transactional
def write_ensemble_data(tr, path: List[str]):
    root_dir = fdb.directory.create_or_open(tr, tuple(path))
    num = os.getenv('JOSHUA_SEED', None)
    has_joshua_seed = num is not None
    num = num if has_joshua_seed else random.uniform(0, 1 << 32 - 1)
    while True:
        if tr[root_dir[num]].present():
            num += 1
        else:
            tr[root_dir[num]] = fdb.tuple.pack((has_joshua_seed,))
            break


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Code Probe Accumulation')
    parser.add_argument('ensemble_dir')
    parser.add_argument('cluster_file')
    args = parser.parse_args()
    dirPath: List[str] = args.ensemble_dir.split(',')
    print('dirPath = ({})'.format(",".join(dirPath)))
    print('clusterFile = {}'.format(args.cluster_file))
    db = fdb.open(args.cluster_file if args.cluster_file != 'None' else None)
    write_ensemble_data(db, dirPath)
