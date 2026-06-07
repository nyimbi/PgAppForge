"""
pgappforge/plugins/erp/grc/anti_bribery/services.py

AntiBriberyService — gift logging, approval workflow, conflict-of-interest declarations.

Key operations:
  log_gift            — record a gift/entertainment entry; auto-approve or queue
  approve_gift        — approve/reject a pending gift entry
  submit_coi_declaration  — employee files a conflict-of-interest declaration
  review_coi          — compliance officer reviews a COI declaration
  get_risk_exposure   — aggregate bribery risk metrics for a period
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)

# Default thresholds (overridden by Flask config)
_DEFAULT_GIFT_THRESHOLD_CENTS = 500_00       # $500
_DEFAULT_GOVT_GIFT_THRESHOLD_CENTS = 0       # $0 — any gift to official requires approval


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("AntiBriberyService: emit suppressed: %s", exc)


def _get_threshold(key: str, default: int) -> int:
	try:
		from flask import current_app
		return current_app.config.get(key, default)
	except Exception:
		return default


# ---------------------------------------------------------------------------
# AntiBriberyService
# ---------------------------------------------------------------------------

class AntiBriberyService:
	"""Stateless Anti-Bribery & Corruption service."""

	# ------------------------------------------------------------------
	# log_gift
	# ------------------------------------------------------------------

	def log_gift(
		self,
		given_to_name: str,
		gift_type: str,
		value_cents: int,
		given_date: date,
		purpose: str,
		employee_id: str,
		tenant_id: str,
		session: Any,
		*,
		given_to_org: str | None = None,
		is_govt_official: bool = False,
		direction: str = "GIVEN",
		country_code: str | None = None,
	) -> Any:
		"""Record a gift/entertainment entry.

		Auto-approves entries below configured thresholds.
		Emits GiftApprovalRequiredEvent for entries that exceed thresholds.
		Always emits GiftLoggedEvent.
		"""
		from pgappforge.plugins.erp.grc.anti_bribery.models import GiftEntertainmentLog
		from pgappforge.plugins.erp.grc.anti_bribery.events import (
			GiftLoggedEvent,
			GiftApprovalRequiredEvent,
		)

		threshold = _get_threshold("GIFT_THRESHOLD_CENTS", _DEFAULT_GIFT_THRESHOLD_CENTS)
		govt_threshold = _get_threshold("GOVT_GIFT_THRESHOLD_CENTS", _DEFAULT_GOVT_GIFT_THRESHOLD_CENTS)

		needs_approval = (
			(is_govt_official and value_cents > govt_threshold)
			or (not is_govt_official and value_cents > threshold)
		)

		gift = GiftEntertainmentLog(
			tenant_id=tenant_id,
			given_to_name=given_to_name,
			given_to_organization=given_to_org,
			gift_type=gift_type,
			value_cents=value_cents,
			given_date=given_date,
			purpose=purpose,
			is_government_official=is_govt_official,
			employee_id=employee_id,
			direction=direction,
			country_code=country_code,
			status="PENDING" if needs_approval else "AUTO_APPROVED",
		)
		session.add(gift)
		session.flush()

		if needs_approval:
			_emit(
				GiftApprovalRequiredEvent(
					aggregate_id=gift.id,
					aggregate_type="GiftEntertainmentLog",
					tenant_id=tenant_id,
					gift_id=gift.id,
					given_to=given_to_name,
					value_cents=value_cents,
					threshold_cents=govt_threshold if is_govt_official else threshold,
				),
				session,
			)

		_emit(
			GiftLoggedEvent(
				aggregate_id=gift.id,
				aggregate_type="GiftEntertainmentLog",
				tenant_id=tenant_id,
				gift_id=gift.id,
				value_cents=value_cents,
				is_government_official=is_govt_official,
			),
			session,
		)
		return gift

	# ------------------------------------------------------------------
	# approve_gift
	# ------------------------------------------------------------------

	def approve_gift(
		self,
		gift_id: str,
		approver_id: str,
		approved: bool,
		notes: str,
		session: Any,
	) -> Any:
		"""Approve or reject a pending gift entry."""
		from pgappforge.plugins.erp.grc.anti_bribery.models import GiftEntertainmentLog

		gift = session.execute(
			select(GiftEntertainmentLog).where(GiftEntertainmentLog.id == gift_id)
		).scalar_one_or_none()
		if gift is None:
			raise ValueError(f"GiftEntertainmentLog {gift_id!r} not found")

		gift.status = "APPROVED" if approved else "REJECTED"
		gift.approved_by = approver_id
		gift.approval_notes = notes
		session.flush()
		return gift

	# ------------------------------------------------------------------
	# submit_coi_declaration
	# ------------------------------------------------------------------

	def submit_coi_declaration(
		self,
		employee_id: str,
		category: str,
		description: str,
		tenant_id: str,
		session: Any,
		*,
		relates_to_supplier: str | None = None,
	) -> Any:
		"""Employee files a conflict-of-interest declaration."""
		from pgappforge.plugins.erp.grc.anti_bribery.models import ConflictOfInterestDeclaration
		from pgappforge.plugins.erp.grc.anti_bribery.events import CoiDeclarationSubmittedEvent

		decl = ConflictOfInterestDeclaration(
			tenant_id=tenant_id,
			employee_id=employee_id,
			category=category,
			description=description,
			declaration_date=date.today(),
			relates_to_supplier=relates_to_supplier,
			status="PENDING",
		)
		session.add(decl)
		session.flush()

		_emit(
			CoiDeclarationSubmittedEvent(
				aggregate_id=decl.id,
				aggregate_type="ConflictOfInterestDeclaration",
				tenant_id=tenant_id,
				declaration_id=decl.id,
				employee_id=employee_id,
				category=category,
			),
			session,
		)
		return decl

	# ------------------------------------------------------------------
	# review_coi
	# ------------------------------------------------------------------

	def review_coi(
		self,
		declaration_id: str,
		reviewer_id: str,
		status: str,
		notes: str,
		session: Any,
	) -> Any:
		"""Compliance officer reviews a COI declaration."""
		from pgappforge.plugins.erp.grc.anti_bribery.models import ConflictOfInterestDeclaration

		decl = session.execute(
			select(ConflictOfInterestDeclaration).where(
				ConflictOfInterestDeclaration.id == declaration_id
			)
		).scalar_one_or_none()
		if decl is None:
			raise ValueError(f"ConflictOfInterestDeclaration {declaration_id!r} not found")

		decl.status = status
		decl.reviewed_by = reviewer_id
		decl.reviewed_at = datetime.now(timezone.utc)
		decl.review_notes = notes
		session.flush()
		return decl

	# ------------------------------------------------------------------
	# get_risk_exposure
	# ------------------------------------------------------------------

	def get_risk_exposure(
		self,
		tenant_id: str,
		period: str,  # e.g. "2026-Q1" or "2026" — used as label only
		session: Any,
	) -> dict:
		"""Return bribery risk exposure summary for the compliance dashboard.

		Returns:
		  {
		    period,
		    total_gifts_value_cents,
		    government_official_count,
		    pending_approvals,
		    coi_open_count,
		    high_risk_employees: [{employee_id, gift_count, total_cents}],
		  }
		"""
		from pgappforge.plugins.erp.grc.anti_bribery.models import (
			GiftEntertainmentLog,
			ConflictOfInterestDeclaration,
		)

		gifts = session.execute(
			select(GiftEntertainmentLog).where(
				GiftEntertainmentLog.tenant_id == tenant_id,
			)
		).scalars().all()

		total_value = sum(g.value_cents for g in gifts)
		govt_count = sum(1 for g in gifts if g.is_government_official)
		pending = sum(1 for g in gifts if g.status == "PENDING")

		# Employees with multiple gifts — potential high-risk pattern
		emp_map: dict[str, dict] = {}
		for g in gifts:
			eid = g.employee_id
			if eid not in emp_map:
				emp_map[eid] = {"employee_id": eid, "gift_count": 0, "total_cents": 0}
			emp_map[eid]["gift_count"] += 1
			emp_map[eid]["total_cents"] += g.value_cents

		high_risk = sorted(
			[e for e in emp_map.values() if e["gift_count"] >= 3 or e["total_cents"] >= 100_000],
			key=lambda x: x["total_cents"],
			reverse=True,
		)[:20]

		coi_open = session.execute(
			select(func.count()).select_from(ConflictOfInterestDeclaration).where(
				ConflictOfInterestDeclaration.tenant_id == tenant_id,
				ConflictOfInterestDeclaration.status.in_(["PENDING", "ESCALATED"]),
			)
		).scalar() or 0

		return {
			"period": period,
			"total_gifts_value_cents": total_value,
			"government_official_count": govt_count,
			"pending_approvals": pending,
			"coi_open_count": coi_open,
			"high_risk_employees": high_risk,
		}


__all__ = ["AntiBriberyService"]
