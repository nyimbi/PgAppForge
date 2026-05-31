"""Shared utilities for the ReportForge plugin."""

from markupsafe import escape as _escape


def html_escape(text: str | None) -> str:
	"""HTML-escape *text* safely; returns '' for None."""
	return str(_escape(str(text) if text is not None else ""))


# Short alias used throughout the plugin
_he = html_escape
