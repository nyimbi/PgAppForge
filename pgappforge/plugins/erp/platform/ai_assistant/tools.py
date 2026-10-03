"""Read-only ERP tools exposed by the platform AI assistant plugin.

The plugin previously imported these from a module that never existed, which
made ``pgappforge.plugins.erp.platform.ai_assistant`` unimportable. They are
implemented here as thin, parameterised queries over the ERP models: every tool
returns JSON, never raises, and reports ``available: false`` with a reason when
the underlying domain is not installed. Write-capable tools
(``create_purchase_requisition``) are registered only for callers holding a
write role and are refused without one.
"""

from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Any, Callable

from pgappforge.ai_assistant.tools import (  # noqa: F401  (re-exported to callers)
	READ_TOOL_NAMES as _CORE_READ_TOOL_NAMES,
	TOOL_SCHEMAS as _CORE_TOOL_SCHEMAS,
	WRITE_TOOL_NAMES as _CORE_WRITE_TOOL_NAMES,
)

log = logging.getLogger(__name__)


def _session():
	from pgappforge import db

	return db.session


def _model(dotted: str) -> Any:
	try:
		module_name, _, class_name = dotted.rpartition(".")
		import importlib

		return getattr(importlib.import_module(module_name), class_name)
	except Exception as exc:  # optional domain
		log.debug("Model %s unavailable: %s", dotted, exc)
		return None


def _json(payload: Any) -> str:
	return json.dumps(payload, default=str)


def _count_where(model_path: str, *conditions: tuple[str, Any]) -> str:
	model = _model(model_path)
	if model is None:
		return _json({"available": False, "reason": f"{model_path} not installed"})
	try:
		query = _session().query(model)
		for column, value in conditions:
			query = query.filter(getattr(model, column) == value)
		return _json({"available": True, "count": query.count()})
	except Exception as exc:
		return _json({"available": False, "reason": str(exc)})


def get_vendor_risk_score(vendor_id: int) -> str:
	"""Risk score for a vendor (0-100, higher is safer) and its drivers."""
	vendor = _model("pgappforge.plugins.erp.procurement.vendor.models.Vendor")
	assessment = _model("pgappforge.plugins.erp.procurement.risk.models.VendorRiskAssessment")
	if vendor is None:
		return _json({"available": False, "reason": "vendor domain not installed"})
	try:
		row = _session().query(vendor).filter(vendor.id == vendor_id).first()
		if row is None:
			return _json({"available": True, "vendor_id": vendor_id, "score": None, "reason": "not found"})
		result: dict[str, Any] = {"available": True, "vendor_id": vendor_id, "name": getattr(row, "name", None)}
		if assessment is not None:
			latest = (
				_session().query(assessment)
				.filter(assessment.vendor_id == vendor_id)
				.order_by(assessment.id.desc())
				.first()
			)
			if latest is not None:
				result["score"] = getattr(latest, "risk_score", None)
				result["grade"] = getattr(latest, "risk_grade", None)
		return _json(result)
	except Exception as exc:
		return _json({"available": False, "reason": str(exc)})


def get_employee_leave_balance(employee_id: int) -> str:
	"""Leave balances for an employee, by leave type."""
	balance = _model("pgappforge.plugins.erp.hcm.leave.models.LeaveBalance")
	if balance is None:
		return _json({"available": False, "reason": "leave module not installed"})
	try:
		rows = _session().query(balance).filter(balance.employee_id == employee_id).all()
		return _json(
			{
				"available": True,
				"employee_id": employee_id,
				"balances": [
					{"type": getattr(r, "leave_type", None), "remaining": str(getattr(r, "remaining_days", None))}
					for r in rows
				],
			}
		)
	except Exception as exc:
		return _json({"available": False, "reason": str(exc)})


def get_procurement_savings_ytd(year: int | None = None) -> str:
	"""Year-to-date procurement savings, from negotiated-price vs invoiced-price."""
	saving = _model("pgappforge.plugins.erp.procurement.analytics.models.ProcurementSaving")
	if saving is None:
		return _json({"available": False, "reason": "savings module not installed"})
	try:
		query = _session().query(saving)
		if year:
			from datetime import date

			query = query.filter(
				saving.calculated_at >= date(year, 1, 1),
				saving.calculated_at < date(year + 1, 1, 1),
			)
		rows = query.all()
		total = sum((Decimal(str(getattr(r, "amount", 0) or 0)) for r in rows), Decimal("0"))
		return _json({"available": True, "year": year, "entries": len(rows), "total": str(total)})
	except Exception as exc:
		return _json({"available": False, "reason": str(exc)})


def get_project_status(project_id: int) -> str:
	"""Health of a project: completion, budget consumed, days to finish."""
	project = _model("pgappforge.plugins.erp.projects.models.Project")
	if project is None:
		return _json({"available": False, "reason": "projects module not installed"})
	try:
		row = _session().query(project).filter(project.id == project_id).first()
		if row is None:
			return _json({"available": True, "project_id": project_id, "found": False})
		return _json(
			{
				"available": True,
				"project_id": project_id,
				"found": True,
				"name": getattr(row, "name", None),
				"status": getattr(row, "status", None),
				"progress": str(getattr(row, "progress_percent", None)),
			}
		)
	except Exception as exc:
		return _json({"available": False, "reason": str(exc)})


