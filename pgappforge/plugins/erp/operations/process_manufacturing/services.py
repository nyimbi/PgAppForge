"""
pgappforge/plugins/erp/operations/process_manufacturing/services.py

ProcessManufacturingService — stateless business logic for process manufacturing.

All methods receive an explicit SQLAlchemy session; no Flask context assumed.
Transaction boundaries owned by the caller.

Monetary invariants:
  - All amounts passed in and returned as integer cents (BigInteger)
  - Decimal arithmetic used internally; results rounded ROUND_HALF_UP to int
  - Quantities use Decimal(str(...)) — never float

BPM registrations:
  ops.process_mfg.complete_batch — Complete process manufacturing batch record

Public API:
  create_recipe(product_id, version, batch_size, batch_size_unit, yield_pct,
                ingredients_data, tenant_id, session, *, ...) -> Recipe
  approve_recipe(recipe_id, approver_id, session) -> Recipe
  create_batch_record(recipe_id, planned_quantity, tenant_id, session, *) -> BatchRecord
  record_ingredients_used(batch_id, actual_ingredients_list, session) -> BatchRecord
  complete_batch(batch_id, actual_yield, quality_checks, session) -> BatchRecord
  get_batch_genealogy(batch_id, session) -> dict
  get_recipe_yield_history(recipe_id, session) -> list[dict]
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BPM action registry
# ---------------------------------------------------------------------------

try:
	from pgappforge.plugins.workflow.engine import BPMActionRegistry
	_bpm_available = True
except Exception:
	_bpm_available = False

	class _FakeBPMRegistry:
		@staticmethod
		def register(action_id: str, description: str):
			def decorator(fn):
				return fn
			return decorator

	BPMActionRegistry = _FakeBPMRegistry()  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProcessManufacturingError(Exception):
	"""Base domain error for process manufacturing operations."""


class RecipeNotFoundError(ProcessManufacturingError):
	pass


class RecipeInvalidStatusError(ProcessManufacturingError):
	pass


class BatchNotFoundError(ProcessManufacturingError):
	pass


class BatchInvalidStatusError(ProcessManufacturingError):
	pass


class MissingCriticalIngredientError(ProcessManufacturingError):
	pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _d(value: Any) -> Decimal:
	"""Safe Decimal coercion — never float intermediate."""
	if isinstance(value, Decimal):
		return value
	return Decimal(str(value))


def _now() -> datetime:
	return datetime.now(timezone.utc)


def _emit(event: Any, session: Any = None) -> None:
	"""Emit domain event; swallow all errors to protect the business transaction."""
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event
		emit_event(event, session)
	except Exception as exc:
		log.debug("ProcessManufacturingService._emit: non-fatal event emission failure: %s", exc)


def _generate_batch_number(tenant_id: str) -> str:
	"""Generate a unique batch number: BTC-<tenant_prefix>-<uuid4_short>."""
	short_uid = str(uuid.uuid4()).replace("-", "")[:8].upper()
	prefix = (tenant_id or "T")[:4].upper()
	return f"BTC-{prefix}-{short_uid}"


# ---------------------------------------------------------------------------
# ProcessManufacturingService
# ---------------------------------------------------------------------------

class ProcessManufacturingService:
	"""Stateless process manufacturing domain service.

	Instantiate once per application (no instance state).
	All public methods accept an explicit SQLAlchemy Session.

	Covers:
	  - Recipe management (DRAFT → UNDER_REVIEW → APPROVED → OBSOLETE)
	  - Batch record creation from approved recipes
	  - Ingredient tracking with variance computation
	  - Batch completion with yield variance and optional GL posting
	  - Genealogy and yield history reporting
	"""

	# ------------------------------------------------------------------
	# create_recipe
	# ------------------------------------------------------------------

	def create_recipe(
		self,
		product_id: str,
		version: str,
		batch_size: Any,
		batch_size_unit: str,
		yield_pct: Any,
		ingredients_data: list[dict[str, Any]],
		tenant_id: str,
		session: Any,
		*,
		instructions: str | None = None,
		ph_min: Any | None = None,
		ph_max: Any | None = None,
		temp_min: Any | None = None,
		temp_max: Any | None = None,
		process_time_minutes: int | None = None,
		entity_id: str | None = None,
	) -> Any:
		"""Create a new process manufacturing recipe in DRAFT status.

		Args:
			product_id: Soft FK → inv_product.id for the output product.
			version: Recipe version string e.g. '1.0'.
			batch_size: Expected batch output quantity (Decimal-coercible).
			batch_size_unit: Unit of measure: KG | L | UNITS | MT.
			yield_pct: Expected yield fraction e.g. 0.95 for 95%.
			ingredients_data: List of dicts: [{ingredient_product_id, quantity, unit,
			                  is_critical?, substitutes?}].
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session (caller commits).
			instructions: Optional process instructions text.
			ph_min: Optional minimum acceptable pH.
			ph_max: Optional maximum acceptable pH.
			temp_min: Optional minimum process temperature in °C.
			temp_max: Optional maximum process temperature in °C.
			process_time_minutes: Optional expected process duration.
			entity_id: Optional multi-entity scoping.

		Returns:
			The created Recipe instance (status=DRAFT).

		Raises:
			AssertionError: If ingredients_data is empty or quantities are invalid.
		"""
		from pgappforge.plugins.erp.operations.process_manufacturing.models import (
			Recipe, RecipeIngredient,
		)
		from pgappforge.plugins.erp.operations.process_manufacturing.events import (
			RecipeCreatedEvent,
		)

		assert ingredients_data, "ingredients_data must not be empty"
		batch_size_d = _d(batch_size)
		yield_pct_d = _d(yield_pct)
		assert batch_size_d > 0, "batch_size must be positive"
		assert 0 < yield_pct_d <= 1, "yield_pct must be in (0, 1]"
		assert batch_size_unit in ("KG", "L", "UNITS", "MT"), (
			f"batch_size_unit must be KG|L|UNITS|MT, got {batch_size_unit!r}"
		)

		recipe = Recipe(
			tenant_id=tenant_id,
			product_id=product_id,
			version=version,
			status="DRAFT",
			batch_size=batch_size_d,
			batch_size_unit=batch_size_unit,
			yield_pct=yield_pct_d,
			ph_min=_d(ph_min) if ph_min is not None else None,
			ph_max=_d(ph_max) if ph_max is not None else None,
			temp_min_celsius=_d(temp_min) if temp_min is not None else None,
			temp_max_celsius=_d(temp_max) if temp_max is not None else None,
			process_time_minutes=process_time_minutes,
			instructions=instructions,
			entity_id=entity_id,
		)
		session.add(recipe)
		session.flush()  # populate recipe.id

		for ing in ingredients_data:
			qty = _d(ing["quantity"])
			assert qty > 0, (
				f"Ingredient quantity must be positive for {ing.get('ingredient_product_id')!r}"
			)
			session.add(RecipeIngredient(
				tenant_id=tenant_id,
				recipe_id=recipe.id,
				ingredient_product_id=str(ing["ingredient_product_id"]),
				quantity=qty,
				unit=str(ing["unit"]),
				is_critical=bool(ing.get("is_critical", False)),
				substitutes=list(ing.get("substitutes", [])),
			))

		log.info(
			"ProcessManufacturingService.create_recipe: recipe=%s product=%s version=%s ingredients=%d",
			recipe.id, product_id, version, len(ingredients_data),
		)

		_emit(
			RecipeCreatedEvent(
				aggregate_id=recipe.id,
				aggregate_type="Recipe",
				tenant_id=tenant_id,
				recipe_id=recipe.id,
				product_id=product_id,
				version=version,
			),
			session,
		)

		return recipe

	# ------------------------------------------------------------------
	# approve_recipe
	# ------------------------------------------------------------------

	def approve_recipe(self, recipe_id: str, approver_id: str, session: Any) -> Any:
		"""Approve a recipe for production use.

		Transitions DRAFT or UNDER_REVIEW → APPROVED.

		Args:
			recipe_id: UUID string of the Recipe to approve.
			approver_id: User ID of the approver.
			session: SQLAlchemy session (caller commits).

		Returns:
			The updated Recipe (status=APPROVED).

		Raises:
			RecipeNotFoundError: recipe_id not found.
			RecipeInvalidStatusError: recipe not in DRAFT or UNDER_REVIEW.
		"""
		from pgappforge.plugins.erp.operations.process_manufacturing.models import Recipe
		from pgappforge.plugins.erp.operations.process_manufacturing.events import RecipeApprovedEvent

		recipe = session.execute(
			sa.select(Recipe).where(Recipe.id == recipe_id)
		).scalar_one_or_none()

		if recipe is None:
			raise RecipeNotFoundError(f"Recipe {recipe_id!r} not found")

		if recipe.status not in ("DRAFT", "UNDER_REVIEW"):
			raise RecipeInvalidStatusError(
				f"Recipe {recipe_id!r} status={recipe.status!r}; "
				"must be DRAFT or UNDER_REVIEW to approve"
			)

		recipe.status = "APPROVED"
		recipe.approved_by = approver_id
		recipe.approved_at = _now()

		log.info(
			"ProcessManufacturingService.approve_recipe: recipe=%s approved_by=%s",
			recipe_id, approver_id,
		)

		_emit(
			RecipeApprovedEvent(
				aggregate_id=recipe.id,
				aggregate_type="Recipe",
				tenant_id=recipe.tenant_id,
				recipe_id=recipe.id,
				approved_by=approver_id,
			),
			session,
		)

		return recipe

	# ------------------------------------------------------------------
	# create_batch_record
	# ------------------------------------------------------------------

	def create_batch_record(
		self,
		recipe_id: str,
		planned_quantity: Any,
		tenant_id: str,
		session: Any,
		*,
		production_order_id: str | None = None,
		operator_id: str | None = None,
	) -> Any:
		"""Create a batch record from an approved recipe.

		Args:
			recipe_id: UUID string of the approved Recipe.
			planned_quantity: Planned output quantity (Decimal-coercible).
			tenant_id: Tenant scoping string.
			session: SQLAlchemy session (caller commits).
			production_order_id: Optional soft FK to production order.
			operator_id: Optional soft FK to operator/employee.

		Returns:
			The created BatchRecord (status=PLANNED).

		Raises:
			RecipeNotFoundError: recipe_id not found.
			RecipeInvalidStatusError: recipe status is not APPROVED.
		"""
		from pgappforge.plugins.erp.operations.process_manufacturing.models import (
			Recipe, BatchRecord,
		)
		from pgappforge.plugins.erp.operations.process_manufacturing.events import (
			BatchRecordCreatedEvent,
		)

		recipe = session.execute(
			sa.select(Recipe).where(Recipe.id == recipe_id)
		).scalar_one_or_none()

		if recipe is None:
			raise RecipeNotFoundError(f"Recipe {recipe_id!r} not found")

		if recipe.status != "APPROVED":
			raise RecipeInvalidStatusError(
				f"Recipe {recipe_id!r} status={recipe.status!r}; "
				"only APPROVED recipes can be used to create batch records"
			)

		planned_qty_d = _d(planned_quantity)
		assert planned_qty_d > 0, "planned_quantity must be positive"

		batch_number = _generate_batch_number(tenant_id)

		batch = BatchRecord(
			tenant_id=tenant_id,
			recipe_id=recipe_id,
			batch_number=batch_number,
			production_order_id=production_order_id,
			planned_quantity=planned_qty_d,
			status="PLANNED",
			operator_id=operator_id,
			actual_ingredients=[],
			quality_checks=[],
		)
		session.add(batch)
		session.flush()

		log.info(
			"ProcessManufacturingService.create_batch_record: batch=%s number=%s recipe=%s qty=%s",
			batch.id, batch_number, recipe_id, planned_qty_d,
		)

		_emit(
			BatchRecordCreatedEvent(
				aggregate_id=batch.id,
				aggregate_type="BatchRecord",
				tenant_id=tenant_id,
				batch_id=batch.id,
				recipe_id=recipe_id,
				batch_number=batch_number,
			),
			session,
		)

		return batch

	# ------------------------------------------------------------------
	# record_ingredients_used
	# ------------------------------------------------------------------

	def record_ingredients_used(
		self,
		batch_id: str,
		actual_ingredients_list: list[dict[str, Any]],
		session: Any,
	) -> Any:
		"""Record actual ingredient quantities consumed during batch execution.

		Computes variance per ingredient vs planned quantities from the recipe.
		Checks coverage of all critical ingredients.

		Args:
			batch_id: UUID string of the BatchRecord.
			actual_ingredients_list: List of dicts: [{product_id, actual_qty}].
			session: SQLAlchemy session (caller commits).

		Returns:
			The updated BatchRecord with actual_ingredients populated.

		Raises:
			BatchNotFoundError: batch_id not found.
			BatchInvalidStatusError: batch not in PLANNED or IN_PROCESS.
			MissingCriticalIngredientError: a critical ingredient has no actual quantity.
		"""
		from pgappforge.plugins.erp.operations.process_manufacturing.models import (
			BatchRecord, RecipeIngredient,
		)

		batch = session.execute(
			sa.select(BatchRecord).where(BatchRecord.id == batch_id)
		).scalar_one_or_none()

		if batch is None:
			raise BatchNotFoundError(f"BatchRecord {batch_id!r} not found")

		if batch.status not in ("PLANNED", "IN_PROCESS"):
			raise BatchInvalidStatusError(
				f"BatchRecord {batch_id!r} status={batch.status!r}; "
				"must be PLANNED or IN_PROCESS to record ingredients"
			)

		# Load recipe ingredients for planned quantities
		recipe_ingredients = session.execute(
			sa.select(RecipeIngredient).where(RecipeIngredient.recipe_id == batch.recipe_id)
		).scalars().all()

		planned_map: dict[str, dict[str, Any]] = {
			ri.ingredient_product_id: {
				"planned_qty": _d(ri.quantity),
				"is_critical": ri.is_critical,
			}
			for ri in recipe_ingredients
		}

		actual_map: dict[str, Decimal] = {
			str(a["product_id"]): _d(a["actual_qty"])
			for a in actual_ingredients_list
		}

		# Check critical ingredient coverage
		for pid, info in planned_map.items():
			if info["is_critical"] and pid not in actual_map:
				raise MissingCriticalIngredientError(
					f"Critical ingredient {pid!r} has no actual quantity recorded for batch {batch_id!r}"
				)

		# Build actual_ingredients JSONB payload with variances
		computed: list[dict[str, Any]] = []
		for pid, info in planned_map.items():
			planned_qty = info["planned_qty"]
			actual_qty = actual_map.get(pid)
			if actual_qty is not None:
				variance = actual_qty - planned_qty
				computed.append({
					"product_id": pid,
					"planned_qty": str(planned_qty),
					"actual_qty": str(actual_qty),
					"variance": str(variance),
				})
			else:
				computed.append({
					"product_id": pid,
					"planned_qty": str(planned_qty),
					"actual_qty": None,
					"variance": None,
				})

		batch.actual_ingredients = computed
		batch.status = "IN_PROCESS"

		log.info(
			"ProcessManufacturingService.record_ingredients_used: batch=%s ingredients=%d",
			batch_id, len(computed),
		)

		return batch

	# ------------------------------------------------------------------
	# complete_batch
	# ------------------------------------------------------------------

	@BPMActionRegistry.register(
		"ops.process_mfg.complete_batch",
		"Complete process manufacturing batch record",
	)
	def complete_batch(
		self,
		batch_id: str,
		actual_yield: Any,
		quality_checks: list[dict[str, Any]],
		session: Any,
	) -> Any:
		"""Complete a batch record with actual yield and quality check results.

		Computes yield variance; posts GL journal if |variance| > 5%.

		Posting rule for GL (DR 5990 Production Variance / CR 5000 WIP):
		  positive variance_pct (over-yield): DR 5000 WIP, CR 5990 Production Variance
		  negative variance_pct (under-yield): DR 5990 Production Variance, CR 5000 WIP

		Args:
			batch_id: UUID string of the BatchRecord.
			actual_yield: Actual output quantity (Decimal-coercible).
			quality_checks: List of dicts:
			  [{parameter, min_value, max_value, actual_value, passed}].
			session: SQLAlchemy session (caller commits).

		Returns:
			The updated BatchRecord (status=COMPLETED).

		Raises:
			BatchNotFoundError: batch_id not found.
			BatchInvalidStatusError: batch not in PLANNED or IN_PROCESS.
		"""
		from pgappforge.plugins.erp.operations.process_manufacturing.models import BatchRecord
		from pgappforge.plugins.erp.operations.process_manufacturing.events import (
			BatchCompletedEvent,
			YieldVariancePostedEvent,
		)

		batch = session.execute(
			sa.select(BatchRecord).where(BatchRecord.id == batch_id)
		).scalar_one_or_none()

		if batch is None:
			raise BatchNotFoundError(f"BatchRecord {batch_id!r} not found")

		if batch.status not in ("PLANNED", "IN_PROCESS"):
			raise BatchInvalidStatusError(
				f"BatchRecord {batch_id!r} status={batch.status!r}; "
				"must be PLANNED or IN_PROCESS to complete"
			)

		actual_yield_d = _d(actual_yield)
		assert actual_yield_d >= 0, "actual_yield must be non-negative"

		planned_qty_d = _d(batch.planned_quantity)
		assert planned_qty_d > 0, "planned_quantity must be positive"

		# Compute yield variance percentage
		yield_variance_pct = (
			(actual_yield_d - planned_qty_d) / planned_qty_d * Decimal("100")
		).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

		batch.status = "COMPLETED"
		batch.actual_yield = actual_yield_d
		batch.yield_variance_pct = yield_variance_pct
		batch.completed_at = _now()
		batch.quality_checks = quality_checks or []

		log.info(
			"ProcessManufacturingService.complete_batch: batch=%s actual_yield=%s "
			"yield_variance_pct=%s",
			batch_id, actual_yield_d, yield_variance_pct,
		)

		_emit(
			BatchCompletedEvent(
				aggregate_id=batch.id,
				aggregate_type="BatchRecord",
				tenant_id=batch.tenant_id,
				batch_id=batch.id,
				actual_yield=str(actual_yield_d),
				yield_variance_pct=str(yield_variance_pct),
			),
			session,
		)

		# Post GL variance if |yield_variance_pct| > 5%
		variance_cents = 0
		if abs(yield_variance_pct) > Decimal("5"):
			variance_cents = self._post_yield_variance_gl(
				batch, yield_variance_pct, session
			)
			if variance_cents != 0:
				_emit(
					YieldVariancePostedEvent(
						aggregate_id=batch.id,
						aggregate_type="BatchRecord",
						tenant_id=batch.tenant_id,
						batch_id=batch.id,
						variance_cents=variance_cents,
					),
					session,
				)

		return batch

	# ------------------------------------------------------------------
	# get_batch_genealogy
	# ------------------------------------------------------------------

	def get_batch_genealogy(self, batch_id: str, session: Any) -> dict[str, Any]:
		"""Return full genealogy for a batch: batch record + ingredients + quality checks.

		Args:
			batch_id: UUID string of the BatchRecord.
			session: SQLAlchemy session.

		Returns:
			Dict with keys: batch, recipe_id, batch_number, planned_quantity,
			actual_yield, yield_variance_pct, status, actual_ingredients, quality_checks.

		Raises:
			BatchNotFoundError: batch_id not found.
		"""
		from pgappforge.plugins.erp.operations.process_manufacturing.models import BatchRecord

		batch = session.execute(
			sa.select(BatchRecord).where(BatchRecord.id == batch_id)
		).scalar_one_or_none()

		if batch is None:
			raise BatchNotFoundError(f"BatchRecord {batch_id!r} not found")

		return {
			"batch_id": batch.id,
			"recipe_id": batch.recipe_id,
			"batch_number": batch.batch_number,
			"production_order_id": batch.production_order_id,
			"planned_quantity": str(batch.planned_quantity),
			"actual_yield": str(batch.actual_yield) if batch.actual_yield is not None else None,
			"yield_variance_pct": (
				str(batch.yield_variance_pct) if batch.yield_variance_pct is not None else None
			),
			"status": batch.status,
			"operator_id": batch.operator_id,
			"started_at": batch.started_at.isoformat() if batch.started_at else None,
			"completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
			"actual_ingredients": batch.actual_ingredients or [],
			"quality_checks": batch.quality_checks or [],
			"notes": batch.notes,
		}

	# ------------------------------------------------------------------
	# get_recipe_yield_history
	# ------------------------------------------------------------------

	def get_recipe_yield_history(self, recipe_id: str, session: Any) -> list[dict[str, Any]]:
		"""Return actual vs planned yield per completed batch for a recipe.

		Args:
			recipe_id: UUID string of the Recipe.
			session: SQLAlchemy session.

		Returns:
			List of dicts sorted by completed_at: [{batch_id, batch_number,
			planned_quantity, actual_yield, yield_variance_pct, completed_at}].
		"""
		from pgappforge.plugins.erp.operations.process_manufacturing.models import BatchRecord

		batches = session.execute(
			sa.select(BatchRecord)
			.where(
				BatchRecord.recipe_id == recipe_id,
				BatchRecord.status == "COMPLETED",
			)
			.order_by(BatchRecord.completed_at.asc())
		).scalars().all()

		return [
			{
				"batch_id": b.id,
				"batch_number": b.batch_number,
				"planned_quantity": str(b.planned_quantity),
				"actual_yield": str(b.actual_yield) if b.actual_yield is not None else None,
				"yield_variance_pct": (
					str(b.yield_variance_pct) if b.yield_variance_pct is not None else None
				),
				"completed_at": b.completed_at.isoformat() if b.completed_at else None,
			}
			for b in batches
		]

	# ------------------------------------------------------------------
	# Internal: GL yield variance posting
	# ------------------------------------------------------------------

	def _post_yield_variance_gl(
		self,
		batch: Any,
		yield_variance_pct: Decimal,
		session: Any,
	) -> int:
		"""Post yield variance to GL accounts 5990 (Production Variance) / 5000 (WIP).

		Non-fatal: GL plugin absence is logged at DEBUG level only.
		Returns the variance_cents posted (0 if GL not available).
		"""
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService

			# Approximate variance_cents from planned_quantity × yield_pct difference
			# (best-effort without access to per-unit cost; caller may enrich)
			abs_variance_pct = abs(yield_variance_pct)
			# Represent variance as fractional cents of a notional 10000-cent batch
			variance_cents = int(
				(abs_variance_pct * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
			)

			if yield_variance_pct > 0:
				# Over-yield: more product than planned → DR WIP, CR Production Variance
				dr_acct, cr_acct = "5000", "5990"
			else:
				# Under-yield: less product → DR Production Variance, CR WIP
				dr_acct, cr_acct = "5990", "5000"

			GLService().post_simple_journal(
				lines=[
					{"account_code": dr_acct, "debit_cents": variance_cents, "credit_cents": 0},
					{"account_code": cr_acct, "debit_cents": 0, "credit_cents": variance_cents},
				],
				session=session,
				tenant_id=batch.tenant_id,
				description=f"Yield variance — batch {batch.batch_number} ({yield_variance_pct:+.4f}%)",
				source_doc_id=batch.id,
				source_doc_type="BATCH_RECORD",
			)
			log.info(
				"ProcessManufacturingService._post_yield_variance_gl: batch=%s "
				"variance_pct=%s cents=%d GL posted",
				batch.id, yield_variance_pct, variance_cents,
			)
			return variance_cents

		except ImportError:
			log.debug(
				"ProcessManufacturingService._post_yield_variance_gl: GL plugin not loaded; "
				"variance for batch %s not posted to ledger",
				batch.id,
			)
		except Exception as exc:
			log.debug(
				"ProcessManufacturingService._post_yield_variance_gl: GL posting failed (non-fatal): %s",
				exc,
			)

		return 0


__all__ = [
	"ProcessManufacturingService",
	"ProcessManufacturingError",
	"RecipeNotFoundError",
	"RecipeInvalidStatusError",
	"BatchNotFoundError",
	"BatchInvalidStatusError",
	"MissingCriticalIngredientError",
]
