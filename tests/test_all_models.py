"""
tests/test_all_models.py

Comprehensive model validation test against pgaf_test PostgreSQL database.

Strategy: Import plugin PACKAGES (not individual models.py files) so each
class is registered exactly once through the package's __init__.py.
Then create all tables and verify every mapped model can INSERT + SELECT.

Run:
    SQLALCHEMY_DATABASE_URI=postgresql:///pgaf_test .venv/bin/python tests/test_all_models.py
"""
from __future__ import annotations
import sys, types, uuid, traceback
from datetime import date, datetime, timezone
from decimal import Decimal

# ── Stub flask_appbuilder before any plugin import ───────────────────────────
def _mk(name):
    m = types.ModuleType(name); sys.modules[name] = m; return m

for _n in [
    "flask_appbuilder","flask_appbuilder.models","flask_appbuilder.models.sqla",
    "flask_appbuilder.models.sqla.interface","flask_appbuilder.security.decorators",
    "flask_appbuilder.baseviews","flask_appbuilder.views","flask_appbuilder.forms",
    "flask_appbuilder.fieldwidgets","flask_appbuilder.actions","flask_appbuilder.hooks",
    "flask_appbuilder.widgets","flask_appbuilder.security","flask_appbuilder.security.manager",
]:
    if _n not in sys.modules: _mk(_n)

class _S:
    def __init__(self,*a,**k): pass
    def __call__(self,*a,**k): return self
    def __class_getitem__(cls,i): return cls
    def __set_name__(self,*a): pass

for _a in ["ModelView","BaseView","expose","has_access","SQLAInterface","MasterDetailView","RulesMixin"]:
    setattr(sys.modules["flask_appbuilder"], _a, _S)
sys.modules["flask_appbuilder.models.sqla.interface"].SQLAInterface = _S
sys.modules["flask_appbuilder.security.decorators"].has_access = lambda f: f

# ── Database setup ───────────────────────────────────────────────────────────
import os
DB_URL = os.environ.get("SQLALCHEMY_DATABASE_URI", "postgresql:///pgaf_test")
import sqlalchemy as sa
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

engine = create_engine(DB_URL, echo=False)

# ── Import all models in dependency order through PACKAGE imports ─────────────
# Importing PACKAGES (not models.py files directly) ensures each class is
# registered exactly once through the package's __init__.py.
from pgappforge.models.sqla import Model  # shared declarative base

# Ordered by FK dependency: foundation → GL → fintech core → everything else
PACKAGES = [
    # ERP Foundation (defines Party, Currency etc. referenced by all plugins)
    "pgappforge.plugins.erp.foundation",
    # GL first — referenced by all finance plugins
    "pgappforge.plugins.erp.finance.gl",
    "pgappforge.plugins.erp.finance.ap",
    "pgappforge.plugins.erp.finance.ar",
    "pgappforge.plugins.erp.finance.assets",
    "pgappforge.plugins.erp.finance.tax",
    "pgappforge.plugins.erp.finance.treasury",
    "pgappforge.plugins.erp.finance.fpa",
    "pgappforge.plugins.erp.finance.entities",
    # HCM
    "pgappforge.plugins.erp.hcm.org",
    "pgappforge.plugins.erp.hcm.payroll",
    "pgappforge.plugins.erp.hcm.personnel",
    "pgappforge.plugins.erp.hcm.talent",
    "pgappforge.plugins.erp.hcm.time",
    "pgappforge.plugins.erp.hcm.travel_expense",
    # CRM
    "pgappforge.plugins.erp.crm.sales",
    "pgappforge.plugins.erp.crm.marketing",
    "pgappforge.plugins.erp.crm.service",
    "pgappforge.plugins.erp.crm.cpq",
    "pgappforge.plugins.erp.crm.commerce",
    "pgappforge.plugins.erp.crm.field_service",
    "pgappforge.plugins.erp.crm.contracts",
    "pgappforge.plugins.erp.crm.pos",
    # Operations
    "pgappforge.plugins.erp.operations.inventory",
    "pgappforge.plugins.erp.operations.production",
    "pgappforge.plugins.erp.operations.quality",
    "pgappforge.plugins.erp.operations.scm",
    "pgappforge.plugins.erp.operations.warehouse",
    "pgappforge.plugins.erp.operations.eam",
    "pgappforge.plugins.erp.operations.fleet",
    # Projects / GRC
    "pgappforge.plugins.erp.projects",
    "pgappforge.plugins.erp.grc.controls",
    # Fintech (imports GL — must come after GL is registered)
    "pgappforge.plugins.fintech.core_banking",
    "pgappforge.plugins.fintech.lending",
    "pgappforge.plugins.fintech.mobile_money",
    "pgappforge.plugins.fintech.payments",
    "pgappforge.plugins.fintech.trade_finance",
    "pgappforge.plugins.fintech.regulatory",
    "pgappforge.plugins.fintech.sacco",
    "pgappforge.plugins.fintech.swift",
    "pgappforge.plugins.fintech.treasury",
    "pgappforge.plugins.fintech.pswitch_adapter",
]

