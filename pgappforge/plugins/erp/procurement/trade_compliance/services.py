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


def _emit(event: Any, session: Any = None) -> None:
	try:
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_event
		_emit_event(event, session)
	except Exception as exc:
		log.debug("TradeComplianceService: emit suppressed: %s", exc)


# ---------------------------------------------------------------------------
# TradeComplianceService
# ---------------------------------------------------------------------------

class TradeComplianceService:
	"""Stateless trade compliance service."""

	# ------------------------------------------------------------------
	# _jaro_winkler
	# ------------------------------------------------------------------

	def _jaro_winkler(self, s1: str, s2: str) -> float:
		"""Jaro-Winkler similarity — stdlib only, no fuzzy library required."""
		if s1 == s2:
			return 1.0
		s1, s2 = s1.lower(), s2.lower()
		if not s1 or not s2:
			return 0.0

		match_dist = max(len(s1), len(s2)) // 2 - 1
		if match_dist < 0:
			match_dist = 0

		s1_matches = [False] * len(s1)
		s2_matches = [False] * len(s2)
		matches = 0
		transpositions = 0

		for i, c1 in enumerate(s1):
			start = max(0, i - match_dist)
			end = min(i + match_dist + 1, len(s2))
			for j in range(start, end):
				if not s2_matches[j] and c1 == s2[j]:
					s1_matches[i] = s2_matches[j] = True
					matches += 1
					break

		if matches == 0:
			return 0.0

		k = 0
		for i in range(len(s1)):
			if s1_matches[i]:
				while not s2_matches[k]:
					k += 1
				if s1[i] != s2[k]:
					transpositions += 1
				k += 1

		jaro = (
			matches / len(s1)
			+ matches / len(s2)
			+ (matches - transpositions / 2) / matches
		) / 3

		prefix = 0
		for i in range(min(4, min(len(s1), len(s2)))):
			if s1[i] == s2[i]:
				prefix += 1
			else:
				break

		return jaro + prefix * 0.1 * (1 - jaro)

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
					duty_rate_pct=float(row.duty_rate_pct or 0),
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
	# refresh_ofac_list
	# ------------------------------------------------------------------

	def refresh_ofac_list(self, tenant_id: str, session: Any) -> dict[str, Any]:
		"""Download OFAC SDN XML and upsert into TradeRestrictionList.

		Production: fetches https://www.treasury.gov/ofac/downloads/sdn.xml
		Gracefully degrades (warns + returns empty) if network unavailable.
		"""
		import urllib.request
		import xml.etree.ElementTree as ET

		from pgappforge.plugins.erp.procurement.trade_compliance.models import TradeRestrictionList
		from pgappforge.plugins.erp.procurement.trade_compliance.events import TradeListRefreshedEvent

		try:
			url = "https://www.treasury.gov/ofac/downloads/sdn.xml"
			with urllib.request.urlopen(url, timeout=30) as resp:
				tree = ET.parse(resp)

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
			log.warning("OFAC refresh failed: %s — seeding empty list", exc)
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
