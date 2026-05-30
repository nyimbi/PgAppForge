import os
import secrets

basedir = os.path.abspath(os.path.dirname(__file__))

CSRF_ENABLED = True

# SECURITY BEST PRACTICE: Use environment variable for secret key
# For production, always set SECRET_KEY environment variable
SECRET_KEY = os.environ.get('SECRET_KEY')

if not SECRET_KEY:
    # For development/example purposes only - NEVER use in production
    print("WARNING: Using development secret key. Set SECRET_KEY environment variable for production!")
    print("Generate a secure key: python -c \"import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))\"")
    SECRET_KEY = secrets.token_urlsafe(64)  # Generate a random key for this session

SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(basedir, "app.db")
# SQLALCHEMY_DATABASE_URI = 'mysql://myapp@localhost/myapp'

BABEL_DEFAULT_LOCALE = "en"

LANGUAGES = {
    "en": {"flag": "gb", "name": "English"},
    "pt": {"flag": "pt", "name": "Portuguese"},
    "es": {"flag": "es", "name": "Spanish"},
    "de": {"flag": "de", "name": "German"},
    "zh": {"flag": "cn", "name": "Chinese"},
    "ru": {"flag": "ru", "name": "Russian"},
}

# ------------------------------
# GLOBALS FOR GENERAL APP's
# ------------------------------
UPLOAD_FOLDER = basedir + "/app/static/uploads/"
IMG_UPLOAD_FOLDER = basedir + "/app/static/uploads/"
IMG_UPLOAD_URL = "/static/uploads/"
IMG_SIZE = (150, 150, True)
AUTH_TYPE = 1
AUTH_ROLE_ADMIN = "Admin"
AUTH_ROLE_PUBLIC = "Public"
APP_NAME = "F.A.B. Example"
APP_THEME = ""  # default
# APP_THEME = "cerulean.css"      # COOL
# APP_THEME = "amelia.css"
# APP_THEME = "cosmo.css"
# APP_THEME = "cyborg.css"       # COOL
# APP_THEME = "flatly.css"
# APP_THEME = "journal.css"
# APP_THEME = "readable.css"
# APP_THEME = "simplex.css"
# APP_THEME = "slate.css"          # COOL
# APP_THEME = "spacelab.css"      # NICE
# APP_THEME = "united.css"
