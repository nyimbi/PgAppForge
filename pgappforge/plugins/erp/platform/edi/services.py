"""EDI service — parse/format X12, EDIFACT, Peppol BIS3, eTIMS."""
from __future__ import annotations
import re
import uuid
from typing import Any

import sqlalchemy as sa

from pgappforge.plugins.erp.platform.edi.models import EDIPartner, EDIMessage


def _uuid() -> str:
	return str(uuid.uuid4())


class EDIService:
	# --- X12 ---
	def parse_x12(self, content: str, message_type: str) -> dict[str, Any]:
		segments = [s.strip() for s in content.split("~") if s.strip()]
		parsed: dict[str, Any] = {"message_type": message_type, "segments": {}}
		for seg in segments:
			elements = seg.split("*")
			seg_id = elements[0]
			parsed["segments"].setdefault(seg_id, []).append(elements[1:])
		return parsed

	def format_x12(self, data: dict[str, Any], message_type: str, partner_id: str) -> str:
		isa = f"ISA*00*          *00*          *ZZ*PGAPPFORGE     *ZZ*{partner_id[:15]:<15}*240101*1200*^*00501*000000001*0*P*:~"
		gs = f"GS*{message_type}*PGAPPFORGE*{partner_id[:15]}*20240101*1200*1*X*005010~"
		ge = "GE*1*1~"
		iea = "IEA*1*000000001~"
		body_segs = []
		for seg_id, rows in data.get("segments", {}).items():
			for row in rows:
				body_segs.append(seg_id + "*" + "*".join(str(e) for e in row) + "~")
		return "\n".join([isa, gs] + body_segs + [ge, iea])

	# --- EDIFACT ---
	def parse_edifact(self, content: str, message_type: str) -> dict[str, Any]:
		segments = [s.strip() for s in content.split("'") if s.strip()]
		parsed: dict[str, Any] = {"message_type": message_type, "segments": {}}
		for seg in segments:
			parts = seg.split("+")
			seg_id = parts[0]
			parsed["segments"].setdefault(seg_id, []).append(parts[1:])
		return parsed

	def format_edifact(self, data: dict[str, Any], message_type: str, partner_id: str) -> str:
		unb = f"UNB+UNOA:1+PGAPPFORGE+{partner_id}+240101:1200+1'"
		unh = f"UNH+1+{message_type}:D:96A:UN'"
		uny = "UNT+2+1'"
		unz = "UNZ+1+1'"
		body = []
		for seg_id, rows in data.get("segments", {}).items():
			for row in rows:
				body.append(seg_id + "+" + "+".join(str(e) for e in row) + "'")
		return "\n".join([unb, unh] + body + [uny, unz])

	# --- Peppol BIS 3.0 ---
	def format_peppol_bis3(self, invoice: dict[str, Any]) -> str:
		inv_id = invoice.get("id", "INV-001")
		date = invoice.get("date", "2024-01-01")
		# total_cents / 1000 gives currency value (e.g. 100000 → 100.00)
		total = invoice.get("total_cents", 0) / 1000
		tax = invoice.get("tax_cents", 0) / 1000
		supplier = invoice.get("supplier_name", "Supplier")
		customer = invoice.get("customer_name", "Customer")
		return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0</cbc:CustomizationID>
  <cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>
  <cbc:ID>{inv_id}</cbc:ID>
  <cbc:IssueDate>{date}</cbc:IssueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>KES</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty><cac:Party><cac:PartyName><cbc:Name>{supplier}</cbc:Name></cac:PartyName></cac:Party></cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty><cac:Party><cac:PartyName><cbc:Name>{customer}</cbc:Name></cac:PartyName></cac:Party></cac:AccountingCustomerParty>
  <cac:TaxTotal><cbc:TaxAmount currencyID="KES">{tax:.2f}</cbc:TaxAmount></cac:TaxTotal>
  <cac:LegalMonetaryTotal><cbc:PayableAmount currencyID="KES">{total:.2f}</cbc:PayableAmount></cac:LegalMonetaryTotal>
</Invoice>"""

	# --- eTIMS ---
	def format_etims(self, invoice: dict[str, Any], pin: str) -> dict[str, Any]:
		return {
			"invoiceNumber": invoice.get("invoice_number"),
			"traderSystemInvoiceNumber": invoice.get("id"),
			"pinOfBuyer": invoice.get("buyer_pin", ""),
			"invoiceDate": invoice.get("date"),
			"totalTaxableAmount": (invoice.get("taxable_cents", 0)) / 100,
			"totalTaxAmount": (invoice.get("tax_cents", 0)) / 100,
			"totalAmount": (invoice.get("total_cents", 0)) / 100,
			"lineItems": invoice.get("line_items", []),
		}

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
		msg = EDIMessage(
			id=_uuid(),
			partner_id=partner_id,
			tenant_id=tenant_id,
			message_type=message_type,
			payload=payload,
			direction=direction,
			reference_id=reference_id,
		)
		if session:
			session.add(msg)
		return msg


__all__ = ["EDIService"]
