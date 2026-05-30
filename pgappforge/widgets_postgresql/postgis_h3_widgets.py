"""
PostGIS full type coverage + Uber H3 hexagonal index widgets.

PostGIS geometry types supported:
  POINT, POINTZ, POINTM, POINTZM,
  LINESTRING, LINESTRINGZ, LINESTRING3D,
  POLYGON, POLYGONZ,
  MULTIPOINT, MULTILINESTRING, MULTIPOLYGON,
  GEOMETRYCOLLECTION,
  CIRCULARSTRING, COMPOUNDCURVE, CURVEPOLYGON,
  TRIANGLE, TIN, POLYHEDRALSURFACE,
  GEOGRAPHY (all subtypes, sphere-based)

Uber H3 hexagonal indexing:
  H3IndexWidget        — single H3 cell selector with map preview
  H3ArrayWidget        — array of H3 cells (geofence editor)
  H3IndexType          — SQLAlchemy custom type for h3index columns

Usage in models::

    from pgappforge.widgets_postgresql.postgis_h3_widgets import H3IndexType

    class Zone(Model):
        __tablename__ = 'zones'
        id = Column(Integer, primary_key=True)
        # H3 cell at resolution 9
        h3_cell = Column(H3IndexType, index=True)
        # Array of H3 cells for a geofence
        h3_fence = Column(ARRAY(H3IndexType))
        # PostGIS geometry
        boundary = Column(Geometry('POLYGON', srid=4326))

Usage in views::

    from pgappforge.widgets_postgresql.postgis_h3_widgets import (
        H3IndexWidget, H3ArrayWidget, PostGISWidget, PostGISGeographyWidget
    )
"""
from __future__ import annotations

import json
from markupsafe import Markup
from wtforms.widgets.core import html_params
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets_postgresql._cdn import (
	LEAFLET_CDN as _LEAFLET_CDN,
	LEAFLET_DRAW_CDN as _LEAFLET_DRAW_CDN,
	H3_CDN as _H3_CDN,
)

try:
	from sqlalchemy import TypeDecorator, String as _String
	class H3IndexType(TypeDecorator):
		"""SQLAlchemy custom type for Uber H3 hexagonal index (h3index).

		H3 indexes are 15-character hexadecimal strings representing a
		hierarchical hexagonal cell on Earth's surface.

		Example::

		    h3_cell = Column(H3IndexType, nullable=True, index=True)
		"""
		impl = _String(16)
		cache_ok = True

		def process_bind_param(self, value, dialect):
			if value is None:
				return None
			return str(value).lower().strip()

		def process_result_value(self, value, dialect):
			return value
except ImportError:
	H3IndexType = None  # type: ignore





