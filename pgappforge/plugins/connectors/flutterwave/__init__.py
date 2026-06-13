"""
pgappforge/plugins/connectors/flutterwave/__init__.py

Flutterwave connector — payments in 34 African countries.

Quick start::

    from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient

    client = FlutterwaveClient.from_config()    # reads FLW_* from Flask config

    # Hosted checkout (redirect to Flutterwave payment page):
    result = client.initiate_payment(
        amount=5000, currency="KES",
        email="user@example.com", phone="+254712345678",
        name="Jane Doe", reference="ORD-2024-001",
        redirect_url="https://myapp.com/payment/callback",
    )
    # Redirect user to result["payment_link"]

    # Verify after callback:
    v = client.verify_payment(request.args["transaction_id"])
    if v["success"] and v["status"] == "successful":
        # fulfil the order
        pass

    # Mobile money (STK push):
    client.initiate_mobile_money(1000, "KES", "+254712345678", "MPESA", "REF-001")

Flask config keys:
    FLW_PUBLIC_KEY   Flutterwave public key
    FLW_SECRET_KEY   Flutterwave secret key (mandatory)
    FLW_BASE_URL     API base (default: https://api.flutterwave.com/v3)
    FLW_ENABLED      Set False to skip in dev (default True)

Use pk_test_* / sk_test_* keys from dashboard.flutterwave.com for sandbox.
"""
from pgappforge.plugins.connectors.flutterwave.client import (
	FlutterwaveClient,
	FlutterwaveError,
)

__all__ = ["FlutterwaveClient", "FlutterwaveError"]
