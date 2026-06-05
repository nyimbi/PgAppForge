"""
tests/ci/test_rules_mixin.py

Unit tests for RulesMixin (pgappforge/plugins/rules/mixin.py).

Strategy
--------
- No real DB or Flask app needed.
- SQLAlchemy event registration works on plain Python classes that inherit from
  a DeclarativeBase, but RulesMixin only calls sa_event.listen(cls, ...) which
  works on any class — so we can define tiny stub classes in tests.
- _unregister_rules() is called in teardown to prevent cross-test pollution.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch, call
import pytest

from pgappforge.plugins.rules.mixin import RulesMixin, _fire
from pgappforge.plugins.rules.engine import RulesValidationError


# ---------------------------------------------------------------------------
# Helpers — isolate each class definition from others
# ---------------------------------------------------------------------------

def _make_subclass(name: str = "TestModel") -> type:
	"""Dynamically create a fresh RulesMixin subclass (triggers __init_subclass__)."""
	return type(name, (RulesMixin,), {})


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestListenerRegistration:

	def test_listeners_registered_once_at_class_definition(self):
		cls = _make_subclass("Foo")
		assert cls._rules_registered is True
		assert cls._rules_listeners is not None
		assert len(cls._rules_listeners) == 6  # (before_insert, before_update, before_delete, after_insert, after_update, after_delete)
		cls._unregister_rules()

	def test_subclass_gets_independent_flag(self):
		A = _make_subclass("IndepA")
		B = _make_subclass("IndepB")
		assert A._rules_registered is True
		assert B._rules_registered is True
		# Each class has its own _rules_listeners tuple (not the same object)
		assert A._rules_listeners is not B._rules_listeners
		A._unregister_rules()
		B._unregister_rules()

	def test_no_duplicate_registration_on_second_subclass_creation(self):
		"""__init_subclass__ must skip if _rules_registered already True on the class."""
		with patch("pgappforge.plugins.rules.mixin._register_listeners") as mock_reg:
			cls = _make_subclass("NoDup")
			# Should have been called exactly once
			mock_reg.assert_called_once_with(cls)
			# Force re-trigger __init_subclass__ by manually calling it
			cls.__init_subclass__()
			# Still only called once — guard prevents second registration
			mock_reg.assert_called_once()

	def test_unregister_rules_removes_listeners(self):
		cls = _make_subclass("Unreg")
		assert cls._rules_registered is True
		cls._unregister_rules()
		assert cls._rules_registered is False
		assert cls._rules_listeners is None

	def test_unregister_rules_is_idempotent(self):
		cls = _make_subclass("IdempUnreg")
		cls._unregister_rules()
		# Second call must not raise
		cls._unregister_rules()


# ---------------------------------------------------------------------------
# Class attribute defaults
# ---------------------------------------------------------------------------

class TestClassAttributes:

	def test_mutable_fields_default_is_empty_frozenset(self):
		assert RulesMixin._rules_mutable_fields == frozenset()

	def test_rules_registered_false_on_base_mixin(self):
		# The base RulesMixin itself is never registered (no __init_subclass__ for itself)
		assert RulesMixin._rules_registered is False

	def test_rules_listeners_none_on_base_mixin(self):
		assert RulesMixin._rules_listeners is None

	def test_subclass_inherits_empty_mutable_fields_by_default(self):
		cls = _make_subclass("MutDefault")
		assert cls._rules_mutable_fields == frozenset()
		cls._unregister_rules()

	def test_subclass_can_override_mutable_fields(self):
		cls = type("MutOverride", (RulesMixin,), {
			"_rules_mutable_fields": frozenset({"status", "amount"}),
		})
		assert cls._rules_mutable_fields == frozenset({"status", "amount"})
		cls._unregister_rules()


# ---------------------------------------------------------------------------
# _fire — error handling
# ---------------------------------------------------------------------------

class TestFire:
	"""
	_fire() uses lazy imports inside the function body:
	    from pgappforge.plugins.rules.engine import get_rules_engine, RulesValidationError
	    from flask import current_app

	We must therefore patch at the source modules, not at mixin's namespace.
	flask.current_app is a Werkzeug LocalProxy; patch it with create=True so
	unittest.mock doesn't try to inspect the proxy object itself.
	"""

	def _make_app_mock(self, session=None):
		mock_app = MagicMock()
		mock_app.appbuilder.get_session = session or MagicMock()
		return mock_app

	def test_fire_reraises_validation_error(self):
		"""RulesValidationError from the engine must propagate to the caller."""
		record = MagicMock()
		mock_app = self._make_app_mock()

		eng = MagicMock()
		eng.evaluate.side_effect = RulesValidationError("blocked!")

		with patch("pgappforge.plugins.rules.engine.get_rules_engine", return_value=eng), \
			 patch("flask.current_app", mock_app, create=True):
			with pytest.raises(RulesValidationError, match="blocked!"):
				_fire("Invoice", "on_create", record)

	def test_fire_swallows_non_validation_errors(self):
		"""Generic exceptions (RuntimeError, etc.) must be logged, not re-raised."""
		record = MagicMock()
		mock_app = self._make_app_mock()

		eng = MagicMock()
		eng.evaluate.side_effect = RuntimeError("db exploded")

		with patch("pgappforge.plugins.rules.engine.get_rules_engine", return_value=eng), \
			 patch("flask.current_app", mock_app, create=True):
			# Must not raise
			_fire("Invoice", "on_create", record)

	def test_fire_swallows_import_error_for_missing_flask_context(self):
		"""If get_rules_engine raises (e.g. outside app context), _fire must swallow it."""
		record = MagicMock()

		with patch("pgappforge.plugins.rules.engine.get_rules_engine",
				   side_effect=RuntimeError("working outside application context")), \
			 patch("flask.current_app", MagicMock(), create=True):
			# Must not raise
			_fire("Widget", "on_update", record)

	def test_fire_calls_evaluate_with_correct_args(self):
		"""_fire must call engine.evaluate(model_name, event, record, session=...)."""
		record = MagicMock()
		fake_session = MagicMock()
		mock_app = self._make_app_mock(session=fake_session)

		eng = MagicMock()

		with patch("pgappforge.plugins.rules.engine.get_rules_engine", return_value=eng), \
			 patch("flask.current_app", mock_app, create=True):
			_fire("Order", "on_delete", record)

		import unittest.mock as mock
		eng.evaluate.assert_called_once_with(
			"Order", "on_delete", record, session=fake_session, context=mock.ANY
		)
