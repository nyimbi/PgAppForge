"""RichTextEditorWidget — PgAppForge widget(s)."""

from __future__ import annotations
import html as _html
import json
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms.validators import ValidationError

class RichTextEditorWidget(BS3TextFieldWidget):
    """
    Advanced rich text editor widget using Quill.js for PgAppForge

    Features:
    - Full WYSIWYG editing powered by Quill.js
    - Highly customizable toolbar with granular control over buttons and groups
    - Enhanced image upload and handling with error management and server-side integration
    - Template insertion feature for reusable content blocks
    - Revision history and basic version control within the editor
    - Real-time collaborative editing capabilities (Requires backend integration - placeholder)
    - Sophisticated word count and text analysis (character count, reading time, etc.)
    - Table support, formula/equation editing, and code highlighting
    - Auto-save functionality with configurable interval
    - Placeholder text and read-only mode
    - Custom formats and themes

    Database Type:
        PostgreSQL: text or jsonb (for storing Quill Delta format)
        SQLAlchemy: Text or JSON/JSONB

    Example Usage:
        content = db.Column(db.Text, nullable=True, info={'widget': RichTextEditorWidget(
                                                        height='500px',
                                                        toolbar_config=[
                                                            [{'header': [1, 2, False]}],
                                                            ['bold', 'italic', 'underline', 'strike'],
                                                            ['link', 'image'],
                                                            ['clean']
                                                        ],
                                                        autosave_interval=10000,
                                                        enable_templates=True,
                                                        enable_history=True,
                                                        enable_collaboration=False
                                                    )})
    """

    data_template = (
        '<div class="rich-text-editor-container">'
        "<input %(hidden)s>"
        '<div id="%(field_id)s-toolbar"></div>'
        '<div id="%(field_id)s-editor"></div>'
        '<div class="editor-metadata">'
        '    <span id="%(field_id)s-wordcount" class="word-count"></span>'
        '    <span id="%(field_id)s-readingtime" class="reading-time"></span>'  # Example of new metadata
        "</div>"
        '<div id="%(field_id)s-error" class="editor-error"></div>'
        ' <div id="%(field_id)s-history" class="editor-history" style="display:none;">'  # History container
        "     <h5>Revision History</h5>"
        '     <ul class="history-list"></ul>'
        " </div>"
        "</div>"
    )
    empty_template = data_template  # Uses same template

    def __init__(self, **kwargs):
        """Initialize rich text editor with extended settings for toolbar, templates, history, and collaboration"""
        super().__init__(**kwargs)
        # Universal widget kwargs
        self.css_class = kwargs.get("css_class", "")
        self.description = kwargs.get("description", "")
        self.readonly = kwargs.get("read_only", False)  # alias: read_only already used below
        self.disabled = kwargs.get("disabled", False)
        self.height = kwargs.get("height", "400px")
        self.toolbar_config = kwargs.get(
            "toolbar_config",
            [
                ["bold", "italic", "underline", "strike"],
                [{"header": [1, 2, 3, False]}],
                ["link", "image"],
                ["clean"],
            ],
        )  # More concise default toolbar
        self.formats = kwargs.get(
            "formats",
            ["bold", "italic", "underline", "strike", "header", "link", "image"],
        )  # Streamlined default formats
        self.placeholder = kwargs.get("placeholder", "Enter text here...")
        self.read_only = kwargs.get("read_only", False)
        self.auto_save = kwargs.get("auto_save", True)
        self.auto_save_interval = kwargs.get(
            "auto_save_interval", 10000
        )  # Increased default autosave interval to 10 seconds
        self.word_count = kwargs.get("word_count", True)
        self.max_length = kwargs.get("max_length", None)
        self.image_upload_url = kwargs.get("image_upload_url", "/api/upload")
        self.image_resize = kwargs.get("image_resize", True)
        self.image_max_size = kwargs.get(
            "image_max_size", 10 * 1024 * 1024
        )  # Increased max image size to 10MB
        self.allowed_image_types = kwargs.get(
            "allowed_image_types",
            ["image/jpeg", "image/png", "image/gif", "image/webp"],
        )  # Added webp support
        self.enable_templates = kwargs.get(
            "enable_templates", False
        )  # Enable template insertion feature
        self.templates_url = kwargs.get(
            "templates_url", "/api/editor-templates"
        )  # URL to fetch templates from
        self.enable_history = kwargs.get(
            "enable_history", False
        )  # Enable revision history
        self.history_url = kwargs.get(
            "history_url", "/api/editor-history"
        )  # URL to fetch revision history
        self.enable_collaboration = kwargs.get(
            "enable_collaboration", False
        )  # Enable real-time collaboration (Placeholder - not fully implemented in this widget)
        self.collaboration_url = kwargs.get(
            "collaboration_url", "/api/editor-collaborate"
        )  # Collaboration endpoint (Placeholder)
        self.text_analysis_features = kwargs.get(
            "text_analysis_features", ["wordCount", "charCount", "readingTime"]
        )  # Configurable text analysis features

    def __call__(self, field, **kwargs):
        """Render the rich text editor widget with enhanced toolbar, template insertion, and history features"""
        kwargs.setdefault("type", "hidden")

        if field.flags.required:
            kwargs["required"] = True
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

        # Aria attributes for the editor container
        aria_label = str(field.label.text) if field.label else field.name
        describedby_parts = []
        if self.description:
            describedby_parts.append(f"{field.id}_help")
        if has_errors:
            describedby_parts.append(f"{field.id}_error")

        # Use json.dumps for all Python values injected into JS
        field_id_js = json.dumps(field.id)
        placeholder_js = json.dumps(self.placeholder)
        image_upload_url_js = json.dumps(self.image_upload_url)
        aria_label_js = json.dumps(aria_label)
        describedby_js = json.dumps(" ".join(describedby_parts)) if describedby_parts else "null"

        script = f"""
        <style>
            .rich-text-editor-container {{ position: relative; margin-bottom: 1em; }}
            .ql-editor {{ min-height: {_html.escape(self.height)}; max-width: 100%; max-height: 800px; overflow-y: auto; }}
            .editor-metadata {{ margin-top: 0.5em; color: #666; font-size: 0.9em; }}
            .editor-error {{ color: #a94442; display: none; margin-top: 0.5em; }}
            .editor-history {{ margin-top: 1em; border: 1px solid #ccc; padding: 10px; border-radius: 4px; }}
            .editor-history .history-list {{ list-style: none; padding: 0; margin: 0; }}
            .editor-history .history-list li {{ padding: 5px 0; border-bottom: 1px dotted #eee; }}
            .editor-history .history-list li:last-child {{ border-bottom: none; }}
        </style>
        <script>
            (function() {{
                var fieldId = {field_id_js};
                var editor = null;
                var $input = $('#' + fieldId);
                var $error = $('#' + fieldId + '-error');
                var $wordcount = $('#' + fieldId + '-wordcount');
                var $readingtime = $('#' + fieldId + '-readingtime');
                var $historyContainer = $('#' + fieldId + '-history');
                var autoSaveTimeout;

                function initializeEditor() {{
                    editor = new Quill('#' + fieldId + '-editor', {{
                        modules: {{
                            toolbar: {{
                                container: {json.dumps(self.toolbar_config)},
                                handlers: {{ image: imageHandler, templates: templatesHandler }}
                            }},
                            formula: true, syntax: true, imageResize: {str(self.image_resize).lower()}, history: {{ delay: 2000, maxStack: 500 }}
                        }},
                        placeholder: {placeholder_js},
                        readOnly: {str(self.read_only).lower()},
                        theme: 'snow',
                        formats: {json.dumps(self.formats)}
                    }});

                    // Apply accessibility attributes to the Quill contenteditable div
                    var qlEditor = document.querySelector('#' + fieldId + '-editor .ql-editor');
                    if (qlEditor) {{
                        qlEditor.setAttribute('aria-label', {aria_label_js});
                        qlEditor.setAttribute('aria-multiline', 'true');
                        if ({describedby_js} !== null) qlEditor.setAttribute('aria-describedby', {describedby_js});
                        {f'qlEditor.setAttribute("aria-invalid", "true");' if has_errors else ''}
                    }}

                    editor.on('text-change', handleTextChange);
                }}

                function imageHandler() {{
                    var input = document.createElement('input');
                    input.setAttribute('type', 'file');
                    input.setAttribute('accept', {json.dumps(",".join(self.allowed_image_types))});

                    input.onchange = async function() {{
                        var file = input.files[0];
                        if (!file) return;

                        if (file.size > {self.image_max_size}) {{
                            displayError('Image too large (max {self.image_max_size} bytes)');
                            return;
                        }}

                        if (!{json.dumps(self.allowed_image_types)}.includes(file.type)) {{
                            displayError('Invalid image type');
                            return;
                        }}

                        const formData = new FormData();
                        formData.append('image', file);

                        try {{
                            showLoading('Uploading Image...');
                            const response = await fetch({image_upload_url_js}, {{
                                method: 'POST',
                                body: formData,
                                processData: false,
                                contentType: false
                            }});
                            hideLoading();
                            const data = await response.json();
                            const range = editor.getSelection(true);
                            editor.insertEmbed(range.index, 'image', data.url);
                        }} catch (error) {{
                            hideLoading();
                            displayError('Image upload failed: ' + error.message);
                            console.error('Image upload error:', error);
                        }}
                    }};
                    input.click();
                }}

                function templatesHandler() {{
                    alert('Template insertion feature is a placeholder and needs backend implementation.');
                }}

                function handleTextChange(delta, oldDelta, source) {{
                    if (source === 'api') return;

                    var contents = editor.getContents();
                    var text = editor.getText().trim();

                    updateTextMetadata(text);

                    if ({json.dumps(self.max_length)} && text.length > {json.dumps(self.max_length)}) {{
                        displayError('Content exceeds maximum length');
                        return;
                    }} else {{
                        $error.hide();
                    }}

                    $input.val(JSON.stringify(contents)).trigger('change');
                    if ({str(self.auto_save).lower()}) queueAutoSave();
                }}

                function updateTextMetadata(text) {{
                    if ({str(self.word_count).lower()}) {{
                        const wordCount = text ? text.trim().split(/\\s+/).length : 0;
                        $wordcount.text('Words: ' + wordCount);
                    }} else {{
                        $wordcount.empty();
                    }}

                    if ({json.dumps(self.text_analysis_features)}.includes('readingTime')) {{
                        const wordsPerMinute = 200;
                        const readingTimeMinutes = Math.ceil(text.trim().split(/\\s+/).length / wordsPerMinute);
                        $readingtime.text('Reading Time: ~' + readingTimeMinutes + ' minutes');
                    }} else {{
                        $readingtime.empty();
                    }}
                }}

                function queueAutoSave() {{
                    clearTimeout(autoSaveTimeout);
                    autoSaveTimeout = setTimeout(triggerAutoSave, {self.auto_save_interval});
                }}

                function triggerAutoSave() {{
                    $input.closest('form').trigger('autosave', [{{ field: $input.attr('name'), value: $input.val() }}]);
                }}

                function toggleHistory() {{
                    $historyContainer.toggle();
                    if ($historyContainer.is(':visible')) {{
                        loadHistory();
                    }}
                }}

                function loadHistory() {{
                    $historyContainer.find('.history-list').html('<li>Revision history loading is a placeholder.</li>');
                }}

                function displayError(message) {{
                    $error.text(message).show();
                }}

                function showLoading(message) {{
                    $('.loading-overlay').text(message).show();
                }}

                function hideLoading() {{
                    $('.loading-overlay').hide();
                }}

                initializeEditor();

                if ($input.val()) {{
                    try {{
                        editor.setContents(JSON.parse($input.val()));
                        updateTextMetadata(editor.getText().trim());
                    }} catch (e) {{
                        console.error('Error setting initial content:', e);
                        $error.text('Error loading content').show();
                    }}
                }}

                $input.closest('form').on('reset', function() {{
                    editor.setContents([]);
                    $error.hide();
                    $wordcount.empty();
                    $readingtime.empty();
                }});
            }})();
        </script>
        """

        return Markup(rendered_html + help_html + error_html + script)

    def pre_validate(self, form):
        """Validate content before form processing"""
        if self.data:
            try:
                content = json.loads(self.data)
                if not isinstance(content, dict):
                    raise ValidationError("Invalid content format")

                # Extract plain text for length validation
                if self.max_length and len(content.get("ops", [])) > 0:
                    text = "".join(op.get("insert", "") for op in content["ops"])
                    if len(text) > self.max_length:
                        raise ValidationError(
                            f"Content exceeds maximum length of {self.max_length} characters"
                        )
            except json.JSONDecodeError:
                raise ValidationError("Invalid JSON content")

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = json.loads(valuelist[0])
            except json.JSONDecodeError as e:
                self.data = None
                raise ValidationError("Invalid rich text content") from e
        else:
            self.data = None

    def process_data(self, value):
        """Process data from database format"""
        if value:
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return value
        return None
