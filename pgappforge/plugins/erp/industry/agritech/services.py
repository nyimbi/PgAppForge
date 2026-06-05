"""
pgappforge/plugins/erp/industry/agritech/services.py

Business logic for the AgriTech plugin.

All methods are stateless beyond construction.
All monetary arithmetic uses Decimal — never float.
Session passed explicitly; never committed inside service methods.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class AgriServiceError(Exception):
	"""Base error for AgriTech service layer."""


class FarmNotFoundError(AgriServiceError):
	pass


class FieldNotFoundError(AgriServiceError):
	pass


class PlantingNotFoundError(AgriServiceError):
	pass


class InvalidStatusTransitionError(AgriServiceError):
	pass


# ---------------------------------------------------------------------------
# AgriTechService
# ---------------------------------------------------------------------------

class AgriTechService:
	"""Stateless AgriTech service.

	All monetary values returned/accepted as integer cents.
	All area/yield values returned as Decimal strings.
	"""

	# Status machine: valid transitions for PlantingActivity
	_PLANTING_TRANSITIONS: dict[str, str] = {
		"PLANNED": "PLANTED",
		"PLANTED": "GROWING",
		"GROWING": "HARVESTED",
	}

	# ------------------------------------------------------------------
	# calculate_field_profitability
	# ------------------------------------------------------------------

	def calculate_field_profitability(
		self,
		field_id: str,
		season_year: int,
		session: Any,
	) -> dict[str, Any]:
		"""Compute revenue, input costs, seed costs and margin per hectare for a field/season.

		Returns:
		  {
		    "field_id": str,
		    "season_year": int,
		    "area_ha": str,              # Decimal
		    "total_revenue_cents": int,
		    "total_input_cost_cents": int,
		    "total_seed_cost_cents": int,
		    "total_cost_cents": int,
		    "gross_margin_cents": int,
		    "margin_per_ha_cents": int,   # integer cents/ha
		    "activities": int,            # count of planting activities
		    "harvested_kg": str,          # Decimal
		  }
		"""
		from pgappforge.plugins.erp.industry.agritech.models import (
			Field, PlantingActivity, HarvestRecord, InputApplication,
		)

		field = session.get(Field, field_id)
		if field is None:
			raise FieldNotFoundError(f"Field {field_id!r} not found")

		area_ha = Decimal(str(field.area_ha or "0"))

		# PlantingActivities in season_year
		activities = session.execute(
			sa.select(PlantingActivity).where(
				PlantingActivity.field_id == field_id,
				sa.extract("year", PlantingActivity.planting_date) == season_year,
			)
		).scalars().all()

		activity_ids = [a.id for a in activities]

		# Revenue from harvest records
		total_revenue_cents = 0
		harvested_kg = Decimal("0")
		if activity_ids:
			hrs = session.execute(
				sa.select(HarvestRecord).where(HarvestRecord.activity_id.in_(activity_ids))
			).scalars().all()
			for hr in hrs:
				total_revenue_cents += hr.total_revenue_cents or 0
				harvested_kg += Decimal(str(hr.quantity_kg or "0"))

		# Input costs
		total_input_cost_cents = 0
		if activity_ids:
			input_apps = session.execute(
				sa.select(InputApplication).where(
					InputApplication.field_id == field_id,
					InputApplication.activity_id.in_(activity_ids),
				)
			).scalars().all()
			total_input_cost_cents = sum(ia.cost_cents or 0 for ia in input_apps)

		# Seed costs from planting activities
		total_seed_cost_cents = sum(a.seed_cost_cents or 0 for a in activities)

		total_cost_cents = total_input_cost_cents + total_seed_cost_cents
		gross_margin_cents = total_revenue_cents - total_cost_cents
		margin_per_ha_cents = (
			int(Decimal(gross_margin_cents) / area_ha)
			if area_ha > Decimal("0") else 0
		)

		return {
			"field_id": field_id,
			"season_year": season_year,
			"area_ha": str(area_ha),
			"total_revenue_cents": total_revenue_cents,
			"total_input_cost_cents": total_input_cost_cents,
			"total_seed_cost_cents": total_seed_cost_cents,
			"total_cost_cents": total_cost_cents,
			"gross_margin_cents": gross_margin_cents,
			"margin_per_ha_cents": margin_per_ha_cents,
			"activities": len(activities),
			"harvested_kg": str(harvested_kg),
		}

	# ------------------------------------------------------------------
	# recommend_inputs
	# ------------------------------------------------------------------

	def recommend_inputs(
		self,
		field_id: str,
		crop_id: str,
		growth_stage: str,
		session: Any,
	) -> list[dict[str, Any]]:
		"""Rule-based input recommendations by growth stage and crop.

		Stages: GERMINATION | VEGETATIVE | FLOWERING | GRAIN_FILL | MATURITY
		Returns list of {input_type, product_hint, quantity_per_ha, unit, priority, reason}

		This is a heuristic engine — real deployments should replace with
		agronomic ML model or advisory API integration.
		"""
		from pgappforge.plugins.erp.industry.agritech.models import Field, Crop

		field = session.get(Field, field_id)
		if field is None:
			raise FieldNotFoundError(f"Field {field_id!r} not found")

		crop = session.get(Crop, crop_id)
		if crop is None:
			raise AgriServiceError(f"Crop {crop_id!r} not found")

		recs: list[dict[str, Any]] = []
		stage = (growth_stage or "").upper()

		# Universal: soil amendment recommendation based on soil type
		soil = (field.soil_type or "").lower()
		if "sandy" in soil:
			recs.append({
				"input_type": "LIME",
				"product_hint": "Agricultural lime",
				"quantity_per_ha": "500",
				"unit": "kg",
				"priority": "MEDIUM",
				"reason": "Sandy soils typically acidic — pH correction improves nutrient uptake",
			})

		# Stage-specific nitrogen recommendations for cereals/legumes
		if crop.category in ("CEREAL", "CASH_CROP"):
			if stage == "VEGETATIVE":
				recs.append({
					"input_type": "FERTILIZER",
					"product_hint": "CAN (Calcium Ammonium Nitrate) 27%N",
					"quantity_per_ha": "150",
					"unit": "kg",
					"priority": "HIGH",
					"reason": f"{crop.crop_name} vegetative stage: high N demand for leaf area development",
				})
			elif stage == "FLOWERING":
				recs.append({
					"input_type": "FERTILIZER",
					"product_hint": "DAP (Di-Ammonium Phosphate)",
					"quantity_per_ha": "100",
					"unit": "kg",
					"priority": "HIGH",
					"reason": f"{crop.crop_name} flowering: P and K support reproductive development",
				})

		# Irrigation recommendation for rain-fed fields
		if field.irrigation_type == "RAIN_FED" and stage in ("FLOWERING", "GRAIN_FILL"):
			recs.append({
				"input_type": "IRRIGATION",
				"product_hint": "Supplemental irrigation",
				"quantity_per_ha": str(crop.water_requirement_mm or 30),
				"unit": "mm",
				"priority": "HIGH",
				"reason": "Rain-fed field at critical water demand stage — monitor soil moisture daily",
			})

		# Pest prevention at VEGETATIVE
		if stage == "VEGETATIVE":
			recs.append({
				"input_type": "PESTICIDE",
				"product_hint": "Broad-spectrum insecticide (consult label for crop)",
				"quantity_per_ha": "1.0",
				"unit": "L",
				"priority": "LOW",
				"reason": "Preventive treatment during high-risk vegetative period",
			})

		return recs

	# ------------------------------------------------------------------
	# detect_pest_risk
	# ------------------------------------------------------------------

	def detect_pest_risk(
		self,
		field_id: str,
		weather_data: dict[str, Any],
		session: Any,
	) -> dict[str, Any]:
		"""Heuristic pest/disease risk scoring from weather + recent observations.

		weather_data keys: temperature_c, humidity_pct, rainfall_mm (last 7 days)

		Returns:
		  {
		    "field_id": str,
		    "overall_risk": LOW|MEDIUM|HIGH|CRITICAL,
		    "risks": [{"pest": str, "risk_level": str, "trigger": str}]
		  }
		"""
		from pgappforge.plugins.erp.industry.agritech.models import FieldObservation

		risks: list[dict[str, str]] = []

		temp = float(weather_data.get("temperature_c", 20) or 20)
		humidity = float(weather_data.get("humidity_pct", 60) or 60)
		rainfall = float(weather_data.get("rainfall_mm", 0) or 0)

		# Fungal disease: high humidity + warm temps
		if humidity > 80 and temp > 18:
			risks.append({
				"pest": "Fungal blight (late blight / grey mould)",
				"risk_level": "HIGH",
				"trigger": f"humidity={humidity:.0f}% > 80% and temp={temp:.1f}°C > 18°C",
			})

		# Armyworm: warm nights + recent rainfall
		if temp > 22 and rainfall > 20:
			risks.append({
				"pest": "Fall armyworm (Spodoptera frugiperda)",
				"risk_level": "HIGH",
				"trigger": f"temp={temp:.1f}°C > 22°C and rainfall_7d={rainfall:.1f}mm > 20mm",
			})

		# Aphids: hot and dry
		if temp > 28 and humidity < 40:
			risks.append({
				"pest": "Aphids",
				"risk_level": "MEDIUM",
				"trigger": f"temp={temp:.1f}°C > 28°C and humidity={humidity:.0f}% < 40%",
			})

		# Check recent CRITICAL/HIGH observations for this field
		recent_critical = session.execute(
			sa.select(FieldObservation).where(
				FieldObservation.field_id == field_id,
				FieldObservation.observation_type.in_(["PEST", "DISEASE"]),
				FieldObservation.severity.in_(["HIGH", "CRITICAL"]),
				FieldObservation.observed_at >= sa.func.now() - sa.text("INTERVAL '14 days'"),
			).limit(5)
		).scalars().all()

		for obs in recent_critical:
			risks.append({
				"pest": f"Confirmed {obs.observation_type.lower()} (recent field report)",
				"risk_level": obs.severity,
				"trigger": f"Observation {obs.id!r} at {obs.observed_at.date().isoformat()}",
			})

		if not risks:
			overall = "LOW"
		elif any(r["risk_level"] == "CRITICAL" for r in risks):
			overall = "CRITICAL"
		elif sum(1 for r in risks if r["risk_level"] == "HIGH") >= 2:
			overall = "HIGH"
		elif any(r["risk_level"] == "HIGH" for r in risks):
			overall = "MEDIUM"
		else:
			overall = "LOW"

		return {"field_id": field_id, "overall_risk": overall, "risks": risks}

	# ------------------------------------------------------------------
	# plan_irrigation
	# ------------------------------------------------------------------

	def plan_irrigation(
		self,
		field_id: str,
		session: Any,
		forecast_days: int = 7,
	) -> list[dict[str, Any]]:
		"""Generate irrigation schedule for the next forecast_days.

		Uses crop water requirement, irrigation type, and recent rainfall
		to compute deficit and schedule irrigation events.

		Returns list of {date, recommended_mm, reason, priority}
		"""
		from pgappforge.plugins.erp.industry.agritech.models import (
			Field, PlantingActivity, Crop, WeatherRecord,
		)

		field = session.get(Field, field_id)
		if field is None:
			raise FieldNotFoundError(f"Field {field_id!r} not found")

		# Get active crop
		active_activity = session.execute(
			sa.select(PlantingActivity).where(
				PlantingActivity.field_id == field_id,
				PlantingActivity.status.in_(["PLANTED", "GROWING"]),
			).order_by(sa.desc(PlantingActivity.planting_date)).limit(1)
		).scalar_one_or_none()

		crop_water_req_mm_per_day = Decimal("5")  # default
		if active_activity and active_activity.crop:
			crop = active_activity.crop
			if crop.water_requirement_mm and crop.growing_season_days:
				crop_water_req_mm_per_day = (
					Decimal(str(crop.water_requirement_mm)) / Decimal(str(crop.growing_season_days))
				).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

		# Recent 7-day rainfall from weather records near this field
		recent_rainfall = session.execute(
			sa.select(sa.func.sum(WeatherRecord.rainfall_mm)).where(
				WeatherRecord.tenant_id == field.tenant_id,
				WeatherRecord.recorded_at >= sa.func.now() - sa.text("INTERVAL '7 days'"),
			)
		).scalar() or Decimal("0")
		recent_rainfall = Decimal(str(recent_rainfall))

		schedule: list[dict[str, Any]] = []
		today = date.today()

		for day_offset in range(forecast_days):
			from datetime import timedelta
			target_date = today + timedelta(days=day_offset + 1)
			daily_deficit = crop_water_req_mm_per_day - (recent_rainfall / Decimal("7"))

			if daily_deficit <= Decimal("0"):
				continue  # Sufficient moisture — no irrigation needed

			# Drip/sprinkler: irrigate daily; flood: every 3-5 days
			if field.irrigation_type in ("DRIP", "SPRINKLER"):
				recommended_mm = daily_deficit
				priority = "HIGH" if daily_deficit > Decimal("4") else "MEDIUM"
				schedule.append({
					"date": target_date.isoformat(),
					"recommended_mm": str(recommended_mm.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
					"reason": f"Daily deficit {daily_deficit:.2f}mm (crop requirement minus rainfall)",
					"priority": priority,
					"irrigation_method": field.irrigation_type,
				})
			elif field.irrigation_type == "FLOOD" and (day_offset + 1) % 4 == 0:
				# Flood irrigation every ~4 days
				batch_mm = (daily_deficit * Decimal("4")).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
				schedule.append({
					"date": target_date.isoformat(),
					"recommended_mm": str(batch_mm),
					"reason": f"4-day flood cycle — accumulated deficit {batch_mm}mm",
					"priority": "HIGH",
					"irrigation_method": "FLOOD",
				})
			# RAIN_FED: informational only
			elif field.irrigation_type == "RAIN_FED" and daily_deficit > Decimal("3"):
				schedule.append({
					"date": target_date.isoformat(),
					"recommended_mm": str(daily_deficit.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)),
					"reason": "Rain-fed field: moisture stress risk — consider supplemental irrigation",
					"priority": "LOW",
					"irrigation_method": "RAIN_FED",
				})

		return schedule

	# ------------------------------------------------------------------
	# get_farm_dashboard
	# ------------------------------------------------------------------

	def get_farm_dashboard(self, farm_id: str, session: Any) -> dict[str, Any]:
		"""Aggregate dashboard data for a farm.

		Returns:
		  {
		    "farm": {id, name, type, total_area_ha},
		    "total_fields": int,
		    "active_crops": [{field_id, field_name, crop_name, status, planted_date}],
		    "total_planted_area_ha": str,
		    "pending_observations": int,   # CRITICAL/HIGH unresolved observations
		    "recent_weather": {station_id, temp_c, humidity, rainfall_7d_mm},
		    "alerts": [str],
		  }
		"""
		from pgappforge.plugins.erp.industry.agritech.models import (
			Farm, Field, PlantingActivity, Crop, FieldObservation, WeatherRecord,
		)

		farm = session.get(Farm, farm_id)
		if farm is None:
			raise FarmNotFoundError(f"Farm {farm_id!r} not found")

		fields = session.execute(
			sa.select(Field).where(Field.farm_id == farm_id)
		).scalars().all()

		field_ids = [f.id for f in fields]
		total_planted_ha = Decimal("0")
		active_crops: list[dict[str, Any]] = []

		for field in fields:
			active_pa = session.execute(
				sa.select(PlantingActivity).where(
					PlantingActivity.field_id == field.id,
					PlantingActivity.status.in_(["PLANTED", "GROWING"]),
				).limit(1)
			).scalar_one_or_none()
			if active_pa:
				crop_name = active_pa.crop.crop_name if active_pa.crop else "Unknown"
				active_crops.append({
					"field_id": field.id,
					"field_name": field.field_name,
					"crop_name": crop_name,
					"status": active_pa.status,
					"planted_date": active_pa.planting_date.isoformat() if active_pa.planting_date else None,
					"expected_harvest": active_pa.expected_harvest_date.isoformat() if active_pa.expected_harvest_date else None,
				})
				total_planted_ha += Decimal(str(field.area_ha or "0"))

		# Critical/high observations in last 30 days
		pending_obs_count = 0
		if field_ids:
			pending_obs_count = session.execute(
				sa.select(sa.func.count()).where(
					FieldObservation.field_id.in_(field_ids),
					FieldObservation.severity.in_(["HIGH", "CRITICAL"]),
					FieldObservation.observed_at >= sa.func.now() - sa.text("INTERVAL '30 days'"),
				)
			).scalar() or 0

		# Most recent weather reading for this tenant
		recent_weather: dict[str, Any] = {}
		latest_wr = session.execute(
			sa.select(WeatherRecord).where(
				WeatherRecord.tenant_id == farm.tenant_id,
			).order_by(sa.desc(WeatherRecord.recorded_at)).limit(1)
		).scalar_one_or_none()
		if latest_wr:
			recent_weather = {
				"station_id": latest_wr.station_id,
				"recorded_at": latest_wr.recorded_at.isoformat(),
				"temperature_c": str(latest_wr.temperature_c or ""),
				"humidity_pct": str(latest_wr.humidity_pct or ""),
				"rainfall_mm": str(latest_wr.rainfall_mm or ""),
			}

		# Build alerts
		alerts: list[str] = []
		if pending_obs_count > 0:
			alerts.append(f"{pending_obs_count} HIGH/CRITICAL field observations in last 30 days require attention")

		today = date.today()
		for crop_info in active_crops:
			if crop_info.get("expected_harvest"):
				exp = date.fromisoformat(crop_info["expected_harvest"])
				days_to_harvest = (exp - today).days
				if 0 <= days_to_harvest <= 14:
					alerts.append(f"{crop_info['field_name']}: {crop_info['crop_name']} harvest due in {days_to_harvest} days")
				elif days_to_harvest < 0:
					alerts.append(f"{crop_info['field_name']}: {crop_info['crop_name']} harvest overdue by {abs(days_to_harvest)} days")

		return {
			"farm": {
				"id": farm.id,
				"name": farm.farm_name,
				"type": farm.farm_type,
				"total_area_ha": str(farm.total_area_ha or "0"),
				"soil_type": farm.soil_type,
				"elevation_m": farm.elevation_m,
			},
			"total_fields": len(fields),
			"active_crops": active_crops,
			"total_planted_area_ha": str(total_planted_ha),
			"pending_observations": pending_obs_count,
			"recent_weather": recent_weather,
			"alerts": alerts,
		}

	# ------------------------------------------------------------------
	# calculate_carbon_sequestration
	# ------------------------------------------------------------------

	def calculate_carbon_sequestration(
		self,
		farm_id: str,
		year: int,
		session: Any,
	) -> dict[str, Any]:
		"""Estimate CO2e sequestered by farming practices in a year.

		Uses simplified IPCC Tier 1 coefficients:
		  - No-till / conservation tillage: +0.3 tCO2e/ha/yr vs conventional
		  - Cover crops / legumes: +0.2 tCO2e/ha/yr
		  - Reduced synthetic N fertilizer: +0.1 tCO2e/ha/yr for each 20% reduction

		Returns:
		  {
		    "farm_id": str,
		    "year": int,
		    "harvested_area_ha": str,
		    "base_sequestration_tco2e": str,
		    "practice_bonuses": [{practice, area_ha, tco2e_per_ha, subtotal_tco2e}],
		    "total_tco2e": str,
		  }
		"""
		from pgappforge.plugins.erp.industry.agritech.models import (
			Farm, Field, PlantingActivity, Crop, InputApplication,
		)

		farm = session.get(Farm, farm_id)
		if farm is None:
			raise FarmNotFoundError(f"Farm {farm_id!r} not found")

		fields = session.execute(
			sa.select(Field).where(Field.farm_id == farm_id)
		).scalars().all()

		field_ids = [f.id for f in fields]
		if not field_ids:
			return {
				"farm_id": farm_id, "year": year,
				"harvested_area_ha": "0", "base_sequestration_tco2e": "0",
				"practice_bonuses": [], "total_tco2e": "0",
			}

		# Total harvested area this year
		harvested_activities = session.execute(
			sa.select(PlantingActivity).where(
				PlantingActivity.field_id.in_(field_ids),
				PlantingActivity.status == "HARVESTED",
				sa.extract("year", PlantingActivity.planting_date) == year,
			)
		).scalars().all()

		harvested_field_ids = {a.field_id for a in harvested_activities}
		harvested_area_ha = sum(
			Decimal(str(f.area_ha or "0"))
			for f in fields if f.id in harvested_field_ids
		)

		# Base sequestration: 0.5 tCO2e/ha/yr for managed cropland (IPCC Tier 1)
		base_rate = Decimal("0.5")
		base_tco2e = (harvested_area_ha * base_rate).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

		practice_bonuses: list[dict[str, Any]] = []
		total_bonus = Decimal("0")

		# Legume crops — nitrogen fixation reduces synthetic N, sequesters C
		legume_activities = [a for a in harvested_activities if a.crop and a.crop.category == "LEGUME"]
		if legume_activities:
			legume_area = sum(
				Decimal(str(f.area_ha or "0"))
				for f in fields if f.id in {a.field_id for a in legume_activities}
			)
			legume_bonus_rate = Decimal("0.2")
			legume_bonus = (legume_area * legume_bonus_rate).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
			total_bonus += legume_bonus
			practice_bonuses.append({
				"practice": "Legume cover crop / nitrogen fixation",
				"area_ha": str(legume_area),
				"tco2e_per_ha": str(legume_bonus_rate),
				"subtotal_tco2e": str(legume_bonus),
			})

		# Drip irrigation — water-efficient = lower N2O emissions proxy
		drip_fields = [f for f in fields if f.id in harvested_field_ids and f.irrigation_type == "DRIP"]
		if drip_fields:
			drip_area = sum(Decimal(str(f.area_ha or "0")) for f in drip_fields)
			drip_bonus_rate = Decimal("0.15")
			drip_bonus = (drip_area * drip_bonus_rate).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
			total_bonus += drip_bonus
			practice_bonuses.append({
				"practice": "Drip/precision irrigation (reduced N2O)",
				"area_ha": str(drip_area),
				"tco2e_per_ha": str(drip_bonus_rate),
				"subtotal_tco2e": str(drip_bonus),
			})

		total_tco2e = (base_tco2e + total_bonus).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)

		return {
			"farm_id": farm_id,
			"year": year,
			"harvested_area_ha": str(harvested_area_ha),
			"base_sequestration_tco2e": str(base_tco2e),
			"practice_bonuses": practice_bonuses,
			"total_tco2e": str(total_tco2e),
		}

	# ------------------------------------------------------------------
	# generate_field_report
	# ------------------------------------------------------------------

	def generate_field_report(
		self,
		field_id: str,
		season_year: int,
		session: Any,
	) -> dict[str, Any]:
		"""Generate a comprehensive field season report.

		Returns yield vs expected, all input applications, costs, observations summary.
		"""
		from pgappforge.plugins.erp.industry.agritech.models import (
			Field, PlantingActivity, HarvestRecord, InputApplication, FieldObservation,
		)

		field = session.get(Field, field_id)
		if field is None:
			raise FieldNotFoundError(f"Field {field_id!r} not found")

		activities = session.execute(
			sa.select(PlantingActivity).where(
				PlantingActivity.field_id == field_id,
				sa.extract("year", PlantingActivity.planting_date) == season_year,
			)
		).scalars().all()

		activity_ids = [a.id for a in activities]

		# Harvest data
		harvest_summary: list[dict[str, Any]] = []
		total_yield_kg = Decimal("0")
		total_expected_kg = Decimal("0")

		for act in activities:
			crop = act.crop
			exp_yield = Decimal("0")
			if crop and crop.typical_yield_kg_per_ha and field.area_ha:
				exp_yield = (
					Decimal(str(crop.typical_yield_kg_per_ha)) * Decimal(str(field.area_ha))
				).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
				total_expected_kg += exp_yield

			hrs = session.execute(
				sa.select(HarvestRecord).where(HarvestRecord.activity_id == act.id)
			).scalars().all()
			actual_yield = sum(Decimal(str(hr.quantity_kg or "0")) for hr in hrs)
			total_yield_kg += actual_yield

			harvest_summary.append({
				"activity_id": act.id,
				"crop": crop.crop_name if crop else "Unknown",
				"variety": act.variety,
				"planted": act.planting_date.isoformat() if act.planting_date else None,
				"expected_kg": str(exp_yield),
				"actual_kg": str(actual_yield),
				"yield_pct": str(
					(actual_yield / exp_yield * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
					if exp_yield > Decimal("0") else Decimal("0")
				),
				"status": act.status,
			})

		# Input applications
		inputs: list[dict[str, Any]] = []
		total_input_cost_cents = 0
		if activity_ids:
			apps = session.execute(
				sa.select(InputApplication).where(
					InputApplication.field_id == field_id,
					sa.extract("year", InputApplication.application_date) == season_year,
				)
			).scalars().all()
			for app in apps:
				inputs.append({
					"date": app.application_date.isoformat() if app.application_date else None,
					"input_type": app.input_type,
					"product": app.product_name,
					"quantity": str(app.quantity),
					"unit": app.unit,
					"cost_cents": app.cost_cents,
				})
				total_input_cost_cents += app.cost_cents or 0

		# Observations summary
		obs_counts: dict[str, int] = {}
		if activity_ids:
			obs_rows = session.execute(
				sa.select(
					FieldObservation.observation_type,
					FieldObservation.severity,
					sa.func.count().label("cnt"),
				).where(
					FieldObservation.field_id == field_id,
					FieldObservation.observed_at >= sa.func.now() - sa.text(f"INTERVAL '{season_year}-01-01'"),
				).group_by(FieldObservation.observation_type, FieldObservation.severity)
			).all()
			for row in obs_rows:
				key = f"{row.observation_type}/{row.severity or 'N/A'}"
				obs_counts[key] = row.cnt

		profitability = self.calculate_field_profitability(field_id, season_year, session)

		return {
			"field": {
				"id": field.id,
				"name": field.field_name,
				"area_ha": str(field.area_ha or "0"),
				"soil_type": field.soil_type,
				"irrigation_type": field.irrigation_type,
			},
			"season_year": season_year,
			"harvest_summary": harvest_summary,
			"total_yield_kg": str(total_yield_kg),
			"total_expected_kg": str(total_expected_kg),
			"yield_pct_of_expected": str(
				(total_yield_kg / total_expected_kg * Decimal("100")).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
				if total_expected_kg > Decimal("0") else Decimal("0")
			),
			"input_applications": inputs,
			"total_input_cost_cents": total_input_cost_cents,
			"observations_summary": obs_counts,
			"profitability": profitability,
		}

	# ------------------------------------------------------------------
	# advance_planting_status
	# ------------------------------------------------------------------

	def advance_planting_status(
		self,
		activity_id: str,
		session: Any,
	) -> Any:
		"""Advance a PlantingActivity to the next status in the state machine.

		PLANNED → PLANTED → GROWING → HARVESTED
		Emits PlantingStatusChangedEvent.
		"""
		from pgappforge.plugins.erp.industry.agritech.models import PlantingActivity
		from pgappforge.plugins.erp.industry.agritech.events import PlantingStatusChangedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event

		act = session.get(PlantingActivity, activity_id)
		if act is None:
			raise PlantingNotFoundError(f"PlantingActivity {activity_id!r} not found")

		next_status = self._PLANTING_TRANSITIONS.get(act.status)
		if next_status is None:
			raise InvalidStatusTransitionError(
				f"No transition from status {act.status!r} — terminal state"
			)

		old_status = act.status
		act.status = next_status
		if next_status == "HARVESTED" and act.actual_harvest_date is None:
			act.actual_harvest_date = date.today()
		act.updated_at = datetime.now(timezone.utc)

		emit_event(
			PlantingStatusChangedEvent(
				aggregate_id=act.id,
				aggregate_type="PlantingActivity",
				tenant_id=act.tenant_id,
				activity_id=act.id,
				field_id=act.field_id,
				crop_id=act.crop_id,
				old_status=old_status,
				new_status=next_status,
			),
			session,
		)
		return act


__all__ = [
	"AgriTechService",
	"AgriServiceError",
	"FarmNotFoundError",
	"FieldNotFoundError",
	"PlantingNotFoundError",
	"InvalidStatusTransitionError",
]
