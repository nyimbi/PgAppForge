"""
pgappforge/plugins/erp/platform/report_builder/services.py

ReportBuilderService — server-side PDF rendering via reportbro-lib (MIT).

Install: pip install reportbro-lib
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class ReportBuilderService:
	"""Generate PDF reports from saved ReportBro definitions.

	Uses reportbro-lib (MIT) for PDF rendering.  Falls back gracefully when
	the library is not installed.

	pip install reportbro-lib
	"""

	# ------------------------------------------------------------------ #
	# Public API
	# ------------------------------------------------------------------ #

	def render_pdf(
		self,
		report_id: str,
		tenant_id: str,
		session,
		data_override: dict | None = None,
	) -> bytes | None:
		"""Render a saved report as PDF bytes.

		Args:
			report_id:     PK of SavedReport row.
			tenant_id:     Tenant scope — prevents cross-tenant reads.
			session:       SQLAlchemy Session.
			data_override: If provided, use this data dict instead of
			               fetching from the report's data_source_*.

		Returns:
			PDF bytes or None if reportbro-lib is not installed.

		Raises:
			ValueError: Report not found for this tenant.
		"""
		from sqlalchemy import select
		from pgappforge.plugins.erp.platform.report_builder.models import SavedReport

		report = session.execute(
			select(SavedReport).where(
				SavedReport.id == report_id,
				SavedReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if report is None:
			raise ValueError(f"Report {report_id!r} not found for tenant {tenant_id!r}")

		data = data_override or self._get_report_data(report, session, tenant_id)
		return self._render_with_reportbro(report.report_definition, data)

	def render_pdf_from_definition(
		self,
		report_definition: dict,
		data: dict,
	) -> bytes | None:
		"""Render a report definition directly without persisting it.

		Useful for live preview from the designer.
		"""
		return self._render_with_reportbro(report_definition, data)

	def get_data_for_report(
		self,
		sql_query: str,
		session,
		params: dict | None = None,
	) -> list[dict]:
		"""Execute a SELECT query and return rows as list of dicts.

		Used by the designer's data-source preview panel.
		Only SELECT statements are permitted.

		Returns up to 1 000 rows (hard cap for designer safety).
		"""
		import sqlalchemy as sa

		if not sql_query.upper().strip().startswith("SELECT"):
			raise ValueError("Only SELECT queries are allowed for report data sources")

		try:
			result = session.execute(sa.text(sql_query), params or {})
			cols = list(result.keys())
			return [dict(zip(cols, row)) for row in result.fetchmany(1000)]
		except Exception as exc:
			log.warning("Report data query failed: %s", exc)
			return []

	def list_reports(
		self,
		tenant_id: str,
		session,
		report_type: str | None = None,
		include_templates: bool = True,
	) -> list[dict]:
		"""Return lightweight metadata list for the report gallery."""
		import sqlalchemy as sa
		from pgappforge.plugins.erp.platform.report_builder.models import SavedReport

		q = sa.select(
			SavedReport.id,
			SavedReport.name,
			SavedReport.description,
			SavedReport.report_type,
			SavedReport.is_public,
			SavedReport.is_template,
			SavedReport.created_at,
			SavedReport.updated_at,
		).where(SavedReport.tenant_id == tenant_id)

		if report_type:
			q = q.where(SavedReport.report_type == report_type)
		if not include_templates:
			q = q.where(SavedReport.is_template == False)  # noqa: E712

		q = q.order_by(SavedReport.updated_at.desc())

		rows = session.execute(q).all()
		return [
			{
				"id": r.id,
				"name": r.name,
				"description": r.description,
				"report_type": r.report_type,
				"is_public": r.is_public,
				"is_template": r.is_template,
				"created_at": r.created_at.isoformat() if r.created_at else None,
				"updated_at": r.updated_at.isoformat() if r.updated_at else None,
			}
			for r in rows
		]

	def save_report(
		self,
		tenant_id: str,
		name: str,
		report_definition: dict,
		session,
		report_id: str | None = None,
		description: str | None = None,
		report_type: str = "standard",
		is_public: bool = False,
		is_template: bool = False,
		data_source_query: str | None = None,
		data_source_model: str | None = None,
		created_by: str | None = None,
	) -> str:
		"""Upsert a SavedReport.  Returns the report id."""
		import sqlalchemy as sa
		from pgappforge.plugins.erp.platform.report_builder.models import SavedReport

		if report_id:
			existing = session.execute(
				sa.select(SavedReport).where(
					SavedReport.id == report_id,
					SavedReport.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if existing:
				existing.name = name
				existing.description = description
				existing.report_definition = report_definition
				existing.report_type = report_type
				existing.is_public = is_public
				existing.is_template = is_template
				existing.data_source_query = data_source_query
				existing.data_source_model = data_source_model
				session.flush()
				return existing.id

		report = SavedReport(
			tenant_id=tenant_id,
			name=name,
			description=description,
			report_definition=report_definition,
			report_type=report_type,
			is_public=is_public,
			is_template=is_template,
			data_source_query=data_source_query,
			data_source_model=data_source_model,
			created_by=created_by,
		)
		session.add(report)
		session.flush()
		return report.id

	# ------------------------------------------------------------------ #
	# Internal helpers
	# ------------------------------------------------------------------ #

	def _render_with_reportbro(
		self,
		report_definition: dict,
		data: dict,
	) -> bytes | None:
		"""Delegate to reportbro-lib for actual PDF generation."""
		try:
			from reportbro import Report, ReportBroError  # type: ignore[import]
		except ImportError:
			log.info(
				"reportbro-lib not installed — PDF generation unavailable. "
				"pip install reportbro-lib"
			)
			return None

		try:
			rpt = Report(report_definition, data)
			if rpt.errors:
				log.error("ReportBro validation errors: %s", rpt.errors)
				return None
			return rpt.generate_pdf()
		except ReportBroError as exc:
			log.error("ReportBro render error: %s", exc)
			return None
		except Exception as exc:
			log.error("ReportBro unexpected failure: %s", exc)
			return None

	def _get_report_data(self, report, session, tenant_id: str) -> dict:
		"""Fetch data for the report from its configured data source."""
		if report.data_source_query:
			try:
				rows = self.get_data_for_report(report.data_source_query, session)
				return {"rows": rows}
			except Exception as exc:
				log.warning("Report data_source_query failed: %s", exc)
				return {"rows": []}

		if report.data_source_model:
			# Attempt to import and query the named model class
			try:
				from pgappforge.models.sqla import Model
				import sqlalchemy as sa
				# Walk all mapped subclasses to find by __name__
				for mapper in Model.registry.mappers:
					cls = mapper.class_
					if cls.__name__ == report.data_source_model:
						q = sa.select(cls)
						# Scope to tenant if the model has tenant_id
						if hasattr(cls, "tenant_id"):
							q = q.where(cls.tenant_id == tenant_id)
						rows = session.execute(q.limit(5000)).scalars().all()
						return {"rows": [
							{c.key: getattr(r, c.key) for c in sa.inspect(cls).mapper.column_attrs}
							for r in rows
						]}
			except Exception as exc:
				log.warning("Report data_source_model lookup failed: %s", exc)
			return {"rows": []}

		return {}


def create_report_tables(engine) -> None:
	"""Create pgaf_report table DDL.  Call once at app startup."""
	import sqlalchemy as sa
	with engine.begin() as conn:
		conn.execute(sa.text("""
			CREATE TABLE IF NOT EXISTS pgaf_report (
				id                  VARCHAR(36)   PRIMARY KEY,
				tenant_id           VARCHAR(36)   NOT NULL,
				name                VARCHAR(200)  NOT NULL,
				description         TEXT,
				report_definition   JSONB         NOT NULL DEFAULT '{}',
				report_type         VARCHAR(20)   NOT NULL DEFAULT 'standard',
				is_public           BOOLEAN       NOT NULL DEFAULT FALSE,
				is_template         BOOLEAN       NOT NULL DEFAULT FALSE,
				data_source_query   TEXT,
				data_source_model   VARCHAR(100),
				created_by          VARCHAR(36),
				created_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
				updated_at          TIMESTAMPTZ   NOT NULL DEFAULT NOW()
			);
			CREATE INDEX IF NOT EXISTS ix_pgaf_report_tenant
				ON pgaf_report(tenant_id);
			CREATE INDEX IF NOT EXISTS ix_pgaf_report_type
				ON pgaf_report(report_type);
		"""))


__all__ = ["ReportBuilderService", "create_report_tables"]
