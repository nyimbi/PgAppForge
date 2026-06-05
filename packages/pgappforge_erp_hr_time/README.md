# pgappforge-erp-hr-time

**Time & Attendance — timesheets, shift schedules, overtime, attendance rules**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-hr-time
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_hr_time import TimePlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = TimePlugin(appbuilder)
plugin.activate()
```

## Features

- Timesheet entry and approval
- Shift schedule management
- Overtime calculation rules
- Attendance and absence reconciliation
- Integration with payroll for gross pay

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
