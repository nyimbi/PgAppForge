"""
pgappforge/plugins/erp/finance/gl/dimension_service.py

Dimensional GL service — Intacct-style multi-dimensional analysis.

Dimensions are tenant-defined arbitrary keys stored as JSONB on
GLJournalLine.dimensions.  This service provides:
  - Dimension catalogue management (define_dimension)
  - Dimension validation against catalogue (validate_dimensions)
  - P&L slice by any dimension combination (get_dimensional_pnl)
  - Statistical account KPI report (get_kpi_report)

Join chain: GLJournalLine → GLJournalEntry → GLJournalBatch → GLPeriod → GLFiscalYear
Field names: debit_amount / credit_amount (integer cents), quantity (Numeric)
"""
from __future__ import annotations

import json
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB as _JSONB

from pgappforge.plugins.erp.finance.gl.models import (
	GLAccount,
	GLAccountBalance,
	GLDimensionDefinition,
	GLJournalLine,
)

log = logging.getLogger(__name__)


class DimensionServiceError(Exception):
	pass


class DimensionService:
	"""Dimensional GL analysis service.

	All methods accept a SQLAlchemy Session and are synchronous (framework
	compatible).  Callers are responsible for commit/rollback.
	"""

	# ------------------------------------------------------------------
	# Catalogue management
	# ------------------------------------------------------------------

	def define_dimension(
		self,
		dimension_code: str,
		name: str,
		tenant_id: str,
		session: Any,
		*,
		is_required: bool = False,
		allowed_values: list[str] | None = None,
		description: str | None = None,
	) -> GLDimensionDefinition:
		"""Upsert a dimension definition for the tenant.

		Returns the existing row (updated in-place) or a newly flushed row.
		"""
		existing = session.execute(
			sa.select(GLDimensionDefinition).where(
				GLDimensionDefinition.tenant_id == tenant_id,
				GLDimensionDefinition.dimension_code == dimension_code,
			)
		).scalar_one_or_none()

		if existing:
			existing.name = name
			existing.is_required = is_required
			existing.allowed_values = allowed_values
			if description is not None:
				existing.description = description
			session.flush()
			return existing

		dim = GLDimensionDefinition(
			tenant_id=tenant_id,
			dimension_code=dimension_code,
			name=name,
			is_required=is_required,
			allowed_values=allowed_values,
			description=description,
		)
		session.add(dim)
		session.flush()
		return dim

	# ------------------------------------------------------------------
	# Validation
	# ------------------------------------------------------------------

	def validate_dimensions(
		self,
		dimensions: dict[str, str] | None,
		tenant_id: str,
		session: Any,
	) -> list[str]:
		"""Validate a dimension dict against the tenant's GLDimensionDefinition catalogue.

		Returns a list of human-readable error messages (empty = valid).
		"""
		if not dimensions:
			# Still need to check required dimensions even when dict is empty/None
			dimensions = {}

		defs: dict[str, GLDimensionDefinition] = {
			d.dimension_code: d
			for d in session.execute(
				sa.select(GLDimensionDefinition).where(
					GLDimensionDefinition.tenant_id == tenant_id,
					GLDimensionDefinition.is_active == True,  # noqa: E712
				)
			)
			.scalars()
			.all()
		}

		errors: list[str] = []

		for code, value in dimensions.items():
			if code not in defs:
				errors.append(f"Unknown dimension {code!r}")
			elif defs[code].allowed_values and value not in defs[code].allowed_values:
				errors.append(f"Value {value!r} not allowed for dimension {code!r}")

		for code, d in defs.items():
			if d.is_required and code not in dimensions:
				errors.append(f"Required dimension {code!r} missing")

		return errors

	# ------------------------------------------------------------------
	# Dimensional P&L
	# ------------------------------------------------------------------

	def get_dimensional_pnl(
		self,
		tenant_id: str,
		period: str,
		session: Any,
		*,
		dimension_filters: dict[str, str] | None = None,
		account_type_filter: list[str] | None = None,
	) -> list[dict[str, Any]]:
		"""P&L sliced by any combination of dimensions.

		Queries GLJournalLine using PostgreSQL JSONB containment (@>) so any
		number of dimension filters can be applied efficiently (requires a GIN
		index on gl_journal_line.dimensions for production scale).

		Parameters
		----------
		tenant_id:
			Multi-tenant isolation key.
		period:
			GLPeriod.period_name e.g. "January 2025".
		dimension_filters:
			JSONB containment filter e.g. {"project": "PRJ001", "grant": "GRT001"}.
			None = all dimensions.
		account_type_filter:
			Restrict to these account_type values e.g. ["REVENUE", "EXPENSE"].
			None = all types.

		Returns
		-------
		list of dicts with keys:
		  account_code, account_type, dimensions, period_debit, period_credit, net
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLFiscalYear,
			GLJournalBatch,
			GLJournalEntry,
			GLPeriod,
		)

		stmt = (
			sa.select(
				GLJournalLine.account_code,
				GLAccount.account_type,
				GLJournalLine.dimensions,
				sa.func.sum(GLJournalLine.debit_amount).label("debit"),
				sa.func.sum(GLJournalLine.credit_amount).label("credit"),
			)
			.join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
			.join(GLJournalBatch, GLJournalEntry.batch_id == GLJournalBatch.id)
			.join(GLPeriod, GLJournalBatch.period_id == GLPeriod.id)
			.join(GLFiscalYear, GLPeriod.fiscal_year_id == GLFiscalYear.id)
			.join(GLAccount, GLJournalLine.account_code == GLAccount.account_code)
			.where(
				GLJournalLine.tenant_id == tenant_id,
				GLPeriod.period_name == period,
			)
		)

		if dimension_filters:
			stmt = stmt.where(
				GLJournalLine.dimensions.op("@>")(
					sa.cast(json.dumps(dimension_filters), _JSONB)
				)
			)

		if account_type_filter:
			stmt = stmt.where(GLAccount.account_type.in_(account_type_filter))

		stmt = stmt.group_by(
			GLJournalLine.account_code,
			GLAccount.account_type,
			GLJournalLine.dimensions,
		)

		rows = session.execute(stmt).all()

		return [
			{
				"account_code": r.account_code,
				"account_type": r.account_type,
				"dimensions": r.dimensions or {},
				"period_debit": r.debit or 0,
				"period_credit": r.credit or 0,
				"net": (r.debit or 0) - (r.credit or 0),
			}
			for r in rows
		]

	# ------------------------------------------------------------------
	# Statistical KPI report
	# ------------------------------------------------------------------

	def get_kpi_report(
		self,
		stat_account_codes: list[str],
		period: str,
		tenant_id: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Return summed statistical quantities for non-monetary accounts.

		Statistical accounts carry GLJournalLine.quantity (Numeric) instead of
		monetary debit/credit amounts.

		Returns
		-------
		list of dicts with keys: account_code, total_quantity
		"""
		from pgappforge.plugins.erp.finance.gl.models import (
			GLJournalBatch,
			GLJournalEntry,
			GLPeriod,
		)

		stmt = (
			sa.select(
				GLJournalLine.account_code,
				sa.func.sum(GLJournalLine.quantity).label("total_qty"),
			)
			.join(GLJournalEntry, GLJournalLine.entry_id == GLJournalEntry.id)
			.join(GLJournalBatch, GLJournalEntry.batch_id == GLJournalBatch.id)
			.join(GLPeriod, GLJournalBatch.period_id == GLPeriod.id)
			.where(
				GLJournalLine.tenant_id == tenant_id,
				GLPeriod.period_name == period,
				GLJournalLine.account_code.in_(stat_account_codes),
				GLJournalLine.quantity.is_not(None),
			)
			.group_by(GLJournalLine.account_code)
		)

		rows = session.execute(stmt).all()

		return [
			{
				"account_code": r.account_code,
				"total_quantity": str(r.total_qty or 0),
			}
			for r in rows
		]


__all__ = ["DimensionServiceError", "DimensionService"]
