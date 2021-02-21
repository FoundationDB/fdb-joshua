#!/bin/bash
######################################################
#
# Generice Service Script
#
# This script will ensure that the a service script
# is always running and stores each run log in a log
# directory.
#
# Defines:
# REQUIREDBINS		Array of required binaries
# SCRIPTDIR			Directory location of the current script
# OSNAME			Name of current OS
# OSTYPE			Type of current OS (WIN | OSX | LINUX)
#
# Author: Alvin Moore
# Date:	 20-08-08
######################################################

# Defines
#
SCRIPTDIR=$( cd "${BASH_SOURCE[0]%\/*}" && pwd )
SCRIPTNAME="${BASH_SOURCE[0]##*\/}"
TZ="${TZ:-America/Los_Angeles}"
CWD=$(pwd)
OSNAME="$(uname -s)"
HOSTNAME="${HOSTNAME:-$(hostname)}"
REQUIREDBINS=('which' 'grep' 'awk' 'sed' 'git')
TMPDIR="${TMPDIR:-/tmp}"
SERVICENAME="${SERVICENAME:-service}"
SERVICEDIR="${SERVICEDIR:-${TMPDIR}/${SERVICENAME}}"
STOPFILE="${STOPFILE:-${SERVICEDIR}/${SERVICENAME}.stop}"
CFGFILE="${CFGFILE:-${SERVICEDIR}/${SERVICENAME}.conf}"
LOGDIR="${LOGDIR:-${HOME}/logs/${SERVICENAME}}"
WAITAMOUNT="${WAITAMOUNT:-30}"
UPDATEREPO="${UPDATEREPO:-0}"
REPODIR="${REPODIR:-${HOME}/repos/${SERVICENAME}}"
GITHUBPROJ="${GITHUBPROJ:-git@github.com:FoundationDB/fdb-joshua.git}"
GITHUBBRANCH="${GITHUBBRANCH:-master}"
GITHUBKEYNAME="${GITHUBKEYNAME:-id_rsa}"
GITHUBKEY="${GITHUBKEY:-${HOME}/.ssh/${GITHUBKEYNAME}}"
DEBUG_LEVEL="${DEBUG_LEVEL:-0}"
VERSION='1.18'

function syntax()
{
	echo 'serviceScript.ksh <service script> [script arg #1] [script arg #2] ...'
	echo "   Environmental Variables:"
	echo "     SERVICENAME:    Name of the service [default ${SERVICENAME}]"
	echo "     SERVICEDIR:     Work directory for the service [default ${SERVICEDIR}]"
	echo "     STOPFILE:       Service stop file [default ${STOPFILE}]"
	echo "     CFGFILE:        Application config file [default ${CFGFILE}]"
	echo "     LOGDIR:         Log directory for the application [default ${LOGDIR}]"
	echo "     WAITAMOUNT:     Number of seconds to wait between runs [default ${WAITAMOUNT}]"
	echo "     UPDATEREPO:     Update GitHub repository directory [default ${UPDATE_REPO}]"
	echo "     REPODIR:        Repository directory [default ${REPODIR}]"
	echo "     GITHUBPROJ:     GitHub project [default ${GITHUBPROJ}]"
	echo "     GITHUBBRANCH:   GitHub project branch [default ${GITHUBBRANCH}]"
	echo "     GITHUBKEY:      GitHub project ssh key [default ${GITHUBKEY}]"

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
application_script="${1}"
shift
application_args=()
while [ "${#}" -gt 0 ]
do
	application_args+=("${1}")
	shift
done

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
		printf "%-16s  %-30s " "$(TZ=${TZ} date "+%F %H-%M-%S")" "$1"

		# Update the variables
		messagetime="${SECONDS}"

		# Add newline, if requested
		if [ "${addnewline}" -gt 0 ]; then messagecount=0; echo ''; fi
	fi

	return "${status}"
}

# The following function will verify that the specified
# binaries are present on the systems
function checkRequiredBins
{
	local status=0

	if [ "$#" -lt 1 ]
	then
		echo "checkRequiredBins <executable #1> [executable #2] ..."
		let status="${status} + 1"
	else
		local errors=()
		local binary

		# Ensure that the required binaries are present
		for binary in "${@}"
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
			printf 'Missing %d required binaries' "${#errors[@]}"
			printf '\n    %s' "${errors[@]}"
			echo ''
		fi
	fi

	return "${status}"
}

