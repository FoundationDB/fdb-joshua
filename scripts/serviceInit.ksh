#!/bin/bash
######################################################
#
# Service Initialization Script
#
# This script will initialize a service to run
# on a machine loading its application and service
# configuration file.
# This script is used to facilitate the service to run
# via init.d
#
# Defines:
# REQUIREDBINS		Array of required binaries
# SCRIPTDIR			Directory location of the current script
# OSNAME			Name of current OS
#
# Author: Alvin Moore
# Date:	 20-08-25
######################################################

# Defines
#
PROJNAME='awstools'
SCRIPTDIR=$( cd "${BASH_SOURCE[0]%\/*}" && pwd )
REQUIREDBINS=('which' 'date' 'nohup' 'env' 'git' 'ssh-add' 'ssh-agent')
SERVICEVARS=('SERVICECFG' 'SERVICESTARTER' 'SERVICESCRIPT')
SHAREDIR="${SHAREDIR:-/usr/local/share/${PROJNAME}}"
SERVICESTARTER="${SERVICESTARTER:-${SHAREDIR}/sbin/serviceScript.ksh}"
CFGDIR="${CFGDIR:-/etc/${PROJNAME}}"
LOGDIR="${LOGDIR:-/var/log/${PROJNAME}/${SERVICENAME}}"
SERVICEDIR="${SERVICEDIR:-/var/lib/${PROJNAME}/${SERVICENAME}}"
CFGFILE="${CFGFILE:-${CFGDIR}/${SERVICENAME}.conf}"
SERVICESRVCFG="${CFGDIR}/${SERVICENAME}service.conf"
SERVICECFG="${CFGDIR}/${SERVICENAME}.conf"
UPDATEREPO="${UPDATEREPO:-1}"
DRYRUN="${DRYRUN:-0}"
DEBUG_LEVEL="${DEBUG_LEVEL:-0}"
VERSION='1.11'

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
			if [ -z "${!variable}" ]
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

function syntax()
{
	echo 'serviceInit.ksh <process 0|1>'
	echo "   Environmental Variables:"
	echo "     SERVICENAME:    Name of the application service (required) [default ${SERVICENAME}]"
	echo "     LOGDIR:         Log directory for the service [default ${LOGDIR}]"
	echo "     CFGDIR:         Configuration directory for the service [default ${CFGDIR}]"
	echo "     SERVICESRVCFG:  Location of the appliation service config [default ${SERVICESRVCFG}]"
	echo "     DRYRUN:         Don't start the service [default ${DRYRUN}]"
	echo "   Service Configuration Variables: (required)"
	echo "     SERVICECFG:     Application config [default ${SERVICECFG}]"
	echo "     SERVICESCRIPT:  Name of the service script"
	echo "     UPDATEREPO:     Update service repository [default ${UPDATEREPO}]"
	echo "     REPODIR:        Repository directory"
	echo "     GITHUBPROJ:     GitHub project"
	echo "     GITHUBBRANCH:   GitHub project branch"
	echo "     GITHUBKEY:      GitHub project ssh key"
	echo "   version: ${VERSION}"
	return 0
}

# Display syntax
if [ "$#" -lt 1 ] || [ "${1}" != '1' ] || [ "${1}" == '--help' ] || [ "${1}" == '-h' ]
then
	syntax
	exit 1

# Ensure that SERVICENAME is defined
elif [ -z "${SERVICENAME}" ]
then
	echo 'The environmental variable SERVICENAME must be defined.'
	exit 1
fi

# Initialize the variables
status=0
date="$(date '+%F_%H-%M-%S')"
datesubdir="$(date '+%Y-%m')"
logdir="${LOGDIR}/cron/${datesubdir}"
linkfile="${LOGDIR}/cron/${SERVICENAME}.log"
logfilebase="${SERVICENAME}-${date}.log"
logfile="${logdir}/${logfilebase}"

printf '%-16s  Starting %s Service\n'		"$(date '+%F %H-%M-%S')" "${SERVICENAME}"
printf '%-20s     Service Name:     %-40s \n'	'' "${SERVICENAME}"
printf '%-20s     Config Directory: %-40s \n'	'' "${CFGDIR}"
printf '%-20s     Applicaiton Cfg:  %-40s \n'	'' "${SERVICECFG}"
printf '%-20s     Service Cfg:      %-40s \n'	'' "${SERVICESRVCFG}"
printf '%-20s     Log Directory:    %-40s \n'	'' "${logdir}"
printf '%-20s     Dry Run:          %-40s \n'	'' "${DRYRUN}"
printf '%-20s     Update Repo:      %-40s \n'	'' "${UPDATEREPO}"
printf '%-20s     Hostname:         %-40s \n'	'' "${HOSTNAME}"
printf '%-20s     OS:               %-40s \n'	'' "${OSNAME}"
printf '%-20s     Version:          %-40s \n'	'' "${VERSION}"
printf '%-20s     Debug Level:      %d \n'	'' "${DEBUG_LEVEL}"
echo ''

