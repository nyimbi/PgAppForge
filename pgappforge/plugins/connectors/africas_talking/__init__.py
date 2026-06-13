"""
pgappforge/plugins/connectors/africas_talking/__init__.py

Africa's Talking connector — SMS, USSD, Voice, Airtime across 18 African countries.

Quick start::

    from pgappforge.plugins.connectors.africas_talking import AfricasTalkingClient

    client = AfricasTalkingClient.from_config()    # reads AT_* from Flask config
    # OR
    client = AfricasTalkingClient.sandbox()        # AT sandbox

    # Send SMS
    result = client.send_sms("+254712345678", "Hello!")

    # Send OTP
    result = client.send_otp("+254712345678", "847291")

    # USSD response (call from your Flask/FastAPI webhook):
    response = client.handle_ussd_request(
        session_id=request.form["sessionId"],
        service_code=request.form["serviceCode"],
        phone_number=request.form["phoneNumber"],
        text=request.form["text"],
    )
    return response, 200, {"Content-Type": "text/plain"}

Flask config keys:
    AT_API_KEY       Africa's Talking API key (mandatory)
    AT_USERNAME      Username; use "sandbox" for testing
    AT_SENDER_ID     Alphanumeric sender ID (e.g. "MYAPP")
    AT_TIMEOUT       HTTP timeout seconds (default 30)
    AT_ENABLED       Set False to skip in dev (default True)
"""
from pgappforge.plugins.connectors.africas_talking.client import (
	AfricasTalkingClient,
	AfricasTalkingError,
)

__all__ = ["AfricasTalkingClient", "AfricasTalkingError"]
