"""
Code Editor Widget for PgForge

Advanced code editor widget with syntax highlighting and IDE features using Monaco Editor.
"""

import logging
from uuid import uuid4

from flask import render_template_string
from markupsafe import Markup
from flask_babel import gettext
from wtforms.widgets import TextArea

log = logging.getLogger(__name__)


class CodeEditorWidget(TextArea):
    """
    Advanced code editor widget with syntax highlighting and IDE features.

    Features:
    - Syntax highlighting for multiple languages
    - Line numbers and code folding
    - Auto-completion and IntelliSense
    - Multiple themes (light/dark)
    - Find and replace functionality
    - Bracket matching and auto-indentation
    - Multiple cursor support
    - Minimap for navigation
    - Error highlighting and linting
    - Customizable keybindings
    """

    def __init__(self,
                 language: str = 'javascript',
                 theme: str = 'vs-light',
                 font_size: int = 14,
                 tab_size: int = 4,
                 word_wrap: bool = True,
                 line_numbers: bool = True,
                 minimap: bool = True,
                 auto_complete: bool = True,
                 bracket_matching: bool = True,
                 folding: bool = True,
                 find_replace: bool = True,
                 multiple_cursors: bool = True,
                 linting: bool = True,
                 readonly: bool = False):
        """
        Initialize the code editor widget.

        Args:
            language: Programming language for syntax highlighting
            theme: Editor theme (vs-light, vs-dark, hc-black)
            font_size: Font size in pixels
            tab_size: Number of spaces per tab
            word_wrap: Enable word wrapping
            line_numbers: Show line numbers
            minimap: Show minimap for navigation
            auto_complete: Enable auto-completion
            bracket_matching: Enable bracket matching
            folding: Enable code folding
            find_replace: Enable find and replace
            multiple_cursors: Enable multiple cursor support
            linting: Enable error highlighting
            readonly: Make editor read-only
        """
        self.language = language
        self.theme = theme
        self.font_size = font_size
        self.tab_size = tab_size
        self.word_wrap = word_wrap
        self.line_numbers = line_numbers
        self.minimap = minimap
        self.auto_complete = auto_complete
        self.bracket_matching = bracket_matching
        self.folding = folding
        self.find_replace = find_replace
        self.multiple_cursors = multiple_cursors
        self.linting = linting
        self.readonly = readonly

    def __call__(self, field, **kwargs):
        """Render the code editor widget."""
        widget_id = kwargs.get('id', f'code_editor_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'code-editor-textarea')
        kwargs['style'] = 'display: none;'

        # Get the textarea HTML for fallback
        textarea_html = super().__call__(field, **kwargs)

        template = """
        {{ textarea_html | safe }}

        <div class="code-editor-container" data-widget="code-editor">
            <div class="code-editor-toolbar">
                <div class="editor-controls">
                    <select class="language-selector" data-for="{{ widget_id }}">
                        <option value="javascript" {{ 'selected' if language == 'javascript' else '' }}>JavaScript</option>
                        <option value="python" {{ 'selected' if language == 'python' else '' }}>Python</option>
                        <option value="html" {{ 'selected' if language == 'html' else '' }}>HTML</option>
                        <option value="css" {{ 'selected' if language == 'css' else '' }}>CSS</option>
                        <option value="json" {{ 'selected' if language == 'json' else '' }}>JSON</option>
                        <option value="sql" {{ 'selected' if language == 'sql' else '' }}>SQL</option>
                        <option value="xml" {{ 'selected' if language == 'xml' else '' }}>XML</option>
                        <option value="yaml" {{ 'selected' if language == 'yaml' else '' }}>YAML</option>
                        <option value="markdown" {{ 'selected' if language == 'markdown' else '' }}>Markdown</option>
                        <option value="typescript" {{ 'selected' if language == 'typescript' else '' }}>TypeScript</option>
                        <option value="java" {{ 'selected' if language == 'java' else '' }}>Java</option>
                        <option value="csharp" {{ 'selected' if language == 'csharp' else '' }}>C#</option>
                        <option value="php" {{ 'selected' if language == 'php' else '' }}>PHP</option>
                        <option value="ruby" {{ 'selected' if language == 'ruby' else '' }}>Ruby</option>
                        <option value="go" {{ 'selected' if language == 'go' else '' }}>Go</option>
                        <option value="rust" {{ 'selected' if language == 'rust' else '' }}>Rust</option>
                    </select>

                    <select class="theme-selector" data-for="{{ widget_id }}">
                        <option value="vs-light" {{ 'selected' if theme == 'vs-light' else '' }}>Light</option>
                        <option value="vs-dark" {{ 'selected' if theme == 'vs-dark' else '' }}>Dark</option>
                        <option value="hc-black" {{ 'selected' if theme == 'hc-black' else '' }}>High Contrast</option>
                    </select>

                    <div class="editor-actions">
                        {% if find_replace %}
                        <button type="button" class="btn-find-replace" title="Find & Replace (Ctrl+F)">
                            <i class="fa fa-search"></i>
                        </button>
                        {% endif %}

                        <button type="button" class="btn-format" title="Format Code (Shift+Alt+F)">
                            <i class="fa fa-magic"></i>
                        </button>

                        <button type="button" class="btn-fullscreen" title="Toggle Fullscreen (F11)">
                            <i class="fa fa-expand"></i>
                        </button>

                        <button type="button" class="btn-settings" title="Editor Settings">
                            <i class="fa fa-cog"></i>
                        </button>
                    </div>
                </div>

                <div class="editor-stats">
                    <span class="cursor-position">Ln 1, Col 1</span>
                    <span class="selection-info"></span>
                    <span class="encoding">UTF-8</span>
                </div>
            </div>

            <div id="{{ widget_id }}_editor" class="monaco-editor-container"
                 style="height: 400px; border: 1px solid #ccc;">
            </div>

            <div class="editor-footer">
                <div class="error-panel" style="display: none;">
                    <div class="error-header">
                        <strong>Problems</strong>
                        <button type="button" class="btn-close-errors">&times;</button>
                    </div>
                    <div class="error-list"></div>
                </div>
            </div>
        </div>

        <style>
        .code-editor-container {
            border: 1px solid #dee2e6;
            border-radius: 0.375rem;
            background: white;
            margin: 0.5rem 0;
        }

        .code-editor-toolbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem 0.75rem;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            border-radius: 0.375rem 0.375rem 0 0;
        }

        .editor-controls {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .language-selector,
        .theme-selector {
            padding: 0.25rem 0.5rem;
            border: 1px solid #ced4da;
            border-radius: 0.25rem;
            background: white;
            font-size: 0.875rem;
        }

        .editor-actions {
            display: flex;
            gap: 0.25rem;
        }

        .editor-actions button {
            padding: 0.25rem 0.5rem;
            border: 1px solid #ced4da;
            background: white;
            border-radius: 0.25rem;
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .editor-actions button:hover {
            background: #e9ecef;
            border-color: #adb5bd;
        }

        .editor-stats {
            display: flex;
            gap: 1rem;
            font-size: 0.75rem;
            color: #6c757d;
        }

        .monaco-editor-container {
            position: relative;
            overflow: hidden;
        }

        .editor-footer {
            border-top: 1px solid #dee2e6;
        }

        .error-panel {
            background: #fff3cd;
            border-top: 1px solid #ffeaa7;
            max-height: 150px;
            overflow-y: auto;
        }

        .error-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem 0.75rem;
            background: #fff3cd;
            border-bottom: 1px solid #ffeaa7;
            font-size: 0.875rem;
            font-weight: 500;
        }

        .btn-close-errors {
            background: none;
            border: none;
            font-size: 1.2rem;
            cursor: pointer;
            color: #856404;
        }

        .error-list {
            padding: 0.5rem 0.75rem;
        }

        .error-item {
            padding: 0.25rem 0;
            font-size: 0.875rem;
            color: #721c24;
        }

        .error-item .line-number {
            font-weight: 500;
            color: #495057;
        }

        /* Dark theme overrides */
        .code-editor-container.dark-theme {
            background: #1e1e1e;
            border-color: #444;
        }

        .code-editor-container.dark-theme .code-editor-toolbar {
            background: #2d2d30;
            border-color: #444;
            color: #cccccc;
        }

        .code-editor-container.dark-theme .language-selector,
        .code-editor-container.dark-theme .theme-selector {
            background: #3c3c3c;
            color: #cccccc;
            border-color: #555;
        }

        .code-editor-container.dark-theme .editor-actions button {
            background: #3c3c3c;
            color: #cccccc;
            border-color: #555;
        }

        .code-editor-container.dark-theme .editor-actions button:hover {
            background: #484848;
        }

        /* Fullscreen styles */
        .code-editor-fullscreen {
            position: fixed !important;
            top: 0 !important;
            left: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            z-index: 10000 !important;
            background: white;
        }

        .code-editor-fullscreen .monaco-editor-container {
            height: calc(100vh - 120px) !important;
        }
        </style>

        <script src="https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs/loader.min.js"></script>
        <script>
        (function() {
            const textareaId = '{{ widget_id }}';
            const editorContainer = document.getElementById(textareaId + '_editor');
            const textarea = document.getElementById(textareaId);
            const container = editorContainer.closest('.code-editor-container');

            let editor = null;
            let isFullscreen = false;

            // Configure Monaco Editor
            require.config({ paths: { vs: 'https://cdnjs.cloudflare.com/ajax/libs/monaco-editor/0.44.0/min/vs' }});

            require(['vs/editor/editor.main'], function() {
                // Initialize Monaco Editor
                editor = monaco.editor.create(editorContainer, {
                    value: textarea.value || '',
                    language: '{{ language }}',
                    theme: '{{ theme }}',
                    fontSize: {{ font_size }},
                    tabSize: {{ tab_size }},
                    wordWrap: {{ 'true' if word_wrap else 'false' }},
                    lineNumbers: {{ 'true' if line_numbers else 'false' }},
                    minimap: { enabled: {{ 'true' if minimap else 'false' }} },
                    automaticLayout: true,
                    scrollBeyondLastLine: false,
                    renderWhitespace: 'selection',
                    bracketPairColorization: { enabled: {{ 'true' if bracket_matching else 'false' }} },
                    foldingStrategy: '{{ "auto" if folding else "never" }}',
                    readOnly: {{ 'true' if readonly else 'false' }},
                    quickSuggestions: {{ 'true' if auto_complete else 'false' }},
                    parameterHints: { enabled: {{ 'true' if auto_complete else 'false' }} },
                    suggestOnTriggerCharacters: {{ 'true' if auto_complete else 'false' }},
                    acceptSuggestionOnEnter: '{{ "on" if auto_complete else "off" }}',
                    multiCursorModifier: '{{ "ctrlCmd" if multiple_cursors else "none" }}'
                });

                // Sync editor content with textarea
                function syncToTextarea() {
                    textarea.value = editor.getValue();
                    textarea.dispatchEvent(new Event('input', { bubbles: true }));
                    textarea.dispatchEvent(new Event('change', { bubbles: true }));
                }

                editor.onDidChangeModelContent(syncToTextarea);

                // Update cursor position
                function updateCursorPosition() {
                    const position = editor.getPosition();
                    const cursorPosEl = container.querySelector('.cursor-position');
                    if (cursorPosEl && position) {
                        cursorPosEl.textContent = `Ln ${position.lineNumber}, Col ${position.column}`;
                    }
                }

                editor.onDidChangeCursorPosition(updateCursorPosition);

                // Update selection info
                function updateSelectionInfo() {
                    const selection = editor.getSelection();
                    const selectionInfoEl = container.querySelector('.selection-info');
                    if (selectionInfoEl && selection && !selection.isEmpty()) {
                        const selectionLength = editor.getModel().getValueInRange(selection).length;
                        selectionInfoEl.textContent = `(${selectionLength} selected)`;
                    } else if (selectionInfoEl) {
                        selectionInfoEl.textContent = '';
                    }
                }

                editor.onDidChangeCursorSelection(updateSelectionInfo);

                // Language selector
                const languageSelector = container.querySelector('.language-selector');
                languageSelector.addEventListener('change', (e) => {
                    monaco.editor.setModelLanguage(editor.getModel(), e.target.value);
                });

                // Theme selector
                const themeSelector = container.querySelector('.theme-selector');
                themeSelector.addEventListener('change', (e) => {
                    monaco.editor.setTheme(e.target.value);

                    // Update container theme class
                    container.classList.toggle('dark-theme',
                        e.target.value === 'vs-dark' || e.target.value === 'hc-black');
                });

                // Find & Replace
                const findReplaceBtn = container.querySelector('.btn-find-replace');
                if (findReplaceBtn) {
                    findReplaceBtn.addEventListener('click', () => {
                        editor.trigger('keyboard', 'actions.find');
                    });
                }

                // Format code
                const formatBtn = container.querySelector('.btn-format');
                formatBtn.addEventListener('click', () => {
                    editor.trigger('keyboard', 'editor.action.formatDocument');
                });

                // Fullscreen toggle
                const fullscreenBtn = container.querySelector('.btn-fullscreen');
                fullscreenBtn.addEventListener('click', () => {
                    isFullscreen = !isFullscreen;

                    if (isFullscreen) {
                        container.classList.add('code-editor-fullscreen');
                        fullscreenBtn.innerHTML = '<i class="fa fa-compress"></i>';
                        fullscreenBtn.title = 'Exit Fullscreen (ESC)';
                    } else {
                        container.classList.remove('code-editor-fullscreen');
                        fullscreenBtn.innerHTML = '<i class="fa fa-expand"></i>';
                        fullscreenBtn.title = 'Toggle Fullscreen (F11)';
                    }

                    // Trigger editor resize
                    setTimeout(() => editor.layout(), 100);
                });

                // ESC key to exit fullscreen
                document.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape' && isFullscreen) {
                        fullscreenBtn.click();
                    }
                });

                // Error handling and linting
                {% if linting %}
                function showErrors(errors) {
                    const errorPanel = container.querySelector('.error-panel');
                    const errorList = container.querySelector('.error-list');

                    if (errors.length > 0) {
                        errorList.innerHTML = errors.map(error =>
                            `<div class="error-item">
                                <span class="line-number">Line ${error.startLineNumber}:</span>
                                ${error.message}
                            </div>`
                        ).join('');
                        errorPanel.style.display = 'block';
                    } else {
                        errorPanel.style.display = 'none';
                    }
                }

                // Listen for model markers (errors/warnings)
                editor.onDidChangeModelDecorations(() => {
                    const model = editor.getModel();
                    const markers = monaco.editor.getModelMarkers({ resource: model.uri });
                    showErrors(markers.filter(marker => marker.severity >= 8)); // Errors only
                });
                {% endif %}

                // Close error panel
                const closeErrorsBtn = container.querySelector('.btn-close-errors');
                if (closeErrorsBtn) {
                    closeErrorsBtn.addEventListener('click', () => {
                        container.querySelector('.error-panel').style.display = 'none';
                    });
                }

                // Settings dialog (placeholder)
                const settingsBtn = container.querySelector('.btn-settings');
                settingsBtn.addEventListener('click', () => {
                    alert('Editor settings dialog would open here. Available shortcuts:\\n\\n' +
                          'Ctrl+F: Find\\n' +
                          'Ctrl+H: Replace\\n' +
                          'Shift+Alt+F: Format\\n' +
                          'F11: Fullscreen\\n' +
                          'Ctrl+D: Add selection to next match\\n' +
                          'Alt+Click: Add cursor');
                });

                // Initialize state
                updateCursorPosition();
                updateSelectionInfo();

                // Apply initial theme
                if ('{{ theme }}' === 'vs-dark' || '{{ theme }}' === 'hc-black') {
                    container.classList.add('dark-theme');
                }
            });
        })();
        </script>
        """

        return Markup(render_template_string(template,
            textarea_html=textarea_html,
            widget_id=widget_id,
            field=field,
            language=self.language,
            theme=self.theme,
            font_size=self.font_size,
            tab_size=self.tab_size,
            word_wrap=self.word_wrap,
            line_numbers=self.line_numbers,
            minimap=self.minimap,
            auto_complete=self.auto_complete,
            bracket_matching=self.bracket_matching,
            folding=self.folding,
            find_replace=self.find_replace,
            multiple_cursors=self.multiple_cursors,
            linting=self.linting,
            readonly=self.readonly,
            _=gettext
        ))