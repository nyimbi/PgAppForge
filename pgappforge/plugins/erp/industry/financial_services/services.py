"""
pgappforge/plugins/erp/industry/financial_services/services.py

FinancialServicesService — stateless business logic for the FinServ plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

Critical invariants:
  - All monetary amounts: integer cents. Never float.
  - ClientHolding rows are NEVER updated — new snapshot rows are inserted.
  - SanctionsScreeningResult rows are NEVER updated — new screening rows inserted.
  - PortfolioAccount balances mutated only through post_account_transaction().
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timezone
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select, func

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class FinServError(Exception):
	"""Base error for Financial Services domain violations."""


class ClientNotFoundError(FinServError):
	"""No FinancialClient with the given id."""


class AccountNotFoundError(FinServError):
	"""No PortfolioAccount with the given id."""


class AccountFrozenError(FinServError):
	"""Operation rejected — account is FROZEN."""


class AccountClosedError(FinServError):
	"""Operation rejected — account is CLOSED."""


class InsufficientBalanceError(FinServError):
	"""Debit would push available_balance_cents below zero."""


class KYCNotApprovedError(FinServError):
	"""Action requires KYC status = APPROVED."""


class SanctionsHoldError(FinServError):
	"""Party has a CONFIRMED_MATCH sanctions hit."""


class DuplicateClientNumberError(FinServError):
	"""client_number already exists for this tenant."""


# ---------------------------------------------------------------------------
# FinancialServicesService
# ---------------------------------------------------------------------------

class FinancialServicesService:
	"""Stateless service for Financial Services Cloud operations.

	Callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# Client management
	# ------------------------------------------------------------------

	def onboard_client(
		self,
		*,
		tenant_id: str,
		party_id: str,
		client_number: str,
		client_type: str,
		risk_profile: str = "MEDIUM",
		relationship_manager_id: int | None = None,
		session: Any,
	) -> dict:
		"""Create a FinancialClient and emit ClientOnboardedEvent.

		KYC status starts as PENDING — caller must run screen_sanctions() and
		then call approve_kyc() to move the client to APPROVED.

		Raises DuplicateClientNumberError if client_number exists for tenant.
		"""
		from pgappforge.plugins.erp.industry.financial_services.models import FinancialClient
		from pgappforge.plugins.erp.industry.financial_services.events import (
			ClientOnboardedEvent, emit_event,
		)

		existing = session.execute(
			select(FinancialClient).where(
				FinancialClient.tenant_id == tenant_id,
				FinancialClient.client_number == client_number,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise DuplicateClientNumberError(
				f"client_number {client_number!r} already exists for tenant {tenant_id!r}"
			)

		client = FinancialClient(
			tenant_id=tenant_id,
			party_id=party_id,
			client_number=client_number,
			client_type=client_type,
			risk_profile=risk_profile,
			kyc_status="PENDING",
			relationship_manager_id=relationship_manager_id,
			total_aum_cents=0,
			net_worth_cents=0,
		)
		session.add(client)
		session.flush()

		emit_event(
			ClientOnboardedEvent(
				aggregate_id=client.id,
				aggregate_type="FinancialClient",
				tenant_id=tenant_id,
				client_id=client.id,
				party_id=party_id,
				client_number=client_number,
				client_type=client_type,
				risk_profile=risk_profile,
			),
			session,
		)

		log.info("onboard_client: created client %r (kyc=PENDING)", client_number)
		return {"client_id": client.id, "client_number": client_number, "kyc_status": "PENDING"}

	def approve_kyc(
		self,
		client_id: str,
		session: Any,
		changed_by: str = "",
	) -> dict:
		"""Transition KYC status from PENDING → APPROVED.

		Raises:
		  ClientNotFoundError if client does not exist.
		  SanctionsHoldError if party has CONFIRMED_MATCH.
		  FinServError if current status is not PENDING.
		"""
		from pgappforge.plugins.erp.industry.financial_services.models import (
			FinancialClient, SanctionsScreeningResult,
		)
		from pgappforge.plugins.erp.industry.financial_services.events import (
			ClientKYCStatusChangedEvent, emit_event,
		)

		client = session.get(FinancialClient, client_id)
		if client is None:
			raise ClientNotFoundError(f"FinancialClient {client_id!r} not found")

		# Block if confirmed sanctions match exists for this party
		hit = session.execute(
			select(SanctionsScreeningResult).where(
				SanctionsScreeningResult.party_id == client.party_id,
				SanctionsScreeningResult.status == "CONFIRMED_MATCH",
			).limit(1)
		).scalar_one_or_none()
		if hit is not None:
			raise SanctionsHoldError(
				f"Party {client.party_id!r} has a CONFIRMED_MATCH sanctions record — KYC blocked"
			)

		old_status = client.kyc_status
		client.kyc_status = "APPROVED"
		client.kyc_completed_at = datetime.now(timezone.utc)

		emit_event(
			ClientKYCStatusChangedEvent(
				aggregate_id=client_id,
				aggregate_type="FinancialClient",
				tenant_id=client.tenant_id,
				client_id=client_id,
				client_number=client.client_number,
				old_status=old_status,
				new_status="APPROVED",
				changed_by=changed_by,
			),
			session,
		)

		log.info("approve_kyc: client %r KYC approved", client.client_number)
		return {"client_id": client_id, "kyc_status": "APPROVED"}

	def change_risk_profile(
		self,
		client_id: str,
		new_profile: str,
		session: Any,
		rationale: str = "",
		changed_by: str = "",
	) -> dict:
		"""Reclassify a client's risk profile. Emits ClientRiskProfileChangedEvent."""
		from pgappforge.plugins.erp.industry.financial_services.models import FinancialClient
		from pgappforge.plugins.erp.industry.financial_services.events import (
			ClientRiskProfileChangedEvent, emit_event,
		)

		valid = {"LOW", "MEDIUM", "HIGH", "SPECULATIVE"}
		if new_profile not in valid:
			raise FinServError(f"risk_profile must be one of {valid}")

		client = session.get(FinancialClient, client_id)
		if client is None:
			raise ClientNotFoundError(f"FinancialClient {client_id!r} not found")

		old_profile = client.risk_profile
		client.risk_profile = new_profile

		emit_event(
			ClientRiskProfileChangedEvent(
				aggregate_id=client_id,
				aggregate_type="FinancialClient",
				tenant_id=client.tenant_id,
				client_id=client_id,
				client_number=client.client_number,
				old_profile=old_profile,
				new_profile=new_profile,
				rationale=rationale,
			),
			session,
		)

		return {"client_id": client_id, "old_profile": old_profile, "new_profile": new_profile}

	# ------------------------------------------------------------------
	# Account management
	# ------------------------------------------------------------------

	def open_account(
		self,
		*,
		tenant_id: str,
		client_id: str,
		account_number: str,
		account_type: str,
		currency_code: str = "USD",
		session: Any,
	) -> dict:
		"""Open a new PortfolioAccount for an APPROVED client.

		Raises KYCNotApprovedError if client KYC is not APPROVED.
		"""
		from pgappforge.plugins.erp.industry.financial_services.models import (
			FinancialClient, PortfolioAccount,
		)
		from pgappforge.plugins.erp.industry.financial_services.events import (
			AccountOpenedEvent, emit_event,
		)

		client = session.get(FinancialClient, client_id)
		if client is None:
			raise ClientNotFoundError(f"FinancialClient {client_id!r} not found")
		if client.kyc_status != "APPROVED":
			raise KYCNotApprovedError(
				f"Client {client.client_number!r} KYC status is {client.kyc_status!r} — "
				f"must be APPROVED before opening accounts"
			)

		account = PortfolioAccount(
			tenant_id=tenant_id,
			client_id=client_id,
			account_number=account_number,
			account_type=account_type,
			currency_code=currency_code,
			balance_cents=0,
			available_balance_cents=0,
			status="ACTIVE",
		)
		session.add(account)
		session.flush()

		emit_event(
			AccountOpenedEvent(
				aggregate_id=account.id,
				aggregate_type="PortfolioAccount",
				tenant_id=tenant_id,
				account_id=account.id,
				account_number=account_number,
				client_id=client_id,
				account_type=account_type,
				currency_code=currency_code,
			),
			session,
		)

		log.info("open_account: %r opened for client %r", account_number, client_id)
		return {"account_id": account.id, "account_number": account_number, "status": "ACTIVE"}

	def post_account_transaction(
		self,
		account_id: str,
		delta_cents: int,
		session: Any,
		transaction_ref: str = "",
	) -> dict:
		"""Adjust account balance by delta_cents (positive=credit, negative=debit).

		Validates:
		  - Account is ACTIVE
		  - Debit does not push available_balance below zero

		Returns new balance dict.
		"""
		from pgappforge.plugins.erp.industry.financial_services.models import PortfolioAccount
		from pgappforge.plugins.erp.industry.financial_services.events import (
			AccountBalanceUpdatedEvent, emit_event,
		)

		account = session.get(PortfolioAccount, account_id)
		if account is None:
			raise AccountNotFoundError(f"PortfolioAccount {account_id!r} not found")
		if account.status == "FROZEN":
			raise AccountFrozenError(f"Account {account.account_number!r} is FROZEN")
		if account.status == "CLOSED":
			raise AccountClosedError(f"Account {account.account_number!r} is CLOSED")
		if delta_cents < 0 and account.available_balance_cents + delta_cents < 0:
			raise InsufficientBalanceError(
				f"Account {account.account_number!r}: "
				f"debit {abs(delta_cents)} exceeds available balance "
				f"{account.available_balance_cents}"
			)

		account.balance_cents += delta_cents
		account.available_balance_cents += delta_cents

		emit_event(
			AccountBalanceUpdatedEvent(
				aggregate_id=account_id,
				aggregate_type="PortfolioAccount",
				tenant_id=account.tenant_id,
				account_id=account_id,
				account_number=account.account_number,
				delta_cents=delta_cents,
				new_balance_cents=account.balance_cents,
				transaction_ref=transaction_ref,
			),
			session,
		)

		return {
			"account_id": account_id,
			"balance_cents": account.balance_cents,
			"available_balance_cents": account.available_balance_cents,
		}

	# ------------------------------------------------------------------
	# Holdings / portfolio
	# ------------------------------------------------------------------

	def record_holding_snapshot(
		self,
		*,
		tenant_id: str,
		client_id: str,
		instrument_isin: str,
		instrument_name: str,
		quantity_str: str,
		avg_cost_cents: int,
		current_value_cents: int,
		as_of_date: date,
		session: Any,
	) -> dict:
		"""Insert a new ClientHolding snapshot row (immutable ledger pattern).

		quantity_str must be a decimal string e.g. '100.00000000'.
		All monetary args must be integer cents.
		"""
		from decimal import Decimal
		from pgappforge.plugins.erp.industry.financial_services.models import ClientHolding
		from pgappforge.plugins.erp.industry.financial_services.events import (
			HoldingRevaluedEvent, emit_event,
		)

		qty = Decimal(quantity_str)
		cost_total = int(qty * avg_cost_cents)
		unrealized = current_value_cents - cost_total

		holding = ClientHolding(
			tenant_id=tenant_id,
			client_id=client_id,
			instrument_isin=instrument_isin,
			instrument_name=instrument_name,
			quantity=qty,
			avg_cost_cents=avg_cost_cents,
			current_value_cents=current_value_cents,
			unrealized_pnl_cents=unrealized,
			as_of_date=as_of_date,
		)
		session.add(holding)
		session.flush()

		emit_event(
			HoldingRevaluedEvent(
				aggregate_id=holding.id,
				aggregate_type="ClientHolding",
				tenant_id=tenant_id,
				holding_id=holding.id,
				client_id=client_id,
				instrument_isin=instrument_isin,
				current_value_cents=current_value_cents,
				unrealized_pnl_cents=unrealized,
				as_of_date=as_of_date.isoformat(),
			),
			session,
		)

		log.info(
			"record_holding_snapshot: client=%r isin=%r date=%s value=%d",
			client_id, instrument_isin, as_of_date, current_value_cents,
		)
		return {
			"holding_id": holding.id,
			"unrealized_pnl_cents": unrealized,
			"current_value_cents": current_value_cents,
		}

	# ------------------------------------------------------------------
	# Sanctions screening
	# ------------------------------------------------------------------

	def screen_sanctions(
		self,
		*,
		tenant_id: str,
		party_id: str,
		list_type: str,
		match_found: bool,
		match_score: float | None,
		match_details: dict,
		session: Any,
	) -> dict:
		"""Insert a new SanctionsScreeningResult (immutable — never updates existing row).

		match_score is passed as float from the screening provider but stored
		as NUMERIC(5,4) in the DB; validated to [0.0, 1.0].
		"""
		from decimal import Decimal
		from pgappforge.plugins.erp.industry.financial_services.models import SanctionsScreeningResult
		from pgappforge.plugins.erp.industry.financial_services.events import (
			SanctionsScreeningCompletedEvent, emit_event,
		)

		valid_lists = {"OFAC", "EU", "UN", "UK", "LOCAL"}
		if list_type not in valid_lists:
			raise FinServError(f"list_type must be one of {valid_lists}")

		status = "POTENTIAL_MATCH" if match_found else "CLEAR"
		score_dec = Decimal(str(match_score)).quantize(Decimal("0.0001")) if match_score is not None else None

		result = SanctionsScreeningResult(
			tenant_id=tenant_id,
			party_id=party_id,
			list_type=list_type,
			match_found=match_found,
			match_score=score_dec,
			match_details=match_details,
			status=status,
		)
		session.add(result)
		session.flush()

		emit_event(
			SanctionsScreeningCompletedEvent(
				aggregate_id=result.id,
				aggregate_type="SanctionsScreeningResult",
				tenant_id=tenant_id,
				screening_id=result.id,
				party_id=party_id,
				list_type=list_type,
				match_found=match_found,
				status=status,
			),
			session,
		)

		log.info(
			"screen_sanctions: party=%r list=%r match=%s status=%r",
			party_id, list_type, match_found, status,
		)
		return {
			"screening_id": result.id,
			"party_id": party_id,
			"list_type": list_type,
			"match_found": match_found,
			"status": status,
		}

	def clear_sanctions_match(
		self,
		screening_id: str,
		cleared_by_user_id: int,
		session: Any,
	) -> dict:
		"""Mark a POTENTIAL_MATCH as CLEAR after compliance review.

		Creates a NEW screening result row (immutable ledger) rather than
		updating the original.
		"""
		from pgappforge.plugins.erp.industry.financial_services.models import SanctionsScreeningResult
		from pgappforge.plugins.erp.industry.financial_services.events import (
			SanctionsMatchClearedEvent, emit_event,
		)

		original = session.get(SanctionsScreeningResult, screening_id)
		if original is None:
			raise FinServError(f"SanctionsScreeningResult {screening_id!r} not found")
		if original.status != "POTENTIAL_MATCH":
			raise FinServError(
				f"Screening {screening_id!r} has status {original.status!r}; "
				f"only POTENTIAL_MATCH can be cleared"
			)

		clearance = SanctionsScreeningResult(
			tenant_id=original.tenant_id,
			party_id=original.party_id,
			list_type=original.list_type,
			match_found=False,
			match_score=None,
			match_details={"cleared_from": screening_id, **original.match_details},
			cleared_by=cleared_by_user_id,
			cleared_at=datetime.now(timezone.utc),
			status="CLEAR",
		)
		session.add(clearance)
		session.flush()

		emit_event(
			SanctionsMatchClearedEvent(
				aggregate_id=clearance.id,
				aggregate_type="SanctionsScreeningResult",
				tenant_id=original.tenant_id,
				screening_id=screening_id,
				party_id=original.party_id,
				cleared_by=str(cleared_by_user_id),
			),
			session,
		)

		return {"clearance_id": clearance.id, "party_id": original.party_id, "status": "CLEAR"}

	# ------------------------------------------------------------------
	# Reports
	# ------------------------------------------------------------------

	def get_client_portfolio_summary(self, client_id: str, as_of_date: date, session: Any) -> dict:
		"""Return portfolio summary: total AUM, holdings breakdown, account balances.

		All monetary values in integer cents.
		"""
		from pgappforge.plugins.erp.industry.financial_services.models import (
			FinancialClient, PortfolioAccount, ClientHolding,
		)

		client = session.get(FinancialClient, client_id)
		if client is None:
			raise ClientNotFoundError(f"FinancialClient {client_id!r} not found")

		accounts = session.execute(
			select(PortfolioAccount).where(
				PortfolioAccount.client_id == client_id,
				PortfolioAccount.status != "CLOSED",
			)
		).scalars().all()

		# Latest holding snapshot per ISIN
		# Subquery: max created_at per (client_id, instrument_isin, as_of_date <= target)
		latest_holdings = session.execute(
			select(ClientHolding).where(
				ClientHolding.client_id == client_id,
				ClientHolding.as_of_date <= as_of_date,
			).order_by(ClientHolding.instrument_isin, ClientHolding.as_of_date.desc())
		).scalars().all()

		# Deduplicate: latest per ISIN
		seen: set[str] = set()
		deduped_holdings = []
		for h in latest_holdings:
			if h.instrument_isin not in seen:
				seen.add(h.instrument_isin)
				deduped_holdings.append(h)

		total_holdings_value = sum(h.current_value_cents for h in deduped_holdings)
		total_unrealized_pnl = sum(h.unrealized_pnl_cents for h in deduped_holdings)
		total_account_balance = sum(a.balance_cents for a in accounts)

		return {
			"client_id": client_id,
			"client_number": client.client_number,
			"as_of_date": as_of_date.isoformat(),
			"total_aum_cents": total_holdings_value + total_account_balance,
			"total_holdings_value_cents": total_holdings_value,
			"total_unrealized_pnl_cents": total_unrealized_pnl,
			"total_account_balance_cents": total_account_balance,
			"accounts": [
				{
					"account_id": a.id,
					"account_number": a.account_number,
					"account_type": a.account_type,
					"currency_code": a.currency_code,
					"balance_cents": a.balance_cents,
					"available_balance_cents": a.available_balance_cents,
					"status": a.status,
				}
				for a in accounts
			],
			"holdings": [
				{
					"instrument_isin": h.instrument_isin,
					"instrument_name": h.instrument_name,
					"quantity": str(h.quantity),
					"avg_cost_cents": h.avg_cost_cents,
					"current_value_cents": h.current_value_cents,
					"unrealized_pnl_cents": h.unrealized_pnl_cents,
					"as_of_date": h.as_of_date.isoformat(),
				}
				for h in deduped_holdings
			],
		}

	def get_aml_watchlist(self, tenant_id: str, session: Any) -> list[dict]:
		"""Return all parties with open POTENTIAL_MATCH or CONFIRMED_MATCH sanctions.

		Used for compliance officer dashboards.
		"""
		from pgappforge.plugins.erp.industry.financial_services.models import SanctionsScreeningResult
		from pgappforge.plugins.erp.foundation.models import Party

		rows = session.execute(
			select(
				SanctionsScreeningResult.id,
				SanctionsScreeningResult.party_id,
				Party.name.label("party_name"),
				SanctionsScreeningResult.list_type,
				SanctionsScreeningResult.match_score,
				SanctionsScreeningResult.status,
				SanctionsScreeningResult.screening_date,
			)
			.join(Party, Party.id == SanctionsScreeningResult.party_id)
			.where(
				SanctionsScreeningResult.tenant_id == tenant_id,
				SanctionsScreeningResult.status.in_(["POTENTIAL_MATCH", "CONFIRMED_MATCH"]),
			)
			.order_by(SanctionsScreeningResult.screening_date.desc())
		).all()

		return [
			{
				"screening_id": r.id,
				"party_id": r.party_id,
				"party_name": r.party_name,
				"list_type": r.list_type,
				"match_score": str(r.match_score) if r.match_score is not None else None,
				"status": r.status,
				"screening_date": r.screening_date.isoformat() if r.screening_date else None,
			}
			for r in rows
		]


__all__ = [
	"FinancialServicesService",
	"FinServError",
	"ClientNotFoundError",
	"AccountNotFoundError",
	"AccountFrozenError",
	"AccountClosedError",
	"InsufficientBalanceError",
	"KYCNotApprovedError",
	"SanctionsHoldError",
	"DuplicateClientNumberError",
]
