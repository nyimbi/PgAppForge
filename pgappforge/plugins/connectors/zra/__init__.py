"""
pgappforge/plugins/connectors/zra/__init__.py

ZRA Smart Invoice connector — Zambia Revenue Authority mandatory e-invoicing.

Zambia VAT rates: 16 % standard, 0 % zero-rated / exempt.

Quick start::

	from pgappforge.plugins.connectors.zra import ZRAClient

	client = ZRAClient.from_config()       # reads ZRA_* from Flask config
	# OR
	client = ZRAClient.sandbox()           # ZRA sandbox environment

	result = client.submit_invoice(
	    invoice_number="INV-001",
	    customer_tpin="0000000000",
	    customer_name="Walk-in Customer",
	    items=[
	        {"description": "Service", "quantity": 1,
	         "unit_price": 11600.0, "vat_rate_pct": 16},
	    ],
	)
	if result["success"]:
	    print("Receipt:", result["receipt_number"])

Flask config keys:
	ZRA_TIN           Taxpayer Identification Number / TPIN (mandatory)
	ZRA_BHFID         Branch identifier (default "000")
	ZRA_DEVICE_SERIAL Control unit serial number
	ZRA_BASE_URL      API base URL (sandbox or production)
	ZRA_TIMEOUT       HTTP timeout seconds (default 30)
	ZRA_ENABLED       Set False to skip in dev (default True)
"""
from pgappforge.plugins.connectors.zra.client import (
	ZRAClient,
	ZRAError,
	ZRASubmissionError,
)

__all__ = ["ZRAClient", "ZRAError", "ZRASubmissionError"]
