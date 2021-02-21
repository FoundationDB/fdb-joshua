#!/bin/bash
######################################################
#
# Joshua WebApp Client
#
# This script will start, stop, list, and tail correctness packages
# submitted or to be submitted to the Joshua Web Application.
#
# Defines:
# REQUIREDBINS		Array of required binaries
# SCRIPTDIR			Directory location of the current script
# OSNAME			Name of current OS
# OSTYPE			Type of current OS (WIN | OSX | LINUX)
#
# Author: Alvin Moore
# Date:	 20-06-01
######################################################

# Defines
#
SCRIPTDIR=$( cd "${BASH_SOURCE[0]%\/*}" && pwd )
SCRIPTNAME="${BASH_SOURCE[0]##*\/}"
TZ="${TZ:-America/Los_Angeles}"
CWD=$(pwd)
OSNAME="$(uname -s)"
REQUIREDBINS=( 'which' 'curl' 'grep' 'cut' )
TMPDIR="${TMPDIR:-/tmp}"
STOPPED="${STOPPED:-0}"
SANITY="${SANITY:-0}"
FAILURES="${FAILURES:-50}"
MAX_RUNS="${MAX_RUNS:-100000}"
PRIORITY="${PRIORITY:-100}"
TIMEOUT="${TIMEOUT:-5400}"
USERSORT="${USERSORT:-0}"
JOBRAW="${JOBRAW:-0}"
JOBERRORS="${JOBERRORS:-0}"
JOBXML="${JOBXML:-0}"
JOBSIMPLE="${JOBSIMPLE:-0}"
DEBUG_LEVEL="${DEBUG_LEVEL:-0}"
VERSION='2.1'

function syntax()
{
	echo 'joshuaClient.ksh <action> [options]'
	echo "   Actions:"
	echo "     list:      List specified ensembles"
	echo "     start:     Submit and start an ensemble"
	echo "     stop:      Stop the specified ensemble(s)"
	echo "     tail:      Display results of the specified ensemble(s)"
	echo ""
	echo "   Required Environmental Variables:"
	echo "     JOSHUAURL: Url specifying the location of the Joshua WebApp"
	echo ""
	echo "   Environmental Variables:"
	echo "     STOPPED:   Stopped ensemble [default ${STOPPED}]"
	echo "     SANITY:    Sanity test ensemble [default ${SANITY}]"
	echo "     FAILURES:  Number of failures resulting in job termination [default ${FAILURES}]"
	echo "     MAX_RUNS:  Max number of runs for job [default ${MAX_RUNS}]"
	echo "     PRIORITY:  CPU time percent for job [default ${PRIORITY}]"
	echo "     TIMEOUT:   Seconds to wait for job completion [default ${TIMEOUT}]"
	echo "     USERNAME:  Username of ensemble owner"
	echo "     USERSORT:  Sort by username"
	echo "     JOBRAW:    Display test output only [default ${JOBRAW}]"
	echo "     JOBERRORS: Display errors only [default ${JOBERRORS}]"
	echo "     JOBXML:    Wrap raw output in <Trace> tags [default ${JOBXML}]"
	echo "     JOBSIMPLE: Filter unimported xml attributes and properties [default ${JOBSIMPLE}]"

	echo "   version: ${VERSION}"
	return 0
}

# Display syntax
if [ "$#" -lt 1 ] || [ "${1}" == '--help' ] || [ "${1}" == '-h' ] || [ -z "${JOSHUAURL}" ]
then
	syntax
	if [ -z "${JOSHUAURL}" ]; then
		echo 'JOSHUAURL environmental variable is not defined!'
	fi
	exit 1
fi

# Read the original arguments
action="${1}"
shift
arguments=()
while [ "${#}" -gt 0 ]; do
	arguments+=("${1}")
	shift
done

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

function ensembleList
{
	local status=0

	if [ "${#}" -gt 0 ] && ([ "${1}" == '--help' ] || [ "${1}" == '-h' ])
	then
		echo "${SCRIPTNAME} list <options>"
		echo "     STOPPED:  Stopped ensemble [default 0]"
		echo "     SANITY:   Sanity test ensemble [default 0]"
		echo "     USERNAME: List ensembles owned by specified username"
		echo "     USERSORT: Sort by username"
		let status="${status} + 1"
	else
		actionurl="${JOSHUAURL}/joblist?stopped=${STOPPED}&sanity=${SANITY}&usersort=${USERSORT}"
		# Add the user name, if specified
		if [ -n "${USERNAME}" ]; then
			actionurl+="&username=${USERNAME}"
		fi
		# Perform the action
		if ! curl "${actionurl}"; then
			let status="${status} + 1"
		fi
	fi
	return ${status}
}

