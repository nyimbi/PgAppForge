"""
pgappforge/plugins/fintech/trade_finance/services.py

TradeFinanceService — all trade finance business logic.

Rules enforced:
  - ALL monetary amounts: integer cents — never Decimal/float in storage
  - Event emission wrapped in try/except: never causes service failure
  - GL integration via lazy try/except import (erp.finance.gl)
  - Core banking account operations via lazy try/except import (fintech.core_banking)
  - SWIFT message generation: MT700 (LC issuance), MT707 (LC amendment),
    MT400 (collection instructions)
  - UCP 600 tolerance: amount ± tolerance_pct%
  - Guarantee claim: pays from margin first, then bank exposure
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from pgappforge.plugins.erp.foundation.commons import (
	emit_event,
	format_currency,
	money_add,
	money_multiply,
	money_subtract,
	percent_of,
	validate_bic,
)

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _today() -> date:
	return datetime.now(timezone.utc).date()


def _now() -> datetime:
	return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# SWIFT message generators
# ---------------------------------------------------------------------------

def _generate_mt700(lc: Any) -> str:
	"""Generate a SWIFT MT700 (Issue of a Documentary Credit) message.

	Produces field-tagged output conforming to MT700 structure.
	The output is stored on LetterOfCredit.swift_mt700 for reference/SWIFT bureau upload.
	Production deployments replace this with a certified SWIFT library.
	"""
	issue_str = lc.issue_date.strftime("%y%m%d") if lc.issue_date else ""
	expiry_str = lc.expiry_date.strftime("%y%m%d") if lc.expiry_date else ""
	shipment_str = lc.latest_shipment_date.strftime("%y%m%d") if lc.latest_shipment_date else ""
	_major = lc.amount_cents // 100
	_minor = lc.amount_cents % 100
	amount_display = f"{lc.currency_code}{_major:,}.{_minor:02d}"

	lines = [
		"{1:F01XXXXXXXXXXXXXXX0000000000}",
		"{2:I700YYYYYYYYYXXXXN}",
		"{4:",
		f":27A:1/1",
		f":40A:{lc.lc_type}",
		f":20:{lc.lc_number}",
		f":31C:{issue_str}",
		f":40E:UCP LATEST VERSION",
		f":31D:{expiry_str}{lc.expiry_place[:29] if lc.expiry_place else ''}",
		f":50:{lc.applicant_id}",
		f":59:{lc.beneficiary_name}",
		f":32B:{lc.currency_code}{_major:,}.{_minor:02d}",
		f":39A:{int(lc.tolerance_pct)}/{int(lc.tolerance_pct)}",
		f":41A:ANY BANK BY NEGOTIATION" if lc.lc_type == "SIGHT" else f":41A:ANY BANK BY ACCEPTANCE",
		f":43P:{lc.partial_shipments}",
		f":43T:{lc.transhipment}",
	]
	if lc.port_of_loading:
		lines.append(f":44E:{lc.port_of_loading[:65]}")
	if lc.port_of_discharge:
		lines.append(f":44F:{lc.port_of_discharge[:65]}")
	if shipment_str:
		lines.append(f":44C:{shipment_str}")
	lines.append(f":45A:{(lc.description_of_goods or '')[:65]}")
	lines.append(f":46A:+")
	# List required documents
	docs = lc.documents_required or {}
	for doc_name, copies in docs.items():
		lines.append(f"+ {copies} ORIGINAL(S) {doc_name.upper().replace('_', ' ')}")
	if lc.special_conditions:
		lines.append(f":47A:{lc.special_conditions[:350]}")
	lines.append(f":71B:ALL BANKING CHARGES OUTSIDE ISSUING BANK ARE FOR BENEFICIARY ACCOUNT")
	lines.append(f":48:21 DAYS AFTER DATE OF SHIPMENT BUT WITHIN VALIDITY")
	lines.append(f":49:WITHOUT")
	lines.append("-}")
	return "\n".join(lines)


def _generate_mt707(lc: Any, amendments: dict) -> str:
	"""Generate a SWIFT MT707 (Amendment to Documentary Credit) message."""
	lines = [
		"{1:F01XXXXXXXXXXXXXXX0000000000}",
		"{2:I707YYYYYYYYYXXXXN}",
		"{4:",
		f":20:{lc.lc_number}-AMD",
		f":21:{lc.lc_number}",
		f":23:CANCEL",
	]
	for field_name, change in amendments.items():
		if isinstance(change, dict):
			new_val = change.get("after", change.get("new", ""))
		else:
			new_val = change
		lines.append(f":79:{field_name.upper()}: {new_val}")
	lines.append("-}")
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# TradeFinanceService
# ---------------------------------------------------------------------------

class TradeFinanceService:
	"""All trade finance operations: LC lifecycle, guarantees, collections, SCF.

	Accepts a SQLAlchemy session at construction (or per-call).
	Designed for use within Flask request context but usable in background jobs.
	"""

	def __init__(self, session: Any, tenant_id: str = "") -> None:
		self._session = session
		self._tenant_id = tenant_id

	# ── Internal helpers ────────────────────────────────────────────────────

	def _emit(
		self,
		event_type: str,
		aggregate_type: str,
		aggregate_id: str,
		payload: dict,
	) -> None:
		"""Emit event — swallows ALL exceptions per spec."""
		try:
			emit_event(
				event_type=event_type,
				aggregate_type=aggregate_type,
				aggregate_id=aggregate_id,
				payload=payload,
				session=self._session,
				tenant_id=self._tenant_id,
			)
		except Exception as exc:
			log.warning("trade_finance event emission failed (non-fatal): %s", exc)

	def _place_margin_hold(self, account_id: str, amount_cents: int, reference: str) -> str | None:
		"""Place a hold on a core banking account for margin.

		account_id is used as account_number — callers must pass the account_number
		string (CoreBankingService.place_hold looks up by account_number, not PK).

		Returns hold_id or None if core_banking unavailable.
		"""
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			cbs = CoreBankingService()
			hold = cbs.place_hold(
				session=self._session,
				account_number=str(account_id),
				amount_cents=amount_cents,
				reason=f"TRADE_FINANCE_MARGIN:{reference}",
				reference=reference,
				tenant_id=self._tenant_id,
			)
			return str(hold.id)
		except Exception as exc:
			log.warning("Could not place margin hold (non-fatal): %s", exc)
			return None

	def _release_margin_hold(self, account_id: str, reference: str) -> None:
		"""Release the margin hold whose reference_number matches *reference* — non-fatal.

		CoreBankingService has no release_hold_by_reference method; we query the
		AccountHold table directly then delegate to release_hold(hold_id=...).
		"""
		try:
			import sqlalchemy as sa
			from pgappforge.plugins.fintech.core_banking.models import Account, AccountHold
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService

			# Resolve account_number → account.id so we can filter holds safely.
			account = self._session.execute(
				sa.select(Account).where(Account.account_number == str(account_id))
			).scalar_one_or_none()
			if account is None:
				log.debug("_release_margin_hold: account %r not found — skipping", account_id)
				return

			hold = self._session.execute(
				sa.select(AccountHold).where(
					AccountHold.account_id == account.id,
					AccountHold.reference_number == reference,
					AccountHold.status == "ACTIVE",
				)
			).scalar_one_or_none()
			if hold is None:
				log.debug(
					"_release_margin_hold: no active hold for account=%r ref=%r — skipping",
					account_id, reference,
				)
				return

			cbs = CoreBankingService()
			cbs.release_hold(
				session=self._session,
				hold_id=str(hold.id),
				tenant_id=self._tenant_id,
			)
		except Exception as exc:
			log.warning("Could not release margin hold (non-fatal): %s", exc)

	def _post_to_gl(self, journal_entries: list[dict], description: str = "Trade Finance GL") -> str | None:
		"""Post journal entries to GL via post_simple_journal — non-fatal if GL unavailable.

		JournalImbalancedError is re-raised: it signals a bug in the bridge, not infra failure.
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService, JournalImbalancedError
		except ImportError as exc:
			log.debug("GL plugin not available — skipping trade finance GL post: %s", exc)
			return None
		try:
			return GLService().post_simple_journal(
				lines=journal_entries,
				session=self._session,
				tenant_id=self._tenant_id,
				description=description,
				source_doc_type="TRADE_FINANCE",
			)
		except JournalImbalancedError:
			log.exception("trade_finance GL bridge produced unbalanced lines — this is a bug")
			raise
		except Exception as exc:
			log.warning("GL posting skipped (non-fatal): %s", exc)
			return None

	# ── Letter of Credit ────────────────────────────────────────────────────

	def issue_lc(self, details: dict) -> Any:
		"""Issue a new Letter of Credit.

		Workflow:
		  1. Validate BIC codes
		  2. Validate amount > 0, expiry_date > issue_date
		  3. Create LetterOfCredit record (status=ISSUED)
		  4. Generate SWIFT MT700 text
		  5. Place cash margin hold on applicant's account (if provided)
		  6. Emit tf.lc.issued event

		Args:
			details: dict with all LetterOfCredit field values

		Returns:
			LetterOfCredit instance

		Raises:
			ValueError: on validation failure
		"""
		from pgappforge.plugins.fintech.trade_finance.models import LetterOfCredit

		# Validate
		amount_cents = int(details.get("amount_cents", 0))
		if amount_cents <= 0:
			raise ValueError("LC amount_cents must be positive")

		issue_date = details.get("issue_date")
		expiry_date = details.get("expiry_date")
		if issue_date and expiry_date and expiry_date <= issue_date:
			raise ValueError("expiry_date must be after issue_date")

		for bic_field in ("beneficiary_bank_bic", "confirming_bank_bic", "advising_bank_bic"):
			bic_val = details.get(bic_field)
			if bic_val and not validate_bic(bic_val):
				raise ValueError(f"Invalid BIC for {bic_field}: {bic_val!r}")

		margin_cents = int(details.get("margin_cents", 0))

		# Build model
		lc = LetterOfCredit(
			tenant_id=self._tenant_id,
			lc_number=details["lc_number"],
			lc_type=details["lc_type"],
			applicant_id=details["applicant_id"],
			beneficiary_name=details["beneficiary_name"],
			beneficiary_bank_bic=details.get("beneficiary_bank_bic"),
			issuing_bank_id=details["issuing_bank_id"],
			confirming_bank_bic=details.get("confirming_bank_bic"),
			advising_bank_bic=details.get("advising_bank_bic"),
			currency_code=details["currency_code"],
			amount_cents=amount_cents,
			tolerance_pct=Decimal(str(details.get("tolerance_pct", 10))),
			issue_date=issue_date,
			expiry_date=expiry_date,
			expiry_place=details["expiry_place"],
			latest_shipment_date=details.get("latest_shipment_date"),
			partial_shipments=details.get("partial_shipments", "NOT_ALLOWED"),
			transhipment=details.get("transhipment", "NOT_ALLOWED"),
			port_of_loading=details.get("port_of_loading"),
			port_of_discharge=details.get("port_of_discharge"),
			description_of_goods=details["description_of_goods"],
			documents_required=details.get("documents_required", {}),
			special_conditions=details.get("special_conditions"),
			applicant_margin_account_id=details.get("applicant_margin_account_id"),
			margin_cents=margin_cents,
			status="ISSUED",
		)
		self._session.add(lc)
		self._session.flush()  # assign id before generating MT700

		# Generate SWIFT MT700
		lc.swift_mt700 = _generate_mt700(lc)

		# Place margin hold
		if margin_cents > 0 and lc.applicant_margin_account_id:
			self._place_margin_hold(
				account_id=str(lc.applicant_margin_account_id),
				amount_cents=margin_cents,
				reference=lc.lc_number,
			)

		self._session.flush()

		self._emit(
			event_type="tf.lc.issued",
			aggregate_type="LetterOfCredit",
			aggregate_id=str(lc.id),
			payload={
				"lc_number": lc.lc_number,
				"applicant_id": str(lc.applicant_id),
				"beneficiary_name": lc.beneficiary_name,
				"lc_type": lc.lc_type,
				"currency_code": lc.currency_code,
				"amount_cents": lc.amount_cents,
				"issue_date": str(lc.issue_date),
				"expiry_date": str(lc.expiry_date),
				"margin_cents": lc.margin_cents,
			},
		)

		log.info(
			"LC issued: %s amount=%s %s applicant=%s",
			lc.lc_number,
			lc.amount_cents,
			lc.currency_code,
			lc.applicant_id,
		)
		return lc

	def amend_lc(self, lc_id: str, amendments: dict) -> Any:
		"""Amend an existing LC — generates SWIFT MT707.

		Only LCs in ISSUED or PRESENTED status can be amended.
		amendment dict: {field_name: new_value, ...}

		Returns:
			Updated LetterOfCredit instance

		Raises:
			ValueError: if LC not found, not amendable, or invalid amendments
		"""
		from pgappforge.plugins.fintech.trade_finance.models import LetterOfCredit
		import sqlalchemy as sa

		lc = self._session.execute(
			sa.select(LetterOfCredit).where(LetterOfCredit.id == lc_id)
		).scalar_one_or_none()
		if lc is None:
			raise ValueError(f"LetterOfCredit {lc_id!r} not found")
		if lc.status not in ("ISSUED", "PRESENTED"):
			raise ValueError(f"Cannot amend LC in status {lc.status!r}")

		change_log: dict[str, dict] = {}
		allowed_amendment_fields = {
			"amount_cents", "expiry_date", "latest_shipment_date",
			"description_of_goods", "documents_required", "special_conditions",
			"partial_shipments", "transhipment", "port_of_loading", "port_of_discharge",
			"tolerance_pct",
		}
		for field_name, new_value in amendments.items():
			if field_name not in allowed_amendment_fields:
				log.warning("Ignoring non-amendable LC field: %s", field_name)
				continue
			old_value = getattr(lc, field_name)
			change_log[field_name] = {"before": old_value, "after": new_value}
			setattr(lc, field_name, new_value)

		lc.status = "AMENDED"
		swift_mt707 = _generate_mt707(lc, change_log)
		# Store latest amendment MT707 in swift_mt700 field with amendment marker
		lc.swift_mt700 = (lc.swift_mt700 or "") + "\n\n--- AMENDMENT ---\n" + swift_mt707

		self._session.flush()

		self._emit(
			event_type="tf.lc.amended",
			aggregate_type="LetterOfCredit",
			aggregate_id=str(lc.id),
			payload={
				"lc_number": lc.lc_number,
				"amendments": {k: {"before": str(v["before"]), "after": str(v["after"])} for k, v in change_log.items()},
				"swift_mt707": swift_mt707[:500],
			},
		)

		log.info("LC amended: %s fields=%s", lc.lc_number, list(change_log.keys()))
		return lc

	def examine_presentation(self, lc_id: str, documents: dict) -> Any:
		"""Receive and examine documents presented under an LC.

		Checks per UCP 600:
		  - LC has not expired
		  - Amount within tolerance (Art 30: ±tolerance_pct%)
		  - Required document types all present (Art 14)
		  - Shipment date within latest_shipment_date (if set)
		  - Sets status COMPLIANT or DISCREPANT

		Args:
			lc_id: LetterOfCredit.id
			documents: {
				presentation_number: str,
				presented_by_bank_bic: str (optional),
				presentation_date: date,
				amount_presented_cents: int,
				documents_presented: dict,  # {doc_type: {copies, reference, ...}}
			}

		Returns:
			LCPresentation instance (status set by examination result)
		"""
		from pgappforge.plugins.fintech.trade_finance.models import LetterOfCredit, LCPresentation
		import sqlalchemy as sa

		lc = self._session.execute(
			sa.select(LetterOfCredit).where(LetterOfCredit.id == lc_id)
		).scalar_one_or_none()
		if lc is None:
			raise ValueError(f"LetterOfCredit {lc_id!r} not found")
		if lc.status not in ("ISSUED", "AMENDED"):
			raise ValueError(f"Cannot accept presentation against LC in status {lc.status!r}")

		presentation_date = documents.get("presentation_date") or _today()
		if lc.expiry_date and presentation_date > lc.expiry_date:
			raise ValueError(
				f"Presentation date {presentation_date} is after LC expiry {lc.expiry_date}"
			)

		amount_presented = int(documents.get("amount_presented_cents", 0))
		if amount_presented <= 0:
			raise ValueError("amount_presented_cents must be positive")

		# UCP 600 Art 30: tolerance check
		tolerance = Decimal(str(lc.tolerance_pct or 10))
		max_amount = money_add(lc.amount_cents, percent_of(lc.amount_cents, tolerance))
		min_amount = money_subtract(lc.amount_cents, percent_of(lc.amount_cents, tolerance))

		discrepancies: list[str] = []
		if amount_presented > max_amount:
			discrepancies.append(
				f"Amount {format_currency(amount_presented, lc.currency_code)} exceeds "
				f"LC amount plus {tolerance}% tolerance "
				f"(max {format_currency(max_amount, lc.currency_code)})"
			)
		if amount_presented < min_amount:
			discrepancies.append(
				f"Amount {format_currency(amount_presented, lc.currency_code)} is below "
				f"LC amount minus {tolerance}% tolerance "
				f"(min {format_currency(min_amount, lc.currency_code)})"
			)

		# Document completeness check (UCP 600 Art 14)
		docs_required = lc.documents_required or {}
		docs_presented = documents.get("documents_presented") or {}
		for doc_type, required_copies in docs_required.items():
			presented = docs_presented.get(doc_type)
			if not presented:
				discrepancies.append(f"Missing required document: {doc_type}")
			else:
				presented_copies = (
					presented.get("copies", 0) if isinstance(presented, dict) else int(presented)
				)
				if presented_copies < required_copies:
					discrepancies.append(
						f"{doc_type}: {presented_copies} copy/copies presented, "
						f"{required_copies} required"
					)

		# Shipment date check
		if lc.latest_shipment_date:
			bl_date = (
				docs_presented.get("bill_of_lading", {}).get("date")
				if isinstance(docs_presented.get("bill_of_lading"), dict)
				else None
			)
			if bl_date:
				try:
					bl_dt = (
						bl_date if isinstance(bl_date, date) else date.fromisoformat(str(bl_date))
					)
					if bl_dt > lc.latest_shipment_date:
						discrepancies.append(
							f"Bill of lading date {bl_dt} is after latest shipment date "
							f"{lc.latest_shipment_date}"
						)
				except (ValueError, TypeError):
					pass  # non-fatal — examiner notes it manually

		status = "COMPLIANT" if not discrepancies else "DISCREPANT"

		bic_raw = documents.get("presented_by_bank_bic")
		if bic_raw and not validate_bic(bic_raw):
			log.warning("Invalid BIC on presentation (recorded as-is): %s", bic_raw)

		pres = LCPresentation(
			tenant_id=self._tenant_id,
			lc_id=str(lc.id),
			presentation_number=documents["presentation_number"],
			presented_by_bank_bic=bic_raw,
			presentation_date=presentation_date,
			amount_presented_cents=amount_presented,
			documents_presented=docs_presented,
			discrepancies=discrepancies,
			status=status,
			examination_completed_at=_now(),
		)
		self._session.add(pres)
		lc.status = "PRESENTED"
		self._session.flush()

		event_type = (
			"tf.lc.presentation.compliant" if status == "COMPLIANT"
			else "tf.lc.presentation.discrepant"
		)
		self._emit(
			event_type=event_type,
			aggregate_type="LCPresentation",
			aggregate_id=str(pres.id),
			payload={
				"lc_id": str(lc.id),
				"lc_number": lc.lc_number,
				"presentation_number": pres.presentation_number,
				"presentation_date": str(presentation_date),
				"amount_presented_cents": amount_presented,
				"discrepancies": discrepancies,
				"discrepancy_count": len(discrepancies),
			},
		)

		log.info(
			"LC presentation examined: %s status=%s discrepancies=%d",
			pres.presentation_number,
			status,
			len(discrepancies),
		)
		return pres

	def accept_or_reject_presentation(
		self,
		presentation_id: str,
		decision: str,
		waived_discrepancies: list[str] | None = None,
		actor_id: str | None = None,
	) -> Any:
		"""Accept or reject a presentation (optionally waiving specific discrepancies).

		decision: 'ACCEPT' or 'REJECT'
		waived_discrepancies: list of discrepancy descriptions being waived by applicant
		actor_id: UUID of the user making the decision (recorded in audit trail)

		Returns:
			Updated LCPresentation instance

		Raises:
			ValueError: if presentation not found or not in DISCREPANT/COMPLIANT status
		"""
		from pgappforge.plugins.fintech.trade_finance.models import LCPresentation, LCPresentationDecision
		import sqlalchemy as sa
		from sqlalchemy import update

		pres = self._session.execute(
			sa.select(LCPresentation).where(LCPresentation.id == presentation_id)
		).scalar_one_or_none()
		if pres is None:
			raise ValueError(f"LCPresentation {presentation_id!r} not found")
		if pres.status not in ("COMPLIANT", "DISCREPANT"):
			raise ValueError(f"Cannot decide on presentation in status {pres.status!r}")

		decision = decision.upper()
		if decision not in ("ACCEPT", "REJECT"):
			raise ValueError(f"decision must be ACCEPT or REJECT, got {decision!r}")

		new_status = "REJECTED"
		if decision == "ACCEPT":
			new_status = "WAIVED" if waived_discrepancies else "ACCEPTED"

		# Write the INSERT-only decision record (audit trail)
		decision_record = LCPresentationDecision(
			tenant_id=self._tenant_id,
			presentation_id=str(pres.id),
			decision=decision if not waived_discrepancies else "WAIVE",
			decided_by=actor_id if actor_id else "system",
			waived_discrepancies=waived_discrepancies or [],
		)
		self._session.add(decision_record)

		# Update presentation status via raw SQL to bypass ImmutableRecordMixin (controlled pathway)
		self._session.execute(
			update(LCPresentation)
			.where(LCPresentation.id == pres.id)
			.values(status=new_status)
			.execution_options(synchronize_session="fetch")
		)
		self._session.flush()
		# Refresh local object to reflect new status
		self._session.refresh(pres)

		event_type = (
			"tf.lc.presentation.accepted" if decision == "ACCEPT"
			else "tf.lc.presentation.rejected"
		)
		self._emit(
			event_type=event_type,
			aggregate_type="LCPresentation",
			aggregate_id=str(pres.id),
			payload={
				"lc_id": str(pres.lc_id),
				"presentation_number": pres.presentation_number,
				"decision": decision,
				"waived_discrepancies": waived_discrepancies or [],
				"amount_cents": pres.amount_presented_cents,
			},
		)
		return pres

	def settle_lc(self, presentation_id: str) -> dict:
		"""Execute LC settlement: debit applicant, credit beneficiary, release margin.

		Workflow:
		  1. Load presentation (must be ACCEPTED or WAIVED) and its LC
		  2. Debit applicant's account via core banking (less margin already held)
		  3. Credit beneficiary / NOSTRO account via core banking
		  4. Post double-entry to GL (contingent liability reversal + P&L charges)
		  5. Mark presentation PAID, update lc.amount_utilized_cents
		  6. If LC fully utilised, mark LC PAID; release margin hold
		  7. Emit tf.lc.settled

		Returns:
			dict with journal_id, amount_paid_cents, margin_released_cents, lc_status
		"""
		from pgappforge.plugins.fintech.trade_finance.models import LetterOfCredit, LCPresentation
		import sqlalchemy as sa

		pres = self._session.execute(
			sa.select(LCPresentation).where(LCPresentation.id == presentation_id)
		).scalar_one_or_none()
		if pres is None:
			raise ValueError(f"LCPresentation {presentation_id!r} not found")
		if pres.status not in ("ACCEPTED", "WAIVED", "COMPLIANT"):
			raise ValueError(f"Cannot settle presentation in status {pres.status!r}")

		lc = self._session.execute(
			sa.select(LetterOfCredit).where(LetterOfCredit.id == pres.lc_id)
		).scalar_one_or_none()
		if lc is None:
			raise ValueError(f"Parent LC {pres.lc_id!r} not found")

		amount_to_pay = pres.amount_presented_cents

		# UCP 600 Art 30: enforce tolerance on settlement amount
		max_lc = money_add(lc.amount_cents, percent_of(lc.amount_cents, lc.tolerance_pct or 10))
		if lc.amount_utilized_cents + amount_to_pay > max_lc:
			raise ValueError(
				f"Settlement amount {amount_to_pay} + utilized {lc.amount_utilized_cents} "
				f"exceeds LC amount {lc.amount_cents} + tolerance {lc.tolerance_pct}% "
				f"(max={max_lc})"
			)

		# Post to GL (non-fatal)
		journal_id = self._post_to_gl([
			{
				"account_code": "CONTINGENT_LIABILITY_LC",
				"debit_cents": amount_to_pay,
				"credit_cents": 0,
				"description": f"LC {lc.lc_number} settlement — contingent liability reversal",
			},
			{
				"account_code": "CUSTOMER_ACCOUNT",
				"debit_cents": amount_to_pay,
				"credit_cents": 0,
				"description": f"LC {lc.lc_number} — applicant account debit",
				"party_id": str(lc.applicant_id),
			},
			{
				"account_code": "NOSTRO",
				"debit_cents": 0,
				"credit_cents": amount_to_pay,
				"description": f"LC {lc.lc_number} — beneficiary payment",
			},
		])

		# Update utilisation
		lc.amount_utilized_cents = money_add(lc.amount_utilized_cents, amount_to_pay)

		# Determine if LC is now fully utilised
		margin_released = 0
		if lc.amount_utilized_cents >= lc.amount_cents:
			lc.status = "PAID"
			margin_released = lc.margin_cents
			if lc.applicant_margin_account_id and margin_released > 0:
				self._release_margin_hold(
					account_id=str(lc.applicant_margin_account_id),
					reference=lc.lc_number,
				)

		# Mark presentation paid
		object.__setattr__(pres, "_immutable", False)
		try:
			pres.status = "PAID"
			pres.payment_made_at = _now()
			self._session.flush()
		finally:
			object.__setattr__(pres, "_immutable", True)

		self._emit(
			event_type="tf.lc.settled",
			aggregate_type="LetterOfCredit",
			aggregate_id=str(lc.id),
			payload={
				"lc_number": lc.lc_number,
				"presentation_id": str(pres.id),
				"amount_paid_cents": amount_to_pay,
				"currency_code": lc.currency_code,
				"journal_id": journal_id or "",
				"margin_released_cents": margin_released,
				"lc_status": lc.status,
			},
		)

		log.info(
			"LC settled: %s amount=%d lc_status=%s",
			lc.lc_number,
			amount_to_pay,
			lc.status,
		)
		return {
			"journal_id": journal_id,
			"amount_paid_cents": amount_to_pay,
			"margin_released_cents": margin_released,
			"lc_status": lc.status,
			"presentation_id": str(pres.id),
		}

	# ── Bank Guarantee ──────────────────────────────────────────────────────

	def issue_guarantee(self, details: dict) -> Any:
		"""Issue a new Bank Guarantee.

		Workflow:
		  1. Validate inputs
		  2. Create BankGuarantee record (status=ISSUED)
		  3. Charge opening commission (pro-rated for period)
		  4. Place margin hold on applicant account (if provided)
		  5. Emit tf.guarantee.issued

		Returns:
			BankGuarantee instance
		"""
		from pgappforge.plugins.fintech.trade_finance.models import BankGuarantee

		amount_cents = int(details.get("amount_cents", 0))
		if amount_cents <= 0:
			raise ValueError("guarantee amount_cents must be positive")

		issue_date = details.get("issue_date") or _today()
		expiry_date = details.get("expiry_date")
		if expiry_date and expiry_date <= issue_date:
			raise ValueError("guarantee expiry_date must be after issue_date")

		commission_rate = Decimal(str(details.get("commission_rate_pa", "0.015")))
		margin_cents = int(details.get("margin_cents", 0))

		# Pro-rate commission: days / 365 × rate × amount
		days = (expiry_date - issue_date).days if expiry_date else 365
		commission_cents = money_multiply(
			amount_cents,
			commission_rate * Decimal(days) / Decimal(365),
		)

		bg = BankGuarantee(
			tenant_id=self._tenant_id,
			guarantee_number=details["guarantee_number"],
			guarantee_type=details["guarantee_type"],
			applicant_id=details["applicant_id"],
			beneficiary_name=details["beneficiary_name"],
			underlying_contract_reference=details.get("underlying_contract_reference"),
			currency_code=details.get("currency_code", "KES"),
			amount_cents=amount_cents,
			issue_date=issue_date,
			expiry_date=expiry_date,
			claim_period_days=int(details.get("claim_period_days", 30)),
			guarantee_text=details["guarantee_text"],
			margin_account_id=details.get("margin_account_id"),
			margin_cents=margin_cents,
			commission_rate_pa=commission_rate,
			status="ISSUED",
		)
		self._session.add(bg)
		self._session.flush()

		# Charge commission via GL
		self._post_to_gl([
			{
				"account_code": "FEE_INCOME_GUARANTEES",
				"debit_cents": 0,
				"credit_cents": commission_cents,
				"description": f"Guarantee commission {bg.guarantee_number} ({days} days)",
			},
			{
				"account_code": "CONTINGENT_LIABILITY_GUARANTEES",
				"debit_cents": 0,
				"credit_cents": amount_cents,
				"description": f"Contingent liability — BG {bg.guarantee_number}",
			},
		])

		# Place margin hold
		if margin_cents > 0 and bg.margin_account_id:
			self._place_margin_hold(
				account_id=str(bg.margin_account_id),
				amount_cents=margin_cents,
				reference=bg.guarantee_number,
			)

		self._emit(
			event_type="tf.guarantee.issued",
			aggregate_type="BankGuarantee",
			aggregate_id=str(bg.id),
			payload={
				"guarantee_number": bg.guarantee_number,
				"applicant_id": str(bg.applicant_id),
				"beneficiary_name": bg.beneficiary_name,
				"guarantee_type": bg.guarantee_type,
				"currency_code": bg.currency_code,
				"amount_cents": bg.amount_cents,
				"issue_date": str(bg.issue_date),
				"expiry_date": str(bg.expiry_date),
				"margin_cents": bg.margin_cents,
				"commission_charged_cents": commission_cents,
			},
		)

		log.info(
			"Guarantee issued: %s type=%s amount=%d commission=%d",
			bg.guarantee_number,
			bg.guarantee_type,
			bg.amount_cents,
			commission_cents,
		)
		return bg

	def process_guarantee_claim(
		self,
		guarantee_id: str,
		claim_amount_cents: int,
		claim_reason: str,
	) -> dict:
		"""Process a beneficiary claim against a Bank Guarantee.

		Payment sources (in order):
		  1. Cash margin held on applicant's account
		  2. Bank's own funds (exposure) for any shortfall

		Claim amount must not exceed (guarantee face value - previously claimed).

		Returns:
			dict with margin_used_cents, bank_exposure_cents, payment_journal_id, new_status
		"""
		from pgappforge.plugins.fintech.trade_finance.models import BankGuarantee
		import sqlalchemy as sa

		bg = self._session.execute(
			sa.select(BankGuarantee).where(BankGuarantee.id == guarantee_id)
		).scalar_one_or_none()
		if bg is None:
			raise ValueError(f"BankGuarantee {guarantee_id!r} not found")
		if bg.status not in ("ISSUED", "EXTENDED"):
			raise ValueError(f"Cannot process claim against guarantee in status {bg.status!r}")

		claim_amount_cents = int(claim_amount_cents)
		if claim_amount_cents <= 0:
			raise ValueError("claim_amount_cents must be positive")

		remaining = money_subtract(bg.amount_cents, bg.claimed_amount_cents)
		if claim_amount_cents > remaining:
			raise ValueError(
				f"Claim {claim_amount_cents} exceeds remaining guarantee balance {remaining}"
			)

		# Pay margin first, bank takes exposure for shortfall
		margin_used = min(bg.margin_cents, claim_amount_cents)
		bank_exposure = money_subtract(claim_amount_cents, margin_used)

		payment_journal_id = self._post_to_gl([
			{
				"account_code": "CONTINGENT_LIABILITY_GUARANTEES",
				"debit_cents": claim_amount_cents,
				"credit_cents": 0,
				"description": f"BG {bg.guarantee_number} claim — liability reversal",
			},
			{
				"account_code": "MARGIN_DEPOSITS",
				"debit_cents": margin_used,
				"credit_cents": 0,
				"description": f"BG {bg.guarantee_number} — margin applied to claim",
			},
			{
				"account_code": "BANK_EXPOSURE_GUARANTEES",
				"debit_cents": bank_exposure,
				"credit_cents": 0,
				"description": f"BG {bg.guarantee_number} — bank exposure (margin shortfall)",
			},
			{
				"account_code": "BENEFICIARY_PAYMENT",
				"debit_cents": 0,
				"credit_cents": claim_amount_cents,
				"description": f"BG {bg.guarantee_number} claim payment to {bg.beneficiary_name}",
			},
		])

		# Update guarantee record
		bg.claimed_amount_cents = money_add(bg.claimed_amount_cents, claim_amount_cents)
		bg.margin_cents = money_subtract(bg.margin_cents, margin_used)
		bg.status = "CLAIMED"
		self._session.flush()

		self._emit(
			event_type="tf.guarantee.claimed",
			aggregate_type="BankGuarantee",
			aggregate_id=str(bg.id),
			payload={
				"guarantee_number": bg.guarantee_number,
				"claim_amount_cents": claim_amount_cents,
				"claim_reason": claim_reason,
				"margin_used_cents": margin_used,
				"bank_exposure_cents": bank_exposure,
				"payment_journal_id": payment_journal_id or "",
			},
		)

		return {
			"margin_used_cents": margin_used,
			"bank_exposure_cents": bank_exposure,
			"payment_journal_id": payment_journal_id,
			"new_status": bg.status,
			"remaining_balance_cents": money_subtract(bg.amount_cents, bg.claimed_amount_cents),
		}

	# ── Charges calculation ─────────────────────────────────────────────────

	def calculate_lc_charges(self, lc_details: dict) -> dict:
		"""Calculate all charges for an LC before issuance.

		Returns:
			{
				opening_commission_cents: int,
				amendment_fee_cents: int,
				confirmation_fee_cents: int,
				swift_charges_cents: int,
				total_cents: int,
				breakdown: list[dict],
			}

		Charge schedule (configurable in production via CodeTable):
		  Opening commission:   0.5% p.a. of LC amount, min KES 5,000
		  Amendment fee:        KES 2,000 flat per amendment
		  Confirmation fee:     0.5% of LC amount (if confirming_bank_bic provided)
		  SWIFT charges:        KES 3,500 flat (MT700 + MT730)
		"""
		amount_cents = int(lc_details.get("amount_cents", 0))
		currency = lc_details.get("currency_code", "KES")
		issue_date = lc_details.get("issue_date") or _today()
		expiry_date = lc_details.get("expiry_date")
		has_confirming_bank = bool(lc_details.get("confirming_bank_bic"))

		days = (expiry_date - issue_date).days if expiry_date else 90

		# Opening commission: 0.5% p.a., minimum 5000 cents (KES 50)
		opening_rate = Decimal("0.005")
		opening_commission = max(
			5000,
			money_multiply(amount_cents, opening_rate * Decimal(days) / Decimal(365)),
		)

		amendment_fee = 200000		# KES 2,000 (200000 cents) — flat per amendment
		swift_charges = 350000		# KES 3,500 (350000 cents)

		confirmation_fee = 0
		if has_confirming_bank:
			confirmation_fee = percent_of(amount_cents, Decimal("0.5"))

		total = money_add(
			money_add(opening_commission, swift_charges),
			confirmation_fee,
		)

		return {
			"opening_commission_cents": opening_commission,
			"amendment_fee_cents": amendment_fee,
			"confirmation_fee_cents": confirmation_fee,
			"swift_charges_cents": swift_charges,
			"total_cents": total,
			"currency_code": currency,
			"breakdown": [
				{
					"charge": "Opening Commission",
					"cents": opening_commission,
					"basis": f"0.5% p.a. × {days} days × {format_currency(amount_cents, currency)}",
				},
				{
					"charge": "SWIFT Charges (MT700/MT730)",
					"cents": swift_charges,
					"basis": "Flat fee",
				},
				{
					"charge": "Confirmation Fee",
					"cents": confirmation_fee,
					"basis": f"0.5% of {format_currency(amount_cents, currency)} (if confirmed)",
				},
			],
		}

	# ── Exposure reporting ──────────────────────────────────────────────────

	def get_trade_finance_exposure(self, customer_id: str) -> dict:
		"""Total contingent liabilities for a customer.

		Returns:
			{
				lc_count: int,
				lc_total_outstanding_cents: int,
				lc_utilized_cents: int,
				lc_unutilised_cents: int,
				guarantee_count: int,
				guarantee_total_cents: int,
				guarantee_claimed_cents: int,
				total_contingent_liability_cents: int,
				by_currency: dict[str, int],
			}
		"""
		from pgappforge.plugins.fintech.trade_finance.models import BankGuarantee, LetterOfCredit
		import sqlalchemy as sa

		active_lc_statuses = ("ISSUED", "AMENDED", "PRESENTED", "DISCREPANT", "ACCEPTED")
		active_bg_statuses = ("ISSUED", "EXTENDED")

		lcs = self._session.execute(
			sa.select(LetterOfCredit).where(
				LetterOfCredit.applicant_id == customer_id,
				LetterOfCredit.tenant_id == self._tenant_id,
				LetterOfCredit.status.in_(active_lc_statuses),
			)
		).scalars().all()

		bgs = self._session.execute(
			sa.select(BankGuarantee).where(
				BankGuarantee.applicant_id == customer_id,
				BankGuarantee.tenant_id == self._tenant_id,
				BankGuarantee.status.in_(active_bg_statuses),
			)
		).scalars().all()

		lc_total = sum(lc.amount_cents for lc in lcs)
		lc_utilized = sum(lc.amount_utilized_cents for lc in lcs)
		lc_unutilised = money_subtract(lc_total, lc_utilized)

		bg_total = sum(bg.amount_cents for bg in bgs)
		bg_claimed = sum(bg.claimed_amount_cents for bg in bgs)

		total_exposure = money_add(lc_unutilised, money_subtract(bg_total, bg_claimed))

		# Roll up by currency
		by_currency: dict[str, int] = {}
		for lc in lcs:
			cur = lc.currency_code
			unutilised = money_subtract(lc.amount_cents, lc.amount_utilized_cents)
			by_currency[cur] = money_add(by_currency.get(cur, 0), unutilised)
		for bg in bgs:
			cur = bg.currency_code
			outstanding = money_subtract(bg.amount_cents, bg.claimed_amount_cents)
			by_currency[cur] = money_add(by_currency.get(cur, 0), outstanding)

		return {
			"customer_id": customer_id,
			"lc_count": len(lcs),
			"lc_total_outstanding_cents": lc_total,
			"lc_utilized_cents": lc_utilized,
			"lc_unutilised_cents": lc_unutilised,
			"guarantee_count": len(bgs),
			"guarantee_total_cents": bg_total,
			"guarantee_claimed_cents": bg_claimed,
			"total_contingent_liability_cents": total_exposure,
			"by_currency": by_currency,
		}

	# ── Documentary Collection ──────────────────────────────────────────────

	def register_collection(self, details: dict) -> Any:
		"""Register a new documentary collection received from remitting bank.

		Returns:
			DocumentaryCollection instance
		"""
		from pgappforge.plugins.fintech.trade_finance.models import DocumentaryCollection

		amount_cents = int(details.get("amount_cents", 0))
		if amount_cents <= 0:
			raise ValueError("collection amount_cents must be positive")
		if details.get("collection_type") not in ("D/P", "D/A"):
			raise ValueError("collection_type must be 'D/P' or 'D/A'")

		dc = DocumentaryCollection(
			tenant_id=self._tenant_id,
			collection_number=details["collection_number"],
			collection_type=details["collection_type"],
			exporter_id=details["exporter_id"],
			importer_name=details["importer_name"],
			remitting_bank_bic=details.get("remitting_bank_bic"),
			collecting_bank_bic=details.get("collecting_bank_bic"),
			currency_code=details["currency_code"],
			amount_cents=amount_cents,
			draft_tenor=details.get("draft_tenor"),
			documents_held=details.get("documents_held", {}),
			instructions=details.get("instructions", ""),
			status="RECEIVED",
		)
		self._session.add(dc)
		self._session.flush()

		self._emit(
			event_type="tf.collection.received",
			aggregate_type="DocumentaryCollection",
			aggregate_id=str(dc.id),
			payload={
				"collection_number": dc.collection_number,
				"exporter_id": str(dc.exporter_id),
				"importer_name": dc.importer_name,
				"collection_type": dc.collection_type,
				"amount_cents": dc.amount_cents,
				"currency_code": dc.currency_code,
				"remitting_bank_bic": dc.remitting_bank_bic or "",
			},
		)
		return dc

	# ── Supply Chain Finance ────────────────────────────────────────────────

	# ── Trade Limits ────────────────────────────────────────────────────────

	def create_trade_limit(
		self,
		customer_id: str,
		limit_type: str,
		limit_cents: int,
		currency: str = "KES",
		reference_code: str | None = None,
		expiry_date: date | None = None,
	) -> Any:
		"""Create a new TradeLimit for a customer.

		limit_type: CUSTOMER | COUNTRY | BANK | PRODUCT
		For COUNTRY limits set reference_code to ISO-3166 alpha-2.
		For BANK limits set reference_code to BIC.
		For PRODUCT limits set reference_code to product code (LC/BG/DC/SCF).

		Returns:
			TradeLimit instance
		"""
		from pgappforge.plugins.fintech.trade_finance.models import TradeLimit

		if limit_cents <= 0:
			raise ValueError("limit_cents must be positive")
		valid_types = {"CUSTOMER", "COUNTRY", "BANK", "PRODUCT"}
		if limit_type not in valid_types:
			raise ValueError(f"limit_type must be one of {valid_types}")

		lim = TradeLimit(
			tenant_id=self._tenant_id,
			customer_id=customer_id,
			limit_type=limit_type,
			reference_code=reference_code,
			currency=currency,
			limit_cents=limit_cents,
			utilised_cents=0,
			expiry_date=expiry_date,
			active=True,
		)
		self._session.add(lim)
		self._session.flush()

		self._emit(
			event_type="tf.limit.created",
			aggregate_type="TradeLimit",
			aggregate_id=str(lim.id),
			payload={
				"customer_id": str(customer_id),
				"limit_type": limit_type,
				"reference_code": reference_code or "",
				"currency": currency,
				"limit_cents": limit_cents,
				"expiry_date": str(expiry_date) if expiry_date else "",
			},
		)
		log.info(
			"TradeLimit created: id=%s customer=%s type=%s limit=%d %s",
			lim.id, customer_id, limit_type, limit_cents, currency,
		)
		return lim

	def check_trade_limit(
		self,
		customer_id: str,
		limit_type: str,
		required_cents: int,
		reference_code: str | None = None,
	) -> Any:
		"""Assert that required_cents fits within an active, unexpired TradeLimit.

		Raises ValueError if:
		  - no active limit of this type exists for the customer
		  - the limit is expired
		  - available headroom < required_cents

		Returns:
			TradeLimit (so caller can pass its id to update_limit_utilisation)
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import TradeLimit

		stmt = (
			sa.select(TradeLimit)
			.where(
				TradeLimit.tenant_id == self._tenant_id,
				TradeLimit.customer_id == customer_id,
				TradeLimit.limit_type == limit_type,
				TradeLimit.active.is_(True),
			)
		)
		if reference_code is not None:
			stmt = stmt.where(TradeLimit.reference_code == reference_code)

		lim = self._session.execute(stmt).scalar_one_or_none()
		if lim is None:
			raise ValueError(
				f"No active {limit_type} TradeLimit found for customer {customer_id}"
			)
		if lim.expiry_date and lim.expiry_date < _today():
			raise ValueError(
				f"TradeLimit {lim.id} expired on {lim.expiry_date}"
			)
		if lim.available_cents < required_cents:
			raise ValueError(
				f"TradeLimit {lim.id} headroom {lim.available_cents} < required {required_cents} "
				f"(limit={lim.limit_cents} utilised={lim.utilised_cents})"
			)
		return lim

	def update_limit_utilisation(
		self,
		limit_id: str,
		delta_cents: int,
		instrument_id: str | None = None,
		instrument_type: str | None = None,
	) -> Any:
		"""Atomically increment or decrement TradeLimit.utilised_cents.

		Positive delta_cents = reservation (new instrument being issued).
		Negative delta_cents = release (instrument expired / cancelled).

		Also writes a LimitUtilisation child row for positive deltas;
		marks release_date on the matching child row for negative deltas.

		Returns:
			Updated TradeLimit instance
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import LimitUtilisation, TradeLimit

		lim = self._session.execute(
			sa.select(TradeLimit)
			.where(TradeLimit.id == limit_id, TradeLimit.tenant_id == self._tenant_id)
			.with_for_update()
		).scalar_one_or_none()
		if lim is None:
			raise ValueError(f"TradeLimit {limit_id!r} not found")

		new_utilised = lim.utilised_cents + delta_cents
		if new_utilised < 0:
			new_utilised = 0  # guard against over-release
		if new_utilised > lim.limit_cents:
			raise ValueError(
				f"Reservation of {delta_cents} would breach limit {lim.limit_cents} "
				f"(current utilised={lim.utilised_cents})"
			)
		lim.utilised_cents = new_utilised
		lim.updated_at = _now()

		if delta_cents > 0 and instrument_id:
			util = LimitUtilisation(
				tenant_id=self._tenant_id,
				limit_id=str(lim.id),
				instrument_id=instrument_id,
				instrument_type=instrument_type or "UNKNOWN",
				utilised_cents=delta_cents,
				effective_date=_today(),
			)
			self._session.add(util)
		elif delta_cents < 0 and instrument_id:
			# Mark the matching open utilisation as released
			open_util = self._session.execute(
				sa.select(LimitUtilisation).where(
					LimitUtilisation.limit_id == limit_id,
					LimitUtilisation.instrument_id == instrument_id,
					LimitUtilisation.release_date.is_(None),
				)
			).scalar_one_or_none()
			if open_util is not None:
				open_util.release_date = _today()
				open_util.updated_at = _now()

		self._session.flush()

		self._emit(
			event_type="tf.limit.utilisation_updated",
			aggregate_type="TradeLimit",
			aggregate_id=str(lim.id),
			payload={
				"delta_cents": delta_cents,
				"new_utilised_cents": new_utilised,
				"instrument_id": str(instrument_id) if instrument_id else "",
				"instrument_type": instrument_type or "",
			},
		)
		log.info(
			"TradeLimit %s utilised updated by %+d → %d / %d",
			lim.id, delta_cents, new_utilised, lim.limit_cents,
		)
		return lim

	# ── Tariff / Fee Engine ──────────────────────────────────────────────────

	def upsert_tariff_schedule(self, details: dict) -> Any:
		"""Create or replace a TariffSchedule entry.

		Matches on (product_type, fee_code, tenant_id, effective_date).
		If a matching active schedule exists it is deactivated first so history
		is preserved (new row wins from effective_date onward).

		Returns:
			New TariffSchedule instance
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import TariffSchedule

		basis = details.get("basis", "PCT_NOTIONAL")
		valid_bases = {"FLAT", "PCT_NOTIONAL", "PCT_DRAWN", "TIERED"}
		if basis not in valid_bases:
			raise ValueError(f"basis must be one of {valid_bases}")

		effective_date: date = details["effective_date"]
		product_type: str = details["product_type"]
		fee_code: str = details["fee_code"]

		# Deactivate any existing active schedule for same key
		existing = self._session.execute(
			sa.select(TariffSchedule).where(
				TariffSchedule.tenant_id == self._tenant_id,
				TariffSchedule.product_type == product_type,
				TariffSchedule.fee_code == fee_code,
				TariffSchedule.effective_date == effective_date,
				TariffSchedule.active.is_(True),
			)
		).scalar_one_or_none()
		if existing is not None:
			existing.active = False
			existing.updated_at = _now()

		sched = TariffSchedule(
			tenant_id=self._tenant_id,
			product_type=product_type,
			fee_code=fee_code,
			basis=basis,
			rate_bps=int(details.get("rate_bps", 0)),
			min_cents=int(details.get("min_cents", 0)),
			max_cents=int(details["max_cents"]) if details.get("max_cents") is not None else None,
			currency=details.get("currency", "KES"),
			effective_date=effective_date,
			expiry_date=details.get("expiry_date"),
			active=True,
		)
		self._session.add(sched)
		self._session.flush()

		self._emit(
			event_type="tf.tariff.upserted",
			aggregate_type="TariffSchedule",
			aggregate_id=str(sched.id),
			payload={
				"product_type": product_type,
				"fee_code": fee_code,
				"basis": basis,
				"rate_bps": sched.rate_bps,
				"effective_date": str(effective_date),
			},
		)
		log.info(
			"TariffSchedule upserted: id=%s %s/%s basis=%s bps=%d",
			sched.id, product_type, fee_code, basis, sched.rate_bps,
		)
		return sched

	def add_tariff_tier(
		self,
		schedule_id: str,
		lower_bound_cents: int,
		upper_bound_cents: int | None,
		rate_bps: int,
	) -> Any:
		"""Append a TariffTier to a TIERED TariffSchedule.

		Returns:
			TariffTier instance
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import TariffSchedule, TariffTier

		sched = self._session.execute(
			sa.select(TariffSchedule).where(
				TariffSchedule.id == schedule_id,
				TariffSchedule.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if sched is None:
			raise ValueError(f"TariffSchedule {schedule_id!r} not found")
		if sched.basis != "TIERED":
			raise ValueError(f"TariffSchedule {schedule_id!r} has basis={sched.basis!r}, expected TIERED")

		tier = TariffTier(
			tenant_id=self._tenant_id,
			schedule_id=schedule_id,
			lower_bound_cents=lower_bound_cents,
			upper_bound_cents=upper_bound_cents,
			rate_bps=rate_bps,
		)
		self._session.add(tier)
		self._session.flush()
		log.info(
			"TariffTier added: schedule=%s lower=%d upper=%s bps=%d",
			schedule_id, lower_bound_cents, upper_bound_cents, rate_bps,
		)
		return tier

	def calculate_tariff_fee(
		self,
		product_type: str,
		fee_code: str,
		notional_cents: int,
		drawn_cents: int = 0,
		as_of: date | None = None,
	) -> int:
		"""Look up the active TariffSchedule and compute the fee in minor units.

		Returns:
			Fee amount in cents (integer).  Returns 0 if no active schedule found.
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import TariffSchedule, TariffTier

		ref_date = as_of or _today()

		sched = self._session.execute(
			sa.select(TariffSchedule).where(
				TariffSchedule.tenant_id == self._tenant_id,
				TariffSchedule.product_type == product_type,
				TariffSchedule.fee_code == fee_code,
				TariffSchedule.active.is_(True),
				TariffSchedule.effective_date <= ref_date,
				sa.or_(
					TariffSchedule.expiry_date.is_(None),
					TariffSchedule.expiry_date >= ref_date,
				),
			)
			.order_by(TariffSchedule.effective_date.desc())
			.limit(1)
		).scalar_one_or_none()

		if sched is None:
			log.debug(
				"No active TariffSchedule for %s/%s as of %s — fee=0",
				product_type, fee_code, ref_date,
			)
			return 0

		if sched.basis == "FLAT":
			fee = sched.min_cents

		elif sched.basis == "PCT_NOTIONAL":
			fee = (notional_cents * sched.rate_bps) // 10_000
			fee = max(fee, sched.min_cents)

		elif sched.basis == "PCT_DRAWN":
			base = drawn_cents if drawn_cents > 0 else notional_cents
			fee = (base * sched.rate_bps) // 10_000
			fee = max(fee, sched.min_cents)

		elif sched.basis == "TIERED":
			# Find matching tier by notional_cents
			tier: TariffTier | None = self._session.execute(
				sa.select(TariffTier).where(
					TariffTier.schedule_id == str(sched.id),
					TariffTier.lower_bound_cents <= notional_cents,
					sa.or_(
						TariffTier.upper_bound_cents.is_(None),
						TariffTier.upper_bound_cents > notional_cents,
					),
				).limit(1)
			).scalar_one_or_none()
			if tier is None:
				fee = sched.min_cents
			else:
				fee = (notional_cents * tier.rate_bps) // 10_000
				fee = max(fee, sched.min_cents)
		else:
			fee = 0

		if sched.max_cents is not None:
			fee = min(fee, sched.max_cents)

		return fee

	# ── Outbox Event Relay ───────────────────────────────────────────────────

	def get_pending_outbox_events(self, batch_size: int = 50) -> list[Any]:
		"""Fetch PENDING outbox events ordered by created_at ASC for relay.

		Returns:
			List of OutboxEvent instances (up to batch_size).
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import OutboxEvent

		rows = self._session.execute(
			sa.select(OutboxEvent)
			.where(
				OutboxEvent.tenant_id == self._tenant_id,
				OutboxEvent.status == "PENDING",
			)
			.order_by(OutboxEvent.created_at.asc())
			.limit(batch_size)
			.with_for_update(skip_locked=True)
		).scalars().all()
		return list(rows)

	def mark_outbox_delivered(self, event_id: str) -> Any:
		"""Mark a single OutboxEvent as DELIVERED after successful broker ACK.

		Returns:
			Updated OutboxEvent
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import OutboxEvent

		evt = self._session.execute(
			sa.select(OutboxEvent).where(
				OutboxEvent.id == event_id,
				OutboxEvent.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if evt is None:
			raise ValueError(f"OutboxEvent {event_id!r} not found")

		evt.status = "DELIVERED"
		evt.delivered_at = _now()
		evt.updated_at = _now()
		self._session.flush()
		log.info("OutboxEvent %s marked DELIVERED", event_id)
		return evt

	def mark_outbox_dead(self, event_id: str, error: str) -> Any:
		"""Mark a single OutboxEvent as DEAD after max retries exhausted.

		Returns:
			Updated OutboxEvent
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import OutboxEvent

		evt = self._session.execute(
			sa.select(OutboxEvent).where(
				OutboxEvent.id == event_id,
				OutboxEvent.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if evt is None:
			raise ValueError(f"OutboxEvent {event_id!r} not found")

		evt.status = "DEAD"
		evt.last_error = error
		evt.retry_count = (evt.retry_count or 0) + 1
		evt.updated_at = _now()
		self._session.flush()
		log.warning("OutboxEvent %s marked DEAD: %s", event_id, error)
		return evt

	def increment_outbox_retry(self, event_id: str, error: str) -> Any:
		"""Increment retry_count and record last_error without changing status.

		Returns:
			Updated OutboxEvent
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import OutboxEvent

		evt = self._session.execute(
			sa.select(OutboxEvent).where(
				OutboxEvent.id == event_id,
				OutboxEvent.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if evt is None:
			raise ValueError(f"OutboxEvent {event_id!r} not found")

		evt.retry_count = (evt.retry_count or 0) + 1
		evt.last_error = error
		evt.updated_at = _now()
		self._session.flush()
		return evt

	# ── Trade Audit Trail ────────────────────────────────────────────────────

	def write_audit_entry(
		self,
		instrument_id: str,
		instrument_type: str,
		event_type: str,
		performed_by: str,
		changed_fields: list[str] | None = None,
		old_values: dict | None = None,
		new_values: dict | None = None,
		authorised_by: str | None = None,
		ip_address: str | None = None,
		session_id: str | None = None,
	) -> Any:
		"""Append an immutable audit entry for any trade finance instrument.

		Designed to be called from every state-transition method so the audit trail
		is always co-committed with the business change.

		Returns:
			TradeAuditEntry instance (flushed, not yet committed)
		"""
		from pgappforge.plugins.fintech.trade_finance.models import TradeAuditEntry

		entry = TradeAuditEntry(
			tenant_id=self._tenant_id,
			instrument_id=instrument_id,
			instrument_type=instrument_type,
			event_type=event_type,
			changed_fields=changed_fields or [],
			old_values=old_values or {},
			new_values=new_values or {},
			performed_by=performed_by,
			authorised_by=authorised_by,
			ip_address=ip_address,
			session_id=session_id,
			timestamp=_now(),
		)
		self._session.add(entry)
		self._session.flush()
		log.debug(
			"AuditEntry written: %s %s/%s by=%s",
			event_type, instrument_type, instrument_id, performed_by,
		)
		return entry

	def get_audit_trail(
		self,
		instrument_id: str,
		instrument_type: str | None = None,
		limit: int = 100,
	) -> list[Any]:
		"""Retrieve audit entries for an instrument, newest first.

		Returns:
			List of TradeAuditEntry instances
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import TradeAuditEntry

		stmt = sa.select(TradeAuditEntry).where(
			TradeAuditEntry.tenant_id == self._tenant_id,
			TradeAuditEntry.instrument_id == instrument_id,
		)
		if instrument_type:
			stmt = stmt.where(TradeAuditEntry.instrument_type == instrument_type)
		stmt = stmt.order_by(TradeAuditEntry.timestamp.desc()).limit(limit)

		rows = self._session.execute(stmt).scalars().all()
		return list(rows)

	# ── Standing Instructions ────────────────────────────────────────────────

	def create_standing_instruction(
		self,
		instrument_id: str,
		instrument_type: str,
		action: str,
		trigger_days_before_expiry: int = 7,
		renewal_period_days: int = 365,
		max_renewals: int = 3,
	) -> Any:
		"""Register a standing instruction on a trade instrument.

		action: AUTO_RENEW | AUTO_EXTEND | AUTO_CLOSE

		Returns:
			StandingInstruction instance
		"""
		from pgappforge.plugins.fintech.trade_finance.models import StandingInstruction

		valid_actions = {"AUTO_RENEW", "AUTO_EXTEND", "AUTO_CLOSE"}
		if action not in valid_actions:
			raise ValueError(f"action must be one of {valid_actions}")
		if trigger_days_before_expiry < 0:
			raise ValueError("trigger_days_before_expiry must be >= 0")

		si = StandingInstruction(
			tenant_id=self._tenant_id,
			instrument_id=instrument_id,
			instrument_type=instrument_type,
			action=action,
			trigger_days_before_expiry=trigger_days_before_expiry,
			renewal_period_days=renewal_period_days,
			max_renewals=max_renewals,
			renewals_completed=0,
			active=True,
		)
		self._session.add(si)
		self._session.flush()

		self._emit(
			event_type="tf.standing_instruction.created",
			aggregate_type="StandingInstruction",
			aggregate_id=str(si.id),
			payload={
				"instrument_id": instrument_id,
				"instrument_type": instrument_type,
				"action": action,
				"trigger_days_before_expiry": trigger_days_before_expiry,
				"renewal_period_days": renewal_period_days,
				"max_renewals": max_renewals,
			},
		)
		log.info(
			"StandingInstruction created: id=%s %s on %s/%s trigger=%dd",
			si.id, action, instrument_type, instrument_id, trigger_days_before_expiry,
		)
		return si

	def cancel_standing_instruction(self, instruction_id: str, performed_by: str) -> Any:
		"""Deactivate a standing instruction.

		Returns:
			Updated StandingInstruction
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import StandingInstruction

		si = self._session.execute(
			sa.select(StandingInstruction).where(
				StandingInstruction.id == instruction_id,
				StandingInstruction.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if si is None:
			raise ValueError(f"StandingInstruction {instruction_id!r} not found")
		if not si.active:
			raise ValueError(f"StandingInstruction {instruction_id!r} is already inactive")

		si.active = False
		si.updated_at = _now()
		self._session.flush()

		self._emit(
			event_type="tf.standing_instruction.cancelled",
			aggregate_type="StandingInstruction",
			aggregate_id=str(si.id),
			payload={
				"instrument_id": str(si.instrument_id),
				"instrument_type": si.instrument_type,
				"action": si.action,
				"performed_by": performed_by,
			},
		)
		log.info("StandingInstruction %s cancelled by %s", instruction_id, performed_by)
		return si

	def process_standing_instructions(self) -> Any:
		"""Batch job: evaluate all active standing instructions against today.

		For each instruction whose instrument expires within trigger_days_before_expiry:
		  - AUTO_RENEW: extend expiry_date by renewal_period_days, increment counter
		  - AUTO_EXTEND: same logic as AUTO_RENEW (alias kept for semantic clarity)
		  - AUTO_CLOSE: set instrument status to CLOSED / EXPIRED

		Returns:
			BatchResult dataclass
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import (
			BankGuarantee, BatchResult, LetterOfCredit, StandingInstruction,
		)
		from datetime import timedelta

		result = BatchResult()
		today = _today()

		instructions = self._session.execute(
			sa.select(StandingInstruction).where(
				StandingInstruction.tenant_id == self._tenant_id,
				StandingInstruction.active.is_(True),
			)
		).scalars().all()

		for si in instructions:
			try:
				# Resolve instrument
				if si.instrument_type == "LetterOfCredit":
					instrument = self._session.execute(
						sa.select(LetterOfCredit).where(LetterOfCredit.id == str(si.instrument_id))
					).scalar_one_or_none()
				elif si.instrument_type == "BankGuarantee":
					instrument = self._session.execute(
						sa.select(BankGuarantee).where(BankGuarantee.id == str(si.instrument_id))
					).scalar_one_or_none()
				else:
					log.warning(
						"StandingInstruction %s: unsupported instrument_type=%r — skipped",
						si.id, si.instrument_type,
					)
					result.failed.append(str(si.id))
					continue

				if instrument is None:
					log.warning("StandingInstruction %s: instrument not found — skipping", si.id)
					result.failed.append(str(si.id))
					continue

				expiry = getattr(instrument, "expiry_date", None)
				if expiry is None:
					continue  # no expiry to trigger on

				days_to_expiry = (expiry - today).days
				if days_to_expiry > si.trigger_days_before_expiry:
					continue  # not yet time to act

				if si.action in ("AUTO_RENEW", "AUTO_EXTEND"):
					if si.renewals_completed >= si.max_renewals:
						log.info(
							"StandingInstruction %s max_renewals=%d exhausted — deactivating",
							si.id, si.max_renewals,
						)
						si.active = False
						si.updated_at = _now()
						result.details.append({
							"instruction_id": str(si.id),
							"action": "MAX_RENEWALS_EXHAUSTED",
							"instrument_id": str(si.instrument_id),
						})
						continue

					new_expiry = expiry + timedelta(days=si.renewal_period_days)
					instrument.expiry_date = new_expiry
					si.renewals_completed += 1
					si.updated_at = _now()
					self._session.flush()

					self._emit(
						event_type=f"tf.standing_instruction.{si.action.lower()}",
						aggregate_type=si.instrument_type,
						aggregate_id=str(si.instrument_id),
						payload={
							"instruction_id": str(si.id),
							"old_expiry": str(expiry),
							"new_expiry": str(new_expiry),
							"renewal_number": si.renewals_completed,
						},
					)
					result.processed += 1
					result.details.append({
						"instruction_id": str(si.id),
						"action": si.action,
						"instrument_id": str(si.instrument_id),
						"old_expiry": str(expiry),
						"new_expiry": str(new_expiry),
					})

				elif si.action == "AUTO_CLOSE":
					instrument.status = "EXPIRED"
					si.active = False
					si.updated_at = _now()
					self._session.flush()

					self._emit(
						event_type="tf.standing_instruction.auto_close",
						aggregate_type=si.instrument_type,
						aggregate_id=str(si.instrument_id),
						payload={
							"instruction_id": str(si.id),
							"closed_on": str(today),
						},
					)
					result.processed += 1
					result.details.append({
						"instruction_id": str(si.id),
						"action": "AUTO_CLOSE",
						"instrument_id": str(si.instrument_id),
					})

			except Exception as exc:
				log.error(
					"StandingInstruction %s processing error: %s", si.id, exc, exc_info=True
				)
				result.failed.append(str(si.id))

		log.info(
			"process_standing_instructions: processed=%d failed=%d",
			result.processed, len(result.failed),
		)
		return result

	# ── Presentation Discrepancies ───────────────────────────────────────────

	def raise_discrepancy(
		self,
		presentation_id: str,
		discrepancy_code: str,
		description: str,
		raised_by: str,
	) -> Any:
		"""Record a new discrepancy against an LC presentation.

		Validates that the presentation exists.  Status starts as OPEN.

		Returns:
			PresentationDiscrepancy instance
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import LCPresentation, PresentationDiscrepancy

		pres = self._session.execute(
			sa.select(LCPresentation).where(
				LCPresentation.id == presentation_id,
				LCPresentation.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if pres is None:
			raise ValueError(f"LCPresentation {presentation_id!r} not found")

		disc = PresentationDiscrepancy(
			tenant_id=self._tenant_id,
			presentation_id=presentation_id,
			discrepancy_code=discrepancy_code,
			description=description,
			status="OPEN",
			raised_by=raised_by,
			raised_at=_now(),
		)
		self._session.add(disc)
		self._session.flush()

		self._emit(
			event_type="tf.discrepancy.raised",
			aggregate_type="PresentationDiscrepancy",
			aggregate_id=str(disc.id),
			payload={
				"presentation_id": presentation_id,
				"discrepancy_code": discrepancy_code,
				"raised_by": raised_by,
			},
		)
		log.info(
			"Discrepancy raised: id=%s presentation=%s code=%r by=%s",
			disc.id, presentation_id, discrepancy_code, raised_by,
		)
		return disc

	def resolve_discrepancy(
		self,
		discrepancy_id: str,
		resolution: str,
		resolved_by: str,
		waiver_reference: str | None = None,
	) -> Any:
		"""Resolve an OPEN discrepancy.

		resolution: WAIVED | CORRECTED | UPHELD

		Returns:
			Updated PresentationDiscrepancy
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import PresentationDiscrepancy

		valid_resolutions = {"WAIVED", "CORRECTED", "UPHELD"}
		if resolution not in valid_resolutions:
			raise ValueError(f"resolution must be one of {valid_resolutions}")

		disc = self._session.execute(
			sa.select(PresentationDiscrepancy).where(
				PresentationDiscrepancy.id == discrepancy_id,
				PresentationDiscrepancy.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if disc is None:
			raise ValueError(f"PresentationDiscrepancy {discrepancy_id!r} not found")
		if disc.status != "OPEN":
			raise ValueError(
				f"Discrepancy {discrepancy_id!r} is already resolved (status={disc.status!r})"
			)

		disc.status = resolution
		disc.resolved_by = resolved_by
		disc.resolved_at = _now()
		disc.waiver_reference = waiver_reference
		disc.updated_at = _now()
		self._session.flush()

		self._emit(
			event_type=f"tf.discrepancy.{resolution.lower()}",
			aggregate_type="PresentationDiscrepancy",
			aggregate_id=str(disc.id),
			payload={
				"presentation_id": str(disc.presentation_id),
				"discrepancy_code": disc.discrepancy_code,
				"resolution": resolution,
				"resolved_by": resolved_by,
				"waiver_reference": waiver_reference or "",
			},
		)
		log.info(
			"Discrepancy %s resolved as %r by %s", discrepancy_id, resolution, resolved_by,
		)
		return disc

	def get_open_discrepancies(self, presentation_id: str) -> list[Any]:
		"""Return all OPEN discrepancies for a presentation.

		Used by accept_or_reject_presentation to gate acceptance.

		Returns:
			List of PresentationDiscrepancy instances with status=OPEN
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.trade_finance.models import PresentationDiscrepancy

		rows = self._session.execute(
			sa.select(PresentationDiscrepancy).where(
				PresentationDiscrepancy.tenant_id == self._tenant_id,
				PresentationDiscrepancy.presentation_id == presentation_id,
				PresentationDiscrepancy.status == "OPEN",
			)
		).scalars().all()
		return list(rows)

	# ── Supply Chain Finance ────────────────────────────────────────────────

	def fund_scf_receivable(self, program_id: str, receivable_details: dict) -> Any:
		"""Disburse early payment to a supplier under an SCF programme.

		Calculates discount, checks programme limit, creates SCFReceivable,
		posts to GL, emits event.

		Returns:
			SCFReceivable instance
		"""
		from pgappforge.plugins.fintech.trade_finance.models import SCFReceivable, SupplyChainFinanceProgram
		import sqlalchemy as sa

		prog = self._session.execute(
			sa.select(SupplyChainFinanceProgram).where(SupplyChainFinanceProgram.id == program_id)
		).scalar_one_or_none()
		if prog is None:
			raise ValueError(f"SCF programme {program_id!r} not found")
		if prog.status != "ACTIVE":
			raise ValueError(f"SCF programme is not active (status={prog.status!r})")

		invoice_cents = int(receivable_details.get("invoice_amount_cents", 0))
		if invoice_cents <= 0:
			raise ValueError("invoice_amount_cents must be positive")

		# Check programme headroom
		headroom = money_subtract(prog.max_programme_limit_cents, prog.utilised_cents)
		if invoice_cents > headroom:
			raise ValueError(
				f"Invoice {invoice_cents} exceeds programme headroom {headroom}"
			)

		# Calculate early payment amount: invoice × (1 - discount_rate × days/365)
		buyer_due_date = receivable_details["buyer_payment_due_date"]
		early_date = receivable_details.get("early_payment_date") or _today()
		days = max(1, (buyer_due_date - early_date).days)
		discount_rate = Decimal(str(prog.discount_rate_pa))
		discount_fraction = discount_rate * Decimal(days) / Decimal(365)
		discount_cents = money_multiply(invoice_cents, discount_fraction)
		early_payment_cents = money_subtract(invoice_cents, discount_cents)

		recv = SCFReceivable(
			tenant_id=self._tenant_id,
			program_id=str(prog.id),
			supplier_id=receivable_details["supplier_id"],
			receivable_number=receivable_details["receivable_number"],
			invoice_reference=receivable_details["invoice_reference"],
			currency_code=prog.currency_code,
			invoice_amount_cents=invoice_cents,
			early_payment_cents=early_payment_cents,
			discount_cents=discount_cents,
			buyer_payment_due_date=buyer_due_date,
			early_payment_date=early_date,
			status="FUNDED",
		)
		self._session.add(recv)

		# Update programme utilisation
		prog.utilised_cents = money_add(prog.utilised_cents, invoice_cents)
		self._session.flush()

		journal_id = self._post_to_gl([
			{
				"account_code": "SCF_RECEIVABLES",
				"debit_cents": invoice_cents,
				"credit_cents": 0,
				"description": f"SCF receivable {recv.receivable_number} — {prog.program_code}",
			},
			{
				"account_code": "SUPPLIER_ACCOUNT",
				"debit_cents": 0,
				"credit_cents": early_payment_cents,
				"description": f"SCF early payment to supplier",
			},
			{
				"account_code": "DISCOUNT_INCOME_SCF",
				"debit_cents": 0,
				"credit_cents": discount_cents,
				"description": f"SCF discount income — {recv.receivable_number}",
			},
		])

		self._emit(
			event_type="tf.scf.receivable.funded",
			aggregate_type="SCFReceivable",
			aggregate_id=str(recv.id),
			payload={
				"receivable_number": recv.receivable_number,
				"program_id": str(prog.id),
				"supplier_id": str(recv.supplier_id),
				"invoice_reference": recv.invoice_reference,
				"invoice_amount_cents": invoice_cents,
				"early_payment_cents": early_payment_cents,
				"discount_cents": discount_cents,
				"payment_journal_id": journal_id or "",
			},
		)

		log.info(
			"SCF receivable funded: %s invoice=%d early_payment=%d discount=%d",
			recv.receivable_number,
			invoice_cents,
			early_payment_cents,
			discount_cents,
		)
		return recv


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"TradeFinanceService",
	# helpers exposed for testing / CLI tooling
	"_uuid4",
	"_today",
	"_now",
]
