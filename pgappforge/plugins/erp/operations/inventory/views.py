"""
pgappforge/plugins/erp/operations/inventory/views.py

Flask views for the Inventory plugin.

Registered views:
  ProductCategoryView   — CRUD for product taxonomy
  ProductView           — CRUD + deactivate action
  WarehouseView         — CRUD + activate/deactivate
  StockLevelView        — read-only stock position with filters
  StockMovementView     — read-only immutable movement log
  InventoryReportView   — 3 canned reports:
                          * Stock Valuation
                          * Reorder Suggestions
                          * Movement History
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import sqlalchemy as sa
from flask import abort, jsonify, make_response, request

from pgappforge import expose
from pgappforge.plugins.erp.base_view import BaseERPView
from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
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


def _qty_cost_cents(qty: object, unit_cost_cents: int | None) -> int:
	return int(
		(Decimal(str(qty or 0)) * Decimal(int(unit_cost_cents or 0)))
		.to_integral_value(rounding=ROUND_HALF_UP)
	)


def _yes_no_badge(active: bool) -> str:
	return (
		'<span class="label label-success">Yes</span>'
		if active else '<span class="label label-default">No</span>'
	)


def _page_html(title: str, body: str) -> str:
	return (
		f'<!DOCTYPE html><html><head><meta charset="utf-8"><title>{title}</title>'
		'<link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">'
		'<style>body{padding:24px} @media print{.noprint{display:none}}</style>'
		f'</head><body>{body}</body></html>'
	)


# ---------------------------------------------------------------------------
# ProductCategoryView
# ---------------------------------------------------------------------------

class ProductCategoryView(BaseERPView):
	"""Product category hierarchy CRUD.

	GET  /inv/categories/         — list (flat with parent names)
	GET  /inv/categories/<id>     — detail (JSON)
	POST /inv/categories/         — create
	PUT  /inv/categories/<id>     — update
	"""

	route_base = "/inv/categories"
	default_view = "list"
	show_columns = ["code", "name", "parent_id", "gl_account", "is_active"]
	search_columns = ["code", "name", "gl_account"]
	label_columns = {
		"code": "Code",
		"name": "Name",
		"parent_id": "Parent",
		"gl_account": "GL Account",
		"is_active": "Active",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.inventory.models import ProductCategory
		session = _get_session()
		q = sa.select(ProductCategory).order_by(ProductCategory.code)
		if request.args.get("tenant_id"):
			q = q.where(ProductCategory.tenant_id == request.args["tenant_id"])
		cats = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"categories": [
				{
					"id": c.id, "code": c.code, "name": c.name,
					"parent_id": c.parent_id, "gl_account": c.gl_account,
					"is_active": c.is_active,
				}
				for c in cats
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(c.code)}</td>"
			f"<td>{_he(c.name)}</td>"
			f"<td>{_he(c.parent_id or '')}</td>"
			f"<td>{_he(c.gl_account or '')}</td>"
			f"<td>{'Yes' if c.is_active else 'No'}</td>"
			f"<td><a href='/inv/categories/{_he(c.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for c in cats
		)
		body = (
			'<h3>Product Categories</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Code</th><th>Name</th><th>Parent</th><th>GL Account</th><th>Active</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Product Categories", body), 200)

	@expose("/<string:cat_id>")
	@has_access
	def detail(self, cat_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import ProductCategory
		session = _get_session()
		cat = session.get(ProductCategory, cat_id)
		if cat is None:
			abort(404)
		return jsonify({
			"id": cat.id, "tenant_id": cat.tenant_id,
			"code": cat.code, "name": cat.name,
			"parent_id": cat.parent_id, "gl_account": cat.gl_account,
			"is_active": cat.is_active,
			"created_at": cat.created_at.isoformat() if cat.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.inventory.models import ProductCategory
		session = _get_session()
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "code", "name") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		cat = ProductCategory(
			tenant_id=data["tenant_id"],
			code=data["code"],
			name=data["name"],
			parent_id=data.get("parent_id"),
			gl_account=data.get("gl_account"),
			is_active=bool(data.get("is_active", True)),
		)
		session.add(cat)
		session.commit()
		return jsonify({"ok": True, "id": cat.id}), 201

	@expose("/<string:cat_id>", methods=["PUT"])
	@has_access
	def update(self, cat_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import ProductCategory
		session = _get_session()
		cat = session.get(ProductCategory, cat_id)
		if cat is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "parent_id", "gl_account", "is_active"):
			if f in data:
				setattr(cat, f, data[f])
		cat.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# ProductView
# ---------------------------------------------------------------------------

class ProductView(BaseERPView):
	"""Product master CRUD.

	GET  /inv/products/               — list with filters
	GET  /inv/products/<id>           — detail (JSON)
	POST /inv/products/               — create
	PUT  /inv/products/<id>           — update
	POST /inv/products/<id>/deactivate — set is_active=False
	"""

	route_base = "/inv/products"
	default_view = "list"
	show_columns = [
		"sku", "barcode", "name", "uom", "category_id",
		"cost_price_cents", "reorder_point", "max_stock_level",
		"qty_issued_ytd", "valuation_method", "is_active",
	]
	search_columns = ["sku", "barcode", "name", "brand", "valuation_method"]
	label_columns = {
		"sku": "SKU",
		"barcode": "Barcode",
		"name": "Name",
		"uom": "UOM",
		"category_id": "Category",
		"cost_price_cents": "Cost (cents)",
		"reorder_point": "Reorder Point",
		"max_stock_level": "Max Stock Level",
		"qty_issued_ytd": "Qty Issued YTD",
		"valuation_method": "Valuation Method",
		"is_active": "Active",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.inventory.models import Product
		session = _get_session()
		q = sa.select(Product).order_by(Product.sku)
		if request.args.get("tenant_id"):
			q = q.where(Product.tenant_id == request.args["tenant_id"])
		if request.args.get("category_id"):
			q = q.where(Product.category_id == request.args["category_id"])
		if request.args.get("active_only", "1") == "1":
			q = q.where(Product.is_active.is_(True))
		if request.args.get("search"):
			term = f"%{request.args['search']}%"
			q = q.where(sa.or_(Product.sku.ilike(term), Product.name.ilike(term)))
		products = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"products": [
				{
					"id": p.id, "sku": p.sku, "barcode": p.barcode,
					"name": p.name, "uom": p.uom, "category_id": p.category_id,
					"base_price_cents": p.base_price_cents,
					"cost_price_cents": p.cost_price_cents,
					"currency_code": p.currency_code,
					"reorder_point": str(p.reorder_point),
					"max_stock_level": str(p.max_stock_level),
					"qty_issued_ytd": str(p.qty_issued_ytd),
					"valuation_method": p.valuation_method,
					"is_active": p.is_active,
				}
				for p in products
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(p.sku)}</td>"
			f"<td>{_he(p.barcode or '')}</td>"
			f"<td>{_he(p.name)}</td>"
			f"<td>{_he(p.uom)}</td>"
			f"<td class='text-right'>{_he(p.currency_code)} {p.cost_price_cents / 100:,.4f}</td>"
			f"<td>{_he(p.valuation_method)}</td>"
			f"<td>{_yes_no_badge(p.is_active)}</td>"
			f"<td><a href='/inv/products/{_he(p.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for p in products
		)
		body = (
			'<h3>Products</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>SKU</th><th>Barcode</th><th>Name</th><th>UOM</th>'
			'<th>Cost</th><th>Valuation</th><th>Active</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Products", body), 200)

	@expose("/<string:product_id>")
	@has_access
	def detail(self, product_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import Product
		session = _get_session()
		p = session.get(Product, product_id)
		if p is None:
			abort(404)
		return jsonify({
			"id": p.id, "tenant_id": p.tenant_id,
			"sku": p.sku, "barcode": p.barcode, "name": p.name,
			"description": p.description, "category_id": p.category_id,
			"brand": p.brand, "uom": p.uom,
			"weight_grams": p.weight_grams, "dimensions_cm": p.dimensions_cm,
			"base_price_cents": p.base_price_cents,
			"cost_price_cents": p.cost_price_cents,
			"standard_cost_cents": p.standard_cost_cents,
			"currency_code": p.currency_code,
			"reorder_point": str(p.reorder_point),
			"reorder_quantity": str(p.reorder_quantity),
			"max_stock_level": str(p.max_stock_level),
			"qty_issued_ytd": str(p.qty_issued_ytd),
			"lead_time_days": p.lead_time_days,
			"is_lot_tracked": p.is_lot_tracked,
			"is_serial_tracked": p.is_serial_tracked,
			"is_batch_managed": p.is_batch_managed,
			"is_hazardous": p.is_hazardous,
			"shelf_life_days": p.shelf_life_days,
			"valuation_method": p.valuation_method,
			"gl_inventory_account": p.gl_inventory_account,
			"gl_cogs_account": p.gl_cogs_account,
			"is_active": p.is_active,
			"created_at": p.created_at.isoformat() if p.created_at else None,
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.inventory.models import Product
		from pgappforge.plugins.erp.operations.inventory.events import ProductCreatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "sku", "name", "uom") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400

		p = Product(
			tenant_id=data["tenant_id"],
			sku=data["sku"],
			barcode=data.get("barcode"),
			name=data["name"],
			description=data.get("description"),
			category_id=data.get("category_id"),
			brand=data.get("brand"),
			uom=data["uom"],
			weight_grams=data.get("weight_grams"),
			dimensions_cm=data.get("dimensions_cm") or {},
			base_price_cents=int(data.get("base_price_cents", 0)),
			cost_price_cents=int(data.get("cost_price_cents", 0)),
			currency_code=data.get("currency_code", "USD"),
			reorder_point=data.get("reorder_point", 0),
			reorder_quantity=data.get("reorder_quantity", 0),
			max_stock_level=data.get("max_stock_level", 0),
			qty_issued_ytd=data.get("qty_issued_ytd", 0),
			lead_time_days=int(data.get("lead_time_days", 0)),
			is_lot_tracked=bool(data.get("is_lot_tracked", False)),
			is_serial_tracked=bool(data.get("is_serial_tracked", False)),
			is_batch_managed=bool(data.get("is_batch_managed", False)),
			is_hazardous=bool(data.get("is_hazardous", False)),
			shelf_life_days=data.get("shelf_life_days"),
			valuation_method=data.get("valuation_method", "WEIGHTED_AVG"),
			standard_cost_cents=int(data.get("standard_cost_cents", 0)) if data.get("standard_cost_cents") is not None else None,
			gl_inventory_account=data.get("gl_inventory_account"),
			gl_cogs_account=data.get("gl_cogs_account"),
			is_active=bool(data.get("is_active", True)),
		)
		session.add(p)
		session.flush()
		emit_event(
			ProductCreatedEvent(
				aggregate_id=p.id,
				aggregate_type="Product",
				tenant_id=p.tenant_id,
				product_id=p.id,
				sku=p.sku,
				name=p.name,
				uom=p.uom,
				valuation_method=p.valuation_method,
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "id": p.id}), 201

	@expose("/<string:product_id>", methods=["PUT"])
	@has_access
	def update(self, product_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import Product
		session = _get_session()
		p = session.get(Product, product_id)
		if p is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in (
			"name", "description", "category_id", "brand", "uom",
			"weight_grams", "dimensions_cm",
			"base_price_cents", "cost_price_cents", "standard_cost_cents",
			"currency_code", "reorder_point", "reorder_quantity", "max_stock_level",
			"qty_issued_ytd", "lead_time_days",
			"is_lot_tracked", "is_serial_tracked", "is_batch_managed",
			"is_hazardous", "shelf_life_days", "valuation_method",
			"gl_inventory_account", "gl_cogs_account",
		):
			if f in data:
				setattr(p, f, data[f])
		p.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:product_id>/deactivate", methods=["POST"])
	@has_access
	def deactivate(self, product_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import Product
		from pgappforge.plugins.erp.operations.inventory.events import ProductDeactivatedEvent
		from pgappforge.plugins.erp.foundation.events import emit_event
		session = _get_session()
		p = session.get(Product, product_id)
		if p is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		p.is_active = False
		p.updated_at = datetime.now(timezone.utc)
		emit_event(
			ProductDeactivatedEvent(
				aggregate_id=product_id,
				aggregate_type="Product",
				tenant_id=p.tenant_id,
				product_id=product_id,
				sku=p.sku,
				reason=data.get("reason", ""),
			),
			session,
		)
		session.commit()
		return jsonify({"ok": True, "is_active": False})


# ---------------------------------------------------------------------------
# WarehouseView
# ---------------------------------------------------------------------------

class WarehouseView(BaseERPView):
	"""Warehouse + location management.

	GET  /inv/warehouses/                 — list
	GET  /inv/warehouses/<id>             — detail with locations
	POST /inv/warehouses/                 — create
	PUT  /inv/warehouses/<id>             — update
	GET  /inv/warehouses/<id>/locations   — list locations
	POST /inv/warehouses/<id>/locations   — add location
	"""

	route_base = "/inv/warehouses"
	default_view = "list"
	show_columns = ["code", "name", "warehouse_type", "timezone", "manager_id", "is_active"]
	search_columns = ["code", "name", "warehouse_type", "timezone"]
	label_columns = {
		"code": "Code",
		"name": "Name",
		"warehouse_type": "Type",
		"timezone": "Timezone",
		"manager_id": "Manager",
		"is_active": "Active",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.inventory.models import Warehouse
		session = _get_session()
		q = sa.select(Warehouse).order_by(Warehouse.code)
		if request.args.get("tenant_id"):
			q = q.where(Warehouse.tenant_id == request.args["tenant_id"])
		whs = session.execute(q.limit(200)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({"warehouses": [
				{
					"id": w.id, "code": w.code, "name": w.name,
					"warehouse_type": w.warehouse_type,
					"timezone": w.timezone,
					"is_active": w.is_active,
				}
				for w in whs
			]})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(w.code)}</td>"
			f"<td>{_he(w.name)}</td>"
			f"<td>{_he(w.warehouse_type)}</td>"
			f"<td>{_he(w.timezone or 'UTC')}</td>"
			f"<td>{'Yes' if w.is_active else 'No'}</td>"
			f"<td><a href='/inv/warehouses/{_he(w.id)}' class='btn btn-xs btn-primary'>View</a></td>"
			f"</tr>"
			for w in whs
		)
		body = (
			'<h3>Warehouses</h3>'
			'<table class="table table-bordered table-condensed">'
			'<thead><tr><th>Code</th><th>Name</th><th>Type</th><th>TZ</th><th>Active</th><th></th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
		)
		return make_response(_page_html("Warehouses", body), 200)

	@expose("/<string:wh_id>")
	@has_access
	def detail(self, wh_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import Warehouse
		session = _get_session()
		wh = session.get(Warehouse, wh_id)
		if wh is None:
			abort(404)
		return jsonify({
			"id": wh.id, "tenant_id": wh.tenant_id,
			"code": wh.code, "name": wh.name,
			"warehouse_type": wh.warehouse_type,
			"address": wh.address, "timezone": wh.timezone,
			"manager_id": wh.manager_id, "is_active": wh.is_active,
			"locations": [
				{
					"id": l.id, "aisle": l.aisle, "rack": l.rack, "bin": l.bin,
					"zone": l.zone, "location_type": l.location_type,
					"capacity_units": str(l.capacity_units) if l.capacity_units else None,
					"capacity_uom": l.capacity_uom, "is_active": l.is_active,
				}
				for l in wh.locations
			],
		})

	@expose("/", methods=["POST"])
	@has_access
	def create(self):
		from pgappforge.plugins.erp.operations.inventory.models import Warehouse
		session = _get_session()
		data = request.get_json(silent=True) or {}
		missing = [f for f in ("tenant_id", "code", "name") if not data.get(f)]
		if missing:
			return jsonify({"ok": False, "error": f"missing: {missing}"}), 400
		wh = Warehouse(
			tenant_id=data["tenant_id"],
			code=data["code"],
			name=data["name"],
			warehouse_type=data.get("warehouse_type", "OWNED"),
			address=data.get("address") or {},
			timezone=data.get("timezone", "UTC"),
			manager_id=data.get("manager_id"),
			is_active=bool(data.get("is_active", True)),
		)
		session.add(wh)
		session.commit()
		return jsonify({"ok": True, "id": wh.id}), 201

	@expose("/<string:wh_id>", methods=["PUT"])
	@has_access
	def update(self, wh_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import Warehouse
		session = _get_session()
		wh = session.get(Warehouse, wh_id)
		if wh is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		for f in ("name", "warehouse_type", "address", "timezone", "manager_id", "is_active"):
			if f in data:
				setattr(wh, f, data[f])
		wh.updated_at = datetime.now(timezone.utc)
		session.commit()
		return jsonify({"ok": True})

	@expose("/<string:wh_id>/locations")
	@has_access
	def locations(self, wh_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import WarehouseLocation
		session = _get_session()
		locs = session.execute(
			sa.select(WarehouseLocation)
			.where(WarehouseLocation.warehouse_id == wh_id)
			.order_by(WarehouseLocation.aisle, WarehouseLocation.rack, WarehouseLocation.bin)
		).scalars().all()
		return jsonify({"locations": [
			{
				"id": l.id, "aisle": l.aisle, "rack": l.rack, "bin": l.bin,
				"zone": l.zone, "location_type": l.location_type,
				"capacity_units": str(l.capacity_units) if l.capacity_units else None,
				"capacity_uom": l.capacity_uom, "is_active": l.is_active,
			}
			for l in locs
		]})

	@expose("/<string:wh_id>/locations", methods=["POST"])
	@has_access
	def add_location(self, wh_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import Warehouse, WarehouseLocation
		session = _get_session()
		wh = session.get(Warehouse, wh_id)
		if wh is None:
			abort(404)
		data = request.get_json(silent=True) or {}
		loc = WarehouseLocation(
			tenant_id=wh.tenant_id,
			warehouse_id=wh_id,
			aisle=data.get("aisle"),
			rack=data.get("rack"),
			bin=data.get("bin"),
			zone=data.get("zone"),
			location_type=data.get("location_type", "BULK"),
			capacity_units=data.get("capacity_units"),
			capacity_uom=data.get("capacity_uom"),
			is_active=bool(data.get("is_active", True)),
		)
		session.add(loc)
		session.commit()
		return jsonify({"ok": True, "id": loc.id}), 201


# ---------------------------------------------------------------------------
# StockLevelView
# ---------------------------------------------------------------------------

class StockLevelView(BaseERPView):
	"""Read-only stock position.

	GET /inv/stock/                — list with filters
	GET /inv/stock/<product_id>   — positions for a product across warehouses
	"""

	route_base = "/inv/stock"
	default_view = "list"
	show_columns = [
		"product_id", "warehouse_id", "location_id", "lot_number",
		"quantity_on_hand", "quantity_reserved", "quantity_available",
		"average_cost_cents", "last_movement_date", "receipt_date",
	]
	search_columns = ["product_id", "warehouse_id", "location_id", "lot_number", "serial_number"]
	label_columns = {
		"product_id": "Product",
		"warehouse_id": "Warehouse",
		"location_id": "Location",
		"lot_number": "Lot",
		"quantity_on_hand": "On Hand",
		"quantity_reserved": "Reserved",
		"quantity_available": "Available",
		"average_cost_cents": "Average Cost (cents)",
		"last_movement_date": "Last Movement Date",
		"receipt_date": "Receipt Date",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel, Product
		session = _get_session()
		q = (
			sa.select(StockLevel, Product)
			.join(Product, StockLevel.product_id == Product.id)
			.order_by(Product.sku)
		)
		for field, col in (
			("tenant_id", StockLevel.tenant_id),
			("warehouse_id", StockLevel.warehouse_id),
			("location_id", StockLevel.location_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		if request.args.get("low_stock"):
			# Only products below reorder point
			q = q.where(StockLevel.quantity_available <= Product.reorder_point)

		rows_raw = session.execute(q.limit(1000)).all()

		return jsonify({"stock": [
			{
				"product_id": sl.product_id,
				"sku": prod.sku,
				"name": prod.name,
				"warehouse_id": sl.warehouse_id,
				"location_id": sl.location_id,
				"lot_number": sl.lot_number,
				"expiry_date": sl.expiry_date.isoformat() if sl.expiry_date else None,
				"quantity_on_hand": str(sl.quantity_on_hand),
				"quantity_reserved": str(sl.quantity_reserved),
				"quantity_available": str(sl.quantity_available),
				"quantity_in_transit": str(sl.quantity_in_transit),
				"average_cost_cents": sl.average_cost_cents,
				"last_movement_at": sl.last_movement_at.isoformat() if sl.last_movement_at else None,
				"last_movement_date": sl.last_movement_date.isoformat() if sl.last_movement_date else None,
				"receipt_date": sl.receipt_date.isoformat() if sl.receipt_date else None,
			}
			for sl, prod in rows_raw
		]})

	@expose("/<string:product_id>")
	@has_access
	def by_product(self, product_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel, Product
		session = _get_session()
		prod = session.get(Product, product_id)
		if prod is None:
			abort(404)
		levels = session.execute(
			sa.select(StockLevel)
			.where(StockLevel.product_id == product_id)
			.order_by(StockLevel.warehouse_id)
		).scalars().all()
		return jsonify({
			"product_id": product_id, "sku": prod.sku, "name": prod.name,
			"reorder_point": str(prod.reorder_point),
			"reorder_quantity": str(prod.reorder_quantity),
			"positions": [
				{
					"warehouse_id": sl.warehouse_id,
					"location_id": sl.location_id,
					"lot_number": sl.lot_number,
					"quantity_on_hand": str(sl.quantity_on_hand),
					"quantity_available": str(sl.quantity_available),
					"quantity_reserved": str(sl.quantity_reserved),
					"average_cost_cents": sl.average_cost_cents,
					"last_movement_date": sl.last_movement_date.isoformat() if sl.last_movement_date else None,
					"receipt_date": sl.receipt_date.isoformat() if sl.receipt_date else None,
				}
				for sl in levels
			],
		})


# ---------------------------------------------------------------------------
# StockMovementView
# ---------------------------------------------------------------------------

class StockMovementView(BaseERPView):
	"""Read-only immutable stock movement ledger.

	GET /inv/movements/           — list with filters (product, warehouse, type, date range)
	GET /inv/movements/<id>       — single movement detail
	"""

	route_base = "/inv/movements"
	default_view = "list"
	show_columns = [
		"product_id", "warehouse_id", "movement_type", "quantity",
		"direction", "unit_cost_cents", "total_cost_cents",
		"reference_type", "reference_id", "moved_at",
	]
	search_columns = ["product_id", "warehouse_id", "movement_type", "reference_type", "reference_id", "lot_number"]
	label_columns = {
		"product_id": "Product",
		"warehouse_id": "Warehouse",
		"movement_type": "Movement Type",
		"quantity": "Quantity",
		"direction": "Direction",
		"unit_cost_cents": "Unit Cost (cents)",
		"total_cost_cents": "Total Cost (cents)",
		"reference_type": "Reference Type",
		"reference_id": "Reference",
		"moved_at": "Moved At",
	}

	@expose("/")
	@has_access
	def list(self):
		from pgappforge.plugins.erp.operations.inventory.models import StockMovement
		session = _get_session()
		q = sa.select(StockMovement).order_by(sa.desc(StockMovement.moved_at))
		for field, col in (
			("tenant_id", StockMovement.tenant_id),
			("product_id", StockMovement.product_id),
			("warehouse_id", StockMovement.warehouse_id),
			("movement_type", StockMovement.movement_type),
			("reference_id", StockMovement.reference_id),
		):
			val = request.args.get(field)
			if val:
				q = q.where(col == val)
		if request.args.get("from_date"):
			q = q.where(StockMovement.moved_at >= date.fromisoformat(request.args["from_date"]))
		if request.args.get("to_date"):
			to_date = date.fromisoformat(request.args["to_date"])
			q = q.where(StockMovement.moved_at <= datetime.combine(to_date, time.max))

		movements = session.execute(q.limit(1000)).scalars().all()
		return jsonify({"movements": [
			{
				"id": m.id,
				"product_id": m.product_id,
				"warehouse_id": m.warehouse_id,
				"movement_type": m.movement_type,
				"quantity": str(m.quantity),
				"direction": m.direction,
				"unit_cost_cents": m.unit_cost_cents,
				"total_cost_cents": m.total_cost_cents,
				"lot_number": m.lot_number,
				"serial_number": m.serial_number,
				"reference_type": m.reference_type,
				"reference_id": m.reference_id,
				"moved_by": m.moved_by,
				"moved_at": m.moved_at.isoformat() if m.moved_at else None,
			}
			for m in movements
		]})

	@expose("/<string:movement_id>")
	@has_access
	def detail(self, movement_id: str):
		from pgappforge.plugins.erp.operations.inventory.models import StockMovement
		session = _get_session()
		m = session.get(StockMovement, movement_id)
		if m is None:
			abort(404)
		return jsonify({
			"id": m.id, "tenant_id": m.tenant_id,
			"product_id": m.product_id, "warehouse_id": m.warehouse_id,
			"from_location_id": m.from_location_id, "to_location_id": m.to_location_id,
			"movement_type": m.movement_type,
			"quantity": str(m.quantity), "direction": m.direction,
			"unit_cost_cents": m.unit_cost_cents, "total_cost_cents": m.total_cost_cents,
			"lot_number": m.lot_number, "serial_number": m.serial_number,
			"expiry_date": m.expiry_date.isoformat() if m.expiry_date else None,
			"reference_type": m.reference_type, "reference_id": m.reference_id,
			"notes": m.notes, "moved_by": m.moved_by,
			"moved_at": m.moved_at.isoformat() if m.moved_at else None,
			"created_at": m.created_at.isoformat() if m.created_at else None,
		})


# ---------------------------------------------------------------------------
# InventoryReportView — 3 canned reports
# ---------------------------------------------------------------------------

class InventoryReportView(BaseERPView):
	"""Inventory canned reports.

	GET /inv/reports/                   — Dashboard with KPI tiles + warehouse value chart
	GET /inv/reports/valuation          — Stock Valuation by warehouse
	GET /inv/reports/reorder            — Reorder Suggestions
	GET /inv/reports/movement-history   — Movement history for a product
	"""

	route_base = "/inv/reports"
	default_view = "dashboard"
	show_columns = ["total_skus", "total_value_cents", "below_reorder_count", "zero_stock_count", "slow_moving_count", "overstock_count"]
	search_columns = ["tenant_id", "warehouse_id", "product_id"]
	label_columns = {
		"total_skus": "Total SKUs",
		"total_value_cents": "Total Value (cents)",
		"below_reorder_count": "Below Reorder",
		"zero_stock_count": "Zero Stock",
		"slow_moving_count": "Slow Moving",
		"overstock_count": "Overstock",
	}

	@expose("/")
	@has_access
	def dashboard(self):
		"""Inventory dashboard — KPIs and inventory value by warehouse bar chart."""
		from pgappforge.plugins.erp.operations.inventory.models import (
			Product, StockLevel, Warehouse,
		)
		from pgappforge.plugins.erp.operations.inventory.services import InventoryService
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")

		total_skus: int = 0
		total_value_cents: int = 0
		below_reorder_count: int = 0
		zero_stock_count: int = 0
		slow_moving_count: int = 0
		overstock_count: int = 0
		warehouse_count: int = 0
		chart_rows: list[dict] = []
		abc_analysis = {
			"A": 0,
			"B": 0,
			"C": 0,
			"A_value_cents": 0,
			"total_value_cents": 0,
		}

		try:
			tenant_filter = [StockLevel.tenant_id == tenant_id] if tenant_id else []
			product_filter = [Product.tenant_id == tenant_id] if tenant_id else []
			stock_summary = (
				sa.select(
					StockLevel.product_id.label("product_id"),
					sa.func.sum(StockLevel.quantity_on_hand).label("current_qty"),
					sa.func.max(StockLevel.last_movement_date).label("last_movement_date"),
				)
				.where(*tenant_filter)
				.group_by(StockLevel.product_id)
				.subquery()
			)
			current_qty = sa.func.coalesce(stock_summary.c.current_qty, 0)
			slow_cutoff = date.today() - timedelta(days=90)

			total_skus = session.execute(
				sa.select(sa.func.count()).select_from(Product).where(
					Product.is_active.is_(True),
					*([Product.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			warehouse_count = session.execute(
				sa.select(sa.func.count()).select_from(Warehouse).where(
					Warehouse.is_active.is_(True),
					*([Warehouse.tenant_id == tenant_id] if tenant_id else []),
				)
			).scalar() or 0

			below_reorder_count = session.execute(
				sa.select(sa.func.count()).select_from(Product).outerjoin(
					stock_summary, Product.id == stock_summary.c.product_id
				).where(
					Product.is_active.is_(True),
					*product_filter,
					current_qty <= Product.reorder_point,
				)
			).scalar() or 0

			zero_stock_count = session.execute(
				sa.select(sa.func.count()).select_from(Product).outerjoin(
					stock_summary, Product.id == stock_summary.c.product_id
				).where(
					Product.is_active.is_(True),
					*product_filter,
					current_qty <= 0,
				)
			).scalar() or 0

			slow_moving_count = session.execute(
				sa.select(sa.func.count()).select_from(Product).join(
					stock_summary, Product.id == stock_summary.c.product_id
				).where(
					Product.is_active.is_(True),
					*product_filter,
					stock_summary.c.last_movement_date < slow_cutoff,
				)
			).scalar() or 0

			overstock_count = session.execute(
				sa.select(sa.func.count()).select_from(Product).outerjoin(
					stock_summary, Product.id == stock_summary.c.product_id
				).where(
					Product.is_active.is_(True),
					*product_filter,
					Product.max_stock_level > 0,
					current_qty > Product.max_stock_level,
				)
			).scalar() or 0

			wh_value_rows = session.execute(
				sa.select(
					StockLevel.warehouse_id,
					sa.func.sum(
						StockLevel.quantity_on_hand * StockLevel.average_cost_cents
					).label("value_cents"),
				)
				.where(*([StockLevel.tenant_id == tenant_id] if tenant_id else []))
				.group_by(StockLevel.warehouse_id)
				.order_by(sa.desc("value_cents"))
				.limit(20)
			).all()

			total_value_cents = sum(int(r.value_cents or 0) for r in wh_value_rows)
			chart_rows = [
				{"label": str(r.warehouse_id)[:12], "value": int(r.value_cents or 0)}
				for r in wh_value_rows
			]
			if tenant_id:
				abc_analysis = InventoryService().get_abc_analysis(tenant_id, session)
		except Exception as exc:
			log.error("Inventory dashboard query error: %s", exc, exc_info=True)

		kpi_html = self.kpi_cards([
			{"label": "Total SKUs", "value": total_skus, "format": "integer",
			 "color": "#1a56db", "icon": "fa-boxes"},
			{"label": "Total Value (cents)", "value": total_value_cents, "format": "integer",
			 "color": "#057a55", "icon": "fa-dollar-sign"},
			{"label": "Below Reorder", "value": below_reorder_count, "format": "integer",
			 "color": "#e02424", "icon": "fa-exclamation-triangle"},
			{"label": "Zero Stock", "value": zero_stock_count, "format": "integer",
			 "color": "#991b1b", "icon": "fa-ban"},
			{"label": "Slow Moving", "value": slow_moving_count, "format": "integer",
			 "color": "#d97706", "icon": "fa-hourglass-half"},
			{"label": "Overstock", "value": overstock_count, "format": "integer",
			 "color": "#7c3aed", "icon": "fa-layer-group"},
			{"label": "Warehouses", "value": warehouse_count, "format": "integer",
			 "color": "#9061f9", "icon": "fa-warehouse"},
			{"label": "ABC A Items", "value": abc_analysis["A"], "format": "integer",
			 "color": "#047857", "icon": "fa-star"},
			{"label": "ABC B Items", "value": abc_analysis["B"], "format": "integer",
			 "color": "#2563eb", "icon": "fa-chart-bar"},
			{"label": "ABC C Items", "value": abc_analysis["C"], "format": "integer",
			 "color": "#6b7280", "icon": "fa-list"},
			{"label": "ABC A Value (cents)", "value": abc_analysis["A_value_cents"], "format": "integer",
			 "color": "#065f46", "icon": "fa-dollar-sign"},
		])
		chart_html = self.chart(
			chart_rows, chart_type="bar",
			x_col="label", y_col="value",
			title="Inventory Value by Warehouse (cents)",
			height=260,
		) if chart_rows else ""

		if request.args.get("format") == "json":
			return jsonify({
				"total_skus": total_skus,
				"total_value_cents": total_value_cents,
				"below_reorder_count": below_reorder_count,
				"zero_stock_count": zero_stock_count,
				"slow_moving_count": slow_moving_count,
				"overstock_count": overstock_count,
				"warehouse_count": warehouse_count,
				"abc_analysis": abc_analysis,
			})

		body = (
			"<h3>Inventory Dashboard</h3>"
			+ str(kpi_html)
			+ str(chart_html)
			+ '<p><a href="/inv/reports/reorder" class="btn btn-default">Reorder Suggestions</a> '
			+ '<a href="/inv/reports/stock-aging" class="btn btn-default">Stock Aging</a> '
			+ '<a href="/inv/reports/valuation?warehouse_id=..." class="btn btn-default">Valuation</a></p>'
		)
		return make_response(_page_html("Inventory Dashboard", body), 200)

	@expose("/valuation")
	@has_access
	def valuation(self):
		"""Stock Valuation — total inventory value by warehouse."""
		from pgappforge.plugins.erp.operations.inventory.services import InventoryService
		session = _get_session()
		warehouse_id = request.args.get("warehouse_id")
		tenant_id = request.args.get("tenant_id", "")
		if not warehouse_id:
			return jsonify({"ok": False, "error": "warehouse_id required"}), 400

		as_of_str = request.args.get("as_of")
		as_of = None
		if as_of_str:
			from datetime import date as date_type
			as_of = date_type.fromisoformat(as_of_str)

		svc = InventoryService()
		result = svc.get_stock_valuation(warehouse_id, as_of, session, tenant_id)

		if request.args.get("format") == "json":
			return jsonify(result)

		lines = result["lines"]
		total = result["total_value_cents"]
		rows = "".join(
			f"<tr>"
			f"<td>{_he(l['sku'])}</td>"
			f"<td>{_he(l['name'])}</td>"
			f"<td class='text-right'>{_he(l['quantity_on_hand'])}</td>"
			f"<td class='text-right'>{l['average_cost_cents'] / 100:,.4f}</td>"
			f"<td class='text-right'>{l['total_value_cents'] / 100:,.2f}</td>"
			f"</tr>"
			for l in lines
		)
		body = (
			f'<h3>Stock Valuation — Warehouse {_he(warehouse_id)} — as of {_he(result["as_of_date"])}</h3>'
			f'<table class="table table-bordered table-condensed">'
			f'<thead><tr><th>SKU</th><th>Name</th><th>QOH</th><th>Avg Cost</th><th>Value</th></tr></thead>'
			f'<tbody>{rows}'
			f'<tr class="info"><td colspan="4"><strong>Total</strong></td>'
			f'<td class="text-right"><strong>{total / 100:,.2f}</strong></td></tr>'
			f'</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Stock Valuation", body), 200)

	@expose("/reorder")
	@has_access
	def reorder(self):
		"""Reorder Suggestions — products below reorder point."""
		from pgappforge.plugins.erp.operations.inventory.services import InventoryService
		session = _get_session()
		tenant_id = request.args.get("tenant_id", "")
		if not tenant_id:
			return jsonify({"ok": False, "error": "tenant_id required"}), 400

		svc = InventoryService()
		suggestions = svc.calculate_reorder_suggestions(tenant_id, session)

		if request.args.get("format") == "json":
			return jsonify({"suggestions": suggestions})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(s['sku'])}</td>"
			f"<td>{_he(s['name'])}</td>"
			f"<td>{_he(s['warehouse_id'])}</td>"
			f"<td class='text-right text-danger'>{_he(s['quantity_available'])}</td>"
			f"<td class='text-right'>{_he(s['reorder_point'])}</td>"
			f"<td class='text-right'>{_he(s['reorder_quantity'])}</td>"
			f"<td class='text-right'>{s['lead_time_days']}d</td>"
			f"<td class='text-right'>{s['estimated_cost_cents'] / 100:,.2f}</td>"
			f"</tr>"
			for s in suggestions
		)
		body = (
			'<h3>Reorder Suggestions</h3>'
			'<table class="table table-bordered table-condensed table-hover">'
			'<thead><tr><th>SKU</th><th>Name</th><th>Warehouse</th>'
			'<th>Avail</th><th>Reorder Pt</th><th>Reorder Qty</th>'
			'<th>Lead Time</th><th>Est. Cost</th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p>Total: {len(suggestions)} SKUs below reorder point</p>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Reorder Suggestions", body), 200)

	@expose("/movement-history")
	@has_access
	def movement_history(self):
		"""Movement history for a product — last 90 days by default."""
		from pgappforge.plugins.erp.operations.inventory.models import StockMovement, Product
		from datetime import timedelta, date as date_type
		session = _get_session()
		product_id = request.args.get("product_id")
		if not product_id:
			return jsonify({"ok": False, "error": "product_id required"}), 400

		days = int(request.args.get("days", 90))
		since = datetime.now(timezone.utc).date() - timedelta(days=days)

		prod = session.get(Product, product_id)
		if prod is None:
			abort(404)

		q = (
			sa.select(StockMovement)
			.where(StockMovement.product_id == product_id)
			.where(StockMovement.moved_at >= since)
			.order_by(sa.desc(StockMovement.moved_at))
		)
		if request.args.get("warehouse_id"):
			q = q.where(StockMovement.warehouse_id == request.args["warehouse_id"])

		movements = session.execute(q.limit(500)).scalars().all()

		if request.args.get("format") == "json":
			return jsonify({
				"product_id": product_id, "sku": prod.sku,
				"movements": [
					{
						"id": m.id, "movement_type": m.movement_type,
						"quantity": str(m.quantity), "direction": m.direction,
						"unit_cost_cents": m.unit_cost_cents,
						"total_cost_cents": m.total_cost_cents,
						"lot_number": m.lot_number,
						"reference_type": m.reference_type, "reference_id": m.reference_id,
						"moved_at": m.moved_at.isoformat() if m.moved_at else None,
					}
					for m in movements
				],
			})

		rows = "".join(
			f"<tr>"
			f"<td>{_he(m.moved_at.strftime('%Y-%m-%d %H:%M') if m.moved_at else '')}</td>"
			f"<td>{_he(m.movement_type)}</td>"
			f"<td class='{'text-success' if m.direction == 1 else 'text-danger'}'>"
			f"{'+ ' if m.direction == 1 else '- '}{_he(m.quantity)}</td>"
			f"<td>{_he(m.lot_number or '')}</td>"
			f"<td>{_he(m.reference_type or '')}</td>"
			f"<td>{_he(str(m.reference_id) if m.reference_id else '')}</td>"
			f"<td class='text-right'>{(m.total_cost_cents or 0) / 100:,.2f}</td>"
			f"</tr>"
			for m in movements
		)
		body = (
			f'<h3>Movement History — {_he(prod.sku)}: {_he(prod.name)} — last {days} days</h3>'
			f'<table class="table table-bordered table-condensed table-hover">'
			f'<thead><tr><th>Date</th><th>Type</th><th>Qty</th><th>Lot</th>'
			f'<th>Ref Type</th><th>Ref ID</th><th>Cost</th></tr></thead>'
			f'<tbody>{rows}</tbody></table>'
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Movement History", body), 200)


# ---------------------------------------------------------------------------
# StockAgingView
# ---------------------------------------------------------------------------

class StockAgingView(BaseERPView):
	"""Stock aging report by receipt date.

	GET /inv/reports/stock-aging/ — age_bucket | item_count | total_value_cents | pct_of_total
	"""

	route_base = "/inv/reports/stock-aging"
	default_view = "index"
	show_columns = ["age_bucket", "item_count", "total_value_cents", "pct_of_total"]
	search_columns = ["tenant_id", "warehouse_id", "product_id", "lot_number"]
	label_columns = {
		"age_bucket": "Age Bucket",
		"item_count": "Item Count",
		"total_value_cents": "Total Value (cents)",
		"pct_of_total": "% of Total",
	}

	@expose("/")
	@has_access
	def index(self):
		from pgappforge.plugins.erp.operations.inventory.models import StockLevel

		session = _get_session()
		tenant_id = request.args.get("tenant_id")
		warehouse_id = request.args.get("warehouse_id")
		product_id = request.args.get("product_id")
		today = date.today()
		buckets = [
			("0-30d", 0, 30),
			("31-60d", 31, 60),
			("61-90d", 61, 90),
			("90-180d", 91, 180),
			(">180d", 181, None),
		]
		bucket_rows = {
			name: {"age_bucket": name, "item_count": 0, "total_value_cents": 0, "pct_of_total": 0.0}
			for name, _, _ in buckets
		}

		q = (
			sa.select(StockLevel)
			.where(StockLevel.quantity_on_hand > 0)
			.where(StockLevel.receipt_date.is_not(None))
		)
		if tenant_id:
			q = q.where(StockLevel.tenant_id == tenant_id)
		if warehouse_id:
			q = q.where(StockLevel.warehouse_id == warehouse_id)
		if product_id:
			q = q.where(StockLevel.product_id == product_id)

		levels = session.execute(q.limit(5000)).scalars().all()
		for level in levels:
			age_days = (today - level.receipt_date).days
			for name, min_days, max_days in buckets:
				if age_days >= min_days and (max_days is None or age_days <= max_days):
					row = bucket_rows[name]
					row["item_count"] += 1
					row["total_value_cents"] += _qty_cost_cents(
						level.quantity_on_hand,
						level.average_cost_cents,
					)
					break

		total_value_cents = int(sum(row["total_value_cents"] for row in bucket_rows.values()))
		data = []
		for name, _, _ in buckets:
			row = bucket_rows[name]
			row["pct_of_total"] = (
				round(row["total_value_cents"] / total_value_cents * 100, 2)
				if total_value_cents else 0.0
			)
			data.append(row)

		if request.args.get("format") == "json":
			return jsonify({"stock_aging": data, "total_value_cents": total_value_cents})

		def row_class(bucket: str) -> str:
			if bucket == ">180d":
				return "danger"
			if bucket == "90-180d":
				return "warning"
			return ""

		rows = "".join(
			f"<tr class='{row_class(r['age_bucket'])}'>"
			f"<td>{_he(r['age_bucket'])}</td>"
			f"<td class='text-right'>{r['item_count']}</td>"
			f"<td class='text-right'>{r['total_value_cents']}</td>"
			f"<td class='text-right'>{r['pct_of_total']:.2f}%</td>"
			f"</tr>"
			for r in data
		)
		body = (
			"<h3>Stock Aging</h3>"
			'<table class="table table-bordered table-condensed table-hover">'
			"<thead><tr><th>Age Bucket</th><th>Item Count</th><th>Total Value (cents)</th>"
			"<th>% of Total</th></tr></thead>"
			f"<tbody>{rows}</tbody></table>"
			f'<p style="color:#888;font-size:0.75em">Generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</p>'
		)
		return make_response(_page_html("Stock Aging", body), 200)


__all__ = [
	"ProductCategoryView",
	"ProductView",
	"WarehouseView",
	"StockLevelView",
	"StockMovementView",
	"InventoryReportView",
	"StockAgingView",
]
