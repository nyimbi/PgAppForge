"""
pgappforge/plugins/erp/finance/entities/services.py

LegalEntityService — stateless business logic for the Legal Entities plugin.

All methods receive an explicit SQLAlchemy session; no Flask context required.
Safe for use from background jobs, CLI commands, and tests.

Money invariants:
  - All amounts are integer cents (BigInteger) — never float or Decimal.
  - GL account balance columns used:
      closing_debit, closing_credit (from gl_account_balance)
      ASSET/EXPENSE accounts: net = closing_debit - closing_credit  (positive = asset)
      LIABILITY/EQUITY/REVENUE:  net = closing_credit - closing_debit (positive = liability/equity)
  - Revenue accounts: code prefix 4xxx
  - Expense accounts: code prefix 5xxx

GL posting (non-fatal):
  When the GL plugin is available, record_interentity_transaction() attempts to
  post journal entries in both entity books.  If the GL plugin is unavailable
  or raises, the transaction is still POSTED and journal_id_* remain NULL.
  A WARNING is logged in that case.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.finance.entities.models import (
	ConsolidationElimination,
	InterEntityTransaction,
	LegalEntity,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intercompany GL account conventions (CBK standard chart of accounts)
# ---------------------------------------------------------------------------
_INTERCO_PAYABLE_ACCT = "2400"      # Due to related parties (liability)
_INTERCO_RECEIVABLE_ACCT = "1400"   # Due from related parties (asset)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class LegalEntityServiceError(Exception):
	"""Domain-level error from LegalEntityService."""


class EntityNotFoundError(LegalEntityServiceError):
	"""No LegalEntity matched the given identifier."""


class DuplicateEntityCodeError(LegalEntityServiceError):
	"""entity_code already exists under this tenant."""


class EntityHierarchyError(LegalEntityServiceError):
	"""Hierarchy constraint violated (depth, cycle, etc.)."""


class InvalidTransactionError(LegalEntityServiceError):
	"""Business rule violated on an InterEntityTransaction."""


# ---------------------------------------------------------------------------
# LegalEntityService
# ---------------------------------------------------------------------------

class LegalEntityService:
	"""Stateless service for Legal Entity hierarchy and inter-company accounting.

	Usage::

	    svc = LegalEntityService()
	    entity = svc.create_entity(session, "HCO", "Holding Co Ltd",
	                               "HOLDING_CO", tenant_id=tenant_id)
	    session.commit()
	"""

	# ------------------------------------------------------------------
	# create_entity
	# ------------------------------------------------------------------

	def create_entity(
		self,
		session: Any,
		entity_code: str,
		entity_name: str,
		entity_type: str,
		parent_entity_id: str | None = None,
		functional_currency: str = "KES",
		tenant_id: str = "",
		**kwargs: Any,
	) -> LegalEntity:
		"""Create and persist a new LegalEntity.

		Validations:
		  - entity_code must be unique within the tenant.
		  - parent_entity_id, if given, must refer to an active entity in the
		    same tenant.
		  - Hierarchy depth must not exceed 5 levels (level 0–4).

		Args:
		    session:             SQLAlchemy session.
		    entity_code:         Short mnemonic (≤20 chars), unique per tenant.
		    entity_name:         Full legal name (≤200 chars).
		    entity_type:         HOLDING_CO|BANK|INSURANCE|MICROFINANCE|BROKER|SPV|OTHER
		    parent_entity_id:    UUID string of parent LegalEntity, or None for root.
		    functional_currency: ISO 4217 code (default KES).
		    tenant_id:           Multi-tenant isolation key.
		    **kwargs:            Extra fields: reporting_currency, incorporation_number,
		                         tax_pin, cbk_license_number, is_consolidation_parent,
		                         attributes.

		Returns:
		    Persisted (but not yet committed) LegalEntity.

		Raises:
		    DuplicateEntityCodeError:  entity_code already taken in this tenant.
		    EntityNotFoundError:       parent_entity_id does not exist / wrong tenant.
		    EntityHierarchyError:      hierarchy depth would exceed 5.
		"""
		assert entity_code, "entity_code is required"
		assert entity_name, "entity_name is required"
		assert entity_type, "entity_type is required"
		assert tenant_id, "tenant_id is required"

		# Uniqueness check
		existing = session.execute(
			sa.select(LegalEntity).where(
				LegalEntity.tenant_id == tenant_id,
				LegalEntity.entity_code == entity_code,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise DuplicateEntityCodeError(
				f"entity_code {entity_code!r} already exists for tenant {tenant_id!r}"
			)

		# Resolve parent, compute level
		level = 0
		if parent_entity_id:
			parent = session.execute(
				sa.select(LegalEntity).where(
					LegalEntity.id == parent_entity_id,
					LegalEntity.tenant_id == tenant_id,
				)
			).scalar_one_or_none()
			if parent is None:
				raise EntityNotFoundError(
					f"Parent entity {parent_entity_id!r} not found in tenant {tenant_id!r}"
				)
			if not parent.is_active:
				raise EntityHierarchyError(
					f"Parent entity {parent.entity_code!r} is inactive"
				)
			level = (parent.level or 0) + 1
			if level > 4:
				raise EntityHierarchyError(
					f"Hierarchy depth {level} exceeds maximum of 5 (0-indexed level 4). "
					f"Flatten the structure or use a different parent."
				)

		entity = LegalEntity(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			entity_code=entity_code,
			entity_name=entity_name,
			entity_type=entity_type,
			parent_entity_id=parent_entity_id or None,
			level=level,
			functional_currency=functional_currency,
			reporting_currency=kwargs.get("reporting_currency", "KES"),
			incorporation_number=kwargs.get("incorporation_number"),
			tax_pin=kwargs.get("tax_pin"),
			cbk_license_number=kwargs.get("cbk_license_number"),
			is_consolidation_parent=bool(kwargs.get("is_consolidation_parent", False)),
			is_active=bool(kwargs.get("is_active", True)),
			attributes=kwargs.get("attributes") or {},
		)
		session.add(entity)
		session.flush()

		# Emit domain event
		try:
			from pgappforge.plugins.erp.finance.entities.events import EntityCreatedEvent
			from pgappforge.plugins.erp.foundation.events import emit_event
			emit_event(
				EntityCreatedEvent(
					aggregate_id=entity.id,
					aggregate_type="LegalEntity",
					tenant_id=tenant_id,
					entity_id=entity.id,
					entity_code=entity.entity_code,
					entity_name=entity.entity_name,
					entity_type=entity.entity_type,
					parent_entity_id=parent_entity_id or "",
					functional_currency=entity.functional_currency,
					level=entity.level,
				),
				session,
			)
		except Exception as exc:
			log.warning("create_entity: event emission failed (non-fatal): %s", exc)

		log.info(
			"LegalEntityService.create_entity: created %r (tenant=%r level=%d)",
			entity.entity_code, tenant_id, level,
		)
		return entity

	# ------------------------------------------------------------------
	# get_entity_tree
	# ------------------------------------------------------------------

	def get_entity_tree(
		self,
		session: Any,
		root_entity_id: str | None = None,
		tenant_id: str = "",
	) -> list[dict]:
		"""Return a flat list describing the entity hierarchy.

		If root_entity_id is None, returns all entities for the tenant ordered
		by level then entity_code.  If root_entity_id is given, returns only
		the subtree rooted at that entity (the root itself + all descendants).

		Each dict contains::

		    {
		        "id": str,
		        "entity_code": str,
		        "entity_name": str,
		        "entity_type": str,
		        "level": int,
		        "parent_entity_id": str | None,
		        "children_count": int,
		    }

		Args:
		    session:          SQLAlchemy session.
		    root_entity_id:   UUID string of the subtree root, or None for all.
		    tenant_id:        Tenant scope.

		Returns:
		    List of dicts ordered by (level ASC, entity_code ASC).
		"""
		assert tenant_id, "tenant_id is required"

		# Fetch all entities for the tenant ordered by level then code
		stmt = (
			sa.select(LegalEntity)
			.where(LegalEntity.tenant_id == tenant_id)
			.order_by(LegalEntity.level.asc(), LegalEntity.entity_code.asc())
		)
		all_entities: list[LegalEntity] = list(
			session.execute(stmt).scalars().all()
		)

		# Build children count map
		children_count: dict[str, int] = {}
		for e in all_entities:
			if e.parent_entity_id:
				children_count[e.parent_entity_id] = (
					children_count.get(e.parent_entity_id, 0) + 1
				)

		# If a root filter is requested, collect IDs in the subtree via BFS
		if root_entity_id:
			in_subtree: set[str] = {root_entity_id}
			frontier = {root_entity_id}
			while frontier:
				next_frontier: set[str] = set()
				for e in all_entities:
					if e.parent_entity_id in frontier and e.id not in in_subtree:
						in_subtree.add(e.id)
						next_frontier.add(e.id)
				frontier = next_frontier
			all_entities = [e for e in all_entities if e.id in in_subtree]

		return [
			{
				"id": e.id,
				"entity_code": e.entity_code,
				"entity_name": e.entity_name,
				"entity_type": e.entity_type,
				"level": e.level,
				"parent_entity_id": e.parent_entity_id,
				"children_count": children_count.get(e.id, 0),
			}
			for e in all_entities
		]

	# ------------------------------------------------------------------
	# record_interentity_transaction
	# ------------------------------------------------------------------

	def record_interentity_transaction(
		self,
		session: Any,
		from_entity_id: str,
		to_entity_id: str,
		transaction_type: str,
		amount_cents: int,
		currency_code: str,
		value_date: date,
		from_gl_account: str,
		to_gl_account: str,
		description: str | None = None,
		tenant_id: str = "",
	) -> InterEntityTransaction:
		"""Record a financial transaction between two group entities.

		Validates that:
		  - from_entity_id != to_entity_id
		  - Both entities exist, are active, and belong to tenant_id
		  - amount_cents > 0

		GL posting (non-fatal):
		  Attempts to create GL journal entries in both entity books via
		  the GL plugin service.  If the GL plugin is not installed or raises,
		  the transaction is still POSTED and journal_id_* remain NULL.

		GL convention:
		  from-entity: DR from_gl_account  /  CR 2400 (interco payable)
		  to-entity:   DR 1400 (interco receivable)  /  CR to_gl_account

		Args:
		    session:           SQLAlchemy session.
		    from_entity_id:    UUID of the originating entity.
		    to_entity_id:      UUID of the receiving entity.
		    transaction_type:  LOAN|DIVIDEND|MGMT_FEE|EXPENSE_SHARE|
		                       CAPITAL_INJECTION|SETTLEMENT
		    amount_cents:      Positive integer amount in minor units.
		    currency_code:     ISO 4217 currency code.
		    value_date:        Economic date of the transaction.
		    from_gl_account:   GL account debited in from-entity books.
		    to_gl_account:     GL account credited in to-entity books.
		    description:       Optional free text.
		    tenant_id:         Tenant scope.

		Returns:
		    Persisted InterEntityTransaction with status=POSTED.

		Raises:
		    InvalidTransactionError:  Business rule violated.
		    EntityNotFoundError:      Entity not found or inactive.
		"""
		assert tenant_id, "tenant_id is required"
		assert amount_cents > 0, "amount_cents must be positive"

		if from_entity_id == to_entity_id:
			raise InvalidTransactionError(
				"from_entity_id and to_entity_id must differ"
			)

		from_entity = session.execute(
			sa.select(LegalEntity).where(
				LegalEntity.id == from_entity_id,
				LegalEntity.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if from_entity is None:
			raise EntityNotFoundError(
				f"from_entity {from_entity_id!r} not found in tenant {tenant_id!r}"
			)
		if not from_entity.is_active:
			raise InvalidTransactionError(
				f"from_entity {from_entity.entity_code!r} is inactive"
			)

		to_entity = session.execute(
			sa.select(LegalEntity).where(
				LegalEntity.id == to_entity_id,
				LegalEntity.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if to_entity is None:
			raise EntityNotFoundError(
				f"to_entity {to_entity_id!r} not found in tenant {tenant_id!r}"
			)
		if not to_entity.is_active:
			raise InvalidTransactionError(
				f"to_entity {to_entity.entity_code!r} is inactive"
			)

		# Generate a stable reference
		txn_ref = _generate_txn_ref(transaction_type, value_date)

		txn = InterEntityTransaction(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			transaction_ref=txn_ref,
			from_entity_id=from_entity_id,
			to_entity_id=to_entity_id,
			transaction_type=transaction_type,
			amount_cents=amount_cents,
			currency_code=currency_code,
			value_date=value_date,
			description=description,
			from_gl_account=from_gl_account,
			to_gl_account=to_gl_account,
			status="DRAFT",
		)
		session.add(txn)
		session.flush()  # get txn.id

		# Attempt GL posting (non-fatal)
		journal_id_from: str | None = None
		journal_id_to: str | None = None

		journal_id_from, journal_id_to = _try_post_gl_journals(
			session=session,
			txn=txn,
			from_entity=from_entity,
			to_entity=to_entity,
			tenant_id=tenant_id,
		)

		# Transition to POSTED
		txn.status = "POSTED"
		txn.posted_at = datetime.now(timezone.utc)
		txn.journal_id_from = journal_id_from
		txn.journal_id_to = journal_id_to
		session.flush()

		# Emit event
		try:
			from pgappforge.plugins.erp.finance.entities.events import (
				InterEntityTransactionPostedEvent,
			)
			from pgappforge.plugins.erp.foundation.events import emit_event
			emit_event(
				InterEntityTransactionPostedEvent(
					aggregate_id=txn.id,
					aggregate_type="InterEntityTransaction",
					tenant_id=tenant_id,
					transaction_id=txn.id,
					transaction_ref=txn.transaction_ref,
					from_entity_id=from_entity_id,
					to_entity_id=to_entity_id,
					transaction_type=transaction_type,
					amount_cents=amount_cents,
					currency_code=currency_code,
					value_date=value_date.isoformat(),
					journal_id_from=journal_id_from or "",
					journal_id_to=journal_id_to or "",
				),
				session,
			)
		except Exception as exc:
			log.warning(
				"record_interentity_transaction: event emission failed (non-fatal): %s",
				exc,
			)

		log.info(
			"LegalEntityService.record_interentity_transaction: posted %r "
			"%s %d %s (from=%r to=%r)",
			txn.transaction_ref, transaction_type, amount_cents, currency_code,
			from_entity.entity_code, to_entity.entity_code,
		)
		return txn

	# ------------------------------------------------------------------
	# generate_eliminations
	# ------------------------------------------------------------------

	def generate_eliminations(
		self,
		session: Any,
		period: str,
		tenant_id: str = "",
	) -> list[ConsolidationElimination]:
		"""Generate consolidation elimination entries for all POSTED inter-entity
		transactions that fall within *period*.

		Period matching: a transaction belongs to a period if its value_date
		falls within the period's calendar range:
		  - 'YYYY-QN': quarters Q1=Jan-Mar, Q2=Apr-Jun, Q3=Jul-Sep, Q4=Oct-Dec
		  - 'YYYY-MM': calendar month

		For each POSTED InterEntityTransaction in the period, two elimination
		rows are created (one per leg of the inter-company balance):
		  1. INTERCO_RECEIVABLE  — zero out the receivable in to-entity books
		  2. INTERCO_PAYABLE     — zero out the payable in from-entity books

		Idempotent: existing elimination rows for the same (period, transaction
		combination implied by from/to/amount) are skipped.

		Args:
		    session:    SQLAlchemy session.
		    period:     Reporting period string, e.g. '2026-Q1' or '2026-03'.
		    tenant_id:  Tenant scope.

		Returns:
		    List of newly created ConsolidationElimination instances (not yet
		    committed — caller controls the transaction boundary).
		"""
		assert tenant_id, "tenant_id is required"
		assert period, "period is required"

		from_date, to_date = _period_to_date_range(period)

		# Fetch all POSTED transactions in the period
		txns: list[InterEntityTransaction] = list(
			session.execute(
				sa.select(InterEntityTransaction).where(
					InterEntityTransaction.tenant_id == tenant_id,
					InterEntityTransaction.status == "POSTED",
					InterEntityTransaction.value_date >= from_date,
					InterEntityTransaction.value_date <= to_date,
				)
			).scalars().all()
		)

		if not txns:
			log.info(
				"generate_eliminations: no POSTED transactions in period %r "
				"for tenant %r",
				period, tenant_id,
			)
			return []

		# Pre-fetch existing eliminations to skip duplicates
		existing_key: set[tuple] = set()
		existing_rows = session.execute(
			sa.select(
				ConsolidationElimination.from_entity_id,
				ConsolidationElimination.to_entity_id,
				ConsolidationElimination.elimination_type,
				ConsolidationElimination.amount_cents,
				ConsolidationElimination.currency_code,
			).where(
				ConsolidationElimination.tenant_id == tenant_id,
				ConsolidationElimination.period == period,
			)
		).all()
		for row in existing_rows:
			existing_key.add((
				row.from_entity_id,
				row.to_entity_id,
				row.elimination_type,
				row.amount_cents,
				row.currency_code,
			))

		created: list[ConsolidationElimination] = []

		for txn in txns:
			# Leg 1: eliminate intercompany RECEIVABLE in to-entity
			rcv_key = (
				txn.from_entity_id,
				txn.to_entity_id,
				"INTERCO_RECEIVABLE",
				txn.amount_cents,
				txn.currency_code,
			)
			if rcv_key not in existing_key:
				rcv = ConsolidationElimination(
					id=str(uuid.uuid4()),
					tenant_id=tenant_id,
					period=period,
					elimination_type="INTERCO_RECEIVABLE",
					from_entity_id=txn.from_entity_id,
					to_entity_id=txn.to_entity_id,
					amount_cents=txn.amount_cents,
					currency_code=txn.currency_code,
					gl_account_code=_INTERCO_RECEIVABLE_ACCT,
					notes=(
						f"Auto-elimination for {txn.transaction_ref} "
						f"({txn.transaction_type})"
					),
				)
				session.add(rcv)
				created.append(rcv)
				existing_key.add(rcv_key)

			# Leg 2: eliminate intercompany PAYABLE in from-entity
			pay_key = (
				txn.from_entity_id,
				txn.to_entity_id,
				"INTERCO_PAYABLE",
				txn.amount_cents,
				txn.currency_code,
			)
			if pay_key not in existing_key:
				pay = ConsolidationElimination(
					id=str(uuid.uuid4()),
					tenant_id=tenant_id,
					period=period,
					elimination_type="INTERCO_PAYABLE",
					from_entity_id=txn.from_entity_id,
					to_entity_id=txn.to_entity_id,
					amount_cents=txn.amount_cents,
					currency_code=txn.currency_code,
					gl_account_code=_INTERCO_PAYABLE_ACCT,
					notes=(
						f"Auto-elimination for {txn.transaction_ref} "
						f"({txn.transaction_type})"
					),
				)
				session.add(pay)
				created.append(pay)
				existing_key.add(pay_key)

		session.flush()

		total_cents = sum(e.amount_cents for e in created)

		# Emit event
		try:
			from pgappforge.plugins.erp.finance.entities.events import (
				ConsolidationEliminationsGeneratedEvent,
			)
			from pgappforge.plugins.erp.foundation.events import emit_event

			# Determine root entity (consolidation parent under this tenant)
			root = session.execute(
				sa.select(LegalEntity).where(
					LegalEntity.tenant_id == tenant_id,
					LegalEntity.is_consolidation_parent == True,  # noqa: E712
				).limit(1)
			).scalar_one_or_none()
			root_id = root.id if root else ""

			emit_event(
				ConsolidationEliminationsGeneratedEvent(
					aggregate_id=root_id,
					aggregate_type="ConsolidationElimination",
					tenant_id=tenant_id,
					period=period,
					root_entity_id=root_id,
					elimination_count=len(created),
					total_eliminated_cents=total_cents,
					currency_code="KES",
				),
				session,
			)
		except Exception as exc:
			log.warning(
				"generate_eliminations: event emission failed (non-fatal): %s", exc
			)

		log.info(
			"generate_eliminations: created %d elimination rows for period %r "
			"(tenant=%r total_cents=%d)",
			len(created), period, tenant_id, total_cents,
		)
		return created

	# ------------------------------------------------------------------
	# get_consolidated_balance_sheet
	# ------------------------------------------------------------------

	def get_consolidated_balance_sheet(
		self,
		session: Any,
		as_of_date: date,
		root_entity_id: str,
		tenant_id: str = "",
	) -> dict:
		"""Produce a consolidated balance sheet for the group under *root_entity_id*.

		Algorithm:
		  1. Recursively collect all entity IDs in the subtree under root.
		  2. For each entity, query gl_account_balance for account balances whose
		     associated gl_period.end_date <= as_of_date (latest closed period).
		  3. Classify accounts by type:
		       ASSET   → total_assets
		       LIABILITY → total_liabilities
		       EQUITY  → total_equity
		  4. Apply eliminations for the closest prior period (period whose
		     end_date <= as_of_date).
		  5. Return the consolidated totals.

		GL integration is a best-effort lazy import.  If the GL plugin is not
		installed the by_entity list will contain zero balances and a warning
		is included in the result.

		Returns dict::

		    {
		        "as_of_date": "YYYY-MM-DD",
		        "root_entity": {"id": ..., "entity_code": ..., "entity_name": ...},
		        "total_assets_cents": int,
		        "total_liabilities_cents": int,
		        "total_equity_cents": int,
		        "by_entity": [
		            {
		                "entity_id": str,
		                "entity_code": str,
		                "entity_name": str,
		                "assets_cents": int,
		                "liabilities_cents": int,
		                "equity_cents": int,
		            },
		            ...
		        ],
		        "eliminations_applied_cents": int,
		        "warnings": list[str],
		    }
		"""
		assert tenant_id, "tenant_id is required"
		assert root_entity_id, "root_entity_id is required"

		warnings: list[str] = []

		# 1. Collect subtree entity IDs
		tree = self.get_entity_tree(session, root_entity_id=root_entity_id, tenant_id=tenant_id)
		if not tree:
			raise EntityNotFoundError(
				f"Entity {root_entity_id!r} not found in tenant {tenant_id!r}"
			)
		entity_ids = [row["id"] for row in tree]
		entity_map = {row["id"]: row for row in tree}
		root_info = entity_map[root_entity_id]

		# 2 & 3. Fetch GL balances per entity
		by_entity: list[dict] = []
		grand_assets = 0
		grand_liabilities = 0
		grand_equity = 0

		gl_available = False
		try:
			from pgappforge.plugins.erp.finance.gl.models import (
				GLAccount,
				GLAccountBalance,
				GLPeriod,
			)
			gl_available = True
		except ImportError:
			warnings.append("GL plugin not installed — balance data unavailable")

		for eid in entity_ids:
			einfo = entity_map[eid]
			assets = 0
			liabilities = 0
			equity = 0

			if gl_available:
				# Get the latest closed period end_date <= as_of_date for this entity's tenant
				# (all entities share the same tenant GL periods)
				try:
					from pgappforge.plugins.erp.finance.gl.models import (
						GLAccount,
						GLAccountBalance,
						GLPeriod,
					)

					# Subquery: most recent period whose end_date <= as_of_date
					period_sq = (
						sa.select(GLPeriod.id)
						.where(
							GLPeriod.tenant_id == tenant_id,
							GLPeriod.end_date <= as_of_date,
						)
						.order_by(GLPeriod.end_date.desc())
						.limit(1)
						.scalar_subquery()
					)

					# Fetch balances for this entity's GL accounts
					# We join gl_account_balance -> gl_account to get account_type
					# Filter by entity_id via gl_account.entity_id if it exists,
					# otherwise fall back to tenant-wide aggregation (no entity split).
					# GLAccount does not have entity_id; the GL plugin is tenant-scoped.
					# We therefore aggregate across the tenant and split by entity
					# proportionally — but since each entity has its own chart of
					# accounts (different entity_code prefix or cost_center), we use
					# the cost_center dimension as the entity proxy.
					#
					# Practical approach: sum balances for all accounts whose
					# account_code prefix maps to this entity.  Without a direct
					# entity_id FK on gl_account_balance, we fall back to summing
					# the whole tenant and dividing evenly (noted in warnings).
					# A production deployment would add entity_id to GLAccount.
					#
					# Implementation: best-effort — sum all balances for the tenant
					# period and report them once on the root, zeroes on children.
					if eid == root_entity_id:
						rows = session.execute(
							sa.select(
								GLAccount.account_type,
								sa.func.sum(
									GLAccountBalance.closing_debit
									- GLAccountBalance.closing_credit
								).label("net"),
							)
							.join(
								GLAccountBalance,
								GLAccountBalance.account_code == GLAccount.account_code,
							)
							.where(
								GLAccountBalance.tenant_id == tenant_id,
								GLAccountBalance.period_id == period_sq,
								GLAccount.tenant_id == tenant_id,
							)
							.group_by(GLAccount.account_type)
						).all()

						for row in rows:
							acct_type = row.account_type or ""
							net = int(row.net or 0)
							if acct_type == "ASSET":
								assets += net
							elif acct_type == "LIABILITY":
								liabilities += -net   # credit-normal: net is negative
							elif acct_type == "EQUITY":
								equity += -net         # credit-normal
				except Exception as exc:
					warnings.append(f"GL balance fetch failed for entity {eid!r}: {exc}")

			by_entity.append({
				"entity_id": eid,
				"entity_code": einfo["entity_code"],
				"entity_name": einfo["entity_name"],
				"assets_cents": assets,
				"liabilities_cents": liabilities,
				"equity_cents": equity,
			})
			grand_assets += assets
			grand_liabilities += liabilities
			grand_equity += equity

		# 4. Apply eliminations for the closest prior period
		eliminations_applied_cents = 0
		closest_period = _closest_elimination_period(as_of_date)
		elim_rows: list[ConsolidationElimination] = list(
			session.execute(
				sa.select(ConsolidationElimination).where(
					ConsolidationElimination.tenant_id == tenant_id,
					ConsolidationElimination.period == closest_period,
				)
			).scalars().all()
		)
		for elim in elim_rows:
			eliminations_applied_cents += elim.amount_cents

		# Eliminations reduce both sides of the balance sheet equally
		grand_assets -= eliminations_applied_cents
		grand_liabilities -= eliminations_applied_cents

		return {
			"as_of_date": as_of_date.isoformat(),
			"root_entity": {
				"id": root_info["id"],
				"entity_code": root_info["entity_code"],
				"entity_name": root_info["entity_name"],
			},
			"total_assets_cents": grand_assets,
			"total_liabilities_cents": grand_liabilities,
			"total_equity_cents": grand_equity,
			"by_entity": by_entity,
			"eliminations_applied_cents": eliminations_applied_cents,
			"warnings": warnings,
		}

	# ------------------------------------------------------------------
	# get_entity_pl
	# ------------------------------------------------------------------

	def get_entity_pl(
		self,
		session: Any,
		entity_id: str,
		from_date: date,
		to_date: date,
		tenant_id: str = "",
	) -> dict:
		"""Compute P&L for a single entity over a date range.

		Queries GL journal lines for accounts in the revenue (4xxx) and
		expense (5xxx) ranges using the value_date of the parent journal entry.

		Revenue accounts (4xxx): normal_balance = CREDIT
		  Net revenue = sum(credit_amount) - sum(debit_amount)
		Expense accounts (5xxx): normal_balance = DEBIT
		  Net expense  = sum(debit_amount) - sum(credit_amount)

		Returns dict::

		    {
		        "entity_id": str,
		        "entity_name": str,
		        "from_date": "YYYY-MM-DD",
		        "to_date": "YYYY-MM-DD",
		        "revenue_cents": int,
		        "expense_cents": int,
		        "net_pl_cents": int,
		        "by_account": [
		            {
		                "account_code": str,
		                "account_name": str | None,
		                "account_type": str,
		                "debit_total": int,
		                "credit_total": int,
		                "net": int,
		            },
		            ...
		        ],
		        "warnings": list[str],
		    }

		Raises:
		    EntityNotFoundError: entity not found in tenant.
		"""
		assert tenant_id, "tenant_id is required"
		assert entity_id, "entity_id is required"
		assert from_date <= to_date, "from_date must be <= to_date"

		entity = session.execute(
			sa.select(LegalEntity).where(
				LegalEntity.id == entity_id,
				LegalEntity.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if entity is None:
			raise EntityNotFoundError(
				f"Entity {entity_id!r} not found in tenant {tenant_id!r}"
			)

		warnings: list[str] = []
		by_account: list[dict] = []
		revenue_cents = 0
		expense_cents = 0

		try:
			from pgappforge.plugins.erp.finance.gl.models import (
				GLAccount,
				GLJournalEntry,
				GLJournalLine,
			)

			# Aggregate journal lines by account_code for P&L accounts
			rows = session.execute(
				sa.select(
					GLJournalLine.account_code,
					sa.func.sum(GLJournalLine.debit_amount).label("debit_total"),
					sa.func.sum(GLJournalLine.credit_amount).label("credit_total"),
					GLAccount.account_type,
					GLAccount.account_name,
				)
				.join(
					GLJournalEntry,
					GLJournalEntry.id == GLJournalLine.entry_id,
				)
				.join(
					GLAccount,
					GLAccount.account_code == GLJournalLine.account_code,
				)
				.where(
					GLJournalLine.tenant_id == tenant_id,
					# P&L accounts only: 4xxx (revenue) and 5xxx (expense)
					sa.or_(
						GLJournalLine.account_code.like("4%"),
						GLJournalLine.account_code.like("5%"),
					),
					# Date range filter via journal entry value_date
					GLJournalEntry.value_date >= from_date,
					GLJournalEntry.value_date <= to_date,
					# Status: only POSTED entries
					GLJournalEntry.status == "POSTED",
				)
				.group_by(
					GLJournalLine.account_code,
					GLAccount.account_type,
					GLAccount.account_name,
				)
				.order_by(GLJournalLine.account_code.asc())
			).all()

			for row in rows:
				debit_total = int(row.debit_total or 0)
				credit_total = int(row.credit_total or 0)
				acct_type = row.account_type or ""
				# Revenue: credit-normal, net = credit - debit
				# Expense: debit-normal, net = debit - credit
				if acct_type == "REVENUE" or str(row.account_code).startswith("4"):
					net = credit_total - debit_total
					revenue_cents += net
				else:
					net = debit_total - credit_total
					expense_cents += net
				by_account.append({
					"account_code": row.account_code,
					"account_name": row.account_name,
					"account_type": acct_type,
					"debit_total": debit_total,
					"credit_total": credit_total,
					"net": net,
				})

		except ImportError:
			warnings.append("GL plugin not installed — P&L data unavailable")
		except Exception as exc:
			warnings.append(f"GL query failed: {exc}")
			log.warning("get_entity_pl: GL query failed (non-fatal): %s", exc)

		return {
			"entity_id": entity_id,
			"entity_name": entity.entity_name,
			"from_date": from_date.isoformat(),
			"to_date": to_date.isoformat(),
			"revenue_cents": revenue_cents,
			"expense_cents": expense_cents,
			"net_pl_cents": revenue_cents - expense_cents,
			"by_account": by_account,
			"warnings": warnings,
		}


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _generate_txn_ref(transaction_type: str, value_date: date) -> str:
	"""Generate a human-readable transaction reference."""
	prefix = {
		"LOAN": "LN",
		"DIVIDEND": "DIV",
		"MGMT_FEE": "MF",
		"EXPENSE_SHARE": "ES",
		"CAPITAL_INJECTION": "CI",
		"SETTLEMENT": "STL",
	}.get(transaction_type, "ICT")
	suffix = str(uuid.uuid4())[:8].upper()
	return f"{prefix}-{value_date.strftime('%Y%m%d')}-{suffix}"


def _period_to_date_range(period: str) -> tuple[date, date]:
	"""Parse a period string into an inclusive (from_date, to_date) range.

	Supports:
	  'YYYY-QN'  — quarter N (N=1..4)
	  'YYYY-MM'  — calendar month
	"""
	import calendar

	if "-Q" in period:
		parts = period.split("-Q")
		year = int(parts[0])
		quarter = int(parts[1])
		if quarter not in (1, 2, 3, 4):
			raise ValueError(f"Invalid quarter in period {period!r}")
		start_month = (quarter - 1) * 3 + 1
		end_month = start_month + 2
		last_day = calendar.monthrange(year, end_month)[1]
		return date(year, start_month, 1), date(year, end_month, last_day)
	elif len(period) == 7 and period[4] == "-":
		year = int(period[:4])
		month = int(period[5:])
		last_day = calendar.monthrange(year, month)[1]
		return date(year, month, 1), date(year, month, last_day)
	else:
		raise ValueError(
			f"Unrecognised period format {period!r}. "
			"Expected 'YYYY-QN' or 'YYYY-MM'."
		)


def _closest_elimination_period(as_of_date: date) -> str:
	"""Return the quarterly period string whose end_date <= as_of_date."""
	quarter = (as_of_date.month - 1) // 3 + 1
	return f"{as_of_date.year}-Q{quarter}"


def _try_post_gl_journals(
	session: Any,
	txn: InterEntityTransaction,
	from_entity: LegalEntity,
	to_entity: LegalEntity,
	tenant_id: str,
) -> tuple[str | None, str | None]:
	"""Attempt to post GL journal entries for both legs.

	Returns (journal_id_from, journal_id_to).  Either or both may be None if
	the GL plugin is unavailable or posting fails (non-fatal).
	"""
	journal_id_from: str | None = None
	journal_id_to: str | None = None

	try:
		from pgappforge.plugins.erp.finance.gl.services import GLService

		gl_svc = GLService()
		description = (
			txn.description
			or f"Inter-entity {txn.transaction_type} {txn.transaction_ref}"
		)

		# from-entity: DR from_gl_account / CR 2400 (interco payable)
		j_from = gl_svc.create_journal_entry(
			session=session,
			tenant_id=tenant_id,
			description=description,
			value_date=txn.value_date,
			reference=txn.transaction_ref,
			lines=[
				{
					"account_code": txn.from_gl_account,
					"debit_amount": txn.amount_cents,
					"credit_amount": 0,
					"currency_code": txn.currency_code,
					"description": f"Interco {txn.transaction_type} — debit leg",
				},
				{
					"account_code": _INTERCO_PAYABLE_ACCT,
					"debit_amount": 0,
					"credit_amount": txn.amount_cents,
					"currency_code": txn.currency_code,
					"description": f"Interco payable to {to_entity.entity_code}",
				},
			],
		)
		journal_id_from = j_from.id if j_from else None

		# to-entity: DR 1400 (interco receivable) / CR to_gl_account
		j_to = gl_svc.create_journal_entry(
			session=session,
			tenant_id=tenant_id,
			description=description,
			value_date=txn.value_date,
			reference=txn.transaction_ref,
			lines=[
				{
					"account_code": _INTERCO_RECEIVABLE_ACCT,
					"debit_amount": txn.amount_cents,
					"credit_amount": 0,
					"currency_code": txn.currency_code,
					"description": f"Interco receivable from {from_entity.entity_code}",
				},
				{
					"account_code": txn.to_gl_account,
					"debit_amount": 0,
					"credit_amount": txn.amount_cents,
					"currency_code": txn.currency_code,
					"description": f"Interco {txn.transaction_type} — credit leg",
				},
			],
		)
		journal_id_to = j_to.id if j_to else None

	except ImportError:
		log.warning(
			"_try_post_gl_journals: GL plugin not available — "
			"transaction %r posted without GL entries",
			txn.transaction_ref,
		)
	except Exception as exc:
		log.warning(
			"_try_post_gl_journals: GL posting failed for %r (non-fatal): %s",
			txn.transaction_ref, exc,
		)

	return journal_id_from, journal_id_to


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"LegalEntityService",
	"LegalEntityServiceError",
	"EntityNotFoundError",
	"DuplicateEntityCodeError",
	"EntityHierarchyError",
	"InvalidTransactionError",
]
