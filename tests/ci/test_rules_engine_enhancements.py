"""
tests/ci/test_rules_engine_enhancements.py

Tests for Rules Engine enhancements (E1-E20).

Uses real RulesEngine instances with mocked sessions to avoid DB dependency.
All tests are synchronous and self-contained.
"""
from __future__ import annotations

import time
import unittest.mock as mock

import pytest

from pgappforge.plugins.rules.engine import (
	RulesEngine,
	RulesFieldError,
	RulesValidationError,
	_OPS,
	_SIMPLE_CACHE,
	_resolve_value,
	get_rules_engine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine() -> RulesEngine:
	return RulesEngine(session_factory=lambda: mock.MagicMock(), cache_ttl=30.0)


_rule_id_counter = 0


def _make_rule(
	trigger: str,
	conditions: list,
	actions: list,
	name: str = "Test Rule",
	stop_after_actions: bool = False,
	stop_on_match: bool = False,
) -> mock.MagicMock:
	"""Build a mock Rule with a mock RuleSet. Each call gets a unique id."""
	global _rule_id_counter
	_rule_id_counter += 1
	rule = mock.MagicMock()
	rule.id = _rule_id_counter
	rule.name = name
	rule.trigger_event = trigger
	rule.conditions_json = conditions
	rule.actions_json = actions
	rule.enabled = True
	rule.order = 0
	rule.stop_after_actions = stop_after_actions
	ruleset = mock.MagicMock()
	ruleset.stop_on_match = stop_on_match
	rule.ruleset = ruleset
	return rule


def _make_engine_with_rules(rules_list: list) -> RulesEngine:
	"""Return an engine whose _load_rules is stubbed to return rules_list without DB."""
	engine = _make_engine()
	engine._load_rules = mock.Mock(return_value=rules_list)
	engine._record_to_dict = mock.Mock(return_value={})
	return engine


def _make_record(**kwargs):
	obj = mock.MagicMock()
	for k, v in kwargs.items():
		setattr(obj, k, v)
	type(obj).__name__ = "FakeModel"
	type(obj)._rules_mutable_fields = frozenset()
	return obj


# ---------------------------------------------------------------------------
# E1: RulesFieldError
# ---------------------------------------------------------------------------

class TestRulesFieldError:

	def test_is_subclass_of_validation_error(self):
		assert issubclass(RulesFieldError, RulesValidationError)

	def test_has_field_attribute(self):
		err = RulesFieldError("email", "Invalid email format")
		assert err.field == "email"

	def test_message_accessible_as_str(self):
		err = RulesFieldError("amount", "Must be positive")
		assert str(err) == "Must be positive"

	def test_field_name_preserved_on_arbitrary_fields(self):
		err = RulesFieldError("customer_id", "Customer not found")
		assert err.field == "customer_id"

	def test_empty_field_name_allowed(self):
		err = RulesFieldError("", "Generic error")
		assert err.field == ""

	def test_is_exception(self):
		err = RulesFieldError("x", "msg")
		assert isinstance(err, Exception)


# ---------------------------------------------------------------------------
# E2: New operators
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("op,a,b,expected", [
	# ends_with
	("ends_with",    "hello@pgaf.dev",  ".dev",       True),
	("ends_with",    "hello@pgaf.dev",  "@other.com", False),
	("ends_with",    "foobar",          "bar",        True),
	("ends_with",    "foobar",          "foo",        False),
	# matches_regex
	("matches_regex", "INV-2024-001",   r"INV-\d{4}-\d{3}", True),
	("matches_regex", "invalid",        r"INV-\d{4}-\d{3}", False),
	("matches_regex", "HELLO",          "hello",            True),   # IGNORECASE
	# not_in
	("not_in",       "x",  ["a", "b", "c"], True),
	("not_in",       "a",  ["a", "b"],      False),
	("not_in",       "z",  ["a", "b", "c"], True),
	# not_contains
	("not_contains", "hello world", "python", True),
	("not_contains", "hello world", "world",  False),
	# between
	("between",      5,    [1, 10],  True),
	("between",      1,    [1, 10],  True),   # inclusive lower bound
	("between",      10,   [1, 10],  True),   # inclusive upper bound
	("between",      0,    [1, 10],  False),
	("between",      11,   [1, 10],  False),
	# length_gt
	("length_gt",    "hello",   3, True),
	("length_gt",    "hi",      3, False),
	("length_gt",    "hey",     3, False),   # equal is not greater
	# length_lt
	("length_lt",    "hi",      3, True),
	("length_lt",    "hello",   3, False),
	("length_lt",    "hey",     3, False),   # equal is not less
])
class TestNewOperators:

	def test_operator(self, op, a, b, expected):
		fn = _OPS[op]
		assert fn(a, b) is expected


class TestNewOperatorEdgeCases:

	def test_between_with_non_list_b_returns_false(self):
		fn = _OPS["between"]
		assert fn(5, "not_a_list") is False

	def test_between_with_wrong_length_list_returns_false(self):
		fn = _OPS["between"]
		assert fn(5, [1]) is False

	def test_between_with_none_value_returns_false(self):
		fn = _OPS["between"]
		assert fn(None, [1, 10]) is False

	def test_between_empty_list_returns_false(self):
		fn = _OPS["between"]
		assert fn(5, []) is False

	def test_matches_regex_is_case_insensitive(self):
		fn = _OPS["matches_regex"]
		assert fn("HELLO WORLD", "hello") is True

	def test_ends_with_empty_suffix_always_true(self):
		fn = _OPS["ends_with"]
		assert fn("anything", "") is True

	def test_not_in_with_non_list_b_treated_as_single_item(self):
		fn = _OPS["not_in"]
		# non-list b is wrapped in a list — "z" not in ["scalar"] → True
		assert fn("z", "scalar") is True
		assert fn("scalar", "scalar") is False


# ---------------------------------------------------------------------------
# E3: Field-to-field comparison (_resolve_value with $ prefix)
# ---------------------------------------------------------------------------

class TestResolveValue:

	def test_dollar_prefix_resolves_to_field_value(self):
		assert _resolve_value("$status", {"status": "active"}) == "active"

	def test_dollar_prefix_missing_field_returns_none(self):
		assert _resolve_value("$missing", {}) is None

	def test_dollar_prefix_nested_key_not_resolved(self):
		# Only top-level key lookup, no dotted path
		assert _resolve_value("$a.b", {"a.b": "val"}) == "val"

	def test_template_substitution_single_pass(self):
		assert _resolve_value("Hello {{name}}", {"name": "Alice"}) == "Hello Alice"

	def test_template_multiple_substitutions(self):
		result = _resolve_value("{{first}} {{last}}", {"first": "Ada", "last": "Lovelace"})
		assert result == "Ada Lovelace"

	def test_template_missing_key_replaced_with_empty(self):
		result = _resolve_value("Hello {{missing}}", {})
		assert result == "Hello "

	def test_template_no_cross_field_injection(self):
		# Record has field "note" = "{{password}}" — should NOT expand to actual password
		# because the resolved value of {{note}} is the literal string "{{password}}",
		# and _resolve_value does a single pass, so that inner template is never expanded.
		ctx = {"note": "{{password}}", "password": "secret123"}
		result = _resolve_value("{{note}}", ctx)
		assert "secret123" not in result

	def test_template_sensitive_key_blocked(self):
		ctx = {"password": "secret"}
		result = _resolve_value("{{password}}", ctx)
		# Sensitive key left unreplaced
		assert "secret" not in result
		assert "{{password}}" in result

	def test_template_sensitive_key_token(self):
		ctx = {"api_key": "sk-abc123"}
		result = _resolve_value("Key: {{api_key}}", ctx)
		assert "sk-abc123" not in result

	def test_plain_value_returned_as_is(self):
		assert _resolve_value("literal", {}) == "literal"

	def test_non_string_int_returned_as_is(self):
		assert _resolve_value(42, {}) == 42

	def test_non_string_none_returned_as_is(self):
		assert _resolve_value(None, {}) is None

	def test_non_string_list_returned_as_is(self):
		lst = [1, 2, 3]
		assert _resolve_value(lst, {}) is lst

	def test_no_template_markers_returned_as_is(self):
		assert _resolve_value("no_braces_here", {"x": "y"}) == "no_braces_here"


# ---------------------------------------------------------------------------
# E5: Nested condition groups
# ---------------------------------------------------------------------------

class TestNestedConditions:

	def setup_method(self):
		self.eng = _make_engine()

	def _eval(self, conditions, ctx):
		return self.eng._evaluate_conditions(conditions, ctx)

	def test_and_group_all_must_match(self):
		conditions = [{
			"type": "group",
			"join": "AND",
			"conditions": [
				{"field": "a", "op": "=", "value": 1, "logic": "AND"},
				{"field": "b", "op": "=", "value": 2, "logic": "AND"},
			],
		}]
		assert self._eval(conditions, {"a": 1, "b": 2}) is True
		assert self._eval(conditions, {"a": 1, "b": 99}) is False
		assert self._eval(conditions, {"a": 99, "b": 2}) is False

	def test_or_group_any_must_match(self):
		conditions = [{
			"type": "group",
			"join": "OR",
			"conditions": [
				{"field": "status", "op": "=", "value": "active", "logic": "OR"},
				{"field": "status", "op": "=", "value": "pending", "logic": "OR"},
			],
			"logic": "OR",
		}]
		assert self._eval(conditions, {"status": "active"}) is True
		assert self._eval(conditions, {"status": "pending"}) is True
		assert self._eval(conditions, {"status": "archived"}) is False

	def test_nested_group_and_of_ors(self):
		# AND( OR(a=1, a=2), OR(b=10, b=20) )
		conditions = [
			{
				"type": "group",
				"join": "OR",
				"logic": "AND",
				"conditions": [
					{"field": "a", "op": "=", "value": 1, "logic": "OR"},
					{"field": "a", "op": "=", "value": 2, "logic": "OR"},
				],
			},
			{
				"type": "group",
				"join": "OR",
				"logic": "AND",
				"conditions": [
					{"field": "b", "op": "=", "value": 10, "logic": "OR"},
					{"field": "b", "op": "=", "value": 20, "logic": "OR"},
				],
			},
		]
		assert self._eval(conditions, {"a": 1, "b": 10}) is True
		assert self._eval(conditions, {"a": 2, "b": 20}) is True
		assert self._eval(conditions, {"a": 1, "b": 99}) is False   # second group fails
		assert self._eval(conditions, {"a": 99, "b": 10}) is False  # first group fails

	def test_empty_group_returns_true(self):
		conditions = [{"type": "group", "join": "AND", "conditions": []}]
		assert self._eval(conditions, {}) is True

	def test_group_with_single_failing_and_condition(self):
		conditions = [{
			"type": "group",
			"join": "AND",
			"logic": "AND",
			"conditions": [{"field": "x", "op": "=", "value": 1, "logic": "AND"}],
		}]
		assert self._eval(conditions, {"x": 99}) is False

	def test_mixed_flat_and_group(self):
		# flat AND condition AND a group
		conditions = [
			{"field": "role", "op": "=", "value": "admin", "logic": "AND"},
			{
				"type": "group",
				"join": "OR",
				"logic": "AND",
				"conditions": [
					{"field": "score", "op": ">", "value": 90, "logic": "OR"},
					{"field": "score", "op": "<", "value": 10, "logic": "OR"},
				],
			},
		]
		assert self._eval(conditions, {"role": "admin", "score": 95}) is True
		assert self._eval(conditions, {"role": "admin", "score": 5}) is True
		assert self._eval(conditions, {"role": "admin", "score": 50}) is False
		assert self._eval(conditions, {"role": "user", "score": 95}) is False


# ---------------------------------------------------------------------------
# E13: Dry-run API (evaluate_dry)
# ---------------------------------------------------------------------------

class TestEvaluateDry:

	def _make_rule(self, trigger, conditions, actions, name="Test Rule"):
		return _make_rule(trigger, conditions, actions, name=name)

	def _make_engine(self, rules):
		eng = _make_engine_with_rules(rules)
		return eng

	def test_dry_run_block_returns_would_block_true(self):
		rule = self._make_rule("on_create", [], [{"type": "block", "message": "Blocked"}])
		engine = self._make_engine([rule])
		record = mock.MagicMock()
		engine._record_to_dict = mock.Mock(return_value={"status": "draft"})
		result = engine.evaluate_dry("Order", "on_create", record, session=mock.MagicMock())
		assert result["would_block"] is True
		assert result["block_message"] == "Blocked"

	def test_dry_run_set_field_no_mutation(self):
		rule = self._make_rule("on_create", [], [{"type": "set_field", "field": "status", "value": "approved"}])
		engine = self._make_engine([rule])
		record = mock.MagicMock()
		record.status = "draft"
		engine._record_to_dict = mock.Mock(return_value={"status": "draft"})
		result = engine.evaluate_dry("Order", "on_create", record, session=mock.MagicMock())
		assert result["would_set"] == {"status": "approved"}
		# Record must NOT be mutated
		assert record.status == "draft"

	def test_dry_run_lists_matched_rules(self):
		rule1 = self._make_rule("on_create", [], [{"type": "set_field", "field": "x", "value": "1"}], name="Rule A")
		rule2 = self._make_rule("on_create", [], [{"type": "set_field", "field": "y", "value": "2"}], name="Rule B")
		engine = self._make_engine([rule1, rule2])
		engine._record_to_dict = mock.Mock(return_value={})
		result = engine.evaluate_dry("Order", "on_create", mock.MagicMock(), session=mock.MagicMock())
		assert "Rule A" in result["rules_matched"]
		assert "Rule B" in result["rules_matched"]

	def test_dry_run_email_listed_without_sending(self):
		rule = self._make_rule("on_create", [], [{
			"type": "send_email",
			"to": "user@example.com",
			"subject": "Hello",
		}])
		engine = self._make_engine([rule])
		engine._record_to_dict = mock.Mock(return_value={})
		result = engine.evaluate_dry("Order", "on_create", mock.MagicMock(), session=mock.MagicMock())
		assert len(result["would_send_emails"]) == 1
		assert result["would_send_emails"][0]["to"] == "user@example.com"
		assert result["would_send_emails"][0]["subject"] == "Hello"

	def test_dry_run_webhook_listed_without_calling(self):
		rule = self._make_rule("on_create", [], [{"type": "call_webhook", "url": "https://example.com/hook"}])
		engine = self._make_engine([rule])
		engine._record_to_dict = mock.Mock(return_value={})
		result = engine.evaluate_dry("Order", "on_create", mock.MagicMock(), session=mock.MagicMock())
		assert len(result["would_call_webhooks"]) == 1
		assert result["would_call_webhooks"][0]["url"] == "https://example.com/hook"

	def test_dry_run_no_matching_rules_returns_empty(self):
		rule = self._make_rule("on_update", [], [{"type": "block", "message": "No"}])
		engine = self._make_engine([rule])
		engine._record_to_dict = mock.Mock(return_value={})
		result = engine.evaluate_dry("Order", "on_create", mock.MagicMock(), session=mock.MagicMock())
		assert result["would_block"] is False
		assert result["rules_matched"] == []

	def test_dry_run_add_error_sets_block_field(self):
		rule = self._make_rule("on_create", [], [{"type": "add_error", "field": "email", "message": "Bad email"}])
		engine = self._make_engine([rule])
		engine._record_to_dict = mock.Mock(return_value={})
		result = engine.evaluate_dry("Order", "on_create", mock.MagicMock(), session=mock.MagicMock())
		assert result["would_block"] is True
		assert result["block_field"] == "email"
		assert result["block_message"] == "Bad email"

	def test_dry_run_create_record_listed(self):
		rule = self._make_rule("on_create", [], [{
			"type": "create_record",
			"model": "AuditLog",
			"fields": {"action": "created"},
		}])
		engine = self._make_engine([rule])
		engine._record_to_dict = mock.Mock(return_value={})
		result = engine.evaluate_dry("Order", "on_create", mock.MagicMock(), session=mock.MagicMock())
		assert len(result["would_create_records"]) == 1
		assert result["would_create_records"][0]["model"] == "AuditLog"

	def test_dry_run_returns_all_expected_keys(self):
		engine = self._make_engine([])
		engine._record_to_dict = mock.Mock(return_value={})
		result = engine.evaluate_dry("Order", "on_create", mock.MagicMock(), session=mock.MagicMock())
		expected_keys = {
			"would_block", "block_message", "block_field",
			"would_set", "would_send_emails", "would_call_webhooks",
			"would_create_records", "would_start_workflows", "rules_matched",
		}
		assert expected_keys == set(result.keys())


# ---------------------------------------------------------------------------
# E20: stop_on_match and stop_after_actions
# ---------------------------------------------------------------------------

class TestStopOnMatch:

	def _make_set_field_rule(self, field, value, name, stop_on_match=False, stop_after_actions=False):
		return _make_rule(
			"on_create",
			[],
			[{"type": "set_field", "field": field, "value": value}],
			name=name,
			stop_on_match=stop_on_match,
			stop_after_actions=stop_after_actions,
		)

	def test_stop_on_match_stops_after_first_matching_rule(self):
		# 3 rules, first has stop_on_match=True on its ruleset
		rule1 = self._make_set_field_rule("x", "from_rule1", "Rule1", stop_on_match=True)
		rule2 = self._make_set_field_rule("y", "from_rule2", "Rule2")
		rule3 = self._make_set_field_rule("z", "from_rule3", "Rule3")
		engine = _make_engine_with_rules([rule1, rule2, rule3])

		record = _make_record(x="init", y="init", z="init")
		engine._record_to_dict = mock.Mock(return_value={"x": "init", "y": "init", "z": "init"})
		engine._log_execution = mock.Mock()

		engine.evaluate("FakeModel", "on_create", record, session=mock.MagicMock())

		# Rule1 fired (set x)
		assert record.x == "from_rule1"
		# Rules 2 and 3 must NOT have fired
		assert record.y == "init"
		assert record.z == "init"

	def test_stop_on_match_false_runs_all_rules(self):
		rule1 = self._make_set_field_rule("x", "r1", "Rule1", stop_on_match=False)
		rule2 = self._make_set_field_rule("y", "r2", "Rule2", stop_on_match=False)
		engine = _make_engine_with_rules([rule1, rule2])

		record = _make_record(x="init", y="init")
		engine._record_to_dict = mock.Mock(return_value={"x": "init", "y": "init"})
		engine._log_execution = mock.Mock()

		engine.evaluate("FakeModel", "on_create", record, session=mock.MagicMock())

		assert record.x == "r1"
		assert record.y == "r2"

	def test_stop_after_actions_on_individual_rule(self):
		# Rule1 has stop_after_actions=True, rule2 should not fire
		rule1 = self._make_set_field_rule("x", "r1", "Rule1", stop_after_actions=True)
		rule2 = self._make_set_field_rule("y", "r2", "Rule2")
		engine = _make_engine_with_rules([rule1, rule2])

		record = _make_record(x="init", y="init")
		engine._record_to_dict = mock.Mock(return_value={"x": "init", "y": "init"})
		engine._log_execution = mock.Mock()

		engine.evaluate("FakeModel", "on_create", record, session=mock.MagicMock())

		assert record.x == "r1"
		assert record.y == "init"   # rule2 never ran

	def test_stop_on_match_does_not_trigger_on_non_matching_rule(self):
		# Rule1 condition doesn't match → skip → rule2 should still run
		rule1 = _make_rule(
			"on_create",
			[{"field": "status", "op": "=", "value": "never_matches", "logic": "AND"}],
			[{"type": "set_field", "field": "x", "value": "r1"}],
			name="Rule1",
			stop_on_match=True,
		)
		rule2 = self._make_set_field_rule("y", "r2", "Rule2")
		engine = _make_engine_with_rules([rule1, rule2])

		record = _make_record(x="init", y="init", status="active")
		engine._record_to_dict = mock.Mock(return_value={"x": "init", "y": "init", "status": "active"})
		engine._log_execution = mock.Mock()

		engine.evaluate("FakeModel", "on_create", record, session=mock.MagicMock())

		assert record.x == "init"   # rule1 condition failed → no stop
		assert record.y == "r2"     # rule2 ran


# ---------------------------------------------------------------------------
# E8: add_error action
# ---------------------------------------------------------------------------

class TestAddErrorAction:

	def setup_method(self):
		self.eng = _make_engine()
		self.session = mock.MagicMock()

	def test_add_error_raises_rules_field_error(self):
		record = _make_record()
		actions = [{"type": "add_error", "field": "amount", "message": "Must be positive"}]
		with pytest.raises(RulesFieldError, match="Must be positive"):
			self.eng._execute_actions(actions, {}, record, self.session)

	def test_field_error_has_correct_field_name(self):
		record = _make_record()
		actions = [{"type": "add_error", "field": "email", "message": "Invalid"}]
		with pytest.raises(RulesFieldError) as exc_info:
			self.eng._execute_actions(actions, {}, record, self.session)
		assert exc_info.value.field == "email"

	def test_add_error_is_subclass_of_validation_error(self):
		record = _make_record()
		actions = [{"type": "add_error", "field": "x", "message": "err"}]
		with pytest.raises(RulesValidationError):
			self.eng._execute_actions(actions, {}, record, self.session)

	def test_add_error_default_message_when_missing(self):
		record = _make_record()
		actions = [{"type": "add_error", "field": "x"}]
		with pytest.raises(RulesFieldError, match="Validation error"):
			self.eng._execute_actions(actions, {}, record, self.session)

	def test_add_error_fires_before_set_field(self):
		"""add_error (block-class action) must run before set_field mutations."""
		record = _make_record(name="original")
		type(record)._rules_mutable_fields = frozenset({"name"})
		actions = [
			{"type": "set_field", "field": "name", "value": "mutated"},
			{"type": "add_error", "field": "name", "message": "stop"},
		]
		with pytest.raises(RulesFieldError):
			self.eng._execute_actions(actions, {}, record, self.session)
		# Must NOT have been mutated — add_error fired first
		assert record.name == "original"

	def test_add_error_with_template_message(self):
		record = _make_record()
		actions = [{"type": "add_error", "field": "amount", "message": "Value {{amount}} is invalid"}]
		ctx = {"amount": "abc"}
		with pytest.raises(RulesFieldError, match="Value abc is invalid"):
			self.eng._execute_actions(actions, ctx, record, self.session)


# ---------------------------------------------------------------------------
# E6: Auto cache invalidation (unit test)
# ---------------------------------------------------------------------------

class TestCacheInvalidation:

	def setup_method(self):
		_SIMPLE_CACHE.clear()

	def teardown_method(self):
		_SIMPLE_CACHE.clear()

	def test_invalidate_clears_specific_model_cache(self):
		_SIMPLE_CACHE["MyModel"] = (0.0, [])
		_SIMPLE_CACHE["OtherModel"] = (0.0, [])
		engine = _make_engine()
		engine.invalidate("MyModel")
		assert "MyModel" not in _SIMPLE_CACHE
		assert "OtherModel" in _SIMPLE_CACHE

	def test_invalidate_none_clears_all(self):
		_SIMPLE_CACHE["A"] = (0.0, [])
		_SIMPLE_CACHE["B"] = (0.0, [])
		_SIMPLE_CACHE["C"] = (0.0, [])
		engine = _make_engine()
		engine.invalidate(None)
		assert len(_SIMPLE_CACHE) == 0

	def test_invalidate_missing_key_is_noop(self):
		engine = _make_engine()
		engine.invalidate("DoesNotExist")  # must not raise

	def test_invalidate_no_arg_clears_all(self):
		_SIMPLE_CACHE["X"] = (0.0, [])
		engine = _make_engine()
		engine.invalidate()  # default model_name=None
		assert len(_SIMPLE_CACHE) == 0

	def test_cache_populated_after_load(self):
		"""Manually seeding cache returns cached rules without DB hit."""
		fake_rules = [mock.MagicMock()]
		_SIMPLE_CACHE["Widget"] = (time.monotonic(), fake_rules)
		engine = _make_engine()
		# Use a session mock that would fail if actually queried
		bad_session = mock.MagicMock()
		bad_session.execute.side_effect = RuntimeError("should not be called")
		result = engine._load_rules(bad_session, "Widget")
		assert result is fake_rules

	def test_invalidate_then_reload_misses_cache(self):
		fake_rules_v1 = [mock.MagicMock()]
		_SIMPLE_CACHE["Widget"] = (time.monotonic(), fake_rules_v1)
		engine = _make_engine()
		engine.invalidate("Widget")
		assert "Widget" not in _SIMPLE_CACHE


# ---------------------------------------------------------------------------
# evaluate() integration: conditions filtering, context kwarg
# ---------------------------------------------------------------------------

class TestEvaluateIntegration:

	def test_evaluate_skips_rule_with_non_matching_event(self):
		rule = _make_rule("on_update", [], [{"type": "block", "message": "No"}])
		engine = _make_engine_with_rules([rule])
		engine._record_to_dict = mock.Mock(return_value={})
		engine._log_execution = mock.Mock()
		# on_create event → rule with on_update trigger → must NOT fire
		engine.evaluate("Model", "on_create", mock.MagicMock(), session=mock.MagicMock())
		engine._log_execution.assert_not_called()

	def test_evaluate_skips_rule_when_conditions_fail(self):
		rule = _make_rule(
			"on_create",
			[{"field": "status", "op": "=", "value": "active", "logic": "AND"}],
			[{"type": "block", "message": "blocked"}],
		)
		engine = _make_engine_with_rules([rule])
		engine._record_to_dict = mock.Mock(return_value={"status": "draft"})
		engine._log_execution = mock.Mock()
		# conditions fail → rule doesn't fire
		engine.evaluate("Model", "on_create", mock.MagicMock(), session=mock.MagicMock())
		engine._log_execution.assert_not_called()

	def test_evaluate_uses_provided_context(self):
		"""When context= kwarg is passed, engine uses it instead of _record_to_dict."""
		rule = _make_rule(
			"on_create",
			[{"field": "vip", "op": "=", "value": True, "logic": "AND"}],
			[{"type": "set_field", "field": "priority", "value": "high"}],
		)
		engine = _make_engine_with_rules([rule])
		engine._record_to_dict = mock.Mock(return_value={"vip": False})  # would fail conditions
		engine._log_execution = mock.Mock()

		record = _make_record(priority="low")
		# Pass explicit context with vip=True → condition passes
		engine.evaluate(
			"Model", "on_create", record,
			session=mock.MagicMock(),
			context={"vip": True},
		)
		assert record.priority == "high"
		# _record_to_dict should NOT have been called
		engine._record_to_dict.assert_not_called()

	def test_evaluate_raises_validation_error_from_block(self):
		rule = _make_rule("on_create", [], [{"type": "block", "message": "Access denied"}])
		engine = _make_engine_with_rules([rule])
		engine._record_to_dict = mock.Mock(return_value={})
		engine._log_execution = mock.Mock()
		with pytest.raises(RulesValidationError, match="Access denied"):
			engine.evaluate("Model", "on_create", mock.MagicMock(), session=mock.MagicMock())

	def test_evaluate_raises_field_error_from_add_error(self):
		rule = _make_rule("on_create", [], [{"type": "add_error", "field": "x", "message": "bad"}])
		engine = _make_engine_with_rules([rule])
		engine._record_to_dict = mock.Mock(return_value={})
		engine._log_execution = mock.Mock()
		with pytest.raises(RulesFieldError) as exc_info:
			engine.evaluate("Model", "on_create", mock.MagicMock(), session=mock.MagicMock())
		assert exc_info.value.field == "x"

	def test_evaluate_no_rules_is_noop(self):
		engine = _make_engine_with_rules([])
		engine._record_to_dict = mock.Mock(return_value={})
		engine._log_execution = mock.Mock()
		# Must not raise
		engine.evaluate("Model", "on_create", mock.MagicMock(), session=mock.MagicMock())


# ---------------------------------------------------------------------------
# Before_* event tests (mixin integration) — added per spec
# ---------------------------------------------------------------------------

class TestBeforeEvents:
	"""
	Tests that _fire() delivers before_* events correctly.
	Uses the same patching strategy as TestFire in test_rules_mixin.py.
	"""

	def _make_app_mock(self, session=None):
		mock_app = mock.MagicMock()
		mock_app.appbuilder.get_session = session or mock.MagicMock()
		return mock_app

	def test_before_insert_fires_on_before_create(self):
		from pgappforge.plugins.rules.mixin import _fire

		record = mock.MagicMock()
		mock_app = self._make_app_mock()
		eng = mock.MagicMock()

		with mock.patch("pgappforge.plugins.rules.engine.get_rules_engine", return_value=eng), \
			 mock.patch("flask.current_app", mock_app, create=True):
			_fire("Invoice", "on_before_create", record)

		eng.evaluate.assert_called_once()
		args, kwargs = eng.evaluate.call_args
		assert args[0] == "Invoice"
		assert args[1] == "on_before_create"
		assert args[2] is record

	def test_before_update_fires_on_before_update(self):
		from pgappforge.plugins.rules.mixin import _fire

		record = mock.MagicMock()
		mock_app = self._make_app_mock()
		eng = mock.MagicMock()

		with mock.patch("pgappforge.plugins.rules.engine.get_rules_engine", return_value=eng), \
			 mock.patch("flask.current_app", mock_app, create=True):
			_fire("Order", "on_before_update", record)

		eng.evaluate.assert_called_once()
		args, _ = eng.evaluate.call_args
		assert args[1] == "on_before_update"

	def test_before_delete_fires_on_before_delete(self):
		from pgappforge.plugins.rules.mixin import _fire

		record = mock.MagicMock()
		mock_app = self._make_app_mock()
		eng = mock.MagicMock()

		with mock.patch("pgappforge.plugins.rules.engine.get_rules_engine", return_value=eng), \
			 mock.patch("flask.current_app", mock_app, create=True):
			_fire("Invoice", "on_before_delete", record)

		eng.evaluate.assert_called_once()
		args, _ = eng.evaluate.call_args
		assert args[1] == "on_before_delete"

	def test_before_create_blocks_via_validation_error(self):
		from pgappforge.plugins.rules.mixin import _fire

		record = mock.MagicMock()
		mock_app = self._make_app_mock()
		eng = mock.MagicMock()
		eng.evaluate.side_effect = RulesValidationError("blocked before insert")

		with mock.patch("pgappforge.plugins.rules.engine.get_rules_engine", return_value=eng), \
			 mock.patch("flask.current_app", mock_app, create=True):
			with pytest.raises(RulesValidationError, match="blocked before insert"):
				_fire("Invoice", "on_before_create", record)

	def test_before_event_swallows_runtime_error(self):
		from pgappforge.plugins.rules.mixin import _fire

		record = mock.MagicMock()
		mock_app = self._make_app_mock()
		eng = mock.MagicMock()
		eng.evaluate.side_effect = RuntimeError("unexpected DB error")

		with mock.patch("pgappforge.plugins.rules.engine.get_rules_engine", return_value=eng), \
			 mock.patch("flask.current_app", mock_app, create=True):
			# Must not raise — non-validation errors are swallowed
			_fire("Invoice", "on_before_create", record)
