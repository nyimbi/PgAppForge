# pgappforge-erp-finserv

**Financial Services vertical — instruments, positions, regulatory capital, AML**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-finserv
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_finserv import FinancialServicesPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = FinancialServicesPlugin(appbuilder)
plugin.activate()
```

## Features

- Financial instrument register
- Position and portfolio management
- Regulatory capital calculation hooks
- AML/KYC workflow
- IFRS 9 / CECL provisioning support

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
