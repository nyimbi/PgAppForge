"""
tests/ci/test_ai_governance.py

CI tests for pgappforge.ai_governance — audit log, RBAC decorator,
HITL gating, table DDL.  No Flask app context required for most tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from pgappforge.ai_governance import (
	AI_PERMISSIONS,
	HITLRequired,
	create_ai_audit_table,
	log_ai_action,
	require_ai_permission,
	require_human_approval,
)


# ── AI_PERMISSIONS registry ───────────────────────────────────────────────────

class TestAiPermissions:
	def test_all_eight_permissions_defined(self):
		assert len(AI_PERMISSIONS) == 8

	def test_permission_keys_are_snake_case(self):
		for key in AI_PERMISSIONS:
			assert key.startswith("can_"), f"unexpected permission key: {key}"

	def test_all_permissions_have_descriptions(self):
		for key, desc in AI_PERMISSIONS.items():
			assert desc, f"empty description for {key}"

	def test_known_permissions_present(self):
		required = {
			"can_use_ai_chat",
			"can_ai_query_data",
			"can_ai_create_records",
			"can_ai_modify_records",
			"can_ai_trigger_workflows",
			"can_view_ai_audit_log",
			"can_ai_document_extract",
			"can_ai_generate_code",
		}
		assert required == set(AI_PERMISSIONS)


# ── HITLRequired exception ────────────────────────────────────────────────────

class TestHITLRequired:
	def test_is_exception_subclass(self):
		assert issubclass(HITLRequired, Exception)

	def test_stores_action_description(self):
		exc = HITLRequired("Delete invoice #42", {"invoice_id": "42"})
		assert exc.action_description == "Delete invoice #42"

	def test_stores_preview(self):
		preview = {"vendor": "Safaricom", "amount_kes": 50000}
		exc = HITLRequired("Create payment", preview)
		assert exc.preview == preview

	def test_str_contains_description(self):
		exc = HITLRequired("trigger workflow", {})
		assert "trigger workflow" in str(exc)
		assert "Human approval required" in str(exc)

	def test_can_be_raised_and_caught(self):
		with pytest.raises(HITLRequired) as exc_info:
			raise HITLRequired("test action", {"key": "value"})
		assert exc_info.value.action_description == "test action"


# ── require_human_approval ────────────────────────────────────────────────────

class TestRequireHumanApproval:
	def test_auto_approve_bypasses_gate(self):
		assert require_human_approval("any action", {}, auto_approve=True) is True

	def test_returns_false_outside_request_context(self):
		# no Flask request context
		assert require_human_approval("delete all", {"count": 9999}) is False

	def test_returns_false_with_empty_preview(self):
		assert require_human_approval("noop", {}) is False


# ── require_ai_permission decorator ──────────────────────────────────────────

class TestRequireAiPermission:
	def test_returns_decorator(self):
		dec = require_ai_permission("can_use_ai_chat")
		assert callable(dec)

	def test_wrapped_function_preserves_name(self):
		def my_view():
			return "data"

		wrapped = require_ai_permission("can_ai_query_data")(my_view)
		assert wrapped.__name__ == "my_view"

	def test_wrapped_function_executes_outside_app_context(self):
		# Outside an app context the permission check is skipped; fn still runs
		def ai_fn():
			return "result"

		wrapped = require_ai_permission("can_use_ai_chat")(ai_fn)
		assert wrapped() == "result"

	def test_accepts_any_registered_permission(self):
		for perm in AI_PERMISSIONS:
			dec = require_ai_permission(perm)
			fn = dec(lambda: perm)
			assert fn() == perm

	def test_works_on_method_with_self(self):
		class MyView:
			@require_ai_permission("can_ai_generate_code")
			def generate(self):
				return "code"

		view = MyView()
		assert view.generate() == "code"


# ── log_ai_action (no DB, graceful) ──────────────────────────────────────────

class TestLogAiAction:
	def test_returns_none_outside_app_context(self):
		# No Flask app — should return None without raising
		result = log_ai_action(
			action_type="chat_reply",
			model_name="claude-sonnet-4-6",
			provider="anthropic",
			prompt_summary="Hello, world",
		)
		assert result is None

	def test_accepts_all_parameters(self):
		result = log_ai_action(
			action_type="nl_to_sql",
			model_name="gpt-4o",
			provider="openai",
			prompt_summary="Show unpaid invoices",
			response_summary="SELECT * FROM fin_invoice WHERE paid = false",
			tool_calls=["execute_sql"],
			confidence_score=0.92,
			reference_type="Invoice",
			reference_id="inv-001",
			human_reviewed=True,
		)
		assert result is None  # non-fatal outside app context

	def test_does_not_raise_on_bad_session(self):
		# Passing a broken object as session should be caught
		result = log_ai_action("prediction", session=object())
		assert result is None


# ── create_ai_audit_table DDL ─────────────────────────────────────────────────

PG_TEST_URI = __import__("os").environ.get("PG_TEST_URI")


@pytest.mark.skipif(not PG_TEST_URI, reason="PG_TEST_URI not set — PostgreSQL required")
class TestCreateAiAuditTable:
	"""PostgreSQL-only DDL tests.  Set PG_TEST_URI to run."""

	def test_table_created(self):
		import os
		import sqlalchemy as sa

		engine = sa.create_engine(os.environ["PG_TEST_URI"])
		try:
			create_ai_audit_table(engine)
			with engine.connect() as conn:
				row = conn.execute(
					sa.text("SELECT to_regclass('pgaf_ai_audit_log')")
				).scalar()
			assert row is not None
		finally:
			engine.dispose()

	def test_indexes_created(self):
		import os
		import sqlalchemy as sa

		engine = sa.create_engine(os.environ["PG_TEST_URI"])
		try:
			create_ai_audit_table(engine)
			with engine.connect() as conn:
				rows = conn.execute(sa.text(
					"SELECT indexname FROM pg_indexes "
					"WHERE tablename = 'pgaf_ai_audit_log'"
				)).fetchall()
			index_names = {r[0] for r in rows}
			assert "ix_pgaf_ai_audit_user" in index_names
			assert "ix_pgaf_ai_audit_type" in index_names
			assert "ix_pgaf_ai_audit_ref" in index_names
		finally:
			engine.dispose()

	def test_idempotent_on_second_call(self):
		import os
		import sqlalchemy as sa

		engine = sa.create_engine(os.environ["PG_TEST_URI"])
		try:
			create_ai_audit_table(engine)
			create_ai_audit_table(engine)  # must not raise
		finally:
			engine.dispose()
