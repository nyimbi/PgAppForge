"""
tests/ci/test_edi_plugin.py

CI tests for EDI Framework plugin.

Tests are import-only / unit-level — no database required.
Async tests use plain async functions + asyncio.get_event_loop().
"""
from __future__ import annotations

import asyncio


# ---------------------------------------------------------------------------
# Import smoke tests
# ---------------------------------------------------------------------------

def test_edi_events_importable():
	from pgappforge.plugins.erp.platform.edi.events import (
		EDIMessageSentEvent,
		EDIMessageReceivedEvent,
		EDIPartnerRegisteredEvent,
		EDIParseErrorEvent,
	)
	assert EDIMessageSentEvent().event_type == "platform.edi.message.sent"
	assert EDIMessageReceivedEvent().event_type == "platform.edi.message.received"
	assert EDIPartnerRegisteredEvent().event_type == "platform.edi.partner.registered"
	assert EDIParseErrorEvent().event_type == "platform.edi.parse.error"


def test_edi_models_importable():
	from pgappforge.plugins.erp.platform.edi.models import EDIPartner, EDIMessage
	assert EDIPartner.__tablename__ == "edi_partner"
	assert EDIMessage.__tablename__ == "edi_message"


def test_edi_service_importable():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	assert callable(EDIService)


def test_edi_plugin_importable():
	from pgappforge.plugins.erp.platform.edi import EDIPlugin, create_plugin
	assert EDIPlugin.name == "edi"
	assert EDIPlugin.domain == "platform"
	assert "foundation" in EDIPlugin.depends_on


# ---------------------------------------------------------------------------
# parse_x12
# ---------------------------------------------------------------------------

def test_parse_x12_850():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	svc = EDIService()
	content = (
		"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
		"*240101*1200*^*00501*000000001*0*P*:~"
		"GS*PO*SENDER*RECEIVER*20240101*1200*1*X*005010~"
		"ST*850*0001~"
		"BEG*00*SA*PO-12345**20240101~"
		"SE*3*0001~"
		"GE*1*1~"
		"IEA*1*000000001~"
	)
	result = svc.parse_x12(content, "850")
	assert result["message_type"] == "850"
	assert result["po_number"] == "PO-12345"
	assert "BEG" in result["segments"]
	assert result["raw_lines"] > 0


def test_parse_x12_810():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	svc = EDIService()
	content = (
		"ISA*00*          *00*          *ZZ*SENDER         *ZZ*RECEIVER       "
		"*240101*1200*^*00501*000000002*0*P*:~"
		"GS*IN*SENDER*RECEIVER*20240101*1200*2*X*005010~"
		"ST*810*0001~"
		"BIG*20240101*INV-9999~"
		"SE*3*0001~"
		"GE*1*2~"
		"IEA*1*000000002~"
	)
	result = svc.parse_x12(content, "810")
	assert result["invoice_number"] == "INV-9999"
	assert result["invoice_date"] == "20240101"


# ---------------------------------------------------------------------------
# format_x12
# ---------------------------------------------------------------------------

def test_format_x12_810():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	svc = EDIService()
	data = {
		"invoice_number": "INV-001",
		"invoice_date": "20240101",
		"currency": "USD",
		"total_cents": 150000,
	}
	output = svc.format_x12(data, "810", "PARTNER01")
	assert "ISA" in output
	assert "GS" in output
	assert "ST*810" in output
	assert "BIG*20240101*INV-001" in output
	assert "IEA" in output


def test_format_x12_850():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	svc = EDIService()
	data = {"po_number": "PO-555", "po_date": "20240201", "currency": "USD"}
	output = svc.format_x12(data, "850", "VENDOR01")
	assert "ST*850" in output
	assert "BEG*00*SA*PO-555" in output


# ---------------------------------------------------------------------------
# format_peppol_bis3
# ---------------------------------------------------------------------------

def test_format_peppol_bis3():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	svc = EDIService()
	inv = {
		"invoice_number": "P-2024-001",
		"invoice_date": "2024-01-15",
		"currency": "EUR",
		"supplier_name": "Acme Ltd",
		"customer_name": "Buyer Corp",
		"total_cents": 500000,
	}
	xml = svc.format_peppol_bis3(inv)
	assert "urn:cen.eu:en16931:2017" in xml
	assert "P-2024-001" in xml
	assert "5000.00" in xml
	assert "EUR" in xml
	assert "Acme Ltd" in xml


# ---------------------------------------------------------------------------
# format_etims
# ---------------------------------------------------------------------------

def test_format_etims_structure():
	from pgappforge.plugins.erp.platform.edi.services import EDIService
	svc = EDIService()
	inv = {
		"invoice_number": "ETI-001",
		"invoice_date": "2024-01-20",
		"buyer_pin": "A123456789B",
		"subtotal_cents": 10000,
		"tax_cents": 1600,
		"total_cents": 11600,
		"line_items": [
			{
				"product_code": "PROD01",
				"description": "Widget",
				"quantity": 2,
				"unit_price_cents": 5000,
				"tax_rate_pct": 16,
				"tax_cents": 1600,
				"total_cents": 11600,
			}
		],
	}
	payload = svc.format_etims(inv, pin="K123456789Z", tenant_id="t1")
	assert payload["invoiceNumber"] == "ETI-001"
	assert payload["pinOfBuyer"] == "A123456789B"
	assert abs(payload["totalAmount"] - 116.0) < 0.01
	assert len(payload["lineItems"]) == 1
	assert payload["lineItems"][0]["itemCode"] == "PROD01"


# ---------------------------------------------------------------------------
# EDIPlugin metadata
# ---------------------------------------------------------------------------

def test_edi_plugin_metadata():
	from pgappforge.plugins.erp.platform.edi import EDIPlugin

	class _FakeAB:
		pass

	plugin = EDIPlugin(_FakeAB())
	meta = plugin.metadata
	assert meta.version == "1.0.0"
	assert "etims" in meta.tags
	assert "peppol" in meta.tags
	events = plugin.get_events()
	assert "platform.edi.message.sent" in events
	models = plugin.register_models()
	assert len(models) == 2
