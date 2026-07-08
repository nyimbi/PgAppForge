"""
Focused CI tests for platform credentials service guardrails.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from pgappforge.plugins.erp.platform.credentials.services import (
	CredentialsService,
	CredentialsServiceError,
)


class _FakeSession:
	def __init__(self, schema=None, credential=None):
		self.schema = schema
		self.credential = credential
		self.added = []
		self.flushed = False
		self.get_calls = []

	def get(self, model, row_id):
		self.get_calls.append((model.__name__, row_id))
		if model.__name__ == "CredentialSchema":
			return self.schema
		if model.__name__ == "IssuedCredential":
			return self.credential
		return None

	def add(self, row):
		self.added.append(row)

	def flush(self):
		self.flushed = True


def _schema():
	return SimpleNamespace(
		id="schema-db-id",
		schema_id="schema-public-id",
		is_published=True,
		credential_type="CERTIFICATE",
		name="Compliance Certificate",
		description="",
		criteria_narrative="",
		image_url="",
		alignment=None,
		issuer_id="issuer-1",
	)


def _issued_credentials(session):
	return [row for row in session.added if row.__class__.__name__ == "IssuedCredential"]


@pytest.mark.parametrize(
	"kwargs, message",
	[
		({"recipient_email": "not-an-email"}, "recipient_email"),
		({"recipient_id": ""}, "recipient_id"),
		({"evidence": []}, "evidence"),
		({"base_url": "javascript:alert(1)"}, "base_url"),
		({"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}, "expires_at"),
	],
)
def test_issue_credential_rejects_invalid_inputs_before_lookup(kwargs, message):
	service = CredentialsService()
	params = {
		"session": _FakeSession(schema=_schema()),
		"tenant_id": "tenant-1",
		"schema_id": "schema-db-id",
		"recipient_id": "recipient-1",
		"recipient_email": "learner@example.com",
		"evidence": {},
		"base_url": "https://credentials.example.com",
		"expires_at": datetime.now(timezone.utc) + timedelta(days=30),
	}
	params.update(kwargs)

	with pytest.raises(CredentialsServiceError, match=message):
		service.issue_credential(**params)

	assert params["session"].get_calls == []
	assert params["session"].added == []


def test_issue_credential_normalizes_base_url_and_evidence():
	service = CredentialsService()
	service._generate_credential_number = lambda *_args: "CERT-2026-00001"
	session = _FakeSession(schema=_schema())

	credential = service.issue_credential(
		session=session,
		tenant_id="tenant-1",
		schema_id="schema-db-id",
		recipient_id="recipient-1",
		recipient_email="learner@example.com",
		evidence={"score": 95},
		base_url="https://credentials.example.com/",
		expires_at=datetime.now(timezone.utc) + timedelta(days=30),
	)

	assert credential is _issued_credentials(session)[0]
	assert credential.verification_url.startswith("https://credentials.example.com/verify/")
	assert "//verify" not in credential.verification_url
	assert credential.evidence == {"score": 95}
	assert session.flushed is True


def test_revoke_credential_requires_reason_before_lookup():
	service = CredentialsService()
	session = _FakeSession()

	with pytest.raises(CredentialsServiceError, match="reason"):
		service.revoke_credential(session, credential_id="cred-1", reason="")

	assert session.get_calls == []


def test_revoke_credential_sets_revocation_fields():
	service = CredentialsService()
	credential = SimpleNamespace(
		id="cred-1",
		tenant_id="tenant-1",
		recipient_id="recipient-1",
		credential_number="CERT-2026-00001",
		status="ACTIVE",
		revoked_at=None,
		revocation_reason=None,
	)
	session = _FakeSession(credential=credential)

	result = service.revoke_credential(
		session,
		credential_id="cred-1",
		reason="Recipient requested revocation",
	)

	assert result is credential
	assert credential.status == "REVOKED"
	assert credential.revocation_reason == "Recipient requested revocation"
	assert credential.revoked_at is not None
	assert session.flushed is True


def test_share_to_linkedin_requires_access_token_before_lookup():
	service = CredentialsService()
	session = _FakeSession()

	with pytest.raises(CredentialsServiceError, match="access_token"):
		service.share_to_linkedin(
			session=session,
			tenant_id="tenant-1",
			credential_id="cred-1",
			access_token="",
		)

	assert session.get_calls == []
