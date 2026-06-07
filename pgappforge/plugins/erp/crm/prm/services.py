"""
pgappforge/plugins/erp/crm/prm/services.py

PRMService — all partner relationship management operations.

Design rules:
  - Synchronous (Flask/SQLAlchemy context).
  - All monetary amounts: integer cents.
  - SQLAlchemy 2.x: select() + session.execute().scalar_one_or_none().
  - Emit domain events within the same session (atomic with business mutation).
  - BPM action registrations at module level.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PRMServiceError(Exception):
	"""Base error for the PRM service layer."""


class PartnerNotFoundError(PRMServiceError):
	"""Raised when a partner account cannot be located."""


class DealNotFoundError(PRMServiceError):
	"""Raised when a deal registration cannot be located."""


class MDFNotFoundError(PRMServiceError):
	"""Raised when an MDF request cannot be located."""


class InvalidStateError(PRMServiceError):
	"""Raised when an operation is invalid given the entity's current state."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("PRM event emit failed: %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("prm.register_partner")
	def _bpm_register_partner(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "prm.register_partner", "params": ctx}

	@_BPMReg.register("prm.register_deal")
	def _bpm_register_deal(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "prm.register_deal", "params": ctx}

	@_BPMReg.register("prm.approve_deal")
	def _bpm_approve_deal(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "prm.approve_deal", "params": ctx}

	@_BPMReg.register("prm.close_deal_won")
	def _bpm_close_deal_won(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "prm.close_deal_won", "params": ctx}

except (ImportError, Exception):
	log.debug("BPMActionRegistry not available — PRM BPM actions not registered")


# ---------------------------------------------------------------------------
# PRMService
# ---------------------------------------------------------------------------

