FROM golang:1.25.10-bookworm AS go-builder

ARG FDB_VERSION="7.1.57"
ARG FDB_WEBSITE
ARG TAG="latest"

# TODO(johscheuer): Add support for arm64.
RUN set -eux && \
    curl --fail -L "https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/foundationdb-clients_${FDB_VERSION}-1_amd64.deb" -o foundationdb-clients_${FDB_VERSION}-1_amd64.deb && \
    curl --fail -L "https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/foundationdb-clients_${FDB_VERSION}-1_amd64.deb.sha256" -o foundationdb-clients_${FDB_VERSION}-1_amd64.deb.sha256 && \
    sha256sum -c foundationdb-clients_${FDB_VERSION}-1_amd64.deb.sha256 && \
    dpkg -i foundationdb-clients_${FDB_VERSION}-1_amd64.deb && \
    rm foundationdb-clients_${FDB_VERSION}-1_amd64.deb foundationdb-clients_${FDB_VERSION}-1_amd64.deb.sha256

ENV CGO_ENABLED=1

COPY go.mod go.sum /src/
WORKDIR /src
RUN go mod download

COPY cmd /src/cmd
COPY internal /src/internal

RUN CGO_ENABLED=1 GOOS=linux GO111MODULE=on go build -ldflags="-s -w" -o /agent-scaler ./cmd

FROM rockylinux/rockylinux:9.6
ARG AGENT_TAG=joshua-agent:latest

RUN dnf -y update && \
    dnf install -y \
        epel-release \
        scl-utils \
        yum-utils \
        pkg-config && \
    dnf -y install \
        gettext \
        procps-ng \
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
RUN rpm -ivh --excludepath=/usr/bin --excludepath=/usr/lib/foundationdb/backup_agent https://github.com/apple/foundationdb/releases/download/${FDB_VERSION}/foundationdb-clients-${FDB_VERSION}-1.el7.x86_64.rpm

# FDB python binding
RUN pip3 install \
         foundationdb==7.1.57 \
         boto3

COPY --from=go-builder /agent-scaler /usr/local/bin
COPY entrypoint.sh /tools/
RUN chmod +x /tools/entrypoint.sh

ENV BATCH_SIZE=1
ENV MAX_JOBS=10
ENV CHECK_DELAY=10
ENV AGENT_TIMEOUT=300
ENV AGENT_TAG=${AGENT_TAG}
ENV NAMESPACE=joshua
ENV AGENT_NAME=joshua-agent
ENV SCALER_IMPL=bash

ENTRYPOINT ["/tools/entrypoint.sh"]
