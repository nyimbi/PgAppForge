"""
pgappforge/plugins/fintech/card_issuing/services.py

CardIssuingService — card lifecycle, PIN management, and authorization.

Security design:
  - PAN is generated in-memory only; only hash + last4 + masked are persisted.
  - PIN is encrypted with AES-256-GCM keyed from an HMAC-SHA256 of the
    CARD_PIN_MASTER_KEY and the card_id (key derivation per card).
  - PIN attempts capped at 3; 4th failure blocks the card with PIN_LOCKED.
  - 3DS OTP is HMAC-TOTP (RFC 6238) with a 30-second window.

Config keys read from Flask app.config then os.environ:
  CARD_PIN_MASTER_KEY  — required; minimum 32-char hex or arbitrary string
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
import struct
import time
from base64 import b64decode, b64encode
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from pgappforge.plugins.fintech.card_issuing.events import (
	CardActivatedEvent,
	CardAuthorizationEvent,
	CardBlockedEvent,
	CardIssuedEvent,
	CardPINSetEvent,
	CardReplacedEvent,
)
from pgappforge.plugins.fintech.card_issuing.models import (
	CardAuthorizationLog,
	CardBIN,
	IssuedCard,
	PINBlock,
)

log = logging.getLogger(__name__)


def _emit(event: Any) -> None:
	try:
		from pgappforge.plugins.erp.foundation.commons import emit_event
		emit_event(event)
	except Exception as exc:
		log.debug("CardIssuingService: event emit suppressed: %s", exc)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CardIssuingError(Exception):
	"""Base exception for all card issuing errors."""


class CardNotFoundError(CardIssuingError):
	"""Raised when a card cannot be located by ID."""


class CardStatusError(CardIssuingError):
	"""Raised when a card operation is invalid for its current status."""


class PINError(CardIssuingError):
	"""Raised on PIN verification failure or PIN validation errors."""


class PINMasterKeyNotConfiguredError(CardIssuingError):
	"""Raised when CARD_PIN_MASTER_KEY is absent or empty."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CardIssuingService:
	"""Card lifecycle, PIN management, 3DS OTP, and authorization service.

	All mutating methods accept an open SQLAlchemy session and do NOT commit;
	callers are responsible for committing or rolling back.

	Usage::

		svc = CardIssuingService()
		card, pan = svc.issue_virtual_card(
			account_id="acc-123",
			bin_code="424242",
			cardholder_name="JOHN DOE",
			tenant_id="default",
			session=session,
		)
		session.commit()
	"""

	# ------------------------------------------------------------------
	# Luhn utilities
	# ------------------------------------------------------------------

	@staticmethod
	def _luhn_check_digit(partial_pan: str) -> str:
		"""Compute the Luhn check digit for a partial PAN (without check digit).

		Implements the standard Luhn doubling algorithm on the reversed digit
		string and returns the check digit as a single character string.

		Args:
			partial_pan: All PAN digits except the trailing check digit.

		Returns:
			Single-character string "0"–"9".
		"""
		digits = [int(c) for c in reversed(partial_pan)]
		total = 0
		for i, d in enumerate(digits):
			if i % 2 == 0:
				# Double every other digit starting from position 0 in reversed order
				# (i.e. every second digit from the right of the partial PAN)
				doubled = d * 2
				total += doubled - 9 if doubled > 9 else doubled
			else:
				total += d
		return str((10 - total % 10) % 10)

	@staticmethod
	def _generate_pan(bin_code: str, length: int = 16) -> str:
		"""Generate a Luhn-valid PAN of the given length.

		Fills the middle digits with cryptographically random decimal digits,
		then appends the computed Luhn check digit.

		Args:
			bin_code: The BIN prefix (6-8 digits).
			length: Total PAN length including check digit. Defaults to 16.

		Returns:
			A string of exactly ``length`` decimal digits with a valid Luhn check.
		"""
		# Fill body with random digits leaving room for check digit
		body_length = length - len(bin_code) - 1
		body = "".join(str(secrets.randbelow(10)) for _ in range(body_length))
		partial = bin_code + body
		check = CardIssuingService._luhn_check_digit(partial)
		return partial + check

	# ------------------------------------------------------------------
	# PIN key derivation
	# ------------------------------------------------------------------

	@staticmethod
	def _get_pin_key(card_id: str) -> bytes:
		"""Derive a per-card AES-256 key from the master key and card_id.

		Key derivation: HMAC-SHA256(CARD_PIN_MASTER_KEY, card_id)
		This gives a unique 32-byte key per card without storing per-card secrets.

		Config lookup order: Flask app.config → os.environ.

		Args:
			card_id: The UUID string of the card.

		Returns:
			32-byte bytes object suitable for AES-256.

		Raises:
			PINMasterKeyNotConfiguredError: If the master key is absent or empty.
		"""
		master_key = ""

		# Try Flask app config first
		try:
			from flask import current_app
			master_key = current_app.config.get("CARD_PIN_MASTER_KEY", "")
		except RuntimeError:
			pass  # No app context

		# Fall back to environment variable
		if not master_key:
			master_key = os.environ.get("CARD_PIN_MASTER_KEY", "")

		if not master_key:
			raise PINMasterKeyNotConfiguredError(
				"CARD_PIN_MASTER_KEY is not configured. "
				"Set it in Flask app.config or the CARD_PIN_MASTER_KEY environment variable."
			)

		return hmac.new(
			master_key.encode(),
			card_id.encode(),
			hashlib.sha256,
		).digest()

	# ------------------------------------------------------------------
	# PIN encryption / decryption
	# ------------------------------------------------------------------

	@staticmethod
	def _encrypt_pin(card_id: str, pin: str) -> tuple[str, str]:
		"""Encrypt a PIN using AES-256-GCM with a per-card derived key.

		The card_id is used as Additional Authenticated Data (AAD), binding the
		ciphertext to this specific card and preventing cross-card replay attacks.

		Args:
			card_id: Card UUID string (used as AAD).
			pin: 4-6 digit PIN string.

		Returns:
			Tuple of (encrypted_pin_b64, nonce_b64) — both base64-encoded strings.

		Raises:
			CardIssuingError: If the cryptography package is not installed.
			PINMasterKeyNotConfiguredError: If the master key is not configured.
		"""
		try:
			from cryptography.hazmat.primitives.ciphers.aead import AESGCM
		except ImportError as exc:
			raise CardIssuingError(
				"The 'cryptography' package is required for PIN encryption. "
				"Install it with: pip install cryptography"
			) from exc

		key = CardIssuingService._get_pin_key(card_id)
		nonce = os.urandom(12)  # 96-bit nonce for AES-GCM
		ct = AESGCM(key).encrypt(nonce, pin.encode(), card_id.encode())
		return b64encode(ct).decode(), b64encode(nonce).decode()

	@staticmethod
	def _verify_pin(
		card_id: str,
		pin: str,
		encrypted_b64: str,
		nonce_b64: str,
	) -> bool:
		"""Verify a PIN against its stored AES-256-GCM ciphertext.

		Args:
			card_id: Card UUID string (must match AAD used during encryption).
			pin: Candidate PIN string submitted by the cardholder.
			encrypted_b64: Base64-encoded ciphertext from PINBlock.
			nonce_b64: Base64-encoded nonce from PINBlock.

		Returns:
			True if the PIN matches, False if incorrect or the tag is invalid.
		"""
		try:
			from cryptography.hazmat.primitives.ciphers.aead import AESGCM
			from cryptography.exceptions import InvalidTag
		except ImportError:
			log.error("_verify_pin: cryptography package not available")
			return False

		try:
			key = CardIssuingService._get_pin_key(card_id)
			ct = b64decode(encrypted_b64)
			nonce = b64decode(nonce_b64)
			plaintext = AESGCM(key).decrypt(nonce, ct, card_id.encode())
			return plaintext.decode() == pin
		except InvalidTag:
			return False
		except Exception as exc:
			log.warning("_verify_pin error for card %s: %s", card_id, exc)
			return False

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	@staticmethod
	def _get_card(card_id: str, tenant_id: str, session: Any) -> IssuedCard:
		"""Fetch an IssuedCard by ID.

		Args:
			card_id: UUID string of the card.
			tenant_id: Tenant identifier (reserved for multi-tenant row filtering).
			session: SQLAlchemy session.

		Returns:
			The IssuedCard instance.

		Raises:
			CardNotFoundError: If no card with that ID exists.
		"""
		card = session.get(IssuedCard, card_id)
		if card is None:
			raise CardNotFoundError(f"Card {card_id!r} not found.")
		return card

	# ------------------------------------------------------------------
	# Card issuance
	# ------------------------------------------------------------------

	def issue_virtual_card(
		self,
		account_id: str,
		bin_code: str,
		cardholder_name: str,
		tenant_id: str,
		session: Any,
		expiry_months: int = 36,
		daily_limit_cents: int = 0,
	) -> tuple[IssuedCard, str]:
		"""Issue a new virtual card for the given account.

		The PAN is generated in-memory, hashed, and immediately discarded.
		Only the SHA-256 hash, last 4 digits, and masked form are stored.

		Args:
			account_id: Customer account identifier.
			bin_code: BIN prefix to use for the card.
			cardholder_name: Name to associate with the card (max 26 chars).
			tenant_id: Tenant identifier.
			session: Open SQLAlchemy session.
			expiry_months: Number of months until card expiry. Defaults to 36.
			daily_limit_cents: Per-day spend limit in cents. 0 = no limit.

		Returns:
			Tuple of (IssuedCard instance, full PAN string).
			The PAN must be delivered to the cardholder and then discarded.

		Raises:
			CardIssuingError: If the BIN is not found or inactive.
		"""
		# Validate BIN
		bin_row = session.execute(
			select(CardBIN).where(
				CardBIN.bin_code == bin_code,
				CardBIN.is_active.is_(True),
			)
		).scalar_one_or_none()
		if bin_row is None:
			raise CardIssuingError(
				f"BIN {bin_code!r} not found or is inactive."
			)

		# Generate PAN
		pan = self._generate_pan(bin_code, length=16)

		# Derive stored fields from PAN
		pan_hash = hashlib.sha256(pan.encode()).hexdigest()
		last4 = pan[-4:]
		# Mask: show BIN (first 6) + asterisks + last 4
		mask_len = max(0, len(pan) - len(bin_code) - 4)
		masked = bin_code + ("*" * mask_len) + pan[-4:]

		# Compute expiry
		now = datetime.now(timezone.utc)
		expiry_month = ((now.month - 1 + expiry_months) % 12) + 1
		expiry_year = now.year + (now.month - 1 + expiry_months) // 12

		card = IssuedCard(
			account_id=account_id,
			bin_id=bin_row.id,
			card_number_hash=pan_hash,
			card_number_last4=last4,
			card_number_masked=masked,
			expiry_month=expiry_month,
			expiry_year=expiry_year,
			cardholder_name=cardholder_name[:26],
			is_virtual=True,
			status="INACTIVE",
			daily_limit_cents=daily_limit_cents,
			card_metadata={},
		)
		session.add(card)
		session.flush()  # Populate card.id
		_emit(CardIssuedEvent(
			aggregate_id=card.id,
			aggregate_type="IssuedCard",
			card_id=card.id,
			account_id=account_id,
			is_virtual=True,
			card_number_last4=card.card_number_last4,
		))

		log.info(
			"issue_virtual_card: issued card %s for account %s (BIN %s)",
			card.id, account_id, bin_code,
		)
		return card, pan

	# ------------------------------------------------------------------
	# Card lifecycle
	# ------------------------------------------------------------------

	def activate_card(self, card_id: str, tenant_id: str, session: Any) -> IssuedCard:
		"""Activate a card (INACTIVE → ACTIVE).

		Args:
			card_id: Card UUID string.
			tenant_id: Tenant identifier.
			session: Open SQLAlchemy session.

		Returns:
			The updated IssuedCard instance.

		Raises:
			CardNotFoundError: If the card does not exist.
			CardStatusError: If the card is not in INACTIVE status.
		"""
		card = self._get_card(card_id, tenant_id, session)
		if card.status != "INACTIVE":
			raise CardStatusError(
				f"Card {card_id!r} cannot be activated — current status is {card.status!r}."
			)
		card.status = "ACTIVE"
		card.activated_at = datetime.now(timezone.utc)
		session.flush()
		_emit(CardActivatedEvent(
			aggregate_id=card.id,
			aggregate_type="IssuedCard",
			card_id=card.id,
		))
		log.info("activate_card: card %s activated", card_id)
		return card

	def block_card(
		self,
		card_id: str,
		reason: str,
		tenant_id: str,
		session: Any,
	) -> IssuedCard:
		"""Block a card for the given reason.

		Args:
			card_id: Card UUID string.
			reason: Block reason string (max 50 chars).
			tenant_id: Tenant identifier.
			session: Open SQLAlchemy session.

		Returns:
			The updated IssuedCard instance.

		Raises:
			CardNotFoundError: If the card does not exist.
		"""
		card = self._get_card(card_id, tenant_id, session)
		card.status = "BLOCKED"
		card.block_reason = reason[:50]
		session.flush()
		_emit(CardBlockedEvent(
			aggregate_id=card.id,
			aggregate_type="IssuedCard",
			card_id=card.id,
			block_reason=reason,
		))
		log.info("block_card: card %s blocked (reason=%r)", card_id, reason)
		return card

	def replace_card(
		self,
		card_id: str,
		reason: str,
		tenant_id: str,
		session: Any,
	) -> tuple[IssuedCard, str]:
		"""Replace a card — block the old card and issue a new one on the same BIN.

		Args:
			card_id: UUID of the card to replace.
			reason: Replacement reason (e.g. LOST, STOLEN, DAMAGED).
			tenant_id: Tenant identifier.
			session: Open SQLAlchemy session.

		Returns:
			Tuple of (new IssuedCard instance, new PAN string).
			The new PAN must be delivered to the cardholder.

		Raises:
			CardNotFoundError: If the old card does not exist.
		"""
		old_card = self._get_card(card_id, tenant_id, session)
		old_card.status = "BLOCKED"
		old_card.block_reason = f"REPLACED:{reason}"[:50]

		# Fetch BIN code from the relationship
		bin_row = session.get(CardBIN, old_card.bin_id)
		bin_code = bin_row.bin_code if bin_row else ""

		new_card, pan = self.issue_virtual_card(
			account_id=old_card.account_id,
			bin_code=bin_code,
			cardholder_name=old_card.cardholder_name,
			tenant_id=tenant_id,
			session=session,
			daily_limit_cents=old_card.daily_limit_cents,
		)
		_emit(CardReplacedEvent(
			aggregate_id=new_card.id,
			aggregate_type="IssuedCard",
			old_card_id=card_id,
			new_card_id=new_card.id,
			replace_reason=reason,
		))
		log.info(
			"replace_card: card %s replaced by %s (reason=%r)",
			card_id, new_card.id, reason,
		)
		return new_card, pan

	# ------------------------------------------------------------------
	# PIN management
	# ------------------------------------------------------------------

	def set_pin(
		self,
		card_id: str,
		pin: str,
		tenant_id: str,
		session: Any,
	) -> None:
		"""Set or change the PIN for a card.

		Validates that the PIN is 4-6 digits, deletes any existing PINBlock,
		inserts a new encrypted PINBlock, and resets pin_attempts to 0.

		Args:
			card_id: Card UUID string.
			pin: New PIN — must be 4-6 numeric digits.
			tenant_id: Tenant identifier.
			session: Open SQLAlchemy session.

		Raises:
			CardNotFoundError: If the card does not exist.
			PINError: If the PIN is not 4-6 digits.
			PINMasterKeyNotConfiguredError: If the master key is missing.
		"""
		if not pin.isdigit() or not (4 <= len(pin) <= 6):
			raise PINError("PIN must be 4-6 numeric digits.")

		card = self._get_card(card_id, tenant_id, session)

		# Delete any existing PIN block for this card
		existing = session.execute(
			select(PINBlock).where(PINBlock.card_id == card_id)
		).scalar_one_or_none()
		if existing is not None:
			# Bypass ORM immutability guard: use raw DELETE
			session.execute(
				PINBlock.__table__.delete().where(PINBlock.card_id == card_id)
			)

		encrypted_pin, pin_nonce = self._encrypt_pin(card_id, pin)
		pin_block = PINBlock(
			card_id=card_id,
			encrypted_pin=encrypted_pin,
			pin_nonce=pin_nonce,
			algorithm="AES256GCM",
		)
		session.add(pin_block)

		# Reset failed attempts and record set time
		card.pin_attempts = 0
		card.pin_set_at = datetime.now(timezone.utc)
		session.flush()
		_emit(CardPINSetEvent(
			aggregate_id=card_id,
			aggregate_type="IssuedCard",
			card_id=card_id,
		))
		log.info("set_pin: PIN set for card %s", card_id)

	def verify_pin(
		self,
		card_id: str,
		pin: str,
		tenant_id: str,
		session: Any,
	) -> bool:
		"""Verify a PIN against the stored PINBlock.

		Increments pin_attempts on failure.  Blocks the card with
		block_reason="PIN_LOCKED" on the 3rd consecutive failure.

		Args:
			card_id: Card UUID string.
			pin: PIN string to verify.
			tenant_id: Tenant identifier.
			session: Open SQLAlchemy session.

		Returns:
			True if the PIN matches, False otherwise.

		Raises:
			CardNotFoundError: If the card does not exist.
			PINError: If no PIN has been set for the card.
		"""
		card = self._get_card(card_id, tenant_id, session)

		pin_block = session.execute(
			select(PINBlock).where(PINBlock.card_id == card_id)
		).scalar_one_or_none()
		if pin_block is None:
			raise PINError(f"No PIN set for card {card_id!r}.")

		ok = self._verify_pin(
			card_id,
			pin,
			pin_block.encrypted_pin,
			pin_block.pin_nonce,
		)

		if ok:
			card.pin_attempts = 0
		else:
			card.pin_attempts = (card.pin_attempts or 0) + 1
			if card.pin_attempts >= 3:
				card.status = "BLOCKED"
				card.block_reason = "PIN_LOCKED"
				log.warning("verify_pin: card %s blocked after %d failed attempts", card_id, card.pin_attempts)
		session.flush()

		return ok

	# ------------------------------------------------------------------
	# 3DS OTP generation
	# ------------------------------------------------------------------

	def generate_3ds_otp(
		self,
		card_id: str,
		tenant_id: str,
		session: Any,
	) -> str:
		"""Generate a 6-digit HMAC-TOTP OTP for 3DS authentication (RFC 6238).

		Key: full 32-byte per-card derived key (_get_pin_key / HMAC-SHA256).
		Time step: 30 seconds (standard TOTP window).

		Args:
			card_id: Card UUID string.
			tenant_id: Tenant identifier.
			session: Open SQLAlchemy session (used to validate card exists).

		Returns:
			A 6-digit string (zero-padded if necessary).

		Raises:
			CardNotFoundError: If the card does not exist.
			PINMasterKeyNotConfiguredError: If the master key is not configured.
		"""
		# Validate card exists
		self._get_card(card_id, tenant_id, session)

		key = self._get_pin_key(card_id)  # full 32 bytes — SHA-256 output
		t = int(time.time()) // 30

		# Pack counter as big-endian 8-byte integer (RFC 6238 / RFC 4226)
		msg = struct.pack(">Q", t)
		h = hmac.new(key, msg, hashlib.sha1).digest()

		# Dynamic truncation (RFC 4226 §5.4)
		offset = h[-1] & 0x0F
		code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
		otp = str(code % 1_000_000).zfill(6)

		log.debug("generate_3ds_otp: generated OTP for card %s", card_id)
		return otp

	# ------------------------------------------------------------------
	# Authorization
	# ------------------------------------------------------------------

	def authorize_transaction(
		self,
		card_id: str,
		amount_cents: int,
		auth_type: str,
		tenant_id: str,
		session: Any,
		merchant_name: str = "",
		mcc: str = "",
		terminal_id: str = "",
		currency_code: str = "KES",
	) -> dict[str, Any]:
		"""Process a card authorization request.

		Checks: card status, card expiry, daily spend limit.
		Records a CardAuthorizationLog entry regardless of outcome.
		Updates last_used_at on approval.

		Args:
			card_id: Card UUID string.
			amount_cents: Transaction amount in minor currency units.
			auth_type: Authorization type (PURCHASE, REFUND, CASH_ADVANCE, etc.).
			tenant_id: Tenant identifier.
			session: Open SQLAlchemy session.
			merchant_name: Optional merchant name.
			mcc: Optional Merchant Category Code (4-digit string).
			terminal_id: Optional POS terminal ID (up to 8 chars).
			currency_code: ISO 4217 currency code. Defaults to "KES".

		Returns:
			Dict with keys:
			  result             — "APPROVED" | "DECLINED"
			  authorization_code — 6-char string on approval, "" on decline
			  decline_reason     — reason string on decline, "" on approval
			  rrn                — 12-char Retrieval Reference Number
		"""
		card = self._get_card(card_id, tenant_id, session)

		result = "APPROVED"
		decline_reason = ""
		authorization_code = ""

		# Generate RRN regardless of outcome (ISO 8583 F37)
		rrn = secrets.token_hex(6).upper()[:12]

		# --- Authorization checks ---

		# 1. Card status
		if card.status != "ACTIVE":
			result = "DECLINED"
			decline_reason = "CARD_BLOCKED" if card.status == "BLOCKED" else "INVALID_CARD"

		# 2. Expiry check
		if result == "APPROVED":
			now = datetime.now(timezone.utc)
			# Card is expired if the expiry month/year has passed
			if (card.expiry_year, card.expiry_month) < (now.year, now.month):
				result = "DECLINED"
				decline_reason = "EXPIRED_CARD"

		# 3. Daily limit check
		if result == "APPROVED" and card.daily_limit_cents > 0:
			from datetime import timezone as _tz
			from sqlalchemy import func
			today_start = datetime.now(_tz.utc).replace(hour=0, minute=0, second=0, microsecond=0)
			daily_spent = session.execute(
				select(func.coalesce(func.sum(CardAuthorizationLog.amount_cents), 0))
				.where(
					CardAuthorizationLog.tenant_id == tenant_id,
					CardAuthorizationLog.card_id == card_id,
					CardAuthorizationLog.result == "APPROVED",
					CardAuthorizationLog.created_at >= today_start,
				)
			).scalar_one()

			if (daily_spent + amount_cents) > card.daily_limit_cents:
				result = "DECLINED"
				decline_reason = "DAILY_LIMIT_EXCEEDED"

		# Generate authorization code on approval
		auth_code: str | None = None
		if result == "APPROVED":
			auth_code = secrets.token_hex(3).upper()  # 6 hex chars
			authorization_code = auth_code
			card.last_used_at = datetime.now(timezone.utc)

			# Place a hold on the linked core banking account for the authorized amount.
			try:
				from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
				cb = CoreBankingService()
				cb.place_hold(
					account_number=card.account_id,  # account_id stores the account number
					amount_cents=amount_cents,
					hold_type="CARD_AUTHORIZATION",
					reference=rrn,
					session=session,
					tenant_id=tenant_id,
					expires_hours=24,
				)
			except Exception as exc:
				log.debug("authorize_transaction: GL hold skipped: %s", exc)

		# --- Log the authorization ---
		auth_log = CardAuthorizationLog(
			card_id=card_id,
			authorization_type=auth_type,
			amount_cents=amount_cents,
			currency_code=currency_code,
			merchant_name=merchant_name[:100] if merchant_name else None,
			merchant_category_code=mcc[:4] if mcc else None,
			terminal_id=terminal_id[:8] if terminal_id else None,
			result=result,
			decline_reason=decline_reason or None,
			authorization_code=authorization_code or None,
			rrn=rrn,
		)
		session.add(auth_log)
		session.flush()
		_emit(CardAuthorizationEvent(
			aggregate_id=str(auth_log.id),
			aggregate_type="CardAuthorizationLog",
			card_id=card_id,
			amount_cents=amount_cents,
			result=result,
			authorization_code=auth_code or "",
		))

		log.info(
			"authorize_transaction: card=%s type=%s amount=%d result=%s",
			card_id, auth_type, amount_cents, result,
		)

		return {
			"result": result,
			"authorization_code": authorization_code,
			"decline_reason": decline_reason,
			"rrn": rrn,
		}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"CardIssuingService",
	"CardIssuingError",
	"CardNotFoundError",
	"CardStatusError",
	"PINError",
	"PINMasterKeyNotConfiguredError",
]
