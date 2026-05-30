"""
import_export_mixin.py

Provides ImportExportMixin for data import/export functionality in SQLAlchemy
models used with Flask-AppBuilder.

Supports CSV, JSON, Excel (openpyxl), XML, and YAML formats with:
- Batch processing with configurable sizes
- Type-aware coercion and validation
- Relationship resolution (FK and M2M)
- Pre/post processing hooks
- Stdlib-only CSV/JSON paths (no pandas required)
- Optional openpyxl for Excel, pyyaml for YAML, xmltodict for XML

Author: Nyimbi Odero
Date: 2024-08-25 (modernized 2026-05-30)
Version: 2.0
"""

from __future__ import annotations

import csv
import io
import json
import logging
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from flask_appbuilder.models.mixins import AuditMixin
from sqlalchemy import (
	ARRAY,
	JSON,
	Boolean,
	Date,
	DateTime,
	Enum,
	Float,
	Integer,
	Numeric,
	String,
	Time,
)
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import RelationshipProperty

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional heavy dependencies — degrade gracefully
# ---------------------------------------------------------------------------
try:
	import openpyxl

	_OPENPYXL_AVAILABLE = True
except ImportError:
	_OPENPYXL_AVAILABLE = False

try:
	import yaml as _yaml

	_YAML_AVAILABLE = True
except ImportError:
	_YAML_AVAILABLE = False

try:
	import xmltodict as _xmltodict

	_XMLTODICT_AVAILABLE = True
except ImportError:
	_XMLTODICT_AVAILABLE = False


# ---------------------------------------------------------------------------
# Lightweight XML builder (replaces dicttoxml dependency)
# ---------------------------------------------------------------------------

def _dict_to_xml_element(tag: str, data: Any) -> ET.Element:
	elem = ET.Element(tag)
	if isinstance(data, dict):
		for key, val in data.items():
			child = _dict_to_xml_element(str(key), val)
			elem.append(child)
	elif isinstance(data, list):
		for item in data:
			child = _dict_to_xml_element("item", item)
			elem.append(child)
	else:
		elem.text = "" if data is None else str(data)
	return elem


def _records_to_xml(records: list[dict[str, Any]], root_tag: str = "data") -> bytes:
	root = ET.Element(root_tag)
	for record in records:
		child = _dict_to_xml_element("item", record)
		root.append(child)
	return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------------------
# Validation error
# ---------------------------------------------------------------------------

class ImportValidationError(ValueError):
	"""Raised when an individual field value fails validation."""


# ---------------------------------------------------------------------------
# Main mixin
# ---------------------------------------------------------------------------

