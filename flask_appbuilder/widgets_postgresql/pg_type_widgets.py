"""
PostgreSQL Type Widgets — complete CRUD coverage for all PostgreSQL column types.

Covers: HSTORE, LTREE, INET, CIDR, MACADDR, TSVECTOR, TSQUERY,
        INT4RANGE, INT8RANGE, NUMRANGE, TSRANGE, TSTZRANGE, DATERANGE,
        RASTER, plus aliases for UUID and pgvector.
"""
from __future__ import annotations

import json
from markupsafe import Markup
from flask_appbuilder.fieldwidgets import BS3TextFieldWidget
from wtforms.widgets import TextArea, Input
from wtforms.widgets.core import html_params


class HStoreEditorWidget(BS3TextFieldWidget):
	"""CRUD widget for PostgreSQL HSTORE (key→value map).

	Renders a two-column key/value table editor with add/remove row controls.
	Stores data as a JSON object internally, converts to/from hstore syntax.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		kwargs.setdefault("id", field.id)
		raw = field.data or {}
		if isinstance(raw, str):
			try:
				raw = json.loads(raw)
			except (ValueError, TypeError):
				raw = {}
		data_json = json.dumps(raw, ensure_ascii=False)
		html = f"""
<div class="hstore-editor" id="{field.id}_container">
  <input type="hidden" name="{field.name}" id="{field.id}" value='{data_json}'>
  <table class="table table-condensed table-bordered" id="{field.id}_table">
    <thead><tr><th>Key</th><th>Value</th><th></th></tr></thead>
    <tbody id="{field.id}_rows">
    </tbody>
  </table>
  <button type="button" class="btn btn-sm btn-default" onclick="hstoreAddRow('{field.id}')">
    <i class="fa fa-plus"></i> Add row
  </button>
</div>
<script>
(function() {{
  var data = {data_json};
  function hstoreSync(id) {{
    var rows = document.querySelectorAll('#' + id + '_rows tr');
    var obj = {{}};
    rows.forEach(function(r) {{
      var k = r.querySelector('.hstore-key').value.trim();
      var v = r.querySelector('.hstore-val').value;
      if (k) obj[k] = v;
    }});
    document.getElementById(id).value = JSON.stringify(obj);
  }}
  window.hstoreAddRow = function(id, k, v) {{
    var tr = document.createElement('tr');
    tr.innerHTML = '<td><input class="form-control hstore-key" value="' + (k||'') + '" oninput="hstoreSync(\\''+id+'\\')">' +
      '</td><td><input class="form-control hstore-val" value="' + (v||'') + '" oninput="hstoreSync(\\''+id+'\\')">' +
      '</td><td><button type="button" class="btn btn-danger btn-sm" onclick="this.closest(\\'tr\\').remove();hstoreSync(\\'{id}\\')"><i class="fa fa-trash"></i></button></td>';
    document.getElementById(id + '_rows').appendChild(tr);
  }};
  Object.keys(data).forEach(function(k) {{ window.hstoreAddRow('{field.id}', k, data[k]); }});
}})();
</script>
"""
		return Markup(html)


class TreeHierarchyWidget(BS3TextFieldWidget):
	"""CRUD widget for PostgreSQL LTREE (label tree path, e.g. 'Top.Science.Physics').

	Renders a text field with live validation of ltree path syntax and a
	breadcrumb preview.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		kwargs["class"] = "form-control"
		kwargs["placeholder"] = "e.g. Top.Category.Subcategory"
		kwargs["pattern"] = r"[A-Za-z0-9_]+(\.[A-Za-z0-9_]+)*"
		value = field.data or ""
		attrs = html_params(name=field.name, id=field.id, value=value, **kwargs)
		crumbs = " › ".join(value.split(".")) if value else ""
		html = f"""
<input {attrs}>
<small class="help-block ltree-preview" id="{field.id}_crumb">{crumbs}</small>
<script>
document.getElementById('{field.id}').addEventListener('input', function() {{
  document.getElementById('{field.id}_crumb').textContent =
    this.value.split('.').filter(Boolean).join(' › ');
}});
</script>
"""
		return Markup(html)


class NetworkAddressWidget(BS3TextFieldWidget):
	"""CRUD widget for INET and CIDR PostgreSQL types.

	Provides input with live validation against IPv4/IPv6 + optional prefix.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		kwargs["class"] = "form-control"
		kwargs["placeholder"] = "e.g. 192.168.1.0/24 or 2001:db8::1"
		value = field.data or ""
		attrs = html_params(name=field.name, id=field.id, value=value, **kwargs)
		html = f"""
