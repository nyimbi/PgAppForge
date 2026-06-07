"""
pgappforge/plugins/erp/crm/loyalty/services.py

LoyaltyService — enrolment, earn, redeem, expiry, tier management.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


def _uuid4() -> str:
	return str(uuid.uuid4())


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("Loyalty event emit failed: %s", exc)


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry as _BPMReg

	@_BPMReg.register("loyalty.earn_points")
	def _bpm_earn(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "loyalty.earn_points", "params": ctx}

	@_BPMReg.register("loyalty.redeem_points")
	def _bpm_redeem(ctx: dict[str, Any]) -> dict[str, Any]:
		return {"action": "loyalty.redeem_points", "params": ctx}

except (ImportError, Exception):
	log.debug("BPMActionRegistry not available — Loyalty BPM actions not registered")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class LoyaltyServiceError(Exception):
	"""Base error for loyalty service."""


class InsufficientPointsError(LoyaltyServiceError):
	"""Raised when redemption exceeds available balance."""


class AccountNotFoundError(LoyaltyServiceError):
	"""Raised when a loyalty account cannot be located."""


class ProgramNotFoundError(LoyaltyServiceError):
	"""Raised when a loyalty program cannot be located."""


# ---------------------------------------------------------------------------
# LoyaltyService
# ---------------------------------------------------------------------------

class LoyaltyService:
	"""Service layer for the Loyalty Engine."""

	# ------------------------------------------------------------------
	# Enrolment
	# ------------------------------------------------------------------

	def enroll(
		self,
		customer_id: str,
		program_id: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Enrol a customer in a loyalty program.

		Idempotent — returns existing account if already enrolled.
		Emits CustomerEnrolledEvent on first enrolment.
		"""
		from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyAccount, LoyaltyProgram
		from pgappforge.plugins.erp.crm.loyalty.events import CustomerEnrolledEvent

		program = session.execute(
			sa.select(LoyaltyProgram).where(
				LoyaltyProgram.id == program_id,
				LoyaltyProgram.tenant_id == tenant_id,
			)
		).scalar_one_or_none()
		if program is None:
			raise ProgramNotFoundError(f"Loyalty program {program_id} not found")

		existing = session.execute(
			sa.select(LoyaltyAccount).where(
				LoyaltyAccount.program_id == program_id,
				LoyaltyAccount.customer_id == customer_id,
			)
		).scalar_one_or_none()
		if existing is not None:
			return existing

		account = LoyaltyAccount(
			id=_uuid4(),
			tenant_id=tenant_id,
			program_id=program_id,
			customer_id=customer_id,
			tier="BRONZE",
			status="ACTIVE",
			points_balance=0,
			lifetime_points=0,
			enrolled_at=_now(),
		)
		session.add(account)
		session.flush()

		_emit(
			CustomerEnrolledEvent(
				aggregate_id=account.id,
				aggregate_type="LoyaltyAccount",
				tenant_id=tenant_id,
				account_id=account.id,
				customer_id=customer_id,
				program_id=program_id,
			),
			session,
		)
		log.info("Loyalty: enrolled customer %s in program %s", customer_id, program_id)
		return account

	# ------------------------------------------------------------------
	# Earn
	# ------------------------------------------------------------------

	def earn_points(
		self,
		account_id: str,
		transaction_amount_cents: int,
		session: Any,
		*,
		reference_id: str = "",
		reference_type: str = "",
		notes: str = "",
	) -> Any:
		"""Credit points for a qualifying transaction using the program earn_rate.

		points = floor(transaction_amount_cents / 100 * earn_rate)
		Emits PointsEarnedEvent and triggers tier upgrade check.
		"""
		from pgappforge.plugins.erp.crm.loyalty.models import (
			LoyaltyAccount, LoyaltyProgram, LoyaltyTransaction,
		)
		from pgappforge.plugins.erp.crm.loyalty.events import PointsEarnedEvent

		account = session.execute(
			sa.select(LoyaltyAccount).where(LoyaltyAccount.id == account_id)
		).scalar_one_or_none()
		if account is None:
			raise AccountNotFoundError(f"Loyalty account {account_id} not found")

		program = session.execute(
			sa.select(LoyaltyProgram).where(LoyaltyProgram.id == account.program_id)
		).scalar_one_or_none()

		earn_rate = Decimal(str(program.earn_rate)) if program else Decimal("1")
		amount_units = Decimal(str(transaction_amount_cents)) / Decimal("100")
		points = int((amount_units * earn_rate).to_integral_value(rounding=ROUND_HALF_UP))

		if points <= 0:
			points = 0

		expiry_days = (program.expiry_days if program else 365) or 0
		expires_at = (_now() + timedelta(days=expiry_days)) if expiry_days > 0 else None

		account.points_balance += points
		account.lifetime_points += points
		account.last_activity_at = _now()

		txn = LoyaltyTransaction(
			id=_uuid4(),
			tenant_id=account.tenant_id,
			account_id=account_id,
			transaction_type="EARN",
			points=points,
			balance_after=account.points_balance,
			reference_id=reference_id,
			reference_type=reference_type,
			notes=notes,
			occurred_at=_now(),
			expires_at=expires_at,
			is_expired=False,
		)
		session.add(txn)
		session.flush()

		_emit(
			PointsEarnedEvent(
				aggregate_id=account_id,
				aggregate_type="LoyaltyAccount",
				tenant_id=account.tenant_id,
				account_id=account_id,
				customer_id=account.customer_id,
				points=points,
				reference_id=reference_id,
				balance_after=account.points_balance,
			),
			session,
		)

		# Check for tier upgrade
		self.check_tier_upgrade(account_id, session)
		return txn

	# ------------------------------------------------------------------
	# Redeem
	# ------------------------------------------------------------------

	def redeem_points(
		self,
		account_id: str,
		points: int,
		session: Any,
		*,
		reference_id: str = "",
		reference_type: str = "",
		notes: str = "",
	) -> Any:
		"""Debit points from an account for a redemption.

		Raises InsufficientPointsError if balance < points.
		Emits PointsRedeemedEvent.
		"""
		from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyAccount, LoyaltyTransaction
		from pgappforge.plugins.erp.crm.loyalty.events import PointsRedeemedEvent

		account = session.execute(
			sa.select(LoyaltyAccount).where(LoyaltyAccount.id == account_id)
		).scalar_one_or_none()
		if account is None:
			raise AccountNotFoundError(f"Loyalty account {account_id} not found")
		if account.points_balance < points:
			raise InsufficientPointsError(
				f"Account {account_id} has {account.points_balance} points; "
				f"redemption requested {points}"
			)

		account.points_balance -= points
		account.last_activity_at = _now()

		txn = LoyaltyTransaction(
			id=_uuid4(),
			tenant_id=account.tenant_id,
			account_id=account_id,
			transaction_type="REDEEM",
			points=-points,
			balance_after=account.points_balance,
			reference_id=reference_id,
			reference_type=reference_type,
			notes=notes,
			occurred_at=_now(),
		)
		session.add(txn)
		session.flush()

		_emit(
			PointsRedeemedEvent(
				aggregate_id=account_id,
				aggregate_type="LoyaltyAccount",
				tenant_id=account.tenant_id,
				account_id=account_id,
				customer_id=account.customer_id,
				points=points,
				reference_id=reference_id,
				balance_after=account.points_balance,
			),
			session,
		)
		return txn

	# ------------------------------------------------------------------
	# Expiry
	# ------------------------------------------------------------------

	def expire_stale_points(
		self,
		tenant_id: str,
		session: Any,
	) -> int:
		"""Expire all LoyaltyTransaction rows that have passed their expires_at.

		For each expired EARN transaction, deduct the original points from the
		account balance (floored at 0) and mark the transaction is_expired=True.
		Returns the count of transactions expired.
		"""
		from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyAccount, LoyaltyTransaction

		now = _now()
		stale = session.execute(
			sa.select(LoyaltyTransaction).where(
				LoyaltyTransaction.tenant_id == tenant_id,
				LoyaltyTransaction.transaction_type == "EARN",
				LoyaltyTransaction.is_expired == False,
				LoyaltyTransaction.expires_at <= now,
				LoyaltyTransaction.expires_at.is_not(None),
			)
		).scalars().all()

		count = 0
		for txn in stale:
			txn.is_expired = True
			account = session.execute(
				sa.select(LoyaltyAccount).where(LoyaltyAccount.id == txn.account_id)
			).scalar_one_or_none()
			if account is not None:
				deduct = min(account.points_balance, txn.points)
				account.points_balance = max(0, account.points_balance - deduct)

				expire_txn = LoyaltyTransaction(
					id=_uuid4(),
					tenant_id=tenant_id,
					account_id=txn.account_id,
					transaction_type="EXPIRE",
					points=-deduct,
					balance_after=account.points_balance,
					reference_id=txn.id,
					reference_type="EXPIRY",
					notes=f"Auto-expired earn txn {txn.id}",
					occurred_at=now,
				)
				session.add(expire_txn)
			count += 1

		session.flush()
		log.info("Loyalty: expired %d stale point transactions for tenant %s", count, tenant_id)
		return count

	# ------------------------------------------------------------------
	# Tier upgrade
	# ------------------------------------------------------------------

	def check_tier_upgrade(
		self,
		account_id: str,
		session: Any,
	) -> bool:
		"""Evaluate whether a customer qualifies for a tier upgrade.

		Uses lifetime_points against program tier_thresholds.
		Emits TierUpgradeEvent if tier changes.
		Returns True if tier was upgraded.
		"""
		from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyAccount, LoyaltyProgram
		from pgappforge.plugins.erp.crm.loyalty.events import TierUpgradeEvent

		TIER_ORDER = ["BRONZE", "SILVER", "GOLD", "PLATINUM", "DIAMOND"]

		account = session.execute(
			sa.select(LoyaltyAccount).where(LoyaltyAccount.id == account_id)
		).scalar_one_or_none()
		if account is None:
			return False

		program = session.execute(
			sa.select(LoyaltyProgram).where(LoyaltyProgram.id == account.program_id)
		).scalar_one_or_none()
		if program is None or not program.tier_thresholds:
			return False

		thresholds: dict[str, int] = program.tier_thresholds
		lifetime = account.lifetime_points

		# Determine highest qualifying tier
		new_tier = account.tier
		for tier in reversed(TIER_ORDER):
			threshold = thresholds.get(tier)
			if threshold is not None and lifetime >= threshold:
				new_tier = tier
				break

		if new_tier == account.tier:
			return False

		old_tier = account.tier
		account.tier = new_tier
		session.flush()

		_emit(
			TierUpgradeEvent(
				aggregate_id=account_id,
				aggregate_type="LoyaltyAccount",
				tenant_id=account.tenant_id,
				account_id=account_id,
				customer_id=account.customer_id,
				old_tier=old_tier,
				new_tier=new_tier,
			),
			session,
		)
		log.info("Loyalty: account %s upgraded from %s to %s", account_id, old_tier, new_tier)
		return True

	# ------------------------------------------------------------------
	# Reporting
	# ------------------------------------------------------------------

	def get_liability_report(
		self,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Compute outstanding loyalty liability for a tenant.

		Liability = sum(points_balance) * redemption_rate_cents, grouped by program.
		"""
		from pgappforge.plugins.erp.crm.loyalty.models import LoyaltyAccount, LoyaltyProgram

		rows = session.execute(
			sa.select(
				LoyaltyProgram.id,
				LoyaltyProgram.name,
				LoyaltyProgram.redemption_rate_cents,
				sa.func.count(LoyaltyAccount.id).label("accounts"),
				sa.func.sum(LoyaltyAccount.points_balance).label("total_points"),
			)
			.join(LoyaltyAccount, LoyaltyAccount.program_id == LoyaltyProgram.id)
			.where(LoyaltyProgram.tenant_id == tenant_id, LoyaltyAccount.status == "ACTIVE")
			.group_by(LoyaltyProgram.id, LoyaltyProgram.name, LoyaltyProgram.redemption_rate_cents)
		).all()

		programs = []
		total_liability_cents = 0
		for row in rows:
			liability = (row.total_points or 0) * (row.redemption_rate_cents or 1)
			total_liability_cents += liability
			programs.append({
				"program_id": row.id,
				"program_name": row.name,
				"accounts": row.accounts,
				"total_points": row.total_points or 0,
				"redemption_rate_cents": row.redemption_rate_cents,
				"liability_cents": liability,
			})

		return {
			"tenant_id": tenant_id,
			"programs": programs,
			"total_liability_cents": total_liability_cents,
		}
