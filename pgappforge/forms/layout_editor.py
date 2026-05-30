"""
pgappforge.forms.layout_editor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Visual drag-and-drop form layout editor, surfaced as a FAB BaseView.

Routes
------
GET  /form-editor/<view_name>/<form_type>   — render inline editor UI
POST /form-editor/save                      — persist layout (JSON body)
GET  /form-editor/reset/<view_name>/<form_type> — delete saved layout

Public helper
-------------
inject_edit_button(view_name, form_html) -> str
    Wraps rendered form HTML to prepend an admin-only "Edit Form" button
    that opens the editor in a Bootstrap 3 modal.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import current_app, jsonify, redirect, render_template_string, request, url_for
from flask_login import current_user
from markupsafe import Markup

from pgappforge.baseviews import BaseView, expose
from pgappforge.forms.layout_manager import AVAILABLE_WIDGETS, FormLayoutManager

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_manager() -> FormLayoutManager:
	"""Resolve the SQLAlchemy session from the running AppBuilder and return a manager."""
	try:
		session = current_app.appbuilder.get_session
	except AttributeError:
		# Fallback: Flask-SQLAlchemy extension
		from flask_sqlalchemy import SQLAlchemy
		db: SQLAlchemy = current_app.extensions["sqlalchemy"]
		session = db.session
	return FormLayoutManager(session)


def _is_admin() -> bool:
	"""Return True when the currently authenticated user holds the Admin role."""
	if not current_user or not current_user.is_authenticated:
		return False
	try:
		return any(
			getattr(r, "name", None) == "Admin"
			for r in current_user.roles
		)
	except Exception:
		return False


# ---------------------------------------------------------------------------
# Editor UI — inline HTML (no external template file required)
# ---------------------------------------------------------------------------

_EDITOR_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Form Layout Editor — {{ view_name }} / {{ form_type }}</title>
  <link rel="stylesheet"
        href="https://maxcdn.bootstrapcdn.com/bootstrap/3.3.7/css/bootstrap.min.css">
  <link rel="stylesheet"
        href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/4.7.0/css/font-awesome.min.css">
  <style>
    body { padding: 20px; background: #f5f5f5; }
    h2   { margin-bottom: 20px; }

    /* Field card */
    .field-card {
      background: #fff;
      border: 1px solid #ddd;
      border-left: 4px solid #337ab7;
      border-radius: 3px;
      padding: 12px 14px;
      margin-bottom: 8px;
      cursor: grab;
      display: flex;
      align-items: flex-start;
      gap: 10px;
    }
    .field-card:active { cursor: grabbing; }
    .field-card.sortable-ghost { opacity: 0.4; }
    .field-card .drag-handle {
      color: #aaa;
      font-size: 18px;
      margin-top: 6px;
      flex-shrink: 0;
    }
    .field-card .field-body { flex: 1; }

    /* Conditional rule builder */
    .cond-block { background: #f9f9f9; border: 1px dashed #ccc; border-radius: 3px; padding: 10px; margin-top: 8px; }
    .cond-label { font-size: 12px; color: #777; margin-bottom: 6px; }

    /* Toolbar */
    .editor-toolbar { margin-bottom: 18px; }
    .editor-toolbar .btn + .btn { margin-left: 6px; }

    /* Field name badge */
    .field-name-badge {
      display: inline-block;
      font-family: monospace;
      font-size: 12px;
      background: #e8edf2;
      padding: 1px 6px;
      border-radius: 3px;
      margin-bottom: 6px;
      color: #555;
    }

    /* Toast */
    #toast {
      position: fixed;
      bottom: 24px;
      right: 24px;
      z-index: 9999;
      min-width: 220px;
      display: none;
    }
  </style>
</head>
<body>

<div class="container-fluid">
  <h2>
    <i class="fa fa-pencil-square-o"></i>
    Form Layout Editor
    <small>{{ view_name }} &mdash; {{ form_type }} form</small>
  </h2>

  <div class="editor-toolbar">
    <button class="btn btn-primary" onclick="saveLayout()">
      <i class="fa fa-save"></i> Save Layout
    </button>
    <button class="btn btn-default" onclick="if(confirm('Reset to default layout?')) resetLayout()">
      <i class="fa fa-undo"></i> Reset to Default
    </button>
    <a class="btn btn-default" href="javascript:history.back()">
      <i class="fa fa-arrow-left"></i> Back
    </a>
  </div>

  <div class="row">
    <div class="col-md-8">
      <div class="panel panel-default">
        <div class="panel-heading">
          <strong>Fields</strong>
          <span class="text-muted" style="font-size:12px; margin-left:8px;">
            Drag to reorder &mdash; unchecked fields are hidden from the form
          </span>
        </div>
        <div class="panel-body" style="padding: 12px;">
          <div id="field-list">
            {% for cfg in layout %}
            <div class="field-card" data-field="{{ cfg.field_name }}">
              <span class="drag-handle fa fa-bars"></span>
              <div class="field-body">

                <span class="field-name-badge">{{ cfg.field_name }}</span>

                <div class="row">
                  <div class="col-sm-5">
                    <div class="form-group" style="margin-bottom:6px;">
                      <label class="control-label" style="font-size:12px;">Label</label>
                      <input type="text"
                             class="form-control input-sm field-label"
                             value="{{ cfg.label | e }}">
                    </div>
                  </div>
                  <div class="col-sm-5">
                    <div class="form-group" style="margin-bottom:6px;">
                      <label class="control-label" style="font-size:12px;">Widget</label>
                      <select class="form-control input-sm field-widget">
                        {% for w in widgets %}
                        <option value="{{ w }}" {% if w == cfg.widget_type %}selected{% endif %}>{{ w }}</option>
                        {% endfor %}
                      </select>
                    </div>
                  </div>
                  <div class="col-sm-2">
                    <div class="form-group" style="margin-bottom:6px;">
                      <label class="control-label" style="font-size:12px;">Required</label><br>
                      <input type="checkbox"
                             class="field-required"
                             {% if cfg.required %}checked{% endif %}>
                    </div>
                  </div>
                </div>

                <div class="form-group" style="margin-bottom:6px;">
                  <label class="control-label" style="font-size:12px;">Help text</label>
                  <input type="text"
                         class="form-control input-sm field-help"
                         value="{{ cfg.help_text | e }}"
                         placeholder="Optional description shown below the field">
                </div>

                <!-- Conditional visibility rule -->
                <div class="cond-block">
                  <div class="cond-label">
                    <i class="fa fa-eye"></i>
                    Conditional visibility &mdash;
                    <em>Show this field only when another field has a specific value</em>
                  </div>
                  <div class="row">
                    <div class="col-sm-1" style="padding-top:6px;">
                      <label style="font-size:12px;">Enable</label>
                      <input type="checkbox"
                             class="cond-enable"
                             {% if cfg.visible_when %}checked{% endif %}
                             onchange="toggleCond(this)">
                    </div>
                    <div class="col-sm-11 cond-fields" style="{% if not cfg.visible_when %}display:none{% endif %}">
                      <div class="row">
                        <div class="col-sm-5">
                          <input type="text"
                                 class="form-control input-sm cond-field"
                                 placeholder="Watch field name"
                                 value="{{ (cfg.visible_when or {}).get('field', '') | e }}">
                        </div>
                        <div class="col-sm-1" style="padding-top:6px; text-align:center;">
                          <span class="text-muted">=</span>
                        </div>
                        <div class="col-sm-5">
                          <input type="text"
                                 class="form-control input-sm cond-value"
                                 placeholder="Expected value"
                                 value="{{ (cfg.visible_when or {}).get('equals', '') | e }}">
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
                <!-- /conditional -->

              </div><!-- /.field-body -->
            </div><!-- /.field-card -->
            {% endfor %}
          </div><!-- /#field-list -->
        </div>
      </div>
    </div><!-- /.col-md-8 -->

    <div class="col-md-4">
      <div class="panel panel-info">
        <div class="panel-heading"><strong>Tips</strong></div>
        <div class="panel-body" style="font-size:13px;">
          <ul style="padding-left:18px; margin:0;">
            <li>Drag the <i class="fa fa-bars"></i> handle to reorder fields.</li>
            <li>Uncheck <strong>Required</strong> to make a field optional.</li>
            <li>Use <strong>Conditional visibility</strong> to show a field only
                when another field equals a specific value
                (e.g. show <code>reason</code> when <code>status = "rejected"</code>).</li>
            <li>Widget selection changes the HTML input control rendered
                by pgappforge.</li>
            <li>Click <strong>Save Layout</strong> — changes take effect immediately
                for all users.</li>
            <li><strong>Reset to Default</strong> removes the saved layout and
                restores the view's original field order.</li>
          </ul>
        </div>
      </div>

      <div class="panel panel-default">
        <div class="panel-heading"><strong>Available Widgets</strong></div>
        <div class="panel-body" style="font-size:12px;">
          <ul style="padding-left:16px; margin:0;">
            {% for w in widgets %}
            <li><code>{{ w }}</code></li>
            {% endfor %}
          </ul>
        </div>
      </div>
    </div>
  </div><!-- /.row -->
</div><!-- /.container-fluid -->

<!-- Toast notification -->
<div id="toast" class="alert alert-success alert-dismissible" role="alert">
  <button type="button" class="close" onclick="document.getElementById('toast').style.display='none'">
    <span>&times;</span>
  </button>
  <span id="toast-msg"></span>
</div>

<!-- SortableJS from CDN -->
<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
<script>
  var VIEW_NAME   = {{ view_name | tojson }};
  var FORM_TYPE   = {{ form_type | tojson }};
  var SAVE_URL    = {{ save_url  | tojson }};
  var RESET_URL   = {{ reset_url | tojson }};

  // Initialise SortableJS on the field list
  Sortable.create(document.getElementById('field-list'), {
    handle: '.drag-handle',
    animation: 150,
    ghostClass: 'sortable-ghost'
  });

  function toggleCond(checkbox) {
    var card   = checkbox.closest('.field-card');
    var fields = card.querySelector('.cond-fields');
    fields.style.display = checkbox.checked ? '' : 'none';
  }

  function collectLayout() {
    var cards = document.querySelectorAll('#field-list .field-card');
    var layout = [];
    cards.forEach(function(card, idx) {
      var condEnable = card.querySelector('.cond-enable').checked;
      var condField  = card.querySelector('.cond-field').value.trim();
      var condValue  = card.querySelector('.cond-value').value.trim();

      var visibleWhen = null;
      if (condEnable && condField !== '') {
        visibleWhen = { field: condField, equals: condValue };
      }

      layout.push({
        field_name:   card.dataset.field,
        widget_type:  card.querySelector('.field-widget').value,
        label:        card.querySelector('.field-label').value,
        help_text:    card.querySelector('.field-help').value,
        required:     card.querySelector('.field-required').checked,
        order:        idx,
        visible_when: visibleWhen
      });
    });
    return layout;
  }

  function showToast(msg, type) {
    var toast = document.getElementById('toast');
    toast.className = 'alert alert-' + (type || 'success') + ' alert-dismissible';
    document.getElementById('toast-msg').textContent = msg;
    toast.style.display = 'block';
    setTimeout(function() { toast.style.display = 'none'; }, 3500);
  }

  function saveLayout() {
    var payload = {
      view_name: VIEW_NAME,
      form_type: FORM_TYPE,
      layout:    collectLayout()
    };

    fetch(SAVE_URL, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload)
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
        showToast('Layout saved — ' + data.fields + ' field(s) persisted.', 'success');
      } else {
        showToast('Error: ' + (data.error || 'unknown'), 'danger');
      }
    })
    .catch(function(err) {
      showToast('Network error: ' + err, 'danger');
    });
  }

  function resetLayout() {
    fetch(RESET_URL, { method: 'GET' })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
        showToast('Layout reset to defaults.', 'info');
        setTimeout(function() { window.location.reload(); }, 1200);
      } else {
        showToast('Error: ' + (data.error || 'unknown'), 'danger');
      }
    })
    .catch(function(err) {
      showToast('Network error: ' + err, 'danger');
    });
  }
</script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Modal snippet injected around the existing form HTML
# ---------------------------------------------------------------------------

_EDIT_BUTTON_TEMPLATE = """
<!-- pgappforge form-layout edit button (admin only) -->
<div style="text-align:right; margin-bottom:6px;">
  <button type="button"
          class="btn btn-default btn-xs"
          data-toggle="modal"
          data-target="#pgf-layout-modal-{view_name}-{form_type}"
          title="Edit form layout">
    <span class="glyphicon glyphicon-cog"></span> Edit Form
  </button>
