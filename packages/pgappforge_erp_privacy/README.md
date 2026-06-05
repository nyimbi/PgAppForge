# pgappforge-erp-privacy

**Privacy Management — data inventory, DSAR, consent, GDPR/CCPA compliance**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-privacy
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_privacy import GRCPrivacyPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = GRCPrivacyPlugin(appbuilder)
plugin.activate()
```

## Features

- Personal data inventory and lineage
- DSAR (Data Subject Access Request) workflow
- Consent record management
- GDPR/CCPA impact assessment
- Breach notification workflow

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
