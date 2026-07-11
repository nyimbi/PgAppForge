"""
pgappforge/plugins/erp/crm/commerce/views.py

Flask views for the Commerce plugin.

Route summary
-------------
ShippingMethodView     /commerce/shipping-methods/
TaxRuleView            /commerce/tax-rules/
SubscriptionPlanView   /commerce/plans/
SubscriptionView       /commerce/subscriptions/
CommerceReportView     /commerce/reports/
  ├─ /mrr-arr            — MRR / ARR breakdown (HTML)
  ├─ /subscription-churn — Churn (CANCELLED) rate by plan (HTML)
  └─ /shipping-usage     — Shipping method usage counts (HTML)
"""
from __future__ import annotations

import logging
from datetime import date

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


def _get_session():
	try:
		from flask import current_app
		ab = current_app.extensions.get("appbuilder")
		if ab and hasattr(ab, "get_session"):
			return ab.get_session
		db = current_app.extensions.get("sqlalchemy")
		if db:
			return db.session
	except RuntimeError:
		pass
	raise RuntimeError("Cannot obtain database session")


def _he(s: object) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _cents(v: int | None) -> str:
	if v is None:
		return "—"
	return f"{v // 100:,}.{abs(v) % 100:02d}"


# ---------------------------------------------------------------------------
# SalesOrderView
# ---------------------------------------------------------------------------

class SalesOrderView(BaseView):
	"""Sales order list, detail, and workflow process action."""

	route_base = "/commerce/orders"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.commerce.models import Order
		session = _get_session()
		q = sa.select(Order).order_by(sa.desc(Order.created_at)).limit(500)
		if request.args.get("tenant_id"):
			q = q.where(Order.tenant_id == request.args["tenant_id"])
		if request.args.get("status"):
			q = q.where(Order.status == request.args["status"].upper())
		orders = session.execute(q).scalars().all()
		if request.args.get("format") == "json":
			return jsonify({"orders": [
				{
					"id": o.id,
					"order_number": o.order_number,
					"customer_id": o.customer_id,
					"status": o.status,
					"payment_status": o.payment_status,
					"total_cents": o.total_cents,
					"process_url": f"/commerce/orders/{o.id}/process",
				}
				for o in orders
			]})
		rows = "".join(
			f"<tr><td>{_he(o.order_number)}</td><td>{_he(o.customer_id)}</td>"
			f"<td>{_cents(o.total_cents)} {_he(o.currency_code if hasattr(o, 'currency_code') else '')}</td>"
			f"<td>{_he(o.status)}</td><td>{_he(o.payment_status)}</td>"
			f"<td><a href='/commerce/orders/{_he(o.id)}' class='btn btn-xs btn-primary'>View</a> "
			f"<form method='post' action='/commerce/orders/{_he(o.id)}/process' style='display:inline'>"
			f"<button type='submit' class='btn btn-xs btn-default'>Process</button></form></td></tr>"
			for o in orders
		)
		return make_response(
			f"<html><body><h2>Sales Orders</h2><table border='1'>"
			f"<tr><th>Order</th><th>Customer</th><th>Total</th><th>Status</th><th>Payment</th><th></th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/<string:order_id>")
	@has_access
	def detail(self, order_id: str):
		from pgappforge.plugins.erp.crm.commerce.models import Order
		session = _get_session()
		order = session.get(Order, order_id)
		if order is None:
			abort(404)
		return jsonify({
			"id": order.id,
			"order_number": order.order_number,
			"customer_id": order.customer_id,
			"status": order.status,
			"payment_status": order.payment_status,
			"total_cents": order.total_cents,
			"delivery_orders": [
				{
					"id": delivery.id,
					"delivery_number": delivery.delivery_number,
					"status": delivery.status,
					"process_url": f"/commerce/deliveries/{delivery.id}/process",
				}
				for delivery in order.delivery_orders
			],
		})

	@expose("/<string:order_id>/process", methods=["POST"])
	@has_access
	def process(self, order_id: str):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceError, CommerceService
		session = _get_session()
		try:
			record = CommerceService().advance_to_next_step(order_id, session)
			session.commit()
			return jsonify({
				"ok": True,
				"id": record.id,
				"type": record.__class__.__name__,
				"status": getattr(record, "status", None),
			})
		except CommerceError as exc:
			session.rollback()
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# DeliveryOrderView
# ---------------------------------------------------------------------------

