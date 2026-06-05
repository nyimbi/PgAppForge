"""
tests/ci/test_rules_engine.py

Unit tests for RulesEngine (pgappforge/plugins/rules/engine.py).

Strategy
--------
- Pure-logic tests: _evaluate_conditions, _execute_actions, operator table,
  cache, singleton — no real DB, no Flask context needed.
- Session and model dependencies are provided via MagicMock.
- _load_rules is monkey-patched where needed so DB is never hit.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from pgappforge.plugins.rules.engine import (
	RulesEngine,
	RulesValidationError,
	_OPS,
	_SIMPLE_CACHE,
	get_rules_engine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> RulesEngine:
	"""Engine with a dummy session factory so _get_session() never fails."""
	return RulesEngine(session_factory=lambda: MagicMock(), cache_ttl=30.0)


def _make_record(**kwargs):
	"""Plain object whose attributes mirror kwargs."""
	obj = MagicMock()
	for k, v in kwargs.items():
		setattr(obj, k, v)
	# Ensure type(record).__name__ is predictable for set_field tests
	type(obj).__name__ = "FakeModel"
	# Default: no mutable-fields restriction
	type(obj)._rules_mutable_fields = frozenset()
	return obj


def _cond(field, op, value, logic="AND") -> dict:
	return {"field": field, "op": op, "value": value, "logic": logic}


# ---------------------------------------------------------------------------
# _evaluate_conditions
# ---------------------------------------------------------------------------

class TestEvaluateConditions:

	def setup_method(self):
		self.eng = _make_engine()

	def test_empty_conditions_returns_true(self):
		assert self.eng._evaluate_conditions([], {}) is True

	def test_single_and_match(self):
		conds = [_cond("status", "=", "active")]
		assert self.eng._evaluate_conditions(conds, {"status": "active"}) is True

	def test_single_and_no_match(self):
		conds = [_cond("status", "=", "active")]
		assert self.eng._evaluate_conditions(conds, {"status": "draft"}) is False

	# Operator truth-table --------------------------------------------------

	@pytest.mark.parametrize("op,actual,value,expected", [
		# equality
		("=",            "x",   "x",        True),
		("=",            "x",   "y",        False),
		("!=",           "x",   "y",        True),
		("!=",           "x",   "x",        False),
		# comparison
		(">",            10,    5,          True),
		(">",            5,     10,         False),
		("<",            3,     9,          True),
		("<",            9,     3,          False),
		(">=",           5,     5,          True),
		(">=",           4,     5,          False),
		("<=",           5,     5,          True),
		("<=",           6,     5,          False),
		# string ops
		("contains",     "hello world", "world", True),
		("contains",     "hello world", "xyz",   False),
		("starts_with",  "foobar", "foo",        True),
		("starts_with",  "foobar", "bar",        False),
		# membership
		("in",           "b",   ["a","b","c"],   True),
		("in",           "z",   ["a","b","c"],   False),
		# null checks (value param ignored)
		("is_null",      None,  None,        True),
		("is_null",      "x",   None,        False),
		("is_not_null",  "x",   None,        True),
		("is_not_null",  None,  None,        False),
	])
	def test_all_operators(self, op, actual, value, expected):
		conds = [_cond("f", op, value)]
		result = self.eng._evaluate_conditions(conds, {"f": actual})
		assert result is expected

	def test_and_conditions_require_all(self):
		conds = [
			_cond("a", "=", 1),
			_cond("b", "=", 2),
		]
		assert self.eng._evaluate_conditions(conds, {"a": 1, "b": 2}) is True
		assert self.eng._evaluate_conditions(conds, {"a": 1, "b": 99}) is False

	def test_or_conditions_require_any(self):
		conds = [
			_cond("x", "=", 1, logic="OR"),
			_cond("x", "=", 2, logic="OR"),
		]
		assert self.eng._evaluate_conditions(conds, {"x": 2}) is True
		assert self.eng._evaluate_conditions(conds, {"x": 99}) is False

	def test_or_group_combined_with_and(self):
		# AND condition must be true AND at least one OR must be true
		conds = [
			_cond("status", "=", "active", logic="AND"),
			_cond("score",  ">", 50,       logic="OR"),
			_cond("score",  "<", 10,       logic="OR"),
		]
		# AND true, OR satisfied (score=60 > 50)
		assert self.eng._evaluate_conditions(conds, {"status": "active", "score": 60}) is True
		# AND false → whole thing false regardless of OR
		assert self.eng._evaluate_conditions(conds, {"status": "draft",  "score": 60}) is False
		# AND true, but OR unsatisfied (score=30 not >50 and not <10)
		assert self.eng._evaluate_conditions(conds, {"status": "active", "score": 30}) is False

	def test_unknown_op_returns_false(self):
		conds = [_cond("f", "gibberish", "v")]
		assert self.eng._evaluate_conditions(conds, {"f": "v"}) is False

	def test_missing_field_defaults_to_none(self):
		# is_null on a missing field → actual=None → True
		conds = [_cond("no_such_field", "is_null", None)]
		assert self.eng._evaluate_conditions(conds, {}) is True


# ---------------------------------------------------------------------------
# _execute_actions — block
# ---------------------------------------------------------------------------

class TestBlockAction:

	def setup_method(self):
		self.eng = _make_engine()
		self.session = MagicMock()

	def test_block_raises_rules_validation_error(self):
		record = _make_record()
		actions = [{"type": "block", "message": "You shall not pass"}]
		with pytest.raises(RulesValidationError, match="You shall not pass"):
			self.eng._execute_actions(actions, {}, record, self.session)

	def test_block_uses_default_message_when_none(self):
		record = _make_record()
		actions = [{"type": "block"}]
		with pytest.raises(RulesValidationError, match="blocked by business rule"):
			self.eng._execute_actions(actions, {}, record, self.session)

	def test_block_runs_before_set_field(self):
		"""block action in the list must fire before set_field, even if listed after."""
		record = _make_record(name="original")
		type(record)._rules_mutable_fields = frozenset({"name"})
		actions = [
			{"type": "set_field", "field": "name", "value": "mutated"},
			{"type": "block", "message": "stop"},
		]
		with pytest.raises(RulesValidationError):
			self.eng._execute_actions(actions, {}, record, self.session)
		# name must NOT have been mutated — block fired first
		assert record.name == "original"


# ---------------------------------------------------------------------------
# _execute_actions — set_field
# ---------------------------------------------------------------------------

class TestSetFieldAction:

	def setup_method(self):
		self.eng = _make_engine()
		self.session = MagicMock()

	def test_set_field_applies_when_mutable_fields_empty(self):
		"""Empty frozenset means 'all fields allowed' (except the hard-blocked ones)."""
		record = _make_record(status="draft")
		type(record)._rules_mutable_fields = frozenset()
		actions = [{"type": "set_field", "field": "status", "value": "active"}]
		self.eng._execute_actions(actions, {}, record, self.session)
		assert record.status == "active"

	def test_set_field_respects_mutable_fields_allowlist(self):
		"""Field not in non-empty mutable list is silently skipped."""
		record = _make_record(status="draft", priority="low")
		type(record)._rules_mutable_fields = frozenset({"priority"})
		actions = [{"type": "set_field", "field": "status", "value": "active"}]
		self.eng._execute_actions(actions, {}, record, self.session)
		assert record.status == "draft"  # blocked — not in mutable list

	def test_set_field_applies_when_field_in_mutable_list(self):
		record = _make_record(priority="low")
		type(record)._rules_mutable_fields = frozenset({"priority"})
		actions = [{"type": "set_field", "field": "priority", "value": "high"}]
		self.eng._execute_actions(actions, {}, record, self.session)
		assert record.priority == "high"

	@pytest.mark.parametrize("protected_field", [
		"id", "password", "password_hash", "is_admin", "tenant_id", "owner_id", "created_by_id",
	])
	def test_set_field_blocked_on_protected_fields(self, protected_field):
		"""Hard-blocked fields cannot be mutated even if listed in _rules_mutable_fields."""
		record = _make_record()
		setattr(record, protected_field, "original")
		type(record)._rules_mutable_fields = frozenset({protected_field})
		actions = [{"type": "set_field", "field": protected_field, "value": "hacked"}]
		self.eng._execute_actions(actions, {}, record, self.session)
		assert getattr(record, protected_field) == "original"

	def test_set_field_empty_field_name_is_skipped(self):
		record = _make_record()
		actions = [{"type": "set_field", "field": "", "value": "x"}]
		# Should not raise
		self.eng._execute_actions(actions, {}, record, self.session)


# ---------------------------------------------------------------------------
# _execute_actions — call_webhook
# ---------------------------------------------------------------------------

class TestCallWebhookAction:

	def setup_method(self):
		self.eng = _make_engine()
		self.session = MagicMock()

	def _make_app_mock(self, allowlist):
		"""Return a Flask app mock whose config.get returns the given allowlist."""
		cfg = {"FAB_RULES_WEBHOOK_ALLOWLIST": allowlist, "FAB_RULES_WEBHOOK_TIMEOUT": 5}
		mock_app = MagicMock()
		mock_app.config.get.side_effect = lambda k, d=None: cfg.get(k, d)
		return mock_app

	def _run(self, url, allowlist=None, record=None, extra_patches=()):
		record = record or _make_record()
		actions = [{"type": "call_webhook", "url": url}]
		mock_app = self._make_app_mock(allowlist or [])
		# current_app is imported lazily inside _execute_actions as:
		#   from flask import current_app
		# We must patch the name in the flask module itself so the local import
		# picks up the mock.
		with patch("flask.current_app", mock_app, create=True):
			outcome, _mutated = self.eng._execute_actions(actions, {}, record, self.session)
			return outcome

	def test_call_webhook_skipped_when_allowlist_empty(self):
		outcome = self._run("https://example.com/hook", allowlist=[])
		assert outcome == "executed"  # no error, just skipped silently

	def test_call_webhook_rejects_http_scheme(self):
		mock_app = self._make_app_mock(["example.com"])
		with patch("flask.current_app", mock_app, create=True):
			record = _make_record()
			actions = [{"type": "call_webhook", "url": "http://example.com/hook"}]
			outcome, _mutated = self.eng._execute_actions(actions, {}, record, self.session)
		assert outcome == "webhook_error"

	def test_call_webhook_rejects_private_ip(self):
		mock_app = self._make_app_mock(["internal.corp"])
		with patch("flask.current_app", mock_app, create=True), \
			 patch("socket.getaddrinfo") as mock_gai:
			mock_gai.return_value = [(None, None, None, None, ("192.168.1.1", 0))]
			record = _make_record()
			actions = [{"type": "call_webhook", "url": "https://internal.corp/hook"}]
			outcome, _mutated = self.eng._execute_actions(actions, {}, record, self.session)
		assert outcome == "webhook_error"

	def test_call_webhook_rejects_host_not_in_allowlist(self):
		mock_app = self._make_app_mock(["example.com"])
		with patch("flask.current_app", mock_app, create=True), \
			 patch("socket.getaddrinfo") as mock_gai:
			mock_gai.return_value = [(None, None, None, None, ("93.184.216.34", 0))]
			record = _make_record()
			actions = [{"type": "call_webhook", "url": "https://notallowed.com/hook"}]
			outcome, _mutated = self.eng._execute_actions(actions, {}, record, self.session)
		assert outcome == "webhook_error"

	def test_call_webhook_skipped_when_url_empty(self):
		record = _make_record()
		actions = [{"type": "call_webhook", "url": ""}]
		# Empty URL → continue before any allowlist check — no Flask context needed
		outcome, _mutated = self.eng._execute_actions(actions, {}, record, self.session)
		assert outcome == "executed"


# ---------------------------------------------------------------------------
# _log_execution — audit session is separate
# ---------------------------------------------------------------------------

class TestAuditSession:

	def setup_method(self):
		self.eng = _make_engine()

	def test_audit_session_is_separate_from_business_session(self):
		"""_log_execution must open its own SASession, not use the caller's session."""
		rule = MagicMock()
		rule.id = 42
		rule.name = "test_rule"
		record = MagicMock()
		record.id = 1

		bind = MagicMock()
		biz_session = MagicMock()
		biz_session.get_bind.return_value = bind

		audit_sessions: list = []

		class _FakeAuditSession:
			def __init__(self, bind):
				audit_sessions.append(self)
				self._added = []
			def __enter__(self): return self
			def __exit__(self, *a): pass
			def add(self, obj): self._added.append(obj)
			def commit(self): pass

		# _log_execution lazy-imports:
		#   from pgappforge.plugins.rules.models import RuleExecution
		#   from sqlalchemy.orm import Session as SASession
		# Patch both at their origin modules.
		import sys
		# Ensure the models module stub is in sys.modules so the lazy import resolves
		mock_models = MagicMock()
		mock_models.RuleExecution = MagicMock()
		with patch.dict("sys.modules", {"pgappforge.plugins.rules.models": mock_models}), \
			 patch("sqlalchemy.orm.Session", _FakeAuditSession):
			self.eng._log_execution(rule, record, "executed", biz_session)

		assert len(audit_sessions) == 1, "Expected exactly one separate audit session"
		# The business session's add/commit must NOT have been called
		biz_session.add.assert_not_called()

	def test_audit_log_swallows_failure_silently(self):
		"""If audit logging fails, must not propagate to caller."""
		rule = MagicMock()
		rule.id = 1
		record = MagicMock()
		record.id = 1
		session = MagicMock()
		session.get_bind.side_effect = RuntimeError("db down")

		# Should not raise
		self.eng._log_execution(rule, record, "executed", session)

	def test_audit_log_skips_skipped_outcome(self):
		"""outcome='skipped' must not write any audit row."""
		rule = MagicMock()
		record = MagicMock()
		session = MagicMock()

		# _log_execution imports Session lazily; patch at source
		with patch("sqlalchemy.orm.Session") as MockSess:
			self.eng._log_execution(rule, record, "skipped", session)
		MockSess.assert_not_called()


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

