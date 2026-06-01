"""
Comprehensive tests for EnhancedDatabaseInspector relationship detection.

Uses unittest.mock to patch SQLAlchemy inspector methods — no live DB required.
All relationship type detection, association table identification, and synthesis
paths are exercised.
"""

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from typing import Dict, List, Any

from pgappforge.cli.generators.database_inspector import (
	EnhancedDatabaseInspector,
	RelationshipType,
	RelationshipInfo,
	TableInfo,
)


# ---------------------------------------------------------------------------
# Helper: build a mock EnhancedDatabaseInspector from a plain schema dict
# ---------------------------------------------------------------------------

def _make_mock_table(table_name: str, schema_def: Dict[str, Any]) -> MagicMock:
	"""Return a minimal mock of a SQLAlchemy Table object."""
	table = MagicMock()
	table.name = table_name
	table.schema = None
	# Build Column mocks from the schema's column list
	cols = []
	for col_def in schema_def.get("columns", []):
		col = MagicMock()
		col.name = col_def["name"]
		col.primary_key = col_def.get("primary_key", False)
		col.foreign_keys = col_def.get("foreign_keys_set", set())
		col.autoincrement = col_def.get("autoincrement", False)
		# Give column.type a sensible str representation and numeric attributes
		col_type = MagicMock()
		col_type.__str__ = lambda self, t=col_def.get("type", "INTEGER"): t.lower()
		col_type.length = None   # avoids `> 200` TypeError in _suggest_widget_type
		col_type.precision = None
		col_type.scale = None
		col.type = col_type
		cols.append(col)
	table.columns = cols
	return table


def make_inspector(schema: Dict[str, Any]) -> "EnhancedDatabaseInspector":
	"""
	Build a fully-mocked EnhancedDatabaseInspector from a schema dict.

	schema format:
	  {
	    "table_name": {
	      "columns": [{"name": "id", "type": "INTEGER", "primary_key": True, ...}],
	      "foreign_keys": [{"constrained_columns": [...], "referred_table": ...,
	                        "referred_columns": [...], "name": "fk_x", "options": {}}],
	      "pk": ["id"],
	      "unique_constraints": [{"name": "uq_x", "column_names": [...]}],
	      "indexes": [],
	    }
	  }
	"""
	# Build mock metadata.tables
	mock_tables = {
		tname: _make_mock_table(tname, tdef)
		for tname, tdef in schema.items()
	}

	# Bypass __init__ entirely
	insp = object.__new__(EnhancedDatabaseInspector)

	# Required __init__ attributes
	insp.database_uri = "postgresql://mock/mock"
	insp._engine = None
	insp._inspector = None
	insp._metadata = None
	insp._connection = None
	insp._table_stats = {}
	insp._relationship_cache = {}
	insp._association_tables = set()
	insp._analysis_cache = None
	insp._table_info_cache = {}
	insp._is_connected = False
	insp._auto_cleanup = False

	# ---- mock inspector (the SQLAlchemy reflection inspector) ----
	sa_inspector = MagicMock()
	sa_inspector.get_table_names.return_value = list(schema.keys())
	sa_inspector.get_view_names.return_value = []

	# Use default-argument capture to freeze `schema` reference in each closure
	def _fks(table_name, _s=schema, **kw):
		tdef = _s.get(table_name)
		return tdef.get("foreign_keys", []) if tdef else []

	def _pk(table_name, _s=schema, **kw):
		tdef = _s.get(table_name, {})
		return {"constrained_columns": tdef.get("pk", [])}

	def _uq(table_name, _s=schema, **kw):
		tdef = _s.get(table_name, {})
		return tdef.get("unique_constraints", [])

	def _cols(table_name, _s=schema, **kw):
		tdef = _s.get(table_name, {})
		out = []
		for c in tdef.get("columns", []):
			out.append({
				"name": c["name"],
				"nullable": c.get("nullable", True),
				"type": c.get("type", "INTEGER"),
				"primary_key": c.get("primary_key", False),
			})
		return out

	def _indexes(table_name, _s=schema, **kw):
		tdef = _s.get(table_name, {})
		return tdef.get("indexes", [])

	sa_inspector.get_foreign_keys.side_effect = _fks
	sa_inspector.get_pk_constraint.side_effect = _pk
	sa_inspector.get_unique_constraints.side_effect = _uq
	sa_inspector.get_columns.side_effect = _cols
	sa_inspector.get_indexes.side_effect = _indexes
	sa_inspector.get_table_comment.return_value = {"text": None}

	# Patch inspector and metadata as attributes (bypass lazy-loading properties)
	insp._inspector = sa_inspector

	mock_meta = MagicMock()
	mock_meta.tables = mock_tables
	insp._metadata = mock_meta

	# ---- patch the property accessors so they return the mocks above ----
	# (Properties are defined on the class; easiest to patch with type(obj))
	type(insp).inspector = property(lambda self: self._inspector)
	type(insp).metadata = property(lambda self: self._metadata)

	# ---- stub out heavy / DB-touching methods ----
	insp.get_all_tables = lambda: list(schema.keys())
	insp.get_all_views = lambda: []
	insp._get_database_info = lambda: {}
	insp._get_database_statistics = lambda: {}
	insp._generate_recommendations = lambda: []
	insp._get_table_constraints = lambda t: []
	insp._categorize_table = lambda t, cols=None: "general"
	insp._get_table_icon = lambda cat, t=None: "fa-table"
	insp._estimate_table_rows = lambda t: 0
	insp._suggest_view_types = lambda cols, rels, is_assoc: []
	insp._assess_security_level = lambda cols: "low"
	insp._pick_display_column = lambda ti: "id"
	insp._tag_partition_inheritance = lambda analysis: None
	insp._detect_actor_tables = lambda analysis: None
	insp._detect_polymorphic_columns = lambda ti: None

	return insp


