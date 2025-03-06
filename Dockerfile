FROM rockylinux:9.3
# this is joshua-agent

WORKDIR /tmp

RUN dnf update -y && \
    dnf install -y \
        epel-release \
        dnf-plugins-core && \
    dnf config-manager --set-enabled crb && \
    dnf install -y \
        bzip2 \
        xz \
        criu \
        gettext \
        golang \
        java-11-openjdk-devel \
        mono-core \
        net-tools \
        python3 \
        python3-devel \
        python3-pip \
        ruby \
        ruby-devel \
        libffi-devel \
        libatomic \
        valgrind && \
    pip3 install \
        python-dateutil \
        subprocess32 \
        psutil \
        kubernetes \
        urllib3==1.26.14 \
        boto3 && \
    gem install ffi --platform=ruby && \
    groupadd -r joshua -g 4060 && \
    useradd \
        -rm \
        -d /home/joshua \
        -s /bin/bash \
        -u 4060 \
        -g joshua \
        joshua && \
    mkdir -p /var/joshua && \
    chown -R joshua:joshua /var/joshua && \
    rm -rf /tmp/*

# Install Joshua client
COPY childsubreaper/ /opt/joshua/install/childsubreaper
COPY joshua/ /opt/joshua/install/joshua
COPY setup.py /opt/joshua/install/
RUN ARTIFACT=client pip3 install /opt/joshua/install && \
    rm -rf /opt/joshua/install

# install old fdbserver binaries and libfdb_c.so
# Skip these old versions: 6.2.30 6.2.29 6.2.28 6.2.27 6.2.26 6.2.25 6.2.24 6.2.23 6.2.22 6.2.21 6.2.20 6.2.19 6.2.18 6.2.17 6.2.16 6.2.15 6.2.10 6.1.13 6.1.12 6.1.11 6.1.10 6.0.18 6.0.17 6.0.16 6.0.15 6.0.14 5.2.8 5.2.7 5.1.7 5.1.6
# because 7.3 no longer supports upgrade from these versions.
ARG OLD_FDB_BINARY_DIR=/app/deploy/global_data/oldBinaries/
ARG FDB_VERSION="7.1.57"
RUN if [ "$(uname -p)" == "x86_64" ]; then \
        mkdir -p ${OLD_FDB_BINARY_DIR} \
                 /usr/lib/foundationdb/plugins && \
        for old_fdb_server_version in 7.3.63, 7.3.57 7.3.43 7.3.27 7.1.61 7.1.57 7.1.43 7.1.35 7.1.33 7.1.27 7.1.25 7.1.23 7.1.19 6.3.18 6.3.17 6.3.16 6.3.15 6.3.13 6.3.12 6.3.9; do \
            curl -Ls --retry 5 --fail https://github.com/apple/foundationdb/releases/download/${old_fdb_server_version}/fdbserver.x86_64 -o ${OLD_FDB_BINARY_DIR}/fdbserver-${old_fdb_server_version}; \
        done && \
        chmod +x ${OLD_FDB_BINARY_DIR}/* && \
        curl -Ls --retry 5 --fail https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/libfdb_c.x86_64.so -o /usr/lib64/libfdb_c_${FDB_VERSION}.so && \
        ln -s /usr/lib64/libfdb_c_${FDB_VERSION}.so /usr/lib64/libfdb_c.so; \
    fi

# Download swift binaries
ARG SWIFT_SIGNING_KEY=8A7495662C3CD4AE18D95637FAF6989E1BC16FEA
ARG SWIFT_PLATFORM=centos
ARG OS_MAJOR_VER=7
ARG SWIFT_WEBROOT=https://download.swift.org/development

ENV SWIFT_SIGNING_KEY=$SWIFT_SIGNING_KEY \
    SWIFT_PLATFORM=$SWIFT_PLATFORM \
    OS_MAJOR_VER=$OS_MAJOR_VER \
    OS_VER=$SWIFT_PLATFORM$OS_MAJOR_VER \
    SWIFT_WEBROOT="$SWIFT_WEBROOT/$SWIFT_PLATFORM$OS_MAJOR_VER"

RUN echo "${SWIFT_WEBROOT}/latest-build.yml"

# Note: Swift package details may need further investigation for Rocky Linux 9
# swift: error while loading shared libraries: libncurses.so.5: cannot open shared object file: No such file or directory
#RUN if [ "$(uname -p)" == "x86_64" ]; then \
#        set -e; \
#        export $(curl -Ls ${SWIFT_WEBROOT}/latest-build.yml | grep 'download:' | sed 's/:[^:\/\/]/=/g') && \
#        export $(curl -Ls ${SWIFT_WEBROOT}/latest-build.yml | grep 'download_signature:' | sed 's/:[^:\/\/]/=/g')  && \
#        export DOWNLOAD_DIR=$(echo $download | sed "s/-${OS_VER}.tar.gz//g") && \
#        echo $DOWNLOAD_DIR > .swift_tag && \
#        export GNUPGHOME="$(mktemp -d)" && \
#        curl -fLs ${SWIFT_WEBROOT}/${DOWNLOAD_DIR}/${download} -o latest_toolchain.tar.gz && \
#        curl -fLs ${SWIFT_WEBROOT}/${DOWNLOAD_DIR}/${download_signature} -o latest_toolchain.tar.gz.sig && \
#        curl -fLs https://swift.org/keys/all-keys.asc | gpg --import -  && \
#        gpg --batch --verify latest_toolchain.tar.gz.sig latest_toolchain.tar.gz && \
#        tar -xzf latest_toolchain.tar.gz --directory / --strip-components=1 && \
#        chmod -R o+r /usr/lib/swift && \
#        rm -rf "$GNUPGHOME" latest_toolchain.tar.gz.sig latest_toolchain.tar.gz; \
#    fi

# Print Installed Swift Version
# RUN if [ "$(uname -p)" == "x86_64" ]; then \
#        swift --version; \
#    fi

ENV FDB_CLUSTER_FILE=/etc/foundationdb/fdb.cluster
ENV AGENT_TIMEOUT=300

USER joshua
CMD python3 -m joshua.joshua_agent \
        -C ${FDB_CLUSTER_FILE} \
        --work_dir /var/joshua \
        --agent-idle-timeout ${AGENT_TIMEOUT}
