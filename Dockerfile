ARG BASE_IMAGE="centos:7"
FROM ${BASE_IMAGE}
# this is joshua-agent

WORKDIR /tmp

# Detect RHEL base version
RUN echo "RHEL_BASE_MAJOR_VERSION=$(awk -F'=' '/VERSION_ID/{ gsub(/"|\..*/,""); print $2; }' /etc/os-release)" >> /etc/session && \
    echo "DISTRIBUTIVE_NAME=$(awk -F'=' '/^ID=/{ gsub(/"/,""); print $2; }' /etc/os-release)" >> /etc/session

RUN source /etc/session && \
    if test -z "$RHEL_BASE_MAJOR_VERSION"; then \
        echo "Failed to detect distributive version" && \
        exit 1; \
    elif test "$RHEL_BASE_MAJOR_VERSION" -eq 7; then \
        package_manager="yum" && \
        $package_manager install -y epel-release \
                                    centos-release-scl-rh && \
        install_pkgs="devtoolset-11 \
                      devtoolset-11-libasan-devel \
                      devtoolset-11-liblsan-devel \
                      devtoolset-11-libtsan-devel \
                      devtoolset-11-libubsan-devel \
                      rh-python38 \
                      rh-python38-python-devel \
                      rh-python38-python-pip \
                      rh-ruby27 \
                      rh-ruby27-ruby-devel"; \
    elif test "$RHEL_BASE_MAJOR_VERSION" -ge 8; then \
        package_manager="dnf --setopt=tsflags=nodocs" && \
        install_pkgs="make \
                      perl \
                      python38 \
                      python38-devel \
                      python38-pip \
                      ruby \
                      ruby-devel \
                      redhat-rpm-config" && \
        if test "rhel" = "$DISTRIBUTIVE_NAME"; then \
            rpmkeys --import "http://keyserver.ubuntu.com/pks/lookup?op=get&search=0x3FA7E0328081BFF6A14DA29AA6A19B38D3D831EF" && \
            curl https://download.mono-project.com/repo/centos8-stable.repo | tee /etc/yum.repos.d/mono-centos8-stable.repo && \
            install_pkgs="gcc-toolset-11-gcc $install_pkgs"; \
        elif test "centos" = "$DISTRIBUTIVE_NAME" -o "rocky" = "$DISTRIBUTIVE_NAME"; then \
            $package_manager install -y epel-release && \
            install_pkgs="gcc-toolset-11 \
                          gcc-toolset-11-libasan-devel \
                          gcc-toolset-11-liblsan-devel \
                          gcc-toolset-11-libtsan-devel \
                          gcc-toolset-11-libubsan-devel \
                          $install_pkgs"; \
        else \
            echo "Unsupported distributive $DISTRIBUTIVE_NAME" && \
            exit 2; \
        fi; \
    else \
        echo "Unsupported version $RHEL_BASE_MAJOR_VERSION" && \
        exit 3; \
    fi && \
 install_pkgs="yum-utils \
               scl-utils \
               bzip2 \
               gettext \
               golang \
               java-11-openjdk-headless \
               mono-core \
               net-tools \
               libatomic \
               $install_pkgs" && \
    $package_manager repolist && \
    $package_manager install -y $install_pkgs && \
    if test "$RHEL_BASE_MAJOR_VERSION" -eq 7; then \
        ls -l /opt/rh/ && \
        source /opt/rh/devtoolset-11/enable; \
        source /opt/rh/rh-python38/enable && \
        source /opt/rh/rh-ruby27/enable; \
    elif test "$RHEL_BASE_MAJOR_VERSION" -ge 8; then \
        echo "" >/usr/lib/rpm/redhat/redhat-annobin-cc1 && \
        source /opt/rh/gcc-toolset-11/enable; \
    fi && \
    pip3 install \
        python-dateutil \
        subprocess32 \
        psutil && \
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

# valgrind
RUN source /etc/session && \
    if test "$RHEL_BASE_MAJOR_VERSION" -eq 7; then \
        source /opt/rh/devtoolset-11/enable; \
    elif test "$RHEL_BASE_MAJOR_VERSION" -ge 8; then \
        source /opt/rh/gcc-toolset-11/enable; \
    fi && \
    curl -Ls https://sourceware.org/pub/valgrind/valgrind-3.19.0.tar.bz2 -o valgrind-3.19.0.tar.bz2 && \
    echo "dd5e34486f1a483ff7be7300cc16b4d6b24690987877c3278d797534d6738f02  valgrind-3.19.0.tar.bz2" > valgrind-sha.txt && \
    sha256sum -c valgrind-sha.txt && \
    mkdir valgrind && \
    tar --strip-components 1 --no-same-owner --no-same-permissions --directory valgrind -xjf valgrind-3.19.0.tar.bz2 && \
    cd valgrind && \
    ./configure && \
    make -j$(nproc) && \
    make install && \
    cd .. && \
    rm -rf /tmp/*

COPY childsubreaper/ /opt/joshua/install/childsubreaper
COPY joshua/ /opt/joshua/install/joshua
COPY setup.py /opt/joshua/install/

RUN source /etc/session && \
    if test "$RHEL_BASE_MAJOR_VERSION" -eq 7; then \
        source /opt/rh/devtoolset-11/enable && \
        source /opt/rh/rh-python38/enable && \
        source /opt/rh/rh-ruby27/enable; \
    elif test "$RHEL_BASE_MAJOR_VERSION" -ge 8; then \
        source /opt/rh/gcc-toolset-11/enable; \
    fi && \
    pip3 install /opt/joshua/install && \
    rm -rf /opt/joshua/install

ARG OLD_FDB_BINARY_DIR=/app/deploy/global_data/oldBinaries/
ARG OLD_TLS_LIBRARY_DIR=/app/deploy/runtime/.tls_5_1/
ARG FDB_VERSION="6.3.18"
RUN if [ "$(uname -p)" == "x86_64" ]; then \
        mkdir -p ${OLD_FDB_BINARY_DIR} \
                 ${OLD_TLS_LIBRARY_DIR} \
                 /usr/lib/foundationdb/plugins && \
        for old_fdb_server_version in 6.3.18 6.3.17 6.3.16 6.3.15 6.3.13 6.3.12 6.3.9 6.2.30 6.2.29 6.2.28 6.2.27 6.2.26 6.2.25 6.2.24 6.2.23 6.2.22 6.2.21 6.2.20 6.2.19 6.2.18 6.2.17 6.2.16 6.2.15 6.2.10 6.1.13 6.1.12 6.1.11 6.1.10 6.0.18 6.0.17 6.0.16 6.0.15 6.0.14 5.2.8 5.2.7 5.1.7 5.1.6; do \
            curl -Ls https://github.com/apple/foundationdb/releases/download/${old_fdb_server_version}/fdbserver.x86_64 -o ${OLD_FDB_BINARY_DIR}/fdbserver-${old_fdb_server_version}; \
        done && \
        chmod +x ${OLD_FDB_BINARY_DIR}/* && \
        curl -Ls https://fdb-joshua.s3.amazonaws.com/old_tls_library.tgz | tar -xz -C ${OLD_TLS_LIBRARY_DIR} --strip-components=1 && \
        curl -Ls https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/libfdb_c.x86_64.so -o /usr/lib64/libfdb_c_${FDB_VERSION}.so && \
        ln -s /usr/lib64/libfdb_c_${FDB_VERSION}.so /usr/lib64/libfdb_c.so && \
        ln -s ${OLD_TLS_LIBRARY_DIR}/FDBGnuTLS.so /usr/lib/foundationdb/plugins/fdb-libressl-plugin.so && \
        ln -s ${OLD_TLS_LIBRARY_DIR}/FDBGnuTLS.so /usr/lib/foundationdb/plugins/FDBGnuTLS.so; \
    fi

ENV FDB_CLUSTER_FILE=/etc/foundationdb/fdb.cluster
ENV AGENT_TIMEOUT=300

USER joshua
CMD source /etc/session && \
    if test "$RHEL_BASE_MAJOR_VERSION" -eq 7; then \
        source /opt/rh/devtoolset-11/enable && \
        source /opt/rh/rh-python38/enable && \
        source /opt/rh/rh-ruby27/enable && \
    elif test "$RHEL_BASE_MAJOR_VERSION" -ge 8; then \
        source /opt/rh/gcc-toolset-11/enable; \
    fi && \
    python3 -m joshua.joshua_agent \
        -C ${FDB_CLUSTER_FILE} \
        --work_dir /var/joshua \
        --agent-idle-timeout ${AGENT_TIMEOUT}

