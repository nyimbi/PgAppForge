"""
Developer tool widgets for PgAppForge.

Provides two standalone BaseView helper widgets intended for admin/dev use:

- SQLEditorWidget  — inline Monaco-based SQL editor with result table
- APITesterWidget  — embedded REST endpoint tester (no CDN beyond Bootstrap)

Neither widget is a WTForms field widget.  Both expose a ``render()``
classmethod that returns a ``Markup`` fragment ready to drop into a Jinja2
template or a BaseView ``extra_args`` dict.

Usage in a BaseView::

    from pgappforge.widgets.dev_widgets import SQLEditorWidget, APITesterWidget

    class DevConsoleView(BaseView):
        @expose("/")
        @has_access
        def index(self):
            sql_html = SQLEditorWidget(
                execute_url="/api/sql/execute",
                schema_url="/api/sql/schema",
            ).render()

            endpoints = [
                {
                    "method": "GET",
                    "path": "/api/users/{id}",
                    "description": "Fetch a single user",
                    "example_body": "",
                },
                {
                    "method": "POST",
                    "path": "/api/users",
                    "description": "Create a new user",
                    "example_body": '{"name": "Alice", "email": "alice@example.com"}',
                },
            ]
            api_html = APITesterWidget().render(endpoints)

            return self.render_template(
                "dev_console.html",
                sql_editor=sql_html,
                api_tester=api_html,
            )

Security notes
--------------
* ``SQLEditorWidget`` is guarded by a Flask-Login ``current_user`` admin check
  at render time; the *execute_url* backend **must** enforce its own auth and
  must reject non-SELECT statements server-side.
* ``APITesterWidget`` is a client-side tool only.  Never expose it in
  production without route-level ``@has_access`` / role guards.
"""
from __future__ import annotations

import json
import logging

from markupsafe import Markup
from pgappforge.widgets._utils import js_json as _js_json

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CDN assets
# ---------------------------------------------------------------------------

