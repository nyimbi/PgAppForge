"""
pgappforge/plugins/erp/finance/joint_venture/services.py

JointVentureService — JV accounting business logic (COPAS/JOA-aligned).

All amounts in integer cents. Decimal arithmetic for WI percentages. No float.

Public API
----------
  create_venture(details, session)                   -> JointVenture
  add_partner(venture_id, details, session)           -> JvPartner
  allocate_costs(venture_id, period_date, costs, session) -> list[JvBillingStatement]
  issue_cash_call(venture_id, details, session)       -> JvCashCall
  record_payment_received(cash_call_line_id, amount_cents, session) -> JvCashCallLine
  raise_audit_query(venture_id, details, session)     -> JvAuditQuery
  resolve_audit_query(query_id, resolution, session)  -> JvAuditQuery
  get_partner_balance(venture_id, partner_id, session) -> dict
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class JvServiceError(Exception):
	"""Base JV service error."""


class VentureNotFoundError(JvServiceError):
	pass


class PartnerNotFoundError(JvServiceError):
	pass


class WorkingInterestError(JvServiceError):
	"""Raised when WI percentages do not sum to 100%."""


class CashCallError(JvServiceError):
	pass


# ---------------------------------------------------------------------------
# Input DTOs
# ---------------------------------------------------------------------------

@dataclass
class VentureDetails:
	tenant_id: str
	venture_code: str
	venture_name: str
	operator_party_id: str
	operator_wi_pct: Decimal          # e.g. Decimal("0.40") = 40%
	effective_date: date
	currency_code: str
	venture_type: str = "GENERAL"    # OIL_GAS | MINING | REAL_ESTATE | GENERAL
	accounting_method: str = "PROPORTIONATE_CONSOLIDATION"
	cost_centre: str | None = None
	gl_jv_control_account: str | None = None
	description: str | None = None
	expiry_date: date | None = None
	metadata: dict[str, Any] | None = None


@dataclass
class PartnerDetails:
	party_id: str
	partner_name: str
	working_interest_pct: Decimal    # e.g. Decimal("0.30") = 30%
	effective_date: date
	is_operator: bool = False
	net_profit_interest_pct: Decimal | None = None
	payment_terms_days: int = 30
	billing_address: str | None = None
	expiry_date: date | None = None
	metadata: dict[str, Any] | None = None


@dataclass
class CashCallDetails:
	call_date: date
	due_date: date
	total_amount_cents: int
	period_covered: str | None = None    # YYYY-MM
	narration: str | None = None
	call_reference: str | None = None


@dataclass
class AuditQueryDetails:
	partner_id: str
	raised_date: date
	description: str
	amount_disputed_cents: int = 0
	period_under_audit: str | None = None   # YYYY-MM
	query_reference: str | None = None
	metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# JointVentureService
# ---------------------------------------------------------------------------

class JointVentureService:
	"""Stateless JV accounting service. Caller owns session transactions."""

	# ------------------------------------------------------------------ #
	# Venture creation
	# ------------------------------------------------------------------ #

	def create_venture(self, details: VentureDetails, session: Any) -> Any:
		"""Register a new joint venture. Emits VentureCreatedEvent."""
		from pgappforge.plugins.erp.finance.joint_venture.models import JointVenture
		from pgappforge.plugins.erp.finance.joint_venture.events import (
			VentureCreatedEvent, emit_event,
		)

		assert details.venture_type in ("OIL_GAS", "MINING", "REAL_ESTATE", "GENERAL"), \
			f"invalid venture_type: {details.venture_type!r}"
		assert Decimal("0") < details.operator_wi_pct <= Decimal("1"), \
			"operator_wi_pct must be 0 < x ≤ 1"

		venture = JointVenture(
			tenant_id=details.tenant_id,
			venture_code=details.venture_code,
			venture_name=details.venture_name,
			venture_type=details.venture_type,
			accounting_method=details.accounting_method,
			operator_party_id=details.operator_party_id,
			operator_wi_pct=details.operator_wi_pct,
			effective_date=details.effective_date,
			expiry_date=details.expiry_date,
			currency_code=details.currency_code.upper(),
			cost_centre=details.cost_centre,
			gl_jv_control_account=details.gl_jv_control_account,
			description=details.description,
			status="ACTIVE",
			metadata_=details.metadata or {},
		)
		session.add(venture)
		session.flush()

		emit_event(
			VentureCreatedEvent(
				aggregate_id=venture.id,
				aggregate_type="JointVenture",
				tenant_id=details.tenant_id,
				venture_id=venture.id,
				venture_code=details.venture_code,
				venture_name=details.venture_name,
				operator_party_id=details.operator_party_id,
				effective_date=str(details.effective_date),
			),
			session,
		)
		log.info("JV created: %r %r", details.venture_code, details.venture_name)
		return venture

	# ------------------------------------------------------------------ #
	# Partner management
	# ------------------------------------------------------------------ #

	def add_partner(
		self, venture_id: str, details: PartnerDetails, session: Any
	) -> Any:
		"""Add a working interest partner to a venture.

		Validates total WI does not exceed 100%. Emits PartnerAddedEvent.
		"""
		from pgappforge.plugins.erp.finance.joint_venture.models import (
			JointVenture, JvPartner,
		)
		from pgappforge.plugins.erp.finance.joint_venture.events import (
			PartnerAddedEvent, emit_event,
		)

		venture = session.get(JointVenture, venture_id)
		if venture is None:
			raise VentureNotFoundError(f"JointVenture {venture_id!r} not found")

		# Check existing total WI
		existing_wi = session.execute(
			sa.select(sa.func.sum(JvPartner.working_interest_pct))
			.where(JvPartner.venture_id == venture_id)
			.where(JvPartner.is_active == True)
		).scalar_one_or_none() or Decimal("0")

		# Add operator WI
		total_after = Decimal(str(existing_wi)) + details.working_interest_pct

		# Allow up to operator_wi_pct + partners
		if total_after > Decimal("1.000001"):  # small float tolerance
			raise WorkingInterestError(
				f"Adding WI {details.working_interest_pct} would push total to "
				f"{total_after:.6f} (>100%)"
			)

		partner = JvPartner(
			tenant_id=venture.tenant_id,
			venture_id=venture_id,
			party_id=details.party_id,
			partner_name=details.partner_name,
			working_interest_pct=details.working_interest_pct,
			net_profit_interest_pct=details.net_profit_interest_pct,
			is_operator=details.is_operator,
			effective_date=details.effective_date,
			expiry_date=details.expiry_date,
			payment_terms_days=details.payment_terms_days,
			billing_address=details.billing_address,
			is_active=True,
			metadata_=details.metadata or {},
		)
		session.add(partner)
		session.flush()

		emit_event(
			PartnerAddedEvent(
				aggregate_id=venture_id,
				aggregate_type="JointVenture",
				tenant_id=venture.tenant_id,
				venture_id=venture_id,
				partner_id=partner.id,
				party_id=details.party_id,
				working_interest_pct=str(details.working_interest_pct),
				effective_date=str(details.effective_date),
			),
			session,
		)
		log.info(
			"Partner added to JV %r: party=%r WI=%s",
			venture_id, details.party_id, details.working_interest_pct,
		)
		return partner

	# ------------------------------------------------------------------ #
	# Cost allocation
	# ------------------------------------------------------------------ #

	def allocate_costs(
		self,
		venture_id: str,
		period_date: date,
		gross_costs_cents: int,
		session: Any,
		*,
		cost_breakdown: list[dict] | None = None,
		operator_overhead_pct: Decimal = Decimal("0"),
	) -> list[Any]:
		"""Allocate JV costs to all active partners for a period.

		Creates one JvBillingStatement per partner.
		Emits JvCostsAllocatedEvent.

		cost_breakdown: [{cost_category, description, amount_cents}]
		operator_overhead_pct: COPAS overhead applied on top of WI share.
		"""
		from pgappforge.plugins.erp.finance.joint_venture.models import (
			JointVenture, JvPartner, JvBillingStatement,
		)
		from pgappforge.plugins.erp.finance.joint_venture.events import (
			JvCostsAllocatedEvent, BillingStatementCutEvent, emit_event,
		)

		venture = session.get(JointVenture, venture_id)
		if venture is None:
			raise VentureNotFoundError(f"JointVenture {venture_id!r} not found")

		billing_period = period_date.strftime("%Y-%m")

		partners = session.execute(
			sa.select(JvPartner)
			.where(JvPartner.venture_id == venture_id)
			.where(JvPartner.is_active == True)
		).scalars().all()

		if not partners:
			raise JvServiceError(f"No active partners for venture {venture_id!r}")

		statements = []
		for partner in partners:
			wi = Decimal(str(partner.working_interest_pct))
			partner_share = int(
				(Decimal(str(gross_costs_cents)) * wi)
				.to_integral_value(ROUND_HALF_UP)
			)
			overhead = int(
				(Decimal(str(partner_share)) * operator_overhead_pct)
				.to_integral_value(ROUND_HALF_UP)
			)
			total_billed = partner_share + overhead

			stmt = JvBillingStatement(
				tenant_id=venture.tenant_id,
				venture_id=venture_id,
				partner_id=partner.id,
				billing_period=billing_period,
				working_interest_pct=wi,
				gross_costs_cents=gross_costs_cents,
				partner_share_cents=partner_share,
				operator_overhead_cents=overhead,
				total_billed_cents=total_billed,
				due_date=period_date,
				status="DRAFT",
				cost_breakdown=cost_breakdown or [],
			)
			session.add(stmt)
			statements.append(stmt)

		session.flush()

		emit_event(
			JvCostsAllocatedEvent(
				aggregate_id=venture_id,
				aggregate_type="JointVenture",
				tenant_id=venture.tenant_id,
				allocation_id="",  # no separate model; venture_id + period is key
				venture_id=venture_id,
				period_date=str(period_date),
				total_costs_cents=gross_costs_cents,
				partners_allocated=len(statements),
			),
			session,
		)
		log.info(
			"Costs allocated for JV %r period=%s partners=%d total=%d",
			venture_id, billing_period, len(statements), gross_costs_cents,
		)
		return statements

	# ------------------------------------------------------------------ #
	# Cash call
	# ------------------------------------------------------------------ #

	def issue_cash_call(
		self, venture_id: str, details: CashCallDetails, session: Any
	) -> Any:
		"""Issue a cash call to all non-operator partners.

		Creates JvCashCall + per-partner JvCashCallLine rows.
		Emits CashCallIssuedEvent.
		"""
		from pgappforge.plugins.erp.finance.joint_venture.models import (
			JointVenture, JvPartner, JvCashCall, JvCashCallLine,
		)
		from pgappforge.plugins.erp.finance.joint_venture.events import (
			CashCallIssuedEvent, emit_event,
		)

		venture = session.get(JointVenture, venture_id)
		if venture is None:
			raise VentureNotFoundError(f"JointVenture {venture_id!r} not found")

		ref = details.call_reference or self._generate_call_reference(venture_id, session)

		call = JvCashCall(
			tenant_id=venture.tenant_id,
			venture_id=venture_id,
			call_reference=ref,
			call_date=details.call_date,
			due_date=details.due_date,
			period_covered=details.period_covered,
			total_amount_cents=details.total_amount_cents,
			narration=details.narration,
			status="ISSUED",
			metadata_={},
		)
		session.add(call)
		session.flush()

		# Create per-partner lines for non-operator partners
		partners = session.execute(
			sa.select(JvPartner)
			.where(JvPartner.venture_id == venture_id)
			.where(JvPartner.is_active == True)
			.where(JvPartner.is_operator == False)
		).scalars().all()

		total_non_op_wi = sum(
			Decimal(str(p.working_interest_pct)) for p in partners
		)
		if total_non_op_wi == 0:
			total_non_op_wi = Decimal("1")

		for partner in partners:
			wi = Decimal(str(partner.working_interest_pct))
			# Allocate proportionally to non-operator WI
			partner_amount = int(
				(Decimal(str(details.total_amount_cents)) * wi / total_non_op_wi)
				.to_integral_value(ROUND_HALF_UP)
			)
			session.add(JvCashCallLine(
				cash_call_id=call.id,
				partner_id=partner.id,
				working_interest_pct=wi,
				amount_cents=partner_amount,
				amount_received_cents=0,
				is_fully_paid=False,
			))

		session.flush()

		emit_event(
			CashCallIssuedEvent(
				aggregate_id=call.id,
				aggregate_type="JvCashCall",
				tenant_id=venture.tenant_id,
				cash_call_id=call.id,
				venture_id=venture_id,
				due_date=str(details.due_date),
				total_amount_cents=details.total_amount_cents,
				partners_notified=len(partners),
			),
			session,
		)
		log.info(
			"Cash call issued %r venture=%r total=%d partners=%d",
			ref, venture_id, details.total_amount_cents, len(partners),
		)
		return call

	def record_payment_received(
		self,
		cash_call_line_id: str,
		amount_cents: int,
		session: Any,
		*,
		payment_reference: str | None = None,
	) -> Any:
		"""Record a partner payment against a cash call line."""
		from pgappforge.plugins.erp.finance.joint_venture.models import JvCashCallLine

		line = session.get(JvCashCallLine, cash_call_line_id)
		if line is None:
			raise CashCallError(f"JvCashCallLine {cash_call_line_id!r} not found")

		line.amount_received_cents += amount_cents
		if payment_reference:
			line.payment_reference = payment_reference
		if line.amount_received_cents >= line.amount_cents:
			line.is_fully_paid = True
		session.flush()

		log.info(
			"Payment received on cash call line %r: amount=%d received_total=%d",
			cash_call_line_id, amount_cents, line.amount_received_cents,
		)
		return line

	# ------------------------------------------------------------------ #
	# Audit query
	# ------------------------------------------------------------------ #

	def raise_audit_query(
		self, venture_id: str, details: AuditQueryDetails, session: Any
	) -> Any:
		"""Raise a partner audit query. Emits AuditQueryRaisedEvent."""
		from pgappforge.plugins.erp.finance.joint_venture.models import (
			JointVenture, JvAuditQuery,
		)
		from pgappforge.plugins.erp.finance.joint_venture.events import (
			AuditQueryRaisedEvent, emit_event,
		)

		venture = session.get(JointVenture, venture_id)
		if venture is None:
			raise VentureNotFoundError(f"JointVenture {venture_id!r} not found")

		ref = details.query_reference or self._generate_query_reference(venture_id, session)

		query = JvAuditQuery(
			tenant_id=venture.tenant_id,
			venture_id=venture_id,
			partner_id=details.partner_id,
			query_reference=ref,
			raised_date=details.raised_date,
			period_under_audit=details.period_under_audit,
			description=details.description,
			amount_disputed_cents=details.amount_disputed_cents,
			status="OPEN",
			metadata_=details.metadata or {},
		)
		session.add(query)
		session.flush()

		emit_event(
			AuditQueryRaisedEvent(
				aggregate_id=query.id,
				aggregate_type="JvAuditQuery",
				tenant_id=venture.tenant_id,
				query_id=query.id,
				venture_id=venture_id,
				partner_id=details.partner_id,
				query_reference=ref,
				amount_disputed_cents=details.amount_disputed_cents,
			),
			session,
		)
		log.info(
			"Audit query raised %r venture=%r disputed=%d",
			ref, venture_id, details.amount_disputed_cents,
		)
		return query

	def resolve_audit_query(
		self,
		query_id: str,
		resolution_notes: str,
		session: Any,
		*,
		resolution_amount_cents: int | None = None,
	) -> Any:
		"""Resolve an audit query."""
		from pgappforge.plugins.erp.finance.joint_venture.models import JvAuditQuery

		query = session.get(JvAuditQuery, query_id)
		if query is None:
			raise JvServiceError(f"JvAuditQuery {query_id!r} not found")
		if query.status not in ("OPEN", "UNDER_REVIEW"):
			raise JvServiceError(
				f"Query {query.query_reference!r} is {query.status!r}, cannot resolve"
			)

		query.status = "RESOLVED"
		query.resolution_notes = resolution_notes
		query.resolution_amount_cents = resolution_amount_cents
		query.resolved_at = datetime.now(timezone.utc)
		query.updated_at = datetime.now(timezone.utc)
		session.flush()

		log.info("Audit query resolved %r amount=%s", query.query_reference, resolution_amount_cents)
		return query

	# ------------------------------------------------------------------ #
	# Balance query
	# ------------------------------------------------------------------ #

	def get_partner_balance(
		self,
		venture_id: str,
		partner_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Summarise outstanding billings and cash call position for a partner."""
		from pgappforge.plugins.erp.finance.joint_venture.models import (
			JvBillingStatement, JvCashCallLine,
		)

		billed = session.execute(
			sa.select(sa.func.sum(JvBillingStatement.total_billed_cents))
			.where(JvBillingStatement.venture_id == venture_id)
			.where(JvBillingStatement.partner_id == partner_id)
			.where(JvBillingStatement.status.in_(["ISSUED", "DISPUTED"]))
		).scalar_one_or_none() or 0

		cash_call_outstanding = session.execute(
			sa.select(
				sa.func.sum(JvCashCallLine.amount_cents - JvCashCallLine.amount_received_cents)
			)
			.join(
				sa.alias(
					sa.select(
						sa.column("id").label("cc_id"),
						sa.column("venture_id").label("cc_venture_id"),
					).select_from(sa.text("erp_jv_cash_call")),
					name="cc",
				),
				JvCashCallLine.cash_call_id == sa.column("cc_id"),
			)
			.where(JvCashCallLine.partner_id == partner_id)
			.where(JvCashCallLine.is_fully_paid == False)
		).scalar_one_or_none() or 0

		return {
			"venture_id": venture_id,
			"partner_id": partner_id,
			"outstanding_billings_cents": billed,
			"outstanding_cash_calls_cents": cash_call_outstanding,
			"total_outstanding_cents": billed + cash_call_outstanding,
		}

	# ------------------------------------------------------------------ #
	# Internal helpers
	# ------------------------------------------------------------------ #

	def _generate_call_reference(self, venture_id: str, session: Any) -> str:
		from pgappforge.plugins.erp.finance.joint_venture.models import JvCashCall
		year = date.today().year
		count = session.execute(
			sa.select(sa.func.count(JvCashCall.id))
			.where(JvCashCall.venture_id == venture_id)
		).scalar_one()
		return f"CC-{year}-{count + 1:04d}"

	def _generate_query_reference(self, venture_id: str, session: Any) -> str:
		from pgappforge.plugins.erp.finance.joint_venture.models import JvAuditQuery
		year = date.today().year
		count = session.execute(
			sa.select(sa.func.count(JvAuditQuery.id))
			.where(JvAuditQuery.venture_id == venture_id)
		).scalar_one()
		return f"AQ-{year}-{count + 1:04d}"


__all__ = [
	"JointVentureService",
	"JvServiceError",
	"VentureNotFoundError",
	"PartnerNotFoundError",
	"WorkingInterestError",
	"CashCallError",
	"VentureDetails",
	"PartnerDetails",
	"CashCallDetails",
	"AuditQueryDetails",
]
