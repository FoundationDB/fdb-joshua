FROM centos:7
ARG AGENT_TAG=joshua-agent:latest

# Install Python 3 and Mono
RUN yum repolist && \
    yum install -y \
        centos-release-scl-rh \
        epel-release \
        scl-utils \
        yum-utils && \
    yum -y install \
        gettext \
        rh-python38 \
        rh-python38-python-pip && \
    yum -y clean all --enablerepo='*' && \
    case $(uname -m) in \
            x86_64) curl -Ls https://dl.k8s.io/release/v1.20.0/bin/linux/amd64/kubectl -o /usr/local/bin/kubectl;; \
            aarch64) curl -Ls https://dl.k8s.io/release/v1.20.0/bin/linux/arm64/kubectl -o /usr/local/bin/kubectl;; \
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
ARG FDB_VERSION="6.3.18"
RUN curl -Ls https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/libfdb_c.x86_64.so \
         -o /lib64/libfdb_c.so && \
    chmod +x /lib64/libfdb_c.so

ENV LD_LIBRARY_PATH="/lib64:$LD_LIBRARY_PATH"

# FDB python binding
RUN source /opt/rh/rh-python38/enable && \
    pip3 install foundationdb==6.3.18

ENV BATCH_SIZE=1
ENV MAX_JOBS=10
ENV CHECK_DELAY=10
ENV AGENT_TIMEOUT=300
ENV AGENT_TAG=${AGENT_TAG}
ENV NAMESPACE=joshua

# Entry point
ENTRYPOINT source /opt/rh/rh-python38/enable && /tools/agent-scaler.sh