class DeliveryOrderView(BaseView):
	"""Delivery order list, create, detail, and workflow process action."""

	route_base = "/commerce/deliveries"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.commerce.models import DeliveryOrder
		session = _get_session()
		q = sa.select(DeliveryOrder).order_by(sa.desc(DeliveryOrder.created_at)).limit(500)
		if request.args.get("tenant_id"):
			q = q.where(DeliveryOrder.tenant_id == request.args["tenant_id"])
		if request.args.get("status"):
			q = q.where(DeliveryOrder.status == request.args["status"].upper())
		deliveries = session.execute(q).scalars().all()
		if request.args.get("format") == "json":
			return jsonify({"deliveries": [
				{
					"id": d.id,
					"delivery_number": d.delivery_number,
					"sales_order_id": d.sales_order_id,
					"customer_id": d.customer_id,
					"delivery_date": d.delivery_date.isoformat() if d.delivery_date else None,
					"status": d.status,
					"process_url": f"/commerce/deliveries/{d.id}/process",
				}
				for d in deliveries
			]})
		rows = "".join(
			f"<tr><td>{_he(d.delivery_number)}</td><td>{_he(d.sales_order_id)}</td>"
			f"<td>{_he(d.delivery_date or '')}</td><td>{_he(d.status)}</td>"
			f"<td><a href='/commerce/deliveries/{_he(d.id)}' class='btn btn-xs btn-primary'>View</a> "
			f"<form method='post' action='/commerce/deliveries/{_he(d.id)}/process' style='display:inline'>"
			f"<button type='submit' class='btn btn-xs btn-default'>Process</button></form></td></tr>"
			for d in deliveries
		)
		return make_response(
			f"<html><body><h2>Delivery Orders</h2><table border='1'>"
			f"<tr><th>Delivery</th><th>Sales Order</th><th>Date</th><th>Status</th><th></th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceError, CommerceService
		data = request.get_json(silent=True) or {}
		if not data.get("order_id"):
			return jsonify({"ok": False, "error": "order_id required"}), 400
		session = _get_session()
		delivery_date = date.fromisoformat(data["delivery_date"]) if data.get("delivery_date") else None
		try:
			delivery = CommerceService().create_delivery_order(
				data["order_id"],
				session,
				tenant_id=data.get("tenant_id", ""),
				delivery_date=delivery_date,
				warehouse_id=data.get("warehouse_id"),
				carrier=data.get("carrier"),
			)
			session.commit()
			return jsonify({"ok": True, "id": delivery.id, "status": delivery.status}), 201
		except CommerceError as exc:
			session.rollback()
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:delivery_id>")
	@has_access
	def detail(self, delivery_id: str):
		from pgappforge.plugins.erp.crm.commerce.models import DeliveryOrder
		session = _get_session()
		delivery = session.get(DeliveryOrder, delivery_id)
		if delivery is None:
			abort(404)
		return jsonify({
			"id": delivery.id,
			"delivery_number": delivery.delivery_number,
			"sales_order_id": delivery.sales_order_id,
			"customer_id": delivery.customer_id,
			"delivery_date": delivery.delivery_date.isoformat() if delivery.delivery_date else None,
			"warehouse_id": delivery.warehouse_id,
			"carrier": delivery.carrier,
			"tracking_number": delivery.tracking_number,
			"status": delivery.status,
			"picked_at": delivery.picked_at.isoformat() if delivery.picked_at else None,
			"shipped_at": delivery.shipped_at.isoformat() if delivery.shipped_at else None,
			"delivered_at": delivery.delivered_at.isoformat() if delivery.delivered_at else None,
		})

	@expose("/<string:delivery_id>/process", methods=["POST"])
	@has_access
	def process(self, delivery_id: str):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceError, CommerceService
		session = _get_session()
		try:
			delivery = CommerceService().advance_to_next_step(delivery_id, session)
			session.commit()
			return jsonify({"ok": True, "id": delivery.id, "status": delivery.status})
		except CommerceError as exc:
			session.rollback()
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# ShippingMethodView
# ---------------------------------------------------------------------------

class ShippingMethodView(BaseView):
	"""Shipping Method CRUD."""

	route_base = "/commerce/shipping-methods"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.commerce.models import ShippingMethod
		session = _get_session()
		methods = session.execute(
			sa.select(ShippingMethod).order_by(ShippingMethod.cost_cents)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(m.name)}</td><td>{_he(m.carrier)}</td>"
			f"<td>{_he(m.service_level or '')}</td><td>{_cents(m.cost_cents)}</td>"
			f"<td>{m.delivery_days_min}-{m.delivery_days_max}d</td>"
			f"<td>{'Active' if m.is_active else 'Inactive'}</td></tr>"
			for m in methods
		)
		return make_response(
			f"<html><body><h2>Shipping Methods</h2><table border='1'>"
			f"<tr><th>Name</th><th>Carrier</th><th>Service</th><th>Cost</th><th>Delivery</th><th>Status</th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.crm.commerce.models import ShippingMethod
		data = request.get_json(force=True) or {}
		for f in ("tenant_id", "name", "carrier", "cost_cents"):
			if not data.get(f) and data.get(f) != 0:
				return jsonify({"error": f"Missing field: {f}"}), 400
		session = _get_session()
		method = ShippingMethod(
			tenant_id=data["tenant_id"],
			name=data["name"],
			carrier=data["carrier"],
			service_level=data.get("service_level"),
			cost_cents=data["cost_cents"],
			free_threshold_cents=data.get("free_threshold_cents"),
			delivery_days_min=data.get("delivery_days_min", 1),
			delivery_days_max=data.get("delivery_days_max", 7),
			is_active=data.get("is_active", True),
		)
		session.add(method)
		session.commit()
		return jsonify({"id": method.id, "name": method.name}), 201

	@expose("/<string:method_id>/apply-cost", methods=["POST"])
	@has_access
	def apply_cost(self, method_id: str):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceService, ShippingMethodNotFoundError
		data = request.get_json(force=True) or {}
		subtotal = data.get("order_subtotal_cents", 0)
		session = _get_session()
		try:
			cost = CommerceService.apply_shipping_cost(subtotal, method_id, session)
			return jsonify({"shipping_cost_cents": cost})
		except ShippingMethodNotFoundError:
			return jsonify({"error": "Shipping method not found or inactive"}), 404


# ---------------------------------------------------------------------------
# TaxRuleView
# ---------------------------------------------------------------------------

class TaxRuleView(BaseView):
	"""Tax Rule CRUD + compute endpoint."""

	route_base = "/commerce/tax-rules"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.commerce.models import TaxRule
		session = _get_session()
		rules = session.execute(
			sa.select(TaxRule).order_by(TaxRule.jurisdiction_code, TaxRule.product_category)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(r.jurisdiction_code)}</td><td>{_he(r.product_category)}</td>"
			f"<td>{_he(r.tax_name)}</td><td>{float(r.tax_rate) * 100:.2f}%</td>"
			f"<td>{'Yes' if r.is_inclusive else 'No'}</td></tr>"
			for r in rules
		)
		return make_response(
			f"<html><body><h2>Tax Rules</h2><table border='1'>"
			f"<tr><th>Jurisdiction</th><th>Category</th><th>Name</th><th>Rate</th><th>Inclusive</th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/compute", methods=["POST"])
	@has_access
	def compute(self):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceService
		data = request.get_json(force=True) or {}
		session = _get_session()
		result = CommerceService.compute_tax(
			data.get("subtotal_cents", 0),
			data.get("jurisdiction_code", ""),
			data.get("product_category", "*"),
			session,
		)
		return jsonify({
			"tax_cents": result["tax_cents"],
			"tax_rate": str(result["tax_rate"]),
			"tax_name": result["tax_name"],
			"is_inclusive": result["is_inclusive"],
		})


