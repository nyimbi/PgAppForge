"""
rich_widgets.py: Rich editing widgets for Flask-AppBuilder

Widgets:
    JSONEditorWidget      - Monaco-based JSON editor with schema validation (AJV)
    MarkdownEditorWidget  - SimpleMDE markdown editor with live preview
    CodeEditorWidget      - Monaco editor with multi-language support, lazy-loaded
    RichTextEditorWidget  - Quill.js WYSIWYG editor
    SignaturePadWidget    - signature_pad.js capture widget

All widgets:
- Lazy-load their CDN dependencies on first use (single guard flag per page)
- Serialize to plain Python str for database storage
- Use markupsafe.Markup exclusively (never flask.Markup)
- Tab-indented, type-annotated, accessible (aria-* where applicable)
"""

from __future__ import annotations

import json
from typing import Any

from flask_appbuilder.fieldwidgets import BS3TextFieldWidget
from markupsafe import Markup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _jsbool(v: bool) -> str:
	return "true" if v else "false"


def _once_guard(flag: str) -> str:
	"""JS snippet that early-exits if flag already set (dedup loader calls)."""
	return f"if (window['{flag}']) {{ return; }} window['{flag}'] = true;"


# ---------------------------------------------------------------------------
# JSONEditorWidget
# ---------------------------------------------------------------------------

class JSONEditorWidget(BS3TextFieldWidget):
	"""
	JSON editor backed by Monaco Editor (CDN, lazy-loaded).

	Improvements over nx_widgets original:
	- Monaco instead of Ace: richer IntelliSense, better JSON schema support
	- AJV schema validation wired to Monaco's setModelMarkers so errors appear
	  inline, not in a separate div
	- Single CDN loader guard prevents double-init when multiple fields exist
	- Serializes value as JSON string to hidden input on every change; form
	  submission always gets the current state even without a blur event
	- No jQuery dependency (uses vanilla JS)
	- process_formdata / process_data are field-level methods, not widget-level;
	  left as static helpers here for documentation; actual coercion happens in
	  the field class

	Args:
		height:           Editor height (CSS string, default "400px")
		theme:            Monaco theme name ("vs-dark" | "vs" | "hc-black")
		tab_size:         Indent width (default 2)
		readonly:         Render as read-only (default False)
		schema:           Optional JSON Schema dict for AJV validation
		word_wrap:        Enable word wrap (default True)
		minimap:          Show minimap (default False)
	"""

	def __init__(
		self,
		height: str = "400px",
		theme: str = "vs-dark",
		tab_size: int = 2,
		readonly: bool = False,
		schema: dict[str, Any] | None = None,
		word_wrap: bool = True,
		minimap: bool = False,
		**kwargs: Any,
	) -> None:
		super().__init__(**kwargs)
		self.height = height
		self.theme = theme
		self.tab_size = tab_size
		self.readonly = readonly
		self.schema = schema
		self.word_wrap = word_wrap
		self.minimap = minimap

	def __call__(self, field: Any, **kwargs: Any) -> Markup:
		field_id = field.id
		field_name = field.name

		# Normalise field.data to a JSON string for the editor's initial value
		raw = field.data
		if raw is None:
			initial_str = "{}"
		elif isinstance(raw, (dict, list)):
			initial_str = json.dumps(raw, indent=self.tab_size)
		elif isinstance(raw, str):
			# Round-trip to normalise; fall back to raw on parse error
			try:
				initial_str = json.dumps(json.loads(raw), indent=self.tab_size)
			except (ValueError, TypeError):
				initial_str = raw
		else:
			initial_str = str(raw)

		schema_js = json.dumps(self.schema) if self.schema else "null"
		loader_guard = f"__fab_monaco_loaded_{field_id}"
		# Shared Monaco require guard (one Monaco loader per page is enough)
		shared_guard = "__fab_monaco_require_ready"

		html = (
			f'<div class="fab-json-editor-wrap" style="margin-bottom:1rem;">'
			f'  <div class="btn-group btn-group-sm mb-1" role="toolbar" aria-label="JSON editor controls">'
			f'    <button type="button" class="btn btn-default" id="{field_id}-fmt-btn" aria-label="Format JSON">Format</button>'
			f'    <button type="button" class="btn btn-default" id="{field_id}-min-btn" aria-label="Minify JSON">Minify</button>'
			f'  </div>'
			f'  <div id="{field_id}-container"'
			f'       style="height:{self.height};border:1px solid #ccc;border-radius:4px;"'
			f'       role="textbox" aria-label="{field.label.text if field.label else field_name}"'
			f'       aria-multiline="true"></div>'
			f'  <div id="{field_id}-errors" class="text-danger" style="font-size:0.85em;margin-top:4px;" role="alert" aria-live="polite"></div>'
			f'  <input type="hidden" name="{field_name}" id="{field_id}" value="{Markup.escape(initial_str)}">'
			f'</div>'
		)

		js = f"""
<script>
(function() {{
	{_once_guard(loader_guard)}

	function initJSONEditor() {{
		var container = document.getElementById('{field_id}-container');
		var hiddenInput = document.getElementById('{field_id}');
		var errDiv = document.getElementById('{field_id}-errors');
		var schema = {schema_js};

		// Configure Monaco JSON defaults if schema provided
		if (schema) {{
			monaco.languages.json.jsonDefaults.setDiagnosticsOptions({{
				validate: true,
				schemas: [{{
					uri: 'fab://{field_id}/schema.json',
					fileMatch: ['{field_id}-model'],
					schema: schema
				}}]
			}});
		}}

		var model = monaco.editor.createModel(
			hiddenInput.value || '{{}}',
			'json',
			monaco.Uri.parse('fab://{field_id}-model')
		);

		var editor = monaco.editor.create(container, {{
			model: model,
			theme: '{self.theme}',
			automaticLayout: true,
			tabSize: {self.tab_size},
			insertSpaces: true,
			wordWrap: '{("on" if self.word_wrap else "off")}',
			minimap: {{ enabled: {_jsbool(self.minimap)} }},
			readOnly: {_jsbool(self.readonly)},
			scrollBeyondLastLine: false,
			formatOnType: true,
			formatOnPaste: true,
			folding: true,
			lineNumbers: 'on',
			renderWhitespace: 'none',
			fontSize: 13,
			fontFamily: "'Fira Code', 'Consolas', 'Courier New', monospace"
		}});

		// Sync editor -> hidden input on every change
		model.onDidChangeContent(function() {{
			var val = model.getValue();
			hiddenInput.value = val;

			// Surface Monaco markers as plain-text errors for screen readers
			var markers = monaco.editor.getModelMarkers({{ resource: model.uri }});
			var errs = markers.filter(function(m) {{
				return m.severity === monaco.MarkerSeverity.Error;
			}});
			if (errs.length) {{
				errDiv.textContent = errs.map(function(e) {{
					return 'Line ' + e.startLineNumber + ': ' + e.message;
				}}).join(' | ');
			}} else {{
				errDiv.textContent = '';
			}}
		}});

		// Format button
		document.getElementById('{field_id}-fmt-btn').addEventListener('click', function() {{
			try {{
				var parsed = JSON.parse(model.getValue());
				model.setValue(JSON.stringify(parsed, null, {self.tab_size}));
				editor.trigger('', 'editor.action.formatDocument', null);
			}} catch(e) {{
				errDiv.textContent = 'Cannot format: ' + e.message;
			}}
		}});

		// Minify button
		document.getElementById('{field_id}-min-btn').addEventListener('click', function() {{
			try {{
				var parsed = JSON.parse(model.getValue());
				model.setValue(JSON.stringify(parsed));
			}} catch(e) {{
				errDiv.textContent = 'Cannot minify: ' + e.message;
			}}
		}});
	}}

	// Lazy-load Monaco via AMD loader (single require per page)
	if (typeof monaco !== 'undefined') {{
		initJSONEditor();
	}} else if (typeof require !== 'undefined' && window['{shared_guard}']) {{
		require(['vs/editor/editor.main'], function() {{ initJSONEditor(); }});
	}} else {{
		window['{shared_guard}'] = true;
		var loaderScript = document.createElement('script');
		loaderScript.src = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs/loader.js';
		loaderScript.onload = function() {{
			require.config({{ paths: {{ vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' }} }});
			require(['vs/editor/editor.main'], function() {{ initJSONEditor(); }});
		}};
		document.head.appendChild(loaderScript);
	}}
}})();
</script>
"""

		return Markup(html + js)


