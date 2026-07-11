"""
pgappforge/plugins/erp/platform/ai_assistant/schemas.py

Pydantic v2 schemas for AI assistant tool responses.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class ToolMetadata(BaseModel):
	model_config = ConfigDict(extra="forbid", validate_by_name=True)

	tenant_id: str | None
	query_time_ms: float


class ToolResponse(BaseModel):
	model_config = ConfigDict(extra="forbid", validate_by_name=True)

	tool: str
	success: bool
	data: dict[str, Any] | None
	error: str | None
	metadata: ToolMetadata


__all__ = ["ToolMetadata", "ToolResponse"]
