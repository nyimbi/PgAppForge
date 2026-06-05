"""
pgappforge/plugins/erp/crm/marketing/services.py

MarketingService — stateless business logic for the Marketing plugin.

Key methods
-----------
  activate_campaign(campaign_id, session) -> Campaign
  complete_campaign(campaign_id, session) -> Campaign
  add_member(campaign_id, party_id, member_type, session) -> CampaignMember
  update_member_status(member_id, status, session) -> CampaignMember
  unsubscribe(campaign_id, party_id, session) -> CampaignMember
  refresh_list_count(list_id, session) -> MarketingList

  -- NEW (world-class gap closure) --
  create_campaign(session, data, tenant_id) -> Campaign
  add_list_members(session, list_id, party_ids, source, tenant_id) -> dict
  build_dynamic_list(session, list_id, tenant_id) -> dict
  send_campaign_asset(session, asset_id, tenant_id) -> dict
  record_campaign_activity(session, campaign_id, metric_type, delta, revenue_cents, tenant_id) -> CampaignMetrics
  score_lead(session, lead_id, activity_type, tenant_id) -> MarketingLead
  qualify_lead(session, lead_id, qualified_by, tenant_id) -> MarketingLead
  convert_lead(session, lead_id, tenant_id) -> dict
  get_campaign_roi(session, campaign_id, tenant_id) -> dict
  get_marketing_dashboard(session, tenant_id) -> dict
  campaign_performance_report(campaign_id, session) -> dict
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa

func = sa.func

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MarketingLead scoring table — EMAIL_OPEN=2, EMAIL_CLICK=5, FORM_SUBMIT=10,
#                      PAGE_VIEW=1, DOWNLOAD=7, CALL=3, MEETING=5
# ---------------------------------------------------------------------------
_SCORE_DELTAS: dict[str, int] = {
	"EMAIL_OPEN": 2,
	"EMAIL_CLICK": 5,
	"FORM_SUBMIT": 10,
	"PAGE_VIEW": 1,
	"DOWNLOAD": 7,
	"CALL": 3,
	"MEETING": 5,
}
_DECAY_DAYS = 30
_DECAY_POINTS = 5


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MarketingError(Exception):
	"""Base exception for Marketing service layer."""


class CampaignNotFoundError(MarketingError):
	pass


class CampaignMemberNotFoundError(MarketingError):
	pass


class ListNotFoundError(MarketingError):
	pass


class LeadNotFoundError(MarketingError):
	pass


class AssetNotFoundError(MarketingError):
	pass


class MarketingValidationError(MarketingError):
	"""Business rule violation."""


# ---------------------------------------------------------------------------
# MarketingService
# ---------------------------------------------------------------------------

class MarketingService:
	"""Stateless business logic for Marketing."""

	# ------------------------------------------------------------------
	# Campaign lifecycle — existing methods
	# ------------------------------------------------------------------

	@staticmethod
	def activate_campaign(campaign_id: str, session: Any) -> Any:
		"""Move campaign DRAFT/SCHEDULED/PLANNING → ACTIVE."""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign
		from pgappforge.plugins.erp.crm.marketing.events import CampaignActivatedEvent
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
		except ImportError:
			emit_event = None  # type: ignore[assignment]

		campaign = session.execute(
			sa.select(Campaign).where(Campaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
		if campaign.status not in ("DRAFT", "SCHEDULED", "PLANNING"):
			raise MarketingValidationError(f"Campaign is {campaign.status!r}, cannot activate")

		campaign.status = "ACTIVE"
		session.flush()

		if emit_event is not None:
			emit_event(CampaignActivatedEvent(
				aggregate_id=campaign.id,
				aggregate_type="Campaign",
				tenant_id=campaign.tenant_id,
				campaign_id=campaign.id,
				campaign_name=campaign.campaign_name,
				campaign_type=campaign.campaign_type,
				budget_cents=campaign.budget_cents or 0,
				start_date=campaign.start_date.isoformat() if campaign.start_date else "",
			), session)

		log.info("MarketingService.activate_campaign: %r activated", campaign.campaign_name)
		return campaign

	@staticmethod
	def complete_campaign(campaign_id: str, session: Any) -> Any:
		"""Move campaign ACTIVE/PAUSED → COMPLETED."""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign
		from pgappforge.plugins.erp.crm.marketing.events import CampaignCompletedEvent
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
		except ImportError:
			emit_event = None  # type: ignore[assignment]

		campaign = session.execute(
			sa.select(Campaign).where(Campaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
		if campaign.status not in ("ACTIVE", "PAUSED"):
			raise MarketingValidationError(
				f"Campaign must be ACTIVE or PAUSED to complete, got {campaign.status!r}"
			)

		campaign.status = "COMPLETED"
		session.flush()

		if emit_event is not None:
			emit_event(CampaignCompletedEvent(
				aggregate_id=campaign.id,
				aggregate_type="Campaign",
				tenant_id=campaign.tenant_id,
				campaign_id=campaign.id,
				campaign_name=campaign.campaign_name,
				actual_cost_cents=campaign.actual_cost_cents,
				actual_leads=campaign.actual_leads,
				actual_revenue_cents=campaign.actual_revenue_cents,
			), session)

		log.info("MarketingService.complete_campaign: %r completed", campaign.campaign_name)
		return campaign

	@staticmethod
	def add_member(
		campaign_id: str,
		party_id: str,
		member_type: str,
		session: Any,
		source_campaign_id: str | None = None,
	) -> Any:
		"""Add a party to a campaign; idempotent (returns existing if already member)."""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CampaignMember

		campaign = session.execute(
			sa.select(Campaign).where(Campaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
		if campaign.status not in ("DRAFT", "SCHEDULED", "PLANNING", "ACTIVE"):
			raise MarketingValidationError(f"Cannot add members to a {campaign.status!r} campaign")

		existing = session.execute(
			sa.select(CampaignMember).where(
				CampaignMember.campaign_id == campaign_id,
				CampaignMember.party_id == party_id,
			)
		).scalar_one_or_none()
		if existing is not None:
			return existing

		member = CampaignMember(
			tenant_id=campaign.tenant_id,
			campaign_id=campaign_id,
			party_id=party_id,
			member_type=member_type,
			status="SENT",
			source_campaign_id=source_campaign_id,
		)
		session.add(member)
		campaign.actual_leads = (campaign.actual_leads or 0) + 1
		session.flush()
		log.debug("MarketingService.add_member: party %s added to campaign %s", party_id, campaign_id)
		return member

	@staticmethod
	def update_member_status(member_id: str, status: str, session: Any) -> Any:
		"""Progress a campaign member through the engagement funnel."""
		from pgappforge.plugins.erp.crm.marketing.models import CampaignMember
		from pgappforge.plugins.erp.crm.marketing.events import LeadRespondedEvent, MemberUnsubscribedEvent
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
		except ImportError:
			emit_event = None  # type: ignore[assignment]

		VALID_STATUS = ("SENT", "DELIVERED", "OPENED", "CLICKED", "RESPONDED", "UNSUBSCRIBED")
		if status not in VALID_STATUS:
			raise MarketingValidationError(f"Invalid status {status!r}")

		member = session.execute(
			sa.select(CampaignMember).where(CampaignMember.id == member_id)
		).scalar_one_or_none()
		if member is None:
			raise CampaignMemberNotFoundError(f"CampaignMember {member_id} not found")

		old_status = member.status
		member.status = status
		now = datetime.now(timezone.utc)

		if emit_event is not None:
			if status == "RESPONDED" and old_status != "RESPONDED":
				member.responded_at = now
				emit_event(LeadRespondedEvent(
					aggregate_id=member.id,
					aggregate_type="CampaignMember",
					tenant_id=member.tenant_id,
					campaign_member_id=member.id,
					campaign_id=member.campaign_id,
					party_id=member.party_id,
					member_type=member.member_type,
					responded_at=now.isoformat(),
				), session)

			if status == "UNSUBSCRIBED":
				emit_event(MemberUnsubscribedEvent(
					aggregate_id=member.id,
					aggregate_type="CampaignMember",
					tenant_id=member.tenant_id,
					campaign_member_id=member.id,
					campaign_id=member.campaign_id,
					party_id=member.party_id,
				), session)

		session.flush()
		log.debug("MarketingService.update_member_status: member %s → %s", member_id, status)
		return member

	@staticmethod
	def unsubscribe(campaign_id: str, party_id: str, session: Any) -> Any:
		"""Opt a party out of a campaign by setting status to UNSUBSCRIBED."""
		from pgappforge.plugins.erp.crm.marketing.models import CampaignMember

		member = session.execute(
			sa.select(CampaignMember).where(
				CampaignMember.campaign_id == campaign_id,
				CampaignMember.party_id == party_id,
			)
		).scalar_one_or_none()
		if member is None:
			raise CampaignMemberNotFoundError(f"Party {party_id} not in campaign {campaign_id}")

		return MarketingService.update_member_status(member.id, "UNSUBSCRIBED", session)

	@staticmethod
	def refresh_list_count(list_id: str, session: Any) -> Any:
		"""Recount ACTIVE members and update denormalised member_count on a MarketingList."""
		from pgappforge.plugins.erp.crm.marketing.models import MarketingList, MarketingListMember

		mlist = session.execute(
			sa.select(MarketingList).where(MarketingList.id == list_id)
		).scalar_one_or_none()
		if mlist is None:
			raise ListNotFoundError(f"MarketingList {list_id} not found")

		count: int = session.execute(
			sa.select(func.count(MarketingListMember.id)).where(
				MarketingListMember.list_id == list_id,
				MarketingListMember.status == "ACTIVE",
			)
		).scalar_one()

		mlist.member_count = count
		mlist.last_synced_at = datetime.now(timezone.utc)
		session.flush()
		log.debug("MarketingService.refresh_list_count: list %s → %d active members", list_id, count)
		return mlist

	@staticmethod
	def campaign_performance_report(campaign_id: str, session: Any) -> dict[str, Any]:
		"""Engagement funnel breakdown for a campaign.

		Returns counts at each funnel stage and open rate / click rate.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CampaignMember

		campaign = session.execute(
			sa.select(Campaign).where(Campaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise CampaignNotFoundError(f"Campaign {campaign_id} not found")

		funnel_rows = session.execute(
			sa.select(CampaignMember.status, func.count(CampaignMember.id).label("cnt"))
			.where(CampaignMember.campaign_id == campaign_id)
			.group_by(CampaignMember.status)
		).all()
		funnel = {row.status: row.cnt for row in funnel_rows}

		sent = sum(funnel.values())
		delivered = sent - funnel.get("SENT", 0)
		opened = funnel.get("OPENED", 0) + funnel.get("CLICKED", 0) + funnel.get("RESPONDED", 0)
		clicked = funnel.get("CLICKED", 0) + funnel.get("RESPONDED", 0)

		open_rate = round(opened / delivered * 100, 1) if delivered else None
		click_rate = round(clicked / opened * 100, 1) if opened else None

		roi_pct = None
		if campaign.budget_cents and campaign.budget_cents > 0:
			roi_pct = round(
				(campaign.actual_revenue_cents - campaign.actual_cost_cents) / campaign.budget_cents * 100, 1
			)

		return {
			"campaign_id": campaign_id,
			"campaign_name": campaign.campaign_name,
			"status": campaign.status,
			"funnel": funnel,
			"total_members": sent,
			"open_rate_pct": open_rate,
			"click_rate_pct": click_rate,
			"actual_cost_cents": campaign.actual_cost_cents,
			"actual_revenue_cents": campaign.actual_revenue_cents,
			"roi_pct": roi_pct,
		}

	# ------------------------------------------------------------------
	# NEW: create_campaign
	# ------------------------------------------------------------------

	@staticmethod
	def create_campaign(session: Any, data: dict[str, Any], tenant_id: str) -> Any:
		"""Create a Campaign with full validation.

		Required keys in data: campaign_name, campaign_type.
		Optional: code, status, goal_type, start_date, end_date, budget_cents,
		          target_list_id, owner_id, target_leads, target_revenue_cents,
		          target_audience.

		Returns the persisted Campaign.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CAMPAIGN_TYPE, CAMPAIGN_STATUS

		name = (data.get("campaign_name") or "").strip()
		if not name:
			raise MarketingValidationError("campaign_name is required")

		c_type = (data.get("campaign_type") or "").upper()
		if c_type not in CAMPAIGN_TYPE:
			raise MarketingValidationError(
				f"campaign_type must be one of {CAMPAIGN_TYPE}, got {c_type!r}"
			)

		status = (data.get("status") or "DRAFT").upper()
		if status not in CAMPAIGN_STATUS:
			raise MarketingValidationError(f"Invalid status {status!r}")

		campaign = Campaign(
			tenant_id=tenant_id,
			code=data.get("code"),
			campaign_name=name,
			campaign_type=c_type,
			status=status,
			goal_type=data.get("goal_type"),
			start_date=data.get("start_date"),
			end_date=data.get("end_date"),
			budget_cents=data.get("budget_cents"),
			target_list_id=data.get("target_list_id"),
			owner_id=data.get("owner_id"),
			target_leads=data.get("target_leads"),
			target_revenue_cents=data.get("target_revenue_cents"),
			target_audience=data.get("target_audience") or {},
		)
		session.add(campaign)
		session.flush()
		log.info(
			"MarketingService.create_campaign: created %r type=%s tenant=%s",
			campaign.campaign_name, campaign.campaign_type, tenant_id,
		)
		return campaign

	# ------------------------------------------------------------------
	# NEW: add_list_members (bulk)
	# ------------------------------------------------------------------

	@staticmethod
	def add_list_members(
		session: Any,
		list_id: str,
		party_ids: list[str],
		source: str,
		tenant_id: str,
	) -> dict[str, int]:
		"""Bulk-add party UUIDs to a MarketingList.

		Idempotent: existing ACTIVE members are skipped.
		Existing UNSUBSCRIBED/BOUNCED members are also skipped — use explicit
		re-subscription flow to override.

		Returns {"added": N, "skipped": M}.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import MarketingList, MarketingListMember

		mlist = session.execute(
			sa.select(MarketingList).where(
				MarketingList.id == list_id,
				MarketingList.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if mlist is None:
			raise ListNotFoundError(f"MarketingList {list_id} not found for tenant {tenant_id}")

		# Fetch all existing memberships in one query
		existing_rows = session.execute(
			sa.select(MarketingListMember.party_id, MarketingListMember.status).where(
				MarketingListMember.list_id == list_id,
				MarketingListMember.party_id.in_(party_ids),
			)
		).all()
		existing_map: dict[str, str] = {str(r.party_id): r.status for r in existing_rows}

		added = 0
		skipped = 0
		now = datetime.now(timezone.utc)

		for pid in party_ids:
			if pid in existing_map:
				skipped += 1
				continue
			session.add(MarketingListMember(
				tenant_id=tenant_id,
				list_id=list_id,
				party_id=pid,
				added_at=now,
				status="ACTIVE",
				source=source,
			))
			added += 1

		if added:
			mlist.member_count = (mlist.member_count or 0) + added
			mlist.last_synced_at = now

		session.flush()
		log.info(
			"MarketingService.add_list_members: list %s added=%d skipped=%d",
			list_id, added, skipped,
		)
		return {"added": added, "skipped": skipped}

	# ------------------------------------------------------------------
	# NEW: build_dynamic_list
	# ------------------------------------------------------------------

	@staticmethod
	def build_dynamic_list(session: Any, list_id: str, tenant_id: str) -> dict[str, int]:
		"""Re-evaluate a DYNAMIC list's filter_criteria against erp_party.

		filter_criteria keys supported:
		  party_type   str   exact match on erp_party.party_type
		  country_id   str   exact match on erp_party.country_id
		  name_like    str   ILIKE '%<value>%' on erp_party.name

		Computes the new desired set, inserts missing rows, marks removed rows
		UNSUBSCRIBED (never deletes).

		Returns {"total": N, "added": A, "removed": R}.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import MarketingList, MarketingListMember

		mlist = session.execute(
			sa.select(MarketingList).where(
				MarketingList.id == list_id,
				MarketingList.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if mlist is None:
			raise ListNotFoundError(f"MarketingList {list_id} not found for tenant {tenant_id}")
		if mlist.list_type != "DYNAMIC":
			raise MarketingValidationError(f"List {list_id} is not DYNAMIC")

		criteria: dict[str, Any] = mlist.filter_criteria or {}

		# Lazy import erp_party table
		try:
			from pgappforge.plugins.erp.foundation.models import Party  # type: ignore[attr-defined]
			q = sa.select(Party.id).where(Party.tenant_id == tenant_id)
			if criteria.get("party_type"):
				q = q.where(Party.party_type == criteria["party_type"])
			if criteria.get("country_id"):
				q = q.where(Party.country_id == criteria["country_id"])
			if criteria.get("name_like"):
				q = q.where(Party.name.ilike(f"%{criteria['name_like']}%"))
			desired_ids: set[str] = {str(r[0]) for r in session.execute(q).all()}
		except Exception as exc:
			log.warning("build_dynamic_list: cannot query erp_party: %s", exc)
			desired_ids = set()

		# Current ACTIVE members
		current_rows = session.execute(
			sa.select(MarketingListMember.party_id, MarketingListMember.id).where(
				MarketingListMember.list_id == list_id,
				MarketingListMember.status == "ACTIVE",
			)
		).all()
		current_map: dict[str, str] = {str(r.party_id): str(r.id) for r in current_rows}
		current_ids = set(current_map)

		to_add = desired_ids - current_ids
		to_remove = current_ids - desired_ids
		now = datetime.now(timezone.utc)

		for pid in to_add:
			# Check if a non-ACTIVE membership already exists (don't re-add UNSUBSCRIBED)
			any_existing = session.execute(
				sa.select(MarketingListMember.id).where(
					MarketingListMember.list_id == list_id,
					MarketingListMember.party_id == pid,
				)
			).scalar_one_or_none()
			if any_existing is None:
				session.add(MarketingListMember(
					tenant_id=tenant_id,
					list_id=list_id,
					party_id=pid,
					added_at=now,
					status="ACTIVE",
					source="DYNAMIC",
				))

		if to_remove:
			session.execute(
				sa.update(MarketingListMember)
				.where(
					MarketingListMember.list_id == list_id,
					MarketingListMember.party_id.in_(list(to_remove)),
					MarketingListMember.status == "ACTIVE",
				)
				.values(status="UNSUBSCRIBED")
			)

		mlist.member_count = len(desired_ids)
		mlist.last_synced_at = now
		session.flush()

		log.info(
			"MarketingService.build_dynamic_list: list %s total=%d added=%d removed=%d",
			list_id, len(desired_ids), len(to_add), len(to_remove),
		)
		return {"total": len(desired_ids), "added": len(to_add), "removed": len(to_remove)}

	# ------------------------------------------------------------------
	# NEW: send_campaign_asset
	# ------------------------------------------------------------------

	@staticmethod
	def send_campaign_asset(session: Any, asset_id: str, tenant_id: str) -> dict[str, Any]:
		"""Mark a CampaignAsset as SENT; initialise CampaignMetrics if absent;
		increment sent_count; emit CampaignAssetSentEvent.

		Returns {"asset_id": ..., "campaign_id": ..., "sent_count": N}.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import CampaignAsset, CampaignMetrics
		from pgappforge.plugins.erp.crm.marketing.events import CampaignAssetSentEvent
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
		except ImportError:
			emit_event = None  # type: ignore[assignment]

		asset = session.execute(
			sa.select(CampaignAsset).where(
				CampaignAsset.id == asset_id,
				CampaignAsset.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if asset is None:
			raise AssetNotFoundError(f"CampaignAsset {asset_id} not found")
		if asset.status == "SENT":
			raise MarketingValidationError(f"Asset {asset_id} has already been sent")

		asset.status = "SENT"
		asset.sent_count = (asset.sent_count or 0) + 1
		now = datetime.now(timezone.utc)

		# Upsert CampaignMetrics
		metrics = session.execute(
			sa.select(CampaignMetrics).where(CampaignMetrics.campaign_id == asset.campaign_id)
		).scalar_one_or_none()
		if metrics is None:
			metrics = CampaignMetrics(
				tenant_id=tenant_id,
				campaign_id=asset.campaign_id,
			)
			session.add(metrics)

		metrics.sent_count = (metrics.sent_count or 0) + asset.sent_count
		metrics.updated_at = now
		session.flush()

		if emit_event is not None:
			emit_event(CampaignAssetSentEvent(
				aggregate_id=asset.id,
				aggregate_type="CampaignAsset",
				tenant_id=tenant_id,
				asset_id=asset.id,
				campaign_id=asset.campaign_id,
				asset_type=asset.asset_type,
				sent_count=asset.sent_count,
			), session)

		log.info(
			"MarketingService.send_campaign_asset: asset %s sent (campaign %s)",
			asset_id, asset.campaign_id,
		)
		return {
			"asset_id": asset_id,
			"campaign_id": asset.campaign_id,
			"sent_count": asset.sent_count,
		}

	# ------------------------------------------------------------------
	# NEW: record_campaign_activity
	# ------------------------------------------------------------------

	@staticmethod
	def record_campaign_activity(
		session: Any,
		campaign_id: str,
		metric_type: str,
		delta: int,
		revenue_cents: int = 0,
		tenant_id: str = "",
	) -> Any:
		"""Increment a specific CampaignMetrics counter by delta.

		metric_type must be one of:
		  sent | delivered | open | click | bounce | unsubscribe | conversion

		Also adds revenue_cents to revenue_attributed_cents if provided.
		Recomputes roi_pct and cost_per_lead_cents.

		Returns the updated CampaignMetrics row.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CampaignMetrics

		_METRIC_FIELD: dict[str, str] = {
			"sent": "sent_count",
			"delivered": "delivered_count",
			"open": "open_count",
			"click": "click_count",
			"bounce": "bounce_count",
			"unsubscribe": "unsubscribe_count",
			"conversion": "conversion_count",
		}
		if metric_type not in _METRIC_FIELD:
			raise MarketingValidationError(
				f"metric_type must be one of {list(_METRIC_FIELD)}, got {metric_type!r}"
			)

		# Resolve tenant_id from campaign if not supplied
		if not tenant_id:
			row = session.execute(
				sa.select(Campaign.tenant_id).where(Campaign.id == campaign_id)
			).scalar_one_or_none()
			if row is None:
				raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
			tenant_id = str(row)

		metrics = session.execute(
			sa.select(CampaignMetrics).where(CampaignMetrics.campaign_id == campaign_id)
		).scalar_one_or_none()
		if metrics is None:
			metrics = CampaignMetrics(tenant_id=tenant_id, campaign_id=campaign_id)
			session.add(metrics)

		field = _METRIC_FIELD[metric_type]
		current_val = getattr(metrics, field) or 0
		setattr(metrics, field, current_val + delta)

		if revenue_cents:
			metrics.revenue_attributed_cents = (metrics.revenue_attributed_cents or 0) + revenue_cents
			# Mirror back to Campaign for quick dashboard queries
			campaign = session.execute(
				sa.select(Campaign).where(Campaign.id == campaign_id)
			).scalar_one_or_none()
			if campaign:
				campaign.actual_revenue_cents = (campaign.actual_revenue_cents or 0) + revenue_cents

		# Recompute derived KPIs
		conversions = metrics.conversion_count or 0
		if conversions > 0:
			campaign_row = session.execute(
				sa.select(Campaign.actual_cost_cents).where(Campaign.id == campaign_id)
			).scalar_one_or_none()
			if campaign_row is not None:
				metrics.cost_per_lead_cents = (campaign_row or 0) // conversions

		rev = metrics.revenue_attributed_cents or 0
		if rev > 0:
			campaign_cost_row = session.execute(
				sa.select(Campaign.actual_cost_cents).where(Campaign.id == campaign_id)
			).scalar_one_or_none()
			cost = campaign_cost_row or 0
			if cost > 0:
				metrics.roi_pct = Decimal(str(round((rev - cost) / cost * 100, 2)))

		metrics.updated_at = datetime.now(timezone.utc)
		session.flush()
		log.debug(
			"MarketingService.record_campaign_activity: campaign=%s %s +%d",
			campaign_id, metric_type, delta,
		)
		return metrics

	# ------------------------------------------------------------------
	# NEW: score_lead
	# ------------------------------------------------------------------

	@staticmethod
	def score_lead(session: Any, lead_id: str, activity_type: str, tenant_id: str) -> Any:
		"""Record a LeadActivity, apply score_delta, apply 30-day decay if needed.

		Scoring table: EMAIL_OPEN=2, EMAIL_CLICK=5, FORM_SUBMIT=10,
		               PAGE_VIEW=1, DOWNLOAD=7, CALL=3, MEETING=5.

		Decay: if lead has no activity in last 30 days, subtract 5 pts first.
		Score floor: 0 (never negative).

		Returns the updated MarketingLead.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import MarketingLead, LeadActivity, LEAD_ACTIVITY_TYPE

		if activity_type not in LEAD_ACTIVITY_TYPE:
			raise MarketingValidationError(
				f"activity_type must be one of {LEAD_ACTIVITY_TYPE}, got {activity_type!r}"
			)

		lead = session.execute(
			sa.select(MarketingLead).where(
				MarketingLead.id == lead_id,
				MarketingLead.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if lead is None:
			raise LeadNotFoundError(f"MarketingLead {lead_id} not found for tenant {tenant_id}")

		now = datetime.now(timezone.utc)
		decay_delta = 0

		# Decay: check last activity timestamp
		last_activity_at = session.execute(
			sa.select(func.max(LeadActivity.occurred_at)).where(
				LeadActivity.lead_id == lead_id,
			)
		).scalar_one_or_none()

		if last_activity_at is not None:
			days_idle = (now - last_activity_at.replace(tzinfo=timezone.utc)).days
			if days_idle >= _DECAY_DAYS:
				decay_delta = -_DECAY_POINTS
				session.add(LeadActivity(
					tenant_id=tenant_id,
					lead_id=lead_id,
					activity_type=activity_type,  # tag decay on the triggering event row
					occurred_at=now,
					description=f"Score decay: {days_idle} days idle",
					score_delta=decay_delta,
				))

		score_delta = _SCORE_DELTAS.get(activity_type, 0)
		session.add(LeadActivity(
			tenant_id=tenant_id,
			lead_id=lead_id,
			activity_type=activity_type,
			occurred_at=now,
			score_delta=score_delta,
		))

		lead.lead_score = max(0, (lead.lead_score or 0) + decay_delta + score_delta)
		session.flush()
		log.debug(
			"MarketingService.score_lead: lead %s %s decay=%d delta=%d → score=%d",
			lead_id, activity_type, decay_delta, score_delta, lead.lead_score,
		)
		return lead

	# ------------------------------------------------------------------
	# NEW: qualify_lead
	# ------------------------------------------------------------------

	@staticmethod
	def qualify_lead(session: Any, lead_id: str, qualified_by: str, tenant_id: str) -> Any:
		"""Move lead to QUALIFIED status and emit LeadQualifiedEvent.

		MarketingLead must be NEW or CONTACTED to qualify.
		Returns the updated MarketingLead.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import MarketingLead
		from pgappforge.plugins.erp.crm.marketing.events import LeadQualifiedEvent
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
		except ImportError:
			emit_event = None  # type: ignore[assignment]

		lead = session.execute(
			sa.select(MarketingLead).where(
				MarketingLead.id == lead_id,
				MarketingLead.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if lead is None:
			raise LeadNotFoundError(f"MarketingLead {lead_id} not found for tenant {tenant_id}")
		if lead.status not in ("NEW", "CONTACTED"):
			raise MarketingValidationError(
				f"MarketingLead must be NEW or CONTACTED to qualify, got {lead.status!r}"
			)

		lead.status = "QUALIFIED"
		session.flush()

		if emit_event is not None:
			emit_event(LeadQualifiedEvent(
				aggregate_id=lead.id,
				aggregate_type="MarketingLead",
				tenant_id=tenant_id,
				lead_id=lead.id,
				email=lead.email,
				lead_score=lead.lead_score,
				qualified_by=qualified_by,
			), session)

		log.info("MarketingService.qualify_lead: lead %s qualified by %s", lead_id, qualified_by)
		return lead

	# ------------------------------------------------------------------
	# NEW: convert_lead
	# ------------------------------------------------------------------

	@staticmethod
	def convert_lead(session: Any, lead_id: str, tenant_id: str) -> dict[str, Any]:
		"""Convert a QUALIFIED MarketingLead into a foundation Party contact record.

		Creates a Party row (party_type='INDIVIDUAL') via lazy import of the
		foundation models.  Sets lead.status=CONVERTED, lead.converted_at=now,
		lead.converted_contact_id=<new_party.id>.

		Returns {
		    "lead_id": ...,
		    "converted_contact_id": ...,
		    "email": ...,
		}.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import MarketingLead
		from pgappforge.plugins.erp.crm.marketing.events import LeadConvertedEvent
		try:
			from pgappforge.plugins.erp.foundation.events import emit_event
		except ImportError:
			emit_event = None  # type: ignore[assignment]

		lead = session.execute(
			sa.select(MarketingLead).where(
				MarketingLead.id == lead_id,
				MarketingLead.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if lead is None:
			raise LeadNotFoundError(f"MarketingLead {lead_id} not found for tenant {tenant_id}")
		if lead.status != "QUALIFIED":
			raise MarketingValidationError(
				f"MarketingLead must be QUALIFIED to convert, got {lead.status!r}"
			)
		if lead.converted_contact_id:
			# Idempotent — already converted
			return {
				"lead_id": lead_id,
				"converted_contact_id": lead.converted_contact_id,
				"email": lead.email,
			}

		# Create Party contact record — lazy import to avoid circular deps
		party_id: str | None = None
		try:
			from pgappforge.plugins.erp.foundation.models import Party  # type: ignore[attr-defined]
			full_name = f"{lead.first_name} {lead.last_name}".strip()
			party = Party(
				tenant_id=tenant_id,
				party_type="INDIVIDUAL",
				name=full_name,
			)
			session.add(party)
			session.flush()
			party_id = str(party.id)
		except Exception as exc:
			log.warning(
				"MarketingService.convert_lead: could not create Party record: %s — "
				"proceeding with conversion without linked party",
				exc,
			)

		now = datetime.now(timezone.utc)
		lead.status = "CONVERTED"
		lead.converted_at = now
		lead.converted_contact_id = party_id
		session.flush()

		if emit_event is not None:
			emit_event(LeadConvertedEvent(
				aggregate_id=lead.id,
				aggregate_type="MarketingLead",
				tenant_id=tenant_id,
				lead_id=lead.id,
				email=lead.email,
				converted_contact_id=party_id or "",
				source_campaign_id=lead.source_campaign_id or "",
			), session)

		log.info(
			"MarketingService.convert_lead: lead %s → contact %s", lead_id, party_id
		)
		return {
			"lead_id": lead_id,
			"converted_contact_id": party_id,
			"email": lead.email,
		}

	# ------------------------------------------------------------------
	# NEW: get_campaign_roi
	# ------------------------------------------------------------------

	@staticmethod
	def get_campaign_roi(session: Any, campaign_id: str, tenant_id: str) -> dict[str, Any]:
		"""Return ROI KPIs for a campaign.

		Reads from CampaignMetrics (canonical) and falls back to Campaign
		denormalised fields.

		Returns {
		    budget_cents, actual_spend_cents, revenue_attributed_cents,
		    roi_pct, cost_per_lead_cents, conversion_rate_pct
		}.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CampaignMetrics

		campaign = session.execute(
			sa.select(Campaign).where(
				Campaign.id == campaign_id,
				Campaign.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if campaign is None:
			raise CampaignNotFoundError(f"Campaign {campaign_id} not found for tenant {tenant_id}")

		metrics = session.execute(
			sa.select(CampaignMetrics).where(CampaignMetrics.campaign_id == campaign_id)
		).scalar_one_or_none()

		budget = campaign.budget_cents or 0
		cost = campaign.actual_cost_cents or 0
		revenue = int(metrics.revenue_attributed_cents) if metrics else (campaign.actual_revenue_cents or 0)
		conversions = (metrics.conversion_count or 0) if metrics else 0
		sent = (metrics.sent_count or 0) if metrics else (campaign.actual_leads or 0)

		roi_pct: float | None = None
		if cost > 0:
			roi_pct = round((revenue - cost) / cost * 100, 2)

		cost_per_lead: int | None = None
		if conversions > 0:
			cost_per_lead = cost // conversions

		conversion_rate: float | None = None
		if sent > 0 and conversions > 0:
			conversion_rate = round(conversions / sent * 100, 2)

		return {
			"campaign_id": campaign_id,
			"campaign_name": campaign.campaign_name,
			"budget_cents": budget,
			"actual_spend_cents": cost,
			"revenue_attributed_cents": revenue,
			"roi_pct": roi_pct,
			"cost_per_lead_cents": cost_per_lead,
			"conversion_rate_pct": conversion_rate,
		}

	# ------------------------------------------------------------------
	# NEW: get_marketing_dashboard
	# ------------------------------------------------------------------

	@staticmethod
	def get_marketing_dashboard(session: Any, tenant_id: str) -> dict[str, Any]:
		"""Tenant-level marketing dashboard.

		Returns {
		    active_campaigns: int,
		    total_leads: int,
		    mql_count: int,           -- QUALIFIED leads
		    conversion_rate: float,   -- CONVERTED / total_leads * 100
		    pipeline_value_cents: int,-- sum of target_revenue_cents on ACTIVE campaigns
		    top_campaigns_by_roi: [   -- up to 5, sorted by roi_pct desc
		        {campaign_id, campaign_name, roi_pct, revenue_attributed_cents}
		    ]
		}.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CampaignMetrics, MarketingLead

		# Active campaigns
		active_campaigns: int = session.execute(
			sa.select(func.count(Campaign.id)).where(
				Campaign.tenant_id == tenant_id,
				Campaign.status == "ACTIVE",
			)
		).scalar_one()

		# Pipeline value — sum of target_revenue_cents on ACTIVE campaigns
		pipeline_value: int = session.execute(
			sa.select(func.coalesce(func.sum(Campaign.target_revenue_cents), 0)).where(
				Campaign.tenant_id == tenant_id,
				Campaign.status == "ACTIVE",
				Campaign.target_revenue_cents.isnot(None),
			)
		).scalar_one() or 0

		# MarketingLead counts
		lead_counts = session.execute(
			sa.select(MarketingLead.status, func.count(MarketingLead.id).label("cnt"))
			.where(MarketingLead.tenant_id == tenant_id)
			.group_by(MarketingLead.status)
		).all()
		lead_by_status: dict[str, int] = {r.status: r.cnt for r in lead_counts}
		total_leads = sum(lead_by_status.values())
		mql_count = lead_by_status.get("QUALIFIED", 0)
		converted_count = lead_by_status.get("CONVERTED", 0)
		conversion_rate = round(converted_count / total_leads * 100, 2) if total_leads else 0.0

		# Top campaigns by ROI
		top_rows = session.execute(
			sa.select(
				Campaign.id,
				Campaign.campaign_name,
				CampaignMetrics.roi_pct,
				CampaignMetrics.revenue_attributed_cents,
			)
			.join(CampaignMetrics, CampaignMetrics.campaign_id == Campaign.id)
			.where(
				Campaign.tenant_id == tenant_id,
				CampaignMetrics.roi_pct.isnot(None),
			)
			.order_by(CampaignMetrics.roi_pct.desc())
			.limit(5)
		).all()

		top_campaigns = [
			{
				"campaign_id": str(r.id),
				"campaign_name": r.campaign_name,
				"roi_pct": float(r.roi_pct) if r.roi_pct is not None else None,
				"revenue_attributed_cents": r.revenue_attributed_cents or 0,
			}
			for r in top_rows
		]

		return {
			"active_campaigns": active_campaigns,
			"total_leads": total_leads,
			"mql_count": mql_count,
			"conversion_rate": conversion_rate,
			"pipeline_value_cents": int(pipeline_value),
			"top_campaigns_by_roi": top_campaigns,
		}


__all__ = [
	"MarketingService",
	"MarketingError",
	"CampaignNotFoundError",
	"CampaignMemberNotFoundError",
	"ListNotFoundError",
	"LeadNotFoundError",
	"AssetNotFoundError",
	"MarketingValidationError",
]
