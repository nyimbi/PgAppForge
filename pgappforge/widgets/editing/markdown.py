"""MarkdownEditorWidget — PgAppForge widget(s)."""

from __future__ import annotations
import html as _html
import json
from typing import Any, Dict, List, Optional, Union
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms.validators import ValidationError

class MarkdownEditorWidget(BS3TextFieldWidget):
    """
    An advanced Markdown editor widget for PgAppForge forms with enhanced features.

    This widget integrates EasyMDE for rich markdown editing capabilities with real-time
    preview, syntax highlighting, and extensive customization options.

    Attributes:
        data_template (str): HTML template for the editor when data is present
        empty_template (str): HTML template for the editor when empty

    Features:
        - Real-time preview with configurable rendering
        - Syntax highlighting with multiple theme support
        - Customizable toolbar with extensive options
        - Image upload support with progress tracking
        - Mathematical equation rendering via KaTeX
        - Auto-save functionality with configurable delay
        - Word and character counting
        - Full-screen editing mode
        - Split-screen preview mode
        - Spell checking with customizable dictionary

    Database Compatibility:
        - PostgreSQL: Text or JSONB (for metadata storage)
        - MySQL: TEXT or JSON
        - SQLite: TEXT
    """

    data_template: str = (
        '<div class="markdown-editor-container">'
        "  <input %(hidden)s>"
        '  <div id="%(field_id)s-editor" class="markdown-editor"></div>'
        '  <div class="markdown-metadata">'
        '    <span class="word-count"></span>'
        '    <span class="char-count"></span>'
        '    <span class="save-status"></span>'
        "  </div>"
        "</div>"
    )
    empty_template: str = data_template

    def __init__(
        self,
        autosave: bool = True,
        autosave_delay: int = 1000,
        spellchecker: bool = True,
        upload_url: str = "/api/upload",
        theme: str = "default",
        toolbar_config: Optional[List[str]] = None,
        status_bar_items: Optional[List[str]] = None,
        syntax_highlighting: bool = True,
        math_delimiters: Optional[List[Dict[str, str]]] = None,
        placeholder: str = "",
        css_class: str = "",
        description: str = "",
        readonly: bool = False,
        disabled: bool = False,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the Markdown editor widget with customizable settings.

        Args:
            autosave: Enable/disable automatic saving of content
            autosave_delay: Delay in milliseconds between auto-saves
            spellchecker: Enable/disable spell checking
            upload_url: Endpoint for image uploads
            theme: Editor theme name
            toolbar_config: List of toolbar items to display
            status_bar_items: List of status bar items to show
            syntax_highlighting: Enable/disable syntax highlighting
            math_delimiters: Custom delimiters for math equations
            **kwargs: Additional keyword arguments
        """
        super().__init__(**kwargs)

        # Universal widget kwargs
        self.placeholder = placeholder
        self.css_class = css_class
        self.description = description
        self.readonly = readonly
        self.disabled = disabled

        self.autosave = autosave
        self.autosave_delay = autosave_delay
        self.spellchecker = spellchecker
        self.upload_url = upload_url
        self.theme = theme
        self.syntax_highlighting = syntax_highlighting

        # Default toolbar configuration
        self.toolbar_config = toolbar_config or [
            "bold",
            "italic",
            "heading",
            "|",
            "quote",
            "code",
            "unordered-list",
            "ordered-list",
            "|",
            "link",
            "image",
            "table",
            "|",
            "preview",
            "side-by-side",
            "fullscreen",
            "|",
            "guide",
        ]

        # Default status bar items
        self.status_bar_items = status_bar_items or [
            "autosave",
            "lines",
            "words",
            "cursor",
            "upload-progress",
        ]

        # Default math delimiters
        self.math_delimiters = math_delimiters or [
            {"left": "$$", "right": "$$", "display": True},
            {"left": "$", "right": "$", "display": False},
        ]

    def __call__(self, field: Any, **kwargs: Any) -> Markup:
        """
        Render the widget HTML and JavaScript.

        Args:
            field: The form field to render
            **kwargs: Additional rendering options

        Returns:
            Markup: Safe HTML markup for the widget
        """
        kwargs.setdefault("type", "hidden")
        if self.readonly:
            kwargs["readonly"] = True
        if self.disabled:
            kwargs["disabled"] = True

        has_errors = bool(field.errors)

        template = self.data_template if field.data else self.empty_template
        rendered_html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        # Help text
        help_html = ""
        if self.description:
            help_html = (
                f'<small class="form-text text-muted" id="{field.id}_help">'
                f'{_html.escape(str(self.description))}</small>'
            )

        # Error feedback (server-side WTForms errors)
        error_html = ""
        if has_errors:
            error_items = "".join(
                f"<span>{_html.escape(str(e))}</span>" for e in field.errors
            )
            error_html = (
                f'<div class="invalid-feedback d-block" id="{field.id}_error" role="alert">'
                f'{error_items}</div>'
            )

        # Accessibility: aria attrs for the hidden input (EasyMDE wraps it)
        aria_label = str(field.label.text) if field.label else field.name
        describedby_parts = []
        if self.description:
            describedby_parts.append(f"{field.id}_help")
        if has_errors:
            describedby_parts.append(f"{field.id}_error")

        # Use json.dumps for all Python values injected into JS
        field_id_js = json.dumps(field.id)
        upload_url_js = json.dumps(self.upload_url)
        theme_js = json.dumps(self.theme)

        script = f"""
            <script>
                (function() {{
                    var fieldId = {field_id_js};
                    var editorEl = document.getElementById(fieldId + '-editor');
                    if (!editorEl) return;

                    // Initialize EasyMDE with enhanced configuration
                    const easyMDE = new EasyMDE({{
                        element: editorEl,
                        initialValue: {_js_json(field.data or "")},
                        spellChecker: {str(self.spellchecker).lower()},
                        autoDownloadFontAwesome: false,
                        autosave: {{
                            enabled: {str(self.autosave).lower()},
                            delay: {self.autosave_delay},
                            uniqueId: fieldId,
                            text: "Auto-saved: "
                        }},
                        theme: {theme_js},
                        toolbar: {_js_json(self.toolbar_config)},
                        status: {_js_json(self.status_bar_items)},
                        uploadImage: true,
                        imageUploadEndpoint: {upload_url_js},
                        renderingConfig: {{
                            singleLineBreaks: false,
                            codeSyntaxHighlighting: {str(self.syntax_highlighting).lower()},
                            sanitizerFunction: function(rawHtml) {{
                                return rawHtml;
                            }}
                        }},
                        previewRender: function(plainText, preview) {{
                            setTimeout(function() {{
                                if (typeof renderMathInElement !== 'undefined') {{
                                    renderMathInElement(preview, {{
                                        delimiters: {_js_json(self.math_delimiters)},
                                        throwOnError: false,
                                        errorColor: '#cc0000'
                                    }});
                                }}
                            }}, 0);
                            return this.parent.markdown(plainText);
                        }}
                    }});

                    // Apply aria attributes to the underlying textarea
                    var textarea = editorEl;
                    textarea.setAttribute('aria-label', {json.dumps(aria_label)});
                    {f'textarea.setAttribute("aria-describedby", {json.dumps(" ".join(describedby_parts))});' if describedby_parts else ''}
                    {f'textarea.setAttribute("aria-invalid", "true");' if has_errors else ''}

                    // Enhanced change handler with debouncing
                    let updateTimeout;
                    easyMDE.codemirror.on("change", function() {{
                        clearTimeout(updateTimeout);
                        updateTimeout = setTimeout(function() {{
                            const value = easyMDE.value();
                            const input = document.getElementById(fieldId);
                            if (input) input.value = value;

                            const wordCount = value.trim().split(/\\s+/).filter(function(w) {{ return w.length > 0; }}).length;
                            const charCount = value.length;

                            const wc = document.querySelector('#' + fieldId + '-editor').closest('.markdown-editor-container').querySelector('.word-count');
                            const cc = document.querySelector('#' + fieldId + '-editor').closest('.markdown-editor-container').querySelector('.char-count');
                            if (wc) wc.textContent = wordCount + ' words';
                            if (cc) cc.textContent = charCount + ' characters';
                        }}, 150);
                    }});

                    // Image upload handler
                    easyMDE.uploadImage = async function(file, onSuccess, onError) {{
                        const formData = new FormData();
                        formData.append('image', file);

                        try {{
                            const response = await fetch({upload_url_js}, {{
                                method: 'POST',
                                body: formData,
                                headers: {{ 'Accept': 'application/json' }}
                            }});

                            if (!response.ok) {{
                                throw new Error('HTTP error! status: ' + response.status);
                            }}

                            const data = await response.json();
                            if (data && data.url) {{
                                onSuccess(data.url);
                            }} else {{
                                throw new Error('Upload response missing URL');
                            }}
                        }} catch (error) {{
                            console.error('Upload error:', error);
                            onError('Image upload failed: ' + error.message);
                        }}
                    }};

                    // Initialize KaTeX for existing math content
                    if (typeof renderMathInElement !== 'undefined' && easyMDE.value().includes('$')) {{
                        renderMathInElement(editorEl, {{
                            delimiters: {_js_json(self.math_delimiters)},
                            throwOnError: false,
                            errorColor: '#cc0000'
                        }});
                    }}
                }})();
            </script>
        """

        return Markup(rendered_html + help_html + error_html + script)

    def process_data(self, value: Union[str, Dict[str, Any], None]) -> str:
        """
        Process data from database format to editor format.

        Args:
            value: Input value from database

        Returns:
            str: Processed content string
        """
        if isinstance(value, dict):
            return value.get("content", "")
        return value or ""

    def process_formdata(self, valuelist: List[str]) -> Optional[str]:
        """
        Process form data to database format.

        Args:
            valuelist: List of form values

        Returns:
            Optional[str]: Processed content string or None
        """
        return valuelist[0] if valuelist else None
