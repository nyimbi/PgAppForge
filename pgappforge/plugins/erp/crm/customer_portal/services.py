"""
pgappforge/plugins/erp/crm/customer_portal/services.py

CustomerPortalService — self-service portal for AR customers.

Security posture
----------------
- Passwords: bcrypt (preferred) with SHA-256 fallback.
- Session tokens: cryptographically random 32-byte hex; only SHA-256 hash stored.
- Account lockout: 5 consecutive failures → 30-minute lock.
- Timing safety: password verification always runs even when user is not found.

BPM actions registered
----------------------
  crm.customer_portal.initiate_payment — submit payment from self-service portal
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import sqlalchemy as sa

from pgappforge.plugins.erp.foundation.events import emit_event
from pgappforge.plugins.erp.crm.customer_portal.events import (
	CustomerPortalLoginEvent,
	CustomerPortalRegisteredEvent,
	PortalPasswordResetEvent,
	PortalPaymentInitiatedEvent,
	PortalStatementDownloadedEvent,
)
from pgappforge.plugins.erp.crm.customer_portal.models import (
	CustomerPortalUser,
	PortalPayment,
	PortalSession,
)
from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)

_SESSION_TTL_HOURS = 8
_MAX_FAILED_LOGINS = 5
_LOCKOUT_MINUTES = 30


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class CustomerPortalError(Exception):
	"""Base error for portal operations."""


class CustomerPortalNotFoundError(CustomerPortalError):
	"""Raised when a user/session cannot be found."""


class CustomerPortalAuthError(CustomerPortalError):
	"""Raised for authentication failures (account locked, etc.)."""


class CustomerPortalValidationError(CustomerPortalError):
	"""Raised for constraint violations."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
	return datetime.now(tz=timezone.utc)


def _new_id() -> str:
	return str(uuid4())


def _emit(event: Any, session: Any = None) -> None:
	try:
		emit_event(event, session)
	except Exception as exc:
		log.debug("_emit suppressed: %s", exc)


def _hash_token(raw: str) -> str:
	"""SHA-256 hash of a raw session token for safe storage."""
	return hashlib.sha256(raw.encode()).hexdigest()


def _hash_password(password: str) -> str:
	"""bcrypt hash with SHA-256 fallback when bcrypt is unavailable."""
	try:
		import bcrypt  # type: ignore[import]
		return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
	except ImportError:
		log.debug("bcrypt unavailable; falling back to SHA-256 for password hash")
		return hashlib.sha256(password.encode()).hexdigest()


