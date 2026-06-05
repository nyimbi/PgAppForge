"""
tests/ci/test_track_trace_plugin.py

CI tests for the Track & Trace (GS1 EPCIS 2.0) plugin.

Covers:
  - Model instantiation and column defaults
  - EPCISEvent immutability guard (ImmutableRecordMixin)
  - TrackTraceService.record_epcis_event validation
  - TrackTraceService.check_cold_chain_integrity
  - TrackTraceService.initiate_recall
  - TrackTraceService.find_affected_items
  - TrackTraceService.import_epcis_document (JSON-LD and XML)
  - TrackTraceService._parse_epcis_json
  - TrackTraceService._parse_epcis_xml
  - Event dataclass field defaults
  - __all__ re-exports from __init__
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uuid() -> str:
	return str(uuid.uuid4())


def _mock_session(objects: list | None = None):
	session = MagicMock()
	objects = objects or []

	def _get(model_cls, pk):
		for obj in objects:
			if isinstance(obj, model_cls) and getattr(obj, "id", None) == pk:
				return obj
		return None

	session.get.side_effect = _get
	session.flush.return_value = None
	session.add.return_value = None
	session.execute.return_value.scalars.return_value.all.return_value = []
	session.execute.return_value.scalar_one.return_value = 0
	session.execute.return_value.scalar_one_or_none.return_value = None
	return session


# ---------------------------------------------------------------------------
# Model import sanity
# ---------------------------------------------------------------------------

def test_track_trace_model_imports():
	from pgappforge.plugins.erp.industry.track_trace.models import (
		TraceableItem, EPCISEvent, ColdChainRecord, RecallEvent,
	)
	assert TraceableItem.__tablename__ == "tt_traceable_item"
	assert EPCISEvent.__tablename__ == "tt_epcis_event"
	assert ColdChainRecord.__tablename__ == "tt_cold_chain_record"
	assert RecallEvent.__tablename__ == "tt_recall_event"


def test_traceable_item_defaults():
	from pgappforge.plugins.erp.industry.track_trace.models import TraceableItem
	item = TraceableItem(
		tenant_id=_uuid(),
		epc="urn:epc:id:sgtin:0614141.107346.2017",
		item_type="SGTIN",
		current_owner_id=_uuid(),
	)
	assert item.is_recalled is False
	assert item.current_location == {}


def test_epcis_event_is_immutable():
	from pgappforge.plugins.erp.industry.track_trace.models import EPCISEvent
	assert EPCISEvent._immutable is True


def test_epcis_event_defaults():
	from pgappforge.plugins.erp.industry.track_trace.models import EPCISEvent
	now = datetime.now(timezone.utc)
	e = EPCISEvent(
		tenant_id=_uuid(),
		event_id=f"urn:uuid:{_uuid()}",
		event_type="OBJECT",
		action="ADD",
		event_time=now,
		biz_step="cbv:BizStep-shipping",
	)
	assert e.epc_list == []
	assert e.quantity_list == []
	assert e.biz_transaction_list == []
	assert e.source_list == []
	assert e.destination_list == []
	assert e.sensor_element_list == []


def test_cold_chain_record_defaults():
	from pgappforge.plugins.erp.industry.track_trace.models import ColdChainRecord
	now = datetime.now(timezone.utc)
	r = ColdChainRecord(
		item_epc="urn:epc:id:sgtin:0614141.107346.2017",
		measured_at=now,
		temperature_c=Decimal("4.5"),
		device_id="SENSOR-001",
	)
	assert r.is_excursion is False
	assert r.excursion_duration_minutes == 0


def test_recall_event_defaults():
	from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent
	now = datetime.now(timezone.utc)
	r = RecallEvent(
		tenant_id=_uuid(),
		recall_id="RCL-001",
		initiated_by=_uuid(),
		initiated_at=now,
		reason="Contamination",
		affected_gtin="12345678901234",
		affected_lots=["LOT001"],
		scope="NATIONAL",
		status="ACTIVE",
	)
	assert r.items_identified == 0
	assert r.items_recovered == 0
	assert r.status == "ACTIVE"
	assert r.scope == "NATIONAL"


# ---------------------------------------------------------------------------
# Event dataclasses
# ---------------------------------------------------------------------------

def test_event_defaults():
	from pgappforge.plugins.erp.industry.track_trace.events import (
		EPCISEventRecordedEvent,
		ColdChainExcursionEvent,
		RecallInitiatedEvent,
		RecallItemIdentifiedEvent,
		RecallCompletedEvent,
	)
	ev = EPCISEventRecordedEvent(aggregate_id="x", aggregate_type="EPCISEvent", tenant_id="t")
	assert ev.event_type == "track_trace.epcis.event_recorded"
	assert ev.epc_count == 0

	ev2 = ColdChainExcursionEvent(aggregate_id="x", aggregate_type="ColdChainRecord", tenant_id="t")
	assert ev2.event_type == "track_trace.cold_chain.excursion"
	assert ev2.excursion_duration_minutes == 0

	ev3 = RecallInitiatedEvent(aggregate_id="x", aggregate_type="RecallEvent", tenant_id="t")
	assert ev3.event_type == "track_trace.recall.initiated"
	assert ev3.affected_lots == []

	ev4 = RecallCompletedEvent(aggregate_id="x", aggregate_type="RecallEvent", tenant_id="t")
	assert ev4.recovery_rate_pct == 0.0
	assert ev4.items_identified == 0

	ev5 = RecallItemIdentifiedEvent(aggregate_id="x", aggregate_type="RecallEvent", tenant_id="t")
	assert ev5.current_location == {}


# ---------------------------------------------------------------------------
# Service: record_epcis_event validation
# ---------------------------------------------------------------------------

def test_record_epcis_event_invalid_type():
	from pgappforge.plugins.erp.industry.track_trace.services import (
		TrackTraceService, EPCISValidationError,
	)
	session = _mock_session()
	svc = TrackTraceService()
	with pytest.raises(EPCISValidationError, match="event_type must be one of"):
		svc.record_epcis_event(
			event_type="INVALID",
			action="ADD",
			epc_list=["urn:epc:id:sgtin:0614141.107346.1"],
			biz_step="cbv:BizStep-shipping",
			location={},
			session=session,
			tenant_id=_uuid(),
		)


def test_record_epcis_event_invalid_action():
	from pgappforge.plugins.erp.industry.track_trace.services import (
		TrackTraceService, EPCISValidationError,
	)
	session = _mock_session()
	svc = TrackTraceService()
	with pytest.raises(EPCISValidationError, match="action must be one of"):
		svc.record_epcis_event(
			event_type="OBJECT",
			action="APPEND",
			epc_list=[],
			biz_step="cbv:BizStep-shipping",
			location={},
			session=session,
			tenant_id=_uuid(),
		)


def test_record_epcis_event_creates_record():
	from pgappforge.plugins.erp.industry.track_trace.models import EPCISEvent
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	session = _mock_session()
	added = []
	session.add.side_effect = added.append

	svc = TrackTraceService()
	with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
		event = svc.record_epcis_event(
			event_type="OBJECT",
			action="ADD",
			epc_list=["urn:epc:id:sgtin:0614141.107346.2017"],
			biz_step="cbv:BizStep-receiving",
			location={
				"read_point": {"id": "urn:epc:id:sgln:0614141.00777.0"},
				"biz_location": {"id": "urn:epc:id:sgln:0614141.00888.0"},
			},
			session=session,
			tenant_id=_uuid(),
			disposition="cbv:Disp-in_progress",
		)

	assert isinstance(event, EPCISEvent)
	assert event.event_type == "OBJECT"
	assert event.action == "ADD"
	assert event.biz_step == "cbv:BizStep-receiving"
	assert event.epc_list == ["urn:epc:id:sgtin:0614141.107346.2017"]
	assert event.disposition == "cbv:Disp-in_progress"
	assert event.event_id.startswith("urn:uuid:")
	assert len(added) >= 1


# ---------------------------------------------------------------------------
# Service: check_cold_chain_integrity
# ---------------------------------------------------------------------------

def test_check_cold_chain_no_excursions():
	from pgappforge.plugins.erp.industry.track_trace.models import ColdChainRecord
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	epc = "urn:epc:id:sgtin:0614141.107346.2017"
	now = datetime.now(timezone.utc)
	records = [
		ColdChainRecord(
			item_epc=epc,
			measured_at=now - timedelta(minutes=i * 5),
			temperature_c=Decimal("5.0"),
			humidity_pct=Decimal("50.0"),
			device_id="SENSOR-001",
			is_excursion=False,
			excursion_duration_minutes=0,
		)
		for i in range(6)  # 6 readings at 5.0°C
	]

	session = _mock_session()
	session.execute.return_value.scalars.return_value.all.return_value = records

	svc = TrackTraceService()
	result = svc.check_cold_chain_integrity(
		item_epc=epc,
		from_time=now - timedelta(hours=1),
		to_time=now,
		session=session,
	)

	assert result["integrity_ok"] is True
	assert result["excursion_count"] == 0
	assert result["min_temp_c"] == 5.0
	assert result["max_temp_c"] == 5.0
	assert result["avg_temp_c"] == 5.0
	assert result["record_count"] == 6


def test_check_cold_chain_with_excursion():
	from pgappforge.plugins.erp.industry.track_trace.models import ColdChainRecord
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	epc = "urn:epc:id:sgtin:0614141.107346.9999"
	now = datetime.now(timezone.utc)
	records = [
		ColdChainRecord(
			item_epc=epc,
			measured_at=now - timedelta(minutes=10),
			temperature_c=Decimal("5.0"),
			device_id="S1",
			is_excursion=False,
			excursion_duration_minutes=0,
		),
		# Excursion: too warm
		ColdChainRecord(
			item_epc=epc,
			measured_at=now - timedelta(minutes=5),
			temperature_c=Decimal("12.5"),
			device_id="S1",
			is_excursion=True,
			excursion_duration_minutes=5,
		),
	]

	session = _mock_session()
	session.execute.return_value.scalars.return_value.all.return_value = records

	svc = TrackTraceService()
	result = svc.check_cold_chain_integrity(
		item_epc=epc,
		from_time=now - timedelta(hours=1),
		to_time=now,
		session=session,
		max_temp_c=8.0,
	)

	assert result["integrity_ok"] is False
	assert result["excursion_count"] == 1
	assert result["max_temp_c"] == 12.5


def test_check_cold_chain_no_records_raises():
	from pgappforge.plugins.erp.industry.track_trace.services import (
		TrackTraceService, ColdChainError,
	)
	session = _mock_session()
	session.execute.return_value.scalars.return_value.all.return_value = []

	svc = TrackTraceService()
	now = datetime.now(timezone.utc)
	with pytest.raises(ColdChainError, match="No cold chain records"):
		svc.check_cold_chain_integrity(
			item_epc="urn:epc:id:sgtin:0614141.107346.0000",
			from_time=now - timedelta(hours=1),
			to_time=now,
			session=session,
		)


# ---------------------------------------------------------------------------
# Service: initiate_recall
# ---------------------------------------------------------------------------

def test_initiate_recall_creates_record():
	from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	session = _mock_session()
	added = []
	session.add.side_effect = added.append
	# find_affected_items returns empty list
	session.execute.return_value.scalars.return_value.all.return_value = []

	svc = TrackTraceService()
	with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
		recall = svc.initiate_recall(
			gtin="12345678901234",
			lots=["LOT001", "LOT002"],
			reason="Microbial contamination",
			initiated_by=_uuid(),
			tenant_id=_uuid(),
			session=session,
			scope="NATIONAL",
		)

	assert isinstance(recall, RecallEvent)
	assert recall.affected_gtin == "12345678901234"
	assert recall.affected_lots == ["LOT001", "LOT002"]
	assert recall.status == "ACTIVE"
	assert recall.scope == "NATIONAL"
	assert recall.items_identified == 0  # no items found in mock


def test_initiate_recall_invalid_gtin():
	from pgappforge.plugins.erp.industry.track_trace.services import (
		TrackTraceService, TrackTraceError,
	)
	session = _mock_session()
	svc = TrackTraceService()
	with pytest.raises(TrackTraceError, match="gtin must be a 14-digit string"):
		svc.initiate_recall(
			gtin="1234",  # too short
			lots=["LOT001"],
			reason="Test",
			initiated_by=_uuid(),
			tenant_id=_uuid(),
			session=session,
		)


def test_initiate_recall_empty_lots():
	from pgappforge.plugins.erp.industry.track_trace.services import (
		TrackTraceService, TrackTraceError,
	)
	session = _mock_session()
	svc = TrackTraceService()
	with pytest.raises(TrackTraceError, match="lots must be a non-empty list"):
		svc.initiate_recall(
			gtin="12345678901234",
			lots=[],
			reason="Test",
			initiated_by=_uuid(),
			tenant_id=_uuid(),
			session=session,
		)


def test_initiate_recall_marks_items():
	from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent, TraceableItem
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	item1 = TraceableItem(
		id=_uuid(), tenant_id=_uuid(),
		epc="urn:epc:id:sgtin:0614141.107346.0001",
		item_type="SGTIN",
		gtin="12345678901234",
		lot_number="LOT001",
		current_owner_id=_uuid(),
		current_location={},
		is_recalled=False,
	)
	item2 = TraceableItem(
		id=_uuid(), tenant_id=_uuid(),
		epc="urn:epc:id:sgtin:0614141.107346.0002",
		item_type="SGTIN",
		gtin="12345678901234",
		lot_number="LOT001",
		current_owner_id=_uuid(),
		current_location={},
		is_recalled=False,
	)

	session = _mock_session()
	session.execute.return_value.scalars.return_value.all.return_value = [item1, item2]
	session.add.return_value = None

	svc = TrackTraceService()
	with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
		recall = svc.initiate_recall(
			gtin="12345678901234",
			lots=["LOT001"],
			reason="Contamination",
			initiated_by=_uuid(),
			tenant_id=_uuid(),
			session=session,
		)

	assert recall.items_identified == 2
	assert item1.is_recalled is True
	assert item2.is_recalled is True


# ---------------------------------------------------------------------------
# Service: find_affected_items
# ---------------------------------------------------------------------------

def test_find_affected_items_by_recall_id():
	from pgappforge.plugins.erp.industry.track_trace.models import RecallEvent, TraceableItem
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	recall = RecallEvent(
		id=_uuid(),
		tenant_id=_uuid(),
		recall_id="RCL-TEST",
		initiated_by=_uuid(),
		initiated_at=datetime.now(timezone.utc),
		reason="Test",
		affected_gtin="12345678901234",
		affected_lots=["LOT001"],
		scope="LOCAL",
		status="ACTIVE",
		items_identified=0,
		items_recovered=0,
		affected_date_range={},
	)

	item = TraceableItem(
		id=_uuid(), tenant_id=_uuid(),
		epc="urn:epc:id:sgtin:0614141.107346.0001",
		item_type="SGTIN",
		gtin="12345678901234",
		lot_number="LOT001",
		current_owner_id=_uuid(),
		current_location={},
		is_recalled=True,
	)

	session = MagicMock()
	# First execute returns recall, second returns items
	call_count = [0]

	def _execute(q):
		call_count[0] += 1
		mock_result = MagicMock()
		if call_count[0] == 1:
			mock_result.scalar_one_or_none.return_value = recall
		else:
			mock_result.scalars.return_value.all.return_value = [item]
		return mock_result

	session.execute.side_effect = _execute
	session.get.return_value = None

	svc = TrackTraceService()
	items = svc.find_affected_items("RCL-TEST", session)
	assert len(items) == 1
	assert items[0].epc == item.epc


def test_find_affected_items_not_found():
	from pgappforge.plugins.erp.industry.track_trace.services import (
		TrackTraceService, RecallNotFoundError,
	)
	session = MagicMock()
	session.execute.return_value.scalar_one_or_none.return_value = None
	session.get.return_value = None

	svc = TrackTraceService()
	with pytest.raises(RecallNotFoundError):
		svc.find_affected_items("NONEXISTENT", session)


# ---------------------------------------------------------------------------
# Service: import_epcis_document — JSON-LD
# ---------------------------------------------------------------------------

def test_import_epcis_json_document():
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	doc = {
		"@context": ["https://ref.gs1.org/standards/epcis/epcis-context.jsonld"],
		"type": "EPCISDocument",
		"epcisBody": {
			"eventList": [
				{
					"type": "ObjectEvent",
					"action": "ADD",
					"epcList": ["urn:epc:id:sgtin:0614141.107346.2017"],
					"bizStep": "cbv:BizStep-receiving",
					"disposition": "cbv:Disp-in_progress",
					"eventTime": "2025-01-15T10:00:00+00:00",
					"readPoint": {"id": "urn:epc:id:sgln:0614141.00777.0"},
				}
			]
		},
	}

	session = _mock_session()
	added = []
	session.add.side_effect = added.append
	session.execute.return_value.scalars.return_value.all.return_value = []

	svc = TrackTraceService()
	with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
		result = svc.import_epcis_document(
			json.dumps(doc), "json", session, tenant_id=_uuid()
		)

	assert result["total_events"] == 1
	assert result["imported"] == 1
	assert result["skipped"] == 0
	assert result["errors"] == []


def test_import_epcis_json_normalises_type():
	"""ObjectEvent → OBJECT normalisation."""
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	doc = {
		"epcisBody": {
			"eventList": [
				{
					"type": "ObjectEvent",
					"action": "OBSERVE",
					"epcList": ["urn:epc:id:sgtin:0614141.107346.9999"],
					"bizStep": "cbv:BizStep-shipping",
					"eventTime": "2025-03-01T08:00:00Z",
				}
			]
		}
	}

	session = _mock_session()
	session.execute.return_value.scalars.return_value.all.return_value = []

	svc = TrackTraceService()
	with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
		result = svc.import_epcis_document(json.dumps(doc), "json", session, tenant_id=_uuid())

	assert result["imported"] == 1


def test_import_epcis_invalid_format():
	from pgappforge.plugins.erp.industry.track_trace.services import (
		TrackTraceService, EPCISValidationError,
	)
	svc = TrackTraceService()
	with pytest.raises(EPCISValidationError, match="format must be"):
		svc.import_epcis_document("<doc/>", "yaml", MagicMock(), tenant_id=_uuid())


# ---------------------------------------------------------------------------
# Service: import_epcis_document — XML
# ---------------------------------------------------------------------------

def test_import_epcis_xml_document():
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService

	xml = """<?xml version="1.0" encoding="UTF-8"?>
