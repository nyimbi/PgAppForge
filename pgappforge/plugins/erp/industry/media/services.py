"""
pgappforge/plugins/erp/industry/media/services.py

MediaService — stateless business logic for the Media & Publishing plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Callers own transaction boundaries (commit/rollback).

Key invariants:
  - slug unique per tenant
  - Content must be DRAFT/REVIEW to schedule; DRAFT/REVIEW/SCHEDULED to publish
  - generate_wire_feed returns RSS/Atom-compatible dicts (no raw HTML)
  - get_top_content aggregates across ContentMetrics rows in the period
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func, desc

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class MediaServiceError(Exception):
	"""Base error for Media & Publishing domain violations."""


class ContentNotFoundError(MediaServiceError):
	"""No ContentItem with the given id."""


class PublicationNotFoundError(MediaServiceError):
	"""No Publication with the given id."""


class AssetNotFoundError(MediaServiceError):
	"""No MediaAsset with the given id."""


class InvalidContentStatusError(MediaServiceError):
	"""Operation not permitted for the current content status."""


class DuplicateSlugError(MediaServiceError):
	"""slug already exists for this tenant."""


# ---------------------------------------------------------------------------
# MediaService
# ---------------------------------------------------------------------------

class MediaService:
	"""Stateless service for Media & Publishing operations."""

	# ------------------------------------------------------------------
	# Publication
	# ------------------------------------------------------------------

	def publish_content(
		self,
		content_id: str,
		channels: list[str],
		session: Any,
	) -> list["ContentDistribution"]:
		"""Publish a ContentItem to one or more distribution channels.

		Transitions status to PUBLISHED (if DRAFT/REVIEW/SCHEDULED).
		Creates one ContentDistribution row per channel.
		Emits ContentPublishedEvent and ContentDistributedEvent.
		"""
		from pgappforge.plugins.erp.industry.media.models import (
			ContentItem, ContentDistribution,
		)
		from pgappforge.plugins.erp.industry.media.events import (
			ContentPublishedEvent, ContentDistributedEvent, emit_event,
		)

		content = session.get(ContentItem, content_id)
		if content is None:
			raise ContentNotFoundError(f"ContentItem {content_id!r} not found")
		if content.status not in ("DRAFT", "REVIEW", "SCHEDULED"):
			raise InvalidContentStatusError(
				f"Cannot publish content in status {content.status!r}. "
				"Expected DRAFT, REVIEW, or SCHEDULED."
			)

		now = datetime.now(timezone.utc)
		content.status = "PUBLISHED"
		content.published_at = now

		distributions: list[ContentDistribution] = []
		for channel in channels:
			dist = ContentDistribution(
				tenant_id=content.tenant_id,
				content_id=content_id,
				channel=channel.upper(),
				distributed_at=now,
				reach=0,
				engagement_metrics={},
			)
			session.add(dist)
			distributions.append(dist)

		session.flush()

		emit_event(
			ContentPublishedEvent(
				aggregate_id=content_id,
				aggregate_type="ContentItem",
				tenant_id=content.tenant_id,
				content_id=content_id,
				slug=content.slug,
				content_type=content.content_type,
				published_at=now.isoformat(),
				channels=channels,
			),
			session,
		)
		emit_event(
			ContentDistributedEvent(
				aggregate_id=content_id,
				aggregate_type="ContentItem",
				tenant_id=content.tenant_id,
				content_id=content_id,
				slug=content.slug,
				channels=channels,
				distribution_count=len(distributions),
			),
			session,
		)

		log.info(
			"publish_content: %r slug=%r channels=%r",
			content_id, content.slug, channels,
		)
		return distributions

	def schedule_publication(
		self,
		content_id: str,
		publish_at: datetime,
		session: Any,
	) -> "ContentItem":
		"""Schedule a ContentItem for future publication.

		Sets status to SCHEDULED and stores scheduled_publish_at.
		Content must be DRAFT or REVIEW.
		"""
		from pgappforge.plugins.erp.industry.media.models import ContentItem
		from pgappforge.plugins.erp.industry.media.events import (
			ContentScheduledEvent, emit_event,
		)

		content = session.get(ContentItem, content_id)
		if content is None:
			raise ContentNotFoundError(f"ContentItem {content_id!r} not found")
		if content.status not in ("DRAFT", "REVIEW"):
			raise InvalidContentStatusError(
				f"Cannot schedule content in status {content.status!r}. "
				"Expected DRAFT or REVIEW."
			)
		if publish_at <= datetime.now(timezone.utc):
			raise MediaServiceError("scheduled_publish_at must be in the future")

		content.status = "SCHEDULED"
		content.scheduled_publish_at = publish_at

		emit_event(
			ContentScheduledEvent(
				aggregate_id=content_id,
				aggregate_type="ContentItem",
				tenant_id=content.tenant_id,
				content_id=content_id,
				slug=content.slug,
				scheduled_publish_at=publish_at.isoformat(),
			),
			session,
		)

		log.info(
			"schedule_publication: %r scheduled for %s",
			content.slug, publish_at.isoformat(),
		)
		return content

	# ------------------------------------------------------------------
	# Metrics
	# ------------------------------------------------------------------

	def track_performance(
		self,
		content_id: str,
		session: Any,
		*,
		page_views: int = 0,
		unique_visitors: int = 0,
		avg_time_on_page_seconds: int = 0,
		social_shares: int = 0,
		comments: int = 0,
		bounce_rate_pct: float | None = None,
	) -> "ContentMetrics":
		"""Record a performance metrics snapshot for a ContentItem.

		Creates a new ContentMetrics row (append-only time-series).
		Returns the new row.
		"""
		from pgappforge.plugins.erp.industry.media.models import ContentItem, ContentMetrics
		from pgappforge.plugins.erp.industry.media.events import (
			MetricsSnapshotRecordedEvent, emit_event,
		)

		content = session.get(ContentItem, content_id)
		if content is None:
			raise ContentNotFoundError(f"ContentItem {content_id!r} not found")

		now = datetime.now(timezone.utc)
		metrics = ContentMetrics(
			tenant_id=content.tenant_id,
			content_id=content_id,
			recorded_at=now,
			page_views=page_views,
			unique_visitors=unique_visitors,
			avg_time_on_page_seconds=avg_time_on_page_seconds,
			social_shares=social_shares,
			comments=comments,
			bounce_rate_pct=bounce_rate_pct,
		)
		session.add(metrics)
		session.flush()

		emit_event(
			MetricsSnapshotRecordedEvent(
				aggregate_id=content_id,
				aggregate_type="ContentItem",
				tenant_id=content.tenant_id,
				content_id=content_id,
				slug=content.slug,
				page_views=page_views,
				recorded_at=now.isoformat(),
			),
			session,
		)

		return metrics

	# ------------------------------------------------------------------
	# Syndication
	# ------------------------------------------------------------------

	def license_content(
		self,
		content_id: str,
		licensee_id: str,
		terms: dict[str, Any],
		session: Any,
	) -> "SyndicationLicense":
		"""Issue a syndication license for a ContentItem.

		terms must include: license_type, valid_from (date), valid_to (date).
		Optional: fee_cents, territory, usage_rights.

		Emits ContentLicensedEvent.
		"""
		from pgappforge.plugins.erp.industry.media.models import ContentItem, SyndicationLicense
		from pgappforge.plugins.erp.industry.media.events import (
			ContentLicensedEvent, emit_event,
		)

		content = session.get(ContentItem, content_id)
		if content is None:
			raise ContentNotFoundError(f"ContentItem {content_id!r} not found")
		if content.status != "PUBLISHED":
			raise InvalidContentStatusError(
				f"Cannot license content in status {content.status!r}. "
				"Content must be PUBLISHED to license."
			)

		license_type = terms.get("license_type", "NON_EXCLUSIVE")
		fee_cents = int(terms.get("fee_cents", 0))
		territory = terms.get("territory", "WORLDWIDE")
		usage_rights = terms.get("usage_rights", {})
		valid_from = terms.get("valid_from") or date.today()
		valid_to = terms.get("valid_to") or date.today().replace(
			year=date.today().year + 1
		)

		lic = SyndicationLicense(
			tenant_id=content.tenant_id,
			content_id=content_id,
			licensee_id=licensee_id,
			license_type=license_type,
			fee_cents=fee_cents,
			territory=territory,
			usage_rights=usage_rights,
			valid_from=valid_from,
			valid_to=valid_to,
		)
		session.add(lic)
		session.flush()

		emit_event(
			ContentLicensedEvent(
				aggregate_id=lic.id,
				aggregate_type="SyndicationLicense",
				tenant_id=content.tenant_id,
				license_id=lic.id,
				content_id=content_id,
				licensee_id=licensee_id,
				license_type=license_type,
				fee_cents=fee_cents,
				territory=territory,
			),
			session,
		)

		log.info(
			"license_content: %r to licensee %r type=%r",
			content_id, licensee_id, license_type,
		)
		return lic

	# ------------------------------------------------------------------
	# Wire feed
	# ------------------------------------------------------------------

	def generate_wire_feed(
		self,
		publication_id: str,
		session: Any,
		limit: int = 20,
	) -> list[dict]:
		"""Generate RSS/Atom-compatible feed entries for a publication.

		Returns dicts matching the RSS 2.0 / Atom item structure:
		  {guid, title, slug, content_type, published_at, categories,
		   tags, iptc_subject_codes, thumbnail_url, word_count}

		Filters to PUBLISHED items belonging to the publication's tenant,
		ordered newest-first.
		"""
		from pgappforge.plugins.erp.industry.media.models import ContentItem, Publication

		pub = session.get(Publication, publication_id)
		if pub is None:
			raise PublicationNotFoundError(f"Publication {publication_id!r} not found")

		rows = session.execute(
			select(ContentItem)
			.where(
				ContentItem.tenant_id == pub.tenant_id,
				ContentItem.status == "PUBLISHED",
				ContentItem.language == pub.language,
			)
			.order_by(desc(ContentItem.published_at))
			.limit(limit)
		).scalars().all()

		base_url = (pub.base_url or "").rstrip("/")

		return [
			{
				"guid": item.id,
				"title": item.headline,
				"subheadline": item.subheadline,
				"slug": item.slug,
				"link": f"{base_url}/{item.slug}" if base_url else f"/{item.slug}",
				"content_type": item.content_type,
				"published_at": (
					item.published_at.isoformat() if item.published_at else None
				),
				"categories": item.categories,
				"tags": item.tags,
				"keywords": item.keywords,
				"iptc_subject_codes": item.iptc_subject_codes,
				"thumbnail_url": item.thumbnail_url,
				"word_count": item.word_count,
				"reading_time_minutes": item.reading_time_minutes,
				"language": item.language,
				"wire_service": item.wire_service,
			}
			for item in rows
		]

	# ------------------------------------------------------------------
	# Analytics
	# ------------------------------------------------------------------

	def get_top_content(
		self,
		tenant_id: str,
		session: Any,
		period_days: int = 7,
		metric: str = "page_views",
		limit: int = 10,
	) -> list[dict]:
		"""Return top-performing content by metric over the last period_days.

		metric options: page_views, unique_visitors, social_shares, comments,
		avg_time_on_page_seconds.

		Aggregates ContentMetrics rows with SUM for count metrics,
		AVG for avg_time_on_page_seconds.
		"""
		from pgappforge.plugins.erp.industry.media.models import ContentItem, ContentMetrics

		allowed_metrics = {
			"page_views", "unique_visitors", "social_shares",
			"comments", "avg_time_on_page_seconds",
		}
		if metric not in allowed_metrics:
			raise MediaServiceError(
				f"Invalid metric {metric!r}. Allowed: {sorted(allowed_metrics)}"
			)

		since = datetime.now(timezone.utc) - timedelta(days=period_days)

		metric_col = getattr(ContentMetrics, metric)
		agg_fn = func.avg if metric == "avg_time_on_page_seconds" else func.sum

		rows = session.execute(
			select(
				ContentItem.id,
				ContentItem.headline,
				ContentItem.slug,
				ContentItem.content_type,
				ContentItem.published_at,
				ContentItem.thumbnail_url,
				agg_fn(metric_col).label("metric_value"),
			)
			.join(ContentMetrics, ContentMetrics.content_id == ContentItem.id)
			.where(
				ContentItem.tenant_id == tenant_id,
				ContentItem.status == "PUBLISHED",
				ContentMetrics.recorded_at >= since,
			)
			.group_by(
				ContentItem.id,
				ContentItem.headline,
				ContentItem.slug,
				ContentItem.content_type,
				ContentItem.published_at,
				ContentItem.thumbnail_url,
			)
			.order_by(desc("metric_value"))
			.limit(limit)
		).all()

		return [
			{
				"content_id": str(r.id),
				"headline": r.headline,
				"slug": r.slug,
				"content_type": r.content_type,
				"published_at": r.published_at.isoformat() if r.published_at else None,
				"thumbnail_url": r.thumbnail_url,
				"metric": metric,
				"metric_value": float(r.metric_value or 0),
				"period_days": period_days,
			}
			for r in rows
		]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"MediaService",
	"MediaServiceError",
	"ContentNotFoundError",
	"PublicationNotFoundError",
	"AssetNotFoundError",
	"InvalidContentStatusError",
	"DuplicateSlugError",
]
