# pgappforge-erp-hr-personnel

**HR Personnel — employee lifecycle, contracts, absences, documents**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-hr-personnel
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_hr_personnel import PersonnelPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = PersonnelPlugin(appbuilder)
plugin.activate()
```

## Features

- Employee record and lifecycle management
- Employment contract management
- Absence and leave management
- Employee document vault
- Probation and confirmation tracking

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
