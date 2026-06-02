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
  campaign_performance_report(campaign_id, session) -> dict
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

class MarketingError(Exception):
	"""Base exception for Marketing service layer."""


class CampaignNotFoundError(MarketingError):
	pass


class CampaignMemberNotFoundError(MarketingError):
	pass


class ListNotFoundError(MarketingError):
	pass


class MarketingValidationError(MarketingError):
	"""Business rule violation."""


# ---------------------------------------------------------------------------
# MarketingService
# ---------------------------------------------------------------------------

class MarketingService:
	"""Stateless business logic for Marketing."""

	@staticmethod
	def activate_campaign(campaign_id: str, session: Any) -> Any:
		"""Move campaign PLANNING → ACTIVE."""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign
		from pgappforge.plugins.erp.crm.marketing.events import CampaignActivatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		campaign = session.execute(
			sa.select(Campaign).where(Campaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
		if campaign.status != "PLANNING":
			raise MarketingValidationError(f"Campaign is {campaign.status!r}, not PLANNING")

		campaign.status = "ACTIVE"
		session.flush()

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
		from pgappforge.plugins.erp.foundation.events import emit_event

		campaign = session.execute(
			sa.select(Campaign).where(Campaign.id == campaign_id)
		).scalar_one_or_none()
		if campaign is None:
			raise CampaignNotFoundError(f"Campaign {campaign_id} not found")
		if campaign.status not in ("ACTIVE", "PAUSED"):
			raise MarketingValidationError(f"Campaign must be ACTIVE or PAUSED to complete, got {campaign.status!r}")

		campaign.status = "COMPLETED"
		session.flush()

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
		if campaign.status not in ("PLANNING", "ACTIVE"):
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
		# Increment denormalised lead count
		campaign.actual_leads = (campaign.actual_leads or 0) + 1
		session.flush()
		log.debug("MarketingService.add_member: party %s added to campaign %s", party_id, campaign_id)
		return member

	@staticmethod
	def update_member_status(member_id: str, status: str, session: Any) -> Any:
		"""Progress a campaign member through the engagement funnel."""
		from pgappforge.plugins.erp.crm.marketing.models import CampaignMember
		from pgappforge.plugins.erp.crm.marketing.events import LeadRespondedEvent, MemberUnsubscribedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

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
		"""Update denormalised member_count on a MarketingList."""
		from pgappforge.plugins.erp.crm.marketing.models import MarketingList
		import sqlalchemy.func as func

		mlist = session.execute(
			sa.select(MarketingList).where(MarketingList.id == list_id)
		).scalar_one_or_none()
		if mlist is None:
			raise ListNotFoundError(f"MarketingList {list_id} not found")

		# For STATIC lists, member_count is maintained externally; this recalcs
		# from a list_membership table (if implemented) or leaves count unchanged.
		# This stub records the refresh timestamp.
		mlist.last_updated_at = datetime.now(timezone.utc)
		session.flush()
		log.debug("MarketingService.refresh_list_count: list %s refreshed", list_id)
		return mlist

	@staticmethod
	def campaign_performance_report(campaign_id: str, session: Any) -> dict[str, Any]:
		"""Engagement funnel breakdown for a campaign.

		Returns counts at each funnel stage and open rate / click rate.
		"""
		from pgappforge.plugins.erp.crm.marketing.models import Campaign, CampaignMember
		import sqlalchemy.func as func

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

		sent = funnel.get("SENT", 0) + funnel.get("DELIVERED", 0) + funnel.get("OPENED", 0) \
			+ funnel.get("CLICKED", 0) + funnel.get("RESPONDED", 0) + funnel.get("UNSUBSCRIBED", 0)
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


__all__ = [
	"MarketingService",
	"MarketingError",
	"CampaignNotFoundError",
	"CampaignMemberNotFoundError",
	"ListNotFoundError",
	"MarketingValidationError",
]
