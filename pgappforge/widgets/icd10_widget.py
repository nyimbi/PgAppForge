"""
ICD-10-CM smart-search widget.

Two components:
  1. ICD10SearchWidget  — form field widget (autocomplete + hierarchy browser)
  2. ICD10SearchView    — Flask blueprint endpoint powering the AJAX search

Usage in a FAB view::

    from pgappforge.widgets.icd10_widget import ICD10SearchWidget, register_icd10_blueprint

    class PatientView(ModelView):
        edit_widget = ICD10SearchWidget      # as default for icd10 columns
        ...

    # In app factory:
    register_icd10_blueprint(appbuilder)

The widget renders:
  • A text input showing "CODE — Short description" when a code is selected
  • A hidden input holding the raw code value (bound to the model field)
  • An autocomplete dropdown populated via /icd10/search?q=<term>&billable_only=1
  • A "Browse" button opening a modal with Chapter → Block → Code drill-down
  • A "Billable only" toggle (hides header/category codes not valid on claims)
"""
from __future__ import annotations

import json
import logging
from typing import Any

from flask import Blueprint, jsonify, request, render_template_string
from wtforms.widgets import html_params

log = logging.getLogger(__name__)

# ─── AJAX search blueprint ─────────────────────────────────────────────────────

_icd10_bp = Blueprint("icd10_api", __name__, url_prefix="/icd10")


@_icd10_bp.route("/search")
def icd10_search():
	"""Search ICD-10-CM codes by keyword or code prefix.

	Query params:
	    q             — search term (code prefix or keywords)
	    billable_only — if "1", exclude header codes
	    limit         — max results (default 20, max 100)
	"""
	from sqlalchemy import text as sa_text
	from flask import current_app

	q = (request.args.get("q") or "").strip()
	billable_only = request.args.get("billable_only") == "1"
	limit = min(int(request.args.get("limit", 20)), 100)

	if not q or len(q) < 2:
		return jsonify([])

	try:
		db = current_app.extensions["sqlalchemy"].db
		with db.engine.connect() as conn:
			params: dict[str, Any] = {"limit": limit}
			billable_clause = "AND is_valid_for_billing = TRUE" if billable_only else ""

			# Code-prefix match (faster, prioritised)
			if q.replace(".", "").isalnum() and len(q) <= 8:
				clean = q.replace(".", "").upper()
				params["prefix"] = clean + "%"
				params["dot_prefix"] = q.upper() + "%"
				rows = conn.execute(sa_text(f"""
					SELECT code, code_with_dots, short_description, long_description,
					       is_valid_for_billing, is_header
					FROM icd10_code
					WHERE (code ILIKE :prefix OR code_with_dots ILIKE :dot_prefix)
					  {billable_clause}
					ORDER BY is_valid_for_billing DESC, LENGTH(code), code
					LIMIT :limit
				"""), params).fetchall()
			else:
				# Full-text search
				params["query"] = " & ".join(q.split())
				rows = conn.execute(sa_text(f"""
					SELECT code, code_with_dots, short_description, long_description,
					       is_valid_for_billing, is_header
					FROM icd10_code
					WHERE search_vector @@ to_tsquery('english', :query)
					  {billable_clause}
					ORDER BY ts_rank(search_vector, to_tsquery('english', :query)) DESC,
					         is_valid_for_billing DESC
					LIMIT :limit
				"""), params).fetchall()

			results = [
				{
					"code": r.code,
					"display": r.code_with_dots,
					"short": r.short_description,
					"long": r.long_description or r.short_description,
					"billable": r.is_valid_for_billing,
					"header": r.is_header,
					"label": f"{r.code_with_dots} — {r.short_description}",
				}
				for r in rows
			]
		return jsonify(results)

	except Exception as exc:
		log.warning("ICD-10 search failed: %s", exc)
		# Table might not exist yet — return empty rather than 500
		return jsonify([])


@_icd10_bp.route("/chapters")
def icd10_chapters():
	"""Return all chapters for the hierarchy browser."""
	from sqlalchemy import text as sa_text
	from flask import current_app
	try:
		db = current_app.extensions["sqlalchemy"].db
		with db.engine.connect() as conn:
			rows = conn.execute(sa_text(
				"SELECT id, chapter_number, code_range_start, code_range_end, title "
				"FROM icd10_chapter ORDER BY chapter_number"
			)).fetchall()
		return jsonify([
			{"id": r.id, "num": r.chapter_number,
			 "start": r.code_range_start, "end": r.code_range_end,
			 "title": r.title}
			for r in rows
		])
	except Exception as exc:
		log.warning("ICD-10 chapters failed: %s", exc)
		return jsonify([])