class ImportExportMixin(AuditMixin):
	"""
	Mixin for SQLAlchemy/Flask-AppBuilder models adding multi-format import/export.

	Class Attributes (override per model):
		__export_fields__       Fields to export; empty = all non-excluded attrs.
		__import_fields__       Fields accepted during import; empty = all non-excluded.
		__export_exclude__      Fields always omitted from export.
		__import_exclude__      Fields always omitted from import.
		__export_labels__       Column label overrides: {field: label}.
		__import_validators__   Per-field callables returning bool; raise on False.
		__import_transformers__ Per-field callables applied before type coercion.
		__batch_size__          Default SQLAlchemy flush batch size.
		__date_format__         strptime format for date/datetime strings.
		__null_values__         String values treated as SQL NULL.
		__true_values__         String values coerced to True.
		__false_values__        String values coerced to False.
	"""

	__export_fields__: list[str] = []
	__import_fields__: list[str] = []
	__export_exclude__: list[str] = [
		"created_by",
		"created_on",
		"changed_by",
		"changed_on",
	]
	__import_exclude__: list[str] = [
		"id",
		"created_by",
		"created_on",
		"changed_by",
		"changed_on",
	]
	__export_labels__: dict[str, str] = {}
	__import_validators__: dict[str, Callable[[Any], bool]] = {}
	__import_transformers__: dict[str, Callable[[Any], Any]] = {}
	__batch_size__: int = 1000
	__date_format__: str = "%Y-%m-%d"
	__null_values__: list[str] = ["", "null", "NULL", "None", "NA", "N/A"]
	__true_values__: list[str] = ["true", "True", "TRUE", "1", "yes", "Yes", "YES"]
	__false_values__: list[str] = ["false", "False", "FALSE", "0", "no", "No", "NO"]

	# ------------------------------------------------------------------
	# Field discovery
	# ------------------------------------------------------------------

	@classmethod
	def get_exportable_fields(cls) -> list[str]:
		"""Return ordered list of fields eligible for export."""
		if cls.__export_fields__:
			return [f for f in cls.__export_fields__ if f not in cls.__export_exclude__]
		try:
			mapper = inspect(cls)
			return [
				c.key
				for c in mapper.attrs
				if not c.key.startswith("_") and c.key not in cls.__export_exclude__
			]
		except Exception:
			return []

	@classmethod
	def get_importable_fields(cls) -> list[str]:
		"""Return ordered list of fields accepted during import."""
		if cls.__import_fields__:
			return [f for f in cls.__import_fields__ if f not in cls.__import_exclude__]
		try:
			mapper = inspect(cls)
			return [
				c.key
				for c in mapper.attrs
				if not c.key.startswith("_") and c.key not in cls.__import_exclude__
			]
		except Exception:
			return []

	# ------------------------------------------------------------------
	# Serialisation helpers
	# ------------------------------------------------------------------

	@classmethod
	def to_dict(cls, instance: Any, include_relations: bool = True) -> dict[str, Any]:
		"""
		Serialise a model instance to a plain dict.

		Relationships are represented by their PK (or list of PKs for M2M).
		date/datetime → ISO string, Decimal → str, list/dict → JSON string.
		"""
		data: dict[str, Any] = {}
		for field in cls.get_exportable_fields():
			value = getattr(instance, field, None)

			if include_relations and hasattr(value, "__table__"):
				# Single related object → FK value
				data[field] = getattr(value, "id", None)
			elif (
				include_relations
				and isinstance(value, list)
				and value
				and hasattr(value[0], "__table__")
			):
				# Collection → list of PKs
				data[field] = [getattr(item, "id", None) for item in value]
			elif isinstance(value, (date, datetime)):
				data[field] = value.isoformat()
			elif isinstance(value, Decimal):
				data[field] = str(value)
			elif isinstance(value, (list, dict)):
				data[field] = json.dumps(value)
			else:
				data[field] = value

		return cls.post_export_hook(data)

	@classmethod
	def _apply_export_labels(cls, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
		"""Rename keys according to __export_labels__."""
		if not cls.__export_labels__:
			return records
		return [
			{cls.__export_labels__.get(k, k): v for k, v in row.items()}
			for row in records
		]

	@classmethod
	def _reverse_export_labels(cls, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
		"""Reverse __export_labels__ mapping for import."""
		if not cls.__export_labels__:
			return records
		reverse = {v: k for k, v in cls.__export_labels__.items()}
		return [
			{reverse.get(k, k): v for k, v in row.items()}
			for row in records
		]

	# ------------------------------------------------------------------
	# Value processing for import
	# ------------------------------------------------------------------

	@classmethod
	def process_import_value(cls, field: str, value: Any) -> Any:
		"""
		Coerce, transform, and validate a single field value for import.

		Order: null check → custom transformer → relationship resolution →
		       SQLAlchemy type coercion → custom validator.

		Raises:
			ImportValidationError on type mismatch or validator failure.
		"""
		# Null handling
		if value is None or str(value).strip() in cls.__null_values__:
			return None

		# Custom transformer (runs before type coercion)
		if field in cls.__import_transformers__:
			value = cls.__import_transformers__[field](value)

		# Relationship resolution
		attr = getattr(cls, field, None)
		if attr is not None and hasattr(attr, "property") and isinstance(
			attr.property, RelationshipProperty
		):
			related_model = attr.property.mapper.class_
			if attr.property.uselist:
				if isinstance(value, str):
					try:
						value = json.loads(value)
					except json.JSONDecodeError as exc:
						raise ImportValidationError(
							f"Field '{field}': expected JSON array, got {value!r}"
						) from exc
				# Use Session.get() pattern (SA 2.x); fall back to query.get (SA 1.x)
				resolved = []
				for pk in value:
					if pk is None:
						continue
					try:
						obj = related_model.query.get(pk)
					except Exception:
						obj = None
					resolved.append(obj)
				return resolved
			else:
				if value is None:
					return None
				try:
					return related_model.query.get(value)
				except Exception:
					return None

		# SQLAlchemy column type coercion
		col_attr = getattr(inspect(cls).attrs, field, None)
		if col_attr is not None and hasattr(col_attr, "columns"):
			try:
				field_type = col_attr.columns[0].type
			except (IndexError, AttributeError):
				field_type = None

			if field_type is not None:
				try:
					if isinstance(field_type, String):
						value = str(value).strip()
					elif isinstance(field_type, Integer):
						value = int(float(value))
					elif isinstance(field_type, Float):
						value = float(value)
					elif isinstance(field_type, Boolean):
						value = str(value).strip() in cls.__true_values__
					elif isinstance(field_type, DateTime):
						if isinstance(value, str):
							value = datetime.strptime(value, cls.__date_format__)
					elif isinstance(field_type, Date):
						if isinstance(value, str):
							value = datetime.strptime(value, cls.__date_format__).date()
					elif isinstance(field_type, Time):
						if isinstance(value, str):
							value = datetime.strptime(value, "%H:%M:%S").time()
					elif isinstance(field_type, Numeric):
						value = Decimal(str(value))
					elif isinstance(field_type, JSON):
						if isinstance(value, str):
							value = json.loads(value)
					elif isinstance(field_type, ARRAY):
						if isinstance(value, str):
							value = json.loads(value)
					elif isinstance(field_type, Enum):
						value = field_type.python_type(value)
				except (ValueError, TypeError, json.JSONDecodeError, InvalidOperation) as exc:
					raise ImportValidationError(
						f"Field '{field}': cannot coerce {value!r} — {exc}"
					) from exc

		# Custom validator (post-coercion)
		if field in cls.__import_validators__:
			try:
				ok = cls.__import_validators__[field](value)
			except Exception as exc:
				raise ImportValidationError(
					f"Field '{field}': validator raised — {exc}"
				) from exc
			if not ok:
				raise ImportValidationError(
					f"Field '{field}': validation rejected value {value!r}"
				)

		return value

	# ------------------------------------------------------------------
	# Export
	# ------------------------------------------------------------------

	@classmethod
	def export_to_csv(
		cls,
		query: Any,
		output_file: str | None = None,
		*,
		dialect: str = "excel",
		encoding: str = "utf-8-sig",
	) -> str:
		"""
		Export query results to CSV.

		Args:
			query:       SQLAlchemy query / iterable of model instances.
			output_file: Destination path. If None, returns CSV as a string.
			dialect:     csv.writer dialect (default 'excel').
			encoding:    File encoding (default 'utf-8-sig' for Excel compatibility).

		Returns:
			Absolute path written, or CSV text if output_file is None.
		"""
		records = cls._apply_export_labels(
			[cls.to_dict(instance) for instance in query]
		)
		if not records:
			fieldnames: list[str] = []
		else:
			fieldnames = list(records[0].keys())

		buf = io.StringIO()
		writer = csv.DictWriter(buf, fieldnames=fieldnames, dialect=dialect)
		writer.writeheader()
		writer.writerows(records)
		csv_text = buf.getvalue()

		if output_file is None:
			return csv_text

		with open(output_file, "w", newline="", encoding=encoding) as fh:
			fh.write(csv_text)
		return output_file

	@classmethod
	def export_to_json(
		cls,
		query: Any,
		output_file: str | None = None,
		*,
		pretty: bool = True,
	) -> str:
		"""
		Export query results to JSON.

		Returns file path written, or JSON text if output_file is None.
		"""
		records = [cls.to_dict(instance) for instance in query]
		text = json.dumps(records, indent=2 if pretty else None, default=str)

		if output_file is None:
			return text

		with open(output_file, "w", encoding="utf-8") as fh:
			fh.write(text)
		return output_file

	@classmethod
	def export_to_excel(cls, query: Any, output_file: str, **kwargs: Any) -> str:
		"""
		Export query results to Excel (.xlsx) via openpyxl.

		Raises:
			RuntimeError if openpyxl is not installed.
		"""
		if not _OPENPYXL_AVAILABLE:
			raise RuntimeError(
				"openpyxl is required for Excel export — pip install openpyxl"
			)
		records = cls._apply_export_labels(
			[cls.to_dict(instance) for instance in query]
		)
		wb = openpyxl.Workbook()
		ws = wb.active
		if records:
			headers = list(records[0].keys())
			ws.append(headers)
			for row in records:
				ws.append([row.get(h) for h in headers])
		wb.save(output_file)
		return output_file

	@classmethod
	def export_to_xml(cls, query: Any, output_file: str) -> str:
		"""Export query results to XML using stdlib xml.etree."""
		records = [cls.to_dict(instance) for instance in query]
		xml_bytes = _records_to_xml(records)
		with open(output_file, "wb") as fh:
			fh.write(xml_bytes)
		return output_file

	@classmethod
	def export_to_yaml(cls, query: Any, output_file: str) -> str:
		"""
		Export query results to YAML.

		Raises:
			RuntimeError if pyyaml is not installed.
		"""
		if not _YAML_AVAILABLE:
			raise RuntimeError("pyyaml is required for YAML export — pip install pyyaml")
		records = [cls.to_dict(instance) for instance in query]
		with open(output_file, "w", encoding="utf-8") as fh:
			_yaml.dump(records, fh, allow_unicode=True)
		return output_file

	# ------------------------------------------------------------------
	# Core import engine
	# ------------------------------------------------------------------

	@classmethod
	def import_data(
		cls,
		session: Any,
		data: list[dict[str, Any]],
		batch_size: int | None = None,
	) -> dict[str, Any]:
		"""
		Bulk-import records with validation, batching, and error collection.

		Args:
			session:    SQLAlchemy session.
			data:       List of raw dicts (field names must match model columns).
			batch_size: Override __batch_size__.

		Returns:
			{
			    "total_processed": int,
			    "successful_imports": int,
			    "failed_imports": int,
			    "errors": [{"row": int, "data": dict, "error": str}, ...]
			}
		"""
		data = cls.pre_import_hook(data)
		data = cls.data_validation_hook(data)

		importable = cls.get_importable_fields()
		total = len(data)
		successful = 0
		errors: list[dict[str, Any]] = []
		effective_batch = batch_size or cls.__batch_size__

		for batch_start in range(0, total, effective_batch):
			batch = data[batch_start : batch_start + effective_batch]
			batch_added = 0

			for local_idx, item in enumerate(batch):
				global_row = batch_start + local_idx + 1
				try:
					instance = cls()
					for field in importable:
						if field in item:
							processed = cls.process_import_value(field, item[field])
							setattr(instance, field, processed)
					session.add(instance)
					batch_added += 1
				except Exception as exc:
					errors.append({"row": global_row, "data": item, "error": str(exc)})
					logger.error("Import row %d error: %s", global_row, exc, exc_info=True)

			try:
				session.flush()
				successful += batch_added
			except Exception as exc:
				session.rollback()
				logger.error("Batch flush error (rows %d-%d): %s", batch_start + 1, batch_start + len(batch), exc, exc_info=True)
				for local_idx, item in enumerate(batch):
					errors.append({
						"row": batch_start + local_idx + 1,
						"data": item,
						"error": f"Batch flush failed: {exc}",
					})

		return {
			"total_processed": total,
			"successful_imports": successful,
			"failed_imports": total - successful,
			"errors": errors,
		}

	# ------------------------------------------------------------------
	# Format-specific importers
	# ------------------------------------------------------------------

	@classmethod
	def import_from_csv(
		cls,
		session: Any,
		file_path: str,
		*,
		encoding: str = "utf-8-sig",
		delimiter: str = ",",
	) -> dict[str, Any]:
		"""Import records from a CSV file (stdlib csv — no pandas required)."""
		with open(file_path, newline="", encoding=encoding) as fh:
			reader = csv.DictReader(fh, delimiter=delimiter)
			records = list(reader)

		records = cls._reverse_export_labels(records)
		return cls.import_data(session, records)

	@classmethod
	def import_from_json(cls, session: Any, file_path: str) -> dict[str, Any]:
		"""Import records from a JSON file (list of objects)."""
		with open(file_path, "r", encoding="utf-8") as fh:
			data = json.load(fh)
		if not isinstance(data, list):
			raise ValueError(f"JSON file must contain a top-level array, got {type(data).__name__}")
		return cls.import_data(session, data)

	@classmethod
	def import_from_excel(
		cls,
		session: Any,
		file_path: str,
		*,
		sheet_name: str | None = None,
	) -> dict[str, Any]:
		"""
		Import records from an Excel (.xlsx) file via openpyxl.

		Args:
			session:    SQLAlchemy session.
			file_path:  Path to .xlsx file.
			sheet_name: Worksheet name; defaults to active sheet.

		Raises:
			RuntimeError if openpyxl is not installed.
		"""
		if not _OPENPYXL_AVAILABLE:
			raise RuntimeError(
				"openpyxl is required for Excel import — pip install openpyxl"
			)
		wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
		ws = wb[sheet_name] if sheet_name else wb.active
		rows = list(ws.iter_rows(values_only=True))
		if not rows:
			return cls.import_data(session, [])

		headers = [str(h) if h is not None else "" for h in rows[0]]
		records = [dict(zip(headers, row)) for row in rows[1:]]
		records = cls._reverse_export_labels(records)
		return cls.import_data(session, records)

	@classmethod
	def import_from_xml(cls, session: Any, file_path: str) -> dict[str, Any]:
		"""
		Import records from an XML file.

		Prefers xmltodict when available; falls back to stdlib xml.etree.
		Expected structure: <data><item>...</item>...</data>
		"""
		if _XMLTODICT_AVAILABLE:
			with open(file_path, "r", encoding="utf-8") as fh:
				parsed = _xmltodict.parse(fh.read())
			items = parsed.get("data", {}).get("item", [])
			if isinstance(items, dict):
				# Single item returned as dict, not list
				items = [items]
		else:
			tree = ET.parse(file_path)
			root = tree.getroot()
			items = []
			for child in root:
				record: dict[str, Any] = {}
				for elem in child:
					record[elem.tag] = elem.text
				items.append(record)

		return cls.import_data(session, items)

	@classmethod
	def import_from_yaml(cls, session: Any, file_path: str) -> dict[str, Any]:
		"""
		Import records from a YAML file.

		Raises:
			RuntimeError if pyyaml is not installed.
		"""
		if not _YAML_AVAILABLE:
			raise RuntimeError("pyyaml is required for YAML import — pip install pyyaml")
		with open(file_path, "r", encoding="utf-8") as fh:
			data = _yaml.safe_load(fh)
		if not isinstance(data, list):
			raise ValueError(f"YAML file must contain a top-level sequence, got {type(data).__name__}")
		return cls.import_data(session, data)

	# ------------------------------------------------------------------
	# Streaming / in-memory export helpers
	# ------------------------------------------------------------------

	@classmethod
	def export_to_csv_stream(cls, query: Any) -> io.BytesIO:
		"""Return a BytesIO containing UTF-8 CSV, suitable for Flask send_file."""
		csv_text = cls.export_to_csv(query, output_file=None)
		return io.BytesIO(csv_text.encode("utf-8-sig"))

	@classmethod
	def export_to_json_stream(cls, query: Any, *, pretty: bool = True) -> io.BytesIO:
		"""Return a BytesIO containing UTF-8 JSON, suitable for Flask send_file."""
		json_text = cls.export_to_json(query, output_file=None, pretty=pretty)
		return io.BytesIO(json_text.encode("utf-8"))

	# ------------------------------------------------------------------
	# Hooks — override in subclasses
	# ------------------------------------------------------------------

	@classmethod
	def data_validation_hook(
		cls, data: list[dict[str, Any]]
	) -> list[dict[str, Any]]:
		"""
		Batch-level validation/transformation hook invoked before row processing.

		Override to reject or amend entire batches before import_data loops.
		"""
		return data

	@classmethod
	def pre_import_hook(
		cls, data: list[dict[str, Any]]
	) -> list[dict[str, Any]]:
		"""
		Pre-processing hook called at the very start of import_data.

		Override to normalise keys, strip prefixes, etc.
		"""
		return data

	@classmethod
	def post_export_hook(cls, data: dict[str, Any]) -> dict[str, Any]:
		"""
		Per-record hook called after each instance is serialised to dict.

		Override to add computed fields or redact sensitive values.
		"""
		return data
