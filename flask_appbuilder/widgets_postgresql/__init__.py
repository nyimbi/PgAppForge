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


from .postgis_h3_widgets import (
	H3IndexWidget,
	H3ArrayWidget,
	H3IndexType,
	PostGISWidget,
	PostGISGeographyWidget,
	POSTGIS_GEOMETRY_TYPES,
	POSTGIS_GEOGRAPHY_TYPES,
	H3_TYPES,
	POSTGIS_H3_WIDGET_MAP,
)
from .pgvector_widgets import (
	VectorType,
	EmbeddingWidget,
	VectorDisplayWidget,
	SimilaritySearchWidget,
	PGVECTOR_WIDGET_MAP,
)
__all__ = [
	# PostGIS + H3
	"H3IndexWidget",
	"H3ArrayWidget",
	"H3IndexType",
	"PostGISWidget",
	"PostGISGeographyWidget",
	"POSTGIS_GEOMETRY_TYPES",
	"H3_TYPES",
	"POSTGIS_H3_WIDGET_MAP",
	# pgvector
	"VectorType",
	"EmbeddingWidget",
	"VectorDisplayWidget",
	"SimilaritySearchWidget",
	"PGVECTOR_WIDGET_MAP",

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