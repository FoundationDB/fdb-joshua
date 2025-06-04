#
# config.py
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

import os
from dotenv import load_dotenv

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'you-will-never-guess'
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'db.sqlite')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    if os.environ.get('MAX_CONTENT_LENGTH'):
        MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH'))
    else:
        MAX_CONTENT_LENGTH = 100 * 1024 * 1024
    JOSHUA_UPLOAD_FOLDER = os.environ.get(
        'JOSHUA_UPLOAD_FOLDER') or os.path.join(basedir, 'upload')
    JOSHUA_FDB_CLUSTER_FILE = os.environ.get(
        'JOSHUA_FDB_CLUSTER_FILE') or 'fdb.cluster'
    JOSHUA_NAMESPACE = os.environ.get('JOSHUA_NAMESPACE') or 'joshua'
