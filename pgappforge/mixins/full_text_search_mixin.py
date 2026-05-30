"""
full_text_search_mixin.py

Full-text search capabilities for SQLAlchemy models in PgAppForge
applications, backed by PostgreSQL's native tsquery/tsvector infrastructure.

Weighted column indexing, relevance ranking via ts_rank_cd, result
highlighting via ts_headline, GIN/GiST index management, and automatic
tsvector maintenance via DDL triggers are all provided out of the box.

Dependencies:
	- SQLAlchemy>=2.0
	- PgAppForge>=3.4.0
	- psycopg2-binary>=2.9.0 or psycopg>=3.0
	- PostgreSQL>=12

Author: Nyimbi Odero
Version: 2.0
"""

from __future__ import annotations

import logging
import re
from typing import Any

try:
	# SQLAlchemy 2.x
	from sqlalchemy import DDL, Column, Index, event, func, select, text
	from sqlalchemy.dialects.postgresql import REGCONFIG, TSVECTOR
	from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
	_SA2 = True
except ImportError:
	from sqlalchemy import DDL, Column, Index, event, func, text
	from sqlalchemy.dialects.postgresql import REGCONFIG, TSVECTOR
	_SA2 = False

from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Query
from sqlalchemy.sql import expression

from pgappforge.models.mixins import AuditMixin

_log = logging.getLogger(__name__)


