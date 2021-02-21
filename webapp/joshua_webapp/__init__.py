# init.py

from flask import Flask
from flask_bootstrap import Bootstrap
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from logging.config import fileConfig

from joshua import joshua_model
from config import Config

import os

# init SQLAlchemy so we can use it later in our models
db = SQLAlchemy()

# Database migration tool
migrate = Migrate()

bootstrap = Bootstrap()

fileConfig('logging.conf')


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = 'auth.login'
    login_manager.init_app(app)

    migrate.init_app(app, db)
    bootstrap.init_app(app)

    # Make sure cluster file is present
    if not os.path.exists(app.config['JOSHUA_FDB_CLUSTER_FILE']):
        raise Exception('JOSHUA_FDB_CLUSTER_FILE {} not found'.format(
            app.config['JOSHUA_FDB_CLUSTER_FILE']))
    joshua_model.open(app.config['JOSHUA_FDB_CLUSTER_FILE'],
                      (app.config['JOSHUA_NAMESPACE'],))
    app.logger.info('Using cluster file: {}'.format(
        app.config['JOSHUA_FDB_CLUSTER_FILE']))

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        # since the user_id is just the primary key of our user table, use it in the query for the user
        return User.query.get(int(user_id))

    # blueprint for auth routes in our app
    from .auth import auth as auth_blueprint
    app.register_blueprint(auth_blueprint)

    # blueprint for non-auth parts of app
    from .main import main as main_blueprint
    app.register_blueprint(main_blueprint)

    # blueprint for REST APIs
    from .api import api as api_blueprint
    app.register_blueprint(api_blueprint, url_prefix='/api')

    return app
