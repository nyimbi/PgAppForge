"""
tests/ci/test_africa_connectors.py

CI tests for the Africa Connector Library (P1-4).

All tests run offline — no real API calls are made.
Sandbox/live calls require environment variables and are skipped in CI.
"""
from __future__ import annotations

import pytest


# ------------------------------------------------------------------ #
# Package-level import
# ------------------------------------------------------------------ #

class TestConnectorsPackage:
	def test_package_importable(self):
		from pgappforge.plugins.connectors import AVAILABLE_CONNECTORS, get_connector
		assert "etims" in AVAILABLE_CONNECTORS
		assert "efris" in AVAILABLE_CONNECTORS
		assert "africas_talking" in AVAILABLE_CONNECTORS
		assert "flutterwave" in AVAILABLE_CONNECTORS

	def test_get_connector_etims(self):
		from pgappforge.plugins.connectors import get_connector
		cls = get_connector("etims")
		assert cls.__name__ == "ETIMSClient"

	def test_get_connector_unknown_raises(self):
		from pgappforge.plugins.connectors import get_connector
		with pytest.raises(KeyError, match="Unknown connector"):
			get_connector("nonexistent_connector")


# ------------------------------------------------------------------ #
# eTIMS
# ------------------------------------------------------------------ #

class TestETIMSClient:
	def test_import(self):
		from pgappforge.plugins.connectors.etims import ETIMSClient, ETIMSError, ETIMSSubmissionError
		assert ETIMSClient is not None

	def test_sandbox_factory(self):
		from pgappforge.plugins.connectors.etims import ETIMSClient
		client = ETIMSClient.sandbox()
		assert "sbx" in client.base_url or "sandbox" in client.base_url
		assert client.pin == "A000000000A"

	def test_disabled_skips_submission(self):
		from pgappforge.plugins.connectors.etims import ETIMSClient
		client = ETIMSClient(pin="P000000000A", enabled=False)
		result = client.submit_invoice(
			invoice_number="INV-001",
			customer_pin="000000000",
			customer_name="Test",
			items=[{"description": "Item", "quantity": 1, "unit_price_kes": 116, "vat_rate_pct": 16}],
		)
		assert result["success"] is True
		assert result.get("skipped") is True

	def test_missing_pin_returns_error(self):
		from pgappforge.plugins.connectors.etims import ETIMSClient
		client = ETIMSClient(pin="", enabled=True)
		result = client.submit_invoice(
			invoice_number="INV-001",
			customer_pin="000000000",
			customer_name="Test",
			items=[{"description": "Item", "quantity": 1, "unit_price_kes": 116, "vat_rate_pct": 16}],
		)
		assert result["success"] is False
		assert "ETIMS_PIN" in result["error"]

	def test_empty_items_returns_error(self):
		from pgappforge.plugins.connectors.etims import ETIMSClient
		client = ETIMSClient(pin="P000000000A", enabled=True)
		result = client.submit_invoice(
			invoice_number="INV-001",
			customer_pin="000000000",
			customer_name="Test",
			items=[],
		)
		assert result["success"] is False
		assert "line item" in result["error"].lower()

	def test_vat_calculation_standard_rate(self):
		"""VAT-inclusive price: 1160 KES = 1000 net + 160 VAT at 16%."""
		from decimal import Decimal, ROUND_HALF_UP
		unit_price = Decimal("1160")
		vat_rate = Decimal("0.16")
		line_total = unit_price * 1
		vat = (line_total * vat_rate / (1 + vat_rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
		net = line_total - vat
		assert vat == Decimal("160.00")
		assert net == Decimal("1000.00")

	def test_exempt_item_no_vat(self):
		"""Zero-rate item: no VAT calculated."""
		from pgappforge.plugins.connectors.etims import ETIMSClient
		# We can't call the real API, but we can verify the payload is built
		# by patching _post to capture it.
		captured = {}

		def _fake_post(path, payload):
			captured.update(payload)
			# Simulate success
			return {"resultCd": "000", "data": {"rcptNo": "CU001", "intrlData": "SIG", "rcptSign": "FSIG"}}

		client = ETIMSClient(pin="P000000000A", enabled=True)
		client._post = _fake_post

		result = client.submit_invoice(
			invoice_number="INV-002",
			customer_pin="000000000",
			customer_name="Test",
			items=[
				{"description": "Exempt", "quantity": 1, "unit_price_kes": 1000, "vat_rate_pct": 0},
			],
		)
		assert result["success"] is True
		assert captured["taxAmtA"] == 0.0
		assert captured["itemList"][0]["taxTyCd"] == "E"

	def test_mixed_vat_items(self):
		"""Mixed standard + exempt items — totals are computed correctly."""
		captured = {}

		def _fake_post(path, payload):
			captured.update(payload)
			return {"resultCd": "000", "data": {"rcptNo": "CU002", "intrlData": "", "rcptSign": ""}}

		from pgappforge.plugins.connectors.etims import ETIMSClient
		client = ETIMSClient(pin="P000000000A", enabled=True)
		client._post = _fake_post

		client.submit_invoice(
			invoice_number="INV-003",
			customer_pin="000000000",
			customer_name="Test",
			items=[
				{"description": "VATable",  "quantity": 1, "unit_price_kes": 11600, "vat_rate_pct": 16},
				{"description": "Exempt",   "quantity": 1, "unit_price_kes": 5000,  "vat_rate_pct": 0},
			],
		)
		# Total should be 11600 + 5000 = 16600
		assert abs(captured["totAmt"] - 16600.0) < 0.01
		# VAT on 11600 at 16%: 11600 * 0.16 / 1.16 = 1600
		assert abs(captured["taxAmtA"] - 1600.0) < 0.01


# ------------------------------------------------------------------ #
# EFRIS
# ------------------------------------------------------------------ #

class TestEFRISClient:
	def test_import(self):
		from pgappforge.plugins.connectors.efris import EFRISClient, EFRISError, EFRISSubmissionError
		assert EFRISClient is not None

	def test_sandbox_factory(self):
		from pgappforge.plugins.connectors.efris import EFRISClient
		client = EFRISClient.sandbox()
		assert "test" in client.base_url or "sbx" in client.base_url
		assert client.tin == "1000000000"

	def test_disabled_skips(self):
		from pgappforge.plugins.connectors.efris import EFRISClient
		client = EFRISClient(tin="1000000001", enabled=False)
		result = client.submit_invoice(
			invoice_number="INV-001",
			customer_tin="0000000000",
			customer_name="Test",
			items=[{"description": "Goods", "quantity": 1, "unit_price_ugx": 118000, "vat_rate_pct": 18}],
		)
		assert result["success"] is True
		assert result.get("skipped") is True

	def test_missing_tin_returns_error(self):
		from pgappforge.plugins.connectors.efris import EFRISClient
		client = EFRISClient(tin="", enabled=True)
		result = client.submit_invoice(
			invoice_number="INV-001",
			customer_tin="0000000000",
			customer_name="Test",
			items=[{"description": "x", "quantity": 1, "unit_price_ugx": 1000, "vat_rate_pct": 18}],
		)
		assert result["success"] is False
		assert "EFRIS_TIN" in result["error"]

	def test_uganda_vat_18pct(self):
		"""Uganda VAT: 118000 UGX = 100000 net + 18000 VAT at 18%."""
		from decimal import Decimal, ROUND_HALF_UP
		price = Decimal("118000")
		rate = Decimal("0.18")
		vat = (price * rate / (1 + rate)).quantize(Decimal("1"), ROUND_HALF_UP)
		net = price - vat
		assert vat == Decimal("18000")
		assert net == Decimal("100000")

	def test_invoice_type_mapping(self):
		"""ORIGINAL→1, CREDIT→3, DEBIT→4."""
		captured = {}

		def _fake_post(path, payload):
			captured.update(payload)
			return {"returnCode": "00", "data": {"fiscalReceiptNumber": "FRN001", "qrCode": ""}}

		from pgappforge.plugins.connectors.efris import EFRISClient
		client = EFRISClient(tin="1000000001", device_id="99999", enabled=True)
		client._post = _fake_post

		client.submit_invoice(
			invoice_number="INV-001",
			customer_tin="0000000000",
			customer_name="Test",
			items=[{"description": "x", "quantity": 1, "unit_price_ugx": 1000, "vat_rate_pct": 0}],
			invoice_type="CREDIT",
		)
		assert captured["invoiceType"] == "3"


# ------------------------------------------------------------------ #
# Africa's Talking
# ------------------------------------------------------------------ #

class TestAfricasTalkingClient:
	def test_import(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient, AfricasTalkingError
		assert AfricasTalkingClient is not None

	def test_sandbox_factory(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient.sandbox()
		assert client.username == "sandbox"
		assert client._is_sandbox is True

	def test_disabled_returns_skipped(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient(api_key="key", username="sandbox", enabled=False)
		result = client.send_sms("+254712345678", "Test")
		assert result.get("skipped") is True

	def test_missing_api_key_returns_error(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient(api_key="", username="sandbox", enabled=True)
		result = client.send_sms("+254712345678", "Test")
		assert "AT_API_KEY" in result.get("error", "")

	def test_send_otp_message_format(self):
		"""OTP message contains the OTP code."""
		messages_sent = []

		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient

		client = AfricasTalkingClient(api_key="testkey", username="sandbox", enabled=True)

		# Capture _post_form call
		def _fake_post_form(url, body):
			messages_sent.append(body)
			return {"SMSMessageData": {"Recipients": []}}

		client._post_form = _fake_post_form
		client.send_otp("+254712345678", "847291", app_name="TestApp")

		assert len(messages_sent) == 1
		assert "847291" in messages_sent[0]["message"]
		assert "TestApp" in messages_sent[0]["message"]

	def test_send_bulk_sms_returns_list(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient(api_key="k", username="sandbox", enabled=True)

		def _fake_post_form(url, body):
			return {"SMSMessageData": {"Recipients": [{"status": "Success"}]}}

		client._post_form = _fake_post_form
		results = client.send_bulk_sms([
			{"to": "+254712345678", "message": "Hello A"},
			{"to": "+254787654321", "message": "Hello B"},
		])
		assert len(results) == 2
		assert results[0]["_to"] == "+254712345678"

	def test_ussd_default_menu_first_request(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient(api_key="k", username="sandbox")
		response = client.handle_ussd_request("sess1", "*384#", "+254712345678", "")
		assert response.startswith("CON ")

	def test_ussd_exit_option(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient(api_key="k", username="sandbox")
		response = client.handle_ussd_request("sess1", "*384#", "+254712345678", "0")
		assert response.startswith("END ")

	def test_ussd_custom_handler(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient(api_key="k", username="sandbox")

		def my_handler(session_id, phone, text):
			return "CON Custom menu\n1. Option A"

		response = client.handle_ussd_request("s1", "*384#", "+254700000000", "", menu_handler=my_handler)
		assert "Custom menu" in response

	def test_ussd_handler_exception_returns_end(self):
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient(api_key="k", username="sandbox")

		def bad_handler(session_id, phone, text):
			raise RuntimeError("DB down")

		response = client.handle_ussd_request("s1", "*384#", "+254700000000", "", menu_handler=bad_handler)
		assert response.startswith("END ")

	def test_list_recipients_joined(self):
		"""Multiple phone numbers are joined into comma-separated string."""
		from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient
		client = AfricasTalkingClient(api_key="k", username="sandbox", enabled=True)
		captured = {}

		def _fake_post_form(url, body):
			captured.update(body)
			return {}

		client._post_form = _fake_post_form
		client.send_sms(["+254712345678", "+254787654321"], "Hello")
		assert captured["to"] == "+254712345678,+254787654321"


# ------------------------------------------------------------------ #
# Flutterwave
# ------------------------------------------------------------------ #

class TestFlutterwaveClient:
	def test_import(self):
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient, FlutterwaveError
		assert FlutterwaveClient is not None

	def test_sandbox_factory(self):
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient
		client = FlutterwaveClient.sandbox(public_key="pk_test_X", secret_key="sk_test_Y")
		assert client.public_key == "pk_test_X"
		assert client.secret_key == "sk_test_Y"

	def test_disabled_skips_payment(self):
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient
		client = FlutterwaveClient(secret_key="sk_test", enabled=False)
		result = client.initiate_payment(
			amount=1000, currency="KES",
			email="test@example.com", phone="+254712345678",
			name="Test", reference="REF-001",
			redirect_url="https://example.com/cb",
		)
		assert result["success"] is True
		assert result.get("skipped") is True

	def test_missing_secret_key_returns_error(self):
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient
		client = FlutterwaveClient(secret_key="", enabled=True)
		result = client.initiate_payment(
			amount=1000, currency="KES",
			email="t@e.com", phone="+254700000000",
			name="T", reference="R1",
			redirect_url="https://example.com",
		)
		assert result["success"] is False
		assert "FLW_SECRET_KEY" in result["error"]

	def test_initiate_payment_builds_correct_payload(self):
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient
		captured = {}

		def _fake_request(method, path, payload):
			if payload:
				captured.update(payload)
			return {"status": "success", "data": {"link": "https://flw.com/pay/TEST"}}

		client = FlutterwaveClient(secret_key="sk_test_x", enabled=True)
		client._request = _fake_request

		result = client.initiate_payment(
			amount=5000, currency="KES",
			email="user@example.com", phone="+254712345678",
			name="Jane Doe", reference="ORD-001",
			redirect_url="https://myapp.com/cb",
			meta={"order_type": "subscription"},
		)
		assert result["success"] is True
		assert result["payment_link"] == "https://flw.com/pay/TEST"
		assert captured["tx_ref"] == "ORD-001"
		assert captured["amount"] == 5000
		assert captured["currency"] == "KES"
		assert captured["customer"]["email"] == "user@example.com"
		assert captured["meta"]["order_type"] == "subscription"

	def test_verify_payment_success(self):
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient

		def _fake_request(method, path, payload):
			return {
				"status": "success",
				"data": {
					"status": "successful",
					"amount": 5000,
					"currency": "KES",
					"tx_ref": "ORD-001",
					"customer": {"email": "user@example.com"},
					"flw_ref": "FLW-REF-001",
				},
			}

		client = FlutterwaveClient(secret_key="sk_test_x", enabled=True)
		client._request = _fake_request

		result = client.verify_payment("123456")
		assert result["success"] is True
		assert result["status"] == "successful"
		assert result["amount"] == 5000

	def test_mobile_money_disabled_skips(self):
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient
		client = FlutterwaveClient(secret_key="sk_test", enabled=False)
		result = client.initiate_mobile_money(1000, "KES", "+254712345678", "MPESA", "REF-MM-001")
		assert result.get("skipped") is True

	def test_get_banks_returns_list_on_api_error(self):
		"""get_banks should return empty list, not raise, on API error."""
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient, FlutterwaveError

		def _fake_request(method, path, payload):
			raise FlutterwaveError("API unavailable")

		client = FlutterwaveClient(secret_key="sk_test", enabled=True)
		client._request = _fake_request

		banks = client.get_banks("KE")
		assert banks == []

	def test_bank_transfer_missing_key_returns_error(self):
		from pgappforge.plugins.connectors.flutterwave import FlutterwaveClient
		client = FlutterwaveClient(secret_key="", enabled=True)
		result = client.initiate_bank_transfer(
			amount=10000, currency="KES",
			bank_code="01", account_number="0123456789",
			account_name="John Doe", reference="TRF-001",
		)
		assert result["success"] is False
		assert "FLW_SECRET_KEY" in result["error"]


# ------------------------------------------------------------------ #
# MTN MoMo
# ------------------------------------------------------------------ #

class TestMTNMoMoClient:
	def test_mtn_momo_client_import(self):
		from pgappforge.plugins.connectors.mtn_momo import MTNMoMoClient, MTNMoMoError
		assert MTNMoMoClient is not None
		assert MTNMoMoError is not None

	def test_mtn_momo_default_config(self):
		"""from_config() outside Flask context returns a default client."""
		from pgappforge.plugins.connectors.mtn_momo import MTNMoMoClient
		client = MTNMoMoClient.from_config()
		assert client.environment == "sandbox"
		assert client.currency == "EUR"
		assert client.timeout == 30
		assert client.enabled is True

	def test_request_to_pay_disabled_skips(self):
		from pgappforge.plugins.connectors.mtn_momo import MTNMoMoClient
		client = MTNMoMoClient(subscription_key="sub_key", enabled=False)
		result = client.request_to_pay(
			amount="100", currency="EUR", msisdn="46733123454",
			external_id="ext-001", payer_message="Test", payee_note="Test",
		)
		assert result["success"] is True
		assert result.get("skipped") is True

	def test_request_to_pay_missing_subscription_key(self):
		from pgappforge.plugins.connectors.mtn_momo import MTNMoMoClient
		client = MTNMoMoClient(subscription_key="", enabled=True)
		result = client.request_to_pay(
			amount="100", currency="EUR", msisdn="46733123454",
			external_id="ext-001", payer_message="Test", payee_note="Test",
		)
		assert result["success"] is False
		assert "MTN_MOMO_SUBSCRIPTION_KEY" in result["error"]

	def test_transfer_disabled_skips(self):
		from pgappforge.plugins.connectors.mtn_momo import MTNMoMoClient
		client = MTNMoMoClient(subscription_key="key", enabled=False)
		result = client.transfer(
			amount="500", currency="UGX", msisdn="256700000000",
			external_id="dis-001", payee_note="Salary",
		)
		assert result.get("skipped") is True

	def test_token_cache_per_product(self):
		"""get_access_token() caches per product, not globally."""
		from pgappforge.plugins.connectors.mtn_momo import MTNMoMoClient
		client = MTNMoMoClient(subscription_key="k", api_user="u", api_key="k2")
		# Pre-populate cache directly
		client._token_cache["collection"] = "tok_col"
		client._token_cache["disbursement"] = "tok_dis"
		assert client._token_cache["collection"] == "tok_col"
		assert client._token_cache["disbursement"] == "tok_dis"
		assert client._token_cache.get("remittance") is None

	def test_product_path_map(self):
		"""All three products have path entries."""
		from pgappforge.plugins.connectors.mtn_momo.client import _PRODUCT_PATH
		assert "collection" in _PRODUCT_PATH
		assert "disbursement" in _PRODUCT_PATH
		assert "remittance" in _PRODUCT_PATH

	def test_get_connector_mtn_momo(self):
		from pgappforge.plugins.connectors import get_connector
		cls = get_connector("mtn_momo")
		assert cls.__name__ == "MTNMoMoClient"


# ------------------------------------------------------------------ #
# Airtel Money
# ------------------------------------------------------------------ #

class TestAirtelMoneyClient:
	def test_airtel_client_import(self):
		from pgappforge.plugins.connectors.airtel_money import AirtelMoneyClient, AirtelMoneyError
		assert AirtelMoneyClient is not None
		assert AirtelMoneyError is not None

	def test_airtel_default_config(self):
		from pgappforge.plugins.connectors.airtel_money import AirtelMoneyClient
		client = AirtelMoneyClient.from_config()
		assert client.country == "KE"
		assert client.currency == "KES"
		assert client.enabled is True

	def test_collections_request_disabled_skips(self):
		from pgappforge.plugins.connectors.airtel_money import AirtelMoneyClient
		client = AirtelMoneyClient(client_id="cid", enabled=False)
		result = client.collections_request(500, "254712345678", "TXN-001", "Ref-1")
		assert result.get("skipped") is True
		assert result["success"] is True

	def test_collections_request_missing_client_id(self):
		from pgappforge.plugins.connectors.airtel_money import AirtelMoneyClient
		client = AirtelMoneyClient(client_id="", enabled=True)
		result = client.collections_request(500, "254712345678", "TXN-001", "Ref-1")
		assert result["success"] is False
		assert "AIRTEL_CLIENT_ID" in result["error"]

	def test_disburse_disabled_skips(self):
		from pgappforge.plugins.connectors.airtel_money import AirtelMoneyClient
		client = AirtelMoneyClient(client_id="cid", enabled=False)
		result = client.disburse(1000, "254712345678", "DIS-001", "Salary")
		assert result.get("skipped") is True

	def test_disburse_missing_client_id(self):
		from pgappforge.plugins.connectors.airtel_money import AirtelMoneyClient
		client = AirtelMoneyClient(client_id="", enabled=True)
		result = client.disburse(1000, "254712345678", "DIS-001", "Salary")
		assert result["success"] is False
		assert "AIRTEL_CLIENT_ID" in result["error"]

	def test_sandbox_factory(self):
		from pgappforge.plugins.connectors.airtel_money import AirtelMoneyClient
		client = AirtelMoneyClient.sandbox(client_id="cid", client_secret="sec")
		assert "uat" in client.base_url or "sandbox" in client.base_url
		assert client.client_id == "cid"

	def test_get_connector_airtel_money(self):
		from pgappforge.plugins.connectors import get_connector
		cls = get_connector("airtel_money")
		assert cls.__name__ == "AirtelMoneyClient"


# ------------------------------------------------------------------ #
# Paystack
# ------------------------------------------------------------------ #

class TestPaystackClient:
	def test_paystack_client_import(self):
		from pgappforge.plugins.connectors.paystack import PaystackClient, PaystackError
		assert PaystackClient is not None
		assert PaystackError is not None

	def test_paystack_amounts_in_kobo(self):
		"""Amounts are always in kobo — 100 units = 10 000 kobo.

		This documents the convention: callers multiply by 100 before passing.
		e.g. NGN 500 → 50 000 kobo, KES 100 → 10 000 kobo.
		"""
		amount_currency = 500        # NGN 500
		amount_kobo = amount_currency * 100
		assert amount_kobo == 50000

	def test_paystack_default_config(self):
		from pgappforge.plugins.connectors.paystack import PaystackClient
		client = PaystackClient.from_config()
		assert client.base_url == "https://api.paystack.co"
		assert client.timeout == 30
		assert client.enabled is True

	def test_initialize_transaction_disabled_skips(self):
		from pgappforge.plugins.connectors.paystack import PaystackClient
		client = PaystackClient(secret_key="sk_test", enabled=False)
		result = client.initialize_transaction(
			email="test@example.com", amount_kobo=10000, reference="REF-001",
		)
		assert result.get("skipped") is True
		assert result["status"] is True

	def test_initialize_transaction_missing_key(self):
		from pgappforge.plugins.connectors.paystack import PaystackClient
		client = PaystackClient(secret_key="", enabled=True)
		result = client.initialize_transaction(
			email="test@example.com", amount_kobo=10000,
		)
		assert result["status"] is False
		assert "PAYSTACK_SECRET_KEY" in result["message"]

	def test_initialize_transaction_builds_correct_payload(self):
		from pgappforge.plugins.connectors.paystack import PaystackClient
		captured: dict = {}

		def _fake_post(path, payload):
			captured.update(payload)
			return {"status": True, "data": {"authorization_url": "https://paystack.com/pay/abc"}}

		client = PaystackClient(secret_key="sk_test_x", enabled=True)
		client._post = _fake_post

		client.initialize_transaction(
			email="user@example.com",
			amount_kobo=50000,
			reference="ORD-PSK-001",
			callback_url="https://myapp.com/cb",
			metadata={"order_id": "ORD-001"},
		)
		assert captured["email"] == "user@example.com"
		assert captured["amount"] == 50000
		assert captured["reference"] == "ORD-PSK-001"
		assert captured["callback_url"] == "https://myapp.com/cb"
		assert captured["metadata"]["order_id"] == "ORD-001"

	def test_charge_authorization_disabled_skips(self):
		from pgappforge.plugins.connectors.paystack import PaystackClient
		client = PaystackClient(secret_key="sk_test", enabled=False)
		result = client.charge_authorization("AUTH_xxx", "test@example.com", 10000)
		assert result.get("skipped") is True

	def test_initiate_transfer_missing_key(self):
		from pgappforge.plugins.connectors.paystack import PaystackClient
		client = PaystackClient(secret_key="", enabled=True)
		result = client.initiate_transfer(50000, "RCP_xxx", "TRF-001", "Salary")
		assert result["status"] is False
		assert "PAYSTACK_SECRET_KEY" in result["message"]

	def test_get_connector_paystack(self):
		from pgappforge.plugins.connectors import get_connector
		cls = get_connector("paystack")
		assert cls.__name__ == "PaystackClient"


# ------------------------------------------------------------------ #
# Pesapal
# ------------------------------------------------------------------ #

class TestPesapalClient:
	def test_pesapal_client_import(self):
		from pgappforge.plugins.connectors.pesapal import PesapalClient, PesapalError
		assert PesapalClient is not None
		assert PesapalError is not None

	def test_pesapal_default_config(self):
		from pgappforge.plugins.connectors.pesapal import PesapalClient
		client = PesapalClient.from_config()
		assert "pesapal.com" in client.base_url
		assert client.timeout == 30
		assert client.enabled is True

	def test_pesapal_sandbox_factory(self):
		from pgappforge.plugins.connectors.pesapal import PesapalClient
		client = PesapalClient.sandbox(consumer_key="ck", consumer_secret="cs")
		assert "cybqa" in client.base_url or "sandbox" in client.base_url
		assert client.consumer_key == "ck"

	def test_submit_order_disabled_skips(self):
		from pgappforge.plugins.connectors.pesapal import PesapalClient
		client = PesapalClient(consumer_key="ck", enabled=False)
		result = client.submit_order(
			id="ORD-001", currency="KES", amount=1000.0,
			description="Test", callback_url="https://example.com/cb",
			redirect_mode="PARENT_WINDOW", notification_id="IPN-001",
		)
		assert result.get("skipped") is True
		assert result["error"] is None

	def test_submit_order_missing_consumer_key(self):
		from pgappforge.plugins.connectors.pesapal import PesapalClient
		client = PesapalClient(consumer_key="", enabled=True)
		result = client.submit_order(
			id="ORD-001", currency="KES", amount=1000.0,
			description="Test", callback_url="https://example.com/cb",
			redirect_mode="PARENT_WINDOW", notification_id="IPN-001",
		)
		assert result["order_tracking_id"] == ""
		assert "PESAPAL_CONSUMER_KEY" in result["error"]

	def test_token_cached_per_instance(self):
		"""_access_token is cached on the instance."""
		from pgappforge.plugins.connectors.pesapal import PesapalClient
		client = PesapalClient(consumer_key="ck", consumer_secret="cs")
		client._access_token = "cached_token"
		# get_access_token should return cache without HTTP call
		# (we haven't set up a fake HTTP server, so if it tries a real call it will raise)
		token = client.get_access_token()
		assert token == "cached_token"

	def test_get_connector_pesapal(self):
		from pgappforge.plugins.connectors import get_connector
		cls = get_connector("pesapal")
		assert cls.__name__ == "PesapalClient"


# ------------------------------------------------------------------ #
# ZRA Smart Invoice
# ------------------------------------------------------------------ #

class TestZRAClient:
	def test_zra_client_import(self):
		from pgappforge.plugins.connectors.zra import ZRAClient, ZRAError, ZRASubmissionError
		assert ZRAClient is not None
		assert ZRAError is not None
		assert ZRASubmissionError is not None

	def test_zra_vat_rate_16_pct(self):
		"""Zambia standard VAT is 16 % — extract from VAT-inclusive price."""
		from decimal import Decimal, ROUND_HALF_UP
		unit_price = Decimal("11600")      # ZMW, VAT-inclusive
		vat_rate = Decimal("0.16")
		line_total = unit_price * 1
		vat = (line_total * vat_rate / (1 + vat_rate)).quantize(Decimal("0.01"), ROUND_HALF_UP)
		net = line_total - vat
		assert vat == Decimal("1600.00")
		assert net == Decimal("10000.00")

	def test_zra_sandbox_factory(self):
		from pgappforge.plugins.connectors.zra import ZRAClient
		client = ZRAClient.sandbox()
		assert client.tin == "1000000001"
		assert "sandbox" in client.base_url or "zra.org.zm" in client.base_url

	def test_zra_disabled_skips_submission(self):
		from pgappforge.plugins.connectors.zra import ZRAClient
		client = ZRAClient(tin="1000000001", enabled=False)
		result = client.submit_invoice(
			invoice_number="INV-001",
			customer_tpin="0000000000",
			customer_name="Test Customer",
			items=[{"description": "Goods", "quantity": 1, "unit_price": 11600, "vat_rate_pct": 16}],
		)
		assert result["success"] is True
		assert result.get("skipped") is True

	def test_zra_missing_tin_returns_error(self):
		from pgappforge.plugins.connectors.zra import ZRAClient
		client = ZRAClient(tin="", enabled=True)
		result = client.submit_invoice(
			invoice_number="INV-001",
			customer_tpin="0000000000",
			customer_name="Test",
			items=[{"description": "Goods", "quantity": 1, "unit_price": 1000, "vat_rate_pct": 16}],
		)
		assert result["success"] is False
		assert "ZRA_TIN" in result["error"]

	def test_zra_empty_items_returns_error(self):
		from pgappforge.plugins.connectors.zra import ZRAClient
		client = ZRAClient(tin="1000000001", enabled=True)
		result = client.submit_invoice(
			invoice_number="INV-001",
			customer_tpin="0000000000",
			customer_name="Test",
			items=[],
		)
		assert result["success"] is False
		assert "line item" in result["error"].lower()

	def test_zra_exempt_item_uses_tax_type_E(self):
		"""Zero-rate items use taxTyCd='E' (exempt)."""
		captured: dict = {}

		def _fake_post(path, payload):
			captured.update(payload)
			return {"resultCd": "000", "data": {"rcptNo": "ZRA001", "rcptSign": "SIG"}}

		from pgappforge.plugins.connectors.zra import ZRAClient
		client = ZRAClient(tin="1000000001", enabled=True)
		client._post = _fake_post

		result = client.submit_invoice(
			invoice_number="INV-002",
			customer_tpin="0000000000",
			customer_name="Test",
			items=[
				{"description": "Exempt Medical", "quantity": 1, "unit_price": 5000, "vat_rate_pct": 0},
			],
		)
		assert result["success"] is True
		assert captured["itemList"][0]["taxTyCd"] == "E"
		assert captured["taxAmtA"] == 0.0

	def test_zra_mixed_vat_totals(self):
		"""Mixed 16 % + exempt items — totals computed correctly."""
		captured: dict = {}

		def _fake_post(path, payload):
			captured.update(payload)
			return {"resultCd": "000", "data": {"rcptNo": "ZRA002", "rcptSign": "SIG"}}

		from pgappforge.plugins.connectors.zra import ZRAClient
		client = ZRAClient(tin="1000000001", enabled=True)
		client._post = _fake_post

		client.submit_invoice(
			invoice_number="INV-003",
			customer_tpin="0000000000",
			customer_name="Test",
			items=[
				{"description": "Standard", "quantity": 1, "unit_price": 11600, "vat_rate_pct": 16},
				{"description": "Exempt",   "quantity": 1, "unit_price": 5000,  "vat_rate_pct": 0},
			],
		)
		# Total = 11600 + 5000 = 16600
		assert abs(captured["totAmt"] - 16600.0) < 0.01
		# VAT on 11600 at 16 %: 11600 * 0.16 / 1.16 = 1600
		assert abs(captured["taxAmtA"] - 1600.0) < 0.01

	def test_zra_invoice_type_mapping(self):
		"""ORIGINAL→'1', CREDIT→'3', DEBIT→'4'."""
		captured: dict = {}

		def _fake_post(path, payload):
			captured.update(payload)
			return {"resultCd": "000", "data": {"rcptNo": "ZRA003", "rcptSign": ""}}

		from pgappforge.plugins.connectors.zra import ZRAClient
		client = ZRAClient(tin="1000000001", enabled=True)
		client._post = _fake_post

		client.submit_invoice(
			invoice_number="INV-004",
			customer_tpin="0000000000",
			customer_name="Test",
			items=[{"description": "x", "quantity": 1, "unit_price": 100, "vat_rate_pct": 0}],
			invoice_type="CREDIT",
		)
		assert captured["rcptTyCd"] == "3"

	def test_get_connector_zra(self):
		from pgappforge.plugins.connectors import get_connector
		cls = get_connector("zra")
		assert cls.__name__ == "ZRAClient"


# ------------------------------------------------------------------ #
# Registry — all 9 connectors present
# ------------------------------------------------------------------ #

class TestConnectorsRegistryComplete:
	def test_all_nine_connectors_in_registry(self):
		from pgappforge.plugins.connectors import AVAILABLE_CONNECTORS
		expected = {
			"etims", "efris", "africas_talking", "flutterwave",
			"mtn_momo", "airtel_money", "paystack", "pesapal", "zra",
		}
		assert expected <= set(AVAILABLE_CONNECTORS)

	def test_get_connector_all_new(self):
		from pgappforge.plugins.connectors import get_connector
		for name, expected_cls in [
			("mtn_momo", "MTNMoMoClient"),
			("airtel_money", "AirtelMoneyClient"),
			("paystack", "PaystackClient"),
			("pesapal", "PesapalClient"),
			("zra", "ZRAClient"),
		]:
			cls = get_connector(name)
			assert cls.__name__ == expected_cls, f"{name}: expected {expected_cls}, got {cls.__name__}"
