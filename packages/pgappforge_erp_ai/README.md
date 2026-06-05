# pgappforge-erp-ai

**AI Insights — LLM-powered summaries, copilot queries, anomaly narratives**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-ai
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_ai import AIPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = AIPlugin(appbuilder)
plugin.activate()
```

## Features

- Natural language query interface
- LLM-powered anomaly narratives
- AI-driven period close commentary
- Intelligent data entry suggestions
- Configurable LLM provider backend

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
