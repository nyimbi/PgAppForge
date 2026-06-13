"""
pgappforge/plugins/connectors/airtel_money/__init__.py

Airtel Money connector — 44 M users across 14 African countries.

Countries: Kenya, Uganda, Tanzania, Rwanda, Zambia, Malawi, Congo DRC,
           Niger, Madagascar, Gabon, Seychelles, Chad, Republic of Congo,
           Sierra Leone.

Quick start::

	from pgappforge.plugins.connectors.airtel_money import AirtelMoneyClient

	client = AirtelMoneyClient.from_config()   # reads AIRTEL_* from Flask config

	# Request payment from customer:
	result = client.collections_request(
	    amount=500, msisdn="254712345678",
	    transaction_id="TXN-001", reference="Invoice-42",
	)

	# Pay a customer:
	result = client.disburse(
	    amount=1000, msisdn="254712345678",
	    transaction_id="DIS-001", reference="Salary-May",
	)

Flask config keys:
	AIRTEL_CLIENT_ID      OAuth2 client ID
	AIRTEL_CLIENT_SECRET  OAuth2 client secret
	AIRTEL_BASE_URL       API base URL (default production; use UAT URL for sandbox)
	AIRTEL_COUNTRY        ISO 3166-1 alpha-2, e.g. "KE" | "UG" | "TZ"
	AIRTEL_CURRENCY       ISO 4217 code, e.g. "KES" | "UGX" | "TZS"
	AIRTEL_TIMEOUT        HTTP timeout seconds (default 30)
	AIRTEL_ENABLED        Set False to skip in dev (default True)
"""
from pgappforge.plugins.connectors.airtel_money.client import (
	AirtelMoneyClient,
	AirtelMoneyError,
)

__all__ = ["AirtelMoneyClient", "AirtelMoneyError"]
