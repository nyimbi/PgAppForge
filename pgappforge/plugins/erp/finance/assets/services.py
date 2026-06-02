"""
pgappforge/plugins/erp/finance/assets/services.py

AssetService — stateless business logic layer for Asset Accounting.

All amounts in integer cents. No float arithmetic anywhere.
All depreciation calculations use Python Decimal for precision.

Public API
----------
  capitalize(details, session)             -> FixedAsset
  run_depreciation(period_id, session)     -> list[AssetDepreciation]
  record_disposal(asset_id, proceeds_cents, disposal_date, session) -> FixedAsset
  record_impairment(asset_id, recoverable_amount_cents, date, reason, session) -> AssetImpairment
  get_asset_register(tenant_id, session)   -> list[FixedAsset]
  asset_schedule(asset_id, session)        -> list[dict]  # full depreciation schedule
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AssetServiceError(Exception):
	"""Base error for Asset Accounting service operations."""


class AssetNotFoundError(AssetServiceError):
	"""Asset does not exist or belongs to a different tenant."""


class AssetStatusError(AssetServiceError):
	"""Operation not permitted in current asset status."""


class DepreciationError(AssetServiceError):
	"""Depreciation calculation or posting error."""


# ---------------------------------------------------------------------------
# Capitalisation details dataclass
# ---------------------------------------------------------------------------

@dataclass
class CapitaliseDetails:
	"""Input DTO for AssetService.capitalize()."""
	tenant_id: str
	asset_class_id: str
	description: str
	acquisition_date: date
	acquisition_cost_cents: int       # never float
	residual_value_cents: int = 0
	useful_life_years: Decimal | None = None   # None = inherit from AssetClass
	depreciation_method: str | None = None     # None = inherit from AssetClass
	location: str | None = None
	custodian_id: str | None = None
	serial_number: str | None = None
	expected_total_units: int | None = None    # required for UNITS_OF_PRODUCTION
	asset_number: str | None = None            # None = auto-generate
	metadata: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# AssetService
# ---------------------------------------------------------------------------

class AssetService:
	"""Stateless service layer for Asset Accounting operations.

	Instantiate once and reuse across requests; holds no mutable state.
	All methods accept an explicit SQLAlchemy session parameter — the caller
	owns the transaction boundary (commit/rollback).
	"""

	# ------------------------------------------------------------------ #
	# Capitalise
	# ------------------------------------------------------------------ #

	def capitalize(self, details: CapitaliseDetails, session: Any) -> Any:
		"""Create and capitalise a new fixed asset.

		Inherits useful_life_years and depreciation_method from the AssetClass
		when not specified in details. Emits AssetCapitalisedEvent.

		Returns the persisted FixedAsset instance (id populated after flush).
		"""
		from pgappforge.plugins.erp.finance.assets.models import AssetClass, FixedAsset
		from pgappforge.plugins.erp.finance.assets.events import AssetCapitalisedEvent, emit_event

		assert details.acquisition_cost_cents > 0, "acquisition_cost_cents must be positive"
		assert details.residual_value_cents >= 0, "residual_value_cents must be non-negative"
		assert details.acquisition_cost_cents > details.residual_value_cents, \
			"cost must exceed residual value"

		asset_class = session.get(AssetClass, details.asset_class_id)
		if asset_class is None:
			raise AssetServiceError(f"AssetClass {details.asset_class_id!r} not found")

		useful_life = Decimal(str(details.useful_life_years or asset_class.useful_life_years))
		method = details.depreciation_method or asset_class.depreciation_method
		asset_number = details.asset_number or self._generate_asset_number(session)

		asset = FixedAsset(
			tenant_id=details.tenant_id,
			asset_class_id=details.asset_class_id,
			asset_number=asset_number,
			description=details.description,
			acquisition_date=details.acquisition_date,
			acquisition_cost_cents=details.acquisition_cost_cents,
			residual_value_cents=details.residual_value_cents,
			useful_life_years=useful_life,
			depreciation_method=method,
			current_book_value_cents=details.acquisition_cost_cents,
			accumulated_depreciation_cents=0,
			location=details.location,
			custodian_id=details.custodian_id,
			serial_number=details.serial_number,
			expected_total_units=details.expected_total_units,
			status="ACTIVE",
			metadata_=details.metadata or {},
		)
		session.add(asset)
		session.flush()

		emit_event(
			AssetCapitalisedEvent(
				aggregate_id=asset.id,
				aggregate_type="FixedAsset",
				tenant_id=details.tenant_id,
				asset_id=asset.id,
				asset_number=asset.asset_number,
				asset_class_id=details.asset_class_id,
				acquisition_cost_cents=details.acquisition_cost_cents,
				acquisition_date=str(details.acquisition_date),
			),
			session,
		)
		log.info("Capitalised asset %r (%s) cost=%d", asset.asset_number, asset.id, details.acquisition_cost_cents)
		return asset

	# ------------------------------------------------------------------ #
	# Run Depreciation
	# ------------------------------------------------------------------ #

	def run_depreciation(self, period_id: str, session: Any, tenant_id: str | None = None) -> list[Any]:
		"""Run periodic depreciation for all ACTIVE assets.

		Skips assets already depreciated in this period (idempotent by
		the unique constraint on asset_id + period_id).

		Args:
			period_id:  String identifier for the accounting period, e.g. "2026-01".
			session:    SQLAlchemy session.
			tenant_id:  Filter to a single tenant. None = all tenants.

		Returns list of AssetDepreciation rows inserted.
		"""
		from pgappforge.plugins.erp.finance.assets.models import AssetDepreciation, FixedAsset
		from pgappforge.plugins.erp.finance.assets.events import AssetDepreciationRunEvent, emit_event

		q = (
			sa.select(FixedAsset)
			.where(FixedAsset.status == "ACTIVE")
		)
		if tenant_id:
			q = q.where(FixedAsset.tenant_id == tenant_id)
		assets = session.execute(q).scalars().all()

		# Assets already processed this period
		already = set(
			session.execute(
				sa.select(AssetDepreciation.asset_id)
				.where(AssetDepreciation.period_id == period_id)
			).scalars().all()
		)

		entries: list[AssetDepreciation] = []
		total_cents = 0

		for asset in assets:
			if asset.id in already:
				log.debug("Skipping %r — already depreciated in %r", asset.asset_number, period_id)
				continue

			charge = self._calculate_depreciation(asset)
			if charge == 0:
				continue

			opening_nbv = asset.current_book_value_cents
			closing_nbv = max(opening_nbv - charge, asset.residual_value_cents)
			actual_charge = opening_nbv - closing_nbv

			entry = AssetDepreciation(
				tenant_id=asset.tenant_id,
				asset_id=asset.id,
				period_id=period_id,
				depreciation_amount_cents=actual_charge,
				opening_nbv_cents=opening_nbv,
				closing_nbv_cents=closing_nbv,
				method_used=asset.depreciation_method,
			)
			session.add(entry)

			# Update asset NBV (this is the one legitimate mutation on FixedAsset)
			asset.current_book_value_cents = closing_nbv
			asset.accumulated_depreciation_cents += actual_charge
			asset.last_depreciation_date = date.today()
			if closing_nbv <= asset.residual_value_cents:
				asset.status = "FULLY_DEPRECIATED"

			entries.append(entry)
			total_cents += actual_charge

		session.flush()

		if entries:
			emit_event(
				AssetDepreciationRunEvent(
					aggregate_id=period_id,
					aggregate_type="DepreciationRun",
					tenant_id=tenant_id or "",
					period_id=period_id,
					assets_processed=len(entries),
					total_depreciation_cents=total_cents,
				),
				session,
			)

		log.info(
			"Depreciation run period=%r: %d assets, total=%d cents",
			period_id, len(entries), total_cents,
		)
		return entries

	# ------------------------------------------------------------------ #
	# Disposal
	# ------------------------------------------------------------------ #

	def record_disposal(
		self,
		asset_id: str,
		proceeds_cents: int,
		session: Any,
		disposal_date: date | None = None,
	) -> Any:
		"""Record disposal of a fixed asset.

		Calculates gain/loss = proceeds - NBV at disposal date.
		Marks asset status DISPOSED (immutable — no further depreciation).
		Emits AssetDisposedEvent.
		"""
		from pgappforge.plugins.erp.finance.assets.models import FixedAsset
		from pgappforge.plugins.erp.finance.assets.events import AssetDisposedEvent, emit_event

		assert proceeds_cents >= 0, "proceeds_cents must be non-negative"

		asset = session.get(FixedAsset, asset_id)
		if asset is None:
			raise AssetNotFoundError(f"FixedAsset {asset_id!r} not found")
		if asset.status == "DISPOSED":
			raise AssetStatusError(f"Asset {asset.asset_number!r} is already disposed")

		d = disposal_date or date.today()
		gain_loss = proceeds_cents - asset.current_book_value_cents

		asset.status = "DISPOSED"
		asset.disposal_date = d
		asset.disposal_proceeds_cents = proceeds_cents
		asset.disposal_gain_loss_cents = gain_loss
		asset.updated_at = datetime.now(timezone.utc)

		emit_event(
			AssetDisposedEvent(
				aggregate_id=asset_id,
				aggregate_type="FixedAsset",
				tenant_id=asset.tenant_id,
				asset_id=asset_id,
				asset_number=asset.asset_number,
				disposal_date=str(d),
				proceeds_cents=proceeds_cents,
				gain_loss_cents=gain_loss,
			),
			session,
		)
		log.info(
			"Disposed asset %r proceeds=%d gain_loss=%d",
			asset.asset_number, proceeds_cents, gain_loss,
		)
		return asset

	# ------------------------------------------------------------------ #
	# Impairment
	# ------------------------------------------------------------------ #

	def record_impairment(
		self,
		asset_id: str,
		recoverable_amount_cents: int,
		reason: str,
		session: Any,
		impairment_date: date | None = None,
	) -> Any:
		"""Record an IAS 36 impairment loss.

		Impairment loss = carrying_amount (NBV) - recoverable_amount.
		Reduces asset's current_book_value_cents.
		Emits AssetImpairedEvent.

		Returns the AssetImpairment record.
		"""
		from pgappforge.plugins.erp.finance.assets.models import AssetImpairment, FixedAsset
		from pgappforge.plugins.erp.finance.assets.events import AssetImpairedEvent, emit_event

		assert recoverable_amount_cents >= 0, "recoverable_amount_cents must be non-negative"

		asset = session.get(FixedAsset, asset_id)
		if asset is None:
			raise AssetNotFoundError(f"FixedAsset {asset_id!r} not found")
		if asset.status == "DISPOSED":
			raise AssetStatusError("Cannot impair a disposed asset")

		carrying = asset.current_book_value_cents
		if recoverable_amount_cents >= carrying:
			raise AssetServiceError(
				f"Recoverable amount ({recoverable_amount_cents}) >= carrying amount ({carrying}); "
				"no impairment required"
			)

		loss = carrying - recoverable_amount_cents
		d = impairment_date or date.today()

		impairment = AssetImpairment(
			tenant_id=asset.tenant_id,
			asset_id=asset_id,
			impairment_date=d,
			carrying_amount_cents=carrying,
			recoverable_amount_cents=recoverable_amount_cents,
			impairment_loss_cents=loss,
			reason=reason,
			is_reversal=False,
		)
		session.add(impairment)

		# Write down NBV
		asset.current_book_value_cents = recoverable_amount_cents
		asset.accumulated_depreciation_cents += loss
		asset.status = "IMPAIRED"
		asset.updated_at = datetime.now(timezone.utc)

		emit_event(
			AssetImpairedEvent(
				aggregate_id=asset_id,
				aggregate_type="FixedAsset",
				tenant_id=asset.tenant_id,
				asset_id=asset_id,
				asset_number=asset.asset_number,
				impairment_date=str(d),
				impairment_loss_cents=loss,
				recoverable_amount_cents=recoverable_amount_cents,
			),
			session,
		)
		log.info(
			"Impairment recorded asset=%r loss=%d recoverable=%d",
			asset.asset_number, loss, recoverable_amount_cents,
		)
		return impairment

	# ------------------------------------------------------------------ #
	# Asset register / schedule
	# ------------------------------------------------------------------ #

	def get_asset_register(self, tenant_id: str, session: Any, status: str | None = None) -> list[Any]:
		"""Return all fixed assets for a tenant, optionally filtered by status."""
		from pgappforge.plugins.erp.finance.assets.models import FixedAsset
		q = (
			sa.select(FixedAsset)
			.where(FixedAsset.tenant_id == tenant_id)
			.order_by(FixedAsset.asset_number)
		)
		if status:
			q = q.where(FixedAsset.status == status.upper())
		return session.execute(q).scalars().all()

	def asset_schedule(self, asset_id: str, session: Any) -> list[dict]:
		"""Return the full depreciation schedule for an asset.

		Each entry shows the period, opening NBV, charge, and closing NBV.
		"""
		from pgappforge.plugins.erp.finance.assets.models import AssetDepreciation
		entries = session.execute(
			sa.select(AssetDepreciation)
			.where(AssetDepreciation.asset_id == asset_id)
			.order_by(AssetDepreciation.period_id)
		).scalars().all()
		return [
			{
				"period_id": e.period_id,
				"depreciation_amount_cents": e.depreciation_amount_cents,
				"opening_nbv_cents": e.opening_nbv_cents,
				"closing_nbv_cents": e.closing_nbv_cents,
				"method_used": e.method_used,
				"posted_at": e.posted_at.isoformat() if e.posted_at else None,
			}
			for e in entries
		]

	# ------------------------------------------------------------------ #
	# Internal helpers
	# ------------------------------------------------------------------ #

	def _calculate_depreciation(self, asset: Any) -> int:
		"""Calculate depreciation charge for one period (month).

		Returns integer cents. Uses Decimal arithmetic — never float.
		"""
		method = asset.depreciation_method
		cost = Decimal(asset.acquisition_cost_cents)
		residual = Decimal(asset.residual_value_cents)
		nbv = Decimal(asset.current_book_value_cents)
		life_years = Decimal(str(asset.useful_life_years))

		if life_years <= 0:
			return 0

		depreciable = cost - residual
		if depreciable <= 0:
			return 0

		if method == "STRAIGHT_LINE":
			annual = depreciable / life_years
			monthly = annual / Decimal("12")

		elif method == "DECLINING":
			rate = Decimal("2") / life_years
			annual = nbv * rate
			monthly = annual / Decimal("12")

		elif method == "UNITS_OF_PRODUCTION":
			# Return 0 here; actual charge is applied via record_units_depreciation()
			return 0

		else:
			log.warning("Unknown depreciation method %r for asset %r", method, asset.id)
			return 0

		charge = monthly.to_integral_value(rounding=ROUND_HALF_UP)
		return int(charge)

	def _generate_asset_number(self, session: Any) -> str:
		"""Generate a sequential asset number FA-YYYY-NNNNN."""
		from pgappforge.plugins.erp.finance.assets.models import FixedAsset
		year = date.today().year
		count = session.execute(
			sa.select(sa.func.count(FixedAsset.id))
		).scalar_one()
		return f"FA-{year}-{count + 1:05d}"


__all__ = [
	"AssetService",
	"AssetServiceError",
	"AssetNotFoundError",
	"AssetStatusError",
	"DepreciationError",
	"CapitaliseDetails",
]
