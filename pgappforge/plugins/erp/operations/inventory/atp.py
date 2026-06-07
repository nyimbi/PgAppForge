"""
pgappforge/plugins/erp/operations/inventory/atp.py

ATPService — Available-to-Promise engine.

Computes whether a quantity of product can be committed for a required_date
based on current stock + confirmed supply - confirmed demand.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import sqlalchemy as sa
from sqlalchemy import BigInteger, Column, Date, Index, String
from sqlalchemy.dialects.postgresql import UUID

from pgappforge.models.sqla import Model
from pgappforge.plugins.audit import AuditMixin

log = logging.getLogger(__name__)


def _d(v: Any) -> Decimal:
	return Decimal(str(v or 0))


# ---------------------------------------------------------------------------
# ATPCommitment model
# ---------------------------------------------------------------------------

class ATPCommitment(AuditMixin, Model):
	"""Records a committed ATP reservation against a product for an order."""

	__allow_unmapped__ = True
	__tablename__ = "inv_atp_commitment"
	__table_args__ = (
		Index("ix_atp_product_date", "product_id", "commit_date"),
		Index("ix_atp_tenant", "tenant_id"),
		{"extend_existing": True},
	)

	id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
	tenant_id = Column(UUID(as_uuid=False), nullable=False)
	product_id = Column(String(50), nullable=False)
	order_id = Column(String(50), nullable=False)
	committed_qty = Column(BigInteger, nullable=False)
	commit_date = Column(Date, nullable=False)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ATPError(Exception):
	"""Base error for ATP operations."""


# ---------------------------------------------------------------------------
# ATPService
# ---------------------------------------------------------------------------

class ATPService:
	"""Available-to-Promise engine.

	All methods accept an explicit SQLAlchemy session; no Flask context assumed.
	Transaction boundaries owned by the caller.
	"""

	def check_atp(
		self,
		product_id: str,
		required_qty: int | Decimal,
		required_date: date,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Check whether product_id can be committed in required_qty by required_date.

		ATP formula: current_stock + confirmed_supply - confirmed_demand

		Returns:
		  {
		    can_commit: bool,
		    available_qty: str (Decimal),
		    earliest_available_date: str | None,
		    current_stock: str,
		    confirmed_supply: str,
		    confirmed_demand: str,
		  }
		"""
		current_stock = self._get_current_stock(product_id, tenant_id, session)
		confirmed_supply = self._get_confirmed_supply(product_id, required_date, tenant_id, session)
		confirmed_demand = self._get_confirmed_demand(product_id, required_date, tenant_id, session)
		atp = current_stock + confirmed_supply - confirmed_demand
		can_commit = atp >= _d(required_qty)
		earliest: date | None = None
		if not can_commit:
			earliest = self._find_earliest_available(product_id, required_qty, tenant_id, session)
		return {
			"can_commit": can_commit,
			"available_qty": str(atp),
			"earliest_available_date": str(earliest) if earliest else None,
			"current_stock": str(current_stock),
			"confirmed_supply": str(confirmed_supply),
			"confirmed_demand": str(confirmed_demand),
		}

	def commit_atp(
		self,
		product_id: str,
		qty: int | Decimal,
		commit_date: date,
		order_id: str,
		tenant_id: str,
		session: Any,
	) -> ATPCommitment:
		"""Record an ATP commitment (e.g., when a sales order is confirmed).

		Does not validate availability — caller should call check_atp first.
		Returns the persisted ATPCommitment (not yet committed).
		"""
		commitment = ATPCommitment(
			id=str(uuid.uuid4()),
			tenant_id=tenant_id,
			product_id=product_id,
			committed_qty=int(qty),
			commit_date=commit_date,
			order_id=order_id,
		)
		session.add(commitment)
		session.flush()
		log.info(
			"ATPService.commit_atp: product=%s qty=%s date=%s order=%s",
			product_id, qty, commit_date, order_id,
		)
		return commitment

	def release_commitment(
		self,
		commitment_id: str,
		session: Any,
	) -> None:
		"""Release (delete) an ATP commitment, e.g. when an order is cancelled."""
		commitment = session.execute(
			sa.select(ATPCommitment).where(ATPCommitment.id == commitment_id)
		).scalar_one_or_none()
		if commitment is None:
			raise ATPError(f"ATPCommitment {commitment_id!r} not found")
		session.delete(commitment)
		session.flush()
		log.info("ATPService.release_commitment: id=%s", commitment_id)

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _get_current_stock(
		self,
		product_id: str,
		tenant_id: str,
		session: Any,
	) -> Decimal:
		"""Sum of quantity_available across all locations for this product."""
		try:
			from pgappforge.plugins.erp.operations.inventory.models import StockLevel
			qty = session.execute(
				sa.select(
					sa.func.coalesce(sa.func.sum(StockLevel.quantity_available), 0)
				).where(
					StockLevel.tenant_id == tenant_id,
					StockLevel.product_id == product_id,
				)
			).scalar() or 0
			return _d(qty)
		except ImportError:
			log.debug("ATPService._get_current_stock: StockLevel model not available")
			return _d(0)
		except Exception as exc:
			log.debug("ATPService._get_current_stock: query failed: %s", exc)
			return _d(0)

	def _get_confirmed_supply(
		self,
		product_id: str,
		required_date: date,
		tenant_id: str,
		session: Any,
	) -> Decimal:
		"""Open PO line receipts expected on or before required_date."""
		try:
			from pgappforge.plugins.erp.operations.scm.models import POLine, PurchaseOrder
			qty = session.execute(
				sa.select(
					sa.func.coalesce(
						sa.func.sum(POLine.ordered_qty - POLine.received_qty), 0
					)
				)
				.join(PurchaseOrder, POLine.purchase_order_id == PurchaseOrder.id)
				.where(
					POLine.tenant_id == tenant_id,
					POLine.product_code == product_id,
					PurchaseOrder.expected_delivery <= required_date,
					PurchaseOrder.status.in_(["SENT", "RECEIVED_PARTIAL"]),
				)
			).scalar() or 0
			return _d(qty)
		except ImportError:
			log.debug("ATPService._get_confirmed_supply: SCM models not available")
			return _d(0)
		except Exception as exc:
			log.debug("ATPService._get_confirmed_supply: query failed: %s", exc)
			return _d(0)

	def _get_confirmed_demand(
		self,
		product_id: str,
		required_date: date,
		tenant_id: str,
		session: Any,
	) -> Decimal:
		"""Sum of existing ATP commitments on or before required_date."""
		committed = session.execute(
			sa.select(
				sa.func.coalesce(sa.func.sum(ATPCommitment.committed_qty), 0)
			).where(
				ATPCommitment.tenant_id == tenant_id,
				ATPCommitment.product_id == product_id,
				ATPCommitment.commit_date <= required_date,
			)
		).scalar() or 0
		return _d(committed)

	def _find_earliest_available(
		self,
		product_id: str,
		required_qty: int | Decimal,
		tenant_id: str,
		session: Any,
	) -> date | None:
		"""Return the earliest future date when required_qty will be available.

		Checks at 7, 14, 30, 60, 90, 180 day horizons; returns None if unavailable
		within 180 days.
		"""
		today = date.today()
		for days_ahead in (7, 14, 30, 60, 90, 180):
			target = today + timedelta(days=days_ahead)
			result = self.check_atp(product_id, required_qty, target, tenant_id, session)
			if result["can_commit"]:
				return target
		return None


__all__ = ["ATPService", "ATPError", "ATPCommitment"]
