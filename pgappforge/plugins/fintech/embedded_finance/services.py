"""
pgappforge/plugins/fintech/embedded_finance/services.py

EmbeddedFinanceService — partner onboarding, product enablement, customer
consent, account provisioning, payment routing, and revenue share.

Security invariants
-------------------
- API keys are generated with secrets.token_hex(32) — 256 bits entropy.
- Only the SHA-256 hash is stored; the raw key is returned once to the caller
  and never persisted.  validate_api_key() hashes the supplied key and looks up
  the hash, so a compromised DB does not expose raw keys.

Money arithmetic
----------------
All amounts are integer cents.  Revenue share uses Decimal multiplication.

Event emission
--------------
All emit_event() calls are wrapped in try/except — failure never rolls back
business transactions.
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from pgappforge.plugins.erp.foundation.commons import (
	emit_event,
	money_multiply,
	hash_sensitive,
)
from pgappforge.plugins.fintech.embedded_finance.models import (
	EmbeddedConsent,
	EmbeddedPartner,
	EmbeddedProduct,
	EmbeddedRevShareRecord,
)
from pgappforge.plugins.fintech.embedded_finance.events import (
	ConsentGrantedEvent,
	EmbeddedTransactionEvent,
	PartnerOnboardedEvent,
	RevShareCalculatedEvent,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class EmbeddedFinanceError(Exception):
	"""Base embedded finance error."""


class PartnerNotFoundError(EmbeddedFinanceError):
	"""No partner matching the given identifier."""


class PartnerSuspendedError(EmbeddedFinanceError):
	"""Partner account is SUSPENDED or TERMINATED."""


class ProductNotEnabledError(EmbeddedFinanceError):
	"""The requested product is not enabled for this partner."""


class ConsentRequiredError(EmbeddedFinanceError):
	"""Customer has not consented to the requested product for this partner."""


class InvalidAPIKeyError(EmbeddedFinanceError):
	"""Supplied API key does not match any active partner."""


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class EmbeddedFinanceService:
	"""Embedded finance service — partner lifecycle, products, consent, payments.

	All methods accept an explicit SQLAlchemy session.
	"""

	def __init__(self, config: dict[str, Any] | None = None) -> None:
		self._config: dict[str, Any] = config or {}

	# -----------------------------------------------------------------------
	# Partner management
	# -----------------------------------------------------------------------

	def register_partner(
		self,
		name: str,
		partner_type: str,
		revenue_share_pct: Decimal | float | str,
		tenant_id: str,
		session: Session,
	) -> tuple[EmbeddedPartner, str]:
		"""Register a new embedded finance partner and issue an API key.

		The raw API key is returned as the second element of the tuple.
		It is shown ONCE and never stored.  The SHA-256 hash is persisted.

		Args:
			name:              Partner company name.
			partner_type:      One of the PARTNER_TYPE constants.
			revenue_share_pct: Revenue share fraction (e.g. Decimal("0.30")).
			tenant_id:         Tenant scope.
			session:           SQLAlchemy session.

		Returns:
			(EmbeddedPartner, raw_api_key)
		"""
		raw_api_key = secrets.token_hex(32)  # 256-bit key
		api_key_hash = hashlib.sha256(raw_api_key.encode()).hexdigest()

		partner = EmbeddedPartner(
			tenant_id=tenant_id,
			name=name,
			partner_type=partner_type,
			api_key_hash=api_key_hash,
			revenue_share_pct=Decimal(str(revenue_share_pct)),
			sandbox_mode=True,
			status="ACTIVE",
			onboarded_at=datetime.now(timezone.utc),
		)
		session.add(partner)
		session.flush()

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = PartnerOnboardedEvent(
				aggregate_type="EmbeddedPartner",
				aggregate_id=partner.id,
				tenant_id=tenant_id,
				payload={"partner_id": partner.id, "name": name},
				partner_id=partner.id,
				partner_name=name,
				partner_type=partner_type,
				sandbox_mode=True,
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning("EmbeddedFinanceService.register_partner: event emit failed (non-fatal): %s", exc)

		log.info(
			"EmbeddedFinanceService.register_partner: partner %s (id=%s, type=%s) registered",
			name,
			partner.id,
			partner_type,
		)
		return partner, raw_api_key

	def validate_api_key(
		self,
		api_key: str,
		tenant_id: str,
		session: Session,
	) -> EmbeddedPartner | None:
		"""Hash the supplied key and look up the matching active partner.

		Returns the EmbeddedPartner or None if not found / not ACTIVE.
		"""
		key_hash = hashlib.sha256(api_key.encode()).hexdigest()
		partner = session.execute(
			select(EmbeddedPartner).where(
				EmbeddedPartner.api_key_hash == key_hash,
				EmbeddedPartner.tenant_id == tenant_id,
				EmbeddedPartner.status == "ACTIVE",
			)
		).scalar_one_or_none()
		return partner

	def suspend_partner(
		self,
		partner_id: str,
		reason: str,
		tenant_id: str,
		session: Session,
	) -> EmbeddedPartner:
		"""Suspend an active partner (status → SUSPENDED).

		Also deactivates all consent records for this partner.
		"""
		partner = self._get_partner(partner_id, tenant_id, session)
		assert partner.status == "ACTIVE", f"Partner {partner_id} is not ACTIVE (status={partner.status})"

		partner.status = "SUSPENDED"
		session.flush()

		# Revoke all active consents
		session.execute(
			sa.update(EmbeddedConsent)
			.where(
				EmbeddedConsent.partner_id == partner_id,
				EmbeddedConsent.tenant_id == tenant_id,
				EmbeddedConsent.is_active.is_(True),
			)
			.values(is_active=False)
		)
		session.flush()

		log.info(
			"EmbeddedFinanceService.suspend_partner: partner %s suspended. reason=%r",
			partner_id,
			reason,
		)
		return partner

	# -----------------------------------------------------------------------
	# Product management
	# -----------------------------------------------------------------------

	def enable_product(
		self,
		partner_id: str,
		product_type: str,
		config: dict,
		tenant_id: str,
		session: Session,
	) -> EmbeddedProduct:
		"""Enable a product for a partner, creating or re-enabling the record.

		Args:
			partner_id:   Target partner.
			product_type: Product type constant.
			config:       Dict with limits, supported_currencies, kyc_tier_required.
			tenant_id:    Tenant scope.
			session:      SQLAlchemy session.

		Returns:
			EmbeddedProduct (enabled).
		"""
		partner = self._get_partner(partner_id, tenant_id, session)
		self._assert_partner_active(partner)

		existing = session.execute(
			select(EmbeddedProduct).where(
				EmbeddedProduct.partner_id == partner_id,
				EmbeddedProduct.product_type == product_type,
				EmbeddedProduct.tenant_id == tenant_id,
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.is_enabled = True
			existing.config = config
			session.flush()
			return existing

		product = EmbeddedProduct(
			tenant_id=tenant_id,
			partner_id=partner_id,
			product_type=product_type,
			is_enabled=True,
			config=config,
		)
		session.add(product)
		session.flush()
		log.info(
			"EmbeddedFinanceService.enable_product: partner=%s product=%s enabled",
			partner_id,
			product_type,
		)
		return product

	# -----------------------------------------------------------------------
	# Consent management
	# -----------------------------------------------------------------------

	def obtain_consent(
		self,
		customer_id: str,
		partner_id: str,
		products: list[str],
		tenant_id: str,
		session: Session,
	) -> EmbeddedConsent:
		"""Record customer consent for a partner's products.

		If an active consent record already exists it is updated with the
		new product list; otherwise a new record is created.

		Args:
			customer_id: UUID of the customer.
			partner_id:  Target partner.
			products:    List of product_type strings being consented to.
			tenant_id:   Tenant scope.
			session:     SQLAlchemy session.

		Returns:
			EmbeddedConsent (active).
		"""
		assert products, "products list must not be empty"
		partner = self._get_partner(partner_id, tenant_id, session)
		self._assert_partner_active(partner)

		existing = session.execute(
			select(EmbeddedConsent).where(
				EmbeddedConsent.customer_id == customer_id,
				EmbeddedConsent.partner_id == partner_id,
				EmbeddedConsent.tenant_id == tenant_id,
				EmbeddedConsent.is_active.is_(True),
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.products_consented = products
			existing.granted_at = datetime.now(timezone.utc)
			session.flush()
			consent = existing
		else:
			consent = EmbeddedConsent(
				tenant_id=tenant_id,
				customer_id=customer_id,
				partner_id=partner_id,
				products_consented=products,
				granted_at=datetime.now(timezone.utc),
				is_active=True,
			)
			session.add(consent)
			session.flush()

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = ConsentGrantedEvent(
				aggregate_type="EmbeddedConsent",
				aggregate_id=consent.id,
				tenant_id=tenant_id,
				payload={"customer_id": customer_id, "partner_id": partner_id},
				consent_id=consent.id,
				customer_id=customer_id,
				partner_id=partner_id,
				products_consented=list(products),
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning("EmbeddedFinanceService.obtain_consent: event emit failed (non-fatal): %s", exc)

		return consent

	def check_consent(
		self,
		customer_id: str,
		partner_id: str,
		product_type: str,
		session: Session,
	) -> bool:
		"""Return True if customer has an active consent covering product_type."""
		from datetime import timezone as _tz
		now = datetime.now(timezone.utc)
		consent = session.execute(
			select(EmbeddedConsent).where(
				EmbeddedConsent.customer_id == customer_id,
				EmbeddedConsent.partner_id == partner_id,
				EmbeddedConsent.is_active.is_(True),
				sa.or_(
					EmbeddedConsent.expires_at.is_(None),
					EmbeddedConsent.expires_at > now,
				),
			)
		).scalar_one_or_none()

		if consent is None:
			return False
		return product_type in (consent.products_consented or [])

	# -----------------------------------------------------------------------
	# Account provisioning / payments
	# -----------------------------------------------------------------------

	def provision_account(
		self,
		customer_id: str,
		partner_id: str,
		tenant_id: str,
		session: Session,
	) -> dict:
		"""Validate consent and provision a bank account via CoreBankingService.

		Args:
			customer_id: UUID of the customer to open the account for.
			partner_id:  Partner initiating the request.
			tenant_id:   Tenant scope.
			session:     SQLAlchemy session.

		Returns:
			Dict with account_number, account_id, status.

		Raises:
			ConsentRequiredError: Customer has not consented to ACCOUNT product.
		"""
		if not self.check_consent(customer_id, partner_id, "ACCOUNT", session):
			raise ConsentRequiredError(
				f"Customer {customer_id} has not consented to ACCOUNT product "
				f"for partner {partner_id}"
			)

		from pgappforge.plugins.fintech.core_banking.services import CoreBankingService
		cb_svc = CoreBankingService()
		product_code = self._config.get("EMB_DEFAULT_ACCOUNT_PRODUCT", "CURRENT")
		account = cb_svc.open_account(
			session=session,
			customer_id=customer_id,
			product_code=product_code,
			opening_deposit_cents=0,
			tenant_id=tenant_id,
		)
		session.flush()

		result = {
			"account_id": account.id,
			"account_number": account.account_number,
			"status": account.status,
			"product_code": product_code,
		}

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = EmbeddedTransactionEvent(
				aggregate_type="EmbeddedPartner",
				aggregate_id=partner_id,
				tenant_id=tenant_id,
				payload={"customer_id": customer_id, "account_id": account.id},
				partner_id=partner_id,
				customer_id=customer_id,
				transaction_type="ACCOUNT_PROVISION",
				amount_cents=0,
				currency=self._config.get("EMB_DEFAULT_CURRENCY", "KES"),
				reference=account.account_number,
				status="COMPLETED",
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning("EmbeddedFinanceService.provision_account: event emit failed (non-fatal): %s", exc)

		log.info(
			"EmbeddedFinanceService.provision_account: customer=%s account=%s via partner=%s",
			customer_id,
			account.account_number,
			partner_id,
		)
		return result

	def process_embedded_payment(
		self,
		customer_id: str,
		partner_id: str,
		amount_cents: int,
		currency: str,
		reference: str,
		tenant_id: str,
		session: Session,
	) -> dict:
		"""Validate PAYMENTS consent and route transaction through the payments plugin.

		Args:
			customer_id:  UUID of the paying customer.
			partner_id:   Partner initiating the payment.
			amount_cents: Payment amount in minor currency units.
			currency:     ISO 4217 currency code.
			reference:    External reference (must be unique).
			tenant_id:    Tenant scope.
			session:      SQLAlchemy session.

		Returns:
			Dict with reference, status, amount_cents.

		Raises:
			ConsentRequiredError: Customer has not consented to PAYMENTS product.
		"""
		assert amount_cents > 0, "amount_cents must be positive"
		if not self.check_consent(customer_id, partner_id, "PAYMENTS", session):
			raise ConsentRequiredError(
				f"Customer {customer_id} has not consented to PAYMENTS product "
				f"for partner {partner_id}"
			)

		# Route through payments plugin (non-fatal fallback if unavailable)
		payment_result: dict = {}
		try:
			from pgappforge.plugins.fintech.payments.services import PaymentsService  # type: ignore
			py_svc = PaymentsService()
			payment_result = py_svc.initiate_payment(
				session=session,
				tenant_id=tenant_id,
				amount_cents=amount_cents,
				currency_code=currency,
				reference_number=reference,
				channel="EMBEDDED",
				initiated_by=customer_id,
			)
		except (ImportError, Exception) as exc:
			log.warning(
				"EmbeddedFinanceService.process_embedded_payment: payments plugin unavailable: %s",
				exc,
			)
			payment_result = {
				"reference": reference,
				"status": "PENDING",
				"amount_cents": amount_cents,
			}

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = EmbeddedTransactionEvent(
				aggregate_type="EmbeddedPartner",
				aggregate_id=partner_id,
				tenant_id=tenant_id,
				payload={"reference": reference, "amount_cents": amount_cents},
				partner_id=partner_id,
				customer_id=customer_id,
				transaction_type="PAYMENT",
				amount_cents=amount_cents,
				currency=currency,
				reference=reference,
				status=payment_result.get("status", "PENDING"),
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning(
				"EmbeddedFinanceService.process_embedded_payment: event emit failed (non-fatal): %s",
				exc,
			)

		return {
			"reference": reference,
			"status": payment_result.get("status", "PENDING"),
			"amount_cents": amount_cents,
			"currency": currency,
		}

	# -----------------------------------------------------------------------
	# Revenue share
	# -----------------------------------------------------------------------

	def calculate_revenue_share(
		self,
		partner_id: str,
		period: str,
		gross_revenue_cents: int,
		product_type: str,
		tenant_id: str,
		session: Session,
	) -> EmbeddedRevShareRecord:
		"""Compute and persist a revenue share record for a partner + period + product.

		partner_share_cents = gross_revenue_cents × revenue_share_pct
		net_cents           = gross_revenue_cents − partner_share_cents

		The record is immutable once written; call for a (partner, period,
		product_type) combination that does not yet exist.

		Args:
			partner_id:          Target partner.
			period:              YYYY-MM.
			gross_revenue_cents: Total gross revenue for the product in the period.
			product_type:        Product type constant.
			tenant_id:           Tenant scope.
			session:             SQLAlchemy session.

		Returns:
			EmbeddedRevShareRecord (flushed).
		"""
		assert len(period) == 7 and period[4] == "-", f"period must be YYYY-MM, got {period!r}"
		assert gross_revenue_cents >= 0, "gross_revenue_cents must be non-negative"

		partner = self._get_partner(partner_id, tenant_id, session)
		share_pct = Decimal(str(partner.revenue_share_pct))
		partner_share = money_multiply(gross_revenue_cents, share_pct)
		net = max(0, gross_revenue_cents - partner_share)

		record = EmbeddedRevShareRecord(
			tenant_id=tenant_id,
			partner_id=partner_id,
			period=period,
			product_type=product_type,
			gross_revenue_cents=gross_revenue_cents,
			partner_share_cents=partner_share,
			net_cents=net,
		)
		session.add(record)
		session.flush()

		try:
			from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed
			ev = RevShareCalculatedEvent(
				aggregate_type="EmbeddedRevShareRecord",
				aggregate_id=record.id,
				tenant_id=tenant_id,
				payload={"partner_id": partner_id, "period": period, "product_type": product_type},
				rev_share_id=record.id,
				partner_id=partner_id,
				period=period,
				product_type=product_type,
				gross_revenue_cents=gross_revenue_cents,
				partner_share_cents=partner_share,
				net_cents=net,
			)
			_emit_typed(ev, session)
		except Exception as exc:
			log.warning(
				"EmbeddedFinanceService.calculate_revenue_share: event emit failed (non-fatal): %s",
				exc,
			)

		log.info(
			"EmbeddedFinanceService.calculate_revenue_share: partner=%s period=%s product=%s "
			"gross=%d share=%d net=%d",
			partner_id,
			period,
			product_type,
			gross_revenue_cents,
			partner_share,
			net,
		)
		return record

	# -----------------------------------------------------------------------
	# Internal helpers
	# -----------------------------------------------------------------------

	def _get_partner(self, partner_id: str, tenant_id: str, session: Session) -> EmbeddedPartner:
		partner = session.execute(
			select(EmbeddedPartner).where(
				EmbeddedPartner.id == partner_id,
				EmbeddedPartner.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if partner is None:
			raise PartnerNotFoundError(f"EmbeddedPartner {partner_id} not found for tenant {tenant_id}")
		return partner

	@staticmethod
	def _assert_partner_active(partner: EmbeddedPartner) -> None:
		if partner.status not in ("ACTIVE",):
			raise PartnerSuspendedError(
				f"Partner {partner.id} is not ACTIVE (status={partner.status})"
			)


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register(
		"embedded.provision_account",
		"Provision a bank account for a customer via an embedded finance partner",
	)
	def _bpm_provision_account(record_ctx, session, **kw):
		svc = EmbeddedFinanceService(record_ctx.get("config"))
		return svc.provision_account(
			customer_id=kw["customer_id"],
			partner_id=kw["partner_id"],
			tenant_id=record_ctx.get("tenant_id", ""),
			session=session,
		)

	@_BPMReg.register(
		"embedded.process_payment",
		"Process an embedded payment on behalf of a customer via a partner",
	)
	def _bpm_process_payment(record_ctx, session, **kw):
		svc = EmbeddedFinanceService(record_ctx.get("config"))
		return svc.process_embedded_payment(
			customer_id=kw["customer_id"],
			partner_id=kw["partner_id"],
			amount_cents=int(kw["amount_cents"]),
			currency=kw.get("currency", "KES"),
			reference=kw["reference"],
			tenant_id=record_ctx.get("tenant_id", ""),
			session=session,
		)

except (ImportError, Exception):
	pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"EmbeddedFinanceService",
	"EmbeddedFinanceError",
	"PartnerNotFoundError",
	"PartnerSuspendedError",
	"ProductNotEnabledError",
	"ConsentRequiredError",
	"InvalidAPIKeyError",
]
