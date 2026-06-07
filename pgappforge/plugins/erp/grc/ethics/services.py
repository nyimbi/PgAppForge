"""
pgappforge/plugins/erp/grc/ethics/services.py

EthicsHotlineService — anonymous report submission, case management, dashboard.

Key operations:
  submit_report    — create anonymous report; return raw tracking token (once only)
  check_status     — reporter queries status using raw token
  open_case        — assign report to investigator
  add_case_note    — append note to case timeline
  resolve_case     — record investigation outcome
  get_dashboard    — aggregate counts for compliance dashboard
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("EthicsHotlineService: emit suppressed: %s", exc)


def _hash_token(raw_token: str) -> str:
	return hashlib.sha256(raw_token.encode()).hexdigest()


# ---------------------------------------------------------------------------
# EthicsHotlineService
# ---------------------------------------------------------------------------

class EthicsHotlineService:
	"""Stateless Ethics Hotline service."""

	# ------------------------------------------------------------------
	# submit_report
	# ------------------------------------------------------------------

	def submit_report(
		self,
		description: str,
		category: str,
		tenant_id: str,
		session: Any,
		*,
		occurred_at: date | None = None,
		location: str | None = None,
		severity: str = "MEDIUM",
		reporter_contact: str | None = None,
	) -> dict:
		"""Submit an ethics report.

		Generates a one-time raw tracking token and stores only its SHA-256 hash.
		The raw token is returned once in the response — it CANNOT be recovered
		from the database.

		Returns:
		  {status, tracking_token, message, report_id}
		"""
		from pgappforge.plugins.erp.grc.ethics.models import EthicsReport
		from pgappforge.plugins.erp.grc.ethics.events import EthicsReportSubmittedEvent

		raw_token = secrets.token_urlsafe(32)
		token_hash = _hash_token(raw_token)

		report = EthicsReport(
			tenant_id=tenant_id,
			anonymous_token=token_hash,
			category=category,
			description=description,
			occurred_at=occurred_at,
			location=location,
			severity=severity,
			status="SUBMITTED",
			is_anonymous=reporter_contact is None,
			reporter_contact=reporter_contact,
		)
		session.add(report)
		session.flush()

		_emit(
			EthicsReportSubmittedEvent(
				aggregate_id=report.id,
				aggregate_type="EthicsReport",
				tenant_id=tenant_id,
				report_id=report.id,
				category=category,
				severity=severity,
				# NO PII — description, reporter_contact deliberately omitted
			),
			session,
		)

		return {
			"status": "submitted",
			"report_id": report.id,
			"tracking_token": raw_token,
			"message": (
				"Use this token to check your report status. "
				"Store it safely — we cannot recover it."
			),
		}

	# ------------------------------------------------------------------
	# check_status
	# ------------------------------------------------------------------

	def check_status(
		self,
		raw_token: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Reporter queries their report status using the raw tracking token."""
		from pgappforge.plugins.erp.grc.ethics.models import EthicsReport

		token_hash = _hash_token(raw_token)
		report = session.execute(
			select(EthicsReport).where(
				EthicsReport.anonymous_token == token_hash,
				EthicsReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if report is None:
			return {"status": "not_found"}
		return {
			"status": report.status,
			"last_updated": report.updated_at.isoformat() if report.updated_at else None,
		}

	# ------------------------------------------------------------------
	# open_case
	# ------------------------------------------------------------------

	def open_case(
		self,
		report_id: str,
		assigned_to: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Open an investigation case for *report_id* and assign it."""
		from pgappforge.plugins.erp.grc.ethics.models import EthicsReport, EthicsCase
		from pgappforge.plugins.erp.grc.ethics.events import (
			EthicsCaseOpenedEvent,
			EthicsReportStatusUpdatedEvent,
		)

		report = session.execute(
			select(EthicsReport).where(
				EthicsReport.id == report_id,
				EthicsReport.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if report is None:
			raise ValueError(f"EthicsReport {report_id!r} not found")

		old_status = report.status
		report.status = "UNDER_INVESTIGATION"
		session.flush()

		case = EthicsCase(
			tenant_id=tenant_id,
			report_id=report_id,
			assigned_to=assigned_to,
			opened_at=datetime.now(timezone.utc),
			is_confidential=True,
			timeline=[{
				"ts": datetime.now(timezone.utc).isoformat(),
				"action": "case_opened",
				"by": assigned_to,
			}],
		)
		session.add(case)
		session.flush()

		_emit(
			EthicsReportStatusUpdatedEvent(
				aggregate_id=report.id,
				aggregate_type="EthicsReport",
				tenant_id=tenant_id,
				report_id=report.id,
				old_status=old_status,
				new_status="UNDER_INVESTIGATION",
			),
			session,
		)
		_emit(
			EthicsCaseOpenedEvent(
				aggregate_id=case.id,
				aggregate_type="EthicsCase",
				tenant_id=tenant_id,
				case_id=case.id,
				report_id=report_id,
				assigned_to=assigned_to,
			),
			session,
		)
		return case

	# ------------------------------------------------------------------
	# add_case_note
	# ------------------------------------------------------------------

	def add_case_note(
		self,
		case_id: str,
		note: str,
		by: str,
		session: Any,
	) -> Any:
		"""Append a note to the case timeline JSONB."""
		from pgappforge.plugins.erp.grc.ethics.models import EthicsCase

		case = session.execute(
			select(EthicsCase).where(EthicsCase.id == case_id)
		).scalar_one_or_none()
		if case is None:
			raise ValueError(f"EthicsCase {case_id!r} not found")

		timeline = list(case.timeline or [])
		timeline.append({
			"ts": datetime.now(timezone.utc).isoformat(),
			"action": "note_added",
			"by": by,
			"note": note,
		})
		case.timeline = timeline
		session.flush()
		return case

	# ------------------------------------------------------------------
	# resolve_case
	# ------------------------------------------------------------------

	def resolve_case(
		self,
		case_id: str,
		resolution: str,
		resolution_category: str,
		session: Any,
	) -> Any:
		"""Record investigation outcome and close the case."""
		from pgappforge.plugins.erp.grc.ethics.models import EthicsCase, EthicsReport
		from pgappforge.plugins.erp.grc.ethics.events import (
			EthicsCaseResolvedEvent,
			EthicsReportStatusUpdatedEvent,
		)

		case = session.execute(
			select(EthicsCase).where(EthicsCase.id == case_id)
		).scalar_one_or_none()
		if case is None:
			raise ValueError(f"EthicsCase {case_id!r} not found")

		case.resolution = resolution
		case.resolution_category = resolution_category
		case.closed_at = datetime.now(timezone.utc)

		timeline = list(case.timeline or [])
		timeline.append({
			"ts": datetime.now(timezone.utc).isoformat(),
			"action": "case_resolved",
			"resolution_category": resolution_category,
		})
		case.timeline = timeline
		session.flush()

		# Update report status
		report = session.execute(
			select(EthicsReport).where(EthicsReport.id == case.report_id)
		).scalar_one_or_none()
		if report is not None:
			old_status = report.status
			report.status = "RESOLVED"
			session.flush()
			_emit(
				EthicsReportStatusUpdatedEvent(
					aggregate_id=report.id,
					aggregate_type="EthicsReport",
					tenant_id=case.tenant_id,
					report_id=report.id,
					old_status=old_status,
					new_status="RESOLVED",
				),
				session,
			)

		_emit(
			EthicsCaseResolvedEvent(
				aggregate_id=case.id,
				aggregate_type="EthicsCase",
				tenant_id=case.tenant_id,
				case_id=case.id,
				resolution_category=resolution_category,
			),
			session,
		)
		return case

	# ------------------------------------------------------------------
	# get_dashboard
	# ------------------------------------------------------------------

	def get_dashboard(self, tenant_id: str, session: Any) -> dict:
		"""Return aggregate counts for the ethics compliance dashboard."""
		from pgappforge.plugins.erp.grc.ethics.models import EthicsReport, EthicsCase

		reports = session.execute(
			select(EthicsReport).where(EthicsReport.tenant_id == tenant_id)
		).scalars().all()

		by_status: dict[str, int] = {}
		by_category: dict[str, int] = {}
		by_severity: dict[str, int] = {}

		for r in reports:
			by_status[r.status] = by_status.get(r.status, 0) + 1
			by_category[r.category] = by_category.get(r.category, 0) + 1
			by_severity[r.severity] = by_severity.get(r.severity, 0) + 1

		# Average time to resolve (days)
		resolved_cases = session.execute(
			select(EthicsCase).where(
				EthicsCase.tenant_id == tenant_id,
				EthicsCase.closed_at.isnot(None),
			)
		).scalars().all()

		avg_days: float | None = None
		if resolved_cases:
			total_seconds = sum(
				(c.closed_at - c.opened_at).total_seconds()
				for c in resolved_cases
				if c.closed_at and c.opened_at
			)
			avg_days = round(total_seconds / len(resolved_cases) / 86400, 1)

		return {
			"by_status": by_status,
			"by_category": by_category,
			"by_severity": by_severity,
			"total_reports": len(reports),
			"avg_time_to_resolve_days": avg_days,
		}


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"grc.ethics.open_case",
	"Open ethics case for investigation",
)
def _bpm_ethics_open_case(
	record_ctx: dict,
	session: Any,
	report_id: str = "",
	assigned_to: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.grc.ethics.services import EthicsHotlineService
	except ImportError:
		return {"status": "error", "message": "grc.ethics plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		case = EthicsHotlineService().open_case(
			report_id=report_id,
			assigned_to=assigned_to,
			tenant_id=tenant_id,
			session=session,
		)
		return {"status": "ok", "case_id": case.id, "report_id": report_id}
	except Exception as exc:
		log.warning("bpm ethics.open_case failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = ["EthicsHotlineService"]
