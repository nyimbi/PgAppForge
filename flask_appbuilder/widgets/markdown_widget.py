"""
Markdown editor and display widgets for Flask-AppBuilder.

Provides:
- MarkdownEditorWidget  — full WYSIWYG markdown editor (EasyMDE via CDN)
- MarkdownDisplayWidget — read-only rendered markdown (marked.js via CDN)

Both work offline after first CDN load (CDN assets are cached by the browser).

Usage in a model view::

    from flask_appbuilder.widgets.markdown_widget import MarkdownEditorWidget, MarkdownDisplayWidget

    class ArticleView(ModelView):
        datamodel = SQLAInterface(Article)

        # Edit/add: use the full editor
        edit_form_extra_fields = {
            "body": TextAreaField("Body", widget=MarkdownEditorWidget())
        }

        # Show: render as HTML
        show_form_extra_fields = {
            "body": StringField("Body", widget=MarkdownDisplayWidget())
        }

The column stores raw Markdown text (PostgreSQL TEXT column is ideal).

Model::

    class Article(Model):
        __tablename__ = 'articles'
        id    = Column(Integer, primary_key=True)
        title = Column(String(255), nullable=False)
        body  = Column(Text)           # Markdown source
        body_html = Column(Text)       # Optional: pre-rendered HTML cache
"""
from __future__ import annotations

from markupsafe import Markup
from flask_appbuilder.fieldwidgets import BS3TextAreaFieldWidget


# CDN references — imported from canonical _cdn module
from flask_appbuilder.widgets_postgresql._cdn import (
	EASYMDE_CDN as _EASYMDE_CSS,
	MARKED_CDN as _MARKED_JS,
	DOMPURIFY_CDN as _DOMPURIFY_JS,
)
# EasyMDE needs both CSS and JS
_EASYMDE_JS = ''  # included in EASYMDE_CDN above


class MarkdownEditorWidget(BS3TextAreaFieldWidget):
	"""Full Markdown editor using EasyMDE.

	Features:
	- Toolbar: bold, italic, heading, quote, code, link, image, list, preview,
	  side-by-side, fullscreen
	- Live split-pane preview
	- Keyboard shortcuts (Ctrl+B bold, Ctrl+I italic, etc.)
	- Spell-check via browser
	- Character/word count in status bar
	- Works with any TEXT/VARCHAR column

	Args:
	    min_height:   Minimum editor height in pixels (default 250).
	    max_height:   Maximum editor height (default 600).
	    placeholder:  Placeholder text shown when empty.
	    autosave:     Enable autosave to localStorage (default False).
	    autosave_key: localStorage key for autosave (default: field id).
	    toolbar:      Custom toolbar list, or None for default.
	    spell_check:  Enable browser spell-check (default True).
	"""

	def __init__(
		self,
		min_height: int = 250,
		max_height: int = 600,
		placeholder: str = "Write Markdown here…",
		autosave: bool = False,
		autosave_key: str | None = None,
		toolbar: list[str] | None = None,
		spell_check: bool = True,
	):
		self.min_height = min_height
		self.max_height = max_height
		self.placeholder = placeholder
		self.autosave = autosave
		self.autosave_key = autosave_key
		self.toolbar = toolbar
		self.spell_check = spell_check

	def __call__(self, field, **kwargs) -> Markup:
		fid = field.id
		value = field.data or ""
		# Serialise via JSON — safe against template-literal injection (${...})
		import json as _json
		value_json = _json.dumps(value)  # produces a quoted, escaped JSON string

		min_h = self.min_height
		max_h = self.max_height
		placeholder = self.placeholder.replace('"', '\\"')
		spell_check = "true" if self.spell_check else "false"
		autosave_key = self.autosave_key or fid

		if self.autosave:
			autosave_cfg = f"""autosave: {{ enabled: true, uniqueId: "{autosave_key}", delay: 3000 }},"""
		else:
			autosave_cfg = ""

		if self.toolbar:
			import json as _j
			toolbar_cfg = f"toolbar: {_j.dumps(self.toolbar)},"
		else:
			toolbar_cfg = ""

		html = f"""
{_EASYMDE_CSS}
{_EASYMDE_JS}

<div class="markdown-editor-widget" id="{fid}_wrapper">
  <textarea name="{field.name}" id="{fid}"
            style="display:none">{value}</textarea>
</div>

<script>
var _mde_val_{fid} = {value_json};
(function() {{
  function initEasyMDE() {{
    if (!window.EasyMDE) {{
      setTimeout(initEasyMDE, 100);
      return;
    }}
    var easyMde = new EasyMDE({{
      element: document.getElementById('{fid}'),
      initialValue: _mde_val_{fid},
      placeholder: "{placeholder}",
      spellChecker: {spell_check},
      minHeight: "{min_h}px",
      maxHeight: "{max_h}px",
      {autosave_cfg}
      {toolbar_cfg}
      renderingConfig: {{
        singleLineBreaks: false,
        codeSyntaxHighlighting: true,
      }},
      status: ['autosave', 'lines', 'words', 'cursor'],
      previewRender: function(plainText) {{
        if (window.DOMPurify && window.marked) {{
          return DOMPurify.sanitize(marked.parse(plainText));
        }} else if (window.marked) {{
          return marked.parse(plainText);
        }}
        return plainText;
      }},
    }});
    // Keep textarea value synced (for FAB form submission)
    easyMde.codemirror.on('change', function() {{
      document.getElementById('{fid}').value = easyMde.value();
    }});
  }}
  document.addEventListener('DOMContentLoaded', initEasyMDE);
}})();
</script>
"""
		return Markup(html)