def _verify_password(password: str, hashed: str) -> bool:
	"""Verify *password* against *hashed*.

	Uses bcrypt.checkpw when available; falls back to SHA-256 via
	secrets.compare_digest (constant-time).
	"""
	try:
		import bcrypt  # type: ignore[import]
		# bcrypt hashes start with $2b$ or $2a$
		if hashed.startswith("$2"):
			return bcrypt.checkpw(password.encode(), hashed.encode())
	except ImportError:
		pass
	# SHA-256 fallback
	candidate = hashlib.sha256(password.encode()).hexdigest()
	return secrets.compare_digest(candidate, hashed)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class CustomerPortalService:
	"""Manages the customer self-service portal lifecycle.

	All methods accept a SQLAlchemy Session (positional or keyword as *session*
	or *db_session* for signature consistency with the spec).  Callers manage
	transaction boundaries.
	"""

	# ------------------------------------------------------------------
	# Registration
	# ------------------------------------------------------------------

	def register_portal_user(
		self,
		customer_id: str,
		email: str,
		password: str,
		tenant_id: str,
		session: Any,
	) -> CustomerPortalUser:
		"""Create a portal account for *customer_id*.

		Raises CustomerPortalValidationError if a portal user already exists
		for this customer in the tenant.
		"""
		existing = session.execute(
			sa.select(CustomerPortalUser).where(
				CustomerPortalUser.tenant_id == tenant_id,
				CustomerPortalUser.customer_id == customer_id,
			)
		).scalar_one_or_none()
		if existing is not None:
			raise CustomerPortalValidationError(
				f"Portal user already exists for customer {customer_id!r} in tenant {tenant_id!r}"
			)

		user = CustomerPortalUser(
			id=_new_id(),
			tenant_id=tenant_id,
			customer_id=customer_id,
			email=email.lower().strip(),
			password_hash=_hash_password(password),
		)
		session.add(user)
		session.flush()

		_emit(
			CustomerPortalRegisteredEvent(
				aggregate_id=user.id,
				aggregate_type="CustomerPortalUser",
				tenant_id=tenant_id,
				user_id=user.id,
				customer_id=customer_id,
				email=user.email,
			),
			session,
		)
		log.info(
			"CustomerPortalService.register: user=%s customer=%s tenant=%s",
			user.id, customer_id, tenant_id,
		)
		return user

	# ------------------------------------------------------------------
	# Authentication
	# ------------------------------------------------------------------

	def authenticate(
		self,
		email: str,
		password: str,
		tenant_id: str,
		session: Any,
		*,
		ip_address: str = "",
	) -> str | None:
		"""Authenticate by email + password.

		Returns a raw session token string on success, or None on failure.
		Raises CustomerPortalAuthError when the account is locked.

		Always runs password verification even when user is not found to
		prevent timing-based user enumeration.
		"""
		user: CustomerPortalUser | None = session.execute(
			sa.select(CustomerPortalUser).where(
				CustomerPortalUser.tenant_id == tenant_id,
				CustomerPortalUser.email == email.lower().strip(),
			)
		).scalar_one_or_none()

		# Timing-safe: always verify to prevent enumeration
		dummy_hash = _hash_password("__dummy__")
		candidate_hash = user.password_hash if user else dummy_hash

		if user is None:
			_verify_password(password, candidate_hash)
			return None

		# Lockout check
		if user.locked_until and user.locked_until > _now():
			raise CustomerPortalAuthError(
				f"Account locked until {user.locked_until.isoformat()}"
			)

		if not _verify_password(password, user.password_hash):
			user.failed_login_count = (user.failed_login_count or 0) + 1
			if user.failed_login_count >= _MAX_FAILED_LOGINS:
				user.locked_until = _now() + timedelta(minutes=_LOCKOUT_MINUTES)
				log.warning(
					"CustomerPortalService.authenticate: account locked user=%s", user.id
				)
			session.flush()
			return None

		# Success path
		user.failed_login_count = 0
		user.locked_until = None
		user.last_login_at = _now()

		raw_token = secrets.token_hex(32)
		ps = PortalSession(
			id=_new_id(),
			tenant_id=tenant_id,
			user_id=user.id,
			session_token_hash=_hash_token(raw_token),
			expires_at=_now() + timedelta(hours=_SESSION_TTL_HOURS),
			ip_address=ip_address or None,
		)
		session.add(ps)
		session.flush()

		_emit(
			CustomerPortalLoginEvent(
				aggregate_id=user.id,
				aggregate_type="CustomerPortalUser",
				tenant_id=tenant_id,
				user_id=user.id,
				customer_id=user.customer_id,
				ip_address=ip_address,
			),
			session,
		)
		return raw_token

	# ------------------------------------------------------------------
	# Session validation (internal)
	# ------------------------------------------------------------------

	def _validate_session(self, session_token: str, db_session: Any) -> PortalSession:
		"""Load and validate a PortalSession by raw token.

		Raises CustomerPortalAuthError on invalid / expired / revoked token.
		"""
		token_hash = _hash_token(session_token)
		ps: PortalSession | None = db_session.execute(
			sa.select(PortalSession).where(PortalSession.session_token_hash == token_hash)
		).scalar_one_or_none()
		if ps is None:
			raise CustomerPortalAuthError("Invalid session token")
		if ps.is_revoked:
			raise CustomerPortalAuthError("Session has been revoked")
		if ps.expires_at < _now():
			raise CustomerPortalAuthError("Session has expired")
		return ps

	# ------------------------------------------------------------------
	# Dashboard
	# ------------------------------------------------------------------

	def get_customer_dashboard(self, session_token: str, db_session: Any) -> dict[str, Any]:
		"""Return aggregated dashboard data for the authenticated customer.

		Attempts to pull live AR stats via ARService when available; falls back
		to empty structures on ImportError.
		"""
		ps = self._validate_session(session_token, db_session)
		user: CustomerPortalUser = db_session.execute(
			sa.select(CustomerPortalUser).where(CustomerPortalUser.id == ps.user_id)
		).scalar_one()

		ar_data: dict[str, Any] = {
			"outstanding_cents": 0,
			"overdue_cents": 0,
			"aging": {},
			"recent_invoices": [],
			"open_orders": [],
		}
		try:
			from pgappforge.plugins.erp.finance.ar.services import ARService
			svc = ARService()
			customer = svc.get_customer_by_id(user.customer_id, user.tenant_id, db_session)
			if customer is not None:
				ar_data["outstanding_cents"] = getattr(customer, "outstanding_cents", 0)
				ar_data["overdue_cents"] = getattr(customer, "overdue_cents", 0)
		except Exception as exc:
			log.debug("get_customer_dashboard: ARService unavailable: %s", exc)

		return {
			"customer_id": user.customer_id,
			**ar_data,
		}

	# ------------------------------------------------------------------
	# Invoices
	# ------------------------------------------------------------------

	def get_invoices(
		self,
		session_token: str,
		db_session: Any,
		*,
		status_filter: str | None = None,
	) -> list[dict[str, Any]]:
		"""Return AR invoices for the authenticated customer.

		Delegates to ARService when available; returns empty list otherwise.
		"""
		ps = self._validate_session(session_token, db_session)
		user: CustomerPortalUser = db_session.execute(
			sa.select(CustomerPortalUser).where(CustomerPortalUser.id == ps.user_id)
		).scalar_one()

		try:
			from pgappforge.plugins.erp.finance.ar.services import ARService
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice
			svc = ARService()
			stmt = sa.select(ARInvoice).where(
				ARInvoice.customer_id == user.customer_id,
			)
			if status_filter:
				stmt = stmt.where(ARInvoice.status == status_filter)
			invoices = list(db_session.execute(stmt).scalars())
			return [
				{
					"id": inv.id,
					"invoice_number": inv.invoice_number,
					"date": inv.invoice_date.isoformat() if getattr(inv, "invoice_date", None) else None,
					"due_date": inv.due_date.isoformat() if getattr(inv, "due_date", None) else None,
					"total_cents": getattr(inv, "total_cents", 0),
					"balance_cents": getattr(inv, "balance_due_cents", 0),
					"status": inv.status,
				}
				for inv in invoices
			]
		except Exception as exc:
			log.debug("get_invoices: ARService unavailable: %s", exc)
			return []

	# ------------------------------------------------------------------
	# Statement download
	# ------------------------------------------------------------------

	def download_statement(
		self,
		session_token: str,
		from_date: str,
		to_date: str,
		db_session: Any,
	) -> dict[str, Any]:
		"""Return a structured account statement dict for the given date range.

		from_date / to_date: ISO date strings (YYYY-MM-DD).
		"""
		ps = self._validate_session(session_token, db_session)
		user: CustomerPortalUser = db_session.execute(
			sa.select(CustomerPortalUser).where(CustomerPortalUser.id == ps.user_id)
		).scalar_one()

		statement: dict[str, Any] = {
			"customer_id": user.customer_id,
			"from_date": from_date,
			"to_date": to_date,
			"invoices": [],
			"payments": [],
			"opening_balance_cents": 0,
			"closing_balance_cents": 0,
		}

		try:
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice, ARPayment
			from datetime import date as _date
			from_d = _date.fromisoformat(from_date)
			to_d = _date.fromisoformat(to_date)

			invoices = list(db_session.execute(
				sa.select(ARInvoice).where(
					ARInvoice.customer_id == user.customer_id,
					ARInvoice.invoice_date >= from_d,
					ARInvoice.invoice_date <= to_d,
				)
			).scalars())
			payments = list(db_session.execute(
				sa.select(ARPayment).where(
					ARPayment.customer_id == user.customer_id,
					ARPayment.payment_date >= from_d,
					ARPayment.payment_date <= to_d,
				)
			).scalars())

			statement["invoices"] = [
				{
					"id": inv.id,
					"invoice_number": inv.invoice_number,
					"date": inv.invoice_date.isoformat(),
					"total_cents": getattr(inv, "total_cents", 0),
					"status": inv.status,
				}
				for inv in invoices
			]
			statement["payments"] = [
				{
					"id": pmt.id,
					"date": pmt.payment_date.isoformat() if getattr(pmt, "payment_date", None) else None,
					"amount_cents": getattr(pmt, "amount_cents", 0),
					"method": getattr(pmt, "payment_method", ""),
				}
				for pmt in payments
			]
		except Exception as exc:
			log.debug("download_statement: AR models unavailable: %s", exc)

		_emit(
			PortalStatementDownloadedEvent(
				aggregate_id=user.id,
				aggregate_type="CustomerPortalUser",
				tenant_id=user.tenant_id or "",
				customer_id=user.customer_id,
				from_date=from_date,
				to_date=to_date,
			),
			db_session,
		)
		return statement

	# ------------------------------------------------------------------
	# Payment initiation
	# ------------------------------------------------------------------

	def initiate_payment(
		self,
		session_token: str,
		invoice_ids: list[str],
		amount_cents: int,
		payment_method: str,
		db_session: Any,
		*,
		reference: str | None = None,
	) -> PortalPayment:
		"""Create a PENDING portal payment record.

		payment_method: MOBILE_MONEY | BANK_TRANSFER | CARD
		"""
		assert amount_cents > 0, "amount_cents must be positive"
		assert payment_method in ("MOBILE_MONEY", "BANK_TRANSFER", "CARD"), (
			f"Invalid payment_method {payment_method!r}"
		)

		ps = self._validate_session(session_token, db_session)
		user: CustomerPortalUser = db_session.execute(
			sa.select(CustomerPortalUser).where(CustomerPortalUser.id == ps.user_id)
		).scalar_one()

		payment = PortalPayment(
			id=_new_id(),
			tenant_id=user.tenant_id,
			customer_id=user.customer_id,
			invoice_ids=invoice_ids,
			amount_cents=amount_cents,
			payment_method=payment_method,
			reference=reference,
			status="PENDING",
			initiated_at=_now(),
		)
		db_session.add(payment)
		db_session.flush()

		_emit(
			PortalPaymentInitiatedEvent(
				aggregate_id=payment.id,
				aggregate_type="PortalPayment",
				tenant_id=user.tenant_id or "",
				payment_id=payment.id,
				customer_id=user.customer_id,
				amount_cents=amount_cents,
				method=payment_method,
			),
			db_session,
		)
		log.info(
			"CustomerPortalService.initiate_payment: payment=%s customer=%s amount=%d method=%s",
			payment.id, user.customer_id, amount_cents, payment_method,
		)
		return payment

	# ------------------------------------------------------------------
	# Logout
	# ------------------------------------------------------------------

	def logout(self, session_token: str, db_session: Any) -> None:
		"""Revoke the portal session."""
		ps = self._validate_session(session_token, db_session)
		ps.is_revoked = True
		db_session.flush()
		log.debug("CustomerPortalService.logout: session=%s revoked", ps.id)

	# ------------------------------------------------------------------
	# Password reset
	# ------------------------------------------------------------------

	def reset_password(
		self,
		user_id: str,
		new_password: str,
		db_session: Any,
	) -> CustomerPortalUser:
		"""Set a new password for *user_id* and revoke all active sessions."""
		user: CustomerPortalUser | None = db_session.execute(
			sa.select(CustomerPortalUser).where(CustomerPortalUser.id == user_id)
		).scalar_one_or_none()
		if user is None:
			raise CustomerPortalNotFoundError(f"Portal user {user_id!r} not found")

		user.password_hash = _hash_password(new_password)
		user.failed_login_count = 0
		user.locked_until = None

		# Revoke all active sessions
		db_session.execute(
			sa.update(PortalSession)
			.where(PortalSession.user_id == user_id, PortalSession.is_revoked.is_(False))
			.values(is_revoked=True)
		)
		db_session.flush()

		_emit(
			PortalPasswordResetEvent(
				aggregate_id=user.id,
				aggregate_type="CustomerPortalUser",
				tenant_id=user.tenant_id or "",
				user_id=user.id,
				customer_id=user.customer_id,
			),
			db_session,
		)
		return user


# ---------------------------------------------------------------------------
# BPM action registration
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"crm.customer_portal.initiate_payment",
	"Initiate customer payment from self-service portal",
)
def _bpm_initiate_payment(
	record_ctx: dict,
	session: Any,
	session_token: str = "",
	invoice_ids: list | None = None,
	amount_cents: int = 0,
	payment_method: str = "BANK_TRANSFER",
	reference: str | None = None,
	**kw: Any,
) -> dict:
	try:
		svc = CustomerPortalService()
		payment = svc.initiate_payment(
			session_token,
			invoice_ids or [],
			amount_cents,
			payment_method,
			session,
			reference=reference,
		)
		return {"status": "ok", "payment_id": payment.id, "payment_status": payment.status}
	except Exception as exc:
		return {"status": "error", "message": str(exc)}


__all__ = [
	"CustomerPortalService",
	"CustomerPortalError",
	"CustomerPortalNotFoundError",
	"CustomerPortalAuthError",
	"CustomerPortalValidationError",
]
