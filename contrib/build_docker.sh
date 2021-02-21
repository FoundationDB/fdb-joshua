#!/bin/bash

# This script will clone this repository from github and build the Joshua
# agent docker image.

SCRIPTDIR=$( cd "${BASH_SOURCE[0]%\/*}" && pwd )
BRANCH='master'
CLONEARGS=( 'bash' '-c' )
CWD=$(pwd)
DEBUGLEVEL="${DEBUGLEVEL:-0}"
REQUIREDBINS=( 'ssh-agent' 'ssh-add' 'ssh' 'git' 'bash' 'docker' )
REVISION="${REVISION:-FETCH_HEAD}"
SOURCEURL="${SOURCEURL:-git@github.com:FoundationDB/fdb-joshua.git}"
SOURCEKEYNAME="${SOURCEKEYNAME:-joshua}"
SOURCEKEY="${SOURCEKEY:-${HOME}/.ssh/${SOURCEKEYNAME}}"
FETCHARGS=( 'git' 'init' '&&' 'git' 'remote' 'add' 'origin' "${SOURCEURL}" '&&' 'ssh-add' '-D' '&&' 'ssh-add' "${SOURCEKEY}" '&&' 'git' 'fetch' '&&' 'git' 'fetch' 'origin' )
FETCHARGSSUFFIX=( '&&' 'git' 'checkout' "${BRANCH}" )
TZ="${TZ:-America/Los_Angeles}"
USE_UMASK="${USE_UMASK:-0}"
VERSION='0.0.1'

if [ "$#" -lt 2 ] ; then
    echo "Usage: build_docker.sh <workdir> <logdir>"
    echo "   version: ${VERSION}"
    exit 1
fi


function displayMessage
{
	local status=0

	if [ "$#" -lt 1 ]
	then
		echo 'displayMessage <message>'
		let status="${status} + 1"
	else
		# Increment the message counter
		let messagecount="${messagecount} + 1"

		# Display successful message, if previous message
		if [ "${messagecount}" -gt 1 ]
		then
			# Determine the amount of transpired time
			let timespent="${SECONDS}-${messagetime}"

			printf '... done in %3d seconds\n' "${timespent}"
		fi

		# Display message
		printf '%-16s      %-35s ' "$(TZ=${TZ} date '+%F %H-%M-%S')" "$1"

		# Update the variables
		messagetime="${SECONDS}"
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
		printf 'Unable to build solution without %d required binaries' "${#errors[@]}"
		printf '\n    %s' "${errors[@]}"
		echo ''
	fi

	return "${status}"
}

# Read the command line arguments
workdir="${1}"
logdir="${2}"

if [ -d "${workdir}" ]
then
    echo "Work directory ${workdir} exists"
    exit 1

# Ensure that the work directory is created
elif ! mkdir -p "${workdir}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to create work directory: ${workdir}"
	exit 1

# Ensure that the log directory is created
elif [ ! -d "${logdir}" ] && ! mkdir -p "${logdir}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to create log directory: ${logdir}"
	exit 1
fi

logdir=$( cd "${logdir}" && pwd )
workdir=$( cd "${workdir}" && pwd )


# Initialize the variables
status=0
messagetime=0
messagecount=0

# Add the remaining fetch arguments
FETCHARGS+=( "${BRANCH}" "${FETCHARGSSUFFIX[@]}" )

printf '%-16s  %-40s \n'		"$(TZ=${TZ} date '+%F %H-%M-%S')" "Fetching Joshua source"
printf '%-20s     SC Repo:      %-40s \n'	'' "${SOURCEURL}"
printf '%-20s     Work:         %-40s \n'	'' "${workdir}"
printf '%-20s     Logs:         %-40s \n'	'' "${logdir}"
printf '%-20s     umask Id:     %-40s \n'	'' "${umaskid}"
printf '%-20s     Use umask:    %-40s \n'	'' "${USE_UMASK}"
printf '%-20s     Version:      %-40s \n'	'' "${VERSION}"

if [ "${DEBUGLEVEL}" -gt 1 ]; then printf '%-20s     Ssh Key:   %-40s \n'	'' "${SOURCEKEY}"; fi

# Display the arguments, if debug
if [ "${DEBUGLEVEL}" -gt 2 ]; then printf '%-20s     Fetch:     %-40s \n'	'' "${FETCHARGS[*]}"; fi

echo ''


# Ensure that the key file is present
if [ ! -f "${SOURCEKEY}" ]
then
	echo "Missing repository key file: ${SOURCEKEY}"
	exit 1

# Ensure that the required binaries are present
elif ! checkRequiredBins
then
	echo "Missing required binaries."
	exit 1

# Display user message
elif [ "${USE_UMASK}" -gt 0 ] && ! displayMessage 'Setting new file perms'
then
	echo 'Failed to display user message'
	let status="${status} + 1"

# Display user message
elif [ "${USE_UMASK}" -gt 0 ] && ! umask 0000 > /dev/null
then
	echo "... failed to set umask: 0000"
	let status="${status} + 1"

# Display user message
elif ! displayMessage 'Create work directories'
then
	echo 'Failed to display user message'
	let status="${status} + 1"

# Change to workdir
elif ! cd "${workdir}"
then
    echo "Failed to change to work dir: ${workdir}"
    let status="${status} + 1"

# Clone the source
elif ! displayMessage "Clone source"
then
	echo 'Failed to display user message'
	let status="${status} + 1"

elif [ ! -d ".git" ] && ! ssh-agent "${CLONEARGS[@]}" "${FETCHARGS[*]}" &> "${logdir}/joshua_source_clone.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds"
	echo "CLONEARGS: ${CLONEARGS[*]}"
	echo "FETCHARGS: ${FETCHARGS[*]}"
	let status="${status} + 1"

# Build the docker image
elif ! displayMessage "Build docker image"
then
	echo 'Failed to display user message'
	let status="${status} + 1"
elif ! ./Docker/build_docker.sh &> "${logdir}/build_docker.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds"
	let status="${status} + 1"

fi


if [ "${status}" -eq 0 ]
then
	echo ''
	printf '%-16s  Successfully cloned, built in %d seconds.\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${SECONDS}"

else
	echo ''
	printf '%-16s  Failed to complete clone and build process. Please check log directory: %s\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${logdir}"
fi

exit "${status}"
