"""
pgappforge/plugins/erp/industry/research/views.py

Flask views for the Research Data Management plugin.

Views:
  ResearchProjectView   — CRUD + DMP generation, impact metrics, status transitions
  DatasetView           — CRUD + DOI minting, DataCite XML export, quality check
  DataProvenanceView    — read-only provenance chain (immutable records)
  PublicationView       — CRUD + citation count update
  PeerReviewView        — CRUD
  ResearchDashboardView — impact metrics dashboard at /research/dashboard/
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	date_widget,
	datetime_widget,
	json_widget,
	rich_text_widget,
	select2_widget,
	chart_widget,
	star_widget,
	file_widget,
	progress_widget,
)

log = logging.getLogger(__name__)

# Status choices for Select2 widgets
_PROJECT_STATUSES = ["PLANNING", "ACTIVE", "ANALYSIS", "WRITING", "COMPLETED"]
_RESOURCE_TYPES = ["DATASET", "SOFTWARE", "IMAGE", "COLLECTION", "TEXT", "WORKFLOW"]
_ACCESS_RIGHTS = ["OPEN", "RESTRICTED", "EMBARGOED", "CLOSED"]
_REVIEW_DECISIONS = ["ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT"]
_ACTIVITY_TYPES = ["COLLECTION", "PROCESSING", "TRANSFORMATION", "ANALYSIS"]


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
	from pgappforge.plugins.erp.industry.research.services import ResearchService
	return ResearchService()


def _parse_date(s: str | None) -> date | None:
	return date.fromisoformat(s) if s else None


def _parse_dt(s: str | None) -> datetime | None:
	return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


# ---------------------------------------------------------------------------
# ResearchProjectView
# ---------------------------------------------------------------------------

class ResearchProjectView(BaseView):
	"""Research project CRUD with DMP generation and impact metrics.

	Widget hints:
	  - DatePickerWidget:  start_date, end_date
	  - Select2Widget:     status (PLANNING/ACTIVE/ANALYSIS/WRITING/COMPLETED)
	  - RichTextWidget:    description
	  - ProgressWidget:    budget utilisation

	GET  /research/projects/                           — list
	GET  /research/projects/<id>                       — detail
	POST /research/projects/                           — create
	GET  /research/projects/<id>/dmp                  — generate DMP document
	GET  /research/projects/<id>/impact               — impact metrics
	POST /research/projects/<id>/complete             — transition to COMPLETED
	"""

	route_base = "/research/projects"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.research.models import ResearchProject
		session = _get_session()
		status = request.args.get("status")
		tenant_id = request.args.get("tenant_id")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(ResearchProject)
			.order_by(ResearchProject.start_date.desc().nullslast())
			.limit(limit)
		)
		if status:
			q = q.where(ResearchProject.status == status)
		if tenant_id:
			q = q.where(ResearchProject.tenant_id == tenant_id)

		projects = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"project_code": p.project_code,
				"title": p.title,
				"status": p.status,
				"funding_source": p.funding_source,
				"grant_reference": p.grant_reference,
				"start_date": p.start_date.isoformat() if p.start_date else None,
				"end_date": p.end_date.isoformat() if p.end_date else None,
				"budget_cents": p.budget_cents,
				"ethical_approval_number": p.ethical_approval_number,
				"_widget_hints": {
					"status": select2_widget(_PROJECT_STATUSES),
					"start_date": date_widget(),
					"end_date": date_widget(),
					"description": rich_text_widget(),
				},
			}
			for p in projects
		])

	@expose("/<string:project_id>")
	@has_access
	def detail(self, project_id: str):
		from pgappforge.plugins.erp.industry.research.models import ResearchProject
		session = _get_session()
		p = session.get(ResearchProject, project_id)
		if p is None:
			abort(404, f"ResearchProject {project_id!r} not found")
		return jsonify({
			"id": p.id,
			"tenant_id": p.tenant_id,
			"project_code": p.project_code,
			"title": p.title,
			"description": p.description,
			"principal_investigator_id": p.principal_investigator_id,
			"institution_id": p.institution_id,
			"funding_source": p.funding_source,
			"grant_reference": p.grant_reference,
			"start_date": p.start_date.isoformat() if p.start_date else None,
			"end_date": p.end_date.isoformat() if p.end_date else None,
			"budget_cents": p.budget_cents,
			"status": p.status,
			"ethical_approval_number": p.ethical_approval_number,
			"data_management_plan_url": p.data_management_plan_url,
			"created_at": p.created_at.isoformat() if p.created_at else None,
			"updated_at": p.updated_at.isoformat() if p.updated_at else None,
			"_widget_hints": {
				"status": select2_widget(_PROJECT_STATUSES),
				"start_date": date_widget(),
				"end_date": date_widget(),
				"description": rich_text_widget(),
				"budget_cents": {"type": "CurrencyWidget", "config": {"currency": "USD", "decimal_places": 2}},
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.research.models import ResearchProject
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "project_code", "title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		proj = ResearchProject(
			tenant_id=data["tenant_id"],
			project_code=data["project_code"],
			title=data["title"],
			description=data.get("description"),
			principal_investigator_id=data.get("principal_investigator_id"),
			institution_id=data.get("institution_id"),
			funding_source=data.get("funding_source"),
			grant_reference=data.get("grant_reference"),
			start_date=_parse_date(data.get("start_date")),
			end_date=_parse_date(data.get("end_date")),
			budget_cents=int(data.get("budget_cents", 0)),
			status=data.get("status", "PLANNING"),
			ethical_approval_number=data.get("ethical_approval_number"),
			data_management_plan_url=data.get("data_management_plan_url"),
		)
		session.add(proj)
		session.commit()
		return jsonify({"project_id": proj.id, "project_code": proj.project_code}), 201

	@expose("/<string:project_id>/dmp")
	@has_access
	def generate_dmp(self, project_id: str):
		"""Action: Generate Data Management Plan document (Markdown)."""
		session = _get_session()
		try:
			dmp = _svc().generate_data_management_plan(project_id, session)
			return jsonify({
				"project_id": project_id,
				"format": "markdown",
				"content": dmp,
				"_widget_hints": {"content": rich_text_widget(height=600)},
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:project_id>/impact")
	@has_access
	def impact_metrics(self, project_id: str):
		"""Action: Research impact metrics (citations, h-index, dataset counts)."""
		session = _get_session()
		try:
			result = _svc().calculate_impact_metrics(project_id, session)
			result["_widget_hints"] = {
				"charts": chart_widget("bar"),
				"h_index": star_widget(max_rating=20, readonly=True),
			}
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:project_id>/complete", methods=["POST"])
	@has_access
	def complete_project(self, project_id: str):
		"""Action: Transition project to COMPLETED status."""
		from pgappforge.plugins.erp.industry.research.models import ResearchProject
		from pgappforge.plugins.erp.industry.research.events import ResearchProjectCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed

		session = _get_session()
		proj = session.get(ResearchProject, project_id)
		if proj is None:
			abort(404)
		if proj.status == "COMPLETED":
			return jsonify({"error": "Project is already COMPLETED"}), 422

		from pgappforge.plugins.erp.industry.research.models import Dataset, Publication
		dataset_count = session.execute(
			sa.select(sa.func.count(Dataset.id)).where(Dataset.project_id == project_id)
		).scalar_one() or 0
		pub_count = session.execute(
			sa.select(sa.func.count(Publication.id)).where(Publication.project_id == project_id)
		).scalar_one() or 0

		proj.status = "COMPLETED"
		session.flush()

		_emit_typed(
			ResearchProjectCompletedEvent(
				aggregate_id=project_id,
				aggregate_type="ResearchProject",
				tenant_id=str(proj.tenant_id),
				project_id=project_id,
				project_code=proj.project_code,
				title=proj.title,
				dataset_count=dataset_count,
				publication_count=pub_count,
			),
			session,
		)
		session.commit()
		return jsonify({
			"project_id": project_id,
			"project_code": proj.project_code,
			"status": proj.status,
			"dataset_count": dataset_count,
			"publication_count": pub_count,
		})


# ---------------------------------------------------------------------------
# DatasetView
# ---------------------------------------------------------------------------

class DatasetView(BaseView):
	"""Dataset CRUD with DOI minting, DataCite XML export, and quality checks.

	Widget hints:
	  - Select2Widget:      resource_type, access_rights
	  - JSONEditorWidget:   metadata, creator_ids
	  - FileUploadWidget:   file_format
	  - DatePickerWidget:   published_at

	GET  /research/datasets/                          — list
	GET  /research/datasets/<id>                      — detail
	POST /research/datasets/                          — create
	POST /research/datasets/<id>/mint-doi             — register DOI (DataCite)
	GET  /research/datasets/<id>/datacite-xml         — export DataCite 4.4 XML
	GET  /research/datasets/<id>/quality              — data quality check
	POST /research/datasets/<id>/publish              — mark as published
	"""

	route_base = "/research/datasets"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.research.models import Dataset
		session = _get_session()
		project_id = request.args.get("project_id")
		access_rights = request.args.get("access_rights")
		resource_type = request.args.get("resource_type")
		is_published = request.args.get("is_published")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(Dataset)
			.order_by(Dataset.created_at.desc())
			.limit(limit)
		)
		if project_id:
			q = q.where(Dataset.project_id == project_id)
		if access_rights:
			q = q.where(Dataset.access_rights == access_rights)
		if resource_type:
			q = q.where(Dataset.resource_type == resource_type)
		if is_published is not None:
			q = q.where(Dataset.is_published == (is_published.lower() == "true"))

		datasets = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": d.id,
				"doi": d.doi,
				"title": d.title,
				"project_id": d.project_id,
				"resource_type": d.resource_type,
				"access_rights": d.access_rights,
				"language": d.language,
				"version": d.version,
				"is_published": d.is_published,
				"published_at": d.published_at.isoformat() if d.published_at else None,
				"file_size_bytes": d.file_size_bytes,
				"_widget_hints": {
					"resource_type": select2_widget(_RESOURCE_TYPES),
					"access_rights": select2_widget(_ACCESS_RIGHTS),
				},
			}
			for d in datasets
		])

	@expose("/<string:dataset_id>")
	@has_access
	def detail(self, dataset_id: str):
		from pgappforge.plugins.erp.industry.research.models import Dataset
		session = _get_session()
		d = session.get(Dataset, dataset_id)
		if d is None:
			abort(404, f"Dataset {dataset_id!r} not found")
		return jsonify({
			"id": d.id,
			"tenant_id": d.tenant_id,
			"doi": d.doi,
			"title": d.title,
			"description": d.description,
			"project_id": d.project_id,
			"creator_ids": d.creator_ids,
			"resource_type": d.resource_type,
			"subjects": d.subjects,
			"keywords": d.keywords,
			"language": d.language,
			"publication_year": d.publication_year,
			"version": d.version,
			"license": d.license,
			"access_rights": d.access_rights,
			"storage_url": d.storage_url,
			"file_format": d.file_format,
			"file_size_bytes": d.file_size_bytes,
			"extra_metadata": d.extra_metadata,
			"is_published": d.is_published,
			"published_at": d.published_at.isoformat() if d.published_at else None,
			"created_at": d.created_at.isoformat() if d.created_at else None,
			"updated_at": d.updated_at.isoformat() if d.updated_at else None,
			"_widget_hints": {
				"resource_type": select2_widget(_RESOURCE_TYPES),
				"access_rights": select2_widget(_ACCESS_RIGHTS),
				"creator_ids": json_widget(mode="code"),
				"extra_metadata": json_widget(mode="tree"),
				"description": rich_text_widget(),
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.research.models import Dataset
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "project_id", "title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		ds = Dataset(
			tenant_id=data["tenant_id"],
			project_id=data["project_id"],
			title=data["title"],
			description=data.get("description"),
			creator_ids=data.get("creator_ids", []),
			resource_type=data.get("resource_type", "DATASET"),
			subjects=data.get("subjects", []),
			keywords=data.get("keywords", []),
			language=data.get("language", "en"),
			publication_year=data.get("publication_year"),
			version=data.get("version", "1"),
			license=data.get("license"),
			access_rights=data.get("access_rights", "OPEN"),
			storage_url=data.get("storage_url"),
			file_format=data.get("file_format", []),
			file_size_bytes=data.get("file_size_bytes"),
			extra_metadata=data.get("extra_metadata", data.get("metadata", {})),
			is_published=bool(data.get("is_published", False)),
		)
		session.add(ds)
		session.commit()
		return jsonify({"dataset_id": ds.id, "title": ds.title}), 201

	@expose("/<string:dataset_id>/mint-doi", methods=["POST"])
	@has_access
	def mint_doi(self, dataset_id: str):
		"""Action: Register DOI via DataCite API."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		try:
			from flask import current_app
			cfg = current_app.config
			doi = _svc().mint_doi(
				dataset_id,
				session,
				datacite_url=cfg.get("DATACITE_API_URL", "https://api.datacite.org"),
				datacite_username=cfg.get("DATACITE_USERNAME", ""),
				datacite_password=cfg.get("DATACITE_PASSWORD", ""),
				doi_prefix=cfg.get("DATACITE_DOI_PREFIX", "10.5281"),
				dry_run=bool(data.get("dry_run", False)),
			)
			session.commit()
			return jsonify({"dataset_id": dataset_id, "doi": doi})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:dataset_id>/datacite-xml")
	@has_access
	def datacite_xml(self, dataset_id: str):
		"""Action: Export DataCite Metadata Schema 4.4 XML."""
		session = _get_session()
		try:
			xml = _svc().export_datacite_xml(dataset_id, session)
			from flask import Response
			return Response(xml, mimetype="application/xml")
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:dataset_id>/quality")
	@has_access
	def quality_check(self, dataset_id: str):
		"""Action: Run DataCite metadata completeness / consistency checks."""
		session = _get_session()
		try:
			result = _svc().check_data_quality(dataset_id, session)
			result["_widget_hints"] = {
				"score": progress_widget(max_value=100),
				"issues": json_widget(mode="view", readonly=True),
			}
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:dataset_id>/publish", methods=["POST"])
	@has_access
	def publish(self, dataset_id: str):
		"""Action: Mark dataset as published."""
		from pgappforge.plugins.erp.industry.research.models import Dataset
		from pgappforge.plugins.erp.industry.research.events import DatasetPublishedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed

		session = _get_session()
		ds = session.get(Dataset, dataset_id)
		if ds is None:
			abort(404)
		if ds.is_published:
			return jsonify({"error": "Dataset is already published"}), 422

		now = datetime.now(timezone.utc)
		ds.is_published = True
		ds.published_at = now
		session.flush()

		_emit_typed(
			DatasetPublishedEvent(
				aggregate_id=dataset_id,
				aggregate_type="Dataset",
				tenant_id=str(ds.tenant_id),
				dataset_id=dataset_id,
				doi=ds.doi or "",
				project_id=str(ds.project_id),
				access_rights=ds.access_rights,
				published_at=now.isoformat(),
			),
			session,
		)
		session.commit()
		return jsonify({
			"dataset_id": dataset_id,
			"is_published": True,
			"published_at": now.isoformat(),
			"doi": ds.doi,
		})