<epcis:EPCISDocument xmlns:epcis="urn:epcglobal:epcis:xsd:2"
	schemaVersion="2.0"
	creationDate="2025-01-15T10:00:00Z">
	<EPCISBody>
		<EventList>
			<ObjectEvent>
				<eventTime>2025-01-15T10:00:00+00:00</eventTime>
				<eventTimeZoneOffset>+00:00</eventTimeZoneOffset>
				<epcList>
					<epc>urn:epc:id:sgtin:0614141.107346.2017</epc>
				</epcList>
				<action>ADD</action>
				<bizStep>cbv:BizStep-receiving</bizStep>
				<disposition>cbv:Disp-in_progress</disposition>
				<readPoint><id>urn:epc:id:sgln:0614141.00777.0</id></readPoint>
				<bizLocation><id>urn:epc:id:sgln:0614141.00888.0</id></bizLocation>
			</ObjectEvent>
		</EventList>
	</EPCISBody>
</epcis:EPCISDocument>"""

	session = _mock_session()
	session.execute.return_value.scalars.return_value.all.return_value = []

	svc = TrackTraceService()
	with patch("pgappforge.plugins.erp.foundation.events.emit_event"):
		result = svc.import_epcis_document(xml, "xml", session, tenant_id=_uuid())

	assert result["total_events"] == 1
	assert result["imported"] == 1
	assert result["skipped"] == 0


# ---------------------------------------------------------------------------
# Service: _parse helpers
# ---------------------------------------------------------------------------

def test_parse_epcis_json_empty_document():
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService
	events = TrackTraceService._parse_epcis_json('{"epcisBody": {"eventList": []}}')
	assert events == []


def test_parse_epcis_json_flat_event_list():
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService
	doc = {"eventList": [{"type": "ObjectEvent", "action": "OBSERVE"}]}
	events = TrackTraceService._parse_epcis_json(json.dumps(doc))
	assert len(events) == 1


def test_parse_epcis_xml_empty():
	from pgappforge.plugins.erp.industry.track_trace.services import TrackTraceService
	xml = '<EPCISDocument><EPCISBody><EventList/></EPCISBody></EPCISDocument>'
	events = TrackTraceService._parse_epcis_xml(xml)
	assert events == []


# ---------------------------------------------------------------------------
# get_item_history — not found
# ---------------------------------------------------------------------------

def test_get_item_history_not_found():
	from pgappforge.plugins.erp.industry.track_trace.services import (
		TrackTraceService, ItemNotFoundError,
	)
	session = MagicMock()
	session.execute.return_value.scalar_one_or_none.return_value = None

	svc = TrackTraceService()
	with pytest.raises(ItemNotFoundError, match="No TraceableItem"):
		svc.get_item_history("urn:epc:id:sgtin:0614141.107346.XXXX", session)


# ---------------------------------------------------------------------------
# __init__ re-exports
# ---------------------------------------------------------------------------

def test_init_all_exports():
	import pgappforge.plugins.erp.industry.track_trace as pkg
	for name in pkg.__all__:
		assert hasattr(pkg, name), f"__all__ exports {name!r} but it is not present"
