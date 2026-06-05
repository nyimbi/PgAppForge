# pgappforge-erp-commerce

**Commerce — product catalogue, storefronts, cart, checkout, promotions**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-commerce
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_commerce import CommercePlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = CommercePlugin(appbuilder)
plugin.activate()
```

## Features

- Product catalogue management
- Multi-storefront configuration
- Cart and checkout workflow
- Promotions and coupon engine
- Order fulfilment integration

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