# ---------------------------------------------------------------------------
# SubscriptionPlanView
# ---------------------------------------------------------------------------

class SubscriptionPlanView(BaseView):
	"""Subscription Plan CRUD."""

	route_base = "/commerce/plans"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.commerce.models import SubscriptionPlan
		session = _get_session()
		plans = session.execute(
			sa.select(SubscriptionPlan).order_by(SubscriptionPlan.amount_cents)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(p.name)}</td><td>{_cents(p.amount_cents)} {_he(p.currency_code)}</td>"
			f"<td>{p.interval_months}mo</td><td>{p.trial_days}d trial</td></tr>"
			for p in plans
		)
		return make_response(
			f"<html><body><h2>Subscription Plans</h2><table border='1'>"
			f"<tr><th>Name</th><th>Amount</th><th>Interval</th><th>Trial</th></tr>"
			f"{rows}</table></body></html>"
		)


# ---------------------------------------------------------------------------
# SubscriptionView
# ---------------------------------------------------------------------------

class SubscriptionView(BaseView):
	"""Subscription lifecycle endpoints."""

	route_base = "/commerce/subscriptions"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.crm.commerce.models import Subscription
		session = _get_session()
		subs = session.execute(
			sa.select(Subscription).order_by(Subscription.created_at.desc()).limit(200)
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(s.id[:8])}</td><td>{_he(s.customer_id[:8])}</td>"
			f"<td>{_he(s.status)}</td><td>{_cents(s.amount_cents)} {_he(s.currency_code)}</td>"
			f"<td>{_he(s.billing_interval)}</td>"
			f"<td>{_he(str(s.next_billing_date) if s.next_billing_date else '')}</td></tr>"
			for s in subs
		)
		return make_response(
			f"<html><body><h2>Subscriptions</h2><table border='1'>"
			f"<tr><th>ID</th><th>Customer</th><th>Status</th><th>Amount</th><th>Interval</th><th>Next Billing</th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceService, PlanNotFoundError, CommerceValidationError
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			sub = CommerceService.create_subscription(data, session)
			session.commit()
			return jsonify({
				"id": sub.id,
				"status": sub.status,
				"next_billing_date": sub.next_billing_date.isoformat() if sub.next_billing_date else None,
			}), 201
		except PlanNotFoundError:
			return jsonify({"error": "Plan not found"}), 404
		except (CommerceValidationError, KeyError) as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:sub_id>/cancel", methods=["POST"])
	@has_access
	def cancel(self, sub_id: str):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceService, SubscriptionNotFoundError
		data = request.get_json(force=True) or {}
		session = _get_session()
		try:
			sub = CommerceService.cancel_subscription(sub_id, data.get("reason", ""), session)
			session.commit()
			return jsonify({"id": sub.id, "status": sub.status})
		except SubscriptionNotFoundError:
			return jsonify({"error": "Subscription not found"}), 404

	@expose("/<string:sub_id>/pause", methods=["POST"])
	@has_access
	def pause(self, sub_id: str):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceService, SubscriptionNotFoundError, CommerceValidationError
		session = _get_session()
		try:
			sub = CommerceService.pause_subscription(sub_id, session)
			session.commit()
			return jsonify({"id": sub.id, "status": sub.status})
		except SubscriptionNotFoundError:
			return jsonify({"error": "Subscription not found"}), 404
		except CommerceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:sub_id>/resume", methods=["POST"])
	@has_access
	def resume(self, sub_id: str):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceService, SubscriptionNotFoundError, CommerceValidationError
		from datetime import date
		data = request.get_json(force=True) or {}
		new_date_str = data.get("new_billing_date", date.today().isoformat())
		session = _get_session()
		try:
			sub = CommerceService.resume_subscription(sub_id, date.fromisoformat(new_date_str), session)
			session.commit()
			return jsonify({"id": sub.id, "status": sub.status, "next_billing_date": str(sub.next_billing_date)})
		except SubscriptionNotFoundError:
			return jsonify({"error": "Subscription not found"}), 404
		except CommerceValidationError as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422

	@expose("/<string:sub_id>/renew", methods=["POST"])
	@has_access
	def renew(self, sub_id: str):
		from pgappforge.plugins.erp.crm.commerce.services import (
			CommerceService, SubscriptionNotFoundError, PlanNotFoundError, CommerceValidationError,
		)
		session = _get_session()
		try:
			sub = CommerceService.process_renewal(sub_id, session)
			session.commit()
			return jsonify({"id": sub.id, "status": sub.status, "next_billing_date": str(sub.next_billing_date)})
		except SubscriptionNotFoundError:
			return jsonify({"error": "Subscription not found"}), 404
		except (PlanNotFoundError, CommerceValidationError) as exc:
			session.rollback()
			return jsonify({"error": str(exc)}), 422


# ---------------------------------------------------------------------------
# CommerceReportView — 3 ReportForge-compatible report endpoints
# ---------------------------------------------------------------------------

class CommerceReportView(BaseView):
	"""Commerce reports."""

	route_base = "/commerce/reports"

	@expose("/mrr-arr")
	@has_access
	def mrr_arr(self):
		from pgappforge.plugins.erp.crm.commerce.services import CommerceService
		tenant_id = request.args.get("tenant_id", "")
		session = _get_session()
		report = CommerceService.subscription_revenue_report(tenant_id, session)
		by_status_rows = "".join(
			f"<tr><td>{_he(s)}</td><td>{cnt}</td></tr>"
			for s, cnt in report["by_status"].items()
		)
		return make_response(
			f"<html><body><h2>MRR / ARR</h2>"
			f"<p>MRR: <strong>{_cents(report['mrr_cents'])}</strong></p>"
			f"<p>ARR: <strong>{_cents(report['arr_cents'])}</strong></p>"
			f"<h3>Subscribers by Status</h3>"
			f"<table border='1'><tr><th>Status</th><th>Count</th></tr>{by_status_rows}</table>"
			f"</body></html>"
		)

	@expose("/subscription-churn")
	@has_access
	def subscription_churn(self):
		from pgappforge.plugins.erp.crm.commerce.models import Subscription, SubscriptionPlan
		import sqlalchemy.func as func
		session = _get_session()
		rows_data = session.execute(
			sa.select(
				SubscriptionPlan.name.label("plan_name"),
				Subscription.status,
				func.count(Subscription.id).label("cnt"),
			)
			.join(SubscriptionPlan, SubscriptionPlan.id == Subscription.plan_id)
			.group_by(SubscriptionPlan.name, Subscription.status)
		).all()

		by_plan: dict[str, dict[str, int]] = {}
		for r in rows_data:
			by_plan.setdefault(r.plan_name, {})[r.status] = r.cnt

		rows = ""
		for plan_name, counts in sorted(by_plan.items()):
			total = sum(counts.values())
			cancelled = counts.get("CANCELLED", 0)
			churn_pct = round(cancelled / total * 100, 1) if total else 0
			rows += f"<tr><td>{_he(plan_name)}</td><td>{total}</td><td>{cancelled}</td><td>{churn_pct}%</td></tr>"

		return make_response(
			f"<html><body><h2>Subscription Churn by Plan</h2><table border='1'>"
			f"<tr><th>Plan</th><th>Total</th><th>Cancelled</th><th>Churn Rate</th></tr>"
			f"{rows}</table></body></html>"
		)

	@expose("/shipping-usage")
	@has_access
	def shipping_usage(self):
		from pgappforge.plugins.erp.crm.commerce.models import ShippingMethod
		session = _get_session()
		# Stub — real impl joins to order table
		methods = session.execute(
			sa.select(ShippingMethod).where(ShippingMethod.is_active == True)  # noqa: E712
		).scalars().all()
		rows = "".join(
			f"<tr><td>{_he(m.name)}</td><td>{_he(m.carrier)}</td>"
			f"<td>{_cents(m.cost_cents)}</td><td>—</td></tr>"
			for m in methods
		)
		return make_response(
			f"<html><body><h2>Shipping Method Usage</h2><table border='1'>"
			f"<tr><th>Method</th><th>Carrier</th><th>Cost</th><th>Orders</th></tr>"
			f"{rows}<p><em>Order count requires order table integration.</em></p>"
			f"</table></body></html>"
		)
