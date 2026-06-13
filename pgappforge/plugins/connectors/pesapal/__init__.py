"""
pgappforge/plugins/connectors/pesapal/__init__.py

Pesapal connector — multi-payment gateway for East and Southern Africa.

Countries: Kenya, Uganda, Tanzania, Rwanda, Malawi, Zimbabwe, Zambia.
Payment methods: M-Pesa, Airtel Money, MTN MoMo, Visa, Mastercard, bank transfers.

Quick start::

	from pgappforge.plugins.connectors.pesapal import PesapalClient

	client = PesapalClient.from_config()   # reads PESAPAL_* from Flask config

	# Register IPN URL once (persist notification_id in your DB):
	ipn = client.register_ipn_url("https://myapp.com/pesapal/ipn")
	notification_id = ipn["ipn_id"]

	# Submit a payment order:
	order = client.submit_order(
	    id="ORD-001",
	    currency="KES",
	    amount=5000.0,
	    description="Invoice #42",
	    callback_url="https://myapp.com/pesapal/callback",
	    redirect_mode="PARENT_WINDOW",
	    notification_id=notification_id,
	    branch="HQ",
	    billing_address={"email_address": "customer@example.com",
	                     "first_name": "Jane", "last_name": "Doe"},
	)
	# Redirect user to order["redirect_url"]

	# Check status (or handle IPN):
	status = client.get_transaction_status(order["order_tracking_id"])
	print(status["payment_status_description"])   # "Completed" | "Failed" | "Pending"

Flask config keys:
	PESAPAL_CONSUMER_KEY     From Pesapal merchant portal
	PESAPAL_CONSUMER_SECRET  From Pesapal merchant portal
	PESAPAL_BASE_URL         Sandbox: "https://cybqa.pesapal.com/pesapalv3"
	                         Production: "https://pay.pesapal.com/v3"
	PESAPAL_TIMEOUT          HTTP timeout seconds (default 30)
	PESAPAL_ENABLED          Set False to skip in dev (default True)
"""
from pgappforge.plugins.connectors.pesapal.client import (
	PesapalClient,
	PesapalError,
)

__all__ = ["PesapalClient", "PesapalError"]
