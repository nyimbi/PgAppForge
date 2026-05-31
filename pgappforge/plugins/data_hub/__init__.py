"""Data Import/Export Hub for pgappforge.

Upload CSV/Excel/JSON/Parquet files with intelligent column mapping,
validation, and chunked async processing. Export data in any format
matching current filter state.
"""
from __future__ import annotations
import logging

log = logging.getLogger(__name__)
__all__ = ["DataHubPlugin"]


class DataHubPlugin:
	name = "data_hub"

	def initialize(self, app, appbuilder) -> None:
		log.info("DataHubPlugin initialized")

	def register_views(self, appbuilder) -> None:
		from pgappforge.plugins.data_hub.views import DataHubView
		appbuilder.add_view(DataHubView, "Data Hub", icon="fa-database", category="Tools")
