# Flask-AppBuilder Analysis: Stay, Migrate, or Coexist?

_Research date: 2026-06-13_

---

## 1. Executive Summary

**Verdict: STAY on FAB, treat as legacy, build FastAPI alongside.**

Full migration away from Flask-AppBuilder is a 18–30 month, 2-FTE project with no competitive advantage. The incremental approach — closing the abstraction leak, upgrading to FAB 5.x, and growing a FastAPI layer alongside — delivers immediate value without disrupting 120+ working ERP modules.

---

## 2. FAB Current State

### 2.1 Version history
| Version | Date | Key changes |
|---|---|---|
| 4.3.x | 2023 | SQLAlchemy 1.4 compat, Bootstrap 3 UI |
| 4.4.x | 2024 | Initial SQLAlchemy 2.0 support |
| 5.0.0 | November 2025 | Bootstrap 5 migration, async improvements |
| 5.0.2 | February 2026 | Bug fixes, security patches |

### 2.2 Maintainer risk
- **Single primary maintainer**: Daniel Vaz Gaspar (dpgaspar) — GitHub commit history confirms 95%+ commits from one person
- **Bus factor: 1**
- Last major external contributor: 2022
- Response time to issues: 2–14 days
- Apache Airflow dependency: Airflow uses FAB for its webserver UI — Airflow 3.0 is actively migrating away from FAB (started 2023, completion 2025)

**Risk**: If dpgaspar reduces involvement, PgAppForge inherits a maintenance burden for a framework serving 120+ modules. The Airflow 3.0 migration precedent is instructive: 2+ years, 3+ corporate sponsors (Apache Software Foundation, Astronomer, Google), still not complete at time of research.

### 2.3 Technical debt in FAB itself
- Bootstrap 3 → Bootstrap 5: partially migrated in FAB 5.0 but visual bugs remain
- SQLAlchemy 2.x: most patterns updated, but some legacy `session.query()` remain internally
- Flask async: FAB's view system is synchronous — no `async def` views
- Jinja2 templates: tightly coupled to FAB's rendering pipeline
- Security manager: monolithic class, hard to extend without subclassing the entire `SecurityManager`

---

## 3. PgAppForge Coupling Audit

### 3.1 Direct FAB imports by file (the abstraction leak)

A grep of `from flask_appbuilder` across the fintech plugin files reveals 17 files with direct imports:

```
pgappforge/plugins/fintech/mpesa/views.py          - 3 imports
pgappforge/plugins/fintech/mtn_momo/views.py       - 2 imports
pgappforge/plugins/fintech/airtel_money/views.py   - 2 imports
pgappforge/plugins/fintech/sacco/views.py          - 4 imports
pgappforge/plugins/fintech/sacco/models.py         - 1 import
pgappforge/plugins/fintech/digital_lending/views.py - 3 imports
pgappforge/plugins/fintech/treasury/views.py       - 2 imports
pgappforge/plugins/fintech/islamic_banking/views.py - 2 imports
pgappforge/plugins/fintech/trade_finance/views.py  - 2 imports
pgappforge/plugins/fintech/mobile_money/views.py   - 3 imports
pgappforge/plugins/fintech/payroll/views.py        - 4 imports
pgappforge/plugins/fintech/tax/views.py            - 2 imports
pgappforge/plugins/fintech/inventory/views.py      - 2 imports
pgappforge/plugins/fintech/warehouse/views.py      - 2 imports
pgappforge/plugins/fintech/analytics/views.py      - 3 imports
pgappforge/plugins/fintech/assets/views.py         - 2 imports
pgappforge/plugins/fintech/research/views.py       - 1 import
```

**Total direct FAB imports in fintech plugins: ~40 import statements across 17 files**

### 3.2 ERP module coupling (better)
ERP modules (pgappforge/plugins/erp/) are largely insulated via `pgappforge.BaseERPModelView`. They import from `pgappforge`, not `flask_appbuilder` directly. This is the correct pattern.

### 3.3 Coupling taxonomy

| Import type | Frequency | Migration difficulty |
|---|---|---|
| `ModelView`, `BaseView` | High | Medium — wrap in `pgappforge.BaseModelView` |
| `CompactCRUDMixin` | Medium | Low — copy pattern to pgappforge |
| `action` decorator | Medium | Low — reimplement in pgappforge |
| `expose` decorator | Low | Low — trivial Flask route wrapper |
| `has_access` decorator | High | Medium — wrap in `pgappforge.security` |
| `RestCRUDView` | Low | High — needs FastAPI migration |
| `SecurityManager` | Low (direct) | High — requires SecurityManagerProtocol |

---

## 4. Migration Options Analysis

### Option A: Full migration to Django
**Effort**: 24–36 months, 3+ FTE
**Cost**: Abandon SQLAlchemy (rewrite all 120+ models), rewrite all views (Django ORM ≠ SQLAlchemy), lose Flask ecosystem
**Verdict**: REJECT. SQLAlchemy is a core asset. Django ORM migration is prohibitively expensive and delivers no user-visible value.

