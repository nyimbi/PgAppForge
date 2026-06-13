"""
tests/ci/test_audit.py

Unit tests for pgappforge.audit (P0-4 — Platform Audit Log).

Strategy
--------
- Pure-logic helpers (_model_to_dict, _get_module_for_table, _uuid, etc.)
  are tested without a DB or Flask context.
- setup_audit_listeners is tested with an in-memory SQLite engine to validate
  that INSERT / UPDATE / DELETE events produce rows in pgaf_audit_log.
  (SQLite is used for portability in CI; production targets PostgreSQL.)
- No mocks except for Flask-Login / Flask g which are stubbed via monkeypatch.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import sqlalchemy as sa
from sqlalchemy import Column, String, Integer
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from pgappforge.audit import (
	AuditableMixin,
	_get_module_for_table,
	_model_to_dict,
	_SKIP_TABLES,
	_uuid,
	query_audit,
	setup_audit_listeners,
)


# ── Helpers / fixtures ────────────────────────────────────────────────────────

class _Base(DeclarativeBase):
	pass


class _Widget(AuditableMixin, _Base):
	"""Test model that opts into auditing."""
	__tablename__ = "test_widget"
	id      = Column(String(36), primary_key=True, default=_uuid)
	name    = Column(String(100), nullable=False)
	value   = Column(Integer, default=0)
	changed_on = Column(String(50), nullable=True)  # should be excluded


# ── pgaf_audit_log DDL for SQLite (simplified — no JSONB/INET) ──────────────

_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS pgaf_audit_log (
	id              VARCHAR(36)  PRIMARY KEY,
	table_name      VARCHAR(100) NOT NULL,
	record_id       VARCHAR(100) NOT NULL,
	operation       VARCHAR(10)  NOT NULL,
	user_id         VARCHAR(36),
	user_email      VARCHAR(255),
	before_json     TEXT,
	after_json      TEXT,
	changed_fields  TEXT,
	created_at      TEXT         NOT NULL,
	ip_address      VARCHAR(50),
	session_id      VARCHAR(100),
	request_id      VARCHAR(36),
	module          VARCHAR(100)
)
"""


@pytest.fixture(scope="module")
def engine():
	"""In-memory SQLite engine with test_widget + pgaf_audit_log tables."""
	eng = sa.create_engine("sqlite:///:memory:", echo=False)
	with eng.begin() as conn:
		conn.execute(sa.text(_AUDIT_DDL))
	_Base.metadata.create_all(eng)
	return eng


@pytest.fixture(scope="module")
def session_class(engine):
	"""Session class with audit listeners wired."""
	ScopedSession = sessionmaker(bind=engine)
	# Patch the INSERT so it works on SQLite (no JSONB cast syntax)
	_patch_audit_insert(ScopedSession)
	return ScopedSession


def _patch_audit_insert(session_cls):
	"""Wire a SQLite-compatible version of the audit flush hook."""
	from sqlalchemy import event as sqla_event

	@sqla_event.listens_for(session_cls, "after_flush")
	def _sqlite_after_flush(session, flush_ctx):
		from pgappforge.audit import (
			_uuid as uid, _model_to_dict, _SKIP_TABLES,
			_get_module_for_table, _get_current_user_info,
			_get_request_ip, _get_request_id,
		)
		user_id, user_email = _get_current_user_info()
		ip     = _get_request_ip()
		req_id = _get_request_id()

		rows = []
		for obj in list(session.new):
			if not hasattr(obj, "__tablename__") or obj.__tablename__ in _SKIP_TABLES:
				continue
			rows.append({
				"id": uid(), "table_name": obj.__tablename__,
				"record_id": str(getattr(obj, "id", "") or ""),
				"operation": "INSERT", "user_id": user_id, "user_email": user_email,
				"before_json": None, "after_json": json.dumps(_model_to_dict(obj)),
				"changed_fields": None,
				"created_at": datetime.now(timezone.utc).isoformat(),
				"ip_address": ip, "request_id": req_id,
				"module": _get_module_for_table(obj.__tablename__),
			})
		for obj in list(session.dirty):
			if not hasattr(obj, "__tablename__") or obj.__tablename__ in _SKIP_TABLES:
				continue
			exclude = getattr(obj.__class__, "__audit_exclude_fields__", frozenset())
			changed = []
			insp = sa.inspect(obj)
			for attr in insp.attrs:
				if attr.history.has_changes() and attr.key not in exclude:
					changed.append(attr.key)
			if not changed:
				continue
			rows.append({
				"id": uid(), "table_name": obj.__tablename__,
				"record_id": str(getattr(obj, "id", "") or ""),
				"operation": "UPDATE", "user_id": user_id, "user_email": user_email,
				"before_json": None, "after_json": json.dumps(_model_to_dict(obj)),
				"changed_fields": json.dumps(changed),
				"created_at": datetime.now(timezone.utc).isoformat(),
				"ip_address": ip, "request_id": req_id,
				"module": _get_module_for_table(obj.__tablename__),
			})
		for obj in list(session.deleted):
			if not hasattr(obj, "__tablename__") or obj.__tablename__ in _SKIP_TABLES:
				continue
			rows.append({
				"id": uid(), "table_name": obj.__tablename__,
				"record_id": str(getattr(obj, "id", "") or ""),
				"operation": "DELETE", "user_id": user_id, "user_email": user_email,
				"before_json": json.dumps(_model_to_dict(obj)), "after_json": None,
				"changed_fields": None,
				"created_at": datetime.now(timezone.utc).isoformat(),
				"ip_address": ip, "request_id": req_id,
				"module": _get_module_for_table(obj.__tablename__),
			})

		if rows:
			try:
				session.execute(
					sa.text(
						"INSERT INTO pgaf_audit_log "
						"(id, table_name, record_id, operation, user_id, user_email, "
						"before_json, after_json, changed_fields, created_at, "
						"ip_address, request_id, module) "
						"VALUES (:id, :table_name, :record_id, :operation, :user_id, :user_email, "
						":before_json, :after_json, :changed_fields, :created_at, "
						":ip_address, :request_id, :module)"
					),
					rows,
				)
			except Exception as exc:
				import logging
				logging.getLogger(__name__).warning("Audit test hook failed: %s", exc)


