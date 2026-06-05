# pgappforge-erp-ar

**Accounts Receivable — customer invoicing, receipts, credit notes, aging, collections**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-ar
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_ar import ARPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = ARPlugin(appbuilder)
plugin.activate()
```

## Features

- Customer invoice lifecycle management
- Payment receipts and allocation
- Credit note processing
- Aging analysis and collections
- GL integration for automatic journal posting

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
