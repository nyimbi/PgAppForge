"""
pgappforge/plugins/connectors/paystack/__init__.py

Paystack connector — Nigeria, Ghana, Kenya, South Africa.

Quick start::

	from pgappforge.plugins.connectors.paystack import PaystackClient

	client = PaystackClient.from_config()   # reads PAYSTACK_* from Flask config

	# Hosted checkout redirect:
	init = client.initialize_transaction(
	    email="customer@example.com",
	    amount_kobo=50000,     # NGN 500 or KES 500
	    reference="ORD-001",
	    callback_url="https://myapp.com/payment/callback",
	)
	# redirect user to init["data"]["authorization_url"]

	# Verify after callback:
	result = client.verify_transaction("ORD-001")
	if result["data"]["status"] == "success":
	    # fulfil order
	    pass

	# Charge a saved card:
	client.charge_authorization("AUTH_xxx", "customer@example.com", 50000)

Amount convention:
	All amounts in kobo (currency × 100).
	NGN 100 = 10 000 kobo, KES 100 = 10 000 kobo.

Flask config keys:
	PAYSTACK_SECRET_KEY   sk_live_* or sk_test_* (mandatory)
	PAYSTACK_BASE_URL     API base (default "https://api.paystack.co")
	PAYSTACK_TIMEOUT      HTTP timeout seconds (default 30)
	PAYSTACK_ENABLED      Set False to skip in dev (default True)
"""
from pgappforge.plugins.connectors.paystack.client import (
	PaystackClient,
	PaystackError,
)

__all__ = ["PaystackClient", "PaystackError"]
