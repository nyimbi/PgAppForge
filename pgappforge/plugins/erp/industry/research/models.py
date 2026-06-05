"""
pgappforge/plugins/erp/industry/research/models.py

SQLAlchemy models for the Research Data Management plugin.

Design invariants:
  - ALL PKs: UUID v4 — gen_random_uuid()
  - ALL timestamps: DateTime(timezone=True) / TIMESTAMPTZ DEFAULT NOW()
  - ALL models: tenant_id UUID NOT NULL
  - DataProvenance is IMMUTABLE — insert-only audit trail
  - creator_ids, subjects, keywords, file_format: PostgreSQL ARRAY or JSONB
  - Monetary values: integer cents (budget_cents)

Table prefix: rdm_
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import sqlalchemy as sa
from sqlalchemy import (
	Boolean,
	BigInteger,
	Column,
	Date,
	DateTime,
	ForeignKey,
	Index,
	Integer,
	SmallInteger,
	String,
	Text,
	UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import relationship

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin
from pgappforge.plugins.erp.foundation.commons import ImmutableRecordMixin


def _uuid4() -> str:
	return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ResearchProject
# ---------------------------------------------------------------------------

class ResearchProject(AuditMixin, Model):
	"""Research project master record.

	Tracks the lifecycle from planning through completion.
	Links to foundation.Party for principal_investigator and institution.
	budget_cents stores budget in integer cents.

	Status flow: PLANNING → ACTIVE → ANALYSIS → WRITING → COMPLETED
	"""

	__allow_unmapped__ = True
	__tablename__ = "rdm_research_project"
	__table_args__ = (
		Index("ix_rdm_proj_tenant", "tenant_id"),
		Index("ix_rdm_proj_pi", "principal_investigator_id"),
		Index("ix_rdm_proj_status", "status"),
		UniqueConstraint("tenant_id", "project_code", name="uq_rdm_proj_tenant_code"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	project_code = Column(String(50), nullable=False, comment="Unique project code per tenant")
	title = Column(String(500), nullable=False)
	description = Column(Text, nullable=True)

	principal_investigator_id = Column(
		UUID(as_uuid=False), nullable=True, index=True,
		comment="FK to foundation.Party (principal investigator)",
	)
	institution_id = Column(
		UUID(as_uuid=False), nullable=True, index=True,
		comment="FK to foundation.Party (institution)",
	)

	funding_source = Column(String(200), nullable=True)
	grant_reference = Column(String(100), nullable=True)

	start_date = Column(Date, nullable=True)
	end_date = Column(Date, nullable=True)
	budget_cents = Column(
		Integer, nullable=False, default=0,
		comment="Project budget in integer cents",
	)

	status = Column(
		String(20),
		nullable=False,
		default="PLANNING",
		comment="PLANNING|ACTIVE|ANALYSIS|WRITING|COMPLETED",
	)

	ethical_approval_number = Column(String(100), nullable=True)
	data_management_plan_url = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __init__(self, **kwargs):
		kwargs.setdefault("status", "PLANNING")
		kwargs.setdefault("budget_cents", 0)
		super().__init__(**kwargs)

	datasets: list[Dataset] = relationship("Dataset", back_populates="project", lazy="select")
	publications: list[Publication] = relationship("Publication", back_populates="project", lazy="select")

	def __repr__(self) -> str:
		return f"<ResearchProject {self.project_code!r} status={self.status!r}>"


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------

class Dataset(AuditMixin, Model):
	"""Citable research dataset with DataCite-compatible metadata.

	doi is the registered DataCite DOI; unique when present.
	creator_ids is a JSONB array of UUID strings referencing foundation.Party.
	subjects and keywords are JSONB string arrays.
	file_format is a JSONB array of MIME type / format strings.
	metadata JSONB stores additional DataCite fields not covered by columns.

	resource_type maps to DataCite resourceTypeGeneral.
	access_rights controls visibility: OPEN/RESTRICTED/EMBARGOED/CLOSED.
	"""

	__allow_unmapped__ = True
	__tablename__ = "rdm_dataset"
	__table_args__ = (
		Index("ix_rdm_ds_tenant", "tenant_id"),
		Index("ix_rdm_ds_project", "project_id"),
		Index("ix_rdm_ds_resource_type", "resource_type"),
		Index("ix_rdm_ds_access_rights", "access_rights"),
		Index("ix_rdm_ds_published", "is_published"),
		UniqueConstraint("doi", name="uq_rdm_ds_doi"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	doi = Column(String(100), nullable=True, unique=True, comment="Registered DataCite DOI")
	title = Column(String(500), nullable=False)
	description = Column(Text, nullable=True)

	project_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rdm_research_project.id"),
		nullable=False,
		index=True,
	)

	# JSONB array of UUID strings (foundation.Party creator references)
	creator_ids = Column(
		JSONB, nullable=False, default=list,
		comment="Array of UUID strings referencing foundation.Party creators",
	)

	resource_type = Column(
		String(20),
		nullable=False,
		default="DATASET",
		comment="DATASET|SOFTWARE|IMAGE|COLLECTION|TEXT|WORKFLOW",
	)

	subjects = Column(
		JSONB, nullable=False, default=list,
		comment="Array of subject/discipline strings",
	)
	keywords = Column(
		JSONB, nullable=False, default=list,
		comment="Array of free-text keyword strings",
	)
	language = Column(String(5), nullable=False, default="en", server_default="en")
	publication_year = Column(SmallInteger, nullable=True)
	version = Column(String(20), nullable=False, default="1", server_default="1")
	license = Column(String(100), nullable=True, comment="SPDX license identifier or URL")

	access_rights = Column(
		String(20),
		nullable=False,
		default="OPEN",
		comment="OPEN|RESTRICTED|EMBARGOED|CLOSED",
	)

	storage_url = Column(Text, nullable=True)
	file_format = Column(
		JSONB, nullable=False, default=list,
		comment="Array of file format/MIME type strings",
	)
	file_size_bytes = Column(BigInteger, nullable=True)

	extra_metadata = Column(
		"metadata",
		JSONB, nullable=False, default=dict,
		comment="Additional DataCite metadata fields (geo_locations, funding_references, etc.)",
	)

	is_published = Column(Boolean, nullable=False, default=False, server_default="false")
	published_at = Column(DateTime(timezone=True), nullable=True)

	created_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __init__(self, **kwargs):
		kwargs.setdefault("creator_ids", [])
		kwargs.setdefault("subjects", [])
		kwargs.setdefault("keywords", [])
		kwargs.setdefault("file_format", [])
		kwargs.setdefault("extra_metadata", {})
		kwargs.setdefault("resource_type", "DATASET")
		kwargs.setdefault("access_rights", "OPEN")
		kwargs.setdefault("language", "en")
		kwargs.setdefault("version", "1")
		kwargs.setdefault("is_published", False)
		super().__init__(**kwargs)

	project: ResearchProject = relationship("ResearchProject", back_populates="datasets", lazy="select")
	provenance_records: list[DataProvenance] = relationship("DataProvenance", back_populates="dataset", lazy="select")
	publications: list[Publication] = relationship("Publication", back_populates="dataset", lazy="select")

	def __repr__(self) -> str:
		return f"<Dataset {self.title!r} doi={self.doi!r} access={self.access_rights!r}>"


# ---------------------------------------------------------------------------
# DataProvenance  (IMMUTABLE)
# ---------------------------------------------------------------------------

class DataProvenance(ImmutableRecordMixin, AuditMixin, Model):
	"""Immutable data provenance record (W3C PROV-compatible).

	Records every transformation, collection, processing, or analysis step
	applied to a dataset.  Rows are NEVER updated — corrections add new rows.

	inputs/outputs are JSONB arrays of {dataset_id, description} dicts.
	parameters captures processing parameters for reproducibility.
	software_used captures {name, version, url} dicts.
	"""

	__allow_unmapped__ = True
	__tablename__ = "rdm_data_provenance"
	__table_args__ = (
		Index("ix_rdm_prov_dataset", "dataset_id"),
		Index("ix_rdm_prov_tenant", "tenant_id"),
		Index("ix_rdm_prov_activity", "activity_type"),
		Index("ix_rdm_prov_performer", "performed_by_id"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	dataset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rdm_dataset.id"),
		nullable=False,
		index=True,
	)

	activity_type = Column(
		String(20),
		nullable=False,
		comment="COLLECTION|PROCESSING|TRANSFORMATION|ANALYSIS",
	)

	performed_by_id = Column(
		UUID(as_uuid=False), nullable=True, index=True,
		comment="FK to foundation.Party (person/agent performing the activity)",
	)

	started_at = Column(DateTime(timezone=True), nullable=False)
	ended_at = Column(DateTime(timezone=True), nullable=True)

	inputs = Column(
		JSONB, nullable=False, default=list,
		comment="[{dataset_id, description}] — input datasets/artifacts",
	)
	outputs = Column(
		JSONB, nullable=False, default=list,
		comment="[{dataset_id, description}] — output datasets/artifacts",
	)
	parameters = Column(
		JSONB, nullable=False, default=dict,
		comment="Processing parameters for reproducibility",
	)
	software_used = Column(
		JSONB, nullable=False, default=list,
		comment="[{name, version, url}] — software tools used",
	)
	description = Column(Text, nullable=True)

	# IMMUTABLE — no updated_at
	created_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	dataset: Dataset = relationship("Dataset", back_populates="provenance_records", lazy="select")

	def __repr__(self) -> str:
		return f"<DataProvenance dataset={self.dataset_id!r} activity={self.activity_type!r}>"


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

class Publication(AuditMixin, Model):
	"""Research publication record.

	Links to either a Dataset, a ResearchProject, or both.
	authors JSONB stores [{name, orcid, affiliation}] for full author list.
	citation_count is periodically updated from external APIs (OpenAlex, CrossRef).
	"""

	__allow_unmapped__ = True
	__tablename__ = "rdm_publication"
	__table_args__ = (
		Index("ix_rdm_pub_tenant", "tenant_id"),
		Index("ix_rdm_pub_dataset", "dataset_id"),
		Index("ix_rdm_pub_project", "project_id"),
		Index("ix_rdm_pub_open_access", "is_open_access"),
		UniqueConstraint("doi", name="uq_rdm_pub_doi"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	dataset_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rdm_dataset.id"),
		nullable=True,
		index=True,
	)
	project_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rdm_research_project.id"),
		nullable=True,
		index=True,
	)

	title = Column(String(500), nullable=False)
	journal = Column(String(300), nullable=True)
	doi = Column(String(100), nullable=True, unique=True)
	authors = Column(
		JSONB, nullable=False, default=list,
		comment="[{name, orcid, affiliation}] ordered author list",
	)
	publication_date = Column(Date, nullable=True)
	abstract = Column(Text, nullable=True)
	is_open_access = Column(Boolean, nullable=False, default=False, server_default="false")
	citation_count = Column(Integer, nullable=False, default=0, server_default="0")
	pdf_url = Column(Text, nullable=True)

	created_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __init__(self, **kwargs):
		kwargs.setdefault("authors", [])
		kwargs.setdefault("citation_count", 0)
		kwargs.setdefault("is_open_access", False)
		super().__init__(**kwargs)

	dataset: Dataset | None = relationship("Dataset", back_populates="publications", lazy="select")
	project: ResearchProject | None = relationship("ResearchProject", back_populates="publications", lazy="select")
	peer_reviews: list[PeerReview] = relationship("PeerReview", back_populates="publication", lazy="select")

	def __repr__(self) -> str:
		return f"<Publication {self.title!r} doi={self.doi!r}>"


# ---------------------------------------------------------------------------
# PeerReview
# ---------------------------------------------------------------------------

class PeerReview(AuditMixin, Model):
	"""Peer review record for a publication.

	reviewer_id is nullable to support blind review (reviewer identity concealed).
	is_blind=True means reviewer identity is not disclosed to authors.
	decision tracks the editorial decision per review round.
	"""

	__allow_unmapped__ = True
	__tablename__ = "rdm_peer_review"
	__table_args__ = (
		Index("ix_rdm_pr_publication", "publication_id"),
		Index("ix_rdm_pr_tenant", "tenant_id"),
		Index("ix_rdm_pr_reviewer", "reviewer_id"),
		Index("ix_rdm_pr_decision", "decision"),
		{"extend_existing": True},
	)

	id = Column(
		UUID(as_uuid=False),
		primary_key=True,
		default=_uuid4,
		server_default=sa.text("gen_random_uuid()"),
	)
	tenant_id = Column(UUID(as_uuid=False), nullable=False, index=True)

	publication_id = Column(
		UUID(as_uuid=False),
		ForeignKey("rdm_publication.id"),
		nullable=False,
		index=True,
	)
	reviewer_id = Column(
		UUID(as_uuid=False), nullable=True, index=True,
		comment="FK to foundation.Party; nullable for blind review",
	)

	review_round = Column(Integer, nullable=False, default=1, server_default="1")
	decision = Column(
		String(20),
		nullable=False,
		comment="ACCEPT|MINOR_REVISION|MAJOR_REVISION|REJECT",
	)
	submitted_at = Column(DateTime(timezone=True), nullable=False)
	comments = Column(Text, nullable=True)
	is_blind = Column(Boolean, nullable=False, default=True, server_default="true")

	created_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)
	updated_at = Column(
		DateTime(timezone=True), nullable=False,
		default=lambda: datetime.now(timezone.utc),
		onupdate=lambda: datetime.now(timezone.utc),
		server_default=sa.text("NOW()"),
	)

	def __init__(self, **kwargs):
		kwargs.setdefault("review_round", 1)
		kwargs.setdefault("is_blind", True)
		super().__init__(**kwargs)

	publication: Publication = relationship("Publication", back_populates="peer_reviews", lazy="select")

	def __repr__(self) -> str:
		return f"<PeerReview pub={self.publication_id!r} round={self.review_round} decision={self.decision!r}>"


# Register immutability guard after class definition
DataProvenance._register_immutability()


__all__ = [
	"ResearchProject",
	"Dataset",
	"DataProvenance",
	"Publication",
	"PeerReview",
]