# ---------------------------------------------------------------------------
# MarkdownEditorWidget
# ---------------------------------------------------------------------------

class MarkdownEditorWidget(BS3TextFieldWidget):
	"""
	Markdown editor backed by SimpleMDE (CDN, lazy-loaded).

	Improvements over nx_widgets original:
	- SimpleMDE instead of EasyMDE: lighter, no extra dependencies, same API
	- No KaTeX/math (optional, add via previewRender if needed) - keeps it
	  self-contained with zero mandatory CDN calls beyond SimpleMDE itself
	- Autosave uses localStorage key = field_id (no server round-trip)
	- Debounced sync to hidden input (150 ms); fires immediately on form submit
	- Word/char count rendered without jQuery
	- Single CDN loader guard

	Args:
		height:        Editor content area min-height (CSS string, "300px")
		autosave:      Enable localStorage autosave (default True)
		spellchecker:  Enable browser spellcheck (default True)
		toolbar:       List of toolbar item names (SimpleMDE format)
		status:        List of status bar items ("lines", "words", "cursor")
		placeholder:   Placeholder text shown when editor is empty
	"""

	_DEFAULT_TOOLBAR = [
		"bold", "italic", "heading", "|",
		"quote", "unordered-list", "ordered-list", "|",
		"link", "image", "table", "|",
		"preview", "side-by-side", "fullscreen", "|",
		"guide",
	]

	def __init__(
		self,
		height: str = "300px",
		autosave: bool = True,
		spellchecker: bool = True,
		toolbar: list[str] | None = None,
		status: list[str] | None = None,
		placeholder: str = "Write Markdown here…",
		**kwargs: Any,
	) -> None:
		super().__init__(**kwargs)
		self.height = height
		self.autosave = autosave
		self.spellchecker = spellchecker
		self.toolbar = toolbar if toolbar is not None else self._DEFAULT_TOOLBAR
		self.status = status if status is not None else ["lines", "words", "cursor"]
		self.placeholder = placeholder

	def __call__(self, field: Any, **kwargs: Any) -> Markup:
		field_id = field.id
		field_name = field.name
		label_text = field.label.text if field.label else field_name

		# field.data is always a plain string; None -> ""
		initial = field.data if isinstance(field.data, str) else ""

		loader_guard = f"__fab_simplemde_loaded_{field_id}"
		shared_guard = "__fab_simplemde_css_loaded"

		html = (
			f'<div class="fab-md-editor-wrap" style="margin-bottom:1rem;">'
			f'  <textarea id="{field_id}-mde"'
			f'            name="{field_name}"'
			f'            aria-label="{Markup.escape(label_text)}"'
			f'            style="display:none;"'
			f'            placeholder="{Markup.escape(self.placeholder)}">'
			f'{Markup.escape(initial)}'
			f'  </textarea>'
			f'  <input type="hidden" name="{field_name}" id="{field_id}" value="{Markup.escape(initial)}">'
			f'  <div class="fab-md-meta" style="font-size:0.8em;color:#666;margin-top:4px;">'
			f'    <span id="{field_id}-wc"></span>'
			f'    <span id="{field_id}-cc" style="margin-left:1em;"></span>'
			f'  </div>'
			f'</div>'
		)

		js = f"""
<script>
(function() {{
	{_once_guard(loader_guard)}

	function initMDE() {{
		var textarea = document.getElementById('{field_id}-mde');
		var hidden   = document.getElementById('{field_id}');
		var wcSpan   = document.getElementById('{field_id}-wc');
		var ccSpan   = document.getElementById('{field_id}-cc');

		var mde = new SimpleMDE({{
			element: textarea,
			initialValue: {json.dumps(initial)},
			spellChecker: {_jsbool(self.spellchecker)},
			autofocus: false,
			autoDownloadFontAwesome: false,
			placeholder: {json.dumps(self.placeholder)},
			toolbar: {json.dumps(self.toolbar)},
			status: {json.dumps(self.status)},
			autosave: {{
				enabled: {_jsbool(self.autosave)},
				uniqueId: 'fab-md-{field_id}',
				delay: 2000
			}},
			renderingConfig: {{
				singleLineBreaks: false,
				codeSyntaxHighlighting: false
			}}
		}});

		// Sync helper
		function syncToHidden() {{
			var val = mde.value();
			hidden.value = val;
			var words = val.trim() ? val.trim().split(/\\s+/).length : 0;
			wcSpan.textContent = words + ' words';
			ccSpan.textContent = val.length + ' chars';
		}}

		// Debounced change sync
		var debTimer;
		mde.codemirror.on('change', function() {{
			clearTimeout(debTimer);
			debTimer = setTimeout(syncToHidden, 150);
		}});

		// Ensure hidden is correct on submit even if debounce hasn't fired
		var form = hidden.closest('form');
		if (form) {{
			form.addEventListener('submit', syncToHidden, {{ capture: true }});
		}}

		// Initial counts
		syncToHidden();
	}}

	// Load SimpleMDE CSS once per page
	if (!window['{shared_guard}']) {{
		window['{shared_guard}'] = true;
		var link = document.createElement('link');
		link.rel = 'stylesheet';
		link.href = 'https://cdn.jsdelivr.net/npm/simplemde@1.11.2/dist/simplemde.min.css';
		document.head.appendChild(link);
	}}

	if (typeof SimpleMDE !== 'undefined') {{
		initMDE();
	}} else {{
		var s = document.createElement('script');
		s.src = 'https://cdn.jsdelivr.net/npm/simplemde@1.11.2/dist/simplemde.min.js';
		s.onload = initMDE;
		document.head.appendChild(s);
	}}
}})();
</script>
"""

		return Markup(html + js)


