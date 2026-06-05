# pgappforge-erp-analytics

**Operational Analytics — KPI dashboards, cross-module reporting, data extracts**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-analytics
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_analytics import OperationalPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = OperationalPlugin(appbuilder)
plugin.activate()
```

## Features

- Pre-built KPI dashboards per domain
- Cross-module consolidated reports
- Scheduled data extract and export
- Drill-down from summary to transaction
- Export to CSV, Excel, PDF

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
