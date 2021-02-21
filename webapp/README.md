## Installation

1. Install Supervisor, Nginx, Git. On CentOS, do:
   ```shell
   $ sudo apt-get -y update
   $ sudo apt-get -y install supervisor nginx git
   $ sudo apt-get -y install python3 python3-venv python3-dev
   ```

1. Create a Python virtual environment and activate it:

   ```shell
   virtualenv env
   source env/bin/activate
   ```

   Or:
   ```shell
   python3 -m venv env
   source env/bin/activate
   ```

1.  Clone this repo install required packages:

   ```shell
   git clone git@github.com:FoundationDB/fdb-joshua.git
   pip install -r fdb-joshua/webapp/requirements.txt
   ```

## Running

First, specify the App name as `joshua_webapp`.

```shell
export FLASK_APP=joshua_webapp
export FLASK_DEBUG=1
export JOSHUA_UPLOAD_FOLDER=YOUR_UPLOAD_DIRECTORY
export JOSHUA_FDB_CLUSTER_FILE=YOUR_CLUSTER_FILE
```

Create `.env` file with contents like:

```bash
SECRET_KEY=113214c7ba524463a988ecd915cd701a
```

This key is used by the Flask server and should be kept as a secret. To generate
a random string, you may use this command:

```bash
python -c "import uuid; print(uuid.uuid4().hex)"
```

Then start the service by:
```shell
(env) $ flask run
 * Serving Flask app "joshua_python" (lazy loading)
 * Environment: production
   WARNING: This is a development server. Do not use it in a production deployment.
   Use a production WSGI server instead.
 * Debug mode: on
 * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
 * Restarting with stat
 * Debugger is active!
 * Debugger PIN: 276-156-512
```

Now the service runs at `http://127.0.0.1:5000/`.

To see a list of endpoints, run:

```bash
$ flask routes
Endpoint          Methods    Rule
----------------  ---------  ---------------------------------
auth.login        GET, POST  /login
auth.logout       GET        /logout
auth.signup       GET, POST  /signup
bootstrap.static  GET        /static/bootstrap/<path:filename>
main.index        GET        /
main.job          GET, POST  /job
main.profile      GET        /profile
main.upload       GET, POST  /upload
static            GET        /static/<path:filename>
```

## Deploy

When running the server with `flask run`, we are using the web server that comes
with Flask, which isn't a good choice to use for a production server for
performance and robustness. Instead, we will use `gunicorn`, a pure Python web
server:

```shell
(env) $ gunicorn -b localhost:8000 -w 4 joshua_python.wsgi:app
```

The `-b` option tells `gunicorn` the listening address. The `-w` option
configures the number of workers that `gunicorn` will run.
The `joshua_python.wsgi:app` argument tells `gunicorn` how to load the
application instance. `joshua_python.wsgi` is the module and python file,
`app` is the name of this application.

If `gunicorn` runs fine, we use the `supervisor` to monitor and to restart
them when necessary. The configuration file `/etc/supervisor/conf.d/joshua.conf`
is:

```bash
[program:joshua]
command=/home/ubuntu/joshua-python/env/bin/gunicorn -b localhost:8000 -w 4 joshua_python.wsgi:app
directory=/home/ubuntu/joshua-python
user=ubuntu
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
```

Reload the supervisor service to import the `joshua.conf` file:

```bash
$ sudo supervisorctl reload
```

### Nginx Reverse Proxy

The public facing port 80 and 443 is served by Nginx, which will forward
traffic to our `gunicorn` server running at 8000.

### Upgrade

```shell
(env) $ git pull                           # download the new version
(env) $ sudo supervisorctl stop joshua     # stop the current server
(env) $ flask db upgrade                   # upgrade the database
(env) $ sudo supervisorctl start joshua    # start a new server
```

### Asynchronous Task Execution

See stackoverflow discussion [here](https://stackoverflow.com/questions/31866796/making-an-asynchronous-task-in-flask).
