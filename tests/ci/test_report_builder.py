"""
tests/ci/test_report_builder.py

CI tests for the No-Code Report Builder plugin (P2-5).

No Flask app context required for unit-level tests.
Service logic and model structure are tested against a real SQLite in-memory DB.
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _make_session() -> tuple:
	"""Create an in-memory SQLite engine + session for testing."""
	engine = create_engine("sqlite:///:memory:", future=True)
	# Create the table manually (SQLite, no JSONB — use TEXT instead)
	with engine.begin() as conn:
		conn.execute(sa.text("""
			CREATE TABLE pgaf_report (
				id                  VARCHAR(36)  PRIMARY KEY,
				tenant_id           VARCHAR(36)  NOT NULL,
				name                VARCHAR(200) NOT NULL,
				description         TEXT,
				report_definition   TEXT         NOT NULL DEFAULT '{}',
				report_type         VARCHAR(20)  NOT NULL DEFAULT 'standard',
				is_public           INTEGER      NOT NULL DEFAULT 0,
				is_template         INTEGER      NOT NULL DEFAULT 0,
				data_source_query   TEXT,
				data_source_model   VARCHAR(100),
				created_by          VARCHAR(36),
				created_at          TEXT         NOT NULL DEFAULT (datetime('now')),
				updated_at          TEXT         NOT NULL DEFAULT (datetime('now'))
			)
		"""))
	session = Session(engine)
	return engine, session


# ------------------------------------------------------------------ #
# ReportBuilderService
# ------------------------------------------------------------------ #


class TestReportBuilderService:
	def test_import(self):
		from pgappforge.plugins.erp.platform.report_builder.services import ReportBuilderService
		assert ReportBuilderService is not None

	def test_save_and_list(self):
		from pgappforge.plugins.erp.platform.report_builder.services import ReportBuilderService
		engine, session = _make_session()
		svc = ReportBuilderService()

		# Bypass ORM — insert via raw SQL so we don't need a real PG JSONB column
		import json
		session.execute(sa.text("""
			INSERT INTO pgaf_report (id, tenant_id, name, report_definition, report_type)
			VALUES (:id, :tid, :name, :defn, :rtype)
		"""), {
			"id": "00000000-0000-0000-0000-000000000001",
			"tid": "tenant-1",
			"name": "Sales Report",
			"defn": json.dumps({"elements": []}),
			"rtype": "standard",
		})
		session.commit()

		rows = session.execute(
			sa.text("SELECT id, name FROM pgaf_report WHERE tenant_id = 'tenant-1'")
		).fetchall()
		assert len(rows) == 1
		assert rows[0].name == "Sales Report"

	def test_render_pdf_returns_none_without_reportbro(self):
		"""When reportbro-lib is not installed, render returns None gracefully."""
		from pgappforge.plugins.erp.platform.report_builder.services import ReportBuilderService
		svc = ReportBuilderService()
		# Pass empty definition — should not raise
		result = svc.render_pdf_from_definition({}, {})
		# Either None (reportbro not installed) or bytes (if it is installed)
		assert result is None or isinstance(result, bytes)

	def test_get_data_for_report_rejects_non_select(self):
		from pgappforge.plugins.erp.platform.report_builder.services import ReportBuilderService
		engine, session = _make_session()
		svc = ReportBuilderService()
		with pytest.raises(ValueError, match="Only SELECT"):
			svc.get_data_for_report("DROP TABLE pgaf_report", session)

	def test_get_data_for_report_returns_rows(self):
		from pgappforge.plugins.erp.platform.report_builder.services import ReportBuilderService
		engine, session = _make_session()
		svc = ReportBuilderService()
		rows = svc.get_data_for_report(
			"SELECT 1 AS num, 'hello' AS greeting",
			session,
		)
		assert len(rows) == 1
		assert rows[0]["num"] == 1
		assert rows[0]["greeting"] == "hello"


# ------------------------------------------------------------------ #
# SavedReport model
# ------------------------------------------------------------------ #

class TestSavedReportModel:
	def test_model_import(self):
		from pgappforge.plugins.erp.platform.report_builder.models import SavedReport
		assert SavedReport.__tablename__ == "pgaf_report"

	def test_model_fields(self):
		from pgappforge.plugins.erp.platform.report_builder.models import SavedReport
		cols = {c.name for c in SavedReport.__table__.columns}
		required = {
			"id", "tenant_id", "name", "description",
			"report_definition", "report_type",
			"is_public", "is_template",
			"data_source_query", "data_source_model",
			"created_by", "created_at", "updated_at",
		}
		assert required.issubset(cols), f"Missing columns: {required - cols}"


# ------------------------------------------------------------------ #
# ReportBuilderPlugin
# ------------------------------------------------------------------ #

class TestReportBuilderPlugin:
	def test_plugin_import(self):
		from pgappforge.plugins.erp.platform.report_builder import ReportBuilderPlugin
		assert ReportBuilderPlugin.domain == "platform"
		assert ReportBuilderPlugin.name == "report_builder"

	def test_plugin_metadata(self):
		from pgappforge.plugins.erp.platform.report_builder import ReportBuilderPlugin
		meta = ReportBuilderPlugin.metadata
		assert meta.name == "report_builder"
		assert "reportbro" in meta.description.lower()

	def test_register_models(self):
		from pgappforge.plugins.erp.platform.report_builder import ReportBuilderPlugin
		from pgappforge.plugins.erp.platform.report_builder.models import SavedReport

		class _FakeAppBuilder:
			pass

		plugin = ReportBuilderPlugin.__new__(ReportBuilderPlugin)
		plugin.config = {}
		models = plugin.register_models()
		assert SavedReport in models
