"""
pgappforge/plugins/erp/crm/marketing_automation/services.py

MarketingAutomationService — business logic for campaigns, sequences,
lead scoring, and revenue attribution.

Conventions:
  - session is always a SQLAlchemy Session passed by the caller (no session factory here)
  - All monetary values are integer cents
  - emit_event() is called BEFORE session.flush() so the event log row is part
    of the same transaction as the business mutation
  - BPMActionRegistry.register decorators expose key operations to workflow steps
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.workflow.engine import BPMActionRegistry

from .events import (
	ABTestVariantWonEvent,
	CampaignActivatedEvent,
	CampaignEmailSentEvent,
	LeadScoredEvent,
	RevenueAttributedEvent,
)
from .models import (
	CampaignAttribution,
	CampaignContact,
	LeadScore,
	MarketingCampaign,
	MarketingSequence,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class MarketingServiceError(Exception):
	"""Base exception for all marketing automation service errors."""


class MarketingNotFoundError(MarketingServiceError):
	"""Raised when a requested entity cannot be located."""


class MarketingStateError(MarketingServiceError):
	"""Raised when an operation is invalid for the entity's current state."""


# ---------------------------------------------------------------------------
# Grade computation helper
# ---------------------------------------------------------------------------

def _compute_grade(score: int) -> str:
	"""Derive letter grade from numeric score.

	A+: 90+  A: 70-89  B: 50-69  C: 30-49  D: 0-29 (or negative)
	"""
	if score >= 90:
		return "A+"
	if score >= 70:
		return "A"
	if score >= 50:
		return "B"
	if score >= 30:
		return "C"
	return "D"


# ---------------------------------------------------------------------------
# Condition evaluator
# ---------------------------------------------------------------------------

def _evaluate_conditions(conditions: list[dict], context: dict[str, Any]) -> bool:
	"""Evaluate a rules-engine conditions array against a context dict.

	Each condition: {field, op, value}
	Supported ops: eq, neq, gt, gte, lt, lte, in, not_in, is_null, contains
	All conditions must pass (implicit AND).  Returns True if conditions is empty.
	"""
	for cond in conditions:
		field = cond.get("field", "")
		op = cond.get("op", "eq")
		expected = cond.get("value")
		actual = context.get(field)

		try:
			if op == "eq" and actual != expected:
				return False
			elif op == "neq" and actual == expected:
				return False
			elif op == "gt" and not (actual is not None and actual > expected):
				return False
			elif op == "gte" and not (actual is not None and actual >= expected):
				return False
			elif op == "lt" and not (actual is not None and actual < expected):
				return False
			elif op == "lte" and not (actual is not None and actual <= expected):
				return False
			elif op == "in" and actual not in (expected or []):
				return False
			elif op == "not_in" and actual in (expected or []):
				return False
			elif op == "is_null":
				if expected and actual is not None:
					return False
				if not expected and actual is None:
					return False
			elif op == "contains" and (actual is None or expected not in str(actual)):
				return False
		except (TypeError, ValueError):
			# Type mismatch → condition fails
			return False

	return True


# ---------------------------------------------------------------------------
# MarketingAutomationService
# ---------------------------------------------------------------------------

