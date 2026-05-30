"""
pgappforge/plugins/billing/views.py

Bootstrap 3 admin views and REST/webhook endpoints for the billing plugin.

Views
-----
BillingDashboardView  /billing/           — MRR, churn, active subs, plan revenue
SubscriptionListView  /billing/subs/      — paginated subscription list
InvoiceView           /billing/invoices/  — invoice list + PDF download
UsageView             /billing/usage/     — per-subscription usage metrics
DunningView           /billing/dunning/   — dunning queue + retry controls

REST endpoints (JSON)
---------------------
POST /billing/api/subscribe
POST /billing/api/cancel
POST /billing/api/usage
GET  /billing/api/invoice/<id>/pdf
POST /billing/webhooks/stripe
"""
from __future__ import annotations

import io
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from flask import (
	Response,
	current_app,
	flash,
	jsonify,
	redirect,
	render_template_string,
	request,
	url_for,
)
from sqlalchemy import func, select

from pgappforge import BaseView, expose, has_access

from .engine import BillingEngine, BillingError, SubscriptionNotFound, PlanNotFound
from .models import (
	Coupon,
	DunningAttempt,
	DunningStatus,
	Invoice,
	InvoiceStatus,
	Plan,
	Subscription,
	SubscriptionStatus,
	UsageRecord,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stripe optional import
# ---------------------------------------------------------------------------

try:
	import stripe as _stripe
	_HAS_STRIPE = True
except ImportError:
	_stripe = None  # type: ignore[assignment]
	_HAS_STRIPE = False

# ---------------------------------------------------------------------------
# PDF optional import (reportlab)
# ---------------------------------------------------------------------------

try:
	from reportlab.lib.pagesizes import A4
	from reportlab.pdfgen import canvas as _rl_canvas
	_HAS_REPORTLAB = True
except ImportError:
	_HAS_REPORTLAB = False

# ---------------------------------------------------------------------------
# Shared Bootstrap 3 shell template
# ---------------------------------------------------------------------------

_BASE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ page_title }} — Billing</title>
  <link rel="stylesheet"
    href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
  <link rel="stylesheet"
    href="https://maxcdn.bootstrapcdn.com/font-awesome/4.7.0/css/font-awesome.min.css">
  <style>
    body { padding-top: 20px; }
    .stat-box { text-align: center; padding: 20px 0; }
    .stat-box .stat-value { font-size: 2.5em; font-weight: bold; }
    .stat-box .stat-label { color: #777; font-size: 0.9em; text-transform: uppercase; }
    .badge-trialing  { background-color: #5bc0de; }
    .badge-active    { background-color: #5cb85c; }
    .badge-past_due  { background-color: #f0ad4e; }
    .badge-canceled  { background-color: #d9534f; }
    .badge-paused    { background-color: #777; }
    .badge-paid      { background-color: #5cb85c; }
    .badge-open      { background-color: #f0ad4e; }
    .badge-draft     { background-color: #aaa; }
    .badge-void      { background-color: #d9534f; }
    .billing-nav { margin-bottom: 20px; }
    .chart-placeholder {
      background: #f9f9f9; border: 1px dashed #ccc;
      height: 200px; display: flex; align-items: center;
      justify-content: center; color: #aaa; font-size: 1.1em;
      border-radius: 4px;
    }
  </style>
</head>
<body>
<div class="container-fluid">
  <div class="row billing-nav">
    <div class="col-sm-12">
      <ul class="nav nav-pills">
        <li {% if active_tab == 'dashboard' %}class="active"{% endif %}>
          <a href="{{ url_for('BillingDashboardView.index') }}">
            <i class="fa fa-tachometer"></i> Dashboard
          </a>
        </li>
        <li {% if active_tab == 'subscriptions' %}class="active"{% endif %}>
          <a href="{{ url_for('SubscriptionListView.index') }}">
            <i class="fa fa-users"></i> Subscriptions
          </a>
        </li>
        <li {% if active_tab == 'invoices' %}class="active"{% endif %}>
          <a href="{{ url_for('InvoiceView.index') }}">
            <i class="fa fa-file-text-o"></i> Invoices
          </a>
        </li>
        <li {% if active_tab == 'usage' %}class="active"{% endif %}>
          <a href="{{ url_for('UsageView.index') }}">
            <i class="fa fa-bar-chart"></i> Usage
          </a>
        </li>
        <li {% if active_tab == 'dunning' %}class="active"{% endif %}>
          <a href="{{ url_for('DunningView.index') }}">
            <i class="fa fa-exclamation-triangle"></i> Dunning
          </a>
        </li>
      </ul>
    </div>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for category, message in messages %}
    <div class="alert alert-{{ category }} alert-dismissible">
      <button type="button" class="close" data-dismiss="alert">&times;</button>
      {{ message }}
    </div>
    {% endfor %}
  {% endwith %}

  {{ content | safe }}

</div>
<script src="https://code.jquery.com/jquery-1.12.4.min.js"></script>
<script src="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/js/bootstrap.min.js"></script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Helper: get engine and session from current app context
# ---------------------------------------------------------------------------

def _get_engine() -> BillingEngine:
	"""Return (or lazily create) the BillingEngine stored on the app."""
	app = current_app._get_current_object()
	if not hasattr(app, "_billing_engine"):
		key = app.config.get("FAB_BILLING_STRIPE_SECRET_KEY")
		currency = app.config.get("FAB_BILLING_CURRENCY", "USD")
		app._billing_engine = BillingEngine(
			stripe_secret_key=key,
			default_currency=currency,
		)
	return app._billing_engine


def _get_session():
	"""Return the SQLAlchemy session from the app context."""
	from flask import current_app as _app
	return _app.appbuilder.get_session


def _render(template_content: str, **ctx) -> str:
	return render_template_string(
		_BASE_TEMPLATE.replace("{{ content | safe }}", template_content),
		**ctx,
	)


def _status_badge(status: str) -> str:
	return f'<span class="badge badge-{status}">{status.replace("_", " ").title()}</span>'


# ---------------------------------------------------------------------------
# BillingDashboardView
# ---------------------------------------------------------------------------

_DASHBOARD_CONTENT = """
<div class="page-header">
  <h2><i class="fa fa-tachometer"></i> Billing Dashboard</h2>
</div>

<!-- KPI row -->
<div class="row">
  <div class="col-sm-3">
    <div class="panel panel-success">
      <div class="panel-body stat-box">
        <div class="stat-value text-success">${{ mrr }}</div>
        <div class="stat-label">Monthly Recurring Revenue</div>
      </div>
    </div>
  </div>
  <div class="col-sm-3">
    <div class="panel panel-primary">
      <div class="panel-body stat-box">
        <div class="stat-value text-primary">{{ active_count }}</div>
        <div class="stat-label">Active Subscriptions</div>
      </div>
    </div>
  </div>
  <div class="col-sm-3">
    <div class="panel panel-warning">
      <div class="panel-body stat-box">
        <div class="stat-value text-warning">{{ trial_count }}</div>
        <div class="stat-label">Trialing</div>
      </div>
    </div>
  </div>
  <div class="col-sm-3">
    <div class="panel panel-danger">
      <div class="panel-body stat-box">
        <div class="stat-value text-danger">{{ churn_count }}</div>
        <div class="stat-label">Canceled (30d)</div>
      </div>
    </div>
  </div>
</div>

<!-- Revenue by plan -->
<div class="row">
  <div class="col-sm-6">
    <div class="panel panel-default">
      <div class="panel-heading"><h4>Revenue by Plan</h4></div>
      <div class="panel-body">
        <table class="table table-condensed">
          <thead><tr><th>Plan</th><th>Active Subs</th><th>MRR</th></tr></thead>
          <tbody>
            {% for row in plan_revenue %}
            <tr>
              <td>{{ row.plan_name }}</td>
              <td>{{ row.count }}</td>
              <td>${{ row.mrr }}</td>
            </tr>
            {% else %}
            <tr><td colspan="3" class="text-muted text-center">No data</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
  <div class="col-sm-6">
    <div class="panel panel-default">
      <div class="panel-heading"><h4>MRR Trend (placeholder)</h4></div>
      <div class="panel-body">
        <div class="chart-placeholder">
          Chart requires a JS charting library (e.g. Chart.js)
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Recent invoices -->
<div class="row">
  <div class="col-sm-12">
    <div class="panel panel-default">
      <div class="panel-heading"><h4>Recent Open Invoices</h4></div>
      <div class="panel-body">
        <table class="table table-hover table-condensed">
          <thead>
            <tr>
              <th>#</th><th>Subscription</th><th>Amount</th>
              <th>Due</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {% for inv in recent_invoices %}
            <tr>
              <td>{{ inv.id }}</td>
              <td>{{ inv.subscription_id }}</td>
              <td>${{ "%.2f"|format(inv.amount_cents / 100) }}</td>
              <td>{{ inv.due_date.strftime('%Y-%m-%d') if inv.due_date else '—' }}</td>
              <td>{{ inv.status }}</td>
            </tr>
            {% else %}
            <tr><td colspan="5" class="text-muted text-center">No open invoices</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</div>
"""


class BillingDashboardView(BaseView):
	route_base = "/billing"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		session = _get_engine()  # just validate app is ready
		db = _get_session()

		# Active / trialing counts
		active_count = db.execute(
			select(func.count(Subscription.id)).where(
				Subscription.status == SubscriptionStatus.ACTIVE.value
			)
		).scalar() or 0

		trial_count = db.execute(
			select(func.count(Subscription.id)).where(
				Subscription.status == SubscriptionStatus.TRIALING.value
			)
		).scalar() or 0

		thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)
		churn_count = db.execute(
			select(func.count(Subscription.id)).where(
				Subscription.status == SubscriptionStatus.CANCELED.value,
				Subscription.updated_at >= thirty_days_ago,
			)
		).scalar() or 0

		# MRR: sum price_cents for all active monthly subs; annual / 12
		active_subs = db.execute(
			select(Subscription).where(
				Subscription.status == SubscriptionStatus.ACTIVE.value
			)
		).scalars().all()

		mrr_cents = 0
		for sub in active_subs:
			if sub.plan:
				if sub.plan.interval == "monthly":
					mrr_cents += sub.plan.price_cents
				elif sub.plan.interval == "annual":
					mrr_cents += sub.plan.price_cents // 12
		mrr = f"{mrr_cents / 100:.2f}"

		# Revenue by plan
		plans = db.execute(select(Plan).where(Plan.is_active == True)).scalars().all()  # noqa: E712
		plan_revenue = []
		for plan in plans:
			cnt = db.execute(
				select(func.count(Subscription.id)).where(
					Subscription.plan_id == plan.id,
					Subscription.status == SubscriptionStatus.ACTIVE.value,
				)
			).scalar() or 0
			if plan.interval == "monthly":
				plan_mrr = plan.price_cents * cnt // 100
			elif plan.interval == "annual":
				plan_mrr = plan.price_cents * cnt // 12 // 100
			else:
				plan_mrr = 0
			plan_revenue.append({
				"plan_name": plan.name,
				"count": cnt,
				"mrr": f"{plan_mrr:.2f}",
			})

		recent_invoices = db.execute(
			select(Invoice).where(
				Invoice.status == InvoiceStatus.OPEN.value
			).order_by(Invoice.created_at.desc()).limit(10)
		).scalars().all()

		content = render_template_string(
			_DASHBOARD_CONTENT,
			mrr=mrr,
			active_count=active_count,
			trial_count=trial_count,
			churn_count=churn_count,
			plan_revenue=plan_revenue,
			recent_invoices=recent_invoices,
			active_tab="dashboard",
		)
		return render_template_string(
			_BASE_TEMPLATE,
			content=content,
			page_title="Billing Dashboard",
			active_tab="dashboard",
		)


# ---------------------------------------------------------------------------
# SubscriptionListView
# ---------------------------------------------------------------------------

_SUB_LIST_CONTENT = """
<div class="page-header">
  <h2><i class="fa fa-users"></i> Subscriptions</h2>
</div>
<div class="panel panel-default">
  <div class="panel-body">
    <table class="table table-hover table-striped">
      <thead>
        <tr>
          <th>#</th><th>Tenant</th><th>Plan</th><th>Status</th>
          <th>Period Start</th><th>Period End</th><th>Trial End</th>
          <th>Cancel at End</th>
        </tr>
      </thead>
      <tbody>
        {% for sub in subscriptions %}
        <tr>
          <td>{{ sub.id }}</td>
          <td>{{ sub.tenant_id }}</td>
          <td>{{ sub.plan.name if sub.plan else '—' }}</td>
          <td><span class="badge badge-{{ sub.status }}">{{ sub.status }}</span></td>
          <td>{{ sub.current_period_start.strftime('%Y-%m-%d') if sub.current_period_start else '—' }}</td>
          <td>{{ sub.current_period_end.strftime('%Y-%m-%d') if sub.current_period_end else '—' }}</td>
          <td>{{ sub.trial_end.strftime('%Y-%m-%d') if sub.trial_end else '—' }}</td>
          <td>
            {% if sub.cancel_at_period_end %}
              <span class="label label-warning">Yes</span>
            {% else %}
              <span class="label label-success">No</span>
            {% endif %}
          </td>
        </tr>
        {% else %}
        <tr><td colspan="8" class="text-muted text-center">No subscriptions found</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
"""


class SubscriptionListView(BaseView):
	route_base = "/billing/subs"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		db = _get_session()
		subscriptions = db.execute(
			select(Subscription).order_by(Subscription.id.desc()).limit(200)
		).scalars().all()

		content = render_template_string(
			_SUB_LIST_CONTENT,
			subscriptions=subscriptions,
		)
		return render_template_string(
			_BASE_TEMPLATE,
			content=content,
			page_title="Subscriptions",
			active_tab="subscriptions",
		)


# ---------------------------------------------------------------------------
# InvoiceView
# ---------------------------------------------------------------------------

_INVOICE_LIST_CONTENT = """
<div class="page-header">
  <h2><i class="fa fa-file-text-o"></i> Invoices</h2>
</div>
<div class="panel panel-default">
  <div class="panel-body">
    <table class="table table-hover table-striped">
      <thead>
        <tr>
          <th>#</th><th>Subscription</th><th>Amount</th><th>Currency</th>
          <th>Status</th><th>Due</th><th>Paid At</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {% for inv in invoices %}
        <tr>
          <td>{{ inv.id }}</td>
          <td>{{ inv.subscription_id }}</td>
          <td>${{ "%.2f"|format(inv.amount_cents / 100) }}</td>
          <td>{{ inv.currency }}</td>
          <td><span class="badge badge-{{ inv.status }}">{{ inv.status }}</span></td>
          <td>{{ inv.due_date.strftime('%Y-%m-%d') if inv.due_date else '—' }}</td>
          <td>{{ inv.paid_at.strftime('%Y-%m-%d') if inv.paid_at else '—' }}</td>
          <td>
            <a href="{{ url_for('InvoiceView.download_pdf', invoice_id=inv.id) }}"
               class="btn btn-xs btn-default">
              <i class="fa fa-download"></i> PDF
            </a>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="8" class="text-muted text-center">No invoices found</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
"""


class InvoiceView(BaseView):
	route_base = "/billing/invoices"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		db = _get_session()
		invoices = db.execute(
			select(Invoice).order_by(Invoice.created_at.desc()).limit(200)
		).scalars().all()

		content = render_template_string(
			_INVOICE_LIST_CONTENT,
			invoices=invoices,
		)
		return render_template_string(
			_BASE_TEMPLATE,
			content=content,
			page_title="Invoices",
			active_tab="invoices",
		)

	@expose("/download/<int:invoice_id>")
	@has_access
	def download_pdf(self, invoice_id: int):
		"""Generate and stream an invoice PDF.  Falls back to plain text if reportlab is absent."""
		db = _get_session()
		invoice = db.get(Invoice, invoice_id)
		if invoice is None:
			return Response("Invoice not found", status=404)

		if _HAS_REPORTLAB:
			pdf_bytes = _build_pdf(invoice)
		else:
			pdf_bytes = _build_text_invoice(invoice)
			return Response(
				pdf_bytes,
				status=200,
				mimetype="text/plain",
				headers={
					"Content-Disposition": f'attachment; filename="invoice_{invoice_id}.txt"'
				},
			)

		return Response(
			pdf_bytes,
			status=200,
			mimetype="application/pdf",
			headers={
				"Content-Disposition": f'attachment; filename="invoice_{invoice_id}.pdf"'
			},
		)


def _build_pdf(invoice: Invoice) -> bytes:
	"""Build a minimal A4 PDF for the invoice using reportlab."""
	buf = io.BytesIO()
	c = _rl_canvas.Canvas(buf, pagesize=A4)
	width, height = A4

	c.setFont("Helvetica-Bold", 16)
	c.drawString(50, height - 60, f"Invoice #{invoice.id}")

	c.setFont("Helvetica", 11)
	c.drawString(50, height - 90, f"Status: {invoice.status}")
	c.drawString(50, height - 110, f"Currency: {invoice.currency}")
	c.drawString(50, height - 130, f"Amount: {invoice.amount_cents / 100:.2f} {invoice.currency}")

	if invoice.due_date:
		c.drawString(50, height - 150, f"Due: {invoice.due_date.strftime('%Y-%m-%d')}")
	if invoice.paid_at:
		c.drawString(50, height - 170, f"Paid: {invoice.paid_at.strftime('%Y-%m-%d')}")

	# Line items
	y = height - 210
	c.setFont("Helvetica-Bold", 11)
	c.drawString(50, y, "Description")
	c.drawString(300, y, "Qty")
	c.drawString(370, y, "Unit Price")
	c.drawString(460, y, "Amount")
	y -= 5
	c.line(50, y, width - 50, y)
	y -= 15

	c.setFont("Helvetica", 10)
	for item in (invoice.items or []):
		c.drawString(50, y, item.description[:45])
		c.drawString(300, y, str(item.quantity))
		c.drawString(370, y, f"{item.unit_price_cents / 100:.2f}")
		c.drawString(460, y, f"{item.amount_cents / 100:.2f}")
		y -= 15
		if y < 80:
			c.showPage()
			y = height - 60

	c.line(50, y, width - 50, y)
	y -= 15
	c.setFont("Helvetica-Bold", 11)
	c.drawString(370, y, "Total:")
	c.drawString(460, y, f"{invoice.amount_cents / 100:.2f} {invoice.currency}")

	c.save()
	return buf.getvalue()


def _build_text_invoice(invoice: Invoice) -> bytes:
	lines = [
		f"INVOICE #{invoice.id}",
		f"Status:   {invoice.status}",
		f"Currency: {invoice.currency}",
		f"Amount:   {invoice.amount_cents / 100:.2f} {invoice.currency}",
		f"Due:      {invoice.due_date.strftime('%Y-%m-%d') if invoice.due_date else '—'}",
		f"Paid:     {invoice.paid_at.strftime('%Y-%m-%d') if invoice.paid_at else '—'}",
		"",
		f"{'Description':<50} {'Qty':>5} {'Unit':>10} {'Amount':>10}",
		"-" * 80,
	]
	for item in (invoice.items or []):
		lines.append(
			f"{item.description[:50]:<50} {item.quantity:>5} "
			f"{item.unit_price_cents/100:>10.2f} {item.amount_cents/100:>10.2f}"
		)
	lines += ["-" * 80, f"{'Total':>67} {invoice.amount_cents/100:>10.2f}"]
	return "\n".join(lines).encode("utf-8")


# ---------------------------------------------------------------------------
# UsageView
# ---------------------------------------------------------------------------

_USAGE_CONTENT = """
<div class="page-header">
  <h2><i class="fa fa-bar-chart"></i> Usage Metrics</h2>
</div>

<div class="panel panel-default">
  <div class="panel-heading">
    <h4>Filter by Subscription</h4>
  </div>
  <div class="panel-body">
    <form method="get" class="form-inline">
      <div class="form-group">
        <label>Subscription ID</label>
        <input type="number" name="sub_id" class="form-control" value="{{ sub_id or '' }}"
               placeholder="All">
      </div>
      <div class="form-group">
        <label>Metric</label>
        <input type="text" name="metric" class="form-control" value="{{ metric or '' }}"
               placeholder="e.g. api_calls">
      </div>
      <button type="submit" class="btn btn-default">Filter</button>
    </form>
  </div>
</div>

<div class="panel panel-default">
  <div class="panel-body">
    <table class="table table-condensed table-hover">
      <thead>
        <tr>
          <th>#</th><th>Subscription</th><th>Metric</th>
          <th>Quantity</th><th>Recorded At</th>
        </tr>
      </thead>
      <tbody>
        {% for rec in records %}
        <tr>
          <td>{{ rec.id }}</td>
          <td>{{ rec.subscription_id }}</td>
          <td><code>{{ rec.metric_name }}</code></td>
          <td>{{ rec.quantity }}</td>
          <td>{{ rec.recorded_at.strftime('%Y-%m-%d %H:%M') }}</td>
        </tr>
        {% else %}
        <tr><td colspan="5" class="text-muted text-center">No usage records found</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
"""


class UsageView(BaseView):
	route_base = "/billing/usage"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		db = _get_session()
		sub_id = request.args.get("sub_id", type=int)
		metric = request.args.get("metric", "").strip() or None

		q = select(UsageRecord).order_by(UsageRecord.recorded_at.desc())
		if sub_id:
			q = q.where(UsageRecord.subscription_id == sub_id)
		if metric:
			q = q.where(UsageRecord.metric_name == metric)
		records = db.execute(q.limit(500)).scalars().all()

		content = render_template_string(
			_USAGE_CONTENT,
			records=records,
			sub_id=sub_id,
			metric=metric,
		)
		return render_template_string(
			_BASE_TEMPLATE,
			content=content,
			page_title="Usage Metrics",
			active_tab="usage",
		)


# ---------------------------------------------------------------------------
# DunningView
# ---------------------------------------------------------------------------

_DUNNING_CONTENT = """
<div class="page-header">
  <h2>
    <i class="fa fa-exclamation-triangle text-warning"></i> Dunning Queue
    {% if pending_count %}
    <span class="badge">{{ pending_count }}</span>
    {% endif %}
  </h2>
</div>

<div class="row">
  <div class="col-sm-12">
    <form action="{{ url_for('DunningView.run_now') }}" method="post"
          style="display:inline;">
      <button type="submit" class="btn btn-warning">
        <i class="fa fa-refresh"></i> Run Dunning Now
      </button>
    </form>
  </div>
</div>
<br>

<div class="panel panel-default">
  <div class="panel-heading"><h4>Pending Attempts</h4></div>
  <div class="panel-body">
    <table class="table table-hover table-condensed">
      <thead>
        <tr>
          <th>#</th><th>Subscription</th><th>Attempt #</th>
          <th>Status</th><th>Attempted At</th><th>Next Attempt</th>
          <th>Failure</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {% for da in attempts %}
        <tr>
          <td>{{ da.id }}</td>
          <td>{{ da.subscription_id }}</td>
          <td>{{ da.attempt_number }}</td>
          <td><span class="badge">{{ da.status }}</span></td>
          <td>{{ da.attempted_at.strftime('%Y-%m-%d %H:%M') }}</td>
          <td>{{ da.next_attempt_at.strftime('%Y-%m-%d %H:%M') if da.next_attempt_at else '—' }}</td>
          <td>{{ da.failure_reason or '—' }}</td>
          <td>
            <form action="{{ url_for('DunningView.retry', attempt_id=da.id) }}"
                  method="post" style="display:inline">
              <button type="submit" class="btn btn-xs btn-primary">
                <i class="fa fa-play"></i> Retry
              </button>
            </form>
          </td>
        </tr>
        {% else %}
        <tr><td colspan="8" class="text-muted text-center">Queue is empty</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</div>
"""


class DunningView(BaseView):
	route_base = "/billing/dunning"
	default_view = "index"

	@expose("/")
	@has_access
	def index(self):
		db = _get_session()
		attempts = db.execute(
			select(DunningAttempt).order_by(
				DunningAttempt.next_attempt_at.asc().nullslast()
			).limit(200)
		).scalars().all()

		pending_count = sum(
			1 for a in attempts if a.status == DunningStatus.PENDING.value
		)

		content = render_template_string(
			_DUNNING_CONTENT,
			attempts=attempts,
			pending_count=pending_count,
		)
		return render_template_string(
			_BASE_TEMPLATE,
			content=content,
			page_title="Dunning",
			active_tab="dunning",
		)

	@expose("/run", methods=["POST"])
	@has_access
	def run_now(self):
		"""Trigger the dunning processor immediately."""
		engine = _get_engine()
		db = _get_session()
		try:
			processed = engine.process_dunning(db)
			db.commit()
			flash(f"Dunning run complete: {len(processed)} attempt(s) processed.", "success")
		except Exception as exc:
			db.rollback()
			log.exception("DunningView.run_now: %s", exc)
			flash(f"Dunning run failed: {exc}", "danger")
		return redirect(url_for("DunningView.index"))

	@expose("/retry/<int:attempt_id>", methods=["POST"])
	@has_access
	def retry(self, attempt_id: int):
		"""Manually retry a specific dunning attempt."""
		db = _get_session()
		attempt = db.get(DunningAttempt, attempt_id)
		if attempt is None:
			flash("Attempt not found.", "danger")
			return redirect(url_for("DunningView.index"))

		engine = _get_engine()
		try:
			# Trigger payment attempt for the subscription's open invoice
			from .models import Invoice as _Invoice
			invoice = db.execute(
				select(_Invoice).where(
					_Invoice.subscription_id == attempt.subscription_id,
					_Invoice.status == InvoiceStatus.OPEN.value,
				).order_by(_Invoice.created_at.desc())
			).scalar_one_or_none()

			if invoice:
				success, reason = engine._attempt_payment(db, invoice)
				db.commit()
				if success:
					flash(f"Payment succeeded for attempt #{attempt_id}.", "success")
				else:
					flash(f"Payment failed: {reason}", "warning")
			else:
				flash("No open invoice found for this subscription.", "warning")
		except Exception as exc:
			db.rollback()
			flash(f"Retry error: {exc}", "danger")

		return redirect(url_for("DunningView.index"))


# ---------------------------------------------------------------------------
# REST API views (Blueprint-style using BaseView)
# ---------------------------------------------------------------------------

class BillingApiView(BaseView):
	"""
	JSON REST endpoints for billing operations.

	POST /billing/api/subscribe   — start/change plan
	POST /billing/api/cancel      — cancel subscription
	POST /billing/api/usage       — record metered usage
	"""
	route_base = "/billing/api"
	default_view = "subscribe"

	@expose("/subscribe", methods=["POST"])
	def subscribe(self):
		"""
		Start a new subscription or switch an existing one.

		Body (JSON):
		  tenant_id       int     required
		  plan_id         int     required
		  payment_method  str     optional  (Stripe PaymentMethod ID)
		  trial           bool    optional  (start as trial, default False)
		  trial_days      int     optional
		"""
		body: dict[str, Any] = request.get_json(silent=True) or {}

		tenant_id = body.get("tenant_id")
		plan_id = body.get("plan_id")
		if not tenant_id or not plan_id:
			return jsonify({"error": "tenant_id and plan_id are required"}), 400

		engine = _get_engine()
		db = _get_session()

		try:
			if body.get("trial", False):
				sub = engine.start_trial(
					db,
					tenant_id=int(tenant_id),
					plan_id=int(plan_id),
					trial_days=body.get("trial_days"),
				)
			else:
				payment_method = body.get("payment_method", "")
				sub = engine.activate_subscription(
					db,
					tenant_id=int(tenant_id),
					plan_id=int(plan_id),
					payment_method_id=payment_method,
				)
			db.commit()
			return jsonify({
				"subscription_id": sub.id,
				"status": sub.status,
				"current_period_end": (
					sub.current_period_end.isoformat() if sub.current_period_end else None
				),
				"trial_end": sub.trial_end.isoformat() if sub.trial_end else None,
			}), 201

		except PlanNotFound as exc:
			db.rollback()
			return jsonify({"error": str(exc)}), 404
		except BillingError as exc:
			db.rollback()
			return jsonify({"error": str(exc)}), 400
		except Exception as exc:
			db.rollback()
			log.exception("BillingApiView.subscribe: %s", exc)
			return jsonify({"error": "internal error"}), 500

	@expose("/cancel", methods=["POST"])
	def cancel(self):
		"""
		Cancel a subscription.

		Body (JSON):
		  subscription_id   int   required
		  at_period_end     bool  optional (default True)
		"""
		body: dict[str, Any] = request.get_json(silent=True) or {}
		sub_id = body.get("subscription_id")
		if not sub_id:
			return jsonify({"error": "subscription_id is required"}), 400

		engine = _get_engine()
		db = _get_session()

		try:
			sub = engine.cancel_subscription(
				db,
				subscription_id=int(sub_id),
				at_period_end=bool(body.get("at_period_end", True)),
			)
			db.commit()
			return jsonify({"subscription_id": sub.id, "status": sub.status}), 200

		except SubscriptionNotFound as exc:
			return jsonify({"error": str(exc)}), 404
		except BillingError as exc:
			db.rollback()
			return jsonify({"error": str(exc)}), 400
		except Exception as exc:
			db.rollback()
			log.exception("BillingApiView.cancel: %s", exc)
			return jsonify({"error": "internal error"}), 500

	@expose("/usage", methods=["POST"])
	def record_usage(self):
		"""
		Record metered usage.

		Body (JSON):
		  subscription_id  int    required
		  metric           str    required
		  quantity         float  required
		  metadata         dict   optional
		"""
		body: dict[str, Any] = request.get_json(silent=True) or {}

		sub_id = body.get("subscription_id")
		metric = body.get("metric", "").strip()
		quantity = body.get("quantity")

		if not sub_id or not metric or quantity is None:
			return jsonify({"error": "subscription_id, metric, quantity are required"}), 400

		engine = _get_engine()
		db = _get_session()

		try:
			record = engine.record_usage(
				db,
				subscription_id=int(sub_id),
				metric_name=metric,
				quantity=float(quantity),
				metadata=body.get("metadata"),
			)
			db.commit()
			return jsonify({
				"usage_record_id": record.id,
				"metric": record.metric_name,
				"quantity": float(record.quantity),
				"recorded_at": record.recorded_at.isoformat(),
			}), 201

		except SubscriptionNotFound as exc:
			return jsonify({"error": str(exc)}), 404
		except Exception as exc:
			db.rollback()
			log.exception("BillingApiView.record_usage: %s", exc)
			return jsonify({"error": "internal error"}), 500


class InvoicePdfApiView(BaseView):
	"""GET /billing/api/invoice/<id>/pdf"""
	route_base = "/billing/api/invoice"
	default_view = "pdf"

	@expose("/<int:invoice_id>/pdf")
	@has_access
	def pdf(self, invoice_id: int):
		db = _get_session()
		invoice = db.get(Invoice, invoice_id)
		if invoice is None:
			return jsonify({"error": "Invoice not found"}), 404

		if _HAS_REPORTLAB:
			data = _build_pdf(invoice)
			mime = "application/pdf"
			fname = f"invoice_{invoice_id}.pdf"
		else:
			data = _build_text_invoice(invoice)
			mime = "text/plain"
			fname = f"invoice_{invoice_id}.txt"

		return Response(
			data,
			status=200,
			mimetype=mime,
			headers={"Content-Disposition": f'attachment; filename="{fname}"'},
		)


# ---------------------------------------------------------------------------
# Stripe webhook handler
# ---------------------------------------------------------------------------

class StripeWebhookView(BaseView):
	"""
	POST /billing/webhooks/stripe

	Validates the Stripe-Signature header and dispatches to local handlers
	for the following events:

	  customer.subscription.created
	  customer.subscription.updated
	  customer.subscription.deleted
	  invoice.payment_succeeded
	  invoice.payment_failed
	"""
	route_base = "/billing/webhooks"
	default_view = "stripe"

	@expose("/stripe", methods=["POST"])
	def stripe(self):
		if not _HAS_STRIPE:
			log.warning("StripeWebhookView: stripe package not installed")
			return Response("stripe not installed", status=503)

		secret = current_app.config.get("FAB_BILLING_STRIPE_WEBHOOK_SECRET")
		if not secret:
			log.error(
				"StripeWebhookView: FAB_BILLING_STRIPE_WEBHOOK_SECRET not configured"
			)
			return Response("webhook secret not configured", status=400)

		payload = request.get_data()
		sig = request.headers.get("Stripe-Signature", "")

		try:
			event = _stripe.Webhook.construct_event(payload, sig, secret)
		except _stripe.error.SignatureVerificationError as exc:
			log.warning("StripeWebhookView: signature verification failed: %s", exc)
			return Response("invalid signature", status=400)
		except Exception as exc:
			log.error("StripeWebhookView: failed to parse event: %s", exc)
			return Response("bad request", status=400)

		log.info("StripeWebhookView: received %s id=%s", event["type"], event["id"])

		try:
			_dispatch_stripe_event(event)
		except Exception as exc:
			log.exception("StripeWebhookView: handler error for %s: %s", event["type"], exc)
			# Return 200 anyway — Stripe will not retry on 5xx from a bad handler

		return Response("", status=200)


# ---------------------------------------------------------------------------
# Stripe event dispatcher
# ---------------------------------------------------------------------------

def _dispatch_stripe_event(event: dict[str, Any]) -> None:
	"""Route a validated Stripe event to the appropriate local handler."""
	event_type: str = event.get("type", "")
	obj: dict[str, Any] = event.get("data", {}).get("object", {})

	handlers = {
		"customer.subscription.created": _on_stripe_sub_created,
		"customer.subscription.updated": _on_stripe_sub_updated,
		"customer.subscription.deleted": _on_stripe_sub_deleted,
		"invoice.payment_succeeded": _on_stripe_payment_succeeded,
		"invoice.payment_failed": _on_stripe_payment_failed,
	}

	handler = handlers.get(event_type)
	if handler:
		handler(obj)
	else:
		log.debug("StripeWebhookView: unhandled event type %r", event_type)


def _on_stripe_sub_created(obj: dict[str, Any]) -> None:
	stripe_sub_id: str = obj.get("id", "")
	log.info("Stripe subscription created: %s status=%s", stripe_sub_id, obj.get("status"))
	db = _get_session()
	sub = db.execute(
		select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
	).scalar_one_or_none()
	if sub:
		sub.status = obj.get("status", sub.status)
		db.commit()


def _on_stripe_sub_updated(obj: dict[str, Any]) -> None:
	stripe_sub_id: str = obj.get("id", "")
	new_status: str = obj.get("status", "")
	log.info("Stripe subscription updated: %s status=%s", stripe_sub_id, new_status)

	db = _get_session()
	sub = db.execute(
		select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
	).scalar_one_or_none()
	if sub and new_status:
		# Map Stripe status values to our enum
		_status_map = {
			"active": SubscriptionStatus.ACTIVE.value,
			"trialing": SubscriptionStatus.TRIALING.value,
			"past_due": SubscriptionStatus.PAST_DUE.value,
			"canceled": SubscriptionStatus.CANCELED.value,
			"paused": SubscriptionStatus.PAUSED.value,
		}
		sub.status = _status_map.get(new_status, new_status)

		# Sync period dates
		if obj.get("current_period_start"):
			sub.current_period_start = datetime.fromtimestamp(
				obj["current_period_start"], tz=timezone.utc
			)
		if obj.get("current_period_end"):
			sub.current_period_end = datetime.fromtimestamp(
				obj["current_period_end"], tz=timezone.utc
			)
		db.commit()


def _on_stripe_sub_deleted(obj: dict[str, Any]) -> None:
	stripe_sub_id: str = obj.get("id", "")
	log.info("Stripe subscription deleted: %s", stripe_sub_id)
	db = _get_session()
	sub = db.execute(
		select(Subscription).where(Subscription.stripe_subscription_id == stripe_sub_id)
	).scalar_one_or_none()
	if sub:
		sub.status = SubscriptionStatus.CANCELED.value
		db.commit()


def _on_stripe_payment_succeeded(obj: dict[str, Any]) -> None:
	stripe_invoice_id: str = obj.get("id", "")
	log.info("Stripe invoice payment succeeded: %s", stripe_invoice_id)
	db = _get_session()
	invoice = db.execute(
		select(Invoice).where(Invoice.stripe_invoice_id == stripe_invoice_id)
	).scalar_one_or_none()
	if invoice:
		invoice.status = InvoiceStatus.PAID.value
		invoice.paid_at = datetime.now(timezone.utc)
		# Restore subscription to active if it was past-due
		sub = db.get(Subscription, invoice.subscription_id)
		if sub and sub.status == SubscriptionStatus.PAST_DUE.value:
			sub.status = SubscriptionStatus.ACTIVE.value
		db.commit()


def _on_stripe_payment_failed(obj: dict[str, Any]) -> None:
	stripe_invoice_id: str = obj.get("id", "")
	log.warning("Stripe invoice payment failed: %s", stripe_invoice_id)
	db = _get_session()
	invoice = db.execute(
		select(Invoice).where(Invoice.stripe_invoice_id == stripe_invoice_id)
	).scalar_one_or_none()
	if invoice:
		# Escalate subscription to past-due and open the first dunning attempt
		sub = db.get(Subscription, invoice.subscription_id)
		if sub and sub.status == SubscriptionStatus.ACTIVE.value:
			sub.status = SubscriptionStatus.PAST_DUE.value
			now = datetime.now(timezone.utc)
			first_attempt = DunningAttempt(
				subscription_id=sub.id,
				attempt_number=1,
				attempted_at=now,
				status=DunningStatus.PENDING.value,
				next_attempt_at=now + timedelta(days=1),
				failure_reason=obj.get("last_payment_error", {}).get("message"),
			)
			db.add(first_attempt)
		db.commit()


__all__ = [
	"BillingDashboardView",
	"SubscriptionListView",
	"InvoiceView",
	"UsageView",
	"DunningView",
	"BillingApiView",
	"InvoicePdfApiView",
	"StripeWebhookView",
]
