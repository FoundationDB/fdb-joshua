#!/bin/bash
######################################################
#
# Joshua Node Manager Script
#
# This script will initialize a machine to run
# agents on a joshua node.
#
# Defines:
# REQUIREDBINS		Array of required binaries
# SCRIPTDIR			Directory location of the current script
# OSNAME			Name of current OS
# OSTYPE			Type of current OS (WIN | OSX | LINUX)
#
# Author: Alvin Moore
# Date:	 20-07-01
######################################################

# Defines
#
SCRIPTDIR=$( cd "${BASH_SOURCE[0]%\/*}" && pwd )
SCRIPTNAME="${BASH_SOURCE[0]##*\/}"
TZ="${TZ:-America/Los_Angeles}"
CWD=$(pwd)
OSNAME="$(uname -s)"
HOSTNAME="${HOSTNAME:-$(hostname)}"
REQUIREDBINS=( 'which' 'nproc' 'grep' 'awk' 'docker' 'git' 'ssh-add' 'ssh-agent' 'hostname' 'id')
RAMDISK_ENABLE="${RAMDISK_ENABLE:-0}"
RAMDISK_SIZE="${RAMDISK_SIZE:-$(nproc)}"
AGENT_TOTAL="${AGENT_TOTAL:-0}"
AGENT_FREECPUS="${AGENT_FREECPUS:-0}"
AGENT_MGRSLEEP="${AGENT_MGRSLEEP:-60}"
AGENT_GROWTHRATE="${AGENT_GROWTHRATE:-34}"
AGENT_PRIORITY="${AGENT_PRIORITY:-0}"
AGENT_FREESPACE="${AGENT_FREESPACE:-10.0}"
AGENT_REPORTFREQ="${AGENT_REPORTFREQ:-10.0}"
AGENT_WORK_DIR="${AGENT_WORK_DIR:-/tmp/joshua_agent/$HOSTNAME}"
AGENT_NAMESPACE="${AGENT_NAMESPACE:-joshua}"
TMPDIR="${TMPDIR:-/tmp}"
WORKDIR="${WORKDIR:-/tmp/joshuaAgent}"
REPODIR="${REPODIR:-${HOME}/repos/fdb-joshua}"
GITHUBPROJ="${GITHUBPROJ:-git@github.com:FoundationDB/fdb-joshua.git}"
GITHUBBRANCH="${GITHUBBRANCH:-master}"
GITHUBKEYNAME="${GITHUBKEYNAME:-id_rsa}"
GITHUBKEY="${GITHUBKEY:-${HOME}/.ssh/${GITHUBKEYNAME}}"
DOCKER_USERID="${DOCKER_USERID:-4060}"
DEBUG_LEVEL="${DEBUG_LEVEL:-0}"
RUN_FOREGROUND="${RUN_FOREGROUND:-0}"
DOCKER_ARGS=('--rm' --hostname="${HOSTNAME}" '-e' INSTANCE_ID_ENV_VAR="${HOSTNAME}" '-e' HOSTNAME="${HOSTNAME}" '-e' AGENT_TOTAL="${AGENT_TOTAL}" '-e' AGENT_FREECPUS="${AGENT_FREECPUS}" '-e' AGENT_WORK_DIR="${AGENT_WORK_DIR}" '-e' AGENT_NAMESPACE="${AGENT_NAMESPACE}" '-e' CLUSTER_FILE="${AGENT_WORK_DIR}/fdb.cluster" '-e' AGENT_MGRSLEEP="${AGENT_MGRSLEEP}" '-e' AGENT_GROWTHRATE="${AGENT_GROWTHRATE}" '-e' AGENT_PRIORITY="${AGENT_PRIORITY}" '-e' AGENT_FREESPACE="${AGENT_FREESPACE}" '-e' AGENT_REPORTFREQ="${AGENT_REPORTFREQ}" -v "${WORKDIR}:${AGENT_WORK_DIR}" -u "${DOCKER_USERID}")
VERSION='2.0'