# Ensure that the required binaries are present
if ! checkRequiredBins "${REQUIREDBINS}"
then
	echo "Missing required binaries."
	let status="${status}+1"

# Ensure that the service configuration is present
elif [ ! -f "${SERVICESRVCFG}" ]
then
	echo "Missing ${SERVICENAME} service config: ${SERVICESRVCFG}"
	let status="${status}+1"

# Create the service log directory, if not present
elif [ ! -d "${logdir}" ] && ! mkdir -p "${logdir}"
then
	echo "Failed to create service log directory: ${logdir}"
	let status="${status}+1"

# Load the service configuration variables
elif ! . "${SERVICESRVCFG}"
then
	echo "Failed to load ${SERVICENAME} service config: ${SERVICESRVCFG}"
	let status="${status}+1"

# Add the repository variables to the list of variables
# to be validated, if updating the service repository
elif [ "${UPDATEREPO}" -gt 0 ]
then
	SERVICEVARS+=('REPODIR' 'GITHUBPROJ' 'GITHUBBRANCH' 'GITHUBKEY')
fi

# Do nothing, if in error
if [ "${status}" -ne  0 ]
then
	:

# Ensure that the required binaries are present
elif ! checkRequiredVars "${SERVICEVARS[@]}"
then
	echo "Unable to run while missing required variables."
	let status="${status}+1"

# Update the GitHub Repository
elif [ "${UPDATEREPO}" -gt 0 ] && ! getRepository "${GITHUBPROJ}" "${GITHUBBRANCH}" "${GITHUBKEY}" "${REPODIR}" "${logdir}"
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... failed in ${timespent} seconds to update repository: ${REPODIR}"
	let status="${status} + 1"

elif ! displayMessage "Validating Files"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Ensure that the configuration file is present
elif [ ! -f "${SERVICECFG}" ]
then
	echo "Missing ${SERVICENAME} application config: ${SERVICECFG}"
	let status="${status}+1"

# Ensure that the service starter script is present
elif [ ! -f "${SERVICESTARTER}" ]
then
	echo "Missing service script: ${SERVICESTARTER}"
	let status="${status}+1"

# Ensure that the service starter script is executable
elif [ ! -x "${SERVICESTARTER}" ]
then
	echo "Service starter script: ${SERVICESTARTER} is not executable"
	let status="${status}+1"

# Ensure that service script is present
elif [ ! -f "${SERVICESCRIPT}" ]
then
	echo "Missing ${SERVICENAME} service script: ${SERVICESCRIPT}"
	let status="${status}+1"

# Ensure that service script is executable
elif [ ! -x "${SERVICESCRIPT}" ]
then
	echo "${SERVICENAME} service script: ${SERVICESCRIPT} is not executable"
	let status="${status}+1"

# Do nothing, if a dry run
elif [ "${DRYRUN}" -gt 0 ]
then
	:

elif ! displayMessage "Starting ${SERVICENAME} Service"
then
	echo "Failed to display user message"
	let status="${status} + 1"

# Update the current log link
elif ! rm -f "${linkfile}" || ! ln -s "${datesubdir}/${logfilebase}" "${linkfile}"
then
	echo "failed to link logfile: ${linkfile} to ${logfilebase}"
	let status="${status} + 1"

# Start the service
elif ! SERVICENAME="${SERVICENAME}" CFGFILE="${SERVICECFG}" SERVICEDIR="${SERVICEDIR}" LOGDIR="${LOGDIR}" nohup bash -ac "date && . '${SERVICECFG}' && env | sort > '${logdir}/${SERVICENAME}.env' &&
echo '${SERVICESTARTER} ${SERVICESCRIPT} ${SERVICESCRIPTARGS}' > '${logdir}/${SERVICENAME}.cmd' &&
'${SERVICESTARTER}' '${SERVICESCRIPT}' ${SERVICESCRIPTARGS}" &> "${logfile}" &
then
	echo "Failed to start the ${SERVICENAME} service"
	let status="${status}+1"
fi

if [ "${status}" -eq 0 ]
then
	let timespent="${SECONDS}-${messagetime}"
	echo "... done in ${timespent} seconds"
	echo ''
	printf 'Successfully started %s service in %d seconds.\n' "${SERVICENAME}" "${SECONDS}"
else
	printf 'Failed to start %s service in %d seconds.\n' "${SERVICENAME}" "${SECONDS}"
fi

exit "${status}"