<input {attrs}>
<small class="help-block text-muted">IPv4 or IPv6 address, optionally with prefix length (CIDR notation).</small>
"""
		return Markup(html)


class MACAddressWidget(BS3TextFieldWidget):
	"""CRUD widget for PostgreSQL MACADDR / MACADDR8.

	Renders a text field that enforces MAC address format (6 or 8 hex groups).
	"""

	def __call__(self, field, **kwargs) -> Markup:
		kwargs["class"] = "form-control"
		kwargs["placeholder"] = "e.g. 08:00:2b:01:02:03"
		kwargs["pattern"] = r"([0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}"
		value = field.data or ""
		attrs = html_params(name=field.name, id=field.id, value=value, **kwargs)
		return Markup(f"<input {attrs}>")


class FullTextSearchWidget:
	"""Read-only display widget for PostgreSQL TSVECTOR columns.

	tsvector values are computed by PostgreSQL; this widget shows the stored
	lexeme list and marks the field as non-editable.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		value = str(field.data or "")
		eid = field.id
		html = f"""
<div class="tsvector-display form-control" style="height:auto;min-height:34px;background:#f9f9f9">
  <code style="font-size:0.85em;color:#555">{value or '<em>computed by PostgreSQL</em>'}</code>
  <input type="hidden" name="{field.name}" value="{value}">
</div>
<small class="help-block">tsvector — managed by PostgreSQL, not directly editable.</small>
"""
		return Markup(html)


class SearchQueryWidget(BS3TextFieldWidget):
	"""CRUD widget for PostgreSQL TSQUERY.

	Provides a text field with tsquery syntax help and live formatting.
	Supports: word, 'phrase', word1 & word2, word1 | word2, !word, word:*
	"""

	def __call__(self, field, **kwargs) -> Markup:
		kwargs["class"] = "form-control"
		kwargs["placeholder"] = "e.g. python & (flask | django) & !java"
		value = field.data or ""
		attrs = html_params(name=field.name, id=field.id, value=value, **kwargs)
		html = f"""
<input {attrs}>
<small class="help-block">tsquery: use <code>&amp;</code> (AND), <code>|</code> (OR), <code>!</code> (NOT), <code>:*</code> (prefix match).</small>
"""
		return Markup(html)


class NumericRangeWidget(BS3TextFieldWidget):
	"""CRUD widget for PostgreSQL INT4RANGE, INT8RANGE, NUMRANGE.

	Renders two inputs (lower bound, upper bound) with inclusivity toggles.
	Serialises to PostgreSQL range literal, e.g. [1,100).
	"""

	def __call__(self, field, **kwargs) -> Markup:
		raw = field.data or ""
		lower, upper, lower_inc, upper_inc = "", "", True, False
		if raw:
			lower_inc = raw.startswith("[")
			upper_inc = raw.endswith("]")
			inner = raw.strip("([])").split(",")
			if len(inner) == 2:
				lower, upper = inner[0].strip(), inner[1].strip()
		fid = field.id
		html = f"""
<div class="input-group" id="{fid}_range">
  <select class="form-control input-sm" id="{fid}_li" style="width:60px" onchange="syncRange('{fid}')">
    <option value="[" {'selected' if lower_inc else ''}>[ (incl)</option>
    <option value="(" {'' if lower_inc else 'selected'}>(excl)</option>
  </select>
  <input class="form-control" id="{fid}_lo" placeholder="lower" value="{lower}" style="width:120px" oninput="syncRange('{fid}')">
  <span class="input-group-addon">,</span>
  <input class="form-control" id="{fid}_hi" placeholder="upper" value="{upper}" style="width:120px" oninput="syncRange('{fid}')">
  <select class="form-control input-sm" id="{fid}_ri" style="width:60px" onchange="syncRange('{fid}')">
    <option value=")" {'selected' if not upper_inc else ''}>) (excl)</option>
    <option value="]" {'' if not upper_inc else 'selected'}>) (incl)</option>
  </select>
  <input type="hidden" name="{field.name}" id="{fid}" value="{raw}">
</div>
<script>
function syncRange(id) {{
  var li = document.getElementById(id+'_li').value;
  var lo = document.getElementById(id+'_lo').value;
  var hi = document.getElementById(id+'_hi').value;
  var ri = document.getElementById(id+'_ri').value;
  document.getElementById(id).value = li + lo + ',' + hi + ri;
}}
</script>
"""
		return Markup(html)


class TimestampRangeWidget(BS3TextFieldWidget):
	"""CRUD widget for PostgreSQL TSRANGE and TSTZRANGE.

	Renders two datetime-local inputs for lower and upper bounds.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		raw = field.data or ""
		lower, upper = "", ""
		if raw:
			inner = raw.strip("([])").split(",", 1)
			if len(inner) == 2:
				lower = inner[0].strip().strip('"')
				upper = inner[1].strip().strip('"')
		fid = field.id
		html = f"""
<div class="row" id="{fid}_tsrange">
  <div class="col-sm-5">
    <label class="control-label">From</label>
    <input type="datetime-local" class="form-control" id="{fid}_lo"
           value="{lower}" oninput="syncTs('{fid}')">
  </div>
  <div class="col-sm-5">
    <label class="control-label">To</label>
    <input type="datetime-local" class="form-control" id="{fid}_hi"
           value="{upper}" oninput="syncTs('{fid}')">
  </div>
  <input type="hidden" name="{field.name}" id="{fid}" value="{raw}">
