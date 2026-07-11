"""
pgappforge/plugins/erp/platform/workflow_dashboard/views.py

Cross-domain workflow status dashboards for P2P and O2C.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

import sqlalchemy as sa
from flask import jsonify, render_template_string, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _age_days(value: Any) -> int:
	if value is None:
		return 0
	if isinstance(value, datetime):
		if value.tzinfo is None:
			value = value.replace(tzinfo=timezone.utc)
		return max(0, (datetime.now(timezone.utc) - value).days)
	if isinstance(value, date):
		return max(0, (date.today() - value).days)
	return 0


def _age_color(max_age_days: int) -> str:
	if max_age_days > 14:
		return "red"
	if max_age_days > 7:
		return "orange"
	return "green"


def _metric(session: Any, model: type, date_col: Any, *criteria: Any) -> dict[str, Any]:
	rows = list(session.execute(sa.select(date_col).select_from(model).where(*criteria)).scalars().all())
	ages = [_age_days(row) for row in rows]
	max_age = max(ages) if ages else 0
	return {
		"count": len(rows),
		"max_age_days": max_age,
		"color": _age_color(max_age),
		"age_gt_7_days": sum(1 for age in ages if age > 7),
		"age_gt_14_days": sum(1 for age in ages if age > 14),
	}


def _render_dashboard(title: str, metrics: list[dict[str, Any]]) -> str:
	return render_template_string(
		_DASHBOARD_TEMPLATE,
		title=title,
		metrics=metrics,
	)


class PTPStatusView(BaseERPView):
	"""Procure-to-pay status dashboard."""

	route_base = "/platform/workflow-dashboard/ptp"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id", "")
		try:
			from pgappforge.plugins.erp.finance.ap.models import APInvoice
			from pgappforge.plugins.erp.operations.scm.models import (
				GoodsReceipt,
				PurchaseOrder,
				PurchaseRequisition,
				SupplierInvoice,
			)

			prq_filters = [PurchaseRequisition.status == "SUBMITTED"]
			po_filters = [PurchaseOrder.status.in_(["SENT", "ACKNOWLEDGED", "PARTIAL"])]
			gr_filters = [
				GoodsReceipt.status.in_(["CONFIRMED", "POSTED"]),
				~sa.exists().where(SupplierInvoice.grn_id == GoodsReceipt.id),
			]
			invoice_filters = [APInvoice.status.in_(["APPROVED", "PAYMENT_SCHEDULED"])]
			if tenant_id:
				prq_filters.append(PurchaseRequisition.tenant_id == tenant_id)
				po_filters.append(PurchaseOrder.tenant_id == tenant_id)
				gr_filters.append(GoodsReceipt.tenant_id == tenant_id)
				invoice_filters.append(APInvoice.tenant_id == tenant_id)

			metrics = [
				{"label": "PRQs pending approval", **_metric(session, PurchaseRequisition, PurchaseRequisition.created_at, *prq_filters)},
				{"label": "POs awaiting GR", **_metric(session, PurchaseOrder, PurchaseOrder.created_at, *po_filters)},
				{"label": "GRs awaiting invoice match", **_metric(session, GoodsReceipt, GoodsReceipt.created_at, *gr_filters)},
				{"label": "Invoices pending payment", **_metric(session, APInvoice, APInvoice.created_at, *invoice_filters)},
			]
		except Exception as exc:
			log.exception("PTPStatusView.index: failed to load status metrics")
			metrics = [{"label": "Dashboard error", "count": 0, "max_age_days": 0, "color": "red", "age_gt_7_days": 0, "age_gt_14_days": 0, "error": str(exc)}]

		if request.args.get("format") == "json":
			return jsonify({"dashboard": "ptp", "metrics": metrics})
		return _render_dashboard("P2P Workflow Status", metrics)


class OTCStatusView(BaseERPView):
	"""Order-to-cash status dashboard."""

	route_base = "/platform/workflow-dashboard/otc"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = self._session()
		tenant_id = request.args.get("tenant_id", "")
		try:
			from pgappforge.plugins.erp.crm.commerce.models import DeliveryOrder, Order
			from pgappforge.plugins.erp.finance.ar.models import ARInvoice

			order_filters = [Order.status.in_(["CONFIRMED", "PROCESSING"])]
			delivery_filters = [DeliveryOrder.status.in_(["READY_TO_PICK", "PICKED"])]
			invoice_filters = [ARInvoice.status == "DRAFT"]
			overdue_filters = [
				ARInvoice.status.in_(["ISSUED", "PARTIAL", "OVERDUE"]),
				ARInvoice.balance_due_cents > 0,
				ARInvoice.due_date < date.today(),
			]
			if tenant_id:
				order_filters.append(Order.tenant_id == tenant_id)
				delivery_filters.append(DeliveryOrder.tenant_id == tenant_id)
				invoice_filters.append(ARInvoice.tenant_id == tenant_id)
				overdue_filters.append(ARInvoice.tenant_id == tenant_id)

			metrics = [
				{"label": "Orders to pick", **_metric(session, Order, Order.created_at, *order_filters)},
				{"label": "Deliveries to ship", **_metric(session, DeliveryOrder, DeliveryOrder.created_at, *delivery_filters)},
				{"label": "Invoices to send", **_metric(session, ARInvoice, ARInvoice.created_at, *invoice_filters)},
				{"label": "Payments overdue", **_metric(session, ARInvoice, ARInvoice.due_date, *overdue_filters)},
			]
		except Exception as exc:
			log.exception("OTCStatusView.index: failed to load status metrics")
			metrics = [{"label": "Dashboard error", "count": 0, "max_age_days": 0, "color": "red", "age_gt_7_days": 0, "age_gt_14_days": 0, "error": str(exc)}]

		if request.args.get("format") == "json":
			return jsonify({"dashboard": "otc", "metrics": metrics})
		return _render_dashboard("O2C Workflow Status", metrics)


_DASHBOARD_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<title>{{ title }}</title>
	<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
	<style>
		body{padding:24px}
		.workflow-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px;margin-top:18px}
		.workflow-card{border:1px solid #ddd;border-left-width:6px;padding:14px;background:#fff}
		.workflow-card.green{border-left-color:#0e9f6e}
		.workflow-card.orange{border-left-color:#e3a008}
		.workflow-card.red{border-left-color:#c81e1e}
		.workflow-count{font-size:30px;font-weight:700;line-height:1}
		.workflow-label{font-weight:600;margin-top:6px}
		.workflow-age{color:#666;font-size:12px;margin-top:8px}
	</style>
</head>
<body>
	<h3>{{ title }}</h3>
	<div class="workflow-grid">
	{% for metric in metrics %}
		<div class="workflow-card {{ metric.color }}">
			<div class="workflow-count">{{ metric.count }}</div>
			<div class="workflow-label">{{ metric.label }}</div>
			<div class="workflow-age">
				Max age {{ metric.max_age_days }}d · &gt;7d {{ metric.age_gt_7_days }} · &gt;14d {{ metric.age_gt_14_days }}
			</div>
		</div>
	{% endfor %}
	</div>
</body>
</html>
"""


__all__ = ["PTPStatusView", "OTCStatusView"]
