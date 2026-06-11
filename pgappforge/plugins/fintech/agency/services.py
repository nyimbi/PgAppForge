"""
pgappforge/plugins/fintech/agency/services.py

AgencyService — all agency banking operations flow through here.

Money arithmetic
----------------
All amounts are integer cents.  Intermediate commission calculations use
Decimal via money_multiply to avoid float rounding.

Event emission
--------------
All emit_event() calls are wrapped in try/except — a failure to publish an
event NEVER causes the business transaction to fail.

KYC stub
--------
_run_kyc_check() is a lightweight synchronous stub.  Replace with a real
KYC provider integration (e.g. IPRS gateway) in production.
"""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.commons import (
	emit_event,
	money_add,
	money_multiply,
	percent_of,
	format_currency,
)
from pgappforge.plugins.fintech.agency.models import (
	AgencyAgent,
	AgencyCommission,
	AgencyFloat,
	AgencyOutlet,
	AgencyTransaction,
)
from pgappforge.plugins.fintech.agency.events import (
	AgentAccreditedEvent,
	AgencyTransactionEvent,
	CommissionSettledEvent,
	FloatToppedUpEvent,
	OutletSuspendedEvent,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class AgencyError(Exception):
	"""Base agency banking error."""


class OutletNotFoundError(AgencyError):
	"""No outlet matching the given identifier."""


class AgentNotFoundError(AgencyError):
	"""No agent matching the given identifier."""


class AgentNotAccreditedError(AgencyError):
	"""Operation requires an ACCREDITED agent."""


class InsufficientFloatError(AgencyError):
	"""Outlet float balance is below the requested amount."""


class FloatNotFoundError(AgencyError):
	"""No float record for the given outlet."""


# ---------------------------------------------------------------------------
# Commission rate table
# ---------------------------------------------------------------------------

# Service-type → agent commission percentage (of transaction amount).
# Override via AGENCY_COMMISSION_RATES config in the plugin.
_DEFAULT_COMMISSION_RATES: dict[str, Decimal] = {
	"CASH_IN":           Decimal("0.20"),
	"CASH_OUT":          Decimal("0.50"),
	"ACCOUNT_OPENING":   Decimal("1.00"),
	"LOAN_DISBURSEMENT": Decimal("0.30"),
	"LOAN_REPAYMENT":    Decimal("0.25"),
	"BILL_PAYMENT":      Decimal("0.20"),
	"GOVT_PAYMENTS":     Decimal("0.15"),
	"REMITTANCE":        Decimal("0.40"),
	"AIRTIME":           Decimal("0.15"),
	"INSURANCE":         Decimal("0.50"),
}


class AgencyService:
	"""Agency banking service — outlets, agents, transactions, float, commissions.

	All methods accept an explicit SQLAlchemy session to support both Flask
	request-scoped sessions and background/batch job usage.
	"""

	def __init__(self, config: dict[str, Any] | None = None) -> None:
		self._config: dict[str, Any] = config or {}

	# -----------------------------------------------------------------------
	# Outlet management
	# -----------------------------------------------------------------------

	def onboard_outlet(
		self,
		name: str,
		outlet_type: str,
		services: list[str],
		location: dict,
		tenant_id: str,
		session: Session,
		**kwargs: Any,
	) -> AgencyOutlet:
		"""Create a new outlet and its corresponding float record.

		Args:
			name:        Human-readable outlet name.
			outlet_type: One of the OUTLET_TYPE constants.
			services:    List of service codes offered at this outlet.
			location:    Dict with keys region, lat, lng, address.
			tenant_id:   Tenant scope.
			session:     SQLAlchemy session (caller manages commit).
			**kwargs:    Optional overrides for float_minimum_cents, status, etc.

		Returns:
			AgencyOutlet (flushed but not committed).
		"""
		outlet = AgencyOutlet(
			tenant_id=tenant_id,
			name=name,
			outlet_type=outlet_type,
			services=services,
			location=location,
			float_balance_cents=kwargs.get("float_balance_cents", 0),
			float_minimum_cents=kwargs.get("float_minimum_cents", 500_000),
			status=kwargs.get("status", "ACTIVE"),
		)
		session.add(outlet)
		session.flush()

		# Create the companion float record
		agent_float = AgencyFloat(
			tenant_id=tenant_id,
			outlet_id=outlet.id,
			current_balance_cents=kwargs.get("float_balance_cents", 0),
		)
		session.add(agent_float)
		session.flush()

		log.info(
			"AgencyService.onboard_outlet: created outlet %s (id=%s, type=%s)",
			name,
			outlet.id,
			outlet_type,
		)
		return outlet

	def suspend_outlet(
		self,
		outlet_id: str,
		reason: str,
		tenant_id: str,
		session: Session,
	) -> AgencyOutlet:
		"""Suspend an outlet — sets status to SUSPENDED.

		Also suspends all ACCREDITED agents at this outlet.
		"""
		outlet = self._get_outlet(outlet_id, tenant_id, session)
		assert outlet.status == "ACTIVE", f"Outlet {outlet_id} is not ACTIVE (status={outlet.status})"

		outlet.status = "SUSPENDED"
		session.flush()

		# Cascade suspend to accredited agents
		accredited_agents = session.execute(
			select(AgencyAgent).where(
				AgencyAgent.outlet_id == outlet_id,
				AgencyAgent.tenant_id == tenant_id,
				AgencyAgent.accreditation_status == "ACCREDITED",
			)
		).scalars().all()
		for agent in accredited_agents:
			agent.accreditation_status = "SUSPENDED"
		if accredited_agents:
			session.flush()

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = OutletSuspendedEvent(
				aggregate_type="AgencyOutlet",
				aggregate_id=outlet_id,
				tenant_id=tenant_id,
				payload={"outlet_id": outlet_id, "reason": reason},
				outlet_id=outlet_id,
				outlet_name=outlet.name,
				reason=reason,
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning("AgencyService.suspend_outlet: event emit failed (non-fatal): %s", exc)

		log.info("AgencyService.suspend_outlet: outlet %s suspended. reason=%r", outlet_id, reason)
		return outlet

	# -----------------------------------------------------------------------
	# Agent management
	# -----------------------------------------------------------------------

	def accredit_agent(
		self,
		outlet_id: str,
		agent_name: str,
		msisdn: str,
		national_id: str,
		tenant_id: str,
		session: Session,
	) -> AgencyAgent:
		"""Create an agent record and run KYC; sets ACCREDITED on pass.

		A failed KYC leaves the agent in PENDING status (not an error) so that
		manual review workflows can pick up PENDING agents.

		Args:
			outlet_id:   Parent outlet ID.
			agent_name:  Full name of the individual.
			msisdn:      Mobile number (E.164 format recommended).
			national_id: Government-issued ID number.
			tenant_id:   Tenant scope.
			session:     SQLAlchemy session.

		Returns:
			AgencyAgent with accreditation_status set to ACCREDITED or PENDING.
		"""
		# Verify outlet exists and is active
		outlet = self._get_outlet(outlet_id, tenant_id, session)
		assert outlet.status == "ACTIVE", f"Outlet {outlet_id} is not ACTIVE"

		agent = AgencyAgent(
			tenant_id=tenant_id,
			outlet_id=outlet_id,
			agent_name=agent_name,
			msisdn=msisdn,
			national_id=national_id,
			accreditation_status="PENDING",
			kyc_tier=1,
		)
		session.add(agent)
		session.flush()

		# Run KYC check
		kyc_passed, kyc_tier = self._run_kyc_check(national_id, msisdn)
		if kyc_passed:
			agent.accreditation_status = "ACCREDITED"
			agent.accredited_at = datetime.now(timezone.utc)
			agent.kyc_tier = kyc_tier
			session.flush()

			try:
				from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
				ev = AgentAccreditedEvent(
					aggregate_type="AgencyAgent",
					aggregate_id=agent.id,
					tenant_id=tenant_id,
					payload={
						"agent_id": agent.id,
						"outlet_id": outlet_id,
						"msisdn": msisdn,
					},
					agent_id=agent.id,
					agent_name=agent_name,
					outlet_id=outlet_id,
					msisdn=msisdn,
					national_id=national_id,
					kyc_tier=kyc_tier,
				)
				_emit_typed(ev, session)
			except Exception as exc:
				log.warning("AgencyService.accredit_agent: event emit failed (non-fatal): %s", exc)

		log.info(
			"AgencyService.accredit_agent: agent %s (id=%s) status=%s",
			agent_name,
			agent.id,
			agent.accreditation_status,
		)
		return agent

	# -----------------------------------------------------------------------
	# Transaction processing
	# -----------------------------------------------------------------------

	def process_transaction(
		self,
		agent_id: str,
		service_type: str,
		customer_msisdn: str,
		amount_cents: int,
		tenant_id: str,
		session: Session,
		*,
		reference: str | None = None,
	) -> AgencyTransaction:
		"""Process an agency service transaction.

		Flow:
		  1. Validate agent is ACCREDITED.
		  2. For CASH_OUT: validate float >= amount_cents.
		  3. Insert AgencyTransaction (PENDING → COMPLETED on float update).
		  4. Update AgencyFloat.
		  5. Compute agent commission.
		  6. Emit AgencyTransactionEvent.

		Args:
			agent_id:        Accredited agent performing the transaction.
			service_type:    One of the SERVICES constants.
			customer_msisdn: Customer's mobile number.
			amount_cents:    Transaction principal in minor currency units.
			tenant_id:       Tenant scope.
			session:         SQLAlchemy session.
			reference:       Optional external reference; auto-generated if None.

		Returns:
			Committed AgencyTransaction with status COMPLETED.

		Raises:
			AgentNotAccreditedError: Agent is not ACCREDITED.
			InsufficientFloatError:  CASH_OUT requested but float < amount.
		"""
		assert amount_cents > 0, "amount_cents must be positive"
		agent = self._get_agent(agent_id, tenant_id, session)
		if agent.accreditation_status != "ACCREDITED":
			raise AgentNotAccreditedError(
				f"Agent {agent_id} is not ACCREDITED (status={agent.accreditation_status})"
			)

		# Float check for CASH_OUT
		agent_float = self._get_float(agent.outlet_id, tenant_id, session)
		if service_type == "CASH_OUT":
			if agent_float.current_balance_cents < amount_cents:
				raise InsufficientFloatError(
					f"Outlet float {format_currency(agent_float.current_balance_cents)} "
					f"< requested {format_currency(amount_cents)}"
				)

		if reference is None:
			reference = secrets.token_hex(12).upper()

		commission_cents = self._compute_commission(service_type, amount_cents)

		txn = AgencyTransaction(
			tenant_id=tenant_id,
			agent_id=agent_id,
			outlet_id=agent.outlet_id,
			service_type=service_type,
			customer_msisdn=customer_msisdn,
			amount_cents=amount_cents,
			fee_cents=0,
			agent_commission_cents=commission_cents,
			status="PENDING",
			reference=reference,
		)
		session.add(txn)
		session.flush()

		# Update float balance
		if service_type == "CASH_OUT":
			agent_float.current_balance_cents = agent_float.current_balance_cents - amount_cents
		elif service_type in ("CASH_IN", "LOAN_REPAYMENT"):
			agent_float.current_balance_cents = agent_float.current_balance_cents + amount_cents
		agent_float.updated_at = datetime.now(timezone.utc)

		# Mark completed
		txn.status = "COMPLETED"
		session.flush()

		# Also update outlet denormalized float balance
		outlet = self._get_outlet(agent.outlet_id, tenant_id, session)
		outlet.float_balance_cents = agent_float.current_balance_cents
		session.flush()

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = AgencyTransactionEvent(
				aggregate_type="AgencyTransaction",
				aggregate_id=txn.id,
				tenant_id=tenant_id,
				payload={"reference": reference, "service_type": service_type},
				transaction_id=txn.id,
				agent_id=agent_id,
				outlet_id=agent.outlet_id,
				service_type=service_type,
				customer_msisdn=customer_msisdn,
				amount_cents=amount_cents,
				fee_cents=txn.fee_cents,
				agent_commission_cents=commission_cents,
				status="COMPLETED",
				reference=reference,
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning("AgencyService.process_transaction: event emit failed (non-fatal): %s", exc)

		log.info(
			"AgencyService.process_transaction: ref=%s service=%s amount=%s status=COMPLETED",
			reference,
			service_type,
			amount_cents,
		)
		return txn

	# -----------------------------------------------------------------------
	# Float management
	# -----------------------------------------------------------------------

	def top_up_float(
		self,
		outlet_id: str,
		amount_cents: int,
		tenant_id: str,
		session: Session,
	) -> AgencyFloat:
		"""Add float to an outlet and post a GL credit entry.

		Args:
			outlet_id:    Target outlet.
			amount_cents: Amount to add (positive integer).
			tenant_id:    Tenant scope.
			session:      SQLAlchemy session.

		Returns:
			Updated AgencyFloat.
		"""
		assert amount_cents > 0, "amount_cents must be positive"
		outlet = self._get_outlet(outlet_id, tenant_id, session)
		agent_float = self._get_float(outlet_id, tenant_id, session)

		previous_balance = agent_float.current_balance_cents
		agent_float.current_balance_cents = money_add(agent_float.current_balance_cents, amount_cents)
		agent_float.last_topped_up_at = datetime.now(timezone.utc)
		agent_float.updated_at = datetime.now(timezone.utc)

		outlet.float_balance_cents = agent_float.current_balance_cents
		session.flush()

		# Post GL entry (non-fatal if GL module unavailable)
		try:
			emit_event(
				"agency.float.gl_credit",
				"AgencyFloat",
				agent_float.id,
				{
					"outlet_id": outlet_id,
					"amount_cents": amount_cents,
					"new_balance_cents": agent_float.current_balance_cents,
				},
				session,
				tenant_id=tenant_id,
			)
		except Exception as exc:
			log.debug("AgencyService.top_up_float: GL post non-fatal: %s", exc)

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = FloatToppedUpEvent(
				aggregate_type="AgencyFloat",
				aggregate_id=agent_float.id,
				tenant_id=tenant_id,
				payload={"outlet_id": outlet_id, "amount_cents": amount_cents},
				outlet_id=outlet_id,
				outlet_name=outlet.name,
				amount_cents=amount_cents,
				new_balance_cents=agent_float.current_balance_cents,
				previous_balance_cents=previous_balance,
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning("AgencyService.top_up_float: event emit failed (non-fatal): %s", exc)

		log.info(
			"AgencyService.top_up_float: outlet=%s +%d → balance=%d",
			outlet_id,
			amount_cents,
			agent_float.current_balance_cents,
		)
		return agent_float

	def check_float_level(
		self,
		outlet_id: str,
		tenant_id: str,
		session: Session,
	) -> dict:
		"""Return float status for an outlet.

		Returns:
			{
				"current_cents": int,
				"minimum_cents": int,
				"is_low": bool,
			}
		"""
		outlet = self._get_outlet(outlet_id, tenant_id, session)
		agent_float = self._get_float(outlet_id, tenant_id, session)
		return {
			"current_cents": agent_float.current_balance_cents,
			"minimum_cents": outlet.float_minimum_cents,
			"is_low": agent_float.current_balance_cents < outlet.float_minimum_cents,
		}

	# -----------------------------------------------------------------------
	# Commission settlement
	# -----------------------------------------------------------------------

	def settle_commissions(
		self,
		period: str,
		tenant_id: str,
		session: Session,
	) -> list[AgencyCommission]:
		"""Aggregate transactions for the period by agent and settle commissions.

		Args:
			period:    YYYY-MM string (e.g. "2025-01").
			tenant_id: Tenant scope.
			session:   SQLAlchemy session.

		Returns:
			List of AgencyCommission records created or updated (status=PAID).
		"""
		assert len(period) == 7 and period[4] == "-", f"period must be YYYY-MM, got {period!r}"

		# Aggregate completed transactions for the period
		period_start = f"{period}-01"
		year, month = period.split("-")
		# Build next month for upper bound
		next_month_year = int(year) + (1 if int(month) == 12 else 0)
		next_month_month = 1 if int(month) == 12 else int(month) + 1
		period_end = f"{next_month_year:04d}-{next_month_month:02d}-01"

		rows = session.execute(
			sa.text(
				"""
				SELECT agent_id,
				       COUNT(*)                          AS txn_count,
				       COALESCE(SUM(agent_commission_cents), 0) AS gross_cents
				FROM   ft_agency_transaction
				WHERE  tenant_id = :tenant_id
				  AND  status    = 'COMPLETED'
				  AND  created_at >= :period_start::date
				  AND  created_at <  :period_end::date
				GROUP BY agent_id
				"""
			),
			{
				"tenant_id": tenant_id,
				"period_start": period_start,
				"period_end": period_end,
			},
		).all()

		# WHT rate (15% stub — configure via AGENCY_WHT_RATE)
		wht_rate = Decimal(str(self._config.get("AGENCY_WHT_RATE", "15")))

		commissions: list[AgencyCommission] = []
		for row in rows:
			agent_id = str(row.agent_id)
			gross = int(row.gross_cents)
			tax = percent_of(gross, wht_rate)
			net = max(0, gross - tax)

			# Upsert: update existing PENDING record or create new one
			existing = session.execute(
				select(AgencyCommission).where(
					AgencyCommission.agent_id == agent_id,
					AgencyCommission.period == period,
					AgencyCommission.tenant_id == tenant_id,
				)
			).scalar_one_or_none()

			if existing is None:
				commission = AgencyCommission(
					tenant_id=tenant_id,
					agent_id=agent_id,
					period=period,
					transactions_count=int(row.txn_count),
					gross_commission_cents=gross,
					tax_cents=tax,
					net_commission_cents=net,
					status="PAID",
					paid_at=datetime.now(timezone.utc),
				)
				session.add(commission)
			else:
				existing.transactions_count = int(row.txn_count)
				existing.gross_commission_cents = gross
				existing.tax_cents = tax
				existing.net_commission_cents = net
				existing.status = "PAID"
				existing.paid_at = datetime.now(timezone.utc)
				commission = existing

			session.flush()
			commissions.append(commission)

		total_gross = sum(c.gross_commission_cents for c in commissions)
		total_net = sum(c.net_commission_cents for c in commissions)

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = CommissionSettledEvent(
				aggregate_type="AgencyCommission",
				aggregate_id=period,
				tenant_id=tenant_id,
				payload={"period": period, "records": len(commissions)},
				period=period,
				records_count=len(commissions),
				total_gross_cents=total_gross,
				total_net_cents=total_net,
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning("AgencyService.settle_commissions: event emit failed (non-fatal): %s", exc)

		log.info(
			"AgencyService.settle_commissions: period=%s records=%d gross=%d net=%d",
			period,
			len(commissions),
			total_gross,
			total_net,
		)
		return commissions

	# -----------------------------------------------------------------------
	# Internal helpers
	# -----------------------------------------------------------------------

	def _get_outlet(self, outlet_id: str, tenant_id: str, session: Session) -> AgencyOutlet:
		outlet = session.execute(
			select(AgencyOutlet).where(
				AgencyOutlet.id == outlet_id,
				AgencyOutlet.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if outlet is None:
			raise OutletNotFoundError(f"AgencyOutlet {outlet_id} not found for tenant {tenant_id}")
		return outlet

	def _get_agent(self, agent_id: str, tenant_id: str, session: Session) -> AgencyAgent:
		agent = session.execute(
			select(AgencyAgent).where(
				AgencyAgent.id == agent_id,
				AgencyAgent.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if agent is None:
			raise AgentNotFoundError(f"AgencyAgent {agent_id} not found for tenant {tenant_id}")
		return agent

	def _get_float(self, outlet_id: str, tenant_id: str, session: Session) -> AgencyFloat:
		agent_float = session.execute(
			select(AgencyFloat).where(
				AgencyFloat.outlet_id == outlet_id,
				AgencyFloat.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if agent_float is None:
			raise FloatNotFoundError(f"No float record for outlet {outlet_id}")
		return agent_float

	def _run_kyc_check(self, national_id: str, msisdn: str) -> tuple[bool, int]:
		"""Stub KYC check.  Replace with IPRS or equivalent gateway call.

		Returns (passed: bool, kyc_tier: int).
		Tier 1 = basic (name + ID), Tier 2 = enhanced (photo match), Tier 3 = full.
		"""
		# Production: call external KYC provider
		# Stub: pass if national_id length ≥ 7
		passed = len(national_id.strip()) >= 7
		tier = 2 if passed else 1
		return passed, tier

	def _compute_commission(self, service_type: str, amount_cents: int) -> int:
		"""Compute agent commission for a transaction.

		Uses AGENCY_COMMISSION_RATES from plugin config if available,
		otherwise falls back to the built-in default rate table.
		"""
		rates: dict[str, Decimal] = self._config.get(
			"AGENCY_COMMISSION_RATES", _DEFAULT_COMMISSION_RATES
		)
		rate = rates.get(service_type, Decimal("0.20"))
		return percent_of(amount_cents, rate)

	def _agent_commission_pct(self, service_type: str) -> Decimal:
		"""Return configured commission % for a service type."""
		rates: dict[str, Decimal] = self._config.get(
			"AGENCY_COMMISSION_RATES", _DEFAULT_COMMISSION_RATES
		)
		return rates.get(service_type, Decimal("0.20"))


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register(
		"agency.process_transaction",
		"Process an agency banking transaction (CASH_IN/CASH_OUT/etc.)",
	)
	def _bpm_process_transaction(record_ctx, session, **kw):
		svc = AgencyService(record_ctx.get("config"))
		return svc.process_transaction(
			agent_id=kw["agent_id"],
			service_type=kw["service_type"],
			customer_msisdn=kw["customer_msisdn"],
			amount_cents=int(kw["amount_cents"]),
			tenant_id=record_ctx.get("tenant_id", ""),
			session=session,
			reference=kw.get("reference"),
		)

	@_BPMReg.register(
		"agency.top_up_float",
		"Top up float for an agency outlet",
	)
	def _bpm_top_up_float(record_ctx, session, **kw):
		svc = AgencyService(record_ctx.get("config"))
		return svc.top_up_float(
			outlet_id=kw["outlet_id"],
			amount_cents=int(kw["amount_cents"]),
			tenant_id=record_ctx.get("tenant_id", ""),
			session=session,
		)

except (ImportError, Exception):
	pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"AgencyService",
	"AgencyError",
	"OutletNotFoundError",
	"AgentNotFoundError",
	"AgentNotAccreditedError",
	"InsufficientFloatError",
	"FloatNotFoundError",
]
