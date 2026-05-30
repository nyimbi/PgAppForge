import os

from flask import Flask
from pgappforge import AppBuilder, SQLA

app = Flask(__name__)

basedir = os.path.abspath(os.path.dirname(__file__))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(basedir, "app.db")
app.config["CSRF_ENABLED"] = True
# SECURITY BEST PRACTICE: Use environment variable for secret key
app.config["SECRET_KEY"] = os.environ.get('SECRET_KEY')
if not app.config["SECRET_KEY"]:
    print("WARNING: Using temporary secret key. Set SECRET_KEY environment variable for production!")
    print("Generate key: python ../../bin/generate_secret_key.py")
    import secrets
    app.config["SECRET_KEY"] = secrets.token_urlsafe(64)

db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

app.run(host="0.0.0.0", port=8080, debug=True)
