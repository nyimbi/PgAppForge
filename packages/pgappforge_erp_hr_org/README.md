# pgappforge-erp-hr-org

**HR Organisation — org chart, positions, job grades, cost centres**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-hr-org
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_hr_org import OrgPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = OrgPlugin(appbuilder)
plugin.activate()
```

## Features

- Organisation hierarchy and org chart
- Position and headcount management
- Job family and grade structure
- Cost centre assignment
- Reporting-line management

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