class TestCache:

	def setup_method(self):
		_SIMPLE_CACHE.clear()
		self.eng = RulesEngine(session_factory=lambda: MagicMock(), cache_ttl=30.0)

	def teardown_method(self):
		_SIMPLE_CACHE.clear()

	def test_cache_returns_cached_rules_on_second_call(self):
		fake_rules = [MagicMock(), MagicMock()]
		session = MagicMock()

		with patch("pgappforge.plugins.rules.engine.RulesEngine._load_rules",
				   wraps=self.eng._load_rules) as spy:
			# Seed cache manually
			_SIMPLE_CACHE["Widget"] = (time.monotonic(), fake_rules)
			result = self.eng._load_rules(session, "Widget")

		assert result is fake_rules

	def test_cache_expires_after_ttl(self):
		"""A stale cache entry (age > TTL) is not served from cache."""
		fake_rules_v1 = [MagicMock()]
		stale_ts = time.monotonic() - 9999
		_SIMPLE_CACHE["Widget"] = (stale_ts, fake_rules_v1)

		# Verify the staleness guard: (now - ts) >= ttl → cache miss
		now = time.monotonic()
		entry_ts, _ = _SIMPLE_CACHE["Widget"]
		assert (now - entry_ts) >= self.eng._cache_ttl, "Entry should be stale"

		# Simulate a fresh DB fetch.
		# _load_rules does:
		#   from pgappforge.plugins.rules.models import RuleSet, Rule
		#   from sqlalchemy import select as sa_select
		#   from sqlalchemy.orm import selectinload
		# We must patch sa_select so it never receives a MagicMock (SA rejects those).
		fresh_rules = [MagicMock(), MagicMock()]
		mock_models = MagicMock()
		mock_models.RuleSet = MagicMock()
		mock_models.Rule    = MagicMock()

		session = MagicMock()
		# Make session.execute(...).scalars().all() return fresh_rules regardless of query
		session.execute.return_value.scalars.return_value.all.return_value = fresh_rules

		mock_select = MagicMock(return_value=MagicMock())

		with patch.dict("sys.modules", {"pgappforge.plugins.rules.models": mock_models}), \
			 patch("sqlalchemy.select", mock_select), \
			 patch("sqlalchemy.orm.selectinload", MagicMock(return_value=MagicMock())):
			result = self.eng._load_rules(session, "Widget")

		assert result is fresh_rules
		# Cache should now hold the fresh entry with an updated timestamp
		assert _SIMPLE_CACHE["Widget"][1] is fresh_rules
		assert _SIMPLE_CACHE["Widget"][0] > stale_ts

	def test_cache_invalidate_clears_specific_entry(self):
		_SIMPLE_CACHE["Widget"] = (time.monotonic(), [])
		_SIMPLE_CACHE["Invoice"] = (time.monotonic(), [])
		self.eng.invalidate("Widget")
		assert "Widget" not in _SIMPLE_CACHE
		assert "Invoice" in _SIMPLE_CACHE

	def test_cache_invalidate_none_clears_all(self):
		_SIMPLE_CACHE["A"] = (time.monotonic(), [])
		_SIMPLE_CACHE["B"] = (time.monotonic(), [])
		self.eng.invalidate()
		assert len(_SIMPLE_CACHE) == 0

	def test_cache_invalidate_missing_key_is_noop(self):
		self.eng.invalidate("DoesNotExist")  # must not raise


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:

	def test_get_rules_engine_returns_singleton(self):
		import pgappforge.plugins.rules.engine as _mod
		orig = _mod._engine
		try:
			_mod._engine = None
			e1 = get_rules_engine()
			e2 = get_rules_engine()
			assert e1 is e2
			assert isinstance(e1, RulesEngine)
		finally:
			_mod._engine = orig

	def test_get_rules_engine_reuses_existing_instance(self):
		import pgappforge.plugins.rules.engine as _mod
		orig = _mod._engine
		try:
			sentinel = RulesEngine()
			_mod._engine = sentinel
			result = get_rules_engine()
			assert result is sentinel
		finally:
			_mod._engine = orig


# ---------------------------------------------------------------------------
# _event_matches
# ---------------------------------------------------------------------------

class TestEventMatches:

	def setup_method(self):
		self.eng = _make_engine()

	def test_exact_match(self):
		assert self.eng._event_matches("on_create", "on_create", MagicMock()) is True

	def test_exact_no_match(self):
		assert self.eng._event_matches("on_create", "on_update", MagicMock()) is False

	def test_unknown_trigger_with_colon_but_wrong_prefix(self):
		record = MagicMock()
		assert self.eng._event_matches("on_something:field", "on_create", record) is False
