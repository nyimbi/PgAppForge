#!/usr/bin/env python3
"""
normalize_templates.py
Cross-cutting schema improvements for all bundled pgappforge templates.

Transformations applied to every table in every JSON:
  a. PK type normalisation: SERIAL/BIGSERIAL/INTEGER PK → UUID + gen_random_uuid()
  b. tenant_id column injection
  c. Audit columns: created_at, updated_at, created_by, updated_by
  d. FK index: any *_id column that is not a PK gets index: true

Special-case for iso20022.json:
  - Inject iso20022_party table
  - Re-point debtor_id  → iso20022_party.id (UUID)
  - Re-point creditor_id → iso20022_party.id (UUID)
  - Leave debtor_account_iban as denorm convenience column
"""

import json
import pathlib
import sys

BUNDLED = pathlib.Path(__file__).parent / "bundled"

# PK types that should be normalised to UUID
SERIAL_TYPES = {"SERIAL", "BIGSERIAL", "INTEGER"}

# Audit columns to inject (in order)
TENANT_COL = {"name": "tenant_id", "type": "UUID", "nullable": False, "index": True}

AUDIT_COLS = [
	{"name": "created_at", "type": "TIMESTAMPTZ", "nullable": False, "default": "NOW()"},
	{"name": "updated_at", "type": "TIMESTAMPTZ", "nullable": False, "default": "NOW()"},
	{"name": "created_by", "type": "UUID", "nullable": True},
	{"name": "updated_by", "type": "UUID", "nullable": True},
]

ISO20022_PARTY_TABLE = [
	{"name": "id",         "type": "UUID",         "pk": True,  "default": "gen_random_uuid()"},
	{"name": "tenant_id",  "type": "UUID",         "nullable": False, "index": True},
	{"name": "party_type", "type": "VARCHAR(20)",  "nullable": False},
	{"name": "name",       "type": "VARCHAR(255)", "nullable": False},
	{"name": "lei",        "type": "CHAR(20)"},
	{"name": "tax_id",     "type": "VARCHAR(50)"},
	{"name": "bic",        "type": "CHAR(11)"},
	{"name": "iban",       "type": "VARCHAR(34)"},
	{"name": "address",    "type": "JSONB",        "default": "{}"},
	{"name": "country",    "type": "CHAR(2)"},
	{"name": "created_at", "type": "TIMESTAMPTZ",  "nullable": False, "default": "NOW()"},
	{"name": "updated_at", "type": "TIMESTAMPTZ",  "nullable": False, "default": "NOW()"},
	{"name": "created_by", "type": "UUID",          "nullable": True},
	{"name": "updated_by", "type": "UUID",          "nullable": True},
]


def normalise_pk(col: dict, counters: dict) -> bool:
	"""Return True if the column was modified."""
	if col.get("pk") and col.get("type") in SERIAL_TYPES:
		col["type"] = "UUID"
		col["default"] = "gen_random_uuid()"
		counters["pks_normalised"] += 1
		return True
	return False


def inject_tenant(cols: list[dict], counters: dict) -> bool:
	names = {c["name"] for c in cols}
	if "tenant_id" not in names:
		cols.append(dict(TENANT_COL))
		counters["cols_added"] += 1
		return True
	return False


def inject_audit(cols: list[dict], counters: dict) -> bool:
	names = {c["name"] for c in cols}
	added = False
	for proto in AUDIT_COLS:
		if proto["name"] not in names:
			cols.append(dict(proto))
			counters["cols_added"] += 1
			added = True
	return added


def inject_fk_indexes(cols: list[dict], counters: dict) -> bool:
	changed = False
	for col in cols:
		name = col.get("name", "")
		if (
			name.endswith("_id")
			and not col.get("pk")
			and not col.get("index")
		):
			col["index"] = True
			counters["fk_indexes_added"] += 1
			changed = True
	return changed


def transform_table(cols: list[dict], counters: dict) -> bool:
	"""Apply all generic transforms to one table's column list. Returns True if any change."""
	if not isinstance(cols, list):
		return False
	changed = False
	for col in cols:
		if normalise_pk(col, counters):
			changed = True
	if inject_tenant(cols, counters):
		changed = True
	if inject_audit(cols, counters):
		changed = True
	if inject_fk_indexes(cols, counters):
		changed = True
	return changed


def apply_iso20022_special(data: dict, counters: dict) -> None:
	tables = data.get("tables", {})

	# 1. Inject iso20022_party if absent
	if "iso20022_party" not in tables:
		# Insert it first so FKs resolve cleanly; dicts preserve insertion order in Python 3.7+
		new_tables = {"iso20022_party": ISO20022_PARTY_TABLE}
		new_tables.update(tables)
		data["tables"] = new_tables
		counters["tables_modified"] += 1
		counters["cols_added"] += len(ISO20022_PARTY_TABLE)

	tables = data["tables"]  # re-bind after possible replacement

	# 2. payment_instruction.debtor_id → iso20022_party.id
	for col in tables.get("payment_instruction", []):
		if col.get("name") == "debtor_id":
			col["fk"] = "iso20022_party.id"
			col["type"] = "UUID"

	# 3. credit_transfer_txn.creditor_id → iso20022_party.id
	for col in tables.get("credit_transfer_txn", []):
		if col.get("name") == "creditor_id":
			col["fk"] = "iso20022_party.id"
			col["type"] = "UUID"


def process_file(path: pathlib.Path, counters: dict) -> bool:
	"""Load, transform, write one JSON file. Returns True if the file was modified."""
	data = json.loads(path.read_text(encoding="utf-8"))
	tables = data.get("tables", {})

	if not tables:
		return False

	file_changed = False

	for tname, cols in tables.items():
		if not isinstance(cols, list):
			continue
		if transform_table(cols, counters):
			counters["tables_modified"] += 1
			file_changed = True

	# iso20022 special case (runs *after* generic transforms so audit cols are already injected)
	if path.name == "iso20022.json":
		apply_iso20022_special(data, counters)
		file_changed = True

	if file_changed:
		path.write_text(
			json.dumps(data, indent=2, ensure_ascii=False),
			encoding="utf-8",
		)
		counters["files_processed"] += 1

	return file_changed


def main() -> None:
	json_files = sorted(BUNDLED.glob("*.json"))
	if not json_files:
		print(f"No JSON files found in {BUNDLED}", file=sys.stderr)
		sys.exit(1)

	counters = {
		"files_processed": 0,
		"tables_modified": 0,
		"cols_added": 0,
		"pks_normalised": 0,
		"fk_indexes_added": 0,
	}

	for path in json_files:
		process_file(path, counters)

	print("=" * 60)
	print("normalize_templates.py — summary")
	print("=" * 60)
	print(f"  Files processed   : {counters['files_processed']}")
	print(f"  Tables modified   : {counters['tables_modified']}")
	print(f"  Columns added     : {counters['cols_added']}")
	print(f"  PKs normalised    : {counters['pks_normalised']}")
	print(f"  FK indexes added  : {counters['fk_indexes_added']}")
	print("=" * 60)


if __name__ == "__main__":
	main()
