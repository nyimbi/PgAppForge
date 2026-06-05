# httpx must be installed for production use: pip install httpx
# Set PSWITCH_ALLOW_OFFLINE=True only for development/testing with amount ceiling PSWITCH_MAX_OFFLINE_CENTS
"""
pgappforge/plugins/fintech/pswitch_adapter/services.py

PswitchAdapterService — bridges core banking accounts to the Hyperion-X
ISO 8583 / ISO 20022 payment switch for card authorization and settlement.

Responsibilities
----------------
  authorize_card_transaction  — place hold on account, POST auth to pswitch,
                                persist CardTransaction (AUTHORIZED/DECLINED)
  process_settlement_file     — consume a batch of DEBIT/CREDIT records,
                                post GL entries, mark transactions SETTLED
  reverse_card_transaction    — release hold, notify pswitch, mark REVERSED
  reconcile_settlement        — compare settled amounts against GL journal entries

Resilience contract
-------------------
  All pswitch HTTP calls are wrapped in try/except.  If the switch is
  unreachable the service emits a warning and falls back gracefully:
    - authorize: returns offline approval with the local hold in place
    - reverse:   marks the transaction REVERSED locally; retries are the
                 caller's responsibility (e.g. a scheduled job)
  Core banking mutations are NEVER aborted due to a pswitch connectivity error.

GL account codes
----------------
  CUSTOMER_DEPOSITS       "2100"   — liability: customer deposit balances
  CARD_SETTLEMENT_SUSPENSE "2120"  — suspense: amounts in transit to/from schemes

Money convention
----------------
  All amounts in INTEGER CENTS (BigInteger).  No floats anywhere.
"""
from __future__ import annotations

import logging
import secrets
import string
import uuid
from datetime import datetime, timezone
from typing import Any

import sqlalchemy as sa
from flask import current_app
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.fintech.pswitch_adapter.events import (
	CardAuthorizedEvent,
	CardDeclinedEvent,
	CardReversedEvent,
	CardSettledEvent,
	SettlementFileProcessedEvent,
)
from pgappforge.plugins.fintech.pswitch_adapter.models import (
	CardSettlementFile,
	CardTransaction,
)

log = logging.getLogger(__name__)

