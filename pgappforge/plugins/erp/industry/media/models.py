"""
pgappforge/plugins/erp/industry/media/models.py

Media & Publishing — SQLAlchemy models.

Extends IPTC metadata conventions (see pgappforge/templates/bundled/iptc.json).

Design rules:
  - All PKs: UUID v4 via gen_random_uuid() + Python default_factory
  - All timestamps: TIMESTAMPTZ (DateTime(timezone=True)) DEFAULT NOW()
  - All models: tenant_id UUID NOT NULL + AuditMixin
  - All monetary amounts: integer cents
  - author_ids / contributor_ids: PostgreSQL UUID[] arrays (no join table)
  - PostGIS GEOMETRY(Point,4326) for geo_point on MediaAsset
  - iptc_subject_codes: TEXT[] for IPTC NewsCodes subject classification

Table prefix: med_

IPTC alignment:
  ContentItem.iptc_subject_codes  ↔ iptc_subject.subject_code[]
  ContentItem.wire_service         ↔ iptc_media_item.editorial_office
  MediaAsset.credit               ↔ iptc_asset (credit_line)
  MediaAsset.taken_at             ↔ iptc_asset.taken_at
  MediaAsset.geo_point            ↔ iptc_asset.gps
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ContentItem
# ---------------------------------------------------------------------------

class ContentItem(AuditMixin, Model):
	"""A publishable content piece — article, video, audio, interactive, etc.

	author_ids and contributor_ids are UUID[] arrays pointing to foundation.Party
	records. Using arrays avoids a many-to-many join table for the common case
	where no additional metadata per-author is needed.

	iptc_subject_codes stores IPTC NewsCodes (e.g. '15054000' = Soccer) for
	interoperability with wire services and media archives.
	"""

	__allow_unmapped__ = True
	__tablename__ = "med_content_item"
	__table_args__ = (
		UniqueConstraint("slug", name="uq_med_content_slug"),
		Index("ix_med_ci_tenant_status", "tenant_id", "status"),
		Index("ix_med_ci_editor", "editor_id"),
		Index("ix_med_ci_published_at", "published_at"),
		Index("ix_med_ci_scheduled", "scheduled_publish_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	slug = Column(String(300), nullable=False, comment="URL slug, unique per tenant")
	headline = Column(String(500), nullable=False)
	subheadline = Column(String(500), nullable=True)
	body_html = Column(Text, nullable=True, comment="HTML body content")

	content_type = Column(
		String(20),
		nullable=False,
		comment="ARTICLE | VIDEO | AUDIO | PHOTO_ESSAY | INTERACTIVE | NEWSLETTER",
	)

	# Authorship — UUID[] arrays (foundation.Party)
	author_ids = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		default=list,
		server_default="{}",
		comment="Primary author party UUIDs",
	)
	contributor_ids = Column(
		ARRAY(UUID(as_uuid=False)),
		nullable=False,
		default=list,
		server_default="{}",
		comment="Contributing author/photographer party UUIDs",
	)
	editor_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="SET NULL"),
		nullable=True,
		comment="Assigning editor party UUID (foundation.Party)",
	)

	# Lifecycle
	status = Column(
		String(10),
		nullable=False,
		default="DRAFT",
		comment="DRAFT | REVIEW | SCHEDULED | PUBLISHED | ARCHIVED",
	)
	published_at = Column(DateTime(timezone=True), nullable=True)
	scheduled_publish_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="Future publish timestamp for scheduled content",
	)

	# Classification
	categories = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
	)
	tags = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
	)
	keywords = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
		comment="SEO and search keywords",
	)

	# Locale
	language = Column(String(5), nullable=False, default="en")
	word_count = Column(Integer, nullable=True)
	reading_time_minutes = Column(Integer, nullable=True)
	thumbnail_url = Column(Text, nullable=True)

	# IPTC metadata
	iptc_subject_codes = Column(
		ARRAY(Text),
		nullable=False,
		default=list,
		server_default="{}",
		comment="IPTC NewsCodes subject codes e.g. ['15054000']",
	)
	wire_service = Column(
		String(50),
		nullable=True,
		comment="Originating wire service e.g. AP, Reuters, AFP",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	# Relationships
	assets: list[MediaAsset] = relationship(
		"MediaAsset",
		back_populates="content_item",
		cascade="all, delete-orphan",
		lazy="select",
	)
	distributions: list[ContentDistribution] = relationship(
		"ContentDistribution",
		back_populates="content_item",
		cascade="all, delete-orphan",
		lazy="select",
	)
	syndication_licenses: list[SyndicationLicense] = relationship(
		"SyndicationLicense",
		back_populates="content_item",
		cascade="all, delete-orphan",
		lazy="select",
	)
	metrics: list[ContentMetrics] = relationship(
		"ContentMetrics",
		back_populates="content_item",
		cascade="all, delete-orphan",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ContentItem {self.id!r} slug={self.slug!r} "
			f"type={self.content_type!r} status={self.status!r}>"
		)


# ---------------------------------------------------------------------------
# MediaAsset
# ---------------------------------------------------------------------------

class MediaAsset(AuditMixin, Model):
	"""A binary media asset — image, video, audio, or document.

	Optionally linked to a ContentItem (nullable for standalone DAM assets).

	geo_point uses PostGIS GEOMETRY(Point,4326) for photo GPS coordinates,
	enabling ST_DWithin radius and ST_Distance spatial queries — consistent
	with iptc_asset.gps in the IPTC template.

	usage_rights JSONB carries structured rights metadata:
	  {"regions": ["worldwide"], "embargo_until": null, "max_uses": null}
	"""

	__allow_unmapped__ = True
	__tablename__ = "med_asset"
	__table_args__ = (
		Index("ix_med_asset_content", "content_item_id"),
		Index("ix_med_asset_tenant_type", "tenant_id", "asset_type"),
		Index("ix_med_asset_taken_at", "taken_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	content_item_id = Column(
		UUID(as_uuid=False),
		ForeignKey("med_content_item.id", ondelete="SET NULL"),
		nullable=True,
		comment="Parent content item (NULL for standalone assets)",
	)

	asset_type = Column(
		String(10),
		nullable=False,
		comment="IMAGE | VIDEO | AUDIO | DOCUMENT",
	)
	filename = Column(String(500), nullable=False)
	mime_type = Column(String(100), nullable=False)
	file_size_bytes = Column(Integer, nullable=True)
	storage_url = Column(Text, nullable=False, comment="Object storage URL")
	thumbnail_url = Column(Text, nullable=True)

	# Editorial metadata
	caption = Column(Text, nullable=True)
	credit = Column(
		String(200),
		nullable=True,
		comment="Credit line e.g. '© Reuters 2026 / Jane Smith'",
	)
	alt_text = Column(String(500), nullable=True, comment="Accessibility alt text")

	# Rights
	copyright_holder = Column(String(300), nullable=True)
	license_type = Column(
		String(50),
		nullable=True,
		comment="e.g. CC-BY-4.0, RIGHTS_MANAGED, ROYALTY_FREE",
	)
	usage_rights: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Structured usage rights: {regions, embargo_until, max_uses}",
	)

	# Geo / temporal (IPTC iptc_asset.gps / taken_at)
	# geo_point stored as WKT text for portability; use PostGIS cast in queries
	geo_point = Column(
		Text,
		nullable=True,
		comment="WKT point: 'SRID=4326;POINT(lng lat)' — cast to GEOMETRY in queries",
	)
	taken_at = Column(
		DateTime(timezone=True),
		nullable=True,
		comment="EXIF DateTimeOriginal converted to UTC (iptc_asset.taken_at)",
	)
	metadata: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="EXIF and other technical metadata",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	content_item: ContentItem | None = relationship(
		"ContentItem",
		back_populates="assets",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<MediaAsset {self.id!r} type={self.asset_type!r} "
			f"filename={self.filename!r}>"
		)


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

class Publication(AuditMixin, Model):
	"""A publication entity — newspaper, magazine, blog, newsletter, or podcast.

	Acts as the organisational unit that owns ContentItems. One tenant may
	have multiple publications (e.g. a media group with several titles).
	"""

	__allow_unmapped__ = True
	__tablename__ = "med_publication"
	__table_args__ = (
		UniqueConstraint("slug", name="uq_med_pub_slug"),
		Index("ix_med_pub_tenant", "tenant_id"),
		Index("ix_med_pub_publisher", "publisher_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	name = Column(String(300), nullable=False)
	slug = Column(String(200), nullable=False)
	publication_type = Column(
		String(15),
		nullable=False,
		comment="NEWSPAPER | MAGAZINE | BLOG | NEWSLETTER | PODCAST",
	)
	base_url = Column(Text, nullable=True)
	language = Column(String(5), nullable=False, default="en")
	timezone = Column(String(50), nullable=False, default="UTC")
	logo_url = Column(Text, nullable=True)
	circulation = Column(
		Integer,
		nullable=True,
		comment="Average issue circulation (print + digital)",
	)
	publisher_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Publisher party UUID (foundation.Party)",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __repr__(self) -> str:
		return (
			f"<Publication {self.id!r} slug={self.slug!r} "
			f"type={self.publication_type!r}>"
		)


# ---------------------------------------------------------------------------
# ContentDistribution
# ---------------------------------------------------------------------------

class ContentDistribution(AuditMixin, Model):
	"""Records a single distribution event for a ContentItem on a channel.

	engagement_metrics JSONB carries channel-specific metrics at time of
	distribution snapshot:
	  {"clicks": 0, "opens": 0, "shares": 0, "plays": 0}
	"""

	__allow_unmapped__ = True
	__tablename__ = "med_distribution"
	__table_args__ = (
		Index("ix_med_dist_content", "content_id"),
		Index("ix_med_dist_tenant_channel", "tenant_id", "channel"),
		Index("ix_med_dist_distributed_at", "distributed_at"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	content_id = Column(
		UUID(as_uuid=False),
		ForeignKey("med_content_item.id", ondelete="RESTRICT"),
		nullable=False,
	)

	channel = Column(
		String(10),
		nullable=False,
		comment="WEB | EMAIL | SOCIAL | WIRE | PRINT | RSS",
	)
	distributed_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	platform = Column(
		String(100),
		nullable=True,
		comment="e.g. Twitter, Facebook, Mailchimp, AP Wire",
	)
	url = Column(Text, nullable=True, comment="Canonical URL on distribution channel")
	reach = Column(Integer, nullable=False, default=0)
	engagement_metrics: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Channel-specific engagement snapshot: {clicks, opens, shares, plays}",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	content_item: ContentItem = relationship(
		"ContentItem",
		back_populates="distributions",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ContentDistribution {self.id!r} channel={self.channel!r} "
			f"content={self.content_id!r}>"
		)


# ---------------------------------------------------------------------------
# SyndicationLicense
# ---------------------------------------------------------------------------

class SyndicationLicense(AuditMixin, Model):
	"""License granting a third-party (licensee) rights to republish a ContentItem.

	fee_cents is integer cents; zero for royalty-free grants.
	usage_rights JSONB mirrors MediaAsset.usage_rights for consistency.
	"""

	__allow_unmapped__ = True
	__tablename__ = "med_syndication_license"
	__table_args__ = (
		Index("ix_med_syn_content", "content_id"),
		Index("ix_med_syn_licensee", "licensee_id"),
		Index("ix_med_syn_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	content_id = Column(
		UUID(as_uuid=False),
		ForeignKey("med_content_item.id", ondelete="RESTRICT"),
		nullable=False,
	)
	licensee_id = Column(
		UUID(as_uuid=False),
		ForeignKey("erp_party.id", ondelete="RESTRICT"),
		nullable=False,
		comment="Licensee party UUID (foundation.Party)",
	)

	license_type = Column(
		String(15),
		nullable=False,
		comment="EXCLUSIVE | NON_EXCLUSIVE | ROYALTY_FREE",
	)
	fee_cents = Column(
		Integer,
		nullable=False,
		default=0,
		comment="Syndication fee in cents; 0 for royalty-free",
	)
	territory = Column(
		String(100),
		nullable=False,
		default="WORLDWIDE",
		comment="Geographic scope e.g. WORLDWIDE, US, EU",
	)
	usage_rights: dict[str, Any] = Column(
		JSONB,
		nullable=False,
		default=dict,
		comment="Permitted uses, exclusivity scope, sub-licensing rights",
	)
	valid_from = Column(Date, nullable=False)
	valid_to = Column(Date, nullable=False)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	content_item: ContentItem = relationship(
		"ContentItem",
		back_populates="syndication_licenses",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<SyndicationLicense {self.id!r} type={self.license_type!r} "
			f"content={self.content_id!r} licensee={self.licensee_id!r}>"
		)


# ---------------------------------------------------------------------------
# ContentMetrics
# ---------------------------------------------------------------------------

class ContentMetrics(AuditMixin, Model):
	"""Time-series performance metrics snapshot for a ContentItem.

	Each row is a point-in-time snapshot (recorded_at). Multiple rows per
	ContentItem allow trend analysis. bounce_rate_pct is NUMERIC(5,2).
	"""

	__allow_unmapped__ = True
	__tablename__ = "med_content_metrics"
	__table_args__ = (
		Index("ix_med_metrics_content", "content_id"),
		Index("ix_med_metrics_recorded_at", "recorded_at"),
		Index("ix_med_metrics_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)
	content_id = Column(
		UUID(as_uuid=False),
		ForeignKey("med_content_item.id", ondelete="RESTRICT"),
		nullable=False,
	)

	recorded_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	page_views = Column(Integer, nullable=False, default=0)
	unique_visitors = Column(Integer, nullable=False, default=0)
	avg_time_on_page_seconds = Column(Integer, nullable=False, default=0)
	social_shares = Column(Integer, nullable=False, default=0)
	comments = Column(Integer, nullable=False, default=0)
	bounce_rate_pct = Column(
		sa.Numeric(5, 2),
		nullable=True,
		comment="Bounce rate percentage 0.00–100.00",
	)

	created_at = Column(
		DateTime(timezone=True),
		nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	content_item: ContentItem = relationship(
		"ContentItem",
		back_populates="metrics",
		lazy="select",
	)

	def __repr__(self) -> str:
		return (
			f"<ContentMetrics {self.id!r} content={self.content_id!r} "
			f"views={self.page_views} at={self.recorded_at!r}>"
		)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ContentItem",
	"MediaAsset",
	"Publication",
	"ContentDistribution",
	"SyndicationLicense",
	"ContentMetrics",
]
