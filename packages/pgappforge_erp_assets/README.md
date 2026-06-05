# pgappforge-erp-assets

**Fixed Assets — asset register, depreciation schedules, disposals, impairment**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-assets
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_assets import AssetsPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = AssetsPlugin(appbuilder)
plugin.activate()
```

## Features

- Asset register with lifecycle tracking
- Multiple depreciation methods (SL, DB, UOP)
- Asset disposal and write-off processing
- Impairment testing support
- GL integration for depreciation journals

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
