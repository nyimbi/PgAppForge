# Tutorial 02: Your First App from a PostgreSQL Database

This tutorial walks through generating a complete pgappforge application directly from an existing PostgreSQL database. By the end you will have a running web app with CRUD views, REST API endpoints, authentication, and Docker support — all generated from your schema without writing a line of application code.

## Prerequisites

- pgappforge installed: `pip install pgappforge`
- A PostgreSQL database with at least one table
- Python 3.11+

For this tutorial we use the `employees` example database included with pgappforge:

```bash
# Create the database
createdb employees

# Apply the example schema and seed data
cd examples/employees
flask fab create-db
flask fab load-data
```

## Step 1 — Run the Generator

`flask forge gen all` inspects your database and produces a complete application directory:

```bash
flask forge gen all \
  --uri postgresql://localhost/employees \
  --name EmployeeApp \
  --output-dir ./empapp/
```

The command:

1. Connects to PostgreSQL and introspects every table, column, index, and FK constraint
2. Classifies column types (UUID, JSONB, TIMESTAMPTZ, INET, arrays, ranges, …) into appropriate widget types
3. Generates Python source files and configuration
4. Writes a `Dockerfile` and `docker-compose.yml` for production deployment

Output (abbreviated):

```
Introspecting postgresql://localhost/employees ...
  Found 8 tables, 63 columns, 12 foreign keys
Generating EmployeeApp → ./empapp/
  ✓ config.py
  ✓ models.py
  ✓ views.py
  ✓ api.py
  ✓ app.py
  ✓ requirements.txt
  ✓ Dockerfile
  ✓ docker-compose.yml
  ✓ tests/
Generation complete! Run: cd empapp && flask run
```

To generate web + mobile at the same time:

```bash
flask forge gen all \
  --uri postgresql://localhost/employees \
  --name EmployeeApp \
  --output-dir ./empapp/ \
  --platform all \
  --api-url https://api.example.com
```

## Step 2 — What Was Generated

```
empapp/
├── app.py          # Flask application factory
├── config.py       # Environment-driven configuration
├── models.py       # SQLAlchemy models, one class per table
├── views.py        # pgappforge ModelView subclasses (CRUD UI)
├── api.py          # ModelRestApi subclasses (REST/OpenAPI)
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── tests/
    └── test_smoke.py
```

**`models.py`** contains one SQLAlchemy model class per table. Column types are inferred from PostgreSQL metadata: `TIMESTAMPTZ` becomes `DateTime(timezone=True)`, `JSONB` becomes `JSONB`, `UUID` primary keys are wired with `gen_random_uuid()` defaults.

**`views.py`** contains one `ModelView` subclass per model. The generator sets `list_columns`, `show_columns`, `add_columns`, and `edit_columns` based on column types — binary/large-object columns are excluded from list views automatically. Foreign-key columns become relationship drop-downs.

**`api.py`** contains one `ModelRestApi` subclass per model, exposing OpenAPI-documented endpoints at `/api/v1/<resource>/`. All endpoints inherit the same role-based permission system as the UI.

**`config.py`** reads from environment variables with sensible defaults. Set `DATABASE_URL` and `SECRET_KEY` in your environment or a `.env` file.

## Step 3 — Run the App

```bash
cd empapp
pip install -r requirements.txt

# Create the security tables (roles, users, permissions)
flask fab create-admin --username admin --password admin --email admin@example.com

# Start the development server
flask run
```

Open `http://127.0.0.1:5000`. Log in with the admin credentials you just created.

## Step 4 — Explore the Auto-Generated CRUD Views

The navigation bar has one menu entry per table. For the `employees` database you will see:

- **Employees** — list, search, add, edit, delete
- **Departments** — list with related employees count
- **Salaries** — date-range aware list view
- **Titles** — filterable by title string

Each list view provides:

- **Column sorting** — click any column header
- **Search bar** — full-text search across string columns
- **Filters** — per-column filter panel (type, operator, value)
- **Export** — CSV download of the current filtered result set
- **Pagination** — configurable page size

The **Add** and **Edit** forms use the correct widget per column type: date pickers for `DATE`/`TIMESTAMPTZ`, numeric inputs for `INTEGER`/`NUMERIC`, rich text for `TEXT`, JSON editors for `JSONB`.

## Step 5 — Explore the REST API

The API is documented at `http://127.0.0.1:5000/api/v1/` (Swagger UI).

```bash
# Get a JWT token
curl -X POST http://127.0.0.1:5000/api/v1/security/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin"}'

# List employees (first page)
curl -H "Authorization: Bearer <token>" \
  "http://127.0.0.1:5000/api/v1/employee/?page=1&page_size=20"

# Create an employee
curl -X POST -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"emp_no": 99999, "birth_date": "1990-01-15", "first_name": "Ada", "last_name": "Lovelace", "gender": "F", "hire_date": "2024-01-01"}' \
  http://127.0.0.1:5000/api/v1/employee/
```

Every endpoint validates input against the generated schema, returns structured error responses, and enforces the same role/permission system used by the UI.

## Next Steps

- **Customise views**: edit `views.py` to add computed columns, custom filters, or related sub-views
- **Add business logic**: override `pre_add`, `post_add`, `pre_update`, `post_update` hooks in your `ModelView` subclasses
- **Apply a template**: see [Tutorial 03](03_using_templates.md) to start from a pre-designed schema instead of an existing database
- **Audit trail**: see [Tutorial 05](05_audit_and_compliance.md) to add tamper-evident change history
