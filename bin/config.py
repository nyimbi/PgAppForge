import os
import secrets
import sys

basedir = os.path.abspath(os.path.dirname(__file__))

CSRF_ENABLED = True

# SECURITY FIX: Replace hardcoded secret key with secure environment variable reading
SECRET_KEY = os.environ.get('SECRET_KEY')

if not SECRET_KEY:
    print("ERROR: SECRET_KEY environment variable is required for security!")
    print("Generate a secure key with: python -c \"import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))\"")
    print("Then set it in your environment: export SECRET_KEY='your-generated-key'")
    sys.exit(1)

if len(SECRET_KEY) < 32:
    print("ERROR: SECRET_KEY must be at least 32 characters long for security!")
    print("Generate a new key with: python -c \"import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))\"")
    sys.exit(1)

OPENID_PROVIDERS = [
    { 'name': 'Google', 'url': 'https://www.google.com/accounts/o8/id' },
    { 'name': 'Yahoo', 'url': 'https://me.yahoo.com' },
    { 'name': 'AOL', 'url': 'http://openid.aol.com/<username>' },
    { 'name': 'Flickr', 'url': 'http://www.flickr.com/<username>' },
    { 'name': 'MyOpenID', 'url': 'https://www.myopenid.com' }]

SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'app.db')
#SQLALCHEMY_DATABASE_URI = 'mysql://myapp@localhost/myapp'
SQLALCHEMY_MIGRATE_REPO = os.path.join(basedir, 'db_repository')

# administrator list
ADMINS = ['you@example.com']

# pagination
POSTS_PER_PAGE = 3
MAX_SEARCH_RESULTS = 50

BABEL_DEFAULT_LOCALE = 'en'

LANGUAGES = {
    'en': {'flag':'gb', 'name':'English'},
    'pt': {'flag':'pt', 'name':'Portugal'}
}



#------------------------------
# GLOBALS FOR GENERAL APP's
#------------------------------
UPLOAD_FOLDER = basedir + '/app/static/uploads/'
IMG_UPLOAD_FOLDER = basedir + '/app/static/uploads/'
IMG_UPLOAD_URL = '/static/uploads/'
AUTH_TYPE = 1
AUTH_ROLE_ADMIN = 'Admin'
AUTH_ROLE_PUBLIC = 'Public'
APP_NAME = "My App 0.2"
APP_THEME = ""                  # default
#APP_THEME = "cerulean.css"      # COOL
#APP_THEME = "amelia.css"
#APP_THEME = "cosmo.css"
#APP_THEME = "cyborg.css"       # COOL
#APP_THEME = "flatly.css"
#APP_THEME = "journal.css"
#APP_THEME = "readable.css"
#APP_THEME = "simplex.css"
#APP_THEME = "slate.css"          # COOL
#APP_THEME = "spacelab.css"      # NICE
#APP_THEME = "united.css"