</div>

<!-- Bootstrap 3 modal housing the iframe editor -->
<div class="modal fade"
     id="pgf-layout-modal-{view_name}-{form_type}"
     tabindex="-1"
     role="dialog"
     aria-labelledby="pgf-layout-modal-label-{view_name}-{form_type}">
  <div class="modal-dialog modal-lg" role="document">
    <div class="modal-content">
      <div class="modal-header">
        <button type="button" class="close" data-dismiss="modal" aria-label="Close">
          <span aria-hidden="true">&times;</span>
        </button>
        <h4 class="modal-title"
            id="pgf-layout-modal-label-{view_name}-{form_type}">
          Form Layout Editor &mdash; {view_name} / {form_type}
        </h4>
      </div>
      <div class="modal-body" style="padding:0;">
        <iframe src="{editor_url}"
                style="width:100%; height:72vh; border:none;"
                onload="this.style.opacity=1"
                style="opacity:0; transition:opacity .2s;">
        </iframe>
      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-default" data-dismiss="modal">Close</button>
      </div>
    </div>
  </div>
</div>

{form_html}
"""


# ---------------------------------------------------------------------------
# Public helper
# ---------------------------------------------------------------------------

def inject_edit_button(view_name: str, form_type: str, form_html: str) -> str:
	"""Wrap *form_html* with an admin-only Edit Form button + Bootstrap modal.

	The button is **completely omitted** for non-admin users so no
	information about the editor leaks into the DOM.

	Args:
		view_name:  Class name of the calling ModelView (e.g. ``"EmployeeView"``).
		form_type:  ``"add"`` or ``"edit"``.
		form_html:  The fully-rendered form HTML string.

	Returns:
		Original *form_html* unchanged for non-admins; wrapped HTML for admins.
	"""
	if not _is_admin():
		return form_html

	try:
		editor_url = url_for(
			"FormLayoutEditorView.editor",
			view_name=view_name,
			form_type=form_type,
		)
	except Exception:
		# If the view hasn't been registered yet, fall back gracefully.
		log.warning("FormLayoutEditorView not registered — edit button suppressed")
		return form_html

	return _EDIT_BUTTON_TEMPLATE.format(
		view_name=view_name,
		form_type=form_type,
		editor_url=editor_url,
		form_html=form_html,
	)


# ---------------------------------------------------------------------------
# FAB view
# ---------------------------------------------------------------------------

class FormLayoutEditorView(BaseView):
	"""Visual drag-and-drop form layout editor.

	Register it with AppBuilder once during application setup::

		appbuilder.add_view_no_menu(FormLayoutEditorView())

	Routes are mounted at ``/form-editor/`` by default (controlled by
	``route_base``).
	"""

	route_base = "/form-editor"
	default_view = "editor"

	# No menu entry — accessed only via inject_edit_button modal
	base_permissions = ["can_editor", "can_save", "can_reset"]

	# ------------------------------------------------------------------
	# Routes
	# ------------------------------------------------------------------

	@expose("/<string:view_name>/<string:form_type>", methods=["GET"])
	def editor(self, view_name: str, form_type: str):
		"""Render the inline editor UI for *(view_name, form_type)*.

		Access restricted to users with the Admin role.  Non-admins
		receive a 403 plain-text response so the modal iframe shows
		something sensible.
		"""
		if not _is_admin():
			from flask import Response
			return Response("Access denied — Admin role required.", status=403)

		if form_type not in ("add", "edit"):
			from flask import Response
			return Response("Invalid form_type — must be 'add' or 'edit'.", status=400)

		mgr = _get_manager()
		layout = mgr.get_layout(view_name, form_type)

		# If no saved layout exists, reflect the view's current field list
		if not layout:
			layout = _infer_layout_from_view(view_name, form_type)

		save_url = url_for("FormLayoutEditorView.save")
		reset_url = url_for(
			"FormLayoutEditorView.reset",
			view_name=view_name,
			form_type=form_type,
		)

		try:
			from jinja2 import Environment
			env = current_app.jinja_env
			tmpl = env.from_string(_EDITOR_TEMPLATE)
			html = tmpl.render(
				view_name=view_name,
				form_type=form_type,
				layout=layout,
				widgets=AVAILABLE_WIDGETS,
				save_url=save_url,
				reset_url=reset_url,
			)
		except Exception:
			log.exception("Error rendering layout editor template")
			from flask import Response
			return Response("Internal error rendering editor.", status=500)

		from flask import Response
		return Response(html, content_type="text/html; charset=utf-8")

	@expose("/save", methods=["POST"])
	def save(self):
		"""Persist the submitted layout config.

		Expects a JSON body::

			{
				"view_name": "EmployeeView",
				"form_type": "add",
				"layout":    [ { ...field config... }, ... ]
			}

		Returns JSON ``{"ok": true, "fields": <count>}`` on success or
		``{"ok": false, "error": "<message>"}`` on failure.
		"""
		if not _is_admin():
			return jsonify({"ok": False, "error": "Admin role required"}), 403

		try:
			body: dict[str, Any] = request.get_json(force=True, silent=True) or {}
			view_name: str = body.get("view_name", "").strip()
			form_type: str = body.get("form_type", "").strip()
			layout: list[dict[str, Any]] = body.get("layout", [])

			if not view_name:
				return jsonify({"ok": False, "error": "view_name is required"}), 400
			if form_type not in ("add", "edit"):
				return jsonify({"ok": False, "error": "form_type must be 'add' or 'edit'"}), 400
			if not isinstance(layout, list):
				return jsonify({"ok": False, "error": "layout must be a list"}), 400

			mgr = _get_manager()
			mgr.save_layout(view_name, form_type, layout)
			return jsonify({"ok": True, "fields": len(layout)})

		except Exception as exc:
			log.exception("Error saving layout")
			return jsonify({"ok": False, "error": str(exc)}), 500

	@expose("/reset/<string:view_name>/<string:form_type>", methods=["GET"])
	def reset(self, view_name: str, form_type: str):
		"""Delete the saved layout for *(view_name, form_type)*.

		Returns JSON ``{"ok": true}`` or ``{"ok": false, "error": "..."}``.
		"""
		if not _is_admin():
			return jsonify({"ok": False, "error": "Admin role required"}), 403

		try:
			mgr = _get_manager()
			mgr.reset_layout(view_name, form_type)
			return jsonify({"ok": True})
		except Exception as exc:
			log.exception("Error resetting layout for %s/%s", view_name, form_type)
			return jsonify({"ok": False, "error": str(exc)}), 500


# ---------------------------------------------------------------------------
# Layout inference (fallback when no saved config exists)
# ---------------------------------------------------------------------------

def _infer_layout_from_view(view_name: str, form_type: str) -> list[dict[str, Any]]:
	"""Best-effort: extract field names from the registered AppBuilder view.

	This is a read-only introspection step — it does not persist anything.
	Falls back to an empty list if the view or its form cannot be found.
	"""
	from pgappforge.forms.layout_manager import _default_field_config

	try:
		ab = current_app.appbuilder
		# AppBuilder keeps registered views in appbuilder.baseviews
		for view in ab.baseviews:
			if view.__class__.__name__ == view_name:
				form_attr = "add_form" if form_type == "add" else "edit_form"
				form_cls = getattr(view, form_attr, None)
				if form_cls is None:
					break
				try:
					form_instance = form_cls()
				except Exception:
					form_instance = form_cls.__new__(form_cls)

				fields = getattr(form_instance, "_fields", None) or {}
				return [
					_default_field_config(fname, idx)
					for idx, fname in enumerate(fields)
					if not fname.startswith("csrf")
				]
		return []
	except Exception:
		log.debug("Could not infer layout for %s/%s", view_name, form_type, exc_info=True)
		return []
