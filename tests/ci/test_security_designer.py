"""
CI tests for the Visual Security Designer (Feature 2).

These are pure-import / structural tests — no app context or DB required.
"""
from __future__ import annotations


def test_security_snapshot_model_compiles():
	"""SecuritySnapshot model can be imported and has the correct tablename."""
	from pgappforge.models.security_designer_models import SecuritySnapshot
	assert SecuritySnapshot.__tablename__ == "security_snapshot"


def test_security_designer_view_imports():
	"""SecurityDesignerView and ROLE_TEMPLATES can be imported cleanly."""
	from pgappforge.views.security_designer import SecurityDesignerView, ROLE_TEMPLATES
	assert SecurityDesignerView is not None
	assert isinstance(ROLE_TEMPLATES, dict)
	assert len(ROLE_TEMPLATES) >= 5


def test_role_templates_have_required_keys():
	"""Every entry in ROLE_TEMPLATES has at minimum label and description keys."""
	from pgappforge.views.security_designer import ROLE_TEMPLATES
	for name, tpl in ROLE_TEMPLATES.items():
		assert "label" in tpl, f"Template '{name}' missing 'label'"
		assert "description" in tpl, f"Template '{name}' missing 'description'"
		assert isinstance(tpl.get("permissions"), list), (
			f"Template '{name}' missing 'permissions' list"
		)


def test_security_designer_view_compiles():
	"""SecurityDesignerView class is importable and has expected route_base."""
	from pgappforge.views.security_designer import SecurityDesignerView
	assert hasattr(SecurityDesignerView, "route_base")
	assert SecurityDesignerView.route_base == "/security-designer"


def test_jsyaml_cdn_added():
	"""JSYAML_CDN constant is present in the CDN module."""
	from pgappforge.widgets_postgresql._cdn import JSYAML_CDN
	assert "js-yaml" in JSYAML_CDN
	assert "<script" in JSYAML_CDN


def test_role_templates_cover_expected_names():
	"""All five expected template names are present."""
	from pgappforge.views.security_designer import ROLE_TEMPLATES
	for expected in ("Admin", "Editor", "Viewer", "API-only", "Auditor"):
		assert expected in ROLE_TEMPLATES, f"Missing template: {expected}"