function ensembleStop
{
	local status=0

	if ([ "${#}" -eq 0 ] && [ -z "${USERNAME}" ])    	|| \
		 ([ "${1}" == '--help' ] || [ "${1}" == '-h' ])	|| \
	 	 ([ "${2}" == '--help' ] || [ "${2}" == '-h' ])
	then
		echo "${SCRIPTNAME} stop [Ensemble Id]"
		echo "     Ensemble Id: Id of specified job ensemble"
		echo "     SANITY:      Sanity test ensemble [default 0]"
		echo "     USERNAME:    Stop ensembles owned by specified username"
		echo "  Note: Ensemble Id or USERNAME must be specified"
		let status="${status} + 1"
	else
		actionurl="${JOSHUAURL}/jobstop?sanity=${SANITY}"
		# Add the job id, if specified
		if [ "${#}" -gt 0 ]; then
			actionurl+="&id=${1}"
		fi
		# Add the user name, if specified
		if [ -n "${USERNAME}" ]; then
			actionurl+="&username=${USERNAME}"
		fi
		# Perform the action
		if ! curl "${actionurl}"; then
			let status="${status} + 1"
		fi
	fi
	return ${status}
}

function ensembleTail
{
	local status=0

	if ([ "${#}" -eq 0 ] && [ -z "${USERNAME}" ]) || \
		 ([ "${1}" == '--help' ] || [ "${1}" == '-h' ])
	then
		echo "${SCRIPTNAME} tail [Ensemble Id]"
		echo "     Ensemble Id: Id of specified job ensemble"
		echo "     USERNAME:    Display running ensembles owned by specified username"
		echo "     JOBRAW:      Display test output only [default ${JOBRAW}]"
		echo "     JOBERRORS:   Display errors only [default ${JOBERRORS}]"
		echo "     JOBXML:      Wrap raw output in <Trace> tags [default ${JOBXML}]"
		echo "     JOBSIMPLE:   Filter unimported xml attributes and properties [default ${JOBSIMPLE}]"
		echo "  Note: Ensemble Id or USERNAME must be specified"
		let status="${status} + 1"
	else
		actionurl="${JOSHUAURL}/jobtail?raw=${JOBRAW}&errorsonly=${JOBERRORS}&xml=${JOBXML}&simple=${JOBSIMPLE}"
		# Add the job id, if specified
		if [ "${#}" -gt 0 ]; then
			actionurl+="&id=${1}"
		fi
		# Add the user name, if specified
		if [ -n "${USERNAME}" ]; then
			actionurl+="&username=${USERNAME}"
		fi
		# Perform the action
		if ! curl "${actionurl}"; then
			let status="${status} + 1"
		fi
	fi
	return ${status}
}

