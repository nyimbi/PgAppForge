"""Base connector ABC for Integration Hub."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseConnector(ABC):
	"""Abstract base class for all Integration Hub connectors.

	Each connector implements authentication, connection testing,
	object listing, and sync operations for a specific external service.
	"""

	name: str = ""           # connector identifier (e.g., "stripe")
	display_name: str = ""   # human label (e.g., "Stripe")
	icon: str = "fa-plug"    # FontAwesome icon
	auth_types: list[str] = []  # supported: oauth2 / api_key / basic / bearer

	def __init__(self, config: dict, credentials: dict):
		self.config = config
		self.credentials = credentials

	@abstractmethod
	def test_connection(self) -> dict:
		"""Test connectivity. Returns {"ok": bool, "message": str}."""

	def list_objects(self) -> list[str]:
		"""List syncable object types (e.g., ["Contact", "Opportunity"])."""
		return []

	def get_object_schema(self, object_type: str) -> list[dict]:
		"""Return field schema for an object type.

		Returns: [{name, type, required, label}]
		"""
		return []

	def sync_to_external(self, object_type: str, record: dict) -> dict:
		"""Push a pgappforge record to the external system.

		Returns: {"external_id": str, "status": str}
		"""
		raise NotImplementedError(f"{self.name} does not support push sync")

	def sync_from_external(self, object_type: str, since_cursor: Any = None) -> list[dict]:
		"""Pull records from the external system since cursor.

		Returns: list of records as dicts
		"""
		raise NotImplementedError(f"{self.name} does not support pull sync")

	def handle_webhook(self, headers: dict, body: bytes) -> dict:
		"""Process an inbound webhook payload.

		Verify signature and parse body.
		Returns: {"event_type": str, "data": dict}
		"""
		return {"event_type": "unknown", "data": {}}

	@classmethod
	def get_oauth_authorize_url(cls, config: dict, redirect_uri: str, state: str) -> str:
		"""Return the OAuth authorization URL for this connector."""
		raise NotImplementedError(f"{cls.name} does not support OAuth")

	@classmethod
	def exchange_oauth_code(cls, config: dict, code: str, redirect_uri: str) -> dict:
		"""Exchange OAuth code for tokens. Returns {"access_token", ...}."""
		raise NotImplementedError(f"{cls.name} does not support OAuth")
