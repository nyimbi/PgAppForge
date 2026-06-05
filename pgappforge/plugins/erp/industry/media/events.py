"""
pgappforge/plugins/erp/industry/media/events.py

Domain events for the Media & Publishing plugin.

Payloads carry identifiers and status codes only — never raw body_html
or binary asset data — to keep event log size bounded.
"""
from __future__ import annotations

from dataclasses import dataclass

from pgappforge.plugins.erp.foundation.events import DomainEvent, emit_event  # noqa: F401


# ---------------------------------------------------------------------------
# Content lifecycle
# ---------------------------------------------------------------------------

@dataclass
class ContentCreatedEvent(DomainEvent):
	"""New ContentItem created (status=DRAFT)."""
	event_type: str = "media.content.created"
	content_id: str = ""
	slug: str = ""
	content_type: str = ""
	editor_id: str = ""


@dataclass
class ContentPublishedEvent(DomainEvent):
	"""ContentItem transitioned to PUBLISHED."""
	event_type: str = "media.content.published"
	content_id: str = ""
	slug: str = ""
	content_type: str = ""
	published_at: str = ""
	channels: list = None

	def __post_init__(self):
		if self.channels is None:
			self.channels = []


@dataclass
class ContentScheduledEvent(DomainEvent):
	"""ContentItem scheduled for future publication."""
	event_type: str = "media.content.scheduled"
	content_id: str = ""
	slug: str = ""
	scheduled_publish_at: str = ""


@dataclass
class ContentArchivedEvent(DomainEvent):
	"""ContentItem archived."""
	event_type: str = "media.content.archived"
	content_id: str = ""
	slug: str = ""


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------

@dataclass
class ContentDistributedEvent(DomainEvent):
	"""ContentItem distributed to one or more channels."""
	event_type: str = "media.distribution.completed"
	content_id: str = ""
	slug: str = ""
	channels: list = None
	distribution_count: int = 0

	def __post_init__(self):
		if self.channels is None:
			self.channels = []


# ---------------------------------------------------------------------------
# Syndication
# ---------------------------------------------------------------------------

@dataclass
class ContentLicensedEvent(DomainEvent):
	"""Syndication license issued for a ContentItem."""
	event_type: str = "media.syndication.licensed"
	license_id: str = ""
	content_id: str = ""
	licensee_id: str = ""
	license_type: str = ""
	fee_cents: int = 0
	territory: str = ""


# ---------------------------------------------------------------------------
# Asset
# ---------------------------------------------------------------------------

@dataclass
class AssetUploadedEvent(DomainEvent):
	"""Media asset uploaded and registered."""
	event_type: str = "media.asset.uploaded"
	asset_id: str = ""
	content_id: str = ""
	asset_type: str = ""
	filename: str = ""
	file_size_bytes: int = 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class MetricsSnapshotRecordedEvent(DomainEvent):
	"""Performance metrics snapshot recorded for a ContentItem."""
	event_type: str = "media.metrics.snapshot"
	content_id: str = ""
	slug: str = ""
	page_views: int = 0
	recorded_at: str = ""


__all__ = [
	"emit_event",
	# content
	"ContentCreatedEvent",
	"ContentPublishedEvent",
	"ContentScheduledEvent",
	"ContentArchivedEvent",
	# distribution
	"ContentDistributedEvent",
	# syndication
	"ContentLicensedEvent",
	# asset
	"AssetUploadedEvent",
	# metrics
	"MetricsSnapshotRecordedEvent",
]