function ensembleStart
{
	local status=0

	if [ "${#}" -lt 1 ]	|| [ "${1}" == '--help' ] || [ "${1}" == '-h' ]
	then
		echo "${SCRIPTNAME} start <correctness package>"
		echo "     SANITY:   Sanity test ensemble [default ${SANITY}]"
		echo "     FAILURES: Number of failures resulting in job termination [default ${FAILURES}]"
		echo "     MAX_RUNS: Max number of runs for job [default ${MAX_RUNS}]"
		echo "     PRIORITY: CPU time percent for job [default ${PRIORITY}]"
		echo "     TIMEOUT:  Seconds to wait for job completion [default ${TIMEOUT}]"
		echo "     USERNAME: Username of ensemble owner [default ${USER}]"
		echo "     ENSEMBLEISURL: Specified ensemble is a URL [default 0]"
		let status="${status} + 1"
	else
		local correctpkg="${1}"
		local cookie="${TMPDIR}/cookie-${$}.txt"
		local curlopts=('-L' '-k' "--cookie-jar" "${cookie}" "--cookie" "${cookie}")
		local USERNAME="${USERNAME:-$USER}"
		local ENSEMBLEISURL="${ENSEMBLEISURL:-0}"
		local postargs=('-F' "max_runs=${MAX_RUNS}" '-F' "fail_fast=${FAILURES}" '-F' "priority=${PRIORITY}" '-F' "timeout=${TIMEOUT}" '-F' "sanity=${SANITY}" '-F' "username=${USERNAME}")
		local ensembleurl

		if [ "${DEBUG_LEVEL}" -gt 1 ]
		then
			curlopts+=("-#")
		else
			curlopts+=('-s')
		fi

		# Define the location of the correctness package, if a url
		if [ "${ENSEMBLEISURL}" -gt 0 ]; then
			ensembleurl="${correctpkg}"
			correctpkg="${TMPDIR}/ensemble-${$}.tar.gz"
		fi

		if [ "${ENSEMBLEISURL}" -gt 0 ] && \
			 [ "${DEBUG_LEVEL}" -gt 0 ] && \
			 ! displayMessage "Downloading url: ${ensembleurl}"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		# Download the ensemble, if a url was specified
		elif [ "${ENSEMBLEISURL}" -gt 0 ] && \
			! curl "${curlopts[@]}" -o "${correctpkg}" "${ensembleurl}"
		then
			echo "Failed to download ensemble url: ${ensembleurl}"
			let status="${status} + 1"

		# Ensure that the correctness package is present
		elif [ ! -f "${correctpkg}" ]
		then
			echo "Missing correctness package: ${correctpkg}"
			let status="${status} + 1"

		elif [ "${DEBUG_LEVEL}" -gt 0 ] && \
				 ! displayMessage "Uploading ensemble: ${correctpkg##*\/}"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		# Post the correctness package
		elif ! curl "${curlopts[@]}" "${postargs[@]}" -F "file=@${correctpkg}" "${JOSHUAURL}/api/upload" | cat
		then
			echo "Failed to post the correctness package: ${correctpkg}"
			let status="${status} + 1"

		elif [ "${DEBUG_LEVEL}" -gt 0 ] && \
				 [ "${ENSEMBLEISURL}" -gt 0 ] && \
				! displayMessage "Deleting downloaded ensemble"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		elif [ "${ENSEMBLEISURL}" -gt 0 ] && \
				! rm -f "${correctpkg}"
		then
			echo "Failed to remove downloaded ensemble: ${correctpkg}"
			let status="${status} + 1"
		fi

		# Delete the cookie
		if [ -f "${cookie}" ] && ! rm -f "${cookie}"
		then
			echo "Failed to delete cookie file: ${cookie}"
			let status="${status} + 1"
		fi

		# Delete the downloaded package, if no debug
		if [ "${DEBUG_LEVEL}" -eq 0 ] && \
			 [ "${ENSEMBLEISURL}" -gt 0 ] && \
			 [ -f "${correctpkg}" ] && ! rm -f "${correctpkg}"
		then
			echo "Failed to delete downloaded correctness package: ${correctpkg}"
			let status="${status} + 1"
		fi
	fi
	return ${status}
}

# Initialize the variables
status=0
messagetime=0
messagecount=0

if [ "${DEBUG_LEVEL}" -gt 0 ]
then
	printf '%-16s  %-40s \n'		"$(TZ=${TZ} date '+%F %H-%M-%S')" "Joshua Client Action"
	printf '%-20s     Joshua Action:   %-40s \n'	'' "${action}"
	printf '%-20s     Joshua Args:     %-40s \n'	'' "${#arguments[@]}"
	printf '%-20s     Server Url:      %-40s \n'	'' "${JOSHUAURL}"
	printf '%-20s     Stopped Enabled: %-40s \n'	'' "${STOPPED}"
	printf '%-20s     Sanity Enabled:  %-40s \n'	'' "${SANITY}"
	printf '%-20s     Temp Dir:        %-40s \n'	'' "${TMPDIR}"
	printf '%-20s     OS:              %-40s \n'	'' "${OSNAME}"
	printf '%-20s     Version:         %-40s \n'	'' "${VERSION}"
	printf '%-20s     Debug Level:     %d \n'	'' "${DEBUG_LEVEL}"

	echo ''
fi

# Ensure that the required binaries are present
if ! checkRequiredBins
then
	echo "Missing required binaries."
	exit 1

# Process the list action
elif [ "${action}" == "list" ]; then
	if ! ensembleList "${arguments[@]}"; then
		let status="${status} + 1"
	fi

# Process the stop action
elif [ "${action}" == "stop" ]; then
	if ! ensembleStop "${arguments[@]}"; then
		let status="${status} + 1"
	fi

# Process the start action
elif [ "${action}" == "start" ]; then
	if ! ensembleStart "${arguments[@]}"; then
		let status="${status} + 1"
	fi

# Process the tail action
elif [ "${action}" == "tail" ]; then
	if ! ensembleTail "${arguments[@]}"; then
		let status="${status} + 1"
	fi

else
	syntax
	echo "Unsupported action: ${action}"
fi

if [ "${DEBUG_LEVEL}" -eq 0 ]
then
	:

elif [ "${status}" -eq 0 ]
then
	echo ''
	printf '%-16s  Successfully performed action: %s in %d seconds.\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${action}" "${SECONDS}"

else
	echo ''
	printf '%-16s  Failed to perform action: %s in %d seconds.\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${action}" "${SECONDS}"
fi

exit "${status}"
