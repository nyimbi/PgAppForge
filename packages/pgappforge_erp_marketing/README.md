# pgappforge-erp-marketing

**Marketing — campaigns, segments, email journeys, lead capture, attribution**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-marketing
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_marketing import MarketingPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = MarketingPlugin(appbuilder)
plugin.activate()
```

## Features

- Campaign planning and execution
- Audience segmentation
- Multi-channel journey builder
- Lead capture forms and scoring
- Attribution and ROI reporting

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
