"""
pgappforge/plugins/erp/industry/real_estate/views.py

Flask views for the Real Estate plugin.

Route summary
-------------
PropertyView            /re/properties/
  ├─ GET  /re/properties/              — list (HTML with map widget, currency display)
  ├─ GET  /re/properties/<id>          — detail (JSON + map + images)
  ├─ POST /re/properties/              — create listing
  ├─ PUT  /re/properties/<id>          — update listing
  ├─ POST /re/properties/<id>/avm      — run AVM valuation
  └─ POST /re/properties/<id>/cma      — generate CMA
TransactionView         /re/transactions/
  ├─ GET  /re/transactions/            — list
  ├─ POST /re/transactions/            — create transaction
  ├─ POST /re/transactions/<id>/offer  — process offer
  └─ POST /re/transactions/<id>/close  — close transaction
AgentView               /re/agents/
  ├─ GET  /re/agents/                  — list with star ratings
  └─ GET  /re/agents/<id>              — detail
ValuationView           /re/valuations/
  └─ GET  /re/valuations/              — list (filter by property_id)
MarketDashboard         /re/dashboard/
  └─ GET  /re/dashboard/market-stats   — market stats by zip code (HTML)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import BaseView, expose
from pgappforge.security.decorators import has_access
from pgappforge.plugins.erp.foundation.commons import format_currency
from pgappforge.plugins.erp.foundation.view_helpers import (
	currency_widget,
	date_widget,
	map_widget,
	star_widget,
	chart_widget,
	file_widget,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


def _cents(cents: int | None, currency: str = "USD") -> str:
	if cents is None:
		return "—"
	major = cents // 100
	minor = abs(cents) % 100
	sign = "-" if cents < 0 else ""
	return f"{sign}{major:,}.{minor:02d} {currency}"


def _widget_config() -> dict:
	"""Return shared widget configs for real estate views."""
	return {
		"list_price": currency_widget("USD"),
		"sold_price": currency_widget("USD"),
		"location": map_widget(zoom=14),
		"images": file_widget(multiple=True, types=["jpg", "jpeg", "png", "webp"]),
		"rating": star_widget(max_rating=5),
		"market_chart": chart_widget("bar"),
	}


# ---------------------------------------------------------------------------
# PropertyView
# ---------------------------------------------------------------------------

class PropertyView(BaseView):
	"""MLS Property listing CRUD with AVM/CMA actions.

	Widgets used:
	  - CurrencyWidget for list_price_cents, sold_price_cents
	  - MapWidget for geo_lat/geo_lng location display
	  - FileUploadWidget for images (multiple)
	  - StarRatingWidget for agent rating display
	"""

	route_base = "/re/properties"
	default_view = "list"

	# Widget metadata (consumed by FAB widget machinery)
	widget_config = {
		"list_price_cents": currency_widget("USD"),
		"sold_price_cents": currency_widget("USD"),
		"geo_location": map_widget(zoom=14),
		"images": file_widget(multiple=True, types=["jpg", "jpeg", "png", "webp"]),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.models import Property

		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		property_type = request.args.get("property_type")

		q = (
			sa.select(Property)
			.order_by(sa.desc(Property.listing_date))
			.limit(500)
		)
		if tenant_id:
			q = q.where(Property.tenant_id == tenant_id)
		if status:
			q = q.where(Property.status == status.upper())
		if property_type:
			q = q.where(Property.property_type == property_type.upper())

		props = session.execute(q).scalars().all()

		rows = "".join(
			f"<tr>"
			f"<td>{_he(p.mls_number)}</td>"
			f"<td>{_he(p.property_type)}</td>"
			f"<td><span class='badge badge-{'success' if p.status == 'ACTIVE' else 'secondary'}'>"
			f"{_he(p.status)}</span></td>"
			f"<td class='text-right'>{_cents(p.list_price_cents)}</td>"
			f"<td>{_he(p.bedrooms or '—')} bd / {_he(p.bathrooms or '—')} ba</td>"
			f"<td>{_he(p.sqft or '—')} sqft</td>"
			f"<td>{_he(p.listing_date or '—')}</td>"
			f"<td>{_he(p.days_on_market or 0)} days</td>"
			f"<td><a href='/re/properties/{_he(p.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for p in props
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>MLS Properties</title>
<link rel="stylesheet" href="/static/appbuilder/css/bootstrap.min.css">
<style>body{{padding:24px}}.badge-success{{background:#27ae60}}.badge-secondary{{background:#7f8c8d}}</style>
</head><body>
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
  <h3>MLS Properties <small>({len(props)})</small></h3>
  <a href="/re/dashboard/market-stats" class="btn btn-default btn-sm">Market Stats</a>
</div>
<table class="table table-bordered table-hover table-condensed">
<thead><tr>
  <th>MLS #</th><th>Type</th><th>Status</th><th class="text-right">List Price</th>
  <th>Beds/Baths</th><th>SqFt</th><th>Listed</th><th>DOM</th><th></th>
</tr></thead>
<tbody>{rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/<string:property_id>")
	@has_access
	def detail(self, property_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.models import Property, PropertyValuation

		prop = session.get(Property, property_id)
		if prop is None:
			abort(404)

		latest_valuation = session.execute(
			sa.select(PropertyValuation)
			.where(PropertyValuation.property_id == property_id)
			.order_by(sa.desc(PropertyValuation.valuation_date))
			.limit(1)
		).scalar_one_or_none()

		return jsonify({
			"id": prop.id,
			"tenant_id": prop.tenant_id,
			"mls_number": prop.mls_number,
			"property_type": prop.property_type,
			"status": prop.status,
			"list_price_cents": prop.list_price_cents,
			"list_price_display": _cents(prop.list_price_cents),
			"sold_price_cents": prop.sold_price_cents,
			"address": prop.address,
			"geo_lat": str(prop.geo_lat) if prop.geo_lat else None,
			"geo_lng": str(prop.geo_lng) if prop.geo_lng else None,
			"bedrooms": prop.bedrooms,
			"bathrooms": str(prop.bathrooms) if prop.bathrooms else None,
			"sqft": prop.sqft,
			"lot_sqft": prop.lot_sqft,
			"year_built": prop.year_built,
			"description": prop.description,
			"listing_agent_id": prop.listing_agent_id,
			"listing_office": prop.listing_office,
			"listing_date": prop.listing_date.isoformat() if prop.listing_date else None,
			"closing_date": prop.closing_date.isoformat() if prop.closing_date else None,
			"days_on_market": prop.days_on_market,
			"images": prop.images,
			"mls_data": prop.mls_data,
			"widget_config": self.widget_config,
			"latest_valuation": {
				"id": latest_valuation.id,
				"valuation_type": latest_valuation.valuation_type,
				"estimated_value_cents": latest_valuation.estimated_value_cents,
				"confidence_score": str(latest_valuation.confidence_score),
				"valuation_date": latest_valuation.valuation_date.isoformat(),
			} if latest_valuation else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.services import RealEstateService, RealEstateServiceError

		data = request.get_json(silent=True) or {}
		svc = RealEstateService()
		try:
			prop = svc.list_property(data, session)
			session.commit()
			return jsonify({"ok": True, "id": prop.id, "mls_number": prop.mls_number}), 201
		except RealEstateServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:property_id>", methods=["PUT"])
	@has_access
	def update(self, property_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.models import Property

		prop = session.get(Property, property_id)
		if prop is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		updatable = (
			"status", "list_price_cents", "description", "bedrooms", "bathrooms",
			"sqft", "lot_sqft", "listing_office", "images", "mls_data",
			"days_on_market", "geo_lat", "geo_lng",
		)
		for field in updatable:
			if field in data:
				setattr(prop, field, data[field])
		if "address" in data:
			prop.address = {**(prop.address or {}), **data["address"]}
		prop.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:property_id>/avm", methods=["POST"])
	@has_access
	def run_avm(self, property_id: str):
		"""Run Automated Valuation Model for a property."""
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.services import RealEstateService, RealEstateServiceError

		data = request.get_json(silent=True) or {}
		svc = RealEstateService()
		try:
			valuation = svc.calculate_avm(
				property_id,
				comparables_radius_km=float(data.get("radius_km") or 1.0),
				session=session,
			)
			session.commit()
			return jsonify({
				"ok": True,
				"id": valuation.id,
				"estimated_value_cents": valuation.estimated_value_cents,
				"estimated_value_display": _cents(valuation.estimated_value_cents),
				"confidence_score": str(valuation.confidence_score),
				"comparable_count": len(valuation.comparable_sales),
			}), 201
		except RealEstateServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:property_id>/cma", methods=["POST"])
	@has_access
	def generate_cma(self, property_id: str):
		"""Generate Comparative Market Analysis."""
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.services import RealEstateService, RealEstateServiceError

		svc = RealEstateService()
		try:
			cma = svc.generate_cma(property_id, session)
			return jsonify({"ok": True, **cma})
		except RealEstateServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# TransactionView
# ---------------------------------------------------------------------------

class TransactionView(BaseView):
	"""Real Estate Transaction CRUD + lifecycle.

	Widget config:
	  - CurrencyWidget for sale_price_cents, earnest_money_cents, commission_cents
	  - DateWidget for contract_date, closing_date
	"""

	route_base = "/re/transactions"
	default_view = "list"

	widget_config = {
		"sale_price_cents": currency_widget("USD"),
		"earnest_money_cents": currency_widget("USD"),
		"commission_cents": currency_widget("USD"),
		"contract_date": date_widget(),
		"closing_date": date_widget(),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.models import Transaction

		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")

		q = (
			sa.select(Transaction)
			.order_by(sa.desc(Transaction.created_at))
			.limit(500)
		)
		if tenant_id:
			q = q.where(Transaction.tenant_id == tenant_id)
		if status:
			q = q.where(Transaction.status == status.upper())

		txns = session.execute(q).scalars().all()
		return jsonify({
			"transactions": [
				{
					"id": t.id,
					"property_id": t.property_id,
					"transaction_type": t.transaction_type,
					"status": t.status,
					"sale_price_cents": t.sale_price_cents,
					"sale_price_display": _cents(t.sale_price_cents),
					"commission_cents": t.commission_cents,
					"contract_date": t.contract_date.isoformat() if t.contract_date else None,
					"closing_date": t.closing_date.isoformat() if t.closing_date else None,
				}
				for t in txns
			]
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.models import Transaction

		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "property_id", "transaction_type") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"Missing: {missing}"}), 400

		txn = Transaction(
			tenant_id=data["tenant_id"],
			property_id=data["property_id"],
			transaction_type=data["transaction_type"].upper(),
			buyer_id=data.get("buyer_id"),
			seller_id=data.get("seller_id"),
			listing_agent_id=data.get("listing_agent_id"),
			buyers_agent_id=data.get("buyers_agent_id"),
			sale_price_cents=int(data.get("sale_price_cents") or 0),
			earnest_money_cents=int(data.get("earnest_money_cents") or 0),
			commission_pct=data.get("commission_pct"),
			status="PENDING",
			contingencies=data.get("contingencies") or [],
			escrow_company=data.get("escrow_company"),
			title_company=data.get("title_company"),
		)
		session.add(txn)
		session.commit()
		return jsonify({"ok": True, "id": txn.id}), 201

	@expose("/<string:txn_id>/offer", methods=["POST"])
	@has_access
	def process_offer(self, txn_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.services import RealEstateService, RealEstateServiceError

		data = request.get_json(silent=True) or {}
		offer_price = data.get("offer_price_cents")
		if not offer_price:
			return jsonify({"ok": False, "error": "offer_price_cents required"}), 400

		svc = RealEstateService()
		try:
			txn = svc.process_offer(
				txn_id,
				int(offer_price),
				data.get("contingencies") or [],
				session,
			)
			session.commit()
			return jsonify({"ok": True, "status": txn.status, "sale_price_cents": txn.sale_price_cents})
		except RealEstateServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422

	@expose("/<string:txn_id>/close", methods=["POST"])
	@has_access
	def close(self, txn_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.services import RealEstateService, RealEstateServiceError

		svc = RealEstateService()
		try:
			result = svc.close_transaction(txn_id, session)
			session.commit()
			return jsonify({"ok": True, **result})
		except RealEstateServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 422


# ---------------------------------------------------------------------------
# AgentView
# ---------------------------------------------------------------------------

class AgentView(BaseView):
	"""Real Estate Agent directory with star ratings.

	Widget config:
	  - StarRatingWidget for rating (0–5)
	  - CurrencyWidget for sold_volume_cents
	"""

	route_base = "/re/agents"
	default_view = "list"

	widget_config = {
		"rating": star_widget(max_rating=5),
		"sold_volume_cents": currency_widget("USD"),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.models import RealEstateAgent

		tenant_id = request.args.get("tenant_id")
		q = (
			sa.select(RealEstateAgent)
			.order_by(sa.desc(RealEstateAgent.sold_volume_cents))
			.limit(200)
		)
		if tenant_id:
			q = q.where(RealEstateAgent.tenant_id == tenant_id)

		agents = session.execute(q).scalars().all()
		return jsonify({
			"agents": [
				{
					"id": a.id,
					"party_id": a.party_id,
					"license_number": a.license_number,
					"license_state": a.license_state,
					"brokerage_name": a.brokerage_name,
					"active_listings": a.active_listings,
					"sold_volume_cents": a.sold_volume_cents,
					"sold_volume_display": _cents(a.sold_volume_cents),
					"rating": str(a.rating) if a.rating else None,
					"reviews_count": a.reviews_count,
					"widget_config": {"rating": self.widget_config["rating"]},
				}
				for a in agents
			]
		})

	@expose("/<string:agent_id>")
	@has_access
	def detail(self, agent_id: str):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.models import RealEstateAgent

		agent = session.get(RealEstateAgent, agent_id)
		if agent is None:
			abort(404)

		return jsonify({
			"id": agent.id,
			"tenant_id": agent.tenant_id,
			"party_id": agent.party_id,
			"license_number": agent.license_number,
			"license_state": agent.license_state,
			"license_expiry": agent.license_expiry.isoformat() if agent.license_expiry else None,
			"brokerage_name": agent.brokerage_name,
			"mls_member_id": agent.mls_member_id,
			"specialties": agent.specialties or [],
			"active_listings": agent.active_listings,
			"sold_volume_cents": agent.sold_volume_cents,
			"sold_volume_display": _cents(agent.sold_volume_cents),
			"rating": str(agent.rating) if agent.rating else None,
			"reviews_count": agent.reviews_count,
			"widget_config": self.widget_config,
		})


# ---------------------------------------------------------------------------
# ValuationView
# ---------------------------------------------------------------------------

class ValuationView(BaseView):
	"""Property Valuation list and detail.

	Widget config:
	  - CurrencyWidget for estimated_value_cents
	  - DateWidget for valuation_date
	"""

	route_base = "/re/valuations"
	default_view = "list"

	widget_config = {
		"estimated_value_cents": currency_widget("USD"),
		"valuation_date": date_widget(),
	}

	@expose("/")
	@has_access
	def list(self):
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.models import PropertyValuation

		property_id = request.args.get("property_id")
		tenant_id = request.args.get("tenant_id")
		valuation_type = request.args.get("valuation_type")

		q = (
			sa.select(PropertyValuation)
			.order_by(sa.desc(PropertyValuation.valuation_date))
			.limit(500)
		)
		if property_id:
			q = q.where(PropertyValuation.property_id == property_id)
		if tenant_id:
			q = q.where(PropertyValuation.tenant_id == tenant_id)
		if valuation_type:
			q = q.where(PropertyValuation.valuation_type == valuation_type.upper())

		valuations = session.execute(q).scalars().all()
		return jsonify({
			"valuations": [
				{
					"id": v.id,
					"property_id": v.property_id,
					"valuation_date": v.valuation_date.isoformat(),
					"valuation_type": v.valuation_type,
					"estimated_value_cents": v.estimated_value_cents,
					"estimated_value_display": _cents(v.estimated_value_cents),
					"confidence_score": str(v.confidence_score) if v.confidence_score else None,
					"report_url": v.report_url,
					"comp_count": len(v.comparable_sales) if v.comparable_sales else 0,
				}
				for v in valuations
			]
		})


# ---------------------------------------------------------------------------
# MarketDashboard
# ---------------------------------------------------------------------------

class MarketDashboard(BaseView):
	"""Real Estate Market Statistics Dashboard.

	GET /re/dashboard/market-stats   — market stats by zip code (HTML report)
	"""

	route_base = "/re/dashboard"
	default_view = "market_stats"

	widget_config = {
		"price_chart": chart_widget("bar"),
		"dom_chart": chart_widget("line"),
	}

	@expose("/market-stats")
	@has_access
	def market_stats(self):
		"""Market statistics dashboard — median price, DOM, absorption rate by zip."""
		session = _get_session()
		from pgappforge.plugins.erp.industry.real_estate.services import RealEstateService
		from pgappforge.plugins.erp.industry.real_estate.models import Property

		zip_code = request.args.get("zip_code", "")
		period_days = int(request.args.get("period_days") or 90)
		tenant_id = request.args.get("tenant_id")

		# Summary counts
		q_summary = sa.select(
			Property.status,
			sa.func.count(Property.id).label("count"),
			sa.func.coalesce(sa.func.avg(Property.list_price_cents), 0).label("avg_list"),
		).group_by(Property.status)
		if tenant_id:
			q_summary = q_summary.where(Property.tenant_id == tenant_id)
		summary_rows = session.execute(q_summary).all()

		status_table = "".join(
			f"<tr><td>{_he(r.status)}</td>"
			f"<td class='text-right'>{r.count}</td>"
			f"<td class='text-right'>{_cents(int(r.avg_list))}</td></tr>"
			for r in summary_rows
		)

		# Market stats if zip provided
		stats_section = ""
		if zip_code:
			svc = RealEstateService()
			stats = svc.get_market_stats(zip_code, period_days, session)
			stats_section = f"""