__all__ = [
	"PswitchAdapterService",
	"PswitchAdapterError",
	"CardTransactionNotFoundError",
	"SettlementFileNotFoundError",
	"DuplicateTransactionError",
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class PswitchAdapterError(Exception):
	"""Base error for pswitch adapter operations."""


class CardTransactionNotFoundError(PswitchAdapterError):
	"""Raised when a CardTransaction lookup by pswitch_txn_id fails."""


class SettlementFileNotFoundError(PswitchAdapterError):
	"""Raised when a CardSettlementFile lookup fails."""


class DuplicateTransactionError(PswitchAdapterError):
	"""Raised when pswitch_txn_id already exists in this tenant."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_code() -> str:
	"""Generate a random 6-character alphanumeric authorization code."""
	alphabet = string.ascii_uppercase + string.digits
	return "".join(secrets.choice(alphabet) for _ in range(6))


def _offline_pswitch_txn_id() -> str:
	"""Fallback pswitch_txn_id when the switch is unreachable (offline mode)."""
	return f"OFFLINE-{uuid.uuid4().hex[:16].upper()}"


# ---------------------------------------------------------------------------
# PswitchAdapterService
# ---------------------------------------------------------------------------

class PswitchAdapterService:
	"""Bridges pgappforge core banking accounts to Hyperion-X pswitch.

	Parameters
	----------
	session:
		Active SQLAlchemy Session.  The caller owns the transaction boundary;
		this service calls session.flush() but never session.commit().
	tenant_id:
		Tenant scope for all DB operations.
	pswitch_base_url:
		Base URL of the Hyperion-X REST API.  Defaults to
		PSWITCH_BASE_URL config key or 'http://localhost:8583'.
	"""

	def __init__(
		self,
		session: Session,
		tenant_id: str,
		pswitch_base_url: str | None = None,
	) -> None:
		self._session = session
		self._tenant_id = tenant_id
		self._base_url: str = pswitch_base_url or self._resolve_base_url()

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _resolve_base_url(self) -> str:
		try:
			return current_app.config.get("PSWITCH_BASE_URL", "http://localhost:8583")
		except RuntimeError:
			# Outside Flask application context (e.g. tests without app)
			return "http://localhost:8583"

	def _core_banking(self) -> Any:
		"""Lazy import CoreBankingService to avoid circular dependency."""
		from pgappforge.plugins.fintech.core_banking.services import (
			CoreBankingService,
		)
		return CoreBankingService(tenant_id=self._tenant_id)

	def _http_post(self, path: str, payload: dict) -> dict | None:
		"""POST *payload* to pswitch REST API at *path*.

		Returns the parsed JSON response dict on success, or None if the
		request fails for any reason (network, timeout, non-2xx status).
		Never raises — all errors are logged as warnings.
		httpx is mandatory for production; set PSWITCH_ALLOW_OFFLINE=True in config
		to allow offline fallback (development/testing only).
		"""
		try:
			import httpx
		except ImportError:
			if not current_app.config.get('PSWITCH_ALLOW_OFFLINE', False):
				raise RuntimeError(
					"httpx is required for PswitchAdapterService. Install it: pip install httpx. "
					"Or set PSWITCH_ALLOW_OFFLINE=True in config (not recommended for production)."
				) from None
			log.warning("pswitch: httpx not installed, using offline approval (PSWITCH_ALLOW_OFFLINE=True)")
			return None

		url = f"{self._base_url}{path}"
		try:
			resp = httpx.post(url, json=payload, timeout=5.0)
			resp.raise_for_status()
			return resp.json()
		except Exception as exc:
			log.warning(
				"pswitch_adapter: POST %s failed (%s) — using offline fallback",
				url,
				exc,
			)
			return None

	def _require_card_transaction(self, pswitch_txn_id: str) -> CardTransaction:
		txn = (
			self._session.execute(
				sa.select(CardTransaction).where(
					CardTransaction.pswitch_txn_id == pswitch_txn_id,
					CardTransaction.tenant_id == self._tenant_id,
				)
			)
			.scalars()
			.one_or_none()
		)
		if txn is None:
			raise CardTransactionNotFoundError(
				f"CardTransaction with pswitch_txn_id={pswitch_txn_id!r} "
				f"not found for tenant {self._tenant_id!r}"
			)
		return txn

	def _post_gl(
		self,
		session: Session,
		*,
		dr_account_code: str,
		cr_account_code: str,
		amount_cents: int,
		party_id: str,
		description: str,
		tenant_id: str,
		source_doc_id: str,
		source_doc_type: str,
	) -> str | None:
		"""Post a double-entry GL line via CoreBankingService._post_to_gl.

		Returns journal_id on success, None if the GL bridge is unavailable.
		Errors are non-fatal (warning logged).
		"""
		try:
			cb = self._core_banking()
			result = cb._post_to_gl(
				session=session,
				lines=[
					{
						"account_code": dr_account_code,
						"debit_cents": amount_cents,
						"credit_cents": 0,
						"party_id": party_id,
						"description": description,
					},
					{
						"account_code": cr_account_code,
						"debit_cents": 0,
						"credit_cents": amount_cents,
						"party_id": party_id,
						"description": description,
					},
				],
				description=description,
				tenant_id=tenant_id,
				source_doc_id=source_doc_id,
				source_doc_type="PSWITCH_CARD_TXN",
			)
			return result.get("journal_id") if isinstance(result, dict) else None
		except Exception as exc:
			log.warning("pswitch_adapter: GL post failed (non-fatal): %s", exc)
			return None

	# ------------------------------------------------------------------
	# authorize_card_transaction
	# ------------------------------------------------------------------

	def authorize_card_transaction(
		self,
		account_number: str,
		card_pan_masked: str,
		amount_cents: int,
		currency_code: str = "KES",
		merchant_name: str | None = None,
		mcc: str | None = None,
		terminal_id: str | None = None,
		card_scheme: str = "KENSWITCH",
		correlation_id: str = "",
	) -> dict:
		"""Authorize a card transaction against a core banking account.

		Flow
		----
		1. Place authorization hold on the account via CoreBankingService.
		2. POST authorization request to pswitch; fall back to offline approval
		   if pswitch is unavailable.
		3. Persist CardTransaction with status=AUTHORIZED (or DECLINED if
		   funds were insufficient or pswitch explicitly declined).
		4. Emit CardAuthorizedEvent or CardDeclinedEvent.

		Returns
		-------
		dict with keys:
		  authorized    bool
		  auth_code     str | None
		  response_code str          (ISO 8583 DE-39)
		  pswitch_txn_id str
		  hold_id       str | None
		  card_transaction_id str
		"""
		assert amount_cents > 0, "amount_cents must be positive"
		assert card_pan_masked, "card_pan_masked is required"
		assert account_number, "account_number is required"

		session = self._session
		now = datetime.now(timezone.utc)

		# 1. Place hold
		hold_id: str | None = None
		hold_placed = False
		try:
			cb = self._core_banking()
			hold = cb.place_hold(
				session=session,
				account_number=account_number,
				amount_cents=amount_cents,
				reason=f"CARD_AUTH {card_pan_masked} {merchant_name or ''}".strip(),
				reference=f"PSWITCH-{uuid.uuid4().hex[:8].upper()}",
				tenant_id=self._tenant_id,
				correlation_id=correlation_id,
			)
			hold_id = hold.id
			hold_placed = True
		except Exception as exc:
			# InsufficientFundsError, account closed, etc. → decline
			log.info(
				"pswitch_adapter: hold placement failed for %s: %s",
				account_number,
				exc,
			)
			decline_txn = CardTransaction(
				tenant_id=self._tenant_id,
				pswitch_txn_id=_offline_pswitch_txn_id(),
				account_id=account_number,  # best-effort; real UUID resolved below
				card_pan_masked=card_pan_masked,
				card_scheme=card_scheme,
				transaction_type="PURCHASE",
				mti="0110",
				amount_cents=amount_cents,
				currency_code=currency_code,
				merchant_name=merchant_name,
				merchant_category_code=mcc,
				terminal_id=terminal_id,
				response_code="51",  # insufficient funds
				status="DECLINED",
				attributes={"decline_reason": str(exc)},
			)
			session.add(decline_txn)
			session.flush()
			self._emit_declined(
				decline_txn,
				account_number=account_number,
				decline_reason=str(exc),
				correlation_id=correlation_id,
			)
			return {
				"authorized": False,
				"auth_code": None,
				"response_code": "51",
				"pswitch_txn_id": decline_txn.pswitch_txn_id,
				"hold_id": None,
				"card_transaction_id": decline_txn.id,
			}

		# 2. Resolve account_id UUID from account_number
		account_id = self._resolve_account_id(account_number)

		# 3. Call pswitch
		pswitch_resp = self._http_post(
			"/api/v1/authorize",
			{
				"amount_cents": amount_cents,
				"currency_code": currency_code,
				"pan_masked": card_pan_masked,
				"mcc": mcc,
				"terminal_id": terminal_id,
				"account_ref": account_number,
				"card_scheme": card_scheme,
				"merchant_name": merchant_name,
			},
		)

		if pswitch_resp is not None:
			# Live pswitch response
			response_code = pswitch_resp.get("response_code", "05")
			pswitch_txn_id = pswitch_resp.get("transaction_id") or _offline_pswitch_txn_id()
			auth_code = pswitch_resp.get("auth_code")
			authorized = response_code == "00"
		else:
			# Offline fallback — approve locally only if within ceiling
			PSWITCH_MAX_OFFLINE_CENTS = int(current_app.config.get('PSWITCH_MAX_OFFLINE_CENTS', 50_00))  # 50 KES default
			if amount_cents > PSWITCH_MAX_OFFLINE_CENTS:
				log.warning(
					"pswitch_adapter: pswitch unreachable — offline approval denied "
					"(amount %dc > ceiling %dc) for %s %s",
					amount_cents, PSWITCH_MAX_OFFLINE_CENTS, account_number, card_pan_masked,
				)
				response_code = "91"
				pswitch_txn_id = _offline_pswitch_txn_id()
				auth_code = None
				authorized = False
			else:
				log.warning(
					"pswitch_adapter: pswitch unreachable — issuing offline approval "
					"for %s %sc %s",
					account_number,
					amount_cents,
					card_pan_masked,
				)
				response_code = "00"
				pswitch_txn_id = _offline_pswitch_txn_id()
				auth_code = _auth_code()
				authorized = True

		# If pswitch explicitly declined, release the hold
		if not authorized and hold_placed and hold_id:
			try:
				cb = self._core_banking()
				cb.release_hold(
					session=session,
					hold_id=hold_id,
					tenant_id=self._tenant_id,
					correlation_id=correlation_id,
				)
			except Exception as exc:
				log.warning("pswitch_adapter: hold release after decline failed: %s", exc)
			hold_id = None

		# 4. Persist CardTransaction
		txn = CardTransaction(
			tenant_id=self._tenant_id,
			pswitch_txn_id=pswitch_txn_id,
			account_id=account_id or account_number,
			card_pan_masked=card_pan_masked,
			card_scheme=card_scheme,
			transaction_type="PURCHASE",
			mti="0110",
			amount_cents=amount_cents,
			currency_code=currency_code,
			merchant_name=merchant_name,
			merchant_category_code=mcc,
			terminal_id=terminal_id,
			auth_code=auth_code if authorized else None,
			response_code=response_code,
			status="AUTHORIZED" if authorized else "DECLINED",
			authorized_at=now if authorized else None,
			hold_id=hold_id,
			attributes={
				"offline": pswitch_resp is None,
				"account_number": account_number,
			},
		)
		session.add(txn)
		session.flush()

		# 5. Emit event
		if authorized:
			self._emit_authorized(
				txn,
				account_number=account_number,
				hold_id=hold_id or "",
				correlation_id=correlation_id,
			)
		else:
			self._emit_declined(
				txn,
				account_number=account_number,
				decline_reason=f"response_code={response_code}",
				correlation_id=correlation_id,
			)

		return {
			"authorized": authorized,
			"auth_code": auth_code if authorized else None,
			"response_code": response_code,
			"pswitch_txn_id": pswitch_txn_id,
			"hold_id": hold_id,
			"card_transaction_id": txn.id,
		}

	# ------------------------------------------------------------------
	# process_settlement_file
	# ------------------------------------------------------------------

	def process_settlement_file(
		self,
		file_ref: str,
		records: list[dict],
		file_date: Any,  # datetime.date
		source: str = "INTERNAL",
		correlation_id: str = "",
	) -> dict:
		"""Process an inbound settlement file and post to GL.

		Parameters
		----------
		file_ref:
			Unique file reference (must be unique within tenant).
		records:
			List of dicts, each with keys:
			  pswitch_txn_id  str   — matches CardTransaction.pswitch_txn_id
			  amount_cents    int   — settlement amount
			  action          str   — "DEBIT" (debit customer) or "CREDIT" (refund)
		file_date:
			Settlement value date (datetime.date).
		source:
			Origin: VISA_NET | MASTERCARD_S2S | KENSWITCH | INTERNAL | MANUAL.

		Returns
		-------
		dict with keys:
		  processed           int   — total records attempted
		  matched             int   — transactions found and settled
		  unmatched           int   — pswitch_txn_id not found in DB
		  total_settled_cents int
		  settlement_file_id  str
		"""
		assert file_ref, "file_ref is required"
		assert isinstance(records, list), "records must be a list"

		session = self._session
		now = datetime.now(timezone.utc)

		# 1. Insert settlement file header
		sf = CardSettlementFile(
			tenant_id=self._tenant_id,
			file_date=file_date,
			file_ref=file_ref,
			source=source,
			record_count=len(records),
			status="RECEIVED",
		)
		session.add(sf)
		session.flush()

		sf.status = "PROCESSING"
		session.flush()

		processed = 0
		matched = 0
		unmatched = 0
		total_debits = 0
		total_credits = 0
		total_settled = 0

		try:
			cb = self._core_banking()

			for rec in records:
				pswitch_txn_id: str = rec["pswitch_txn_id"]
				rec_amount: int = int(rec["amount_cents"])
				action: str = rec.get("action", "DEBIT").upper()
				processed += 1

				# Find matching CardTransaction
				txn = (
					session.execute(
						sa.select(CardTransaction).where(
							CardTransaction.pswitch_txn_id == pswitch_txn_id,
							CardTransaction.tenant_id == self._tenant_id,
						)
					)
					.scalars()
					.one_or_none()
				)

				if txn is None:
					log.warning(
						"pswitch_adapter: settlement record %s not found — skipping",
						pswitch_txn_id,
					)
					unmatched += 1
					continue

				account_id = str(txn.account_id)
				account_number = txn.attributes.get("account_number", account_id)

				if action == "DEBIT":
					# Debit customer account — consume the existing hold if present
					try:
						if txn.hold_id:
							# Capture the hold (withdraw consuming the hold)
							cb.release_hold(
								session=session,
								hold_id=txn.hold_id,
								tenant_id=self._tenant_id,
								correlation_id=correlation_id,
							)
						# Post the actual debit
						entry_result = cb.withdraw(
							session=session,
							account_number=account_number,
							amount_cents=rec_amount,
							channel="CARD",
							reference=f"SETTLE-{sf.id[:8]}-{pswitch_txn_id[:8]}",
							narrative=f"Card settlement {sf.file_ref}",
							tenant_id=self._tenant_id,
							correlation_id=correlation_id,
						)
						ledger_entry_id = entry_result.get("entry_id", "")
					except Exception as exc:
						log.warning(
							"pswitch_adapter: settlement DEBIT for %s failed: %s",
							pswitch_txn_id,
							exc,
						)
						unmatched += 1
						continue

					total_debits += rec_amount
					total_settled += rec_amount

					# GL: DR CUSTOMER_DEPOSITS CR CARD_SETTLEMENT_SUSPENSE
					self._post_gl(
						session,
						dr_account_code="CUSTOMER_DEPOSITS",
						cr_account_code="CARD_SETTLEMENT_SUSPENSE",
						amount_cents=rec_amount,
						party_id=account_id,
						description=f"Card settlement DEBIT {pswitch_txn_id}",
						tenant_id=self._tenant_id,
						source_doc_id=txn.id,
						source_doc_type="PSWITCH_CARD_TXN",
					)

				elif action == "CREDIT":
					# Credit customer account — refund scenario
					try:
						entry_result = cb.deposit(
							session=session,
							account_number=account_number,
							amount_cents=rec_amount,
							channel="CARD_REFUND",
							reference=f"REFUND-{sf.id[:8]}-{pswitch_txn_id[:8]}",
							narrative=f"Card refund {sf.file_ref}",
							tenant_id=self._tenant_id,
							correlation_id=correlation_id,
						)
						ledger_entry_id = entry_result.get("entry_id", "")
					except Exception as exc:
						log.warning(
							"pswitch_adapter: settlement CREDIT for %s failed: %s",
							pswitch_txn_id,
							exc,
						)
						unmatched += 1
						continue

					total_credits += rec_amount
					total_settled += rec_amount

					# GL: DR CARD_SETTLEMENT_SUSPENSE CR CUSTOMER_DEPOSITS
					self._post_gl(
						session,
						dr_account_code="CARD_SETTLEMENT_SUSPENSE",
						cr_account_code="CUSTOMER_DEPOSITS",
						amount_cents=rec_amount,
						party_id=account_id,
						description=f"Card refund CREDIT {pswitch_txn_id}",
						tenant_id=self._tenant_id,
						source_doc_id=txn.id,
						source_doc_type="PSWITCH_CARD_TXN",
					)

				else:
					log.warning(
						"pswitch_adapter: unknown action %r for %s — skipping",
						action,
						pswitch_txn_id,
					)
					unmatched += 1
					continue

				# Mark transaction SETTLED
				txn.status = "SETTLED"
				txn.settled_at = now
				txn.ledger_entry_id = ledger_entry_id
				matched += 1

				# Emit CardSettledEvent
				try:
					emit_event(
						CardSettledEvent(
							aggregate_id=txn.id,
							aggregate_type="CardTransaction",
							tenant_id=self._tenant_id,
							correlation_id=correlation_id,
							card_transaction_id=txn.id,
							pswitch_txn_id=pswitch_txn_id,
							account_id=account_id,
							settlement_file_id=sf.id,
							amount_cents=rec_amount,
							currency_code=txn.currency_code,
							ledger_entry_id=ledger_entry_id,
						),
						session,
					)
				except Exception as exc:
					log.warning("pswitch_adapter: CardSettledEvent emit failed: %s", exc)

		except Exception as exc:
			# Unrecoverable error — mark file FAILED
			sf.status = "FAILED"
			sf.error_summary = str(exc)
			session.flush()
			log.error("pswitch_adapter: settlement file %s failed: %s", file_ref, exc)
			raise

		# 6. Update file header
		sf.status = "POSTED"
		sf.record_count = processed
		sf.total_debits_cents = total_debits
		sf.total_credits_cents = total_credits
		sf.processed_at = now
		session.flush()

		# Emit SettlementFileProcessedEvent
		try:
			emit_event(
				SettlementFileProcessedEvent(
					aggregate_id=sf.id,
					aggregate_type="CardSettlementFile",
					tenant_id=self._tenant_id,
					correlation_id=correlation_id,
					settlement_file_id=sf.id,
					file_ref=file_ref,
					source=source,
					record_count=processed,
					processed=processed,
					matched=matched,
					unmatched=unmatched,
					total_settled_cents=total_settled,
					total_debits_cents=total_debits,
					total_credits_cents=total_credits,
				),
				session,
			)
		except Exception as exc:
			log.warning("pswitch_adapter: SettlementFileProcessedEvent emit failed: %s", exc)

		return {
			"processed": processed,
			"matched": matched,
			"unmatched": unmatched,
			"total_settled_cents": total_settled,
			"settlement_file_id": sf.id,
		}

	# ------------------------------------------------------------------
	# reverse_card_transaction
	# ------------------------------------------------------------------

	def reverse_card_transaction(
		self,
		pswitch_txn_id: str,
		reason: str,
		correlation_id: str = "",
	) -> dict:
		"""Reverse an authorized card transaction.

		Flow
		----
		1. Load CardTransaction; assert it is AUTHORIZED (or CLEARED).
		2. Release authorization hold via CoreBankingService.release_hold().
		3. POST reversal notification to pswitch (non-fatal if unavailable).
		4. Mark CardTransaction status=REVERSED.
		5. Emit CardReversedEvent.

		Returns
		-------
		dict with keys:
		  reversed        bool
		  pswitch_txn_id  str
		  card_transaction_id str
		"""
		assert pswitch_txn_id, "pswitch_txn_id is required"
		assert reason, "reason is required"

		session = self._session
		txn = self._require_card_transaction(pswitch_txn_id)

		if txn.status not in ("AUTHORIZED", "CLEARED"):
			raise PswitchAdapterError(
				f"Cannot reverse CardTransaction {pswitch_txn_id!r} "
				f"with status={txn.status!r} — only AUTHORIZED/CLEARED allowed"
			)

		# 1. Release hold
		hold_released = False
		if txn.hold_id:
			try:
				cb = self._core_banking()
				cb.release_hold(
					session=session,
					hold_id=txn.hold_id,
					tenant_id=self._tenant_id,
					correlation_id=correlation_id,
				)
				hold_released = True
			except Exception as exc:
				log.warning(
					"pswitch_adapter: hold release for reversal %s failed: %s",
					pswitch_txn_id,
					exc,
				)

		# 2. Notify pswitch (non-fatal)
		self._http_post(
			"/api/v1/reverse",
			{
				"transaction_id": pswitch_txn_id,
				"reason": reason,
				"original_amount_cents": txn.amount_cents,
				"currency_code": txn.currency_code,
			},
		)

		# 3. Update status
		txn.status = "REVERSED"
		session.flush()

		# 4. Emit event
		try:
			emit_event(
				CardReversedEvent(
					aggregate_id=txn.id,
					aggregate_type="CardTransaction",
					tenant_id=self._tenant_id,
					correlation_id=correlation_id,
					card_transaction_id=txn.id,
					pswitch_txn_id=pswitch_txn_id,
					account_id=str(txn.account_id),
					amount_cents=txn.amount_cents,
					currency_code=txn.currency_code,
					reversal_reason=reason,
					hold_released=hold_released,
				),
				session,
			)
		except Exception as exc:
			log.warning("pswitch_adapter: CardReversedEvent emit failed: %s", exc)

		return {
			"reversed": True,
			"pswitch_txn_id": pswitch_txn_id,
			"card_transaction_id": txn.id,
		}

	# ------------------------------------------------------------------
	# reconcile_settlement
	# ------------------------------------------------------------------

	def reconcile_settlement(
		self,
		settlement_file_id: str,
		correlation_id: str = "",
	) -> dict:
		"""Reconcile a processed settlement file against GL journal entries.

		Compares each SETTLED CardTransaction's amount_cents against the
		ledger_entry amount posted during settlement processing.

		Returns
		-------
		dict with keys:
		  matched             int   — transactions with matching GL entries
		  breaks              int   — mismatches or missing GL entries
		  total_break_cents   int   — sum of absolute discrepancies
		  settlement_file_id  str
		"""
		assert settlement_file_id, "settlement_file_id is required"

		session = self._session

		sf = session.get(CardSettlementFile, settlement_file_id)
		if sf is None or sf.tenant_id != self._tenant_id:
			raise SettlementFileNotFoundError(
				f"CardSettlementFile {settlement_file_id!r} not found "
				f"for tenant {self._tenant_id!r}"
			)

		# Load all SETTLED transactions linked to this file
		settled_txns = (
			session.execute(
				sa.select(CardTransaction).where(
					CardTransaction.tenant_id == self._tenant_id,
					CardTransaction.status == "SETTLED",
					CardTransaction.settled_at >= sf.created_at,
				)
			)
			.scalars()
			.all()
		)

		# Attempt to match against GL journal entries
		matched = 0
		breaks = 0
		total_break_cents = 0

		for txn in settled_txns:
			if not txn.ledger_entry_id:
				breaks += 1
				total_break_cents += txn.amount_cents
				log.warning(
					"pswitch_adapter: reconcile: txn %s has no ledger_entry_id",
					txn.pswitch_txn_id,
				)
				continue

			# Try to load the GL entry and compare amounts
			gl_amount = self._resolve_gl_entry_amount(txn.ledger_entry_id)

			if gl_amount is None:
				# GL entry not found
				breaks += 1
				total_break_cents += txn.amount_cents
				log.warning(
					"pswitch_adapter: reconcile: GL entry %s not found for txn %s",
					txn.ledger_entry_id,
					txn.pswitch_txn_id,
				)
			elif gl_amount != txn.amount_cents:
				diff = abs(gl_amount - txn.amount_cents)
				breaks += 1
				total_break_cents += diff
				log.warning(
					"pswitch_adapter: reconcile break: txn %s "
					"amount=%dc GL amount=%dc diff=%dc",
					txn.pswitch_txn_id,
					txn.amount_cents,
					gl_amount,
					diff,
				)
			else:
				matched += 1

		# Mark file RECONCILED if no breaks
		if breaks == 0 and sf.status == "POSTED":
			sf.status = "RECONCILED"
			session.flush()

		return {
			"matched": matched,
			"breaks": breaks,
			"total_break_cents": total_break_cents,
			"settlement_file_id": settlement_file_id,
		}

	# ------------------------------------------------------------------
	# Private event emitters
	# ------------------------------------------------------------------

	def _emit_authorized(
		self,
		txn: CardTransaction,
		*,
		account_number: str,
		hold_id: str,
		correlation_id: str,
	) -> None:
		try:
			emit_event(
				CardAuthorizedEvent(
					aggregate_id=txn.id,
					aggregate_type="CardTransaction",
					tenant_id=self._tenant_id,
					correlation_id=correlation_id,
					card_transaction_id=txn.id,
					pswitch_txn_id=txn.pswitch_txn_id,
					account_id=str(txn.account_id),
					account_number=account_number,
					card_pan_masked=txn.card_pan_masked,
					card_scheme=txn.card_scheme,
					amount_cents=txn.amount_cents,
					currency_code=txn.currency_code,
					auth_code=txn.auth_code or "",
					hold_id=hold_id,
					merchant_name=txn.merchant_name or "",
					merchant_category_code=txn.merchant_category_code or "",
					terminal_id=txn.terminal_id or "",
				),
				self._session,
			)
		except Exception as exc:
			log.warning("pswitch_adapter: CardAuthorizedEvent emit failed: %s", exc)

	def _emit_declined(
		self,
		txn: CardTransaction,
		*,
		account_number: str,
		decline_reason: str,
		correlation_id: str,
	) -> None:
		try:
			emit_event(
				CardDeclinedEvent(
					aggregate_id=txn.id,
					aggregate_type="CardTransaction",
					tenant_id=self._tenant_id,
					correlation_id=correlation_id,
					card_transaction_id=txn.id,
					pswitch_txn_id=txn.pswitch_txn_id,
					account_id=str(txn.account_id),
					account_number=account_number,
					card_pan_masked=txn.card_pan_masked,
					card_scheme=txn.card_scheme,
					amount_cents=txn.amount_cents,
					currency_code=txn.currency_code,
					response_code=txn.response_code,
					decline_reason=decline_reason,
					merchant_name=txn.merchant_name or "",
					merchant_category_code=txn.merchant_category_code or "",
					terminal_id=txn.terminal_id or "",
				),
				self._session,
			)
		except Exception as exc:
			log.warning("pswitch_adapter: CardDeclinedEvent emit failed: %s", exc)

	# ------------------------------------------------------------------
	# Private resolution helpers
	# ------------------------------------------------------------------

	def _resolve_account_id(self, account_number: str) -> str | None:
		"""Resolve an account_number string to the Account.id UUID.

		Non-fatal — returns None if the account can't be found.
		"""
		try:
			from pgappforge.plugins.fintech.core_banking.models import Account
			row = (
				self._session.execute(
					sa.select(Account.id).where(
						Account.account_number == account_number,
						Account.tenant_id == self._tenant_id,
					)
				)
				.one_or_none()
			)
			return str(row[0]) if row else None
		except Exception as exc:
			log.warning("pswitch_adapter: account_id resolution failed: %s", exc)
			return None

	def _resolve_gl_entry_amount(self, ledger_entry_id: str) -> int | None:
		"""Load the debit_cents from a LedgerEntry by id.

		Returns None if the entry is not found or the GL module is unavailable.
		"""
		try:
			from pgappforge.plugins.fintech.core_banking.models import LedgerEntry
			row = (
				self._session.execute(
					sa.select(LedgerEntry.debit_cents).where(
						LedgerEntry.id == ledger_entry_id,
					)
				)
				.one_or_none()
			)
			return int(row[0]) if row else None
		except Exception as exc:
			log.warning("pswitch_adapter: GL entry amount resolution failed: %s", exc)
			return None
