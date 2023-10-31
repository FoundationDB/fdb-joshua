FROM rockylinux:9
# this is joshua-agent

WORKDIR /tmp

RUN dnf -y update && \
    dnf install -y \
        epel-release \
        scl-utils \
        yum-utils && \
    dnf -y install --enablerepo=devel \
        bzip2 \
        criu \
        gcc-c++ \
        gettext \
        java-11-openjdk-devel \
        libasan \
        libasan-static \
        libatomic \
        libatomic-static \
        libffi \
        libffi-devel \
        liblsan \
        liblsan-static \
        libtsan \
        libtsan-static \
        libubsan \
        libubsan-static \
        mono-core \
        net-tools \
        python3-devel \
        redhat-rpm-config \
        ruby \
        ruby-devel \
        rubygem-ffi \
        systemtap-sdt-devel && \
    pip3 install \
        python-dateutil \
        subprocess32 \
        psutil \
        kubernetes \
        urllib3==1.26.14 \
        boto3 && \
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

# valgrind
RUN curl -Ls --retry 5 --fail https://sourceware.org/pub/valgrind/valgrind-3.20.0.tar.bz2 -o valgrind.tar.bz2 && \
    echo "8536c031dbe078d342f121fa881a9ecd205cb5a78e639005ad570011bdb9f3c6  valgrind.tar.bz2" > valgrind-sha.txt && \
    sha256sum -c valgrind-sha.txt && \
    mkdir valgrind && \
    tar --strip-components 1 --no-same-owner --no-same-permissions --directory valgrind -xjf valgrind.tar.bz2 && \
    cd valgrind && \
    ./configure --enable-only64bit --enable-lto && \
    make && \
    make install && \
    cd .. && \
    rm -rf /tmp/*

# install golang 1.20
RUN if [ "$(uname -m)" == "aarch64" ]; then \
        GOLANG_ARCH="arm64"; \
        GOLANG_SHA256="4e15ab37556e979181a1a1cc60f6d796932223a0f5351d7c83768b356f84429b"; \
    else \
        GOLANG_ARCH="amd64"; \
        GOLANG_SHA256="b945ae2bb5db01a0fb4786afde64e6fbab50b67f6fa0eb6cfa4924f16a7ff1eb"; \
    fi && \
    curl -Ls https://golang.org/dl/go1.20.6.linux-${GOLANG_ARCH}.tar.gz -o golang.tar.gz && \
    echo "${GOLANG_SHA256}  golang.tar.gz" > golang-sha.txt && \
    sha256sum --quiet -c golang-sha.txt && \
    tar --directory /usr/local -xf golang.tar.gz && \
    echo '[ -x /usr/local/go/bin/go ] && export GOROOT=/usr/local/go && export GOPATH=$HOME/go && export PATH=$GOPATH/bin:$GOROOT/bin:$PATH' >> /etc/profile.d/golang.sh && \
    source /etc/profile.d/golang.sh && \
    rm -rf /tmp/*

COPY childsubreaper/ /opt/joshua/install/childsubreaper
COPY joshua/ /opt/joshua/install/joshua
COPY setup.py /opt/joshua/install/

RUN pip3 install /opt/joshua/install && \
    rm -rf /opt/joshua/install

ARG OLD_FDB_BINARY_DIR=/app/deploy/global_data/oldBinaries/
ARG OLD_TLS_LIBRARY_DIR=/app/deploy/runtime/.tls_5_1/
ARG FDB_VERSION="6.3.18"
RUN if [ "$(uname -p)" == "x86_64" ]; then \
        mkdir -p ${OLD_FDB_BINARY_DIR} \
                 ${OLD_TLS_LIBRARY_DIR} \
                 /usr/lib/foundationdb/plugins && \
        for old_fdb_server_version in 7.3.25 7.1.43 7.1.41 7.1.39 6.3.25 6.3.18; do \
            curl -Ls --retry 5 --fail https://github.com/apple/foundationdb/releases/download/${old_fdb_server_version}/fdbserver.x86_64 -o ${OLD_FDB_BINARY_DIR}/fdbserver-${old_fdb_server_version}; \
        done && \
        chmod +x ${OLD_FDB_BINARY_DIR}/* && \
        curl -Ls --retry 5 --fail https://fdb-joshua.s3.amazonaws.com/old_tls_library.tgz | tar -xz -C ${OLD_TLS_LIBRARY_DIR} --strip-components=1 && \
        curl -Ls --retry 5 --fail https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/libfdb_c.x86_64.so -o /usr/lib64/libfdb_c_${FDB_VERSION}.so && \
        ln -s /usr/lib64/libfdb_c_${FDB_VERSION}.so /usr/lib64/libfdb_c.so && \
        ln -s ${OLD_TLS_LIBRARY_DIR}/FDBGnuTLS.so /usr/lib/foundationdb/plugins/fdb-libressl-plugin.so && \
        ln -s ${OLD_TLS_LIBRARY_DIR}/FDBGnuTLS.so /usr/lib/foundationdb/plugins/FDBGnuTLS.so; \
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

# aarch64 package is not available for CentOS7
# https://www.swift.org/download/
RUN if [ "$(uname -p)" == "x86_64" ]; then \
        set -e; \
        export $(curl -Ls ${SWIFT_WEBROOT}/latest-build.yml | grep 'download:' | sed 's/:[^:\/\/]/=/g') && \
        export $(curl -Ls ${SWIFT_WEBROOT}/latest-build.yml | grep 'download_signature:' | sed 's/:[^:\/\/]/=/g')  && \
        export DOWNLOAD_DIR=$(echo $download | sed "s/-${OS_VER}.tar.gz//g") && \
        echo $DOWNLOAD_DIR > .swift_tag && \
        export GNUPGHOME="$(mktemp -d)" && \
        curl -fLs ${SWIFT_WEBROOT}/${DOWNLOAD_DIR}/${download} -o latest_toolchain.tar.gz && \
        curl -fLs ${SWIFT_WEBROOT}/${DOWNLOAD_DIR}/${download_signature} -o latest_toolchain.tar.gz.sig && \
        curl -fLs https://swift.org/keys/all-keys.asc | gpg --import -  && \
        gpg --batch --verify latest_toolchain.tar.gz.sig latest_toolchain.tar.gz && \
        tar -xzf latest_toolchain.tar.gz --directory / --strip-components=1 && \
        chmod -R o+r /usr/lib/swift && \
        rm -rf "$GNUPGHOME" latest_toolchain.tar.gz.sig latest_toolchain.tar.gz; \
    fi

# Print Installed Swift Version
RUN if [ "$(uname -p)" == "x86_64" ]; then \
        swift --version; \
    fi

ENV FDB_CLUSTER_FILE=/etc/foundationdb/fdb.cluster
ENV AGENT_TIMEOUT=300

USER joshua
CMD source /opt/rh/devtoolset-${DEVTOOLSET_VERSION}/enable && \
    source /opt/rh/rh-python38/enable && \
    source /opt/rh/rh-ruby27/enable && \
    python3 -m joshua.joshua_agent \
        -C ${FDB_CLUSTER_FILE} \
        --work_dir /var/joshua \
        --agent-idle-timeout ${AGENT_TIMEOUT}

