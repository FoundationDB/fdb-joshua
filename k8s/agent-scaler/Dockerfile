FROM centos:centos7

# Install Python 3 and Mono
RUN yum update all && yum install -y yum-utils && \
    yum -y install centos-release-scl epel-release && \
    yum -y install rh-python36-python rh-python36-python-pip gettext

# kubectl
RUN curl -LO https://storage.googleapis.com/kubernetes-release/release/v1.14.0/bin/linux/amd64/kubectl && chmod +x kubectl && mv kubectl /bin/

# agent-scaler tools
RUN mkdir -p /tools
COPY agent-scaler.sh ensemble_count.py tmp/joshua_model.py /tools/
RUN chmod +x /tools/agent-scaler.sh /tools/ensemble_count.py /tools/joshua_model.py

# libfdb_c.so
RUN curl -L https://www.foundationdb.org/downloads/$(curl -L https://www.foundationdb.org/downloads/version.txt)/linux/libfdb_c_$(curl -L https://www.foundationdb.org/downloads/version.txt).so -o /lib64/libfdb_c.so
RUN chmod +x /lib64/libfdb_c.so
ENV LD_LIBRARY_PATH="/lib64:$LD_LIBRARY_PATH"

# FDB python binding
RUN scl enable rh-python36 -- pip install foundationdb

ENV BATCH_SIZE=1
ENV MAX_JOBS=10
ENV CHECK_DELAY=10
ENV AGENT_TIMEOUT=300
ENV AGENT_TAG="joshua-agent:latest"

# Entry point
ENTRYPOINT ["scl", "enable", "rh-python36", "--", "/tools/agent-scaler.sh"]
