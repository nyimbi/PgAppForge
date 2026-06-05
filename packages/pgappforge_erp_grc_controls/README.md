# pgappforge-erp-grc-controls

**GRC Controls — control library, risk register, assessments, SOX/ISO compliance**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-grc-controls
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_grc_controls import GRCControlsPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = GRCControlsPlugin(appbuilder)
plugin.activate()
```

## Features

- Internal control library
- Risk register and risk scoring
- Control assessment and testing
- SOX and ISO 27001 mapping
- Remediation tracking

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
