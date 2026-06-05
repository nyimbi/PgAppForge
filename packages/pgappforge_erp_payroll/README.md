# pgappforge-erp-payroll

**Payroll — pay runs, gross-to-net, statutory deductions, payslips, GL posting**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-payroll
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_payroll import PayrollPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = PayrollPlugin(appbuilder)
plugin.activate()
```

## Features

- Pay run processing (gross-to-net)
- Statutory deduction calculation (PAYE, NI, pension)
- Payslip generation and distribution
- GL posting for payroll journals
- Multi-currency payroll support

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
