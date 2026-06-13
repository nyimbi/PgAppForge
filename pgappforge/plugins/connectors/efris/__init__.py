"""
pgappforge/plugins/connectors/efris/__init__.py

URA EFRIS connector — Uganda mandatory e-fiscal receipts and invoices.

Quick start::

    from pgappforge.plugins.connectors.efris import EFRISClient

    client = EFRISClient.from_config()    # reads EFRIS_* from Flask config
    # OR
    client = EFRISClient.sandbox()        # URA sandbox environment

    result = client.submit_invoice(
        invoice_number="INV-001",
        customer_tin="0000000000",
        customer_name="Walk-in Customer",
        items=[{"description": "Goods", "quantity": 1,
                "unit_price_ugx": 118000, "vat_rate_pct": 18}],
    )

Flask config keys:
    EFRIS_TIN            Uganda TIN (mandatory)
    EFRIS_DEVICE_ID      Fiscal device ID from URA portal
    EFRIS_BASE_URL       API base URL
    EFRIS_TIMEOUT        HTTP timeout seconds (default 30)
    EFRIS_ENABLED        Set False to skip in dev (default True)
"""
from pgappforge.plugins.connectors.efris.client import (
	EFRISClient,
	EFRISError,
	EFRISSubmissionError,
)

__all__ = ["EFRISClient", "EFRISError", "EFRISSubmissionError"]
