"""
pgappforge/plugins/fintech/remittance/services.py

RemittanceService — cross-border money transfer operations.

All methods accept an explicit SQLAlchemy session so callers control
transaction boundaries.  Event emission is wrapped in try/except so
a broken event bus never aborts a business transaction.

FX rate lookup order:
  1. Config dict REMITTANCE_FX_RATES keyed by "FROM_TO" e.g. {"KE_GB": 0.0066}
  2. Default fallback: 1.0

Fee formula (applied to send_amount_cents):
  fee = flat_fee_cents + round(send_amount_cents * fee_pct)
  receive_amount = round((send_amount_cents - fee) * fx_rate)
  total_debit = send_amount_cents + fee
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.erp.foundation.commons import emit_event
from pgappforge.plugins.fintech.remittance.models import (
	RemittanceCorridor,
	RemittanceComplianceLog,
	RemittanceQuote,
	RemittanceTransaction,
)
from pgappforge.plugins.fintech.remittance.events import (
	ComplianceCheckEvent,
	QuoteGeneratedEvent,
	TransferCancelledEvent,
	TransferInitiatedEvent,
	TransferPaidEvent,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Africa-focused corridor seed data
# ---------------------------------------------------------------------------

_AFRICA_CORRIDORS: list[dict[str, Any]] = [
	{
		"from_country": "KE", "to_country": "UG",
		"currency_pair": "KES/UGX",
		"payout_methods": ["MOBILE_MONEY", "BANK", "CASH_PICKUP"],
		"min_amount_cents": 1_000_00, "max_amount_cents": 5_000_000_00,
		"flat_fee_cents": 200_00, "fee_pct": "0.0100",
		"regulatory_notes": "CBK and BoU dual reporting required above KES 1M",
	},
	{
		"from_country": "KE", "to_country": "TZ",
		"currency_pair": "KES/TZS",
		"payout_methods": ["MOBILE_MONEY", "BANK", "CASH_PICKUP"],
		"min_amount_cents": 1_000_00, "max_amount_cents": 5_000_000_00,
		"flat_fee_cents": 200_00, "fee_pct": "0.0100",
		"regulatory_notes": "CBK and BoT reporting required",
	},
	{
		"from_country": "KE", "to_country": "RW",
		"currency_pair": "KES/RWF",
		"payout_methods": ["MOBILE_MONEY", "BANK"],
		"min_amount_cents": 1_000_00, "max_amount_cents": 5_000_000_00,
		"flat_fee_cents": 200_00, "fee_pct": "0.0100",
		"regulatory_notes": "EAC corridor — CBK/BNR",
	},
	{
		"from_country": "KE", "to_country": "GB",
		"currency_pair": "KES/GBP",
		"payout_methods": ["BANK", "CARD_PUSH"],
		"min_amount_cents": 5_000_00, "max_amount_cents": 50_000_000_00,
		"flat_fee_cents": 500_00, "fee_pct": "0.0150",
		"regulatory_notes": "CBK forex dealer licence required; FCA SWIFT rails",
	},
	{
		"from_country": "KE", "to_country": "US",
		"currency_pair": "KES/USD",
		"payout_methods": ["BANK", "WALLET"],
		"min_amount_cents": 5_000_00, "max_amount_cents": 50_000_000_00,
		"flat_fee_cents": 500_00, "fee_pct": "0.0150",
		"regulatory_notes": "FinCEN / OFAC checks mandatory",
	},
	{
		"from_country": "KE", "to_country": "AE",
		"currency_pair": "KES/AED",
		"payout_methods": ["BANK", "WALLET", "CASH_PICKUP"],
		"min_amount_cents": 5_000_00, "max_amount_cents": 30_000_000_00,
		"flat_fee_cents": 400_00, "fee_pct": "0.0120",
		"regulatory_notes": "CBUAE and CBK",
	},
	{
		"from_country": "NG", "to_country": "GB",
		"currency_pair": "NGN/GBP",
		"payout_methods": ["BANK", "CARD_PUSH"],
		"min_amount_cents": 10_000_00, "max_amount_cents": 100_000_000_00,
		"flat_fee_cents": 1_000_00, "fee_pct": "0.0200",
		"regulatory_notes": "CBN diaspora remittance policy; FCA regulated rails",
	},
	{
		"from_country": "NG", "to_country": "US",
		"currency_pair": "NGN/USD",
		"payout_methods": ["BANK", "WALLET"],
		"min_amount_cents": 10_000_00, "max_amount_cents": 100_000_000_00,
		"flat_fee_cents": 1_000_00, "fee_pct": "0.0200",
		"regulatory_notes": "CBN + FinCEN; BVN required for sender",
	},
	{
		"from_country": "GH", "to_country": "GB",
		"currency_pair": "GHS/GBP",
		"payout_methods": ["BANK", "MOBILE_MONEY", "CARD_PUSH"],
		"min_amount_cents": 5_000_00, "max_amount_cents": 50_000_000_00,
		"flat_fee_cents": 500_00, "fee_pct": "0.0150",
		"regulatory_notes": "BoG and FCA",
	},
]


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class RemittanceError(Exception):
	"""Base exception for remittance service errors."""


class CorridorNotFoundError(RemittanceError):
	"""No active corridor for the requested country pair."""


class QuoteExpiredError(RemittanceError):
	"""The referenced quote has expired."""


class QuoteNotFoundError(RemittanceError):
	"""No quote found for the given ID."""


class TransactionNotFoundError(RemittanceError):
	"""No transaction found for the given ID."""


class InvalidTransactionStatusError(RemittanceError):
	"""Operation not permitted in the current transaction status."""


# ---------------------------------------------------------------------------
# RemittanceService
# ---------------------------------------------------------------------------

class RemittanceService:
	"""Cross-border remittance operations.

	Instantiate without arguments; pass session explicitly to every method.
	Config is read from Flask app config when available; falls back to defaults.
	"""

	def __init__(self, config: dict[str, Any] | None = None) -> None:
		self._config: dict[str, Any] = config or {}
		# Try to pull config from Flask app context
		try:
			from flask import current_app
			self._config = {**current_app.config, **self._config}
		except RuntimeError:
			pass

	# ------------------------------------------------------------------ #
	# Internal helpers                                                     #
	# ------------------------------------------------------------------ #

	def _fx_rate(self, from_country: str, to_country: str) -> Decimal:
		"""Look up FX rate from config or return 1.0 as fallback.

		Config key: REMITTANCE_FX_RATES  (dict keyed by "FROM_TO" e.g. "KE_GB")
		"""
		rates: dict[str, float] = self._config.get("REMITTANCE_FX_RATES", {})
		key = f"{from_country}_{to_country}"
		rate = rates.get(key, rates.get(key.upper(), None))
		if rate is not None:
			return Decimal(str(rate))
		return Decimal("1.0")

	def _generate_reference(self) -> str:
		return f"REM-{uuid.uuid4().hex[:12].upper()}"

	# ------------------------------------------------------------------ #
	# Public service methods                                               #
	# ------------------------------------------------------------------ #

	def get_quote(
		self,
		from_country: str,
		to_country: str,
		send_amount_cents: int,
		payout_method: str,
		tenant_id: str,
		session: Any,
	) -> RemittanceQuote:
		"""Compute an FX quote for a given send amount and corridor.

		Returns a persisted RemittanceQuote with 15-minute expiry.
		Emits QuoteGeneratedEvent.

		Raises CorridorNotFoundError if no active corridor exists.
		"""
		corridor: RemittanceCorridor | None = session.execute(
			select(RemittanceCorridor).where(
				RemittanceCorridor.tenant_id == tenant_id,
				RemittanceCorridor.from_country == from_country,
				RemittanceCorridor.to_country == to_country,
				RemittanceCorridor.is_active.is_(True),
			)
		).scalar_one_or_none()

		if corridor is None:
			raise CorridorNotFoundError(
				f"No active corridor {from_country!r}→{to_country!r} for tenant {tenant_id!r}"
			)

		fx_rate = self._fx_rate(from_country, to_country)
		fee_pct = Decimal(str(corridor.fee_pct))
		flat = corridor.flat_fee_cents

		fee_cents = flat + int((Decimal(send_amount_cents) * fee_pct).to_integral_value(ROUND_HALF_UP))
		net_send = send_amount_cents - fee_cents
		receive_amount_cents = int((Decimal(net_send) * fx_rate).to_integral_value(ROUND_HALF_UP))
		total_debit_cents = send_amount_cents + fee_cents

		now = datetime.now(timezone.utc)
		quote = RemittanceQuote(
			tenant_id=tenant_id,
			corridor_id=corridor.id,
			send_amount_cents=send_amount_cents,
			receive_amount_cents=receive_amount_cents,
			fx_rate=fx_rate,
			fee_cents=fee_cents,
			total_debit_cents=total_debit_cents,
			payout_method=payout_method,
			expires_at=now + timedelta(minutes=15),
			created_at=now,
		)
		session.add(quote)
		session.flush()

		try:
			emit_event(
				QuoteGeneratedEvent(
					aggregate_id=quote.id,
					aggregate_type="RemittanceQuote",
					tenant_id=tenant_id,
					quote_id=quote.id,
					corridor_id=corridor.id,
					from_country=from_country,
					to_country=to_country,
					send_amount_cents=send_amount_cents,
					receive_amount_cents=receive_amount_cents,
					fx_rate=str(fx_rate),
					fee_cents=fee_cents,
					payout_method=payout_method,
					expires_at=quote.expires_at.isoformat(),
				),
				session,
			)
		except Exception as exc:
			log.warning("get_quote: event emission failed (non-fatal): %s", exc)

		log.info(
			"RemittanceService.get_quote: quote %s created for %s→%s send=%dc",
			quote.id, from_country, to_country, send_amount_cents,
		)
		return quote

	def initiate_transfer(
		self,
		quote_id: str,
		sender_customer_id: str,
		receiver_name: str,
		receiver_phone: str,
		tenant_id: str,
		session: Any,
		*,
		receiver_account: str | None = None,
	) -> RemittanceTransaction:
		"""Create a transfer from a valid (non-expired) quote.

		1. Validates quote not expired.
		2. Creates RemittanceTransaction (PENDING).
		3. Runs AML and KYC compliance checks.
		4. Advances status to PROCESSING if all checks pass.
		5. Emits TransferInitiatedEvent.

		Raises QuoteNotFoundError, QuoteExpiredError.
		"""
		quote: RemittanceQuote | None = session.execute(
			select(RemittanceQuote).where(
				RemittanceQuote.id == quote_id,
				RemittanceQuote.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if quote is None:
			raise QuoteNotFoundError(f"Quote {quote_id!r} not found for tenant {tenant_id!r}")

		now = datetime.now(timezone.utc)
		if quote.expires_at < now:
			raise QuoteExpiredError(f"Quote {quote_id!r} expired at {quote.expires_at.isoformat()!r}")

		txn = RemittanceTransaction(
			tenant_id=tenant_id,
			quote_id=quote_id,
			sender_customer_id=sender_customer_id,
			receiver_name=receiver_name,
			receiver_phone=receiver_phone,
			receiver_account=receiver_account,
			payout_method=quote.payout_method,
			send_amount_cents=quote.send_amount_cents,
			receive_amount_cents=quote.receive_amount_cents,
			fx_rate=quote.fx_rate,
			fee_cents=quote.fee_cents,
			status="PENDING",
			reference=self._generate_reference(),
			compliance_checked=False,
		)
		session.add(txn)
		session.flush()

		# Compliance checks
		aml_pass = self._run_aml_check(txn, session)
		kyc_pass = self._run_kyc_check(sender_customer_id, session)

		txn.compliance_checked = True
		if aml_pass and kyc_pass:
			txn.status = "PROCESSING"
		else:
			txn.status = "PENDING"
			log.warning(
				"initiate_transfer: compliance failed for txn %s (aml=%s kyc=%s)",
				txn.id, aml_pass, kyc_pass,
			)

		session.flush()

		try:
			emit_event(
				TransferInitiatedEvent(
					aggregate_id=txn.id,
					aggregate_type="RemittanceTransaction",
					tenant_id=tenant_id,
					transaction_id=txn.id,
					reference=txn.reference,
					quote_id=quote_id,
					sender_customer_id=sender_customer_id,
					receiver_name=receiver_name,
					payout_method=txn.payout_method,
					send_amount_cents=txn.send_amount_cents,
					receive_amount_cents=txn.receive_amount_cents,
					status=txn.status,
				),
				session,
			)
		except Exception as exc:
			log.warning("initiate_transfer: event emission failed (non-fatal): %s", exc)

		log.info(
			"RemittanceService.initiate_transfer: txn %s ref=%s status=%s",
			txn.id, txn.reference, txn.status,
		)
		return txn

	def process_payout(
		self,
		transaction_id: str,
		provider_reference: str,
		tenant_id: str,
		session: Any,
	) -> RemittanceTransaction:
		"""Record provider payout confirmation — sets status to PAID.

		Emits TransferPaidEvent.
		Raises TransactionNotFoundError.
		"""
		txn = self._get_transaction(transaction_id, tenant_id, session)
		txn.status = "PAID"
		txn.provider_reference = provider_reference
		session.flush()

		try:
			emit_event(
				TransferPaidEvent(
					aggregate_id=txn.id,
					aggregate_type="RemittanceTransaction",
					tenant_id=tenant_id,
					transaction_id=txn.id,
					reference=txn.reference,
					provider_reference=provider_reference,
					send_amount_cents=txn.send_amount_cents,
					receive_amount_cents=txn.receive_amount_cents,
					payout_method=txn.payout_method,
				),
				session,
			)
		except Exception as exc:
			log.warning("process_payout: event emission failed (non-fatal): %s", exc)

		log.info("RemittanceService.process_payout: txn %s PAID via %s", txn.id, provider_reference)
		return txn

	def cancel_transfer(
		self,
		transaction_id: str,
		reason: str,
		tenant_id: str,
		session: Any,
	) -> RemittanceTransaction:
		"""Cancel a PENDING or PROCESSING transfer.

		Emits TransferCancelledEvent.
		Raises TransactionNotFoundError, InvalidTransactionStatusError.
		"""
		txn = self._get_transaction(transaction_id, tenant_id, session)
		if txn.status not in ("PENDING", "PROCESSING"):
			raise InvalidTransactionStatusError(
				f"Cannot cancel transfer in status {txn.status!r}; "
				"must be PENDING or PROCESSING"
			)

		prior_status = txn.status
		txn.status = "CANCELLED"
		session.flush()

		try:
			emit_event(
				TransferCancelledEvent(
					aggregate_id=txn.id,
					aggregate_type="RemittanceTransaction",
					tenant_id=tenant_id,
					transaction_id=txn.id,
					reference=txn.reference,
					reason=reason,
					prior_status=prior_status,
				),
				session,
			)
		except Exception as exc:
			log.warning("cancel_transfer: event emission failed (non-fatal): %s", exc)

		log.info("RemittanceService.cancel_transfer: txn %s CANCELLED (%s)", txn.id, reason)
		return txn

	def get_transfer_status(
		self,
		transaction_id: str,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Return a lightweight status dict for a transfer."""
		txn = self._get_transaction(transaction_id, tenant_id, session)
		return {
			"transaction_id": txn.id,
			"reference": txn.reference,
			"status": txn.status,
			"send_amount_cents": txn.send_amount_cents,
			"receive_amount_cents": txn.receive_amount_cents,
			"payout_method": txn.payout_method,
			"provider_reference": txn.provider_reference,
			"compliance_checked": txn.compliance_checked,
			"created_at": txn.created_at.isoformat() if txn.created_at else None,
			"updated_at": txn.updated_at.isoformat() if txn.updated_at else None,
		}

	def seed_africa_corridors(self, tenant_id: str, session: Any) -> int:
		"""Idempotently seed the 9 Africa-focused corridors for a tenant.

		Returns the count of newly inserted corridors.
		"""
		from decimal import Decimal

		inserted = 0
		for spec in _AFRICA_CORRIDORS:
			existing = session.execute(
				select(RemittanceCorridor).where(
					RemittanceCorridor.tenant_id == tenant_id,
					RemittanceCorridor.from_country == spec["from_country"],
					RemittanceCorridor.to_country == spec["to_country"],
				)
			).scalar_one_or_none()
			if existing is not None:
				continue

			corridor = RemittanceCorridor(
				tenant_id=tenant_id,
				from_country=spec["from_country"],
				to_country=spec["to_country"],
				currency_pair=spec["currency_pair"],
				payout_methods=spec["payout_methods"],
				min_amount_cents=spec["min_amount_cents"],
				max_amount_cents=spec["max_amount_cents"],
				flat_fee_cents=spec["flat_fee_cents"],
				fee_pct=Decimal(spec["fee_pct"]),
				is_active=True,
				regulatory_notes=spec.get("regulatory_notes"),
			)
			session.add(corridor)
			inserted += 1

		if inserted:
			session.flush()
			log.info(
				"RemittanceService.seed_africa_corridors: inserted %d corridors for tenant %r",
				inserted, tenant_id,
			)
		return inserted

	# ------------------------------------------------------------------ #
	# Internal compliance helpers                                          #
	# ------------------------------------------------------------------ #

	def _run_aml_check(
		self,
		transaction: RemittanceTransaction,
		session: Any,
	) -> bool:
		"""Run AML screening on a transaction.

		Attempts to call regulatory AMLService.  Falls back to True (pass)
		if the regulatory plugin is not installed or raises.

		Records a RemittanceComplianceLog row in all cases.
		"""
		result = "PASS"
		details: dict[str, Any] = {"provider": "INTERNAL", "fallback": True}

		try:
			from pgappforge.plugins.fintech.regulatory.services import AMLService
			aml_svc = AMLService()
			outcome = aml_svc.screen_transaction(
				transaction_id=transaction.id,
				amount_cents=transaction.send_amount_cents,
				sender_id=str(transaction.sender_customer_id),
				session=session,
			)
			result = "PASS" if outcome.get("cleared") else "FAIL"
			details = {**outcome, "fallback": False}
		except ImportError:
			log.debug("_run_aml_check: regulatory plugin not installed, defaulting PASS")
		except Exception as exc:
			log.warning("_run_aml_check: AML check error (defaulting PASS): %s", exc)

		log_row = RemittanceComplianceLog(
			tenant_id=transaction.tenant_id,
			transaction_id=transaction.id,
			check_type="AML",
			result=result,
			details=details,
		)
		session.add(log_row)
		session.flush()

		try:
			emit_event(
				ComplianceCheckEvent(
					aggregate_id=log_row.id,
					aggregate_type="RemittanceComplianceLog",
					tenant_id=transaction.tenant_id,
					compliance_log_id=log_row.id,
					transaction_id=transaction.id,
					check_type="AML",
					result=result,
				),
				session,
			)
		except Exception as exc:
			log.warning("_run_aml_check: event emission failed (non-fatal): %s", exc)

		return result == "PASS"

	def _run_kyc_check(
		self,
		sender_customer_id: str,
		session: Any,
	) -> bool:
		"""Check KYC status for the sending customer.

		Attempts to call regulatory KYC service.  Falls back to True (pass).
		"""
		try:
			from pgappforge.plugins.fintech.regulatory.services import KYCService
			kyc_svc = KYCService()
			outcome = kyc_svc.check_customer(
				customer_id=sender_customer_id,
				session=session,
			)
			return bool(outcome.get("verified", True))
		except ImportError:
			log.debug("_run_kyc_check: regulatory plugin not installed, defaulting PASS")
			return True
		except Exception as exc:
			log.warning("_run_kyc_check: KYC check error (defaulting PASS): %s", exc)
			return True

	# ------------------------------------------------------------------ #
	# Internal fetch helpers                                               #
	# ------------------------------------------------------------------ #

	def _get_transaction(
		self,
		transaction_id: str,
		tenant_id: str,
		session: Any,
	) -> RemittanceTransaction:
		txn: RemittanceTransaction | None = session.execute(
			select(RemittanceTransaction).where(
				RemittanceTransaction.id == transaction_id,
				RemittanceTransaction.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if txn is None:
			raise TransactionNotFoundError(
				f"Transaction {transaction_id!r} not found for tenant {tenant_id!r}"
			)
		return txn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"RemittanceService",
	"RemittanceError",
	"CorridorNotFoundError",
	"QuoteExpiredError",
	"QuoteNotFoundError",
	"TransactionNotFoundError",
	"InvalidTransactionStatusError",
]
