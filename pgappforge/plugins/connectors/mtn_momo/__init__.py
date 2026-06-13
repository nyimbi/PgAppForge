"""
pgappforge/plugins/connectors/mtn_momo/__init__.py

MTN Mobile Money (MoMo) connector — 63 M users across 13 African countries.

Supports Collections (customer → business), Disbursements (business → customer),
and Remittance product lines.

Quick start (sandbox)::

	from pgappforge.plugins.connectors.mtn_momo import MTNMoMoClient

	client = MTNMoMoClient(
	    subscription_key="...",
	    base_url="https://sandbox.momoapi.mtn.com",
	    environment="sandbox",
	    currency="EUR",
	)
	api_user = client.create_api_user("https://myapp.example.com")
	api_key  = client.get_api_key(api_user)
	client.api_user = api_user
	client.api_key  = api_key

	result = client.request_to_pay(
	    amount="1000", currency="EUR", msisdn="46733123454",
	    external_id="ORD-001", payer_message="Invoice 1", payee_note="Ref 1",
	)

Quick start (production)::

	from pgappforge.plugins.connectors.mtn_momo import MTNMoMoClient

	client = MTNMoMoClient.from_config()   # reads MTN_MOMO_* from Flask config
	result = client.request_to_pay(
	    amount="10000", currency="UGX", msisdn="256700000000",
	    external_id="ORD-001", payer_message="Order payment", payee_note="ORD-001",
	)

Flask config keys:
	MTN_MOMO_SUBSCRIPTION_KEY   Ocp-Apim-Subscription-Key from developer portal
	MTN_MOMO_API_USER           UUID of the provisioned API user
	MTN_MOMO_API_KEY            API key for the API user
	MTN_MOMO_BASE_URL           API base URL
	MTN_MOMO_ENVIRONMENT        "sandbox" | "production"
	MTN_MOMO_CURRENCY           ISO 4217 code (default "EUR" sandbox, "UGX" prod)
	MTN_MOMO_TIMEOUT            HTTP timeout seconds (default 30)
	MTN_MOMO_ENABLED            Set False to skip in dev (default True)
"""
from pgappforge.plugins.connectors.mtn_momo.client import (
	MTNMoMoClient,
	MTNMoMoError,
)

__all__ = ["MTNMoMoClient", "MTNMoMoError"]
