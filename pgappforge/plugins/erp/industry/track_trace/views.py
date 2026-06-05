"""
pgappforge/plugins/erp/industry/track_trace/views.py

Flask views for the Track & Trace plugin (GS1 EPCIS 2.0).

Views:
  ItemView          — TraceableItem CRUD + QR code widget for EPC, MapWidget for location
  EventView         — EPCISEvent list/detail + CodeEditorWidget for EPCIS JSON
  ColdChainView     — Cold chain sensor data + AdvancedChartsWidget for temperature trend
  RecallDashboard   — Recall management + GeographicHeatmapWidget for affected items
  ProvenanceView    — Full item history (provenance chain) view
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.view_helpers import (
	qr_widget,
	map_widget,
	json_widget,
	select2_widget,
	datetime_widget,
	date_widget,
	chart_widget,
	heatmap_widget,
)

log = logging.getLogger(__name__)

_EVENT_TYPES = ["OBJECT", "AGGREGATION", "TRANSACTION", "TRANSFORMATION"]
_ACTIONS = ["ADD", "OBSERVE", "DELETE"]
_ITEM_TYPES = ["SGTIN", "SSCC", "SGLN", "GRAI", "GIAI"]
_RECALL_SCOPES = ["LOCAL", "NATIONAL", "GLOBAL"]
_RECALL_STATUSES = ["ACTIVE", "COMPLETED", "CANCELLED"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session outside app context")


def _svc():
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService
	return TrackTraceService()


def _parse_dt(s: str | None) -> datetime | None:
	return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


# ---------------------------------------------------------------------------
# ItemView
# ---------------------------------------------------------------------------

class ItemView(BaseView):
	"""TraceableItem CRUD.

	Widget hints:
	  - QrCodeWidget:       epc (renders scannable QR for item)
	  - MapWidget:          current_location (renders geo pin)
	  - Select2Widget:      item_type
	  - DatePickerWidget:   expiry_date

	GET  /track-trace/items/                          — list
	GET  /track-trace/items/<id>                      — detail with QR code hint
	POST /track-trace/items/                          — register new traceable item
	GET  /track-trace/items/<id>/history              — full provenance chain
	GET  /track-trace/items/by-epc/<epc>              — lookup by EPC URI
	"""

	route_base = "/track-trace/items"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.track_trace.models import TraceableItem
		session = _get_session()
		gtin = request.args.get("gtin")
		lot_number = request.args.get("lot_number")
		is_recalled = request.args.get("is_recalled")
		item_type = request.args.get("item_type")
		tenant_id = request.args.get("tenant_id")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = sa.select(TraceableItem).order_by(TraceableItem.created_at.desc()).limit(limit)
		if gtin:
			q = q.where(TraceableItem.gtin == gtin)
		if lot_number:
			q = q.where(TraceableItem.lot_number == lot_number)
		if is_recalled is not None:
			q = q.where(TraceableItem.is_recalled == (is_recalled.lower() == "true"))
		if item_type:
			q = q.where(TraceableItem.item_type == item_type)
		if tenant_id:
			q = q.where(TraceableItem.tenant_id == tenant_id)

		items = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": i.id,
				"epc": i.epc,
				"item_type": i.item_type,
				"gtin": i.gtin,
				"serial_number": i.serial_number,
				"lot_number": i.lot_number,
				"expiry_date": i.expiry_date.isoformat() if i.expiry_date else None,
				"current_owner_id": i.current_owner_id,
				"is_recalled": i.is_recalled,
				"_widget_hints": {
					"epc": qr_widget(size=150),
					"current_location": map_widget(),
					"item_type": select2_widget(_ITEM_TYPES),
					"expiry_date": date_widget(),
				},
			}
			for i in items
		])

	@expose("/<string:item_id>")
	@has_access
	def detail(self, item_id: str):
		from pgappforge.plugins.erp.industry.track_trace.models import TraceableItem
		session = _get_session()
		i = session.get(TraceableItem, item_id)
		if i is None:
			abort(404, f"TraceableItem {item_id!r} not found")
		return jsonify({
			"id": i.id,
			"tenant_id": i.tenant_id,
			"epc": i.epc,
			"item_type": i.item_type,
			"gtin": i.gtin,
			"serial_number": i.serial_number,
			"lot_number": i.lot_number,
			"expiry_date": i.expiry_date.isoformat() if i.expiry_date else None,
			"product_id": i.product_id,
			"current_owner_id": i.current_owner_id,
			"current_location": i.current_location,
			"is_recalled": i.is_recalled,
			"created_at": i.created_at.isoformat() if i.created_at else None,
			"updated_at": i.updated_at.isoformat() if i.updated_at else None,
			"_widget_hints": {
				"epc": qr_widget(size=250),
				"current_location": map_widget(zoom=14),
				"item_type": select2_widget(_ITEM_TYPES),
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.industry.track_trace.models import TraceableItem
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "epc", "item_type", "current_owner_id")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing required fields: {missing}"}), 400

		from datetime import date as _date
		expiry = None
		if data.get("expiry_date"):
			try:
				expiry = _date.fromisoformat(data["expiry_date"])
			except ValueError:
				return jsonify({"error": "expiry_date must be ISO date (YYYY-MM-DD)"}), 400

		item = TraceableItem(
			tenant_id=data["tenant_id"],
			epc=data["epc"],
			item_type=data["item_type"],
			gtin=data.get("gtin"),
			serial_number=data.get("serial_number"),
			lot_number=data.get("lot_number"),
			expiry_date=expiry,
			product_id=data.get("product_id"),
			current_owner_id=data["current_owner_id"],
			current_location=data.get("current_location", {}),
			is_recalled=bool(data.get("is_recalled", False)),
		)
		session.add(item)
		session.commit()
		return jsonify({"item_id": item.id, "epc": item.epc}), 201

	@expose("/<string:item_id>/history")
	@has_access
	def history(self, item_id: str):
		"""Action: Full EPCIS provenance chain for this item."""
		from pgappforge.plugins.erp.industry.track_trace.models import TraceableItem
		session = _get_session()
		item = session.get(TraceableItem, item_id)
		if item is None:
			abort(404)
		try:
			events = _svc().get_item_history(item.epc, session)
			return jsonify({
				"epc": item.epc,
				"event_count": len(events),
				"events": [
					{
						"id": e.id,
						"event_id": e.event_id,
						"event_type": e.event_type,
						"action": e.action,
						"event_time": e.event_time.isoformat() if e.event_time else None,
						"biz_step": e.biz_step,
						"disposition": e.disposition,
						"read_point": e.read_point,
						"biz_location": e.biz_location,
					}
					for e in events
				],
				"_widget_hints": {"location": map_widget()},
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/by-epc/<path:epc>")
	@has_access
	def by_epc(self, epc: str):
		"""Lookup TraceableItem by EPC URI."""
		from pgappforge.plugins.erp.industry.track_trace.models import TraceableItem
		session = _get_session()
		item = session.execute(
			sa.select(TraceableItem).where(TraceableItem.epc == epc)
		).scalar_one_or_none()
		if item is None:
			abort(404, f"No TraceableItem with EPC {epc!r}")
		return jsonify({
			"id": item.id,
			"epc": item.epc,
			"item_type": item.item_type,
			"gtin": item.gtin,
			"lot_number": item.lot_number,
			"is_recalled": item.is_recalled,
			"current_location": item.current_location,
			"_widget_hints": {
				"epc": qr_widget(size=250),
				"current_location": map_widget(),
			},
		})


# ---------------------------------------------------------------------------
# EventView
# ---------------------------------------------------------------------------

class EventView(BaseView):
	"""EPCIS event list / detail + document import.

	Widget hints:
	  - JSONEditorWidget (CodeEditor mode): full EPCIS JSON for create/view
	  - Select2Widget:   event_type, action
	  - DateTimePickerWidget: event_time

	GET  /track-trace/events/                         — list
	GET  /track-trace/events/<id>                     — detail
	POST /track-trace/events/                         — record EPCIS event
	POST /track-trace/events/import                   — import EPCIS document (XML or JSON)
	"""

	route_base = "/track-trace/events"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.track_trace.models import EPCISEvent
		session = _get_session()
		event_type = request.args.get("event_type")
		action = request.args.get("action")
		biz_step = request.args.get("biz_step")
		tenant_id = request.args.get("tenant_id")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = (
			sa.select(EPCISEvent)
			.order_by(EPCISEvent.event_time.desc())
			.limit(limit)
		)
		if event_type:
			q = q.where(EPCISEvent.event_type == event_type)
		if action:
			q = q.where(EPCISEvent.action == action)
		if biz_step:
			q = q.where(EPCISEvent.biz_step == biz_step)
		if tenant_id:
			q = q.where(EPCISEvent.tenant_id == tenant_id)

		events = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": e.id,
				"event_id": e.event_id,
				"event_type": e.event_type,
				"action": e.action,
				"event_time": e.event_time.isoformat() if e.event_time else None,
				"biz_step": e.biz_step,
				"disposition": e.disposition,
				"epc_count": len(e.epc_list or []),
				"_immutable": True,
				"_widget_hints": {
					"event_type": select2_widget(_EVENT_TYPES),
					"action": select2_widget(_ACTIONS),
					"event_time": datetime_widget(),
				},
			}
			for e in events
		])

	@expose("/<string:event_id>")
	@has_access
	def detail(self, event_id: str):
		from pgappforge.plugins.erp.industry.track_trace.models import EPCISEvent
		session = _get_session()
		e = session.get(EPCISEvent, event_id)
		if e is None:
			abort(404, f"EPCISEvent {event_id!r} not found")
		return jsonify({
			"id": e.id,
			"tenant_id": e.tenant_id,
			"event_id": e.event_id,
			"event_type": e.event_type,
			"action": e.action,
			"event_time": e.event_time.isoformat() if e.event_time else None,
			"record_time": e.record_time.isoformat() if e.record_time else None,
			"biz_step": e.biz_step,
			"disposition": e.disposition,
			"read_point": e.read_point,
			"biz_location": e.biz_location,
			"epc_list": e.epc_list,
			"quantity_list": e.quantity_list,
			"biz_transaction_list": e.biz_transaction_list,
			"source_list": e.source_list,
			"destination_list": e.destination_list,
			"sensor_element_list": e.sensor_element_list,
			"created_at": e.created_at.isoformat() if e.created_at else None,
			"_immutable": True,
			"_widget_hints": {
				"event_type": select2_widget(_EVENT_TYPES),
				"action": select2_widget(_ACTIONS),
				"event_time": datetime_widget(),
				"epc_list": json_widget(mode="code", readonly=True),
				"sensor_element_list": json_widget(mode="tree", readonly=True),
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Record an EPCIS event (immutable append)."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "event_type", "action", "epc_list", "biz_step")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			event = _svc().record_epcis_event(
				event_type=data["event_type"],
				action=data["action"],
				epc_list=data["epc_list"],
				biz_step=data["biz_step"],
				location=data.get("location", {}),
				session=session,
				tenant_id=data["tenant_id"],
				disposition=data.get("disposition", ""),
				quantity_list=data.get("quantity_list"),
				biz_transaction_list=data.get("biz_transaction_list"),
				source_list=data.get("source_list"),
				destination_list=data.get("destination_list"),
				sensor_element_list=data.get("sensor_element_list"),
				event_time=_parse_dt(data.get("event_time")),
				event_id=data.get("event_id"),
			)
			session.commit()
			return jsonify({
				"id": event.id,
				"event_id": event.event_id,
				"event_type": event.event_type,
				"action": event.action,
				"epc_count": len(event.epc_list or []),
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/import", methods=["POST"])
	@has_access
	def import_document(self):
		"""Action: Import EPCIS 2.0 document (XML or JSON-LD)."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "content", "format")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			result = _svc().import_epcis_document(
				xml_or_json=data["content"],
				format=data["format"],
				session=session,
				tenant_id=data["tenant_id"],
			)
			session.commit()
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# ColdChainView
# ---------------------------------------------------------------------------

