#
# main.py
#
# This source file is part of the FoundationDB open source project
#
# Copyright 2013-2020 Apple Inc. and the FoundationDB project authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from collections import OrderedDict
from flask import current_app as app
from flask import Blueprint, render_template, request, flash, redirect, url_for, Response
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from joshua import joshua, joshua_model
from werkzeug.utils import secure_filename
from wtforms import StringField, SubmitField, FileField, BooleanField, IntegerField
from wtforms.validators import DataRequired, NumberRange

import os, sys

main = Blueprint('main', __name__)


class UploadJobForm(FlaskForm):
    file = FileField('Joshua Package', validators=[DataRequired()])
    fail_fast = IntegerField('Fail Fast',
                             default=10,
                             validators=[NumberRange(min=0, max=1000)])
    allow_multiple = BooleanField('Allow Multiple Ensembles for User',
                                  default=False)
    no_max_runs = BooleanField('Test Continuously', default=False)
    no_fail_fast = BooleanField('No Limit on Failures', default=False)
    max_runs = IntegerField('Max Runs',
                            default=20 * 1000,
                            validators=[NumberRange(min=0, max=1000 * 1000)])
    priority = IntegerField('Priority',
                            default=100,
                            validators=[NumberRange(min=1, max=1000)])
    timeout = IntegerField('Timeout',
                           default=5400,
                           validators=[NumberRange(min=100, max=43200)])
    sanity = BooleanField('Sanity Test', default=False)
    username = StringField('User Name', default='unknown')
    submit = SubmitField('Upload')

    def get_properties(self):
        properties = {
            'priority': self.priority.data,
            'timeout': self.timeout.data,
            'allow_multiple': allow_multiple,
            'no_max_runs': no_max_runs,
            'no_fail_fast': no_fail_fast,
            'username': self.username.data,
            'sanity': self.sanity.data,
            'compressed': True
        }
        # Process the max number of tests
        if self.max_runs.data > 0:
            properties['max_runs'] = self.max_runs.data
        else:
            properties['no_max_runs'] = true
        # Process the max number of failures
        if self.max_runs.fail_fast > 0:
            properties['fail_fast'] = self.fail_fast.data
        else:
            properties['no_fail_fast'] = true
        return properties


@main.route('/')
def index():
    return render_template('index.html')


@main.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)


@main.route('/job', methods=['GET', 'POST'])
def job():
    ensemble_list = joshua.get_active_ensembles(False, False)
    ensembles = []
    for ensemble, properties in ensemble_list:
        ensembles.append([ensemble, OrderedDict(sorted(properties.items()))])
    return render_template('job.html',
                           user=current_user,
                           ensembles=ensemble_list)


@main.route('/joblist', methods=['GET', 'POST'])
def joblist():
    stopped_arg = request.args.get('stopped', default='false').lower()
    stopped = (stopped_arg == 'true') or (stopped_arg == '1')
    sanity_arg = request.args.get('sanity', default='false').lower()
    sanity = (sanity_arg == 'true') or (sanity_arg == '1')
    username = request.args.get('username', default=None)
    usersort_arg = request.args.get('usersort', default='false').lower()
    usersort = (usersort_arg == 'true') or (usersort_arg == '1')
    app.logger.info('joblist: stopped: {}  sanity: {}  usersort: {}'.format(
        stopped, sanity, usersort))
    ensemble_list = joshua.get_active_ensembles(stopped, sanity, username)
    if usersort:
        ensemble_list = sorted(ensemble_list, key=lambda i: i[1]['username'])
    return render_template('joblist.txt',
                           user=current_user,
                           ensembles=ensemble_list)


@main.route('/jobstop', methods=['GET', 'POST'])
def jobstop():
    jobid = request.args.get('id')
    username = request.args.get('username')
    sanity_arg = request.args.get('sanity', default='false').lower()
    sanity = (sanity_arg == 'true') or (sanity_arg == '1')
    app.logger.info('jobstop: id: {}  username: {}  sanity: {}'.format(
        jobid, username, sanity))
    joshua.stop_ensemble(jobid, username, sanity)
    return render_template('joblist.txt',
                           user=current_user,
                           ensembles=joshua.get_active_ensembles(
                               False, sanity, username))


