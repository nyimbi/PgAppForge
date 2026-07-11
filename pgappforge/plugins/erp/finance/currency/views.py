"""
pgappforge/plugins/erp/finance/currency/views.py

Exchange-rate CRUD and dashboard views.
"""
from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from flask import current_app, request
from markupsafe import Markup, escape

from pgappforge import ModelView, expose
from pgappforge.models.sqla.interface import SQLAInterface
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.plugins.erp.finance.currency.models import ExchangeRate
from pgappforge.plugins.erp.finance.currency.services import CurrencyRateNotFoundError
from pgappforge.plugins.erp.finance.currency.services import ExchangeRateService
from pgappforge.security.decorators import has_access


AFRICA_USD_PAIRS: tuple[tuple[str, str], ...] = (
	("KES", "USD"),
	("UGX", "USD"),
	("TZS", "USD"),
	("RWF", "USD"),
	("GHS", "USD"),
	("NGN", "USD"),
	("ZAR", "USD"),
	("ETB", "USD"),
)


def _get_session():
	ab = current_app.extensions.get("appbuilder")
	if ab and hasattr(ab, "get_session"):
		return ab.get_session
	db = current_app.extensions.get("sqlalchemy")
	if db:
		return db.session
	raise RuntimeError("Cannot obtain database session outside app context")


def _tenant_id() -> str:
	arg_value = request.args.get("tenant_id")
	if arg_value:
		return arg_value
	try:
		from flask_login import current_user
		user_tenant = getattr(current_user, "tenant_id", None)
		if user_tenant:
			return str(user_tenant)
	except Exception:
		pass
	return str(current_app.config.get("ERP_DEFAULT_TENANT_ID", ""))


class ExchangeRateView(ModelView):
	datamodel = SQLAInterface(ExchangeRate)

	list_columns = ['effective_date', 'from_currency', 'to_currency', 'rate', 'source']
	label_columns = {'from_currency': 'From', 'to_currency': 'To', 'effective_date': 'Date', 'rate': 'Rate', 'source': 'Source'}
	base_order = ('effective_date', 'desc')
	page_size = 50
	search_columns = ['from_currency', 'to_currency', 'source']
	export_columns = list_columns
	add_exclude_columns = ['id', 'created_at']
	edit_exclude_columns = ['id', 'created_at']


class CurrencyDashboardView(BaseERPView):
	"""Current Africa/USD rates and 30-day trend table."""

	route_base = "/finance/currency"
	default_view = "dashboard"

	@expose("/")
	@has_access
	def dashboard(self):
		session = _get_session()
		tenant_id = _tenant_id()
		today = date.today()
		svc = ExchangeRateService()

		current_rows: list[dict[str, str]] = []
		latest_update = ""
		latest_source = ""
		for from_ccy, to_ccy in AFRICA_USD_PAIRS:
			rate_display = "Missing"
			effective_display = ""
			source_display = ""
			try:
				rate = svc.get_rate(tenant_id, from_ccy, to_ccy, today, session)
				row = session.execute(
					sa.select(ExchangeRate)
					.where(ExchangeRate.tenant_id == tenant_id)
					.where(ExchangeRate.from_currency == from_ccy)
					.where(ExchangeRate.to_currency == to_ccy)
					.where(ExchangeRate.effective_date <= today)
					.order_by(sa.desc(ExchangeRate.effective_date), sa.desc(ExchangeRate.created_at))
					.limit(1)
				).scalar_one_or_none()
				rate_display = str(rate)
				if row is not None:
					effective_display = row.effective_date.isoformat()
					source_display = row.source
					created_display = row.created_at.isoformat() if row.created_at else ""
					if created_display > latest_update:
						latest_update = created_display
						latest_source = source_display
			except CurrencyRateNotFoundError:
				pass
			current_rows.append({
				"pair": f"{from_ccy}/{to_ccy}",
				"rate": rate_display,
				"effective_date": effective_display,
				"source": source_display,
			})

		trend_rows: list[dict[str, str]] = []
		for from_ccy, to_ccy in AFRICA_USD_PAIRS:
			for row in svc.get_rate_history(tenant_id, from_ccy, to_ccy, session, days=30):
				trend_rows.append({
					"pair": f"{from_ccy}/{to_ccy}",
					"effective_date": row.effective_date.isoformat(),
					"rate": str(row.rate),
					"source": row.source,
				})
		trend_rows.sort(key=lambda item: (item["effective_date"], item["pair"]), reverse=True)

		return Markup(self._render_dashboard(tenant_id, current_rows, trend_rows, latest_update, latest_source))

	def _render_dashboard(
		self,
		tenant_id: str,
		current_rows: list[dict[str, str]],
		trend_rows: list[dict[str, str]],
		latest_update: str,
		latest_source: str,
	) -> str:
		current_html = "".join(
			"<tr>"
			f"<td>{escape(row['pair'])}</td>"
			f"<td class='text-right'>{escape(row['rate'])}</td>"
			f"<td>{escape(row['effective_date'])}</td>"
			f"<td>{escape(row['source'])}</td>"
			"</tr>"
			for row in current_rows
		)
		trend_html = "".join(
			"<tr>"
			f"<td>{escape(row['effective_date'])}</td>"
			f"<td>{escape(row['pair'])}</td>"
			f"<td class='text-right'>{escape(row['rate'])}</td>"
			f"<td>{escape(row['source'])}</td>"
			"</tr>"
			for row in trend_rows
		)
		if not trend_html:
			trend_html = "<tr><td colspan='4'>No 30-day rate history found.</td></tr>"
		last_update = latest_update or "No rates loaded"
		source = latest_source or "n/a"
		return f"""
<div class="container-fluid">
	<h3>Currency Dashboard</h3>
	<p>
		<strong>Tenant:</strong> {escape(tenant_id or "default")}
		&nbsp; <strong>Last update:</strong> {escape(last_update)}
		&nbsp; <strong>Source:</strong> {escape(source)}
	</p>
	<h4>Today's Africa/USD Rates</h4>
	<table class="table table-condensed table-bordered table-hover">
		<thead>
			<tr><th>Pair</th><th class="text-right">Rate</th><th>Date</th><th>Source</th></tr>
		</thead>
		<tbody>{current_html}</tbody>
	</table>
	<h4>30-Day Trend</h4>
	<table class="table table-condensed table-bordered table-hover">
		<thead>
			<tr><th>Date</th><th>Pair</th><th class="text-right">Rate</th><th>Source</th></tr>
		</thead>
		<tbody>{trend_html}</tbody>
	</table>
</div>
"""


__all__ = [
	"AFRICA_USD_PAIRS",
	"CurrencyDashboardView",
	"ExchangeRateView",
]
