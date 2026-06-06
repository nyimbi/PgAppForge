"""
pgappforge/plugins/rules/mixin.py

RulesMixin — attach to any SQLAlchemy Model to automatically fire
the rules engine on insert / update / delete.

Usage
-----
    class Invoice(Model, RulesMixin):
        __tablename__ = "invoices"
        _rules_mutable_fields = frozenset({"status", "amount"})

Rules fire at class-definition time via __init_subclass__, not per-instance,
so there is no per-instantiation overhead and no thread-safety race.

Teardown (for testing)
----------------------
    Invoice._unregister_rules()
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger(__name__)

_REGISTRATION_LOCK = threading.Lock()


class RulesMixin:
	"""Mixin that wires SQLAlchemy after_insert/after_update/after_delete events
	to the rules engine for any model that inherits from it.

	Subclasses may declare:
	    _rules_mutable_fields: frozenset[str]
	to restrict which columns the set_field action may modify.
	"""

	_rules_mutable_fields: frozenset[str] = frozenset()
	_rules_registered: bool = False
	_rules_listeners: tuple | None = None

	def __init_subclass__(cls, **kwargs: object) -> None:
		super().__init_subclass__(**kwargs)
		with _REGISTRATION_LOCK:
			if cls.__dict__.get("_rules_registered"):
				return
			cls._rules_registered = True
			_register_listeners(cls)

	@classmethod
	def _unregister_rules(cls) -> None:
		"""Remove event listeners — use in test teardown to prevent pollution."""
		with _REGISTRATION_LOCK:
			if not cls._rules_registered or not cls._rules_listeners:
				return
			from sqlalchemy import event as sa_event
			ai, au, ad = cls._rules_listeners
			for event_name, fn in (("after_insert", ai), ("after_update", au), ("after_delete", ad)):
				try:
					sa_event.remove(cls, event_name, fn)
				except Exception:
					pass
			cls._rules_registered = False
			cls._rules_listeners = None


def _register_listeners(cls: type) -> None:
	from sqlalchemy import event as sa_event
	model_name = cls.__name__

	def _ai(mapper, connection, target):
		_fire(model_name, "on_create", target)

	def _au(mapper, connection, target):
		_fire(model_name, "on_update", target)

	def _ad(mapper, connection, target):
		_fire(model_name, "on_delete", target)

	sa_event.listen(cls, "after_insert", _ai)
	sa_event.listen(cls, "after_update", _au)
	sa_event.listen(cls, "after_delete", _ad)
	cls._rules_listeners = (_ai, _au, _ad)


def _fire(model_name: str, event: str, target: object) -> None:
	"""Invoke the rules engine; swallow non-blocking exceptions."""
	try:
		from .engine import get_rules_engine, RulesValidationError
		from flask import current_app
		session = current_app.appbuilder.get_session
		ctx: dict = {}
		if hasattr(target, "__dict__"):
			ctx = {k: v for k, v in vars(target).items() if not k.startswith("_")}
		get_rules_engine().evaluate(model_name, event, target, session=session, context=ctx)
	except Exception as exc:
		from .engine import RulesValidationError
		if isinstance(exc, RulesValidationError):
			raise
		log.error("RulesMixin._fire(%s, %s) failed: %s", model_name, event, exc)
