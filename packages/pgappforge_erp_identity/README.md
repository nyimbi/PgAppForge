# pgappforge-erp-identity

**Identity & Access — RBAC, API keys, MFA, SSO/OIDC integration, audit**

Part of the [PgAppForge](https://github.com/pgappforge/pgappforge) ERP plugin suite.

## Installation

```bash
pip install pgappforge pgappforge-erp-identity
```

## Quick Start

```python
from flask import Flask
from pgappforge import AppBuilder, SQLA
from pgappforge_erp_identity import PlatformIdentityPlugin

app = Flask(__name__)
db = SQLA(app)
appbuilder = AppBuilder(app, db.session)

# Plugin auto-registers all views and models via entry points
plugin = PlatformIdentityPlugin(appbuilder)
plugin.activate()
```

## Features

- Role-based access control (RBAC)
- API key management
- Multi-factor authentication (MFA)
- SSO/OIDC integration hooks
- Access audit trail

## Composability

This plugin emits and/or consumes domain events compatible with the pgappforge event bus.
See the [composability docs](https://pgappforge.dev/plugins/erp/composability) for wiring
multiple ERP plugins together.

## License

MIT — Nyimbi Odero
