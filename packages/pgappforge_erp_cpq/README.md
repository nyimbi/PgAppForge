# pgappforge-erp-cpq

**Configure Price Quote — product configurator, pricing rules, discount approvals**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-cpq
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_cpq import CPQPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = CPQPlugin(appbuilder)
plugin.activate()
```

## Features

- Product configuration rules engine
- Dynamic pricing and discount tiers
- Approval workflow for non-standard discounts
- Quote PDF generation
- Integration with sales order

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
