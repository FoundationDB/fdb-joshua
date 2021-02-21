#!/bin/bash

set -e

OLD_FDB_BINARY_DIR="${OLD_FDB_BINARY_DIR:-/app/deploy/global_data/oldBinaries/}"
OLD_TLS_LIBRARY_DIR="${OLD_TLS_LIBRARY_DIR:-/app/deploy/runtime/.tls_5_1/}"
FDB_VERSION="${FDB_VERSION:-0}"

if [[ ${#} -lt 1 ]]
then
    echo "Usage: ./download_old_fdb.sh 1"
    echo "Downloads old fdbserver binaries and TLS libraries for FDB simulation tests."
    echo
    echo "Additional options (set through environment variables) include :"
    echo "      OLD_FDB_BINARY_DIR     Directory for old fdbserver binaries (Default: ${OLD_FDB_BINARY_DIR})."
    echo "      OLD_TLS_LIBRARY_DIR    Directory for old TLS libraries (Default: ${OLD_TLS_LIBRARY_DIR})."

    exit 1
fi

mkdir -p "${OLD_FDB_BINARY_DIR}"
mkdir -p "${OLD_TLS_LIBRARY_DIR}"

# If FDB_VERSION is not set, then use the latest available version.
if [ "${FDB_VERSION}" -eq "0" ]
then
    FDB_VERSION=`curl -L https://www.foundationdb.org/downloads/version.txt`
fi

echo "FDB_VERSION is: ${FDB_VERSION}"

curl -L https://www.foundationdb.org/downloads/misc/fdbservers-${FDB_VERSION}.tar.gz | tar -xz -C ${OLD_FDB_BINARY_DIR}
rm -f ${OLD_FDB_BINARY_DIR}/*.sha256
chmod +x ${OLD_FDB_BINARY_DIR}/*

curl -L https://www.foundationdb.org/downloads/misc/joshua_tls_library.tar.gz | tar -xz -C ${OLD_TLS_LIBRARY_DIR} --strip-components=1

curl -L https://www.foundationdb.org/downloads/${FDB_VERSION}/linux/libfdb_c_${FDB_VERSION}.so -o /usr/lib64/libfdb_c_${FDB_VERSION}.so
ln -s /usr/lib64/libfdb_c_${FDB_VERSION}.so /usr/lib64/libfdb_c.so
mkdir -p /usr/lib/foundationdb/plugins
ln -s ${OLD_TLS_LIBRARY_DIR}/FDBGnuTLS.so /usr/lib/foundationdb/plugins/fdb-libressl-plugin.so
ln -s ${OLD_TLS_LIBRARY_DIR}/FDBGnuTLS.so /usr/lib/foundationdb/plugins/FDBGnuTLS.so
