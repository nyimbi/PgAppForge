# pgappforge-erp-talent

**Talent Management — recruitment, performance reviews, learning, succession planning**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-talent
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_talent import TalentPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = TalentPlugin(appbuilder)
plugin.activate()
```

## Features

- Recruitment and applicant tracking
- Performance review cycles
- Learning and development plans
- Succession planning and talent pools
- Skills inventory

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