@main.route('/jobtail', methods=['GET', 'POST'])
def jobtail():
    jobid = request.args.get('id')
    username = request.args.get('username')
    if not jobid and not username:
        return redirect(url_for('main.index'))
    fileid = ('j-' + jobid) if jobid else ('u-' + username)
    raw_arg = request.args.get('raw', default='false').lower()
    raw = (raw_arg == 'true') or (raw_arg == '1')
    errorsonly_arg = request.args.get('errorsonly', default='true').lower()
    errorsonly = (errorsonly_arg == 'true') or (errorsonly_arg == '1')
    xml_arg = request.args.get('xml', default='false').lower()
    xml = (xml_arg == 'true') or (xml_arg == '1')
    simple_arg = request.args.get('simple', default='false').lower()
    simple = (simple_arg == 'true') or (simple_arg == '1')
    sanity_arg = request.args.get('sanity', default='false').lower()
    sanity = (sanity_arg == 'true') or (sanity_arg == '1')
    jobfile = os.path.join(app.config['JOSHUA_UPLOAD_FOLDER'],
                           'tail__' + fileid + '.log')
    app.logger.info('jobtail: id: {}  errors: {}  xml: {}  simple: {}'.format(
        jobid, errorsonly, xml, simple))
    stdout_backup = sys.stdout
    sys.stdout = open(jobfile, 'w')
    joshua.tail_ensemble(jobid,
                         raw=raw,
                         errors_only=errorsonly,
                         xml=xml,
                         sanity=sanity,
                         simple=simple,
                         stopped=False,
                         username=username)
    sys.stdout = stdout_backup
    filehandle = open(jobfile)
    return Response(filehandle.read(), mimetype='text/plain')


@main.route('/upload', methods=['GET', 'POST'])
def upload():
    if request.method == 'POST' and not current_user.is_authenticated:
        return redirect(url_for('main.index'))

    form = UploadJobForm()
    if form.validate_on_submit():
        filename = secure_filename(form.file.data.filename)
        filepath = os.path.join(app.config['JOSHUA_UPLOAD_FOLDER'],
                                secure_filename(current_user.username))
        if not os.path.exists(filepath):
            os.mkdir(filepath, 0o755)
        saved_file = os.path.join(filepath, filename)
        form.file.data.save(saved_file)
        properties = form.get_properties()
        flash('Uploaded:  user: {}   package: {}'.format(
            current_user.username, filename))
        app.logger.info('Uploaded:  user: {}   package: {}'.format(
            current_user.username, filename))
        # convert to non-unicode string for username
        properties['username'] = str(current_user.username)
        # if not form.allow_multiple.data:
        #    joshua.stop_ensemble(username=current_user.username, sanity=form.sanity.data)

        with open(saved_file, "rb") as tarfile:
            tarfile.seek(0, os.SEEK_END)
            size = tarfile.tell()
            tarfile.seek(0, os.SEEK_SET)
            properties['data_size'] = size

        ensemble_id = joshua_model.create_ensemble(properties['username'],
                                                   properties, tarfile, False)
        app.logger.info('Ensemble {} created with properties: {}!'.format(
            ensemble_id, properties))
        flash(f'Ensemble {ensemble_id} created!')
    return render_template('upload.html', user=current_user, form=form)


@main.route('/action', methods=['GET', 'POST'])
def action():
    ensemble = request.args.get('ensemble')
    act = request.args.get('action')
    app.logger.debug(f'Action {act} on ensemble {ensemble}')
    flash(f'Action {act} on ensemble {ensemble}')
    joshua_model.stop_ensemble(ensemble, sanity=True)
    return redirect(url_for('main.job'))
