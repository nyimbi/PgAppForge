"""
PostgreSQL-specific widgets for Flask-AppBuilder.

Complete CRUD widget coverage for all PostgreSQL column types:
  JSONB, ARRAY, HSTORE, LTREE, INET, CIDR, MACADDR, UUID,
  TSVECTOR, TSQUERY, ranges (int/num/ts/date), PostGIS, pgvector.
"""

from .postgresql import (
	JSONBWidget,
	PostgreSQLArrayWidget,
	PostGISGeometryWidget,
	PgVectorWidget,
	PostgreSQLIntervalWidget,
	PostgreSQLUUIDWidget,
	PostgreSQLBitStringWidget,
)
from .tree_widget import PostgreSQLTreeWidget
from .pg_type_widgets import (
	HStoreEditorWidget,
	TreeHierarchyWidget,
	NetworkAddressWidget,
	MACAddressWidget,
	FullTextSearchWidget,
	SearchQueryWidget,
	NumericRangeWidget,
	TimestampRangeWidget,
	DateRangeWidget,
	RasterImageWidget,
	VectorSimilarityWidget,
	UUIDFieldWidget,
	PG_TYPE_WIDGET_MAP,
)

__all__ = [
	# Original widgets
	"JSONBWidget",
	"PostgreSQLArrayWidget",
	"PostGISGeometryWidget",
	"PgVectorWidget",
	"PostgreSQLIntervalWidget",
	"PostgreSQLUUIDWidget",
	"PostgreSQLBitStringWidget",
	"PostgreSQLTreeWidget",
	# New type-complete widgets
	"HStoreEditorWidget",
	"TreeHierarchyWidget",
	"NetworkAddressWidget",
	"MACAddressWidget",
	"FullTextSearchWidget",
	"SearchQueryWidget",
	"NumericRangeWidget",
	"TimestampRangeWidget",
	"DateRangeWidget",
	"RasterImageWidget",
	"VectorSimilarityWidget",
	"UUIDFieldWidget",
	"PG_TYPE_WIDGET_MAP",
]