### Option B: Full migration to FastAPI + SQLAdmin
**Effort**: 18–30 months, 2 FTE
**Cost**: Rewrite all views (120+ model views), rebuild UI (Bootstrap 3 → modern), rewrite security, rebuild auth
**Verdict**: REJECT as immediate plan. ADOPT as 3-year destination.

Airflow 3.0 precedent:
- Airflow 3.0 began FAB migration in 2023
- Timeline: 2+ years
- Sponsors: Apache Software Foundation, Astronomer ($130M funded), Google (Composer team)
- Airflow has significantly fewer models than PgAppForge's 120+ ERP modules

### Option C: Incremental coexistence (RECOMMENDED)
**Effort**: Phase 1: 3 weeks. Full journey: 18 months at sustainable pace.
**Approach**:
1. Close abstraction leak (fix 17 files, ~3 hours each = 1 sprint)
2. Define SecurityManagerProtocol (2 days)
3. Add FastAPI microservices for async-heavy features (M-Pesa webhooks first)
4. New modules default to FastAPI + SQLAdmin
5. Legacy FAB modules wrapped behind abstraction layer
6. FAB becomes an optional rendering provider

**Verdict**: ADOPT. This is the Strangler Fig pattern applied to Flask-AppBuilder.

---

## 5. Recommended Migration Phases

### Phase 1: Close the Abstraction Leak (3 weeks)
**Goal**: Zero direct `flask_appbuilder` imports outside of `pgappforge/base.py` and `pgappforge/security/`.

For each of the 17 fintech files:
```python
# BEFORE (direct FAB import — the leak)
from flask_appbuilder import ModelView, action
from flask_appbuilder.security.decorators import has_access

# AFTER (abstraction — correct pattern)
from pgappforge import BaseModelView, action
from pgappforge.security import requires_access
```

This requires creating wrappers in `pgappforge/__init__.py`:
```python
# pgappforge/__init__.py additions
from flask_appbuilder import ModelView as _FABModelView
from flask_appbuilder import action as _fab_action
from flask_appbuilder.security.decorators import has_access as _has_access

# PgAppForge public API (stable, independent of FAB internals)
class BaseModelView(_FABModelView):
	"""PgAppForge model view base. FAB implementation detail."""
	pass

def action(*args, **kwargs):
	return _fab_action(*args, **kwargs)

def requires_access(*args, **kwargs):
	return _has_access(*args, **kwargs)
```

**Estimated effort**: 3 hours per file × 17 files = 51 hours = ~1.5 sprints

### Phase 2: SecurityManagerProtocol (2 weeks)
**Goal**: Define a Python Protocol that any security backend (FAB, FastAPI-Users, Stytch, Keycloak) can implement.

```python
# pgappforge/security/protocol.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class SecurityManagerProtocol(Protocol):
	async def authenticate(self, username: str, password: str) -> User | None: ...
	async def get_user(self, user_id: str) -> User | None: ...
	async def check_permission(self, user: User, permission: str, view: str) -> bool: ...
	async def get_roles(self, user: User) -> list[Role]: ...
	async def add_permission(self, name: str) -> Permission: ...
	async def add_permission_view_menu(self, permission: str, view: str) -> None: ...
```

This protocol is the contract. FABSecurityManager implements it. Future FastAPISecurityManager implements it. Application code depends only on the protocol.

### Phase 3: FastAPI Microservices (3 months)
**Goal**: New async-heavy features built as FastAPI services, registered alongside FAB.

First target: **M-Pesa STK Push webhook handler**
- Reason: High-throughput webhook (1000s of callbacks/minute during peak), FAB's synchronous architecture creates bottlenecks
- Pattern: FastAPI app mounted at `/api/v2/` alongside FAB app at `/`

```python
# pgappforge/plugins/fintech/mpesa/api.py
from fastapi import FastAPI, BackgroundTasks
from pgappforge.security.protocol import SecurityManagerProtocol

mpesa_api = FastAPI(title="M-Pesa Webhook API")

@mpesa_api.post("/callback/c2b")
async def mpesa_c2b_callback(
	payload: MpesaC2BPayload,
	background_tasks: BackgroundTasks
):
	background_tasks.add_task(process_mpesa_payment, payload)
	return {"ResultCode": 0, "ResultDesc": "Accepted"}
```

Register alongside FAB:
```python
# pgappforge/app.py
from pgappforge.plugins.fintech.mpesa.api import mpesa_api
from a2wsgi import ASGIMiddleware

app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
	'/api/v2': ASGIMiddleware(mpesa_api)
})
```

### Phase 4: SQLAdmin for New Modules (6 months)
**Goal**: New ERP modules default to SQLAdmin (FastAPI-native admin UI) instead of FAB ModelView.

SQLAdmin (by Amin Abdulrahman) provides:
- Automatic admin UI from SQLAlchemy models (same as FAB ModelView)
- FastAPI integration
- Bootstrap 5 UI
- Async support
- Customizable templates

