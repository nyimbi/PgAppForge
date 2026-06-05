"""
pgappforge/plugins/erp/industry/track_trace/services.py

TrackTraceService — stateless business logic for the Track & Trace plugin.

All methods accept an explicit SQLAlchemy Session; no Flask context assumed.
Safe to call from background jobs, CLI commands, and tests.

GS1 EPCIS 2.0 compliance:
  - EPCISEvent rows are NEVER updated (append-only ledger)
  - EPCIS corrections use action=DELETE + action=ADD pattern
  - import_epcis_document supports both EPCIS 2.0 XML and JSON-LD
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import func, select

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class TrackTraceError(Exception):
	"""Base error for Track & Trace domain violations."""


class ItemNotFoundError(TrackTraceError):
	"""No TraceableItem with the given EPC."""


class RecallNotFoundError(TrackTraceError):
	"""No RecallEvent with the given recall_id or id."""


class EPCISValidationError(TrackTraceError):
	"""EPCIS event payload failed validation."""


class ColdChainError(TrackTraceError):
	"""Cold chain integrity check failed or data unavailable."""


# ---------------------------------------------------------------------------
# TrackTraceService
# ---------------------------------------------------------------------------

class TrackTraceService:
	"""Stateless service for GS1 EPCIS Track & Trace operations.

	Callers own transaction boundaries (commit/rollback).
	"""

	# ------------------------------------------------------------------
	# EPCIS event recording
	# ------------------------------------------------------------------

	def record_epcis_event(
		self,
		*,
		event_type: str,
		action: str,
		epc_list: list[str],
		biz_step: str,
		location: dict,
		session: Any,
		tenant_id: str,
		disposition: str = "",
		quantity_list: list | None = None,
		biz_transaction_list: list | None = None,
		source_list: list | None = None,
		destination_list: list | None = None,
		sensor_element_list: list | None = None,
		event_time: datetime | None = None,
		event_id: str | None = None,
	) -> Any:
		"""Append an EPCIS 2.0 event to the immutable event ledger.

		event_type: OBJECT|AGGREGATION|TRANSACTION|TRANSFORMATION
		action:     ADD|OBSERVE|DELETE
		location:   {read_point: {id: GLN}, biz_location: {id: GLN}}
		epc_list:   list of EPC URI strings

		Raises:
		  EPCISValidationError for invalid event_type or action.
		"""
		from pgappforge.plugins.erp.industry.track_trace.models import EPCISEvent
		from pgappforge.plugins.erp.industry.track_trace.events import EPCISEventRecordedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed

		valid_types = {"OBJECT", "AGGREGATION", "TRANSACTION", "TRANSFORMATION"}
		if event_type not in valid_types:
			raise EPCISValidationError(
				f"event_type must be one of {valid_types}, got {event_type!r}"
			)

		valid_actions = {"ADD", "OBSERVE", "DELETE"}
		if action not in valid_actions:
			raise EPCISValidationError(
				f"action must be one of {valid_actions}, got {action!r}"
			)

		now = datetime.now(timezone.utc)
		eid = event_id or f"urn:uuid:{uuid.uuid4()}"

		event = EPCISEvent(
			tenant_id=tenant_id,
			event_id=eid,
			event_type=event_type,
			action=action,
			event_time=event_time or now,
			record_time=now,
			biz_step=biz_step,
			disposition=disposition,
			read_point=location.get("read_point"),
			biz_location=location.get("biz_location"),
			epc_list=epc_list,
			quantity_list=quantity_list or [],
			biz_transaction_list=biz_transaction_list or [],
			source_list=source_list or [],
			destination_list=destination_list or [],
			sensor_element_list=sensor_element_list or [],
		)
		session.add(event)
		session.flush()

		_emit_typed(
			EPCISEventRecordedEvent(
				aggregate_id=event.id,
				aggregate_type="EPCISEvent",
				tenant_id=tenant_id,
				epcis_event_id=eid,
				epcis_event_type=event_type,
				action=action,
				biz_step=biz_step,
				epc_count=len(epc_list),
				event_time=(event_time or now).isoformat(),
			),
			session,
		)

		# Update current_location on affected TraceableItems for ADD/OBSERVE
		if action in ("ADD", "OBSERVE") and epc_list:
			from pgappforge.plugins.erp.industry.track_trace.models import TraceableItem
			biz_loc = location.get("biz_location") or location.get("read_point") or {}
			items = session.execute(
				sa.select(TraceableItem).where(TraceableItem.epc.in_(epc_list))
			).scalars().all()
			for item in items:
				item.current_location = biz_loc

		log.info(
			"record_epcis_event: id=%r type=%r action=%r epcs=%d step=%r",
			eid, event_type, action, len(epc_list), biz_step,
		)
		return event

	# ------------------------------------------------------------------
	# Full item provenance chain
	# ------------------------------------------------------------------

	def get_item_history(
		self,
		epc: str,
		session: Any,
	) -> list[Any]:
		"""Return full EPCIS event history for an EPC (provenance chain).

		Searches epc_list JSONB array for events that contain this EPC.
		Returns events ordered by event_time ascending (oldest first).

		Raises:
		  ItemNotFoundError if no TraceableItem with this EPC exists.
		"""
		from pgappforge.plugins.erp.industry.track_trace.models import (
			EPCISEvent, TraceableItem,
		)

		item = session.execute(
			sa.select(TraceableItem).where(TraceableItem.epc == epc)
		).scalar_one_or_none()
		if item is None:
			raise ItemNotFoundError(f"No TraceableItem with EPC {epc!r}")

		# PostgreSQL JSONB array containment: epc_list @> '[epc]'
		events = session.execute(
			sa.select(EPCISEvent)
			.where(
				EPCISEvent.epc_list.cast(sa.Text).contains(json.dumps(epc)[1:-1])
			)
			.order_by(EPCISEvent.event_time.asc())
		).scalars().all()

		# Fallback: Python-side filter if JSON cast search is unreliable
		if not events:
			all_events = session.execute(
				sa.select(EPCISEvent).order_by(EPCISEvent.event_time.asc())
			).scalars().all()
			events = [e for e in all_events if epc in (e.epc_list or [])]

		log.debug("get_item_history: epc=%r found %d events", epc, len(events))
		return list(events)

	# ------------------------------------------------------------------
	# Cold chain integrity
	# ------------------------------------------------------------------

	def check_cold_chain_integrity(
		self,
		item_epc: str,
		from_time: datetime,
		to_time: datetime,
		session: Any,
		*,
		min_temp_c: float = 2.0,
		max_temp_c: float = 8.0,
	) -> dict:
		"""Analyse cold chain sensor data for an item over a time window.

		Returns:
		  - excursion_count: number of records with is_excursion=True
		  - min_temp_c: minimum recorded temperature
		  - max_temp_c: maximum recorded temperature
		  - avg_temp_c: mean temperature
		  - total_excursion_minutes: sum of excursion_duration_minutes
		  - record_count: number of sensor readings
		  - integrity_ok: True if no excursions detected
		  - excursion_events: list of {measured_at, temperature_c, excursion_duration_minutes}

		Raises:
		  ColdChainError if no records found for the item in the time window.
		"""
		from pgappforge.plugins.erp.industry.track_trace.models import ColdChainRecord

		records = session.execute(
			sa.select(ColdChainRecord)
			.where(
				ColdChainRecord.item_epc == item_epc,
				ColdChainRecord.measured_at >= from_time,
				ColdChainRecord.measured_at <= to_time,
			)
			.order_by(ColdChainRecord.measured_at.asc())
		).scalars().all()

		if not records:
			raise ColdChainError(
				f"No cold chain records for EPC {item_epc!r} "
				f"between {from_time.isoformat()} and {to_time.isoformat()}"
			)

		temps = [float(r.temperature_c) for r in records]
		excursions = [r for r in records if r.is_excursion]
		total_excursion_min = sum(r.excursion_duration_minutes or 0 for r in excursions)

		# Re-evaluate excursions against provided thresholds
		threshold_excursions = [
			{
				"measured_at": r.measured_at.isoformat(),
				"temperature_c": float(r.temperature_c),
				"excursion_duration_minutes": r.excursion_duration_minutes,
				"device_id": r.device_id,
			}
			for r in records
			if float(r.temperature_c) < min_temp_c or float(r.temperature_c) > max_temp_c
		]

		return {
			"item_epc": item_epc,
			"from_time": from_time.isoformat(),
			"to_time": to_time.isoformat(),
			"record_count": len(records),
			"min_temp_c": min(temps),
			"max_temp_c": max(temps),
			"avg_temp_c": round(sum(temps) / len(temps), 2),
			"permitted_range_c": {"min": min_temp_c, "max": max_temp_c},
			"excursion_count": len(threshold_excursions),
			"total_excursion_minutes": total_excursion_min,
			"integrity_ok": len(threshold_excursions) == 0,
			"excursion_events": threshold_excursions,
		}

	# ------------------------------------------------------------------
	# Recall management
	# ------------------------------------------------------------------

	def initiate_recall(
		self,
		*,
		gtin: str,
		lots: list[str],
		reason: str,
		initiated_by: str,
		tenant_id: str,
		session: Any,
		scope: str = "NATIONAL",
		affected_date_range: dict | None = None,
		recall_id: str | None = None,
	) -> Any:
		"""Initiate a product recall.

		Creates a RecallEvent record with status=ACTIVE.
		Immediately queries TraceableItem for affected items and updates
		items_identified.  Sets is_recalled=True on each affected item.

		Raises:
		  TrackTraceError if gtin is not 14 digits or lots is empty.
		"""
		from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent, TraceableItem
		from pgappforge.plugins.erp.industry.track_trace.events import RecallInitiatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed

		if not re.match(r"^\d{14}$", gtin):
			raise TrackTraceError(f"gtin must be a 14-digit string, got {gtin!r}")

		if not lots:
			raise TrackTraceError("lots must be a non-empty list of lot number strings")

		valid_scopes = {"LOCAL", "NATIONAL", "GLOBAL"}
		if scope not in valid_scopes:
			raise TrackTraceError(f"scope must be one of {valid_scopes}, got {scope!r}")

		now = datetime.now(timezone.utc)
		rid = recall_id or f"RCL-{uuid.uuid4().hex[:10].upper()}"

		recall = RecallEvent(
			tenant_id=tenant_id,
			recall_id=rid,
			initiated_by=initiated_by,
			initiated_at=now,
			reason=reason,
			affected_gtin=gtin,
			affected_lots=lots,
			affected_date_range=affected_date_range or {},
			scope=scope,
			status="ACTIVE",
			items_identified=0,
			items_recovered=0,
		)
		session.add(recall)
		session.flush()

		# Identify affected items immediately
		affected = self._identify_affected_items(gtin, lots, session)
		for item in affected:
			item.is_recalled = True
		recall.items_identified = len(affected)
		session.flush()

		_emit_typed(
			RecallInitiatedEvent(
				aggregate_id=recall.id,
				aggregate_type="RecallEvent",
				tenant_id=tenant_id,
				recall_id=rid,
				affected_gtin=gtin,
				affected_lots=lots,
				scope=scope,
				initiated_by=initiated_by,
				initiated_at=now.isoformat(),
			),
			session,
		)
		log.warning(
			"initiate_recall: recall=%r gtin=%r lots=%r items_identified=%d scope=%r",
			rid, gtin, lots, len(affected), scope,
		)
		return recall

	def find_affected_items(
		self,
		recall_id: str,
		session: Any,
	) -> list[Any]:
		"""Return all TraceableItems affected by a recall.

		Looks up the RecallEvent by recall_id (the human-readable reference),
		then queries TraceableItem by gtin + lot intersection.

		Raises:
		  RecallNotFoundError if recall_id not found.
		"""
		from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent

		recall = session.execute(
			sa.select(RecallEvent).where(RecallEvent.recall_id == recall_id)
		).scalar_one_or_none()
		if recall is None:
			# Try by UUID PK
			recall = session.get(RecallEvent, recall_id)
		if recall is None:
			raise RecallNotFoundError(f"RecallEvent {recall_id!r} not found")

		return self._identify_affected_items(
			recall.affected_gtin,
			recall.affected_lots or [],
			session,
		)

	def _identify_affected_items(
		self,
		gtin: str,
		lots: list[str],
		session: Any,
	) -> list[Any]:
		"""Internal: query TraceableItems matching gtin + lot membership."""
		from pgappforge.plugins.erp.industry.track_trace.models import TraceableItem

		q = sa.select(TraceableItem).where(TraceableItem.gtin == gtin)
		if lots:
			q = q.where(TraceableItem.lot_number.in_(lots))
		return session.execute(q).scalars().all()

	# ------------------------------------------------------------------
	# EPCIS document import
	# ------------------------------------------------------------------

	def import_epcis_document(
		self,
		xml_or_json: str,
		format: str,
		session: Any,
		tenant_id: str,
	) -> dict:
		"""Import an EPCIS 2.0 document (XML or JSON-LD) and persist events.

		format: "xml" or "json"

		Parses the document, extracts EventList, and calls record_epcis_event
		for each event.  Returns a summary dict.

		XML parsing uses xml.etree.ElementTree.
		JSON parsing expects EPCIS 2.0 JSON-LD structure:
		  {"@context": [...], "type": "EPCISDocument", "epcisBody": {"eventList": [...]}}

		Returns:
		  {imported: int, skipped: int, errors: [{event_index, error}]}
		"""
		imported = 0
		skipped = 0
		errors: list[dict] = []

		if format.lower() == "json":
			events_raw = self._parse_epcis_json(xml_or_json)
		elif format.lower() == "xml":
			events_raw = self._parse_epcis_xml(xml_or_json)
		else:
			raise EPCISValidationError(f"format must be 'json' or 'xml', got {format!r}")

		for idx, ev in enumerate(events_raw):
			try:
				event_type = ev.get("type", ev.get("event_type", "OBJECT")).upper()
				# Normalise EPCIS 2.0 type names
				_type_norm = {
					"OBJECTEVENT": "OBJECT",
					"AGGREGATIONEVENT": "AGGREGATION",
					"TRANSACTIONEVENT": "TRANSACTION",
					"TRANSFORMATIONEVENT": "TRANSFORMATION",
				}
				event_type = _type_norm.get(event_type, event_type)

				action = ev.get("action", "OBSERVE").upper()
				epc_list = ev.get("epcList", ev.get("epc_list", []))
				biz_step = ev.get("bizStep", ev.get("biz_step", ""))
				disposition = ev.get("disposition", "")
				event_time_str = ev.get("eventTime", ev.get("event_time"))
				event_time = (
					datetime.fromisoformat(event_time_str.replace("Z", "+00:00"))
					if event_time_str else None
				)

				read_point_raw = ev.get("readPoint", ev.get("read_point"))
				biz_loc_raw = ev.get("bizLocation", ev.get("biz_location"))
				location = {}
				if read_point_raw:
					location["read_point"] = (
						read_point_raw if isinstance(read_point_raw, dict)
						else {"id": str(read_point_raw)}
					)
				if biz_loc_raw:
					location["biz_location"] = (
						biz_loc_raw if isinstance(biz_loc_raw, dict)
						else {"id": str(biz_loc_raw)}
					)

				event_id = ev.get("eventID", ev.get("event_id"))

				self.record_epcis_event(
					event_type=event_type,
					action=action,
					epc_list=epc_list,
					biz_step=biz_step,
					location=location,
					session=session,
					tenant_id=tenant_id,
					disposition=disposition,
					quantity_list=ev.get("quantityList", ev.get("quantity_list", [])),
					biz_transaction_list=ev.get("bizTransactionList", ev.get("biz_transaction_list", [])),
					source_list=ev.get("sourceList", ev.get("source_list", [])),
					destination_list=ev.get("destinationList", ev.get("destination_list", [])),
					sensor_element_list=ev.get("sensorElementList", ev.get("sensor_element_list", [])),
					event_time=event_time,
					event_id=event_id,
				)
				imported += 1
			except Exception as exc:
				errors.append({"event_index": idx, "error": str(exc)})
				skipped += 1
				log.warning("import_epcis_document: skipping event[%d]: %s", idx, exc)

		log.info(
			"import_epcis_document: format=%r imported=%d skipped=%d",
			format, imported, skipped,
		)
		return {
			"format": format,
			"total_events": len(events_raw),
			"imported": imported,
			"skipped": skipped,
			"errors": errors,
		}

	@staticmethod
	def _parse_epcis_json(json_str: str) -> list[dict]:
		"""Parse EPCIS 2.0 JSON-LD document, return list of event dicts."""
		doc = json.loads(json_str)
		# Support both EPCISDocument and EPCISQueryDocument wrappings
		body = doc.get("epcisBody", doc.get("EPCISBody", {}))
		event_list = (
			body.get("eventList", body.get("EventList", []))
			if body
			else doc.get("eventList", [])
		)
		return event_list if isinstance(event_list, list) else []

	@staticmethod
	def _parse_epcis_xml(xml_str: str) -> list[dict]:
		"""Parse EPCIS 2.0 XML document, return list of minimal event dicts.

		Handles both namespaced (urn:epcglobal:epcis:xsd:2) and bare XML.
		Uses Clark notation {ns}tag throughout to avoid ElementTree prefix errors.
		"""
		import xml.etree.ElementTree as ET

		root = ET.fromstring(xml_str)

		_EPCIS_NS = ("urn:epcglobal:epcis:xsd:2", "urn:epcglobal:epcis:xsd:1", "")

		def _localname(el: ET.Element) -> str:
			tag = el.tag
			return tag.split("}")[-1] if "}" in tag else tag

		def _find_any(node: ET.Element, local: str) -> ET.Element | None:
			"""Find first child/descendant matching local tag name across all namespaces."""
			for ns in _EPCIS_NS:
				key = f"{{{ns}}}{local}" if ns else local
				found = node.find(f".//{key}")
				if found is not None:
					return found
			# Fallback: linear scan by local name
			for el in node.iter():
				if _localname(el) == local:
					return el
			return None

		def _text_local(node: ET.Element, local: str) -> str:
			el = _find_any(node, local)
			return el.text.strip() if el is not None and el.text else ""

		# Locate EventList
		event_list_el = _find_any(root, "EventList")
		if event_list_el is None:
			return []

		_type_tag_map = {
			"ObjectEvent": "OBJECT",
			"AggregationEvent": "AGGREGATION",
			"TransactionEvent": "TRANSACTION",
			"TransformationEvent": "TRANSFORMATION",
		}

		events: list[dict] = []
		for child in event_list_el:
			tag = _localname(child)
			event_type = _type_tag_map.get(tag, tag.upper())

			# EPC list
			epc_list_el = _find_any(child, "epcList")
			epc_list: list[str] = []
			if epc_list_el is not None:
				for e in epc_list_el:
					if _localname(e) == "epc" and e.text:
						epc_list.append(e.text.strip())

			# readPoint / bizLocation id
			rp_el = _find_any(child, "readPoint")
			rp_id = ""
			if rp_el is not None:
				rp_id = _text_local(rp_el, "id")

			bl_el = _find_any(child, "bizLocation")
			bl_id = ""
			if bl_el is not None:
				bl_id = _text_local(bl_el, "id")

			events.append({
				"type": event_type,
				"action": _text_local(child, "action") or "OBSERVE",
				"epcList": epc_list,
				"bizStep": _text_local(child, "bizStep"),
				"disposition": _text_local(child, "disposition"),
				"eventTime": _text_local(child, "eventTime"),
				"eventID": _text_local(child, "eventID"),
				"readPoint": {"id": rp_id},
				"bizLocation": {"id": bl_id},
			})

		return events


# Late import for regex used in initiate_recall
import re  # noqa: E402


__all__ = [
	"TrackTraceService",
	"TrackTraceError",
	"ItemNotFoundError",
	"RecallNotFoundError",
	"EPCISValidationError",
	"ColdChainError",
]
