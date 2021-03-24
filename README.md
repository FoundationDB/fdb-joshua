Joshua
======

> How about using FoundationDB to test FoundationDB?

Joshua is a tool designed to coordinate ephemeral tests of the FoundationDB. The
architecture is essentially as follows:

 * The Joshua agent should be run in the various machines where one would like
   jobs to be executed. It will look for jobs to run (called ensembles) by looking 
   for updates from a coordinating FoundationDB cluster.

 * Jobs should be submitted through a Joshua client that pushes a package to
   run as well as adding an ensemble name into the same coordinating database.
   The package should have a script called `joshua_test` that is marked as
   executable that the agent will run in order to run the test.

 * The agent will cycle through the ensembles that have currently been submitted.
   It will run the ensemble given through the `joshua_test` script, and it
   will consider a test to be a success if that script exits with exit code
   zero and a failure otherwise. It will then log the output into the database,
   and it will record whether the test succeeded or failed.

 * Clients can request that an ensemble be stopped, after which agents will no
   longer elect to run that task in particular. Old test results are viewable
   by clients.

At the moment, Joshua agent has been designed to "die on failure" rather than
deal with failures more elegantly. This is because the environment will just reschedule
an agent after its task ends, so it is cheaper and easier to simply have an agent
die if it sees something it can't deal with and allow its environment to be
reset rather than to deal with it more elegantly.

By design, the current package does NOT include two dependencies that it will need
if one wants to run the agent, namely `childsubreaper` and `subprocess32`.
The first module is home built,
but it is an extension module that can only be compiled on Linux and only with
the Python development tools. The other is the Python 3 `subprocess32` module.
As these are not required to run the client, and
as many people may be running the rest of this module from outside of a Linux
environment, these dependencies for the agent only are left out. If you wish to
run the agent manually, you will have to download them separately. The preferred
way of running agents is via the provided Docker image (as described below), so
you don't need to manually managing packages and some required binaries.

## Usage

To start an ensemble, create a `tar.gz` archive where there is a file
called `joshua_test` within the top level directory. This file should be an
executable bash script that performs whatever test you want to run. The
test should finish with exit code 0 upon success and a non-zero exit code
upon failure. Then submit the job by running (assuming your FoundationDB cluster
file is `./fdb.cluster`, otherwise use `-C path/to/cluster_file` for following
commands):

```bash
python3 -m joshua.joshua start --tarball path/to/archive.tar.gz
```

You can then see the results of the test by running:

```bash
python3 -m joshua.joshua tail
```

Or:

```bash
python3 -m joshua.joshua tail --errors
```

If you only want to see the errors from your run. By default, jobs will complete
after they have failed 100 times (though that is configurable through the
`fail-fast` option at ensemble start time). You can manually stop a job by
running:

```bash
python3 -m joshua.joshua stop
```

You can also see which jobs are running:

```bash
python3 -m joshua.joshua list
```

Two more usage notes: Joshua operates by connecting to a coordinating FoundationDB
cluster, which is where it places jobs to start and also where the agents report
back results. You should therefore either set the `FDB_CLUSTER_FILE` environment
variable to that cluster file or pass the cluster file path through the `--cluster-file`
command line argument. Also, Joshua uses the "username" of the user who
submits jobs in order to track which user started jobs and in order to know which
jobs to tail or stop. By default, this is the user's OS user name, but this
can be configured by either passing the `--username` flag (if the command takes
one) or by setting the `JOSHUA_USER` environment variable to the desired name. 

## Build and Run Agent Docker Images

To run Joshua agent processes, we provide a Docker image that can spawn multiple
agent processes. This docker image created by `build.sh` script,
which uses `Dockerfile`.

Note restarting tests need old `fdbserver` binaries and TLS libraries, which
should be saved in `Docker/old_binary` and `Docker/old_tls_library` directories,
respectively.

To start agents, run
```shell
docker run --rm -v /home/centos/joshua/:/opt/joshua -it foundationdb/joshua-agent:latest
```
The `-v` parameter is to pass the cluster file `/home/centos/joshua/fdb.cluster`
for the docker to use. Change this parameter path to where the cluster file is
stored.

By default, agents run under `/tmp/joshua_agent/XX/`, where `XX` is the agent ID
number. Each agent also produces a log file at `/tmp/joshua_agent/XX.log`. If an
agent died, its working directory is renamed as `/tmp/joshua_agent/XX.failed`
and a new agent with a different ID number will be spawned. Agent spawning
events are logged in log file `/tmp/joshua_agent/start_agent.log`.
