"""Focused guardrail tests for ActivityPub federation egress."""
from __future__ import annotations

import importlib.util
import json
import sys
import types
import urllib.request
import uuid
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy.orm import DeclarativeBase


SERVICES_PATH = (
	Path(__file__).resolve().parents[2]
	/ "pgappforge/plugins/erp/platform/social/services.py"
)


class _Base(DeclarativeBase):
	pass


class Actor(_Base):
	__tablename__ = "test_social_actor"

	id = Column(String(36), primary_key=True)
	tenant_id = Column(String(36), nullable=False)
	actor_id = Column(String(200), nullable=False)
	username = Column(String(100), nullable=False)
	display_name = Column(String(255), nullable=True)
	actor_type = Column(String(15), nullable=False)
	inbox_url = Column(String(500), nullable=True)
	outbox_url = Column(String(500), nullable=True)
	followers_url = Column(String(500), nullable=True)
	following_url = Column(String(500), nullable=True)
	profile_url = Column(String(500), nullable=True)
	public_key_pem = Column(String(500), nullable=True)
	is_local = Column(Boolean, nullable=False, default=False)
	domain = Column(String(255), nullable=True)


class SocialActivity(_Base):
	__tablename__ = "test_social_activity"

	id = Column(String(36), primary_key=True)
	tenant_id = Column(String(36), nullable=False)
	activity_id = Column(String(200), nullable=False)
	actor_id = Column(String(36), nullable=False)
	activity_type = Column(String(15), nullable=False)
	object_type = Column(String(100), nullable=True)
	object_id = Column(String(500), nullable=True)
	published_at = Column(DateTime, nullable=True)
	visibility = Column(String(10), nullable=False, default="PUBLIC")
	is_local = Column(Boolean, nullable=False, default=False)

	def __init__(self, **kwargs):
		object_content = kwargs.pop("object_content", None)
		super().__init__(**kwargs)
		self.object_content = object_content


class Follow(_Base):
	__tablename__ = "test_social_follow"

	id = Column(String(36), primary_key=True)
	follower_id = Column(String(36), nullable=False)
	following_id = Column(String(36), nullable=False)
	status = Column(String(20), nullable=False)


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
def social_module(monkeypatch: pytest.MonkeyPatch):
	for module_name in (
		"pgappforge",
		"pgappforge.plugins",
		"pgappforge.plugins.erp",
		"pgappforge.plugins.erp.platform",
		"pgappforge.plugins.erp.platform.social",
		"pgappforge.plugins.erp.foundation",
	):
		_install_module(monkeypatch, module_name)

	models = _install_module(monkeypatch, "pgappforge.plugins.erp.platform.social.models")
	models.Actor = Actor
	models.SocialActivity = SocialActivity
	models.Follow = Follow

	events = _install_module(monkeypatch, "pgappforge.plugins.erp.platform.social.events")
	events.ActivityFederatedEvent = _Event
	events.ActivityReceivedEvent = _Event

	foundation_events = _install_module(
		monkeypatch,
		"pgappforge.plugins.erp.foundation.events",
	)
	foundation_events.emit_event = lambda event, session: None

	spec = importlib.util.spec_from_file_location(
		"pgappforge.plugins.erp.platform.social.services",
		SERVICES_PATH,
	)
	assert spec is not None
	assert spec.loader is not None
	module = importlib.util.module_from_spec(spec)
	monkeypatch.setitem(sys.modules, spec.name, module)
	spec.loader.exec_module(module)
	module._test_foundation_events = foundation_events
	return module


class _FakeHTTPResponse:
	def __init__(self, payload: dict, *, status: int = 200):
		self.payload = json.dumps(payload).encode()
		self.status = status

	def __enter__(self):
		return self

	def __exit__(self, exc_type, exc, tb):
		return False

	def read(self, limit=-1):
		if limit is None or limit < 0:
			return self.payload
		return self.payload[:limit]


class _ScalarResult:
	def __init__(self, value):
		self.value = value

	def scalar_one_or_none(self):
		return self.value