class PRMService:
	"""Service layer for Partner Relationship Management operations."""

	# ------------------------------------------------------------------
	# Partner management
	# ------------------------------------------------------------------

	def register_partner(
		self,
		company_name: str,
		partner_tier: str,
		tenant_id: str,
		session: Any,
		*,
		region: str | None = None,
		contact_email: str | None = None,
		contact_name: str | None = None,
		country_code: str | None = None,
	) -> Any:
		"""Create a new partner account.

		Generates a unique partner_code as PRM-<8-char-UUID-prefix>.
		Emits PartnerRegisteredEvent.
		"""
		from pgappforge.plugins.erp.crm.prm.models import PartnerAccount
		from pgappforge.plugins.erp.crm.prm.events import PartnerRegisteredEvent

		partner_code = f"PRM-{_uuid4()[:8].upper()}"
		partner = PartnerAccount(
			id=_uuid4(),
			tenant_id=tenant_id,
			company_name=company_name,
			partner_code=partner_code,
			partner_tier=partner_tier.upper(),
			region=region,
			country_code=country_code,
			contact_name=contact_name,
			contact_email=contact_email,
			status="ACTIVE",
			annual_revenue_target_cents=0,
			ytd_revenue_cents=0,
		)
		session.add(partner)
		session.flush()

		_emit(
			PartnerRegisteredEvent(
				aggregate_id=partner.id,
				aggregate_type="PartnerAccount",
				tenant_id=tenant_id,
				partner_id=partner.id,
				company_name=company_name,
				tier=partner_tier.upper(),
			),
			session,
		)
		log.info("PRM: registered partner %s [%s]", partner_code, partner_tier)
		return partner

	# ------------------------------------------------------------------
	# Deal registration
	# ------------------------------------------------------------------

	def register_deal(
		self,
		partner_id: str,
		opportunity_name: str,
		customer_name: str,
		estimated_value_cents: int,
		session: Any,
		*,
		close_date: Any = None,
		customer_domain: str | None = None,
		notes: str | None = None,
	) -> Any:
		"""Submit a new deal registration for a partner.

		Emits DealRegisteredEvent.
		"""
		from pgappforge.plugins.erp.crm.prm.models import DealRegistration, PartnerAccount
		from pgappforge.plugins.erp.crm.prm.events import DealRegisteredEvent

		partner = session.execute(
			sa.select(PartnerAccount).where(PartnerAccount.id == partner_id)
		).scalar_one_or_none()
		if partner is None:
			raise PartnerNotFoundError(f"Partner {partner_id} not found")

		deal = DealRegistration(
			id=_uuid4(),
			tenant_id=partner.tenant_id,
			partner_id=partner_id,
			opportunity_name=opportunity_name,
			customer_name=customer_name,
			customer_domain=customer_domain,
			estimated_value_cents=estimated_value_cents,
			stage="SUBMITTED",
			close_date=close_date,
			submitted_at=_now(),
			notes=notes,
		)
		session.add(deal)
		session.flush()

		_emit(
			DealRegisteredEvent(
				aggregate_id=deal.id,
				aggregate_type="DealRegistration",
				tenant_id=partner.tenant_id,
				deal_id=deal.id,
				partner_id=partner_id,
				customer_name=customer_name,
				estimated_value_cents=estimated_value_cents,
			),
			session,
		)
		log.info("PRM: deal %s registered by partner %s", deal.id, partner_id)
		return deal

	def approve_deal(
		self,
		deal_id: str,
		approver_id: str,
		session: Any,
	) -> Any:
		"""Transition deal from SUBMITTED → APPROVED.

		Raises InvalidStateError if not in SUBMITTED stage.
		"""
		from pgappforge.plugins.erp.crm.prm.models import DealRegistration

		deal = session.execute(
			sa.select(DealRegistration).where(DealRegistration.id == deal_id)
		).scalar_one_or_none()
		if deal is None:
			raise DealNotFoundError(f"Deal {deal_id} not found")
		if deal.stage != "SUBMITTED":
			raise InvalidStateError(f"Cannot approve deal in stage {deal.stage!r}")

		deal.stage = "APPROVED"
		deal.approved_by = approver_id
		deal.approved_at = _now()
		session.flush()
		log.info("PRM: deal %s approved by %s", deal_id, approver_id)
		return deal

	def close_deal_won(
		self,
		deal_id: str,
		actual_value_cents: int,
		session: Any,
	) -> Any:
		"""Mark deal as WON and update partner YTD revenue.

		Emits DealWonEvent.
		"""
		from pgappforge.plugins.erp.crm.prm.models import DealRegistration, PartnerAccount
		from pgappforge.plugins.erp.crm.prm.events import DealWonEvent

		deal = session.execute(
			sa.select(DealRegistration).where(DealRegistration.id == deal_id)
		).scalar_one_or_none()
		if deal is None:
			raise DealNotFoundError(f"Deal {deal_id} not found")

		deal.stage = "WON"
		deal.actual_value_cents = actual_value_cents

		# Update partner YTD revenue
		partner = session.execute(
			sa.select(PartnerAccount).where(PartnerAccount.id == deal.partner_id)
		).scalar_one_or_none()
		if partner is not None:
			partner.ytd_revenue_cents = (partner.ytd_revenue_cents or 0) + actual_value_cents

		session.flush()

		_emit(
			DealWonEvent(
				aggregate_id=deal.id,
				aggregate_type="DealRegistration",
				tenant_id=deal.tenant_id,
				deal_id=deal.id,
				partner_id=deal.partner_id,
				actual_value_cents=actual_value_cents,
			),
			session,
		)
		log.info("PRM: deal %s won; actual_value=%d cents", deal_id, actual_value_cents)
		return deal

	# ------------------------------------------------------------------
	# MDF
	# ------------------------------------------------------------------

	def request_mdf(
		self,
		partner_id: str,
		campaign_name: str,
		amount_cents: int,
		period: str,
		tenant_id: str,
		session: Any,
		*,
		purpose: str = "",
	) -> Any:
		"""Submit an MDF request for a partner."""
		from pgappforge.plugins.erp.crm.prm.models import MDFRequest

		mdf = MDFRequest(
			id=_uuid4(),
			tenant_id=tenant_id,
			partner_id=partner_id,
			campaign_name=campaign_name,
			purpose=purpose,
			amount_requested_cents=amount_cents,
			period=period,
			status="PENDING",
		)
		session.add(mdf)
		session.flush()
		log.info("PRM: MDF request %s submitted by partner %s", mdf.id, partner_id)
		return mdf

	def approve_mdf(
		self,
		request_id: str,
		approver_id: str,
		approved_cents: int,
		session: Any,
	) -> Any:
		"""Approve an MDF request, setting approved_cents.

		Emits MDFApprovedEvent.
		"""
		from pgappforge.plugins.erp.crm.prm.models import MDFRequest
		from pgappforge.plugins.erp.crm.prm.events import MDFApprovedEvent

		mdf = session.execute(
			sa.select(MDFRequest).where(MDFRequest.id == request_id)
		).scalar_one_or_none()
		if mdf is None:
			raise MDFNotFoundError(f"MDF request {request_id} not found")
		if mdf.status != "PENDING":
			raise InvalidStateError(f"Cannot approve MDF in status {mdf.status!r}")

		mdf.status = "APPROVED"
		mdf.approved_by = approver_id
		mdf.approved_cents = approved_cents
		session.flush()

		_emit(
			MDFApprovedEvent(
				aggregate_id=mdf.id,
				aggregate_type="MDFRequest",
				tenant_id=mdf.tenant_id,
				request_id=mdf.id,
				partner_id=mdf.partner_id,
				approved_cents=approved_cents,
			),
			session,
		)
		log.info("PRM: MDF %s approved for %d cents by %s", request_id, approved_cents, approver_id)
		return mdf

	# ------------------------------------------------------------------
	# Dashboard
	# ------------------------------------------------------------------

	def get_partner_dashboard(
		self,
		partner_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return a summary dashboard for a partner.

		Returns:
		    {tier, ytd_revenue_cents, annual_target_cents, deals, mdf, training_completions}
		"""
		from pgappforge.plugins.erp.crm.prm.models import PartnerAccount, DealRegistration, MDFRequest

		partner = session.execute(
			sa.select(PartnerAccount).where(PartnerAccount.id == partner_id)
		).scalar_one_or_none()
		if partner is None:
			raise PartnerNotFoundError(f"Partner {partner_id} not found")

		# Deal summary
		deal_rows = session.execute(
			sa.select(DealRegistration.stage, sa.func.count().label("cnt"))
			.where(DealRegistration.partner_id == partner_id)
			.group_by(DealRegistration.stage)
		).all()
		deals_by_stage = {row.stage: row.cnt for row in deal_rows}

		deal_value_rows = session.execute(
			sa.select(
				sa.func.sum(DealRegistration.estimated_value_cents).label("pipeline"),
				sa.func.sum(DealRegistration.actual_value_cents).label("won_value"),
			).where(DealRegistration.partner_id == partner_id)
		).one()

		# MDF summary
		mdf_rows = session.execute(
			sa.select(MDFRequest.status, sa.func.sum(MDFRequest.approved_cents).label("total"))
			.where(MDFRequest.partner_id == partner_id)
			.group_by(MDFRequest.status)
		).all()
		mdf_approved = sum(
			(row.total or 0) for row in mdf_rows if row.status == "APPROVED"
		)
		mdf_spent = sum(
			(row.total or 0) for row in mdf_rows if row.status == "SPENT"
		)

		return {
			"partner_id": partner_id,
			"company_name": partner.company_name,
			"tier": partner.partner_tier,
			"status": partner.status,
			"ytd_revenue_cents": partner.ytd_revenue_cents,
			"annual_revenue_target_cents": partner.annual_revenue_target_cents,
			"deals": {
				"by_stage": deals_by_stage,
				"pipeline_value_cents": deal_value_rows.pipeline or 0,
				"won_value_cents": deal_value_rows.won_value or 0,
			},
			"mdf": {
				"approved_cents": mdf_approved,
				"spent_cents": mdf_spent,
				"available_cents": mdf_approved - mdf_spent,
			},
			"training_completions": 0,  # Placeholder — link to LMS plugin when available
		}
