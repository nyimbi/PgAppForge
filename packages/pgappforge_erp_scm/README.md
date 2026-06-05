# pgappforge-erp-scm

**Supply Chain Management — procurement, purchase orders, goods receipt, supplier management**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-scm
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_scm import SCMPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = SCMPlugin(appbuilder)
plugin.activate()
```

## Features

- Procurement request and approval workflow
- Purchase order management
- Goods receipt and quality inspection
- Supplier performance tracking
- Demand-driven replenishment

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