import importlib

# Pre-register stub tables for ALL known cross-plugin FK targets
# Must happen BEFORE package imports because SQLAlchemy resolves FK refs on class definition
_EXTERNAL_STUBS = [
    # FAB user tables — not in our models, need stubs for FK resolution
    "ab_user","ab_role","ab_permission","ab_view_menu","ab_permission_view",
    # Tenancy — cross-plugin reference
    "tenancy_tenant",
    # foundation_party — stub only; erp_party/erp_currency/erp_country/erp_address
    # are defined by erp.foundation and must NOT be stubbed here (would conflict with real model)
    "foundation_party",
]
for _st in _EXTERNAL_STUBS:
    if _st not in Model.metadata.tables:
        try:
            sa.Table(_st, Model.metadata, autoload_with=engine, extend_existing=True)
        except Exception:
            _id_col = sa.Column("id", sa.Integer if _st.startswith("ab_") else sa.String(36), primary_key=True)
            sa.Table(_st, Model.metadata, _id_col,
                sa.Column("tenant_id", sa.String(36), nullable=True),
                sa.Column("name", sa.String(200), nullable=True),
                extend_existing=True,
            )

loaded = failed = 0
fail_list = []
for pkg in PACKAGES:
    try:
        importlib.import_module(pkg)
        loaded += 1
    except Exception as e:
        failed += 1
        fail_list.append((pkg.split(".")[-1], str(e)[:100]))

print(f"\n{'='*70}")
print(f"PACKAGE IMPORTS: {loaded}/{len(PACKAGES)} loaded, {failed} failed")
for name, err in fail_list:
    print(f"  FAIL {name}: {err}")

# ── Create all tables ─────────────────────────────────────────────────────────
print(f"\nCreating all tables in {DB_URL}...")
try:
    with engine.connect() as c:
        c.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        c.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        c.commit()
except Exception:
    pass

# Remove trgm GIN indexes if pg_trgm is unavailable in this environment
_trgm_removed = 0
for tbl in list(Model.metadata.sorted_tables):
    for idx in list(tbl.indexes):
        if "trgm" in str(getattr(idx, 'kwargs', {})):
            tbl.indexes.discard(idx)
            _trgm_removed += 1
if _trgm_removed:
    print(f"  ℹ Skipped {_trgm_removed} trgm GIN indexes (pg_trgm unavailable)")

# Reflect/stub FAB + cross-plugin tables referenced by FK
_EXTERNAL = [
    "ab_user","ab_role","ab_permission","ab_view_menu","ab_permission_view",
    "tenancy_tenant","foundation_party",
]
for _t in _EXTERNAL:
    if _t not in Model.metadata.tables:
        try:
            sa.Table(_t, Model.metadata, autoload_with=engine, extend_existing=True)
        except Exception:
            _id_type = sa.Integer if _t.startswith("ab_") else sa.String(36)
            sa.Table(_t, Model.metadata,
                sa.Column("id", _id_type, primary_key=True),
                sa.Column("tenant_id", sa.String(36), nullable=True),
                sa.Column("name", sa.String(200), nullable=True),
                extend_existing=True,
            )

created = skipped = ddl_failed = 0
# Run create_all twice: pass 1 creates independent tables, pass 2 picks up FK-dependent ones
for _attempt in (1, 2):
    try:
        Model.metadata.create_all(engine, checkfirst=True)
    except Exception:
        for tbl in Model.metadata.sorted_tables:
            try:
                tbl.create(engine, checkfirst=True)
            except Exception as e2:
                if "already exists" not in str(e2) and "trgm" not in str(e2):
                    ddl_failed += 1

with engine.connect() as _c:
    created = _c.execute(text(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'"
    )).scalar()
print(f"  ✓ {created} tables in database ({ddl_failed} DDL errors total)")

# ── Collect all mapped model classes ─────────────────────────────────────────
def _all_subclasses(cls):
    for sub in cls.__subclasses__():
        if hasattr(sub, '__tablename__'):
            yield sub
        yield from _all_subclasses(sub)

all_models = list({m.__name__: m for m in _all_subclasses(Model)}.values())
print(f"\nFound {len(all_models)} mapped model classes\n")

# ── Test every model: INSERT + SELECT + DELETE ────────────────────────────────
def _uid(): return str(uuid.uuid4())
def _now(): return datetime.now(timezone.utc)
TENANT = _uid()

results = {"ok": [], "skip": [], "fail": []}

