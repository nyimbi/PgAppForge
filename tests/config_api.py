import os

basedir = os.path.abspath(os.path.dirname(__file__))

SQLALCHEMY_DATABASE_URI = (
    os.environ.get("SQLALCHEMY_DATABASE_URI")
    or os.environ.get("PGAPPFORGE_DB")
    or "postgresql:///pgaf_test"
)

SECRET_KEY = "thisismyscretkey"
SQLALCHEMY_TRACK_MODIFICATIONS = False
WTF_CSRF_ENABLED = False
PGAF_API_SWAGGER_UI = True
PGAF_ROLES = {
    "ReadOnly": [
        [".*", "can_get"],
        [".*", "can_info"],
        [".*", "can_list"],
        [".*", "can_show"],
    ]
}
