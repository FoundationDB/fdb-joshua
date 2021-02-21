#
# istest.py
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

import subprocess, encodings
process = subprocess.Popen(['sleep', '1'],
                           stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
process.communicate()

# Python 2.7 set notation.
a = {'asdf', 'qwerty', 'asdf', 'ghij'}

# Let's just check the version.
import sys
ver = sys.version_info

assert ver.major in {2, 3}

if ver.major == 2:
    assert ver.minor >= 7
else:
    assert ver.minor >= 5
