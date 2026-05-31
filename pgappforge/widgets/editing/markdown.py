"""MarkdownEditorWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms import Field
from wtforms.fields import (
    BooleanField, DateField, DateTimeField, DecimalField, FileField,
    FloatField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import ValidationError
from wtforms.widgets import TextInput, html_params

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

        template = self.data_template if field.data else self.empty_template
        html = template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
        }

        return Markup(f"""
            {html}
            <script>
                (function() {{
                    // Initialize EasyMDE with enhanced configuration
                    const easyMDE = new EasyMDE({{
                        element: document.getElementById('{field.id}-editor'),
                        initialValue: {_js_json(field.data or "")},
                        spellChecker: {str(self.spellchecker).lower()},
                        autoDownloadFontAwesome: false,
                        autosave: {{
                            enabled: {str(self.autosave).lower()},
                            delay: {self.autosave_delay},
                            uniqueId: "{field.id}",
                            text: "Auto-saved: "
                        }},
                        theme: "{self.theme}",
                        toolbar: {_js_json(self.toolbar_config)},
                        status: {_js_json(self.status_bar_items)},
                        uploadImage: true,
                        imageUploadEndpoint: "{self.upload_url}",
                        renderingConfig: {{
                            singleLineBreaks: false,
                            codeSyntaxHighlighting: {str(self.syntax_highlighting).lower()},
                            sanitizerFunction: (html) => {{
                                // Implement custom sanitization if needed
                                return html;
                            }}
                        }},
                        previewRender: function(plainText, preview) {{
                            // Enhanced preview with KaTeX support
                            setTimeout(() => {{
                                renderMathInElement(preview, {{
                                    delimiters: {_js_json(self.math_delimiters)},
                                    throwOnError: false,
                                    errorColor: '#cc0000'
                                }});
                            }}, 0);
                            return this.parent.markdown(plainText);
                        }}
                    }});

                    // Enhanced change handler with debouncing
                    let updateTimeout;
                    easyMDE.codemirror.on("change", () => {{
                        clearTimeout(updateTimeout);
                        updateTimeout = setTimeout(() => {{
                            const value = easyMDE.value();
                            const input = document.getElementById('{field.id}');
                            input.value = value;

                            // Update metadata with enhanced counting
                            const wordCount = value.trim().split(/\\s+/).filter(w => w.length > 0).length;
                            const charCount = value.length;

                            document.querySelector('.markdown-metadata .word-count')
                                .textContent = `${{wordCount}} words`;
                            document.querySelector('.markdown-metadata .char-count')
                                .textContent = `${{charCount}} characters`;
                        }}, 150);
                    }});

                    // Enhanced image upload handler with progress tracking
                    easyMDE.uploadImage = async function(file, onSuccess, onError) {{
                        const formData = new FormData();
                        formData.append('image', file);

                        try {{
                            const response = await fetch('{self.upload_url}', {{
                                method: 'POST',
                                body: formData,
                                headers: {{
                                    'Accept': 'application/json'
                                }}
                            }});

                            if (!response.ok) {{
                                throw new Error(`HTTP error! status: ${{response.status}}`);
                            }}

                            const data = await response.json();
                            if (data?.url) {{
                                onSuccess(data.url);
                            }} else {{
                                throw new Error('Upload response missing URL');
                            }}
                        }} catch (error) {{
                            console.error('Upload error:', error);
                            onError(`Image upload failed: ${{error.message}}`);
                        }}
                    }};

                    // Initialize KaTeX for existing math content
                    if (easyMDE.value().includes('$')) {{
                        renderMathInElement(
                            document.getElementById('{field.id}-editor'),
                            {{
                                delimiters: {_js_json(self.math_delimiters)},
                                throwOnError: false,
                                errorColor: '#cc0000'
                            }}
                        );
                    }}
                }})();
            </script>
        """)

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