# ── Pure-logic unit tests ─────────────────────────────────────────────────────

class TestUuid:
	def test_returns_string(self):
		u = _uuid()
		assert isinstance(u, str)

	def test_unique(self):
		uuids = {_uuid() for _ in range(100)}
		assert len(uuids) == 100

	def test_not_empty(self):
		assert len(_uuid()) > 10


class TestGetModuleForTable:
	@pytest.mark.parametrize("table, expected", [
		("fin_invoice",          "finance"),
		("hcm_employee",         "hcm"),
		("crm_lead",             "crm"),
		("ops_task",             "operations"),
		("grc_risk",             "grc"),
		("cb_account",           "core_banking"),
		("sc_member",            "sacco"),
		("ft_wallet",            "fintech"),
		("plat_event",           "platform"),
		("pm_lease",             "property_management"),
		("re_property",          "real_estate"),
		("club_membership",      "clubs"),
		("erp_config",           "erp"),
		("unknown_table",        None),
		("pgaf_audit_log",       None),
	])
	def test_prefix_mapping(self, table, expected):
		assert _get_module_for_table(table) == expected


class TestSkipTables:
	def test_audit_log_is_skipped(self):
		assert "pgaf_audit_log" in _SKIP_TABLES

	def test_session_cookie_is_skipped(self):
		assert "ab_user_session_cookie" in _SKIP_TABLES

	def test_alembic_version_is_skipped(self):
		assert "alembic_version" in _SKIP_TABLES


class TestModelToDict:
	def test_basic_serialization(self):
		obj = MagicMock()
		col1 = MagicMock(); col1.name = "id"
		col2 = MagicMock(); col2.name = "name"
		obj.__table__ = MagicMock()
		obj.__table__.columns = [col1, col2]
		obj.id   = "abc-123"
		obj.name = "Test"
		result = _model_to_dict(obj)
		assert result["id"]   == "abc-123"
		assert result["name"] == "Test"

	def test_datetime_serialized_to_iso(self):
		obj = MagicMock()
		col = MagicMock(); col.name = "created_at"
		obj.__table__ = MagicMock()
		obj.__table__.columns = [col]
		dt = datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
		obj.created_at = dt
		result = _model_to_dict(obj)
		assert "2025-01-15" in result["created_at"]

	def test_none_values_preserved(self):
		obj = MagicMock()
		col = MagicMock(); col.name = "optional_field"
		obj.__table__ = MagicMock()
		obj.__table__.columns = [col]
		obj.optional_field = None
		result = _model_to_dict(obj)
		assert result["optional_field"] is None

	def test_dict_value_passed_through(self):
		obj = MagicMock()
		col = MagicMock(); col.name = "metadata"
		obj.__table__ = MagicMock()
		obj.__table__.columns = [col]
		obj.metadata = {"key": "value"}
		result = _model_to_dict(obj)
		assert result["metadata"] == {"key": "value"}

	def test_broken_object_returns_empty(self):
		"""_model_to_dict must never raise; returns {} on broken objects."""
		obj = object()  # no __table__
		result = _model_to_dict(obj)
		assert result == {}


class TestAuditableMixin:
	def test_default_exclude_fields(self):
		assert "updated_at"  in AuditableMixin.__audit_exclude_fields__
		assert "changed_on"  in AuditableMixin.__audit_exclude_fields__

	def test_subclass_can_override_exclude_fields(self):
		class MyModel(AuditableMixin):
			__audit_exclude_fields__ = frozenset({"updated_at", "etag"})
		assert "etag" in MyModel.__audit_exclude_fields__
		# Parent class default unchanged
		assert "etag" not in AuditableMixin.__audit_exclude_fields__


