FROM rockylinux/rockylinux:9.7
ARG AGENT_TAG=joshua-agent:latest

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

RUN case $(uname -m) in \
            x86_64) curl -Ls https://dl.k8s.io/release/v1.30.14/bin/linux/amd64/kubectl -o /usr/local/bin/kubectl;; \
            aarch64) curl -Ls https://dl.k8s.io/release/v1.30.14/bin/linux/arm64/kubectl -o /usr/local/bin/kubectl;; \
            *) echo "unsupported architecture for kubectl"; exit 1 ;; \
    esac; \
    chmod +x /usr/local/bin/kubectl

# agent-scaler tools
COPY agent-scaler.sh /tools/
COPY ensemble_count.py /tools/
COPY joshua_model.py /tools/

RUN chmod +x \
    /tools/agent-scaler.sh \
    /tools/ensemble_count.py \
    /tools/joshua_model.py

# libfdb_c.so
ARG FDB_VERSION="7.1.57"
RUN curl -Ls https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/libfdb_c.x86_64.so \
         -o /lib64/libfdb_c.so && \
    chmod +x /lib64/libfdb_c.so

ENV LD_LIBRARY_PATH="/lib64:$LD_LIBRARY_PATH"

# FDB python binding
# TODO: This should be in a requirements file with version pinning.
RUN python3 -m pip install \
        foundationdb==${FDB_VERSION} \
        boto3==1.43.14

ENV BATCH_SIZE=1
ENV MAX_JOBS=10
ENV CHECK_DELAY=10
ENV AGENT_TAG=${AGENT_TAG}
ENV NAMESPACE=joshua
ENV AGENT_NAME=joshua-agent

# Entry point
ENTRYPOINT /tools/agent-scaler.sh