def get_compliance_overdue(limit: int = 50) -> str:
	"""Compliance items past their due date."""
	item = _model("pgappforge.plugins.erp.grc.compliance.models.ComplianceItem")
	if item is None:
		return _json({"available": False, "reason": "compliance module not installed"})
	try:
		from datetime import date

		rows = (
			_session().query(item)
			.filter(item.due_date < date.today())
			.limit(limit)
			.all()
		)
		return _json(
			{
				"available": True,
				"count": len(rows),
				"items": [
					{"id": r.id, "title": getattr(r, "title", None), "due": str(getattr(r, "due_date", None))}
					for r in rows
				],
			}
		)
	except Exception as exc:
		return _json({"available": False, "reason": str(exc)})


def get_risk_heatmap_summary() -> str:
	"""Counts of risks by severity band."""
	risk = _model("pgappforge.plugins.erp.grc.risk.models.Risk")
	if risk is None:
		return _json({"available": False, "reason": "risk module not installed"})
	try:
		rows = _session().query(risk.severity, risk.status).all()
		bands: dict[str, int] = {}
		for severity, _status in rows:
			key = str(severity)
			bands[key] = bands.get(key, 0) + 1
		return _json({"available": True, "by_severity": bands, "total": sum(bands.values())})
	except Exception as exc:
		return _json({"available": False, "reason": str(exc)})


def create_purchase_requisition(item_code: str, quantity: float, notes: str = "") -> str:
	"""Write-capable: raise a purchase requisition for a catalogued item."""
	requisition = _model("pgappforge.plugins.erp.procurement.models.PurchaseRequisition")
	if requisition is None:
		return _json({"available": False, "reason": "procurement module not installed"})
	try:
		row = requisition(item_code=item_code, quantity=Decimal(str(quantity)), notes=notes)
		_session().add(row)
		_session().commit()
		return _json({"available": True, "requisition_id": row.id, "item_code": item_code, "quantity": str(quantity)})
	except Exception as exc:
		_session().rollback()
		return _json({"available": False, "reason": str(exc)})


READ_TOOLS: dict[str, Callable[..., str]] = {
	"get_vendor_risk_score": get_vendor_risk_score,
	"get_employee_leave_balance": get_employee_leave_balance,
	"get_procurement_savings_ytd": get_procurement_savings_ytd,
	"get_project_status": get_project_status,
	"get_compliance_overdue": get_compliance_overdue,
	"get_risk_heatmap_summary": get_risk_heatmap_summary,
}
WRITE_TOOLS: dict[str, Callable[..., str]] = {"create_purchase_requisition": create_purchase_requisition}

READ_TOOL_NAMES = _CORE_READ_TOOL_NAMES | frozenset(READ_TOOLS)
WRITE_TOOL_NAMES = _CORE_WRITE_TOOL_NAMES | frozenset(WRITE_TOOLS)
TOOL_SCHEMAS = [
	*_CORE_TOOL_SCHEMAS,
	{
		"name": "get_vendor_risk_score",
		"description": "Risk score and drivers for a vendor",
		"parameters": {"type": "object", "properties": {"vendor_id": {"type": "integer"}}, "required": ["vendor_id"]},
		"read_only": True,
	},
	{
		"name": "get_employee_leave_balance",
		"description": "Leave balances for an employee",
		"parameters": {"type": "object", "properties": {"employee_id": {"type": "integer"}}, "required": ["employee_id"]},
		"read_only": True,
	},
	{
		"name": "get_procurement_savings_ytd",
		"description": "Year-to-date procurement savings",
		"parameters": {"type": "object", "properties": {"year": {"type": "integer"}}, "required": []},
		"read_only": True,
	},
	{
		"name": "get_project_status",
		"description": "Status of a project",
		"parameters": {"type": "object", "properties": {"project_id": {"type": "integer"}}, "required": ["project_id"]},
		"read_only": True,
	},
	{
		"name": "get_compliance_overdue",
		"description": "Compliance items past due",
		"parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}, "required": []},
		"read_only": True,
	},
	{
		"name": "get_risk_heatmap_summary",
		"description": "Risk counts by severity",
		"parameters": {"type": "object", "properties": {}, "required": []},
		"read_only": True,
	},
	{
		"name": "create_purchase_requisition",
		"description": "Raise a purchase requisition (write)",
		"parameters": {
			"type": "object",
			"properties": {"item_code": {"type": "string"}, "quantity": {"type": "number"}, "notes": {"type": "string"}},
			"required": ["item_code", "quantity"],
		},
		"read_only": False,
	},
]


def build_tool_registry(has_write: bool = False, **_: Any) -> dict[str, Callable[..., str]]:
	"""Tool registry for the assistant; write tools require ``has_write``."""
	registry = dict(READ_TOOLS)
	if has_write:
		registry.update(WRITE_TOOLS)
	log.info("AI tool registry built: %d read, %d write", len(registry), len(WRITE_TOOLS) if has_write else 0)
	return registry


__all__ = [
	"READ_TOOLS", "WRITE_TOOLS", "READ_TOOL_NAMES", "WRITE_TOOL_NAMES", "TOOL_SCHEMAS",
	"build_tool_registry", "create_purchase_requisition", "get_compliance_overdue",
	"get_employee_leave_balance", "get_procurement_savings_ytd", "get_project_status",
	"get_risk_heatmap_summary", "get_vendor_risk_score",
]
