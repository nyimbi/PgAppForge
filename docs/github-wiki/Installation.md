# Installation

[Home](Home) > Installation

---

## Requirements

- Python 3.12+
- PostgreSQL 14+ (the only supported database)
- pip or uv

---

## Base Install

```bash
pip install pgappforge
```

---

## Extras

Install optional extras based on the features you need:

| Extra | Installs | Use when |
|---|---|---|
| `speech` | speech-to-text libraries | Voice input widgets |
| `analytics` | pandas, openpyxl, plotly | Data Hub export, charts |
| `realtime` | flask-socketio, redis | WebSocket collaboration |
| `geo` | GeoAlchemy2, Shapely | Spatial fields and INSPIRE templates |
| `full` | all of the above | Development / evaluation |

```bash
# Single extra
pip install "pgappforge[realtime]"

# Multiple extras
pip install "pgappforge[analytics,geo]"

# Everything
pip install "pgappforge[full]"
```

---

## PostgreSQL Setup

pgappforge requires a PostgreSQL 14+ database. The connection user needs DDL rights if you intend to use the ERD Designer's schema mutation endpoints.

```sql
-- Create database and user
CREATE DATABASE myapp;
CREATE USER myapp_user WITH PASSWORD 'secret';
GRANT ALL PRIVILEGES ON DATABASE myapp TO myapp_user;

-- For ERD Designer DDL mutations:
GRANT CREATE ON SCHEMA public TO myapp_user;
```

Recommended PostgreSQL extensions (installed automatically by some templates):

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- For geo templates:
CREATE EXTENSION IF NOT EXISTS postgis;
```

---

## Environment Variables

```bash
export DATABASE_URL="postgresql://myapp_user:secret@localhost/myapp"
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

---

## Minimal `config.py`

```python
import os

SECRET_KEY = os.environ["SECRET_KEY"]
SQLALCHEMY_DATABASE_URI = os.environ["DATABASE_URL"]
APP_NAME = "My App"
FAB_UPDATE_PERMS = True
```

---

## First Run

```bash
flask db upgrade          # run Alembic migrations (if using Alembic)
flask fab create-admin    # create the initial admin user
flask run
```

Visit `http://localhost:5000` — you will see the pgappforge welcome screen.

---

## See also

- [Quick Start](Quick-Start)
- [Architecture](Architecture)
- [Configuration Reference](../api/configuration.md)
- [FAQ](FAQ)
