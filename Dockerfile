FROM rockylinux/rockylinux:9.7
# This is joshua-agent

WORKDIR /tmp

# Currently Python 3.13 is used as the default python version 3.9 is EOL:
# https://devguide.python.org/versions
RUN dnf update -y && \
    dnf install -y \
        epel-release \
        dnf-plugins-core && \
    dnf config-manager --set-enabled crb && \
    dnf install -y \
        lsof \
        net-tools \
        procps-ng \
        python3.13 \
        python3.13-devel \
        python3.13-pip \
        libffi-devel \
        gcc && \
    dnf -y clean all --enablerepo='*'

RUN ln -sf /usr/bin/python3.13 /usr/bin/python3 && \
    ln -sf /usr/bin/pip3.13 /usr/bin/pip3

# This should be moved into a dedicated step with a requirements file + version pinning.
RUN python3 -m pip install \
        python-dateutil \
        subprocess32 \
        psutil \
        kubernetes==30.1.0 \
        urllib3==1.26.20 \
        boto3==1.43.14

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
ARG FDB_VERSION="7.1.57"
# This image only works for x86_64 ...
RUN if [ "$(uname -p)" == "x86_64" ]; then \
        mkdir -p ${OLD_FDB_BINARY_DIR} \
                 /usr/lib/foundationdb/plugins && \
        for old_fdb_server_version in 7.4.5 7.3.69 7.3.43 7.1.61 7.1.19 6.3.18; do \
            curl -Ls --retry 5 --fail https://github.com/apple/foundationdb/releases/download/${old_fdb_server_version}/fdbserver.x86_64 -o ${OLD_FDB_BINARY_DIR}/fdbserver-${old_fdb_server_version}; \
        done && \
        chmod +x ${OLD_FDB_BINARY_DIR}/* && \
        curl -Ls --retry 5 --fail https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/libfdb_c.x86_64.so -o /usr/lib64/libfdb_c_${FDB_VERSION}.so && \
        ln -s /usr/lib64/libfdb_c_${FDB_VERSION}.so /usr/lib64/libfdb_c.so; \
    fi

ENV FDB_CLUSTER_FILE=/etc/foundationdb/fdb.cluster
ENV AGENT_TIMEOUT=300

# joshua-agent often needs huge retry limits
# because of thundering-herd of thousands of agents doing joshua_model.try_running_test()
ENV TRANSACTION_TIMEOUT_MS=256000
ENV TRANSACTION_RETRY_LIMIT=1000

USER joshua
CMD python3 -m joshua.joshua_agent \
        -C ${FDB_CLUSTER_FILE} \
        --work_dir /var/joshua \
        --agent-idle-timeout ${AGENT_TIMEOUT}
