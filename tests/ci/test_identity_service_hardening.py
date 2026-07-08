"""
Focused CI tests for platform identity service guardrails.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pgappforge.plugins.erp.platform.identity.services import (
	IdentityService,
	IdentityServiceError,
	PolicyConflictError,
)


class _ScalarResult:
	def __init__(self, row=None):
		self._row = row

	def scalar_one_or_none(self):
		return self._row


class _FakeSession:
	def __init__(self, existing=None):
		self.existing = existing
		self.added = []
		self.flushed = False
		self.execute_calls = []

	def execute(self, statement):
		self.execute_calls.append(statement)
		return _ScalarResult(self.existing)

	def add(self, row):
		self.added.append(row)

	def flush(self):
		self.flushed = True


def _access_policy_rows(session):
	return [row for row in session.added if row.__class__.__name__ == "AccessPolicy"]


def test_create_policy_normalizes_permissions_effect_and_principal_type():
	session = _FakeSession()
	service = IdentityService()

	result = service.create_policy(
		session=session,
		tenant_id="tenant-1",
		policy_name="finance.gl.read",
		resource_type="GLAccount",
		principal_type="role",
		principal_id="Finance Manager",
		permissions=["read", "read", "*"],
		effect="allow",
		resource_id="account-1",
		conditions={},
	)

	policy = _access_policy_rows(session)[0]
	assert result["status"] == "created"
	assert policy.principal_type == "ROLE"
	assert policy.effect == "ALLOW"
	assert policy.permissions == ["read", "*"]
	assert policy.resource_id == "account-1"
	assert session.flushed is True


@pytest.mark.parametrize(
	"kwargs, message",
	[
		({"policy_name": "bad policy"}, "policy_name"),
		({"resource_type": "GLAccount;DROP"}, "resource_type"),
		({"principal_type": "SERVICE"}, "principal_type"),
		({"permissions": "read"}, "permissions"),
		({"permissions": ["read", ""]}, "permission"),
		({"conditions": []}, "conditions"),
	],
)
def test_create_policy_rejects_invalid_definition_before_write(kwargs, message):
	session = _FakeSession()
	service = IdentityService()
	params = {
		"session": session,
		"tenant_id": "tenant-1",
		"policy_name": "finance.gl.read",
		"resource_type": "GLAccount",
		"principal_type": "ROLE",
		"principal_id": "Finance Manager",
		"permissions": ["read"],
		"effect": "ALLOW",
		"conditions": {},
	}
	params.update(kwargs)

	with pytest.raises(IdentityServiceError, match=message):
		service.create_policy(**params)

	assert session.added == []
	assert session.execute_calls == []


def test_create_policy_duplicate_check_is_tenant_scoped():
	session = _FakeSession(existing=MagicMock())
	service = IdentityService()

	with pytest.raises(PolicyConflictError):
		service.create_policy(
			session=session,
			tenant_id="tenant-1",
			policy_name="finance.gl.read",
			resource_type="GLAccount",
			principal_type="ROLE",
			principal_id="Finance Manager",
			permissions=["read"],
		)

	statement = session.execute_calls[0]
	sql = str(statement)
	assert "tenant_id" in sql
	assert "policy_name" in sql
