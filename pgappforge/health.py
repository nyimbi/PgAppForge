"""Liveness and readiness endpoints for PgAppForge.

Split deliberately:

* :func:`liveness`  — "is this process running?"  No dependency checks.  A
  liveness probe that touches the database restarts the whole pod when the
  database blips, turning a dependency outage into an outage of everything.
* :func:`readiness` — "should traffic be routed here?"  Checks PostgreSQL,
  Alembic migration state, the plugin registry, and Redis / the Celery broker
  when they are configured.

Both return machine-readable **codes**, never driver exception text: a health
endpoint that echoes ``str(exc)`` leaks the DSN, the hostname, and the driver
version to anyone who can reach it.
"""
from __future__ import annotations

import logging
from typing import Any

from flask import Blueprint, jsonify
from sqlalchemy import text

log = logging.getLogger(__name__)

#: Failure codes.  Stable strings — dashboards and alerts key off these.
DB_UNREACHABLE = "DB_UNREACHABLE"
MIGRATION_DRIFT = "MIGRATION_DRIFT"
PLUGIN_LOAD_FAILED = "PLUGIN_LOAD_FAILED"
REDIS_UNREACHABLE = "REDIS_UNREACHABLE"
BROKER_UNREACHABLE = "BROKER_UNREACHABLE"

DB_TIMEOUT_MS = 2000


# ── Helpers ───────────────────────────────────────────────────────────────────

def _as_list(value: Any) -> list[Any]:
	if value is None:
		return []
	if isinstance(value, (list, tuple, set)):
		return list(value)
	if isinstance(value, str):
		return [item.strip() for item in value.split(",") if item.strip()]
	return [value]


def _db_session(db: Any) -> Any:
	return getattr(db, "session", db)


def _component(code: str | None, **extra: Any) -> dict[str, Any]:
	"""Build one component entry: ``ok`` when ``code`` is None, else failed."""
	entry: dict[str, Any] = {"status": "ok" if code is None else "error"}
	if code:
		entry["code"] = code
	entry.update(extra)
	return entry


# ── Liveness ──────────────────────────────────────────────────────────────────

def liveness() -> tuple[dict[str, Any], int]:
	"""Process-is-alive probe. Touches nothing external; always 200."""
	return {"status": "alive"}, 200


# ── Readiness checks ──────────────────────────────────────────────────────────

def _check_database(db: Any) -> dict[str, Any]:
	"""``SELECT 1`` with a 2 s statement_timeout so a wedged DB fails fast."""
	try:
		session = _db_session(db)
		if session is None:
			raise RuntimeError("no database session configured")
		session.execute(text("SET LOCAL statement_timeout = :ms"), {"ms": DB_TIMEOUT_MS})
		session.execute(text("SELECT 1")).scalar()
		return _component(None, probe="SELECT 1")
	except Exception as exc:
		log.warning("readiness: database probe failed: %s", type(exc).__name__)
		return _component(DB_UNREACHABLE, probe="SELECT 1")


def _check_migrations(db: Any) -> dict[str, Any]:
	"""Compare ``alembic_version`` against the migration heads on disk."""
	try:
		from alembic.config import Config
		from alembic.script import ScriptDirectory
		from alembic.runtime.migration import MigrationContext

		session = _db_session(db)
		connection = session.connection()
		ctx = MigrationContext.configure(connection)
		heads = set(ctx.get_current_heads())
		if not heads:
			# No alembic_version table / no stamping — nothing to compare.
			return _component(None, heads=[])

		script = ScriptDirectory.from_config(Config("alembic.ini"))
		head_revs = set(script.get_heads())
		drift = heads - head_revs
		if drift:
			log.warning("readiness: migration drift on %d revision(s)", len(drift))
			return _component(MIGRATION_DRIFT, heads=sorted(heads))
		return _component(None, heads=sorted(heads))
	except Exception as exc:
		# alembic.ini missing or unreadable is normal outside a deployed app.
		log.debug("readiness: alembic check skipped: %s", type(exc).__name__)
		return _component(None, skipped=True)


