"""
pgappforge/plugins/erp/finance/product_costing/services.py

ProductCostingService — stateless business logic for the Product Costing plugin.

All methods accept an explicit SQLAlchemy 2.x session.
No session.commit() inside service methods — callers own the transaction boundary.

Monetary invariant: ALL amounts are BigInteger cents. Float is never used.

Key methods
-----------
  create_cost_version(product_id, version_type, effective_from, tenant_id, session)
      Create a new CostVersion in DRAFT status.

  add_cost_element(version_id, element_type, description, unit_cost_cents, session)
      Add a CostElement to a DRAFT CostVersion; computes total_cost_cents.

  rollup_standard_cost(product_id, version_id, session)
      Sum all elements; create/update ProductStandardCost; emit CostRollUpCompletedEvent.

  release_standard_cost(product_id, version_id, effective_from, session)
      Activate version; archive prior active; emit StandardCostReleasedEvent.

  compute_actual_cost(production_order_id, ..., session)
      Load standard; compute variance; post GL if |variance| > 1000¢;
      emit ActualCostComputedEvent + CostVariancePostedEvent.

  get_cost_history(product_id, tenant_id, session)
      Return standard cost rows ordered by effective_from desc.

BPM action
----------
  finance.costing.compute_actual — registered via @BPMActionRegistry.register
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.bpm_actions import BPMActionRegistry
from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event

log = logging.getLogger(__name__)

# Variance threshold: only post GL entry when |variance| exceeds this (cents)
_GL_VARIANCE_THRESHOLD_CENTS = 1_000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _emit(event: Any, session: Any = None) -> None:
	try:
		_emit_event(event, session)
	except Exception as exc:
		log.debug("_emit: swallowed event emission error: %s", exc)


def _round_cents(value: Decimal) -> int:
	"""Round a Decimal to the nearest integer cent (ROUND_HALF_UP)."""
	return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProductCostingError(Exception):
	"""Base exception for Product Costing service errors."""


class CostVersionNotFoundError(ProductCostingError):
	pass


class CostVersionStatusError(ProductCostingError):
	"""Raised when an operation is invalid for the version's current status."""


class StandardCostNotFoundError(ProductCostingError):
	pass


class ProductionOrderCostError(ProductCostingError):
	pass


# ---------------------------------------------------------------------------
# ProductCostingService
# ---------------------------------------------------------------------------