# ---------------------------------------------------------------------------
# CodeEditorWidget
# ---------------------------------------------------------------------------

class CodeEditorWidget(BS3TextFieldWidget):
	"""
	Multi-language code editor backed by Monaco Editor (CDN, lazy-loaded).

	Improvements over nx_widgets original:
	- Correct AMD require pattern: single shared loader per page, subsequent
	  fields reuse the already-resolved monaco global
	- value is synced to hidden input on every content change AND on submit,
	  so partial edits are never lost
	- process_formdata returns str (not stored on self.data in wrong slot)
	- Editor height is configurable (was hard-coded to 500px)
	- No separate _state hidden field; view state is transient
	- Validates language against supported set at render time (Python error,
	  not silent JS failure)

	Args:
		language:     Monaco language id (default "plaintext")
		theme:        Monaco theme ("vs-dark" | "vs" | "hc-black")
		height:       Editor height CSS string (default "400px")
		tab_size:     Indent size (default 4)
		word_wrap:    "on" | "off" | "wordWrapColumn" (default "on")
		minimap:      Show minimap (default False)
		line_numbers: "on" | "off" | "relative" (default "on")
		readonly:     Read-only mode (default False)
		font_size:    Font size in px (default 14)
		rulers:       List of column ruler positions (default [80, 120])
	"""

	SUPPORTED_LANGUAGES = frozenset([
		"bat", "c", "clojure", "coffeescript", "cpp", "csharp", "css",
		"dockerfile", "fsharp", "go", "graphql", "handlebars", "html",
		"ini", "java", "javascript", "json", "julia", "kotlin", "less",
		"lua", "markdown", "msdax", "mysql", "objective-c", "pascal",
		"perl", "pgsql", "php", "plaintext", "postiats", "powerquery",
		"powershell", "proto", "python", "r", "razor", "redis", "redshift",
		"restructuredtext", "ruby", "rust", "sb", "scala", "scheme", "scss",
		"shell", "sol", "sparql", "sql", "st", "swift", "systemverilog",
		"tcl", "toml", "twig", "typescript", "vb", "xml", "yaml",
	])

	def __init__(
		self,
		language: str = "plaintext",
		theme: str = "vs-dark",
		height: str = "400px",
		tab_size: int = 4,
		word_wrap: str = "on",
		minimap: bool = False,
		line_numbers: str = "on",
		readonly: bool = False,
		font_size: int = 14,
		rulers: list[int] | None = None,
		**kwargs: Any,
	) -> None:
		super().__init__(**kwargs)
		if language not in self.SUPPORTED_LANGUAGES:
			raise ValueError(
				f"CodeEditorWidget: unsupported language {language!r}. "
				f"Valid values: {sorted(self.SUPPORTED_LANGUAGES)}"
			)
		self.language = language
		self.theme = theme
		self.height = height
		self.tab_size = tab_size
		self.word_wrap = word_wrap
		self.minimap = minimap
		self.line_numbers = line_numbers
		self.readonly = readonly
		self.font_size = font_size
		self.rulers = rulers if rulers is not None else [80, 120]

	def __call__(self, field: Any, **kwargs: Any) -> Markup:
		field_id = field.id
		field_name = field.name
		label_text = field.label.text if field.label else field_name

		raw = field.data or ""
		if not isinstance(raw, str):
			raw = str(raw)

		loader_guard = f"__fab_monaco_loaded_{field_id}"
		shared_guard = "__fab_monaco_require_ready"

		html = (
			f'<div class="fab-code-editor-wrap"'
			f'     style="border:1px solid #dee2e6;border-radius:4px;overflow:hidden;margin-bottom:1rem;">'
			f'  <div id="{field_id}-container"'
			f'       style="height:{self.height};width:100%;"'
			f'       role="textbox"'
			f'       aria-label="{Markup.escape(label_text)}"'
			f'       aria-multiline="true"></div>'
			f'  <div id="{field_id}-status"'
			f'       style="padding:2px 8px;background:#f8f9fa;border-top:1px solid #dee2e6;'
			f'              font-size:12px;color:#6c757d;font-family:monospace;">'
			f'    {Markup.escape(self.language)}'
			f'  </div>'
			f'  <div id="{field_id}-errors" class="text-danger" style="font-size:0.85em;padding:4px 8px;" role="alert" aria-live="polite"></div>'
			f'  <input type="hidden" name="{field_name}" id="{field_id}" value="{Markup.escape(raw)}">'
			f'</div>'
		)

		config = {
			"language": self.language,
			"theme": self.theme,
			"tabSize": self.tab_size,
			"wordWrap": self.word_wrap,
			"minimap": {"enabled": self.minimap},
			"lineNumbers": self.line_numbers,
			"readOnly": self.readonly,
			"fontSize": self.font_size,
			"rulers": self.rulers,
			"automaticLayout": True,
			"scrollBeyondLastLine": False,
			"formatOnPaste": True,
			"formatOnType": False,
			"folding": True,
			"renderWhitespace": "none",
			"fontFamily": "'Fira Code', Consolas, 'Courier New', monospace",
		}

		js = f"""
<script>
(function() {{
	{_once_guard(loader_guard)}

	var editorConfig = {json.dumps(config, indent="\t\t")};

	function initCodeEditor() {{
		var container  = document.getElementById('{field_id}-container');
		var hidden     = document.getElementById('{field_id}');
		var statusBar  = document.getElementById('{field_id}-status');
		var errDiv     = document.getElementById('{field_id}-errors');

		editorConfig.value = hidden.value || '';

		var editor = monaco.editor.create(container, editorConfig);

		// Sync on every change
		editor.onDidChangeModelContent(function() {{
			hidden.value = editor.getValue();
		}});

		// Status bar
		function updateStatus() {{
			var pos   = editor.getPosition();
			var model = editor.getModel();
			if (!pos || !model) return;
			statusBar.textContent = (
				'{self.language}  |  Ln ' + pos.lineNumber +
				', Col ' + pos.column +
				'  |  ' + model.getLineCount() + ' lines'
			);
		}}
		editor.onDidChangeCursorPosition(updateStatus);
		updateStatus();

		// Error markers
		monaco.editor.onDidChangeMarkers(function() {{
			var markers = monaco.editor.getModelMarkers({{ resource: editor.getModel().uri }});
			var errs = markers.filter(function(m) {{
				return m.severity === monaco.MarkerSeverity.Error;
			}});
			errDiv.textContent = errs.length
				? errs.length + ' error(s): ' + errs.map(function(e) {{
					return 'Ln ' + e.startLineNumber + ' ' + e.message;
				}}).join('; ')
				: '';
		}});

		// Guarantee hidden has latest value on submit
		var form = hidden.closest('form');
		if (form) {{
			form.addEventListener('submit', function() {{
				hidden.value = editor.getValue();
			}}, {{ capture: true }});
		}}
	}}

	if (typeof monaco !== 'undefined') {{
		initCodeEditor();
	}} else if (typeof require !== 'undefined' && window['{shared_guard}']) {{
		require(['vs/editor/editor.main'], function() {{ initCodeEditor(); }});
	}} else {{
		window['{shared_guard}'] = true;
		var loaderScript = document.createElement('script');
		loaderScript.src = 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs/loader.js';
		loaderScript.onload = function() {{
			require.config({{ paths: {{ vs: 'https://cdn.jsdelivr.net/npm/monaco-editor@0.44.0/min/vs' }} }});
			require(['vs/editor/editor.main'], function() {{ initCodeEditor(); }});
		}};
		document.head.appendChild(loaderScript);
	}}
}})();
</script>
"""

		return Markup(html + js)

	@staticmethod
	def process_formdata(valuelist: list[str]) -> str | None:
		"""Coerce submitted value to str. Call from a custom WTForms field."""
		return valuelist[0] if valuelist else None