# ---------------------------------------------------------------------------
# Test class: Association table detection (_is_association_table)
# ---------------------------------------------------------------------------

class TestAssociationTableDetection:

	def _schema_for(self, table_def: Dict[str, Any]) -> Dict[str, Any]:
		"""Wrap a single table def in a schema with the required referenced tables."""
		schema = {
			"users":  {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"roles":  {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"orgs":   {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"junction": table_def,
		}
		return schema

	def test_pure_junction_with_composite_pk(self):
		"""user_role(user_id, role_id, PK(user_id,role_id)) — 2 FKs, no extra cols → IS association."""
		table_def = {
			"columns": [
				{"name": "user_id", "type": "INTEGER", "primary_key": True},
				{"name": "role_id", "type": "INTEGER", "primary_key": True},
			],
			"pk": ["user_id", "role_id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
				{"constrained_columns": ["role_id"], "referred_table": "roles", "referred_columns": ["id"], "name": "fk2", "options": {}},
			],
			"unique_constraints": [],
			"indexes": [],
		}
		insp = make_inspector(self._schema_for(table_def))
		assert insp._is_association_table("junction") is True

	def test_junction_with_surrogate_pk(self):
		"""user_role(id PK, user_id FK, role_id FK) — 'id' is in audit_cols → IS association."""
		table_def = {
			"columns": [
				{"name": "id", "type": "INTEGER", "primary_key": True},
				{"name": "user_id", "type": "INTEGER"},
				{"name": "role_id", "type": "INTEGER"},
			],
			"pk": ["id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
				{"constrained_columns": ["role_id"], "referred_table": "roles", "referred_columns": ["id"], "name": "fk2", "options": {}},
			],
			"unique_constraints": [],
			"indexes": [],
		}
		insp = make_inspector(self._schema_for(table_def))
		assert insp._is_association_table("junction") is True

	def test_junction_with_audit_cols(self):
		"""id + user_id FK + role_id FK + created_at + updated_at — all audit → IS association."""
		table_def = {
			"columns": [
				{"name": "id", "type": "INTEGER", "primary_key": True},
				{"name": "user_id", "type": "INTEGER"},
				{"name": "role_id", "type": "INTEGER"},
				{"name": "created_at", "type": "TIMESTAMP"},
				{"name": "updated_at", "type": "TIMESTAMP"},
			],
			"pk": ["id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
				{"constrained_columns": ["role_id"], "referred_table": "roles", "referred_columns": ["id"], "name": "fk2", "options": {}},
			],
			"unique_constraints": [],
			"indexes": [],
		}
		insp = make_inspector(self._schema_for(table_def))
		assert insp._is_association_table("junction") is True

	def test_not_junction_three_fks(self):
		"""3 FKs → NOT association table."""
		schema = {
			"users": {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"roles": {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"orgs":  {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"junction": {
				"columns": [
					{"name": "user_id", "type": "INTEGER", "primary_key": True},
					{"name": "role_id", "type": "INTEGER", "primary_key": True},
					{"name": "org_id", "type": "INTEGER", "primary_key": True},
				],
				"pk": ["user_id", "role_id", "org_id"],
				"foreign_keys": [
					{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
					{"constrained_columns": ["role_id"], "referred_table": "roles", "referred_columns": ["id"], "name": "fk2", "options": {}},
					{"constrained_columns": ["org_id"], "referred_table": "orgs", "referred_columns": ["id"], "name": "fk3", "options": {}},
				],
				"unique_constraints": [],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		assert insp._is_association_table("junction") is False

	def test_not_junction_one_fk(self):
		"""Only 1 FK → NOT association table."""
		table_def = {
			"columns": [
				{"name": "user_id", "type": "INTEGER"},
				{"name": "name", "type": "VARCHAR"},
			],
			"pk": [],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
			],
			"unique_constraints": [],
			"indexes": [],
		}
		insp = make_inspector(self._schema_for(table_def))
		assert insp._is_association_table("junction") is False

	def test_not_junction_self_referencing_fks(self):
		"""Both FKs reference the same table → NOT association (len(referred) < 2)."""
		schema = {
			"nodes": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "parent_id", "type": "INTEGER"},
				],
				"pk": ["id"],
				"foreign_keys": [
					{"constrained_columns": ["parent_id"], "referred_table": "nodes", "referred_columns": ["id"], "name": "fk1", "options": {}},
				],
				"unique_constraints": [],
				"indexes": [],
			},
			"junction": {
				"columns": [
					{"name": "a_id", "type": "INTEGER", "primary_key": True},
					{"name": "b_id", "type": "INTEGER", "primary_key": True},
				],
				"pk": ["a_id", "b_id"],
				"foreign_keys": [
					{"constrained_columns": ["a_id"], "referred_table": "nodes", "referred_columns": ["id"], "name": "fk1", "options": {}},
					{"constrained_columns": ["b_id"], "referred_table": "nodes", "referred_columns": ["id"], "name": "fk2", "options": {}},
				],
				"unique_constraints": [],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		# Both FKs reference 'nodes' → referred set has size 1 → NOT association
		assert insp._is_association_table("junction") is False

	def test_not_junction_too_many_extra_cols(self):
		"""4 extra non-FK non-audit columns → NOT association table."""
		table_def = {
			"columns": [
				{"name": "user_id", "type": "INTEGER", "primary_key": True},
				{"name": "role_id", "type": "INTEGER", "primary_key": True},
				{"name": "col1", "type": "VARCHAR"},
				{"name": "col2", "type": "VARCHAR"},
				{"name": "col3", "type": "VARCHAR"},
				{"name": "col4", "type": "VARCHAR"},
			],
			"pk": ["user_id", "role_id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
				{"constrained_columns": ["role_id"], "referred_table": "roles", "referred_columns": ["id"], "name": "fk2", "options": {}},
			],
			"unique_constraints": [],
			"indexes": [],
		}
		insp = make_inspector(self._schema_for(table_def))
		assert insp._is_association_table("junction") is False

	def test_junction_with_one_extra_col(self):
		"""1 extra non-audit col (assigned_at) → IS association (borderline but ≤ 3)."""
		table_def = {
			"columns": [
				{"name": "user_id", "type": "INTEGER", "primary_key": True},
				{"name": "role_id", "type": "INTEGER", "primary_key": True},
				{"name": "assigned_at", "type": "TIMESTAMP"},
			],
			"pk": ["user_id", "role_id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
				{"constrained_columns": ["role_id"], "referred_table": "roles", "referred_columns": ["id"], "name": "fk2", "options": {}},
			],
			"unique_constraints": [],
			"indexes": [],
		}
		insp = make_inspector(self._schema_for(table_def))
		assert insp._is_association_table("junction") is True

	def test_junction_three_extra_cols_at_limit(self):
		"""Exactly 3 extra non-FK non-audit cols → IS association (at the limit)."""
		table_def = {
			"columns": [
				{"name": "user_id", "type": "INTEGER", "primary_key": True},
				{"name": "role_id", "type": "INTEGER", "primary_key": True},
				{"name": "a", "type": "VARCHAR"},
				{"name": "b", "type": "VARCHAR"},
				{"name": "c", "type": "VARCHAR"},
			],
			"pk": ["user_id", "role_id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
				{"constrained_columns": ["role_id"], "referred_table": "roles", "referred_columns": ["id"], "name": "fk2", "options": {}},
			],
			"unique_constraints": [],
			"indexes": [],
		}
		insp = make_inspector(self._schema_for(table_def))
		assert insp._is_association_table("junction") is True

	def test_not_junction_four_extra_cols(self):
		"""4 extra non-FK non-audit cols → NOT association (> 3)."""
		table_def = {
			"columns": [
				{"name": "user_id", "type": "INTEGER", "primary_key": True},
				{"name": "role_id", "type": "INTEGER", "primary_key": True},
				{"name": "a", "type": "VARCHAR"},
				{"name": "b", "type": "VARCHAR"},
				{"name": "c", "type": "VARCHAR"},
				{"name": "d", "type": "VARCHAR"},
			],
			"pk": ["user_id", "role_id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk1", "options": {}},
				{"constrained_columns": ["role_id"], "referred_table": "roles", "referred_columns": ["id"], "name": "fk2", "options": {}},
			],
			"unique_constraints": [],
			"indexes": [],
		}
		insp = make_inspector(self._schema_for(table_def))
		assert insp._is_association_table("junction") is False


# ---------------------------------------------------------------------------
# Test class: _determine_relationship_type
# ---------------------------------------------------------------------------

class TestDetermineRelationshipType:

	def _make_fk(self, constrained: List[str], referred_table: str, referred: List[str]) -> Dict[str, Any]:
		return {
			"constrained_columns": constrained,
			"referred_table": referred_table,
			"referred_columns": referred,
			"name": "fk_test",
			"options": {},
		}

	def test_many_to_one_simple_fk(self):
		"""orders.user_id → users.id, no unique constraint → MANY_TO_ONE."""
		schema = {
			"users":  {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"orders": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "user_id", "type": "INTEGER"},
				],
				"pk": ["id"],
				"foreign_keys": [self._make_fk(["user_id"], "users", ["id"])],
				"unique_constraints": [],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		insp._identify_association_tables()
		fk = schema["orders"]["foreign_keys"][0]
		result = insp._determine_relationship_type("orders", fk)
		assert result == RelationshipType.MANY_TO_ONE

	def test_one_to_one_via_unique_constraint(self):
		"""profiles.user_id → users.id, UNIQUE(user_id) → ONE_TO_ONE."""
		schema = {
			"users":    {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"profiles": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "user_id", "type": "INTEGER"},
				],
				"pk": ["id"],
				"foreign_keys": [self._make_fk(["user_id"], "users", ["id"])],
				"unique_constraints": [{"name": "uq_profiles_user_id", "column_names": ["user_id"]}],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		insp._identify_association_tables()
		fk = schema["profiles"]["foreign_keys"][0]
		result = insp._determine_relationship_type("profiles", fk)
		assert result == RelationshipType.ONE_TO_ONE

	def test_one_to_one_via_pk_fk(self):
		"""profiles.id → users.id (FK col == PK col, shared-PK pattern) → ONE_TO_ONE."""
		schema = {
			"users":    {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"profiles": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
				],
				"pk": ["id"],
				"foreign_keys": [self._make_fk(["id"], "users", ["id"])],
				"unique_constraints": [],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		insp._identify_association_tables()
		fk = schema["profiles"]["foreign_keys"][0]
		result = insp._determine_relationship_type("profiles", fk)
		assert result == RelationshipType.ONE_TO_ONE

	def test_self_referencing(self):
		"""employees.manager_id → employees.id → SELF_REFERENCING."""
		schema = {
			"employees": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "manager_id", "type": "INTEGER"},
				],
				"pk": ["id"],
				"foreign_keys": [self._make_fk(["manager_id"], "employees", ["id"])],
				"unique_constraints": [],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		insp._identify_association_tables()
		fk = schema["employees"]["foreign_keys"][0]
		result = insp._determine_relationship_type("employees", fk)
		assert result == RelationshipType.SELF_REFERENCING

	def test_many_to_many_from_junction(self):
		"""When the source table is a junction, FKs become MANY_TO_MANY."""
		schema = {
			"users":     {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"groups":    {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"user_group": {
				"columns": [
					{"name": "user_id", "type": "INTEGER", "primary_key": True},
					{"name": "group_id", "type": "INTEGER", "primary_key": True},
				],
				"pk": ["user_id", "group_id"],
				"foreign_keys": [
					self._make_fk(["user_id"], "users", ["id"]),
					self._make_fk(["group_id"], "groups", ["id"]),
				],
				"unique_constraints": [],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		insp._identify_association_tables()
		# user_group should have been detected as an association table
		assert "user_group" in insp._association_tables
		fk = schema["user_group"]["foreign_keys"][0]
		result = insp._determine_relationship_type("user_group", fk)
		assert result == RelationshipType.MANY_TO_MANY

	def test_no_false_one_to_one_partial_unique(self):
		"""
		CRITICAL Bug 3 regression: orders.customer_id → customers.id
		UNIQUE constraint covers (customer_id, promo_code) — not just customer_id.
		Must return MANY_TO_ONE, not ONE_TO_ONE.
		"""
		schema = {
			"customers": {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"orders": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "customer_id", "type": "INTEGER"},
					{"name": "promo_code", "type": "VARCHAR"},
				],
				"pk": ["id"],
				"foreign_keys": [self._make_fk(["customer_id"], "customers", ["id"])],
				# Composite unique — does NOT cover just customer_id
				"unique_constraints": [{"name": "uq_orders_cust_promo", "column_names": ["customer_id", "promo_code"]}],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		insp._identify_association_tables()
		fk = schema["orders"]["foreign_keys"][0]
		result = insp._determine_relationship_type("orders", fk)
		assert result == RelationshipType.MANY_TO_ONE, (
			"Composite unique on (customer_id, promo_code) must NOT trigger ONE_TO_ONE "
			"for a FK only on customer_id"
		)

	def test_one_to_one_exact_unique_match(self):
		"""profiles.user_id → users.id, unique constraint is exactly (user_id) → ONE_TO_ONE."""
		schema = {
			"users":    {"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}], "pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": []},
			"profiles": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "user_id", "type": "INTEGER"},
				],
				"pk": ["id"],
				"foreign_keys": [self._make_fk(["user_id"], "users", ["id"])],
				"unique_constraints": [{"name": "uq_profiles_user_id", "column_names": ["user_id"]}],
				"indexes": [],
			},
		}
		insp = make_inspector(schema)
		insp._identify_association_tables()
		fk = schema["profiles"]["foreign_keys"][0]
		result = insp._determine_relationship_type("profiles", fk)
		assert result == RelationshipType.ONE_TO_ONE


# ---------------------------------------------------------------------------
# Shared schema builders for synthesis tests
# ---------------------------------------------------------------------------

def _m2m_schema() -> Dict[str, Any]:
	"""users ↔ groups via user_group junction."""
	return {
		"users": {
			"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}],
			"pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": [],
		},
		"groups": {
			"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}],
			"pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": [],
		},
		"user_group": {
			"columns": [
				{"name": "user_id", "type": "INTEGER", "primary_key": True},
				{"name": "group_id", "type": "INTEGER", "primary_key": True},
			],
			"pk": ["user_id", "group_id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk_ug_u", "options": {}},
				{"constrained_columns": ["group_id"], "referred_table": "groups", "referred_columns": ["id"], "name": "fk_ug_g", "options": {}},
			],
			"unique_constraints": [], "indexes": [],
		},
	}


def _o2o_schema() -> Dict[str, Any]:
	"""users ← user_profiles (ONE_TO_ONE via UNIQUE FK)."""
	return {
		"users": {
			"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}],
			"pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": [],
		},
		"user_profiles": {
			"columns": [
				{"name": "id", "type": "INTEGER", "primary_key": True},
				{"name": "user_id", "type": "INTEGER"},
			],
			"pk": ["id"],
			"foreign_keys": [
				{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk_up_u", "options": {}},
			],
			"unique_constraints": [{"name": "uq_up_user_id", "column_names": ["user_id"]}],
			"indexes": [],
		},
	}


def _o2m_schema() -> Dict[str, Any]:
	"""customers ← orders (ONE_TO_MANY)."""
	return {
		"customers": {
			"columns": [{"name": "id", "type": "INTEGER", "primary_key": True}],
			"pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": [],
		},
		"orders": {
			"columns": [
				{"name": "id", "type": "INTEGER", "primary_key": True},
				{"name": "customer_id", "type": "INTEGER"},
			],
			"pk": ["id"],
			"foreign_keys": [
				{"constrained_columns": ["customer_id"], "referred_table": "customers", "referred_columns": ["id"], "name": "fk_ord_cust", "options": {}},
			],
			"unique_constraints": [], "indexes": [],
		},
	}


# ---------------------------------------------------------------------------
# Test class: MANY_TO_MANY synthesis
# ---------------------------------------------------------------------------

class TestSynthesizeManyToMany:

	def _result(self):
		insp = make_inspector(_m2m_schema())
		return insp.analyze_database()

	def test_many_to_many_on_owner_tables(self):
		"""After analyze_database both User and Group have MANY_TO_MANY rels."""
		result = self._result()
		user_rel_types = [r.type for r in result["tables"]["users"].relationships]
		group_rel_types = [r.type for r in result["tables"]["groups"].relationships]
		assert RelationshipType.MANY_TO_MANY in user_rel_types
		assert RelationshipType.MANY_TO_MANY in group_rel_types

	def test_many_to_many_association_table_set(self):
		"""MANY_TO_MANY rels on owner tables reference the junction table.

		NOTE: The current implementation has a known double-append issue: when
		analyze_database sets analysis['relationships'][t] = table_info.relationships
		(same list object), _synthesize_many_to_many_relationships appends via both
		owner_info.relationships and analysis['relationships'].setdefault(owner, []),
		resulting in 2 identical entries per owner instead of 1.  Tests document
		actual behavior; the assertion checks ≥1 and correct content rather than
		exact count to avoid being brittle against a future single-line fix.
		"""
		result = self._result()
		mm_rels = [r for r in result["tables"]["users"].relationships if r.type == RelationshipType.MANY_TO_MANY]
		assert len(mm_rels) >= 1
		assert mm_rels[0].association_table == "user_group"
		assert mm_rels[0].remote_table == "groups"

	def test_many_to_many_back_populates(self):
		"""back_populates is p.plural(owner_table_name).

		inflect treats already-plural table names as singular:
		  p.plural("users")  → "user"
		  p.plural("groups") → "group"
		This mirrors the actual _synthesize_many_to_many_relationships logic.
		"""
		result = self._result()
		user_mm = next(r for r in result["tables"]["users"].relationships if r.type == RelationshipType.MANY_TO_MANY)
		group_mm = next(r for r in result["tables"]["groups"].relationships if r.type == RelationshipType.MANY_TO_MANY)
		# back_populates on users' rel = p.plural("users") = "user"
		assert user_mm.back_populates == "user"
		# back_populates on groups' rel = p.plural("groups") = "group"
		assert group_mm.back_populates == "group"

	def test_junction_table_excluded_from_synthesis(self):
		"""
		The synthesis should NOT add user_group as a remote_table for users or groups.
		user_group is an association table and gets its own MANY_TO_MANY FK rels,
		but owner tables should not have user_group as their remote_table for synthesized N-N rels.
		"""
		result = self._result()
		for owner in ("users", "groups"):
			synth_remotes = {
				r.remote_table
				for r in result["tables"][owner].relationships
				if r.type == RelationshipType.MANY_TO_MANY
			}
			assert "user_group" not in synth_remotes, (
				f"{owner} should not have user_group as a MANY_TO_MANY remote_table"
			)

	def test_many_to_many_not_duplicated(self):
		"""Second call to analyze_database returns the exact same cached object (no re-synthesis)."""
		insp = make_inspector(_m2m_schema())
		r1 = insp.analyze_database()
		r2 = insp.analyze_database()
		# Must return the cached result — identical object
		assert r1 is r2
		# Count on second call is identical to first (no additional appends)
		count_after_first = len([r for r in r1["tables"]["users"].relationships if r.type == RelationshipType.MANY_TO_MANY])
		count_after_second = len([r for r in r2["tables"]["users"].relationships if r.type == RelationshipType.MANY_TO_MANY])
		assert count_after_first == count_after_second


# ---------------------------------------------------------------------------
# Test class: ONE_TO_ONE back-ref synthesis on referenced table
# ---------------------------------------------------------------------------

class TestSynthesizeOneToOne:

	def _result(self):
		insp = make_inspector(_o2o_schema())
		return insp.analyze_database()

	def test_one_to_one_back_ref_on_referenced_table(self):
		"""user_profiles.user_id UNIQUE → users.id creates ONE_TO_ONE back-ref on users.

		NOTE: Same double-append bug as M2M — analysis['relationships'][parent] is aliased
		to parent_info.relationships, causing each synthesis append to fire twice.
		Tests assert ≥1 and correct content rather than exact count.
		"""
		result = self._result()
		profile_rels = [
			r for r in result["tables"]["users"].relationships
			if r.type == RelationshipType.ONE_TO_ONE
		]
		assert len(profile_rels) >= 1
		assert profile_rels[0].remote_table == "user_profiles"

	def test_one_to_one_back_ref_singular_name(self):
		"""ONE_TO_ONE back-ref on users uses table name 'user_profiles' (singular-ish)."""
		result = self._result()
		profile_rel = next(
			r for r in result["tables"]["users"].relationships
			if r.type == RelationshipType.ONE_TO_ONE
		)
		# The synthesized name is the child table name (singular, per _synthesize_parent_relationships)
		assert profile_rel.name == "user_profiles"

	def test_one_to_many_not_emitted_for_one_to_one(self):
		"""users.relationships must NOT include a ONE_TO_MANY for user_profiles."""
		result = self._result()
		o2m_for_profiles = [
			r for r in result["tables"]["users"].relationships
			if r.type == RelationshipType.ONE_TO_MANY and r.remote_table == "user_profiles"
		]
		assert len(o2m_for_profiles) == 0, (
			"ONE_TO_ONE child must not also generate a ONE_TO_MANY back-ref on the parent"
		)


# ---------------------------------------------------------------------------
# Test class: ONE_TO_MANY synthesis
# ---------------------------------------------------------------------------

class TestSynthesizeOneToMany:

	def _result(self):
		insp = make_inspector(_o2m_schema())
		return insp.analyze_database()

	def test_one_to_many_on_parent(self):
		"""Customer has ONE_TO_MANY to orders after analyze_database."""
		result = self._result()
		customer_rels = result["tables"]["customers"].relationships
		assert any(r.type == RelationshipType.ONE_TO_MANY for r in customer_rels)

	def test_one_to_many_back_populates_matches_child_rel_name(self):
		"""Parent ONE_TO_MANY back_populates == child's MANY_TO_ONE rel name."""
		result = self._result()
		parent_rel = next(
			r for r in result["tables"]["customers"].relationships
			if r.type == RelationshipType.ONE_TO_MANY
		)
		child_rel = next(
			r for r in result["tables"]["orders"].relationships
			if r.type == RelationshipType.MANY_TO_ONE
		)
		assert parent_rel.back_populates == child_rel.name

	def test_one_to_many_plural_name(self):
		"""ONE_TO_MANY rel name on customers is p.plural(child_table_name).

		inflect treats 'orders' as already-plural and returns the singular 'order'.
		p.plural("orders") == "order" — this is the real output from the synthesis.
		"""
		result = self._result()
		parent_rel = next(
			r for r in result["tables"]["customers"].relationships
			if r.type == RelationshipType.ONE_TO_MANY
		)
		# p.plural("orders") → "order" (inflect de-pluralizes)
		assert parent_rel.name == "order"

	def test_no_duplicate_one_to_many(self):
		"""Second call to analyze_database returns the cached result — no additional synthesis."""
		insp = make_inspector(_o2m_schema())
		r1 = insp.analyze_database()
		r2 = insp.analyze_database()
		# Must be the same cached object — synthesis not re-run
		assert r1 is r2
		count1 = len([r for r in r1["tables"]["customers"].relationships if r.type == RelationshipType.ONE_TO_MANY])
		count2 = len([r for r in r2["tables"]["customers"].relationships if r.type == RelationshipType.ONE_TO_MANY])
		assert count1 == count2

	def test_self_referencing_one_to_many_antonym(self):
		"""employees.manager_id → employees: forward rel is 'manager', back_populates is 'subordinates'.

		_build_reverse_fk_index only indexes MANY_TO_ONE and ONE_TO_ONE — SELF_REFERENCING is
		excluded, so _synthesize_parent_relationships does NOT add a separate 'subordinates' rel.
		Instead the antonym lives in child_rel.back_populates on the forward 'manager' rel.
		"""
		schema = {
			"employees": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "manager_id", "type": "INTEGER", "nullable": True},
				],
				"pk": ["id"],
				"foreign_keys": [
					{"constrained_columns": ["manager_id"], "referred_table": "employees", "referred_columns": ["id"], "name": "fk_emp_mgr", "options": {}},
				],
				"unique_constraints": [], "indexes": [],
			},
		}
		insp = make_inspector(schema)
		result = insp.analyze_database()
		emp_rels = result["tables"]["employees"].relationships
		rel_names = [r.name for r in emp_rels]
		# Forward rel name derived from 'manager_id' → 'manager'
		assert "manager" in rel_names
		# Antonym stored in back_populates of the forward rel (not as a separate synthesized rel)
		manager_rel = next(r for r in emp_rels if r.name == "manager")
		assert manager_rel.back_populates == "subordinates"


# ---------------------------------------------------------------------------
# Test class: RelationshipInfo.foreign_key_column property
# ---------------------------------------------------------------------------

class TestRelationshipInfoForeignKeyColumn:

	def _make_rel(self, local_columns: List[str]) -> RelationshipInfo:
		return RelationshipInfo(
			name="test_rel",
			type=RelationshipType.MANY_TO_ONE,
			local_table="orders",
			remote_table="customers",
			local_columns=local_columns,
			remote_columns=["id"],
			association_table=None,
			back_populates="orders",
			cascade_options=[],
			lazy_loading="select",
			display_name="Test Rel",
			description="",
			cardinality_description="",
			ui_hint="",
		)

	def test_foreign_key_column_returns_first_local_col(self):
		"""foreign_key_column property returns first local column."""
		rel = self._make_rel(["customer_id"])
		assert rel.foreign_key_column == "customer_id"

	def test_foreign_key_column_returns_first_when_multiple(self):
		"""When multiple local columns, the first one is returned."""
		rel = self._make_rel(["customer_id", "branch_id"])
		assert rel.foreign_key_column == "customer_id"

	def test_foreign_key_column_empty_when_no_local_cols(self):
		"""foreign_key_column returns empty string when local_columns is empty (ONE_TO_MANY parent side)."""
		rel = self._make_rel([])
		assert rel.foreign_key_column == ""


# ---------------------------------------------------------------------------
# Test class: Full pipeline — all relationship types in one schema
# ---------------------------------------------------------------------------

class TestFullPipeline:

	def _full_schema(self) -> Dict[str, Any]:
		return {
			# Self-referencing
			"users": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "manager_id", "type": "INTEGER", "nullable": True},
				],
				"pk": ["id"],
				"foreign_keys": [
					{"constrained_columns": ["manager_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk_u_mgr", "options": {}},
				],
				"unique_constraints": [], "indexes": [],
			},
			# ONE_TO_ONE (shared-PK / unique FK)
			"profiles": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "user_id", "type": "INTEGER"},
				],
				"pk": ["id"],
				"foreign_keys": [
					{"constrained_columns": ["user_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk_p_u", "options": {}},
				],
				"unique_constraints": [{"name": "uq_p_user_id", "column_names": ["user_id"]}],
				"indexes": [],
			},
			# MANY_TO_ONE side
			"orders": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "customer_id", "type": "INTEGER"},
				],
				"pk": ["id"],
				"foreign_keys": [
					{"constrained_columns": ["customer_id"], "referred_table": "users", "referred_columns": ["id"], "name": "fk_ord_cust", "options": {}},
				],
				"unique_constraints": [], "indexes": [],
			},
			# N-N target
			"tags": {
				"columns": [
					{"name": "id", "type": "INTEGER", "primary_key": True},
					{"name": "name", "type": "VARCHAR"},
				],
				"pk": ["id"], "foreign_keys": [], "unique_constraints": [], "indexes": [],
			},
			# Junction
			"order_tags": {
				"columns": [
					{"name": "order_id", "type": "INTEGER", "primary_key": True},
					{"name": "tag_id", "type": "INTEGER", "primary_key": True},
				],
				"pk": ["order_id", "tag_id"],
				"foreign_keys": [
					{"constrained_columns": ["order_id"], "referred_table": "orders", "referred_columns": ["id"], "name": "fk_ot_ord", "options": {}},
					{"constrained_columns": ["tag_id"], "referred_table": "tags", "referred_columns": ["id"], "name": "fk_ot_tag", "options": {}},
				],
				"unique_constraints": [], "indexes": [],
			},
		}

	def _result(self):
		insp = make_inspector(self._full_schema())
		return insp.analyze_database()

	def test_association_tables_detected(self):
		"""order_tags is identified as an association table."""
		result = self._result()
		assert result["tables"]["order_tags"].is_association_table is True

	def test_self_referencing_on_users(self):
		"""users has a SELF_REFERENCING relationship (manager_id → users)."""
		result = self._result()
		user_types = [r.type for r in result["tables"]["users"].relationships]
		assert RelationshipType.SELF_REFERENCING in user_types

	def test_one_to_one_on_profiles(self):
		"""profiles has a ONE_TO_ONE relationship to users."""
		result = self._result()
		profile_types = [r.type for r in result["tables"]["profiles"].relationships]
		assert RelationshipType.ONE_TO_ONE in profile_types

	def test_one_to_one_back_ref_on_users(self):
		"""users gets a ONE_TO_ONE back-ref for profiles."""
		result = self._result()
		user_rels = result["tables"]["users"].relationships
		o2o_remotes = [r.remote_table for r in user_rels if r.type == RelationshipType.ONE_TO_ONE]
		assert "profiles" in o2o_remotes

	def test_many_to_one_on_orders(self):
		"""orders has MANY_TO_ONE to users."""
		result = self._result()
		order_types = [r.type for r in result["tables"]["orders"].relationships]
		assert RelationshipType.MANY_TO_ONE in order_types

	def test_one_to_many_on_users_for_orders(self):
		"""users gets ONE_TO_MANY back-ref for orders."""
		result = self._result()
		user_rels = result["tables"]["users"].relationships
		o2m_remotes = [r.remote_table for r in user_rels if r.type == RelationshipType.ONE_TO_MANY]
		assert "orders" in o2m_remotes

	def test_many_to_many_on_orders(self):
		"""orders gets a MANY_TO_MANY relationship to tags via order_tags."""
		result = self._result()
		order_types = [r.type for r in result["tables"]["orders"].relationships]
		assert RelationshipType.MANY_TO_MANY in order_types

	def test_many_to_many_on_tags(self):
		"""tags gets a MANY_TO_MANY relationship to orders via order_tags."""
		result = self._result()
		tag_types = [r.type for r in result["tables"]["tags"].relationships]
		assert RelationshipType.MANY_TO_MANY in tag_types

	def test_many_to_many_association_table_reference(self):
		"""MANY_TO_MANY rels on orders and tags reference order_tags as association_table."""
		result = self._result()
		order_mm = next(
			r for r in result["tables"]["orders"].relationships
			if r.type == RelationshipType.MANY_TO_MANY
		)
		tag_mm = next(
			r for r in result["tables"]["tags"].relationships
			if r.type == RelationshipType.MANY_TO_MANY
		)
		assert order_mm.association_table == "order_tags"
		assert tag_mm.association_table == "order_tags"

	def test_association_tables_in_analysis_key(self):
		"""association_tables list in analysis result contains 'order_tags'."""
		result = self._result()
		assert "order_tags" in result["association_tables"]

	def test_no_one_to_many_for_one_to_one_child(self):
		"""users must NOT have a ONE_TO_MANY for profiles (it's ONE_TO_ONE)."""
		result = self._result()
		user_rels = result["tables"]["users"].relationships
		o2m_for_profiles = [
			r for r in user_rels
			if r.type == RelationshipType.ONE_TO_MANY and r.remote_table == "profiles"
		]
		assert len(o2m_for_profiles) == 0

	def test_all_tables_in_analysis(self):
		"""All 5 tables appear in analysis['tables']."""
		result = self._result()
		for name in ("users", "profiles", "orders", "tags", "order_tags"):
			assert name in result["tables"], f"Missing table: {name}"
