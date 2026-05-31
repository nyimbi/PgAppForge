"""
SNOMED CT smart-search widget.

Two components:
  1. SNOMEDSearchWidget  — form field widget (search-first, domain filter, concept detail)
  2. snomed_bp           — Flask blueprint powering AJAX endpoints

Usage::

    from pgappforge.widgets.snomed_widget import SNOMEDSearchWidget, register_snomed_blueprint

    class ProblemListForm(FlaskForm):
        # Any clinical finding
        problem = StringField("Problem", widget=SNOMEDSearchWidget())
        # Restricted to procedures only
        procedure = StringField("Procedure",
                                widget=SNOMEDSearchWidget(domain="procedure"))

    # In app factory:
    register_snomed_blueprint(appbuilder)

SNOMED differs from ICD-10 in three ways that shape this widget:
  1. Poly-hierarchy (multiple parents) — no chapter browser; search is primary
  2. Semantic tags embedded in the FSN: "Pneumonia (disorder)", "Excision (procedure)"
  3. 350k+ concepts — domain filtering (clinical finding, procedure, substance…)
     via subsumption using the snomed_transitive_closure table

Top-level domain SCTIDs (stable across releases):
  138875005 SNOMED CT concept (root)
  404684003 Clinical finding
  71388002  Procedure
  123037004 Body structure
  105590001 Substance
  373873005 Pharmaceutical / biologic product
  308916002 Environment or geographical location
  48176007  Social context
  243796009 Situation with explicit context
  272379006 Event
  900000000000441003 SNOMED CT Model Component (metadata)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from flask import Blueprint, jsonify, request

log = logging.getLogger(__name__)

# ─── Top-level SNOMED domains for the filter dropdown ─────────────────────────

SNOMED_DOMAINS: list[dict] = [
	{"id": None,            "label": "All concepts"},
	{"id": 404684003,       "label": "Clinical finding"},
	{"id": 71388002,        "label": "Procedure"},
	{"id": 123037004,       "label": "Body structure"},
	{"id": 105590001,       "label": "Substance"},
	{"id": 373873005,       "label": "Pharmaceutical product"},
	{"id": 362981000,       "label": "Qualifier value"},
	{"id": 48176007,        "label": "Social context"},
	{"id": 272379006,       "label": "Event"},
	{"id": 243796009,       "label": "Situation with explicit context"},
]

_SEMANTIC_TAG_RE = re.compile(r'\(([^)]+)\)$')


def _extract_semantic_tag(fsn: str) -> str:
	"""Extract the semantic tag from a Fully Specified Name, e.g. '(disorder)'."""
	m = _SEMANTIC_TAG_RE.search(fsn or "")
	return m.group(1) if m else ""


# ─── Blueprint ────────────────────────────────────────────────────────────────

snomed_bp = Blueprint("snomed_api", __name__, url_prefix="/snomed")


@snomed_bp.route("/search")
def snomed_search():
	"""Search SNOMED CT concepts by clinical term.

	Query params:
	    q           — search term (minimum 2 chars)
	    domain_id   — restrict to descendants of this top-concept SCTID (optional)
	    active_only — if "1" (default), exclude retired concepts
	    limit       — max results (default 20, max 100)
	"""
	from sqlalchemy import text as sa_text
	from flask import current_app

	q = (request.args.get("q") or "").strip()
	domain_id = request.args.get("domain_id")
	active_only = request.args.get("active_only", "1") != "0"
	limit = min(int(request.args.get("limit", 20)), 100)

	if not q or len(q) < 2:
		return jsonify([])

	try:
		db = current_app.extensions["sqlalchemy"].db
		with db.engine.connect() as conn:
			params: dict[str, Any] = {"limit": limit}
			active_clause = "AND d.active = TRUE AND c.active = TRUE" if active_only else ""
			domain_clause = ""
			if domain_id:
				params["domain_id"] = int(domain_id)
				domain_clause = """
					AND c.id IN (
						SELECT sub_type_id FROM snomed_transitive_closure
						WHERE super_type_id = :domain_id
					)
				"""

			params["query"] = " & ".join(q.split())
			rows = conn.execute(sa_text(f"""
				SELECT
					c.id AS concept_id,
					d.term AS matched_term,
					d.type_id,
					fsn.term AS fsn
				FROM snomed_description d
				JOIN snomed_concept c ON c.id = d.concept_id
				LEFT JOIN snomed_description fsn
					ON fsn.concept_id = c.id
					AND fsn.type_id = 900000000000003001
					AND fsn.active = TRUE
				WHERE d.search_vector @@ to_tsquery('english', :query)
				  {active_clause}
				  {domain_clause}
				ORDER BY
					ts_rank(d.search_vector, to_tsquery('english', :query)) DESC,
					d.type_id  -- FSNs (003001) before synonyms (013009)
				LIMIT :limit
			"""), params).fetchall()

			# De-duplicate by concept_id, preferring FSN match over synonym
			seen: set[int] = set()
			results = []
			for r in rows:
				if r.concept_id in seen:
					continue
				seen.add(r.concept_id)
				fsn = r.fsn or r.matched_term
				tag = _extract_semantic_tag(fsn)
				preferred = fsn[:fsn.rfind(" (")].strip() if " (" in fsn else fsn
				results.append({
					"id": r.concept_id,
					"fsn": fsn,
					"preferred": preferred,
					"tag": tag,
					"matched_term": r.matched_term,
					"label": f"{preferred} ({tag})" if tag else preferred,
					"sctid_label": f"{r.concept_id} | {preferred} |",
				})

		return jsonify(results)

	except Exception as exc:
		log.warning("SNOMED search failed: %s", exc)
		return jsonify([])


@snomed_bp.route("/concept/<int:concept_id>")
def snomed_concept(concept_id: int):
	"""Return full concept detail: FSN, synonyms, Is-a parents, semantic tag."""
	from sqlalchemy import text as sa_text
	from flask import current_app
	try:
		db = current_app.extensions["sqlalchemy"].db
		with db.engine.connect() as conn:
			# FSN + all active descriptions
			descs = conn.execute(sa_text("""
				SELECT term, type_id, language_code
				FROM snomed_description
				WHERE concept_id = :cid AND active = TRUE
				ORDER BY type_id, language_code
			"""), {"cid": concept_id}).fetchall()

			# Direct Is-a parents (one hop)
			parents = conn.execute(sa_text("""
				SELECT c.id, d.term
				FROM snomed_relationship r
				JOIN snomed_concept c ON c.id = r.destination_id
				LEFT JOIN snomed_description d
					ON d.concept_id = c.id
					AND d.type_id = 900000000000003001
					AND d.active = TRUE
				WHERE r.source_id = :cid
				  AND r.type_id = 116680003  -- Is a
				  AND r.active = TRUE
				LIMIT 10
			"""), {"cid": concept_id}).fetchall()

		fsn = next((d.term for d in descs if d.type_id == 900000000000003001), None)
		synonyms = [d.term for d in descs if d.type_id == 900000000000013009]
		tag = _extract_semantic_tag(fsn or "")
		preferred = (fsn[:fsn.rfind(" (")].strip() if fsn and " (" in fsn else fsn) or ""

		return jsonify({
			"id": concept_id,
			"fsn": fsn,
			"preferred": preferred,
			"tag": tag,
			"synonyms": synonyms,
			"parents": [{"id": p.id, "fsn": p.term} for p in parents],
		})

	except Exception as exc:
		log.warning("SNOMED concept detail failed: %s", exc)
		return jsonify({})


def register_snomed_blueprint(appbuilder) -> None:
	"""Register SNOMED AJAX endpoints with the Flask app."""
	app = appbuilder.app
	if "snomed_api" not in app.blueprints:
		app.register_blueprint(snomed_bp)
		log.info("Registered SNOMED CT search blueprint at /snomed/")


# ─── Widget ───────────────────────────────────────────────────────────────────

_SNOMED_COUNTER = 0


class SNOMEDSearchWidget:
	"""WTForms widget for SNOMED CT concept selection.

	Renders a search-first interface (no chapter browser — SNOMED's poly-hierarchy
	makes tree navigation impractical). Features:

	- Debounced FTS against snomed_description via /snomed/search
	- Semantic tag badges: (disorder), (procedure), (finding), etc.
	- Domain filter dropdown to restrict scope
	- Concept detail panel on selection: FSN, preferred term, Is-a parents
	- Stores SCTID (integer) in the hidden input bound to the model field

	Args:
	    domain: Optional top-concept SCTID string or domain key to pre-select
	            in the filter. E.g. "404684003" for Clinical finding,
	            "71388002" for Procedure.
	    active_only: If True (default), exclude retired SNOMED concepts.
	    placeholder: Input placeholder text.
	"""

	# Semantic-tag → Bootstrap badge color
	_TAG_COLORS: dict[str, str] = {
		"disorder":    "danger",
		"finding":     "warning",
		"procedure":   "primary",
		"substance":   "info",
		"product":     "info",
		"body structure": "secondary",
		"organism":    "success",
		"qualifier value": "light",
		"situation":   "warning",
		"event":       "dark",
	}

	def __init__(
		self,
		domain: str | int | None = None,
		active_only: bool = True,
		placeholder: str = "Search SNOMED CT clinical term or SCTID…",
	):
		self.domain = str(domain) if domain is not None else ""
		self.active_only = active_only
		self.placeholder = placeholder

	def __call__(self, field, **kwargs) -> str:
		global _SNOMED_COUNTER
		_SNOMED_COUNTER += 1
		wid = f"snomedw_{_SNOMED_COUNTER}"

		current_val = field.data or ""
		active_flag = "true" if self.active_only else "false"
		domains_json = json.dumps(SNOMED_DOMAINS)
		tag_colors_json = json.dumps(self._TAG_COLORS)

		domain_options = "\n".join(
			f'<option value="{d["id"] or ""}" '
			f'{"selected" if str(d["id"] or "") == self.domain else ""}>'
			f'{d["label"]}</option>'
			for d in SNOMED_DOMAINS
		)

		html = f"""
