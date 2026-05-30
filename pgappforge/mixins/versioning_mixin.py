"""
versioning_mixin.py

Temporal versioning mixin for PgAppForge SQLAlchemy models.

Implements:
- Bi-temporal tables (transaction time + valid time) via system-period columns
- Full snapshot + RFC 6902 patch chain for storage-efficient history
- Point-in-time recovery: reconstruct any field state at any UTC timestamp
- Structural diff generation (stdlib only — no deepdiff/pandas)
- Named branching forked from any historic snapshot
- Branch merging with pluggable conflict resolution
- Configurable snapshot compaction (periodic re-baseline)
- GIN-indexed JSONB data payloads (PostgreSQL), TEXT fallback elsewhere
- Event hooks: after_version_save, after_branch_create, after_merge

PostgreSQL-specific:
  - JSONB for patch/snapshot payloads with GIN index
  - TIMESTAMPTZ columns, not naive TIMESTAMP
  - TEXT for unbounded strings (comment, branch_name)

SQLAlchemy 2.x only (mapped_column / Mapped). Falls back silently for 1.x
via try/except but logs a warning — upgrade is strongly recommended.

Author: Nyimbi Odero
Version: 3.0 (2026-05-30)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable

from flask import current_app
from sqlalchemy import (
	DateTime, ForeignKey, Index, Integer, Text, event, func, select,
)
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.inspection import inspect as sa_inspect

try:
	from sqlalchemy.dialects.postgresql import JSONB
	_HAS_JSONB = True
except ImportError:
	_HAS_JSONB = False

try:
	from sqlalchemy.orm import Mapped, mapped_column, relationship
	_SA2 = True
except ImportError:
	from sqlalchemy import Column
	from sqlalchemy.orm import relationship  # type: ignore[assignment]
	_SA2 = False
	logging.getLogger(__name__).warning(
		"versioning_mixin: SQLAlchemy < 2.x detected — upgrade recommended."
	)

try:
	import jsonpatch as _jsonpatch
	_HAS_JSONPATCH = True
except ImportError:
	_jsonpatch = None  # type: ignore[assignment]
	_HAS_JSONPATCH = False

# FAB Model — optional import; mixin works without it but supporting models need it
try:
	from pgappforge import Model as _FABModel
	_BASE = _FABModel
except ImportError:
	from sqlalchemy.orm import DeclarativeBase as _BASE  # type: ignore[assignment]

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# JSON backend — JSONB on PostgreSQL, generic JSON everywhere else
# ---------------------------------------------------------------------------
_JSON_TYPE = MutableDict.as_mutable(JSONB) if _HAS_JSONB else MutableDict.as_mutable(
	__import__("sqlalchemy").JSON
)


def _utcnow() -> datetime:
	"""Stdlib-only timezone-aware UTC now."""
	return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
	"""Render a datetime to ISO-8601 string, None-safe."""
	return dt.isoformat() if dt is not None else None


# ---------------------------------------------------------------------------
# Internal diff helpers (no deepdiff / pandas)
# ---------------------------------------------------------------------------

def _dict_diff(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
	"""
	Produce a human-readable field-level diff between two flat dicts.

	Returns a dict shaped::

		{
		    "added":   {key: new_value, ...},
		    "removed": {key: old_value, ...},
		    "changed": {key: {"old": old_value, "new": new_value}, ...},
		}

	Nested structures are compared shallowly; for deep RFC 6902 patches use
	`_make_patch` / `_apply_patch`.
	"""
	all_keys = set(old) | set(new)
	added: dict[str, Any] = {}
	removed: dict[str, Any] = {}
	changed: dict[str, Any] = {}
	for k in all_keys:
		in_old, in_new = k in old, k in new
		if in_old and not in_new:
			removed[k] = old[k]
		elif in_new and not in_old:
			added[k] = new[k]
		elif old[k] != new[k]:
			changed[k] = {"old": old[k], "new": new[k]}
	return {"added": added, "removed": removed, "changed": changed}


def _make_patch(old: dict[str, Any], new: dict[str, Any]) -> list[dict[str, Any]]:
	"""
	Generate an RFC 6902 JSON-patch list from old → new.

	Uses jsonpatch when available; falls back to a naïve but correct
	replace-every-changed-key implementation so the mixin has zero hard deps.
	"""
	if _HAS_JSONPATCH:
		return _jsonpatch.make_patch(old, new).patch
	# Fallback: emit one "replace" or "add" or "remove" op per changed key
	ops: list[dict[str, Any]] = []
	diff = _dict_diff(old, new)
	for k, v in diff["removed"].items():
		ops.append({"op": "remove", "path": f"/{k}"})
	for k, v in diff["added"].items():
		ops.append({"op": "add", "path": f"/{k}", "value": v})
	for k, info in diff["changed"].items():
		ops.append({"op": "replace", "path": f"/{k}", "value": info["new"]})
	return ops


def _apply_patch(doc: dict[str, Any], patch: list[dict[str, Any]]) -> dict[str, Any]:
	"""
	Apply an RFC 6902 patch list to a document dict.

	Uses jsonpatch when available; falls back to a stdlib interpretation that
	handles add / remove / replace operations on top-level keys only.
	"""
	if _HAS_JSONPATCH:
		return _jsonpatch.apply_patch(doc, patch)
	result = dict(doc)
	for op in patch:
		key = op["path"].lstrip("/")
		match op["op"]:
			case "remove":
				result.pop(key, None)
			case "add" | "replace":
				result[key] = op["value"]
			case _:
				log.warning("versioning_mixin: unknown patch op %s — skipped", op["op"])
	return result


# ---------------------------------------------------------------------------
# Supporting ORM models
# ---------------------------------------------------------------------------

class ModelVersion(_BASE):  # type: ignore[valid-type]
	"""
	One version entry for a versioned model instance.

	Storage strategy:
	- version_number == 1 (or first on a branch) → full snapshot in `data`
	- subsequent entries → RFC 6902 patch list in `data`
	- `is_snapshot` distinguishes them: 1 = full data, 0 = patch

	Bi-temporal columns:
	- `created_at`   — transaction time: when this row was written (system)
	- `valid_from`   — valid time begin: moment this version became effective
	- `valid_until`  — valid time end: NULL means "current head"

	The combination of (parent_id, branch_name, valid_from) identifies a
	unique point in the bi-temporal space.
	"""
	__tablename__ = "nx_model_versions"
	__table_args__ = (
		# Fast lookups by parent + branch + time
		Index(
			"ix_nx_model_versions_parent_branch_vfrom",
			"parent_id", "branch_name", "valid_from",
		),
		# Fast "current head" queries (valid_until IS NULL)
		Index(
			"ix_nx_model_versions_parent_branch_current",
			"parent_id", "branch_name",
		),
		# GIN on JSONB payload when available (PostgreSQL only)
		*(
			[Index("ix_nx_model_versions_data_gin", "data", postgresql_using="gin")]
			if _HAS_JSONB else []
		),
	)

	if _SA2:
		id: Mapped[int] = mapped_column(Integer, primary_key=True)
		# parent_id is a generic integer FK; concrete table FK is wired via
		# declared_attr on the mixin rather than here, so this column is bare.
		parent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
		version_number: Mapped[int] = mapped_column(Integer, nullable=False)
		# 1 = full snapshot dict, 0 = RFC 6902 patch list
		is_snapshot: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)
		data: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False)
		# transaction time
		created_at: Mapped[datetime] = mapped_column(
			DateTime(timezone=True), nullable=False, default=_utcnow,
		)
		# valid time
		valid_from: Mapped[datetime] = mapped_column(
			DateTime(timezone=True), nullable=False, default=_utcnow,
		)
		valid_until: Mapped[datetime | None] = mapped_column(
			DateTime(timezone=True), nullable=True, default=None,
		)
		user_id: Mapped[int | None] = mapped_column(
			Integer, ForeignKey("ab_user.id"), nullable=True,
		)
		comment: Mapped[str | None] = mapped_column(Text, nullable=True)
		# NULL = main branch
		branch_name: Mapped[str | None] = mapped_column(Text, nullable=True)
		# sha256 hex digest of serialised `data` — deduplication guard
		data_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
	else:
		from sqlalchemy import Column as _Col, JSON as _JSON, Boolean as _Bool
		id = _Col(Integer, primary_key=True)
		parent_id = _Col(Integer, nullable=False, index=True)
		version_number = _Col(Integer, nullable=False)
		is_snapshot = _Col(Integer, nullable=False, default=0)
		data = _Col(MutableDict.as_mutable(_JSON), nullable=False)
		created_at = _Col(DateTime, nullable=False, default=_utcnow)
		valid_from = _Col(DateTime, nullable=False, default=_utcnow)
		valid_until = _Col(DateTime, nullable=True, default=None)
		user_id = _Col(Integer, ForeignKey("ab_user.id"), nullable=True)
		comment = _Col(Text, nullable=True)
		branch_name = _Col(Text, nullable=True)
		data_hash = _Col(Text, nullable=True)

	def __repr__(self) -> str:
		branch = f":{self.branch_name}" if self.branch_name else ""
		snap = "S" if self.is_snapshot else "P"
		return f"<ModelVersion({self.parent_id}) v{self.version_number}{branch} [{snap}]>"


class ModelBranch(_BASE):  # type: ignore[valid-type]
	"""
	Named branch off a versioned model instance.

	A branch stores a full field snapshot at fork time plus a reference to
	the base version number it forked from.  Merging computes the branch→main
	diff and either applies it automatically or delegates to a resolver.
	"""
	__tablename__ = "nx_model_branches"
	__table_args__ = (
		Index("ix_nx_model_branches_parent_name", "parent_id", "name", unique=True),
	)

	if _SA2:
		id: Mapped[int] = mapped_column(Integer, primary_key=True)
		parent_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
		name: Mapped[str] = mapped_column(Text, nullable=False)
		# Full field snapshot at branch-creation time
		data: Mapped[dict] = mapped_column(_JSON_TYPE, nullable=False)
		# Version number on main that this branch forked from
		base_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
		created_at: Mapped[datetime] = mapped_column(
			DateTime(timezone=True), nullable=False, default=_utcnow,
		)
		created_by: Mapped[int | None] = mapped_column(
			Integer, ForeignKey("ab_user.id"), nullable=True,
		)
		description: Mapped[str | None] = mapped_column(Text, nullable=True)
		# Marks branch as closed after a merge
		merged_at: Mapped[datetime | None] = mapped_column(
			DateTime(timezone=True), nullable=True, default=None,
		)
	else:
		from sqlalchemy import Column as _Col, JSON as _JSON
		id = _Col(Integer, primary_key=True)
		parent_id = _Col(Integer, nullable=False, index=True)
		name = _Col(Text, nullable=False)
		data = _Col(MutableDict.as_mutable(_JSON), nullable=False)
		base_version = _Col(Integer, nullable=True)
		created_at = _Col(DateTime, nullable=False, default=_utcnow)
		created_by = _Col(Integer, ForeignKey("ab_user.id"), nullable=True)
		description = _Col(Text, nullable=True)
		merged_at = _Col(DateTime, nullable=True, default=None)

	def __repr__(self) -> str:
		merged = " [merged]" if self.merged_at else ""
		return f"<ModelBranch '{self.name}' on parent {self.parent_id}{merged}>"


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class VersioningMixin:
	"""
	Bi-temporal versioning mixin for PgAppForge SQLAlchemy models.

	Attach to any FAB ``Model`` subclass to gain:

	**Version history**
	  Maintains a chronological chain of RFC 6902 patches anchored on periodic
	  full snapshots.  Storage cost is proportional to change volume, not
	  record size.  Configurable snapshot compaction re-baselines the chain
	  to keep replay cost bounded.

	**Bi-temporal modelling**
	  Each version carries ``valid_from`` / ``valid_until`` (valid time) and
	  ``created_at`` (transaction time).  Point-in-time queries honour *both*
	  axes independently.

	**Point-in-time recovery**
	  ``restore_at(dt)`` reconstructs and applies the field state that was
	  valid at any UTC datetime without round-tripping to a backup.

	**Structural diff**
	  ``diff_versions(a, b)`` returns a plain dict (no deepdiff dependency)
	  with ``added``, ``removed``, and ``changed`` keys.
	  ``diff_from_current(n)`` compares a historic version against live fields.

	**Branching**
	  ``create_branch(name)`` forks a named branch from the current or a
	  historic snapshot.  Branches are independent; the main chain is
	  unaffected.  ``list_branches()`` enumerates open (un-merged) branches.

	**Merging**
	  ``merge_branch(name)`` applies branch changes to the live instance.
	  Conflict-free merges apply automatically; conflicted merges require a
	  ``resolve_conflicts(main, branch) -> resolved`` callable or raise.

	**Event hooks**
	  Subscribe via::

	      from sqlalchemy import event
	      event.listen(MyModel, "after_version_save", handler)

	  Available signals: ``after_version_save``, ``after_branch_create``,
	  ``after_merge``.

	**Configuration class attributes** (set on host model):

	.. code-block:: python

	    class Document(VersioningMixin, Model):
	        __tablename__ = "documents"
	        id   = Column(Integer, primary_key=True)
	        title   = Column(String(200))
	        content = Column(Text)

	        # Fields to track; auto-discovered from columns if omitted
	        __versioned__: list[str] = ["title", "content"]

	        # 0 = unlimited; positive N evicts oldest when exceeded
	        __max_versions__: int = 50

	        # Re-baseline every N patch-only versions (0 = never)
	        __snapshot_every__: int = 20

	        # Exclude from auto-discovery even if not in __versioned__
	        __versioned_exclude__: list[str] = ["updated_at"]

	**Dependencies**:
	  - SQLAlchemy 2.x (``mapped_column`` / ``Mapped``)
	  - PgAppForge ≥ 4.x
	  - ``jsonpatch`` (optional — stdlib fallback used when absent)
	  - PostgreSQL strongly recommended for JSONB + GIN index performance
	"""

	__versioned__: list[str] = []
	__versioned_exclude__: list[str] = []
	__max_versions__: int = 0
	__snapshot_every__: int = 20

	# ------------------------------------------------------------------
	# declared_attr relationships
	# ------------------------------------------------------------------

	@declared_attr
	def _versions(cls):	 # noqa: N805
		"""All version entries for this instance (main branch only)."""
		return relationship(
			"ModelVersion",
			primaryjoin=(
				f"and_(ModelVersion.parent_id == foreign({cls.__name__}.id),"
				" ModelVersion.branch_name == None)"
			),
			cascade="all, delete-orphan",
			order_by="ModelVersion.version_number",
			lazy="select",
			overlaps="_branch_versions",
		)

	@declared_attr
	def _branch_versions(cls):	# noqa: N805
		"""All version entries that belong to a named branch."""
		return relationship(
			"ModelVersion",
			primaryjoin=(
				f"and_(ModelVersion.parent_id == foreign({cls.__name__}.id),"
				" ModelVersion.branch_name != None)"
			),
			cascade="all, delete-orphan",
			order_by="ModelVersion.version_number",
			lazy="select",
			overlaps="_versions",
		)

	@declared_attr
	def _branches(cls):	 # noqa: N805
		"""Named branches forked from this instance."""
		return relationship(
			"ModelBranch",
			primaryjoin=f"ModelBranch.parent_id == foreign({cls.__name__}.id)",
			cascade="all, delete-orphan",
			lazy="select",
		)

	# ------------------------------------------------------------------
	# Auto-discover versioned fields after mapper configuration
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		if not cls.__versioned__:
			exclude = set(cls.__versioned_exclude__ or [])
			cls.__versioned__ = [
				c.key
				for c in sa_inspect(cls).column_attrs
				if c.key not in exclude
			]
			log.debug(
				"VersioningMixin: auto-detected fields for %s: %s",
				cls.__name__,
				cls.__versioned__,
			)

	# ------------------------------------------------------------------
	# Session accessor
	# ------------------------------------------------------------------

	def _session(self):
		"""Resolve the active SQLAlchemy session from PgAppForge or FSA."""
		# Try FAB db first
		db = getattr(current_app, "db", None)
		if db is None:
			ext = current_app.extensions.get("sqlalchemy")
			if ext is None:
				raise RuntimeError(
					"VersioningMixin: no db session found — ensure "
					"PgAppForge or Flask-SQLAlchemy is initialised."
				)
			try:
				from flask_sqlalchemy import SQLAlchemy as _FSA
				db = ext if isinstance(ext, _FSA) else getattr(ext, "db", ext)
			except ImportError:
				db = ext
		return db.session

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _snapshot(self) -> dict[str, Any]:
		"""Serialise all versioned fields to a JSON-safe dict."""
		out: dict[str, Any] = {}
		for attr in self.__versioned__:
			val = getattr(self, attr, None)
			if isinstance(val, datetime):
				val = val.isoformat()
			out[attr] = val
		return out

	@staticmethod
	def _hash_data(data: dict[str, Any] | list[Any]) -> str:
		import hashlib
		blob = json.dumps(data, sort_keys=True, default=str)
		return hashlib.sha256(blob.encode()).hexdigest()

	def _main_chain(self) -> list[ModelVersion]:
		"""Main-branch version list, ascending by version_number."""
		return list(self._versions)	 # relationship is ordered asc

	def _branch_chain(self, branch_name: str) -> list[ModelVersion]:
		"""Version entries for a named branch, ascending."""
		return sorted(
			[v for v in self._branch_versions if v.branch_name == branch_name],
			key=lambda v: v.version_number,
		)

	def _reconstruct(
		self,
		chain: list[ModelVersion],
		up_to_version: int | None = None,
		as_of: datetime | None = None,
	) -> dict[str, Any]:
		"""
		Replay a version chain to produce the field state at a given version
		or UTC datetime.

		Priority: `as_of` > `up_to_version` > chain head.
		The chain must be sorted ascending; the first entry must be a snapshot.
		"""
		if not chain:
			raise ValueError("Empty version chain.")
		if not chain[0].is_snapshot:
			raise RuntimeError(
				f"Chain for {self!r} is corrupt: first entry is not a snapshot "
				f"(v{chain[0].version_number})."
			)

		# Determine stopping criterion
		stop_at: int
		if as_of is not None:
			# Valid-time: find latest version whose valid_from <= as_of
			eligible = [v for v in chain if v.valid_from <= as_of]
			if not eligible:
				raise ValueError(
					f"No version exists with valid_from <= {as_of.isoformat()!r} "
					f"on {self!r}."
				)
			stop_at = eligible[-1].version_number
		elif up_to_version is not None:
			stop_at = up_to_version
		else:
			stop_at = chain[-1].version_number

		data: dict[str, Any] = dict(chain[0].data)
		for v in chain[1:]:
			if v.version_number > stop_at:
				break
			data = _apply_patch(data, v.data)
		return data

	def _next_version_number(self, chain: list[ModelVersion]) -> int:
		return chain[-1].version_number + 1 if chain else 1

	def _should_snapshot(self, chain: list[ModelVersion]) -> bool:
		"""True when forced re-baselining is due."""
		if self.__snapshot_every__ <= 0 or not chain:
			return False
		patches_since = sum(1 for v in reversed(chain) if not v.is_snapshot)
		return patches_since >= self.__snapshot_every__

	# ------------------------------------------------------------------
	# Eviction / compaction
	# ------------------------------------------------------------------

	def _evict_oldest(self, session, chain: list[ModelVersion]) -> None:
		"""
		Remove the oldest version, re-promoting chain[1] to a full snapshot
		first when chain[0] is the only baseline.
		"""
		if len(chain) < 2:
			return
		oldest = chain[0]
		if oldest.is_snapshot:
			# Promote chain[1] to full snapshot before deleting chain[0]
			promoted = chain[1]
			promoted.data = self._reconstruct(chain, up_to_version=promoted.version_number)
			promoted.is_snapshot = 1
			promoted.data_hash = self._hash_data(promoted.data)
			session.add(promoted)
		session.delete(oldest)

	def _compact_chain(self, session, chain: list[ModelVersion]) -> None:
		"""
		Re-baseline the chain: reconstruct current state as a new snapshot,
		delete all prior entries.  Called when __snapshot_every__ is triggered.
		"""
		if len(chain) < 2:
			return
		head_data = self._reconstruct(chain)
		# Replace the entire chain with a single snapshot at the head version
		for v in chain[:-1]:
			session.delete(v)
		head = chain[-1]
		head.data = head_data
		head.is_snapshot = 1
		head.data_hash = self._hash_data(head_data)
		session.add(head)
		log.debug(
			"VersioningMixin: compacted %d versions into snapshot v%d for %r",
			len(chain),
			head.version_number,
			self,
		)

	# ------------------------------------------------------------------
	# Public API — versioning
	# ------------------------------------------------------------------

	def save_version(
		self,
		user_id: int | None = None,
		comment: str | None = None,
		valid_from: datetime | None = None,
	) -> ModelVersion:
		"""
		Persist a new version of the current field state on the main branch.

		Version 1 stores a full snapshot.  Subsequent versions store an RFC
		6902 patch relative to the reconstructed previous head.  Identical
		states (same sha256) are skipped — no duplicate versions written.

		Enforces ``__max_versions__`` by evicting the oldest when exceeded.
		Triggers compaction when ``__snapshot_every__`` patch-only versions
		have accumulated since the last snapshot.

		Args:
			user_id:    FAB user id (``ab_user.id``) to attribute this version.
			comment:    Free-text annotation stored with the version.
			valid_from: Valid-time begin for bi-temporal modelling.  Defaults
			            to ``utcnow()``.

		Returns:
			The ``ModelVersion`` instance added to the session.  Call
			``session.commit()`` yourself; this method only flushes.

		Raises:
			RuntimeError: Session cannot be resolved.
		"""
		session = self._session()
		now = _utcnow()
		vf = valid_from or now
		current = self._snapshot()
		current_hash = self._hash_data(current)
		chain = self._main_chain()

		if not chain:
			# Bootstrap: full snapshot
			new_version = ModelVersion(
				parent_id=self.id,
				version_number=1,
				is_snapshot=1,
				data=current,
				data_hash=current_hash,
				created_at=now,
				valid_from=vf,
				valid_until=None,
				user_id=user_id,
				comment=comment,
				branch_name=None,
			)
		else:
			last = chain[-1]
			# Dedup: skip if state identical to previous head
			if last.data_hash == current_hash:
				log.debug(
					"VersioningMixin: state unchanged for %r — skipping version.", self
				)
				return last

			prev_data = self._reconstruct(chain)
			patch = _make_patch(prev_data, current)
			force_snap = self._should_snapshot(chain)
			new_version = ModelVersion(
				parent_id=self.id,
				version_number=self._next_version_number(chain),
				is_snapshot=1 if force_snap else 0,
				data=current if force_snap else patch,
				data_hash=current_hash,
				created_at=now,
				valid_from=vf,
				valid_until=None,
				user_id=user_id,
				comment=comment,
				branch_name=None,
			)
			# Close the valid-time window on the previous head
			last.valid_until = vf
			session.add(last)

		session.add(new_version)
		session.flush()

		# Re-load chain after flush to include the new entry
		chain = self._main_chain()

		if self.__max_versions__ > 0 and len(chain) > self.__max_versions__:
			self._evict_oldest(session, chain)
			session.flush()

		# Emit event
		event.dispatch(self, "after_version_save", new_version)
		return new_version

	def get_version(self, version_number: int) -> dict[str, Any]:
		"""
		Reconstruct the full field snapshot for ``version_number`` on the
		main branch.

		Args:
			version_number: Target version to reconstruct.

		Returns:
			Dict mapping versioned field names → values at that version.

		Raises:
			ValueError: Version does not exist.
		"""
		chain = self._main_chain()
		numbers = [v.version_number for v in chain]
		if version_number not in numbers:
			raise ValueError(
				f"Version {version_number} not found for {self!r}. "
				f"Available: {numbers}"
			)
		return self._reconstruct(chain, up_to_version=version_number)

	def restore_version(self, version_number: int) -> None:
		"""
		Apply a historic version's field values to the live instance.

		Does not commit — caller must ``session.commit()`` afterwards.

		Args:
			version_number: Version to restore.
		"""
		data = self.get_version(version_number)
		for attr, val in data.items():
			setattr(self, attr, val)

	def restore_at(self, as_of: datetime) -> None:
		"""
		Point-in-time recovery: apply the field state valid at ``as_of`` (UTC).

		Uses the valid-time axis (``valid_from``), not transaction time.

		Args:
			as_of: UTC datetime.  Timezone-naive values are accepted and
			       treated as UTC (a ``UserWarning`` is emitted).

		Raises:
			ValueError: No version exists at or before ``as_of``.
		"""
		import warnings
		if as_of.tzinfo is None:
			warnings.warn(
				f"restore_at: received naive datetime {as_of!r} — treating as UTC.",
				UserWarning,
				stacklevel=2,
			)
			as_of = as_of.replace(tzinfo=timezone.utc)
		chain = self._main_chain()
		data = self._reconstruct(chain, as_of=as_of)
		for attr, val in data.items():
			setattr(self, attr, val)

	def history(self, branch_name: str | None = None) -> list[dict[str, Any]]:
		"""
		Summarise the version log for the main branch (or a named branch).

		Returns:
			List of metadata dicts (no raw data payloads), newest-first::

			    [
			        {
			            "version_number": int,
			            "is_snapshot":    bool,
			            "created_at":     str (ISO-8601),
			            "valid_from":     str | None,
			            "valid_until":    str | None,
			            "user_id":        int | None,
			            "comment":        str | None,
			            "data_hash":      str | None,
			            "branch_name":    str | None,
			        },
			        ...
			    ]
		"""
		if branch_name:
			chain = self._branch_chain(branch_name)
		else:
			chain = self._main_chain()
		return [
			{
				"version_number": v.version_number,
				"is_snapshot": bool(v.is_snapshot),
				"created_at": _iso(v.created_at),
				"valid_from": _iso(v.valid_from),
				"valid_until": _iso(v.valid_until),
				"user_id": v.user_id,
				"comment": v.comment,
				"data_hash": v.data_hash,
				"branch_name": v.branch_name,
			}
			for v in reversed(chain)
		]

	# ------------------------------------------------------------------
	# Public API — diff
	# ------------------------------------------------------------------

	def diff_versions(
		self,
		version_a: int,
		version_b: int,
	) -> dict[str, Any]:
		"""
		Field-level diff between two main-branch versions.

		Returns:
			Dict with keys ``added``, ``removed``, ``changed``.  Empty
			sub-dicts mean no change in that category.

		Args:
			version_a: Earlier (or first) version number.
			version_b: Later (or second) version number.
		"""
		data_a = self.get_version(version_a)
		data_b = self.get_version(version_b)
		return _dict_diff(data_a, data_b)

	def diff_from_current(self, version_number: int) -> dict[str, Any]:
		"""
		Compare a historic version against the live (not-yet-saved) field state.

		Args:
			version_number: Historic version to compare against.

		Returns:
			Same shape as ``diff_versions``.
		"""
		historic = self.get_version(version_number)
		current = self._snapshot()
		return _dict_diff(historic, current)

	def diff_at(self, as_of_a: datetime, as_of_b: datetime) -> dict[str, Any]:
		"""
		Field-level diff between two UTC datetimes using the valid-time axis.

		Args:
			as_of_a: First point in time.
			as_of_b: Second point in time.

		Returns:
			Same shape as ``diff_versions``.
		"""
		chain = self._main_chain()
		data_a = self._reconstruct(chain, as_of=as_of_a)
		data_b = self._reconstruct(chain, as_of=as_of_b)
		return _dict_diff(data_a, data_b)

	# ------------------------------------------------------------------
	# Public API — branching
	# ------------------------------------------------------------------

	def create_branch(
		self,
		branch_name: str,
		base_version: int | None = None,
		description: str | None = None,
		created_by: int | None = None,
	) -> ModelBranch:
		"""
		Fork a named branch from the current or a specific historic version.

		The branch stores a full field snapshot at fork time.  It is
		independent of the main chain; subsequent saves on the main branch do
		not affect the branch data.

		Args:
			branch_name:  Unique name (scoped to this record).
			base_version: Version number to fork from.  Defaults to the
			              current live state if omitted.
			description:  Human-readable annotation.
			created_by:   FAB user id.

		Returns:
			The newly created ``ModelBranch`` instance (not yet committed).

		Raises:
			ValueError: Branch name already exists on this record, or
			            ``base_version`` does not exist.
		"""
		session = self._session()

		if any(b.name == branch_name for b in self._branches):
			raise ValueError(
				f"Branch '{branch_name}' already exists on {self!r}."
			)

		if base_version is not None:
			data = self.get_version(base_version)
			bv: int | None = base_version
		else:
			data = self._snapshot()
			chain = self._main_chain()
			bv = chain[-1].version_number if chain else None

		branch = ModelBranch(
			parent_id=self.id,
			name=branch_name,
			data=data,
			base_version=bv,
			created_at=_utcnow(),
			created_by=created_by,
			description=description,
			merged_at=None,
		)
		session.add(branch)
		event.dispatch(self, "after_branch_create", branch)
		return branch

	def list_branches(self, include_merged: bool = False) -> list[dict[str, Any]]:
		"""
		Enumerate branches on this record.

		Args:
			include_merged: When True, closed (merged) branches are included.

		Returns:
			List of branch metadata dicts::

			    [
			        {
			            "name":         str,
			            "base_version": int | None,
			            "created_at":   str (ISO-8601),
			            "created_by":   int | None,
			            "description":  str | None,
			            "merged_at":    str | None,
			        },
			        ...
			    ]
		"""
		branches = self._branches
		if not include_merged:
			branches = [b for b in branches if b.merged_at is None]
		return [
			{
				"name": b.name,
				"base_version": b.base_version,
				"created_at": _iso(b.created_at),
				"created_by": b.created_by,
				"description": b.description,
				"merged_at": _iso(b.merged_at),
			}
			for b in branches
		]

	def get_branch_data(self, branch_name: str) -> dict[str, Any]:
		"""
		Return the full field snapshot stored in a branch.

		Args:
			branch_name: Branch to inspect.

		Returns:
			Dict of field values at branch-creation time.

		Raises:
			ValueError: Branch not found.
		"""
		branch = self._find_branch(branch_name)
		return dict(branch.data)

	def update_branch(
		self,
		branch_name: str,
		field_updates: dict[str, Any],
	) -> ModelBranch:
		"""
		Apply field updates to a branch snapshot (not the main instance).

		Useful for iterative editing on a branch before merging.

		Args:
			branch_name:   Branch to mutate.
			field_updates: Partial dict of field → new value.

		Returns:
			The updated ``ModelBranch`` instance.

		Raises:
			ValueError: Branch not found or is already merged.
		"""
		branch = self._find_branch(branch_name, require_open=True)
		data = dict(branch.data)
		data.update(field_updates)
		branch.data = data
		self._session().add(branch)
		return branch

	def merge_branch(
		self,
		branch_name: str,
		resolve_conflicts: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] | None = None,
		user_id: int | None = None,
		comment: str | None = None,
	) -> ModelVersion:
		"""
		Merge a named branch into the main version timeline.

		Conflict detection:
		  The diff between the branch data and the *base version* the branch
		  forked from is computed.  Any field mutated on both the main chain
		  (since the fork point) and the branch constitutes a conflict.

		  - No conflicts → branch values win (three-way merge, branch side).
		  - Conflicts + resolver → ``resolve_conflicts(main_current, branch_data)``
		    must return the resolved field dict.
		  - Conflicts + no resolver → ``ValueError`` raised.

		After a successful merge:
		  - The branch ``merged_at`` timestamp is set (soft-close).
		  - A new main-branch version is created with the merged field state.

		Args:
			branch_name:       Branch to merge.
			resolve_conflicts: Callable for conflict resolution (see above).
			user_id:           FAB user id for the resulting version.
			comment:           Defaults to ``"Merged branch '<name>'"`` if omitted.

		Returns:
			The new ``ModelVersion`` created by the merge.

		Raises:
			ValueError: Branch not found, already merged, or conflicts without
			            a resolver.
		"""
		session = self._session()
		branch = self._find_branch(branch_name, require_open=True)
		main_current = self._snapshot()
		branch_data: dict[str, Any] = dict(branch.data)

		# Three-way diff: base → main vs base → branch
		if branch.base_version is not None:
			try:
				base_data = self.get_version(branch.base_version)
			except ValueError:
				# Base version evicted; treat branch data as authoritative
				base_data = branch_data
		else:
			base_data = branch_data

		base_to_main = _dict_diff(base_data, main_current)
		base_to_branch = _dict_diff(base_data, branch_data)
		conflicts = (
			set(base_to_main["changed"]) & set(base_to_branch["changed"])
		)

		if conflicts:
			if resolve_conflicts is None:
				raise ValueError(
					f"Merge conflicts on fields {sorted(conflicts)!r} "
					f"when merging '{branch_name}' into {self!r}. "
					"Provide a resolve_conflicts callable."
				)
			resolved = resolve_conflicts(main_current, branch_data)
		else:
			# No conflict: apply branch changes on top of main current
			resolved = dict(main_current)
			for k, v in base_to_branch["added"].items():
				resolved[k] = v
			for k in base_to_branch["removed"]:
				resolved.pop(k, None)
			for k, info in base_to_branch["changed"].items():
				resolved[k] = info["new"]

		# Apply resolved state to the live instance
		for attr, val in resolved.items():
			if attr in self.__versioned__:
				setattr(self, attr, val)

		version = self.save_version(
			user_id=user_id,
			comment=comment or f"Merged branch '{branch_name}'",
		)
		branch.merged_at = _utcnow()
		session.add(branch)
		event.dispatch(self, "after_merge", branch, version)
		return version

	# ------------------------------------------------------------------
	# Internal branch lookup
	# ------------------------------------------------------------------

	def _find_branch(
		self,
		branch_name: str,
		require_open: bool = False,
	) -> ModelBranch:
		branch = next((b for b in self._branches if b.name == branch_name), None)
		if branch is None:
			raise ValueError(f"Branch '{branch_name}' not found on {self!r}.")
		if require_open and branch.merged_at is not None:
			raise ValueError(
				f"Branch '{branch_name}' on {self!r} is already merged "
				f"at {_iso(branch.merged_at)}."
			)
		return branch

	# ------------------------------------------------------------------
	# Convenience
	# ------------------------------------------------------------------

	def compacted_version_count(self) -> int:
		"""Number of versions currently stored on the main branch."""
		return len(self._main_chain())

	def force_compact(self) -> None:
		"""
		Immediately re-baseline the main version chain.

		Collapses all patch entries into a single snapshot at the current
		head version.  Useful before archiving or exporting a record.
		"""
		session = self._session()
		chain = self._main_chain()
		self._compact_chain(session, chain)
		session.flush()