class ColdChainView(BaseView):
	"""Cold chain sensor data view.

	Widget hints:
	  - AdvancedChartsWidget (line): temperature trend over time
	  - RangeSliderWidget:           temperature threshold configuration

	GET  /track-trace/cold-chain/                          — list records
	POST /track-trace/cold-chain/                          — record sensor reading
	GET  /track-trace/cold-chain/integrity/<epc>           — cold chain integrity check
	GET  /track-trace/cold-chain/excursions?tenant_id=<id> — active excursions
	"""

	route_base = "/track-trace/cold-chain"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.track_trace.models import ColdChainRecord
		session = _get_session()
		item_epc = request.args.get("item_epc")
		device_id = request.args.get("device_id")
		excursions_only = request.args.get("excursions_only", "false").lower() == "true"
		limit = min(int(request.args.get("limit", 200)), 2000)

		q = (
			sa.select(ColdChainRecord)
			.order_by(ColdChainRecord.measured_at.desc())
			.limit(limit)
		)
		if item_epc:
			q = q.where(ColdChainRecord.item_epc == item_epc)
		if device_id:
			q = q.where(ColdChainRecord.device_id == device_id)
		if excursions_only:
			q = q.where(ColdChainRecord.is_excursion.is_(True))

		records = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"item_epc": r.item_epc,
				"measured_at": r.measured_at.isoformat() if r.measured_at else None,
				"temperature_c": float(r.temperature_c),
				"humidity_pct": float(r.humidity_pct) if r.humidity_pct is not None else None,
				"device_id": r.device_id,
				"is_excursion": r.is_excursion,
				"excursion_duration_minutes": r.excursion_duration_minutes,
				"_widget_hints": {
					"temperature_trend": chart_widget("line"),
					"threshold": {
						"type": "RangeSliderWidget",
						"config": {"min": -30, "max": 30, "step": 0.5},
					},
				},
			}
			for r in records
		])

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		"""Record a cold chain sensor reading."""
		from pgappforge.plugins.erp.industry.track_trace.models import ColdChainRecord
		from pgappforge.plugins.erp.industry.track_trace.events import ColdChainExcursionEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed

		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("item_epc", "measured_at", "temperature_c", "device_id")
		missing = [f for f in required if data.get(f) is None]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400

		min_t = float(data.get("min_temp_c", 2.0))
		max_t = float(data.get("max_temp_c", 8.0))
		temp = float(data["temperature_c"])
		is_excursion = temp < min_t or temp > max_t

		record = ColdChainRecord(
			item_epc=data["item_epc"],
			measured_at=_parse_dt(data["measured_at"]) or datetime.now(timezone.utc),
			temperature_c=temp,
			humidity_pct=data.get("humidity_pct"),
			location=data.get("location"),
			device_id=data["device_id"],
			is_excursion=is_excursion,
			excursion_duration_minutes=int(data.get("excursion_duration_minutes", 0)),
		)
		session.add(record)

		if is_excursion:
			tenant_id = data.get("tenant_id", "")
			_emit_typed(
				ColdChainExcursionEvent(
					aggregate_id=record.id if hasattr(record, "id") else "",
					aggregate_type="ColdChainRecord",
					tenant_id=tenant_id,
					item_epc=data["item_epc"],
					device_id=data["device_id"],
					temperature_c=str(temp),
					measured_at=record.measured_at.isoformat(),
					excursion_duration_minutes=record.excursion_duration_minutes,
				),
				session,
			)

		session.commit()
		return jsonify({
			"item_epc": record.item_epc,
			"temperature_c": float(record.temperature_c),
			"is_excursion": record.is_excursion,
			"measured_at": record.measured_at.isoformat(),
		}), 201

	@expose("/integrity/<path:epc>")
	@has_access
	def integrity(self, epc: str):
		"""Action: Cold chain integrity analysis for an EPC over a time window."""
		session = _get_session()
		from_str = request.args.get("from_time")
		to_str = request.args.get("to_time")
		if not from_str or not to_str:
			return jsonify({"error": "from_time and to_time query params required (ISO datetime)"}), 400
		try:
			result = _svc().check_cold_chain_integrity(
				item_epc=epc,
				from_time=_parse_dt(from_str),
				to_time=_parse_dt(to_str),
				session=session,
				min_temp_c=float(request.args.get("min_temp_c", 2.0)),
				max_temp_c=float(request.args.get("max_temp_c", 8.0)),
			)
			result["_widget_hints"] = {
				"temperature_trend": chart_widget("line"),
				"threshold": {
					"type": "RangeSliderWidget",
					"config": {"min": -30, "max": 30, "step": 0.5, "show_value": True},
				},
			}
			return jsonify(result)
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/excursions")
	@has_access
	def excursions(self):
		"""List active temperature excursions for a tenant."""
		from pgappforge.plugins.erp.industry.track_trace.models import ColdChainRecord
		session = _get_session()
		limit = min(int(request.args.get("limit", 100)), 500)

		rows = session.execute(
			sa.select(ColdChainRecord)
			.where(ColdChainRecord.is_excursion.is_(True))
			.order_by(ColdChainRecord.measured_at.desc())
			.limit(limit)
		).scalars().all()

		return jsonify({
			"active_excursion_count": len(rows),
			"excursions": [
				{
					"id": r.id,
					"item_epc": r.item_epc,
					"measured_at": r.measured_at.isoformat() if r.measured_at else None,
					"temperature_c": float(r.temperature_c),
					"device_id": r.device_id,
					"excursion_duration_minutes": r.excursion_duration_minutes,
				}
				for r in rows
			],
			"_widget_hints": {"charts": chart_widget("line")},
		})


