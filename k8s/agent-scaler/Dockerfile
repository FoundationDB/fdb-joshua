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
    curl -Ls https://dl.k8s.io/release/v1.20.0/bin/linux/$(uname -p)/kubectl \
         -o /usr/local/bin/kubectl && \
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
ARG FDB_VERSION="6.2.29"
RUN curl -Ls https://www.foundationdb.org/downloads/${FDB_VERSION}/linux/libfdb_c_${FDB_VERSION}.so \
         -o /lib64/libfdb_c.so && \
    chmod +x /lib64/libfdb_c.so

ENV LD_LIBRARY_PATH="/lib64:$LD_LIBRARY_PATH"

# FDB python binding
RUN source /opt/rh/rh-python38/enable && \
    pip3 install foundationdb==6.2.10

ENV BATCH_SIZE=1
ENV MAX_JOBS=10
ENV CHECK_DELAY=10
ENV AGENT_TIMEOUT=300
ENV AGENT_TAG=${AGENT_TAG}
ENV NAMESPACE=joshua

# Entry point
ENTRYPOINT source /opt/rh/rh-python38/enable && /tools/agent-scaler.sh