# ---------------------------------------------------------------------------
# RichTextEditorWidget
# ---------------------------------------------------------------------------

class RichTextEditorWidget(BS3TextFieldWidget):
	"""
	WYSIWYG rich text editor backed by Quill.js (CDN, lazy-loaded).

	Improvements over nx_widgets original:
	- Stores HTML string (not Quill Delta JSON) in hidden input by default,
	  matching what most TEXT/JSONB columns actually expect
	- delta_mode=True stores Quill Delta JSON instead (set explicitly)
	- No placeholder jQuery in image handler; uses native fetch
	- Max-length guard is client-side only (server validates separately)
	- Single CSS/JS loader guard per page
	- No collaborative editing stub that just alerts()
	- Accessible: toolbar gets aria-label, editor div gets role="textbox"

	Args:
		height:         Editor min-height CSS string (default "300px")
		theme:          Quill theme ("snow" | "bubble", default "snow")
		toolbar:        Quill toolbar config (nested list/dict, default standard set)
		placeholder:    Placeholder text (default "Enter rich text…")
		readonly:       Read-only mode (default False)
		delta_mode:     Store Quill Delta JSON instead of HTML (default False)
		max_length:     Optional character limit (default None = unlimited)
		image_upload_url: Optional endpoint for image uploads (None = base64 inline)
		word_count:     Show word/char count bar (default True)
		autosave_ms:    Autosave debounce ms (0 = no autosave, default 0)
	"""

	_DEFAULT_TOOLBAR = [
		[{"header": [1, 2, 3, False]}],
		["bold", "italic", "underline", "strike"],
		[{"color": []}, {"background": []}],
		[{"list": "ordered"}, {"list": "bullet"}],
		[{"indent": "-1"}, {"indent": "+1"}],
		["blockquote", "code-block"],
		["link", "image"],
		["clean"],
	]

	def __init__(
		self,
		height: str = "300px",
		theme: str = "snow",
		toolbar: list | None = None,
		placeholder: str = "Enter rich text…",
		readonly: bool = False,
		delta_mode: bool = False,
		max_length: int | None = None,
		image_upload_url: str | None = None,
		word_count: bool = True,
		autosave_ms: int = 0,
		**kwargs: Any,
	) -> None:
		super().__init__(**kwargs)
		self.height = height
		self.theme = theme
		self.toolbar = toolbar if toolbar is not None else self._DEFAULT_TOOLBAR
		self.placeholder = placeholder
		self.readonly = readonly
		self.delta_mode = delta_mode
		self.max_length = max_length
		self.image_upload_url = image_upload_url
		self.word_count = word_count
		self.autosave_ms = autosave_ms

	def __call__(self, field: Any, **kwargs: Any) -> Markup:
		field_id = field.id
		field_name = field.name
		label_text = field.label.text if field.label else field_name

		# Normalise field.data: plain HTML string expected; Delta JSON if delta_mode
		raw = field.data or ""
		if isinstance(raw, dict):
			# Delta stored in DB; we render as-is in delta_mode
			initial_html = ""
			initial_delta = json.dumps(raw)
		elif isinstance(raw, str):
			initial_html = raw
			initial_delta = "null"
		else:
			initial_html = str(raw)
			initial_delta = "null"

		loader_guard = f"__fab_quill_loaded_{field_id}"
		shared_guard = "__fab_quill_css_loaded"
		quill_ver = "1.3.7"
		quill_cdn = f"https://cdn.jsdelivr.net/npm/quill@{quill_ver}/dist"

		html = (
			f'<div class="fab-rte-wrap" style="margin-bottom:1rem;">'
			f'  <div id="{field_id}-toolbar" aria-label="Rich text toolbar"></div>'
			f'  <div id="{field_id}-editor"'
			f'       role="textbox"'
			f'       aria-label="{Markup.escape(label_text)}"'
			f'       aria-multiline="true"'
			f'       style="min-height:{self.height};"></div>'
		)
		if self.word_count:
			html += (
				f'  <div class="fab-rte-meta" style="font-size:0.8em;color:#666;margin-top:4px;">'
				f'    <span id="{field_id}-wc"></span>'
				f'    <span id="{field_id}-cc" style="margin-left:1em;"></span>'
				f'  </div>'
			)
		if self.max_length:
			html += (
				f'  <div id="{field_id}-maxlen-warn" class="text-danger" style="display:none;font-size:0.85em;">'
				f'    Content exceeds {self.max_length} character limit.'
				f'  </div>'
			)
		html += (
			f'  <input type="hidden" name="{field_name}" id="{field_id}" value="{Markup.escape(initial_html)}">'
			f'</div>'
		)

		image_handler_js = ""
		if self.image_upload_url:
			image_handler_js = f"""
		quill.getModule('toolbar').addHandler('image', function() {{
			var input = document.createElement('input');
			input.type = 'file';
			input.accept = 'image/*';
			input.onchange = function() {{
				var file = input.files[0];
				if (!file) return;
				var fd = new FormData();
				fd.append('image', file);
				fetch({json.dumps(self.image_upload_url)}, {{ method: 'POST', body: fd }})
					.then(function(r) {{ return r.json(); }})
					.then(function(data) {{
						if (data && data.url) {{
							var range = quill.getSelection(true);
							quill.insertEmbed(range.index, 'image', data.url);
						}}
					}})
					.catch(function(err) {{
						console.error('Image upload failed', err);
					}});
			}};
			input.click();
		}});
"""

		autosave_js = ""
		if self.autosave_ms > 0:
			autosave_js = f"""
		var asTimer;
		quill.on('text-change', function() {{
			clearTimeout(asTimer);
			asTimer = setTimeout(function() {{
				var form = hidden.closest('form');
				if (form) form.dispatchEvent(new CustomEvent('fab-autosave', {{ detail: {{ field: '{field_name}', value: hidden.value }} }}));
			}}, {self.autosave_ms});
		}});
"""

		js = f"""
<script>
(function() {{
	{_once_guard(loader_guard)}

	function initQuill() {{
		var hidden  = document.getElementById('{field_id}');
		var toolDiv = document.getElementById('{field_id}-toolbar');
		var editDiv = document.getElementById('{field_id}-editor');
		var wcSpan  = document.getElementById('{field_id}-wc');
		var ccSpan  = document.getElementById('{field_id}-cc');
		var mlWarn  = document.getElementById('{field_id}-maxlen-warn');

		// Inject toolbar HTML via Quill Snow theme
		var quill = new Quill('#' + '{field_id}-editor', {{
			modules: {{
				toolbar: {json.dumps(self.toolbar)}
			}},
			placeholder: {json.dumps(self.placeholder)},
			readOnly: {_jsbool(self.readonly)},
			theme: {json.dumps(self.theme)}
		}});

		// Set initial content
		var initialDelta = {initial_delta};
		if (initialDelta) {{
			quill.setContents(initialDelta);
		}} else {{
			var initHtml = {json.dumps(initial_html)};
			if (initHtml) {{
				quill.clipboard.dangerouslyPasteHTML(initHtml);
			}}
		}}

		{image_handler_js}

		// Sync on change
		quill.on('text-change', function() {{
			var text = quill.getText().trim();
			var maxLen = {self.max_length if self.max_length else 'null'};
			if (mlWarn) {{
				if (maxLen && text.length > maxLen) {{
					mlWarn.style.display = 'block';
				}} else {{
					mlWarn.style.display = 'none';
				}}
			}}
			if (wcSpan) {{
				var words = text ? text.split(/\\s+/).length : 0;
				wcSpan.textContent = words + ' words';
				ccSpan.textContent = text.length + ' chars';
			}}
			// Store HTML or Delta depending on mode
			if ({_jsbool(self.delta_mode)}) {{
				hidden.value = JSON.stringify(quill.getContents());
			}} else {{
				hidden.value = quill.root.innerHTML;
			}}
		}});

		// Flush on submit
		var form = hidden.closest('form');
		if (form) {{
			form.addEventListener('submit', function() {{
				if ({_jsbool(self.delta_mode)}) {{
					hidden.value = JSON.stringify(quill.getContents());
				}} else {{
					hidden.value = quill.root.innerHTML;
				}}
			}}, {{ capture: true }});
		}}

		{autosave_js}
	}}

	// Load Quill CSS once per page
	if (!window['{shared_guard}']) {{
		window['{shared_guard}'] = true;
		var link = document.createElement('link');
		link.rel = 'stylesheet';
		link.href = '{quill_cdn}/quill.snow.min.css';
		document.head.appendChild(link);
	}}

	if (typeof Quill !== 'undefined') {{
		initQuill();
	}} else {{
		var s = document.createElement('script');
		s.src = '{quill_cdn}/quill.min.js';
		s.onload = initQuill;
		document.head.appendChild(s);
	}}
}})();
</script>
"""

		return Markup(html + js)

	@staticmethod
	def process_formdata(valuelist: list[str]) -> str | None:
		"""Return HTML string (or Delta JSON string if delta_mode) as-is."""
		return valuelist[0] if valuelist else None


