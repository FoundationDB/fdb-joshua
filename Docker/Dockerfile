FROM centos:centos7

# Install Python 3 and Mono
RUN yum update all && yum install -y yum-utils && \
    yum -y install centos-release-scl epel-release && \
    yum -y install gcc mono-core rh-python38-python rh-python38-python-devel \
           rh-python38-python-pip valgrind net-tools golang java-11-openjdk \
           sysvinit-tools rh-ruby27 rh-ruby27-ruby-devel make \
           libasan libubsan && \
    scl enable rh-python38 -- pip install python-dateutil subprocess32 psutil && \
    scl enable rh-ruby27 -- gem install ffi --platform=ruby

# Install Joshua python package and fix time zone
ARG TIMEZONEINFO=America/Los_Angeles
ADD install /opt/joshua/install
RUN scl enable rh-python38 -- pip install /opt/joshua/install && rm -rf /opt/joshua/install && rm -f /etc/localtime && ln -s /usr/share/zoneinfo/${TIMEZONEINFO} /etc/localtime

# Download and install old fdbserver binaries, TLS libraries, and C bindings. (x86_64 build only)
COPY download_old_fdb.sh start_agents.py /usr/bin/
RUN if [ "$(uname -p)" == "x86_64" ]; then \
        /usr/bin/download_old_fdb.sh 1; \
    fi

# Add the user and group joshua
RUN groupadd -r joshua -g 4060 && useradd -rm -d /home/joshua -s /bin/bash -u 4060 -g joshua joshua && mkdir -p /var/joshua && chown -R joshua:joshua /var/joshua

# By default, the number of agents is set to be the same as the number of CPUs.
ENV AGENT_TOTAL=0

# By default, leave no CPUs free on the machine
ENV AGENT_FREECPUS=0

# By default, let agent manager sleep for 15 seconds between checks
ENV AGENT_MGRSLEEP=15

# By default, the agent priority is normal.
ENV AGENT_PRIORITY=0

# By default, agent grows at 100%
ENV AGENT_GROWTHRATE=100

# By default, node exits when 10GB left
ENV AGENT_FREESPACE=10.0

# By default, display reports every 10.0 minutes
ENV AGENT_REPORTFREQ=10.0

# Top level directory for joshua agent to run and to store log files
ARG AGENT_WORK_DIR=/tmp/joshua_agent
ENV AGENT_WORK_DIR=${AGENT_WORK_DIR}

# FoundationDB directory layer
ARG AGENT_NAMESPACE='joshua'
ENV AGENT_NAMESPACE=${AGENT_NAMESPACE}

# FoundationDB cluster file
ARG CLUSTER_FILE=${AGENT_WORK_DIR}/fdb.cluster
ENV CLUSTER_FILE=${CLUSTER_FILE}

ARG DOCKER_IMAGEVER=devel
ENV DOCKER_IMAGEVER=${DOCKER_IMAGEVER}
LABEL version=${DOCKER_IMAGEVER}

# Run the image as joshua
USER joshua

CMD scl enable rh-python38 rh-ruby27 -- python3 -u /usr/bin/start_agents.py -C "${CLUSTER_FILE}" --dir "${AGENT_WORK_DIR}" --name-space "${AGENT_NAMESPACE}" --number "${AGENT_TOTAL}" --priority "${AGENT_PRIORITY}" --free-cpus "${AGENT_FREECPUS}" --free-space "${AGENT_FREESPACE}" --growth-rate "${AGENT_GROWTHRATE}" --report-freq "${AGENT_REPORTFREQ}" --mgr-sleep "${AGENT_MGRSLEEP}"
