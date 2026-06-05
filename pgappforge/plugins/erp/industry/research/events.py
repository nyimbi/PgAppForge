"""
pgappforge/plugins/erp/industry/research/events.py

Domain events for the Research Data Management plugin.

Events emitted:
  research.dataset.doi_minted        — DOI successfully registered with DataCite
  research.dataset.published         — dataset made publicly available
  research.project.completed         — research project reached COMPLETED status
  research.publication.cited         — citation count updated for a publication
  research.provenance.recorded       — new provenance activity logged for a dataset
"""
from __future__ import annotations

from dataclasses import dataclass, field

from pgappforge.plugins.erp.foundation.events import DomainEvent


@dataclass
class DatasetDOIMintedEvent(DomainEvent):
	"""Emitted when a DOI is successfully registered via DataCite API."""
	event_type: str = "research.dataset.doi_minted"
	dataset_id: str = ""
	doi: str = ""
	project_id: str = ""
	title: str = ""


@dataclass
class DatasetPublishedEvent(DomainEvent):
	"""Emitted when a dataset is published and made publicly accessible."""
	event_type: str = "research.dataset.published"
	dataset_id: str = ""
	doi: str = ""
	project_id: str = ""
	access_rights: str = ""
	published_at: str = ""  # ISO datetime


@dataclass
class ResearchProjectCompletedEvent(DomainEvent):
	"""Emitted when a research project transitions to COMPLETED status."""
	event_type: str = "research.project.completed"
	project_id: str = ""
	project_code: str = ""
	title: str = ""
	dataset_count: int = 0
	publication_count: int = 0


@dataclass
class PublicationCitedEvent(DomainEvent):
	"""Emitted when citation count for a publication is updated."""
	event_type: str = "research.publication.cited"
	publication_id: str = ""
	doi: str = ""
	old_citation_count: int = 0
	new_citation_count: int = 0


@dataclass
class ProvenanceRecordedEvent(DomainEvent):
	"""Emitted when a new provenance activity is recorded for a dataset."""
	event_type: str = "research.provenance.recorded"
	provenance_id: str = ""
	dataset_id: str = ""
	activity_type: str = ""
	performed_by_id: str = ""
	started_at: str = ""  # ISO datetime


__all__ = [
	"DatasetDOIMintedEvent",
	"DatasetPublishedEvent",
	"ResearchProjectCompletedEvent",
	"PublicationCitedEvent",
	"ProvenanceRecordedEvent",
]
