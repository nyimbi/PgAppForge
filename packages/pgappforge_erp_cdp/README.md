# pgappforge-erp-cdp

**Customer Data Platform — unified customer profiles, identity resolution, segmentation**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-cdp
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_cdp import CDPPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = CDPPlugin(appbuilder)
plugin.activate()
```

## Features

- Unified customer profile stitching
- Identity resolution across channels
- Real-time segmentation engine
- Profile enrichment and scoring
- Activation to marketing and sales

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
