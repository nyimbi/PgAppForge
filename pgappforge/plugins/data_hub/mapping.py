"""Intelligent column mapping with fuzzy matching."""
from __future__ import annotations
import re
from difflib import SequenceMatcher


def _normalize(s: str) -> str:
	"""Normalize for comparison: lowercase, strip spaces, remove punctuation."""
	return re.sub(r"[^a-z0-9]", "", s.lower())


def fuzzy_score(a: str, b: str) -> float:
	"""Return similarity score 0-1 between two column names."""
	na, nb = _normalize(a), _normalize(b)
	if na == nb:
		return 1.0
	# Check if one contains the other
	if na in nb or nb in na:
		return 0.85
	return SequenceMatcher(None, na, nb).ratio()


def suggest_column_mapping(
	upload_columns: list[str],
	model_fields: list[dict],
	threshold: float = 0.6,
) -> dict[str, dict]:
	"""Suggest field mapping from upload columns to model fields.

	Args:
		upload_columns: column names from the uploaded file
		model_fields: list of {name, type, required, is_fk, display_name}
		threshold: minimum fuzzy score to auto-suggest

	Returns:
		{upload_col: {model_field: str, score: float, requires_fk_lookup: bool}}
	"""
	mapping: dict[str, dict] = {}
	field_names = [f["name"] for f in model_fields]
	field_display = {f["name"]: f.get("display_name", f["name"]) for f in model_fields}
	field_is_fk = {f["name"]: f.get("is_fk", False) for f in model_fields}

	for col in upload_columns:
		best_field = None
		best_score = 0.0
		for field in field_names:
			# Score against both the field name and its display name
			s1 = fuzzy_score(col, field)
			s2 = fuzzy_score(col, field_display.get(field, field))
			s = max(s1, s2)
			if s > best_score:
				best_score = s
				best_field = field
		if best_field and best_score >= threshold:
			mapping[col] = {
				"model_field": best_field,
				"score": round(best_score, 3),
				"requires_fk_lookup": field_is_fk.get(best_field, False),
			}
		else:
			mapping[col] = {"model_field": None, "score": 0.0, "requires_fk_lookup": False}
	return mapping


def get_model_fields_meta(model_class) -> list[dict]:
	"""Extract field metadata from a SQLAlchemy model class."""
	from sqlalchemy import inspect as sa_inspect
	fields = []
	try:
		mapper = sa_inspect(model_class)
		for col in mapper.columns:
			fields.append({
				"name": col.key,
				"type": str(col.type),
				"required": not col.nullable and col.default is None,
				"is_fk": bool(col.foreign_keys),
				"display_name": col.key.replace("_", " ").title(),
			})
	except Exception:
		pass
	return fields
