"""SQLAlchemy model mixin injection — the _inherit equivalent for PgAppForge.

Problem
-------
Plugin A owns ARInvoice. Plugin B (Trade Finance) wants to add a
letter_of_credit_id column to ARInvoice without modifying Plugin A's source.
With standard Python there is no way to do this cleanly.

Solution
--------
ModelMixinRegistry allows Plugin B to call::

    register_mixin('pgappforge.plugins.erp.finance.ar.models.ARInvoice',
                   TradeFinanceMixin)

At app startup, ``apply_all_mixins()`` is called before SQLAlchemy compiles
the mappers. It adds the mixin's columns/relationships to the target class
using SQLAlchemy's ``declared_attr`` and column attachment API.

Design constraints
------------------
- Must be called BEFORE ``db.create_all()`` / Alembic migration runs
- The mixin class must use ``declared_attr`` for columns that depend on the
  table (FK references etc.)
- Plain ``sa.Column`` attributes are copied directly onto the target class
- Does NOT break Alembic autogenerate — added columns appear in the mapped
  class and autogenerate sees them normally

Usage
-----
    # In trade_finance/__init__.py:
    import sqlalchemy as sa
    from sqlalchemy.orm import declared_attr
    from pgappforge.composition import register_mixin

    class TradeFinanceMixin:
        letter_of_credit_id = sa.Column(sa.String(36), nullable=True, index=True)
        lc_expiry_date = sa.Column(sa.Date, nullable=True)

        @declared_attr
        def letter_of_credit(cls):
            from pgappforge.plugins.erp.finance.trade_finance.models import LetterOfCredit
            return sa.orm.relationship(LetterOfCredit, foreign_keys=[cls.letter_of_credit_id])

    register_mixin(
        'pgappforge.plugins.erp.finance.ar.models.ARInvoice',
        TradeFinanceMixin,
        priority=10,  # lower = applied first
    )

    # In app factory, before db.create_all():
    from pgappforge.composition import apply_all_mixins
    apply_all_mixins()
"""
from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import declared_attr

log = logging.getLogger(__name__)


@dataclass
class _MixinEntry:
	target_class_path: str   # dotted path: 'pgappforge.plugins.erp.finance.ar.models.ARInvoice'
	mixin_class: type
	priority: int = 50       # lower = applied first


class ModelMixinRegistry:
	"""Registry of mixins to be applied to existing SQLAlchemy models."""

	def __init__(self) -> None:
		self._entries: list[_MixinEntry] = []
		self._applied = False

	def register(self, target_class_path: str, mixin_class: type, priority: int = 50) -> None:
		"""Queue *mixin_class* to be applied to the model at *target_class_path*.

		Must be called before :func:`apply_all_mixins`.
		"""
		if self._applied:
			raise RuntimeError(
				f"apply_all_mixins() has already run; cannot register {mixin_class!r}. "
				"Call register_mixin() during plugin initialization, before app startup."
			)
		self._entries.append(_MixinEntry(
			target_class_path=target_class_path,
			mixin_class=mixin_class,
			priority=priority,
		))
		log.debug("ModelMixinRegistry: queued %s → %s", target_class_path, mixin_class.__name__)

	def apply_all(self) -> int:
		"""Apply all registered mixins to their target models.

		Returns the number of mixins successfully applied.
		Must be called once at app startup before SQLAlchemy mapper compilation.
		"""
		if self._applied:
			log.warning("ModelMixinRegistry.apply_all() called more than once — skipping.")
			return 0

		self._applied = True
		self._entries.sort(key=lambda e: e.priority)
		applied = 0

		for entry in self._entries:
			try:
				applied += self._apply_one(entry)
			except Exception:
				log.exception(
					"ModelMixinRegistry: failed to apply %s to %s",
					entry.mixin_class.__name__, entry.target_class_path,
				)
		log.info("ModelMixinRegistry: applied %d/%d mixins", applied, len(self._entries))
		return applied

	def _apply_one(self, entry: _MixinEntry) -> int:
		module_path, class_name = entry.target_class_path.rsplit('.', 1)
		module = importlib.import_module(module_path)
		target_cls = getattr(module, class_name)

		if not hasattr(target_cls, '__table__'):
			log.warning(
				"ModelMixinRegistry: %s has no __table__ — not a mapped model; skipping.",
				entry.target_class_path,
			)
			return 0

		mixin = entry.mixin_class
		table = target_cls.__table__
		added = 0

		for attr_name in vars(mixin):
			if attr_name.startswith('_'):
				continue
			attr_val = vars(mixin)[attr_name]

			if isinstance(attr_val, sa.Column):
				# Copy the column so the same Column object isn't reused across tables
				if attr_name not in target_cls.__mapper__.columns:
					col_copy = attr_val.copy()
					col_copy.name = attr_name
					table.append_column(col_copy)
					setattr(target_cls, attr_name, col_copy)
					added += 1
					log.debug(
						"ModelMixinRegistry: added column %s.%s from %s",
						class_name, attr_name, mixin.__name__,
					)
				else:
					log.debug(
						"ModelMixinRegistry: column %s.%s already exists — skipping",
						class_name, attr_name,
					)

			elif isinstance(attr_val, declared_attr):
				# Evaluate and attach relationship/property
				if not hasattr(target_cls, attr_name):
					setattr(target_cls, attr_name, attr_val.__get__(None, target_cls))
					added += 1

		return 1 if added > 0 else 0

	def list_registered(self) -> list[dict[str, Any]]:
		return [
			{'target': e.target_class_path, 'mixin': e.mixin_class.__name__, 'priority': e.priority}
			for e in self._entries
		]


# Module-level singleton
_registry: ModelMixinRegistry | None = None


def get_mixin_registry() -> ModelMixinRegistry:
	global _registry
	if _registry is None:
		_registry = ModelMixinRegistry()
	return _registry


def register_mixin(target_class_path: str, mixin_class: type, priority: int = 50) -> None:
	"""Queue *mixin_class* to be applied to the model at *target_class_path*.

	Call this in your plugin's module-level code or ``initialize()`` method,
	before the app factory calls ``apply_all_mixins()``.
	"""
	get_mixin_registry().register(target_class_path, mixin_class, priority)


def apply_all_mixins() -> int:
	"""Apply all queued mixins. Call once in the app factory before db.create_all()."""
	return get_mixin_registry().apply_all()


__all__ = ['ModelMixinRegistry', 'register_mixin', 'apply_all_mixins', 'get_mixin_registry']
