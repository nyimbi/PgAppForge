# pgappforge-erp-ap

**Accounts Payable — supplier invoices, payment runs, three-way matching, aging**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-ap
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_ap import APPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = APPlugin(appbuilder)
plugin.activate()
```

## Features

- Supplier invoice processing and approval
- Payment run generation
- Three-way matching (PO / GR / invoice)
- Aging analysis and cash-flow forecasting
- GL integration for automatic journal posting

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