def _check_plugins(app: Any) -> dict[str, Any]:
	"""The plugin registry must load without raising."""
	try:
		appbuilder = getattr(app, "appbuilder", None) or (
			app.extensions.get("appbuilder") if hasattr(app, "extensions") else None
		)
		plugin_manager = getattr(appbuilder, "plugin_manager", None)
		if plugin_manager is None:
			return _component(None, source="erp_registry", registered=0)
		plugins = plugin_manager.list_plugins()
		failed = [p for p in plugins if p.get("status") in {"failed", "error"}]
		if failed:
			return _component(PLUGIN_LOAD_FAILED, failed=len(failed), registered=len(plugins))
		return _component(None, registered=len(plugins))
	except Exception as exc:
		log.warning("readiness: plugin registry failed: %s", type(exc).__name__)
		return _component(PLUGIN_LOAD_FAILED)


def _check_redis(app: Any) -> dict[str, Any]:
	"""Ping Redis only when the app is configured to use it."""
	url = app.config.get("REDIS_URL") or app.config.get("PGAF_REDIS_URL")
	if not url:
		return _component(None, configured=False)
	try:
		import redis
	except ImportError:
		return _component(None, configured=True, skipped=True)
	try:
		redis.from_url(url, socket_connect_timeout=2, socket_timeout=2).ping()
		return _component(None, configured=True)
	except Exception as exc:
		log.warning("readiness: redis ping failed: %s", type(exc).__name__)
		return _component(REDIS_UNREACHABLE, configured=True)


def _check_broker(app: Any) -> dict[str, Any]:
	"""Ping the Celery broker only when Celery is wired to this app."""
	celery_app = app.extensions.get("celery") if hasattr(app, "extensions") else None
	if celery_app is None:
		return _component(None, configured=False)
	try:
		with celery_app.connection_or_acquire() as conn:  # type: ignore[union-attr]
			conn.ensure_connection(max_retries=0, timeout=2)
		return _component(None, configured=True)
	except Exception as exc:
		log.warning("readiness: celery broker ping failed: %s", type(exc).__name__)
		return _component(BROKER_UNREACHABLE, configured=True)


# ── Readiness ─────────────────────────────────────────────────────────────────

def readiness(app: Any, db: Any) -> tuple[dict[str, Any], int]:
	"""Aggregate every dependency check into one verdict.

	Returns a ``(payload, status_code)`` pair; 200 when healthy, 503 otherwise.
	"""
	components = {
		"database":    _check_database(db),
		"migrations":  _check_migrations(db),
		"plugins":     _check_plugins(app),
		"redis":       _check_redis(app),
		"broker":      _check_broker(app),
	}
	failed = sorted({c["code"] for c in components.values() if "code" in c})
	if failed:
		return {"status": "not_ready", "codes": failed, "components": components}, 503
	return {"status": "ready", "codes": [], "components": components}, 200


# ── Blueprint ─────────────────────────────────────────────────────────────────

def _build_blueprint(app: Any, db: Any) -> Blueprint:
	bp = Blueprint("pgappforge_health", __name__)

	@bp.route("/healthz", methods=["GET"], endpoint="healthz")
	def healthz() -> Any:
		return liveness()

	@bp.route("/readyz", methods=["GET"], endpoint="readyz")
	def readyz() -> Any:
		payload, code = readiness(app, db)
		return jsonify(payload), code

	# /health was the pre-4.9 name for the readiness probe.  Keep it so existing
	# orchestrator configs and the nginx healthcheck do not break.
	@bp.route("/health", methods=["GET"], endpoint="health")
	def health() -> Any:
		payload, code = readiness(app, db)
		return jsonify(payload), code

	return bp


def register_health_check(app: Any, db: Any) -> None:
	"""Register ``/healthz``, ``/readyz`` and the legacy ``/health`` alias.

	Idempotent — a second call on the same app is a no-op.

	Args:
		app: Flask application instance.
		db:  Flask-SQLAlchemy instance (or a bare session object).
	"""
	if "pgappforge_health" in app.blueprints:
		return
	app.register_blueprint(_build_blueprint(app, db))


__all__ = [
	"DB_UNREACHABLE",
	"MIGRATION_DRIFT",
	"PLUGIN_LOAD_FAILED",
	"REDIS_UNREACHABLE",
	"BROKER_UNREACHABLE",
	"liveness",
	"readiness",
	"register_health_check",
]