@_icd10_bp.route("/chapter/<int:chapter_id>/codes")
def icd10_chapter_codes(chapter_id: int):
	"""Return top-level codes (3-char) for a chapter for the hierarchy browser."""
	from sqlalchemy import text as sa_text
	from flask import current_app
	billable_only = request.args.get("billable_only") == "1"
	billable_clause = "AND is_valid_for_billing = TRUE" if billable_only else ""
	try:
		db = current_app.extensions["sqlalchemy"].db
		with db.engine.connect() as conn:
			rows = conn.execute(sa_text(f"""
				SELECT code, code_with_dots, short_description, is_valid_for_billing, is_header,
				       (SELECT COUNT(*) FROM icd10_code c2
				         WHERE c2.parent_code = c1.code) AS child_count
				FROM icd10_code c1
				WHERE chapter_id = :cid
				  AND parent_code IS NULL
				  {billable_clause}
				ORDER BY code
				LIMIT 500
			"""), {"cid": chapter_id}).fetchall()
		return jsonify([
			{"code": r.code, "display": r.code_with_dots,
			 "short": r.short_description,
			 "billable": r.is_valid_for_billing, "header": r.is_header,
			 "has_children": r.child_count > 0}
			for r in rows
		])
	except Exception as exc:
		log.warning("ICD-10 chapter codes failed: %s", exc)
		return jsonify([])


@_icd10_bp.route("/children/<path:parent_code>")
def icd10_children(parent_code: str):
	"""Return direct children of a code for hierarchy drill-down."""
	from sqlalchemy import text as sa_text
	from flask import current_app
	billable_only = request.args.get("billable_only") == "1"
	billable_clause = "AND is_valid_for_billing = TRUE" if billable_only else ""
	try:
		db = current_app.extensions["sqlalchemy"].db
		with db.engine.connect() as conn:
			rows = conn.execute(sa_text(f"""
				SELECT code, code_with_dots, short_description, long_description,
				       is_valid_for_billing, is_header,
				       (SELECT COUNT(*) FROM icd10_code c2
				         WHERE c2.parent_code = c1.code) AS child_count
				FROM icd10_code c1
				WHERE parent_code = :parent
				  {billable_clause}
				ORDER BY code
				LIMIT 200
			"""), {"parent": parent_code.replace(".", "").upper()}).fetchall()
		return jsonify([
			{"code": r.code, "display": r.code_with_dots,
			 "short": r.short_description,
			 "long": r.long_description or r.short_description,
			 "billable": r.is_valid_for_billing, "header": r.is_header,
			 "has_children": r.child_count > 0}
			for r in rows
		])
	except Exception as exc:
		log.warning("ICD-10 children failed: %s", exc)
		return jsonify([])


def register_icd10_blueprint(appbuilder) -> None:
	"""Register the ICD-10 AJAX endpoints with the Flask app."""
	app = appbuilder.app
	if "icd10_api" not in app.blueprints:
		app.register_blueprint(_icd10_bp)
		log.info("Registered ICD-10 search blueprint at /icd10/")


# ─── Widget ────────────────────────────────────────────────────────────────────

# Unique ID counter to support multiple instances on the same page
_WIDGET_COUNTER = 0


