"""
tests/ci/test_research_plugin.py

CI tests for the Research Data Management plugin.

Covers:
  - Model instantiation and column defaults
  - DataProvenance immutability guard (ImmutableRecordMixin)
  - ResearchService.generate_data_management_plan (offline — no DB)
  - ResearchService.check_data_quality (offline mock)
  - ResearchService.export_datacite_xml (offline mock)
  - ResearchService.mint_doi dry_run mode
  - ResearchService.calculate_impact_metrics
  - ResearchService.track_provenance
  - Event dataclass field defaults
  - __all__ re-exports from __init__
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
	return str(uuid.uuid4())


def _mock_session(objects: list | None = None):
	"""Return a minimal MagicMock session."""
	session = MagicMock()
	objects = objects or []

	def _get(model_cls, pk):
		for obj in objects:
			if isinstance(obj, model_cls) and getattr(obj, "id", None) == pk:
				return obj
		return None

	session.get.side_effect = _get
	session.flush.return_value = None
	session.add.return_value = None
	# execute().scalars().all() → []
	session.execute.return_value.scalars.return_value.all.return_value = []
	session.execute.return_value.scalar_one.return_value = 0
	session.execute.return_value.scalar_one_or_none.return_value = None
	return session


# ---------------------------------------------------------------------------
# Model import sanity
# ---------------------------------------------------------------------------

def test_research_model_imports():
	from pgappforge.plugins.erp.industry.research.models import (
		ResearchProject, Dataset, DataProvenance, Publication, PeerReview,
	)
	assert ResearchProject.__tablename__ == "rdm_research_project"
	assert Dataset.__tablename__ == "rdm_dataset"
	assert DataProvenance.__tablename__ == "rdm_data_provenance"
	assert Publication.__tablename__ == "rdm_publication"
	assert PeerReview.__tablename__ == "rdm_peer_review"


def test_research_project_defaults():
	from pgappforge.plugins.erp.industry.research.models import ResearchProject
	p = ResearchProject(
		tenant_id=_uuid(),
		project_code="PRJ-001",
		title="Test Project",
	)
	assert p.status == "PLANNING"
	assert p.budget_cents == 0
	assert p.project_code == "PRJ-001"


def test_dataset_defaults():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	d = Dataset(
		tenant_id=_uuid(),
		project_id=_uuid(),
		title="Test Dataset",
	)
	assert d.resource_type == "DATASET"
	assert d.access_rights == "OPEN"
	assert d.language == "en"
	assert d.version == "1"
	assert d.is_published is False
	assert d.creator_ids == []
	assert d.subjects == []
	assert d.keywords == []
	assert d.file_format == []
	assert d.extra_metadata == {}


def test_data_provenance_is_immutable():
	"""DataProvenance must carry _immutable=True from ImmutableRecordMixin."""
	from pgappforge.plugins.erp.industry.research.models import DataProvenance
	assert DataProvenance._immutable is True


def test_peer_review_defaults():
	from pgappforge.plugins.erp.industry.research.models import PeerReview
	r = PeerReview(
		tenant_id=_uuid(),
		publication_id=_uuid(),
		decision="ACCEPT",
		submitted_at=datetime.now(timezone.utc),
	)
	assert r.review_round == 1
	assert r.is_blind is True


def test_publication_defaults():
	from pgappforge.plugins.erp.industry.research.models import Publication
	p = Publication(
		tenant_id=_uuid(),
		title="My Paper",
	)
	assert p.citation_count == 0
	assert p.is_open_access is False
	assert p.authors == []


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------

def test_event_defaults():
	from pgappforge.plugins.erp.industry.research.events import (
		DatasetDOIMintedEvent,
		DatasetPublishedEvent,
		ResearchProjectCompletedEvent,
		PublicationCitedEvent,
		ProvenanceRecordedEvent,
	)
	ev = DatasetDOIMintedEvent(aggregate_id="x", aggregate_type="Dataset", tenant_id="t")
	assert ev.event_type == "research.dataset.doi_minted"
	assert ev.doi == ""

	ev2 = ResearchProjectCompletedEvent(aggregate_id="x", aggregate_type="ResearchProject", tenant_id="t")
	assert ev2.dataset_count == 0
	assert ev2.publication_count == 0

	ev3 = PublicationCitedEvent(aggregate_id="x", aggregate_type="Publication", tenant_id="t")
	assert ev3.old_citation_count == 0
	assert ev3.new_citation_count == 0

	ev4 = ProvenanceRecordedEvent(aggregate_id="x", aggregate_type="DataProvenance", tenant_id="t")
	assert ev4.activity_type == ""


# ---------------------------------------------------------------------------
# Service: check_data_quality (offline mock)
# ---------------------------------------------------------------------------

def test_check_data_quality_complete_dataset():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	from pgappforge.plugins.erp.industry.research.services import ResearchService

	ds = Dataset(
		id=_uuid(),
		tenant_id=_uuid(),
		project_id=_uuid(),
		title="Complete Dataset",
		description="An abstract.",
		creator_ids=[_uuid()],
		resource_type="DATASET",
		subjects=["biology"],
		keywords=["cells"],
		language="en",
		publication_year=2024,
		version="1",
		license="CC-BY-4.0",
		access_rights="OPEN",
		storage_url="https://example.com/data.zip",
		file_format=["application/zip"],
		metadata={},
		is_published=False,
	)
	session = _mock_session([ds])
	svc = ResearchService()
	result = svc.check_data_quality(ds.id, session)

	assert result["is_publishable"] is True
	assert result["error_count"] == 0
	assert result["score"] == 100


def test_check_data_quality_minimal_dataset():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	from pgappforge.plugins.erp.industry.research.services import ResearchService

	ds = Dataset(
		id=_uuid(),
		tenant_id=_uuid(),
		project_id=_uuid(),
		title="Minimal",
		creator_ids=[],        # missing creators
		resource_type="DATASET",
		access_rights="OPEN",
		language="en",
		version="1",
		subjects=[],
		keywords=[],
		file_format=[],
		metadata={},
		is_published=False,
	)
	session = _mock_session([ds])
	svc = ResearchService()
	result = svc.check_data_quality(ds.id, session)

	assert result["error_count"] >= 1  # missing creators
	assert result["is_publishable"] is False


def test_check_data_quality_invalid_resource_type():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	from pgappforge.plugins.erp.industry.research.services import ResearchService

	ds = Dataset(
		id=_uuid(),
		tenant_id=_uuid(),
		project_id=_uuid(),
		title="Bad Type",
		creator_ids=[_uuid()],
		resource_type="INVALID_TYPE",
		access_rights="OPEN",
		language="en",
		version="1",
		subjects=[],
		keywords=[],
		file_format=[],
		metadata={},
		is_published=False,
	)
	session = _mock_session([ds])
	svc = ResearchService()
	result = svc.check_data_quality(ds.id, session)
	assert result["is_publishable"] is False
	error_fields = [i["field"] for i in result["issues"] if i["severity"] == "ERROR"]
	assert "resource_type" in error_fields


def test_check_data_quality_not_found():
	from pgappforge.plugins.erp.industry.research.services import (
		ResearchService, DatasetNotFoundError,
	)
	session = _mock_session([])
	svc = ResearchService()
	with pytest.raises(DatasetNotFoundError):
		svc.check_data_quality(_uuid(), session)


# ---------------------------------------------------------------------------
# Service: export_datacite_xml (offline mock)
# ---------------------------------------------------------------------------

def test_export_datacite_xml_structure():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	from pgappforge.plugins.erp.industry.research.services import ResearchService
	import xml.etree.ElementTree as ET

	ds = Dataset(
		id=_uuid(),
		tenant_id=_uuid(),
		project_id=_uuid(),
		title="XML Test Dataset",
		description="Abstract here.",
		creator_ids=[_uuid(), _uuid()],
		resource_type="DATASET",
		subjects=["bioinformatics"],
		keywords=["genome"],
		language="en",
		publication_year=2025,
		version="2",
		license="MIT",
		access_rights="OPEN",
		file_format=["text/csv"],
		file_size_bytes=102400,
		metadata={},
		doi="10.5281/test.12345",
		is_published=True,
	)
	session = _mock_session([ds])
	svc = ResearchService()
	xml_str = svc.export_datacite_xml(ds.id, session)

	assert "<?xml version=" in xml_str
	assert "datacite.org/schema/kernel-4" in xml_str

	root = ET.fromstring(xml_str.split("\n", 1)[1])  # strip XML declaration
	# Find title text
	titles = root.find("{http://datacite.org/schema/kernel-4}titles")
	assert titles is not None
	title_el = titles.find("{http://datacite.org/schema/kernel-4}title")
	assert title_el.text == "XML Test Dataset"

	# Creator count
	creators = root.find("{http://datacite.org/schema/kernel-4}creators")
	assert len(list(creators)) == 2

	# DOI
	id_el = root.find("{http://datacite.org/schema/kernel-4}identifier")
	assert id_el.text == "10.5281/test.12345"


def test_export_datacite_xml_not_found():
	from pgappforge.plugins.erp.industry.research.services import (
		ResearchService, DatasetNotFoundError,
	)
	session = _mock_session([])
	svc = ResearchService()
	with pytest.raises(DatasetNotFoundError):
		svc.export_datacite_xml(_uuid(), session)


# ---------------------------------------------------------------------------
# Service: mint_doi dry_run
# ---------------------------------------------------------------------------

def test_mint_doi_dry_run():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	from pgappforge.plugins.erp.industry.research.services import ResearchService

	ds = Dataset(
		id=_uuid(),
		tenant_id=_uuid(),
		project_id=_uuid(),
		title="DOI Test",
		creator_ids=[_uuid()],
		resource_type="DATASET",
		access_rights="OPEN",
		language="en",
		version="1",
		subjects=[],
		keywords=[],
		file_format=[],
		metadata={},
		is_published=False,
	)
	session = _mock_session([ds])
	svc = ResearchService()

	with patch("pgappforge.plugins.erp.foundation.commons.emit_event"):
		doi = svc.mint_doi(ds.id, session, dry_run=True)

	assert doi.startswith("10.5281/rdm.")
	assert ds.doi == doi


def test_mint_doi_already_has_doi():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	from pgappforge.plugins.erp.industry.research.services import (
		ResearchService, DOIMintError,
	)

	ds = Dataset(
		id=_uuid(),
		tenant_id=_uuid(),
		project_id=_uuid(),
		title="Has DOI",
		creator_ids=[_uuid()],
		resource_type="DATASET",
		access_rights="OPEN",
		language="en",
		version="1",
		subjects=[],
		keywords=[],
		file_format=[],
		metadata={},
		doi="10.5281/existing.123",
		is_published=True,
	)
	session = _mock_session([ds])
	svc = ResearchService()
	with pytest.raises(DOIMintError, match="already has DOI"):
		svc.mint_doi(ds.id, session, dry_run=True)


# ---------------------------------------------------------------------------
# Service: generate_data_management_plan (offline)
# ---------------------------------------------------------------------------

def test_generate_dmp_structure():
	from pgappforge.plugins.erp.industry.research.models import ResearchProject
	from pgappforge.plugins.erp.industry.research.services import ResearchService
	import sqlalchemy as sa

	proj = ResearchProject(
		id=_uuid(),
		tenant_id=_uuid(),
		project_code="DMP-001",
		title="Genomics Study",
		status="ACTIVE",
		funding_source="NSF",
		grant_reference="NSF-2024-001",
		ethical_approval_number="EA-2024-01",
	)
	session = _mock_session([proj])
	# dataset count query returns 0
	session.execute.return_value.scalar_one.return_value = 0
	session.execute.return_value.scalars.return_value.all.return_value = []

	svc = ResearchService()
	dmp = svc.generate_data_management_plan(proj.id, session)

	assert "# Data Management Plan" in dmp
	assert "Genomics Study" in dmp
	assert "DMP-001" in dmp
	assert "NSF" in dmp
	assert "EA-2024-01" in dmp
	assert "DataCite" in dmp
	assert "3-2-1" in dmp


def test_generate_dmp_not_found():
	from pgappforge.plugins.erp.industry.research.services import (
		ResearchService, ProjectNotFoundError,
	)
	session = _mock_session([])
	svc = ResearchService()
	with pytest.raises(ProjectNotFoundError):
		svc.generate_data_management_plan(_uuid(), session)


# ---------------------------------------------------------------------------
# Service: track_provenance
# ---------------------------------------------------------------------------

def test_track_provenance_records_activity():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	from pgappforge.plugins.erp.industry.research.services import ResearchService

	dataset_id = _uuid()
	ds = Dataset(
		id=dataset_id,
		tenant_id=_uuid(),
		project_id=_uuid(),
		title="Prov Dataset",
		creator_ids=[],
		resource_type="DATASET",
		access_rights="OPEN",
		language="en",
		version="1",
		subjects=[],
		keywords=[],
		file_format=[],
		metadata={},
		is_published=False,
	)
	session = _mock_session([ds])

	added_objects = []
	session.add.side_effect = lambda obj: added_objects.append(obj)

	svc = ResearchService()
	with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
		prov = svc.track_provenance(
			dataset_id=dataset_id,
			activity_type="PROCESSING",
			details={
				"inputs": [{"dataset_id": dataset_id, "description": "raw data"}],
				"outputs": [],
				"parameters": {"tool": "pandas", "version": "2.0"},
				"software_used": [{"name": "pandas", "version": "2.0", "url": ""}],
				"description": "Cleaned and normalised raw data",
			},
			session=session,
			performed_by_id=_uuid(),
		)

	assert prov.activity_type == "PROCESSING"
	assert prov.dataset_id == dataset_id
	assert prov.parameters == {"tool": "pandas", "version": "2.0"}


def test_track_provenance_invalid_activity_type():
	from pgappforge.plugins.erp.industry.research.models import Dataset
	from pgappforge.plugins.erp.industry.research.services import (
		ResearchService, ResearchError,
	)

	dataset_id = _uuid()
	ds = Dataset(
		id=dataset_id, tenant_id=_uuid(), project_id=_uuid(),
		title="T", creator_ids=[], resource_type="DATASET",
		access_rights="OPEN", language="en", version="1",
		subjects=[], keywords=[], file_format=[], metadata={}, is_published=False,
	)
	session = _mock_session([ds])
	svc = ResearchService()
	with pytest.raises(ResearchError, match="activity_type must be one of"):
		svc.track_provenance(dataset_id, "INVALID", {}, session)


# ---------------------------------------------------------------------------
# Service: calculate_impact_metrics
# ---------------------------------------------------------------------------

def test_calculate_impact_metrics_empty():
	from pgappforge.plugins.erp.industry.research.models import ResearchProject
	from pgappforge.plugins.erp.industry.research.services import ResearchService

	proj = ResearchProject(
		id=_uuid(), tenant_id=_uuid(),
		project_code="IMP-001", title="Empty Project", status="ACTIVE",
		budget_cents=0,
	)
	session = _mock_session([proj])
	session.execute.return_value.scalars.return_value.all.return_value = []
	session.execute.return_value.scalar_one.return_value = 0

	svc = ResearchService()
	result = svc.calculate_impact_metrics(proj.id, session)

	assert result["metrics"]["h_index"] == 0
	assert result["metrics"]["total_citations"] == 0
	assert result["metrics"]["dataset_count"] == 0


# ---------------------------------------------------------------------------
# __init__ re-exports
# ---------------------------------------------------------------------------

def test_init_all_exports():
	import pgappforge.plugins.erp.industry.research as pkg
	for name in pkg.__all__:
		assert hasattr(pkg, name), f"__all__ exports {name!r} but it is not present"
