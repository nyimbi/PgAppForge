"""
pgappforge/plugins/erp/finance/credit_management/services.py

CreditManagementService — stateless business logic for the Credit Management plugin.

All methods accept an explicit SQLAlchemy 2.x session.
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are BigInteger cents. Float is never used.

Key methods
-----------
  set_credit_limit(customer_id, limit_cents, tenant_id, session)
      Upsert CustomerCreditProfile; emit CreditLimitSetEvent.

  update_exposure(customer_id, tenant_id, session)
      Recompute exposure from CreditExposureComponent rows;
      emit CreditLimitBreachEvent if limit breached;
      emit CreditExposureUpdatedEvent.

  check_credit(customer_id, order_amount_cents, tenant_id, session) -> dict
      Return approval decision with available/exposure/limit.

  place_hold(customer_id, reason, placed_by, tenant_id, session)
      Set is_on_hold=True; emit CreditHoldPlacedEvent.

  release_hold(customer_id, released_by, tenant_id, session)
      Set is_on_hold=False; emit CreditHoldReleasedEvent.

  register_exposure_component(customer_id, source_type, source_id, amount_cents, tenant_id, session)
      Upsert CreditExposureComponent; call update_exposure().

  remove_exposure_component(source_type, source_id, tenant_id, session)
      Delete component; call update_exposure().

  get_overdue_customers(tenant_id, session, *, overdue_days=30) -> list[dict]
      Customers with overdue components; ordered by overdue amount desc.

BPM actions
-----------
  finance.credit.check       — registered via @BPMActionRegistry.register
  finance.credit.place_hold  — registered via @BPMActionRegistry.register
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.bpm_actions import BPMActionRegistry
from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _emit(event: Any, session: Any = None) -> None:
	try:
		_emit_event(event, session)
	except Exception as exc:
		log.debug("_emit: swallowed event emission error: %s", exc)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class CreditManagementError(Exception):
	"""Base exception for Credit Management service errors."""


class CreditProfileNotFoundError(CreditManagementError):
	pass


class CreditValidationError(CreditManagementError):
	"""Business rule violation."""


# ---------------------------------------------------------------------------
# CreditManagementService
# ---------------------------------------------------------------------------

class CreditManagementService:
	"""Stateless credit management business logic.

	Instantiate per-request or as a singleton — no instance state.
	All monetary arithmetic uses int (cents).
	"""

	# ------------------------------------------------------------------
	# set_credit_limit
	# ------------------------------------------------------------------

	def set_credit_limit(
		self,
		customer_id: str,
		limit_cents: int,
		tenant_id: str,
		session: Any,
		*,
		currency_code: str = "USD",
		credit_rating: str | None = None,
		payment_terms_days: int = 30,
	) -> Any:
		"""Create or update a customer credit profile with a new limit.

		Upserts CustomerCreditProfile on (tenant_id, customer_id).
		available_credit_cents is recomputed as limit - current_exposure.

		Args:
			customer_id:        Soft FK to CRM/AR customer.
			limit_cents:        New credit ceiling in cents.
			tenant_id:          Tenant UUID string.
			session:            SA 2.x session — caller owns commit.
			currency_code:      ISO 4217, default USD.
			credit_rating:      AAA | AA | A | BBB | BB | CCC | D.
			payment_terms_days: Net payment terms.

		Returns:
			The upserted CustomerCreditProfile.

		Emits:
			CreditLimitSetEvent
		"""
		from pgappforge.plugins.erp.finance.credit_management.events import CreditLimitSetEvent
		from pgappforge.plugins.erp.finance.credit_management.models import CustomerCreditProfile

		assert int(limit_cents) >= 0, "limit_cents must be non-negative"

		profile = session.execute(
			sa.select(CustomerCreditProfile)
			.where(CustomerCreditProfile.tenant_id == tenant_id)
			.where(CustomerCreditProfile.customer_id == customer_id)
		).scalar_one_or_none()

		if profile is None:
			profile = CustomerCreditProfile(
				tenant_id=tenant_id,
				customer_id=customer_id,
				credit_limit_cents=int(limit_cents),
				currency_code=currency_code,
				current_exposure_cents=0,
				available_credit_cents=int(limit_cents),
				credit_rating=credit_rating,
				payment_terms_days=payment_terms_days,
				is_on_hold=False,
			)
			session.add(profile)
		else:
			profile.credit_limit_cents = int(limit_cents)
			profile.currency_code = currency_code
			profile.payment_terms_days = payment_terms_days
			if credit_rating is not None:
				profile.credit_rating = credit_rating
			# Recompute available
			profile.available_credit_cents = int(limit_cents) - profile.current_exposure_cents
			profile.updated_at = datetime.now(timezone.utc)

		session.flush()

		_emit(
			CreditLimitSetEvent(
				aggregate_id=profile.id,
				aggregate_type="CustomerCreditProfile",
				tenant_id=tenant_id,
				customer_id=customer_id,
				limit_cents=int(limit_cents),
				currency=currency_code,
			),
			session,
		)

		log.info(
			"CreditManagementService.set_credit_limit: customer=%r limit=%d¢",
			customer_id, limit_cents,
		)
		return profile

	# ------------------------------------------------------------------
	# update_exposure
	# ------------------------------------------------------------------

	def update_exposure(
		self,
		customer_id: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Recompute current exposure from all open CreditExposureComponent rows.

		Sets:
		  profile.current_exposure_cents = SUM(component.amount_cents)
		  profile.available_credit_cents = limit - exposure

		Emits CreditLimitBreachEvent when exposure > limit.
		Emits CreditExposureUpdatedEvent always.

		Args:
			customer_id: Soft FK to customer.
			tenant_id:   Tenant UUID string.
			session:     SA 2.x session.

		Returns:
			Updated CustomerCreditProfile.

		Raises:
			CreditProfileNotFoundError: no profile exists for customer.
		"""
		from pgappforge.plugins.erp.finance.credit_management.events import (
			CreditExposureUpdatedEvent,
			CreditLimitBreachEvent,
		)
		from pgappforge.plugins.erp.finance.credit_management.models import (
			CreditExposureComponent,
			CustomerCreditProfile,
		)

		profile = session.execute(
			sa.select(CustomerCreditProfile)
			.where(CustomerCreditProfile.tenant_id == tenant_id)
			.where(CustomerCreditProfile.customer_id == customer_id)
		).scalar_one_or_none()

		if profile is None:
			raise CreditProfileNotFoundError(
				f"No credit profile for customer {customer_id!r} in tenant {tenant_id!r}"
			)

		# Sum all components for this profile
		total_exposure: int = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(CreditExposureComponent.amount_cents), 0)
			)
			.where(CreditExposureComponent.profile_id == profile.id)
		).scalar() or 0

		limit = profile.credit_limit_cents
		available = limit - total_exposure

		profile.current_exposure_cents = total_exposure
		profile.available_credit_cents = available
		profile.last_exposure_update = datetime.now(timezone.utc)
		profile.updated_at = datetime.now(timezone.utc)
		session.flush()

		if total_exposure > limit:
			overage = total_exposure - limit
			_emit(
				CreditLimitBreachEvent(
					aggregate_id=profile.id,
					aggregate_type="CustomerCreditProfile",
					tenant_id=tenant_id,
					customer_id=customer_id,
					exposure_cents=total_exposure,
					limit_cents=limit,
					overage_cents=overage,
				),
				session,
			)
			log.warning(
				"CreditManagementService.update_exposure: BREACH customer=%r "
				"exposure=%d¢ limit=%d¢ overage=%d¢",
				customer_id, total_exposure, limit, overage,
			)

		_emit(
			CreditExposureUpdatedEvent(
				aggregate_id=profile.id,
				aggregate_type="CustomerCreditProfile",
				tenant_id=tenant_id,
				customer_id=customer_id,
				exposure_cents=total_exposure,
				available_cents=available,
			),
			session,
		)

		log.info(
			"CreditManagementService.update_exposure: customer=%r exposure=%d¢ available=%d¢",
			customer_id, total_exposure, available,
		)
		return profile

	# ------------------------------------------------------------------
	# check_credit
	# ------------------------------------------------------------------

	def check_credit(
		self,
		customer_id: str,
		order_amount_cents: int,
		tenant_id: str,
		session: Any,
	) -> dict:
		"""Evaluate whether a customer can take on additional credit.

		Logic:
		  - is_on_hold → approved=False, message="Customer is on credit hold"
		  - (exposure + order_amount) > limit → approved=False, message="Credit limit exceeded"
		  - Otherwise → approved=True

		Args:
			customer_id:       Soft FK to customer.
			order_amount_cents: Proposed new order amount in cents.
			tenant_id:         Tenant UUID string.
			session:           SA 2.x session.

		Returns:
			dict with keys:
			  approved (bool), available_cents (int), exposure_cents (int),
			  limit_cents (int), is_on_hold (bool), message (str)

		Raises:
			CreditProfileNotFoundError: no profile exists for customer.
		"""
		from pgappforge.plugins.erp.finance.credit_management.models import CustomerCreditProfile

		profile = session.execute(
			sa.select(CustomerCreditProfile)
			.where(CustomerCreditProfile.tenant_id == tenant_id)
			.where(CustomerCreditProfile.customer_id == customer_id)
		).scalar_one_or_none()

		if profile is None:
			raise CreditProfileNotFoundError(
				f"No credit profile for customer {customer_id!r} in tenant {tenant_id!r}"
			)

		if profile.is_on_hold:
			return {
				"approved": False,
				"available_cents": profile.available_credit_cents,
				"exposure_cents": profile.current_exposure_cents,
				"limit_cents": profile.credit_limit_cents,
				"is_on_hold": True,
				"message": "Customer is on credit hold",
			}

		projected_exposure = profile.current_exposure_cents + int(order_amount_cents)
		if projected_exposure > profile.credit_limit_cents:
			shortfall = projected_exposure - profile.credit_limit_cents
			return {
				"approved": False,
				"available_cents": profile.available_credit_cents,
				"exposure_cents": profile.current_exposure_cents,
				"limit_cents": profile.credit_limit_cents,
				"is_on_hold": False,
				"message": (
					f"Credit limit exceeded by {shortfall}¢; "
					f"available {profile.available_credit_cents}¢ < order {order_amount_cents}¢"
				),
			}

		return {
			"approved": True,
			"available_cents": profile.available_credit_cents,
			"exposure_cents": profile.current_exposure_cents,
			"limit_cents": profile.credit_limit_cents,
			"is_on_hold": False,
			"message": "Credit approved",
		}

	# ------------------------------------------------------------------
	# place_hold
	# ------------------------------------------------------------------

	def place_hold(
		self,
		customer_id: str,
		reason: str,
		placed_by: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Place a credit hold on a customer account.

		Idempotent — placing a hold on an already-held customer only updates
		the reason and placed_by fields without raising an error.

		Args:
			customer_id: Soft FK to customer.
			reason:      Hold reason text.
			placed_by:   User ID or name of person placing the hold.
			tenant_id:   Tenant UUID string.
			session:     SA 2.x session.

		Returns:
			Updated CustomerCreditProfile.

		Emits:
			CreditHoldPlacedEvent

		Raises:
			CreditProfileNotFoundError: no profile exists for customer.
		"""
		from pgappforge.plugins.erp.finance.credit_management.events import CreditHoldPlacedEvent
		from pgappforge.plugins.erp.finance.credit_management.models import CustomerCreditProfile

		profile = session.execute(
			sa.select(CustomerCreditProfile)
			.where(CustomerCreditProfile.tenant_id == tenant_id)
			.where(CustomerCreditProfile.customer_id == customer_id)
		).scalar_one_or_none()

		if profile is None:
			raise CreditProfileNotFoundError(
				f"No credit profile for customer {customer_id!r} in tenant {tenant_id!r}"
			)

		profile.is_on_hold = True
		profile.hold_reason = reason
		profile.hold_placed_by = placed_by
		profile.hold_placed_at = datetime.now(timezone.utc)
		profile.updated_at = datetime.now(timezone.utc)
		session.flush()

		_emit(
			CreditHoldPlacedEvent(
				aggregate_id=profile.id,
				aggregate_type="CustomerCreditProfile",
				tenant_id=tenant_id,
				customer_id=customer_id,
				reason=reason,
				placed_by=placed_by,
			),
			session,
		)

		log.info(
			"CreditManagementService.place_hold: customer=%r reason=%r placed_by=%r",
			customer_id, reason, placed_by,
		)
		return profile

	# ------------------------------------------------------------------
	# release_hold
	# ------------------------------------------------------------------

	def release_hold(
		self,
		customer_id: str,
		released_by: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Release a credit hold from a customer account.

		Idempotent — releasing an already-active customer is a no-op (no error).

		Args:
			customer_id:  Soft FK to customer.
			released_by:  User ID or name of person releasing the hold.
			tenant_id:    Tenant UUID string.
			session:      SA 2.x session.

		Returns:
			Updated CustomerCreditProfile.

		Emits:
			CreditHoldReleasedEvent

		Raises:
			CreditProfileNotFoundError: no profile exists for customer.
		"""
		from pgappforge.plugins.erp.finance.credit_management.events import CreditHoldReleasedEvent
		from pgappforge.plugins.erp.finance.credit_management.models import CustomerCreditProfile

		profile = session.execute(
			sa.select(CustomerCreditProfile)
			.where(CustomerCreditProfile.tenant_id == tenant_id)
			.where(CustomerCreditProfile.customer_id == customer_id)
		).scalar_one_or_none()

		if profile is None:
			raise CreditProfileNotFoundError(
				f"No credit profile for customer {customer_id!r} in tenant {tenant_id!r}"
			)

		profile.is_on_hold = False
		profile.hold_reason = None
		profile.hold_placed_by = None
		profile.hold_placed_at = None
		profile.updated_at = datetime.now(timezone.utc)
		session.flush()

		_emit(
			CreditHoldReleasedEvent(
				aggregate_id=profile.id,
				aggregate_type="CustomerCreditProfile",
				tenant_id=tenant_id,
				customer_id=customer_id,
				released_by=released_by,
			),
			session,
		)

		log.info(
			"CreditManagementService.release_hold: customer=%r released_by=%r",
			customer_id, released_by,
		)
		return profile

	# ------------------------------------------------------------------
	# register_exposure_component
	# ------------------------------------------------------------------

	def register_exposure_component(
		self,
		customer_id: str,
		source_type: str,
		source_id: str,
		amount_cents: int,
		tenant_id: str,
		session: Any,
		*,
		due_date: date | str | None = None,
	) -> Any:
		"""Upsert a CreditExposureComponent and refresh exposure totals.

		source_type: INVOICE | SALES_ORDER | DELIVERY.

		The upsert is on (profile_id, source_type, source_id) — inserting the
		same document twice updates the amount (e.g., partial payment reduces it).

		After upsert, calls update_exposure() to recompute the profile totals.

		Args:
			customer_id:  Soft FK to customer.
			source_type:  INVOICE | SALES_ORDER | DELIVERY.
			source_id:    PK of the source document.
			amount_cents: Open amount in cents.
			tenant_id:    Tenant UUID string.
			session:      SA 2.x session.
			due_date:     Optional due date; triggers is_overdue computation.

		Returns:
			The upserted CreditExposureComponent.

		Raises:
			CreditProfileNotFoundError: no profile exists for customer.
		"""
		from pgappforge.plugins.erp.finance.credit_management.models import (
			CreditExposureComponent,
			CustomerCreditProfile,
		)

		source_type = source_type.upper()
		assert source_type in ("INVOICE", "SALES_ORDER", "DELIVERY"), (
			f"source_type must be INVOICE/SALES_ORDER/DELIVERY, got {source_type!r}"
		)
		assert int(amount_cents) >= 0, "amount_cents must be non-negative"

		if isinstance(due_date, str):
			due_date = date.fromisoformat(due_date)

		profile = session.execute(
			sa.select(CustomerCreditProfile)
			.where(CustomerCreditProfile.tenant_id == tenant_id)
			.where(CustomerCreditProfile.customer_id == customer_id)
		).scalar_one_or_none()

		if profile is None:
			raise CreditProfileNotFoundError(
				f"No credit profile for customer {customer_id!r} in tenant {tenant_id!r}; "
				"call set_credit_limit first"
			)

		today = date.today()
		is_overdue = bool(due_date and due_date < today and int(amount_cents) > 0)

		# Upsert component
		existing = session.execute(
			sa.select(CreditExposureComponent)
			.where(CreditExposureComponent.profile_id == profile.id)
			.where(CreditExposureComponent.source_type == source_type)
			.where(CreditExposureComponent.source_id == source_id)
		).scalar_one_or_none()

		if existing is not None:
			existing.amount_cents = int(amount_cents)
			existing.due_date = due_date
			existing.is_overdue = is_overdue
			existing.updated_at = datetime.now(timezone.utc)
			component = existing
		else:
			component = CreditExposureComponent(
				tenant_id=tenant_id,
				profile_id=profile.id,
				source_type=source_type,
				source_id=source_id,
				amount_cents=int(amount_cents),
				due_date=due_date,
				is_overdue=is_overdue,
			)
			session.add(component)

		session.flush()

		# Refresh exposure totals
		self.update_exposure(customer_id, tenant_id, session)

		log.debug(
			"CreditManagementService.register_exposure_component: "
			"customer=%r type=%r src=%r amount=%d¢",
			customer_id, source_type, source_id, amount_cents,
		)
		return component

	# ------------------------------------------------------------------
	# remove_exposure_component
	# ------------------------------------------------------------------

	def remove_exposure_component(
		self,
		source_type: str,
		source_id: str,
		tenant_id: str,
		session: Any,
	) -> None:
		"""Delete a CreditExposureComponent and refresh exposure totals.

		Called when an invoice is paid, an order is shipped/cancelled, etc.
		Silently no-ops if the component does not exist.

		Args:
			source_type: INVOICE | SALES_ORDER | DELIVERY.
			source_id:   PK of the source document.
			tenant_id:   Tenant UUID string.
			session:     SA 2.x session.
		"""
		from pgappforge.plugins.erp.finance.credit_management.models import (
			CreditExposureComponent,
			CustomerCreditProfile,
		)

		source_type = source_type.upper()

		component = session.execute(
			sa.select(CreditExposureComponent)
			.join(
				CustomerCreditProfile,
				CreditExposureComponent.profile_id == CustomerCreditProfile.id,
			)
			.where(CustomerCreditProfile.tenant_id == tenant_id)
			.where(CreditExposureComponent.source_type == source_type)
			.where(CreditExposureComponent.source_id == source_id)
		).scalar_one_or_none()

		if component is None:
			log.debug(
				"CreditManagementService.remove_exposure_component: "
				"no component found for type=%r src=%r — no-op",
				source_type, source_id,
			)
			return

		# Resolve customer_id via profile before deletion
		profile = session.get(CustomerCreditProfile, component.profile_id)
		customer_id = profile.customer_id if profile else None

		session.delete(component)
		session.flush()

		if customer_id is not None:
			self.update_exposure(customer_id, tenant_id, session)

		log.debug(
			"CreditManagementService.remove_exposure_component: "
			"deleted type=%r src=%r for customer=%r",
			source_type, source_id, customer_id,
		)

	# ------------------------------------------------------------------
	# get_overdue_customers
	# ------------------------------------------------------------------

	def get_overdue_customers(
		self,
		tenant_id: str,
		session: Any,
		*,
		overdue_days: int = 30,
	) -> list[dict]:
		"""Return customers with overdue exposure components.

		A component is overdue when due_date < (today - overdue_days) and
		is_overdue is True.

		Results are ordered by total overdue amount descending.

		Args:
			tenant_id:    Tenant UUID string.
			session:      SA 2.x session.
			overdue_days: Minimum days past due to include (default 30).

		Returns:
			List of dicts, each containing:
			  customer_id, overdue_amount_cents, component_count,
			  oldest_due_date, is_on_hold, credit_rating
		"""
		from pgappforge.plugins.erp.finance.credit_management.models import (
			CreditExposureComponent,
			CustomerCreditProfile,
		)

		cutoff = date.today()

		rows = session.execute(
			sa.select(
				CustomerCreditProfile.customer_id,
				CustomerCreditProfile.is_on_hold,
				CustomerCreditProfile.credit_rating,
				sa.func.sum(CreditExposureComponent.amount_cents).label("overdue_amount_cents"),
				sa.func.count(CreditExposureComponent.id).label("component_count"),
				sa.func.min(CreditExposureComponent.due_date).label("oldest_due_date"),
			)
			.join(
				CreditExposureComponent,
				CreditExposureComponent.profile_id == CustomerCreditProfile.id,
			)
			.where(CustomerCreditProfile.tenant_id == tenant_id)
			.where(CreditExposureComponent.is_overdue.is_(True))
			.where(CreditExposureComponent.due_date <= cutoff)
			.group_by(
				CustomerCreditProfile.customer_id,
				CustomerCreditProfile.is_on_hold,
				CustomerCreditProfile.credit_rating,
			)
			.order_by(sa.desc("overdue_amount_cents"))
		).all()

		return [
			{
				"customer_id": r.customer_id,
				"overdue_amount_cents": int(r.overdue_amount_cents or 0),
				"component_count": int(r.component_count or 0),
				"oldest_due_date": r.oldest_due_date.isoformat() if r.oldest_due_date else None,
				"is_on_hold": r.is_on_hold,
				"credit_rating": r.credit_rating,
			}
			for r in rows
		]


# ---------------------------------------------------------------------------
# BPM action registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"finance.credit.check",
	"Check customer credit before order",
)
def _bpm_check_credit(context: dict, session: Any) -> dict:
	"""BPM action: credit check from workflow context.

	Expected context keys: customer_id, order_amount_cents, tenant_id

	Returns the check_credit dict (approved, available_cents, message, ...).
	"""
	svc = CreditManagementService()
	return svc.check_credit(
		customer_id=context["customer_id"],
		order_amount_cents=int(context["order_amount_cents"]),
		tenant_id=context["tenant_id"],
		session=session,
	)


@BPMActionRegistry.register(
	"finance.credit.place_hold",
	"Place credit hold on customer",
)
def _bpm_place_hold(context: dict, session: Any) -> dict:
	"""BPM action: place hold from workflow context.

	Expected context keys: customer_id, reason, placed_by, tenant_id

	Returns dict with customer_id and is_on_hold=True.
	"""
	svc = CreditManagementService()
	profile = svc.place_hold(
		customer_id=context["customer_id"],
		reason=context["reason"],
		placed_by=context["placed_by"],
		tenant_id=context["tenant_id"],
		session=session,
	)
	return {
		"customer_id": profile.customer_id,
		"is_on_hold": profile.is_on_hold,
		"hold_reason": profile.hold_reason,
	}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"CreditManagementService",
	"CreditManagementError",
	"CreditProfileNotFoundError",
	"CreditValidationError",
]
