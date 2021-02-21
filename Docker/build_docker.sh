#!/bin/bash
######################################################
#
# Joshua Agent Docker Image Build Script
#
# This script will build the joshua agent docker image
# from the source repository.
#
# Defines:
# REQUIREDBINS		Array of required binaries
# SCRIPTDIR			Directory location of the current script
# OSNAME			Name of current OS
#
# Author: Alvin Moore
# Date:	 20-07-01
######################################################

# Defines
#
SCRIPTDIR=$( cd "${BASH_SOURCE[0]%\/*}" && pwd )
PROJECTDIR=$( cd "${SCRIPTDIR%\/*}" && pwd )
SCRIPTNAME="${BASH_SOURCE[0]##*\/}"
TZ="${TZ:-America/Los_Angeles}"
CWD=$(pwd)
OSNAME="$(uname -s)"
REQUIREDBINS=( 'which' 'curl' 'grep' 'cut' 'rsync' 'git' 'docker' )
PROJECTVER=$(cat "${PROJECTDIR}/version.txt")
IMAGENAME="${IMAGENAME:-foundationdb/joshua-agent}"
IMAGEVER="${IMAGEVER:-${PROJECTVER}}"
TMPDIR="${TMPDIR:-/tmp}"
WORKDIR="${WORKDIR:-${TMPDIR}/builddocker_${$}}"
UPDATE_REPO="${UPDATE_REPO:-0}"
DEBUG_LEVEL="${DEBUG_LEVEL:-0}"
VERSION="2.0"

function syntax()
{
	echo 'build_docker.sh <process 0|1>'
	echo "   Environmental Variables:"
	echo "     IMAGENAME:   Name of the docker image [default ${IMAGENAME}]"
	echo "     IMAGEVER:    Version fo the docker image [default ${PROJECTVER}]"
	echo "     UPDATE_REPO: Update git repository first [default: ${UPDATE_REPO}]"
	echo "     TMPDIR:      Location of temp directory [default ${TMPDIR}]"
	echo "     WORKDIR:     Work directory to perform build [default ${WORKDIR}]"
	echo "   version: ${VERSION}"
	return 0
}

# Display syntax
if [ "$#" -lt 1 ] || [ "${1}" == '--help' ] || [ "${1}" == '-h' ]
then
	syntax
	exit 1
fi

# Delete the work directory on exit
if [ "${DEBUG_LEVEL}" -eq 0 ]; then
	trap "rm -rf ${WORKDIR}" EXIT
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
		printf 'Unable to run script without %d required binaries' "${#errors[@]}"
		printf '\n    %s' "${errors[@]}"
		echo ''
	fi

	return "${status}"
}

# Initialize the variables
status=0
messagetime=0
messagecount=0
logdir="${WORKDIR}/logs"
installdir="${WORKDIR}/install"

printf '%-16s  %-40s \n'		"$(TZ=${TZ} date '+%F %H-%M-%S')" "Joshua Build and Deployer"
printf '%-20s     Image Name:      %-40s \n'	'' "${IMAGENAME}"
printf '%-20s     Image Version:   %-40s \n'	'' "${IMAGEVER}"
printf '%-20s     Update Repo:     %d \n'	'' "${UPDATE_REPO}"
printf '%-20s     Project Dir:     %-40s \n'	'' "${PROJECTDIR}"
printf '%-20s     Docker Dir:      %-40s \n'	'' "${SCRIPTDIR}"
printf '%-20s     Work Dir:        %-40s \n'	'' "${WORKDIR}"
printf '%-20s     Install Dir:     %-40s \n'	'' "${installdir}"
printf '%-20s     Log Dir:         %-40s \n'	'' "${logdir}"
printf '%-20s     Temp Dir:        %-40s \n'	'' "${TMPDIR}"
printf '%-20s     OS:              %-40s \n'	'' "${OSNAME}"
printf '%-20s     Version:         %-40s \n'	'' "${VERSION}"
printf '%-20s     Debug Level:     %d \n'	'' "${DEBUG_LEVEL}"

echo ''

# Ensure that the Dockerfile is present
if [ ! -f "${SCRIPTDIR}/Dockerfile" ]
then
	echo "Missing Dockerfile: ${SCRIPTDIR}/Dockerfile"
	exit 1

elif [ ! -f "${PROJECTDIR}/version.txt" ]
then
	echo "Missing version file: ${WORKDIR}/version.txt"
	exit 1

# Ensure that the required binaries are present
elif ! checkRequiredBins
then
	echo "Missing required binaries."
	exit 1