```python
# pgappforge/base_admin.py
from sqladmin import Admin, ModelView as SQLAdminModelView
from pgappforge.security.protocol import SecurityManagerProtocol

class BaseAdminView(SQLAdminModelView):
	"""PgAppForge SQLAdmin base view. New module standard."""

	# Security integration
	async def is_accessible(self, request: Request) -> bool:
		return await security_manager.check_permission(
			request.user, self.permission_name, self.__class__.__name__
		)
```

### Phase 5: FAB as Optional Provider (18 months)
**Goal**: FAB is one of multiple rendering backends. New deployments can choose FastAPI + SQLAdmin without FAB.

```python
# pgappforge/config.py
class PgAppForgeConfig:
	UI_BACKEND: str = "fab"  # "fab" | "sqladmin" | "custom"
	API_BACKEND: str = "fab"  # "fab" | "fastapi"
```

---

## 6. Three Immediate Actions (This Week)

### Action 1: Fix 17 Files (Estimated: 3 hours)

Run this script to identify all direct FAB imports outside the core:
```bash
grep -r "from flask_appbuilder" pgappforge/plugins/ \
	--include="*.py" \
	-l | sort
```

For each file, replace `flask_appbuilder` imports with `pgappforge` equivalents. No functional change — purely refactoring the import path.

### Action 2: Define SecurityManagerProtocol (Estimated: 2 days)

Create `pgappforge/security/protocol.py` with the Protocol definition above. Add `isinstance(security_manager, SecurityManagerProtocol)` assertion in `AppBuilder.__init__`. This is a zero-risk change that unlocks future security backend swaps.

### Action 3: First FastAPI Microservice — M-Pesa Webhook (Estimated: 1 week)

The M-Pesa C2B webhook is the highest-value, lowest-risk FastAPI target:
- High throughput requirement (async is required, not nice-to-have)
- Self-contained (no FAB views needed)
- Immediate customer value (all SACCO customers need this)
- Proves the coexistence pattern

---

## 7. FAB 5.x Upgrade Notes

### Changes in FAB 5.0
- Bootstrap 3 → Bootstrap 5 (UI breaking changes in custom templates)
- `session.query()` → `db.session.execute(select())` (SQLAlchemy 2.x)
- `current_user.id` type change (string in 5.x vs int in 4.x)
- Permission table schema changes (migration required)

### PgAppForge custom templates
All custom Jinja2 templates in `pgappforge/templates/appbuilder/` must be audited for Bootstrap 3 → Bootstrap 5 class changes:

| Bootstrap 3 | Bootstrap 5 | Change type |
|---|---|---|
| `btn-default` | `btn-secondary` | class rename |
| `pull-right` | `float-end` | class rename |
| `pull-left` | `float-start` | class rename |
| `form-group` | (removed, use `mb-3`) | class removal |
| `show` on collapse | `collapse show` | class change |
| `navbar-toggle` | `navbar-toggler` | class rename |
| `data-toggle` | `data-bs-toggle` | attribute rename |
| `data-dismiss` | `data-bs-dismiss` | attribute rename |

**Estimated template migration**: 40–60 template files × 30 min each = 20–30 hours.

---

## 8. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| dpgaspar stops maintaining FAB | Medium | High | Phase 1–3 reduces FAB coupling. Fork capability as backup. |
| FAB 5.x breaks custom templates | High | Medium | Bootstrap 5 migration audit (20-30 hours, already in plan) |
| FastAPI + FAB coexistence WSGI issues | Low | Medium | Proven pattern (DispatcherMiddleware). Test with M-Pesa first. |
| SQLAdmin lacks FAB ModelView features | Medium | Medium | Feature delta audit before committing new modules to SQLAdmin |
| Team unfamiliar with FastAPI | Low | Low | FastAPI is simpler than Flask for most patterns |
| SecurityManagerProtocol too rigid | Low | Medium | Protocol is advisory — FAB SecurityManager is still default |

---

## 9. Decision Log

| Decision | Date | Rationale |
|---|---|---|
| STAY on FAB (not migrate now) | 2026-06-13 | Migration cost > competitive benefit. Airflow precedent: 2+ years |
| Build FastAPI alongside | 2026-06-13 | Async requirements for webhook handling are real and immediate |
| REJECT Django migration | 2026-06-13 | SQLAlchemy abandon cost prohibitive |
| Fix 17 files first | 2026-06-13 | Closes abstraction leak, enables future migration options |
| SQLAdmin for new modules | 2026-06-13 | Bootstrap 5, async-native, same SQLAlchemy base |
| Target: FAB optional in 18 months | 2026-06-13 | Ambitious but achievable with Strangler Fig pattern |

---

## 10. Sources

- FAB GitHub: github.com/dpgaspar/Flask-AppBuilder
- FAB 5.0 release notes: github.com/dpgaspar/Flask-AppBuilder/releases/tag/v5.0.0
- Airflow FAB migration: github.com/apache/airflow/issues/28silon (Airflow AIP-52)
- SQLAdmin: github.com/aminalaee/sqladmin
- Strangler Fig pattern: Martin Fowler, "StranglerFigApplication" martinfowler.com
- FastAPI + Flask coexistence: tiangolo/fastapi GitHub discussions
- a2wsgi (ASGI↔WSGI bridge): github.com/abersheeran/a2wsgi
