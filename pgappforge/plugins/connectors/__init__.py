"""
pgappforge/plugins/connectors/__init__.py

Africa-first connector library for PgAppForge.

Each connector is independently importable and config-driven.
Enable only what your deployment needs.

Available connectors
--------------------
etims          KRA eTIMS — mandatory Kenya tax invoice submission (Jan 2024+)
efris          URA EFRIS — mandatory Uganda e-fiscal receipts
africas_talking Africa's Talking — SMS, USSD, Voice across 18 countries
flutterwave    Flutterwave — cards, mobile money, bank transfer in 34 countries

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

Lazy imports — no connector is loaded until explicitly imported, so unused
connectors carry zero overhead.
"""

# Expose connector names for discovery without eagerly importing clients
AVAILABLE_CONNECTORS: dict[str, str] = {
	"etims": "pgappforge.plugins.connectors.etims.ETIMSClient",
	"efris": "pgappforge.plugins.connectors.efris.EFRISClient",
	"africas_talking": "pgappforge.plugins.connectors.africas_talking.AfricasTalkingClient",
	"flutterwave": "pgappforge.plugins.connectors.flutterwave.FlutterwaveClient",
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