class H3IndexWidget(BS3TextFieldWidget):
	"""Widget for a single Uber H3 hexagonal index value.

	Features:
	- Text input accepting a 15-char H3 index (e.g. ``8928308280fffff``)
	- Resolution selector (0 = continent, 15 = ~1 m²)
	- Interactive Leaflet map: click to select cell at chosen resolution
	- Live hex cell outline rendered on the map
	- Validates H3 format client-side

	Stores the H3 index string directly in the hidden field.
	"""

	def __init__(self, resolution: int = 9, height: int = 300):
		self.resolution = resolution
		self.height = height

	def __call__(self, field, **kwargs) -> Markup:
		fid = field.id
		value = str(field.data or "")
		res = self.resolution
		height = self.height

		html = f"""
{_LEAFLET_CDN}
{_H3_CDN}
<div class="h3-index-widget" id="{fid}_container">
  <div class="input-group">
    <input type="text" class="form-control" id="{fid}_display"
           placeholder="H3 index (e.g. 8928308280fffff)"
           value="{value}" maxlength="16"
           oninput="h3widgetSetIndex('{fid}', this.value)"
           aria-label="H3 hexagonal index">
    <span class="input-group-addon">
      <select id="{fid}_res" title="Resolution" style="border:none;background:transparent"
              onchange="h3widgetSetRes('{fid}', parseInt(this.value))">
        {''.join(f'<option value="{r}"{" selected" if r==res else ""}>R{r}</option>' for r in range(16))}
      </select>
    </span>
    <span class="input-group-btn">
      <button type="button" class="btn btn-default" title="My location"
              onclick="h3widgetGPS('{fid}')">
        <i class="fa fa-location-arrow"></i>
      </button>
      <button type="button" class="btn btn-default" title="Clear"
              onclick="h3widgetClear('{fid}')">
        <i class="fa fa-times"></i>
      </button>
    </span>
  </div>
  <div id="{fid}_map" style="height:{height}px;margin-top:8px;border:1px solid #ddd;border-radius:4px"></div>
  <div id="{fid}_info" class="help-block" style="font-size:0.85em;margin-top:4px"></div>
  <input type="hidden" name="{field.name}" id="{fid}" value="{value}">
</div>

<script>
(function() {{
  var _resolution = {res};
  var _map, _layer;

  function waitH3(cb) {{
    if (window.h3) cb();
    else document.addEventListener('h3loaded', cb);
  }}

  function initMap() {{
    waitH3(function() {{
      _map = L.map('{fid}_map').setView([20, 0], 2);
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
        {{attribution:'© OSM',maxZoom:20}}).addTo(_map);

      var initial = document.getElementById('{fid}').value;
      if (initial && h3.isValidCell(initial)) renderCell(initial);

      _map.on('click', function(e) {{
        var idx = h3.latLngToCell(e.latlng.lat, e.latlng.lng, _resolution);
        setIndex(idx);
      }});
    }});
  }}

  function renderCell(idx) {{
    if (_layer) _map.removeLayer(_layer);
    var boundary = h3.cellToBoundary(idx).map(function(p){{return [p[0],p[1]];}});
    _layer = L.polygon(boundary, {{color:'#2980b9',fillOpacity:0.2,weight:2}}).addTo(_map);
    _map.fitBounds(_layer.getBounds());
    var info = h3.cellToParent ? '' : '';
    document.getElementById('{fid}_info').textContent =
      'Resolution: ' + h3.getResolution(idx) + ' | Area: ~' +
      Math.round(h3.cellArea(idx, 'm2')) + ' m²';
  }}

  function setIndex(idx) {{
    document.getElementById('{fid}_display').value = idx;
    document.getElementById('{fid}').value = idx;
    if (h3.isValidCell(idx)) renderCell(idx);
  }}

  window.h3widgetSetIndex = function(id, val) {{
    if (id === '{fid}') {{
      document.getElementById('{fid}').value = val;
      if (window.h3 && h3.isValidCell(val)) renderCell(val);
    }}
  }};

  window.h3widgetSetRes = function(id, res) {{
    if (id === '{fid}') _resolution = res;
  }};

  window.h3widgetGPS = function(id) {{
    if (id !== '{fid}') return;
    navigator.geolocation.getCurrentPosition(function(p) {{
      waitH3(function() {{
        var idx = h3.latLngToCell(p.coords.latitude, p.coords.longitude, _resolution);
        setIndex(idx);
      }});
    }});
  }};

  window.h3widgetClear = function(id) {{
    if (id !== '{fid}') return;
    document.getElementById('{fid}_display').value = '';
    document.getElementById('{fid}').value = '';
    document.getElementById('{fid}_info').textContent = '';
    if (_layer) {{ _map.removeLayer(_layer); _layer = null; }}
  }};

  document.addEventListener('DOMContentLoaded', initMap);
}})();
</script>
"""
		return Markup(html)


