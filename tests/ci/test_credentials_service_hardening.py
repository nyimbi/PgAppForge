"""
Focused CI tests for platform credentials service guardrails.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import sys
import types
import urllib.request
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, DateTime, Integer, JSON, String
from sqlalchemy.orm import DeclarativeBase


SERVICES_PATH = (
	Path(__file__).resolve().parents[2]
	/ "pgappforge/plugins/erp/platform/credentials/services.py"
)


class _Base(DeclarativeBase):
	pass


class CredentialSchema(_Base):
	__tablename__ = "test_credential_schema"

	id = Column(String(36), primary_key=True)


class IssuedCredential(_Base):
	__tablename__ = "test_issued_credential"

	id = Column(String(36), primary_key=True)
	tenant_id = Column(String(36), nullable=False)
	credential_number = Column(String(100), nullable=False)
	schema_id = Column(String(36), nullable=False)
	recipient_id = Column(String(36), nullable=False)
	recipient_email = Column(String(255), nullable=False)
	issued_at = Column(DateTime, nullable=True)
	expires_at = Column(DateTime, nullable=True)
	evidence = Column(JSON, nullable=True)
	narrative = Column(String(500), nullable=True)
	achievement_id = Column(String(500), nullable=True)
	verification_url = Column(String(500), nullable=True)
	qr_code_url = Column(String(500), nullable=True)
	vc_jwt = Column(String(500), nullable=True)
	status = Column(String(20), nullable=False)
	revoked_at = Column(DateTime, nullable=True)
	revocation_reason = Column(String(500), nullable=True)


class CredentialVerification(_Base):
	__tablename__ = "test_credential_verification"

	id = Column(String(36), primary_key=True)
	tenant_id = Column(String(36), nullable=False)
	credential_id = Column(String(36), nullable=True)
	verification_token = Column(String(128), nullable=False)
	verified_at = Column(DateTime, nullable=True)
	verifier_id = Column(String(36), nullable=True)
	verifier_email = Column(String(255), nullable=True)
	result = Column(String(20), nullable=False)
	verification_details = Column(JSON, nullable=True)


class CredentialShare(_Base):
	__tablename__ = "test_credential_share"

	id = Column(String(36), primary_key=True)
	tenant_id = Column(String(36), nullable=False)
	credential_id = Column(String(36), nullable=False)
	share_token = Column(String(64), nullable=False)
	platform = Column(String(10), nullable=False)
	view_count = Column(Integer, nullable=True)


class _Event:
	def __init__(self, **kwargs):
		self.__dict__.update(kwargs)


def _install_module(monkeypatch: pytest.MonkeyPatch, name: str) -> types.ModuleType:
	module = types.ModuleType(name)
	module.__path__ = []  # type: ignore[attr-defined]
	monkeypatch.setitem(sys.modules, name, module)
	parent_name, _, attr = name.rpartition(".")
	if parent_name:
		setattr(sys.modules[parent_name], attr, module)
	return module


@pytest.fixture
def credentials_module(monkeypatch: pytest.MonkeyPatch):
	for module_name in (
		"pgappforge",
		"pgappforge.plugins",
		"pgappforge.plugins.erp",
		"pgappforge.plugins.erp.platform",
		"pgappforge.plugins.erp.platform.credentials",
		"pgappforge.plugins.erp.foundation",
	):
		_install_module(monkeypatch, module_name)

	models = _install_module(
		monkeypatch,
		"pgappforge.plugins.erp.platform.credentials.models",
	)
	models.CredentialSchema = CredentialSchema
	models.IssuedCredential = IssuedCredential
	models.CredentialVerification = CredentialVerification
	models.CredentialShare = CredentialShare

	events = _install_module(
		monkeypatch,
		"pgappforge.plugins.erp.platform.credentials.events",
	)
	for event_name in (
		"CredentialIssuedEvent",
		"CredentialVerifiedEvent",
		"CredentialRevokedEvent",
		"CredentialSharedEvent",
	):
		setattr(events, event_name, _Event)

	foundation_events = _install_module(
		monkeypatch,
		"pgappforge.plugins.erp.foundation.events",
	)
	foundation_events.emit_event = lambda event, session: None

	spec = importlib.util.spec_from_file_location(
		"pgappforge.plugins.erp.platform.credentials.services",
		SERVICES_PATH,
	)
	assert spec is not None
	assert spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	monkeypatch.setitem(sys.modules, spec.name, module)
	spec.loader.exec_module(module)
	module._test_foundation_events = foundation_events
	return module


class _FakeSession:
	def __init__(self, schema=None, credential=None):
		self.schema = schema
		self.credential = credential
		self.added = []
		self.executed = []
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
		if getattr(row, "id", None) is None:
			row.id = f"{row.__class__.__name__.lower()}-id"
		self.added.append(row)

	def execute(self, stmt):
		self.executed.append(stmt)
		return _FakeResult(self.credential)

	def flush(self):
		self.flushed = True


class _FakeResult:
	def __init__(self, row=None):
		self.row = row

	def scalar_one_or_none(self):
		return self.row

	def scalar_one(self):
		return 0


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


def _credential(**overrides):
	values = {
		"id": "cred-1",
		"tenant_id": "tenant-1",
		"credential_number": "CERT-2026-00001",
		"schema_id": "schema-db-id",
		"recipient_id": "recipient-1",
		"recipient_email": "learner@example.com",
		"issued_at": datetime.now(timezone.utc),
		"expires_at": None,
		"status": "ACTIVE",
		"verification_url": "https://credentials.example.com/verify/" + ("a" * 43),
	}
	values.update(overrides)
	return SimpleNamespace(**values)


def _issued_credentials(session):
	return [row for row in session.added if row.__class__.__name__ == "IssuedCredential"]


def _credential_shares(session):
	return [row for row in session.added if row.__class__.__name__ == "CredentialShare"]


class _FakeHTTPResponse:
	def __init__(self, payload, *, status=201):
		self.payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
		self.status = status

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, tb):
		return False

	def read(self, limit=-1):
		if limit is None or limit < 0:
			return self.payload
		return self.payload[:limit]


@pytest.mark.parametrize(
	"kwargs, message",
	[
		({"recipient_email": "not-an-email"}, "recipient_email"),
		({"recipient_id": ""}, "recipient_id"),
		({"evidence": []}, "evidence"),
		({"base_url": "javascript:alert(1)"}, "base_url"),
		({"base_url": "http://credentials.example.com"}, "base_url"),
		({"expires_at": datetime.now(timezone.utc) - timedelta(days=1)}, "expires_at"),
	],
)
def test_issue_credential_rejects_invalid_inputs_before_lookup(
	credentials_module,
	kwargs,
	message,
):
	service = credentials_module.CredentialsService()
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

	with pytest.raises(credentials_module.CredentialsServiceError, match=message):
		service.issue_credential(**params)

	assert params["session"].get_calls == []
	assert params["session"].added == []


def test_issue_credential_normalizes_base_url_and_evidence(credentials_module):
	service = credentials_module.CredentialsService()
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


def test_vc_jwt_stub_is_explicitly_unsigned(credentials_module):
	service = credentials_module.CredentialsService()
	token = service._encode_vc_jwt_stub({"sub": "credential-1"})
	header_segment, payload_segment, signature = token.split(".")

	def decode(segment):
		padding = "=" * (-len(segment) % 4)
		return json.loads(base64.urlsafe_b64decode(segment + padding))

	assert decode(header_segment) == {"alg": "none", "typ": "JWT", "cty": "vc+ld+json"}
	assert decode(payload_segment) == {"sub": "credential-1"}
	assert signature == ""


def test_verify_credential_normalizes_full_url_and_records_exact_token(
	credentials_module,
):
	service = credentials_module.CredentialsService()
	token = "a" * 43
	credential = SimpleNamespace(
		id="cred-1",
		tenant_id="tenant-1",
		credential_number="CERT-2026-00001",
		schema_id="schema-db-id",
		issued_at=datetime.now(timezone.utc),
		expires_at=None,
		status="ACTIVE",
		verification_url=f"https://credentials.example.com/verify/{token}",
	)
	session = _FakeSession(credential=credential)

	verification = service.verify_credential(
		session=session,
		tenant_id="",
		verification_token=f"https://credentials.example.com/verify/{token}?utm=ignored",
		verifier_email="verifier@example.com",
	)

	assert verification.result == "VALID"
	assert verification.verification_token == token
	assert verification.tenant_id == "tenant-1"
	assert verification.verifier_email == "verifier@example.com"
	assert verification in session.added
	assert session.flushed is True


def test_verify_credential_rejects_malformed_token_before_query(credentials_module):
	service = credentials_module.CredentialsService()
	session = _FakeSession()

	with pytest.raises(
		credentials_module.CredentialsServiceError,
		match="verification_token",
	):
		service.verify_credential(
			session=session,
			tenant_id="tenant-1",
			verification_token="short",
		)

	assert session.executed == []
	assert session.added == []


def test_revoke_credential_requires_reason_before_lookup(credentials_module):
	service = credentials_module.CredentialsService()
	session = _FakeSession()

	with pytest.raises(credentials_module.CredentialsServiceError, match="reason"):
		service.revoke_credential(session, credential_id="cred-1", reason="")

	assert session.get_calls == []


def test_revoke_credential_sets_revocation_fields(credentials_module):
	service = credentials_module.CredentialsService()
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


def test_share_to_linkedin_requires_access_token_before_lookup(credentials_module):
	service = credentials_module.CredentialsService()
	session = _FakeSession()

	with pytest.raises(credentials_module.CredentialsServiceError, match="access_token"):
		service.share_to_linkedin(
			session=session,
			tenant_id="tenant-1",
			credential_id="cred-1",
			access_token="",
		)

	assert session.get_calls == []


def test_share_to_linkedin_rejects_bearer_prefix_before_lookup(credentials_module):
	service = credentials_module.CredentialsService()
	session = _FakeSession()

	with pytest.raises(credentials_module.CredentialsServiceError, match="raw OAuth"):
		service.share_to_linkedin(
			session=session,
			tenant_id="tenant-1",
			credential_id="cred-1",
			access_token="Bearer " + ("a" * 32),
		)

	assert session.get_calls == []
	assert session.added == []


def test_share_to_linkedin_enforces_credential_tenant_before_share(
	credentials_module,
	monkeypatch,
):
	service = credentials_module.CredentialsService()
	session = _FakeSession(credential=_credential(tenant_id="tenant-2"), schema=_schema())

	def fail_urlopen(*args, **kwargs):
		raise AssertionError("urlopen should not be called for tenant mismatch")

	monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

	with pytest.raises(credentials_module.CredentialNotFoundError):
		service.share_to_linkedin(
			session=session,
			tenant_id="tenant-1",
			credential_id="cred-1",
			access_token="a" * 32,
		)

	assert _credential_shares(session) == []


def test_share_to_linkedin_rejects_unsafe_verification_url_before_share(
	credentials_module,
	monkeypatch,
):
	service = credentials_module.CredentialsService()
	session = _FakeSession(
		credential=_credential(verification_url="http://localhost/verify/token"),
		schema=_schema(),
	)

	def fail_urlopen(*args, **kwargs):
		raise AssertionError("urlopen should not be called for unsafe share URL")

	monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

	with pytest.raises(credentials_module.CredentialsServiceError, match="verification_url"):
		service.share_to_linkedin(
			session=session,
			tenant_id="tenant-1",
			credential_id="cred-1",
			access_token="a" * 32,
		)

	assert _credential_shares(session) == []


def test_share_to_linkedin_posts_sanitized_bounded_payload(
	credentials_module,
	monkeypatch,
):
	service = credentials_module.CredentialsService()
	schema = _schema()
	schema.name = "Compliance\nCertificate " + ("x" * 260)
	schema.description = "Line one\r\n" + ("d" * 260)
	session = _FakeSession(credential=_credential(), schema=schema)
	requests = []

	def fake_urlopen(req, timeout):
		requests.append((req, timeout))
		return _FakeHTTPResponse({"id": "urn:li:share:123"})

	monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

	result = service.share_to_linkedin(
		session=session,
		tenant_id="tenant-1",
		credential_id="cred-1",
		access_token="a" * 32,
	)

	assert result["share_url"] == session.credential.verification_url
	assert result["linkedin_post_id"] == "urn:li:share:123"
	assert len(_credential_shares(session)) == 1
	assert session.flushed is True
	assert len(requests) == 1

	req, timeout = requests[0]
	assert timeout == 10
	assert req.full_url == "https://api.linkedin.com/v2/ugcPosts"
	assert req.headers["Authorization"] == "Bearer " + ("a" * 32)
	payload = json.loads(req.data)
	content = payload["specificContent"]["com.linkedin.ugc.ShareContent"]
	commentary = content["shareCommentary"]["text"]
	media = content["media"][0]
	assert "\n" not in commentary
	assert len(commentary) <= 2800
	assert len(media["title"]["text"]) == 200
	assert "\r" not in media["description"]["text"]
	assert len(media["description"]["text"]) == 200
	assert media["originalUrl"] == session.credential.verification_url


def test_share_to_linkedin_ignores_oversized_response_but_keeps_share(
	credentials_module,
	monkeypatch,
):
	service = credentials_module.CredentialsService()
	session = _FakeSession(credential=_credential(), schema=_schema())

	def fake_urlopen(req, timeout):
		return _FakeHTTPResponse(b'{"id":"' + (b"x" * (70 * 1024)) + b'"}')

	monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

	result = service.share_to_linkedin(
		session=session,
		tenant_id="tenant-1",
		credential_id="cred-1",
		access_token="a" * 32,
	)

	assert result["linkedin_post_id"] == ""
	assert len(_credential_shares(session)) == 1
	assert session.flushed is True
