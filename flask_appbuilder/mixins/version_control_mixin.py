"""
version_control_mixin.py

Git-like version control for SQLAlchemy models in Flask-AppBuilder.

Tracks field-level changes as JSON patches (RFC 6902), supports branching
and merging with pluggable conflict resolution, and enforces configurable
version retention limits.

Dependencies:
	- SQLAlchemy 2.x (1.x compatible via try/except)
	- Flask-AppBuilder
	- jsonpatch (RFC 6902 patch generation/application)
	- deepdiff (structural diffing for compare_versions)

Author: Nyimbi Odero
Date: 2024-08-25 (modernized 2026-05-30)
Version: 2.0
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

import jsonpatch
from deepdiff import DeepDiff
from flask import current_app
from flask_appbuilder import Model
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.inspection import inspect

# SQLAlchemy 2.x preferred; fall back to 1.x patterns transparently
try:
	from sqlalchemy.orm import Mapped, mapped_column, relationship
	from sqlalchemy import JSON
	_SA2 = True
except ImportError:
	from sqlalchemy import Column, JSON
	from sqlalchemy.orm import relationship
	_SA2 = False

from sqlalchemy.ext.declarative import declared_attr

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
	"""Timezone-aware UTC now, stdlib only."""
	return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------

class ModelVersion(Model):
	"""
	Stores one version entry for a versioned model instance.

	Version 1 stores the full snapshot; subsequent versions store RFC 6902
	JSON patches relative to the previous version, minimising storage.
	"""
	__tablename__ = "nx_model_versions"

	if _SA2:
		id: Mapped[int] = mapped_column(Integer, primary_key=True)
		# parent_id / parent are declared on the concrete subclass via
		# declared_attr so FK references the correct table at runtime.
		version_number: Mapped[int] = mapped_column(Integer, nullable=False)
		data: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), nullable=False)
		is_snapshot: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
		created_at: Mapped[datetime] = mapped_column(
			DateTime(timezone=True), nullable=False, default=_utcnow
		)
		user_id: Mapped[int | None] = mapped_column(
			Integer, ForeignKey("ab_user.id"), nullable=True
		)
		comment: Mapped[str | None] = mapped_column(Text, nullable=True)
		branch_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
	else:
		id = Column(Integer, primary_key=True)
		version_number = Column(Integer, nullable=False)
		data = Column(MutableDict.as_mutable(JSON), nullable=False)
		is_snapshot = Column(Integer, nullable=False, default=0)
		created_at = Column(DateTime, nullable=False, default=_utcnow)
		user_id = Column(Integer, ForeignKey("ab_user.id"), nullable=True)
		comment = Column(Text, nullable=True)
		branch_name = Column(String(100), nullable=True)

	def __repr__(self) -> str:
		branch = f":{self.branch_name}" if self.branch_name else ""
		return f"<ModelVersion v{self.version_number}{branch}>"


class ModelBranch(Model):
	"""
	Stores a named branch — a divergent snapshot of a versioned model's fields.

	Branches are lightweight: they hold only the full field snapshot at branch
	creation time (or at a specific historic version). Merging applies the
	branch diff back to the main timeline.
	"""
	__tablename__ = "nx_model_branches"

	if _SA2:
		id: Mapped[int] = mapped_column(Integer, primary_key=True)
		name: Mapped[str] = mapped_column(String(100), nullable=False)
		data: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), nullable=False)
		base_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
		created_at: Mapped[datetime] = mapped_column(
			DateTime(timezone=True), nullable=False, default=_utcnow
		)
	else:
		id = Column(Integer, primary_key=True)
		name = Column(String(100), nullable=False)
		data = Column(MutableDict.as_mutable(JSON), nullable=False)
		base_version = Column(Integer, nullable=True)
		created_at = Column(DateTime, nullable=False, default=_utcnow)

	def __repr__(self) -> str:
		return f"<ModelBranch '{self.name}'>"


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class VersionControlMixin:
	"""
	Git-like version control mixin for Flask-AppBuilder SQLAlchemy models.

	Attach to any FAB Model subclass to gain:
	- Field-level change tracking via RFC 6902 JSON patches
	- Configurable retention limits (__max_versions__)
	- Named branching from any historic version
	- Merging with pluggable conflict resolution
	- Structural diff between any two version numbers

	Class attributes to configure on the host model:

		__versioned__: list[str]
			Field names to track. Auto-populated from column attrs if empty.

		__max_versions__: int
			Maximum versions per instance on the main branch (0 = unlimited).

	Example::

		class Document(VersionControlMixin, Model):
			__tablename__ = "nx_documents"
			id = Column(Integer, primary_key=True)
			title = Column(String(100), nullable=False)
			content = Column(Text)
			__versioned__ = ["title", "content"]
			__max_versions__ = 10
	"""

	__versioned__: list[str] = []
	__max_versions__: int = 0

	# -- relationships declared via declared_attr so they resolve lazily -----

	@declared_attr
	def versions(cls):  # noqa: N805
		return relationship(
			"ModelVersion",
			primaryjoin=(
				f"and_(ModelVersion.parent_id == foreign({cls.__name__}.id),"
				" ModelVersion.branch_name == None)"
			),
			cascade="all, delete-orphan",
			order_by="ModelVersion.version_number.desc()",
			lazy="select",
			overlaps="branch_versions",
		)

	@declared_attr
	def branch_versions(cls):  # noqa: N805
		return relationship(
			"ModelVersion",
			primaryjoin=(
				f"and_(ModelVersion.parent_id == foreign({cls.__name__}.id),"
				" ModelVersion.branch_name != None)"
			),
			cascade="all, delete-orphan",
			order_by="ModelVersion.version_number.desc()",
			lazy="select",
			overlaps="versions",
		)

	@declared_attr
	def branches(cls):  # noqa: N805
		return relationship(
			"ModelBranch",
			primaryjoin=f"ModelBranch.parent_id == foreign({cls.__name__}.id)",
			cascade="all, delete-orphan",
			lazy="select",
		)

	# -- auto-populate __versioned__ after mapper config --------------------

	@classmethod
	def __declare_last__(cls) -> None:
		if not cls.__versioned__:
			cls.__versioned__ = [c.key for c in inspect(cls).column_attrs]
			log.debug(
				"VersionControlMixin: auto-detected versioned fields for %s: %s",
				cls.__name__,
				cls.__versioned__,
			)

	# -- internal helpers ----------------------------------------------------

	def _current_data(self) -> dict[str, Any]:
		"""Snapshot of all versioned fields as a JSON-serialisable dict."""
		raw: dict[str, Any] = {}
		for attr in self.__versioned__:
			val = getattr(self, attr, None)
			if isinstance(val, datetime):
				val = val.isoformat()
			raw[attr] = val
		return raw

	def _db_session(self):
		"""Resolve the SQLAlchemy session via Flask-AppBuilder's db extension."""
		db = getattr(current_app, "db", None) or current_app.extensions.get("sqlalchemy")
		if db is None:
			raise RuntimeError(
				"VersionControlMixin: cannot locate db session — ensure"
				" Flask-AppBuilder or Flask-SQLAlchemy is initialised."
			)
		return db.session

	def _main_versions_asc(self) -> list[ModelVersion]:
		"""Main-branch versions sorted ascending (oldest first)."""
		return sorted(self.versions, key=lambda v: v.version_number)

	def _reconstruct_at(self, target_number: int, version_chain: list[ModelVersion]) -> dict[str, Any]:
		"""
		Replay patches from the base snapshot forward to reconstruct state at
		`target_number`. `version_chain` must be sorted ascending.
		"""
		if not version_chain:
			raise ValueError("Empty version chain — nothing to reconstruct.")

		snapshot = version_chain[0]
		if not snapshot.is_snapshot:
			raise RuntimeError(
				f"Version chain for {self!r} is corrupt: first entry is not a snapshot."
			)
		data: dict[str, Any] = dict(snapshot.data)

		for v in version_chain[1:]:
			if v.version_number > target_number:
				break
			data = jsonpatch.apply_patch(data, v.data)

		return data

	# -- public API ----------------------------------------------------------

	def save_version(
		self,
		user_id: int | None = None,
		comment: str | None = None,
	) -> ModelVersion:
		"""
		Persist a new version of the current field state.

		Version 1 stores the full snapshot; every subsequent version stores
		only the RFC 6902 diff against its predecessor, keeping storage lean.
		Enforces __max_versions__ by evicting the oldest version when the limit
		is exceeded (the base snapshot is protected — oldest non-snapshot evicted
		first, with re-baselining if required).

		Args:
			user_id: ID of the authenticated user creating this version.
			comment: Human-readable description of the change.

		Returns:
			The newly created ModelVersion instance (not yet flushed to DB if
			you are inside a transaction — call session.commit() yourself).
		"""
		session = self._db_session()
		current_data = self._current_data()
		chain = self._main_versions_asc()

		if not chain:
			# First version — store full snapshot
			version = ModelVersion(
				parent_id=self.id,
				version_number=1,
				data=current_data,
				is_snapshot=1,
				user_id=user_id,
				comment=comment,
			)
		else:
			last = chain[-1]
			prev_data = self._reconstruct_at(last.version_number, chain)
			patch = jsonpatch.make_patch(prev_data, current_data)
			version = ModelVersion(
				parent_id=self.id,
				version_number=last.version_number + 1,
				data=patch.patch,
				is_snapshot=0,
				user_id=user_id,
				comment=comment,
			)

		session.add(version)
		# Invalidate the cached collection so the limit check sees the new entry
		session.flush()

		if self.__max_versions__ > 0 and len(self.versions) > self.__max_versions__:
			self._evict_oldest_version(session)

		return version

	def _evict_oldest_version(self, session) -> None:
		"""
		Remove the oldest version, re-baselining if it was the snapshot.

		When the snapshot (version 1) is the oldest we need to evict, we
		reconstruct version 2's full state and promote it to a new snapshot
		before deleting version 1, preserving replay integrity.
		"""
		chain = self._main_versions_asc()
		if len(chain) < 2:
			return  # Cannot evict the only version

		oldest = chain[0]

		if oldest.is_snapshot and len(chain) >= 2:
			# Promote chain[1] to a full snapshot before evicting oldest
			v2 = chain[1]
			v2_data = self._reconstruct_at(v2.version_number, chain)
			v2.data = v2_data
			v2.is_snapshot = 1
			session.add(v2)

		session.delete(oldest)

	def get_version_data(self, version_number: int) -> dict[str, Any]:
		"""
		Reconstruct and return the full field snapshot for `version_number`.

		Args:
			version_number: Target version to reconstruct.

		Returns:
			Dict mapping versioned field names to their values at that version.

		Raises:
			ValueError: Version number does not exist in the main branch.
		"""
		chain = self._main_versions_asc()
		numbers = [v.version_number for v in chain]
		if version_number not in numbers:
			raise ValueError(
				f"Version {version_number} does not exist for {self!r}. "
				f"Available: {numbers}"
			)
		return self._reconstruct_at(version_number, chain)

	def revert_to_version(self, version_number: int) -> None:
		"""
		Apply a historic version's field values to the current instance.

		Does not commit — the caller must call session.commit() after.

		Args:
			version_number: The target version to restore.

		Raises:
			ValueError: Version number does not exist.
		"""
		data = self.get_version_data(version_number)
		for attr, value in data.items():
			setattr(self, attr, value)

	def compare_versions(
		self,
		version1: int,
		version2: int,
		ignore_order: bool = True,
	) -> DeepDiff:
		"""
		Structural diff between two versions.

		Args:
			version1: First version number.
			version2: Second version number.
			ignore_order: Passed through to DeepDiff (default True).

		Returns:
			DeepDiff result — empty dict means identical.
		"""
		data1 = self.get_version_data(version1)
		data2 = self.get_version_data(version2)
		return DeepDiff(data1, data2, ignore_order=ignore_order)

	def get_version_history(self) -> list[dict[str, Any]]:
		"""
		Summarise the main-branch version log (no data payloads).

		Returns:
			List of dicts with keys: version_number, created_at, user_id, comment,
			is_snapshot — ordered newest-first.
		"""
		return [
			{
				"version_number": v.version_number,
				"created_at": v.created_at,
				"user_id": v.user_id,
				"comment": v.comment,
				"is_snapshot": bool(v.is_snapshot),
			}
			for v in self.versions  # relationship already ordered desc
		]

	def create_branch(
		self,
		branch_name: str,
		base_version: int | None = None,
	) -> ModelBranch:
		"""
		Fork a named branch from the current state or a specific historic version.

		The branch stores a full data snapshot at its creation point, independent
		of the main version chain.

		Args:
			branch_name: Unique name for this branch.
			base_version: If provided, snapshot that version; otherwise snapshot
				          the live instance fields.

		Returns:
			The newly created ModelBranch instance.

		Raises:
			ValueError: A branch with `branch_name` already exists on this record,
			            or `base_version` does not exist.
		"""
		session = self._db_session()

		if any(b.name == branch_name for b in self.branches):
			raise ValueError(
				f"Branch '{branch_name}' already exists on {self!r}."
			)

		if base_version is not None:
			data = self.get_version_data(base_version)
		else:
			data = self._current_data()
			base_version = self.versions[0].version_number if self.versions else None

		branch = ModelBranch(
			parent_id=self.id,
			name=branch_name,
			data=data,
			base_version=base_version,
		)
		session.add(branch)
		return branch

	def merge_branch(
		self,
		branch_name: str,
		resolve_conflicts: Callable[[dict, dict], dict] | None = None,
		user_id: int | None = None,
		comment: str | None = None,
	) -> ModelVersion:
		"""
		Merge a named branch back into the main version timeline.

		When the branch data differs from the current main-branch state, the
		caller must supply `resolve_conflicts`. The resolver receives
		``(main_data, branch_data)`` and must return the resolved dict.

		Args:
			branch_name: Name of the branch to merge.
			resolve_conflicts: Optional callable for conflict resolution.
			user_id: Attributed to the resulting version entry.
			comment: Defaults to "Merged branch '<branch_name>'" if omitted.

		Returns:
			The new ModelVersion created by the merge.

		Raises:
			ValueError: Branch not found, or conflicts detected without a resolver.
		"""
		session = self._db_session()

		branch = next((b for b in self.branches if b.name == branch_name), None)
		if branch is None:
			raise ValueError(
				f"Branch '{branch_name}' does not exist on {self!r}."
			)

		main_data = self._current_data()
		branch_data: dict[str, Any] = dict(branch.data)

		diff = DeepDiff(main_data, branch_data, ignore_order=True)
		if diff:
			if resolve_conflicts is None:
				raise ValueError(
					f"Conflicts detected merging '{branch_name}' into {self!r}. "
					"Provide a resolve_conflicts callable."
				)
			resolved = resolve_conflicts(main_data, branch_data)
			for attr, value in resolved.items():
				setattr(self, attr, value)
		else:
			# Branch is identical to main — apply branch fields anyway (no-op safe)
			for attr, value in branch_data.items():
				setattr(self, attr, value)

		version = self.save_version(
			user_id=user_id,
			comment=comment or f"Merged branch '{branch_name}'",
		)
		session.delete(branch)
		return version

	def diff_from_current(self, version_number: int) -> DeepDiff:
		"""
		Convenience: compare a historic version against the live (unsaved) state.

		Args:
			version_number: Historic version to compare against current fields.

		Returns:
			DeepDiff result.
		"""
		historic = self.get_version_data(version_number)
		current = self._current_data()
		return DeepDiff(historic, current, ignore_order=True)
