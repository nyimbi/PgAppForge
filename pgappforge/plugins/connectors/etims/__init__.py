"""
pgappforge/plugins/connectors/etims/__init__.py

KRA eTIMS connector — Kenya mandatory electronic tax invoice submission.

Quick start::

    from pgappforge.plugins.connectors.etims import ETIMSClient

    client = ETIMSClient.from_config()       # reads ETIMS_* from Flask config
    # OR
    client = ETIMSClient.sandbox()           # KRA sandbox environment

    result = client.submit_invoice(
        invoice_number="INV-001",
        customer_pin="A000000000Z",
        customer_name="Acme Ltd",
        items=[{"description": "Service", "quantity": 1,
                "unit_price_kes": 11600, "vat_rate_pct": 16}],
    )

Flask config keys:
    ETIMS_PIN            KRA PIN (mandatory)
    ETIMS_BRANCH_ID      Branch ID (default "00")
    ETIMS_BASE_URL       API base URL
    ETIMS_DEVICE_SERIAL  Control unit serial
    ETIMS_TIMEOUT        HTTP timeout seconds (default 30)
    ETIMS_ENABLED        Set False to skip submission in dev (default True)
"""
from pgappforge.plugins.connectors.etims.client import (
	ETIMSClient,
	ETIMSError,
	ETIMSSubmissionError,
	ETIMSValidationError,
)

__all__ = ["ETIMSClient", "ETIMSError", "ETIMSSubmissionError", "ETIMSValidationError"]
