"""
pgappforge/plugins/erp/industry/media/views.py

Flask views for the Media & Publishing plugin.

Views:
  ContentView       — content CRUD with rich text, tags, scheduling
  AssetView         — media asset CRUD with image crop / document viewer
  PublicationView   — publication management
  ContentDashboard  — engagement analytics with AdvancedChartsWidget
"""
from __future__ import annotations

import logging

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	rich_text_widget,
	select2_widget,
	select2_many_widget,
	datetime_widget,
	date_widget,
	file_widget,
	chart_widget,
	map_widget,
	json_widget,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Widget metadata
# ---------------------------------------------------------------------------

CONTENT_WIDGETS = {
	"body_html": rich_text_widget(height=500),
	"keywords": {
		"type": "TagInputWidget",
		"config": {"delimiter": ",", "max_tags": 30, "placeholder": "Add keyword…"},
	},
	"tags": {
		"type": "TagInputWidget",
		"config": {"delimiter": ",", "max_tags": 20},
	},
	"categories": select2_many_widget(),
	"scheduled_publish_at": datetime_widget(),
	"published_at": datetime_widget(),
	"content_type": select2_widget(
		choices=["ARTICLE", "VIDEO", "AUDIO", "PHOTO_ESSAY", "INTERACTIVE", "NEWSLETTER"]
	),
	"status": select2_widget(
		choices=["DRAFT", "REVIEW", "SCHEDULED", "PUBLISHED", "ARCHIVED"]
	),
	"thumbnail_url": file_widget(types=["jpg", "jpeg", "png", "webp"]),
	"editor_id": {
		"type": "Select2AJAXWidget",
		"config": {"delay": 250, "minimum_input_length": 1},
	},
}

ASSET_WIDGETS = {
	"asset_type": select2_widget(choices=["IMAGE", "VIDEO", "AUDIO", "DOCUMENT"]),
	"storage_url": file_widget(
		multiple=False,
		types=["jpg", "jpeg", "png", "webp", "mp4", "mp3", "pdf"],
	),
	"thumbnail_url": file_widget(types=["jpg", "jpeg", "png", "webp"]),
	"taken_at": datetime_widget(),
	"geo_point": map_widget(zoom=12),
	"usage_rights": json_widget(mode="tree", height=150),
	"metadata": json_widget(mode="tree", height=200, readonly=True),
	# ImageCropWidget for image assets
	"_image_crop": {
		"type": "ImageCropWidget",
		"config": {
			"aspect_ratios": ["16:9", "4:3", "1:1", "3:2"],
			"preview": True,
			"output_format": "webp",
		},
	},
	# DocumentViewerWidget for document assets
	"_doc_viewer": {
		"type": "DocumentViewerWidget",
		"config": {
			"supported_types": ["pdf", "docx"],
			"allow_download": True,
			"show_page_count": True,
		},
	},
}

