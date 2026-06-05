# pgappforge-erp-tax

**Tax Management — tax codes, VAT/GST calculation, returns, withholding tax**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-tax
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_tax import TaxPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = TaxPlugin(appbuilder)
plugin.activate()
```

## Features

- Multi-jurisdiction tax code configuration
- VAT/GST automatic calculation
- Tax return preparation and filing
- Withholding tax management
- GL integration for tax postings

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