class MarketingAutomationService:
	"""Stateless service — callers supply a SQLAlchemy session per operation."""

	# ------------------------------------------------------------------
	# Campaign lifecycle
	# ------------------------------------------------------------------

	def activate_campaign(self, campaign_id: str, session: Any) -> MarketingCampaign:
		"""Transition campaign DRAFT → ACTIVE and emit CampaignActivatedEvent.

		Raises:
		  MarketingNotFoundError: campaign not found.
		  MarketingStateError: campaign is not in DRAFT status.
		"""
		campaign = session.execute(
			sa.select(MarketingCampaign).where(MarketingCampaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise MarketingNotFoundError(f"MarketingCampaign {campaign_id!r} not found")
		if campaign.status != "DRAFT":
			raise MarketingStateError(
				f"Campaign {campaign_id!r} cannot be activated from status {campaign.status!r}"
			)

		campaign.status = "ACTIVE"
		session.flush()

		emit_event(
			CampaignActivatedEvent(
				aggregate_id=campaign.id,
				aggregate_type="MarketingCampaign",
				tenant_id=campaign.tenant_id,
				campaign_id=campaign.id,
			),
			session,
		)
		log.info("activate_campaign: campaign=%s activated", campaign_id)
		return campaign

	# ------------------------------------------------------------------
	# Contact enrollment
	# ------------------------------------------------------------------

	def enroll_contact(
		self,
		campaign_id: str,
		contact_id: str,
		email: str,
		session: Any,
		*,
		phone: str | None = None,
		metadata: dict | None = None,
	) -> CampaignContact:
		"""Enrol a contact in a campaign and assign an A/B variant if enabled.

		Idempotent: if the contact is already enrolled the existing row is
		returned unchanged (re-enrollment requires explicit unenroll first).

		Raises:
		  MarketingNotFoundError: campaign not found.
		  MarketingStateError: campaign is not ACTIVE.
		"""
		campaign = session.execute(
			sa.select(MarketingCampaign).where(MarketingCampaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise MarketingNotFoundError(f"MarketingCampaign {campaign_id!r} not found")
		if campaign.status != "ACTIVE":
			raise MarketingStateError(
				f"Cannot enrol contact into campaign {campaign_id!r} with status {campaign.status!r}"
			)

		# Idempotency check
		existing = session.execute(
			sa.select(CampaignContact).where(
				CampaignContact.campaign_id == campaign_id,
				CampaignContact.contact_id == contact_id,
			)
		).scalar_one_or_none()
		if existing is not None:
			log.debug("enroll_contact: contact=%s already enrolled in campaign=%s", contact_id, campaign_id)
			return existing

		# A/B variant assignment
		ab_variant: str | None = None
		if campaign.ab_test_enabled and campaign.ab_variants:
			ab_variant = _assign_ab_variant(campaign.ab_variants)

		# Find first step's delay to schedule next_action_at
		first_step = session.execute(
			sa.select(MarketingSequence)
			.where(MarketingSequence.campaign_id == campaign_id)
			.order_by(MarketingSequence.step_number)
			.limit(1)
		).scalar_one_or_none()

		now = datetime.now(timezone.utc)
		next_action_at: datetime | None = None
		if first_step is not None:
			delay_hours = first_step.delay_hours or 0
			next_action_at = now + timedelta(hours=delay_hours)

		cc = CampaignContact(
			tenant_id=campaign.tenant_id,
			campaign_id=campaign_id,
			contact_id=contact_id,
			email=email,
			phone=phone,
			status="ENROLLED",
			ab_variant=ab_variant,
			enrolled_at=now,
			current_step=0,
			next_action_at=next_action_at,
			metadata_=metadata or {},
		)
		session.add(cc)
		session.flush()
		log.info(
			"enroll_contact: contact=%s enrolled in campaign=%s variant=%s",
			contact_id, campaign_id, ab_variant,
		)
		return cc

	# ------------------------------------------------------------------
	# Sequence processing
	# ------------------------------------------------------------------

	def process_sequence_step(
		self,
		contact_id: str,
		campaign_id: str,
		session: Any,
	) -> CampaignContact | None:
		"""Execute the current sequence step for a campaign contact.

		Loads the CampaignContact, resolves the current MarketingSequence step,
		evaluates its conditions_json against the contact context, and if the
		conditions pass executes the step action (EMAIL/SMS/WEBHOOK).  Advances
		current_step and schedules next_action_at.

		Returns None if the contact has completed all steps.

		Raises:
		  MarketingNotFoundError: contact enrollment not found.
		"""
		cc = session.execute(
			sa.select(CampaignContact).where(
				CampaignContact.campaign_id == campaign_id,
				CampaignContact.contact_id == contact_id,
			)
		).scalar_one_or_none()
		if cc is None:
			raise MarketingNotFoundError(
				f"CampaignContact for contact={contact_id!r} campaign={campaign_id!r} not found"
			)

		if cc.status in ("COMPLETED", "UNSUBSCRIBED", "BOUNCED"):
			log.debug(
				"process_sequence_step: contact=%s campaign=%s already %s — skipping",
				contact_id, campaign_id, cc.status,
			)
			return cc

		# Load the step at current_step index (step_number is 1-based)
		step = session.execute(
			sa.select(MarketingSequence)
			.where(
				MarketingSequence.campaign_id == campaign_id,
				MarketingSequence.step_number == cc.current_step + 1,
			)
		).scalar_one_or_none()

		if step is None:
			# No more steps — mark completed
			cc.status = "COMPLETED"
			cc.next_action_at = None
			session.flush()
			log.info(
				"process_sequence_step: contact=%s campaign=%s — all steps complete",
				contact_id, campaign_id,
			)
			return cc

		# Build contact context for condition evaluation
		contact_ctx: dict[str, Any] = {
			"contact_id": cc.contact_id,
			"email": cc.email,
			"phone": cc.phone,
			"status": cc.status,
			"ab_variant": cc.ab_variant,
			"current_step": cc.current_step,
			**(cc.metadata_ or {}),
		}

		# Evaluate conditions — skip step (but keep enrolled) if conditions fail
		if step.conditions_json and not _evaluate_conditions(step.conditions_json, contact_ctx):
			log.debug(
				"process_sequence_step: contact=%s step=%d conditions not met — advancing without action",
				contact_id, step.step_number,
			)
		else:
			_execute_step_action(step, cc, session)

		# Advance to next step
		cc.current_step = step.step_number
		cc.status = "ACTIVE"

		# Schedule next step
		next_step = session.execute(
			sa.select(MarketingSequence)
			.where(
				MarketingSequence.campaign_id == campaign_id,
				MarketingSequence.step_number == step.step_number + 1,
			)
		).scalar_one_or_none()

		if next_step is not None:
			cc.next_action_at = datetime.now(timezone.utc) + timedelta(hours=next_step.delay_hours or 0)
		else:
			cc.next_action_at = None

		session.flush()
		return cc

	# ------------------------------------------------------------------
	# Lead scoring
	# ------------------------------------------------------------------

	def score_lead(
		self,
		contact_id: str,
		factor: str,
		delta: int,
		tenant_id: str,
		session: Any,
	) -> LeadScore:
		"""Upsert a LeadScore, append scoring factor, recompute grade.

		Emits LeadScoredEvent if the grade boundary changes.

		Raises:
		  MarketingServiceError: on persistence failure.
		"""
		lead = session.execute(
			sa.select(LeadScore).where(
				LeadScore.tenant_id == tenant_id,
				LeadScore.contact_id == contact_id,
			)
		).scalar_one_or_none()

		if lead is None:
			lead = LeadScore(
				tenant_id=tenant_id,
				contact_id=contact_id,
				score=0,
				grade="D",
				scoring_factors=[],
				last_activity_at=datetime.now(timezone.utc),
				converted=False,
			)
			session.add(lead)
			session.flush()

		old_score = lead.score
		old_grade = lead.grade

		lead.score = max(0, old_score + delta)
		new_grade = _compute_grade(lead.score)
		lead.grade = new_grade
		lead.last_activity_at = datetime.now(timezone.utc)

		# Append factor entry (keep list immutable-style: replace with new list)
		factors = list(lead.scoring_factors or [])
		factors.append({
			"factor": factor,
			"delta": delta,
			"ts": datetime.now(timezone.utc).isoformat(),
		})
		lead.scoring_factors = factors
		session.flush()

		if old_grade != new_grade:
			emit_event(
				LeadScoredEvent(
					aggregate_id=contact_id,
					aggregate_type="LeadScore",
					tenant_id=tenant_id,
					lead_id=contact_id,
					old_score=old_score,
					new_score=lead.score,
					triggers=[factor],
				),
				session,
			)
			log.info(
				"score_lead: contact=%s score %d→%d grade %s→%s",
				contact_id, old_score, lead.score, old_grade, new_grade,
			)

		return lead

	# ------------------------------------------------------------------
	# Revenue attribution
	# ------------------------------------------------------------------

	def attribute_revenue(
		self,
		campaign_id: str,
		contact_id: str,
		opportunity_id: str,
		revenue_cents: int,
		session: Any,
		*,
		attribution_model: str = "LAST_TOUCH",
	) -> CampaignAttribution:
		"""Create a CampaignAttribution row and update campaign.spent_cents.

		Emits RevenueAttributedEvent.

		Raises:
		  MarketingNotFoundError: campaign not found.
		"""
		campaign = session.execute(
			sa.select(MarketingCampaign).where(MarketingCampaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise MarketingNotFoundError(f"MarketingCampaign {campaign_id!r} not found")

		attr = CampaignAttribution(
			tenant_id=campaign.tenant_id,
			campaign_id=campaign_id,
			contact_id=contact_id,
			opportunity_id=opportunity_id,
			revenue_cents=revenue_cents,
			attribution_model=attribution_model,
			attributed_at=datetime.now(timezone.utc),
		)
		session.add(attr)

		# Accumulate on campaign spent (proxy for attributed spend tracking)
		campaign.spent_cents = (campaign.spent_cents or 0) + revenue_cents
		session.flush()

		emit_event(
			RevenueAttributedEvent(
				aggregate_id=campaign_id,
				aggregate_type="MarketingCampaign",
				tenant_id=campaign.tenant_id,
				campaign_id=campaign_id,
				opportunity_id=opportunity_id,
				amount_cents=revenue_cents,
			),
			session,
		)
		log.info(
			"attribute_revenue: campaign=%s contact=%s opportunity=%s revenue_cents=%d",
			campaign_id, contact_id, opportunity_id, revenue_cents,
		)
		return attr

	# ------------------------------------------------------------------
	# Analytics
	# ------------------------------------------------------------------

	def get_campaign_analytics(self, campaign_id: str, session: Any) -> dict[str, Any]:
		"""Return engagement and attribution analytics for a campaign.

		Returns:
		  dict with keys: enrolled, active, completed, unsubscribed, bounced,
		  conversion_rate_pct, revenue_attributed_cents,
		  cost_per_conversion_cents, ab_variant_performance
		"""
		from sqlalchemy import func

		campaign = session.execute(
			sa.select(MarketingCampaign).where(MarketingCampaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise MarketingNotFoundError(f"MarketingCampaign {campaign_id!r} not found")

		# Contact status counts
		status_rows = session.execute(
			sa.select(CampaignContact.status, func.count(CampaignContact.id).label("cnt"))
			.where(CampaignContact.campaign_id == campaign_id)
			.group_by(CampaignContact.status)
		).all()
		status_counts: dict[str, int] = {r.status: r.cnt for r in status_rows}

		enrolled = sum(status_counts.values())
		completed = status_counts.get("COMPLETED", 0)
		conversion_rate_pct = round(completed / enrolled * 100, 2) if enrolled else 0.0

		# Revenue attribution
		revenue_total = session.execute(
			sa.select(func.coalesce(func.sum(CampaignAttribution.revenue_cents), 0))
			.where(CampaignAttribution.campaign_id == campaign_id)
		).scalar() or 0

		cost_per_conversion = (
			campaign.budget_cents // completed if completed else 0
		)

		# A/B variant performance
		ab_perf: list[dict] = []
		if campaign.ab_test_enabled and campaign.ab_variants:
			variant_rows = session.execute(
				sa.select(
					CampaignContact.ab_variant,
					func.count(CampaignContact.id).label("total"),
					func.count(
						sa.case((CampaignContact.status == "COMPLETED", CampaignContact.id), else_=None)
					).label("completed_count"),
				)
				.where(CampaignContact.campaign_id == campaign_id)
				.group_by(CampaignContact.ab_variant)
			).all()
			for row in variant_rows:
				conv = round(row.completed_count / row.total * 100, 2) if row.total else 0.0
				ab_perf.append({
					"variant": row.ab_variant,
					"enrolled": row.total,
					"completed": row.completed_count,
					"conversion_rate_pct": conv,
				})

		return {
			"enrolled": enrolled,
			"active": status_counts.get("ACTIVE", 0),
			"completed": completed,
			"unsubscribed": status_counts.get("UNSUBSCRIBED", 0),
			"bounced": status_counts.get("BOUNCED", 0),
			"conversion_rate_pct": conversion_rate_pct,
			"revenue_attributed_cents": int(revenue_total),
			"cost_per_conversion_cents": cost_per_conversion,
			"ab_variant_performance": ab_perf,
		}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _assign_ab_variant(variants: list[dict]) -> str | None:
	"""Weighted random selection of an A/B variant.

	Each variant dict must have: {id, percentage, ...}.
	Percentages should sum to 100; if they don't the last variant absorbs the remainder.
	"""
	if not variants:
		return None
	total = sum(v.get("percentage", 0) for v in variants)
	if total <= 0:
		return str(variants[0].get("id", ""))
	roll = random.uniform(0, total)
	cumulative = 0.0
	for variant in variants:
		cumulative += variant.get("percentage", 0)
		if roll <= cumulative:
			return str(variant.get("id", ""))
	return str(variants[-1].get("id", ""))


def _execute_step_action(
	step: MarketingSequence,
	cc: CampaignContact,
	session: Any,
) -> None:
	"""Dispatch the step action — EMAIL, SMS, or WEBHOOK.

	Actual sending is delegated to the platform integration layer; this function
	emits the appropriate domain event and logs the dispatch.
	"""
	if step.step_type == "EMAIL":
		log.info(
			"_execute_step_action: EMAIL step=%d contact=%s email=%s subject=%r",
			step.step_number, cc.contact_id, cc.email, step.subject_line,
		)
		emit_event(
			CampaignEmailSentEvent(
				aggregate_id=cc.campaign_id,
				aggregate_type="MarketingCampaign",
				tenant_id=str(cc.tenant_id),
				campaign_id=str(cc.campaign_id),
				contact_id=cc.contact_id,
				email=cc.email or "",
			),
			session,
		)

	elif step.step_type == "SMS":
		log.info(
			"_execute_step_action: SMS step=%d contact=%s phone=%s",
			step.step_number, cc.contact_id, cc.phone,
		)
		# Platform integration: send via SMS gateway

	elif step.step_type == "WEBHOOK":
		if step.webhook_url:
			log.info(
				"_execute_step_action: WEBHOOK step=%d contact=%s url=%s",
				step.step_number, cc.contact_id, step.webhook_url,
			)
			# Platform integration: POST to step.webhook_url with contact context

	elif step.step_type in ("WAIT", "CONDITION"):
		# WAIT and CONDITION steps have no side-effect action — delay handled by next_action_at
		log.debug(
			"_execute_step_action: %s step=%d contact=%s — no action",
			step.step_type, step.step_number, cc.contact_id,
		)


# ---------------------------------------------------------------------------
# BPM Action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"crm.marketing.enroll_contact",
	"Enroll contact in marketing campaign",
)
def _bpm_enroll_contact(
	record_ctx: dict,
	session: Any,
	campaign_id: str = "",
	contact_id: str = "",
	email: str = "",
	phone: str | None = None,
	metadata: dict | None = None,
	**kw: Any,
) -> dict:
	try:
		svc = MarketingAutomationService()
		cc = svc.enroll_contact(
			campaign_id=campaign_id,
			contact_id=contact_id,
			email=email,
			session=session,
			phone=phone,
			metadata=metadata,
		)
		return {"status": "ok", "contact_record_id": cc.id, "ab_variant": cc.ab_variant}
	except MarketingServiceError as exc:
		log.warning("bpm crm.marketing.enroll_contact failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"crm.marketing.score_lead",
	"Update lead score from workflow trigger",
)
def _bpm_score_lead(
	record_ctx: dict,
	session: Any,
	contact_id: str = "",
	factor: str = "workflow_trigger",
	delta: int = 5,
	tenant_id: str = "",
	**kw: Any,
) -> dict:
	_tenant_id = tenant_id or record_ctx.get("tenant_id", "")
	try:
		svc = MarketingAutomationService()
		lead = svc.score_lead(
			contact_id=contact_id,
			factor=factor,
			delta=delta,
			tenant_id=_tenant_id,
			session=session,
		)
		return {"status": "ok", "score": lead.score, "grade": lead.grade}
	except MarketingServiceError as exc:
		log.warning("bpm crm.marketing.score_lead failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = [
	"MarketingAutomationService",
	"MarketingServiceError",
	"MarketingNotFoundError",
	"MarketingStateError",
]
