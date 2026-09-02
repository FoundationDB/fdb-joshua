FROM rockylinux/rockylinux:9.8
# This is joshua-agent
ARG TARGETARCH
WORKDIR /tmp

# Currently Python 3.13 is used as the default python version 3.9 is EOL:
# https://devguide.python.org/versions
RUN dnf update -y && \
    dnf install -y \
        epel-release \
        dnf-plugins-core && \
    dnf config-manager --set-enabled crb && \
    dnf install -y \
        xz \
        lsof \
        net-tools \
        procps-ng \
        python3.13 \
        python3.13-devel \
        python3.13-pip \
        libffi-devel \
        gcc \
        valgrind && \
    dnf -y clean all --enablerepo='*'

RUN ln -sf /usr/bin/python3.13 /usr/bin/python3 && \
    ln -sf /usr/bin/pip3.13 /usr/bin/pip3

# This should be moved into a dedicated step with a requirements file + version pinning.
RUN python3 -m pip install \
        python-dateutil \
        psutil \
        kubernetes==30.1.0 \
        urllib3==1.26.20 \
        boto3==1.43.14 \
        azure-storage-blob

RUN groupadd -r joshua -g 4060 && \
    useradd \
        -rm \
        -d /home/joshua \
        -s /bin/bash \
        -u 4060 \
        -g joshua \
        joshua && \
    mkdir -p /var/joshua && \
    chown -R joshua:joshua /var/joshua

# Install Joshua client
COPY childsubreaper/ /opt/joshua/install/childsubreaper
COPY joshua/ /opt/joshua/install/joshua
COPY setup.py /opt/joshua/install/
RUN ARTIFACT=client python3 -m pip install /opt/joshua/install && \
    rm -rf /opt/joshua/install

# install old fdbserver binaries and libfdb_c.so
# just enough for foundationdb/tests/restarting/* for branches: release-7.3 release-7.4 main
ARG OLD_FDB_BINARY_DIR=/app/deploy/global_data/oldBinaries/
# This image only works for x86_64 ...
RUN if [ "${TARGETARCH}" = "amd64" ]; then \
        mkdir -p ${OLD_FDB_BINARY_DIR} \
                 /usr/lib/foundationdb/plugins && \
        for old_fdb_server_version in 7.4.5 7.3.69 7.3.43 7.1.61 7.1.19 6.3.18; do \
            curl -Ls --retry 5 --fail https://github.com/apple/foundationdb/releases/download/${old_fdb_server_version}/fdbserver.x86_64 -o ${OLD_FDB_BINARY_DIR}/fdbserver-${old_fdb_server_version}; \
        done && \
        chmod +x ${OLD_FDB_BINARY_DIR}/* ; \
    fi

ARG FDB_VERSION="7.1.57"
# Install primary FDB version.
# Note: The agent doesn't support arm64 right now because the old versions are only available in x64, see above.
RUN set -eux && \
    if [ "${TARGETARCH}" = "amd64" ]; then \
         FDB_ARCH=x86_64; \
    elif [ "${TARGETARCH}" = "arm64" ]; then \
         FDB_ARCH=aarch64; \
         if [ "${FDB_VERSION%.*}" = "7.1" ]; then \
            FDB_VERSION="7.3.79"; \
         fi; \
    else \
         echo "ERROR: unsupported architecture ${TARGETARCH}" 1>&2; \
         exit 1; \
    fi; \
    if [ "${FDB_VERSION%.*}" = "7.1" ]; then \
         # FDB 7.1 published the client packages for el7, 7.3 and newer uses el9.
         FDB_OS=el7; \
    else \
         FDB_OS=el9; \
    fi; \
    curl --fail -L "https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/foundationdb-clients-${FDB_VERSION}-1.${FDB_OS}.${FDB_ARCH}.rpm" -o foundationdb-clients-${FDB_VERSION}-1.${FDB_OS}.${FDB_ARCH}.rpm && \
    curl --fail -L "https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/foundationdb-clients-${FDB_VERSION}-1.${FDB_OS}.${FDB_ARCH}.rpm.sha256" -o foundationdb-clients-${FDB_VERSION}-1.${FDB_OS}.${FDB_ARCH}.rpm.sha256 && \
    # Disable buggy mirrors for RockyLinux.
    sed -i.bak 's/^#baseurl=/baseurl=/; s/^mirrorlist=/#mirrorlist=/' /etc/yum.repos.d/rocky.repo && \
    dnf install --disablerepo=* --enablerepo=baseos --enablerepo=appstream -y glibc pkg-config bind-utils && \
    dnf clean all && \
    sha256sum -c foundationdb-clients-${FDB_VERSION}-1.${FDB_OS}.${FDB_ARCH}.rpm.sha256 && \
    rpm -i foundationdb-clients-${FDB_VERSION}-1.${FDB_OS}.${FDB_ARCH}.rpm --excludepath=/usr/bin --excludepath=/usr/lib/foundationdb/backup_agent && \
    rm foundationdb-clients-${FDB_VERSION}-1.${FDB_OS}.${FDB_ARCH}.rpm foundationdb-clients-${FDB_VERSION}-1.${FDB_OS}.${FDB_ARCH}.rpm.sha256

# Install multi-version libraries to allow FDB joshua to connect to clusters with a different version
RUN for version in "${FDB_VERSION}" "7.3.79" "7.4.7"; \
    do \
        curl -Ls https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/libfdb_c.x86_64.so -o "/usr/lib64/libfdb_c_${version%.*}.so"; \
    done

ENV FDB_CLUSTER_FILE=/etc/foundationdb/fdb.cluster
ENV AGENT_TIMEOUT=900

# joshua-agent often needs huge retry limits
# because of thundering-herd of thousands of agents doing joshua_model.try_running_test()
ENV TRANSACTION_TIMEOUT_MS=256000
ENV TRANSACTION_RETRY_LIMIT=1000
ENV FDB_NETWORK_OPTION_EXTERNAL_CLIENT_DIRECTORY=/usr/lib/fdb

USER joshua
CMD python3 -m joshua.joshua_agent \
        -C ${FDB_CLUSTER_FILE} \
        --work_dir /var/joshua
