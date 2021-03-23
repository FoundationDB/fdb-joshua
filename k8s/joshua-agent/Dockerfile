FROM foundationdb/joshua-agent:latest

# image name and version above need to be set
# via IMAGENAME and IMAGEVER environment variables
# at the base image creation time

# FoundationDB cluster file
# fdb.cluster must be configured through configMap
ENV FDB_CLUSTER_FILE=/etc/foundationdb/fdb.cluster

# Defualt timeout
ENV AGENT_TIMEOUT=300

# start 1 agent only
# --work_dir and --cluster-file must be specified via command line
CMD scl enable rh-python38 rh-ruby27 -- python3 -m joshua.joshua_agent -C ${FDB_CLUSTER_FILE} --work_dir ${AGENT_WORK_DIR} --agent-idle-timeout ${AGENT_TIMEOUT}
