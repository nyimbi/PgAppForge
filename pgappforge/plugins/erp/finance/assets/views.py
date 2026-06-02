"""
pgappforge/plugins/erp/finance/assets/views.py

Flask views for the Asset Accounting plugin.

Routes:
  AssetClassView       GET/POST /assets/classes/
  FixedAssetView       GET/POST /assets/register/
                       POST     /assets/register/<id>/dispose
                       POST     /assets/register/<id>/impair
  AssetDepreciationView GET     /assets/depreciation/
                       POST     /assets/depreciation/run
  AssetReportView      GET     /assets/reports/register
                       GET     /assets/reports/depreciation-schedule/<id>
                       GET     /assets/reports/nbv-summary
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

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


def _he(s: str) -> str:
	return (
		str(s)
		.replace("&", "&amp;")
		.replace("<", "&lt;")
		.replace(">", "&gt;")
		.replace('"', "&quot;")
	)


def _fmt_cents(v: int | None) -> str:
	if v is None:
		return ""
	return f"{v:,}"


# ---------------------------------------------------------------------------
# AssetClassView
# ---------------------------------------------------------------------------

class AssetClassView(BaseView):
	"""Asset class CRUD.

	GET  /assets/classes/            — list (JSON)
	GET  /assets/classes/<id>        — detail (JSON)
	POST /assets/classes/            — create (JSON)
	PUT  /assets/classes/<id>        — update (JSON)
	"""

	route_base = "/assets/classes"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.assets.models import AssetClass
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		q = sa.select(AssetClass).order_by(AssetClass.code)
		if tenant_id:
			q = q.where(AssetClass.tenant_id == tenant_id)
		classes = session.execute(q).scalars().all()
		return jsonify({
			"asset_classes": [
				{
					"id": c.id,
					"code": c.code,
					"name": c.name,
					"useful_life_years": str(c.useful_life_years),
					"depreciation_method": c.depreciation_method,
					"gl_asset_account": c.gl_asset_account,
					"gl_accumulated_depreciation_account": c.gl_accumulated_depreciation_account,
					"gl_depreciation_expense_account": c.gl_depreciation_expense_account,
					"is_active": c.is_active,
				}
				for c in classes
			]
		})

	@expose("/<string:class_id>")
	@has_access
	def detail(self, class_id: str):
		from pgappforge.plugins.erp.finance.assets.models import AssetClass
		session = _get_session()
		ac = session.get(AssetClass, class_id)
		if ac is None:
			abort(404)
		return jsonify({
			"id": ac.id,
			"code": ac.code,
			"name": ac.name,
			"useful_life_years": str(ac.useful_life_years),
			"depreciation_method": ac.depreciation_method,
			"gl_asset_account": ac.gl_asset_account,
			"gl_accumulated_depreciation_account": ac.gl_accumulated_depreciation_account,
			"gl_depreciation_expense_account": ac.gl_depreciation_expense_account,
			"gl_disposal_gain_account": ac.gl_disposal_gain_account,
			"gl_disposal_loss_account": ac.gl_disposal_loss_account,
			"is_active": ac.is_active,
			"metadata": ac.metadata_,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.finance.assets.models import AssetClass
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "code", "name", "useful_life_years",
		            "gl_asset_account", "gl_accumulated_depreciation_account",
		            "gl_depreciation_expense_account")
		missing = [f for f in required if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		ac = AssetClass(
			tenant_id=data["tenant_id"],
			code=data["code"].upper(),
			name=data["name"],
			useful_life_years=data["useful_life_years"],
			depreciation_method=(data.get("depreciation_method") or "STRAIGHT_LINE").upper(),
			gl_asset_account=data["gl_asset_account"],
			gl_accumulated_depreciation_account=data["gl_accumulated_depreciation_account"],
			gl_depreciation_expense_account=data["gl_depreciation_expense_account"],
			gl_disposal_gain_account=data.get("gl_disposal_gain_account"),
			gl_disposal_loss_account=data.get("gl_disposal_loss_account"),
			metadata_=data.get("metadata") or {},
		)
		session.add(ac)
		session.commit()
		return jsonify({"ok": True, "id": ac.id}), 201

	@expose("/<string:class_id>", methods=["PUT"])
	@has_access
	def update(self, class_id: str):
		from pgappforge.plugins.erp.finance.assets.models import AssetClass
		session = _get_session()
		ac = session.get(AssetClass, class_id)
		if ac is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "useful_life_years", "depreciation_method",
		          "gl_asset_account", "gl_accumulated_depreciation_account",
		          "gl_depreciation_expense_account", "gl_disposal_gain_account",
		          "gl_disposal_loss_account", "is_active"):
			if f in data:
				setattr(ac, f, data[f])
		if "metadata" in data:
			ac.metadata_ = data["metadata"]
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# FixedAssetView
# ---------------------------------------------------------------------------

class FixedAssetView(BaseView):
	"""Fixed asset register CRUD + business actions.

	GET  /assets/register/               — list (JSON)
	GET  /assets/register/<id>           — detail (JSON)
	POST /assets/register/               — capitalise (JSON)
	POST /assets/register/<id>/dispose   — record disposal (JSON)
	POST /assets/register/<id>/impair    — record impairment (JSON)
	"""

	route_base = "/assets/register"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.assets.models import FixedAsset
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status")
		q = sa.select(FixedAsset).order_by(FixedAsset.asset_number)
		if tenant_id:
			q = q.where(FixedAsset.tenant_id == tenant_id)
		if status:
			q = q.where(FixedAsset.status == status.upper())
		assets = session.execute(q).scalars().all()
		return jsonify({
			"assets": [
				{
					"id": a.id,
					"asset_number": a.asset_number,
					"description": a.description,
					"asset_class_id": a.asset_class_id,
					"acquisition_date": str(a.acquisition_date) if a.acquisition_date else None,
					"acquisition_cost_cents": a.acquisition_cost_cents,
					"current_book_value_cents": a.current_book_value_cents,
					"accumulated_depreciation_cents": a.accumulated_depreciation_cents,
					"status": a.status,
					"depreciation_method": a.depreciation_method,
				}
				for a in assets
			]
		})

	@expose("/<string:asset_id>")
	@has_access
	def detail(self, asset_id: str):
		from pgappforge.plugins.erp.finance.assets.models import FixedAsset
		session = _get_session()
		asset = session.get(FixedAsset, asset_id)
		if asset is None:
			abort(404)
		return jsonify({
			"id": asset.id,
			"asset_number": asset.asset_number,
			"description": asset.description,
			"asset_class_id": asset.asset_class_id,
			"acquisition_date": str(asset.acquisition_date) if asset.acquisition_date else None,
			"acquisition_cost_cents": asset.acquisition_cost_cents,
			"residual_value_cents": asset.residual_value_cents,
			"useful_life_years": str(asset.useful_life_years),
			"depreciation_method": asset.depreciation_method,
			"current_book_value_cents": asset.current_book_value_cents,
			"accumulated_depreciation_cents": asset.accumulated_depreciation_cents,
			"location": asset.location,
			"serial_number": asset.serial_number,
			"status": asset.status,
			"last_depreciation_date": str(asset.last_depreciation_date) if asset.last_depreciation_date else None,
			"disposal_date": str(asset.disposal_date) if asset.disposal_date else None,
			"disposal_proceeds_cents": asset.disposal_proceeds_cents,
			"disposal_gain_loss_cents": asset.disposal_gain_loss_cents,
			"tenant_id": asset.tenant_id,
			"metadata": asset.metadata_,
		})

	@expose("/", methods=["POST"])
	@has_access
	def capitalise(self):
		"""POST /assets/register/ — capitalise a new fixed asset."""
		from pgappforge.plugins.erp.finance.assets.services import AssetService, CapitaliseDetails, AssetServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		required = ("tenant_id", "asset_class_id", "description",
		            "acquisition_date", "acquisition_cost_cents")
		missing = [f for f in required if not data.get(f) and data.get(f) != 0]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		try:
			from decimal import Decimal
			details = CapitaliseDetails(
				tenant_id=data["tenant_id"],
				asset_class_id=data["asset_class_id"],
				description=data["description"],
				acquisition_date=date.fromisoformat(data["acquisition_date"]),
				acquisition_cost_cents=int(data["acquisition_cost_cents"]),
				residual_value_cents=int(data.get("residual_value_cents") or 0),
				useful_life_years=Decimal(str(data["useful_life_years"])) if data.get("useful_life_years") else None,
				depreciation_method=data.get("depreciation_method"),
				location=data.get("location"),
				custodian_id=data.get("custodian_id"),
				serial_number=data.get("serial_number"),
				asset_number=data.get("asset_number"),
				metadata=data.get("metadata"),
			)
			asset = AssetService().capitalize(details, session)
			session.commit()
			return jsonify({"ok": True, "id": asset.id, "asset_number": asset.asset_number}), 201
		except AssetServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:asset_id>/dispose", methods=["POST"])
	@has_access
	def dispose(self, asset_id: str):
		"""POST /assets/register/<id>/dispose — record asset disposal."""
		from pgappforge.plugins.erp.finance.assets.services import AssetService, AssetServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		proceeds = data.get("proceeds_cents")
		if proceeds is None:
			return jsonify({"ok": False, "error": "proceeds_cents required"}), 400
		disposal_date = date.fromisoformat(data["disposal_date"]) if data.get("disposal_date") else None
		try:
			asset = AssetService().record_disposal(
				asset_id, int(proceeds), session, disposal_date=disposal_date,
			)
			session.commit()
			return jsonify({
				"ok": True,
				"asset_number": asset.asset_number,
				"gain_loss_cents": asset.disposal_gain_loss_cents,
			})
		except AssetServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400

	@expose("/<string:asset_id>/impair", methods=["POST"])
	@has_access
	def impair(self, asset_id: str):
		"""POST /assets/register/<id>/impair — record IAS 36 impairment."""
		from pgappforge.plugins.erp.finance.assets.services import AssetService, AssetServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		recoverable = data.get("recoverable_amount_cents")
		reason = data.get("reason", "")
		if recoverable is None or not reason:
			return jsonify({"ok": False, "error": "recoverable_amount_cents and reason required"}), 400
		imp_date = date.fromisoformat(data["impairment_date"]) if data.get("impairment_date") else None
		try:
			impairment = AssetService().record_impairment(
				asset_id, int(recoverable), reason, session, impairment_date=imp_date,
			)
			session.commit()
			return jsonify({
				"ok": True,
				"id": impairment.id,
				"impairment_loss_cents": impairment.impairment_loss_cents,
			})
		except AssetServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# AssetDepreciationView
# ---------------------------------------------------------------------------

class AssetDepreciationView(BaseView):
	"""Depreciation entries browser + run trigger.

	GET  /assets/depreciation/       — list entries (JSON, filterable by asset/period)
	POST /assets/depreciation/run    — trigger depreciation run for a period
	"""

	route_base = "/assets/depreciation"
	default_view = "list"

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.finance.assets.models import AssetDepreciation
		session = _get_session()
		asset_id = request.args.get("asset_id")
		period_id = request.args.get("period_id")
		q = (
			sa.select(AssetDepreciation)
			.order_by(sa.desc(AssetDepreciation.posted_at))
			.limit(500)
		)
		if asset_id:
			q = q.where(AssetDepreciation.asset_id == asset_id)
		if period_id:
			q = q.where(AssetDepreciation.period_id == period_id)
		entries = session.execute(q).scalars().all()
		return jsonify({
			"entries": [
				{
					"id": e.id,
					"asset_id": e.asset_id,
					"period_id": e.period_id,
					"depreciation_amount_cents": e.depreciation_amount_cents,
					"opening_nbv_cents": e.opening_nbv_cents,
					"closing_nbv_cents": e.closing_nbv_cents,
					"method_used": e.method_used,
					"posted_at": e.posted_at.isoformat() if e.posted_at else None,
				}
				for e in entries
			]
		})

	@expose("/run", methods=["POST"])
	@has_access
	def run_depreciation(self):
		"""POST /assets/depreciation/run — trigger periodic depreciation run."""
		from pgappforge.plugins.erp.finance.assets.services import AssetService, AssetServiceError
		session = _get_session()
		data = request.get_json(silent=True) or {}
		period_id = data.get("period_id", "").strip()
		if not period_id:
			return jsonify({"ok": False, "error": "period_id required (e.g. '2026-01')"}), 400
		try:
			entries = AssetService().run_depreciation(
				period_id, session,
				tenant_id=data.get("tenant_id"),
			)
			session.commit()
			return jsonify({
				"ok": True,
				"period_id": period_id,
				"assets_processed": len(entries),
				"total_depreciation_cents": sum(e.depreciation_amount_cents for e in entries),
			})
		except AssetServiceError as exc:
			return jsonify({"ok": False, "error": str(exc)}), 400


# ---------------------------------------------------------------------------
# AssetReportView  (3 reports)
# ---------------------------------------------------------------------------

class AssetReportView(BaseView):
	"""Asset Accounting reports.

	GET /assets/reports/register                   — Fixed Asset Register (HTML)
	GET /assets/reports/depreciation-schedule/<id> — Full depreciation schedule (HTML)
	GET /assets/reports/nbv-summary                — NBV Summary by class (HTML)
	"""

	route_base = "/assets/reports"
	default_view = "register"

	@expose("/register")
	@has_access
	def register(self):
		"""Fixed Asset Register — all assets with cost, accumulated depreciation, NBV."""
		from pgappforge.plugins.erp.finance.assets.models import AssetClass, FixedAsset
		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		status = request.args.get("status", "ACTIVE")

		q = (
			sa.select(FixedAsset, AssetClass.name.label("class_name"))
			.join(AssetClass, FixedAsset.asset_class_id == AssetClass.id)
			.order_by(AssetClass.name, FixedAsset.asset_number)
		)
		if tenant_id:
			q = q.where(FixedAsset.tenant_id == tenant_id)
		if status != "ALL":
			q = q.where(FixedAsset.status == status.upper())

		rows_data = session.execute(q).all()

		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(r.FixedAsset.asset_number)}</td>"
			f"<td>{_he(r.class_name)}</td>"
			f"<td>{_he(r.FixedAsset.description[:60])}</td>"
			f"<td>{_he(str(r.FixedAsset.acquisition_date) if r.FixedAsset.acquisition_date else '')}</td>"
			f"<td style='text-align:right'>{_fmt_cents(r.FixedAsset.acquisition_cost_cents)}</td>"
			f"<td style='text-align:right'>{_fmt_cents(r.FixedAsset.accumulated_depreciation_cents)}</td>"
			f"<td style='text-align:right'><strong>{_fmt_cents(r.FixedAsset.current_book_value_cents)}</strong></td>"
			f"<td>{_he(r.FixedAsset.status)}</td>"
			f"</tr>"
			for r in rows_data
		)
		total_cost = sum(r.FixedAsset.acquisition_cost_cents for r in rows_data)
		total_accum = sum(r.FixedAsset.accumulated_depreciation_cents for r in rows_data)
		total_nbv = sum(r.FixedAsset.current_book_value_cents for r in rows_data)

		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Fixed Asset Register</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}} @media print{{.noprint{{display:none}}}}</style>
</head><body>
<h3>Fixed Asset Register</h3>
<div class="noprint" style="margin-bottom:8px">
  <a href="?status=ACTIVE" class="btn btn-xs btn-default">Active</a>
  <a href="?status=DISPOSED" class="btn btn-xs btn-default">Disposed</a>
  <a href="?status=ALL" class="btn btn-xs btn-default">All</a>
  <button onclick="window.print()" class="btn btn-xs btn-primary">Print</button>
</div>
<table class="table table-bordered table-condensed table-hover" style="font-size:0.85em">
<thead><tr><th>Asset No.</th><th>Class</th><th>Description</th><th>Acquired</th>
<th style="text-align:right">Cost</th><th style="text-align:right">Accum. Dep.</th>
<th style="text-align:right">NBV</th><th>Status</th></tr></thead>
<tbody>{table_rows}</tbody>
<tfoot><tr class="info">
  <td colspan="4"><strong>Totals</strong></td>
  <td style="text-align:right"><strong>{_fmt_cents(total_cost)}</strong></td>
  <td style="text-align:right"><strong>{_fmt_cents(total_accum)}</strong></td>
  <td style="text-align:right"><strong>{_fmt_cents(total_nbv)}</strong></td>
  <td></td>
</tr></tfoot>
</table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} — {len(rows_data)} assets</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/depreciation-schedule/<string:asset_id>")
	@has_access
	def depreciation_schedule(self, asset_id: str):
		"""Full depreciation schedule for a single asset (HTML)."""
		from pgappforge.plugins.erp.finance.assets.models import AssetDepreciation, FixedAsset
		session = _get_session()
		asset = session.get(FixedAsset, asset_id)
		if asset is None:
			abort(404)
		entries = session.execute(
			sa.select(AssetDepreciation)
			.where(AssetDepreciation.asset_id == asset_id)
			.order_by(AssetDepreciation.period_id)
		).scalars().all()
		table_rows = "".join(
			f"<tr>"
			f"<td>{_he(e.period_id)}</td>"
			f"<td style='text-align:right'>{_fmt_cents(e.opening_nbv_cents)}</td>"
			f"<td style='text-align:right'>{_fmt_cents(e.depreciation_amount_cents)}</td>"
			f"<td style='text-align:right'><strong>{_fmt_cents(e.closing_nbv_cents)}</strong></td>"
			f"<td>{_he(e.method_used)}</td>"
			f"</tr>"
			for e in entries
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Depreciation Schedule — {_he(asset.asset_number)}</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style></head><body>
<h3>Depreciation Schedule: {_he(asset.asset_number)} — {_he(asset.description)}</h3>
<dl class="dl-horizontal">
  <dt>Cost</dt><dd>{_fmt_cents(asset.acquisition_cost_cents)}</dd>
  <dt>Residual</dt><dd>{_fmt_cents(asset.residual_value_cents)}</dd>
  <dt>Method</dt><dd>{_he(asset.depreciation_method)}</dd>
  <dt>Useful Life</dt><dd>{asset.useful_life_years} years</dd>
  <dt>Current NBV</dt><dd><strong>{_fmt_cents(asset.current_book_value_cents)}</strong></dd>
</dl>
<table class="table table-bordered table-condensed">
<thead><tr><th>Period</th><th style="text-align:right">Opening NBV</th>
<th style="text-align:right">Charge</th><th style="text-align:right">Closing NBV</th><th>Method</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">{len(entries)} periods — Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)

	@expose("/nbv-summary")
	@has_access
	def nbv_summary(self):
		"""NBV Summary by asset class (HTML)."""
		from pgappforge.plugins.erp.finance.assets.models import AssetClass, FixedAsset
		session = _get_session()
		tenant_id = request.args.get("tenant_id")

		q = (
			sa.select(
				AssetClass.code,
				AssetClass.name,
				sa.func.count(FixedAsset.id).label("count"),
				sa.func.sum(FixedAsset.acquisition_cost_cents).label("total_cost"),
				sa.func.sum(FixedAsset.accumulated_depreciation_cents).label("total_accum"),
				sa.func.sum(FixedAsset.current_book_value_cents).label("total_nbv"),
			)
			.join(FixedAsset, FixedAsset.asset_class_id == AssetClass.id)
			.where(FixedAsset.status.in_(["ACTIVE", "IMPAIRED", "FULLY_DEPRECIATED"]))
			.group_by(AssetClass.code, AssetClass.name)
			.order_by(AssetClass.code)
		)
		if tenant_id:
			q = q.where(FixedAsset.tenant_id == tenant_id)
		rows = session.execute(q).all()

		table_rows = "".join(
			f"<tr><td>{_he(r.code)}</td><td>{_he(r.name)}</td>"
			f"<td style='text-align:right'>{r.count}</td>"
			f"<td style='text-align:right'>{_fmt_cents(int(r.total_cost or 0))}</td>"
			f"<td style='text-align:right'>{_fmt_cents(int(r.total_accum or 0))}</td>"
			f"<td style='text-align:right'><strong>{_fmt_cents(int(r.total_nbv or 0))}</strong></td>"
			f"</tr>"
			for r in rows
		)
		html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>NBV Summary</title>
<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
<style>body{{padding:24px}}</style></head><body>
<h3>Net Book Value Summary by Asset Class</h3>
<p style="color:#888">As at {datetime.now(timezone.utc).strftime('%Y-%m-%d')} (active/impaired/fully-depreciated assets)</p>
<table class="table table-bordered table-condensed">
<thead><tr><th>Code</th><th>Class Name</th><th style="text-align:right">Count</th>
<th style="text-align:right">Total Cost</th><th style="text-align:right">Accum. Dep.</th>
<th style="text-align:right">NBV</th></tr></thead>
<tbody>{table_rows}</tbody></table>
<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
</body></html>"""
		return make_response(html, 200)


__all__ = [
	"AssetClassView",
	"FixedAssetView",
	"AssetDepreciationView",
	"AssetReportView",
]