class ICD10SearchWidget:
	"""WTForms widget for ICD-10-CM code selection.

	Renders a text input with:
	- Live autocomplete (debounced, 300ms) against /icd10/search
	- Billable-only toggle (excludes header/category codes)
	- Browse button opening a chapter → code drill-down modal
	- Hidden input bound to the form field (stores raw code without dots)

	Usage::

	    class DiagnosisForm(FlaskForm):
	        primary_dx = StringField("Primary Diagnosis",
	                                 widget=ICD10SearchWidget())
	        secondary_dx = StringField("Secondary Diagnosis",
	                                   widget=ICD10SearchWidget(billable_only=True))
	"""

	def __init__(self, billable_only: bool = False, placeholder: str = "Search ICD-10 code or description…"):
		self.billable_only = billable_only
		self.placeholder = placeholder

	def __call__(self, field, **kwargs) -> str:
		global _WIDGET_COUNTER
		_WIDGET_COUNTER += 1
		wid = f"icd10w_{_WIDGET_COUNTER}"

		current_code = field.data or ""
		billable_flag = "true" if self.billable_only else "false"

		html = f"""
<div class="icd10-widget" id="{wid}_container" style="position:relative;">
  <div style="display:flex;gap:6px;align-items:center;">
    <input type="hidden" name="{field.name}" id="{wid}_hidden" value="{current_code}">
    <input type="text"
           id="{wid}_display"
           class="form-control"
           placeholder="{self.placeholder}"
           autocomplete="off"
           style="flex:1;"
           value="">
    <button type="button" class="btn btn-sm btn-outline-secondary"
            onclick="icd10Browse('{wid}')" title="Browse by chapter">
      <i class="fa fa-sitemap"></i>
    </button>
    <label style="margin:0;white-space:nowrap;font-size:12px;cursor:pointer;"
           title="Show only codes valid for billing (leaf codes)">
      <input type="checkbox" id="{wid}_billable"
             {'checked' if self.billable_only else ''}
             onchange="icd10SetBillable('{wid}', this.checked)">
      Billable only
    </label>
  </div>
  <div id="{wid}_dropdown"
       style="display:none;position:absolute;z-index:9999;background:#fff;
              border:1px solid #ccc;border-radius:4px;max-height:320px;
              overflow-y:auto;width:100%;box-shadow:0 4px 12px rgba(0,0,0,.15);
              top:calc(100% + 2px);left:0;">
  </div>
  <div id="{wid}_selected"
       style="margin-top:4px;padding:4px 8px;background:#f0f7ff;border-radius:4px;
              font-size:12px;color:#2c5f8a;display:none;">
  </div>
</div>

<div id="{wid}_modal" class="modal fade" tabindex="-1" role="dialog" aria-hidden="true">
  <div class="modal-dialog modal-lg" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <h5 class="modal-title">
          <i class="fa fa-stethoscope"></i> ICD-10-CM Code Browser
        </h5>
        <button type="button" class="close" data-dismiss="modal">
          <span>&times;</span>
        </button>
      </div>
      <div class="modal-body" style="min-height:400px;">
        <nav aria-label="breadcrumb">
          <ol class="breadcrumb" id="{wid}_breadcrumb">
            <li class="breadcrumb-item active">Chapters</li>
          </ol>
        </nav>
        <div id="{wid}_browser_content">
          <div class="text-center text-muted py-4">
            <i class="fa fa-spinner fa-spin"></i> Loading chapters…
          </div>
        </div>
      </div>
      <div class="modal-footer">
        <small class="text-muted mr-auto">
          Click a code to select it. Header codes (grey) cannot be billed directly.
        </small>
        <button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
      </div>
    </div>
  </div>
</div>

<script>
(function() {{
  var wid = {_js_json(wid)};
  var billableOnly = {billable_flag};
  var debounceTimer = null;
  var breadcrumbStack = []; // {{label, url}} entries

  // ── Restore display if value already set ──────────────────────────────────
  var hv = document.getElementById(wid + '_hidden').value;
  if (hv) {{
    fetch('/icd10/search?q=' + encodeURIComponent(hv) + '&limit=1')
      .then(r => r.json())
      .then(data => {{
        if (data.length) setSelected(data[0]);
      }}).catch(() => {{}});
  }}

  // ── Autocomplete ──────────────────────────────────────────────────────────
  var inp = document.getElementById(wid + '_display');
  inp.addEventListener('input', function() {{
    clearTimeout(debounceTimer);
    var q = this.value.trim();
    if (q.length < 2) {{ closeDropdown(); return; }}
    debounceTimer = setTimeout(function() {{ doSearch(q); }}, 300);
  }});
  inp.addEventListener('blur', function() {{
    setTimeout(closeDropdown, 200);
  }});

  function doSearch(q) {{
    var url = '/icd10/search?q=' + encodeURIComponent(q) +
              '&billable_only=' + (billableOnly ? '1' : '0') + '&limit=20';
    fetch(url).then(r => r.json()).then(showDropdown).catch(() => closeDropdown());
  }}

  function showDropdown(items) {{
    var dd = document.getElementById(wid + '_dropdown');
    if (!items.length) {{ dd.style.display = 'none'; return; }}
    dd.innerHTML = items.map(function(it) {{
      var badge = it.billable
        ? '<span class="badge badge-success" style="font-size:10px;">Billable</span>'
        : '<span class="badge badge-secondary" style="font-size:10px;">Header</span>';
      return '<div class="icd10-item" data-code="' + it.code + '" ' +
             'style="padding:8px 12px;cursor:pointer;border-bottom:1px solid #f0f0f0;' +
             (it.header ? 'color:#888;' : '') + '" ' +
             'onmousedown="icd10Pick(\'' + wid + '\',' + JSON.stringify(it) + ')">' +
             '<strong style="font-family:monospace;">' + it.display + '</strong> ' +
             badge + '<br>' +
             '<small>' + it.short + '</small></div>';
    }}).join('');
    dd.style.display = 'block';
  }}

  function closeDropdown() {{
    document.getElementById(wid + '_dropdown').style.display = 'none';
  }}

  function setSelected(it) {{
    document.getElementById(wid + '_hidden').value = it.code;
    document.getElementById(wid + '_display').value = it.display + ' — ' + it.short;
    var sel = document.getElementById(wid + '_selected');
    var billTag = it.billable
      ? '<span class="badge badge-success">Billable</span>'
      : '<span class="badge badge-warning">Header — not valid for billing</span>';
    sel.innerHTML = '<strong>' + it.display + '</strong> ' + billTag +
                    '<br><span style="color:#555;">' + (it.long || it.short) + '</span>';
    sel.style.display = 'block';
    closeDropdown();
  }}

  // ── Public API (called from onclick attrs) ────────────────────────────────
  window.icd10Pick = function(w, it) {{ if (w === wid) setSelected(it); }};

  window.icd10SetBillable = function(w, val) {{
    if (w !== wid) return;
    billableOnly = val;
    var q = document.getElementById(wid + '_display').value.trim();
    if (q.length >= 2) doSearch(q);
  }};

  window.icd10Browse = function(w) {{
    if (w !== wid) return;
    breadcrumbStack = [];
    document.getElementById(wid + '_breadcrumb').innerHTML =
      '<li class="breadcrumb-item active">Chapters</li>';
    loadChapters();
    $('#' + wid + '_modal').modal('show');
  }};

  function loadChapters() {{
    var el = document.getElementById(wid + '_browser_content');
    el.innerHTML = '<div class="text-center py-3"><i class="fa fa-spinner fa-spin"></i></div>';
    fetch('/icd10/chapters').then(r => r.json()).then(function(chapters) {{
      el.innerHTML = chapters.map(function(ch) {{
        return '<div class="list-group-item list-group-item-action" style="cursor:pointer;" ' +
               'onclick="icd10DrillChapter(\'' + wid + '\',' + ch.id + ',\'' +
               ch.title.replace(/'/g, "\\'") + '\')">' +
               '<strong>Chapter ' + ch.num + '</strong>: ' + ch.start + '–' + ch.end + ' ' +
               '<span class="text-muted">— ' + ch.title + '</span>' +
               '<i class="fa fa-chevron-right float-right text-muted" style="margin-top:3px;"></i>' +
               '</div>';
      }}).join('');
    }}).catch(function() {{
      el.innerHTML = '<div class="alert alert-warning">Could not load chapters. ' +
                     'Run: flask forge templates install-data icd10 -d postgresql://...</div>';
    }});
  }}

  window.icd10DrillChapter = function(w, chapterId, title) {{
    if (w !== wid) return;
    var el = document.getElementById(wid + '_browser_content');
    el.innerHTML = '<div class="text-center py-3"><i class="fa fa-spinner fa-spin"></i></div>';
    breadcrumbStack = [{{label: title, chapterId: chapterId}}];
    updateBreadcrumb();
    fetch('/icd10/chapter/' + chapterId + '/codes?billable_only=' + (billableOnly ? '1' : '0'))
      .then(r => r.json()).then(function(codes) {{ showCodeList(codes, el); }})
      .catch(() => {{
        el.innerHTML = '<div class="alert alert-danger">Error loading codes.</div>';
      }});
  }};

  window.icd10DrillCode = function(w, code, short, hasChildren) {{
    if (w !== wid) return;
    if (!hasChildren) {{
      // leaf — select it directly
      icd10Pick(w, {{code: code.replace('.',''), display: code, short: short, long: short,
                     billable: true, header: false}});
      $('#' + wid + '_modal').modal('hide');
      return;
    }}
    var el = document.getElementById(wid + '_browser_content');
    el.innerHTML = '<div class="text-center py-3"><i class="fa fa-spinner fa-spin"></i></div>';
    breadcrumbStack.push({{label: code + ' ' + short, code: code}});
    updateBreadcrumb();
    fetch('/icd10/children/' + code + '?billable_only=' + (billableOnly ? '1' : '0'))
      .then(r => r.json()).then(function(codes) {{ showCodeList(codes, el); }})
      .catch(() => {{
        el.innerHTML = '<div class="alert alert-danger">Error loading children.</div>';
      }});
  }};

  function showCodeList(codes, el) {{
    if (!codes.length) {{
      el.innerHTML = '<div class="alert alert-info">No codes found in this section.</div>';
      return;
    }}
    el.innerHTML = codes.map(function(c) {{
      var icon = c.has_children ? 'fa-chevron-right' : 'fa-check-circle';
      var style = c.header ? 'color:#888;' : '';
      var badge = c.billable
        ? '<span class="badge badge-success" style="font-size:10px;">Billable</span>'
        : '<span class="badge badge-secondary" style="font-size:10px;">Category</span>';
      return '<div class="list-group-item list-group-item-action" style="cursor:pointer;' + style + '" ' +
             'onclick="icd10DrillCode(\'' + wid + '\',\'' + c.display + '\',' +
             JSON.stringify(c.short) + ',' + c.has_children + ')">' +
             '<i class="fa ' + icon + ' text-muted" style="margin-right:8px;"></i>' +
             '<strong style="font-family:monospace;">' + c.display + '</strong> ' +
             badge + ' — ' + c.short +
             '</div>';
    }}).join('');
  }}

  function updateBreadcrumb() {{
    var bc = document.getElementById(wid + '_breadcrumb');
    var items = ['<li class="breadcrumb-item"><a href="#" onclick="icd10BrowseBack(\'' +
                 wid + '\',-1);return false;">Chapters</a></li>'];
    breadcrumbStack.forEach(function(entry, idx) {{
      if (idx === breadcrumbStack.length - 1) {{
        items.push('<li class="breadcrumb-item active">' + entry.label + '</li>');
      }} else {{
        items.push('<li class="breadcrumb-item"><a href="#" onclick="icd10BrowseBack(\'' +
                   wid + '\',' + idx + ');return false;">' + entry.label + '</a></li>');
      }}
    }});
    bc.innerHTML = items.join('');
  }}

  window.icd10BrowseBack = function(w, idx) {{
    if (w !== wid) return;
    if (idx === -1) {{
      breadcrumbStack = [];
      document.getElementById(wid + '_breadcrumb').innerHTML =
        '<li class="breadcrumb-item active">Chapters</li>';
      loadChapters();
      return;
    }}
    var target = breadcrumbStack[idx];
    breadcrumbStack = breadcrumbStack.slice(0, idx + 1);
    updateBreadcrumb();
    var el = document.getElementById(wid + '_browser_content');
    el.innerHTML = '<div class="text-center py-3"><i class="fa fa-spinner fa-spin"></i></div>';
    if (target.chapterId) {{
      fetch('/icd10/chapter/' + target.chapterId + '/codes?billable_only=' + (billableOnly ? '1' : '0'))
        .then(r => r.json()).then(function(codes) {{ showCodeList(codes, el); }});
    }} else if (target.code) {{
      fetch('/icd10/children/' + target.code + '?billable_only=' + (billableOnly ? '1' : '0'))
        .then(r => r.json()).then(function(codes) {{ showCodeList(codes, el); }});
    }}
  }};

}})();
</script>
"""
		return html


# ─── WTForms field (convenience) ──────────────────────────────────────────────

try:
	from wtforms import StringField

	class ICD10Field(StringField):
		"""WTForms StringField that uses ICD10SearchWidget by default."""
		widget = ICD10SearchWidget()

except ImportError:
	pass  # WTForms not installed — widget still usable standalone