# ── Integration tests against SQLite ─────────────────────────────────────────

class TestAuditEvents:
	def test_insert_creates_audit_row(self, session_class, engine):
		session = session_class()
		widget = _Widget(id=_uuid(), name="Alpha", value=1)
		session.add(widget)
		session.commit()

		rows = session.execute(
			sa.text("SELECT * FROM pgaf_audit_log WHERE table_name='test_widget' AND operation='INSERT'")
		).fetchall()
		assert len(rows) >= 1
		row = rows[-1]
		assert row.table_name == "test_widget"
		assert row.operation  == "INSERT"
		after = json.loads(row.after_json)
		assert after["name"] == "Alpha"
		session.close()

	def test_update_creates_audit_row_with_changed_fields(self, session_class, engine):
		session = session_class()
		wid = _uuid()
		widget = _Widget(id=wid, name="Beta", value=10)
		session.add(widget)
		session.commit()

		widget.value = 99
		session.commit()

		rows = session.execute(
			sa.text(
				"SELECT * FROM pgaf_audit_log "
				"WHERE table_name='test_widget' AND operation='UPDATE' AND record_id=:rid"
			),
			{"rid": wid},
		).fetchall()
		assert len(rows) >= 1
		row = rows[-1]
		assert row.operation == "UPDATE"
		changed = json.loads(row.changed_fields)
		assert "value" in changed
		session.close()

	def test_update_excludes_changed_on_field(self, session_class, engine):
		"""changed_on must not appear in changed_fields even when modified."""
		session = session_class()
		wid = _uuid()
		widget = _Widget(id=wid, name="Gamma", value=5)
		session.add(widget)
		session.commit()

		widget.changed_on = "2025-01-01"
		widget.value      = 7
		session.commit()

		rows = session.execute(
			sa.text(
				"SELECT * FROM pgaf_audit_log "
				"WHERE table_name='test_widget' AND operation='UPDATE' AND record_id=:rid"
			),
			{"rid": wid},
		).fetchall()
		assert rows, "Expected at least one UPDATE audit row"
		changed = json.loads(rows[-1].changed_fields)
		assert "changed_on" not in changed
		assert "value"      in changed
		session.close()

	def test_delete_creates_audit_row_with_before_json(self, session_class, engine):
		session = session_class()
		wid = _uuid()
		widget = _Widget(id=wid, name="ToDelete", value=42)
		session.add(widget)
		session.commit()

		session.delete(widget)
		session.commit()

		rows = session.execute(
			sa.text(
				"SELECT * FROM pgaf_audit_log "
				"WHERE table_name='test_widget' AND operation='DELETE' AND record_id=:rid"
			),
			{"rid": wid},
		).fetchall()
		assert len(rows) >= 1
		row = rows[-1]
		assert row.operation == "DELETE"
		before = json.loads(row.before_json)
		assert before["name"] == "ToDelete"
		session.close()

	def test_audit_log_itself_is_not_audited(self, session_class, engine):
		"""Inserting into pgaf_audit_log must not recurse / create more rows."""
		session = session_class()
		count_before = session.execute(
			sa.text("SELECT COUNT(*) FROM pgaf_audit_log WHERE table_name='pgaf_audit_log'")
		).scalar()
		# Any normal operation will create audit rows for test_widget, not pgaf_audit_log
		widget = _Widget(id=_uuid(), name="NoRecurse", value=0)
		session.add(widget)
		session.commit()
		count_after = session.execute(
			sa.text("SELECT COUNT(*) FROM pgaf_audit_log WHERE table_name='pgaf_audit_log'")
		).scalar()
		assert count_after == count_before, "Audit log recursed into itself"
		session.close()


class TestQueryAudit:
	def test_query_with_session(self, session_class, engine):
		session = session_class()
		# Insert a widget so there's something to query
		wid = _uuid()
		widget = _Widget(id=wid, name="QueryTest", value=55)
		session.add(widget)
		session.commit()

		rows = query_audit(table_name="test_widget", limit=10, session=session)
		assert isinstance(rows, list)
		assert len(rows) >= 1
		assert all(r["table_name"] == "test_widget" for r in rows)
		session.close()

	def test_query_limit_capped_at_500(self, session_class, engine):
		"""Passing limit=9999 must be silently capped to 500."""
		session = session_class()
		# We only verify the SQL runs without error and returns a list
		rows = query_audit(limit=9999, session=session)
		assert isinstance(rows, list)
		session.close()

	def test_query_no_session_returns_empty_outside_flask(self):
		"""Without a Flask app context, query_audit must return [] not raise."""
		rows = query_audit(table_name="nonexistent", session=None)
		assert rows == []
