"""
tests/ci/test_view_security_contracts.py

Static attribute tests for ERP view security contracts.

No Flask context, no DB, no mocks — just import the view classes and assert
that security-sensitive columns and permission restrictions are in place.

The FAB stubs in conftest.py handle the flask_appbuilder import chain so
ModelView et al. are replaced with a passthrough _Stub class.
"""
from __future__ import annotations

from pgappforge.plugins.erp.grc.ethics.views import (
	EthicsReportView,
	EthicsCaseView,
)
from pgappforge.plugins.erp.platform.tenant_control.views import (
	TenantProfileView,
	TenantUsageEventView,
)
from pgappforge.plugins.erp.platform.row_security.views import (
	SecurityContextView,
	RowSecurityPolicyView,
)


# ---------------------------------------------------------------------------
# EthicsReportView
# ---------------------------------------------------------------------------

def test_ethics_report_show_excludes_token():
	"""anonymous_token must never appear in show view — links reporter identity."""
	assert "anonymous_token" in EthicsReportView.show_exclude_columns


def test_ethics_report_search_excludes_token():
	"""anonymous_token must not be searchable — prevents enumeration attacks."""
	assert "anonymous_token" in EthicsReportView.search_exclude_columns


def test_ethics_report_add_excludes_token():
	"""anonymous_token must not be manually settable via the add form."""
	assert "anonymous_token" in EthicsReportView.add_exclude_columns


def test_ethics_report_show_excludes_reporter_contact():
	"""reporter_contact is PII — excluded from show to restrict casual access."""
	assert "reporter_contact" in EthicsReportView.show_exclude_columns


def test_ethics_report_list_omits_pii_fields():
	"""list_columns should never expose PII or token fields."""
	listed = set(EthicsReportView.list_columns)
	assert "anonymous_token"   not in listed
	assert "reporter_contact"  not in listed


# ---------------------------------------------------------------------------
# EthicsCaseView
# ---------------------------------------------------------------------------

def test_ethics_case_list_no_report_id():
	"""report_id is an FK — omitted from list to avoid exposing cross-reference."""
	assert "report_id" not in EthicsCaseView.list_columns


def test_ethics_case_list_columns_present():
	"""Smoke-check that list_columns is non-empty and contains expected fields."""
	listed = EthicsCaseView.list_columns
	assert len(listed) > 0
	assert "case_ref" in listed
	assert "status"   in listed


# ---------------------------------------------------------------------------
# TenantProfileView
# ---------------------------------------------------------------------------

def test_tenant_profile_base_permissions_read_only():
	"""TenantProfile is managed by platform ops — views are read-only for users."""
	perms = set(TenantProfileView.base_permissions)
	assert perms == {"can_list", "can_show"}


def test_tenant_profile_no_delete_permission():
	assert "can_delete" not in TenantProfileView.base_permissions


def test_tenant_profile_no_add_permission():
	assert "can_add" not in TenantProfileView.base_permissions


def test_tenant_profile_hides_billing_id():
	"""billing_hyperion_customer_id must be excluded from add/edit/show."""
	assert "billing_hyperion_customer_id" in TenantProfileView.add_exclude_columns
	assert "billing_hyperion_customer_id" in TenantProfileView.edit_exclude_columns
	assert "billing_hyperion_customer_id" in TenantProfileView.show_exclude_columns


# ---------------------------------------------------------------------------
# TenantUsageEventView
# ---------------------------------------------------------------------------

def test_tenant_usage_read_only():
	"""Usage events are append-only audit records — list + show only."""
	assert hasattr(TenantUsageEventView, "base_permissions")
	perms = set(TenantUsageEventView.base_permissions)
	assert perms <= {"can_list", "can_show"}
	assert "can_delete" not in perms
	assert "can_edit"   not in perms


def test_tenant_usage_has_list_columns():
	listed = TenantUsageEventView.list_columns
	assert "event_type"  in listed
	assert "recorded_at" in listed


# ---------------------------------------------------------------------------
# SecurityContextView
# ---------------------------------------------------------------------------

def test_security_context_no_computed_scope_in_list():
	"""computed_scope can be large JSON — excluded from list for performance."""
	assert "computed_scope" not in SecurityContextView.list_columns


def test_security_context_no_user_id_in_list():
	"""user_id is filtered server-side via RLS — not surfaced in list view."""
	assert "user_id" not in SecurityContextView.list_columns


def test_security_context_read_only():
	"""Security contexts are computed records — no delete permission."""
	assert hasattr(SecurityContextView, "base_permissions")
	assert "can_delete" not in SecurityContextView.base_permissions


def test_security_context_computed_scope_in_show_excludes():
	"""computed_scope excluded from show to prevent leaking full scope JSON."""
	assert "computed_scope" in SecurityContextView.show_exclude_columns


# ---------------------------------------------------------------------------
# RowSecurityPolicyView
# ---------------------------------------------------------------------------

def test_row_security_policy_allows_edit():
	"""Admins must be able to add/edit policies — can_add + can_edit present."""
	perms = set(RowSecurityPolicyView.base_permissions)
	assert "can_add"  in perms
	assert "can_edit" in perms


def test_row_security_policy_no_delete_by_default():
	"""Delete is excluded by default to prevent accidental policy removal."""
	assert "can_delete" not in RowSecurityPolicyView.base_permissions


def test_row_security_policy_list_has_key_fields():
	listed = RowSecurityPolicyView.list_columns
	assert "name"      in listed
	assert "is_active" in listed
