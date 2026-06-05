# pgappforge-erp-predictive

**Predictive Analytics — demand forecasting, churn prediction, anomaly detection**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-predictive
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_predictive import PredictivePlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = PredictivePlugin(appbuilder)
plugin.activate()
```

## Features

- Demand forecasting (statistical + ML)
- Customer churn prediction
- Anomaly detection on financial data
- Model training pipeline hooks
- Forecast accuracy tracking

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
