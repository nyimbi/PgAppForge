"""
pgappforge/multitenancy

Multi-tenancy via PostgreSQL Row Level Security.

Provides database-level tenant isolation for SaaS deployments: every
SQLAlchemy model table that carries a ``tenant_id`` column is locked down at
the PostgreSQL layer so that an application session can only read/write rows
belonging to the active tenant.

Architecture summary
--------------------
- ``rls.py``        — DDL helpers to enable/force RLS + policy CRUD
- ``middleware.py`` — Flask before-request hook to set ``app.tenant_id``
- ``models.py``     — ``Tenant`` ORM model (``pgaf_tenant`` table)

Quick start (app factory)
--------------------------
::

    from pgappforge.multitenancy import (
        setup_multitenancy,   # one-shot convenience
        Tenant,
    )

    with app.app_context():
        setup_multitenancy(app, engine)

    # Or call pieces individually:
    from pgappforge.multitenancy import (
        enable_rls_all_tenant_tables,
        setup_tenant_middleware,
    )
    enable_rls_all_tenant_tables(engine)
    setup_tenant_middleware(app, db_session_factory=db.session)

Per-request context (handled automatically by middleware)
---------------------------------------------------------
::

    from pgappforge.multitenancy import set_tenant_context, clear_tenant_context

    # In a background job:
    with engine.begin() as conn:
        clear_tenant_context(conn)   # SYSTEM bypass
        # … cross-tenant admin queries …
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.multitenancy.rls import (
	RLS_EXCLUDE_TABLES,
	enable_rls_on_table,
	disable_rls_on_table,
	enable_rls_all_tenant_tables,
	get_rls_status,
	set_tenant_context,
	clear_tenant_context,
	get_current_db_tenant,
)
from pgappforge.multitenancy.middleware import (
	setup_tenant_middleware,
	get_current_tenant_id,
	require_tenant,
)
from pgappforge.multitenancy.models import (
	Tenant,
	PLAN_FREE, PLAN_STARTER, PLAN_GROWTH, PLAN_ENTERPRISE,
	VALID_PLANS,
	STATUS_TRIAL, STATUS_ACTIVE, STATUS_SUSPENDED, STATUS_CANCELLED,
	VALID_STATUSES,
)

log = logging.getLogger(__name__)


def setup_multitenancy(
	app: Any,
	engine: Any,
	db_session_factory: Any = None,
	enable_rls: bool = True,
) -> int:
	"""One-shot initialisation for the multi-tenancy layer.

	1. Register Flask before-request middleware.
	2. Enable RLS on all tables with a ``tenant_id`` column (optional).

	Parameters
	----------
	app:
		Flask application instance.
	engine:
		SQLAlchemy engine (PostgreSQL only).
	db_session_factory:
		Optional scoped session (e.g. ``db.session``).
	enable_rls:
		When True (default), calls :func:`enable_rls_all_tenant_tables`.
		Set to False when running outside PostgreSQL (e.g. tests) or
		to defer RLS setup to a migration step.

	Returns
	-------
	int
		Number of tables on which RLS was enabled, or 0 when *enable_rls*
		is False.
	"""
	setup_tenant_middleware(app, db_session_factory=db_session_factory)

	rls_count = 0
	if enable_rls:
		try:
			rls_count = enable_rls_all_tenant_tables(engine)
		except Exception as exc:
			log.warning("multitenancy: RLS bulk setup failed: %s", exc)

	log.info(
		"multitenancy: initialised — RLS active on %d table(s)", rls_count
	)
	return rls_count


__all__ = [
	# rls
	"RLS_EXCLUDE_TABLES",
	"enable_rls_on_table",
	"disable_rls_on_table",
	"enable_rls_all_tenant_tables",
	"get_rls_status",
	"set_tenant_context",
	"clear_tenant_context",
	"get_current_db_tenant",
	# middleware
	"setup_tenant_middleware",
	"get_current_tenant_id",
	"require_tenant",
	# models
	"Tenant",
	"PLAN_FREE", "PLAN_STARTER", "PLAN_GROWTH", "PLAN_ENTERPRISE",
	"VALID_PLANS",
	"STATUS_TRIAL", "STATUS_ACTIVE", "STATUS_SUSPENDED", "STATUS_CANCELLED",
	"VALID_STATUSES",
	# convenience
	"setup_multitenancy",
]
