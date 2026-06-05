# pgappforge-erp-warehouse

**Warehouse Management — locations, putaway, pick/pack/ship, cycle counts**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-warehouse
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_warehouse import WarehousePlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = WarehousePlugin(appbuilder)
plugin.activate()
```

## Features

- Multi-warehouse and location hierarchy
- Putaway and picking rules
- Pick/pack/ship workflow
- Cycle count and full physical inventory
- Barcode and RFID integration hooks

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
