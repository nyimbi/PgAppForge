"""
pgappforge/env_pipeline/deployment_log.py

Deployment audit log — records every deploy / promote event to
``pgaf_deployment_log``.  All writes are best-effort (non-fatal).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ── Public API ────────────────────────────────────────────────────────────────

def log_deployment(
	environment: str,
	action: str,
	*,
	source_env: str = "",
	notes: str = "",
	session=None,
) -> str | None:
	"""Record a deployment event to ``pgaf_deployment_log``.

	Args:
		environment: Target environment name (e.g. "production").
		action: ``"SUCCESS"`` | ``"PROMOTE"`` | ``"DRY_RUN"`` | ``"FAILED"``.
		source_env: For ``PROMOTE`` actions, the environment promoted from.
		notes: Free-text notes about the deployment.
		session: Optional SQLAlchemy session; inferred from app context if None.

	Returns:
		The UUID7 string of the new log row, or ``None`` on failure.
	"""
	try:
		if session is None:
			from flask import current_app
			session = current_app.appbuilder.get_session()

		from uuid6 import uuid7
		entry_id = str(uuid7())

		session.execute(
			sa.text(
				"INSERT INTO pgaf_deployment_log "
				"(id, environment, action, source_env, notes, deployed_at, deployed_by) "
				"VALUES (:id, :env, :action, :src, :notes, :ts, :by)"
			),
			{
				"id": entry_id,
				"env": environment,
				"action": action,
				"src": source_env,
				"notes": notes,
				"ts": datetime.now(timezone.utc),
				"by": _current_user_email(),
			},
		)
		session.commit()
		return entry_id

	except Exception as exc:
		log.debug("Deployment log write failed (non-fatal): %s", exc)
		return None


def create_deployment_log_table(engine) -> None:
	"""Create ``pgaf_deployment_log`` table if it does not already exist.

	Safe to call on every app startup.
	"""
	ddl = """
	CREATE TABLE IF NOT EXISTS pgaf_deployment_log (
		id           VARCHAR(36)   PRIMARY KEY,
		environment  VARCHAR(50)   NOT NULL,
		action       VARCHAR(20)   NOT NULL,
		source_env   VARCHAR(50),
		notes        TEXT,
		deployed_at  TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
		deployed_by  VARCHAR(255)
	);
	CREATE INDEX IF NOT EXISTS ix_pgaf_deploy_env_ts
		ON pgaf_deployment_log (environment, deployed_at DESC);
	"""
	with engine.begin() as conn:
		conn.execute(sa.text(ddl))


# ── Internals ─────────────────────────────────────────────────────────────────

def _current_user_email() -> str:
	"""Return the authenticated user's email, or ``'system'``."""
	try:
		from flask_login import current_user  # type: ignore[import-untyped]
		if current_user and current_user.is_authenticated:
			return getattr(current_user, "email", "system") or "system"
	except Exception:
		pass
	return "system"