function syntax()
{
	echo 'joshuaNodeMgr.ksh <FDB cluster file>'
	echo "   Environmental Variables:"
	echo "     REPODIR:        Repository directory [default ${REPODIR}]"
	echo "     WORKDIR:        Work directory for the joshua node [default ${WORKDIR}]"
	echo "     GITHUBPROJ:     GitHub project [default ${GITHUBPROJ}]"
	echo "     GITHUBBRANCH:   GitHub project branch [default ${GITHUBBRANCH}]"
	echo "     GITHUBKEY:      GitHub project ssh key [default ${GITHUBKEY}]"
	echo "     RAMDISK_ENABLE: Enable Ramdisk [default ${RAMDISK_ENABLE}]"
	echo "     RAMDISK_SIZE:   Ramdisk size (in GB) [default ${RAMDISK_SIZE}]"
	echo "     AGENT_TOTAL:    Number of agent processes to spawn [default ${AGENT_TOTAL}]"
	echo "     AGENT_PRIORITY: Nice priority for the agent process [default ${AGENT_PRIORITY}]"
	echo "     AGENT_FREESPACE: Amount of free space to maintain [default ${AGENT_FREESPACE}]"
	echo "     AGENT_REPORTFREQ:Frequency (in minutes) to display reports [default ${AGENT_REPORTFREQ}]"
	echo "     AGENT_FREECPUS: Number of CPUs to keep available [default ${AGENT_FREECPUS}]"
	echo "     AGENT_NAMESPACE: Name of the Joshua directory layer [default ${AGENT_NAMESPACE}]"
	echo "     AGENT_WORK_DIR: Location of Joshua work directory within docker [default ${AGENT_WORK_DIR}]"

	echo "   version: ${VERSION}"
	return 0
}

# Display syntax
if [ "$#" -lt 1 ] || [ "${1}" == '--help' ] || [ "${1}" == '-h' ]
then
	syntax
	exit 1
fi

# Read the original arguments
cluster_file="${1}"


function displayMessage
{
	local status=0

	if [ "$#" -lt 1 ]
	then
		echo "displayMessage <message> [add newline 0|1]"
		let status="${status} + 1"
	else
		local addnewline=0
		if [ "$#" -gt 1 ]; then addnewline="${2}"; fi

		# Increment the message counter
		let messagecount="${messagecount} + 1"

		# Display successful message, if previous message
		if [ "${messagecount}" -gt 1 ]
		then
			# Determine the amount of transpired time
			let timespent="${SECONDS}-${messagetime}"

			printf "... done in %3d seconds\n" "${timespent}"
		fi

		# Display message
		printf "%-16s      %-35s " "$(TZ=${TZ} date "+%F %H-%M-%S")" "$1"

		# Update the variables
		messagetime="${SECONDS}"

		# Add newline, if requested
		if [ "${addnewline}" -gt 0 ]; then messagecount=0; echo ''; fi
	fi

	return "${status}"
}

# The following function will verify that the required binaries are present on the systems
checkRequiredBins()
{
	local status=0
	local errors=()

	# Ensure that the required binaries are present
	for binary in "${REQUIREDBINS[@]}"
	do
		# Ensure that the binary is in the path or is the full path
		if [ ! -f "${binary}" ] && ! which "${binary}" &> /dev/null
		then
			# Store the missing binary
			errors+=("${binary}")

			# Increment the error counter
			let status="${status} + 1"
		fi
	done

	# Report on the missing required binaries, if any
	if [ "${#errors[@]}" -gt 0 ]
	then
		printf 'Unable to run script without %d required binaries' "${#errors[@]}"
		printf '\n    %s' "${errors[@]}"
		echo ''
	fi

	return "${status}"
}