# The following function will verify that the specified
# variables are currently defined
function checkRequiredVars
{
	local status=0

	if [ "$#" -lt 1 ]
	then
		echo "checkRequiredVars <variable #1> [variable #2] ..."
		let status="${status} + 1"
	else
		local errors=()
		local variable

		# Ensure that the required variable are defined
		for variable in "${@}"
		do
			# Ensure that the binary is in the path or is the full path
			if [ ! -z "${!variable}" ]
			then
				# Store the missing variable
				errors+=("${variable}")

				# Increment the error counter
				let status="${status} + 1"
			fi
		done

		# Report on the missing required binaries, if any
		if [ "${#errors[@]}" -gt 0 ]
		then
			printf 'Missing %d required variable' "${#errors[@]}"
			printf '\n    %s' "${errors[@]}"
			echo ''
		fi
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

# Attempt to load application configuration file
if [ -f "${CFGFILE}" ]  && ! . "${CFGFILE}"
then
	echo "Failed to load application config: ${CFGFILE}"
	exit 1
fi

printf '%-16s  %-40s \n'		"$(TZ=${TZ} date '+%F %H-%M-%S')" "${SERVICENAME} Service Script"
printf '%-20s     Service:          %-40s \n'	'' "${SERVICENAME}"
printf '%-20s     App Script:       %-40s \n'	'' "${application_script}"
printf '%-20s     Service Args:     (%d) %-40s \n'	'' "${#application_args[@]}" "${application_args[*]}"
printf '%-20s     Service Dir:      %-40s \n'	'' "${SERVICEDIR}"
printf '%-20s     Service Stopfile: %-40s \n'	'' "${STOPFILE}"
printf '%-20s     Config file:      %-40s \n'	'' "${CFGFILE}"
printf '%-20s     Log Directory:    %-40s \n'	'' "${LOGDIR}"
printf '%-20s     Update Repo:      %-40s \n'	'' "${UPDATEREPO}"
if [ "${UPDATEREPO}" -gt 0 ]
then
	printf '%-20s     Repository Dir:   %-40s \n'	'' "${REPODIR}"
	printf '%-20s     GitHub Project:   %-40s \n'	'' "${GITHUBPROJ}"
	printf '%-20s     GitHub Branch:    %-40s \n'	'' "${GITHUBBRANCH}"
	printf '%-20s     GitHub SSH Key:   %-40s \n'	'' "${GITHUBKEY}"
fi
printf '%-20s     Temp Dir:         %-40s \n'	'' "${TMPDIR}"
printf '%-20s     Hostname:         %-40s \n'	'' "${HOSTNAME}"
printf '%-20s     OS:               %-40s \n'	'' "${OSNAME}"
printf '%-20s     Version:          %-40s \n'	'' "${VERSION}"
printf '%-20s     Debug Level:      %d \n'	'' "${DEBUG_LEVEL}"

echo ''

# Ensure that the required binaries are present
if ! checkRequiredBins "${REQUIREDBINS[@]}"
then
	echo "Missing required binaries."
	let status="${status} + 1"

elif [ "${UPDATEREPO}" -gt 0 ] && [ ! -f "${GITHUBKEY}" ]
then
	echo "Unable to update repository while missing GitHub key: ${GITHUBKEY}."
	let status="${status} + 1"

# Display user message
elif ! displayMessage "Creating directories"
then
	echo "Failed to display user message"
	let status="${status} + 1"

elif [ ! -d "${SERVICEDIR}" ] && ! mkdir -p "${SERVICEDIR}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to create work directory: ${SERVICEDIR}"
	let status="${status} + 1"

elif [ ! -d "${LOGDIR}" ] && ! mkdir -p "${LOGDIR}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to create service log directory: ${LOGDIR}"
	let status="${status} + 1"

# Display user message
elif [ -f "${STOPFILE}" ] && ! displayMessage "Removing Existing StopFile"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Remove the stopfile, if present
elif [ -f "${STOPFILE}" ] && ! rm -f "${STOPFILE}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to remove existing stop file: ${STOPFILE}"
	let status="${status} + 1"

# Display user message
elif ! displayMessage "Running Service ${SERVICENAME}" 1
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Run the service
else
	servicestart="${SECONDS}"
	cycles=0
	passed=0
	failed=0

	while [ ! -f "${STOPFILE}" ]
	do
		let cycles="${cycles} + 1"
		date="$(date '+%F_%H-%M-%S')"
		datesubdir="$(date '+%Y-%m')"
		servicelogdir="${LOGDIR}/service/${datesubdir}"
		logfilebase="${SERVICENAME}-${date}.log"
		logfile="${servicelogdir}/${logfilebase}"
		linkfile="${LOGDIR}/service/${SERVICENAME}.log"
		envfile="${servicelogdir}/${SERVICENAME}.env"
		messagetime="${SECONDS}"
		messagecount=0
		runservice=0

		printf '%-16s Cycle #%4d:\n' "$(date '+%F %H-%M-%S')" "${cycles}"

		# Create the service log directory
		if [ ! -d "${servicelogdir}" ] && ! mkdir -p "${servicelogdir}"
		then
			echo "Failed to create service log directory: ${servicelogdir}"
			let status="${status} + 1"
			break

		# Display user message
		elif [ -f "${CFGFILE}" ]  && ! displayMessage "Loading Config: ${CFGFILE##*\/}"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		# Load the application configuration file, if present
		elif [ -f "${CFGFILE}" ]  && ! . "${CFGFILE}"
		then
			let timespent="${SECONDS}-${messagetime}"
			echo "... failed in ${timespent} seconds load config: ${CFGFILE}"
			let status="${status} + 1"

		# Update/Install the repository files
		elif [ "${UPDATEREPO}" -gt 0 ] && ! getRepository "${GITHUBPROJ}" "${GITHUBBRANCH}" "${GITHUBKEY}" "${REPODIR}" "${logdir}"
		then
			let timespent="${SECONDS}-${messagetime}"
			echo "... failed in ${timespent} seconds to update repo: ${REPODIR}"
			let status="${status} + 1"

		# Display user message
		elif ! displayMessage "Validating Script: ${application_script##*\/}"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		elif [ ! -f "${application_script}" ]
		then
			echo "application script does not exist: ${application_script}"
			let status="${status} + 1"

		elif [ ! -x "${application_script}" ]
		then
			echo "application script is not executable: ${application_script}"
			let status="${status} + 1"

		# Update the current log link
		elif ! rm -f "${linkfile}" || ! ln -s "${datesubdir}/${logfilebase}" "${linkfile}"
		then
			echo "failed to link logfile: ${linkfile} to ${logfilebase}"
			let status="${status} + 1"

		# Create service directory, if not present
		elif [ ! -d "${SERVICEDIR}" ] && ! mkdir -p "${SERVICEDIR}"
		then
			let timespent="${SECONDS}-${messagetime}"
			echo "... failed in ${timespent} seconds to create work directory: ${SERVICEDIR}"
			let status="${status} + 1"

		# Move to service directory
		elif ! cd "${SERVICEDIR}"
		then
			echo "failed to move to service directory: ${SERVICEDIR}"
			let status="${status} + 1"

		# Display user message
		elif ! displayMessage "Logging ${SERVICENAME} to ${logfile}" 1
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		# Run the service scriptwith the environmental file, if defined
		elif [ -f "${CFGFILE}" ]
		then
			bash -ac "source '${CFGFILE}'; env > '${envfile}'; '${application_script}' ${application_args[*]} &> '${logfile}'"
			result_code="${?}"
			let runservice="${runservice}+1"

		# Otherwise, just run the service
		else
			env > '${envfile}'
			"${application_script}" "${application_args[@]}" &> "${logfile}"
			result_code="${?}"
			let runservice="${runservice}+1"
		fi

		# Do nothing, if service was not run
		if [ "${runservice}" -le 0 ]
		then
			:
		elif [ "${result_code}" -eq 0 ]
		then
			let timespent="${SECONDS}-${messagetime}"
			let passed="${passed} + 1"
			echo "... (${result_code}) passed after ${timespent} seconds."
		else
			let timespent="${SECONDS}-${messagetime}"
			let failed="${failed} + 1"
			echo "... (${result_code}) failed after ${timespent} seconds."
		fi

		messagecount=0

		# Do nothing, if stopfile is present
		if [ -f "${STOPFILE}" ]
		then
			:
		# Display user message
		elif ! displayMessage "Pausing ${WAITAMOUNT} seconds"
		then
			echo "Failed to display user message"
			let status="${status} + 1"

		elif ! sleep "${WAITAMOUNT}"
		then
			echo "failed to complete sleep"
			let status="${status} + 1"
		else
			let timespent="${SECONDS}-${messagetime}"
			echo "... done in ${timespent} seconds"
		fi
	done

	# Calculate the amount of time spent
	let timespent="${SECONDS}-${messagetime}"

	# Display report
	printf '\n%-16s Stop file found after %d cycles and %d seconds.\n' "$(date '+%F %H-%M-%S')" "${cycles}" "${timespent}"
	printf '%-16s Passed:%4d  Failed: %4d   Total:%4d\n' "" "${passed}" "${failed}" "${cycles}"
fi

if [ "${status}" -ne 0 ]
then
	echo ''
	printf '%-16s  Failed to start %s service after %d seconds.\n'	"$(TZ=${TZ} date '+%F %H-%M-%S')" "${SERVICENAME}" "${SECONDS}"
fi

exit "${status}"
