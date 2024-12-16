FROM rockylinux:9.3
ARG AGENT_TAG=joshua-agent:latest

RUN dnf -y update && \
    dnf install -y \
        epel-release \
        scl-utils \
        yum-utils && \
    dnf -y install \
        gettext \
        jq-1.6 \
        python3-pip && \
    dnf -y clean all --enablerepo='*' && \
    case $(uname -m) in \
            x86_64) curl -Ls https://dl.k8s.io/release/v1.27.5/bin/linux/amd64/kubectl -o /usr/local/bin/kubectl;; \
            aarch64) curl -Ls https://dl.k8s.io/release/v1.27.5/bin/linux/arm64/kubectl -o /usr/local/bin/kubectl;; \
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
RUN pip3 install \
        foundationdb==7.1.57 \
        boto3

ENV BATCH_SIZE=1
ENV MAX_JOBS=10
ENV CHECK_DELAY=10
ENV AGENT_TIMEOUT=300
ENV AGENT_TAG=${AGENT_TAG}
ENV NAMESPACE=joshua

# Entry point
ENTRYPOINT /tools/agent-scaler.sh