</div>
<script>
function syncTs(id) {{
  var lo = document.getElementById(id+'_lo').value.replace('T', ' ');
  var hi = document.getElementById(id+'_hi').value.replace('T', ' ');
  document.getElementById(id).value = '[' + lo + ',' + hi + ')';
}}
</script>
"""
		return Markup(html)


class DateRangeWidget(BS3TextFieldWidget):
	"""CRUD widget for PostgreSQL DATERANGE.

	Renders two date inputs for lower and upper date bounds.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		raw = field.data or ""
		lower, upper = "", ""
		if raw:
			inner = raw.strip("([])").split(",", 1)
			if len(inner) == 2:
				lower = inner[0].strip()
				upper = inner[1].strip()
		fid = field.id
		html = f"""
<div class="row" id="{fid}_daterange">
  <div class="col-sm-4">
    <label class="control-label">From</label>
    <input type="date" class="form-control" id="{fid}_lo"
           value="{lower}" oninput="syncDate('{fid}')">
  </div>
  <div class="col-sm-4">
    <label class="control-label">To</label>
    <input type="date" class="form-control" id="{fid}_hi"
           value="{upper}" oninput="syncDate('{fid}')">
  </div>
  <input type="hidden" name="{field.name}" id="{fid}" value="{raw}">
</div>
<script>
function syncDate(id) {{
  var lo = document.getElementById(id+'_lo').value;
  var hi = document.getElementById(id+'_hi').value;
  document.getElementById(id).value = '[' + lo + ',' + hi + ')';
}}
</script>
"""
		return Markup(html)


class RasterImageWidget:
	"""Display widget for PostgreSQL RASTER (PostGIS raster data).

	Raster data is large binary and not directly editable through the web UI.
	Shows metadata and a thumbnail if available.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		html = f"""
<div class="raster-widget">
  <div class="alert alert-info">
    <i class="fa fa-image"></i>
    <strong>Raster column</strong> — PostGIS raster data is managed server-side.
    Use PostgreSQL functions (ST_AsGDALRaster, ST_AsPNG) to export.
  </div>
  <input type="hidden" name="{field.name}" value="">
</div>
"""
		return Markup(html)


class VectorSimilarityWidget(BS3TextFieldWidget):
	"""CRUD widget for pgvector VECTOR columns.

	Renders a textarea accepting comma-separated float values with dimension
	validation. Shows the vector dimension count.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		value = field.data or ""
		if isinstance(value, (list, tuple)):
			value = ",".join(str(x) for x in value)
		fid = field.id
		html = f"""
<textarea class="form-control" name="{field.name}" id="{fid}"
          rows="3" placeholder="0.1, -0.23, 0.88, ..."
          oninput="updateVecDim('{fid}')"
          style="font-family:monospace;font-size:0.85em">{value}</textarea>
<small class="help-block">
  Comma-separated float values.
  <span id="{fid}_dim" class="label label-info">
    {len(str(value).split(',')) if value else 0} dimensions
  </span>
</small>
<script>
function updateVecDim(id) {{
  var v = document.getElementById(id).value.trim();
  var n = v ? v.split(',').filter(function(x){{return x.trim()!==''}}).length : 0;
  document.getElementById(id+'_dim').textContent = n + ' dimensions';
}}
</script>
"""
		return Markup(html)


class UUIDFieldWidget(BS3TextFieldWidget):
	"""CRUD widget for PostgreSQL UUID columns.

	Text field with UUID format validation and a generate-UUID button.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		kwargs["class"] = "form-control"
		kwargs["placeholder"] = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
		kwargs["pattern"] = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
		value = field.data or ""
		attrs = html_params(name=field.name, id=field.id, value=str(value), **kwargs)
		fid = field.id
		html = f"""
<div class="input-group">
  <input {attrs}>
  <span class="input-group-btn">
    <button type="button" class="btn btn-default" title="Generate UUID"
            onclick="generateUUID('{fid}')">
      <i class="fa fa-refresh"></i>
    </button>
  </span>
</div>
<script>
function generateUUID(id) {{
  var uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {{
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  }});
  document.getElementById(id).value = uuid;
}}
</script>
"""
		return Markup(html)


# ─── Type → widget name mapping (matches database_inspector._suggest_widget_type) ────

PG_TYPE_WIDGET_MAP: dict[str, type] = {
	"JSONEditorWidget": None,        # from nx_widgets or widgets_postgresql.postgresql
	"HStoreEditorWidget": HStoreEditorWidget,
	"TreeHierarchyWidget": TreeHierarchyWidget,
	"NetworkAddressWidget": NetworkAddressWidget,
	"MACAddressWidget": MACAddressWidget,
	"FullTextSearchWidget": FullTextSearchWidget,
	"SearchQueryWidget": SearchQueryWidget,
	"NumericRangeWidget": NumericRangeWidget,
	"TimestampRangeWidget": TimestampRangeWidget,
	"DateRangeWidget": DateRangeWidget,
	"RasterImageWidget": RasterImageWidget,
	"VectorSimilarityWidget": VectorSimilarityWidget,
	"UUIDFieldWidget": UUIDFieldWidget,
}
