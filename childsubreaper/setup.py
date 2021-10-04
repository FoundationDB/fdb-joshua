"""
    setup.py
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
from distutils.core import setup, Extension

import os.path

file_dir = os.path.dirname(__file__)

childsubreaper = Extension(
    "childsubreaper", sources=[os.path.join(file_dir, "childsubreaper.c")]
)
setup(
    name="childsubreaper",
    version="1.0",
    author="The FoundationDB Team",
    author_email="fdbteam@apple.com",
    description="This wraps the prctl command to set a process as the child subreaper",
    ext_modules=[childsubreaper],
)
