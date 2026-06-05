"""
pgappforge/plugins/erp/industry/research/__init__.py

ResearchPlugin — Research Data Management ERP plugin.

Provides:
  - ResearchProject    (project lifecycle: PLANNING → ACTIVE → ANALYSIS → WRITING → COMPLETED)
  - Dataset            (DataCite 4.4 metadata, DOI minting, access rights, versioning)
  - DataProvenance     (W3C PROV-compatible immutable audit trail)
  - Publication        (journal papers, preprints, citation tracking)
  - PeerReview         (blind/open review rounds per publication)

Business rules enforced:
  - DataProvenance rows are NEVER updated (immutable audit trail)
  - DOI minting calls DataCite REST API; dry_run mode available for staging
  - Datasets require quality check (check_data_quality) before DOI minting
  - EMBARGOED datasets cannot be published until embargo lifted

Events emitted:
  research.dataset.doi_minted
  research.dataset.published
  research.project.completed
  research.publication.cited
  research.provenance.recorded

Events consumed:
  (none — research plugin is currently event-source only)

Usage
-----
    PGAPPFORGE_PLUGINS = [
        "pgappforge.plugins.erp.foundation",
        "pgappforge.plugins.erp.industry.research",
    ]
"""
from __future__ import annotations

import logging
from typing import Any

from pgappforge.plugins.base_plugin import BasePlugin, PluginMetadata, PluginPriority

log = logging.getLogger(__name__)


class ResearchPlugin(BasePlugin):
	"""Research Data Management ERP plugin.

	Class-level routing metadata:
	    name       = "research"
	    domain     = "industry"
	    depends_on = ["foundation"]
	"""

	name = "research"
	domain = "industry"
	depends_on: list[str] = ["foundation"]

	# ------------------------------------------------------------------
	# BasePlugin.metadata
	# ------------------------------------------------------------------

	@property
	def metadata(self) -> PluginMetadata:
		return PluginMetadata(
			name="research",
			version="1.0.0",
			description=(
				"Research Data Management — DataCite 4.4 DOI minting, W3C PROV "
				"provenance tracking, data quality validation, DMP generation, "
				"impact metrics (h-index, citation counts), and peer review workflows."
			),
			author="PgAppForge Contributors",
			tags=["erp", "industry", "research", "datacite", "doi", "provenance", "rdm"],
			priority=PluginPriority.NORMAL,
			permissions=[
				"can_rdm_project_read",
				"can_rdm_project_write",
				"can_rdm_project_complete",
				"can_rdm_dataset_read",
				"can_rdm_dataset_write",
				"can_rdm_dataset_publish",
				"can_rdm_doi_mint",
				"can_rdm_provenance_read",
				"can_rdm_provenance_write",
				"can_rdm_publication_read",
				"can_rdm_publication_write",
				"can_rdm_peer_review_read",
				"can_rdm_peer_review_write",
				"can_rdm_dashboard",
				"can_rdm_reports",
			],
			safe_mode_compatible=True,
		)

	# ------------------------------------------------------------------
	# ERP plugin contract
	# ------------------------------------------------------------------

	def get_events(self) -> list[str]:
		"""Events this plugin emits."""
		return [
			"research.dataset.doi_minted",
			"research.dataset.published",
			"research.project.completed",
			"research.publication.cited",
			"research.provenance.recorded",
		]

	def subscribe_to(self) -> list[str]:
		"""Events this plugin consumes."""
		return []

	# ------------------------------------------------------------------
	# Lifecycle
	# ------------------------------------------------------------------

	def initialize(self) -> None:
		defaults: dict[str, Any] = {
			"RDM_MENU_CATEGORY": "Research Data",
			"DATACITE_API_URL": "https://api.datacite.org",
			"DATACITE_USERNAME": "",
			"DATACITE_PASSWORD": "",
			"DATACITE_DOI_PREFIX": "10.5281",
			"RDM_DOI_DRY_RUN": False,
		}
		self.config = {**defaults, **self.config}
		log.info("ResearchPlugin initialised (config keys: %s)", list(self.config))

	def register_views(self) -> None:
		"""Register Research Data Management views under the configured menu category."""
		from pgappforge.plugins.erp.industry.research.views import (
			ResearchProjectView,
			DatasetView,
			DataProvenanceView,
			PublicationView,
			PeerReviewView,
			ResearchDashboardView,
		)

		cat = self.config.get("RDM_MENU_CATEGORY", "Research Data")

		self.add_view(
			ResearchProjectView,
			"Research Projects",
			icon="fa-flask",
			category=cat,
		)
		self.add_view(
			DatasetView,
			"Datasets",
			icon="fa-database",
			category=cat,
		)
		self.add_view(
			DataProvenanceView,
			"Data Provenance",
			icon="fa-history",
			category=cat,
		)
		self.add_view(
			PublicationView,
			"Publications",
			icon="fa-file-text-o",
			category=cat,
		)
		self.add_view(
			PeerReviewView,
			"Peer Reviews",
			icon="fa-comments",
			category=cat,
		)
		self.add_view(
			ResearchDashboardView,
			"Research Dashboard",
			icon="fa-bar-chart",
			category=cat,
		)

		log.info("ResearchPlugin: views registered under category %r", cat)

	def register_models(self) -> list:
		"""Model classes for Alembic autogenerate discovery."""
		from pgappforge.plugins.erp.industry.research.models import (
			ResearchProject,
			Dataset,
			DataProvenance,
			Publication,
			PeerReview,
		)
		return [ResearchProject, Dataset, DataProvenance, Publication, PeerReview]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_plugin(
	appbuilder: Any,
	config: dict[str, Any] | None = None,
) -> ResearchPlugin:
	return ResearchPlugin(appbuilder, config=config or {})


# ---------------------------------------------------------------------------
# Public API re-exports
# ---------------------------------------------------------------------------

from pgappforge.plugins.erp.industry.research.models import (  # noqa: E402
	ResearchProject,
	Dataset,
	DataProvenance,
	Publication,
	PeerReview,
)
from pgappforge.plugins.erp.industry.research.events import (  # noqa: E402
	DatasetDOIMintedEvent,
	DatasetPublishedEvent,
	ResearchProjectCompletedEvent,
	PublicationCitedEvent,
	ProvenanceRecordedEvent,
)
from pgappforge.plugins.erp.industry.research.services import (  # noqa: E402
	ResearchService,
	ResearchError,
	ProjectNotFoundError,
	DatasetNotFoundError,
	DOIMintError,
	PublicationNotFoundError,
	ImmutableProvenanceError,
)

__all__ = [
	# plugin
	"ResearchPlugin",
	"create_plugin",
	# models
	"ResearchProject",
	"Dataset",
	"DataProvenance",
	"Publication",
	"PeerReview",
	# events
	"DatasetDOIMintedEvent",
	"DatasetPublishedEvent",
	"ResearchProjectCompletedEvent",
	"PublicationCitedEvent",
	"ProvenanceRecordedEvent",
	# services
	"ResearchService",
	"ResearchError",
	"ProjectNotFoundError",
	"DatasetNotFoundError",
	"DOIMintError",
	"PublicationNotFoundError",
	"ImmutableProvenanceError",
]