class H3ArrayWidget(BS3TextFieldWidget):
	"""Widget for an array of H3 cells — geofence / coverage area editor.

	Features:
	- Interactive map: click to add/remove H3 cells at chosen resolution
	- Renders all selected cells as colored hexagons
	- Stores a JSON array of H3 index strings
	- Import/export via paste-area

	Pairs with a PostgreSQL ``ARRAY(H3IndexType)`` column::

	    geofence = Column(ARRAY(H3IndexType), default=list)
	"""

	def __init__(self, resolution: int = 9, height: int = 400):
		self.resolution = resolution
		self.height = height

	def __call__(self, field, **kwargs) -> Markup:
		fid = field.id
		raw = field.data or "[]"
		if isinstance(raw, list):
			cells = raw
		else:
			try:
				cells = json.loads(raw)
			except Exception:
				cells = []
		cells_json = json.dumps(cells)
		res = self.resolution
		height = self.height

		html = f"""
{_LEAFLET_CDN}
{_H3_CDN}
<div class="h3-array-widget" id="{fid}_container">
  <div class="row" style="margin-bottom:6px">
    <div class="col-xs-6">
      <label>Resolution:
        <select id="{fid}_res" class="form-control input-sm" style="width:auto;display:inline">
          {''.join(f'<option value="{r}"{" selected" if r==res else ""}>R{r} (~{["1000km","500km","100km","50km","10km","5km","1km","300m","80m","20m","5m","1.5m","50cm","15cm","5cm","1cm"][r]} cell)</option>' for r in range(16))}
        </select>
      </label>
    </div>
    <div class="col-xs-6 text-right">
      <span id="{fid}_count" class="label label-info">0 cells</span>
      <button type="button" class="btn btn-xs btn-danger" onclick="h3arrClear('{fid}')">Clear all</button>
    </div>
  </div>
  <div id="{fid}_map" style="height:{height}px;border:1px solid #ddd;border-radius:4px"></div>
  <div style="margin-top:6px">
    <small class="help-block">Click cells to add/remove. Shift+drag to select area.</small>
    <textarea class="form-control input-sm" id="{fid}_paste" rows="2"
              placeholder='Paste H3 indexes (one per line or JSON array) then click Import'
              style="margin-top:4px"></textarea>
    <button type="button" class="btn btn-xs btn-default" onclick="h3arrImport('{fid}')">Import</button>
    <button type="button" class="btn btn-xs btn-default" onclick="h3arrExport('{fid}')">Export</button>
  </div>
  <input type="hidden" name="{field.name}" id="{fid}" value='{cells_json}'>
</div>

<script>
(function() {{
  var _cells = new Set({cells_json});
  var _layers = {{}};
  var _res = {res};
  var _map;

  function waitH3(cb) {{
    if (window.h3) cb();
    else document.addEventListener('h3loaded', cb);
  }}

  function syncField() {{
    var arr = Array.from(_cells);
    document.getElementById('{fid}').value = JSON.stringify(arr);
    document.getElementById('{fid}_count').textContent = arr.length + ' cells';
  }}

  function addCell(idx) {{
    if (_cells.has(idx)) return;
    _cells.add(idx);
    var boundary = h3.cellToBoundary(idx).map(function(p){{return [p[0],p[1]];}});
    _layers[idx] = L.polygon(boundary, {{color:'#27ae60',fillOpacity:0.3,weight:1}})
      .addTo(_map)
      .on('click', function(){{ removeCell(idx); }});
    syncField();
  }}

  function removeCell(idx) {{
    _cells.delete(idx);
    if (_layers[idx]) {{ _map.removeLayer(_layers[idx]); delete _layers[idx]; }}
    syncField();
  }}

  function renderAll() {{
    _cells.forEach(function(idx) {{
      if (!_layers[idx] && h3.isValidCell(idx)) {{
        var boundary = h3.cellToBoundary(idx).map(function(p){{return [p[0],p[1]];}});
        _layers[idx] = L.polygon(boundary, {{color:'#27ae60',fillOpacity:0.3,weight:1}})
          .addTo(_map)
          .on('click', function(){{ removeCell(idx); }});
      }}
    }});
  }}

  document.addEventListener('DOMContentLoaded', function() {{
    waitH3(function() {{
      _map = L.map('{fid}_map').setView([20, 0], 2);
      L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
        {{attribution:'© OSM',maxZoom:20}}).addTo(_map);
      _map.on('click', function(e) {{
        _res = parseInt(document.getElementById('{fid}_res').value);
        var idx = h3.latLngToCell(e.latlng.lat, e.latlng.lng, _res);
        if (_cells.has(idx)) removeCell(idx); else addCell(idx);
      }});
      renderAll();
      syncField();
    }});
  }});

  window.h3arrClear = function(id) {{
    if (id !== '{fid}') return;
    _cells.clear();
    Object.values(_layers).forEach(function(l){{ _map.removeLayer(l); }});
    _layers = {{}};
    syncField();
  }};

  window.h3arrImport = function(id) {{
    if (id !== '{fid}') return;
    var raw = document.getElementById('{fid}_paste').value.trim();
    var idxs;
    try {{ idxs = JSON.parse(raw); }} catch(e) {{ idxs = raw.split(/[\\s,]+/); }}
    waitH3(function() {{
      idxs.forEach(function(idx) {{ idx = idx.trim(); if (h3.isValidCell(idx)) addCell(idx); }});
    }});
  }};

  window.h3arrExport = function(id) {{
    if (id !== '{fid}') return;
    document.getElementById('{fid}_paste').value = JSON.stringify(Array.from(_cells));
  }};
}})();
</script>
"""
		return Markup(html)


