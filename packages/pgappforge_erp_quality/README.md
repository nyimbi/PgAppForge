# pgappforge-erp-quality

**Quality Control — inspection plans, non-conformance, CAPA, certifications**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-quality
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_quality import QCPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = QCPlugin(appbuilder)
plugin.activate()
```

## Features

- Inspection plan configuration
- Non-conformance report (NCR) management
- Corrective and preventive actions (CAPA)
- Quality certificate management
- Statistical process control charts

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