# ---------------------------------------------------------------------------
# RecallDashboard
# ---------------------------------------------------------------------------

class RecallDashboard(BaseView):
	"""Product recall management dashboard.

	Widget hints:
	  - GeographicHeatmapWidget: geographic distribution of affected items
	  - Select2Widget:           scope, status

	GET  /track-trace/recalls/                        — list recalls
	GET  /track-trace/recalls/<recall_id>             — detail
	POST /track-trace/recalls/                        — initiate recall
	GET  /track-trace/recalls/<recall_id>/items       — affected items
	POST /track-trace/recalls/<recall_id>/complete    — close recall
	GET  /track-trace/recalls/dashboard               — summary heatmap dashboard
	"""

	route_base = "/track-trace/recalls"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent
		session = _get_session()
		status = request.args.get("status")
		scope = request.args.get("scope")
		gtin = request.args.get("gtin")
		tenant_id = request.args.get("tenant_id")
		limit = min(int(request.args.get("limit", 100)), 500)

		q = sa.select(RecallEvent).order_by(RecallEvent.initiated_at.desc()).limit(limit)
		if status:
			q = q.where(RecallEvent.status == status)
		if scope:
			q = q.where(RecallEvent.scope == scope)
		if gtin:
			q = q.where(RecallEvent.affected_gtin == gtin)
		if tenant_id:
			q = q.where(RecallEvent.tenant_id == tenant_id)

		recalls = session.execute(q).scalars().all()
		return jsonify([
			{
				"id": r.id,
				"recall_id": r.recall_id,
				"affected_gtin": r.affected_gtin,
				"initiated_at": r.initiated_at.isoformat() if r.initiated_at else None,
				"scope": r.scope,
				"status": r.status,
				"items_identified": r.items_identified,
				"items_recovered": r.items_recovered,
				"recovery_rate_pct": (
					round(r.items_recovered / r.items_identified * 100, 1)
					if r.items_identified > 0 else 0.0
				),
				"_widget_hints": {
					"scope": select2_widget(_RECALL_SCOPES),
					"status": select2_widget(_RECALL_STATUSES),
					"location_heatmap": heatmap_widget(),
				},
			}
			for r in recalls
		])

	@expose("/<string:recall_ref>")
	@has_access
	def detail(self, recall_ref: str):
		from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent
		session = _get_session()
		# Try by recall_id string first, then by UUID PK
		r = session.execute(
			sa.select(RecallEvent).where(RecallEvent.recall_id == recall_ref)
		).scalar_one_or_none()
		if r is None:
			r = session.get(RecallEvent, recall_ref)
		if r is None:
			abort(404, f"RecallEvent {recall_ref!r} not found")
		return jsonify({
			"id": r.id,
			"tenant_id": r.tenant_id,
			"recall_id": r.recall_id,
			"initiated_by": r.initiated_by,
			"initiated_at": r.initiated_at.isoformat() if r.initiated_at else None,
			"reason": r.reason,
			"affected_gtin": r.affected_gtin,
			"affected_lots": r.affected_lots,
			"affected_date_range": r.affected_date_range,
			"scope": r.scope,
			"status": r.status,
			"items_identified": r.items_identified,
			"items_recovered": r.items_recovered,
			"recovery_rate_pct": (
				round(r.items_recovered / r.items_identified * 100, 1)
				if r.items_identified > 0 else 0.0
			),
			"created_at": r.created_at.isoformat() if r.created_at else None,
			"_widget_hints": {
				"scope": select2_widget(_RECALL_SCOPES),
				"status": select2_widget(_RECALL_STATUSES),
				"location_heatmap": heatmap_widget(),
			},
		})

	@expose("/", methods=["POST"])
	@has_access
	def initiate(self):
		"""Action: Initiate a product recall."""
		session = _get_session()
		data = request.get_json(force=True) or {}
		required = ("tenant_id", "gtin", "lots", "reason", "initiated_by")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"error": f"Missing: {missing}"}), 400
		try:
			recall = _svc().initiate_recall(
				gtin=data["gtin"],
				lots=data["lots"],
				reason=data["reason"],
				initiated_by=data["initiated_by"],
				tenant_id=data["tenant_id"],
				session=session,
				scope=data.get("scope", "NATIONAL"),
				affected_date_range=data.get("affected_date_range", {}),
				recall_id=data.get("recall_id"),
			)
			session.commit()
			return jsonify({
				"recall_id": recall.recall_id,
				"id": recall.id,
				"affected_gtin": recall.affected_gtin,
				"scope": recall.scope,
				"status": recall.status,
				"items_identified": recall.items_identified,
			}), 201
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:recall_ref>/items")
	@has_access
	def affected_items(self, recall_ref: str):
		"""Action: List all TraceableItems affected by this recall."""
		session = _get_session()
		try:
			items = _svc().find_affected_items(recall_ref, session)
			return jsonify({
				"recall_id": recall_ref,
				"item_count": len(items),
				"items": [
					{
						"id": i.id,
						"epc": i.epc,
						"gtin": i.gtin,
						"lot_number": i.lot_number,
						"current_owner_id": i.current_owner_id,
						"current_location": i.current_location,
						"is_recalled": i.is_recalled,
					}
					for i in items
				],
				"_widget_hints": {"location_heatmap": heatmap_widget()},
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:recall_ref>/complete", methods=["POST"])
	@has_access
	def complete_recall(self, recall_ref: str):
		"""Action: Close out a recall (COMPLETED or CANCELLED)."""
		from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent
		from pgappforge.plugins.erp.industry.track_trace.events import RecallCompletedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event as _emit_typed

		session = _get_session()
		r = session.execute(
			sa.select(RecallEvent).where(RecallEvent.recall_id == recall_ref)
		).scalar_one_or_none()
		if r is None:
			r = session.get(RecallEvent, recall_ref)
		if r is None:
			abort(404)
		if r.status != "ACTIVE":
			return jsonify({"error": f"Recall is already {r.status!r}"}), 422

		data = request.get_json(force=True) or {}
		new_status = data.get("status", "COMPLETED")
		if new_status not in ("COMPLETED", "CANCELLED"):
			return jsonify({"error": "status must be COMPLETED or CANCELLED"}), 400

		items_recovered = int(data.get("items_recovered", r.items_recovered))
		r.status = new_status
		r.items_recovered = items_recovered
		session.flush()

		recovery_rate = (
			round(items_recovered / r.items_identified * 100, 2)
			if r.items_identified > 0 else 0.0
		)
		_emit_typed(
			RecallCompletedEvent(
				aggregate_id=r.id,
				aggregate_type="RecallEvent",
				tenant_id=str(r.tenant_id),
				recall_id=r.recall_id,
				affected_gtin=r.affected_gtin,
				final_status=new_status,
				items_identified=r.items_identified,
				items_recovered=items_recovered,
				recovery_rate_pct=recovery_rate,
			),
			session,
		)
		session.commit()
		return jsonify({
			"recall_id": r.recall_id,
			"status": new_status,
			"items_identified": r.items_identified,
			"items_recovered": items_recovered,
			"recovery_rate_pct": recovery_rate,
		})

	@expose("/dashboard")
	@has_access
	def dashboard(self):
		"""Dashboard: recall summary with geographic heatmap data."""
		from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent, TraceableItem
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		if not tenant_id:
			return jsonify({"error": "tenant_id query param required"}), 400

		active_recalls = session.execute(
			sa.select(RecallEvent)
			.where(RecallEvent.tenant_id == tenant_id, RecallEvent.status == "ACTIVE")
		).scalars().all()

		total_recalled_items = session.execute(
			sa.select(sa.func.count(TraceableItem.id))
			.where(
				TraceableItem.tenant_id == tenant_id,
				TraceableItem.is_recalled.is_(True),
			)
		).scalar_one() or 0

		recall_by_scope = session.execute(
			sa.select(
				RecallEvent.scope,
				sa.func.count(RecallEvent.id).label("count"),
			)
			.where(RecallEvent.tenant_id == tenant_id)
			.group_by(RecallEvent.scope)
		).all()

		# Heatmap data: locations of recalled items
		recalled_items = session.execute(
			sa.select(TraceableItem.current_location)
			.where(
				TraceableItem.tenant_id == tenant_id,
				TraceableItem.is_recalled.is_(True),
				TraceableItem.current_location.isnot(None),
			)
			.limit(500)
		).scalars().all()

		heatmap_points = []
		for loc in recalled_items:
			if isinstance(loc, dict):
				lat = loc.get("geo_lat") or loc.get("lat")
				lng = loc.get("geo_lng") or loc.get("lng")
				if lat and lng:
					heatmap_points.append({"lat": lat, "lng": lng, "weight": 1})

		return jsonify({
			"tenant_id": tenant_id,
			"active_recall_count": len(active_recalls),
			"total_recalled_items": total_recalled_items,
			"recalls_by_scope": {r.scope: r.count for r in recall_by_scope},
			"active_recalls": [
				{
					"recall_id": r.recall_id,
					"affected_gtin": r.affected_gtin,
					"initiated_at": r.initiated_at.isoformat() if r.initiated_at else None,
					"scope": r.scope,
					"items_identified": r.items_identified,
					"items_recovered": r.items_recovered,
				}
				for r in active_recalls
			],
			"heatmap_data": heatmap_points,
			"_widget_hints": {
				"location_heatmap": heatmap_widget(),
				"charts": chart_widget("bar"),
			},
		})


# ---------------------------------------------------------------------------
# ProvenanceView
# ---------------------------------------------------------------------------

class ProvenanceView(BaseView):
	"""EPCIS item provenance chain view.

	GET  /track-trace/provenance/<epc>                — full event history by EPC
	"""

	route_base = "/track-trace/provenance"
	default_view = "by_epc"

	@expose("/<path:epc>")
	@has_access
	def by_epc(self, epc: str):
		"""Full EPCIS provenance chain for an EPC URI."""
		session = _get_session()
		try:
			events = _svc().get_item_history(epc, session)
			return jsonify({
				"epc": epc,
				"event_count": len(events),
				"provenance_chain": [
					{
						"id": e.id,
						"event_id": e.event_id,
						"event_type": e.event_type,
						"action": e.action,
						"event_time": e.event_time.isoformat() if e.event_time else None,
						"biz_step": e.biz_step,
						"disposition": e.disposition,
						"read_point": e.read_point,
						"biz_location": e.biz_location,
						"source_list": e.source_list,
						"destination_list": e.destination_list,
					}
					for e in events
				],
				"_widget_hints": {
					"location": map_widget(),
					"event_payload": json_widget(mode="view", readonly=True),
				},
			})
		except Exception as exc:
			return jsonify({"error": str(exc)}), 422


__all__ = [
	"ItemView",
	"EventView",
	"ColdChainView",
	"RecallDashboard",
	"ProvenanceView",
]