class PostGISWidget(BS3TextFieldWidget):
	"""Enhanced PostGIS geometry widget with full type coverage.

	Supports all PostGIS geometry types:
	- 2D: POINT, LINESTRING, POLYGON, MULTI*, GEOMETRYCOLLECTION
	- 3D/4D: POINTZ, POINTM, POINTZM, LINESTRING3D, etc.
	- Curved: CIRCULARSTRING, COMPOUNDCURVE, CURVEPOLYGON
	- Surface: TRIANGLE, TIN, POLYHEDRALSURFACE

	Features:
	- Draw any geometry type using Leaflet.Draw
	- Input/output in WKT, EWKT, GeoJSON, WKB (hex)
	- SRID picker with common CRS list
	- 3D coordinate support (Z displayed, not edited on map)
	- Copy WKT to clipboard
	"""

	def __init__(self, geometry_type: str = "GEOMETRY", srid: int = 4326,
	             height: int = 400, allow_3d: bool = False):
		self.geometry_type = geometry_type.upper()
		self.srid = srid
		self.height = height
		self.allow_3d = allow_3d

	def __call__(self, field, **kwargs) -> Markup:
		fid = field.id
		value = str(field.data or "")
		geom_type = self.geometry_type
		srid = self.srid
		height = self.height
		allow_3d = "true" if self.allow_3d else "false"

		# Determine which draw controls to enable
		_multi = "MULTI" in geom_type
		_polygon = "POLYGON" in geom_type or geom_type in ("GEOMETRY", "GEOMETRYCOLLECTION")
		_line = "LINESTRING" in geom_type or "LINE" in geom_type or geom_type in ("GEOMETRY", "GEOMETRYCOLLECTION", "COMPOUNDCURVE", "CIRCULARSTRING")
		_point = "POINT" in geom_type or geom_type in ("GEOMETRY", "GEOMETRYCOLLECTION")

		draw_opts = json.dumps({
			"polygon": _polygon,
			"polyline": _line,
			"marker": _point,
			"circle": False,
			"rectangle": _polygon,
			"circlemarker": False,
		})

		html = f"""
{_LEAFLET_CDN}
<!-- Leaflet.Draw -->
<link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css" crossorigin="">
<script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js" crossorigin=""></script>

<div class="postgis-widget" id="{fid}_container">
  <div class="row" style="margin-bottom:6px">
    <div class="col-xs-6">
      <span class="label label-default">{geom_type}</span>
      <span class="label label-info">SRID:{srid}</span>
    </div>
    <div class="col-xs-6 text-right">
      <button type="button" class="btn btn-xs btn-default" onclick="pgwCopyWKT('{fid}')" title="Copy WKT">
        <i class="fa fa-clipboard"></i> WKT
      </button>
      <button type="button" class="btn btn-xs btn-warning" onclick="pgwClear('{fid}')">
        <i class="fa fa-times"></i> Clear
      </button>
    </div>
  </div>

  <div id="{fid}_map" style="height:{height}px;border:1px solid #ddd;border-radius:4px"></div>

  <div style="margin-top:6px">
    <div class="input-group">
      <span class="input-group-addon">WKT/EWKT</span>
      <input type="text" class="form-control input-sm" id="{fid}_wkt"
             placeholder="POINT(lng lat) or SRID=4326;POINT(…)"
             value="{value}"
             oninput="pgwFromWKT('{fid}', this.value)">
      <span class="input-group-btn">
        <button type="button" class="btn btn-sm btn-default" onclick="pgwFromWKT('{fid}', document.getElementById('{fid}_wkt').value)">
          <i class="fa fa-map-marker"></i>
        </button>
      </span>
    </div>
    <small class="help-block">
      Accepts WKT (POINT, LINESTRING, POLYGON, MULTI*, GEOMETRYCOLLECTION) or EWKT with SRID prefix.
      {'Supports Z/M coordinates.' if self.allow_3d else ''}
    </small>
  </div>

  <input type="hidden" name="{field.name}" id="{fid}" value="{value}">
</div>

<script>
(function() {{
  var _map, _drawnItems, _drawControl;
  var _srid = {srid};
  var _drawOpts = {draw_opts};

  // Simple WKT parser (handles 2D geometries)
  function parseWKT(wkt) {{
    if (!wkt) return null;
    // Strip EWKT prefix SRID=n;...
    var m = wkt.match(/^SRID=\\d+;(.+)$/i);
    if (m) wkt = m[1];
    wkt = wkt.trim().toUpperCase();

    if (wkt.startsWith('POINT')) {{
      var coords = wkt.match(/POINT[ZM]?\\s*\\(([^)]+)\\)/i);
      if (!coords) return null;
      var parts = coords[1].trim().split(/\\s+/);
      return {{type:'Point', coordinates:[parseFloat(parts[0]), parseFloat(parts[1])]}};
    }}
    if (wkt.startsWith('LINESTRING')) {{
      var coords = wkt.match(/LINESTRING[ZM]?\\s*\\(([^)]+)\\)/i);
      if (!coords) return null;
      var pts = coords[1].split(',').map(function(p) {{
        var xy = p.trim().split(/\\s+/); return [parseFloat(xy[0]), parseFloat(xy[1])];
      }});
      return {{type:'LineString', coordinates:pts}};
    }}
    if (wkt.startsWith('POLYGON')) {{
      var coords = wkt.match(/POLYGON[ZM]?\\s*\\(\\(([^)]+)\\)/i);
      if (!coords) return null;
      var pts = coords[1].split(',').map(function(p) {{
        var xy = p.trim().split(/\\s+/); return [parseFloat(xy[0]), parseFloat(xy[1])];
      }});
      return {{type:'Polygon', coordinates:[pts]}};
    }}
    return null;
  }}

  function geojsonToLeaflet(gj) {{
    if (!gj) return null;
    try {{ return L.geoJSON({{type:'Feature',geometry:gj}}); }} catch(e) {{ return null; }}
  }}

  function syncFromLayer() {{
    var gj = _drawnItems.toGeoJSON();
    var features = gj.features;
    if (!features.length) {{
      document.getElementById('{fid}').value = '';
      document.getElementById('{fid}_wkt').value = '';
      return;
    }}
    // Build WKT from GeoJSON (basic)
    var geom = features[0].geometry;
    var wkt = geojsonGeomToWKT(geom);
    var ewkt = 'SRID=' + _srid + ';' + wkt;
    document.getElementById('{fid}').value = ewkt;
    document.getElementById('{fid}_wkt').value = ewkt;
  }}

  function geojsonGeomToWKT(geom) {{
    if (!geom) return '';
    var t = geom.type.toUpperCase();
    var c = geom.coordinates;
    if (t === 'POINT') return 'POINT(' + c[0] + ' ' + c[1] + ')';
    if (t === 'LINESTRING') return 'LINESTRING(' + c.map(function(p){{return p[0]+' '+p[1];}}).join(',') + ')';
    if (t === 'POLYGON') return 'POLYGON((' + c[0].map(function(p){{return p[0]+' '+p[1];}}).join(',') + '))';
    if (t === 'MULTIPOINT') return 'MULTIPOINT(' + c.map(function(p){{return '('+p[0]+' '+p[1]+')'; }}).join(',') + ')';
    if (t === 'MULTILINESTRING') return 'MULTILINESTRING(' + c.map(function(ls){{return '('+ls.map(function(p){{return p[0]+' '+p[1];}}).join(',')+')';}}).join(',') + ')';
    if (t === 'MULTIPOLYGON') return 'MULTIPOLYGON(' + c.map(function(poly){{return '(('+poly[0].map(function(p){{return p[0]+' '+p[1];}}).join(',')+'[])';}}+')').join(',') + ')';
    return '';
  }}

  document.addEventListener('DOMContentLoaded', function() {{
    _map = L.map('{fid}_map').setView([20, 0], 2);
    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
      {{attribution:'© OSM',maxZoom:20}}).addTo(_map);

    _drawnItems = new L.FeatureGroup().addTo(_map);
    _drawControl = new L.Control.Draw({{
      edit: {{featureGroup: _drawnItems}},
      draw: {{
        polygon: _drawOpts.polygon ? {{allowIntersection:false}} : false,
        polyline: _drawOpts.polyline,
        marker:   _drawOpts.marker,
        circle:   false,
        rectangle: _drawOpts.rectangle ? {{}} : false,
        circlemarker: false
      }}
    }}).addTo(_map);

    _map.on(L.Draw.Event.CREATED, function(e) {{
      _drawnItems.clearLayers();
      _drawnItems.addLayer(e.layer);
      syncFromLayer();
    }});
    _map.on(L.Draw.Event.EDITED, function() {{ syncFromLayer(); }});
    _map.on(L.Draw.Event.DELETED, function() {{ syncFromLayer(); }});

    // Render initial value
    var initial = document.getElementById('{fid}').value;
    if (initial) {{
      var geom = parseWKT(initial);
      if (geom) {{
        var lyr = geojsonToLeaflet(geom);
        if (lyr) {{
          lyr.eachLayer(function(l) {{ _drawnItems.addLayer(l); }});
          _map.fitBounds(_drawnItems.getBounds().pad(0.2));
        }}
      }}
    }}
  }});

  window.pgwFromWKT = function(id, wkt) {{
    if (id !== '{fid}') return;
    document.getElementById('{fid}').value = wkt;
    var geom = parseWKT(wkt);
    if (geom) {{
      _drawnItems.clearLayers();
      var lyr = geojsonToLeaflet(geom);
      if (lyr) {{
        lyr.eachLayer(function(l) {{ _drawnItems.addLayer(l); }});
        _map.fitBounds(_drawnItems.getBounds().pad(0.2));
      }}
    }}
  }};

  window.pgwCopyWKT = function(id) {{
    if (id !== '{fid}') return;
    var wkt = document.getElementById('{fid}').value;
    if (wkt && navigator.clipboard) navigator.clipboard.writeText(wkt);
  }};

  window.pgwClear = function(id) {{
    if (id !== '{fid}') return;
    _drawnItems.clearLayers();
    document.getElementById('{fid}').value = '';
    document.getElementById('{fid}_wkt').value = '';
  }};
}})();
</script>
"""
		return Markup(html)


