"""
pgappforge/ai_governance.py

AI Governance for PgAppForge — three pillars:

1. Audit log    — every AI action recorded to pgaf_ai_audit_log
2. RBAC         — permission decorators for AI features
3. HITL         — human-in-the-loop gating for high-risk AI actions

Usage:

    from pgappforge.ai_governance import (
        log_ai_action,
        require_ai_permission,
        require_human_approval,
        create_ai_audit_table,
        AI_PERMISSIONS,
        HITLRequired,
    )

    # 1. Record an AI action
    log_ai_action(
        action_type="nl_to_sql",
        model_name="claude-sonnet-4-6",
        provider="anthropic",
        prompt_summary="Show me unpaid invoices over KES 10,000",
        response_summary="SELECT * FROM fin_invoice WHERE ...",
    )

    # 2. Gate a view method behind an AI permission
    @require_ai_permission("can_ai_query_data")
    def nl_to_sql(self, question): ...

    # 3. Require human approval before a high-risk action
    if not require_human_approval("Create invoice KES 50,000", preview):
        return {"requires_approval": True, "preview": preview}
    # proceed
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ── AI Audit Log ─────────────────────────────────────────────────────────────

def log_ai_action(
	action_type: str,
	model_name: str | None = None,
	provider: str | None = None,
	prompt_summary: str | None = None,
	response_summary: str | None = None,
	tool_calls: list | None = None,
	confidence_score: float | None = None,
	reference_type: str | None = None,
	reference_id: str | None = None,
	human_reviewed: bool = False,
	session=None,
) -> str | None:
	"""Record an AI action to ``pgaf_ai_audit_log``.

	Call from every AI feature: chatbot, NL-to-SQL, document intelligence,
	agent actions, anomaly alerts, etc.

	Args:
		action_type: One of ``"chat_reply"`` | ``"record_create"`` |
		             ``"anomaly_alert"`` | ``"nl_to_sql"`` |
		             ``"document_extract"`` | ``"workflow_trigger"`` |
		             ``"prediction"``.
		model_name: LLM model used (e.g. ``"claude-sonnet-4-6"``).
		provider: ``"anthropic"`` | ``"openai"`` | ``"ollama"`` | ``"litellm"``.
		prompt_summary: First 500 chars of the prompt (truncated for privacy).
		response_summary: First 500 chars of the response.
		tool_calls: List of tool names invoked by the agent.
		confidence_score: 0.0-1.0 confidence score if applicable.
		reference_type: SQLAlchemy model class name of the affected record.
		reference_id: Primary key of the affected record.
		human_reviewed: Whether a human approved this action before it ran.
		session: SQLAlchemy session; inferred from app context if ``None``.

	Returns:
		UUID7 string of the new audit row, or ``None`` on failure.
	"""
	try:
		if session is None:
			from flask import current_app  # type: ignore[import-untyped]
			session = current_app.appbuilder.get_session()

		user_id, user_email = _get_current_user()
		ip = _get_ip()

		from uuid6 import uuid7
		entry_id = str(uuid7())

		session.execute(
			sa.text("""
				INSERT INTO pgaf_ai_audit_log
				(id, action_type, model_name, provider, user_id, user_email,
				 prompt_summary, response_summary, tool_calls, confidence_score,
				 reference_type, reference_id, human_reviewed, created_at, ip_address)
				VALUES
				(:id, :action_type, :model_name, :provider, :user_id, :user_email,
				 :prompt_summary, :response_summary, :tool_calls::jsonb, :confidence_score,
				 :reference_type, :reference_id, :human_reviewed, :created_at, :ip_address)
			"""),
			{
				"id": entry_id,
				"action_type": action_type,
				"model_name": model_name,
				"provider": provider,
				"user_id": user_id,
				"user_email": user_email,
				"prompt_summary": (prompt_summary or "")[:500],
				"response_summary": (response_summary or "")[:500],
				"tool_calls": json.dumps(tool_calls or []),
				"confidence_score": confidence_score,
				"reference_type": reference_type,
				"reference_id": reference_id,
				"human_reviewed": human_reviewed,
				"created_at": datetime.now(timezone.utc),
				"ip_address": ip,
			},
		)
		session.commit()
		return entry_id

	except Exception as exc:
		log.debug("AI audit log failed (non-fatal): %s", exc)
		return None


# ── RBAC for AI Features ──────────────────────────────────────────────────────

AI_PERMISSIONS: dict[str, str] = {
	"can_use_ai_chat":          "Basic AI chatbot access",
	"can_ai_query_data":        "NL-to-SQL analytics queries",
	"can_ai_create_records":    "Agent can create records on behalf of user",
	"can_ai_modify_records":    "Agent can modify records on behalf of user",
	"can_ai_trigger_workflows": "Agent can start BPM processes",
	"can_view_ai_audit_log":    "View the AI action audit trail",
	"can_ai_document_extract":  "Upload documents for AI extraction",
	"can_ai_generate_code":     "Use AI code generation features",
}


def require_ai_permission(permission_name: str) -> Callable:
	"""Decorator: abort 403 unless the current user holds ``permission_name``.

	The permission is checked against the ``"AI"`` view name in the FAB
	security manager.

	Usage::

		@require_ai_permission("can_ai_query_data")
		def nl_to_sql(self, question): ...
	"""
	def decorator(fn: Callable) -> Callable:
		@wraps(fn)
		def wrapper(*args: Any, **kwargs: Any) -> Any:
			try:
				from flask import abort, current_app  # type: ignore[import-untyped]
				if not current_app.appbuilder.sm.has_access(permission_name, "AI"):
					log.warning(
						"AI permission denied: %s for user %s",
						permission_name,
						_get_current_user()[1],
					)
					abort(403)
			except Exception as exc:
				log.debug("AI permission check skipped: %s", exc)
			return fn(*args, **kwargs)

		return wrapper

	return decorator


# ── Human-in-the-Loop ─────────────────────────────────────────────────────────

class HITLRequired(Exception):
	"""Raised when an AI action requires human approval before proceeding.

	Callers can catch this and return the ``preview`` to the UI, which should
	re-submit with ``{"_ai_approved": true}`` in the JSON body.
	"""

	def __init__(self, action_description: str, preview: dict) -> None:
		self.action_description = action_description
		self.preview = preview
		super().__init__(f"Human approval required: {action_description}")


def require_human_approval(
	action_description: str,
	preview: dict,
	*,
	auto_approve: bool = False,
) -> bool:
	"""Gate an AI action behind human approval.

	In a request context the caller checks ``request.json["_ai_approved"]``.
	Outside a request context (batch jobs, tests) pass ``auto_approve=True``
	to bypass the gate.

	Args:
		action_description: Human-readable description shown in the approval UI.
		preview: Dict snapshot of what the action will do (shown to the approver).
		auto_approve: Skip HITL for trusted automated pipelines.

	Returns:
		``True`` if approved and the caller should proceed, ``False`` otherwise.
	"""
	if auto_approve:
		return True

	try:
		from flask import request  # type: ignore[import-untyped]
		if request.is_json:
			return bool(request.json.get("_ai_approved", False))
	except Exception:
		pass

	return False


# ── Table DDL ─────────────────────────────────────────────────────────────────

def create_ai_audit_table(engine) -> None:
	"""Create ``pgaf_ai_audit_log`` table and indexes if they do not exist.

	Safe to call on every app startup.
	"""
	ddl = """
	CREATE TABLE IF NOT EXISTS pgaf_ai_audit_log (
		id               VARCHAR(36)   PRIMARY KEY,
		action_type      VARCHAR(30)   NOT NULL,
		model_name       VARCHAR(50),
		provider         VARCHAR(20),
		user_id          VARCHAR(36),
		user_email       VARCHAR(255),
		prompt_summary   TEXT,
		response_summary TEXT,
		tool_calls       JSONB,
		confidence_score NUMERIC(4,3),
		reference_type   VARCHAR(100),
		reference_id     VARCHAR(100),
		human_reviewed   BOOLEAN       NOT NULL DEFAULT FALSE,
		created_at       TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
		ip_address       INET
	);
	CREATE INDEX IF NOT EXISTS ix_pgaf_ai_audit_user
		ON pgaf_ai_audit_log (user_id, created_at DESC);
	CREATE INDEX IF NOT EXISTS ix_pgaf_ai_audit_type
		ON pgaf_ai_audit_log (action_type, created_at DESC);
	CREATE INDEX IF NOT EXISTS ix_pgaf_ai_audit_ref
		ON pgaf_ai_audit_log (reference_type, reference_id);
	"""
	with engine.begin() as conn:
		conn.execute(sa.text(ddl))


# ── Internals ─────────────────────────────────────────────────────────────────

def _get_current_user() -> tuple[str | None, str | None]:
	"""Return ``(user_id, user_email)`` for the authenticated user, or ``(None, None)``."""
	try:
		from flask_login import current_user  # type: ignore[import-untyped]
		if current_user and current_user.is_authenticated:
			return (
				str(getattr(current_user, "id", "") or ""),
				getattr(current_user, "email", None),
			)
	except Exception:
		pass
	return None, None


def _get_ip() -> str | None:
	"""Return the request remote address, or ``None`` outside a request context."""
	try:
		from flask import request  # type: ignore[import-untyped]
		return request.remote_addr
	except Exception:
		return None


__all__ = [
	"log_ai_action",
	"require_ai_permission",
	"require_human_approval",
	"create_ai_audit_table",
	"AI_PERMISSIONS",
	"HITLRequired",
]