# ---------------------------------------------------------------------------
# DataProvenanceView
# ---------------------------------------------------------------------------

class DataProvenanceView(BaseView):
	"""Provenance chain view — read-only (records are immutable).

	Widget hints:
	  - JSONEditorWidget (readonly): inputs, outputs, parameters, software_used
	  - DateTimePickerWidget:        started_at, ended_at
	  - Select2Widget:               activity_type

	GET  /research/provenance/                        — list (filter by dataset_id)
	GET  /research/provenance/<id>                    — detail
	POST /research/provenance/                        — record new provenance activity
	"""

	route_base = "/research/provenance"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.research.models import DataProvenance
		session = _get_session()
		dataset_id = request.args.get("dataset_id")
		activity_type = request.args.get("activity_type")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(DataProvenance)
			.order_by(DataProvenance.started_at.desc())
			.limit(limit)
		)
		if dataset_id:
			q = q.where(DataProvenance.dataset_id == dataset_id)
		if activity_type:
			q = q.where(DataProvenance.activity_type == activity_type)

		records = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"dataset_id": r.dataset_id,
				"activity_type": r.activity_type,
				"performed_by_id": r.performed_by_id,
				"started_at": r.started_at.isoformat() if r.started_at else None,
				"ended_at": r.ended_at.isoformat() if r.ended_at else None,
				"description": r.description,
				"_immutable": True,
				"_widget_hints": {
					"activity_type": select2_widget(_ACTIVITY_TYPES),
					"started_at": datetime_widget(),
					"inputs": json_widget(mode="view", readonly=True),
					"outputs": json_widget(mode="view", readonly=True),
				},
			}
			for r in records
		])

	@expose("/<string:prov_id>")
	@has_access
	def detail(self, prov_id: str):
		from pgappforge.plugins.erp.industry.research.models import DataProvenance
		session = _get_session()
		r = session.get(DataProvenance, prov_id)
		if r is None:
			abort(404, f"DataProvenance {prov_id!r} not found")
		return jsonify({
			"id": r.id,
			"tenant_id": r.tenant_id,
			"dataset_id": r.dataset_id,
			"activity_type": r.activity_type,
			"performed_by_id": r.performed_by_id,
			"started_at": r.started_at.isoformat() if r.started_at else None,
			"ended_at": r.ended_at.isoformat() if r.ended_at else None,
			"inputs": r.inputs,
			"outputs": r.outputs,
			"parameters": r.parameters,
			"software_used": r.software_used,
			"description": r.description,
			"created_at": r.created_at.isoformat() if r.created_at else None,
			"_immutable": True,
			"_widget_hints": {
				"activity_type": select2_widget(_ACTIVITY_TYPES),
				"inputs": json_widget(mode="view", readonly=True),
				"outputs": json_widget(mode="view", readonly=True),
				"parameters": json_widget(mode="view", readonly=True),
				"software_used": json_widget(mode="view", readonly=True),
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Record a new provenance activity (immutable insert)."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("dataset_id", "activity_type", "started_at")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			prov = _svc().track_provenance(
				dataset_id=data["dataset_id"],
				activity_type=data["activity_type"],
				details={
					"inputs": data.get("inputs", []),
					"outputs": data.get("outputs", []),
					"parameters": data.get("parameters", {}),
					"software_used": data.get("software_used", []),
					"description": data.get("description"),
				},
				session=session,
				performed_by_id=data.get("performed_by_id"),
				started_at=_parse_dt(data.get("started_at")),
				ended_at=_parse_dt(data.get("ended_at")),
			)
			session.commit()
			return jsonify({
				"provenance_id": prov.id,
				"dataset_id": prov.dataset_id,
				"activity_type": prov.activity_type,
				"_immutable": True,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# PublicationView
# ---------------------------------------------------------------------------

class PublicationView(BaseView):
	"""Publication CRUD with citation count refresh.

	Widget hints:
	  - DatePickerWidget:   publication_date
	  - JSONEditorWidget:   authors
	  - StarRatingWidget:   star_rating (derived from citation tier)

	GET  /research/publications/                      — list
	GET  /research/publications/<id>                  — detail
	POST /research/publications/                      — create
	POST /research/publications/<id>/update-citations — refresh citation_count
	"""

	route_base = "/research/publications"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.research.models import Publication
		session = _get_session()
		project_id = request.args.get("project_id")
		dataset_id = request.args.get("dataset_id")
		is_open_access = request.args.get("is_open_access")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(Publication)
			.order_by(Publication.citation_count.desc())
			.limit(limit)
		)
		if project_id:
			q = q.where(Publication.project_id == project_id)
		if dataset_id:
			q = q.where(Publication.dataset_id == dataset_id)
		if is_open_access is not None:
			q = q.where(Publication.is_open_access == (is_open_access.lower() == "true"))

		pubs = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": p.id,
				"title": p.title,
				"journal": p.journal,
				"doi": p.doi,
				"publication_date": p.publication_date.isoformat() if p.publication_date else None,
				"is_open_access": p.is_open_access,
				"citation_count": p.citation_count,
				"project_id": p.project_id,
				"dataset_id": p.dataset_id,
				"_widget_hints": {
					"publication_date": date_widget(),
					"citation_count": star_widget(max_rating=100, readonly=True),
				},
			}
			for p in pubs
		])

	@expose("/<string:pub_id>")
	@has_access
	def detail(self, pub_id: str):
		from pgappforge.plugins.erp.industry.research.models import Publication
		session = _get_session()
		p = session.get(Publication, pub_id)
		if p is None:
			abort(404, f"Publication {pub_id!r} not found")
		return jsonify({
			"id": p.id,
			"tenant_id": p.tenant_id,
			"dataset_id": p.dataset_id,
			"project_id": p.project_id,
			"title": p.title,
			"journal": p.journal,
			"doi": p.doi,
			"authors": p.authors,
			"publication_date": p.publication_date.isoformat() if p.publication_date else None,
			"abstract": p.abstract,
			"is_open_access": p.is_open_access,
			"citation_count": p.citation_count,
			"pdf_url": p.pdf_url,
			"created_at": p.created_at.isoformat() if p.created_at else None,
			"_widget_hints": {
				"publication_date": date_widget(),
				"authors": json_widget(mode="tree"),
				"abstract": rich_text_widget(),
				"citation_count": star_widget(max_rating=100, readonly=True),
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.research.models import Publication
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "title")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		pub = Publication(
			tenant_id=data["tenant_id"],
			dataset_id=data.get("dataset_id"),
			project_id=data.get("project_id"),
			title=data["title"],
			journal=data.get("journal"),
			doi=data.get("doi"),
			authors=data.get("authors", []),
			publication_date=_parse_date(data.get("publication_date")),
			abstract=data.get("abstract"),
			is_open_access=bool(data.get("is_open_access", False)),
			citation_count=int(data.get("citation_count", 0)),
			pdf_url=data.get("pdf_url"),
		)
		session.add(pub)
		session.commit()
		return jsonify({"publication_id": pub.id, "title": pub.title}), 201

	@expose("/<string:pub_id>/update-citations", methods=["POST"])
	@has_access
	def update_citations(self, pub_id: str):
		"""Action: Update citation count from external source."""
		from pgappforge.plugins.erp.industry.research.models import Publication
		from pgappforge.plugins.erp.industry.research.events import PublicationCitedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed

		session = _get_session()
		p = session.get(Publication, pub_id)
		if p is None:
			abort(404)

		data = request.get_json(force=True) or {}
		new_count = int(data.get("citation_count", p.citation_count))
		old_count = p.citation_count

		if new_count != old_count:
			p.citation_count = new_count
			_emit_typed(
				PublicationCitedEvent(
					aggregate_id=pub_id,
					aggregate_type="Publication",
					tenant_id=str(p.tenant_id),
					publication_id=pub_id,
					doi=p.doi or "",
					old_citation_count=old_count,
					new_citation_count=new_count,
				),
				session,
			)
			session.commit()

		return jsonify({
			"publication_id": pub_id,
			"old_citation_count": old_count,
			"new_citation_count": new_count,
			"changed": new_count != old_count,
		})


# ---------------------------------------------------------------------------
# PeerReviewView
# ---------------------------------------------------------------------------

class PeerReviewView(BaseView):
	"""Peer review CRUD.

	Widget hints:
	  - Select2Widget:          decision
	  - DateTimePickerWidget:   submitted_at
	  - StarRatingWidget:       review quality (implicit from decision)

	GET  /research/peer-reviews/                      — list
	GET  /research/peer-reviews/<id>                  — detail
	POST /research/peer-reviews/                      — create
	"""

	route_base = "/research/peer-reviews"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.research.models import PeerReview
		session = _get_session()
		publication_id = request.args.get("publication_id")
		decision = request.args.get("decision")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = sa.select(PeerReview).order_by(PeerReview.submitted_at.desc()).limit(limit)
		if publication_id:
			q = q.where(PeerReview.publication_id == publication_id)
		if decision:
			q = q.where(PeerReview.decision == decision)

		reviews = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"publication_id": r.publication_id,
				"review_round": r.review_round,
				"decision": r.decision,
				"submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
				"is_blind": r.is_blind,
				"reviewer_id": r.reviewer_id if not r.is_blind else None,
				"_widget_hints": {
					"decision": select2_widget(_REVIEW_DECISIONS),
					"submitted_at": datetime_widget(),
				},
			}
			for r in reviews
		])

	@expose("/<string:review_id>")
	@has_access
	def detail(self, review_id: str):
		from pgappforge.plugins.erp.industry.research.models import PeerReview
		session = _get_session()
		r = session.get(PeerReview, review_id)
		if r is None:
			abort(404, f"PeerReview {review_id!r} not found")
		return jsonify({
			"id": r.id,
			"tenant_id": r.tenant_id,
			"publication_id": r.publication_id,
			"reviewer_id": r.reviewer_id if not r.is_blind else None,
			"review_round": r.review_round,
			"decision": r.decision,
			"submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
			"comments": r.comments,
			"is_blind": r.is_blind,
			"_widget_hints": {
				"decision": select2_widget(_REVIEW_DECISIONS),
				"submitted_at": datetime_widget(),
				"comments": rich_text_widget(),
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.research.models import PeerReview
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "publication_id", "decision", "submitted_at")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		valid_decisions = {"ACCEPT", "MINOR_REVISION", "MAJOR_REVISION", "REJECT"}
		if data["decision"] not in valid_decisions:
			return jsonify({"error": f"decision must be one of {valid_decisions}"}), 400

		rev = PeerReview(
			tenant_id=data["tenant_id"],
			publication_id=data["publication_id"],
			reviewer_id=data.get("reviewer_id"),
			review_round=int(data.get("review_round", 1)),
			decision=data["decision"],
			submitted_at=_parse_dt(data["submitted_at"]) or datetime.now(timezone.utc),
			comments=data.get("comments"),
			is_blind=bool(data.get("is_blind", True)),
		)
		session.add(rev)
		session.commit()
		return jsonify({"review_id": rev.id, "decision": rev.decision}), 201


# ---------------------------------------------------------------------------
# ResearchDashboardView
# ---------------------------------------------------------------------------

class ResearchDashboardView(BaseView):
	"""Research impact dashboard at /research/dashboard/.

	Widget hints:
	  - AdvancedChartsWidget: citations by project, dataset types, open access ratio
	  - StarRatingWidget:     h-index display

	GET /research/dashboard/                          — dashboard index
	GET /research/dashboard/impact?tenant_id=<id>     — cross-project impact summary
	GET /research/dashboard/open-access?tenant_id=<id> — open access metrics
	GET /research/dashboard/recent-activity?tenant_id=<id> — recent datasets/publications
	"""

	route_base = "/research/dashboard"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		return jsonify({
			"title": "Research Data Management Dashboard",
			"description": "Impact metrics, DataCite DOI status, and open access analytics.",
			"endpoints": {
				"impact": "/research/dashboard/impact?tenant_id=<id>",
				"open_access": "/research/dashboard/open-access?tenant_id=<id>",
				"recent_activity": "/research/dashboard/recent-activity?tenant_id=<id>",
			},
			"_widget_hints": {
				"charts": chart_widget("bar"),
				"h_index": star_widget(max_rating=20, readonly=True),
			},
		})

	@expose("/impact")
	@has_access
	def impact_summary(self):
		"""Cross-project impact summary for a tenant."""
		from pgappforge.plugins.erp.industry.research.models import (
			ResearchProject, Dataset, Publication,
		)
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id query param required"}), 400

		projects = session.execute(
			sa.select(ResearchProject)
			.where(ResearchProject.tenant_id == tenant_id)
		).scalars().all()

		total_citations = session.execute(
			sa.select(sa.func.sum(Publication.citation_count))
			.where(Publication.tenant_id == tenant_id)
		).scalar_one() or 0

		published_datasets = session.execute(
			sa.select(sa.func.count(Dataset.id))
			.where(Dataset.tenant_id == tenant_id, Dataset.is_published.is_(True))
		).scalar_one() or 0

		dois_minted = session.execute(
			sa.select(sa.func.count(Dataset.id))
			.where(Dataset.tenant_id == tenant_id, Dataset.doi.isnot(None))
		).scalar_one() or 0

		# h-index across all tenant publications
		all_counts = session.execute(
			sa.select(Publication.citation_count)
			.where(Publication.tenant_id == tenant_id)
			.order_by(Publication.citation_count.desc())
		).scalars().all()
		h_index = 0
		for i, c in enumerate(all_counts, start=1):
			if (c or 0) >= i:
				h_index = i
			else:
				break

		return jsonify({
			"tenant_id": tenant_id,
			"project_count": len(projects),
			"total_citations": total_citations,
			"h_index": h_index,
			"published_datasets": published_datasets,
			"dois_minted": dois_minted,
			"_widget_hints": {
				"charts": chart_widget("bar"),
				"h_index": star_widget(max_rating=20, readonly=True),
			},
		})

	@expose("/open-access")
	@has_access
	def open_access_metrics(self):
		"""Open access publishing ratio and license breakdown."""
		from pgappforge.plugins.erp.industry.research.models import Publication, Dataset
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id query param required"}), 400

		pub_rows = session.execute(
			sa.select(
				Publication.is_open_access,
				sa.func.count(Publication.id).label("count"),
			)
			.where(Publication.tenant_id == tenant_id)
			.group_by(Publication.is_open_access)
		).all()

		oa_pub = sum(r.count for r in pub_rows if r.is_open_access)
		total_pub = sum(r.count for r in pub_rows)

		dataset_rows = session.execute(
			sa.select(
				Dataset.access_rights,
				sa.func.count(Dataset.id).label("count"),
			)
			.where(Dataset.tenant_id == tenant_id)
			.group_by(Dataset.access_rights)
		).all()

		return jsonify({
			"tenant_id": tenant_id,
			"publications": {
				"total": total_pub,
				"open_access": oa_pub,
				"open_access_ratio": round(oa_pub / total_pub, 4) if total_pub > 0 else 0.0,
			},
			"datasets_by_access_rights": {r.access_rights: r.count for r in dataset_rows},
			"_widget_hints": {"charts": chart_widget("pie")},
		})

	@expose("/recent-activity")
	@has_access
	def recent_activity(self):
		"""Recent datasets and publications for a tenant (last 30 days)."""
		from pgappforge.plugins.erp.industry.research.models import Dataset, Publication
		from datetime import timedelta
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id query param required"}), 400

		cutoff = datetime.now(timezone.utc) - timedelta(days=30)

		recent_ds = session.execute(
			sa.select(Dataset)
			.where(Dataset.tenant_id == tenant_id, Dataset.created_at >= cutoff)
			.order_by(Dataset.created_at.desc())
			.limit(10)
		).scalars().all()

		recent_pubs = session.execute(
			sa.select(Publication)
			.where(Publication.tenant_id == tenant_id, Publication.created_at >= cutoff)
			.order_by(Publication.created_at.desc())
			.limit(10)
		).scalars().all()

		return jsonify({
			"tenant_id": tenant_id,
			"recent_datasets": [
				{
					"id": d.id,
					"title": d.title,
					"doi": d.doi,
					"resource_type": d.resource_type,
					"is_published": d.is_published,
					"created_at": d.created_at.isoformat() if d.created_at else None,
				}
				for d in recent_ds
			],
			"recent_publications": [
				{
					"id": p.id,
					"title": p.title,
					"doi": p.doi,
					"citation_count": p.citation_count,
					"created_at": p.created_at.isoformat() if p.created_at else None,
				}
				for p in recent_pubs
			],
		})


__all__ = [
	"ResearchProjectView",
	"DatasetView",
	"DataProvenanceView",
	"PublicationView",
	"PeerReviewView",
	"ResearchDashboardView",
]