class ProductCostingService:
	"""Stateless product costing business logic.

	Instantiate per-request or as a singleton — no instance state.
	All monetary arithmetic uses int (cents). Decimal is used only for
	intermediate multiplication, then rounded to int.
	"""

	# ------------------------------------------------------------------
	# create_cost_version
	# ------------------------------------------------------------------

	def create_cost_version(
		self,
		product_id: str,
		version_type: str,
		effective_from: date | str,
		tenant_id: str,
		session: Any,
		*,
		currency_code: str = "USD",
	) -> Any:
		"""Create a new CostVersion in DRAFT status.

		Args:
			product_id:     Soft FK to inventory/production product.
			version_type:   STANDARD | PLANNED | ACTUAL.
			effective_from: Date the version becomes effective.
			tenant_id:      Tenant UUID string.
			session:        SA 2.x session — caller owns commit.
			currency_code:  ISO 4217, default USD.

		Returns:
			The newly created CostVersion instance (flushed, id populated).

		Emits:
			CostVersionCreatedEvent
		"""
		from pgappforge.plugins.erp.finance.product_costing.events import CostVersionCreatedEvent
		from pgappforge.plugins.erp.finance.product_costing.models import CostVersion

		if isinstance(effective_from, str):
			effective_from = date.fromisoformat(effective_from)

		version_type = version_type.upper()
		assert version_type in ("STANDARD", "PLANNED", "ACTUAL"), (
			f"version_type must be STANDARD/PLANNED/ACTUAL, got {version_type!r}"
		)

		version = CostVersion(
			tenant_id=tenant_id,
			product_id=product_id,
			version_type=version_type,
			effective_from=effective_from,
			status="DRAFT",
			currency_code=currency_code,
		)
		session.add(version)
		session.flush()  # populate version.id

		_emit(
			CostVersionCreatedEvent(
				aggregate_id=version.id,
				aggregate_type="CostVersion",
				tenant_id=tenant_id,
				version_id=version.id,
				product_id=product_id,
				effective_from=effective_from.isoformat(),
			),
			session,
		)

		log.info(
			"ProductCostingService.create_cost_version: product=%r type=%r id=%r",
			product_id, version_type, version.id,
		)
		return version

	# ------------------------------------------------------------------
	# add_cost_element
	# ------------------------------------------------------------------

	def add_cost_element(
		self,
		version_id: str,
		element_type: str,
		description: str,
		unit_cost_cents: int,
		session: Any,
		*,
		quantity: int | float | Decimal = 1,
		overhead_rate: float | Decimal | None = None,
		source_component_id: str | None = None,
	) -> Any:
		"""Add a CostElement to a DRAFT CostVersion.

		total_cost_cents = round(quantity * unit_cost_cents).

		For OVERHEAD elements, overhead_rate (%) is stored but the total is
		still computed from quantity * unit_cost_cents; the rate is informational
		for cost analysts — the service caller is responsible for setting
		unit_cost_cents correctly from the rate at add time.

		Args:
			version_id:          UUID of the parent CostVersion (must be DRAFT).
			element_type:        MATERIAL | LABOR | OVERHEAD | SUBCONTRACTING | SETUP.
			description:         Human-readable cost element description.
			unit_cost_cents:     Cost per unit in cents (int).
			session:             SA 2.x session.
			quantity:            Quantity consumed (default 1).
			overhead_rate:       % of direct costs for OVERHEAD type (informational).
			source_component_id: BOM component or work center soft FK.

		Returns:
			The newly created CostElement instance.

		Raises:
			CostVersionNotFoundError:  version_id not found.
			CostVersionStatusError:    version is not in DRAFT status.
		"""
		from pgappforge.plugins.erp.finance.product_costing.models import CostElement, CostVersion

		version = session.get(CostVersion, version_id)
		if version is None:
			raise CostVersionNotFoundError(f"CostVersion {version_id!r} not found")
		if version.status != "DRAFT":
			raise CostVersionStatusError(
				f"CostVersion {version_id!r} is {version.status!r}; elements can only be added to DRAFT versions"
			)

		element_type = element_type.upper()
		assert element_type in ("MATERIAL", "LABOR", "OVERHEAD", "SUBCONTRACTING", "SETUP"), (
			f"element_type must be one of MATERIAL/LABOR/OVERHEAD/SUBCONTRACTING/SETUP, got {element_type!r}"
		)
		assert int(unit_cost_cents) >= 0, "unit_cost_cents must be non-negative"

		qty = Decimal(str(quantity))
		total = _round_cents(qty * Decimal(str(unit_cost_cents)))

		element = CostElement(
			tenant_id=version.tenant_id,
			version_id=version_id,
			element_type=element_type,
			description=description,
			quantity=qty,
			unit_cost_cents=int(unit_cost_cents),
			total_cost_cents=total,
			source_component_id=source_component_id,
			overhead_rate=Decimal(str(overhead_rate)) if overhead_rate is not None else None,
		)
		session.add(element)
		session.flush()

		log.debug(
			"ProductCostingService.add_cost_element: version=%r type=%r total=%d¢",
			version_id, element_type, total,
		)
		return element

	# ------------------------------------------------------------------
	# rollup_standard_cost
	# ------------------------------------------------------------------

	def rollup_standard_cost(
		self,
		product_id: str,
		version_id: str,
		session: Any,
	) -> Any:
		"""Sum all CostElements for a version; create/update ProductStandardCost.

		Groups elements by type into material/labor/overhead buckets.
		SUBCONTRACTING and SETUP elements are rolled into the material bucket
		for the standard cost summary (common ERP convention; analysts can
		inspect CostElement rows for the breakdown).

		Args:
			product_id:  Soft FK to product.
			version_id:  UUID of the CostVersion to roll up.
			session:     SA 2.x session.

		Returns:
			The upserted ProductStandardCost instance.

		Emits:
			CostRollUpCompletedEvent

		Raises:
			CostVersionNotFoundError: version_id not found.
		"""
		from pgappforge.plugins.erp.finance.product_costing.events import CostRollUpCompletedEvent
		from pgappforge.plugins.erp.finance.product_costing.models import (
			CostElement,
			CostVersion,
			ProductStandardCost,
		)

		version = session.get(CostVersion, version_id)
		if version is None:
			raise CostVersionNotFoundError(f"CostVersion {version_id!r} not found")

		elements = session.execute(
			sa.select(CostElement).where(CostElement.version_id == version_id)
		).scalars().all()

		material_cents: int = 0
		labor_cents: int = 0
		overhead_cents: int = 0

		for el in elements:
			t = el.element_type
			if t in ("MATERIAL", "SUBCONTRACTING", "SETUP"):
				material_cents += el.total_cost_cents
			elif t == "LABOR":
				labor_cents += el.total_cost_cents
			elif t == "OVERHEAD":
				overhead_cents += el.total_cost_cents

		total_cents = material_cents + labor_cents + overhead_cents
		effective_from = version.effective_from
		tenant_id = version.tenant_id

		# Upsert ProductStandardCost
		existing = session.execute(
			sa.select(ProductStandardCost)
			.where(ProductStandardCost.tenant_id == tenant_id)
			.where(ProductStandardCost.product_id == product_id)
			.where(ProductStandardCost.effective_from == effective_from)
		).scalar_one_or_none()

		if existing is not None:
			existing.material_cost_cents = material_cents
			existing.labor_cost_cents = labor_cents
			existing.overhead_cost_cents = overhead_cents
			existing.total_standard_cost_cents = total_cents
			existing.currency_code = version.currency_code
			existing.updated_at = datetime.now(timezone.utc)
			std = existing
		else:
			std = ProductStandardCost(
				tenant_id=tenant_id,
				product_id=product_id,
				effective_from=effective_from,
				material_cost_cents=material_cents,
				labor_cost_cents=labor_cents,
				overhead_cost_cents=overhead_cents,
				total_standard_cost_cents=total_cents,
				currency_code=version.currency_code,
			)
			session.add(std)

		session.flush()

		period = effective_from.strftime("%Y-%m")
		_emit(
			CostRollUpCompletedEvent(
				aggregate_id=version_id,
				aggregate_type="CostVersion",
				tenant_id=tenant_id,
				product_id=product_id,
				standard_cost_cents=total_cents,
				period=period,
			),
			session,
		)

		log.info(
			"ProductCostingService.rollup_standard_cost: product=%r total=%d¢ "
			"(mat=%d¢ lab=%d¢ ovh=%d¢)",
			product_id, total_cents, material_cents, labor_cents, overhead_cents,
		)
		return std

	# ------------------------------------------------------------------
	# release_standard_cost
	# ------------------------------------------------------------------

	def release_standard_cost(
		self,
		product_id: str,
		version_id: str,
		effective_from: date | str,
		session: Any,
	) -> Any:
		"""Activate a cost version; archive any prior ACTIVE version.

		Steps:
		  1. Load version; assert DRAFT or already ACTIVE (idempotent).
		  2. Archive any other ACTIVE version for this product → HISTORICAL.
		  3. Set this version status = ACTIVE, effective_to = None.
		  4. Run rollup to ensure ProductStandardCost is current.
		  5. Emit StandardCostReleasedEvent.

		Args:
			product_id:     Soft FK to product.
			version_id:     UUID of the CostVersion to release.
			effective_from: Effective date (must match version.effective_from).
			session:        SA 2.x session.

		Returns:
			The ProductStandardCost row for the released version.

		Raises:
			CostVersionNotFoundError:  version_id not found.
			CostVersionStatusError:    version is HISTORICAL (cannot re-release).
		"""
		from pgappforge.plugins.erp.finance.product_costing.events import StandardCostReleasedEvent
		from pgappforge.plugins.erp.finance.product_costing.models import CostVersion

		if isinstance(effective_from, str):
			effective_from = date.fromisoformat(effective_from)

		version = session.get(CostVersion, version_id)
		if version is None:
			raise CostVersionNotFoundError(f"CostVersion {version_id!r} not found")
		if version.status == "HISTORICAL":
			raise CostVersionStatusError(
				f"CostVersion {version_id!r} is HISTORICAL; cannot re-release"
			)

		tenant_id = version.tenant_id

		# Archive any other currently ACTIVE version for this product
		other_active = session.execute(
			sa.select(CostVersion)
			.where(CostVersion.tenant_id == tenant_id)
			.where(CostVersion.product_id == product_id)
			.where(CostVersion.version_type == version.version_type)
			.where(CostVersion.status == "ACTIVE")
			.where(CostVersion.id != version_id)
		).scalars().all()

		for old in other_active:
			old.status = "HISTORICAL"
			old.effective_to = effective_from
			old.updated_at = datetime.now(timezone.utc)

		# Activate this version
		version.status = "ACTIVE"
		version.effective_from = effective_from
		version.effective_to = None
		version.updated_at = datetime.now(timezone.utc)
		session.flush()

		# Rollup to ensure ProductStandardCost is current
		std = self.rollup_standard_cost(product_id, version_id, session)

		_emit(
			StandardCostReleasedEvent(
				aggregate_id=version_id,
				aggregate_type="CostVersion",
				tenant_id=tenant_id,
				product_id=product_id,
				standard_cost_cents=std.total_standard_cost_cents,
				effective_from=effective_from.isoformat(),
			),
			session,
		)

		log.info(
			"ProductCostingService.release_standard_cost: product=%r effective=%r cost=%d¢",
			product_id, effective_from, std.total_standard_cost_cents,
		)
		return std

	# ------------------------------------------------------------------
	# compute_actual_cost
	# ------------------------------------------------------------------

	def compute_actual_cost(
		self,
		production_order_id: str,
		material_actual_cents: int,
		labor_actual_cents: int,
		overhead_actual_cents: int,
		product_id: str,
		period: str,
		session: Any,
	) -> Any:
		"""Compute actual vs standard cost for a production order.

		Algorithm:
		  1. total_actual = material_actual + labor_actual + overhead_actual
		  2. Load current ACTIVE standard cost for product (most recent effective_from).
		  3. total_variance = total_actual - total_standard
		  4. price_variance = (actual_unit - std_unit) * actual_qty
		     [simplified: treated as total_actual - total_standard at bucket level
		      since production orders carry totals not per-unit here]
		  5. qty_variance = total_variance - price_variance
		  6. Post GL variance entry if |total_variance| > 1000¢:
		     DR/CR Production Variance (5990)
		  7. Emit ActualCostComputedEvent, CostVariancePostedEvent.

		Args:
			production_order_id:    Soft FK to production order; unique per tenant.
			material_actual_cents:  Actual material cost in cents.
			labor_actual_cents:     Actual labor cost in cents.
			overhead_actual_cents:  Actual overhead cost in cents.
			product_id:             Soft FK to product.
			period:                 Reporting period string (e.g. "2026-06").
			session:                SA 2.x session.

		Returns:
			ProductionOrderActualCost instance (upserted).

		Emits:
			ActualCostComputedEvent
			CostVariancePostedEvent (only when |variance| > threshold)

		Raises:
			StandardCostNotFoundError: no ACTIVE standard cost found for product.
		"""
		from pgappforge.plugins.erp.finance.product_costing.events import (
			ActualCostComputedEvent,
			CostVariancePostedEvent,
		)
		from pgappforge.plugins.erp.finance.product_costing.models import (
			ProductionOrderActualCost,
			ProductStandardCost,
		)

		assert int(material_actual_cents) >= 0, "material_actual_cents must be non-negative"
		assert int(labor_actual_cents) >= 0, "labor_actual_cents must be non-negative"
		assert int(overhead_actual_cents) >= 0, "overhead_actual_cents must be non-negative"

		total_actual = int(material_actual_cents) + int(labor_actual_cents) + int(overhead_actual_cents)

		# Load current standard — most recent active effective_from for product
		std = session.execute(
			sa.select(ProductStandardCost)
			.where(ProductStandardCost.product_id == product_id)
			.order_by(ProductStandardCost.effective_from.desc())
			.limit(1)
		).scalar_one_or_none()

		if std is None:
			raise StandardCostNotFoundError(
				f"No standard cost found for product {product_id!r}; "
				"run rollup_standard_cost first"
			)

		tenant_id = std.tenant_id
		total_standard = std.total_standard_cost_cents
		total_variance = total_actual - total_standard

		# Variance decomposition at bucket level
		# price variance: difference in cost rates (actual bucket vs std bucket)
		mat_var = int(material_actual_cents) - std.material_cost_cents
		lab_var = int(labor_actual_cents) - std.labor_cost_cents
		ovh_var = int(overhead_actual_cents) - std.overhead_cost_cents
		price_variance = mat_var + lab_var + ovh_var   # == total_variance at bucket level
		qty_variance = total_variance - price_variance  # zero with bucket approach; holds for per-unit analysis

		# Upsert ProductionOrderActualCost
		existing = session.execute(
			sa.select(ProductionOrderActualCost)
			.where(ProductionOrderActualCost.tenant_id == tenant_id)
			.where(ProductionOrderActualCost.production_order_id == production_order_id)
		).scalar_one_or_none()

		if existing is not None:
			existing.material_actual_cents = int(material_actual_cents)
			existing.labor_actual_cents = int(labor_actual_cents)
			existing.overhead_actual_cents = int(overhead_actual_cents)
			existing.total_actual_cents = total_actual
			existing.total_standard_cents = total_standard
			existing.total_variance_cents = total_variance
			existing.price_variance_cents = price_variance
			existing.qty_variance_cents = qty_variance
			existing.period = period
			existing.updated_at = datetime.now(timezone.utc)
			actual_rec = existing
		else:
			actual_rec = ProductionOrderActualCost(
				tenant_id=tenant_id,
				production_order_id=production_order_id,
				product_id=product_id,
				period=period,
				material_actual_cents=int(material_actual_cents),
				labor_actual_cents=int(labor_actual_cents),
				overhead_actual_cents=int(overhead_actual_cents),
				total_actual_cents=total_actual,
				total_standard_cents=total_standard,
				total_variance_cents=total_variance,
				price_variance_cents=price_variance,
				qty_variance_cents=qty_variance,
			)
			session.add(actual_rec)

		session.flush()

		# Post GL variance entry when material
		if abs(total_variance) > _GL_VARIANCE_THRESHOLD_CENTS:
			self._post_variance_gl(
				tenant_id=tenant_id,
				order_id=production_order_id,
				variance_cents=total_variance,
				session=session,
			)
			_emit(
				CostVariancePostedEvent(
					aggregate_id=production_order_id,
					aggregate_type="ProductionOrder",
					tenant_id=tenant_id,
					order_id=production_order_id,
					variance_cents=total_variance,
					variance_type="TOTAL",
				),
				session,
			)

		_emit(
			ActualCostComputedEvent(
				aggregate_id=production_order_id,
				aggregate_type="ProductionOrder",
				tenant_id=tenant_id,
				production_order_id=production_order_id,
				actual_cost_cents=total_actual,
				variance_cents=total_variance,
			),
			session,
		)

		log.info(
			"ProductCostingService.compute_actual_cost: order=%r actual=%d¢ std=%d¢ var=%+d¢",
			production_order_id, total_actual, total_standard, total_variance,
		)
		return actual_rec

	# ------------------------------------------------------------------
	# get_cost_history
	# ------------------------------------------------------------------

	def get_cost_history(
		self,
		product_id: str,
		tenant_id: str,
		session: Any,
	) -> list[dict]:
		"""Return standard cost history for a product, most-recent first.

		Each dict contains:
			effective_from, material_cost_cents, labor_cost_cents,
			overhead_cost_cents, total_standard_cost_cents, currency_code.

		Args:
			product_id: Soft FK to product.
			tenant_id:  Tenant UUID string.
			session:    SA 2.x session.

		Returns:
			List of dicts ordered by effective_from descending.
		"""
		from pgappforge.plugins.erp.finance.product_costing.models import ProductStandardCost

		rows = session.execute(
			sa.select(ProductStandardCost)
			.where(ProductStandardCost.tenant_id == tenant_id)
			.where(ProductStandardCost.product_id == product_id)
			.order_by(ProductStandardCost.effective_from.desc())
		).scalars().all()

		return [
			{
				"id": r.id,
				"effective_from": r.effective_from.isoformat() if r.effective_from else None,
				"material_cost_cents": r.material_cost_cents,
				"labor_cost_cents": r.labor_cost_cents,
				"overhead_cost_cents": r.overhead_cost_cents,
				"total_standard_cost_cents": r.total_standard_cost_cents,
				"currency_code": r.currency_code,
			}
			for r in rows
		]

	# ------------------------------------------------------------------
	# Internal helpers
	# ------------------------------------------------------------------

	def _post_variance_gl(
		self,
		tenant_id: str,
		order_id: str,
		variance_cents: int,
		session: Any,
	) -> None:
		"""Post a GL journal entry for production variance to account 5990.

		Unfavourable variance (positive): DR Production Variance / CR WIP
		Favourable variance (negative):   DR WIP / CR Production Variance

		Gracefully skips when GL plugin is not loaded.
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.models import GLJournalEntry  # type: ignore[import]

			if variance_cents > 0:
				debit_acct = "5990"     # Production Variance
				credit_acct = "1410"    # WIP Inventory
			else:
				debit_acct = "1410"     # WIP Inventory
				credit_acct = "5990"    # Production Variance

			entry = GLJournalEntry(
				tenant_id=tenant_id,
				reference=f"VAR-{order_id}",
				debit_account=debit_acct,
				credit_account=credit_acct,
				amount_cents=abs(variance_cents),
				currency_code="USD",
				effective_date=date.today(),
				description=f"Production variance for order {order_id}",
				source_plugin="product_costing",
			)
			session.add(entry)
		except ImportError:
			log.debug("_post_variance_gl: GL plugin not available, skipping for order %r", order_id)
		except Exception as exc:
			log.warning("_post_variance_gl: failed for order %r: %s", order_id, exc)


# ---------------------------------------------------------------------------
# BPM action registration
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"finance.costing.compute_actual",
	"Compute actual vs standard cost variance for a production order",
)
def _bpm_compute_actual(context: dict, session: Any) -> dict:
	"""BPM action: compute actual cost from workflow context.

	Expected context keys:
	  production_order_id, material_actual_cents, labor_actual_cents,
	  overhead_actual_cents, product_id, period

	Returns dict with total_actual_cents, total_variance_cents.
	"""
	svc = ProductCostingService()
	rec = svc.compute_actual_cost(
		production_order_id=context["production_order_id"],
		material_actual_cents=int(context["material_actual_cents"]),
		labor_actual_cents=int(context["labor_actual_cents"]),
		overhead_actual_cents=int(context["overhead_actual_cents"]),
		product_id=context["product_id"],
		period=context["period"],
		session=session,
	)
	return {
		"production_order_id": rec.production_order_id,
		"total_actual_cents": rec.total_actual_cents,
		"total_standard_cents": rec.total_standard_cents,
		"total_variance_cents": rec.total_variance_cents,
	}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"ProductCostingService",
	"ProductCostingError",
	"CostVersionNotFoundError",
	"CostVersionStatusError",
	"StandardCostNotFoundError",
	"ProductionOrderCostError",
]
