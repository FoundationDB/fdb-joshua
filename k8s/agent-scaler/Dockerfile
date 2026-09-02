FROM rockylinux/rockylinux:9.8
ARG AGENT_TAG=joshua-agent:latest
ARG TARGETARCH
# Currently Python 3.13 is used as the default python version 3.9 is EOL:
# https://devguide.python.org/versions
# gettext is for 'envsubst'
RUN dnf -y update && \
    dnf install -y \
        epel-release \
        scl-utils \
        yum-utils && \
    dnf -y install \
        lsof \
        procps-ng \
        gettext \
        jq-1.6 \
        python3.13 \
        python3.13-pip && \
    dnf -y clean all --enablerepo='*'

RUN ln -sf /usr/bin/python3.13 /usr/bin/python3 && \
    ln -sf /usr/bin/pip3.13 /usr/bin/pip3

RUN curl -Ls "https://dl.k8s.io/release/v1.30.14/bin/linux/${TARGETARCH}/kubectl" -o /usr/local/bin/kubectl && \
    chmod +x /usr/local/bin/kubectl

# agent-scaler tools
COPY agent-scaler.sh /tools/
COPY ensemble_count.py /tools/
COPY joshua_model.py /tools/
COPY stop_completed_ensembles.py /tools/

# libfdb_c.so
ARG FDB_VERSION="7.1.57"

VOLUME /usr/lib/fdb
# Install primary FDB version
RUN set -eux && \
    if [ "${TARGETARCH}" = "amd64" ]; then \
         FDB_ARCH=x86_64; \
    elif [ "${TARGETARCH}" = "arm64" ]; then \
         FDB_ARCH=aarch64; \
         if [ "${FDB_VERSION%.*}" = "7.1" ]; then \
            FDB_VERSION="7.3.71"; \
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

# FDB python binding
# TODO: This should be in a requirements file with version pinning.
RUN python3 -m pip install \
        foundationdb==${FDB_VERSION} \
        boto3==1.43.14 \
        azure-storage-blob

ENV BATCH_SIZE=1
ENV MAX_JOBS=10
ENV CHECK_DELAY=10
ENV AGENT_TAG=${AGENT_TAG}
ENV NAMESPACE=joshua
ENV AGENT_NAME=joshua-agent
ENV FDB_NETWORK_OPTION_EXTERNAL_CLIENT_DIRECTORY=/usr/lib/fdb

# Entry point
ENTRYPOINT /tools/agent-scaler.sh
