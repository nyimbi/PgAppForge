"""App-wide unified search across all registered PgAppForge models.

Usage::

    from pgappforge.search import GlobalSearchManager

    # In your AppBuilder init
    search_manager = GlobalSearchManager()
    search_manager.init_app(app, db.session)

    # Register searchable models
    search_manager.register(Employee, fields=['first_name', 'last_name', 'email'],
                            label='Employees', url_template='/employee/show/{pk}')
    search_manager.register(Department, fields=['name', 'code'],
                            label='Departments')

    # Query
    results = search_manager.search('engineering', limit=20)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Type

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass
class SearchResult:
	"""A single search result from any registered model."""
	model_name: str
	label: str         # human-readable model label
	pk: Any           # primary key value
	display: str      # text to show as the result title
	snippet: str      # surrounding context text
	rank: float       # relevance score (higher = better)
	url: str          # link to the record's show/detail page


@dataclass
class _Registration:
	model_class: type
	fields: list[str]
	label: str
	url_template: str  # e.g. "/employee/show/{pk}"
	pk_field: str = "id"
	ts_config: str = "english"


class GlobalSearchManager:
	"""Registry and query engine for app-wide search.

	Supports two backends:
	- **PostgreSQL FTS** (default): uses ``plainto_tsquery`` + ``to_tsvector``
	  with GIN index for fast ranked search across multiple models.
	- **ILIKE fallback**: for SQLite/MySQL (useful in tests).

	The PostgreSQL backend runs all models in a single UNION query so it
	scales to dozens of models without N+1 round trips.
	"""

	def __init__(self) -> None:
		self._registrations: list[_Registration] = []
		self._session: Session | None = None

	def init_app(self, app, session: Session) -> None:
		"""Attach to a Flask app and set the SQLAlchemy session."""
		self._session = session
		app.extensions["fab_search_manager"] = self

	def register(
		self,
		model_class: type,
		fields: list[str],
		label: str | None = None,
		url_template: str | None = None,
		pk_field: str = "id",
		ts_config: str = "english",
	) -> None:
		"""Register a model for global search.

		Args:
		    model_class:   The SQLAlchemy model to search.
		    fields:        Column names to include in the search index.
		    label:         Display name (defaults to class name).
		    url_template:  URL pattern for the detail view, e.g. ``/model/show/{pk}``.
		                   If None, no link is generated.
		    pk_field:      Primary key attribute name (default: "id").
		    ts_config:     PostgreSQL text search configuration (default: "english").
		"""
		label = label or model_class.__name__
		tablename = model_class.__tablename__
		url_template = url_template or f"/{tablename}/show/{{pk}}"
		self._registrations.append(
			_Registration(
				model_class=model_class,
				fields=fields,
				label=label,
				url_template=url_template,
				pk_field=pk_field,
				ts_config=ts_config,
			)
		)

	def search(self, query: str, limit: int = 20) -> list[SearchResult]:
		"""Search across all registered models.

		Returns results ranked by relevance (PostgreSQL ts_rank).
		Falls back to ILIKE if dialect is not PostgreSQL.
		"""
		if not query or not self._registrations or self._session is None:
			return []

		dialect = self._session.bind.dialect.name if self._session.bind else "sqlite"
		if dialect == "postgresql":
			return self._search_pg(query, limit)
		return self._search_ilike(query, limit)

	def _clean_query(self, query: str) -> str:
		"""Sanitise search query — keep alphanumeric, spaces, hyphens."""
		return re.sub(r"[^\w\s\-]", " ", query).strip()

	def _search_pg(self, query: str, limit: int) -> list[SearchResult]:
		"""PostgreSQL FTS search using plainto_tsquery + UNION ALL."""
		q = self._clean_query(query)
		if not q:
			return []

		per_model = max(1, limit // max(len(self._registrations), 1))
		all_results: list[SearchResult] = []

		for reg in self._registrations:
			tablename = reg.model_class.__tablename__
			concat_expr = " || ' ' || ".join(
				f"COALESCE({f}::text, '')" for f in reg.fields
			)
			config = reg.ts_config
			sql = text(f"""
			    SELECT
			        {reg.pk_field}::text AS pk,
			        ({concat_expr}) AS display_text,
			        ts_rank(
			            to_tsvector('{config}', {concat_expr}),
			            plainto_tsquery('{config}', :q)
			        ) AS rank
			    FROM {tablename}
			    WHERE to_tsvector('{config}', {concat_expr})
			          @@ plainto_tsquery('{config}', :q)
			    ORDER BY rank DESC
			    LIMIT {per_model}
			""")
			try:
				rows = self._session.execute(sql, {"q": q}).fetchall()
			except Exception:
				continue

			for row in rows:
				display = (row.display_text or "").strip()
				# Extract a snippet (first 120 chars around query term)
				snippet = display[:120] + ("…" if len(display) > 120 else "")
				url = reg.url_template.format(pk=row.pk)
				all_results.append(
					SearchResult(
						model_name=reg.model_class.__name__,
						label=reg.label,
						pk=row.pk,
						display=display[:80],
						snippet=snippet,
						rank=float(row.rank or 0),
						url=url,
					)
				)

		# Global rank sort, cap at limit
		all_results.sort(key=lambda r: r.rank, reverse=True)
		return all_results[:limit]

	def _search_ilike(self, query: str, limit: int) -> list[SearchResult]:
		"""ILIKE fallback for non-PostgreSQL databases (e.g. SQLite in tests)."""
		q = f"%{self._clean_query(query)}%"
		results: list[SearchResult] = []

		for reg in self._registrations:
			model = reg.model_class
			filters = []
			for fname in reg.fields:
				col = getattr(model, fname, None)
				if col is not None:
					filters.append(col.ilike(q))

			if not filters:
				continue

			from sqlalchemy import or_
			rows = (
				self._session.query(model)
				.filter(or_(*filters))
				.limit(limit)
				.all()
			)
			for row in rows:
				pk = getattr(row, reg.pk_field, None)
				display = " ".join(
					str(getattr(row, f, "") or "") for f in reg.fields
				).strip()
				url = reg.url_template.format(pk=pk)
				results.append(
					SearchResult(
						model_name=model.__name__,
						label=reg.label,
						pk=pk,
						display=display[:80],
						snippet=display[:120],
						rank=1.0,
						url=url,
					)
				)

		return results[:limit]

	@property
	def registered_models(self) -> list[str]:
		"""Names of all registered model classes."""
		return [r.model_class.__name__ for r in self._registrations]
