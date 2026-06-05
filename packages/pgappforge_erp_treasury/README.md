# pgappforge-erp-treasury

**Treasury — cash management, bank reconciliation, FX exposure, investments, debt**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-treasury
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_treasury import TreasuryPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = TreasuryPlugin(appbuilder)
plugin.activate()
```

## Features

- Cash position and forecasting
- Bank statement import and reconciliation
- FX exposure management
- Investment portfolio tracking
- Debt and facility management

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
