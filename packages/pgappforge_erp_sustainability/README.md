# pgappforge-erp-sustainability

**Sustainability — ESG data collection, carbon accounting, scope 1/2/3, reporting**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-sustainability
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_sustainability import GRCSustainabilityPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = GRCSustainabilityPlugin(appbuilder)
plugin.activate()
```

## Features

- ESG data collection templates
- Carbon footprint accounting (scope 1/2/3)
- Emission factor library
- GHG Protocol compliant reporting
- Science-based targets tracking

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
