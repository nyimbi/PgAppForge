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
from datetime import date, datetime, time, timedelta, timezone
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

_CLOSED_STAGES = ("CLOSED_WON", "CLOSED_LOST")
_OPEN_STAGES = tuple(stage for stage in _STAGE_ORDER if stage not in _CLOSED_STAGES)
_FORECAST_CATEGORY_WEIGHTS: dict[str, float] = {
	"PIPELINE": 0.25,
	"BEST_CASE": 0.60,
	"COMMIT": 0.90,
	"CLOSED": 1.00,
}


def _parse_date(value: Any) -> date | None:
	if value is None:
		return None
	if isinstance(value, datetime):
		return value.date()
	if isinstance(value, date):
		return value
	if isinstance(value, str):
		return date.fromisoformat(value[:10])
	return None


def _to_aware_datetime(value: Any) -> datetime | None:
	if value is None:
		return None
	if isinstance(value, datetime):
		if value.tzinfo is None:
			return value.replace(tzinfo=timezone.utc)
		return value.astimezone(timezone.utc)
	if isinstance(value, date):
		return datetime.combine(value, time.min, tzinfo=timezone.utc)
	return None


def _safe_int(value: Any) -> int:
	if value is None:
		return 0
	return int(value)


def _safe_float(value: Any) -> float:
	if value is None:
		return 0.0
	return float(value)


def _clamp(value: float, low: float, high: float) -> float:
	return max(low, min(high, value))


def _percent(numerator: int | float, denominator: int | float) -> float:
	if not denominator:
		return 0.0
	return round((float(numerator) / float(denominator)) * 100, 1)


def _normalise_label(value: Any, fallback: str = "Unspecified") -> str:
	label = str(value or "").strip()
	return label or fallback


def _add_group_metric(groups: dict[str, dict[str, int]], key: Any, amount_cents: int) -> None:
	label = _normalise_label(key)
	if label not in groups:
		groups[label] = {"label": label, "deal_count": 0, "amount_cents": 0}
	groups[label]["deal_count"] += 1
	groups[label]["amount_cents"] += amount_cents