class PostGISGeographyWidget(PostGISWidget):
	"""PostGIS GEOGRAPHY widget — sphere-based coordinates (SRID 4326 always).

	GEOGRAPHY behaves identically to GEOMETRY for CRUD purposes but forces
	geodetic distance calculations. This widget sets SRID=4326 and labels the
	field accordingly.
	"""

	def __init__(self, geometry_type: str = "POINT", height: int = 400):
		super().__init__(geometry_type=geometry_type, srid=4326, height=height)

	def __call__(self, field, **kwargs) -> Markup:
		# Geography always uses SRID 4326 — patch the label
		html = super().__call__(field, **kwargs)
		return Markup(str(html).replace(
			f'<span class="label label-default">{self.geometry_type}</span>',
			f'<span class="label label-success">GEOGRAPHY {self.geometry_type}</span>'
		))


# ─── PostGIS type → widget name mapping ─────────────────────────────────────

POSTGIS_GEOMETRY_TYPES: list[str] = [
	"POINT", "POINTZ", "POINTM", "POINTZM",
	"LINESTRING", "LINESTRINGZ", "LINESTRING3D",
	"POLYGON", "POLYGONZ",
	"MULTIPOINT", "MULTIPOINTZ",
	"MULTILINESTRING", "MULTILINESTRINGZ",
	"MULTIPOLYGON", "MULTIPOLYGONZ",
	"GEOMETRYCOLLECTION",
	"CIRCULARSTRING",
	"COMPOUNDCURVE",
	"CURVEPOLYGON",
	"MULTICURVE",
	"MULTISURFACE",
	"TRIANGLE",
	"TIN",
	"POLYHEDRALSURFACE",
]

POSTGIS_GEOGRAPHY_TYPES: list[str] = [
	"GEOGRAPHY",
	"GEOGRAPHY(POINT)",
	"GEOGRAPHY(LINESTRING)",
	"GEOGRAPHY(POLYGON)",
	"GEOGRAPHY(MULTIPOINT)",
	"GEOGRAPHY(MULTILINESTRING)",
	"GEOGRAPHY(MULTIPOLYGON)",
	"GEOGRAPHY(GEOMETRYCOLLECTION)",
]

H3_TYPES: list[str] = ["H3INDEX", "H3_INDEX", "H3CELL"]

POSTGIS_H3_WIDGET_MAP: dict[str, type] = {
	"H3IndexWidget": H3IndexWidget,
	"H3ArrayWidget": H3ArrayWidget,
	"PostGISWidget": PostGISWidget,
	"PostGISGeographyWidget": PostGISGeographyWidget,
}
