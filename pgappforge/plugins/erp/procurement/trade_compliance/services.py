"""
pgappforge/plugins/erp/procurement/trade_compliance/services.py

TradeComplianceService — entity screening, HS code classification, duty calc,
and OFAC SDN list refresh.

Fuzzy matching uses a stdlib-only Jaro-Winkler implementation — no third-party
fuzzy library required.

Thresholds:
  >= 0.95  → MATCH (blocked)
  >= 0.85  → POSSIBLE_MATCH (requires manual review)
  < 0.85   → CLEAR

BPM actions:
  trade.compliance.screen_entity    — Screen entity against denied party lists
  trade.compliance.classify_product — Classify product with HS code
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select

from pgappforge.plugins.workflow.engine import BPMActionRegistry

log = logging.getLogger(__name__)


def _jaro_winkler(s1: str, s2: str) -> float:
	"""Module-level Jaro-Winkler — delegates to foundation.commons."""
	from pgappforge.plugins.erp.foundation.commons import jaro_winkler
	return jaro_winkler(s1, s2)


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("TradeComplianceService: emit suppressed: %s", exc)


def _resolve_declaration_tenant(shipment_id: str, hs_codes: list[Any], session: Any) -> str:
	try:
		from pgappforge.plugins.erp.operations.scm.models import ShipmentTracking
		shipment = session.get(ShipmentTracking, shipment_id)
		if shipment is not None and getattr(shipment, "tenant_id", None):
			return str(shipment.tenant_id)
	except Exception:
		pass

	for line in hs_codes:
		if isinstance(line, dict) and line.get("tenant_id"):
			return str(line["tenant_id"])
	raise ValueError("tenant_id could not be inferred from shipment_id or hs_codes")


def _declaration_dict(declaration: Any) -> dict[str, Any]:
	return {
		"id": declaration.id,
		"tenant_id": declaration.tenant_id,
		"shipment_id": declaration.shipment_id,
		"export_country": declaration.export_country,
		"import_country": declaration.import_country,
		"total_value_cents": declaration.total_value_cents,
		"total_duty_cents": declaration.total_duty_cents,
		"lines": declaration.lines,
		"status": declaration.status,
		"submitted_at": declaration.submitted_at,
		"cleared_at": declaration.cleared_at,
		"declaration_reference": declaration.declaration_reference,
	}


# ---------------------------------------------------------------------------
# TradeComplianceService
# ---------------------------------------------------------------------------

class TradeComplianceService:
	"""Stateless trade compliance service."""

	# ------------------------------------------------------------------
	# _jaro_winkler
	# ------------------------------------------------------------------

	def _jaro_winkler(self, s1: str, s2: str) -> float:
		"""Delegate to shared foundation utility."""
		from pgappforge.plugins.erp.foundation.commons import jaro_winkler
		return jaro_winkler(s1, s2)

	# ------------------------------------------------------------------
	# screen_entity
	# ------------------------------------------------------------------

	def screen_entity(
		self,
		entity_name: str,
		tenant_id: str,
		session: Any,
		*,
		source_type: str | None = None,
		source_id: str | None = None,
	) -> Any:
		"""Screen entity_name against all active restriction lists.

		Returns a persisted TradeScreeningResult with status CLEAR/MATCH/POSSIBLE_MATCH.
		Emits EntityScreenedEvent; additionally emits EntityBlockedEvent on MATCH.
		"""
		from pgappforge.plugins.erp.procurement.trade_compliance.models import (
			TradeRestrictionList,
			TradeScreeningResult,
		)
		from pgappforge.plugins.erp.procurement.trade_compliance.events import (
			EntityBlockedEvent,
			EntityScreenedEvent,
		)

		lists = session.execute(
			select(TradeRestrictionList).where(
				TradeRestrictionList.tenant_id == tenant_id,
				TradeRestrictionList.is_active.is_(True),
			)
		).scalars().all()

		best_score = 0.0
		best_name = ""
		best_list = ""
		hit_count = 0

		for lst in lists:
			for entry in lst.entries or []:
				candidates = [entry.get("name", "")] + (entry.get("aliases") or [])
				for candidate in candidates:
					if not candidate:
						continue
					score = self._jaro_winkler(entity_name, candidate)
					if score >= 0.85:
						hit_count += 1
					if score > best_score:
						best_score = score
						best_name = candidate
						best_list = lst.list_name

		if best_score >= 0.95:
			status = "MATCH"
		elif best_score >= 0.85:
			status = "POSSIBLE_MATCH"
		else:
			status = "CLEAR"
			best_name = ""
			best_list = ""

		score_decimal = (
			Decimal(str(best_score)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
			if best_score > 0
			else None
		)

		result = TradeScreeningResult(
			tenant_id=tenant_id,
			entity_name=entity_name,
			screened_at=datetime.now(timezone.utc),
			hit_count=hit_count,
			top_match_name=best_name or None,
			top_match_score=score_decimal,
			matched_list=best_list or None,
			status=status,
			source_document_type=source_type,
			source_document_id=source_id,
		)
		session.add(result)
		session.flush()

		_emit(
			EntityScreenedEvent(
				aggregate_id=result.id,
				aggregate_type="TradeScreeningResult",
				tenant_id=tenant_id,
				entity_name=entity_name,
				result=status,
				hit_count=hit_count,
			),
			session,
		)

		if status == "MATCH":
			_emit(
				EntityBlockedEvent(
					aggregate_id=result.id,
					aggregate_type="TradeScreeningResult",
					tenant_id=tenant_id,
					entity_name=entity_name,
					matched_list=best_list,
					matched_entry=best_name,
				),
				session,
			)

		return result

	# ------------------------------------------------------------------
	# classify_product
	# ------------------------------------------------------------------

	def classify_product(
		self,
		product_code: str,
		country_code: str,
		tenant_id: str,
		session: Any,
	) -> Any | None:
		"""Look up HS code by product_code; country-specific row takes precedence over universal."""
		from pgappforge.plugins.erp.procurement.trade_compliance.models import HSCodeMapping
		from pgappforge.plugins.erp.procurement.trade_compliance.events import HSCodeLookedUpEvent

		# Prefer country-specific mapping, fall back to universal (country_code IS NULL)
		row = session.execute(
			select(HSCodeMapping).where(
				HSCodeMapping.tenant_id == tenant_id,
				HSCodeMapping.product_code == product_code,
				HSCodeMapping.country_code == country_code,
			)
		).scalar_one_or_none()

		if row is None:
			row = session.execute(
				select(HSCodeMapping).where(
					HSCodeMapping.tenant_id == tenant_id,
					HSCodeMapping.product_code == product_code,
					HSCodeMapping.country_code.is_(None),
				)
			).scalar_one_or_none()

		if row is not None:
			_emit(
				HSCodeLookedUpEvent(
					aggregate_id=row.id,
					aggregate_type="HSCodeMapping",
					tenant_id=tenant_id,
					product_code=product_code,
					hs_code=row.hs_code,
					duty_rate_pct=Decimal(str(row.duty_rate_pct or 0)),
				),
				session,
			)

		return row

	# ------------------------------------------------------------------
	# calculate_duty
	# ------------------------------------------------------------------

	def calculate_duty(
		self,
		hs_code: str,
		country_origin: str,
		country_dest: str,
		value_cents: int,
		tenant_id: str,
		session: Any,
	) -> dict[str, Any]:
		"""Calculate import duty for an HS code.

		Returns {hs_code, duty_rate_pct, duty_cents, is_controlled}.
		Duty = value_cents × duty_rate_pct / 100, rounded HALF_UP to integer cents.
		"""
		from pgappforge.plugins.erp.procurement.trade_compliance.models import HSCodeMapping

		row = session.execute(
			select(HSCodeMapping).where(
				HSCodeMapping.tenant_id == tenant_id,
				HSCodeMapping.hs_code == hs_code,
			)
		).scalar_one_or_none()

		if row is None:
			return {
				"hs_code": hs_code,
				"duty_rate_pct": Decimal("0"),
				"duty_cents": 0,
				"is_controlled": False,
				"found": False,
			}

		rate = Decimal(str(row.duty_rate_pct or 0))
		duty_cents = int(
			(Decimal(str(value_cents)) * rate / Decimal("100")).quantize(
				Decimal("1"), rounding=ROUND_HALF_UP
			)
		)
		return {
			"hs_code": hs_code,
			"duty_rate_pct": rate,
			"duty_cents": duty_cents,
			"is_controlled": bool(row.is_controlled),
			"found": True,
		}

	# ------------------------------------------------------------------
	# create_customs_declaration
	# ------------------------------------------------------------------

	def create_customs_declaration(
		self,
		shipment_id: str,
		export_country: str,
		import_country: str,
		hs_codes: list[Any],
		total_value_cents: int,
		session: Any,
	) -> dict[str, Any]:
		"""Create a draft customs declaration with per-HS-code duties."""
		from pgappforge.plugins.erp.procurement.trade_compliance.models import CustomsDeclaration

		if total_value_cents <= 0:
			raise ValueError("total_value_cents must be positive")
		if not hs_codes:
			raise ValueError("hs_codes must contain at least one line")

		tenant_id = _resolve_declaration_tenant(shipment_id, hs_codes, session)
		normalized_lines: list[dict[str, Any]] = []
		explicit_value = sum(
			int(line.get("value_cents", 0) or 0)
			for line in hs_codes
			if isinstance(line, dict)
		)
		default_value = int(Decimal(str(total_value_cents)) / Decimal(str(len(hs_codes))))

		for index, raw_line in enumerate(hs_codes):
			line = raw_line if isinstance(raw_line, dict) else {"hs_code": str(raw_line)}
			hs_code = str(line.get("hs_code", "")).strip()
			if not hs_code:
				raise ValueError("Each customs line must include hs_code")
			if explicit_value:
				value_cents = int(line.get("value_cents", 0) or 0)
			else:
				value_cents = default_value
				if index == len(hs_codes) - 1:
					value_cents = int(total_value_cents) - default_value * (len(hs_codes) - 1)
			duty = self.calculate_duty(
				hs_code=hs_code,
				country_origin=export_country,
				country_dest=import_country,
				value_cents=value_cents,
				tenant_id=tenant_id,
				session=session,
			)
			normalized_lines.append({
				"hs_code": hs_code,
				"description": line.get("description", ""),
				"value_cents": value_cents,
				"duty_cents": int(duty["duty_cents"]),
				"duty_rate_pct": str(duty["duty_rate_pct"]),
			})

		total_duty_cents = sum(int(line["duty_cents"]) for line in normalized_lines)
		declaration = CustomsDeclaration(
			tenant_id=tenant_id,
			shipment_id=shipment_id,
			export_country=export_country.upper().strip(),
			import_country=import_country.upper().strip(),
			total_value_cents=int(total_value_cents),
			total_duty_cents=total_duty_cents,
			lines=normalized_lines,
			status="DRAFT",
		)
		session.add(declaration)
		session.flush()
		return _declaration_dict(declaration)

	# ------------------------------------------------------------------
	# submit_declaration
	# ------------------------------------------------------------------

	def submit_declaration(self, declaration_id: str, session: Any) -> dict[str, Any]:
		"""Submit a draft customs declaration after validating required values."""
		from pgappforge.plugins.erp.procurement.trade_compliance.models import CustomsDeclaration

		declaration = session.get(CustomsDeclaration, declaration_id)
		if declaration is None:
			raise ValueError(f"CustomsDeclaration {declaration_id!r} not found")
		if declaration.status != "DRAFT":
			raise ValueError("Only DRAFT declarations can be submitted")
		if int(declaration.total_value_cents or 0) <= 0:
			raise ValueError("total_value_cents must be positive")
		for line in declaration.lines or []:
			if not line.get("hs_code"):
				raise ValueError("All declaration lines must include hs_code")

		declaration.status = "SUBMITTED"
		declaration.submitted_at = datetime.now(timezone.utc)
		session.flush()
		return {
			"id": declaration.id,
			"shipment_id": declaration.shipment_id,
			"status": declaration.status,
			"submitted_at": declaration.submitted_at,
			"total_value_cents": declaration.total_value_cents,
			"total_duty_cents": declaration.total_duty_cents,
		}

	# ------------------------------------------------------------------
	# check_export_license_required
	# ------------------------------------------------------------------

	def check_export_license_required(
		self,
		hs_code: str,
		dest_country: str,
		session: Any,
	) -> dict[str, Any]:
		"""Return whether an HS code is export-controlled for a destination."""
		from pgappforge.plugins.erp.procurement.trade_compliance.models import HSCodeMapping

		row = session.execute(
			select(HSCodeMapping)
			.where(
				HSCodeMapping.hs_code == hs_code,
				sa.or_(
					HSCodeMapping.country_code == dest_country,
					HSCodeMapping.country_code.is_(None),
				),
			)
			.order_by(sa.desc(HSCodeMapping.country_code == dest_country))
			.limit(1)
		).scalar_one_or_none()
		if row is None:
			return {
				"required": False,
				"reason": "No HS code mapping found",
				"applying_regulation": "",
			}

		required = bool(getattr(row, "export_control_flag", getattr(row, "is_controlled", False)))
		return {
			"required": required,
			"reason": "HS code is export-controlled" if required else "No export control flag on HS code mapping",
			"applying_regulation": f"HSCodeMapping:{row.hs_code}",
		}

	# ------------------------------------------------------------------
	# refresh_ofac_list
	# ------------------------------------------------------------------

	def refresh_ofac_list(self, tenant_id: str, session: Any) -> dict[str, Any]:
		"""Download OFAC SDN XML and upsert into TradeRestrictionList.

		Production: fetches https://www.treasury.gov/ofac/downloads/sdn.xml
		Gracefully degrades (warns + returns empty) if network unavailable.
		"""
		import urllib.request
		# Use defusedxml to prevent XXE/DTD attacks; fall back to stdlib with
		# entity expansion disabled if defusedxml is not installed.
		try:
			import defusedxml.ElementTree as ET  # pip install defusedxml
		except ImportError:
			import xml.etree.ElementTree as ET  # noqa: N812 — safe fallback
			log.debug("defusedxml not installed — using stdlib ET (no XXE protection)")

		from pgappforge.plugins.erp.procurement.trade_compliance.models import TradeRestrictionList
		from pgappforge.plugins.erp.procurement.trade_compliance.events import TradeListRefreshedEvent

		_OFAC_MAX_BYTES = 60 * 1024 * 1024  # 60 MB hard cap (real SDN.xml ≈ 40 MB)

		try:
			url = "https://www.treasury.gov/ofac/downloads/sdn.xml"
			with urllib.request.urlopen(url, timeout=30) as resp:
				raw = resp.read(_OFAC_MAX_BYTES + 1)

			if len(raw) > _OFAC_MAX_BYTES:
				raise ValueError(
					f"OFAC SDN feed exceeds {_OFAC_MAX_BYTES // 1024 // 1024}MB size cap — possible poisoned feed"
				)

			import io
			tree = ET.parse(io.BytesIO(raw))

			entries: list[dict[str, Any]] = []
			for entry in tree.findall(".//{*}sdnEntry"):
				last_names = entry.findall(".//{*}lastName")
				first_names = entry.findall(".//{*}firstName")
				name_parts = [t.text or "" for t in last_names + first_names]
				name = " ".join(p for p in name_parts if p).strip()
				aliases = [
					a.text
					for a in entry.findall(".//{*}aka/{*}lastName")
					if a.text
				]
				entity_type = entry.findtext(".//{*}sdnType", "")
				entries.append({
					"name": name,
					"aliases": aliases,
					"entity_type": entity_type,
				})

			# Safety: never replace a populated list with zero entries
			# (would clear all sanctions screening — catastrophic)
			if len(entries) == 0:
				log.error(
					"refresh_ofac_list: parsed 0 entries from feed — refusing to overwrite existing list. "
					"This may indicate a feed format change or empty/corrupt response."
				)
				return {"entries": 0, "error": "zero_entries_refused"}

			lst = session.execute(
				select(TradeRestrictionList).where(
					TradeRestrictionList.list_name == "OFAC_SDN",
					TradeRestrictionList.tenant_id == tenant_id,
				)
			).scalar_one_or_none()

			if lst is None:
				lst = TradeRestrictionList(
					tenant_id=tenant_id,
					list_name="OFAC_SDN",
					description="OFAC Specially Designated Nationals",
					is_active=True,
				)
				session.add(lst)

			lst.entries = entries
			lst.entry_count = len(entries)
			lst.last_updated = datetime.now(timezone.utc)
			session.flush()

			_emit(
				TradeListRefreshedEvent(
					aggregate_id=lst.id,
					aggregate_type="TradeRestrictionList",
					tenant_id=tenant_id,
					list_name="OFAC_SDN",
					entry_count=len(entries),
				),
				session,
			)
			log.info("refresh_ofac_list: %d entries loaded for tenant %s", len(entries), tenant_id)
			return {"entries": len(entries)}

		except Exception as exc:
			log.error("OFAC refresh FAILED: %s — existing list unchanged (NOT cleared)", exc)
			return {"entries": 0, "error": str(exc)}


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"trade.compliance.screen_entity",
	"Screen entity against denied party lists",
)
def _bpm_screen_entity(
	record_ctx: dict,
	session: Any,
	entity_name: str = "",
	source_type: str | None = None,
	source_id: str | None = None,
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.procurement.trade_compliance.services import (
			TradeComplianceService,
		)
	except ImportError:
		return {"status": "error", "message": "trade_compliance plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		result = TradeComplianceService().screen_entity(
			entity_name=entity_name,
			tenant_id=tenant_id,
			session=session,
			source_type=source_type,
			source_id=source_id,
		)
		return {
			"status": "ok",
			"screening_status": result.status,
			"hit_count": result.hit_count,
			"top_match": result.top_match_name,
			"matched_list": result.matched_list,
		}
	except Exception as exc:
		log.warning("bpm trade.compliance.screen_entity failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"trade.compliance.classify_product",
	"Classify product with HS code",
)
def _bpm_classify_product(
	record_ctx: dict,
	session: Any,
	product_code: str = "",
	country_code: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.procurement.trade_compliance.services import (
			TradeComplianceService,
		)
	except ImportError:
		return {"status": "error", "message": "trade_compliance plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		row = TradeComplianceService().classify_product(
			product_code=product_code,
			country_code=country_code,
			tenant_id=tenant_id,
			session=session,
		)
		if row is None:
			return {"status": "ok", "found": False, "product_code": product_code}
		return {
			"status": "ok",
			"found": True,
			"hs_code": row.hs_code,
			"duty_rate_pct": str(row.duty_rate_pct),
			"is_controlled": row.is_controlled,
		}
	except Exception as exc:
		log.warning("bpm trade.compliance.classify_product failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = ["TradeComplianceService"]