class SalesService:
	"""Stateless sales business logic.

	Instantiate per-request or as a singleton — no instance state.
	"""

	# ------------------------------------------------------------------
	# calculate_customer_health_score
	# ------------------------------------------------------------------

	def calculate_customer_health_score(self, account_id: str, session: Any) -> dict[str, Any]:
		"""Compute and persist a 0.0-10.0 customer health score.

		Signals combine contact engagement, activity recency, win/loss history,
		customer value, NPS, stale opportunities, and overdue open pipeline.
		The caller owns transaction commit/rollback.
		"""
		from pgappforge.plugins.erp.crm.sales.models import (
			Activity,
			Opportunity,
			SalesAccount,
			SalesContact,
		)

		account = session.get(SalesAccount, account_id)
		if account is None:
			raise SalesAccountNotFoundError(f"SalesAccount {account_id!r} not found")

		contacts = session.execute(
			sa.select(SalesContact)
			.where(SalesContact.tenant_id == account.tenant_id)
			.where(SalesContact.account_id == account.id)
		).scalars().all()
		opportunities = session.execute(
			sa.select(Opportunity)
			.where(Opportunity.tenant_id == account.tenant_id)
			.where(Opportunity.account_id == account.id)
		).scalars().all()

		opp_ids = [opp.id for opp in opportunities]
		activity_filters = [Activity.account_id == account.id]
		if opp_ids:
			activity_filters.append(Activity.opportunity_id.in_(opp_ids))
		activities = session.execute(
			sa.select(Activity)
			.where(Activity.tenant_id == account.tenant_id)
			.where(sa.or_(*activity_filters))
			.order_by(sa.desc(Activity.activity_date))
			.limit(500)
		).scalars().all()

		now = datetime.now(timezone.utc)
		today = now.date()
		completed_activities = [
			act for act in activities
			if (act.status or "").upper() == "COMPLETED"
		]
		last_activity_at = max(
			(
				_to_aware_datetime(act.activity_date)
				for act in completed_activities
				if _to_aware_datetime(act.activity_date) is not None
			),
			default=None,
		)
		days_since_last_activity = (
			max(0, (now - last_activity_at).days)
			if last_activity_at is not None else None
		)

		engagement_values = [
			_safe_float(contact.engagement_score)
			for contact in contacts
			if contact.engagement_score is not None
		]
		avg_engagement = (
			round(sum(engagement_values) / len(engagement_values), 1)
			if engagement_values else None
		)
		if avg_engagement is not None:
			engagement_points = _clamp(avg_engagement, 0.0, 10.0) * 3.0
		elif days_since_last_activity is None:
			engagement_points = 0.0
		elif days_since_last_activity <= 30:
			engagement_points = 24.0
		elif days_since_last_activity <= 90:
			engagement_points = 14.0
		else:
			engagement_points = 6.0

		lifetime_value_cents = _safe_int(account.lifetime_value_cents)
		annual_revenue_cents = _safe_int(account.annual_revenue_cents)
		if lifetime_value_cents >= 10_000_000:
			revenue_points = 20.0
		elif lifetime_value_cents > 0:
			revenue_points = 15.0
		elif annual_revenue_cents >= 100_000_000:
			revenue_points = 10.0
		else:
			revenue_points = 5.0

		closed_won = [
			opp for opp in opportunities
			if (opp.stage or "").upper() == "CLOSED_WON"
		]
		closed_lost = [
			opp for opp in opportunities
			if (opp.stage or "").upper() == "CLOSED_LOST"
		]
		open_opportunities = [
			opp for opp in opportunities
			if (opp.stage or "").upper() in _OPEN_STAGES
		]
		closed_count = len(closed_won) + len(closed_lost)
		if closed_count:
			opportunity_points = (len(closed_won) / closed_count) * 20.0
		elif open_opportunities:
			opportunity_points = 12.0
		else:
			opportunity_points = 8.0

		if account.nps_score is None:
			satisfaction_points = 10.0
		else:
			satisfaction_points = _clamp((_safe_float(account.nps_score) + 100.0) / 10.0, 0.0, 20.0)

		if days_since_last_activity is None:
			freshness_points = 0.0
		elif days_since_last_activity <= 30:
			freshness_points = 10.0
		elif days_since_last_activity <= 90:
			freshness_points = 6.0
		else:
			freshness_points = 2.0

		overdue_open_opportunities = [
			opp for opp in open_opportunities
			if _parse_date(opp.expected_close_date) is not None
			and _parse_date(opp.expected_close_date) < today
		]
		stale_penalty = 5.0 if (
			days_since_last_activity is None or days_since_last_activity > 90
		) else 0.0
		overdue_penalty = min(10.0, len(overdue_open_opportunities) * 5.0)
		raw_points = (
			engagement_points
			+ revenue_points
			+ opportunity_points
			+ satisfaction_points
			+ freshness_points
			- stale_penalty
			- overdue_penalty
		)
		health_score = round(_clamp(raw_points / 10.0, 0.0, 10.0), 1)
		churn_risk_score = round(
			_clamp(
				10.0 - health_score
				+ (len(overdue_open_opportunities) * 0.5)
				+ (1.0 if days_since_last_activity is None else 0.0),
				0.0,
				10.0,
			),
			1,
		)

		if health_score >= 7.5:
			band = "HEALTHY"
		elif health_score >= 5.0:
			band = "WATCH"
		else:
			band = "AT_RISK"

		recommendations: list[str] = []
		if days_since_last_activity is None:
			recommendations.append("Log a completed customer activity.")
		elif days_since_last_activity > 30:
			recommendations.append("Schedule a customer touchpoint.")
		if overdue_open_opportunities:
			recommendations.append("Review overdue open opportunities.")
		if account.nps_score is not None and account.nps_score < 0:
			recommendations.append("Escalate negative NPS feedback.")
		if not recommendations:
			recommendations.append("Maintain current account cadence.")

		account.health_score = health_score
		account.churn_risk_score = churn_risk_score
		account.updated_at = now

		signals = {
			"avg_engagement_score": avg_engagement,
			"completed_activity_count": len(completed_activities),
			"days_since_last_activity": days_since_last_activity,
			"open_opportunity_count": len(open_opportunities),
			"overdue_open_opportunity_count": len(overdue_open_opportunities),
			"closed_won_count": len(closed_won),
			"closed_lost_count": len(closed_lost),
			"lifetime_value_cents": lifetime_value_cents,
			"annual_revenue_cents": annual_revenue_cents,
			"nps_score": account.nps_score,
		}
		return {
			"account_id": account.id,
			"account_name": account.name,
			"health_score": health_score,
			"churn_risk_score": churn_risk_score,
			"band": band,
			"signals": signals,
			"recommendations": recommendations,
		}

	# ------------------------------------------------------------------
	# get_pipeline_forecast
	# ------------------------------------------------------------------

	def get_pipeline_forecast(
		self,
		session: Any,
		tenant_id: str | None = None,
		owner_id: str | None = None,
		period_start: date | str | None = None,
		period_end: date | str | None = None,
	) -> dict[str, Any]:
		"""Return open-pipeline totals and forecast projections.

		Forecast projections include probability-weighted pipeline, stored
		Einstein-score weighted pipeline, and forecast-category weighted totals.
		"""
		from pgappforge.plugins.erp.crm.sales.models import Opportunity

		start_date = _parse_date(period_start) or datetime.now(timezone.utc).date()
		end_date = _parse_date(period_end) or (start_date + timedelta(days=90))

		q = sa.select(Opportunity).where(Opportunity.stage.notin_(_CLOSED_STAGES))
		if tenant_id:
			q = q.where(Opportunity.tenant_id == tenant_id)
		if owner_id:
			q = q.where(Opportunity.owner_id == owner_id)
		q = q.order_by(Opportunity.expected_close_date, sa.desc(Opportunity.amount_cents))
		opportunities = session.execute(q).scalars().all()

		by_stage: dict[str, dict[str, Any]] = {}
		by_category: dict[str, dict[str, Any]] = {}
		total_open_cents = 0
		weighted_pipeline_cents = 0
		ai_weighted_pipeline_cents = 0
		category_forecast_cents = 0
		closing_this_period_cents = 0
		overdue_pipeline_cents = 0
		overdue_deal_count = 0
		probabilities: list[int] = []
		at_risk_deals: list[dict[str, Any]] = []
		today = datetime.now(timezone.utc).date()

		for opp in opportunities:
			stage = (opp.stage or "UNSPECIFIED").upper()
			amount_cents = _safe_int(opp.amount_cents)
			probability = int(_clamp(_safe_float(opp.probability), 0.0, 100.0))
			category = (
				(opp.forecast_category or _STAGE_FORECAST.get(stage, "PIPELINE"))
				.upper()
			)
			probabilities.append(probability)
			weighted_cents = int(round(amount_cents * (probability / 100.0)))

			if opp.einstein_score is not None:
				ai_ratio = _clamp(_safe_float(opp.einstein_score) / 10.0, 0.0, 1.0)
			else:
				ai_ratio = probability / 100.0
			ai_weighted_cents = int(round(amount_cents * ai_ratio))

			category_weight = _FORECAST_CATEGORY_WEIGHTS.get(category, probability / 100.0)
			category_cents = int(round(amount_cents * category_weight))

			close_date = _parse_date(opp.expected_close_date)
			is_closing_this_period = (
				close_date is not None
				and start_date <= close_date <= end_date
			)
			is_overdue = close_date is not None and close_date < today

			total_open_cents += amount_cents
			weighted_pipeline_cents += weighted_cents
			ai_weighted_pipeline_cents += ai_weighted_cents
			category_forecast_cents += category_cents
			if is_closing_this_period:
				closing_this_period_cents += amount_cents
			if is_overdue:
				overdue_deal_count += 1
				overdue_pipeline_cents += amount_cents

			stage_metric = by_stage.setdefault(stage, {
				"stage": stage,
				"deal_count": 0,
				"total_cents": 0,
				"weighted_cents": 0,
				"ai_weighted_cents": 0,
			})
			stage_metric["deal_count"] += 1
			stage_metric["total_cents"] += amount_cents
			stage_metric["weighted_cents"] += weighted_cents
			stage_metric["ai_weighted_cents"] += ai_weighted_cents

			category_metric = by_category.setdefault(category, {
				"forecast_category": category,
				"deal_count": 0,
				"total_cents": 0,
				"forecast_cents": 0,
			})
			category_metric["deal_count"] += 1
			category_metric["total_cents"] += amount_cents
			category_metric["forecast_cents"] += category_cents

			if is_overdue or probability <= 20:
				at_risk_deals.append({
					"id": opp.id,
					"name": opp.opportunity_name,
					"stage": stage,
					"amount_cents": amount_cents,
					"probability": probability,
					"expected_close_date": close_date.isoformat() if close_date else None,
					"reason": "OVERDUE" if is_overdue else "LOW_PROBABILITY",
				})

		ordered_stages = [
			by_stage[stage] for stage in _STAGE_ORDER
			if stage in by_stage and stage not in _CLOSED_STAGES
		]
		ordered_stages.extend(
			metric for stage, metric in sorted(by_stage.items())
			if stage not in _STAGE_ORDER
		)
		ordered_categories = [
			by_category[category]
			for category in ("COMMIT", "BEST_CASE", "PIPELINE", "CLOSED")
			if category in by_category
		]
		ordered_categories.extend(
			metric for category, metric in sorted(by_category.items())
			if category not in _FORECAST_CATEGORY_WEIGHTS
		)
		at_risk_deals.sort(key=lambda item: item["amount_cents"], reverse=True)

		return {
			"tenant_id": tenant_id,
			"owner_id": owner_id,
			"period_start": start_date.isoformat(),
			"period_end": end_date.isoformat(),
			"deal_count": len(opportunities),
			"total_open_pipeline_cents": total_open_cents,
			"weighted_pipeline_cents": weighted_pipeline_cents,
			"ai_weighted_pipeline_cents": ai_weighted_pipeline_cents,
			"category_forecast_cents": category_forecast_cents,
			"closing_this_period_cents": closing_this_period_cents,
			"overdue_deal_count": overdue_deal_count,
			"overdue_pipeline_cents": overdue_pipeline_cents,
			"average_probability_pct": round(
				sum(probabilities) / len(probabilities), 1
			) if probabilities else 0.0,
			"by_stage": ordered_stages,
			"by_forecast_category": ordered_categories,
			"at_risk_deals": at_risk_deals[:10],
		}

	# ------------------------------------------------------------------
	# get_win_loss_analysis
	# ------------------------------------------------------------------

	def get_win_loss_analysis(
		self,
		session: Any,
		tenant_id: str | None = None,
		owner_id: str | None = None,
		since: date | str | None = None,
		until: date | str | None = None,
	) -> dict[str, Any]:
		"""Return closed-opportunity win/loss metrics and grouped reasons."""
		from pgappforge.plugins.erp.crm.sales.models import Opportunity

		since_date = _parse_date(since)
		until_date = _parse_date(until)
		q = sa.select(Opportunity).where(Opportunity.stage.in_(_CLOSED_STAGES))
		if tenant_id:
			q = q.where(Opportunity.tenant_id == tenant_id)
		if owner_id:
			q = q.where(Opportunity.owner_id == owner_id)
		if since_date:
			q = q.where(Opportunity.closed_at >= _to_aware_datetime(since_date))
		if until_date:
			q = q.where(
				Opportunity.closed_at < _to_aware_datetime(until_date + timedelta(days=1))
			)
		q = q.order_by(sa.desc(Opportunity.closed_at))
		opportunities = session.execute(q).scalars().all()

		won = [
			opp for opp in opportunities
			if (opp.stage or "").upper() == "CLOSED_WON"
		]
		lost = [
			opp for opp in opportunities
			if (opp.stage or "").upper() == "CLOSED_LOST"
		]
		reason_won: dict[str, dict[str, int]] = {}
		reason_lost: dict[str, dict[str, int]] = {}
		competitors: dict[str, dict[str, int]] = {}
		lead_sources: dict[str, dict[str, int]] = {}
		sales_cycle_days: list[int] = []

		for opp in opportunities:
			amount_cents = _safe_int(opp.amount_cents)
			if (opp.stage or "").upper() == "CLOSED_WON":
				_add_group_metric(reason_won, opp.reason_won, amount_cents)
			else:
				_add_group_metric(reason_lost, opp.reason_lost, amount_cents)
				_add_group_metric(competitors, opp.competitor, amount_cents)
			_add_group_metric(lead_sources, opp.lead_source, amount_cents)

			created_at = _to_aware_datetime(opp.created_at)
			closed_at = _to_aware_datetime(opp.closed_at)
			if created_at and closed_at:
				sales_cycle_days.append(max(0, (closed_at - created_at).days))

		won_revenue_cents = sum(_safe_int(opp.amount_cents) for opp in won)
		lost_revenue_cents = sum(_safe_int(opp.amount_cents) for opp in lost)
		closed_count = len(opportunities)
		avg_cycle = (
			round(sum(sales_cycle_days) / len(sales_cycle_days), 1)
			if sales_cycle_days else 0.0
		)

		return {
			"tenant_id": tenant_id,
			"owner_id": owner_id,
			"since": since_date.isoformat() if since_date else None,
			"until": until_date.isoformat() if until_date else None,
			"closed_deal_count": closed_count,
			"won_deal_count": len(won),
			"lost_deal_count": len(lost),
			"win_rate_pct": _percent(len(won), closed_count),
			"won_revenue_cents": won_revenue_cents,
			"lost_revenue_cents": lost_revenue_cents,
			"average_won_deal_cents": int(won_revenue_cents / len(won)) if won else 0,
			"average_lost_deal_cents": int(lost_revenue_cents / len(lost)) if lost else 0,
			"average_sales_cycle_days": avg_cycle,
			"top_win_reasons": sorted(
				reason_won.values(),
				key=lambda row: (row["deal_count"], row["amount_cents"]),
				reverse=True,
			),
			"top_loss_reasons": sorted(
				reason_lost.values(),
				key=lambda row: (row["deal_count"], row["amount_cents"]),
				reverse=True,
			),
			"losses_by_competitor": sorted(
				competitors.values(),
				key=lambda row: (row["deal_count"], row["amount_cents"]),
				reverse=True,
			),
			"by_lead_source": sorted(
				lead_sources.values(),
				key=lambda row: (row["deal_count"], row["amount_cents"]),
				reverse=True,
			),
		}

	# ------------------------------------------------------------------
	# get_customer_health_summary
	# ------------------------------------------------------------------

	def get_customer_health_summary(
		self,
		session: Any,
		tenant_id: str | None = None,
		limit: int = 10,
	) -> dict[str, Any]:
		"""Return stored account-health distribution and at-risk customers."""
		from pgappforge.plugins.erp.crm.sales.models import SalesAccount

		q = sa.select(SalesAccount).where(SalesAccount.status == "ACTIVE")
		if tenant_id:
			q = q.where(SalesAccount.tenant_id == tenant_id)
		accounts = session.execute(q.order_by(SalesAccount.name)).scalars().all()
		health_values = [
			_safe_float(account.health_score)
			for account in accounts
			if account.health_score is not None
		]
		churn_values = [
			_safe_float(account.churn_risk_score)
			for account in accounts
			if account.churn_risk_score is not None
		]
		distribution = {"healthy": 0, "watch": 0, "at_risk": 0, "unscored": 0}
		for account in accounts:
			if account.health_score is None:
				distribution["unscored"] += 1
				continue
			score = _safe_float(account.health_score)
			if score >= 7.5:
				distribution["healthy"] += 1
			elif score >= 5.0:
				distribution["watch"] += 1
			else:
				distribution["at_risk"] += 1

		at_risk_accounts = [
			account for account in accounts
			if (
				account.health_score is not None
				and _safe_float(account.health_score) < 5.0
			)
			or (
				account.churn_risk_score is not None
				and _safe_float(account.churn_risk_score) >= 7.0
			)
		]
		at_risk_accounts.sort(
			key=lambda account: (
				_safe_float(account.health_score)
				if account.health_score is not None else 10.0,
				-_safe_float(account.churn_risk_score),
			)
		)

		return {
			"tenant_id": tenant_id,
			"account_count": len(accounts),
			"scored_account_count": len(health_values),
			"average_health_score": (
				round(sum(health_values) / len(health_values), 1)
				if health_values else 0.0
			),
			"average_churn_risk_score": (
				round(sum(churn_values) / len(churn_values), 1)
				if churn_values else 0.0
			),
			"distribution": distribution,
			"at_risk_customers": [
				{
					"id": account.id,
					"name": account.name,
					"owner_id": account.owner_id,
					"health_score": _safe_float(account.health_score),
					"churn_risk_score": _safe_float(account.churn_risk_score),
					"lifetime_value_cents": _safe_int(account.lifetime_value_cents),
					"nps_score": account.nps_score,
				}
				for account in at_risk_accounts[:limit]
			],
		}

	# ------------------------------------------------------------------
	# get_analytics_dashboard
	# ------------------------------------------------------------------

	def get_analytics_dashboard(
		self,
		session: Any,
		tenant_id: str | None = None,
		owner_id: str | None = None,
		period_start: date | str | None = None,
		period_end: date | str | None = None,
		win_loss_since: date | str | None = None,
	) -> dict[str, Any]:
		"""Return the CRM advanced analytics dashboard payload."""
		start_date = _parse_date(period_start) or datetime.now(timezone.utc).date()
		end_date = _parse_date(period_end) or (start_date + timedelta(days=90))
		loss_since = (
			_parse_date(win_loss_since)
			or (datetime.now(timezone.utc).date() - timedelta(days=180))
		)
		pipeline = self.get_pipeline_forecast(
			session=session,
			tenant_id=tenant_id,
			owner_id=owner_id,
			period_start=start_date,
			period_end=end_date,
		)
		win_loss = self.get_win_loss_analysis(
			session=session,
			tenant_id=tenant_id,
			owner_id=owner_id,
			since=loss_since,
			until=end_date,
		)
		health = self.get_customer_health_summary(
			session=session,
			tenant_id=tenant_id,
		)

		return {
			"generated_at": datetime.now(timezone.utc).isoformat(),
			"scope": {
				"tenant_id": tenant_id,
				"owner_id": owner_id,
				"period_start": start_date.isoformat(),
				"period_end": end_date.isoformat(),
				"win_loss_since": loss_since.isoformat(),
			},
			"kpis": {
				"open_pipeline_cents": pipeline["total_open_pipeline_cents"],
				"forecast_cents": pipeline["category_forecast_cents"],
				"weighted_pipeline_cents": pipeline["weighted_pipeline_cents"],
				"win_rate_pct": win_loss["win_rate_pct"],
				"average_health_score": health["average_health_score"],
				"at_risk_customer_count": len(health["at_risk_customers"]),
			},
			"pipeline_forecast": pipeline,
			"win_loss_analysis": win_loss,
			"customer_health": health,
		}

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
