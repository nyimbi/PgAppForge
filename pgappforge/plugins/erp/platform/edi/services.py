"""
pgappforge/plugins/erp/platform/edi/services.py

EDIService — trading partner management, message formatting, and dispatch.

Supported formats:
  X12        — parse_x12 (850/810/856/997), format_x12 (850/810)
  PEPPOL     — format_peppol_bis3 (UBL 2.1 BIS 3.0)
  ETIMS      — format_etims (KRA eTIMS JSON v3)

Transport dispatch currently supports HTTPS; AS2/SFTP stubs in place.

BPM actions:
  platform.edi.send_invoice     — Send invoice via EDI to trading partner
  platform.edi.format_etims     — Format invoice for KE eTIMS submission
"""
from __future__ import annotations

import datetime
import logging
import re
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
		log.debug("EDIService: emit suppressed: %s", exc)


# ---------------------------------------------------------------------------
# EDIService
# ---------------------------------------------------------------------------

class EDIService:
	"""Stateless EDI service — partner registration, parse, format, dispatch."""

	# ------------------------------------------------------------------
	# register_partner
	# ------------------------------------------------------------------

	def register_partner(
		self,
		name: str,
		code: str,
		protocol: str,
		tenant_id: str,
		session: Any,
		*,
		message_types: list[str] | None = None,
		connectivity: dict[str, Any] | None = None,
	) -> Any:
		"""Create or update a trading partner record and emit registered event."""
		from pgappforge.plugins.erp.platform.edi.models import EDIPartner
		from pgappforge.plugins.erp.platform.edi.events import EDIPartnerRegisteredEvent

		existing = session.execute(
			select(EDIPartner).where(
				EDIPartner.tenant_id == tenant_id,
				EDIPartner.code == code,
			)
		).scalar_one_or_none()

		if existing is not None:
			existing.name = name
			existing.protocol = protocol
			if message_types is not None:
				existing.message_types = message_types
			if connectivity is not None:
				existing.connectivity = connectivity
			partner = existing
		else:
			partner = EDIPartner(
				tenant_id=tenant_id,
				name=name,
				code=code,
				protocol=protocol,
				message_types=message_types or [],
				connectivity=connectivity or {},
				is_active=True,
			)
			session.add(partner)

		session.flush()

		_emit(
			EDIPartnerRegisteredEvent(
				aggregate_id=partner.id,
				aggregate_type="EDIPartner",
				tenant_id=tenant_id,
				partner_id=partner.id,
				name=name,
				protocol=protocol,
			),
			session,
		)
		return partner

	# ------------------------------------------------------------------
	# parse_x12
	# ------------------------------------------------------------------

	def parse_x12(self, content: str, message_type: str) -> dict[str, Any]:
		"""Parse X12 EDI message.

		Supported: 850 (PO), 810 (Invoice), 856 (ASN), 997 (Ack).
		X12 structure: ISA*...*~GS*...*~ST*850*...~BEG*00*SA*PO-12345*...*~

		Returns dict with {transaction_type, sender_id, receiver_id, date,
		segments: {tag: [[field, ...], ...]}, raw_lines}.
		"""
		segments = [s.strip() for s in re.split(r"[~\n]", content) if s.strip()]
		result: dict[str, Any] = {
			"message_type": message_type,
			"segments": {},
			"raw_lines": len(segments),
		}
		for seg in segments:
			parts = seg.split("*")
			tag = parts[0]
			result["segments"].setdefault(tag, []).append(parts[1:])

		# ISA header fields
		isa = result["segments"].get("ISA", [[]])[0]
		result["sender_id"] = isa[5].strip() if len(isa) > 5 else ""
		result["receiver_id"] = isa[7].strip() if len(isa) > 7 else ""
		result["date"] = isa[8] if len(isa) > 8 else ""

		# Extract key fields by message type
		if message_type == "850":  # Purchase Order
			beg = result["segments"].get("BEG", [[]])[0]
			result["po_number"] = beg[2] if len(beg) > 2 else ""
			result["po_date"] = beg[4] if len(beg) > 4 else ""
		elif message_type == "810":  # Invoice
			big = result["segments"].get("BIG", [[]])[0]
			result["invoice_date"] = big[0] if big else ""
			result["invoice_number"] = big[1] if len(big) > 1 else ""
		elif message_type == "856":  # ASN
			bsn = result["segments"].get("BSN", [[]])[0]
			result["shipment_id"] = bsn[1] if len(bsn) > 1 else ""
			result["shipment_date"] = bsn[2] if len(bsn) > 2 else ""
		elif message_type == "997":  # Functional Ack
			ak1 = result["segments"].get("AK1", [[]])[0]
			result["functional_id"] = ak1[0] if ak1 else ""
			ak9 = result["segments"].get("AK9", [[]])[0]
			result["ack_code"] = ak9[0] if ak9 else ""

		return result

	# ------------------------------------------------------------------
	# format_x12
	# ------------------------------------------------------------------

	def format_x12(
		self,
		data_dict: dict[str, Any],
		message_type: str,
		partner_code: str,
	) -> str:
		"""Generate X12 envelope. Supports: 850 (PO), 810 (Invoice outbound)."""
		now = datetime.datetime.now()
		isa_date = now.strftime("%y%m%d")
		isa_time = now.strftime("%H%M")
		control = f"{hash(str(data_dict)) % 100000000:08d}"
		lines = [
			f"ISA*00*          *00*          *ZZ*PGAPPFORGE     "
			f"*ZZ*{partner_code[:15]:<15}*{isa_date}*{isa_time}*^*00501*{control}*0*P*:~",
			f"GS*{message_type}*PGAPPFORGE*{partner_code}"
			f"*{now.strftime('%Y%m%d')}*{isa_time}*1*X*005010~",
			f"ST*{message_type}*0001~",
		]
		if message_type == "810":
			inv = data_dict
			lines += [
				f"BIG*{inv.get('invoice_date','')}*{inv.get('invoice_number','')}***BI~",
				f"CUR*SE*{inv.get('currency','USD')}~",
				f"TDS*{inv.get('total_cents', 0) // 100}~",
			]
		elif message_type == "850":
			po = data_dict
			lines += [
				f"BEG*00*SA*{po.get('po_number','')}**{po.get('po_date','')}~",
				f"CUR*BY*{po.get('currency','USD')}~",
			]
		segment_count = len(lines) - 1  # exclude ISA
		lines += [
			f"SE*{segment_count}*0001~",
			"GE*1*1~",
			f"IEA*1*{control}~",
		]
		return "\n".join(lines)

	# ------------------------------------------------------------------
	# format_peppol_bis3
	# ------------------------------------------------------------------

	def format_peppol_bis3(self, invoice_dict: dict[str, Any]) -> str:
		"""Generate Peppol BIS 3.0 UBL 2.1 XML for PINT (Pan-European Invoice Network)."""
		inv = invoice_dict
		payable = f"{inv.get('total_cents', 0) / 100:.2f}"
		currency = inv.get("currency", "KES")
		return f"""<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"
         xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2"
         xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">
  <cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:fdc:peppol.eu:2017:poacc:billing:3.0</cbc:CustomizationID>
  <cbc:ID>{inv.get('invoice_number', 'INV-001')}</cbc:ID>
  <cbc:IssueDate>{inv.get('invoice_date', '2024-01-01')}</cbc:IssueDate>
  <cbc:InvoiceTypeCode>380</cbc:InvoiceTypeCode>
  <cbc:DocumentCurrencyCode>{currency}</cbc:DocumentCurrencyCode>
  <cac:AccountingSupplierParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>{inv.get('supplier_name', '')}</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingSupplierParty>
  <cac:AccountingCustomerParty>
    <cac:Party>
      <cac:PartyName><cbc:Name>{inv.get('customer_name', '')}</cbc:Name></cac:PartyName>
    </cac:Party>
  </cac:AccountingCustomerParty>
  <cac:LegalMonetaryTotal>
    <cbc:PayableAmount currencyID="{currency}">{payable}</cbc:PayableAmount>
  </cac:LegalMonetaryTotal>
</Invoice>"""

	# ------------------------------------------------------------------
	# format_etims
	# ------------------------------------------------------------------

	def format_etims(
		self,
		invoice_dict: dict[str, Any],
		pin: str,
		tenant_id: str,
	) -> dict[str, Any]:
		"""Generate KE eTIMS JSON payload per KRA API v3 specification."""
		inv = invoice_dict
		return {
			"invoiceNumber": inv.get("invoice_number", ""),
			"traderSystemInvoiceNumber": inv.get("invoice_number", ""),
			"relevantTaxInvoiceNumber": "",
			"pinOfBuyer": inv.get("buyer_pin", ""),
			"vatAccountNo": "",
			"invoiceDate": inv.get("invoice_date", ""),
			"totalTaxableAmount": inv.get("subtotal_cents", 0) / 100,
			"totalTaxAmount": inv.get("tax_cents", 0) / 100,
			"totalAmount": inv.get("total_cents", 0) / 100,
			"lineItems": [
				{
					"itemCode": li.get("product_code", ""),
					"itemName": li.get("description", ""),
					"quantity": li.get("quantity", 1),
					"unitPrice": li.get("unit_price_cents", 0) / 100,
					"taxRate": li.get("tax_rate_pct", 16),
					"taxAmount": li.get("tax_cents", 0) / 100,
					"totalAmount": li.get("total_cents", 0) / 100,
				}
				for li in inv.get("line_items", [])
			],
		}

	# ------------------------------------------------------------------
	# create_message
	# ------------------------------------------------------------------

	def create_message(
		self,
		partner_id: str,
		message_type: str,
		direction: str,
		payload: str,
		tenant_id: str,
		session: Any,
	) -> Any:
		"""Persist an EDI message and emit received/created event."""
		from pgappforge.plugins.erp.platform.edi.models import EDIMessage
		from pgappforge.plugins.erp.platform.edi.events import EDIMessageReceivedEvent

		msg = EDIMessage(
			tenant_id=tenant_id,
			partner_id=partner_id,
			message_type=message_type,
			direction=direction,
			payload=payload,
			status="PENDING",
		)
		session.add(msg)
		session.flush()

		if direction == "INBOUND":
			_emit(
				EDIMessageReceivedEvent(
					aggregate_id=msg.id,
					aggregate_type="EDIMessage",
					tenant_id=tenant_id,
					message_id=msg.id,
					partner_id=partner_id,
					message_type=message_type,
					status="PENDING",
				),
				session,
			)
		return msg

	# ------------------------------------------------------------------
	# dispatch
	# ------------------------------------------------------------------

	def dispatch(self, message_id: str, session: Any) -> dict[str, Any]:
		"""Route outbound message to partner's configured transport and emit sent event.

		Transport routing:
		  HTTPS  — urllib.request POST (implemented)
		  AS2    — stub (not yet implemented)
		  SFTP   — stub (not yet implemented)
		"""
		import urllib.request
		import json as _json

		from pgappforge.plugins.erp.platform.edi.models import EDIMessage, EDIPartner
		from pgappforge.plugins.erp.platform.edi.events import EDIMessageSentEvent

		msg = session.execute(
			select(EDIMessage).where(EDIMessage.id == message_id)
		).scalar_one_or_none()
		if msg is None:
			raise ValueError(f"EDIMessage {message_id!r} not found")

		partner = session.execute(
			select(EDIPartner).where(EDIPartner.id == msg.partner_id)
		).scalar_one_or_none()
		if partner is None:
			raise ValueError(f"EDIPartner {msg.partner_id!r} not found")

		connectivity: dict[str, Any] = partner.connectivity or {}
		transport = (connectivity.get("transport") or "HTTPS").upper()
		endpoint = connectivity.get("endpoint", "")

		result: dict[str, Any] = {"transport": transport, "endpoint": endpoint}

		try:
			if transport == "HTTPS" and endpoint:
				payload_bytes = msg.payload.encode("utf-8")
				req = urllib.request.Request(
					endpoint,
					data=payload_bytes,
					method="POST",
					headers={"Content-Type": "application/xml"},
				)
				auth = connectivity.get("auth", {})
				if auth.get("token"):
					req.add_header("Authorization", f"Bearer {auth['token']}")
				with urllib.request.urlopen(req, timeout=30) as resp:
					result["http_status"] = resp.status
					result["response"] = resp.read(512).decode("utf-8", errors="replace")
			elif transport in ("AS2", "SFTP"):
				log.info("dispatch: transport %s stub — message %s queued", transport, message_id)
				result["note"] = f"{transport} transport not yet implemented; message queued"
			else:
				log.warning("dispatch: unknown transport %r for message %s", transport, message_id)
				result["note"] = f"transport {transport!r} unknown; skipped"

			msg.status = "SENT"
		except Exception as exc:
			msg.status = "ERROR"
			msg.error_log = str(exc)
			result["error"] = str(exc)
			log.warning("dispatch failed for message %s: %s", message_id, exc)

		session.flush()

		_emit(
			EDIMessageSentEvent(
				aggregate_id=msg.id,
				aggregate_type="EDIMessage",
				tenant_id=msg.tenant_id,
				message_id=msg.id,
				partner_id=msg.partner_id,
				message_type=msg.message_type,
				protocol=partner.protocol,
			),
			session,
		)
		return result


