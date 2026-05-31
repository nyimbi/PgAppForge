# Quick Start

[Home](Home) > Quick Start

Five minutes from install to a running app.

---

## Step 1 — Install

```bash
pip install pgappforge
```

---

## Step 2 — Create `app.py`

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "postgresql://user:pass@localhost/mydb"
app.config["SECRET_KEY"] = "change-me-in-production-use-32-random-bytes"

db = SQLA(app)
appbuilder = AppBuilder(app, db.session)
```

---

## Step 3 — Generate everything

Point the generator at your existing PostgreSQL database:

```bash
export FLASK_APP=app.py
flask forge gen all \
  --uri postgresql://user:pass@localhost/mydb \
  --name "My App" \
  --output-dir myapp/
```

This produces:

```
myapp/
  models.py       # SQLAlchemy models for every table
  views.py        # ModelView subclasses with list/add/edit/show
  api/
    __init__.py   # ModelRestApi endpoints
  app.py          # Wired-up Flask factory
```

---

## Step 4 — Create the admin user

```bash
flask fab create-admin
```

---

## Step 5 — Run

```bash
flask run
```

Open `http://localhost:5000`. Log in with the admin credentials you just created. Every table in your database now has list, add, edit, show, and delete views plus REST API endpoints.

---

## What's next?

- Open the **ERD Designer** at `/erd-designer/` to edit your schema visually.
- Open the **Security Designer** at `/security-designer/` to manage roles and permissions.
- Browse the 62 bundled schema templates: `flask forge templates list`
- Apply a template to a new schema: `flask forge templates apply fhir-r4 --schema clinical`

---

## See also

- [Installation](Installation)
- [Code Generator](Code-Generator)
- [ERD Designer](ERD-Designer)
- [Schema Templates](Schema-Templates)
- [CLI Reference](../api/cli.md)