_MONACO_LOADER = (
	"https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs/loader.js"
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid(prefix: str) -> str:
	"""Return a collision-resistant DOM id prefix (no runtime deps)."""
	import hashlib, time
	h = hashlib.md5(f"{prefix}{time.monotonic()}".encode()).hexdigest()[:8]
	return f"{prefix}_{h}"


def _is_admin() -> bool:
	"""Return True when the current Flask-Login user has the Admin role."""
	try:
		from flask_login import current_user
		if not current_user or not current_user.is_authenticated:
			return False
		# FAB stores roles as a list of role objects with a .name attribute
		roles = getattr(current_user, "roles", [])
		return any(getattr(r, "name", r) == "Admin" for r in roles)
	except Exception:
		return False


# ---------------------------------------------------------------------------
# SQLEditorWidget
# ---------------------------------------------------------------------------


class SQLEditorWidget:
	"""Inline Monaco-based SQL editor for admin / developer views.

	This is a **standalone** widget — it is not a WTForms field widget.
	Call ``render()`` to get a ``Markup`` fragment.

	The widget is only rendered when the current user has the **Admin** role.
	For all other users ``render()`` returns an empty ``Markup``.

	The backend endpoint at *execute_url* receives a POST with JSON body
	``{"sql": "<query>"}`` and must return JSON in one of two shapes::

	    # success
	    {"columns": ["col1", "col2"], "rows": [[v, v], [v, v]], "elapsed_ms": 12}

	    # error
	    {"error": "message string"}

	The widget enforces SELECT-only on the *client* side (as UX feedback).
	The *server* side **must** independently enforce this restriction.

	Args:
	    execute_url: URL that executes the SQL query (default ``/api/sql/execute``).
	    schema_url:  URL that returns schema metadata for autocomplete
	                 (default ``/api/sql/schema``).  Expected response shape::

	                     {"tables": [{"name": "users", "columns": ["id", "name"]}, ...]}

	    height:      Editor height in pixels (default 400).
	    theme:       Monaco editor theme — ``"vs"`` (light) or ``"vs-dark"``
	                 (default ``"vs-dark"``).
	    placeholder: Initial SQL shown in the editor on first load.
	    widget_id:   Optional stable DOM id prefix.  Auto-generated when omitted.
	"""

	def __init__(
		self,
		execute_url: str = "/api/sql/execute",
		schema_url: str = "/api/sql/schema",
		height: int = 400,
		theme: str = "vs-dark",
		placeholder: str = "SELECT * FROM users LIMIT 10;",
		widget_id: str | None = None,
	) -> None:
		self.execute_url = execute_url
		self.schema_url = schema_url
		self.height = height
		self.theme = theme
		self.placeholder = placeholder
		self._wid = widget_id or _uid("sqled")

	# ------------------------------------------------------------------

	def render(self) -> Markup:
		"""Render the SQL editor widget.

		Returns an empty ``Markup`` when the current user is not an admin.
		"""
		if not _is_admin():
			log.debug("SQLEditorWidget.render(): non-admin user — skipping render")
			return Markup("")

		wid = self._wid
		execute_url = self.execute_url
		schema_url = self.schema_url
		height = self.height
		theme = self.theme
		placeholder_json = json.dumps(self.placeholder)
		monaco_loader = _MONACO_LOADER

		html = f"""
<!-- SQLEditorWidget [{wid}] -->
<div id="{wid}_container" class="sql-editor-widget" style="font-family:monospace">
  <!-- toolbar -->
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
    <span class="label label-info" style="font-size:0.8em;padding:3px 7px">
      SQL Editor <small>(SELECT only)</small>
    </span>
    <button id="{wid}_run_btn" class="btn btn-sm btn-primary"
            title="Run query (Ctrl+Enter)">
      &#9654; Run
    </button>
    <button id="{wid}_clear_btn" class="btn btn-sm btn-default"
            title="Clear editor">
      Clear
    </button>
    <span id="{wid}_status" style="margin-left:auto;font-size:0.8em;color:#888"></span>
  </div>

  <!-- Monaco editor host -->
  <div id="{wid}_editor"
       style="width:100%;height:{height}px;border:1px solid #ccc;border-radius:3px">
  </div>

  <!-- error banner -->
  <div id="{wid}_error"
       style="display:none;margin-top:8px;padding:8px 12px;
              background:#f2dede;border:1px solid #ebccd1;border-radius:3px;
              color:#a94442;font-size:0.9em">
  </div>

  <!-- results table -->
  <div id="{wid}_results_wrap"
       style="display:none;margin-top:10px;max-height:360px;overflow:auto">
    <table id="{wid}_results_tbl"
           class="table table-bordered table-condensed table-hover"
           style="margin-bottom:0;font-size:0.85em">
      <thead id="{wid}_thead"></thead>
      <tbody id="{wid}_tbody"></tbody>
    </table>
  </div>
</div>

<script>
(function() {{
  var WID       = {_js_json(wid)};
  var EXEC_URL  = {_js_json(execute_url)};
  var SCHEMA_URL= {_js_json(schema_url)};
  var THEME     = {_js_json(theme)};
  var INIT_VAL  = {placeholder_json};
  var monacoEditor = null;

  /* ---- DOM helpers ---- */
  function $id(suffix) {{ return document.getElementById(WID + suffix); }}

  function setStatus(msg) {{ $id('_status').textContent = msg; }}

  function showError(msg) {{
    var el = $id('_error');
    el.textContent = '⚠ ' + msg;
    el.style.display = 'block';
  }}

  function clearError() {{
    $id('_error').style.display = 'none';
    $id('_error').textContent = '';
  }}

  function renderResults(data) {{
    clearError();
    var wrap  = $id('_results_wrap');
    var thead = $id('_thead');
    var tbody = $id('_tbody');

    if (!data.columns || data.columns.length === 0) {{
      wrap.style.display = 'none';
      setStatus('Query executed (no rows returned)');
      return;
    }}

    /* header */
    var trh = document.createElement('tr');
    data.columns.forEach(function(col) {{
      var th = document.createElement('th');
      th.textContent = col;
      trh.appendChild(th);
    }});
    thead.innerHTML = '';
    thead.appendChild(trh);

    /* rows */
    tbody.innerHTML = '';
    (data.rows || []).forEach(function(row) {{
      var tr = document.createElement('tr');
      row.forEach(function(cell) {{
        var td = document.createElement('td');
        td.textContent = (cell === null ? 'NULL' : String(cell));
        tr.appendChild(td);
      }});
      tbody.appendChild(tr);
    }});

    wrap.style.display = 'block';

    var rowCount = (data.rows || []).length;
    var elapsed  = data.elapsed_ms != null ? (' • ' + data.elapsed_ms + ' ms') : '';
    setStatus(rowCount + ' row' + (rowCount !== 1 ? 's' : '') + elapsed);
  }}

  /* ---- execute ---- */
  function runQuery() {{
    if (!monacoEditor) return;
    var sql = monacoEditor.getValue().trim();
    if (!sql) return;

    /* client-side SELECT guard — UX only; backend must re-validate */
    var firstWord = sql.replace(/\\/\\*[\\s\\S]*?\\*\\//g, '')   /* strip block comments */
                       .replace(/--[^\\n]*/g, '')               /* strip line comments  */
                       .trim()
                       .split(/\\s+/)[0]
                       .toUpperCase();
    if (firstWord !== 'SELECT' && firstWord !== 'WITH' && firstWord !== 'EXPLAIN') {{
      showError('Only SELECT / WITH / EXPLAIN statements are permitted here.');
      return;
    }}

    clearError();
    setStatus('Running…');
    $id('_run_btn').disabled = true;

    var xhr = new XMLHttpRequest();
    xhr.open('POST', EXEC_URL, true);
    xhr.setRequestHeader('Content-Type', 'application/json');
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');

    /* attach CSRF token if Flask-WTF meta tag is present */
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    if (csrfMeta) xhr.setRequestHeader('X-CSRFToken', csrfMeta.getAttribute('content'));

    xhr.onreadystatechange = function() {{
      if (xhr.readyState !== 4) return;
      $id('_run_btn').disabled = false;
      if (xhr.status !== 200) {{
        showError('HTTP ' + xhr.status + ': ' + xhr.statusText);
        setStatus('');
        return;
      }}
      try {{
        var resp = JSON.parse(xhr.responseText);
        if (resp.error) {{
          showError(resp.error);
          setStatus('');
        }} else {{
          renderResults(resp);
        }}
      }} catch(e) {{
        showError('Invalid JSON response: ' + e.message);
        setStatus('');
      }}
    }};

    xhr.send(JSON.stringify({{sql: sql}}));
  }}

  /* ---- fetch schema for autocomplete ---- */
  function fetchSchema(callback) {{
    var xhr = new XMLHttpRequest();
    xhr.open('GET', SCHEMA_URL, true);
    xhr.setRequestHeader('X-Requested-With', 'XMLHttpRequest');
    xhr.onreadystatechange = function() {{
      if (xhr.readyState !== 4) return;
      if (xhr.status === 200) {{
        try {{ callback(JSON.parse(xhr.responseText)); }} catch(e) {{ /* ignore */ }}
      }}
    }};
    xhr.send();
  }}

  /* ---- Monaco init ---- */
  function initMonaco() {{
    require.config({{ paths: {{ vs: '{monaco_loader}'.replace('/loader.js', '') }} }});
    require(['vs/editor/editor.main'], function() {{

      monacoEditor = monaco.editor.create($id('_editor'), {{
        value: INIT_VAL,
        language: 'sql',
        theme: THEME,
        minimap: {{ enabled: false }},
        fontSize: 13,
        wordWrap: 'on',
        scrollBeyondLastLine: false,
        automaticLayout: true,
        suggestOnTriggerCharacters: true,
      }});

      /* Ctrl+Enter shortcut */
      monacoEditor.addCommand(
        monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter,
        runQuery
      );

      /* autocomplete from schema endpoint */
      fetchSchema(function(schema) {{
        var suggestions = [];
        (schema.tables || []).forEach(function(tbl) {{
          suggestions.push({{
            label: tbl.name,
            kind: monaco.languages.CompletionItemKind.Class,
            insertText: tbl.name,
            detail: 'table',
          }});
          (tbl.columns || []).forEach(function(col) {{
            suggestions.push({{
              label: col,
              kind: monaco.languages.CompletionItemKind.Field,
              insertText: col,
              detail: tbl.name + '.' + col,
            }});
          }});
        }});
        monaco.languages.registerCompletionItemProvider('sql', {{
          provideCompletionItems: function() {{
            return {{ suggestions: suggestions }};
          }}
        }});
      }});
    }});
  }}

  /* ---- button wiring ---- */
  function wireButtons() {{
    $id('_run_btn').addEventListener('click', runQuery);
    $id('_clear_btn').addEventListener('click', function() {{
      if (monacoEditor) monacoEditor.setValue('');
      clearError();
      $id('_results_wrap').style.display = 'none';
      setStatus('');
    }});
  }}

  /* ---- bootstrap ---- */
  function bootstrap() {{
    wireButtons();
    if (window.require && window.require.config) {{
      initMonaco();
    }} else {{
      var s = document.createElement('script');
      s.src = {_js_json(monaco_loader)};
      s.onload = initMonaco;
      document.head.appendChild(s);
    }}
  }}

  if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', bootstrap);
  }} else {{
    bootstrap();
  }}
}})();
</script>
<!-- /SQLEditorWidget [{wid}] -->
"""
		return Markup(html)


# ---------------------------------------------------------------------------
# APITesterWidget
# ---------------------------------------------------------------------------


class APITesterWidget:
	"""Embedded REST endpoint tester for development mode.

	No external CDN required beyond the Bootstrap already loaded by FAB.

	Each *endpoint* dict passed to ``render()`` must contain:

	- ``method``       — HTTP verb string: ``"GET"``, ``"POST"``, ``"PUT"``,
	                     ``"PATCH"``, or ``"DELETE"``
	- ``path``         — URL path, may contain ``{param}`` placeholders,
	                     e.g. ``"/api/users/{id}"``
	- ``description``  — Short human-readable label shown in the dropdown
	- ``example_body`` — JSON string pre-filled in the request body textarea
	                     (ignored for GET / DELETE)

	Args:
	    base_url:   Base URL prepended to every path (default ``""`` — same
	                origin).  Example: ``"https://api.example.com"``.
	    widget_id:  Optional stable DOM id prefix.  Auto-generated when omitted.
	"""

	# Bootstrap colour classes for HTTP method badges
	_METHOD_COLOURS: dict[str, str] = {
		"GET":    "success",
		"POST":   "primary",
		"PUT":    "warning",
		"PATCH":  "info",
		"DELETE": "danger",
	}

	def __init__(
		self,
		base_url: str = "",
		widget_id: str | None = None,
	) -> None:
		self.base_url = base_url
		self._wid = widget_id or _uid("apitst")

	# ------------------------------------------------------------------

	def render(self, endpoints: list[dict]) -> Markup:
		"""Render the API tester widget.

		Args:
		    endpoints: List of endpoint descriptor dicts (see class docstring).

		Returns:
		    A ``Markup`` HTML fragment safe for direct template insertion.
		"""
		if not endpoints:
			return Markup(
				'<p class="text-muted"><em>No endpoints configured.</em></p>'
			)

		# Sanitise and normalise endpoint list
		clean: list[dict] = []
		for ep in endpoints:
			method = str(ep.get("method", "GET")).upper().strip()
			if method not in self._METHOD_COLOURS:
				method = "GET"
			clean.append({
				"method":      method,
				"path":        str(ep.get("path", "/")),
				"description": str(ep.get("description", ep.get("path", "/"))),
				"example_body": str(ep.get("example_body", "")),
			})

		endpoints_json = json.dumps(clean)
		wid = self._wid
		base_url_json = json.dumps(self.base_url)
		method_colours_json = json.dumps(self._METHOD_COLOURS)
		wid_json = json.dumps(wid)

		# HTML markup — only simple Python identifiers interpolated, no JS braces.
		html_markup = (
			"\n<!-- APITesterWidget [" + wid + "] -->\n"
			'<div id="' + wid + '_container" class="api-tester-widget panel panel-default"'
			' style="margin-bottom:0">\n'
			'  <div class="panel-heading" style="padding:8px 12px">\n'
			'    <strong>API Tester</strong>\n'
			'    <span class="label label-default" style="margin-left:6px;font-size:0.75em">\n'
			'      dev only\n'
			'    </span>\n'
			'  </div>\n'
			'  <div class="panel-body" style="padding:12px">\n'
			'\n'
			'    <!-- endpoint selector -->\n'
			'    <div class="form-group" style="margin-bottom:8px">\n'
			'      <label style="font-size:0.85em;margin-bottom:4px">Endpoint</label>\n'
			'      <select id="' + wid + '_ep_select" class="form-control input-sm"></select>\n'
			'    </div>\n'
			'\n'
			'    <!-- method badge + URL row -->\n'
			'    <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap">\n'
			'      <span id="' + wid + '_method_badge" class="label label-success"\n'
			'            style="font-size:1em;padding:5px 10px;min-width:60px;text-align:center">\n'
			'        GET\n'
			'      </span>\n'
			'      <code id="' + wid + '_url_display"\n'
			'            style="flex:1;background:#f5f5f5;border:1px solid #ddd;\n'
			'                   border-radius:3px;padding:5px 8px;font-size:0.9em;\n'
			'                   word-break:break-all;min-width:0">\n'
			'      </code>\n'
			'    </div>\n'
			'\n'
			'    <!-- path parameter inputs (rendered dynamically) -->\n'
			'    <div id="' + wid + '_path_params" style="margin-bottom:8px"></div>\n'
			'\n'
			'    <!-- request body -->\n'
			'    <div id="' + wid + '_body_wrap" class="form-group" style="margin-bottom:8px">\n'
			'      <label style="font-size:0.85em;margin-bottom:4px">\n'
			'        Request Body <small class="text-muted">(JSON)</small>\n'
			'      </label>\n'
			'      <textarea id="' + wid + '_body_ta" class="form-control"\n'
			'                rows="5" spellcheck="false"\n'
			'                style="font-family:monospace;font-size:0.85em;resize:vertical">\n'
			'      </textarea>\n'
			'    </div>\n'
			'\n'
			'    <!-- send button -->\n'
			'    <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">\n'
			'      <button id="' + wid + '_send_btn" class="btn btn-sm btn-primary">\n'
			'        &#9654; Send\n'
			'      </button>\n'
			'      <button id="' + wid + '_copy_curl_btn" class="btn btn-sm btn-default"\n'
			'              title="Copy cURL command to clipboard">\n'
			'        Copy cURL\n'
			'      </button>\n'
			'      <span id="' + wid + '_send_status" style="font-size:0.8em;color:#888"></span>\n'
			'    </div>\n'
			'\n'
			'    <!-- response panel -->\n'
			'    <div id="' + wid + '_resp_panel" style="display:none">\n'
			'      <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">\n'
			'        <span style="font-size:0.85em;color:#666">Response</span>\n'
			'        <span id="' + wid + '_status_badge" class="label label-default"\n'
			'              style="font-size:0.9em"></span>\n'
			'        <span id="' + wid + '_resp_time"\n'
			'              style="font-size:0.8em;color:#888;margin-left:auto"></span>\n'
			'      </div>\n'
			'      <pre id="' + wid + '_resp_body"\n'
			'           style="max-height:320px;overflow:auto;background:#1e1e1e;\n'
			'                  color:#d4d4d4;border:none;border-radius:4px;\n'
			'                  padding:10px;font-size:0.8em;margin:0;white-space:pre-wrap;\n'
			'                  word-break:break-word"></pre>\n'
			'    </div>\n'
			'\n'
			'  </div><!-- /panel-body -->\n'
			'</div><!-- /api-tester-widget -->\n'
		)

		# JS block — use % formatting so { and } are literal JS chars,
		# no escaping gymnastics required.
		js_block = (
			"\n<script>\n"
			"(function() {\n"
			"  var WID          = %(wid_json)s;\n"
			"  var ENDPOINTS    = %(endpoints_json)s;\n"
			"  var BASE_URL     = %(base_url_json)s;\n"
			"  var METHOD_COLS  = %(method_colours_json)s;\n"
			"  var currentIdx   = 0;\n"
			"\n"
			"  /* ---- DOM helpers ---- */\n"
			"  function $id(suffix) { return document.getElementById(WID + suffix); }\n"
			"\n"
			"  function setStatus(msg, colour) {\n"
			"    var el = $id('_send_status');\n"
			"    el.textContent = msg;\n"
			"    el.style.color = colour || '#888';\n"
			"  }\n"
			"\n"
			"  /* ---- path param extraction ---- */\n"
			"  function extractParams(path) {\n"
			"    var re = new RegExp('\\\\{([^}]+)\\\\}', 'g'), params = [], m;\n"
			"    while ((m = re.exec(path)) !== null) params.push(m[1]);\n"
			"    return params;\n"
			"  }\n"
			"\n"
			"  function buildParamInputsHTML(params) {\n"
			"    if (!params.length) return '';\n"
			"    var rows = params.map(function(p) {\n"
			"      return '<div style=\"display:flex;align-items:center;gap:6px;margin-bottom:4px\">'\n"
			"        + '<label style=\"min-width:80px;font-size:0.82em;margin:0;font-weight:normal\">'\n"
			"        +   p\n"
			"        + '</label>'\n"
			"        + '<input id=\"' + WID + '_param_' + p + '\" class=\"form-control input-sm\"'\n"
			"        +        ' style=\"max-width:240px\" placeholder=\"' + p + '\" />'\n"
			"        + '</div>';\n"
			"    });\n"
			"    return '<div style=\"background:#f9f9f9;border:1px solid #eee;border-radius:3px;'\n"
			"         + 'padding:8px 10px;margin-bottom:8px\">'\n"
			"         + '<small class=\"text-muted\" style=\"display:block;margin-bottom:4px\">'\n"
			"         + 'Path parameters</small>'\n"
			"         + rows.join('')\n"
			"         + '</div>';\n"
			"  }\n"
			"\n"
			"  function resolveUrl(path, params) {\n"
			"    var url = path;\n"
			"    params.forEach(function(p) {\n"
			"      var el = document.getElementById(WID + '_param_' + p);\n"
			"      var val = el ? encodeURIComponent(el.value || ':' + p) : (':' + p);\n"
			"      url = url.replace('{' + p + '}', val);\n"
			"    });\n"
			"    return BASE_URL + url;\n"
			"  }\n"
			"\n"
			"  /* ---- cURL generation ---- */\n"
			"  function buildCurl(method, url, body, headers) {\n"
			"    var parts = ['curl -X ' + method];\n"
			"    Object.keys(headers).forEach(function(k) {\n"
			"      parts.push('  -H ' + JSON.stringify(k + ': ' + headers[k]));\n"
			"    });\n"
			"    if (body && method !== 'GET' && method !== 'DELETE') {\n"
			"      parts.push('  -d ' + JSON.stringify(body));\n"
			"    }\n"
			"    parts.push('  ' + JSON.stringify(url));\n"
			"    return parts.join(' \\\\\\n');\n"
			"  }\n"
			"\n"
			"  /* ---- update UI for selected endpoint ---- */\n"
			"  function selectEndpoint(idx) {\n"
			"    currentIdx = idx;\n"
			"    var ep     = ENDPOINTS[idx];\n"
			"    var method = ep.method;\n"
			"    var colour = METHOD_COLS[method] || 'default';\n"
			"    var params = extractParams(ep.path);\n"
			"\n"
			"    /* method badge */\n"
			"    var badge = $id('_method_badge');\n"
			"    badge.textContent = method;\n"
			"    badge.className = 'label label-' + colour;\n"
			"\n"
			"    /* path param inputs */\n"
			"    $id('_path_params').innerHTML = buildParamInputsHTML(params);\n"
			"\n"
			"    /* update URL display whenever a param input changes */\n"
			"    params.forEach(function(p) {\n"
			"      var el = document.getElementById(WID + '_param_' + p);\n"
			"      if (el) el.addEventListener('input', refreshUrlDisplay);\n"
			"    });\n"
			"\n"
			"    refreshUrlDisplay();\n"
			"\n"
			"    /* body textarea */\n"
			"    var noBody = method === 'GET' || method === 'DELETE';\n"
			"    $id('_body_wrap').style.display = noBody ? 'none' : '';\n"
			"    $id('_body_ta').value = ep.example_body || '';\n"
			"\n"
			"    /* hide stale response */\n"
			"    $id('_resp_panel').style.display = 'none';\n"
			"    setStatus('');\n"
			"  }\n"
			"\n"
			"  function refreshUrlDisplay() {\n"
			"    var ep     = ENDPOINTS[currentIdx];\n"
			"    var params = extractParams(ep.path);\n"
			"    $id('_url_display').textContent = resolveUrl(ep.path, params);\n"
			"  }\n"
			"\n"
			"  /* ---- HTTP status badge colour ---- */\n"
			"  function statusColour(code) {\n"
			"    if (code >= 200 && code < 300) return 'success';\n"
			"    if (code >= 300 && code < 400) return 'info';\n"
			"    if (code >= 400 && code < 500) return 'warning';\n"
			"    if (code >= 500)               return 'danger';\n"
			"    return 'default';\n"
			"  }\n"
			"\n"
			"  /* ---- send request ---- */\n"
			"  function sendRequest() {\n"
			"    var ep     = ENDPOINTS[currentIdx];\n"
			"    var method = ep.method;\n"
			"    var params = extractParams(ep.path);\n"
			"    var url    = resolveUrl(ep.path, params);\n"
			"    var body   = (method === 'GET' || method === 'DELETE')\n"
			"                   ? null\n"
			"                   : $id('_body_ta').value.trim();\n"
			"\n"
			"    var headers = { 'X-Requested-With': 'XMLHttpRequest' };\n"
			"    if (body) headers['Content-Type'] = 'application/json';\n"
			"    var csrfMeta = document.querySelector('meta[name=\"csrf-token\"]');\n"
			"    if (csrfMeta) headers['X-CSRFToken'] = csrfMeta.getAttribute('content');\n"
			"\n"
			"    setStatus('Sending…');\n"
			"    $id('_send_btn').disabled = true;\n"
			"    var t0 = Date.now();\n"
			"\n"
			"    var xhr = new XMLHttpRequest();\n"
			"    xhr.open(method, url, true);\n"
			"    Object.keys(headers).forEach(function(k) { xhr.setRequestHeader(k, headers[k]); });\n"
			"\n"
			"    xhr.onreadystatechange = function() {\n"
			"      if (xhr.readyState !== 4) return;\n"
			"      $id('_send_btn').disabled = false;\n"
			"      var elapsed = Date.now() - t0;\n"
			"\n"
			"      var statusBadge = $id('_status_badge');\n"
			"      statusBadge.textContent = xhr.status + ' ' + xhr.statusText;\n"
			"      statusBadge.className = 'label label-' + statusColour(xhr.status);\n"
			"\n"
			"      $id('_resp_time').textContent = elapsed + ' ms';\n"
			"\n"
			"      var raw = xhr.responseText || '';\n"
			"      var pretty = raw;\n"
			"      try {\n"
			"        pretty = JSON.stringify(JSON.parse(raw), null, 2);\n"
			"      } catch(e) { /* leave as-is */ }\n"
			"      $id('_resp_body').textContent = pretty;\n"
			"      $id('_resp_panel').style.display = 'block';\n"
			"\n"
			"      setStatus('Done', '#888');\n"
			"    };\n"
			"\n"
			"    $id('_copy_curl_btn')._curls = buildCurl(method, url, body, headers);\n"
			"    xhr.send(body || null);\n"
			"  }\n"
			"\n"
			"  /* ---- copy cURL ---- */\n"
			"  function copyCurl() {\n"
			"    var curlStr = $id('_copy_curl_btn')._curls;\n"
			"    if (!curlStr) {\n"
			"      var ep     = ENDPOINTS[currentIdx];\n"
			"      var method = ep.method;\n"
			"      var params = extractParams(ep.path);\n"
			"      var url    = resolveUrl(ep.path, params);\n"
			"      var body   = (method === 'GET' || method === 'DELETE')\n"
			"                     ? null\n"
			"                     : $id('_body_ta').value.trim();\n"
			"      var headers = { 'X-Requested-With': 'XMLHttpRequest' };\n"
			"      if (body) headers['Content-Type'] = 'application/json';\n"
			"      curlStr = buildCurl(method, url, body, headers);\n"
			"    }\n"
			"    if (navigator.clipboard && navigator.clipboard.writeText) {\n"
			"      navigator.clipboard.writeText(curlStr).then(function() {\n"
			"        setStatus('cURL copied!', '#3c763d');\n"
			"        setTimeout(function() { setStatus(''); }, 2000);\n"
			"      });\n"
			"    } else {\n"
			"      var ta = document.createElement('textarea');\n"
			"      ta.value = curlStr;\n"
			"      ta.style.position = 'fixed';\n"
			"      ta.style.opacity  = '0';\n"
			"      document.body.appendChild(ta);\n"
			"      ta.focus(); ta.select();\n"
			"      try { document.execCommand('copy'); setStatus('cURL copied!', '#3c763d'); }\n"
			"      catch(e) { setStatus('Copy failed', '#a94442'); }\n"
			"      document.body.removeChild(ta);\n"
			"      setTimeout(function() { setStatus(''); }, 2000);\n"
			"    }\n"
			"  }\n"
			"\n"
			"  /* ---- build dropdown ---- */\n"
			"  function buildDropdown() {\n"
			"    var sel = $id('_ep_select');\n"
			"    ENDPOINTS.forEach(function(ep, i) {\n"
			"      var opt = document.createElement('option');\n"
			"      opt.value = i;\n"
			"      opt.textContent = '[' + ep.method + '] ' + ep.path\n"
			"                       + (ep.description ? '  —  ' + ep.description : '');\n"
			"      sel.appendChild(opt);\n"
			"    });\n"
			"    sel.addEventListener('change', function() {\n"
			"      selectEndpoint(parseInt(this.value, 10));\n"
			"    });\n"
			"  }\n"
			"\n"
			"  /* ---- bootstrap ---- */\n"
			"  function init() {\n"
			"    buildDropdown();\n"
			"    selectEndpoint(0);\n"
			"    $id('_send_btn').addEventListener('click', sendRequest);\n"
			"    $id('_copy_curl_btn').addEventListener('click', copyCurl);\n"
			"  }\n"
			"\n"
			"  if (document.readyState === 'loading') {\n"
			"    document.addEventListener('DOMContentLoaded', init);\n"
			"  } else {\n"
			"    init();\n"
			"  }\n"
			"})();\n"
			"</script>\n"
			"<!-- /APITesterWidget [%(wid)s] -->\n"
		) % {
			"wid":                 wid,
			"wid_json":            wid_json,
			"endpoints_json":      endpoints_json,
			"base_url_json":       base_url_json,
			"method_colours_json": method_colours_json,
		}

		return Markup(html_markup + js_block)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

__all__ = [
	"SQLEditorWidget",
	"APITesterWidget",
]