class FullTextSearchMixin(AuditMixin):
	"""
	Mixin adding PostgreSQL full-text search to any PgAppForge model.

	Configure via class attributes before mapping:

		class Article(FullTextSearchMixin, Model):
			__tablename__ = 'articles'
			id = Column(Integer, primary_key=True)
			title = Column(String(200), nullable=False)
			content = Column(Text)

			__fulltext_columns__ = {
				'title': 'A',    # highest priority weight
				'content': 'B',  # secondary priority
			}
			__search_config__  = 'english'
			__index_type__     = 'gin'

	Class Attributes:
		__fulltext_columns__ (dict[str, str]):
			Maps column names to PostgreSQL weights A–D (A = highest).
		__tsvector_column__ (str):
			Name of the generated tsvector column (default: 'search_vector').
		__search_config__ (str):
			PostgreSQL text search configuration (default: 'english').
		__index_type__ (str):
			Index type — 'gin' (update-heavy) or 'gist' (space-constrained).
		__highlight_opts__ (dict[str, Any]):
			Default options forwarded to ts_headline().
	"""

	__fulltext_columns__: dict[str, str] = {}
	__tsvector_column__: str = "search_vector"
	__search_config__: str = "english"
	__index_type__: str = "gin"
	__highlight_opts__: dict[str, Any] = {
		"StartSel": "<mark>",
		"StopSel": "</mark>",
		"MaxWords": 35,
		"MinWords": 15,
		"ShortWord": 3,
		"HighlightAll": False,
		"MaxFragments": 3,
		"FragmentDelimiter": " ... ",
	}

	# ------------------------------------------------------------------
	# Declared columns — generated once per concrete subclass
	# ------------------------------------------------------------------

	@declared_attr
	def search_vector(cls) -> Column:
		"""Pre-computed tsvector for the row; updated by a DDL trigger."""
		return Column(TSVECTOR, nullable=True)

	@declared_attr
	def search_config(cls) -> Column:
		"""Per-row language configuration; defaults to cls.__search_config__."""
		return Column(
			REGCONFIG,
			nullable=False,
			server_default=text(f"'{cls.__search_config__}'::regconfig"),
		)

	# ------------------------------------------------------------------
	# DDL / event wiring
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""
		Called by SQLAlchemy after mapper configuration.

		Validates __fulltext_columns__, creates the GIN/GiST index, and
		registers a DDL trigger that keeps search_vector current on every
		INSERT/UPDATE.  Also wires Python-side before_insert/before_update
		listeners so in-session objects stay consistent without a round-trip.
		"""
		if not cls.__fulltext_columns__:
			raise ValueError(
				f"{cls.__name__}.__fulltext_columns__ must be non-empty"
			)

		valid_weights = {"A", "B", "C", "D"}
		bad = {w for w in cls.__fulltext_columns__.values() if w not in valid_weights}
		if bad:
			raise ValueError(
				f"Invalid weights {bad} in {cls.__name__}.__fulltext_columns__. "
				f"Allowed: {valid_weights}"
			)

		# Build weighted tsvector expression (Python-side, for before_insert/update)
		weight_groups: dict[str, list[str]] = {}
		for col, weight in cls.__fulltext_columns__.items():
			weight_groups.setdefault(weight, []).append(col)

		search_vector_expr = None
		for weight, columns in weight_groups.items():
			col_concat = " || ' ' || ".join(f"coalesce({c}, '')" for c in columns)
			weighted = func.setweight(
				func.to_tsvector(cls.search_config, text(col_concat)),
				weight,
			)
			search_vector_expr = (
				weighted if search_vector_expr is None
				else search_vector_expr.op("||")(weighted)
			)

		# GIN/GiST index on the tsvector column
		index_name = f"ix_{cls.__tablename__}_{cls.__tsvector_column__}"
		Index(
			index_name,
			"search_vector",
			postgresql_using=cls.__index_type__.lower(),
			postgresql_where=text("search_vector IS NOT NULL"),
		)

		# DDL trigger — uses PostgreSQL's built-in tsvector_update_trigger()
		column_list = ", ".join(cls.__fulltext_columns__.keys())
		trigger_name = f"{cls.__tablename__}_fts_vector_update"
		trigger_ddl = DDL(
			f"""
			CREATE OR REPLACE TRIGGER {trigger_name}
			BEFORE INSERT OR UPDATE ON {cls.__tablename__}
			FOR EACH ROW EXECUTE FUNCTION tsvector_update_trigger(
				{cls.__tsvector_column__},
				'{cls.__search_config__}',
				{column_list}
			);
			"""
		)

		@event.listens_for(cls.__table__, "after_create")
		def _create_fts_trigger(target, connection, **kw):
			connection.execute(trigger_ddl)
			_log.info(
				"Created FTS trigger %s on %s", trigger_name, cls.__tablename__
			)

		@event.listens_for(cls, "before_insert")
		@event.listens_for(cls, "before_update")
		def _sync_search_vector(mapper, connection, target):
			"""
			Keep search_vector consistent in the Python object graph so that
			code reading the attribute after flush() but before commit() sees
			the correct value.  The authoritative update is performed by the
			DDL trigger on the database side.
			"""
			try:
				target.search_vector = search_vector_expr
			except Exception as exc:
				_log.error(
					"Failed to update search_vector on %s pk=%s: %s",
					cls.__name__,
					getattr(target, "id", "?"),
					exc,
				)
				raise

	# ------------------------------------------------------------------
	# Search helpers (class methods, composable with any query)
	# ------------------------------------------------------------------

	@classmethod
	def search(
		cls,
		query: Query,
		search_term: str,
		*,
		sort: bool = True,
		highlight: list[str] | None = None,
		language: str | None = None,
		phrase: bool = False,
	) -> Query:
		"""
		Filter *query* to rows matching *search_term* using the tsvector index.

		Args:
			query:       Base SQLAlchemy ORM query targeting this model.
			search_term: One or more search words.
			sort:        Order results by ts_rank_cd descending (relevance).
			highlight:   Column names whose text should be annotated with
			             <mark>…</mark> spans; added as extra SELECT columns
			             named ``<col>_highlighted``.
			language:    Override cls.__search_config__ for this call.
			phrase:      Use phraseto_tsquery() instead of plainto_tsquery()
			             to enforce word adjacency.

		Returns:
			Filtered (and optionally sorted/annotated) ORM query.
		"""
		if not search_term or not search_term.strip():
			return query

		config = language or cls.__search_config__
		tsquery_fn = func.phraseto_tsquery if phrase else func.plainto_tsquery
		search_query = tsquery_fn(config, search_term.strip())
		result = query.filter(cls.search_vector.op("@@")(search_query))

		if highlight:
			for column_name in highlight:
				if column_name not in cls.__fulltext_columns__:
					_log.warning(
						"highlight column '%s' not in __fulltext_columns__; skipping",
						column_name,
					)
					continue
				col_attr = getattr(cls, column_name, None)
				if col_attr is None:
					continue
				result = result.add_columns(
					cls.highlight_term(
						col_attr, search_term, language=language
					).label(f"{column_name}_highlighted")
				)

		if sort:
			result = result.order_by(
				cls.search_ranking(search_term, language=language).desc()
			)

		return result

	@classmethod
	def highlight_term(
		cls,
		column: Column,
		search_term: str,
		*,
		language: str | None = None,
		options: dict[str, Any] | None = None,
	) -> expression.ClauseElement:
		"""
		Build a ts_headline() SQL expression for *column*.

		Args:
			column:      SQLAlchemy column attribute or expression.
			search_term: Term to highlight.
			language:    Override cls.__search_config__.
			options:     Override specific __highlight_opts__ keys.

		Returns:
			SQLAlchemy expression evaluating to annotated text.
		"""
		config = language or cls.__search_config__
		merged_opts: dict[str, Any] = {**cls.__highlight_opts__, **(options or {})}

		opts_str = ", ".join(
			f"{k}={int(v) if isinstance(v, bool) else v}"
			for k, v in merged_opts.items()
		)

		return func.ts_headline(
			config,
			column,
			func.plainto_tsquery(config, search_term),
			opts_str,
		)

	@classmethod
	def search_ranking(
		cls,
		search_term: str,
		*,
		language: str | None = None,
		weights: list[float] | None = None,
	) -> expression.ClauseElement:
		"""
		Build a ts_rank_cd() expression for relevance-based ordering.

		Args:
			search_term: Term to rank against.
			language:    Override cls.__search_config__.
			weights:     Four floats [D, C, B, A] adjusting weight impact.
			             Defaults to PostgreSQL built-in values.

		Returns:
			SQLAlchemy expression suitable for order_by().
		"""
		config = language or cls.__search_config__
		tsq = func.plainto_tsquery(config, search_term)
		if weights:
			if len(weights) != 4:
				raise ValueError("weights must have exactly 4 elements [D, C, B, A]")
			return func.ts_rank_cd(cls.search_vector, tsq, weights)
		return func.ts_rank_cd(cls.search_vector, tsq)

	# ------------------------------------------------------------------
	# Utility methods
	# ------------------------------------------------------------------

	@staticmethod
	def _log_pretty_path(path: str) -> str:
		"""Truncate long paths for log output."""
		return path if len(path) <= 60 else f"…{path[-57:]}"

	@staticmethod
	def remove_html_tags(raw: str) -> str:
		"""
		Strip HTML tags from *raw* using a compiled regex.

		Args:
			raw: Text that may contain HTML markup.

		Returns:
			Plain text with all tags removed.
		"""
		if not raw:
			return ""
		return re.sub(re.compile(r"<[^>]+>"), "", raw)

	@classmethod
	def reindex_all(
		cls,
		session: Session,
		batch_size: int = 1000,
	) -> int:
		"""
		Force-refresh search_vector for every row in the table.

		Iterates in batches to avoid loading the entire table into memory.
		Uses expire+refresh so that each object re-runs the before_update
		listener and the DDL trigger fires on the subsequent flush.

		Args:
			session:    Active SQLAlchemy session.
			batch_size: Rows processed per transaction.

		Returns:
			Total number of rows reindexed.

		Raises:
			Exception: Re-raises any DB error after rolling back.
		"""
		try:
			if _SA2:
				total: int = session.execute(
					select(func.count()).select_from(cls)
				).scalar_one()
			else:
				total = session.query(cls).count()

			processed = 0
			while processed < total:
				if _SA2:
					batch = session.execute(
						select(cls).limit(batch_size).offset(processed)
					).scalars().all()
				else:
					batch = (
						session.query(cls)
						.limit(batch_size)
						.offset(processed)
						.all()
					)

				for item in batch:
					session.expire(item)
					session.refresh(item)

				processed += len(batch)
				session.commit()
				_log.info(
					"[%s] reindexed %d/%d rows",
					cls.__name__,
					processed,
					total,
				)

			return processed

		except Exception as exc:
			_log.error("reindex_all failed on %s: %s", cls.__name__, exc)
			session.rollback()
			raise