class _FederationSession:
	def __init__(self):
		self.activity = SimpleNamespace(
			id="activity-db-id",
			tenant_id="tenant-1",
			activity_id="https://social.example/activities/1",
			activity_type="CREATE",
			actor_id="actor-db-id",
			object_content={"type": "Note", "content": "hello"},
			object_id=None,
			published_at=datetime.now(timezone.utc),
			visibility="PUBLIC",
		)
		self.actor = SimpleNamespace(
			id="actor-db-id",
			actor_id="https://social.example/users/local",
		)
		self.executed = []

	def execute(self, stmt):
		self.executed.append(stmt)
		return _ScalarResult(self.activity)

	def get(self, model, key):
		if key == self.actor.id:
			return self.actor
		return None


class _ReceiveSession:
	def __init__(self):
		self.results = []
		self.added = []
		self.executed = []

	def execute(self, stmt):
		self.executed.append(stmt)
		value = self.results.pop(0) if self.results else None
		return _ScalarResult(value)

	def add(self, obj):
		if getattr(obj, "id", None) is None:
			obj.id = str(uuid.uuid4())
		self.added.append(obj)

	def flush(self):
		return None


def test_social_remote_domain_rejects_private_and_internal_hosts(social_module):
	FederatedSocialService = social_module.FederatedSocialService
	SocialServiceError = social_module.SocialServiceError

	for domain in [
		"localhost",
		"127.0.0.1",
		"10.0.0.1",
		"metadata.google.internal",
		"social.local",
		"intranet",
		"remote.example:8443",
	]:
		with pytest.raises(SocialServiceError):
			FederatedSocialService._normalize_remote_domain(domain)


def test_social_remote_url_requires_safe_https_public_dns(social_module):
	FederatedSocialService = social_module.FederatedSocialService
	SocialServiceError = social_module.SocialServiceError

	assert (
		FederatedSocialService._normalize_remote_url(
			"https://Remote.EXAMPLE/users/alice",
			"actor_url",
			allowed_domain="remote.example",
		)
		== "https://remote.example/users/alice"
	)

	for url in [
		"http://remote.example/users/alice",
		"https://127.0.0.1/users/alice",
		"https://localhost/users/alice",
		"https://remote.example:8443/users/alice",
		"https://evil.example/users/alice",
		"https://user:pass@remote.example/users/alice",
	]:
		with pytest.raises(SocialServiceError):
			FederatedSocialService._normalize_remote_url(
				url,
				"actor_url",
				allowed_domain="remote.example",
			)


def test_webfinger_rejects_private_domain_before_network(monkeypatch, social_module):
	FederatedSocialService = social_module.FederatedSocialService

	def fail_urlopen(*args, **kwargs):
		raise AssertionError("urlopen should not be called for unsafe domains")

	monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

	result = FederatedSocialService()._webfinger_lookup(
		SimpleNamespace(),
		"tenant-1",
		"alice",
		"localhost",
	)

	assert result is None


def test_webfinger_rejects_private_actor_url_before_second_fetch(
	monkeypatch,
	social_module,
):
	FederatedSocialService = social_module.FederatedSocialService

	calls = []

	def fake_urlopen(url, timeout):
		calls.append(url)
		return _FakeHTTPResponse({
			"links": [{
				"rel": "self",
				"type": "application/activity+json",
				"href": "https://127.0.0.1/users/alice",
			}],
		})

	monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

	result = FederatedSocialService()._webfinger_lookup(
		SimpleNamespace(),
		"tenant-1",
		"alice",
		"remote.example",
	)

	assert result is None
	assert calls == [
		"https://remote.example/.well-known/webfinger?resource=acct%3Aalice%40remote.example"
	]


def test_federate_activity_skips_unsafe_inboxes_before_urlopen(
	monkeypatch,
	social_module,
):
	FederatedSocialService = social_module.FederatedSocialService

	def fail_urlopen(*args, **kwargs):
		raise AssertionError("urlopen should not be called for unsafe inboxes")

	monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

	result = FederatedSocialService().federate_activity(
		_FederationSession(),
		"activity-db-id",
		recipient_inboxes=[
			"http://remote.example/inbox",
			"https://localhost/inbox",
			"https://127.0.0.1/inbox",
		],
	)

	assert result == {"delivered": 0, "failed": 3, "inboxes": []}


