"""Shared utilities for media widgets."""

import json


def js_json(value) -> str:
	"""json.dumps safe for embedding inside an HTML <script> block.

	Escapes <, >, & as Unicode escapes so the HTML parser cannot
	misinterpret </script> or <script> sequences inside JS strings.
	"""
	return (
		json.dumps(value)
		.replace("<", "\\u003c")
		.replace(">", "\\u003e")
		.replace("&", "\\u0026")
	)
