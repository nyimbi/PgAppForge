"""
pgappforge/plugins/connectors/zra/client.py

ZRA Smart Invoice — Zambia Revenue Authority mandatory e-invoicing system.

Mandatory for all VAT-registered taxpayers in Zambia (rollout from 2023).
Similar in design to Kenya's eTIMS: every invoice must be submitted to ZRA
before issuance.  ZRA returns a receipt number and digital signature.

Zambia VAT rates:
  16 %   Standard rate (most goods and services)
   0 %   Zero-rated (exports, selected basic goods)
   Exempt (financial services, education, health, etc.)

Penalties for non-compliance: as set out in the VAT Act Cap 331.

Config (Flask app.config):
  ZRA_TIN           Taxpayer Identification Number (TPIN), e.g. "1000000001"
  ZRA_BHFID         Branch Identifier (default "000")
  ZRA_DEVICE_SERIAL Control unit / fiscal device serial number
  ZRA_BASE_URL      API base URL (sandbox or production)
  ZRA_TIMEOUT       HTTP timeout seconds (default 30)
  ZRA_ENABLED       Set False to skip in dev (default True)

Sandbox:
  ZRA provides a test environment — use their test TPIN and device serial
  from the ZRA Smart Invoice developer documentation.

CLI test helper:
  python -m pgappforge.plugins.connectors.zra.client --test
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

log = logging.getLogger(__name__)

_SANDBOX_BASE_URL = "https://sandbox.zra.org.zm/smartinvoice"
_PROD_BASE_URL = "https://smartinvoice.zra.org.zm"

_ZAMBIA_VAT_STANDARD = Decimal("0.16")   # 16 %
_ZAMBIA_VAT_ZERO = Decimal("0.00")       # 0 % (zero-rated / exempt)


class ZRAError(Exception):
	"""Base error for all ZRA Smart Invoice client errors."""


class ZRASubmissionError(ZRAError):
	"""ZRA API returned an error or the HTTP request failed."""


class ZRAClient:
	"""ZRA Smart Invoice API client.

	Submits invoices to ZRA and returns the receipt number and fiscal signature
	that must appear on all issued tax invoices.

	Example::

		client = ZRAClient.from_config()
		result = client.submit_invoice(
		    invoice_number="INV-2024-001",
		    customer_tpin="1000000002",
		    customer_name="Acme Zambia Ltd",
		    items=[
		        {
		            "description": "Consulting Services",
		            "quantity": 1,
		            "unit_price": 11600.0,   # ZMW, VAT-inclusive
		            "vat_rate_pct": 16,
		        },
		    ],
		)
		if result["success"]:
		    print("Receipt:", result["receipt_number"])
		    print("Signature:", result["signature"])
	"""

	def __init__(
		self,
		tin: str = "",
		bhfid: str = "000",
		device_serial: str = "",
		base_url: str = _PROD_BASE_URL,
		timeout: int = 30,
		enabled: bool = True,
	) -> None:
		self.tin = tin
		self.bhfid = bhfid
		self.device_serial = device_serial
		self.base_url = base_url.rstrip("/")
		self.timeout = timeout
		self.enabled = enabled

	@classmethod
	def from_config(cls) -> "ZRAClient":
		"""Construct from Flask app.config."""
		try:
			from flask import current_app
			cfg = current_app.config
			return cls(
				tin=cfg.get("ZRA_TIN", ""),
				bhfid=cfg.get("ZRA_BHFID", "000"),
				device_serial=cfg.get("ZRA_DEVICE_SERIAL", ""),
				base_url=cfg.get("ZRA_BASE_URL", _PROD_BASE_URL),
				timeout=int(cfg.get("ZRA_TIMEOUT", 30)),
				enabled=cfg.get("ZRA_ENABLED", True),
			)
		except RuntimeError:
			return cls()

	@classmethod
	def sandbox(cls, tin: str = "1000000001") -> "ZRAClient":
		"""Convenience factory for ZRA sandbox environment."""
		return cls(tin=tin, base_url=_SANDBOX_BASE_URL, enabled=True)

	# ------------------------------------------------------------------ #
	# Public API
	# ------------------------------------------------------------------ #

	def submit_invoice(
		self,
		invoice_number: str,
		customer_tpin: str,
		customer_name: str,
		items: list[dict[str, Any]],
		invoice_date: str | None = None,
		invoice_type: str = "ORIGINAL",
	) -> dict[str, Any]:
		"""Submit an invoice to ZRA Smart Invoice.

		Args:
			invoice_number:  Your internal invoice number (unique per branch).
			customer_tpin:   ZRA TPIN of the buyer.  Use "0000000000" for
			                 non-registered individuals.
			customer_name:   Buyer name (truncated to 100 chars).
			items:           List of line item dicts.  Each accepts:
			                   description    str
			                   quantity       float
			                   unit_price     float  (ZMW, VAT-inclusive)
			                   vat_rate_pct   float  (0 | 16, default 16)
			                   item_code      str    (optional)
			                   class_code     str    (ZRA classification, optional)
			invoice_date:    ISO date string (YYYY-MM-DD).  Defaults to today UTC.
			invoice_type:    "ORIGINAL" | "CREDIT" | "DEBIT"

		Returns:
			{
			  success: bool,
			  receipt_number: str,
			  signature: str,
			  error: str | None,
			}
		"""
		if not self.enabled:
			log.debug("ZRA Smart Invoice disabled — skipping %s", invoice_number)
			return {
				"success": True,
				"receipt_number": "",
				"signature": "",
				"error": None,
				"skipped": True,
			}

		if not self.tin:
			return {"success": False, "error": "ZRA_TIN not configured", "receipt_number": "", "signature": ""}

		if not items:
			return {"success": False, "error": "Invoice must have at least one line item", "receipt_number": "", "signature": ""}

		if not invoice_date:
			invoice_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

		_type_map = {"ORIGINAL": "1", "CREDIT": "3", "DEBIT": "4"}
		invoice_type_code = _type_map.get(invoice_type.upper(), "1")

		payload: dict[str, Any] = {
			"tpin": self.tin,
			"bhfId": self.bhfid,
			"orgInvcNo": str(invoice_number),
			"custTpin": customer_tpin,
			"custNm": customer_name[:100],
			"salesTyCd": "N",           # N = Normal sale
			"rcptTyCd": invoice_type_code,
			"salesSttsCd": "02",         # 02 = Approved
			"cfmDt": invoice_date.replace("-", ""),
			"salesDt": invoice_date.replace("-", ""),
			"itemList": [],
		}

		total_vatable = Decimal("0")
		total_vat = Decimal("0")
		total_exempt = Decimal("0")
		total_amount = Decimal("0")

		for i, item in enumerate(items):
			unit_price = Decimal(str(item.get("unit_price", 0)))
			quantity = Decimal(str(item.get("quantity", 1)))
			vat_rate_pct = Decimal(str(item.get("vat_rate_pct", 16)))
			vat_rate = vat_rate_pct / 100

			line_total = (unit_price * quantity).quantize(Decimal("0.01"), ROUND_HALF_UP)

			if vat_rate > 0:
				# unit_price is VAT-inclusive: extract VAT
				vat_amount = (line_total * vat_rate / (1 + vat_rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
				vatable_amount = line_total - vat_amount
				tax_type_cd = "A"   # Standard-rated
				total_vatable += vatable_amount
				total_vat += vat_amount
			else:
				vat_amount = Decimal("0")
				vatable_amount = Decimal("0")
				tax_type_cd = "E"   # Exempt / zero-rated
				total_exempt += line_total

			total_amount += line_total

			payload["itemList"].append({
				"itemSeq": i + 1,
				"itemCd": item.get("item_code", f"ITM{i+1:03d}"),
				"itemClsCd": item.get("class_code", "5020230602"),
				"itemNm": str(item.get("description", ""))[:100],
				"qty": float(quantity),
				"qtyUnitCd": "U",
				"prc": float(unit_price),
				"splyAmt": float(line_total),
				"dcRt": 0,
				"dcAmt": 0,
				"taxblAmt": float(vatable_amount),
				"taxTyCd": tax_type_cd,
				"taxAmt": float(vat_amount),
				"totAmt": float(line_total),
			})

		payload["taxblAmtA"] = float(total_vatable)
		payload["taxRtA"] = 16.0
		payload["taxAmtA"] = float(total_vat)
		payload["taxblAmtE"] = float(total_exempt)
		payload["totTaxblAmt"] = float(total_vatable + total_exempt)
		payload["totTaxAmt"] = float(total_vat)
		payload["totAmt"] = float(total_amount)

		try:
			result = self._post("/api/method/saveSales", payload)
			data = result.get("data", {})
			return {
				"success": True,
				"receipt_number": data.get("rcptNo", ""),
				"signature": data.get("rcptSign", ""),
				"error": None,
			}
		except ZRASubmissionError as exc:
			log.warning("ZRA submission failed for %s: %s", invoice_number, exc)
			return {
				"success": False,
				"receipt_number": "",
				"signature": "",
				"error": str(exc),
			}

	def get_item_classification_list(self) -> list[dict[str, Any]]:
		"""Get the list of valid ZRA item classification codes.

		Returns:
			List of classification code dicts from ZRA.
		"""
		try:
			result = self._post("/api/method/selectItemClsList", {
				"tpin": self.tin or "1000000001",
				"bhfId": self.bhfid,
			})
			data = result.get("data", {})
			return data.get("itemClsList", []) if isinstance(data, dict) else []
		except ZRASubmissionError as exc:
			log.warning("get_item_classification_list failed: %s", exc)
			return []

	def ping(self) -> bool:
		"""Check connectivity to the ZRA Smart Invoice API.

		Returns:
			True if reachable, False otherwise.
		"""
		try:
			self._post("/api/method/selectInitOsdcInfo", {
				"tpin": self.tin or "1000000001",
				"bhfId": self.bhfid,
			})
			return True
		except ZRASubmissionError:
			return False

	# ------------------------------------------------------------------ #
	# Internal
	# ------------------------------------------------------------------ #

	def _post(self, path: str, payload: dict) -> dict:
		url = f"{self.base_url}{path}"
		data = json.dumps(payload).encode()
		req = urllib.request.Request(
			url,
			data=data,
			method="POST",
			headers={
				"Content-Type": "application/json",
				"tpin": self.tin,
				"bhfId": self.bhfid,
				"cmcKey": self.device_serial,
			},
		)
		try:
			with urllib.request.urlopen(req, timeout=self.timeout) as resp:
				body = resp.read()
				result = json.loads(body)
				if result.get("resultCd") not in ("000", 0, "0"):
					raise ZRASubmissionError(
						f"ZRA error {result.get('resultCd')}: {result.get('resultMsg', '')}"
					)
				return result
		except urllib.error.HTTPError as exc:
			body_text = exc.read().decode(errors="replace")[:300]
			raise ZRASubmissionError(f"ZRA HTTP {exc.code}: {body_text}") from exc
		except ZRASubmissionError:
			raise
		except Exception as exc:
			raise ZRASubmissionError(f"ZRA request failed: {exc}") from exc


# ------------------------------------------------------------------ #
# CLI test helper
# ------------------------------------------------------------------ #

def _cli_test() -> None:
	"""Sandbox smoke test.
	Run: python -m pgappforge.plugins.connectors.zra.client --test
	"""
	logging.basicConfig(level=logging.INFO)
	client = ZRAClient.sandbox()
	print(f"ZRA sandbox client: TIN={client.tin}  URL={client.base_url}")

	result = client.submit_invoice(
		invoice_number="TEST-001",
		customer_tpin="0000000000",
		customer_name="Walk-in Customer",
		items=[
			{
				"description": "Consulting Service",
				"quantity": 1,
				"unit_price": 11600.0,  # ZMW 10 000 + 16 % VAT
				"vat_rate_pct": 16,
			},
			{
				"description": "Exempt Medical Supply",
				"quantity": 2,
				"unit_price": 5000.0,
				"vat_rate_pct": 0,
			},
		],
	)
	import pprint
	pprint.pprint(result)


if __name__ == "__main__":
	import sys
	if "--test" in sys.argv:
		_cli_test()


__all__ = ["ZRAClient", "ZRAError", "ZRASubmissionError"]