function getRepository
{
	local status=0

	if [ "$#" -lt 5 ]
	then
		echo "getRepository <GitHub Project> <Project Branch> <Project Key> <Repository Dir> <Log Dir>"
		let status="${status} + 1"
	else
		local GITHUBPROJ="${1}"
		local GITHUBBRANCH="${2}"
		local GITHUBKEY="${3}"
		local REPODIR="${4}"
		local LOGDIR="${5}"
		local GITARGS=('bash' '-c')
		local GITCLONEARGS=('eval "$(ssh-agent)"' '&&' 'git' 'init' '&&' 'git' 'remote' 'add' 'origin' "${GITHUBPROJ}" '&&' 'ssh-add' '-D' '&&' 'ssh-add' "${GITHUBKEY}" '&&' 'git' 'fetch' 'origin' "${GITHUBBRANCH}" '&&' 'git' 'fetch' '&&' 'git' 'checkout' "${GITHUBBRANCH}" ';' 'pkill' 'ssh-agent')
		local GITPULLARGS=( 'eval "$(ssh-agent)"' '&&' 'ssh-add' '-D' '&&' 'ssh-add' "${GITHUBKEY}" '&&' 'git' 'pull' '&&' 'git' 'checkout' "${GITHUBBRANCH}" ';' 'pkill' 'ssh-agent')

		if ! displayMessage "Validating GitHub Files"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		# Ensure that the key file is present
		elif [ ! -f "${GITHUBKEY}" ]
		then
			let timespent="${SECONDS}-${messagetime}"
			echo "... failed in ${timespent} seconds to locate GitHub key file: ${GITHUBKEY}"
			let status="${status} + 1"

		elif [ -d "${LOGDIR}" ] && ! displayMessage "Creating Log Directory"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		# Create the log directory, if not created
		elif [ -d "${LOGDIR}" ] && ! mkdir -p "${LOGDIR}"
		then
			let timespent="${SECONDS}-${messagetime}"
			echo "... failed in ${timespent} seconds to create log directory: ${LOGDIR}"
			let status="${status} + 1"

		# Display user message
		elif [ -d "${REPODIR}" ] && ! displayMessage "Updating GitHub repository"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		# Update GitHub repository, if present
		elif [ -d "${REPODIR}" ] && (! cd "${REPODIR}" || ! "${GITARGS[@]}" "${GITPULLARGS[*]}" &> "${LOGDIR}/git_pull.log")
		then
			let timespent="${SECONDS}-${messagetime}"
			echo "... failed in ${timespent} seconds to update FoundationDB/fdb-joshua repository dir: ${REPODIR}"
			echo "GITARGS: ${GITARGS[*]}"
			echo "GITPULLARGS: ${GITPULLARGS[*]}"
			let status="${status} + 1"

		# Display user message
		elif [ ! -d "${REPODIR}" ] && ! displayMessage "Cloning GitHub repository"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		# Clone the source
		elif [ ! -d "${REPODIR}" ] && (! mkdir -p "${REPODIR}" || ! cd "${REPODIR}" || ! "${GITARGS[@]}" "${GITCLONEARGS[*]}" &> "${LOGDIR}/git_clone.log")
		then
			let timespent="${SECONDS}-${messagetime}"
			echo "... failed in ${timespent} seconds to clone FoundationDB/fdb-joshua github repository"
			echo "GITARGS: ${GITARGS[*]}"
			echo "GITCLONEARGS: ${GITCLONEARGS[*]}"
			let status="${status} + 1"
		fi
	fi
	return "${status}"
}


# Initialize the variables
status=0
messagetime=0
messagecount=0
logdir="${TMPDIR}/joshuaAgentInitLogs-${$}"
versionfile="${REPODIR}/version.txt"

# Delete the log directory on exit
if [ "${DEBUG_LEVEL}" -eq 0 ]; then
	trap "rm -rf ${logdir}" EXIT
fi

if [ "${RAMDISK_ENABLE}" -gt 0 ]; then
	REQUIREDBINS+=('sudo')
fi

