import pytest
import sqlite3
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

@pytest.fixture(scope='function')
def app():
    from app import app as flask_app
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False
    flask_app.config['STRIPE_SECRET_KEY'] = 'sk_test_mock'
    flask_app.config['STRIPE_PUBLISHABLE_KEY'] = 'pk_test_mock'
    
    with flask_app.app_context():
        yield flask_app

@pytest.fixture(scope='function')
def client(app):
    return app.test_client()

@pytest.fixture(scope='function')
def db():
    test_db = 'test_database.db'
    yield test_db
    if os.path.exists(test_db):
        os.remove(test_db)

@pytest.fixture(scope='function')
def init_database(app, db):
    from init_db import init_database as create_db
    create_db()
    yield
