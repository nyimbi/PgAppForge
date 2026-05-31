"""Integration Hub connectors package."""
from __future__ import annotations

from pgappforge.plugins.integrations.connectors.base import BaseConnector
from pgappforge.plugins.integrations.connectors.slack import SlackConnector

__all__ = ["BaseConnector", "SlackConnector"]