printf '%-16s  %-40s \n'		"$(TZ=${TZ} date '+%F %H-%M-%S')" "Joshua Node Initialization"
printf '%-20s     Cluster File:    %-40s \n'	'' "${cluster_file}"
printf '%-20s     Repository Dir:  %-40s \n'	'' "${REPODIR}"
printf '%-20s     GitHub Project:  %-40s \n'	'' "${GITHUBPROJ}"
printf '%-20s     GitHub Branch:   %-40s \n'	'' "${GITHUBBRANCH}"
printf '%-20s     GitHub SSH Key:  %-40s \n'	'' "${GITHUBKEY}"
printf '%-20s     Work Directory:  %-40s \n'	'' "${WORKDIR}"
printf '%-20s     Agent Work Dir:  %-40s \n'	'' "${AGENT_WORK_DIR}"
printf '%-20s     Agent Total:     %-40s \n'	'' "${AGENT_TOTAL}"
printf '%-20s     Agent Free CPUs: %-40s \n'	'' "${AGENT_FREECPUS}"
printf '%-20s     Agent Priority:  %-40s \n'	'' "${AGENT_PRIORITY}"
printf '%-20s     Agent Mgr Sleep: %-40s \n'	'' "${AGENT_MGRSLEEP}"
printf '%-20s     Agent GrowthRate:%-40s \n'	'' "${AGENT_GROWTHRATE}"
printf '%-20s     Agent Free Space:%-40s \n'	'' "${AGENT_FREESPACE}"
printf '%-20s     Report Frequency:%-40s \n'	'' "${AGENT_REPORTFREQ}"
printf '%-20s     Run Foreground:  %-40s \n'	'' "${RUN_FOREGROUND}"
printf '%-20s     Enable RamDisk:  %-40s \n'	'' "${RAMDISK_ENABLE}"
printf '%-20s     RamDisk Size:    %-40s \n'	'' "${RAMDISK_SIZE}"
printf '%-20s     Temp Dir:        %-40s \n'	'' "${TMPDIR}"
printf '%-20s     Log Directory:   %-40s \n'	'' "${logdir}"
printf '%-20s     HOSTNAME:        %-40s \n'	'' "${HOSTNAME}"
printf '%-20s     OS:              %-40s \n'	'' "${OSNAME}"
printf '%-20s     Version:         %-40s \n'	'' "${VERSION}"
printf '%-20s     Debug Level:     %d \n'	'' "${DEBUG_LEVEL}"

echo ''

# Ensure that the required binaries are present
if ! checkRequiredBins
then
	echo "Missing required binaries."
	exit 1

elif [ ! -f "${cluster_file}" ]
then
	echo "Cluster file: ${cluster_file} does not exists."
	exit 1

# Display user message
elif ! displayMessage "Creating log directory"
then
	echo "Failed to display user message"
	let status="${status} + 1"

elif [ ! -d "${logdir}" ] && ! mkdir -p "${logdir}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to create log directory: ${logdir}"
	let status="${status} + 1"

# Update the GitHub Repository
elif ! getRepository "${GITHUBPROJ}" "${GITHUBBRANCH}" "${GITHUBKEY}" "${REPODIR}" "${logdir}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to update repository: ${REPODIR}"
	let status="${status} + 1"

# Display user message
elif ! displayMessage "Validation GitHub Project"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Validate the files
elif [ ! -f "${versionfile}" ]
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to locate Project version file: ${versionfile}"
	let status="${status} + 1"

# Get the Joshua version
else
	joshua_version=$(cat "${versionfile}")
fi

if [ "${status}" -ne 0 ]
then
	:

# Display user message
elif ! displayMessage "Building Joshua Agent Ver: ${joshua_version}" 1
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Build the docker
elif ! WORKDIR="${logdir}/builddocker" "${REPODIR}/Docker/build_docker.sh" 1
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to build docker file"
	let status="${status} + 1"

# Display user message
elif ! displayMessage "Checking for Running Joshua Agent"
then
	echo "Failed to display user message"
	let status="${status} + 1"

