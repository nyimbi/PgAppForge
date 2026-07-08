"""Hardening tests for platform EDI parsing and formatting."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from pgappforge.plugins.erp.platform.edi.models import EDIPartner
from pgappforge.plugins.erp.platform.edi.services import EDIService, EDIServiceError


class _Session:
    def __init__(self, partner=None) -> None:
        self.partner = partner
        self.added = []

    def get(self, model, item_id):
        if model is EDIPartner and self.partner is not None and self.partner.id == item_id:
            return self.partner
        return None

    def add(self, obj) -> None:
        self.added.append(obj)


def test_x12_parse_enriches_business_fields_and_rejects_delimiters():
    service = EDIService()
    payload = (
        "ST*850*0001~"
        "BEG*00*SA*PO-12345**20240101~"
        "SE*3*0001~"
    )

    parsed = service.parse_x12(payload, "850")

    assert parsed["raw_lines"] == 3
    assert parsed["po_number"] == "PO-12345"
    assert parsed["po_date"] == "20240101"

    with pytest.raises(EDIServiceError, match="reserved delimiter"):
        service.format_x12({"segments": {"BEG": [["00", "bad~value"]]}}, "850", "PARTNER1")
    with pytest.raises(EDIServiceError, match="segment id"):
        service.parse_x12("BAD_SEG*segment~", "850")


def test_x12_format_builds_standard_850_and_810_bodies():
    service = EDIService()

    po = service.format_x12({"po_number": "PO-555", "po_date": "20240201"}, "850", "VENDOR01")
    invoice = service.format_x12(
        {"invoice_number": "INV-001", "invoice_date": "20240101"},
        "810",
        "PARTNER01",
    )

    assert "ST*850" in po
    assert "BEG*00*SA*PO-555**20240201" in po
    assert "ST*810" in invoice
    assert "BIG*20240101*INV-001" in invoice


def test_peppol_escapes_xml_and_uses_cent_amounts():
    service = EDIService()

    xml = service.format_peppol_bis3(
        {
            "invoice_number": "P-2024-001",
            "invoice_date": "2024-01-15",
            "currency": "EUR",
            "supplier_name": "Acme & Sons",
            "customer_name": "Buyer <Corp>",
            "total_cents": 500000,
            "tax_cents": 80000,
        }
    )
    root = ET.fromstring(xml.split("\n", 1)[1])

    assert "Acme &amp; Sons" in xml
    assert "Buyer &lt;Corp&gt;" in xml
    assert "5000.00" in xml
    assert root.tag.endswith("Invoice")


def test_etims_maps_line_items_and_validates_pins():
    service = EDIService()
    invoice = {
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

    payload = service.format_etims(invoice, pin="K123456789Z", tenant_id="tenant-1")

    assert payload["pinOfSeller"] == "K123456789Z"
    assert payload["tenantId"] == "tenant-1"
    assert payload["totalAmount"] == 116.0
    assert payload["lineItems"][0]["itemCode"] == "PROD01"
    assert payload["lineItems"][0]["unitPrice"] == 50.0
    with pytest.raises(EDIServiceError, match="PIN"):
        service.format_etims(invoice, pin="bad pin")


def test_create_message_validates_direction_partner_scope_and_payload():
    service = EDIService()
    partner = EDIPartner(
        id="partner-1",
        tenant_id="tenant-1",
        name="Partner",
        protocol="X12",
        direction="OUTBOUND",
        message_types=["850"],
        is_active=True,
    )
    session = _Session(partner)

    msg = service.create_message(
        "partner-1",
        "tenant-1",
        "850",
        "ST*850*0001~SE*2*0001~",
        direction="outbound",
        reference_id="PO-1",
        session=session,
    )

    assert msg.direction == "OUTBOUND"
    assert msg.message_type == "850"
    assert session.added == [msg]

    with pytest.raises(EDIServiceError, match="Invalid direction"):
        service.create_message("partner-1", "tenant-1", "850", "payload", direction="SIDEWAYS")
    with pytest.raises(EDIServiceError, match="was not found"):
        service.create_message("missing", "tenant-1", "850", "payload", session=session)