class MarkdownDisplayWidget:
	"""Read-only widget that renders stored Markdown as sanitised HTML.

	Uses marked.js for Markdown parsing and DOMPurify for XSS sanitisation.
	Applies GitHub-flavoured Markdown by default (tables, task lists, etc.).

	The rendered HTML respects Bootstrap typography classes so it integrates
	naturally with Flask-AppBuilder's default Bootstrap 3/4 theme.

	Args:
	    css_class: Extra CSS class(es) on the container div.
	    gfm:       Enable GitHub-flavoured Markdown (default True).
	    breaks:    Render newlines as <br> (default False).
	    sanitize:  Apply DOMPurify sanitisation (default True).
	"""

	def __init__(
		self,
		css_class: str = "",
		gfm: bool = True,
		breaks: bool = False,
		sanitize: bool = True,
	):
		self.css_class = css_class
		self.gfm = "true" if gfm else "false"
		self.breaks = "true" if breaks else "false"
		self.sanitize = sanitize

	def __call__(self, field, **kwargs) -> Markup:
		fid = field.id
		value = field.data or ""
		# Store raw markdown in hidden input
		import json as _j
		raw_json = _j.dumps(value)  # safe for <script> injection
		css = "markdown-display " + self.css_class
		gfm = self.gfm
		breaks = self.breaks
		sanitize = "true" if self.sanitize else "false"

		html = f"""
{_MARKED_JS}
{_DOMPURIFY_JS}

<div class="{css}" id="{fid}_display"
     style="padding:8px;background:#fafafa;border:1px solid #eee;border-radius:4px;min-height:40px">
  <em class="text-muted" style="font-size:0.85em">Rendering…</em>
</div>
<input type="hidden" name="{field.name}" id="{fid}" value="">

<script>
(function() {{
  var raw = {raw_json};
  var fieldEl = document.getElementById('{fid}');
  var displayEl = document.getElementById('{fid}_display');
  fieldEl.value = raw;

  function render() {{
    if (!window.marked) {{ setTimeout(render, 80); return; }}
    marked.setOptions({{gfm: {gfm}, breaks: {breaks}, mangle: false, headerIds: false}});
    var html = marked.parse(raw);
    if ({sanitize} && window.DOMPurify) html = DOMPurify.sanitize(html);
    displayEl.innerHTML = html || '<em class="text-muted">(empty)</em>';
  }}
  document.addEventListener('DOMContentLoaded', render);
}})();
</script>
"""
		return Markup(html)


class MarkdownPreviewWidget(MarkdownEditorWidget):
	"""Markdown editor with a permanent side-by-side live preview.

	Identical to MarkdownEditorWidget but forces side-by-side mode on load
	so the preview is always visible without toggling.
	"""

	def __call__(self, field, **kwargs) -> Markup:
		html = str(super().__call__(field, **kwargs))
		# Activate side-by-side mode after init
		html = html.replace(
			"document.addEventListener('DOMContentLoaded', initEasyMDE);",
			"""document.addEventListener('DOMContentLoaded', function() {
  initEasyMDE();
  // Activate side-by-side after a short delay so EasyMDE is ready
  setTimeout(function() {
    var btn = document.querySelector('#""" + field.id + """_wrapper .editor-toolbar button.side-by-side');
    if (btn) btn.click();
  }, 300);
});"""
		)
		return Markup(html)


__all__ = [
	"MarkdownEditorWidget",
	"MarkdownDisplayWidget",
	"MarkdownPreviewWidget",
]