<div class="snomed-widget" id="{wid}_container" style="position:relative;">
  <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
    <input type="hidden" name="{field.name}" id="{wid}_hidden" value="{current_val}">
    <input type="text"
           id="{wid}_display"
           class="form-control"
           placeholder="{self.placeholder}"
           autocomplete="off"
           style="flex:1;min-width:260px;"
           value="">
    <select id="{wid}_domain" class="form-control" style="max-width:180px;flex-shrink:0;"
            onchange="snomedSetDomain('{wid}', this.value)">
      {domain_options}
    </select>
  </div>

  <div id="{wid}_dropdown"
       style="display:none;position:absolute;z-index:9999;background:#fff;
              border:1px solid #ccc;border-radius:4px;max-height:340px;
              overflow-y:auto;width:100%;box-shadow:0 4px 12px rgba(0,0,0,.15);
              top:calc(100% + 2px);left:0;">
  </div>

  <div id="{wid}_detail"
       style="display:none;margin-top:6px;padding:8px 12px;
              background:#f8f9fa;border:1px solid #dee2e6;border-radius:4px;
              font-size:12px;">
  </div>
</div>

<script>
(function() {{
  var wid = {_js_json(wid)};
  var domainId = {_js_json(self.domain)};
  var activeOnly = {active_flag};
  var debounceTimer = null;
  var TAG_COLORS = {tag_colors_json};

  // ── Restore if value already set ─────────────────────────────────────────
  var hv = document.getElementById(wid + '_hidden').value;
  if (hv) {{
    fetch('/snomed/concept/' + hv)
      .then(r => r.json())
      .then(function(data) {{ if (data.id) restoreSelected(data); }})
      .catch(function() {{}});
  }}

  function restoreSelected(data) {{
    var tag = data.tag || '';
    document.getElementById(wid + '_display').value =
      data.preferred + (tag ? ' (' + tag + ')' : '');
    showDetail(data);
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

  function buildUrl(q) {{
    var url = '/snomed/search?q=' + encodeURIComponent(q) +
              '&active_only=' + (activeOnly ? '1' : '0') +
              '&limit=20';
    if (domainId) url += '&domain_id=' + domainId;
    return url;
  }}

  function doSearch(q) {{
    fetch(buildUrl(q)).then(r => r.json()).then(showDropdown).catch(closeDropdown);
  }}

  function tagBadge(tag) {{
    if (!tag) return '';
    var color = TAG_COLORS[tag.toLowerCase()] || 'secondary';
    return '<span class="badge badge-' + color + '" style="font-size:10px;margin-left:4px;">'
           + tag + '</span>';
  }}

  function showDropdown(items) {{
    var dd = document.getElementById(wid + '_dropdown');
    if (!items.length) {{ dd.style.display = 'none'; return; }}
    dd.innerHTML = items.map(function(it) {{
      return '<div class="snomed-item" style="padding:8px 12px;cursor:pointer;' +
             'border-bottom:1px solid #f0f0f0;" ' +
             'onmousedown="snomedPick(\'' + wid + '\',' + JSON.stringify(it) + ')">' +
             '<div>' +
             '<strong>' + it.preferred + '</strong>' + tagBadge(it.tag) +
             '</div>' +
             (it.matched_term !== it.preferred
               ? '<div style="color:#666;font-size:11px;">Also known as: ' + it.matched_term + '</div>'
               : '') +
             '<div style="color:#999;font-size:10px;font-family:monospace;">' +
             it.concept_id + '</div>' +
             '</div>';
    }}).join('');
    dd.style.display = 'block';
  }}

  function closeDropdown() {{
    document.getElementById(wid + '_dropdown').style.display = 'none';
  }}

  function showDetail(data) {{
    var el = document.getElementById(wid + '_detail');
    var tag = data.tag || '';
    var parents = (data.parents || []).map(function(p) {{
      var ptag = p.fsn ? p.fsn.match(/[(]([^)]+)[)]$/) : null;
      var plabel = p.fsn && p.fsn.includes(' (')
        ? p.fsn.substring(0, p.fsn.lastIndexOf(' ('))
        : (p.fsn || p.id);
      return '<span class="badge badge-light" style="margin:1px;border:1px solid #ccc;">' +
             plabel + (ptag ? ' <em>(' + ptag[1] + ')</em>' : '') + '</span>';
    }}).join(' ');

    el.innerHTML =
      '<div style="display:flex;align-items:flex-start;gap:8px;">' +
      '<div style="flex:1;">' +
      '<strong>' + (data.preferred || data.fsn) + '</strong>' + tagBadge(tag) +
      '<br><span style="color:#666;font-size:11px;">FSN: ' + (data.fsn || '—') + '</span>' +
      '<br><span style="color:#999;font-size:10px;font-family:monospace;">SCTID: ' + data.id + '</span>' +
      (parents ? '<br><span style="font-size:11px;color:#555;">Is a: ' + parents + '</span>' : '') +
      '</div>' +
      '<button type="button" class="btn btn-sm btn-outline-secondary" ' +
      'style="flex-shrink:0;padding:2px 6px;font-size:11px;" ' +
      'onclick="snomedClear(\'' + wid + '\')">&times; Clear</button>' +
      '</div>';
    el.style.display = 'block';
  }}

  // ── Public API ────────────────────────────────────────────────────────────
  window.snomedPick = function(w, it) {{
    if (w !== wid) return;
    document.getElementById(wid + '_hidden').value = it.id;
    document.getElementById(wid + '_display').value =
      it.preferred + (it.tag ? ' (' + it.tag + ')' : '');
    closeDropdown();
    // Fetch full detail (parents, synonyms)
    fetch('/snomed/concept/' + it.id)
      .then(r => r.json())
      .then(showDetail)
      .catch(function() {{
        showDetail({{id: it.id, preferred: it.preferred, fsn: it.fsn, tag: it.tag, parents: []}});
      }});
  }};

  window.snomedSetDomain = function(w, val) {{
    if (w !== wid) return;
    domainId = val;
    var q = document.getElementById(wid + '_display').value.trim();
    if (q.length >= 2) doSearch(q);
  }};

  window.snomedClear = function(w) {{
    if (w !== wid) return;
    document.getElementById(wid + '_hidden').value = '';
    document.getElementById(wid + '_display').value = '';
    document.getElementById(wid + '_detail').style.display = 'none';
    closeDropdown();
  }};

}})();
</script>
"""
		return html


# ─── WTForms field ────────────────────────────────────────────────────────────

try:
	from wtforms import IntegerField

	class SNOMEDField(IntegerField):
		"""WTForms IntegerField that stores SCTID and renders SNOMEDSearchWidget."""
		widget = SNOMEDSearchWidget()

except ImportError:
	pass
