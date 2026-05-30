"""
polymorphic_mixin.py: Advanced Polymorphic Inheritance for Flask-AppBuilder

Supports both single-table and joined-table inheritance strategies with:
- Flexible polymorphic relationships and associations
- Automatic discriminator column management
- Type-safe registry with class decorator registration
- Hybrid property access for polymorphic type
- Full to_dict serialization with version tracking
- Polymorphic association management with integrity validation
- Orphan cleanup via session-aware operations

Compatible with SQLAlchemy 2.x (primary) and 1.4.x (fallback).

Author: Nyimbi Odero
Date: 25/08/2024
Version: 2.0
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, ClassVar, TypeVar

from flask import current_app
from flask_appbuilder import Model
from sqlalchemy import (
	JSON,
	Boolean,
	Column,
	DateTime,
	ForeignKey,
	Integer,
	String,
	and_,
	event,
	func,
	inspect,
	or_,
	text,
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import backref, relationship, with_polymorphic

# SQLAlchemy 2.x preferred imports with 1.4 fallback
try:
	from sqlalchemy.orm import mapped_column, Mapped
	_SA2 = True
except ImportError:
	_SA2 = False

# PostgreSQL JSONB with fallback to generic JSON
try:
	from sqlalchemy.dialects.postgresql import JSONB as _JSONB
	_METADATA_TYPE = MutableDict.as_mutable(_JSONB)
except ImportError:
	_METADATA_TYPE = MutableDict.as_mutable(JSON)

logger = logging.getLogger(__name__)
T = TypeVar("T", bound="PolymorphicMixin")


def _utcnow() -> datetime:
	"""Timezone-aware UTC now; avoids deprecated datetime.utcnow()."""
	return datetime.now(timezone.utc)


class PolymorphicMixin:
	"""
	Mixin for SQLAlchemy models that participate in polymorphic inheritance.

	Provides the discriminator column, JSONB metadata, timestamps, optional
	optimistic-locking version column, a class-level registry of subtypes,
	and helpers for creating/querying polymorphic instances.

	Class Attributes:
		__polymorphic_on__       Column name used as the discriminator (set on base).
		__polymorphic_identity__ Identity string registered for this concrete type.
		__polymorphic_registry__ Class-level dict mapping identity → class.
		__allow_unmapped__       Required True for SA 2.x hybrid declarative compat.
		__version_id_col__       Enable optimistic-locking via integer version column.

	Typical Usage::

		class Content(PolymorphicMixin, AuditMixin, Model):
			__tablename__ = 'nx_content'
			__polymorphic_on__ = 'type'

		@Content.register_polymorphic('article')
		class Article(Content):
			__tablename__ = 'nx_articles'
			id = Column(Integer, ForeignKey('nx_content.id'), primary_key=True)
	"""

	__polymorphic_registry__: ClassVar[dict[str, type]] = {}
	__allow_unmapped__ = True
	__version_id_col__: ClassVar[bool] = True

	# ------------------------------------------------------------------
	# declared_attr columns
	# ------------------------------------------------------------------

	@declared_attr
	def __tablename__(cls) -> str:
		"""Default table name: nx_<lowercased class name>."""
		return f"nx_{cls.__name__.lower()}"

	@declared_attr
	def id(cls) -> Column:
		"""Integer primary key with index."""
		return Column(Integer, primary_key=True, index=True)

	@declared_attr
	def type(cls) -> Column:
		"""Polymorphic discriminator column."""
		return Column(String(100), nullable=False, index=True)

	@declared_attr
	def metadata_(cls) -> Column:
		"""
		JSONB/JSON metadata column, exposed as 'metadata' in the database.
		Backed by MutableDict so in-place mutations are tracked by the ORM.
		"""
		return Column(
			"metadata",
			_METADATA_TYPE,
			default=dict,
			nullable=False,
			server_default="{}",
		)

	@declared_attr
	def version_id(cls) -> Column | None:
		"""Optimistic-locking integer. None when __version_id_col__ is False."""
		if cls.__version_id_col__:
			return Column(Integer, nullable=False, default=1)
		return None

	@declared_attr
	def created_at(cls) -> Column:
		"""Creation timestamp (timezone-aware UTC)."""
		return Column(DateTime(timezone=True), default=_utcnow, nullable=False)

	@declared_attr
	def updated_at(cls) -> Column:
		"""Last-update timestamp, auto-updated on flush (timezone-aware UTC)."""
		return Column(
			DateTime(timezone=True),
			default=_utcnow,
			onupdate=_utcnow,
			nullable=False,
		)

	# ------------------------------------------------------------------
	# Mapper configuration
	# ------------------------------------------------------------------

	@declared_attr
	def __mapper_args__(cls) -> dict[str, Any]:
		"""
		Build SQLAlchemy mapper args for polymorphic configuration.

		Both __polymorphic_on__ (base class) and __polymorphic_identity__
		(each concrete subtype) are pulled from the class if present.
		version_id_col is wired when __version_id_col__ is True.
		"""
		args: dict[str, Any] = {}

		if hasattr(cls, "__polymorphic_on__"):
			args["polymorphic_on"] = cls.__polymorphic_on__

		if hasattr(cls, "__polymorphic_identity__"):
			identity = cls.__polymorphic_identity__
			args["polymorphic_identity"] = identity
			cls.__polymorphic_registry__[identity] = cls

		if cls.__version_id_col__ and hasattr(cls, "version_id"):
			args["version_id_col"] = cls.version_id

		return args

	# ------------------------------------------------------------------
	# Registration decorator
	# ------------------------------------------------------------------

	@classmethod
	def register_polymorphic(cls, identity: str):
		"""
		Class decorator that registers a subtype under *identity*.

		Sets ``__polymorphic_identity__`` on the decorated class and records
		it in the shared ``__polymorphic_registry__``.

		Example::

			@Content.register_polymorphic('article')
			class Article(Content):
				...
		"""
		def wrapper(subcls: type[T]) -> type[T]:
			subcls.__polymorphic_identity__ = identity
			cls.__polymorphic_registry__[identity] = subcls
			return subcls
		return wrapper

	# ------------------------------------------------------------------
	# Query helpers
	# ------------------------------------------------------------------

	@classmethod
	def polymorphic_query(cls, *entities: Any) -> Any:
		"""
		Return a query that loads *entities* polymorphically.

		Pass no arguments to load all registered subtypes (``'*'`` wildcard).
		Uses SQLAlchemy's ``with_polymorphic`` loader strategy for joined
		loading in a single query where possible.

		Example::

			all_content = Content.polymorphic_query().all()
			# Load only articles and videos
			mixed = Content.polymorphic_query(Article, Video).all()
		"""
		if not entities:
			entities = ("*",)
		return cls.query.with_polymorphic(entities)

	@classmethod
	def create_polymorphic(cls, data: dict[str, Any]) -> T:
		"""
		Instantiate the correct subtype from *data*.

		Reads the discriminator field (``__polymorphic_on__``) from *data*,
		resolves the registered class, and returns a new instance.

		Raises:
			ValueError: Missing discriminator key, or identity not registered.
		"""
		discriminator = cls.__polymorphic_on__
		if discriminator not in data:
			raise ValueError(
				f"Missing discriminator field '{discriminator}' in data"
			)

		identity = data[discriminator]
		subcls = cls.__polymorphic_registry__.get(identity)
		if subcls is None:
			registered = list(cls.__polymorphic_registry__.keys())
			raise ValueError(
				f"Unknown polymorphic identity '{identity}'. "
				f"Registered: {registered}"
			)

		return subcls(**data)

	# ------------------------------------------------------------------
	# Hybrid property for type access
	# ------------------------------------------------------------------

	@hybrid_property
	def polymorphic_type(self) -> str:
		"""Read the current discriminator value via the configured column name."""
		return getattr(self, self.__polymorphic_on__)

	@polymorphic_type.setter
	def polymorphic_type(self, value: str) -> None:
		"""
		Set the discriminator value after validating it is a registered identity.

		Raises:
			ValueError: *value* not in ``__polymorphic_registry__``.
		"""
		if value not in self.__polymorphic_registry__:
			registered = list(self.__polymorphic_registry__.keys())
			raise ValueError(
				f"Invalid polymorphic type '{value}'. Valid: {registered}"
			)
		setattr(self, self.__polymorphic_on__, value)

	# ------------------------------------------------------------------
	# Serialization
	# ------------------------------------------------------------------

	def to_dict(self, include_none: bool = False) -> dict[str, Any]:
		"""
		Serialize this instance to a plain dict.

		Always includes: id, type (discriminator value), metadata, created_at,
		updated_at, and version_id (when tracking is enabled).  All other
		mapped columns are appended, optionally filtering None values.

		Args:
			include_none: When False (default), columns whose value is None
			              are omitted from the output.

		Returns:
			dict with string keys and serialisable values.
		"""
		data: dict[str, Any] = {
			"id": self.id,
			"type": self.polymorphic_type,
			"metadata": self.metadata_,
			"created_at": self.created_at,
			"updated_at": self.updated_at,
		}

		if self.__version_id_col__:
			data["version_id"] = self.version_id

		mapper = inspect(type(self))
		for col_key in mapper.columns.keys():
			if col_key not in data:
				value = getattr(self, col_key, None)
				if include_none or value is not None:
					data[col_key] = value

		return data


class PolymorphicAssociationMixin:
	"""
	Mixin for models that store a generic (type, id) reference to any model.

	Implements the classic "generic foreign key" pattern: two columns
	(``associated_id`` and ``associated_type``) together point to a record
	of an arbitrary type.  Integrity validation is provided via
	``validate_association()``.

	Typical Usage::

		class Tag(PolymorphicAssociationMixin, Model):
			__tablename__ = 'nx_tags'
			id = Column(Integer, primary_key=True)
			name = Column(String(50), nullable=False)

		tag = Tag(name='python', associated_type='Article', associated_id=42)
		tag.validate_association()  # checks record actually exists
	"""

	@declared_attr
	def associated_id(cls) -> Column:
		"""PK of the associated record (type-agnostic)."""
		return Column(Integer, nullable=False, index=True)

	@declared_attr
	def associated_type(cls) -> Column:
		"""Discriminator naming the associated model class."""
		return Column(String(100), nullable=False, index=True)

	@declared_attr
	def created_by_id(cls) -> Column:
		"""FK to ab_user — records who created the association."""
		return Column(Integer, ForeignKey("ab_user.id"), nullable=True)

	@declared_attr
	def created_by(cls) -> relationship:
		"""Lazy-loaded relationship to the FAB User model."""
		return relationship(
			"User",
			foreign_keys=[cls.created_by_id],
			lazy="select",
		)

	# ------------------------------------------------------------------
	# Association factory
	# ------------------------------------------------------------------

	@classmethod
	def associate_with(
		cls,
		associated_class: type[Model],
		lazy: str = "select",
		uselist: bool = True,
	) -> relationship:
		"""
		Build a SQLAlchemy relationship from this class to *associated_class*.

		The join condition is on both ``associated_id`` and ``associated_type``
		so that only records of the right type are loaded.  A backref
		``<cls_lower>_associations`` is added to *associated_class*.

		Args:
			associated_class: The target model class.
			lazy:             SQLAlchemy lazy-loading strategy (default 'select').
			uselist:          True for a collection, False for a scalar.

		Returns:
			Configured ``relationship()`` descriptor.

		Example::

			class Tag(PolymorphicAssociationMixin, Model):
				...
				content_assoc = Tag.associate_with(Content)
		"""
		name = associated_class.__name__
		backref_name = f"{cls.__name__.lower()}_associations"

		return relationship(
			associated_class,
			primaryjoin=and_(
				cls.associated_id == associated_class.id,
				cls.associated_type == name,
			),
			backref=backref(
				backref_name,
				cascade="all, delete-orphan",
				lazy=lazy,
			),
			foreign_keys=[cls.associated_id],
			uselist=uselist,
		)

	# ------------------------------------------------------------------
	# Integrity helpers
	# ------------------------------------------------------------------

	def validate_association(self) -> None:
		"""
		Assert that the (type, id) pair references a real database record.

		Uses Flask-AppBuilder's appbuilder registry to resolve the model class
		by name, then issues a lightweight existence query.

		Raises:
			ValueError: Missing fields, unknown type, or record not found.
		"""
		if not self.associated_id or not self.associated_type:
			raise ValueError(
				"Both 'associated_id' and 'associated_type' must be set"
			)

		model = current_app.appbuilder.get_model(self.associated_type)
		if model is None:
			raise ValueError(
				f"Unknown association type: '{self.associated_type}'"
			)

		# SA 2.x compatible existence check — avoids deprecated Query.get()
		session = inspect(self).session
		if session is None:
			raise RuntimeError(
				"validate_association() requires the instance to be bound to a session"
			)

		from sqlalchemy import select, exists as sa_exists
		exists_stmt = select(
			sa_exists().where(model.id == self.associated_id)
		)
		found = session.scalar(exists_stmt)
		if not found:
			raise ValueError(
				f"No {self.associated_type} record with id={self.associated_id}"
			)

	@classmethod
	def cleanup_orphans(cls, session) -> int:
		"""
		Remove associations whose referenced record no longer exists.

		Iterates all rows of this association table and deletes those that
		fail ``validate_association()``.  Commits only when at least one
		orphan is removed.

		Args:
			session: Active SQLAlchemy session (passed explicitly to avoid
			         relying on the legacy ``db.session`` global).

		Returns:
			Count of orphaned rows deleted.
		"""
		from sqlalchemy import select as sa_select

		stmt = sa_select(cls)
		rows = session.scalars(stmt).all()

		count = 0
		for assoc in rows:
			try:
				assoc.validate_association()
			except ValueError:
				session.delete(assoc)
				count += 1

		if count:
			session.commit()
			logger.info(
				"cleanup_orphans: removed %d orphaned %s rows",
				count,
				cls.__name__,
			)

		return count


__all__ = [
	"PolymorphicMixin",
	"PolymorphicAssociationMixin",
]