else
	container_id=$(docker ps --format '{{.ID}} {{.Names}} {{.Image}}' | grep -e 'foundationdb/joshua-agent:' -e 'foundationdb__joshua-agent__' | awk '{ print $1 }')
	docker_status=$?

	if [ "${docker_status}" -ne 0 ]
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to get the container id of the running joshua agent"
		let status="${status} + 1"

	# Display user message
	elif [ -n "${container_id}" ] && ! displayMessage "Stopping Joshua Agent: ${container_id}"
	then
		echo "Failed to display user message"
		let status="${status} + 1"

	elif [ -n "${container_id}" ] && ! docker stop "${container_id}" &> "${logdir}/agent_stop.log"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to stop the currently running joshua agent with container id: ${containter_id}"
		let status="${status} + 1"

	# Display user message
	elif ! displayMessage "Provisioning work directory"
	then
		echo "Failed to display user message"
		let status="${status} + 1"

	# Unmount work directory or remove, if present and ramdisk enable
	elif [ -d "${WORKDIR}" ] && [ "${RAMDISK_ENABLE}" -gt 0 ] && (! sudo umount "${WORKDIR}" &> "${logdir}/ramdisk_unmount.log" && ! rmdir "${WORKDIR}" &> "${logdir}/ramdisk_rmdir.log" )
	then
		let timespent="${SECONDS}-${messagetime}"
		let status="${status} + 1"
		echo "... failed in ${timespent} seconds to unmount and remove ramdisk: ${WORKDIR}"

	# Delete work directory, if present
	elif [ -d "${WORKDIR}" ] && ! rm -rf "${WORKDIR}"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to delete existing work directory: ${WORKDIR}"
		let status="${status} + 1"

	elif [ ! -d "${WORKDIR}" ] && ! mkdir -p "${WORKDIR}"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to create work directory: ${WORKDIR}"
		let status="${status} + 1"

	elif [ "${RAMDISK_ENABLE}" -gt 0 ] && ! sudo mount -t tmpfs -o "size=${RAMDISK_SIZE}G" myramdisk "${WORKDIR}" &> "${logdir}/ramdisk_mount.log"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to create ramdisk in ${WORKDIR}"
		let status="${status} + 1"

	elif [ "${RAMDISK_ENABLE}" -gt 0 ] && ! sudo chmod 777 "${WORKDIR}"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to permission ramdisk directory: ${WORKDIR}"
		let status="${status} + 1"

	# Display user message
	elif ! displayMessage "Copying FoundationDB Cluster file"
	then
		echo "Failed to display user message"
		let status="${status} + 1"

	elif ! cp -f "${cluster_file}" "${WORKDIR}/fdb.cluster"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to copy cluster file"
		let status="${status} + 1"

	# Display user message
	elif ! displayMessage "Starting Joshua Agent Ver: ${joshua_version}" "${RUN_FOREGROUND}"
	then
		echo "Failed to display user message"
		let status="${status} + 1"

	elif [ "${RUN_FOREGROUND}" -le 0 ] && ! docker run -d --name "foundationdb__joshua-agent__${joshua_version}" "${DOCKER_ARGS[@]}" "foundationdb/joshua-agent:${joshua_version}"  &> "${logdir}/agent_start.log"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to start Joshua Agent ver: ${joshua_version}"
		let status="${status} + 1"

	elif [ "${RUN_FOREGROUND}" -gt 0 ] && ! docker run --name "foundationdb__joshua-agent__${joshua_version}" "${DOCKER_ARGS[@]}" "foundationdb/joshua-agent:${joshua_version}"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to start Joshua Agent ver: ${joshua_version}"
		let status="${status} + 1"

	# Display user message
	elif ! displayMessage "Removing log directory"
	then
		echo "Failed to display user message"
		let status="${status} + 1"

	elif [ -d "${logdir}" ] && ! rm -rf "${logdir}"
	then
		let timespent="${SECONDS}-${messagetime}"
		echo "... failed in ${timespent} seconds to remove log directory: ${logdir}"
		let status="${status} + 1"

	else
		# Determine the amount of transpired time
		let timespent="${SECONDS}-${messagetime}"
		printf "... done in %3d seconds\n" "${timespent}"
	fi
fi

if [ "${status}" -eq 0 ]
then
	echo ''
	printf '%-16s  Successfully initialized AWS Joshua node with %d agents in %d seconds.\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${AGENT_TOTAL}" "${SECONDS}"

else
	echo ''
	printf '%-16s  Failed to initialize AWS Joshua node for %d agents in %d seconds.\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${AGENT_TOTAL}" "${SECONDS}"

	if [ "${DEBUG_LEVEL}" -gt 0 ]
	then
		printf "%-16s  Please check log directory: %s\n"	"$(TZ=${TZ} date "+%F %H-%M-%S")" "${logdir}"
	else
		printf "%-16s  Set DEBUG_LEVEL to 1 to enable log directory: %s\n"	"$(TZ=${TZ} date "+%F %H-%M-%S")" "${logdir}"
	fi
fi

exit "${status}"
