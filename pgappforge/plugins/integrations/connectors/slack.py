"""Slack connector for Integration Hub."""
from __future__ import annotations
import hashlib
import hmac
import json
import time
import logging
from pgappforge.plugins.integrations.connectors.base import BaseConnector

log = logging.getLogger(__name__)


class SlackConnector(BaseConnector):
	"""Send messages to Slack channels and receive slash commands."""
	name = "slack"
	display_name = "Slack"
	icon = "fa-slack"
	auth_types = ["oauth2", "bearer"]

	def test_connection(self) -> dict:
		try:
			import requests
			token = self.credentials.get("access_token") or self.credentials.get("bot_token", "")
			resp = requests.get(
				"https://slack.com/api/auth.test",
				headers={"Authorization": f"Bearer {token}"},
				timeout=10,
			)
			data = resp.json()
			return {"ok": data.get("ok", False), "message": data.get("error", "Connected")}
		except Exception as exc:
			return {"ok": False, "message": str(exc)}

	def send_message(self, channel: str, text: str, blocks: list | None = None) -> dict:
		"""Send a message to a Slack channel."""
		try:
			import requests
			token = self.credentials.get("access_token") or self.credentials.get("bot_token", "")
			payload: dict = {"channel": channel, "text": text}
			if blocks:
				payload["blocks"] = blocks
			resp = requests.post(
				"https://slack.com/api/chat.postMessage",
				headers={
					"Authorization": f"Bearer {token}",
					"Content-Type": "application/json",
				},
				json=payload,
				timeout=10,
			)
			return resp.json()
		except Exception as exc:
			log.error("Slack send_message failed: %s", exc)
			return {"ok": False, "error": str(exc)}

	def handle_webhook(self, headers: dict, body: bytes) -> dict:
		"""Verify Slack signing secret and parse event."""
		signing_secret = self.credentials.get("signing_secret", "")
		if signing_secret:
			timestamp = headers.get("x-slack-request-timestamp", "")
			sig_header = headers.get("x-slack-signature", "")
			try:
				ts_int = int(timestamp)
			except (ValueError, TypeError):
				ts_int = 0
			if abs(time.time() - ts_int) > 300:
				return {"event_type": "expired", "data": {}}
			base = f"v0:{timestamp}:{body.decode('utf-8')}"
			computed = "v0=" + hmac.new(
				signing_secret.encode(), base.encode(), hashlib.sha256
			).hexdigest()
			if not hmac.compare_digest(computed, sig_header):
				return {"event_type": "invalid_signature", "data": {}}
		try:
			data = json.loads(body)
			return {"event_type": data.get("type", "unknown"), "data": data}
		except Exception:
			return {"event_type": "parse_error", "data": {}}

	@classmethod
	def get_oauth_authorize_url(cls, config: dict, redirect_uri: str, state: str) -> str:
		client_id = config.get("client_id", "")
		scopes = config.get("scopes", "chat:write,channels:read")
		return (
			f"https://slack.com/oauth/v2/authorize"
			f"?client_id={client_id}&scope={scopes}"
			f"&redirect_uri={redirect_uri}&state={state}"
		)

	@classmethod
	def exchange_oauth_code(cls, config: dict, code: str, redirect_uri: str) -> dict:
		import requests
		resp = requests.post(
			"https://slack.com/api/oauth.v2.access",
			data={
				"code": code,
				"redirect_uri": redirect_uri,
				"client_id": config["client_id"],
				"client_secret": config["client_secret"],
			},
			timeout=15,
		)
		return resp.json()