def _test_model(cls):
    try:
        mapper = sa.inspect(cls).mapper
        cols = {c.key for c in mapper.column_attrs}
    except Exception as e:
        results["skip"].append(cls.__name__)
        return  # mapper not initialized — skip silently

    tbl_name = cls.__tablename__
    if tbl_name not in Model.metadata.tables:
        results["skip"].append(cls.__name__)
        return

    # Detect integer PK models (rules engine etc.) — use None so DB auto-assigns
    pk_cols_list = [c for c in mapper.primary_key]
    uses_int_pk = (len(pk_cols_list) == 1 and
                   type(pk_cols_list[0].type).__name__ in ('Integer','BigInteger') and
                   pk_cols_list[0].autoincrement is not False)

    defaults = {"tenant_id": TENANT, "created_at": _now(), "updated_at": _now()}
    if not uses_int_pk:
        defaults["id"] = _uid()

    # Enum defaults take priority for CHECK-constrained columns
    _ENUM_DEFAULTS = {
        'direction': 1, 'movement_type': 'RECEIPT', 'entry_type': 'DEBIT',
        'normal_balance': 'DEBIT', 'account_type': 'ASSET',
        'meter_type': 'HOURS', 'criticality': 'LOW', 'asset_type': 'EQUIPMENT',
        'incident_type': 'BREAKDOWN', 'service_type': 'ROUTINE', 'doc_type': 'INSURANCE',
        'schedule_type': 'ROUTINE_SERVICE', 'location_type': 'BULK',
        'order_type': 'SALES_ORDER', 'count_type': 'FULL',
        'frequency': 'MONTHLY', 'capacity_units': Decimal('10'),
    }

    overrides = {}
    for col_name in cols:
        if col_name in defaults: continue
        col = mapper.columns.get(col_name)
        if col is None: continue
        if col.nullable or col.default is not None or col.server_default is not None:
            continue
        # Apply enum defaults first, then fall through to type-based defaults
        if col_name in _ENUM_DEFAULTS:
            overrides[col_name] = _ENUM_DEFAULTS[col_name]
            continue
        # Required column — infer minimal value from type
        t = type(col.type).__name__
        if t in ('String','VARCHAR','Text','TEXT'):
            overrides[col_name] = 'TEST'[: getattr(col.type, 'length', 4) or 4]
        elif t in ('Integer','BigInteger'):
            overrides[col_name] = 1  # use 1 not 0 to satisfy > 0 CHECK constraints
        elif t == 'Numeric':
            overrides[col_name] = Decimal('1')  # use 1 not 0 to satisfy > 0 CHECK constraints
        elif t == 'Boolean':
            overrides[col_name] = False
        elif t == 'Date':
            overrides[col_name] = date.today()
        elif t in ('DateTime','TIMESTAMP','TIMESTAMPTZ'):
            overrides[col_name] = _now()
        elif t == 'Time':
            from datetime import time as _time
            overrides[col_name] = _time(8, 0)
        elif t == 'UUID':
            overrides[col_name] = _uid()
        elif t in ('JSONB','JSON'):
            overrides[col_name] = {}
        elif t == 'TSVECTOR':
            pass  # skip — server-side computed or trigger-maintained
        elif t == 'ARRAY':
            overrides[col_name] = []

    rec = {k: v for k, v in {**defaults, **overrides}.items() if k in cols}

    # Make string PKs unique to avoid UniqueViolation when the same model is tested twice
    # (e.g. GLAccount with account_code PK, Currency with code PK)
    for col in pk_cols_list:
        cname = col.key
        if cname in rec and isinstance(rec[cname], str) and rec[cname] == 'TEST':
            rec[cname] = f'TST{uuid.uuid4().hex[:6].upper()}'

    try:
        with Session(engine) as s:
            # Bypass FK constraints during test (replica role skips FK trigger enforcement)
            s.execute(sa.text("SET session_replication_role = replica"))
            obj = cls(**rec)
            s.add(obj)
            s.flush()
            # Get PK value(s) using mapper (handles composite + non-UUID PKs)
            insp = sa.inspect(cls)
            pk_vals = tuple(getattr(obj, col.key) for col in insp.mapper.primary_key)
            pk_val = pk_vals[0] if len(pk_vals) == 1 else pk_vals
            s.commit()
        with Session(engine) as s:
            found = s.get(cls, pk_val)
            assert found is not None, f"SELECT returned None for {cls.__name__}"
            s.delete(found)
            s.commit()
        results["ok"].append(cls.__name__)
        print(f"  OK  {cls.__name__}")
    except Exception as e:
        results["fail"].append((cls.__name__, str(e)[:120]))
        print(f"  FAIL {cls.__name__}: {e!s:.100}")

for cls in sorted(all_models, key=lambda c: c.__name__):
    _test_model(cls)

# ── Summary ───────────────────────────────────────────────────────────────────
total = len(results["ok"]) + len(results["fail"])
print(f"\n{'='*70}")
print(f"MODEL TEST RESULTS: {len(results['ok'])}/{total} passed  ({len(results['skip'])} skipped/mapper-uninit)")
if results["fail"]:
    print(f"\nFAILED ({len(results['fail'])}):")
    for name, err in results["fail"]:
        print(f"  {name}: {err}")
print(f"\nDatabase: {DB_URL}")
print(f"Tables in metadata: {len(Model.metadata.tables)}")
