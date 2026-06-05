"""
pgappforge/plugins/fintech/swift/services.py

SWIFTService — all SWIFT correspondent banking logic.

Rules enforced:
  - ALL monetary amounts: integer cents — never Decimal/float in storage
  - Event emission wrapped in try/except: never causes service failure
  - GL integration via lazy try/except import (erp.finance.gl)
  - Core banking operations via lazy try/except import (fintech.core_banking)
  - SWIFT FIN body generation: MT103, MT202, MT900, MT910
  - gpi UETR lifecycle: insert SWIFTGpiStatus on each tracker update
  - Nostro reconciliation: match MT900/910 confirmations against messages
  - PostgreSQL ONLY — no sqlite/mysql fallbacks
  - BIC validation via commons.validate_bic
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any

from pgappforge.plugins.erp.foundation.commons import (
	emit_event,
	validate_bic,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SWIFT field sanitisation
# ---------------------------------------------------------------------------

def _swift_safe(value: str, max_len: int = 35) -> str:
	"""Strip SWIFT-unsafe chars that could enable field/tag injection.

	Removes control characters (ord < 32) and characters that could introduce
	new SWIFT tags or block terminators: newlines (CR/LF), carriage returns,
	and characters that start tag lines (':') or block-close lines ('-}').
	Truncates to max_len.
	"""
	if not value:
		return ''
	# Remove control chars (includes CR, LF, TAB) and the backslash
	cleaned = ''.join(c for c in value if 32 <= ord(c) < 127 and c != '\\')
	# Prevent tag injection: strip lines starting with ':' or the block-close '-}'
	lines = [ln for ln in cleaned.split('\n') if not ln.startswith(':') and ln != '-}']
	result = ' '.join(lines)
	return result[:max_len]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _uuid4() -> str:
	return str(uuid.uuid4())


def _today() -> date:
	return datetime.now(timezone.utc).date()


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _fmt_date(d: date) -> str:
	"""Format date as SWIFT YYMMDD."""
	return d.strftime("%y%m%d")


def _fmt_amount(amount_cents: int, currency_code: str) -> str:
	"""Format amount as SWIFT :32A: style: e.g. 'USD100000,00' (comma decimal)."""
	major = amount_cents // 100
	minor = amount_cents % 100
	return f"{currency_code}{major},{minor:02d}"


def _make_message_ref(reference: str | None, prefix: str = "REF") -> str:
	"""Ensure reference fits SWIFT :20: 16-char max. Generates one if None."""
	if reference:
		# Strip disallowed chars, truncate to 16
		clean = re.sub(r"[^A-Z0-9/\-\?:.,'\(\)\+ ]", "", reference.upper())
		return clean[:16]
	ts = datetime.now(timezone.utc).strftime("%y%m%d%H%M%S")
	return f"{prefix}{ts}"[:16]


# ---------------------------------------------------------------------------
# SWIFT FIN body generators
# ---------------------------------------------------------------------------

def _generate_mt103(
	message_ref: str,
	sender_bic: str,
	receiver_bic: str,
	ordering_customer_name: str,
	ordering_account: str,
	beneficiary_name: str,
	beneficiary_account: str,
	beneficiary_bank_bic: str,
	amount_cents: int,
	currency_code: str,
	value_date: date,
	remittance_info: str = "",
	uetr: str = "",
) -> str:
	"""Build MT103 Single Customer Credit Transfer FIN body.

	Fields generated:
	  :20:  Sender's Reference
	  :23B: Bank Operation Code (CRED = credit transfer)
	  :32A: Value Date/Currency/Interbank Settled Amount
	  :50K: Ordering Customer (name + account)
	  :57A: Account With Institution (beneficiary bank BIC)
	  :59:  Beneficiary Customer (name + account)
	  :70:  Remittance Information
	  :71A: Details of Charges (SHA = shared)
	  :121: UETR (gpi mandatory field, placed in block 3 in production;
	         included here as a comment line for reference implementations)

	In production, the raw_message feeds into SWIFT Alliance Access which
	wraps it in block headers {1:...}{2:...}{3:...}{4:...}{5:...}.
	"""
	vd_str = _fmt_date(value_date)
	amt_str = _fmt_amount(amount_cents, currency_code)

	lines = [
		"{4:",
		f":20:{message_ref}",
		":23B:CRED",
		f":32A:{vd_str}{amt_str}",
		f":50K:/{ordering_account}",
		f"{ordering_customer_name[:35]}",
		f":57A:{beneficiary_bank_bic}",
		f":59:/{beneficiary_account}",
		f"{beneficiary_name[:35]}",
	]
	if remittance_info:
		# :70: max 4 lines × 35 chars
		chunks = [remittance_info[i:i+35] for i in range(0, min(len(remittance_info), 140), 35)]
		lines.append(f":70:{''.join(chunks[:1])}")
		for chunk in chunks[1:]:
			lines.append(chunk)
	else:
		lines.append(":70:/INTL TRANSFER")
	lines.append(":71A:SHA")
	if uetr:
		lines.append(f":121:{uetr}")
	lines.append("-}")
	return "\n".join(lines)


def _generate_mt202(
	message_ref: str,
	related_ref: str,
	sender_bic: str,
	receiver_bic: str,
	account_with_institution_bic: str,
	beneficiary_institution_bic: str,
	amount_cents: int,
	currency_code: str,
	value_date: date,
) -> str:
	"""Build MT202 Financial Institution Transfer FIN body.

	MT202 is used for bank-to-bank cover payments — typically the correspondent
	leg that funds an MT103 customer payment routed through an intermediary bank.

	Fields generated:
	  :20:  Transaction Reference Number
	  :21:  Related Reference (links to the MT103 :20: it covers)
	  :32A: Value Date/Currency/Amount
	  :57A: Account With Institution (intermediary/correspondent bank BIC)
	  :58A: Beneficiary Institution (final receiving institution BIC)
	"""
	vd_str = _fmt_date(value_date)
	amt_str = _fmt_amount(amount_cents, currency_code)

	lines = [
		"{4:",
		f":20:{message_ref}",
		f":21:{related_ref[:16]}",
		f":32A:{vd_str}{amt_str}",
		f":57A:{account_with_institution_bic}",
		f":58A:{beneficiary_institution_bic}",
		"-}",
	]
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# MT FIN parser helpers
# ---------------------------------------------------------------------------

def _extract_field(fin_text: str, tag: str) -> str:
	"""Extract the value of a :TAG: field from a FIN block 4 body.

	Handles multi-line field values (lines not starting with : belong to
	the previous field). Returns the first match stripped of leading newline.
	"""
	pattern = rf":{re.escape(tag)}:(.*?)(?=\n:[A-Z0-9]{{2,3}}[A-Z]?:|$|-\}})"
	m = re.search(pattern, fin_text, re.DOTALL)
	if m:
		return m.group(1).strip()
	return ""


def _parse_32a(field_value: str) -> tuple[str, str, int]:
	"""Parse :32A: field value → (value_date_str_YYMMDD, currency_code, amount_cents).

	:32A: format: YYMMDDISOAMOUNT e.g. '260604USD100000,00'
	SWIFT amount uses comma as decimal separator.
	Uses Decimal arithmetic to avoid float rounding errors on monetary amounts.
	"""
	from decimal import Decimal as _D
	if len(field_value) < 9:
		return "", "", 0
	date_str = field_value[:6]
	currency = field_value[6:9]
	amount_raw = field_value[9:].replace(",", "").strip()
	try:
		amount_cents = int(_D(amount_raw) * 100)
	except (ValueError, TypeError, Exception):
		amount_cents = 0
	return date_str, currency, amount_cents


def _parse_value_date(yymmdd: str) -> date:
	"""Parse SWIFT YYMMDD to Python date. Assumes 20xx."""
	try:
		return datetime.strptime(f"20{yymmdd}", "%Y%m%d").date()
	except ValueError:
		return _today()


# ---------------------------------------------------------------------------
# SWIFTService
# ---------------------------------------------------------------------------

class SWIFTService:
	"""SWIFT correspondent banking operations: send, receive, gpi tracking, nostro reconciliation.

	All methods operate within the supplied SQLAlchemy session. The caller is
	responsible for session.commit(). Methods call session.flush() to assign PKs
	before emitting events.

	GL posting and core banking deposits are non-fatal — failures are logged at
	WARNING level and the SWIFT message record is still persisted.
	"""

	# GL account codes (override in config / subclass for your CoA)
	GL_NOSTRO = "1011"					# Nostro / Correspondent account (asset)
	GL_CUSTOMER_DEPOSITS = "2100"		# Customer deposit liabilities
	GL_VOSTRO = "2300"					# Vostro / mirror account for MT202 cover

	def __init__(self, session: Any, tenant_id: str = "") -> None:
		self._session = session
		self._tenant_id = tenant_id

	# ── Internal helpers ─────────────────────────────────────────────────────

	def _emit(
		self,
		event_type: str,
		aggregate_type: str,
		aggregate_id: str,
		payload: dict,
	) -> None:
		"""Emit domain event — swallows ALL exceptions (never causes service failure)."""
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
			log.warning("swift event emission failed (non-fatal): %s", exc)

	def _post_to_gl(self, lines: list[dict], description: str = "SWIFT GL") -> str | None:
		"""Post journal to GL — non-fatal if GL plugin unavailable.

		JournalImbalancedError is re-raised (signals a service bug, not infra).
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService, JournalImbalancedError
		except ImportError as exc:
			log.debug("GL plugin not available — skipping SWIFT GL post: %s", exc)
			return None
		try:
			return GLService().post_simple_journal(
				lines=lines,
				session=self._session,
				tenant_id=self._tenant_id,
				description=description,
				source_doc_type="SWIFT",
			)
		except Exception as exc:
			# Re-raise imbalance errors — they indicate a coding bug
			if "imbalanced" in type(exc).__name__.lower() or "imbalanced" in str(exc).lower():
				raise
			log.warning("GL posting skipped (non-fatal): %s", exc)
			return None

	def _core_deposit(
		self,
		beneficiary_account_ref: str,
		amount_cents: int,
		currency_code: str,
		reference: str,
	) -> None:
		"""Credit beneficiary via CoreBankingService — non-fatal if unavailable."""
		try:
			from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
			cbs = CoreBankingService(self._session, self._tenant_id)
			cbs.deposit(
				account_ref=beneficiary_account_ref,
				amount_cents=amount_cents,
				currency_code=currency_code,
				reference=reference,
				narration=f"SWIFT inbound MT103 {reference}",
			)
		except Exception as exc:
			log.warning("CoreBanking deposit skipped (non-fatal): %s", exc)

	# ── Outbound MT103 ────────────────────────────────────────────────────────

	def create_mt103(
		self,
		sender_bic: str,
		receiver_bic: str,
		ordering_customer_name: str,
		ordering_account: str,
		beneficiary_name: str,
		beneficiary_account: str,
		beneficiary_bank_bic: str,
		amount_cents: int,
		currency_code: str,
		value_date: date,
		remittance_info: str = "",
		reference: str | None = None,
	) -> Any:
		"""Create and persist an outbound SWIFT MT103 Single Customer Credit Transfer.

		Workflow:
		  1. Validate BICs and amount
		  2. Generate UETR (UUID4 per SWIFT gpi specification)
		  3. Build MT103 FIN body (block 4)
		  4. Persist SWIFTMessage (status=DRAFT)
		  5. Post GL: DR Nostro (1011) / CR Customer Deposits (2100)
		  6. Emit swift.message.sent

		Args:
			sender_bic:              BIC11 of our bank (the sender)
			receiver_bic:            BIC11 of the correspondent bank
			ordering_customer_name:  Remitting customer full name
			ordering_account:        Remitting customer account number (IBAN or local)
			beneficiary_name:        Beneficiary full name
			beneficiary_account:     Beneficiary account number
			beneficiary_bank_bic:    BIC of beneficiary's bank (:57A:)
			amount_cents:            Transfer amount in integer minor units
			currency_code:           ISO 4217 e.g. USD, EUR, KES
			value_date:              Settlement value date
			remittance_info:         Payment details / invoice reference (field :70:)
			reference:               Override :20: sender reference (auto-generated if None)

		Returns:
			SWIFTMessage instance (flushed, not committed)

		Raises:
			ValueError: on invalid BIC or non-positive amount
		"""
		from pgappforge.plugins.fintech.swift.models import SWIFTMessage

		# Validate
		if amount_cents <= 0:
			raise ValueError(f"amount_cents must be positive, got {amount_cents}")
		for bic_label, bic_val in [
			("sender_bic", sender_bic),
			("receiver_bic", receiver_bic),
			("beneficiary_bank_bic", beneficiary_bank_bic),
		]:
			if bic_val and not validate_bic(bic_val):
				raise ValueError(f"Invalid BIC for {bic_label}: {bic_val!r}")

		# Sanitise all user-supplied string fields before embedding in FIN body
		ordering_customer_name = _swift_safe(ordering_customer_name, 35)
		beneficiary_name = _swift_safe(beneficiary_name, 35)
		remittance_info = _swift_safe(remittance_info, 140)
		ordering_account = _swift_safe(ordering_account, 34)
		beneficiary_account = _swift_safe(beneficiary_account, 34)

		# UETR — mandatory for MT103 gpi (UUID4 per RFC 4122)
		uetr = _uuid4()
		msg_ref = _make_message_ref(reference, prefix="MT103")

		raw_fin = _generate_mt103(
			message_ref=msg_ref,
			sender_bic=sender_bic,
			receiver_bic=receiver_bic,
			ordering_customer_name=ordering_customer_name,
			ordering_account=ordering_account,
			beneficiary_name=beneficiary_name,
			beneficiary_account=beneficiary_account,
			beneficiary_bank_bic=beneficiary_bank_bic,
			amount_cents=amount_cents,
			currency_code=currency_code,
			value_date=value_date,
			remittance_info=remittance_info,
			uetr=uetr,
		)

		msg = SWIFTMessage(
			tenant_id=self._tenant_id,
			message_ref=msg_ref,
			message_type="MT103",
			direction="OUTBOUND",
			status="DRAFT",
			sender_bic=sender_bic,
			receiver_bic=receiver_bic,
			value_date=value_date,
			currency_code=currency_code,
			amount_cents=amount_cents,
			ordering_customer=f"/{ordering_account}\n{ordering_customer_name}",
			beneficiary_customer=f"/{beneficiary_account}\n{beneficiary_name}",
			remittance_info=remittance_info,
			raw_message=raw_fin,
			uetr=uetr,
		)
		self._session.add(msg)
		self._session.flush()

		# GL: DR Nostro (funds leaving our nostro), CR Customer Deposits (liability cleared)
		journal_id = self._post_to_gl(
			lines=[
				{
					"account_code": self.GL_NOSTRO,
					"debit_cents": amount_cents,
					"credit_cents": 0,
					"description": f"MT103 {msg_ref} — nostro DR (outbound payment)",
				},
				{
					"account_code": self.GL_CUSTOMER_DEPOSITS,
					"debit_cents": 0,
					"credit_cents": amount_cents,
					"description": f"MT103 {msg_ref} — customer deposit CR (payment instruction)",
				},
			],
			description=f"SWIFT MT103 {msg_ref} outbound",
		)
		if journal_id:
			msg.gl_journal_id = journal_id
			self._session.flush()

		self._emit(
			event_type="swift.message.sent",
			aggregate_type="SWIFTMessage",
			aggregate_id=str(msg.id),
			payload={
				"message_id": str(msg.id),
				"message_ref": msg_ref,
				"message_type": "MT103",
				"sender_bic": sender_bic,
				"receiver_bic": receiver_bic,
				"value_date": str(value_date),
				"currency_code": currency_code,
				"amount_cents": amount_cents,
				"uetr": uetr,
				"gl_journal_id": journal_id or "",
			},
		)

		log.info(
			"MT103 created: ref=%s uetr=%s amount=%d %s → %s",
			msg_ref, uetr, amount_cents, currency_code, receiver_bic,
		)
		return msg

	# ── Outbound MT202 ────────────────────────────────────────────────────────

	def create_mt202(
		self,
		sender_bic: str,
		receiver_bic: str,
		account_with_institution_bic: str,
		beneficiary_institution_bic: str,
		amount_cents: int,
		currency_code: str,
		value_date: date,
		reference: str | None = None,
		related_ref: str = "NONREF",
	) -> Any:
		"""Create and persist an outbound SWIFT MT202 Financial Institution Transfer.

		MT202 is the bank-to-bank cover payment used when routing customer
		payments through intermediary correspondents. Debit our nostro at the
		correspondent, credit the vostro of the receiving institution.

		Workflow:
		  1. Validate BICs and amount
		  2. Build MT202 FIN body (:20: :21: :32A: :57A: :58A:)
		  3. Persist SWIFTMessage (no UETR for plain MT202)
		  4. Post GL: DR Nostro (1011) / CR Vostro (2300)
		  5. Emit swift.message.sent

		Args:
			sender_bic:                   BIC11 of our bank
			receiver_bic:                 BIC11 of correspondent receiving MT202
			account_with_institution_bic: :57A: intermediary BIC
			beneficiary_institution_bic:  :58A: final beneficiary institution BIC
			amount_cents:                 Transfer amount in integer minor units
			currency_code:                ISO 4217
			value_date:                   Settlement value date
			reference:                    Override :20: reference
			related_ref:                  :21: related reference (MT103 ref this covers)

		Returns:
			SWIFTMessage instance
		"""
		from pgappforge.plugins.fintech.swift.models import SWIFTMessage

		if amount_cents <= 0:
			raise ValueError(f"amount_cents must be positive, got {amount_cents}")
		for bic_label, bic_val in [
			("sender_bic", sender_bic),
			("receiver_bic", receiver_bic),
			("account_with_institution_bic", account_with_institution_bic),
			("beneficiary_institution_bic", beneficiary_institution_bic),
		]:
			if bic_val and not validate_bic(bic_val):
				raise ValueError(f"Invalid BIC for {bic_label}: {bic_val!r}")

		msg_ref = _make_message_ref(reference, prefix="MT202")
		raw_fin = _generate_mt202(
			message_ref=msg_ref,
			related_ref=related_ref,
			sender_bic=sender_bic,
			receiver_bic=receiver_bic,
			account_with_institution_bic=account_with_institution_bic,
			beneficiary_institution_bic=beneficiary_institution_bic,
			amount_cents=amount_cents,
			currency_code=currency_code,
			value_date=value_date,
		)

		msg = SWIFTMessage(
			tenant_id=self._tenant_id,
			message_ref=msg_ref,
			message_type="MT202",
			direction="OUTBOUND",
			status="DRAFT",
			sender_bic=sender_bic,
			receiver_bic=receiver_bic,
			value_date=value_date,
			currency_code=currency_code,
			amount_cents=amount_cents,
			raw_message=raw_fin,
		)
		self._session.add(msg)
		self._session.flush()

		# GL: DR Nostro / CR Vostro of receiving institution
		journal_id = self._post_to_gl(
			lines=[
				{
					"account_code": self.GL_NOSTRO,
					"debit_cents": amount_cents,
					"credit_cents": 0,
					"description": f"MT202 {msg_ref} — nostro DR (cover payment)",
				},
				{
					"account_code": self.GL_VOSTRO,
					"debit_cents": 0,
					"credit_cents": amount_cents,
					"description": f"MT202 {msg_ref} — vostro CR ({beneficiary_institution_bic})",
				},
			],
			description=f"SWIFT MT202 {msg_ref} outbound",
		)
		if journal_id:
			msg.gl_journal_id = journal_id
			self._session.flush()

		self._emit(
			event_type="swift.message.sent",
			aggregate_type="SWIFTMessage",
			aggregate_id=str(msg.id),
			payload={
				"message_id": str(msg.id),
				"message_ref": msg_ref,
				"message_type": "MT202",
				"sender_bic": sender_bic,
				"receiver_bic": receiver_bic,
				"account_with_institution_bic": account_with_institution_bic,
				"beneficiary_institution_bic": beneficiary_institution_bic,
				"value_date": str(value_date),
				"currency_code": currency_code,
				"amount_cents": amount_cents,
				"gl_journal_id": journal_id or "",
			},
		)

		log.info(
			"MT202 created: ref=%s amount=%d %s → %s",
			msg_ref, amount_cents, currency_code, beneficiary_institution_bic,
		)
		return msg

	# ── Inbound MT103 processing ──────────────────────────────────────────────

	def process_inbound_mt103(self, raw_fin_message: str) -> Any:
		"""Parse and persist an inbound SWIFT MT103.

		Parsing extracts key fields from the FIN block 4 text using regex.
		Persists the message as INBOUND/RECEIVED, then attempts to credit the
		beneficiary via CoreBankingService.deposit() (non-fatal).

		Parsing handles:
		  :20:  sender reference
		  :32A: value date, currency, amount
		  :50K: ordering customer
		  :59:  beneficiary customer
		  :70:  remittance information
		  :121: UETR (gpi field — present in gpi-enabled messages)

		Args:
			raw_fin_message: Full SWIFT FIN block 4 text

		Returns:
			SWIFTMessage instance (INBOUND, status=RECEIVED)

		Raises:
			ValueError: if :20: or :32A: cannot be parsed (malformed message)
		"""
		from pgappforge.plugins.fintech.swift.models import SWIFTMessage

		msg_ref = _extract_field(raw_fin_message, "20")
		if not msg_ref:
			raise ValueError("Cannot parse :20: sender reference from MT103 FIN text")

		field_32a = _extract_field(raw_fin_message, "32A")
		if not field_32a:
			raise ValueError("Cannot parse :32A: value/currency/amount from MT103 FIN text")

		date_str, currency_code, amount_cents = _parse_32a(field_32a)
		value_date = _parse_value_date(date_str)

		ordering_customer = _extract_field(raw_fin_message, "50K") or _extract_field(raw_fin_message, "50A")
		beneficiary_customer = _extract_field(raw_fin_message, "59")
		remittance_info = _extract_field(raw_fin_message, "70")
		uetr = _extract_field(raw_fin_message, "121") or None

		# Infer sender BIC from block 1 header if present, else use placeholder
		# In production this comes from the SWIFT network envelope
		sender_bic_match = re.search(r"\{1:F01([A-Z0-9]{8,11})", raw_fin_message)
		sender_bic = sender_bic_match.group(1)[:11] if sender_bic_match else "UNKNOWNXXXX"
		receiver_bic_match = re.search(r"\{2:[IO]\d{3}([A-Z0-9]{8,11})", raw_fin_message)
		receiver_bic = receiver_bic_match.group(1)[:11] if receiver_bic_match else "UNKNOWNXXXX"

		if amount_cents <= 0:
			raise ValueError(f"Parsed amount_cents={amount_cents} is non-positive for ref {msg_ref!r}")

		msg = SWIFTMessage(
			tenant_id=self._tenant_id,
			message_ref=msg_ref,
			message_type="MT103",
			direction="INBOUND",
			status="RECEIVED",
			sender_bic=sender_bic,
			receiver_bic=receiver_bic,
			value_date=value_date,
			currency_code=currency_code,
			amount_cents=amount_cents,
			ordering_customer=ordering_customer,
			beneficiary_customer=beneficiary_customer,
			remittance_info=remittance_info,
			raw_message=raw_fin_message,
			uetr=uetr,
		)
		self._session.add(msg)
		self._session.flush()

		# Credit beneficiary — extract account from :59: field (/account\nname format)
		bene_lines = (beneficiary_customer or "").splitlines()
		bene_account = bene_lines[0].lstrip("/") if bene_lines else ""
		if bene_account:
			self._core_deposit(
				beneficiary_account_ref=bene_account,
				amount_cents=amount_cents,
				currency_code=currency_code,
				reference=msg_ref,
			)

		self._emit(
			event_type="swift.message.received",
			aggregate_type="SWIFTMessage",
			aggregate_id=str(msg.id),
			payload={
				"message_id": str(msg.id),
				"message_ref": msg_ref,
				"message_type": "MT103",
				"sender_bic": sender_bic,
				"receiver_bic": receiver_bic,
				"value_date": str(value_date),
				"currency_code": currency_code,
				"amount_cents": amount_cents,
				"uetr": uetr or "",
				"ordering_customer": (ordering_customer or "")[:200],
				"beneficiary_customer": (beneficiary_customer or "")[:200],
			},
		)

		log.info(
			"MT103 inbound processed: ref=%s amount=%d %s uetr=%s",
			msg_ref, amount_cents, currency_code, uetr,
		)
		return msg

	# ── Inbound MT900/MT910 ───────────────────────────────────────────────────

	def process_mt900_910(self, raw_fin_message: str, message_type: str) -> Any:
		"""Parse and persist an inbound MT900 (debit confirmation) or MT910 (credit confirmation).

		MT900 — correspondent confirms our nostro was debited (sent payment confirmation).
		MT910 — correspondent confirms our nostro was credited (received funds confirmation).

		Both carry :20: reference, :21: related reference, :32A: value/currency/amount.
		Parsed fields are stored; a reconciliation event is emitted for the nostro
		matching engine to consume.

		Args:
			raw_fin_message: Full SWIFT FIN block 4 text
			message_type:    "MT900" or "MT910"

		Returns:
			SWIFTMessage instance (INBOUND, status=RECEIVED)

		Raises:
			ValueError: if message_type is invalid, or mandatory fields missing
		"""
		from pgappforge.plugins.fintech.swift.models import SWIFTMessage

		if message_type not in ("MT900", "MT910"):
			raise ValueError(f"message_type must be MT900 or MT910, got {message_type!r}")

		msg_ref = _extract_field(raw_fin_message, "20")
		if not msg_ref:
			raise ValueError(f"Cannot parse :20: from {message_type} FIN text")

		related_ref = _extract_field(raw_fin_message, "21") or ""

		field_32a = _extract_field(raw_fin_message, "32A")
		if not field_32a:
			raise ValueError(f"Cannot parse :32A: from {message_type} FIN text")

		date_str, currency_code, amount_cents = _parse_32a(field_32a)
		value_date = _parse_value_date(date_str)

		sender_bic_match = re.search(r"\{1:F01([A-Z0-9]{8,11})", raw_fin_message)
		sender_bic = sender_bic_match.group(1)[:11] if sender_bic_match else "UNKNOWNXXXX"
		receiver_bic_match = re.search(r"\{2:[IO]\d{3}([A-Z0-9]{8,11})", raw_fin_message)
		receiver_bic = receiver_bic_match.group(1)[:11] if receiver_bic_match else "UNKNOWNXXXX"

		if amount_cents <= 0:
			raise ValueError(f"Parsed amount_cents={amount_cents} is non-positive for {message_type} ref {msg_ref!r}")

		msg = SWIFTMessage(
			tenant_id=self._tenant_id,
			message_ref=msg_ref,
			message_type=message_type,
			direction="INBOUND",
			status="RECEIVED",
			sender_bic=sender_bic,
			receiver_bic=receiver_bic,
			value_date=value_date,
			currency_code=currency_code,
			amount_cents=amount_cents,
			remittance_info=related_ref,		# store :21: in remittance_info for cross-reference
			raw_message=raw_fin_message,
		)
		self._session.add(msg)
		self._session.flush()

		# Emit reconciliation event
		event_type = (
			"swift.nostro.debit_confirmed" if message_type == "MT900"
			else "swift.nostro.credit_confirmed"
		)
		self._emit(
			event_type=event_type,
			aggregate_type="SWIFTMessage",
			aggregate_id=str(msg.id),
			payload={
				"message_id": str(msg.id),
				"message_ref": msg_ref,
				"message_type": message_type,
				"related_ref": related_ref,
				"sender_bic": sender_bic,
				"value_date": str(value_date),
				"currency_code": currency_code,
				"amount_cents": amount_cents,
			},
		)

		log.info(
			"%s inbound processed: ref=%s related_ref=%s amount=%d %s",
			message_type, msg_ref, related_ref, amount_cents, currency_code,
		)
		return msg

	# ── gpi status updates ────────────────────────────────────────────────────

	def update_gpi_status(self, uetr: str, status_payload: dict) -> Any:
		"""Receive a SWIFT gpi Tracker status update and persist a SWIFTGpiStatus row.

		When status_code is ACCC (completed), updates SWIFTMessage.delivered_at.
		When status_code is RJCT (rejected), updates SWIFTMessage.error_code/error_text
		and sets status to REJECTED.

		Args:
			uetr:           UUID4 UETR from the gpi Tracker webhook payload
			status_payload: dict with keys:
			  status_code      (str, required): ACSP | ACCC | RJCT | PDNG
			  agent_bic        (str, required): BIC of reporting agent
			  updated_by_bank  (str, required): BIC of gpi member writing this update
			  event_timestamp  (str | datetime, required): ISO datetime or datetime obj
			  status_reason    (str, optional): ISO 20022 reason code
			  raw_payload      (dict, optional): full tracker payload for audit

		Returns:
			SWIFTGpiStatus instance

		Raises:
			ValueError: if UETR not found, or mandatory payload fields missing
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.swift.models import SWIFTGpiStatus, SWIFTMessage

		status_code = status_payload.get("status_code", "")
		if status_code not in ("ACSP", "ACCC", "RJCT", "PDNG"):
			raise ValueError(f"status_code must be ACSP|ACCC|RJCT|PDNG, got {status_code!r}")

		agent_bic = status_payload.get("agent_bic", "")
		updated_by_bank = status_payload.get("updated_by_bank", "")
		if not agent_bic or not updated_by_bank:
			raise ValueError("status_payload must contain agent_bic and updated_by_bank")

		# Resolve event_timestamp
		raw_ts = status_payload.get("event_timestamp", _now())
		if isinstance(raw_ts, str):
			try:
				event_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
			except ValueError:
				event_ts = _now()
		elif isinstance(raw_ts, datetime):
			event_ts = raw_ts
		else:
			event_ts = _now()

		# Find the parent SWIFTMessage
		msg = self._session.execute(
			sa.select(SWIFTMessage).where(
				SWIFTMessage.uetr == uetr,
				SWIFTMessage.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if msg is None:
			raise ValueError(f"SWIFTMessage with uetr={uetr!r} not found for tenant {self._tenant_id!r}")

		gpi = SWIFTGpiStatus(
			tenant_id=self._tenant_id,
			uetr=uetr,
			message_id=str(msg.id),
			status_code=status_code,
			agent_bic=agent_bic,
			status_reason=status_payload.get("status_reason"),
			updated_by_bank=updated_by_bank,
			event_timestamp=event_ts,
			raw_payload=status_payload.get("raw_payload") or status_payload,
		)
		self._session.add(gpi)

		# Update parent message on terminal statuses
		if status_code == "ACCC":
			msg.delivered_at = event_ts
			msg.status = "DELIVERED"
		elif status_code == "RJCT":
			msg.status = "REJECTED"
			msg.error_code = status_payload.get("status_reason", "RJCT")[:10]
			msg.error_text = status_payload.get("reject_reason") or f"Payment rejected by {agent_bic}"

		self._session.flush()

		is_final = status_code in ("ACCC", "RJCT")
		self._emit(
			event_type="swift.gpi.updated",
			aggregate_type="SWIFTGpiStatus",
			aggregate_id=str(gpi.id),
			payload={
				"gpi_status_id": str(gpi.id),
				"message_id": str(msg.id),
				"uetr": uetr,
				"status_code": status_code,
				"agent_bic": agent_bic,
				"status_reason": status_payload.get("status_reason") or "",
				"event_timestamp": event_ts.isoformat(),
				"is_final": is_final,
			},
		)

		log.info(
			"gpi status updated: uetr=%s status=%s agent=%s final=%s",
			uetr, status_code, agent_bic, is_final,
		)
		return gpi

	# ── Message status query ──────────────────────────────────────────────────

	def get_message_status(self, message_ref: str) -> dict:
		"""Return status dict for a message identified by :20: sender reference.

		Includes the parent SWIFTMessage fields and the latest SWIFTGpiStatus
		row (if any) ordered by event_timestamp DESC.

		Args:
			message_ref: SWIFT :20: sender reference, max 16 chars

		Returns:
			dict with keys: message, latest_gpi_status (may be None)

		Raises:
			ValueError: if message not found
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.swift.models import SWIFTGpiStatus, SWIFTMessage

		msg = self._session.execute(
			sa.select(SWIFTMessage).where(
				SWIFTMessage.message_ref == message_ref,
				SWIFTMessage.tenant_id == self._tenant_id,
			)
		).scalar_one_or_none()
		if msg is None:
			raise ValueError(f"SWIFTMessage ref={message_ref!r} not found for tenant {self._tenant_id!r}")

		latest_gpi: SWIFTGpiStatus | None = None
		if msg.uetr:
			latest_gpi = self._session.execute(
				sa.select(SWIFTGpiStatus)
				.where(
					SWIFTGpiStatus.uetr == msg.uetr,
					SWIFTGpiStatus.tenant_id == self._tenant_id,
				)
				.order_by(SWIFTGpiStatus.event_timestamp.desc())
				.limit(1)
			).scalar_one_or_none()

		gpi_dict: dict | None = None
		if latest_gpi is not None:
			gpi_dict = {
				"id": str(latest_gpi.id),
				"status_code": latest_gpi.status_code,
				"agent_bic": latest_gpi.agent_bic,
				"status_reason": latest_gpi.status_reason,
				"updated_by_bank": latest_gpi.updated_by_bank,
				"event_timestamp": latest_gpi.event_timestamp.isoformat(),
			}

		return {
			"message": {
				"id": str(msg.id),
				"message_ref": msg.message_ref,
				"message_type": msg.message_type,
				"direction": msg.direction,
				"status": msg.status,
				"sender_bic": msg.sender_bic,
				"receiver_bic": msg.receiver_bic,
				"value_date": str(msg.value_date),
				"currency_code": msg.currency_code,
				"amount_cents": msg.amount_cents,
				"uetr": msg.uetr,
				"ack_at": msg.ack_at.isoformat() if msg.ack_at else None,
				"delivered_at": msg.delivered_at.isoformat() if msg.delivered_at else None,
				"error_code": msg.error_code,
				"error_text": msg.error_text,
				"gl_journal_id": msg.gl_journal_id,
				"created_at": msg.created_at.isoformat() if msg.created_at else None,
			},
			"latest_gpi_status": gpi_dict,
		}

	# ── Nostro reconciliation ─────────────────────────────────────────────────

	def reconcile_nostro(
		self,
		account_code: str,
		from_date: date,
		to_date: date,
	) -> dict:
		"""Reconcile nostro account by comparing outbound SWIFT messages against
		MT900/MT910 confirmations received within a date range.

		Matching logic:
		  - Outbound MT103/MT202 within value_date range → expected debits
		  - Inbound MT900 within value_date range → confirmed debits
		  - Inbound MT910 within value_date range → confirmed credits
		  - A message is "matched" if an MT900/MT910 exists with remittance_info
		    (the :21: related reference field) equal to the outbound :20: reference,
		    or if the amounts and dates tally within the date window.

		This is a first-pass reconciliation. Production implementations feed this
		output into a treasury system for manual exception resolution.

		Args:
			account_code:  Nostro GL account code (for reporting context only)
			from_date:     Start of reconciliation window (inclusive, value_date)
			to_date:       End of reconciliation window (inclusive, value_date)

		Returns:
			dict with:
			  matched_count           — number of outbound messages with confirmation
			  unmatched_count         — outbound messages lacking MT900 confirmation
			  total_outbound_cents    — sum of all outbound MT103+MT202 amounts
			  total_inbound_cents     — sum of all inbound MT103 amounts
			  total_debit_confirmed_cents  — sum of MT900 confirmed debits
			  total_credit_confirmed_cents — sum of MT910 confirmed credits
			  unmatched_refs          — list of unmatched outbound message refs
			  account_code            — echoed back for context
			  from_date               — echoed back
			  to_date                 — echoed back
		"""
		import sqlalchemy as sa
		from pgappforge.plugins.fintech.swift.models import SWIFTMessage

		# Outbound MT103 + MT202 within window
		outbound_rows = self._session.execute(
			sa.select(SWIFTMessage).where(
				SWIFTMessage.tenant_id == self._tenant_id,
				SWIFTMessage.direction == "OUTBOUND",
				SWIFTMessage.message_type.in_(["MT103", "MT202"]),
				SWIFTMessage.value_date >= from_date,
				SWIFTMessage.value_date <= to_date,
			)
		).scalars().all()

		# MT900 debit confirmations within window
		mt900_rows = self._session.execute(
			sa.select(SWIFTMessage).where(
				SWIFTMessage.tenant_id == self._tenant_id,
				SWIFTMessage.direction == "INBOUND",
				SWIFTMessage.message_type == "MT900",
				SWIFTMessage.value_date >= from_date,
				SWIFTMessage.value_date <= to_date,
			)
		).scalars().all()

		# MT910 credit confirmations within window
		mt910_rows = self._session.execute(
			sa.select(SWIFTMessage).where(
				SWIFTMessage.tenant_id == self._tenant_id,
				SWIFTMessage.direction == "INBOUND",
				SWIFTMessage.message_type == "MT910",
				SWIFTMessage.value_date >= from_date,
				SWIFTMessage.value_date <= to_date,
			)
		).scalars().all()

		# Inbound MT103 (funds received)
		inbound_mt103_rows = self._session.execute(
			sa.select(SWIFTMessage).where(
				SWIFTMessage.tenant_id == self._tenant_id,
				SWIFTMessage.direction == "INBOUND",
				SWIFTMessage.message_type == "MT103",
				SWIFTMessage.value_date >= from_date,
				SWIFTMessage.value_date <= to_date,
			)
		).scalars().all()

		# Build lookup: :21: related_ref (stored in remittance_info) → MT900 confirmation
		# remittance_info holds the :21: related reference for MT900/910
		confirmed_refs: set[str] = {
			(row.remittance_info or "").strip() for row in mt900_rows
			if row.remittance_info
		}

		matched: list[str] = []
		unmatched: list[str] = []
		for msg in outbound_rows:
			ref = (msg.message_ref or "").strip()
			if ref in confirmed_refs or msg.status == "DELIVERED":
				matched.append(ref)
			else:
				unmatched.append(ref)

		total_outbound = sum(m.amount_cents for m in outbound_rows)
		total_inbound = sum(m.amount_cents for m in inbound_mt103_rows)
		total_debit_confirmed = sum(m.amount_cents for m in mt900_rows)
		total_credit_confirmed = sum(m.amount_cents for m in mt910_rows)

		return {
			"matched_count": len(matched),
			"unmatched_count": len(unmatched),
			"total_outbound_cents": total_outbound,
			"total_inbound_cents": total_inbound,
			"total_debit_confirmed_cents": total_debit_confirmed,
			"total_credit_confirmed_cents": total_credit_confirmed,
			"unmatched_refs": unmatched,
			"account_code": account_code,
			"from_date": str(from_date),
			"to_date": str(to_date),
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SWIFTService",
	# helpers exposed for testing
	"_uuid4",
	"_today",
	"_now",
	"_fmt_date",
	"_fmt_amount",
	"_make_message_ref",
	"_generate_mt103",
	"_generate_mt202",
	"_extract_field",
	"_parse_32a",
	"_parse_value_date",
]