<div class="panel panel-default" style="margin-top:20px">
  <div class="panel-heading"><strong>Market Stats: {_he(zip_code)} (last {period_days} days)</strong></div>
  <div class="panel-body">
    <div class="row">
      <div class="col-md-3">
        <div class="well text-center">
          <h4>Median Sale Price</h4>
          <p class="h3" style="color:#27ae60">{_cents(stats['median_sold_price_cents'])}</p>
        </div>
      </div>
      <div class="col-md-3">
        <div class="well text-center">
          <h4>Avg Days on Market</h4>
          <p class="h3">{stats['avg_days_on_market']}</p>
        </div>
      </div>
      <div class="col-md-3">
        <div class="well text-center">
          <h4>Absorption Rate</h4>
          <p class="h3">{stats['absorption_rate']}</p>
        </div>
      </div>
      <div class="col-md-3">
        <div class="well text-center">
          <h4>Months of Supply</h4>
          <p class="h3">{stats['months_of_supply'] or '—'}</p>
        </div>
      </div>
    </div>
    <p><small>{stats['sold_count']} sold / {stats['active_count']} active</small></p>
  </div>
</div>"""

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Real Estate Market Dashboard</title>
<link rel="stylesheet" href="/static/appbuilder/css/bootstrap.min.css">
<style>body{{padding:24px}}.well{{border-radius:4px}}</style>
</head><body>
<h3>Real Estate Market Dashboard</h3>
<form class="form-inline" style="margin-bottom:16px">
  <input type="text" name="zip_code" value="{_he(zip_code)}"
    placeholder="Zip Code" class="form-control" style="width:120px">
  <select name="period_days" class="form-control" style="margin-left:8px">
    <option value="30" {"selected" if period_days==30 else ""}>30 days</option>
    <option value="90" {"selected" if period_days==90 else ""}>90 days</option>
    <option value="180" {"selected" if period_days==180 else ""}>180 days</option>
  </select>
  <button type="submit" class="btn btn-primary" style="margin-left:8px">Search</button>
</form>
{stats_section}
<h4>Portfolio by Status</h4>
<table class="table table-bordered table-condensed">
<thead><tr><th>Status</th><th class="text-right">Count</th><th class="text-right">Avg List Price</th></tr></thead>
<tbody>{status_table}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"PropertyView",
	"TransactionView",
	"AgentView",
	"ValuationView",
	"MarketDashboard",
]
