"""
pgappforge/plugins/connectors/__init__.py

Africa-first connector library for PgAppForge.

Each connector is independently importable and config-driven.
Enable only what your deployment needs.

Available connectors
--------------------
etims           KRA eTIMS — mandatory Kenya tax invoice submission (Jan 2024+)
efris           URA EFRIS — mandatory Uganda e-fiscal receipts
africas_talking Africa's Talking — SMS, USSD, Voice across 18 countries
flutterwave     Flutterwave — cards, mobile money, bank transfer in 34 countries
mtn_momo        MTN Mobile Money — 63 M users across 13 African countries
airtel_money    Airtel Money — 44 M users across 14 African countries
paystack        Paystack — cards, bank transfer in Nigeria, Ghana, Kenya, South Africa
pesapal         Pesapal — M-Pesa, cards, Airtel in Kenya, Uganda, Tanzania, Rwanda, Zambia
zra             ZRA Smart Invoice — Zambia mandatory e-invoicing (16 % VAT)

Quick start
-----------
All connectors follow the same pattern::

    from pgappforge.plugins.connectors.<name> import <ClientClass>
    client = <ClientClass>.from_config()   # reads from Flask app.config
    # OR
    client = <ClientClass>.sandbox()       # pre-configured test environment

Flask config keys (enable only what you need)
---------------------------------------------
eTIMS:
    ETIMS_ENABLED = True
    ETIMS_PIN = "P000000000A"
    ETIMS_BRANCH_ID = "00"
    ETIMS_BASE_URL = "https://etims-api.kra.go.ke"
    ETIMS_DEVICE_SERIAL = "..."
    ETIMS_TIMEOUT = 30

EFRIS:
    EFRIS_ENABLED = True
    EFRIS_TIN = "1000000000"
    EFRIS_DEVICE_ID = "..."
    EFRIS_BASE_URL = "https://efris.ura.go.ug"
    EFRIS_TIMEOUT = 30

Africa's Talking:
    AT_ENABLED = True
    AT_API_KEY = "..."
    AT_USERNAME = "sandbox"   # or your production username
    AT_SENDER_ID = "MYAPP"
    AT_TIMEOUT = 30

Flutterwave:
    FLW_ENABLED = True
    FLW_PUBLIC_KEY = "pk_live_..."
    FLW_SECRET_KEY = "sk_live_..."
    FLW_BASE_URL = "https://api.flutterwave.com/v3"

MTN MoMo:
    MTN_MOMO_ENABLED = True
    MTN_MOMO_SUBSCRIPTION_KEY = "..."
    MTN_MOMO_API_USER = "..."        # UUID from developer portal
    MTN_MOMO_API_KEY = "..."
    MTN_MOMO_BASE_URL = "https://momoapi.mtn.com"
    MTN_MOMO_ENVIRONMENT = "production"   # or "sandbox"
    MTN_MOMO_CURRENCY = "UGX"            # "EUR" for sandbox

Airtel Money:
    AIRTEL_ENABLED = True
    AIRTEL_CLIENT_ID = "..."
    AIRTEL_CLIENT_SECRET = "..."
    AIRTEL_BASE_URL = "https://openapi.airtel.africa"
    AIRTEL_COUNTRY = "KE"
    AIRTEL_CURRENCY = "KES"

Paystack:
    PAYSTACK_ENABLED = True
    PAYSTACK_SECRET_KEY = "sk_live_..."
    PAYSTACK_BASE_URL = "https://api.paystack.co"

Pesapal:
    PESAPAL_ENABLED = True
    PESAPAL_CONSUMER_KEY = "..."
    PESAPAL_CONSUMER_SECRET = "..."
    PESAPAL_BASE_URL = "https://pay.pesapal.com/v3"

ZRA Smart Invoice:
    ZRA_ENABLED = True
    ZRA_TIN = "1000000001"
    ZRA_BHFID = "000"
    ZRA_DEVICE_SERIAL = "..."
    ZRA_BASE_URL = "https://smartinvoice.zra.org.zm"

Lazy imports — no connector is loaded until explicitly imported, so unused
connectors carry zero overhead.
"""

# Expose connector names for discovery without eagerly importing clients
AVAILABLE_CONNECTORS: dict[str, str] = {
	"etims": "pgappforge.plugins.connectors.etims.ETIMSClient",
	"efris": "pgappforge.plugins.connectors.efris.EFRISClient",
	"africas_talking": "pgappforge.plugins.connectors.africas_talking.AfricasTalkingClient",
	"flutterwave": "pgappforge.plugins.connectors.flutterwave.FlutterwaveClient",
	"mtn_momo": "pgappforge.plugins.connectors.mtn_momo.MTNMoMoClient",
	"airtel_money": "pgappforge.plugins.connectors.airtel_money.AirtelMoneyClient",
	"paystack": "pgappforge.plugins.connectors.paystack.PaystackClient",
	"pesapal": "pgappforge.plugins.connectors.pesapal.PesapalClient",
	"zra": "pgappforge.plugins.connectors.zra.ZRAClient",
}


def get_connector(name: str):
	"""Lazily import and return a connector client class by name.

	Args:
		name: One of the keys in AVAILABLE_CONNECTORS.

	Returns:
		The connector client class.

	Raises:
		KeyError: Unknown connector name.
		ImportError: Connector module import failed.

	Example::

		ETIMSClient = get_connector("etims")
		client = ETIMSClient.from_config()
	"""
	if name not in AVAILABLE_CONNECTORS:
		raise KeyError(
			f"Unknown connector {name!r}. Available: {list(AVAILABLE_CONNECTORS)}"
		)
	module_path, class_name = AVAILABLE_CONNECTORS[name].rsplit(".", 1)
	import importlib
	module = importlib.import_module(module_path)
	return getattr(module, class_name)


__all__ = ["AVAILABLE_CONNECTORS", "get_connector"]
