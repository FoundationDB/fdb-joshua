# Joshua Scripts

## joshuaClient.ksh &lt;action&gt; [options]
Script used to list, submit, and manage ensembles for Joshua web application.

__Actions:__
* __List__ - List the specified ensembles
* __Start__ - Upload and start the specified ensemble
* __Stop__ - Stop the specified running ensemble
* __Tail__ - Display the result of the specified ensemble

## Actions:
#### List
  * __Description__:  List the specified ensembles
  * __Syntax__:       `list`
  * __Environmental Variables:__
    * __STOPPED__:  _Stopped ensemble [default 0]_
    * __SANITY__:   _Sanity test ensemble [default 0]_
    * __USERSORT__: _Sort by username_

#### Start
  * __Description__:  Upload and start the specified ensemble
  * __Syntax__:       `start <ensemble package>`
  * __Environmental Variables:__
    * __SANITY__:   _Sanity test ensemble [default 0]_
    * __FAILURES__: _Number of failures resulting in job termination [default 10]_
    * __MAX_RUNS__: _Max number of runs for job [default 100000]_
    * __PRIORITY__: _CPU time percent for job [default 100]_
    * __TIMEOUT__:  _Seconds to wait for job completion [default 5400]_
    * __USERNAME__: _Username of ensemble owner [default <current user>]_

#### Stop
  * __Description__:  Stop the specified running ensemble
  * __Syntax__:       `stop [ensemble id]`
  * __Arguments:__
    * __Ensemble Id__:  _Id of specified job ensemble_
  * __Environmental Variables:__
    * __SANITY__:       _Sanity test ensemble [default 0]_
    * __USERNAME__:     _Stop ensembles owned by specified username_
   * __Note__:         _Ensemble Id_ or _USERNAME_ must be specified

#### Tail
  * __Description__:	Display the result of the specified ensemble
  * __Syntax__:       `tail [ensemble id]`
  * __Arguments:__
    * __Ensemble Id__:  _Id of specified job ensemble_
  * __Environmental Variables:__
    * __USERNAME__:     _Display running ensembles owned by specified username_
    * __JOBRAW__:       _Display test output only [default 0]_
    * __JOBERRORS__:    _Display errors only [default 0]_
    * __JOBXML__:       _Wrap raw output in <Trace> tags [default 0]_
   * __Note__:         _Ensemble Id_ or _USERNAME_ must be specified


 ## joshuaNodeInit.ksh &lt;FDB cluster file&gt;
 Script used to initialize a machine to host Joshua agents. The script will install, build, and deploy the Joshua docker image with optional configuration modifications via environmental variables.

__Environmental Variables:__
* __REPODIR__      - Specifies the repository directory
* __WORKDIR__      - Specifies the Joshua work directory
* __GITHUBPROJ__   - GitHub project for Joshua
* __GITHUBBRANCH__ - Branch of the Joshua GitHub project to deploy
* __GITHUBKEY__    - Location of the ssh key for Joshua project
* __AGENT_TOTAL__  - The number of agents to run on this Joshua node
* __AGENT_PRIORITY__ - Nice priority for the Joshua agent processes
* __RAMDISK_ENABLE__ - 1 to enable a Ramdisk for the Joshua agents
* __RAMDISK_SIZE__ - The size of the Ram disks (in GB)
