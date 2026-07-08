"""EDI service: parse/format X12, EDIFACT, Peppol BIS3, eTIMS."""
from __future__ import annotations

import re
import uuid
import xml.etree.ElementTree as ET
from typing import Any

from pgappforge.plugins.erp.platform.edi.models import EDIPartner, EDIMessage

_CAC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
_CBC_NS = "urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
_EDI_MAX_PAYLOAD_LENGTH = 1_000_000
_MESSAGE_TYPE_RE = re.compile(r"^[A-Z0-9]{2,10}$")
_PARTNER_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,35}$")
_PIN_RE = re.compile(r"^[A-Z0-9]{6,15}$")
_SEGMENT_ID_RE = re.compile(r"^[A-Z0-9]{2,6}$")
_UBL_NS = "urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
_VALID_DIRECTIONS = {"INBOUND", "OUTBOUND"}
_X12_DELIMITERS = "*~\r\n"
_EDIFACT_DELIMITERS = "+'\r\n"


def _uuid() -> str:
    return str(uuid.uuid4())


class EDIServiceError(Exception):
    """Base error for EDI service input or format violations."""


class EDIService:
    # --- X12 ---
    def parse_x12(self, content: str, message_type: str) -> dict[str, Any]:
        message_type = self._validate_message_type(message_type)
        content = self._validate_payload_text(content, "content")
        segments = [s.strip() for s in content.split("~") if s.strip()]
        parsed: dict[str, Any] = {
            "message_type": message_type,
            "segments": {},
            "raw_lines": len(segments),
        }
        for seg in segments:
            elements = seg.split("*")
            seg_id = self._validate_segment_id(elements[0])
            parsed["segments"].setdefault(seg_id, []).append(elements[1:])
        self._enrich_x12_summary(parsed)
        return parsed

    def format_x12(self, data: dict[str, Any], message_type: str, partner_id: str) -> str:
        data = self._validate_mapping(data, "data")
        message_type = self._validate_message_type(message_type)
        partner_id = self._validate_partner_id(partner_id)
        body_segments = self._x12_body_segments(data, message_type)
        body_count = len(body_segments)
        isa_partner = partner_id[:15].ljust(15)
        gs_partner = partner_id[:15]
        isa = (
            "ISA*00*          *00*          *ZZ*PGAPPFORGE     "
            f"*ZZ*{isa_partner}*240101*1200*^*00501*000000001*0*P*:~"
        )
        gs = f"GS*{message_type}*PGAPPFORGE*{gs_partner}*20240101*1200*1*X*005010~"
        ge = f"GE*1*1~"
        iea = "IEA*1*000000001~"
        return "\n".join([isa, gs] + body_segments + [ge, iea])

    # --- EDIFACT ---
    def parse_edifact(self, content: str, message_type: str) -> dict[str, Any]:
        message_type = self._validate_message_type(message_type)
        content = self._validate_payload_text(content, "content")
        segments = [s.strip() for s in content.split("'") if s.strip()]
        parsed: dict[str, Any] = {
            "message_type": message_type,
            "segments": {},
            "raw_lines": len(segments),
        }
        for seg in segments:
            parts = seg.split("+")
            seg_id = self._validate_segment_id(parts[0])
            parsed["segments"].setdefault(seg_id, []).append(parts[1:])
        return parsed

    def format_edifact(self, data: dict[str, Any], message_type: str, partner_id: str) -> str:
        data = self._validate_mapping(data, "data")
        message_type = self._validate_message_type(message_type)
        partner_id = self._validate_partner_id(partner_id)
        body = self._format_segment_rows(
            data.get("segments", {}),
            element_sep="+",
            terminator="'",
            delimiters=_EDIFACT_DELIMITERS,
        )
        unh = f"UNH+1+{message_type}:D:96A:UN'"
        if not any(seg.startswith("UNH+") for seg in body):
            body.insert(0, unh)
        if not any(seg.startswith("UNT+") for seg in body):
            body.append(f"UNT+{len(body) + 1}+1'")
        unb = f"UNB+UNOA:1+PGAPPFORGE+{partner_id}+240101:1200+1'"
        unz = "UNZ+1+1'"
        return "\n".join([unb] + body + [unz])

    # --- Peppol BIS 3.0 ---
    def format_peppol_bis3(self, invoice: dict[str, Any]) -> str:
        invoice = self._validate_mapping(invoice, "invoice")
        inv_id = self._safe_xml_text(
            invoice.get("invoice_number") or invoice.get("id") or "INV-001",
            "invoice id",
            max_length=80,
        )
        issue_date = self._safe_xml_text(
            invoice.get("invoice_date") or invoice.get("date") or "2024-01-01",
            "invoice date",
            max_length=20,
        )
        currency = self._safe_xml_text(invoice.get("currency") or "KES", "currency", max_length=3)
        supplier = self._safe_xml_text(
            invoice.get("supplier_name") or "Supplier",
            "supplier_name",
            max_length=200,
        )
        customer = self._safe_xml_text(
            invoice.get("customer_name") or "Customer",
            "customer_name",
            max_length=200,
        )
        total = self._cents_to_amount(invoice.get("total_cents", 0), "total_cents")
        tax = self._cents_to_amount(invoice.get("tax_cents", 0), "tax_cents")

        ET.register_namespace("", _UBL_NS)
        ET.register_namespace("cbc", _CBC_NS)
        ET.register_namespace("cac", _CAC_NS)
        root = ET.Element(f"{{{_UBL_NS}}}Invoice")
        self._sub(root, _CBC_NS, "CustomizationID").text = (
            "urn:cen.eu:en16931:2017#compliant#"
            "urn:fdc:peppol.eu:2017:poacc:billing:3.0"
        )
        self._sub(root, _CBC_NS, "ProfileID").text = "urn:fdc:peppol.eu:2017:poacc:billing:01:1.0"
        self._sub(root, _CBC_NS, "ID").text = inv_id
        self._sub(root, _CBC_NS, "IssueDate").text = issue_date
        self._sub(root, _CBC_NS, "InvoiceTypeCode").text = "380"
        self._sub(root, _CBC_NS, "DocumentCurrencyCode").text = currency
        self._party(root, "AccountingSupplierParty", supplier)
        self._party(root, "AccountingCustomerParty", customer)
        tax_total = self._sub(root, _CAC_NS, "TaxTotal")
        self._amount(tax_total, "TaxAmount", tax, currency)
        legal_total = self._sub(root, _CAC_NS, "LegalMonetaryTotal")
        self._amount(legal_total, "PayableAmount", total, currency)
        body = ET.tostring(root, encoding="unicode")
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + body

    # --- eTIMS ---
    def format_etims(
        self,
        invoice: dict[str, Any],
        pin: str,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        invoice = self._validate_mapping(invoice, "invoice")
        seller_pin = self._validate_pin(pin, "pin")
        buyer_pin = invoice.get("buyer_pin", "")
        if buyer_pin:
            buyer_pin = self._validate_pin(buyer_pin, "buyer_pin")
        taxable_cents = invoice.get("taxable_cents", invoice.get("subtotal_cents", 0))
        payload = {
            "invoiceNumber": self._safe_xml_text(
                invoice.get("invoice_number") or invoice.get("id"),
                "invoice_number",
                max_length=80,
            ),
            "traderSystemInvoiceNumber": self._safe_xml_text(
                invoice.get("id") or invoice.get("invoice_number"),
                "id",
                max_length=80,
            ),
            "pinOfSeller": seller_pin,
            "pinOfBuyer": buyer_pin,
            "invoiceDate": self._safe_xml_text(
                invoice.get("invoice_date") or invoice.get("date"),
                "invoice_date",
                max_length=20,
            ),
            "totalTaxableAmount": self._cents_to_amount(taxable_cents, "taxable_cents"),
            "totalTaxAmount": self._cents_to_amount(invoice.get("tax_cents", 0), "tax_cents"),
            "totalAmount": self._cents_to_amount(invoice.get("total_cents", 0), "total_cents"),
            "lineItems": self._etims_line_items(invoice.get("line_items", [])),
        }
        if tenant_id is not None:
            payload["tenantId"] = self._require_text(tenant_id, "tenant_id", max_length=64)
        return payload

    def create_message(
        self,
        partner_id: str,
        tenant_id: str,
        message_type: str,
        payload: str,
        direction: str = "OUTBOUND",
        reference_id: str | None = None,
        session: Any = None,
    ) -> EDIMessage:
        partner_id = self._require_text(partner_id, "partner_id", max_length=36)
        tenant_id = self._require_text(tenant_id, "tenant_id", max_length=36)
        message_type = self._validate_message_type(message_type)
        payload = self._validate_payload_text(payload, "payload")
        direction = self._normalize_direction(direction)
        reference_id = (
            self._require_text(reference_id, "reference_id", max_length=100)
            if reference_id is not None
            else None
        )
        self._validate_partner_scope(partner_id, tenant_id, session)
        msg = EDIMessage(
            id=_uuid(),
            partner_id=partner_id,
            tenant_id=tenant_id,
            message_type=message_type,
            payload=payload,
            direction=direction,
            reference_id=reference_id,
        )
        if session is not None:
            session.add(msg)
        return msg

    def _x12_body_segments(self, data: dict[str, Any], message_type: str) -> list[str]:
        if data.get("segments"):
            body = self._format_segment_rows(
                data["segments"],
                element_sep="*",
                terminator="~",
                delimiters=_X12_DELIMITERS,
            )
        elif message_type == "810":
            body = [
                self._x12_segment("BIG", [
                    data.get("invoice_date") or data.get("date") or "20240101",
                    data.get("invoice_number") or data.get("id") or "INV-001",
                ]),
            ]
        elif message_type == "850":
            body = [
                self._x12_segment("BEG", [
                    "00",
                    "SA",
                    data.get("po_number") or data.get("id") or "PO-001",
                    "",
                    data.get("po_date") or data.get("date") or "20240101",
                ]),
            ]
        else:
            body = []
        if not any(seg.startswith("ST*") for seg in body):
            body.insert(0, self._x12_segment("ST", [message_type, "0001"]))
        if not any(seg.startswith("SE*") for seg in body):
            body.append(self._x12_segment("SE", [str(len(body) + 1), "0001"]))
        return body

    def _format_segment_rows(
        self,
        segments: Any,
        *,
        element_sep: str,
        terminator: str,
        delimiters: str,
    ) -> list[str]:
        if not isinstance(segments, dict):
            raise EDIServiceError("segments must be a mapping")
        output: list[str] = []
        for raw_seg_id, rows in segments.items():
            seg_id = self._validate_segment_id(raw_seg_id)
            if not isinstance(rows, list):
                raise EDIServiceError(f"segment {seg_id} rows must be a list")
            for row in rows:
                if not isinstance(row, (list, tuple)):
                    raise EDIServiceError(f"segment {seg_id} row must be a list")
                elements = [self._edi_element(value, delimiters) for value in row]
                output.append(seg_id + element_sep + element_sep.join(elements) + terminator)
        return output

    def _x12_segment(self, seg_id: str, elements: list[Any]) -> str:
        seg_id = self._validate_segment_id(seg_id)
        values = [self._edi_element(value, _X12_DELIMITERS) for value in elements]
        return seg_id + "*" + "*".join(values) + "~"

    def _enrich_x12_summary(self, parsed: dict[str, Any]) -> None:
        beg_rows = parsed["segments"].get("BEG") or []
        if beg_rows:
            row = beg_rows[0]
            if len(row) > 2:
                parsed["po_number"] = row[2]
            if len(row) > 4:
                parsed["po_date"] = row[4]
        big_rows = parsed["segments"].get("BIG") or []
        if big_rows:
            row = big_rows[0]
            if len(row) > 0:
                parsed["invoice_date"] = row[0]
            if len(row) > 1:
                parsed["invoice_number"] = row[1]

    @staticmethod
    def _validate_mapping(value: Any, field_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise EDIServiceError(f"{field_name} must be a JSON object")
        return value

    def _validate_message_type(self, value: Any) -> str:
        text = self._require_text(value, "message_type", max_length=10).upper()
        if not _MESSAGE_TYPE_RE.fullmatch(text):
            raise EDIServiceError("message_type must be alphanumeric")
        return text

    def _validate_partner_id(self, value: Any) -> str:
        text = self._require_text(value, "partner_id", max_length=35)
        if not _PARTNER_ID_RE.fullmatch(text):
            raise EDIServiceError("partner_id contains unsupported EDI characters")
        return text

    def _validate_segment_id(self, value: Any) -> str:
        text = self._require_text(value, "segment id", max_length=6).upper()
        if not _SEGMENT_ID_RE.fullmatch(text):
            raise EDIServiceError(f"Invalid EDI segment id {value!r}")
        return text

    @staticmethod
    def _edi_element(value: Any, delimiters: str) -> str:
        text = "" if value is None else str(value)
        if any(ch in text for ch in delimiters):
            raise EDIServiceError(f"EDI element contains reserved delimiter: {text!r}")
        return text

    def _validate_payload_text(self, value: Any, field_name: str) -> str:
        return self._require_text(
            value,
            field_name,
            max_length=_EDI_MAX_PAYLOAD_LENGTH,
        )

    @staticmethod
    def _require_text(value: Any, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise EDIServiceError(f"{field_name} must be a string")
        text = value.strip()
        if not text:
            raise EDIServiceError(f"{field_name} is required")
        if len(text) > max_length:
            raise EDIServiceError(f"{field_name} must be at most {max_length} characters")
        return text

    @staticmethod
    def _safe_xml_text(value: Any, field_name: str, max_length: int) -> str:
        text = "" if value is None else str(value).strip()
        if len(text) > max_length:
            raise EDIServiceError(f"{field_name} must be at most {max_length} characters")
        if "\x00" in text:
            raise EDIServiceError(f"{field_name} contains invalid XML characters")
        return text

    @staticmethod
    def _cents_to_amount(value: Any, field_name: str) -> float:
        if isinstance(value, bool):
            raise EDIServiceError(f"{field_name} must be numeric cents")
        try:
            cents = int(value or 0)
        except (TypeError, ValueError) as exc:
            raise EDIServiceError(f"{field_name} must be numeric cents") from exc
        if cents < 0:
            raise EDIServiceError(f"{field_name} must be non-negative")
        return round(cents / 100, 2)

    @staticmethod
    def _sub(parent: ET.Element, namespace: str, name: str) -> ET.Element:
        return ET.SubElement(parent, f"{{{namespace}}}{name}")

    def _party(self, root: ET.Element, role: str, name: str) -> None:
        party_role = self._sub(root, _CAC_NS, role)
        party = self._sub(party_role, _CAC_NS, "Party")
        party_name = self._sub(party, _CAC_NS, "PartyName")
        self._sub(party_name, _CBC_NS, "Name").text = name

    def _amount(self, parent: ET.Element, name: str, amount: float, currency: str) -> None:
        element = self._sub(parent, _CBC_NS, name)
        element.set("currencyID", currency)
        element.text = f"{amount:.2f}"

    def _validate_pin(self, value: Any, field_name: str) -> str:
        text = self._require_text(value, field_name, max_length=15).upper()
        if not _PIN_RE.fullmatch(text):
            raise EDIServiceError(f"{field_name} has invalid PIN format")
        return text

    def _etims_line_items(self, line_items: Any) -> list[dict[str, Any]]:
        if line_items is None:
            return []
        if not isinstance(line_items, list):
            raise EDIServiceError("line_items must be a list")
        output: list[dict[str, Any]] = []
        for index, item in enumerate(line_items):
            if not isinstance(item, dict):
                raise EDIServiceError(f"line_items[{index}] must be a JSON object")
            output.append(
                {
                    "itemCode": self._safe_xml_text(
                        item.get("product_code") or item.get("itemCode") or "",
                        f"line_items[{index}].product_code",
                        max_length=50,
                    ),
                    "itemName": self._safe_xml_text(
                        item.get("description") or item.get("itemName") or "",
                        f"line_items[{index}].description",
                        max_length=200,
                    ),
                    "quantity": item.get("quantity", 1),
                    "unitPrice": self._cents_to_amount(
                        item.get("unit_price_cents", item.get("unitPrice", 0)),
                        f"line_items[{index}].unit_price_cents",
                    ),
                    "taxRate": item.get("tax_rate_pct", item.get("taxRate", 0)),
                    "taxAmount": self._cents_to_amount(
                        item.get("tax_cents", item.get("taxAmount", 0)),
                        f"line_items[{index}].tax_cents",
                    ),
                    "totalAmount": self._cents_to_amount(
                        item.get("total_cents", item.get("totalAmount", 0)),
                        f"line_items[{index}].total_cents",
                    ),
                }
            )
        return output

    def _normalize_direction(self, value: Any) -> str:
        text = self._require_text(value, "direction", max_length=10).upper()
        if text not in _VALID_DIRECTIONS:
            allowed = ", ".join(sorted(_VALID_DIRECTIONS))
            raise EDIServiceError(f"Invalid direction {value!r}; expected one of {allowed}")
        return text

    def _validate_partner_scope(self, partner_id: str, tenant_id: str, session: Any) -> None:
        if session is None or not hasattr(session, "get"):
            return
        partner = session.get(EDIPartner, partner_id)
        if partner is None:
            raise EDIServiceError(f"EDIPartner {partner_id!r} was not found")
        if getattr(partner, "tenant_id", tenant_id) != tenant_id:
            raise EDIServiceError(f"EDIPartner {partner_id!r} does not belong to tenant")
        if getattr(partner, "is_active", True) is False:
            raise EDIServiceError(f"EDIPartner {partner_id!r} is inactive")


__all__ = ["EDIService", "EDIServiceError"]
