"""
pgappforge/plugins/erp/industry/media/__init__.py

MediaPlugin — Media & Publishing ERP plugin.

Extends IPTC metadata conventions (iptc_subject_codes, wire_service,
credit, taken_at, geo_point — aligned with iptc_media_item and iptc_asset
schema in pgappforge/templates/bundled/iptc.json).

Provides:
  - ContentItem         (ARTICLE/VIDEO/AUDIO/PHOTO_ESSAY/INTERACTIVE/NEWSLETTER)
  - MediaAsset          (IMAGE/VIDEO/AUDIO/DOCUMENT; PostGIS geo_point, EXIF)
  - Publication         (NEWSPAPER/MAGAZINE/BLOG/NEWSLETTER/PODCAST)
  - ContentDistribution (WEB/EMAIL/SOCIAL/WIRE/PRINT/RSS channel records)
  - SyndicationLicense  (EXCLUSIVE/NON_EXCLUSIVE/ROYALTY_FREE)
  - ContentMetrics      (time-series page_views, shares, bounce_rate_pct)

Business rules enforced:
  - slug unique per tenant
  - Content must be DRAFT/REVIEW/SCHEDULED to publish
  - Content must be PUBLISHED to license
  - ContentMetrics rows are append-only (time-series; no UPDATE)
  - generate_wire_feed returns RSS/Atom-compatible dicts (no raw HTML body)

Events emitted:
  media.content.created
  media.content.published
  media.content.scheduled
  media.content.archived
  media.distribution.completed
  media.syndication.licensed
  media.asset.uploaded
  media.metrics.snapshot

Events consumed:
  party.created  (optionally pre-register publisher shell)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.media",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class MediaPlugin(BasePlugin):
	"""Media & Publishing ERP plugin.

	Class-level routing metadata:
	    name       = "media"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "media"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="media",
			version="1.0.0",
			description=(
				"Media & Publishing — IPTC-aligned content management, "
				"multi-channel distribution (web, email, social, wire, print, RSS), "
				"syndication licensing, digital asset management with PostGIS "
				"geo-tagging, engagement metrics time-series, and wire feed generation."
			),
			author="PgAppForge Contributors",
			tags=[
				"erp", "industry", "media", "publishing", "iptc",
				"cms", "dam", "newsroom", "syndication",
			],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_media_content_read",
				"can_media_content_write",
				"can_media_content_publish",
				"can_media_content_archive",
				"can_media_asset_read",
				"can_media_asset_write",
				"can_media_publication_read",
				"can_media_publication_write",
				"can_media_distribution_read",
				"can_media_syndication_read",
				"can_media_syndication_write",
				"can_media_metrics_read",
				"can_media_metrics_write",
				"can_media_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"media.content.created",
			"media.content.published",
			"media.content.scheduled",
			"media.content.archived",
			"media.distribution.completed",
			"media.syndication.licensed",
			"media.asset.uploaded",
			"media.metrics.snapshot",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return [
			"party.created",  # Optionally pre-register publisher shell
		]

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		"""Merge config defaults."""
		defaults: dict[str, Any] = {
			"MEDIA_MENU_CATEGORY": "Media & Publishing",
			"MEDIA_SEED_RULES_ON_INIT": True,
			"MEDIA_DEFAULT_LANGUAGE": "en",
			"MEDIA_DEFAULT_WIRE_FEED_LIMIT": 20,
		}
		self.config = {**defaults, **self.config}
		log.info("MediaPlugin initialised (config keys: %s)", list(self.config))

	def post_initialize(self) -> None:
		"""Seed rules after tables exist."""
		if self.config.get("MEDIA_SEED_RULES_ON_INIT", True):
			self._try_setup_rules()

	def register_views(self) -> None:
		"""Register Media views under the configured menu category."""
		from pgappforge.plugins.erp.industry.media.views import (
			ContentView,
			AssetView,
			PublicationView,
			ContentDashboard,
		)

		cat = self.config.get("MEDIA_MENU_CATEGORY", "Media & Publishing")

		self.add_view(ContentView, "Content", icon="fa-newspaper-o", category=cat)
		self.add_view(AssetView, "Assets", icon="fa-photo", category=cat)
		self.add_view(PublicationView, "Publications", icon="fa-book", category=cat)
		self.add_view(
			ContentDashboard, "Dashboard", icon="fa-bar-chart", category=cat
		)

		log.info("MediaPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.media.models import (
			ContentItem,
			MediaAsset,
			Publication,
			ContentDistribution,
			SyndicationLicense,
			ContentMetrics,
		)
		return [
			ContentItem,
			MediaAsset,
			Publication,
			ContentDistribution,
			SyndicationLicense,
			ContentMetrics,
		]

	# ------------------------------------------------------------------
	# Rules Engine pre-configuration
	# ------------------------------------------------------------------

	@staticmethod
	def setup_rules(session: Any) -> None:
		"""Pre-configure rulesets for Media & Publishing domain rules.

		Idempotent — skips rulesets that already exist.
		"""
		try:
			from pgappforge.plugins.rules.models import Rule, RuleSet
		except ImportError:
			log.debug("MediaPlugin.setup_rules: rules plugin not available, skipping")
			return

		import sqlalchemy as sa

		RULESETS = [
			{
				"name": "media.content.no_edit_published",
				"description": "Block direct edit of PUBLISHED content body",
				"model_name": "ContentItem",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_published_body_edit",
						"trigger_event": "on_before_update",
						"conditions_json": [
							{"field": "_old_status", "op": "eq", "value": "PUBLISHED"},
							{
								"field": "_changed_fields",
								"op": "contains",
								"value": "body_html",
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"Cannot edit body_html of a PUBLISHED ContentItem. "
									"Archive and create a new version instead."
								),
							}
						],
					},
				],
			},
			{
				"name": "media.content.license_requires_published",
				"description": "Block syndication license on non-PUBLISHED content",
				"model_name": "SyndicationLicense",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_license_non_published",
						"trigger_event": "on_before_create",
						"conditions_json": [
							{
								"field": "content.status",
								"op": "ne",
								"value": "PUBLISHED",
							},
						],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"SyndicationLicense requires content status=PUBLISHED."
								),
							}
						],
					},
				],
			},
			{
				"name": "media.metrics.append_only",
				"description": "Block UPDATE on ContentMetrics (time-series append-only)",
				"model_name": "ContentMetrics",
				"stop_on_match": True,
				"rules": [
					{
						"name": "block_metrics_update",
						"trigger_event": "on_before_update",
						"conditions_json": [],
						"actions_json": [
							{
								"type": "raise_error",
								"message": (
									"ContentMetrics rows are append-only. "
									"Record a new snapshot instead of updating."
								),
							}
						],
					},
				],
			},
		]

		for rs_def in RULESETS:
			existing = session.execute(
				sa.select(RuleSet).where(RuleSet.name == rs_def["name"])
			).scalar_one_or_none()
			if existing is not None:
				continue
			rs = RuleSet(
				name=rs_def["name"],
				description=rs_def["description"],
				model_name=rs_def["model_name"],
				stop_on_match=rs_def.get("stop_on_match", False),
				enabled=True,
			)
			session.add(rs)
			session.flush()
			for r_def in rs_def.get("rules", []):
				session.add(Rule(
					ruleset_id=rs.id,
					name=r_def["name"],
					trigger_event=r_def["trigger_event"],
					conditions_json=r_def["conditions_json"],
					actions_json=r_def["actions_json"],
					enabled=True,
				))
		log.info("MediaPlugin.setup_rules: %d rulesets configured", len(RULESETS))

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _try_setup_rules(self) -> None:
		try:
			from flask import current_app
			ab = current_app.extensions.get("appbuilder")
			if ab is None:
				return
			session = ab.get_session
			self.setup_rules(session)
			session.commit()
		except RuntimeError:
			pass
		except Exception as exc:
			log.warning("MediaPlugin._try_setup_rules failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> MediaPlugin:
	return MediaPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.media.models import (  # noqa: E402
	ContentItem,
	MediaAsset,
	Publication,
	ContentDistribution,
	SyndicationLicense,
	ContentMetrics,
)
from pgappforge.plugins.erp.industry.media.events import (  # noqa: E402
	emit_event,
	ContentCreatedEvent,
	ContentPublishedEvent,
	ContentScheduledEvent,
	ContentArchivedEvent,
	ContentDistributedEvent,
	ContentLicensedEvent,
	AssetUploadedEvent,
	MetricsSnapshotRecordedEvent,
)
from pgappforge.plugins.erp.industry.media.services import (  # noqa: E402
	MediaService,
	MediaServiceError,
	ContentNotFoundError,
	PublicationNotFoundError,
	AssetNotFoundError,
	InvalidContentStatusError,
	DuplicateSlugError,
)

__all__ = [
	# plugin
	"MediaPlugin",
	"create_plugin",
	# models
	"ContentItem",
	"MediaAsset",
	"Publication",
	"ContentDistribution",
	"SyndicationLicense",
	"ContentMetrics",
	# events
	"emit_event",
	"ContentCreatedEvent",
	"ContentPublishedEvent",
	"ContentScheduledEvent",
	"ContentArchivedEvent",
	"ContentDistributedEvent",
	"ContentLicensedEvent",
	"AssetUploadedEvent",
	"MetricsSnapshotRecordedEvent",
	# services
	"MediaService",
	"MediaServiceError",
	"ContentNotFoundError",
	"PublicationNotFoundError",
	"AssetNotFoundError",
	"InvalidContentStatusError",
	"DuplicateSlugError",
]
