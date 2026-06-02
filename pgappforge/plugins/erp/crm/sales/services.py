"""
pgappforge/plugins/erp/crm/sales/services.py

SalesService — stateless business logic for the Sales Force Automation plugin.

All methods accept an explicit SQLAlchemy session (SA 2.x execute() pattern).
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are integer cents throughout.

Key methods
-----------
  score_lead(lead_id, session) -> int
      Einstein-style lead scoring (0–100).  Updates lead.score + lead.grade.

  advance_stage(opportunity_id, new_stage, session) -> Opportunity
      Validates transition, updates stage/probability/forecast_category,
      emits appropriate event (won/lost/advanced).

  convert_lead(lead_id, data, session) -> dict
      Converts lead to account + contact + opportunity.

  record_activity(data, session) -> Activity
      Logs an activity and updates contact.last_activity_at +
      contact.engagement_score.

  update_sales_target(owner_id, period_id, amount_cents, session)
      Adds achieved_amount_cents to matching SalesTarget rows.

  submit_forecast(data, session) -> SalesForecast
      Creates or replaces a period forecast for a rep/manager.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class SalesServiceError(Exception):
	"""Base exception for sales service layer errors."""


class SalesAccountNotFoundError(SalesServiceError):
	pass


class SalesContactNotFoundError(SalesServiceError):
	pass


class LeadNotFoundError(SalesServiceError):
	pass


class OpportunityNotFoundError(SalesServiceError):
	pass


class SalesValidationError(SalesServiceError):
	"""Business rule violation — surfaces as HTTP 422 in views."""


# ---------------------------------------------------------------------------
# Stage transition rules
# ---------------------------------------------------------------------------

# Valid forward (and backward) transitions — any stage can go to CLOSED_*
_STAGE_ORDER = [
	"PROSPECTING",
	"QUALIFICATION",
	"DEMO",
	"PROPOSAL",
	"NEGOTIATION",
	"CLOSED_WON",
	"CLOSED_LOST",
]

# Default probability per stage
_STAGE_PROBABILITY: dict[str, int] = {
	"PROSPECTING": 10,
	"QUALIFICATION": 20,
	"DEMO": 40,
	"PROPOSAL": 60,
	"NEGOTIATION": 80,
	"CLOSED_WON": 100,
	"CLOSED_LOST": 0,
}

_STAGE_FORECAST: dict[str, str] = {
	"PROSPECTING": "PIPELINE",
	"QUALIFICATION": "PIPELINE",
	"DEMO": "PIPELINE",
	"PROPOSAL": "BEST_CASE",
	"NEGOTIATION": "COMMIT",
	"CLOSED_WON": "CLOSED",
	"CLOSED_LOST": "CLOSED",
}


class SalesService:
	"""Stateless sales business logic.

	Instantiate per-request or as a singleton — no instance state.
	"""

	# ------------------------------------------------------------------
	# score_lead
	# ------------------------------------------------------------------

	def score_lead(self, lead_id: str, session: Any) -> int:
		"""Einstein-style lead scoring (0–100).

		Scoring factors:
		  +20  email present
		  +15  phone present
		  +20  company present
		  +10  source in (REFERRAL, TRADE_SHOW)
		  +10  title present (suggests seniority)
		  +10  campaign attribution present
		  +15  previous activity count > 0

		Updates lead.score and lead.grade in the session.
		Returns the new score.
		"""
		from pgappforge.plugins.erp.crm.sales.models import Lead, Activity
		from pgappforge.plugins.erp.crm.sales.events import LeadScoredEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		lead = session.get(Lead, lead_id)
		if lead is None:
			raise LeadNotFoundError(f"Lead {lead_id!r} not found")

		old_score = lead.score
		old_grade = lead.grade or ""

		score = 0
		if lead.email:
			score += 20
		if lead.phone:
			score += 15
		if lead.company:
			score += 20
		if lead.source in ("REFERRAL", "TRADE_SHOW"):
			score += 10
		if lead.title:
			score += 10
		if lead.campaign_id:
			score += 10

		# Activity signal
		activity_count = session.execute(
			sa.select(sa.func.count(Activity.id))
			.where(Activity.tenant_id == lead.tenant_id)
			# Activities on leads are linked via the email match heuristic
			# In production, a lead_id FK on Activity would be cleaner
		).scalar() or 0
		if activity_count > 0:
			score += 15

		score = min(score, 100)

		# Grade bands
		if score >= 90:
			grade = "A"
		elif score >= 70:
			grade = "B"
		elif score >= 50:
			grade = "C"
		else:
			grade = "D"

		lead.score = score
		lead.grade = grade
		lead.updated_at = datetime.now(timezone.utc)

		emit_event(
			LeadScoredEvent(
				aggregate_id=lead_id,
				aggregate_type="Lead",
				tenant_id=lead.tenant_id,
				lead_id=lead_id,
				old_score=old_score,
				new_score=score,
				old_grade=old_grade,
				new_grade=grade,
			),
			session,
		)

		log.info(
			"SalesService.score_lead: %r scored %d (grade=%s, was %d/%s)",
			lead_id, score, grade, old_score, old_grade,
		)
		return score

	# ------------------------------------------------------------------
	# advance_stage
	# ------------------------------------------------------------------

	def advance_stage(
		self,
		opportunity_id: str,
		new_stage: str,
		session: Any,
		reason: str = "",
		competitor: str = "",
	) -> Any:
		"""Transition opportunity to new_stage.

		Validations:
		  - Opportunity must exist.
		  - new_stage must be a recognised stage value.
		  - Cannot transition from a terminal stage (CLOSED_WON/CLOSED_LOST)
		    unless reverting to NEGOTIATION for re-open.

		Side-effects:
		  - Updates stage, probability, forecast_category.
		  - Sets closed_at for CLOSED_* transitions.
		  - Updates SalesTarget.achieved_amount_cents on CLOSED_WON.
		  - Emits OpportunityWonEvent / OpportunityLostEvent / OpportunityStageAdvancedEvent.

		Returns updated Opportunity.
		"""
		from pgappforge.plugins.erp.crm.sales.models import Opportunity
		from pgappforge.plugins.erp.crm.sales.events import (
			OpportunityStageAdvancedEvent,
			OpportunityWonEvent,
			OpportunityLostEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		opp = session.get(Opportunity, opportunity_id)
		if opp is None:
			raise OpportunityNotFoundError(f"Opportunity {opportunity_id!r} not found")

		new_stage = new_stage.upper()
		if new_stage not in _STAGE_ORDER:
			raise SalesValidationError(
				f"Invalid stage {new_stage!r}. Valid: {_STAGE_ORDER}"
			)

		old_stage = opp.stage
		if old_stage in ("CLOSED_WON", "CLOSED_LOST") and new_stage not in ("CLOSED_WON", "CLOSED_LOST", "NEGOTIATION"):
			raise SalesValidationError(
				f"Cannot reopen opportunity from {old_stage!r} to {new_stage!r}; "
				"use NEGOTIATION to re-open"
			)

		opp.stage = new_stage
		opp.probability = _STAGE_PROBABILITY[new_stage]
		opp.forecast_category = _STAGE_FORECAST[new_stage]
		opp.updated_at = datetime.now(timezone.utc)

		now_utc = datetime.now(timezone.utc)

		if new_stage == "CLOSED_WON":
			opp.closed_at = now_utc
			opp.reason_won = reason or opp.reason_won
			# Update sales target achieved
			self._credit_sales_target(
				owner_id=opp.owner_id,
				tenant_id=opp.tenant_id,
				amount_cents=opp.amount_cents or 0,
				session=session,
			)
			emit_event(
				OpportunityWonEvent(
					aggregate_id=opportunity_id,
					aggregate_type="Opportunity",
					tenant_id=opp.tenant_id,
					opportunity_id=opportunity_id,
					opportunity_name=opp.opportunity_name,
					account_id=opp.account_id,
					amount_cents=opp.amount_cents or 0,
					currency_code=opp.currency_code,
					owner_id=opp.owner_id or "",
					reason_won=reason,
					closed_at=now_utc.isoformat(),
				),
				session,
			)
		elif new_stage == "CLOSED_LOST":
			opp.closed_at = now_utc
			opp.reason_lost = reason or opp.reason_lost
			opp.competitor = competitor or opp.competitor
			emit_event(
				OpportunityLostEvent(
					aggregate_id=opportunity_id,
					aggregate_type="Opportunity",
					tenant_id=opp.tenant_id,
					opportunity_id=opportunity_id,
					opportunity_name=opp.opportunity_name,
					account_id=opp.account_id,
					amount_cents=opp.amount_cents or 0,
					currency_code=opp.currency_code,
					reason_lost=reason,
					competitor=competitor,
					closed_at=now_utc.isoformat(),
				),
				session,
			)
		else:
			emit_event(
				OpportunityStageAdvancedEvent(
					aggregate_id=opportunity_id,
					aggregate_type="Opportunity",
					tenant_id=opp.tenant_id,
					opportunity_id=opportunity_id,
					opportunity_name=opp.opportunity_name,
					account_id=opp.account_id,
					old_stage=old_stage,
					new_stage=new_stage,
					amount_cents=opp.amount_cents or 0,
					currency_code=opp.currency_code,
					probability=opp.probability,
				),
				session,
			)

		log.info(
			"SalesService.advance_stage: %r %s → %s",
			opp.opportunity_name, old_stage, new_stage,
		)
		return opp

	# ------------------------------------------------------------------
	# convert_lead
	# ------------------------------------------------------------------

	def convert_lead(self, lead_id: str, data: dict, session: Any) -> dict:
		"""Convert a QUALIFIED lead to SalesAccount + SalesContact + Opportunity.

		data keys (all optional override existing lead fields):
		  account_name, account_type, owner_id,
		  opportunity_name, amount_cents, currency_code, expected_close_date,
		  create_opportunity (bool, default True)

		Returns dict with created entity IDs.
		"""
		from pgappforge.plugins.erp.crm.sales.models import (
			Lead, SalesAccount, SalesContact, Opportunity,
		)
		from pgappforge.plugins.erp.crm.sales.events import (
			LeadConvertedEvent, OpportunityCreatedEvent,
		)
		from pgappforge.plugins.erp.foundation.events import emit_event

		lead = session.get(Lead, lead_id)
		if lead is None:
			raise LeadNotFoundError(f"Lead {lead_id!r} not found")
		if lead.status == "CONVERTED":
			raise SalesValidationError(f"Lead {lead_id!r} is already converted")
		if lead.status not in ("QUALIFIED", "WORKING", "CONTACTED"):
			raise SalesValidationError(
				f"Lead must be QUALIFIED (or WORKING/CONTACTED) before conversion; "
				f"current status: {lead.status!r}"
			)

		owner_id = data.get("owner_id") or lead.assigned_to

		# Create SalesAccount
		account = SalesAccount(
			tenant_id=lead.tenant_id,
			name=data.get("account_name") or lead.company or "Unknown",
			account_type=data.get("account_type") or "CUSTOMER",
			owner_id=owner_id,
			email=lead.email,
			phone=lead.phone,
		)
		session.add(account)
		session.flush()

		# Create SalesContact
		contact = SalesContact(
			tenant_id=lead.tenant_id,
			account_id=account.id,
			first_name=lead.first_name or "",
			last_name=lead.last_name or "Unknown",
			title=lead.title,
			email=lead.email,
			phone=lead.phone,
			owner_id=owner_id,
		)
		session.add(contact)
		session.flush()

		opp_id = None
		create_opp = data.get("create_opportunity", True)
		if create_opp:
			opp_name = (
				data.get("opportunity_name")
				or f"{account.name} — {lead.source or 'Opportunity'}"
			)
			opp = Opportunity(
				tenant_id=lead.tenant_id,
				account_id=account.id,
				contact_id=contact.id,
				opportunity_name=opp_name,
				stage="QUALIFICATION",
				probability=_STAGE_PROBABILITY["QUALIFICATION"],
				forecast_category=_STAGE_FORECAST["QUALIFICATION"],
				amount_cents=data.get("amount_cents"),
				currency_code=data.get("currency_code", "USD"),
				owner_id=owner_id,
				lead_source=lead.source,
			)
			if data.get("expected_close_date"):
				from datetime import date
				opp.expected_close_date = date.fromisoformat(data["expected_close_date"])
			session.add(opp)
			session.flush()
			opp_id = opp.id

			emit_event(
				OpportunityCreatedEvent(
					aggregate_id=opp.id,
					aggregate_type="Opportunity",
					tenant_id=lead.tenant_id,
					opportunity_id=opp.id,
					account_id=account.id,
					opportunity_name=opp.opportunity_name,
					amount_cents=opp.amount_cents or 0,
					currency_code=opp.currency_code,
					stage=opp.stage,
					owner_id=owner_id or "",
				),
				session,
			)

		# Mark lead converted
		lead.status = "CONVERTED"
		lead.converted_at = datetime.now(timezone.utc)
		lead.converted_account_id = account.id
		lead.converted_contact_id = contact.id
		lead.converted_opportunity_id = opp_id
		lead.updated_at = datetime.now(timezone.utc)

		emit_event(
			LeadConvertedEvent(
				aggregate_id=lead_id,
				aggregate_type="Lead",
				tenant_id=lead.tenant_id,
				lead_id=lead_id,
				converted_account_id=account.id,
				converted_contact_id=contact.id,
				converted_opportunity_id=opp_id or "",
			),
			session,
		)

		log.info(
			"SalesService.convert_lead: lead %r → account=%r contact=%r opp=%r",
			lead_id, account.id, contact.id, opp_id,
		)
		return {
			"account_id": account.id,
			"contact_id": contact.id,
			"opportunity_id": opp_id,
		}

	# ------------------------------------------------------------------
	# record_activity
	# ------------------------------------------------------------------

	def record_activity(self, data: dict, session: Any) -> Any:
		"""Log a sales activity and update contact engagement score.

		data keys: tenant_id, activity_type, subject, status, direction,
		           outcome, duration_minutes, contact_id, account_id,
		           opportunity_id, owner_id, activity_date
		"""
		from pgappforge.plugins.erp.crm.sales.models import Activity, SalesContact
		from pgappforge.plugins.erp.crm.sales.events import ActivityLoggedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "activity_type", "subject", "activity_date")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise SalesValidationError(f"Missing required activity fields: {missing}")

		from datetime import datetime as dt
		act_date = data["activity_date"]
		if isinstance(act_date, str):
			act_date = dt.fromisoformat(act_date)

		act = Activity(
			tenant_id=data["tenant_id"],
			activity_type=data["activity_type"].upper(),
			subject=data["subject"],
			description=data.get("description"),
			status=(data.get("status") or "COMPLETED").upper(),
			direction=data.get("direction", "").upper() or None,
			outcome=data.get("outcome"),
			duration_minutes=data.get("duration_minutes"),
			contact_id=data.get("contact_id"),
			account_id=data.get("account_id"),
			opportunity_id=data.get("opportunity_id"),
			owner_id=data.get("owner_id"),
			activity_date=act_date,
		)
		session.add(act)
		session.flush()

		# Update contact engagement
		contact_id = data.get("contact_id")
		if contact_id and act.status == "COMPLETED":
			contact = session.get(SalesContact, contact_id)
			if contact:
				# Simple engagement increment (0–10 capped)
				current = float(contact.engagement_score or 0)
				contact.engagement_score = min(10.0, current + 0.5)
				contact.last_activity_at = act_date
				contact.updated_at = datetime.now(timezone.utc)

		if act.status == "COMPLETED":
			emit_event(
				ActivityLoggedEvent(
					aggregate_id=act.id,
					aggregate_type="Activity",
					tenant_id=act.tenant_id,
					activity_id=act.id,
					activity_type=act.activity_type,
					contact_id=act.contact_id or "",
					account_id=act.account_id or "",
					opportunity_id=act.opportunity_id or "",
					owner_id=act.owner_id or "",
					outcome=act.outcome or "",
				),
				session,
			)

		return act

	# ------------------------------------------------------------------
	# submit_forecast
	# ------------------------------------------------------------------

	def submit_forecast(self, data: dict, session: Any) -> Any:
		"""Create or replace a period forecast for owner_id.

		data keys: tenant_id, period_id, owner_id, pipeline_cents,
		           best_case_cents, commit_cents, closed_cents,
		           ai_forecast_cents (optional)

		Replaces any existing unsubmitted forecast for the same owner/period.
		Returns the created SalesForecast.
		"""
		from pgappforge.plugins.erp.crm.sales.models import SalesForecast
		from pgappforge.plugins.erp.crm.sales.events import ForecastSubmittedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		required = ("tenant_id", "period_id", "owner_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			raise SalesValidationError(f"Missing forecast fields: {missing}")

		# Expire any existing draft for this owner/period
		existing = session.execute(
			sa.select(SalesForecast)
			.where(SalesForecast.tenant_id == data["tenant_id"])
			.where(SalesForecast.owner_id == data["owner_id"])
			.where(SalesForecast.period_id == data["period_id"])
			.where(SalesForecast.submitted_at.is_(None))
		).scalar_one_or_none()
		if existing:
			session.delete(existing)
			session.flush()

		fc = SalesForecast(
			tenant_id=data["tenant_id"],
			period_id=data["period_id"],
			owner_id=data["owner_id"],
			pipeline_cents=int(data.get("pipeline_cents") or 0),
			best_case_cents=int(data.get("best_case_cents") or 0),
			commit_cents=int(data.get("commit_cents") or 0),
			closed_cents=int(data.get("closed_cents") or 0),
			ai_forecast_cents=data.get("ai_forecast_cents"),
			submitted_at=datetime.now(timezone.utc),
		)
		session.add(fc)
		session.flush()

		emit_event(
			ForecastSubmittedEvent(
				aggregate_id=fc.id,
				aggregate_type="SalesForecast",
				tenant_id=fc.tenant_id,
				forecast_id=fc.id,
				period_id=fc.period_id,
				owner_id=fc.owner_id,
				commit_cents=fc.commit_cents,
				best_case_cents=fc.best_case_cents,
				pipeline_cents=fc.pipeline_cents,
			),
			session,
		)

		log.info(
			"SalesService.submit_forecast: owner=%r period=%r commit=%d¢",
			fc.owner_id, fc.period_id, fc.commit_cents,
		)
		return fc

	# ------------------------------------------------------------------
	# update_sales_target
	# ------------------------------------------------------------------

	def update_sales_target(
		self,
		owner_id: str,
		tenant_id: str,
		period_id: str,
		amount_cents: int,
		session: Any,
	) -> None:
		"""Add amount_cents to achieved_amount_cents on matching SalesTarget.

		Called internally by advance_stage on CLOSED_WON.
		"""
		from pgappforge.plugins.erp.crm.sales.models import SalesTarget

		targets = session.execute(
			sa.select(SalesTarget)
			.where(SalesTarget.tenant_id == tenant_id)
			.where(SalesTarget.owner_id == owner_id)
			.where(SalesTarget.period_id == period_id)
			.where(SalesTarget.target_type == "REVENUE")
		).scalars().all()

		for t in targets:
			t.achieved_amount_cents += amount_cents
			t.updated_at = datetime.now(timezone.utc)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _credit_sales_target(
		self,
		owner_id: str | None,
		tenant_id: str,
		amount_cents: int,
		session: Any,
	) -> None:
		"""Best-effort: credit the current-period revenue target on win.

		Skips gracefully if no matching target found or owner_id is None.
		"""
		if not owner_id or not amount_cents:
			return
		try:
			from pgappforge.plugins.erp.crm.sales.models import SalesTarget
			targets = session.execute(
				sa.select(SalesTarget)
				.where(SalesTarget.tenant_id == tenant_id)
				.where(SalesTarget.owner_id == owner_id)
				.where(SalesTarget.target_type == "REVENUE")
			).scalars().all()
			for t in targets:
				t.achieved_amount_cents = (t.achieved_amount_cents or 0) + amount_cents
				t.updated_at = datetime.now(timezone.utc)
		except Exception as exc:
			log.debug("_credit_sales_target: skipped — %s", exc)


__all__ = [
	"SalesService",
	"SalesServiceError",
	"SalesAccountNotFoundError",
	"SalesContactNotFoundError",
	"LeadNotFoundError",
	"OpportunityNotFoundError",
	"SalesValidationError",
]
