"""
PostgreSQL dialect type detection tests for EnhancedDatabaseInspector.

Exercises _categorize_column and _suggest_widget_type for every PG-specific
type in the ColumnType enum — no live DB required.
"""

import pytest
from unittest import mock
from sqlalchemy import types as sa_types

from pgappforge.cli.generators.database_inspector import (
	EnhancedDatabaseInspector,
	ColumnType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_inspector() -> EnhancedDatabaseInspector:
	"""Return a bare EnhancedDatabaseInspector with no DB connection."""
	with mock.patch.object(EnhancedDatabaseInspector, '__init__', return_value=None):
		insp = EnhancedDatabaseInspector.__new__(EnhancedDatabaseInspector)
	insp._association_tables = set()
	return insp


def make_pg_col(
	type_str: str,
	primary_key: bool = False,
	foreign_keys=None,
	nullable: bool = True,
	col_name: str = "test_col",
) -> mock.MagicMock:
	"""
	Create a mock SQLAlchemy Column whose str(col.type) returns *type_str*.

	The mock type object also has length/precision/scale set to None so that
	_suggest_widget_type doesn't blow up on attribute access.
	"""
	col = mock.MagicMock()
	col.name = col_name
	col.primary_key = primary_key
	col.foreign_keys = foreign_keys if foreign_keys is not None else set()
	col.nullable = nullable
	col.autoincrement = False
	col.default = None
	col.unique = False

	mock_type = mock.MagicMock()
	mock_type.__str__ = mock.Mock(return_value=type_str)
	mock_type.__class__.__name__ = type_str
	# Prevent TypeError in length/precision comparisons
	mock_type.length = None
	mock_type.precision = None
	mock_type.scale = None
	col.type = mock_type
	return col


# Singleton inspector reused across all tests
_INSPECTOR = _make_inspector()


def categorize(type_str: str, **kwargs) -> ColumnType:
	col = make_pg_col(type_str, **kwargs)
	return _INSPECTOR._categorize_column(col, "test_table")


def widget(type_str: str, col_name: str = "test_col") -> str:
	col = make_pg_col(type_str, col_name=col_name)
	cat = _INSPECTOR._categorize_column(col, "test_table")
	return _INSPECTOR._suggest_widget_type(col, cat)


# ---------------------------------------------------------------------------
# TestColumnTypeCategorization
# ---------------------------------------------------------------------------

class TestColumnTypeCategorization:
	"""One test per ColumnType value touched by _categorize_column."""

	# --- primary / foreign key -------------------------------------------------

	def test_primary_key(self):
		assert categorize("INTEGER", primary_key=True) == ColumnType.PRIMARY_KEY

	def test_foreign_key(self):
		fk = mock.MagicMock()
		assert categorize("INTEGER", foreign_keys={fk}) == ColumnType.FOREIGN_KEY

	# --- ARRAY -----------------------------------------------------------------

	def test_array_bracket_notation(self):
		"""SQLAlchemy reflects PG arrays as 'INTEGER[]' / 'VARCHAR[]' — bracket notation triggers ARRAY."""
		assert categorize("INTEGER[]") == ColumnType.ARRAY

	def test_array_inet_bracket(self):
		assert categorize("INET[]") == ColumnType.ARRAY

	# --- UUID ------------------------------------------------------------------

	def test_uuid(self):
		assert categorize("UUID") == ColumnType.UUID

	def test_uuid_lower(self):
		assert categorize("uuid") == ColumnType.UUID

	# --- JSON / JSONB ----------------------------------------------------------

	def test_jsonb(self):
		assert categorize("JSONB") == ColumnType.JSONB

	def test_jsonb_not_json(self):
		assert categorize("JSONB") != ColumnType.JSON

	def test_json(self):
		assert categorize("JSON") == ColumnType.JSON

	def test_json_not_jsonb(self):
		assert categorize("JSON") != ColumnType.JSONB

	# --- PostgreSQL advanced ---------------------------------------------------

	def test_hstore(self):
		assert categorize("HSTORE") == ColumnType.HSTORE

	def test_ltree(self):
		assert categorize("LTREE") == ColumnType.LTREE

	def test_inet(self):
		assert categorize("INET") == ColumnType.INET

	def test_cidr(self):
		assert categorize("CIDR") == ColumnType.CIDR

	def test_macaddr(self):
		assert categorize("MACADDR") == ColumnType.MACADDR

	def test_tsvector(self):
		assert categorize("TSVECTOR") == ColumnType.TSVECTOR

	def test_tsquery(self):
		assert categorize("TSQUERY") == ColumnType.TSQUERY

	# --- PostGIS ---------------------------------------------------------------

	def test_geometry_bare(self):
		assert categorize("GEOMETRY") == ColumnType.GEOMETRY

	def test_geometry_with_params(self):
		assert categorize("GEOMETRY(Point,4326)") == ColumnType.GEOMETRY

	def test_geography(self):
		assert categorize("GEOGRAPHY") == ColumnType.GEOGRAPHY

	def test_raster(self):
		assert categorize("RASTER") == ColumnType.RASTER

	# --- pgVector --------------------------------------------------------------

	def test_vector(self):
		assert categorize("VECTOR(1536)") == ColumnType.VECTOR

	def test_vector_bare(self):
		assert categorize("VECTOR") == ColumnType.VECTOR

	# --- Range types -----------------------------------------------------------

	def test_int4range(self):
		assert categorize("INT4RANGE") == ColumnType.INT4RANGE

	def test_int8range(self):
		assert categorize("INT8RANGE") == ColumnType.INT8RANGE

	def test_numrange(self):
		assert categorize("NUMRANGE") == ColumnType.NUMRANGE

	def test_tsrange(self):
		assert categorize("TSRANGE") == ColumnType.TSRANGE

	def test_tstzrange(self):
		assert categorize("TSTZRANGE") == ColumnType.TSTZRANGE

	def test_daterange(self):
		assert categorize("DATERANGE") == ColumnType.DATERANGE

	# --- Multirange types (PG14+) ---------------------------------------------

	def test_int4multirange(self):
		assert categorize("INT4MULTIRANGE") == ColumnType.INT4MULTIRANGE

	def test_int8multirange(self):
		assert categorize("INT8MULTIRANGE") == ColumnType.INT8MULTIRANGE

	def test_nummultirange(self):
		assert categorize("NUMMULTIRANGE") == ColumnType.NUMMULTIRANGE

	def test_tsmultirange(self):
		assert categorize("TSMULTIRANGE") == ColumnType.TSMULTIRANGE

	def test_tstzmultirange(self):
		assert categorize("TSTZMULTIRANGE") == ColumnType.TSTZMULTIRANGE

	def test_datemultirange(self):
		assert categorize("DATEMULTIRANGE") == ColumnType.DATEMULTIRANGE

	# --- Other PG types -------------------------------------------------------

	def test_interval(self):
		assert categorize("INTERVAL") == ColumnType.INTERVAL

	def test_money(self):
		assert categorize("MONEY") == ColumnType.MONEY

	def test_bit_bare(self):
		assert categorize("BIT") == ColumnType.BIT

	def test_bit_with_size(self):
		assert categorize("BIT(8)") == ColumnType.BIT

	def test_bit_varying(self):
		assert categorize("BIT VARYING(64)") == ColumnType.BIT

	def test_xml(self):
		assert categorize("XML") == ColumnType.XML

	# --- Native PG geometric types -------------------------------------------

	def test_point(self):
		assert categorize("POINT") == ColumnType.POINT

	def test_line(self):
		assert categorize("LINE") == ColumnType.LINE

	def test_lseg(self):
		assert categorize("LSEG") == ColumnType.LSEG

	def test_box(self):
		assert categorize("BOX") == ColumnType.BOX

	def test_path(self):
		assert categorize("PATH") == ColumnType.PATH

	def test_polygon(self):
		assert categorize("POLYGON") == ColumnType.POLYGON

	def test_circle(self):
		assert categorize("CIRCLE") == ColumnType.CIRCLE


# ---------------------------------------------------------------------------
# TestCriticalOrderingBugs
# ---------------------------------------------------------------------------

class TestCriticalOrderingBugs:
	"""Regression tests for substring-collision ordering bugs."""

	def test_tstzrange_not_misclassified_as_tsrange(self):
		"""CRITICAL: tstzrange must return TSTZRANGE, not TSRANGE.

		Before the fix, 'tsrange' in 'tstzrange' = True caused tstzrange to be
		classified as TSRANGE (dead code path for TSTZRANGE).
		"""
		result = categorize("TSTZRANGE")
		assert result == ColumnType.TSTZRANGE, (
			f"Got {result} — tstzrange ordering bug not fixed"
		)
		assert result != ColumnType.TSRANGE

	def test_int4multirange_not_misclassified_as_int4range(self):
		"""CRITICAL: int4multirange must return INT4MULTIRANGE, not INT4RANGE.

		'int4range' is a substring of 'int4multirange', so range check must come
		after multirange check.
		"""
		result = categorize("INT4MULTIRANGE")
		assert result == ColumnType.INT4MULTIRANGE
		assert result != ColumnType.INT4RANGE

	def test_tsrange_still_works_after_tstzrange_fix(self):
		"""Fixing tstzrange ordering must not break tsrange detection."""
		result = categorize("TSRANGE")
		assert result == ColumnType.TSRANGE

	def test_tstzmultirange_not_misclassified_as_tsmultirange(self):
		"""tstzmultirange must come before tsmultirange in detection order."""
		result = categorize("TSTZMULTIRANGE")
		assert result == ColumnType.TSTZMULTIRANGE
		assert result != ColumnType.TSMULTIRANGE

	def test_int8multirange_not_misclassified_as_int8range(self):
		result = categorize("INT8MULTIRANGE")
		assert result == ColumnType.INT8MULTIRANGE
		assert result != ColumnType.INT8RANGE

	def test_jsonb_not_misclassified_as_json(self):
		"""'json' ⊂ 'jsonb' — JSONB check must precede JSON check."""
		result = categorize("JSONB")
		assert result == ColumnType.JSONB
		assert result != ColumnType.JSON

	def test_geometry_not_misclassified_as_geography(self):
		"""'geometry' must not match geography check."""
		result = categorize("GEOMETRY")
		assert result == ColumnType.GEOMETRY
		assert result != ColumnType.GEOGRAPHY

	def test_lseg_not_misclassified_as_line(self):
		"""'lseg' does not contain 'line', but verify explicit ordering holds."""
		result = categorize("LSEG")
		assert result == ColumnType.LSEG
		assert result != ColumnType.LINE

	def test_tsvector_not_misclassified_as_tsquery(self):
		result = categorize("TSVECTOR")
		assert result == ColumnType.TSVECTOR
		assert result != ColumnType.TSQUERY

	def test_numrange_not_misclassified_as_nummultirange(self):
		"""numrange is NOT a substring of nummultirange, but test for symmetry."""
		result = categorize("NUMRANGE")
		assert result == ColumnType.NUMRANGE
		assert result != ColumnType.NUMMULTIRANGE


# ---------------------------------------------------------------------------
# TestGeneratedColumnDetection
# ---------------------------------------------------------------------------

class TestGeneratedColumnDetection:
	"""Tests for _analyze_column handling of generated/computed columns."""

	def _make_full_inspector(self):
		"""Inspector with a stub SQLAlchemy inspector (for get_columns)."""
		insp = _make_inspector()
		insp._inspector = mock.MagicMock()
		insp._inspector.get_unique_constraints.return_value = []
		return insp

	def test_generated_column_detected(self):
		"""GENERATED ALWAYS AS (expr) STORED columns set is_generated=True."""
		insp = self._make_full_inspector()
		col = make_pg_col("NUMERIC")
		col_meta = {
			"test_col": {
				"computed": {"sqltext": "price * quantity", "persisted": True},
				"comment": None,
				"default": None,
			}
		}
		result = insp._analyze_column(col, "test_table", col_meta, set())
		assert result.is_generated is True
		assert result.generated_expression == "price * quantity"

	def test_non_generated_column(self):
		"""Regular columns have is_generated=False."""
		insp = self._make_full_inspector()
		col = make_pg_col("INTEGER")
		col_meta = {
			"test_col": {
				"computed": {},
				"comment": None,
				"default": None,
			}
		}
		result = insp._analyze_column(col, "test_table", col_meta, set())
		assert result.is_generated is False
		assert result.generated_expression == ""

	def test_generated_column_none_computed(self):
		"""computed=None (absent key) also gives is_generated=False."""
		insp = self._make_full_inspector()
		col = make_pg_col("TEXT")
		col_meta = {
			"test_col": {
				"comment": None,
				"default": None,
			}
		}
		result = insp._analyze_column(col, "test_table", col_meta, set())
		assert result.is_generated is False

	def test_server_default_extracted(self):
		"""server_default is extracted from column_data['default']."""
		insp = self._make_full_inspector()
		col = make_pg_col("UUID", col_name="test_col")
		col_meta = {
			"test_col": {
				"default": "gen_random_uuid()",
				"comment": None,
				"computed": {},
			}
		}
		result = insp._analyze_column(col, "test_table", col_meta, set())
		assert result.server_default == "gen_random_uuid()"

	def test_server_default_none_becomes_empty_string(self):
		insp = self._make_full_inspector()
		col = make_pg_col("INTEGER")
		col_meta = {
			"test_col": {"default": None, "comment": None, "computed": {}}
		}
		result = insp._analyze_column(col, "test_table", col_meta, set())
		assert result.server_default == ""

	def test_server_default_non_string_coerced(self):
		"""Non-string defaults (e.g. integer 0) are coerced to str."""
		insp = self._make_full_inspector()
		col = make_pg_col("INTEGER")
		col_meta = {
			"test_col": {"default": 0, "comment": None, "computed": {}}
		}
		result = insp._analyze_column(col, "test_table", col_meta, set())
		assert result.server_default == "0"


# ---------------------------------------------------------------------------
# TestWidgetTypeMapping
# ---------------------------------------------------------------------------

class TestWidgetTypeMapping:
	"""Verify _suggest_widget_type returns the correct widget for new PG types."""

	def test_interval_widget(self):
		assert widget("INTERVAL") == "DurationWidget"

	def test_money_widget(self):
		assert widget("MONEY") == "CurrencyWidget"

	def test_xml_widget(self):
		assert widget("XML") == "CodeEditorWidget"

	def test_point_widget(self):
		assert widget("POINT") == "MapWidget"

	def test_line_widget(self):
		assert widget("LINE") == "MapWidget"

	def test_lseg_widget(self):
		assert widget("LSEG") == "MapWidget"

	def test_box_widget(self):
		assert widget("BOX") == "MapWidget"

	def test_path_widget(self):
		assert widget("PATH") == "MapWidget"

	def test_polygon_widget(self):
		assert widget("POLYGON") == "MapWidget"

	def test_circle_widget(self):
		assert widget("CIRCLE") == "MapWidget"

	def test_int4multirange_widget(self):
		assert widget("INT4MULTIRANGE") == "NumericRangeWidget"

	def test_int8multirange_widget(self):
		assert widget("INT8MULTIRANGE") == "NumericRangeWidget"

	def test_nummultirange_widget(self):
		assert widget("NUMMULTIRANGE") == "NumericRangeWidget"

	def test_tsmultirange_widget(self):
		assert widget("TSMULTIRANGE") == "TimestampRangeWidget"

	def test_tstzmultirange_widget(self):
		assert widget("TSTZMULTIRANGE") == "TimestampRangeWidget"

	def test_datemultirange_widget(self):
		assert widget("DATEMULTIRANGE") == "DateRangeWidget"

	# Spot-check pre-existing range widgets still work
	def test_int4range_widget(self):
		assert widget("INT4RANGE") == "NumericRangeWidget"

	def test_tstzrange_widget(self):
		assert widget("TSTZRANGE") == "TimestampRangeWidget"

	def test_daterange_widget(self):
		assert widget("DATERANGE") == "DateRangeWidget"

	# Other PG widgets
	def test_jsonb_widget(self):
		assert widget("JSONB") == "JSONEditorWidget"

	def test_hstore_widget(self):
		assert widget("HSTORE") == "HStoreEditorWidget"

	def test_inet_widget(self):
		assert widget("INET") == "NetworkAddressWidget"

	def test_cidr_widget(self):
		assert widget("CIDR") == "NetworkAddressWidget"

	def test_tsvector_widget(self):
		assert widget("TSVECTOR") == "FullTextSearchWidget"

	def test_vector_widget(self):
		assert widget("VECTOR(1536)") == "EmbeddingWidget"

	def test_geometry_widget(self):
		assert widget("GEOMETRY(Point,4326)") == "PostGISMapWidget"

	def test_geography_widget(self):
		assert widget("GEOGRAPHY") == "PostGISMapWidget"
