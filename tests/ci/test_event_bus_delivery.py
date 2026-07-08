"""
Focused CI tests for platform event delivery reliability.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from pgappforge.plugins.erp.foundation.events import DomainEvent
from pgappforge.plugins.erp.platform.events.events import EventBus
from pgappforge.plugins.erp.platform.events.services import (
	EventBusService,
	EventBusServiceError,
)


class _ScalarResult:
	def __init__(self, rows):
		self._rows = rows

	def scalars(self):
		return self

	def all(self):
		return list(self._rows)


class _FakeSession:
	def __init__(self, subscriptions):
		self.subscriptions = subscriptions
		self.added = []

	def execute(self, _statement):
		return _ScalarResult(self.subscriptions)

	def add(self, row):
		self.added.append(row)


def _subscription(**overrides):
	values = {
		"id": "sub-1",
		"handler_function": "tests.fake.handle_event",
		"retry_count": 2,
		"dead_letter_after": 3,
	}
	values.update(overrides)
	return SimpleNamespace(**values)


def _event():
	return DomainEvent(
		event_id="evt-1",
		event_type="invoice.paid",
		aggregate_id="inv-1",
		aggregate_type="Invoice",
		tenant_id="tenant-1",
	)


def _delivery_logs(session):
	return [
		row
		for row in session.added
		if row.__class__.__name__ == "EventDeliveryLog"
	]


def _domain_event_logs(session):
	return [
		row
		for row in session.added
		if row.__class__.__name__ == "DomainEventLog"
	]


def test_delivery_retries_and_dead_letters_after_terminal_failure():
	calls = []

	def always_fail(event):
		calls.append(event.event_id)
		raise RuntimeError("downstream unavailable")

	bus = EventBus()
	bus._resolve_handler = lambda _path: always_fail
	session = _FakeSession([_subscription()])

	bus._deliver(_event(), session)

	logs = _delivery_logs(session)
	assert len(calls) == 2
	assert [row.delivery_attempt for row in logs] == [1, 2]
	assert [row.status for row in logs] == ["FAILED", "DEAD_LETTER"]
	assert all("downstream unavailable" in row.error_message for row in logs)

	outcome_events = _domain_event_logs(session)
	assert [row.event_type for row in outcome_events] == [
		"event.delivery.failed",
		"event.delivery.failed",
		"event.delivery.dead_lettered",
	]


def test_delivery_logs_success_after_retry_without_dead_letter():
	calls = []

	def flaky_handler(event):
		calls.append(event.event_id)
		if len(calls) == 1:
			raise RuntimeError("temporary outage")

	bus = EventBus()
	bus._resolve_handler = lambda _path: flaky_handler
	session = _FakeSession([_subscription(retry_count=3, dead_letter_after=3)])

	bus._deliver(_event(), session)

	logs = _delivery_logs(session)
	assert len(calls) == 2
	assert [row.delivery_attempt for row in logs] == [1, 2]
	assert [row.status for row in logs] == ["FAILED", "DELIVERED"]
	assert [row.event_type for row in _domain_event_logs(session)] == [
		"event.delivery.failed",
	]


def test_missing_handler_is_dead_lettered_once():
	bus = EventBus()
	bus._resolve_handler = lambda _path: None
	session = _FakeSession([_subscription(retry_count=5, dead_letter_after=5)])

	bus._deliver(_event(), session)

	logs = _delivery_logs(session)
	assert len(logs) == 1
	assert logs[0].delivery_attempt == 1
	assert logs[0].status == "DEAD_LETTER"
	assert "Cannot resolve handler" in logs[0].error_message


def test_create_subscription_rejects_invalid_retry_policy():
	service = EventBusService()
	with pytest.raises(EventBusServiceError, match="retry_count cannot exceed"):
		service.create_subscription(
			object(),
			subscriber_plugin="finance.gl",
			event_type="invoice.paid",
			handler_function="tests.fake.handle_event",
			retry_count=4,
			dead_letter_after=3,
		)


def test_create_subscription_rejects_non_positive_retry_policy():
	service = EventBusService()
	with pytest.raises(EventBusServiceError, match="retry_count"):
		service.create_subscription(
			object(),
			subscriber_plugin="finance.gl",
			event_type="invoice.paid",
			handler_function="tests.fake.handle_event",
			retry_count=0,
			dead_letter_after=3,
		)