# ---------------------------------------------------------------------------
# BPM registrations
# ---------------------------------------------------------------------------

@BPMActionRegistry.register(
	"platform.edi.send_invoice",
	"Send invoice via EDI to trading partner",
)
def _bpm_edi_send_invoice(
	record_ctx: dict,
	session: Any,
	partner_id: str = "",
	message_type: str = "810",
	payload: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.platform.edi.services import EDIService
	except ImportError:
		return {"status": "error", "message": "platform.edi plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		svc = EDIService()
		msg = svc.create_message(
			partner_id=partner_id,
			message_type=message_type,
			direction="OUTBOUND",
			payload=payload,
			tenant_id=tenant_id,
			session=session,
		)
		result = svc.dispatch(msg.id, session)
		return {"status": "ok", "message_id": msg.id, **result}
	except Exception as exc:
		log.warning("bpm platform.edi.send_invoice failed: %s", exc)
		return {"status": "error", "message": str(exc)}


@BPMActionRegistry.register(
	"platform.edi.format_etims",
	"Format invoice for KE eTIMS submission",
)
def _bpm_edi_format_etims(
	record_ctx: dict,
	session: Any,
	invoice_dict: dict | None = None,
	pin: str = "",
	**kw: Any,
) -> dict:
	try:
		from pgappforge.plugins.erp.platform.edi.services import EDIService
	except ImportError:
		return {"status": "error", "message": "platform.edi plugin not installed"}
	tenant_id = record_ctx.get("tenant_id", "")
	try:
		payload = EDIService().format_etims(invoice_dict or {}, pin, tenant_id)
		return {"status": "ok", "payload": payload}
	except Exception as exc:
		log.warning("bpm platform.edi.format_etims failed: %s", exc)
		return {"status": "error", "message": str(exc)}


__all__ = ["EDIService"]
