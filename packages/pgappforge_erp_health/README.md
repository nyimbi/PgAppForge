# pgappforge-erp-health

**Healthcare vertical — patient registry, episodes, clinical encounters, billing**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-health
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_health import HealthPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = HealthPlugin(appbuilder)
plugin.activate()
```

## Features

- Patient and demographic registry
- Clinical episode and encounter management
- Diagnosis and procedure coding (ICD/CPT)
- Healthcare billing and claims
- HIPAA-compliant access controls

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
