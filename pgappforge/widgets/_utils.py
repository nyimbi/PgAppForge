"""Shared utilities for all widget modules."""

import json


def js_json(value) -> str:
	"""json.dumps safe for embedding inside an HTML <script> block.

	Escapes <, >, & as Unicode sequences so the HTML parser cannot
	misinterpret </script> or <script> sequences in a JS string literal.
	Use this everywhere json.dumps output lands inside a <script> tag.
	"""
	return (
		json.dumps(value)
		.replace("<", "\\u003c")
		.replace(">", "\\u003e")
		.replace("&", "\\u0026")
	)