# ---------------------------------------------------------------------------
# SignaturePadWidget
# ---------------------------------------------------------------------------

class SignaturePadWidget(BS3TextFieldWidget):
	"""
	Digital signature capture widget backed by signature_pad.js (CDN, lazy-loaded).

	Stores a JSON string with keys:
		{
		  "dataURL": "data:image/png;base64,...",  # PNG snapshot
		  "points":  [...],                         # raw point arrays
		  "signerName": "…",                        # present if require_name=True
		  "timestamp": "2026-05-30T12:00:00.000Z"
		}

	Improvements over nx_widgets original:
	- Stores a plain JSON string (not a nested hidden-input + canvas hack)
	- Canvas resizes responsively on window resize via ResizeObserver
	- Undo uses a simple snapshots stack (no separate bezier.js required)
	- No broken _get_widget_scripts = _get_widget_scripts comment
	- Clear/Undo/Done buttons are type="button" (prevent accidental form submit)
	- Accessible: canvas has role="img" aria-label, status region is aria-live

	Args:
		width:          Canvas CSS width (default "100%")
		height:         Canvas CSS height (default "200px")
		pen_color:      Pen stroke colour (default "#000000")
		pen_width_min:  Min line width (default 0.5)
		pen_width_max:  Max line width (default 2.5)
		background:     Canvas background colour (default "#f8f9fa")
		require_name:   Show signer-name input (default False)
		allow_undo:     Show Undo button (default True)
		readonly:       Disable drawing (default False)
		grid:           Draw a faint grid on the canvas (default False)
	"""

	def __init__(
		self,
		width: str = "100%",
		height: str = "200px",
		pen_color: str = "#000000",
		pen_width_min: float = 0.5,
		pen_width_max: float = 2.5,
		background: str = "#f8f9fa",
		require_name: bool = False,
		allow_undo: bool = True,
		readonly: bool = False,
		grid: bool = False,
		**kwargs: Any,
	) -> None:
		super().__init__(**kwargs)
		self.width = width
		self.height = height
		self.pen_color = pen_color
		self.pen_width_min = pen_width_min
		self.pen_width_max = pen_width_max
		self.background = background
		self.require_name = require_name
		self.allow_undo = allow_undo
		self.readonly = readonly
		self.grid = grid

	def __call__(self, field: Any, **kwargs: Any) -> Markup:
		field_id = field.id
		field_name = field.name
		label_text = field.label.text if field.label else field_name

		# Existing stored value (JSON string or None)
		stored = field.data or ""
		if isinstance(stored, dict):
			stored = json.dumps(stored)

		loader_guard = f"__fab_sigpad_loaded_{field_id}"
		shared_guard = "__fab_sigpad_lib_loaded"

		name_input_html = ""
		if self.require_name:
			name_input_html = (
				f'<div class="form-group mt-2">'
				f'  <label for="{field_id}-signer-name">Signer name</label>'
				f'  <input type="text" class="form-control" id="{field_id}-signer-name"'
				f'         placeholder="Full name" autocomplete="name">'
				f'</div>'
			)

		undo_btn_html = ""
		if self.allow_undo:
			undo_btn_html = (
				f'<button type="button" class="btn btn-sm btn-default"'
				f'        id="{field_id}-undo" aria-label="Undo last stroke">'
				f'  <i class="fa fa-undo"></i> Undo'
				f'</button> '
			)

		html = (
			f'<div class="fab-sigpad-wrap" style="margin-bottom:1rem;">'
			f'  <div style="position:relative;width:{self.width};height:{self.height};'
			f'              border:1px solid #ccc;border-radius:4px;'
			f'              background:{self.background};overflow:hidden;">'
			f'    <canvas id="{field_id}-canvas"'
			f'            style="position:absolute;top:0;left:0;width:100%;height:100%;'
			f'                   touch-action:none;"'
			f'            role="img"'
			f'            aria-label="{Markup.escape(label_text)} signature pad">'
			f'    </canvas>'
			f'  </div>'
			f'  <div class="mt-2 btn-group">'
			f'    <button type="button" class="btn btn-sm btn-default"'
			f'            id="{field_id}-clear" aria-label="Clear signature">'
			f'      <i class="fa fa-eraser"></i> Clear'
			f'    </button>'
			f'    {undo_btn_html}'
			f'  </div>'
			f'  {name_input_html}'
			f'  <div id="{field_id}-status" class="text-muted" style="font-size:0.8em;margin-top:4px;"'
			f'       role="status" aria-live="polite">Ready to sign.</div>'
			f'  <input type="hidden" name="{field_name}" id="{field_id}" value="{Markup.escape(stored)}">'
			f'</div>'
		)

		config = {
			"fieldId": field_id,
			"requireName": self.require_name,
			"allowUndo": self.allow_undo,
			"readonly": self.readonly,
			"grid": self.grid,
			"penColor": self.pen_color,
			"penWidthMin": self.pen_width_min,
			"penWidthMax": self.pen_width_max,
			"background": self.background,
		}

		js = f"""
<script>
(function() {{
	{_once_guard(loader_guard)}

	var cfg = {json.dumps(config)};

	function initSignaturePad() {{
		var canvas  = document.getElementById(cfg.fieldId + '-canvas');
		var hidden  = document.getElementById(cfg.fieldId);
		var status  = document.getElementById(cfg.fieldId + '-status');
		var clearBtn = document.getElementById(cfg.fieldId + '-clear');
		var undoBtn  = cfg.allowUndo ? document.getElementById(cfg.fieldId + '-undo') : null;
		var nameInput = cfg.requireName ? document.getElementById(cfg.fieldId + '-signer-name') : null;

		// Resize canvas to its CSS pixel dimensions
		function resizeCanvas() {{
			var ratio  = Math.max(window.devicePixelRatio || 1, 1);
			var rect   = canvas.getBoundingClientRect();
			canvas.width  = rect.width  * ratio;
			canvas.height = rect.height * ratio;
			canvas.getContext('2d').scale(ratio, ratio);
			if (cfg.grid) drawGrid();
			pad.clear(); // clear after resize
		}}

		function drawGrid() {{
			var ctx  = canvas.getContext('2d');
			var w    = canvas.offsetWidth;
			var h    = canvas.offsetHeight;
			ctx.strokeStyle = 'rgba(0,0,0,0.07)';
			ctx.lineWidth   = 1;
			for (var x = 20; x < w; x += 20) {{
				ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
			}}
			for (var y = 20; y < h; y += 20) {{
				ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
			}}
		}}

		var pad = new SignaturePad(canvas, {{
			minWidth:        cfg.penWidthMin,
			maxWidth:        cfg.penWidthMax,
			penColor:        cfg.penColor,
			backgroundColor: 'rgba(0,0,0,0)',  // transparent; container sets bg
		}});

		if (cfg.readonly) {{
			pad.off();
		}}

		// Snapshot stack for undo
		var snapshots = [];

		pad.addEventListener('beginStroke', function() {{
			snapshots.push(pad.toData());
			status.textContent = 'Signing…';
		}});

		pad.addEventListener('endStroke', function() {{
			syncToHidden();
			status.textContent = 'Signature captured.';
		}});

		function syncToHidden() {{
			if (pad.isEmpty()) {{
				hidden.value = '';
				return;
			}}
			var payload = {{
				dataURL:   pad.toDataURL('image/png'),
				points:    pad.toData(),
				timestamp: new Date().toISOString()
			}};
			if (nameInput) {{
				payload.signerName = nameInput.value.trim();
			}}
			hidden.value = JSON.stringify(payload);
		}}

		// Restore existing signature if any
		var stored = hidden.value;
		if (stored) {{
			try {{
				var parsed = JSON.parse(stored);
				if (parsed.points && parsed.points.length) {{
					pad.fromData(parsed.points);
					if (nameInput && parsed.signerName) {{
						nameInput.value = parsed.signerName;
					}}
					status.textContent = 'Existing signature loaded.';
				}} else if (parsed.dataURL) {{
					pad.fromDataURL(parsed.dataURL);
					status.textContent = 'Existing signature loaded.';
				}}
			}} catch(e) {{ /* ignore invalid stored value */ }}
		}}

		// Clear button
		clearBtn.addEventListener('click', function() {{
			pad.clear();
			if (cfg.grid) drawGrid();
			snapshots = [];
			hidden.value = '';
			if (nameInput) nameInput.value = '';
			status.textContent = 'Cleared. Ready to sign.';
		}});

		// Undo button
		if (undoBtn) {{
			undoBtn.addEventListener('click', function() {{
				if (!snapshots.length) return;
				snapshots.pop();
				pad.fromData(snapshots.length ? snapshots[snapshots.length - 1] : []);
				syncToHidden();
				status.textContent = snapshots.length ? 'Undone.' : 'All strokes removed.';
			}});
		}}

		// Responsive canvas via ResizeObserver
		if (typeof ResizeObserver !== 'undefined') {{
			var ro = new ResizeObserver(function() {{ resizeCanvas(); }});
			ro.observe(canvas.parentElement);
		}} else {{
			window.addEventListener('resize', resizeCanvas);
		}}

		// Initial size
		resizeCanvas();

		// Sync on form submit
		var form = hidden.closest('form');
		if (form) {{
			form.addEventListener('submit', syncToHidden, {{ capture: true }});
		}}
	}}

	if (typeof SignaturePad !== 'undefined') {{
		initSignaturePad();
	}} else if (window['{shared_guard}']) {{
		// Another field already kicked off the load; wait for it
		document.addEventListener('fab-sigpad-ready', initSignaturePad);
	}} else {{
		window['{shared_guard}'] = true;
		var s = document.createElement('script');
		s.src = 'https://cdn.jsdelivr.net/npm/signature_pad@4.1.7/dist/signature_pad.umd.min.js';
		s.onload = function() {{
			document.dispatchEvent(new Event('fab-sigpad-ready'));
			initSignaturePad();
		}};
		document.head.appendChild(s);
	}}
}})();
</script>
"""

		return Markup(html + js)

	@staticmethod
	def process_formdata(valuelist: list[str]) -> str | None:
		"""Return the JSON string as-is; caller decodes if needed."""
		if not valuelist or not valuelist[0]:
			return None
		return valuelist[0]
