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
# MACRS half-year convention rates — IRS Rev. Proc. 87-57
# Keys are recovery periods; values are annual rate lists (year 1 … year n+1).
# ---------------------------------------------------------------------------
MACRS_RATES: dict[int, list[Decimal]] = {
	3: [
		Decimal("0.3333"), Decimal("0.4445"),
		Decimal("0.1481"), Decimal("0.0741"),
	],
	5: [
		Decimal("0.2000"), Decimal("0.3200"), Decimal("0.1920"),
		Decimal("0.1152"), Decimal("0.1152"), Decimal("0.0576"),
	],
	7: [
		Decimal("0.1429"), Decimal("0.2449"), Decimal("0.1749"),
		Decimal("0.1249"), Decimal("0.0893"), Decimal("0.0892"),
		Decimal("0.0893"), Decimal("0.0446"),
	],
	10: [
		Decimal("0.1000"), Decimal("0.1800"), Decimal("0.1440"),
		Decimal("0.1152"), Decimal("0.0922"), Decimal("0.0737"),
		Decimal("0.0655"), Decimal("0.0655"), Decimal("0.0656"),
		Decimal("0.0655"), Decimal("0.0328"),
	],
}


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
	# CapexProject
	# ------------------------------------------------------------------ #

	def create_capex_project(self, session: Any, data: dict[str, Any], tenant_id: str) -> Any:
		"""Create a new CAPEX project.

		Args:
			data: dict with keys project_code, name, budget_cents, expected_completion (date|None),
			      asset_class (str|None), department_id (str|None), committed_cents (int),
			      spent_cents (int), notes (str|None).
			tenant_id: tenant scoping key.

		Returns CapexProject instance after flush.
		"""
		from pgappforge.plugins.erp.finance.assets.models import CapexProject

		assert data.get("budget_cents", 0) > 0, "budget_cents must be positive"
		assert data.get("project_code"), "project_code is required"

		project = CapexProject(
			tenant_id=tenant_id,
			project_code=data["project_code"],
			name=data["name"],
			budget_cents=data["budget_cents"],
			committed_cents=data.get("committed_cents", 0),
			spent_cents=data.get("spent_cents", 0),
			status=data.get("status", "PLANNED"),
			expected_completion=data.get("expected_completion"),
			asset_class=data.get("asset_class"),
			department_id=data.get("department_id"),
			notes=data.get("notes"),
		)
		session.add(project)
		session.flush()
		log.info("Created CAPEX project %r budget=%d", project.project_code, project.budget_cents)
		return project

	# ------------------------------------------------------------------ #
	# Capitalise from CAPEX project
	# ------------------------------------------------------------------ #

	def capitalise_asset_from_project(
		self,
		session: Any,
		project_id: str,
		asset_data: dict[str, Any],
		capitalisation_date: date,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Transfer a completed CAPEX project to the fixed asset register.

		Creates a FixedAsset from the project's WIP balance.
		GL:  DR  fixed_asset  1500   (cost)
		     CR  capex_WIP    1560   (remove WIP)
		Marks project status COMPLETED.

		Args:
			project_id: CapexProject.id
			asset_data: passed directly to CapitaliseDetails (minus tenant_id / acquisition_date)
			capitalisation_date: date the asset enters the register
			tenant_id: tenant scoping key

		Returns dict {asset, project, gl_ref}.
		"""
		from pgappforge.plugins.erp.finance.assets.models import CapexProject

		project = session.get(CapexProject, project_id)
		if project is None:
			raise AssetServiceError(f"CapexProject {project_id!r} not found")
		if project.status == "COMPLETED":
			raise AssetStatusError(f"Project {project.project_code!r} already completed")
		if project.status == "CANCELLED":
			raise AssetStatusError(f"Project {project.project_code!r} is cancelled")

		cost = asset_data.get("acquisition_cost_cents") or project.spent_cents
		assert cost > 0, "acquisition_cost_cents must be positive"

		details = CapitaliseDetails(
			tenant_id=tenant_id,
			asset_class_id=asset_data["asset_class_id"],
			description=asset_data.get("description", project.name),
			acquisition_date=capitalisation_date,
			acquisition_cost_cents=cost,
			residual_value_cents=asset_data.get("residual_value_cents", 0),
			useful_life_years=asset_data.get("useful_life_years"),
			depreciation_method=asset_data.get("depreciation_method"),
			location=asset_data.get("location"),
			custodian_id=asset_data.get("custodian_id"),
			serial_number=asset_data.get("serial_number"),
			asset_number=asset_data.get("asset_number"),
			metadata=asset_data.get("metadata"),
		)
		asset = self.capitalize(details, session)

		project.status = "COMPLETED"

		gl_ref: str | None = None
		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			gl = GLService()
			gl_ref = gl.post_journal(
				{
					"tenant_id": tenant_id,
					"description": f"Capitalise project {project.project_code} → {asset.asset_number}",
					"reference": asset.asset_number,
					"lines": [
						{"account": "1500", "debit": cost, "credit": 0, "description": "Fixed asset cost"},
						{"account": "1560", "debit": 0, "credit": cost, "description": "CAPEX WIP transfer"},
					],
				},
				session=session,
			)
		except Exception as exc:
			log.debug("GL post skipped (plugin not loaded): %s", exc)

		log.info(
			"Capitalised project %r → asset %r cost=%d gl_ref=%r",
			project.project_code, asset.asset_number, cost, gl_ref,
		)
		return {"asset": asset, "project": project, "gl_ref": gl_ref}

	# ------------------------------------------------------------------ #
	# Dispose asset  (structured disposal record)
	# ------------------------------------------------------------------ #

	def dispose_asset(
		self,
		session: Any,
		asset_id: str,
		disposal_date: date,
		disposal_type: str,
		proceeds_cents: int,
		approved_by: str,
		tenant_id: str,
		disposal_costs_cents: int = 0,
		disposal_ref: str | None = None,
		notes: str | None = None,
	) -> Any:
		"""Dispose of a fixed asset and create an immutable AssetDisposal record.

		Gain/loss = proceeds - disposal_costs - net_book_value_at_disposal.

		GL:
		  DR  disposal_proceeds  1011  (proceeds)
		  CR  fixed_asset        1500  (remove cost)
		  DR  accum_depr         1510  (remove accumulated depreciation)
		  DR/CR gain_loss        5500 (loss) / 4500 (gain)

		Marks asset status DISPOSED. Returns AssetDisposal.
		"""
		from pgappforge.plugins.erp.finance.assets.models import AssetDisposal, FixedAsset
		from pgappforge.plugins.erp.finance.assets.events import AssetDisposedEvent, emit_event

		assert proceeds_cents >= 0, "proceeds_cents must be non-negative"
		assert disposal_costs_cents >= 0, "disposal_costs_cents must be non-negative"
		valid_types = {"SALE", "SCRAP", "DONATION", "WRITE_OFF"}
		assert disposal_type in valid_types, f"disposal_type must be one of {valid_types}"

		asset = session.get(FixedAsset, asset_id)
		if asset is None:
			raise AssetNotFoundError(f"FixedAsset {asset_id!r} not found")
		if asset.status == "DISPOSED":
			raise AssetStatusError(f"Asset {asset.asset_number!r} is already disposed")

		nbv = asset.current_book_value_cents
		gain_loss = proceeds_cents - disposal_costs_cents - nbv
		ref = disposal_ref or f"DSP-{asset.asset_number}"

		disposal = AssetDisposal(
			tenant_id=tenant_id,
			asset_id=asset_id,
			disposal_date=disposal_date,
			disposal_type=disposal_type,
			proceeds_cents=proceeds_cents,
			disposal_costs_cents=disposal_costs_cents,
			gain_loss_cents=gain_loss,
			disposal_ref=ref,
			approved_by=approved_by,
			notes=notes,
		)
		session.add(disposal)

		asset.status = "DISPOSED"
		asset.disposal_date = disposal_date
		asset.disposal_proceeds_cents = proceeds_cents
		asset.disposal_gain_loss_cents = gain_loss

		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			gl = GLService()
			gl_lines = [
				{"account": "1011", "debit": proceeds_cents, "credit": 0, "description": "Disposal proceeds"},
				{"account": "1500", "debit": 0, "credit": asset.acquisition_cost_cents, "description": "Remove asset cost"},
				{"account": "1510", "debit": asset.accumulated_depreciation_cents, "credit": 0, "description": "Remove accumulated depreciation"},
			]
			if gain_loss >= 0:
				gl_lines.append({"account": "4500", "debit": 0, "credit": gain_loss, "description": "Disposal gain"})
			else:
				gl_lines.append({"account": "5500", "debit": abs(gain_loss), "credit": 0, "description": "Disposal loss"})
			if disposal_costs_cents > 0:
				gl_lines.append({"account": "5500", "debit": disposal_costs_cents, "credit": 0, "description": "Disposal costs"})
			gl.post_journal(
				{
					"tenant_id": tenant_id,
					"description": f"Disposal of {asset.asset_number} ({disposal_type})",
					"reference": ref,
					"lines": gl_lines,
				},
				session=session,
			)
		except Exception as exc:
			log.debug("GL post skipped (plugin not loaded): %s", exc)

		emit_event(
			AssetDisposedEvent(
				aggregate_id=asset_id,
				aggregate_type="FixedAsset",
				tenant_id=tenant_id,
				asset_id=asset_id,
				asset_number=asset.asset_number,
				disposal_date=str(disposal_date),
				proceeds_cents=proceeds_cents,
				gain_loss_cents=gain_loss,
			),
			session,
		)
		session.flush()
		log.info(
			"Disposed asset %r type=%r proceeds=%d gain_loss=%d",
			asset.asset_number, disposal_type, proceeds_cents, gain_loss,
		)
		return disposal

	# ------------------------------------------------------------------ #
	# Revalue asset  (IAS 16)
	# ------------------------------------------------------------------ #

	def revalue_asset(
		self,
		session: Any,
		asset_id: str,
		new_value_cents: int,
		method: str,
		revaluation_date: date,
		reference: str,
		tenant_id: str,
	) -> Any:
		"""Revalue a fixed asset to a new carrying amount (IAS 16).

		Surplus  (new > old): DR fixed_asset 1500  CR revaluation_reserve 3200
		Deficit  (new < old): DR revaluation_reserve 3200  CR fixed_asset 1500
		          (deficit > prior surplus → excess debited to P&L impairment 5500)

		Returns AssetRevaluation record.
		"""
		from pgappforge.plugins.erp.finance.assets.models import AssetRevaluation, FixedAsset

		assert new_value_cents >= 0, "new_value_cents must be non-negative"
		valid_methods = {"MARKET_VALUE", "APPRAISAL"}
		assert method in valid_methods, f"method must be one of {valid_methods}"

		asset = session.get(FixedAsset, asset_id)
		if asset is None:
			raise AssetNotFoundError(f"FixedAsset {asset_id!r} not found")
		if asset.status == "DISPOSED":
			raise AssetStatusError("Cannot revalue a disposed asset")

		previous = asset.current_book_value_cents
		surplus = new_value_cents - previous

		reval = AssetRevaluation(
			tenant_id=tenant_id,
			asset_id=asset_id,
			revaluation_date=revaluation_date,
			previous_book_value_cents=previous,
			new_book_value_cents=new_value_cents,
			revaluation_surplus_cents=surplus,
			method=method,
			reference=reference,
		)
		session.add(reval)

		asset.current_book_value_cents = new_value_cents

		try:
			from pgappforge.plugins.erp.finance.gl.services import GLService
			gl = GLService()
			if surplus >= 0:
				gl_lines = [
					{"account": "1500", "debit": surplus, "credit": 0, "description": "Revaluation uplift"},
					{"account": "3200", "debit": 0, "credit": surplus, "description": "Revaluation reserve"},
				]
			else:
				deficit = abs(surplus)
				gl_lines = [
					{"account": "3200", "debit": deficit, "credit": 0, "description": "Revaluation reserve drawdown"},
					{"account": "1500", "debit": 0, "credit": deficit, "description": "Revaluation write-down"},
				]
			gl.post_journal(
				{
					"tenant_id": tenant_id,
					"description": f"Revaluation {asset.asset_number} ref={reference}",
					"reference": reference,
					"lines": gl_lines,
				},
				session=session,
			)
		except Exception as exc:
			log.debug("GL post skipped (plugin not loaded): %s", exc)

		session.flush()
		log.info(
			"Revalued asset %r previous=%d new=%d surplus=%d method=%r",
			asset.asset_number, previous, new_value_cents, surplus, method,
		)
		return reval

	# ------------------------------------------------------------------ #
	# Depreciation batch  (GL-posting variant)
	# ------------------------------------------------------------------ #

	def run_depreciation_batch(
		self,
		session: Any,
		period_date: date,
		asset_class: str | None = None,
		tenant_id: str = "",
	) -> dict[str, Any]:
		"""Run monthly depreciation for all ACTIVE assets, posting GL entries.

		Idempotent: skips assets already processed for the period.
		GL:  DR  depreciation_expense  5200
		     CR  accumulated_depr      1510

		Args:
			period_date:  Any date within the target period; period_id derived as YYYY-MM.
			asset_class:  Optional AssetClass.code filter.
			tenant_id:    Tenant filter; empty string = all tenants.

		Returns dict {assets_processed, total_depreciation_cents}.
		"""
		from pgappforge.plugins.erp.finance.assets.models import AssetClass, AssetDepreciation, FixedAsset

		period_id = period_date.strftime("%Y-%m")

		q = sa.select(FixedAsset).where(FixedAsset.status == "ACTIVE")
		if tenant_id:
			q = q.where(FixedAsset.tenant_id == tenant_id)
		if asset_class:
			class_ids = session.execute(
				sa.select(AssetClass.id).where(AssetClass.code == asset_class)
			).scalars().all()
			if not class_ids:
				return {"assets_processed": 0, "total_depreciation_cents": 0}
			q = q.where(FixedAsset.asset_class_id.in_(class_ids))

		assets = session.execute(q).scalars().all()

		already = set(
			session.execute(
				sa.select(AssetDepreciation.asset_id)
				.where(AssetDepreciation.period_id == period_id)
			).scalars().all()
		)

		processed = 0
		total_cents = 0

		for asset in assets:
			if asset.id in already:
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

			asset.current_book_value_cents = closing_nbv
			asset.accumulated_depreciation_cents += actual_charge
			asset.last_depreciation_date = period_date
			if closing_nbv <= asset.residual_value_cents:
				asset.status = "FULLY_DEPRECIATED"

			try:
				from pgappforge.plugins.erp.finance.gl.services import GLService
				gl = GLService()
				gl.post_journal(
					{
						"tenant_id": asset.tenant_id,
						"description": f"Depreciation {asset.asset_number} period={period_id}",
						"reference": f"DEPR-{asset.asset_number}-{period_id}",
						"lines": [
							{"account": "5200", "debit": actual_charge, "credit": 0, "description": "Depreciation expense"},
							{"account": "1510", "debit": 0, "credit": actual_charge, "description": "Accumulated depreciation"},
						],
					},
					session=session,
				)
			except Exception as exc:
				log.debug("GL post skipped for asset %r: %s", asset.id, exc)

			processed += 1
			total_cents += actual_charge

		session.flush()
		log.info(
			"Depreciation batch period=%r asset_class=%r: %d assets, %d cents",
			period_id, asset_class, processed, total_cents,
		)
		return {"assets_processed": processed, "total_depreciation_cents": total_cents}

	# ------------------------------------------------------------------ #
	# Asset register (structured dict output)
	# ------------------------------------------------------------------ #

	def get_asset_register(  # type: ignore[override]
		self,
		session: Any,
		as_of_date: date,
		asset_class: str | None = None,
		tenant_id: str = "",
	) -> list[dict[str, Any]]:
		"""Return the fixed asset register as a list of dicts as of a given date.

		Each row: {asset_code, name, cost_cents, accum_depr_cents,
		           net_book_value_cents, remaining_life_months}.

		This overloads (and supersedes) the original get_asset_register() which
		returned ORM objects. Callers needing ORM objects should use
		get_asset_register_orm() instead.
		"""
		from pgappforge.plugins.erp.finance.assets.models import AssetClass, FixedAsset
		from decimal import Decimal as D

		q = (
			sa.select(FixedAsset)
			.where(FixedAsset.status.in_(["ACTIVE", "IMPAIRED", "FULLY_DEPRECIATED"]))
			.order_by(FixedAsset.asset_number)
		)
		if tenant_id:
			q = q.where(FixedAsset.tenant_id == tenant_id)
		if asset_class:
			class_ids = session.execute(
				sa.select(AssetClass.id).where(AssetClass.code == asset_class)
			).scalars().all()
			if not class_ids:
				return []
			q = q.where(FixedAsset.asset_class_id.in_(class_ids))

		assets = session.execute(q).scalars().all()
		rows: list[dict[str, Any]] = []
		for a in assets:
			# Remaining life: original life in months minus months since acquisition
			life_months_total = int(D(str(a.useful_life_years)) * D("12"))
			acq = a.acquisition_date
			months_elapsed = (
				(as_of_date.year - acq.year) * 12 + (as_of_date.month - acq.month)
			)
			remaining = max(life_months_total - months_elapsed, 0)
			rows.append({
				"asset_code": a.asset_number,
				"name": a.description,
				"cost_cents": a.acquisition_cost_cents,
				"accum_depr_cents": a.accumulated_depreciation_cents,
				"net_book_value_cents": a.current_book_value_cents,
				"remaining_life_months": remaining,
				"status": a.status,
				"asset_class_id": a.asset_class_id,
				"acquisition_date": str(a.acquisition_date),
			})
		return rows

	def get_asset_register_orm(self, tenant_id: str, session: Any, status: str | None = None) -> list[Any]:
		"""Return raw ORM FixedAsset objects — original signature preserved for compatibility."""
		from pgappforge.plugins.erp.finance.assets.models import FixedAsset
		q = (
			sa.select(FixedAsset)
			.where(FixedAsset.tenant_id == tenant_id)
			.order_by(FixedAsset.asset_number)
		)
		if status:
			q = q.where(FixedAsset.status == status.upper())
		return session.execute(q).scalars().all()

	# ------------------------------------------------------------------ #
	# Internal helpers
	# ------------------------------------------------------------------ #

	def _get_asset_age_years(self, asset: Any) -> Decimal:
		"""Return asset age in years as a Decimal.

		Prefers acquisition_date; falls back to NBV-based estimate when the
		date is absent (should not happen with valid data, but defensive).
		"""
		acq: date | None = getattr(asset, "acquisition_date", None)
		if acq is not None:
			delta_days = (date.today() - acq).days
			return Decimal(str(delta_days)) / Decimal("365")
		# Fallback: back-compute from remaining NBV fraction
		cost = Decimal(asset.acquisition_cost_cents)
		nbv = Decimal(asset.current_book_value_cents)
		life_years = Decimal(str(asset.useful_life_years))
		if cost <= 0:
			return Decimal("0")
		consumed_fraction = (cost - nbv) / cost
		return (consumed_fraction * life_years).max(Decimal("0"))

	def _calculate_depreciation(self, asset: Any) -> int:
		"""Calculate depreciation charge for one period (month).

		Returns integer cents. Uses Decimal arithmetic — never float.

		Supported methods
		-----------------
		STRAIGHT_LINE        — equal monthly charge over useful life
		DECLINING            — double-declining balance (2/N × NBV)
		SUM_OF_YEARS_DIGITS  — front-loaded; SYD factor × depreciable cost
		MACRS                — US MACRS half-year convention (IRS Rev. Proc. 87-57)
		                       supported recovery periods: 3, 5, 7, 10 years;
		                       falls back to STRAIGHT_LINE for other periods
		UNITS_OF_PRODUCTION  — returns 0; charge via record_units_depreciation()
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

		elif method == "SUM_OF_YEARS_DIGITS":
			# SYD denominator = n*(n+1)/2  where n = total useful life in years
			n = life_years.to_integral_value(rounding=ROUND_HALF_UP)
			syd_denominator = n * (n + Decimal("1")) / Decimal("2")
			if syd_denominator <= 0:
				return 0
			# Remaining life in years (integer) based on actual asset age
			age_years = self._get_asset_age_years(asset)
			remaining_life = (life_years - age_years).to_integral_value(
				rounding=ROUND_HALF_UP
			)
			remaining_life = max(Decimal("0"), remaining_life)
			syd_factor = remaining_life / syd_denominator
			annual = depreciable * syd_factor
			monthly = annual / Decimal("12")

		elif method == "MACRS":
			# MACRS half-year convention — rates indexed from year 1
			recovery_period = int(life_years.to_integral_value(rounding=ROUND_HALF_UP))
			rates = MACRS_RATES.get(recovery_period)
			if rates is None:
				# Unsupported recovery period → fall back to straight-line
				log.debug(
					"MACRS: unsupported recovery period %d for asset %r; "
					"falling back to STRAIGHT_LINE",
					recovery_period,
					asset.id,
				)
				annual = depreciable / life_years
			else:
				age_years = self._get_asset_age_years(asset)
				# year_number is 1-based calendar year of the asset's life
				year_number = int(age_years.to_integral_value(rounding=ROUND_HALF_UP)) + 1
				year_number = max(1, year_number)
				year_idx = max(0, min(len(rates) - 1, year_number - 1))
				annual = cost * rates[year_idx]
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
	# new methods exposed via service instance:
	# create_capex_project, capitalise_asset_from_project, dispose_asset,
	# revalue_asset, run_depreciation_batch, get_asset_register (dict),
	# get_asset_register_orm
]