# Display user message
elif [ "${UPDATE_REPO}" -gt 0 ] && ! displayMessage "Updating git repository"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Move to project directory
elif [ "${UPDATE_REPO}" -gt 0 ] && ! cd "${PROJECTDIR}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to move to project dir: ${PROJECTDIR}"
	let status="${status} + 1"

# Update the git repository
elif [ "${UPDATE_REPO}" -gt 0 ] && ! git pull &> "${logdir}/git_pull.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to update git repository"
	let status="${status} + 1"

# Display user message
elif ! displayMessage "Create work directories"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Remove existing work directory, if present
elif [ -d "${WORKDIR}" ] && ! rm -rf "${WORKDIR}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to remove existing work directory: ${WORKDIR}"
	let status="${status} + 1"

# Create work directory, if not present
elif [ ! -d "${WORKDIR}" ] && ! mkdir -p "${WORKDIR}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to create work directory: ${WORKDIR}"
	let status="${status} + 1"

# Create logs directory, if not present
elif [ ! -d "${logdir}" ] && ! mkdir -p "${logdir}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to create logs directory: ${logdir}"
	let status="${status} + 1"

# Display user message
elif ! displayMessage "Populate work directories"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Copy script directory to work directory, if present
elif ! rsync -arv "${SCRIPTDIR}/" "${WORKDIR}/" &> "${logdir}/copy_scriptdir.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to copy script directory: ${SCRIPTDIR} to work dir: ${WORKDIR}"
	let status="${status} + 1"

# Copy childreaper directory to work directory, if present
elif ! rsync -arv "${PROJECTDIR}/childsubreaper" "${installdir}/" &> "${logdir}/copy_childreaperdir.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to copy childreaper directory: ${PROJECTDIR}/childsubreaper to work dir: ${installdir}"
	let status="${status} + 1"

# Copy joshua directory to work directory, if present
elif ! rsync -ar "${PROJECTDIR}/joshua" "${installdir}/" &> "${logdir}/copy_joshuadir.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to copy joshua directory: ${PROJECTDIR}/joshua to work dir: ${installdir}"
	let status="${status} + 1"

# Copy setup script to work directory, if present
elif ! rsync -ar "${PROJECTDIR}/setup.py" "${installdir}/" &> "${logdir}/copy_setup.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to copy setup script: ${PROJECTDIR}/setup.py to work dir: ${installdir}"
	let status="${status} + 1"

# Display user message
elif ! displayMessage 'Testing docker'
then
	echo 'Failed to display user message'
	let status="${status} + 1"

# Testing the docker daemon
elif ! docker info &> "${logdir}/docker_test.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to test docker daemon: ${docker_file}"
	echo "Please ensure that the docker daemon is running."
	let status="${status} + 1"

# Display user message
elif ! displayMessage "Building docker image"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Build docker image
elif ! docker build --build-arg DOCKER_IMAGEVER="${IMAGEVER}" --network host -t "${IMAGENAME}:${IMAGEVER}" -t "${IMAGENAME}:latest" -f "${WORKDIR}/Dockerfile" "${WORKDIR}" &> "${logdir}/docker_build.log"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to build docker image: ${IMAGENAME}:${IMAGEVER}"
	let status="${status} + 1"

# Display user message
elif ! displayMessage "Removing work directories"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Remove existing work directory, if present
elif [ -d "${WORKDIR}" ] && ! rm -rf "${WORKDIR}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to remove work directory: ${WORKDIR}"
	let status="${status} + 1"

else
	# Determine the amount of transpired time
	let timespent="${SECONDS}-${messagetime}"
	printf "... done in %3d seconds\n" "${timespent}"
fi

if [ "${status}" -eq 0 ]
then
	echo ''
	printf '%-16s  Successfully built docker: %s:%s in %d seconds.\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${IMAGENAME}" "${IMAGEVER}" "${SECONDS}"

else
	echo ''
	printf '%-16s  Failed to build docker: %s:%s in %d seconds.\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${IMAGENAME}" "${IMAGEVER}" "${SECONDS}"

	if [ "${DEBUG_LEVEL}" -gt 0 ]
	then
		printf "%-16s  Please check log directory: %s\n"	"$(TZ=${TZ} date "+%F %H-%M-%S")" "${logdir}"
	else
		printf "%-16s  Set DEBUG_LEVEL to 1 to enable log directory: %s\n"	"$(TZ=${TZ} date "+%F %H-%M-%S")" "${logdir}"
	fi
fi

exit "${status}"
