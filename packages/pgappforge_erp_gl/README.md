# pgappforge-erp-gl

**General Ledger — chart of accounts, fiscal years, double-entry journal, period balances, budgets**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-gl
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_gl import GLPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = GLPlugin(appbuilder)
plugin.activate()
```

## Features

- Chart of Accounts with IFRS/GAAP concept mapping
- Fiscal years and accounting periods
- Double-entry journal batches and lines
- Period account balance snapshots
- Budget vs actual tracking
- Cost centre dimension

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
