"""
pgappforge/plugins/rules/mixin.py

RulesMixin — attach to any SQLAlchemy Model to automatically fire
the rules engine on insert / update / delete.

Usage
-----
    class Invoice(Model, RulesMixin):
        __tablename__ = "invoices"
        ...

Rules are evaluated lazily: the first time an instance of the class is
created the mixin registers SQLAlchemy event listeners on the *class*
(not the instance), so the overhead is exactly one check per class.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class RulesMixin:
	"""
	Mixin that wires SQLAlchemy after_insert / after_update / after_delete
	events to the rules engine for any model that inherits from it.

	Class-level attributes
	----------------------
	_rules_registered : bool
	    Set to True once event listeners have been attached.  Prevents
	    duplicate listener registration across multiple instances.
	"""

	# Populated by __init_subclass__ on every concrete subclass
	_rules_registered: bool = False

	def __init_subclass__(cls, **kwargs: object) -> None:
		super().__init_subclass__(**kwargs)
		cls._rules_registered = False

	# ------------------------------------------------------------------

	def _ensure_rules_registered(self) -> None:
		"""Register SQLAlchemy event listeners on the model class (once only)."""
		cls = type(self)
		if cls._rules_registered:
			return

		try:
			from sqlalchemy import event as sa_event

			model_name = cls.__name__

			@sa_event.listens_for(cls, "after_insert")
			def _after_insert(mapper, connection, target):
				_fire(model_name, "on_create", target)

			@sa_event.listens_for(cls, "after_update")
			def _after_update(mapper, connection, target):
				_fire(model_name, "on_update", target)

			@sa_event.listens_for(cls, "after_delete")
			def _after_delete(mapper, connection, target):
				_fire(model_name, "on_delete", target)

			cls._rules_registered = True
			log.debug("RulesMixin: registered event listeners for %r", model_name)

		except Exception as exc:
			log.warning(
				"RulesMixin: could not register event listeners for %r: %s",
				cls.__name__,
				exc,
			)

	def __init__(self, *args: object, **kwargs: object) -> None:
		super().__init__(*args, **kwargs)
		self._ensure_rules_registered()


# ---------------------------------------------------------------------------
# Internal helper (module scope keeps closures light)
# ---------------------------------------------------------------------------

def _fire(model_name: str, event: str, target: object) -> None:
	"""Call the rules engine; swallow non-blocking exceptions."""
	try:
		from .engine import get_rules_engine, RulesValidationError
		get_rules_engine().evaluate(model_name, event, target)
	except RulesValidationError:
		# Re-raise so the ORM session rolls back
		raise
	except Exception as exc:
		log.warning(
			"RulesMixin: error evaluating rules for %r/%s: %s",
			model_name, event, exc,
		)