def test_federation_inbox_normalization_dedupes_and_counts_rejections(social_module):
	FederatedSocialService = social_module.FederatedSocialService

	inboxes, rejected = FederatedSocialService._normalize_recipient_inboxes([
		"https://remote.example/inbox",
		"https://REMOTE.example/inbox",
		"https://localhost/inbox",
	])

	assert inboxes == ["https://remote.example/inbox"]
	assert rejected == 1


def test_receive_activity_rejects_unsafe_actor_before_persistence(social_module):
	FederatedSocialService = social_module.FederatedSocialService
	SocialServiceError = social_module.SocialServiceError

	session = _ReceiveSession()
	payload = json.dumps({
		"id": "https://remote.example/activities/1",
		"type": "Create",
		"actor": "https://127.0.0.1/users/alice",
		"object": {
			"id": "https://remote.example/objects/1",
			"type": "Note",
			"content": "hello",
		},
	})

	with pytest.raises(SocialServiceError, match="activity.actor"):
		FederatedSocialService().receive_activity(session, "tenant-1", payload)

	assert session.added == []


def test_receive_activity_rejects_activity_id_from_actor_confusion_domain(social_module):
	FederatedSocialService = social_module.FederatedSocialService
	SocialServiceError = social_module.SocialServiceError

	session = _ReceiveSession()
	payload = json.dumps({
		"id": "https://spoof.example/activities/1",
		"type": "Create",
		"actor": "https://remote.example/users/alice",
		"object": {
			"id": "https://remote.example/objects/1",
			"type": "Note",
			"content": "hello",
		},
	})

	with pytest.raises(SocialServiceError, match="activity.id host"):
		FederatedSocialService().receive_activity(session, "tenant-1", payload)

	assert session.added == []


def test_receive_activity_rejects_oversized_object_before_persistence(social_module):
	FederatedSocialService = social_module.FederatedSocialService
	SocialServiceError = social_module.SocialServiceError

	session = _ReceiveSession()
	payload = json.dumps({
		"id": "https://remote.example/activities/1",
		"type": "Create",
		"actor": "https://remote.example/users/alice",
		"object": {
			"id": "https://remote.example/objects/1",
			"type": "Note",
			"content": "x" * 130_000,
		},
	})

	with pytest.raises(SocialServiceError, match="activity.object"):
		FederatedSocialService().receive_activity(session, "tenant-1", payload)

	assert session.added == []


def test_receive_activity_ignores_unknown_type_before_persistence(social_module):
	FederatedSocialService = social_module.FederatedSocialService

	session = _ReceiveSession()
	payload = json.dumps({
		"id": "https://remote.example/activities/1",
		"type": "Exploit",
		"actor": "https://remote.example/users/alice",
		"object": {"type": "Note"},
	})

	FederatedSocialService().receive_activity(session, "tenant-1", payload)

	assert session.added == []


def test_receive_activity_persists_valid_bounded_activity(monkeypatch, social_module):
	FederatedSocialService = social_module.FederatedSocialService

	emitted = []
	monkeypatch.setattr(
		social_module._test_foundation_events,
		"emit_event",
		lambda event, session: emitted.append(event),
	)

	session = _ReceiveSession()
	payload = json.dumps({
		"id": "https://remote.example/activities/1",
		"type": "Create",
		"actor": "https://remote.example/users/alice",
		"object": {
			"id": "https://remote.example/objects/1",
			"type": "Note",
			"content": "hello",
		},
	})

	FederatedSocialService().receive_activity(session, "tenant-1", payload)

	assert len(session.added) == 2
	actor, activity = session.added
	assert actor.actor_id == "https://remote.example/users/alice"
	assert actor.username == "alice"
	assert actor.domain == "remote.example"
	assert activity.activity_id == "https://remote.example/activities/1"
	assert activity.activity_type == "CREATE"
	assert activity.object_id == "https://remote.example/objects/1"
	assert activity.object_content["content"] == "hello"
	assert len(emitted) == 1
