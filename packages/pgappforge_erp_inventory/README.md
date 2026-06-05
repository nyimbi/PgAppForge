# pgappforge-erp-inventory

**Inventory Management — items, stock levels, valuation, movements, lot/serial tracking**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-inventory
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_inventory import InventoryPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = InventoryPlugin(appbuilder)
plugin.activate()
```

## Features

- Item master with UOM and category management
- Real-time stock level tracking
- FIFO/LIFO/Average cost valuation
- Inventory movement and adjustment journal
- Lot and serial number tracking

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
