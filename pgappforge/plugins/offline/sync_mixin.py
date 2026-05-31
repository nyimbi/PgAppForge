"""
pgappforge/plugins/offline/sync_mixin.py

SyncMixin for ModelRestApi — adds WatermelonDB-compatible pull/push sync
endpoints to any ModelRestApi subclass.

Usage::

	from pgappforge.plugins.offline.sync_mixin import SyncMixin
	from pgappforge.views import ModelRestApi

	class EmployeeApi(SyncMixin, ModelRestApi):
		datamodel = SQLAInterface(Employee)
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from flask import request
from flask_appbuilder.api import expose, protect, safe

log = logging.getLogger(__name__)

_SYNC_LIMIT = 500


class SyncMixin:
	"""
	Mixin for ModelRestApi that exposes WatermelonDB-compatible sync endpoints.

	GET  /api/v1/<resource>/sync?since=<unix_ms>
	     Returns changes in WatermelonDB pull format::

	         {
	           "changes": {
	             "<table>": {"created": [...], "updated": [...], "deleted": [...]}
	           },
	           "timestamp": <unix_ms_int>
	         }

	POST /api/v1/<resource>/sync
	     Accepts WatermelonDB push format::

	         {"changes": {"<table>": {"created": [...], "updated": [...], "deleted": [...]}}}

	     Returns::

	         {"pushed": <count>}

	Conflict strategy: server-wins — records that already exist locally are not
	overwritten; only genuinely new records are inserted.
	"""

	# ------------------------------------------------------------------
	# Pull
	# ------------------------------------------------------------------

	@expose("/sync", methods=["GET"])
	@protect()
	@safe
	def pull_changes(self):
		"""
		Pull changes since *since* (Unix milliseconds, 0 = full sync).

		Query params
		------------
		since : int  Unix timestamp in milliseconds (default 0).
		"""
		since_ms: int = int(request.args.get("since", 0) or 0)
		since_dt: datetime | None = None
		if since_ms > 0:
			since_dt = datetime.fromtimestamp(since_ms / 1000.0, tz=timezone.utc)

		model_cls = self._get_model_class()
		if model_cls is None:
			return self.response(500, message="model class not resolvable")

		table_name: str = getattr(model_cls, "__tablename__", model_cls.__name__.lower())
		session = self.appbuilder.get_session

		try:
			query = session.query(model_cls)
			if since_dt is not None and hasattr(model_cls, "updated_at"):
				query = query.filter(model_cls.updated_at > since_dt)
			rows = query.limit(_SYNC_LIMIT).all()
		except Exception as exc:
			log.error("sync pull error: %s", exc)
			return self.response(500, message=str(exc))

		created: list[dict[str, Any]] = []
		updated: list[dict[str, Any]] = []

		for row in rows:
			d = _row_to_dict(row)
			if since_dt is None:
				created.append(d)
			else:
				created.append(d) if _is_new(row, since_dt) else updated.append(d)

		timestamp_ms: int = int(time.time() * 1000)
		return self.response(
			200,
			changes={table_name: {"created": created, "updated": updated, "deleted": []}},
			timestamp=timestamp_ms,
		)

	# ------------------------------------------------------------------
	# Push
	# ------------------------------------------------------------------

	@expose("/sync", methods=["POST"])
	@protect()
	@safe
	def push_changes(self):
		"""
		Push changes from the client.  Server-wins: existing records are not
		overwritten — only records absent on the server are inserted.

		Body (JSON)
		-----------
		changes : dict  WatermelonDB changes payload.
		"""
		payload: dict = request.get_json(silent=True) or {}
		changes: dict = payload.get("changes", {})

		model_cls = self._get_model_class()
		if model_cls is None:
			return self.response(500, message="model class not resolvable")

		session = self.appbuilder.get_session
		pushed = 0

		try:
			for _table, ops in changes.items():
				for record in ops.get("created", []):
					pk_val = record.get("id")
					if pk_val is not None:
						existing = session.get(model_cls, pk_val)
						if existing is not None:
							# Server-wins: skip
							continue
					obj = model_cls()
					for key, val in record.items():
						if hasattr(obj, key):
							setattr(obj, key, val)
					session.add(obj)
					pushed += 1

				for record in ops.get("updated", []):
					pk_val = record.get("id")
					if pk_val is None:
						continue
					existing = session.get(model_cls, pk_val)
					if existing is None:
						# Record not on server yet — insert it
						obj = model_cls()
						for key, val in record.items():
							if hasattr(obj, key):
								setattr(obj, key, val)
						session.add(obj)
						pushed += 1
					# else server-wins: do nothing

				for record in ops.get("deleted", []):
					pk_val = record.get("id")
					if pk_val is None:
						continue
					existing = session.get(model_cls, pk_val)
					if existing is not None:
						session.delete(existing)
						pushed += 1

			session.commit()
		except Exception as exc:
			session.rollback()
			log.error("sync push error: %s", exc)
			return self.response(500, message=str(exc))

		return self.response(200, pushed=pushed)

	# ------------------------------------------------------------------
	# Helpers
	# ------------------------------------------------------------------

	def _get_model_class(self):
		"""Resolve the SQLAlchemy model class from the datamodel."""
		try:
			return self.datamodel.obj
		except Exception:
			pass
		try:
			return self.datamodel.model
		except Exception:
			pass
		return None


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict[str, Any]:
	"""Shallow-serialise a SQLAlchemy row to a JSON-safe dict."""
	try:
		from sqlalchemy import inspect as sa_inspect
		mapper = sa_inspect(type(row))
		result: dict[str, Any] = {}
		for col in mapper.column_attrs:
			val = getattr(row, col.key)
			if isinstance(val, datetime):
				val = val.isoformat()
			result[col.key] = val
		return result
	except Exception:
		return {}


def _is_new(row, since_dt: datetime) -> bool:
	"""Return True if the row was created at or after *since_dt*."""
	for attr in ("created_on", "created_at"):
		ts = getattr(row, attr, None)
		if ts is not None:
			if ts.tzinfo is None:
				ts = ts.replace(tzinfo=timezone.utc)
			return ts >= since_dt
	return False
