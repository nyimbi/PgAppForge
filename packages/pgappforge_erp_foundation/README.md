# pgappforge-erp-foundation

**ERP Foundation — shared master-data entities (Party, Currency, Country, CodeTable) used by all ERP plugins**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-foundation
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_foundation import FoundationPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = FoundationPlugin(appbuilder)
plugin.activate()
```

## Features

- Party and PartyRole master data
- Currency and exchange rate management
- Country and CodeTable reference data
- Address, Contact, Note, Attachment entities
- Domain event log

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
