#
# api.py
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

#
# This file provides RESTful API

from flask import Blueprint, jsonify, request
from flask import current_app as app
from marshmallow import Schema, fields
# import built-in validators
from marshmallow.validate import Length, Range
from werkzeug.utils import secure_filename
from joshua import joshua, joshua_model
import tarfile
import os

api = Blueprint('api', __name__)


class UploadJobForm(Schema):
    fail_fast = fields.Int(default=10,
                           missing=10,
                           validate=Range(min=0, max=1000))
    no_fail_fast = fields.Bool(default=False, missing=False)
    max_runs = fields.Int(default=1000,
                          missing=1000,
                          validate=Range(min=0, max=1000000))
    priority = fields.Int(default=100,
                          missing=100,
                          validate=Range(min=1, max=1000))
    timeout = fields.Int(default=5400,
                         missing=5400,
                         validate=Range(min=100, max=43200))
    sanity = fields.Bool(default=False, missing=False)
    username = fields.Str(required=True, validate=Length(max=60))


@api.route('/list', methods=['GET'])
def list_ensembles():
    stopped_arg = request.args.get('stopped', default='false').lower()
    stopped = (stopped_arg == 'true') or (stopped_arg == '1')
    sanity_arg = request.args.get('sanity', default='false').lower()
    sanity = (sanity_arg == 'true') or (sanity_arg == '1')
    username = request.args.get('username', default=None)
    usersort_arg = request.args.get('usersort', default='false').lower()
    usersort = (usersort_arg == 'true') or (usersort_arg == '1')
    app.logger.info('joblist: stopped: {} sanity: {} usersort: {}'.format(
        stopped, sanity, usersort))
    ensemble_list = joshua.get_active_ensembles(stopped, sanity, username)
    if usersort:
        ensemble_list = sorted(ensemble_list, key=lambda i: i[1]['username'])
    return jsonify(ensemble_list), 200


@api.route('/upload', methods=['POST'])
def upload_ensemble():
    request_data = request.form.to_dict()
    request_files = request.files.to_dict()
    if not request_data:
        app.logger.info('api_upload: No form data')
        return {"error": 'api_upload: No form data'}, 400
    if not request_files:
        app.logger.info('api_upload: Missing uploaded file')
        return {
            "message":
                'api_upload: Missing uploaded file  request: {}'.format(
                    request_data)
        }, 400
    schema = UploadJobForm()
    try:
        properties = schema.load(request_data)
    except Exception as err:
        app.logger.info(f'api_upload: Validation error: {err}')
        return {
            "message": f'api_upload: Post field validation error: {err}'
        }, 422
    fileobj = request_files['file']
    filename = secure_filename(fileobj.filename)
    filepath = os.path.join(app.config['JOSHUA_UPLOAD_FOLDER'],
                            secure_filename(properties['username']))
    if not os.path.exists(filepath):
        os.mkdir(filepath, 0o755)
    saved_file = os.path.join(filepath, filename)
    fileobj.save(saved_file)
    if not tarfile.is_tarfile(saved_file):
        os.remove(saved_file)
        app.logger.info(
            f'api_upload: not a valid tar file: {saved_file}')
        return {"error": 'api_upload: not a valid tar file'}, 400

    # convert to non-unicode string for username
    properties['username'] = str(properties['username'])

    with open(saved_file, "rb") as file:
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0, os.SEEK_SET)
        properties['data_size'] = size
        ensemble_id = joshua_model.create_ensemble(properties['username'],
                                                   properties, file, False)
        app.logger.info('Ensemble {} created with properties: {}'.format(
            ensemble_id, properties))
    # Delete the file
    os.remove(saved_file)
    return jsonify(ensemble_id), 200


@api.route('/stop/<string:ensemble>')
def stop_ensemble(ensemble):
    ensemble = str(ensemble)  # unicode to ASCII
    properties = joshua_model.get_ensemble_properties(ensemble)
    sanity = properties[
        'sanity'] if properties and 'sanity' in properties else True
    app.logger.info(f'Stop ensemble {ensemble} {sanity}')
    joshua_model.stop_ensemble(ensemble, sanity=sanity)
    return jsonify('OK'), 200


@api.route('/resume/<string:ensemble>', methods=['GET'])
def resume_ensemble(ensemble):
    ensemble = str(ensemble)  # unicode to ASCII
    properties = joshua_model.get_ensemble_properties(ensemble)
    sanity = properties[
        'sanity'] if properties and 'sanity' in properties else True
    app.logger.info(f'Resume ensemble {ensemble} {sanity}')
    joshua_model.resume_ensemble(ensemble, sanity=sanity)
    return jsonify('OK'), 200
