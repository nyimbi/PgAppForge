"""Focused guardrail tests for ActivityPub federation egress."""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


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


def test_social_remote_domain_rejects_private_and_internal_hosts():
	from pgappforge.plugins.erp.platform.social.services import (
		FederatedSocialService,
		SocialServiceError,
	)

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


def test_social_remote_url_requires_safe_https_public_dns():
	from pgappforge.plugins.erp.platform.social.services import (
		FederatedSocialService,
		SocialServiceError,
	)

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


def test_webfinger_rejects_private_domain_before_network(monkeypatch):
	from pgappforge.plugins.erp.platform.social.services import FederatedSocialService

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


def test_webfinger_rejects_private_actor_url_before_second_fetch(monkeypatch):
	from pgappforge.plugins.erp.platform.social.services import FederatedSocialService

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


def test_federate_activity_skips_unsafe_inboxes_before_urlopen(monkeypatch):
	from pgappforge.plugins.erp.platform.social.services import FederatedSocialService

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


def test_federation_inbox_normalization_dedupes_and_counts_rejections():
	from pgappforge.plugins.erp.platform.social.services import FederatedSocialService

	inboxes, rejected = FederatedSocialService._normalize_recipient_inboxes([
		"https://remote.example/inbox",
		"https://REMOTE.example/inbox",
		"https://localhost/inbox",
	])

	assert inboxes == ["https://remote.example/inbox"]
	assert rejected == 1