DASHBOARD_WIDGETS = {
	"page_views_trend": chart_widget("line"),
	"social_shares_trend": chart_widget("bar"),
	"content_type_mix": chart_widget("doughnut"),
	"engagement_heatmap": chart_widget("heatmap"),
	"top_content": chart_widget("horizontalBar"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.media.services import MediaService
	return MediaService()


# ---------------------------------------------------------------------------
# ContentView
# ---------------------------------------------------------------------------

class ContentView(BaseView):
	"""Content CRUD with publishing workflow.

	GET  /media/content/                        — list
	POST /media/content/                        — create draft
	GET  /media/content/<id>                    — detail
	PUT  /media/content/<id>                    — update
	POST /media/content/<id>/publish            — publish to channels
	POST /media/content/<id>/schedule           — schedule publication
	POST /media/content/<id>/archive            — archive
	"""

	route_base = "/media/content"
	default_view = "list"
	_widgets = CONTENT_WIDGETS

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.media.models import ContentItem
		session = _get_session()
		q = sa.select(ContentItem).order_by(ContentItem.published_at.desc()).limit(200)
		if request.args.get("tenant_id"):
			q = q.where(ContentItem.tenant_id == request.args["tenant_id"])
		if request.args.get("status"):
			q = q.where(ContentItem.status == request.args["status"])
		if request.args.get("content_type"):
			q = q.where(ContentItem.content_type == request.args["content_type"])
		if request.args.get("editor_id"):
			q = q.where(ContentItem.editor_id == request.args["editor_id"])
		items = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": item.id,
				"slug": item.slug,
				"headline": item.headline,
				"content_type": item.content_type,
				"status": item.status,
				"language": item.language,
				"word_count": item.word_count,
				"reading_time_minutes": item.reading_time_minutes,
				"published_at": item.published_at.isoformat() if item.published_at else None,
				"scheduled_publish_at": (
					item.scheduled_publish_at.isoformat()
					if item.scheduled_publish_at else None
				),
				"thumbnail_url": item.thumbnail_url,
				"categories": item.categories,
				"tags": item.tags,
			}
			for item in items
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.media.models import ContentItem
		from pgappforge.plugins.erp.industry.media.events import (
			ContentCreatedEvent, emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "slug", "headline", "content_type")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			item = ContentItem(
				tenant_id=data["tenant_id"],
				slug=data["slug"],
				headline=data["headline"],
				subheadline=data.get("subheadline"),
				body_html=data.get("body_html"),
				content_type=data["content_type"],
				author_ids=data.get("author_ids", []),
				contributor_ids=data.get("contributor_ids", []),
				editor_id=data.get("editor_id"),
				status="DRAFT",
				categories=data.get("categories", []),
				tags=data.get("tags", []),
				keywords=data.get("keywords", []),
				language=data.get("language", "en"),
				word_count=data.get("word_count"),
				reading_time_minutes=data.get("reading_time_minutes"),
				thumbnail_url=data.get("thumbnail_url"),
				iptc_subject_codes=data.get("iptc_subject_codes", []),
				wire_service=data.get("wire_service"),
			)
			session.add(item)
			session.flush()
			emit_event(
				ContentCreatedEvent(
					aggregate_id=item.id,
					aggregate_type="ContentItem",
					tenant_id=item.tenant_id,
					content_id=item.id,
					slug=item.slug,
					content_type=item.content_type,
					editor_id=item.editor_id or "",
				),
				session,
			)
			session.commit()
			return jsonify({"content_id": item.id, "slug": item.slug, "status": item.status}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:content_id>")
	@has_access
	def detail(self, content_id: str):
		from pgappforge.plugins.erp.industry.media.models import ContentItem
		session = _get_session()
		item = session.get(ContentItem, content_id)
		if item is None:
			abort(404)
		return jsonify({
			"id": item.id,
			"tenant_id": item.tenant_id,
			"slug": item.slug,
			"headline": item.headline,
			"subheadline": item.subheadline,
			"body_html": item.body_html,
			"content_type": item.content_type,
			"author_ids": item.author_ids,
			"contributor_ids": item.contributor_ids,
			"editor_id": item.editor_id,
			"status": item.status,
			"published_at": item.published_at.isoformat() if item.published_at else None,
			"scheduled_publish_at": (
				item.scheduled_publish_at.isoformat()
				if item.scheduled_publish_at else None
			),
			"categories": item.categories,
			"tags": item.tags,
			"keywords": item.keywords,
			"language": item.language,
			"word_count": item.word_count,
			"reading_time_minutes": item.reading_time_minutes,
			"thumbnail_url": item.thumbnail_url,
			"iptc_subject_codes": item.iptc_subject_codes,
			"wire_service": item.wire_service,
			"_widgets": CONTENT_WIDGETS,
		})

	@expose("/<string:content_id>", methods=["PUT"])
	@has_access
	def update(self, content_id: str):
		from pgappforge.plugins.erp.industry.media.models import ContentItem
		session = _get_session()
		item = session.get(ContentItem, content_id)
		if item is None:
			abort(404)
		if item.status == "PUBLISHED":
			return jsonify({"error": "Cannot edit PUBLISHED content — archive and create new version"}), 422
		data = request.get_json(force=True) or {}
		updatable = (
			"headline", "subheadline", "body_html", "categories",
			"tags", "keywords", "word_count", "reading_time_minutes",
			"thumbnail_url", "iptc_subject_codes", "wire_service",
			"author_ids", "contributor_ids",
		)
		for field in updatable:
			if field in data:
				setattr(item, field, data[field])
		session.commit()
		return jsonify({"content_id": content_id, "status": item.status})

	@expose("/<string:content_id>/publish", methods=["POST"])
	@has_access
	def publish(self, content_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		channels = data.get("channels", ["WEB"])
		try:
			distributions = _svc().publish_content(content_id, channels, session)
			session.commit()
			return jsonify({
				"content_id": content_id,
				"status": "PUBLISHED",
				"distributions": [d.id for d in distributions],
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:content_id>/schedule", methods=["POST"])
	@has_access
	def schedule(self, content_id: str):
		session = _get_session()
		data = request.get_json(force=True) or {}
		if not data.get("publish_at"):
			return jsonify({"error": "publish_at required"}), 400
		try:
			from datetime import datetime, timezone as tz
			publish_at = datetime.fromisoformat(data["publish_at"])
			if publish_at.tzinfo is None:
				publish_at = publish_at.replace(tzinfo=tz.utc)
			item = _svc().schedule_publication(content_id, publish_at, session)
			session.commit()
			return jsonify({
				"content_id": content_id,
				"status": "SCHEDULED",
				"scheduled_publish_at": publish_at.isoformat(),
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:content_id>/archive", methods=["POST"])
	@has_access
	def archive(self, content_id: str):
		from pgappforge.plugins.erp.industry.media.models import ContentItem
		from pgappforge.plugins.erp.industry.media.events import (
			ContentArchivedEvent, emit_event,
		)
		session = _get_session()
		item = session.get(ContentItem, content_id)
		if item is None:
			abort(404)
		item.status = "ARCHIVED"
		emit_event(
			ContentArchivedEvent(
				aggregate_id=content_id,
				aggregate_type="ContentItem",
				tenant_id=item.tenant_id,
				content_id=content_id,
				slug=item.slug,
			),
			session,
		)
		session.commit()
		return jsonify({"content_id": content_id, "status": "ARCHIVED"})


# ---------------------------------------------------------------------------
# AssetView
# ---------------------------------------------------------------------------

class AssetView(BaseView):
	"""Media asset management with crop and document viewer.

	GET  /media/assets/               — list
	POST /media/assets/               — upload / register asset
	GET  /media/assets/<id>           — detail (with widget hints)
	"""

	route_base = "/media/assets"
	default_view = "list"
	_widgets = ASSET_WIDGETS

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.media.models import MediaAsset
		session = _get_session()
		q = sa.select(MediaAsset).order_by(MediaAsset.created_at.desc()).limit(200)
		if request.args.get("content_item_id"):
			q = q.where(MediaAsset.content_item_id == request.args["content_item_id"])
		if request.args.get("asset_type"):
			q = q.where(MediaAsset.asset_type == request.args["asset_type"])
		if request.args.get("tenant_id"):
			q = q.where(MediaAsset.tenant_id == request.args["tenant_id"])
		assets = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": a.id,
				"content_item_id": a.content_item_id,
				"asset_type": a.asset_type,
				"filename": a.filename,
				"mime_type": a.mime_type,
				"file_size_bytes": a.file_size_bytes,
				"storage_url": a.storage_url,
				"thumbnail_url": a.thumbnail_url,
				"caption": a.caption,
				"credit": a.credit,
				"copyright_holder": a.copyright_holder,
				"license_type": a.license_type,
				"taken_at": a.taken_at.isoformat() if a.taken_at else None,
			}
			for a in assets
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.media.models import MediaAsset
		from pgappforge.plugins.erp.industry.media.events import (
			AssetUploadedEvent, emit_event,
		)
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "asset_type", "filename", "mime_type", "storage_url")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			from datetime import datetime, timezone as tz
			taken_at_raw = data.get("taken_at")
			taken_at = None
			if taken_at_raw:
				taken_at = datetime.fromisoformat(taken_at_raw)
				if taken_at.tzinfo is None:
					taken_at = taken_at.replace(tzinfo=tz.utc)

			asset = MediaAsset(
				tenant_id=data["tenant_id"],
				content_item_id=data.get("content_item_id"),
				asset_type=data["asset_type"],
				filename=data["filename"],
				mime_type=data["mime_type"],
				file_size_bytes=data.get("file_size_bytes"),
				storage_url=data["storage_url"],
				thumbnail_url=data.get("thumbnail_url"),
				caption=data.get("caption"),
				credit=data.get("credit"),
				alt_text=data.get("alt_text"),
				copyright_holder=data.get("copyright_holder"),
				license_type=data.get("license_type"),
				usage_rights=data.get("usage_rights", {}),
				geo_point=data.get("geo_point"),
				taken_at=taken_at,
				metadata=data.get("metadata", {}),
			)
			session.add(asset)
			session.flush()
			emit_event(
				AssetUploadedEvent(
					aggregate_id=asset.id,
					aggregate_type="MediaAsset",
					tenant_id=asset.tenant_id,
					asset_id=asset.id,
					content_id=asset.content_item_id or "",
					asset_type=asset.asset_type,
					filename=asset.filename,
					file_size_bytes=asset.file_size_bytes or 0,
				),
				session,
			)
			session.commit()
			return jsonify({"asset_id": asset.id, "storage_url": asset.storage_url}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:asset_id>")
	@has_access
	def detail(self, asset_id: str):
		from pgappforge.plugins.erp.industry.media.models import MediaAsset
		session = _get_session()
		asset = session.get(MediaAsset, asset_id)
		if asset is None:
			abort(404)
		# Select widget hints based on asset type
		is_image = asset.mime_type and asset.mime_type.startswith("image/")
		is_doc = asset.mime_type in ("application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
		widget_hints = {**ASSET_WIDGETS}
		if not is_image:
			widget_hints.pop("_image_crop", None)
		if not is_doc:
			widget_hints.pop("_doc_viewer", None)
		return jsonify({
			"id": asset.id,
			"tenant_id": asset.tenant_id,
			"content_item_id": asset.content_item_id,
			"asset_type": asset.asset_type,
			"filename": asset.filename,
			"mime_type": asset.mime_type,
			"file_size_bytes": asset.file_size_bytes,
			"storage_url": asset.storage_url,
			"thumbnail_url": asset.thumbnail_url,
			"caption": asset.caption,
			"credit": asset.credit,
			"alt_text": asset.alt_text,
			"copyright_holder": asset.copyright_holder,
			"license_type": asset.license_type,
			"usage_rights": asset.usage_rights,
			"geo_point": asset.geo_point,
			"taken_at": asset.taken_at.isoformat() if asset.taken_at else None,
			"metadata": asset.metadata,
			"_widgets": widget_hints,
		})


# ---------------------------------------------------------------------------
# PublicationView
# ---------------------------------------------------------------------------

class PublicationView(BaseView):
	"""Publication management.

	GET  /media/publications/          — list
	POST /media/publications/          — create
	GET  /media/publications/<id>/feed — wire feed (RSS-compatible)
	"""

	route_base = "/media/publications"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.media.models import Publication
		session = _get_session()
		q = sa.select(Publication).order_by(Publication.name)
		if request.args.get("tenant_id"):
			q = q.where(Publication.tenant_id == request.args["tenant_id"])
		pubs = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"name": p.name,
				"slug": p.slug,
				"publication_type": p.publication_type,
				"base_url": p.base_url,
				"language": p.language,
				"timezone": p.timezone,
				"circulation": p.circulation,
				"logo_url": p.logo_url,
				"publisher_id": p.publisher_id,
			}
			for p in pubs
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.media.models import Publication
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "name", "slug", "publication_type", "publisher_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			pub = Publication(
				tenant_id=data["tenant_id"],
				name=data["name"],
				slug=data["slug"],
				publication_type=data["publication_type"],
				base_url=data.get("base_url"),
				language=data.get("language", "en"),
				timezone=data.get("timezone", "UTC"),
				logo_url=data.get("logo_url"),
				circulation=data.get("circulation"),
				publisher_id=data["publisher_id"],
			)
			session.add(pub)
			session.commit()
			return jsonify({"publication_id": pub.id, "slug": pub.slug}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:publication_id>/feed")
	@has_access
	def feed(self, publication_id: str):
		"""RSS/Atom-compatible wire feed for a publication."""
		session = _get_session()
		limit = int(request.args.get("limit", 20))
		try:
			items = _svc().generate_wire_feed(publication_id, session, limit=limit)
			return jsonify({
				"publication_id": publication_id,
				"item_count": len(items),
				"items": items,
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 404


# ---------------------------------------------------------------------------
# ContentDashboard
# ---------------------------------------------------------------------------

class ContentDashboard(BaseView):
	"""Engagement analytics dashboard.

	GET /media/dashboard/                          — index
	GET /media/dashboard/top-content              — top performing content
	GET /media/dashboard/engagement-trends/<id>   — per-content metrics trend
	GET /media/dashboard/distribution-summary     — distribution channel breakdown
	"""

	route_base = "/media/dashboard"
	default_view = "index"
	_widgets = DASHBOARD_WIDGETS

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"widgets": list(DASHBOARD_WIDGETS.keys()),
			"endpoints": {
				"top_content": "/media/dashboard/top-content",
				"engagement_trends": "/media/dashboard/engagement-trends/<content_id>",
				"distribution_summary": "/media/dashboard/distribution-summary",
			},
		})

	@expose("/top-content")
	@has_access
	def top_content(self):
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id required"}), 400
		period_days = int(request.args.get("period_days", 7))
		metric = request.args.get("metric", "page_views")
		limit = int(request.args.get("limit", 10))
		try:
			results = _svc().get_top_content(
				tenant_id, session,
				period_days=period_days,
				metric=metric,
				limit=limit,
			)
			return jsonify({
				"tenant_id": tenant_id,
				"period_days": period_days,
				"metric": metric,
				"count": len(results),
				"items": results,
				"_chart": chart_widget("horizontalBar"),
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/engagement-trends/<string:content_id>")
	@has_access
	def engagement_trends(self, content_id: str):
		"""Return time-series engagement metrics for a content item."""
		from pgappforge.plugins.erp.industry.media.models import ContentMetrics
		session = _get_session()
		rows = session.execute(
			sa.select(ContentMetrics)
			.where(ContentMetrics.content_id == content_id)
			.order_by(ContentMetrics.recorded_at)
		).scalars().all()
		return jsonify({
			"content_id": content_id,
			"count": len(rows),
			"_chart": chart_widget("line"),
			"metrics": [
				{
					"recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
					"page_views": r.page_views,
					"unique_visitors": r.unique_visitors,
					"avg_time_on_page_seconds": r.avg_time_on_page_seconds,
					"social_shares": r.social_shares,
					"comments": r.comments,
					"bounce_rate_pct": float(r.bounce_rate_pct) if r.bounce_rate_pct else None,
				}
				for r in rows
			],
		})

	@expose("/distribution-summary")
	@has_access
	def distribution_summary(self):
		"""Channel distribution breakdown for a tenant."""
		from pgappforge.plugins.erp.industry.media.models import ContentDistribution
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id required"}), 400
		rows = session.execute(
			sa.select(
				ContentDistribution.channel,
				sa.func.count(ContentDistribution.id).label("count"),
				sa.func.sum(ContentDistribution.reach).label("total_reach"),
			)
			.where(ContentDistribution.tenant_id == tenant_id)
			.group_by(ContentDistribution.channel)
			.order_by(sa.desc("total_reach"))
		).all()
		return jsonify({
			"tenant_id": tenant_id,
			"_chart": chart_widget("bar"),
			"channels": [
				{
					"channel": r.channel,
					"distribution_count": r.count,
					"total_reach": r.total_reach or 0,
				}
				for r in rows
			],
		})


__all__ = [
	"ContentView",
	"AssetView",
	"PublicationView",
	"ContentDashboard",
]
