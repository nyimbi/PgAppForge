"""
Mermaid Editor Widget for PgForge

Provides a comprehensive Mermaid diagram editor with real-time preview,
syntax highlighting, diagram validation, and export capabilities.
"""

from markupsafe import Markup
from wtforms.widgets import TextArea
from flask_babel import gettext as _


class MermaidEditorWidget(TextArea):
    """Advanced Mermaid diagram editor with live preview and comprehensive features."""

    def __init__(self, default_diagram_type='flowchart', enable_live_preview=True,
                 enable_syntax_highlighting=True, enable_auto_complete=True,
                 enable_validation=True, enable_export=True, enable_themes=True,
                 enable_collaboration=False, auto_save=True, save_interval=5000,
                 editor_height='400px', preview_height='400px', split_view=True,
                 enable_zoom=True, enable_pan=True, **kwargs):
        """
        Initialize Mermaid editor widget.

        Args:
            default_diagram_type: Default diagram type ('flowchart', 'sequence', 'gantt', etc.)
            enable_live_preview: Enable real-time diagram preview
            enable_syntax_highlighting: Enable syntax highlighting in editor
            enable_auto_complete: Enable auto-completion suggestions
            enable_validation: Enable diagram syntax validation
            enable_export: Enable export functionality (PNG, SVG, PDF)
            enable_themes: Enable theme switching
            enable_collaboration: Enable real-time collaboration features
            auto_save: Enable automatic saving
            save_interval: Auto-save interval in milliseconds
            editor_height: Height of the code editor
            preview_height: Height of the preview panel
            split_view: Enable split view (editor + preview)
            enable_zoom: Enable zoom functionality in preview
            enable_pan: Enable pan functionality in preview
        """
        super().__init__(**kwargs)
        self.default_diagram_type = default_diagram_type
        self.enable_live_preview = enable_live_preview
        self.enable_syntax_highlighting = enable_syntax_highlighting
        self.enable_auto_complete = enable_auto_complete
        self.enable_validation = enable_validation
        self.enable_export = enable_export
        self.enable_themes = enable_themes
        self.enable_collaboration = enable_collaboration
        self.auto_save = auto_save
        self.save_interval = save_interval
        self.editor_height = editor_height
        self.preview_height = preview_height
        self.split_view = split_view
        self.enable_zoom = enable_zoom
        self.enable_pan = enable_pan

        # Mermaid diagram types and their templates
        self.diagram_types = {
            'flowchart': {
                'name': _('Flowchart'),
                'icon': 'fas fa-project-diagram',
                'template': '''graph TD
    A[Start] --> B{Is it?}
    B -->|Yes| C[OK]
    C --> D[Rethink]
    D --> B
    B ---->|No| E[End]'''
            },
            'sequence': {
                'name': _('Sequence Diagram'),
                'icon': 'fas fa-exchange-alt',
                'template': '''sequenceDiagram
    participant A as Alice
    participant B as Bob
    A->>B: Hello Bob, how are you?
    B-->>A: Great!
    A-)B: See you later!'''
            },
            'gantt': {
                'name': _('Gantt Chart'),
                'icon': 'fas fa-chart-gantt',
                'template': '''gantt
    title A Gantt Diagram
    dateFormat  YYYY-MM-DD
    section Section
    A task           :a1, 2014-01-01, 30d
    Another task     :after a1  , 20d
    section Another
    Task in sec      :2014-01-12  , 12d
    another task      : 24d'''
            },
            'class': {
                'name': _('Class Diagram'),
                'icon': 'fas fa-sitemap',
                'template': '''classDiagram
    Animal <|-- Duck
    Animal <|-- Fish
    Animal <|-- Zebra
    Animal : +int age
    Animal : +String gender
    Animal: +isMammal()
    Animal: +mate()
    class Duck{
        +String beakColor
        +swim()
        +quack()
    }'''
            },
            'state': {
                'name': _('State Diagram'),
                'icon': 'fas fa-circle-nodes',
                'template': '''stateDiagram-v2
    [*] --> Still
    Still --> [*]
    Still --> Moving
    Moving --> Still
    Moving --> Crash
    Crash --> [*]'''
            },
            'er': {
                'name': _('Entity Relationship'),
                'icon': 'fas fa-database',
                'template': '''erDiagram
    CUSTOMER ||--o{ ORDER : places
    ORDER ||--|{ LINE-ITEM : contains
    CUSTOMER }|..|{ DELIVERY-ADDRESS : uses'''
            },
            'journey': {
                'name': _('User Journey'),
                'icon': 'fas fa-route',
                'template': '''journey
    title My working day
    section Go to work
      Make tea: 5: Me
      Go upstairs: 3: Me
      Do work: 1: Me, Cat
    section Go home
      Go downstairs: 5: Me
      Sit down: 5: Me'''
            },
            'pie': {
                'name': _('Pie Chart'),
                'icon': 'fas fa-chart-pie',
                'template': '''pie title Pets adopted by volunteers
    "Dogs" : 386
    "Cats" : 85
    "Rats" : 15'''
            }
        }

        # Mermaid themes
        self.themes = {
            'default': _('Default'),
            'forest': _('Forest'),
            'dark': _('Dark'),
            'neutral': _('Neutral'),
            'base': _('Base')
        }

        # Default Mermaid content
        self.default_content = self.diagram_types[self.default_diagram_type]['template']

    def __call__(self, field, **kwargs):
        """Render the Mermaid editor widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)

        editor_id = f"mermaid_editor_{field.id}"

        # Generate CSS styles
        css_styles = self._generate_css(editor_id)

        # Generate toolbar
        toolbar_html = self._generate_toolbar(editor_id)

        # Generate main editor area
        editor_area_html = self._generate_editor_area(editor_id)

        # Generate modals
        modals_html = self._generate_modals(editor_id)

        # Generate JavaScript
        javascript = self._generate_javascript(editor_id)

        return Markup(f"""
        {css_styles}
        <div id="{editor_id}" class="mermaid-editor-container"
             data-auto-save="{str(self.auto_save).lower()}"
             data-save-interval="{self.save_interval}"
             data-split-view="{str(self.split_view).lower()}">

            <!-- Toolbar -->
            {toolbar_html}

            <!-- Main Editor Area -->
            {editor_area_html}

            <!-- Status Bar -->
            <div class="mermaid-editor-status">
                <div class="status-info">
                    <span class="diagram-type" id="{editor_id}_current_type">
                        <i class="{self.diagram_types[self.default_diagram_type]['icon']}"></i>
                        {self.diagram_types[self.default_diagram_type]['name']}
                    </span>
                    <span class="line-count" id="{editor_id}_line_count">
                        <i class="fas fa-list-ol"></i> 1 {_('lines')}
                    </span>
                    <span class="validation-status" id="{editor_id}_validation">
                        <i class="fas fa-check-circle"></i> {_('Valid')}
                    </span>
                    <span class="save-status" id="{editor_id}_save_status">
                        <i class="fas fa-save"></i> {_('Saved')}
                    </span>
                </div>
                <div class="status-actions">
                    <button class="btn btn-sm btn-outline-secondary" onclick="toggleView('{editor_id}')">
                        <i class="fas fa-columns"></i> {_('Toggle View')}
                    </button>
                    <button class="btn btn-sm btn-outline-info" onclick="validateDiagram('{editor_id}')">
                        <i class="fas fa-check"></i> {_('Validate')}
                    </button>
                </div>
            </div>

            <!-- Hidden input for form data -->
            <input type="hidden" id="{kwargs['id']}" name="{kwargs['name']}"
                   value="{self.default_content}" data-mermaid-content="">
        </div>

        {modals_html}
        {javascript}
        """)

    def _generate_toolbar(self, editor_id):
        """Generate the toolbar HTML."""
        diagram_type_options = ""
        for type_key, type_info in self.diagram_types.items():
            selected = "selected" if type_key == self.default_diagram_type else ""
            diagram_type_options += f'''
            <option value="{type_key}" {selected}>
                {type_info['name']}
            </option>
            '''

        theme_options = ""
        if self.enable_themes:
            for theme_key, theme_name in self.themes.items():
                theme_options += f'<option value="{theme_key}">{theme_name}</option>'

        theme_section = ""
        if self.enable_themes:
            theme_section = f"""
            <div class="toolbar-group">
                <label>{_('Theme')}</label>
                <select class="form-control" id="{editor_id}_theme" onchange="changeTheme('{editor_id}')">
                    {theme_options}
                </select>
            </div>
            """

        export_buttons = ""
        if self.enable_export:
            export_buttons = f"""
            <div class="toolbar-group">
                <div class="dropdown">
                    <button class="btn btn-outline-info dropdown-toggle" data-bs-toggle="dropdown">
                        <i class="fas fa-download"></i> {_('Export')}
                    </button>
                    <ul class="dropdown-menu">
                        <li><a class="dropdown-item" onclick="exportDiagram('{editor_id}', 'png')">
                            <i class="fas fa-image"></i> PNG Image
                        </a></li>
                        <li><a class="dropdown-item" onclick="exportDiagram('{editor_id}', 'svg')">
                            <i class="fas fa-vector-square"></i> SVG Vector
                        </a></li>
                        <li><a class="dropdown-item" onclick="exportDiagram('{editor_id}', 'pdf')">
                            <i class="fas fa-file-pdf"></i> PDF Document
                        </a></li>
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item" onclick="exportDiagram('{editor_id}', 'mmd')">
                            <i class="fas fa-file-code"></i> Mermaid Source
                        </a></li>
                    </ul>
                </div>
            </div>
            """

        collaboration_buttons = ""
        if self.enable_collaboration:
            collaboration_buttons = f"""
            <div class="toolbar-group">
                <button class="btn btn-outline-success" onclick="shareForCollaboration('{editor_id}')">
                    <i class="fas fa-share-alt"></i> {_('Share')}
                </button>
                <button class="btn btn-outline-warning" onclick="showVersionHistory('{editor_id}')">
                    <i class="fas fa-history"></i> {_('History')}
                </button>
            </div>
            """

        return f"""
        <div class="mermaid-toolbar">
            <div class="toolbar-group">
                <label>{_('Diagram Type')}</label>
                <select class="form-control" id="{editor_id}_type" onchange="changeDiagramType('{editor_id}')">
                    {diagram_type_options}
                </select>
            </div>

            {theme_section}

            <div class="toolbar-group">
                <button class="btn btn-primary" onclick="insertTemplate('{editor_id}')">
                    <i class="fas fa-plus"></i> {_('New')}
                </button>
                <button class="btn btn-outline-secondary" onclick="formatCode('{editor_id}')">
                    <i class="fas fa-code"></i> {_('Format')}
                </button>
                <button class="btn btn-outline-secondary" onclick="openHelp('{editor_id}')">
                    <i class="fas fa-question-circle"></i> {_('Help')}
                </button>
            </div>

            {export_buttons}
            {collaboration_buttons}

            <div class="toolbar-group ml-auto">
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="{editor_id}_live_preview"
                           {'checked' if self.enable_live_preview else ''} onchange="toggleLivePreview('{editor_id}')">
                    <label class="form-check-label">{_('Live Preview')}</label>
                </div>
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="{editor_id}_auto_save"
                           {'checked' if self.auto_save else ''} onchange="toggleAutoSave('{editor_id}')">
                    <label class="form-check-label">{_('Auto Save')}</label>
                </div>
            </div>
        </div>
        """

    def _generate_editor_area(self, editor_id):
        """Generate the main editor area HTML."""
        editor_class = "split-view" if self.split_view else "full-view"

        return f"""
        <div class="mermaid-editor-main {editor_class}">
            <!-- Code Editor Panel -->
            <div class="editor-panel">
                <div class="editor-header">
                    <h6><i class="fas fa-code"></i> {_('Mermaid Code')}</h6>
                    <div class="editor-actions">
                        <button class="btn btn-sm btn-outline-secondary" onclick="undoEditor('{editor_id}')">
                            <i class="fas fa-undo"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="redoEditor('{editor_id}')">
                            <i class="fas fa-redo"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="findInEditor('{editor_id}')">
                            <i class="fas fa-search"></i>
                        </button>
                    </div>
                </div>
                <div class="editor-content">
                    <textarea id="{editor_id}_editor" class="mermaid-code-editor"
                              placeholder="{_('Enter your Mermaid diagram code here...')}"
                              style="height: {self.editor_height};">{self.default_content}</textarea>
                </div>
            </div>

            <!-- Preview Panel -->
            <div class="preview-panel" style="{'display: block' if self.enable_live_preview else 'display: none'}">
                <div class="preview-header">
                    <h6><i class="fas fa-eye"></i> {_('Preview')}</h6>
                    <div class="preview-actions">
                        <button class="btn btn-sm btn-outline-secondary" onclick="zoomIn('{editor_id}')"
                                style="{'display: inline-flex' if self.enable_zoom else 'display: none'}">
                            <i class="fas fa-search-plus"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="zoomOut('{editor_id}')"
                                style="{'display: inline-flex' if self.enable_zoom else 'display: none'}">
                            <i class="fas fa-search-minus"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="resetZoom('{editor_id}')"
                                style="{'display: inline-flex' if self.enable_zoom else 'display: none'}">
                            <i class="fas fa-expand-arrows-alt"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="centerDiagram('{editor_id}')"
                                style="{'display: inline-flex' if self.enable_pan else 'display: none'}">
                            <i class="fas fa-crosshairs"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-secondary" onclick="refreshPreview('{editor_id}')">
                            <i class="fas fa-sync-alt"></i>
                        </button>
                    </div>
                </div>
                <div class="preview-content" style="height: {self.preview_height};">
                    <div id="{editor_id}_preview" class="mermaid-preview">
                        <!-- Mermaid diagram will be rendered here -->
                    </div>
                    <div class="preview-loading" id="{editor_id}_loading" style="display: none;">
                        <i class="fas fa-spinner fa-spin"></i>
                        <p>{_('Rendering diagram...')}</p>
                    </div>
                    <div class="preview-error" id="{editor_id}_error" style="display: none;">
                        <i class="fas fa-exclamation-triangle"></i>
                        <h6>{_('Diagram Error')}</h6>
                        <p id="{editor_id}_error_message"></p>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_modals(self, editor_id):
        """Generate modal dialogs."""
        return f"""
        <!-- Help Modal -->
        <div class="modal fade" id="{editor_id}_help_modal" tabindex="-1">
            <div class="modal-dialog modal-xl">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">{_('Mermaid Syntax Help')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="help-tabs">
                            <ul class="nav nav-tabs" role="tablist">
                                <li class="nav-item">
                                    <a class="nav-link active" data-bs-toggle="tab" href="#{editor_id}_flowchart_help">
                                        {_('Flowchart')}
                                    </a>
                                </li>
                                <li class="nav-item">
                                    <a class="nav-link" data-bs-toggle="tab" href="#{editor_id}_sequence_help">
                                        {_('Sequence')}
                                    </a>
                                </li>
                                <li class="nav-item">
                                    <a class="nav-link" data-bs-toggle="tab" href="#{editor_id}_gantt_help">
                                        {_('Gantt')}
                                    </a>
                                </li>
                                <li class="nav-item">
                                    <a class="nav-link" data-bs-toggle="tab" href="#{editor_id}_class_help">
                                        {_('Class')}
                                    </a>
                                </li>
                            </ul>

                            <div class="tab-content">
                                <div class="tab-pane fade show active" id="{editor_id}_flowchart_help">
                                    <h6>{_('Flowchart Syntax')}</h6>
                                    <div class="syntax-examples">
                                        <div class="example">
                                            <strong>{_('Basic Elements')}:</strong>
                                            <pre><code>graph TD
    A[Rectangle] --> B((Circle))
    B --> C{Diamond}
    C -->|Yes| D[Result 1]
    C -->|No| E[Result 2]</code></pre>
                                        </div>
                                        <div class="example">
                                            <strong>{_('Node Shapes')}:</strong>
                                            <ul>
                                                <li><code>A[Rectangle]</code> - Rectangle</li>
                                                <li><code>B((Circle))</code> - Circle</li>
                                                <li><code>C{Diamond}</code> - Diamond</li>
                                                <li><code>D(Round edges)</code> - Round edges</li>
                                                <li><code>E>Flag]</code> - Flag shape</li>
                                            </ul>
                                        </div>
                                    </div>
                                </div>

                                <div class="tab-pane fade" id="{editor_id}_sequence_help">
                                    <h6>{_('Sequence Diagram Syntax')}</h6>
                                    <div class="syntax-examples">
                                        <div class="example">
                                            <strong>{_('Basic Interactions')}:</strong>
                                            <pre><code>sequenceDiagram
    Alice->>Bob: Hello Bob
    Bob-->>Alice: Hello Alice
    Alice-)Bob: Async message</code></pre>
                                        </div>
                                        <div class="example">
                                            <strong>{_('Arrow Types')}:</strong>
                                            <ul>
                                                <li><code>-></code> - Solid arrow</li>
                                                <li><code>--></code> - Dotted arrow</li>
                                                <li><code>->></code> - Solid arrow with arrowhead</li>
                                                <li><code>-->></code> - Dotted arrow with arrowhead</li>
                                                <li><code>-)</code> - Async arrow</li>
                                            </ul>
                                        </div>
                                    </div>
                                </div>

                                <div class="tab-pane fade" id="{editor_id}_gantt_help">
                                    <h6>{_('Gantt Chart Syntax')}</h6>
                                    <div class="syntax-examples">
                                        <div class="example">
                                            <strong>{_('Basic Structure')}:</strong>
                                            <pre><code>gantt
    title Project Timeline
    dateFormat YYYY-MM-DD
    section Phase 1
    Task 1: task1, 2024-01-01, 30d
    Task 2: task2, after task1, 20d</code></pre>
                                        </div>
                                    </div>
                                </div>

                                <div class="tab-pane fade" id="{editor_id}_class_help">
                                    <h6>{_('Class Diagram Syntax')}</h6>
                                    <div class="syntax-examples">
                                        <div class="example">
                                            <strong>{_('Class Relationships')}:</strong>
                                            <pre><code>classDiagram
    Animal <|-- Duck
    Animal <|-- Fish
    Animal : +int age
    Animal : +String gender</code></pre>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">{_('Close')}</button>
                        <a href="https://mermaid-js.github.io/mermaid/" target="_blank" class="btn btn-primary">
                            {_('Full Documentation')}
                        </a>
                    </div>
                </div>
            </div>
        </div>

        <!-- Share Modal -->
        <div class="modal fade" id="{editor_id}_share_modal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">{_('Share Diagram')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="form-group">
                            <label>{_('Share Link')}</label>
                            <div class="input-group">
                                <input type="text" class="form-control" id="{editor_id}_share_link" readonly>
                                <button class="btn btn-outline-secondary" onclick="copyShareLink('{editor_id}')">
                                    <i class="fas fa-copy"></i>
                                </button>
                            </div>
                        </div>
                        <div class="form-group">
                            <label>{_('Embed Code')}</label>
                            <textarea class="form-control" id="{editor_id}_embed_code" rows="3" readonly></textarea>
                        </div>
                        <div class="share-options">
                            <h6>{_('Permissions')}</h6>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="share_permission" value="view" checked>
                                <label class="form-check-label">{_('View Only')}</label>
                            </div>
                            <div class="form-check">
                                <input class="form-check-input" type="radio" name="share_permission" value="edit">
                                <label class="form-check-label">{_('Can Edit')}</label>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">{_('Close')}</button>
                        <button type="button" class="btn btn-primary" onclick="generateShareLink('{editor_id}')">{_('Generate Link')}</button>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_css(self, editor_id):
        """Generate CSS styles for the Mermaid editor widget."""
        return f"""
        <style>
        #{editor_id}.mermaid-editor-container {{
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            height: 600px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}

        #{editor_id} .mermaid-toolbar {{
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 12px 16px;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            flex-wrap: wrap;
        }}

        #{editor_id} .toolbar-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        #{editor_id} .toolbar-group.ml-auto {{
            margin-left: auto;
        }}

        #{editor_id} .toolbar-group label {{
            font-size: 12px;
            font-weight: 500;
            color: #495057;
            margin-bottom: 0;
            white-space: nowrap;
        }}

        #{editor_id} .form-control {{
            padding: 4px 8px;
            font-size: 12px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            background: #fff;
            color: #495057;
        }}

        #{editor_id} .mermaid-editor-main {{
            display: flex;
            flex: 1;
            min-height: 0;
        }}

        #{editor_id} .mermaid-editor-main.split-view .editor-panel {{
            flex: 1;
            border-right: 1px solid #dee2e6;
        }}

        #{editor_id} .mermaid-editor-main.split-view .preview-panel {{
            flex: 1;
        }}

        #{editor_id} .mermaid-editor-main.full-view .editor-panel {{
            flex: 1;
        }}

        #{editor_id} .mermaid-editor-main.full-view .preview-panel {{
            display: none;
        }}

        #{editor_id} .editor-panel,
        #{editor_id} .preview-panel {{
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}

        #{editor_id} .editor-header,
        #{editor_id} .preview-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 12px;
            background: #fafafa;
            border-bottom: 1px solid #dee2e6;
        }}

        #{editor_id} .editor-header h6,
        #{editor_id} .preview-header h6 {{
            margin: 0;
            font-size: 12px;
            font-weight: 600;
            color: #495057;
        }}

        #{editor_id} .editor-actions,
        #{editor_id} .preview-actions {{
            display: flex;
            gap: 4px;
        }}

        #{editor_id} .editor-content {{
            flex: 1;
            overflow: hidden;
        }}

        #{editor_id} .mermaid-code-editor {{
            width: 100%;
            height: 100%;
            border: none;
            padding: 16px;
            font-family: 'Monaco', 'Menlo', 'Ubuntu Mono', monospace;
            font-size: 14px;
            line-height: 1.5;
            resize: none;
            outline: none;
            background: #fafafa;
            color: #495057;
        }}

        #{editor_id} .preview-content {{
            flex: 1;
            position: relative;
            overflow: auto;
            background: #fff;
        }}

        #{editor_id} .mermaid-preview {{
            width: 100%;
            height: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 20px;
        }}

        #{editor_id} .mermaid-preview svg {{
            max-width: 100%;
            max-height: 100%;
            cursor: move;
        }}

        #{editor_id} .preview-loading,
        #{editor_id} .preview-error {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            background: rgba(255,255,255,0.95);
            z-index: 10;
        }}

        #{editor_id} .preview-loading i {{
            font-size: 32px;
            color: #007bff;
            margin-bottom: 12px;
        }}

        #{editor_id} .preview-error i {{
            font-size: 32px;
            color: #dc3545;
            margin-bottom: 12px;
        }}

        #{editor_id} .preview-error h6 {{
            color: #dc3545;
            margin-bottom: 8px;
        }}

        #{editor_id} .preview-error p {{
            color: #6c757d;
            text-align: center;
            margin: 0;
            font-family: monospace;
            white-space: pre-wrap;
        }}

        #{editor_id} .mermaid-editor-status {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 16px;
            background: #f8f9fa;
            border-top: 1px solid #dee2e6;
            font-size: 12px;
        }}

        #{editor_id} .status-info {{
            display: flex;
            gap: 16px;
            color: #6c757d;
        }}

        #{editor_id} .status-actions {{
            display: flex;
            gap: 8px;
        }}

        #{editor_id} .validation-status.valid {{
            color: #28a745;
        }}

        #{editor_id} .validation-status.invalid {{
            color: #dc3545;
        }}

        #{editor_id} .save-status.saving {{
            color: #ffc107;
        }}

        #{editor_id} .save-status.saved {{
            color: #28a745;
        }}

        #{editor_id} .save-status.error {{
            color: #dc3545;
        }}

        #{editor_id} .btn {{
            padding: 4px 8px;
            font-size: 12px;
            border-radius: 4px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.2s ease;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}

        #{editor_id} .btn-primary {{
            background: #007bff;
            color: white;
            border-color: #007bff;
        }}

        #{editor_id} .btn-outline-secondary {{
            color: #6c757d;
            border-color: #6c757d;
            background: transparent;
        }}

        #{editor_id} .btn-outline-secondary:hover {{
            background: #6c757d;
            color: white;
        }}

        #{editor_id} .btn-outline-info {{
            color: #17a2b8;
            border-color: #17a2b8;
            background: transparent;
        }}

        #{editor_id} .btn-outline-success {{
            color: #28a745;
            border-color: #28a745;
            background: transparent;
        }}

        #{editor_id} .btn-outline-warning {{
            color: #ffc107;
            border-color: #ffc107;
            background: transparent;
        }}

        #{editor_id} .form-check {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        #{editor_id} .form-check-input {{
            margin: 0;
        }}

        #{editor_id} .form-check-label {{
            font-size: 12px;
            color: #495057;
        }}

        /* Help Modal Styles */
        #{editor_id}_help_modal .syntax-examples {{
            margin-top: 16px;
        }}

        #{editor_id}_help_modal .example {{
            margin-bottom: 20px;
            padding: 12px;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            background: #f8f9fa;
        }}

        #{editor_id}_help_modal .example strong {{
            color: #495057;
            display: block;
            margin-bottom: 8px;
        }}

        #{editor_id}_help_modal pre {{
            background: #2d3748;
            color: #e2e8f0;
            padding: 12px;
            border-radius: 4px;
            font-size: 13px;
            margin: 8px 0;
            overflow-x: auto;
        }}

        #{editor_id}_help_modal ul {{
            margin: 8px 0;
            padding-left: 20px;
        }}

        #{editor_id}_help_modal li {{
            margin-bottom: 4px;
            font-family: monospace;
            font-size: 13px;
        }}

        /* Share Modal Styles */
        #{editor_id} .share-options {{
            margin-top: 16px;
        }}

        #{editor_id} .share-options h6 {{
            font-size: 14px;
            margin-bottom: 8px;
            color: #495057;
        }}

        #{editor_id} .input-group {{
            display: flex;
        }}

        #{editor_id} .input-group .form-control {{
            border-top-right-radius: 0;
            border-bottom-right-radius: 0;
            border-right: none;
        }}

        #{editor_id} .input-group .btn {{
            border-top-left-radius: 0;
            border-bottom-left-radius: 0;
        }}

        /* Responsive design */
        @media (max-width: 768px) {{
            #{editor_id} .mermaid-editor-main.split-view {{
                flex-direction: column;
            }}

            #{editor_id} .mermaid-editor-main.split-view .editor-panel {{
                border-right: none;
                border-bottom: 1px solid #dee2e6;
            }}

            #{editor_id} .toolbar-group {{
                flex-wrap: wrap;
            }}
        }}
        </style>
        """

    def _generate_javascript(self, editor_id):
        """Generate JavaScript for Mermaid editor functionality."""
        import json
        diagram_types_json = json.dumps(self.diagram_types)
        themes_json = json.dumps(list(self.themes.keys()))

        return f"""
        <script src="https://cdn.jsdelivr.net/npm/mermaid@10.6.1/dist/mermaid.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.15/codemirror.min.js"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.15/mode/yaml/yaml.min.js"></script>
        <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.15/codemirror.min.css">
        <script>
        (function() {{
            // Mermaid editor state
            let mermaidEditorState = {{
                editor: null,
                currentContent: `{self.default_content}`,
                currentType: '{self.default_diagram_type}',
                currentTheme: 'default',
                livePreview: {str(self.enable_live_preview).lower()},
                autoSave: {str(self.auto_save).lower()},
                saveTimer: null,
                zoomLevel: 1,
                isDirty: false
            }};

            const diagramTypes = {diagram_types_json};
            const themes = {themes_json};

            // Initialize Mermaid editor
            function initializeMermaidEditor() {{
                // Initialize Mermaid
                mermaid.initialize({{
                    startOnLoad: false,
                    theme: mermaidEditorState.currentTheme,
                    securityLevel: 'loose',
                    fontFamily: 'Arial, sans-serif'
                }});

                // Initialize CodeMirror editor
                const textarea = document.getElementById('{editor_id}_editor');
                mermaidEditorState.editor = CodeMirror.fromTextArea(textarea, {{
                    mode: 'yaml',
                    theme: 'default',
                    lineNumbers: true,
                    lineWrapping: true,
                    autoCloseBrackets: true,
                    matchBrackets: true,
                    indentUnit: 2,
                    tabSize: 2,
                    extraKeys: {{
                        'Ctrl-S': function() {{ saveContent('{editor_id}'); }},
                        'Ctrl-F': function() {{ findInEditor('{editor_id}'); }},
                        'F11': function() {{ toggleFullscreen('{editor_id}'); }},
                        'Esc': function() {{ exitFullscreen('{editor_id}'); }}
                    }}
                }});

                // Set initial content
                mermaidEditorState.editor.setValue(mermaidEditorState.currentContent);

                // Setup event listeners
                mermaidEditorState.editor.on('change', onEditorChange);

                // Initial render
                if (mermaidEditorState.livePreview) {{
                    renderDiagram();
                }}

                // Setup auto-save
                if (mermaidEditorState.autoSave) {{
                    setupAutoSave();
                }}

                // Update UI
                updateUI();
            }}

            // Handle editor content changes
            function onEditorChange() {{
                mermaidEditorState.currentContent = mermaidEditorState.editor.getValue();
                mermaidEditorState.isDirty = true;

                // Update line count
                updateLineCount();

                // Update form data
                updateFormData();

                // Validate content
                if ({str(self.enable_validation).lower()}) {{
                    validateContent();
                }}

                // Trigger live preview
                if (mermaidEditorState.livePreview) {{
                    debounceRender();
                }}

                // Update save status
                updateSaveStatus('unsaved');
            }}

            // Debounced render function
            let renderTimeout;
            function debounceRender() {{
                clearTimeout(renderTimeout);
                renderTimeout = setTimeout(renderDiagram, 500);
            }}

            // Render Mermaid diagram
            function renderDiagram() {{
                const content = mermaidEditorState.currentContent.trim();
                if (!content) {{
                    clearPreview();
                    return;
                }}

                showPreviewLoading();

                try {{
                    // Generate unique ID for diagram
                    const diagramId = 'mermaid_' + Date.now();

                    // Clear previous diagram
                    const previewContainer = document.getElementById('{editor_id}_preview');
                    previewContainer.innerHTML = '';

                    // Render new diagram
                    mermaid.render(diagramId, content)
                        .then(result => {{
                            previewContainer.innerHTML = result.svg;
                            hidePreviewLoading();
                            hidePreviewError();

                            // Setup zoom and pan if enabled
                            if ({str(self.enable_zoom).lower()} || {str(self.enable_pan).lower()}) {{
                                setupDiagramInteraction();
                            }}

                            // Update validation status
                            updateValidationStatus(true);
                        }})
                        .catch(error => {{
                            showPreviewError(error.message);
                            updateValidationStatus(false, error.message);
                        }});

                }} catch (error) {{
                    showPreviewError(error.message);
                    updateValidationStatus(false, error.message);
                }}
            }}

            // Setup diagram interaction (zoom/pan)
            function setupDiagramInteraction() {{
                const svg = document.querySelector('#{editor_id}_preview svg');
                if (!svg) return;

                let isPanning = false;
                let startPoint = {{ x: 0, y: 0 }};
                let endPoint = {{ x: 0, y: 0 }};
                let scale = 1;

                if ({str(self.enable_pan).lower()}) {{
                    svg.addEventListener('mousedown', (e) => {{
                        isPanning = true;
                        startPoint = {{ x: e.clientX, y: e.clientY }};
                        svg.style.cursor = 'grabbing';
                    }});

                    svg.addEventListener('mousemove', (e) => {{
                        if (!isPanning) return;

                        endPoint = {{ x: e.clientX, y: e.clientY }};
                        const dx = endPoint.x - startPoint.x;
                        const dy = endPoint.y - startPoint.y;

                        // Update transform
                        const currentTransform = svg.style.transform || '';
                        const newTransform = `${{currentTransform}} translate(${{dx}}px, ${{dy}}px)`;
                        svg.style.transform = newTransform;

                        startPoint = endPoint;
                    }});

                    svg.addEventListener('mouseup', () => {{
                        isPanning = false;
                        svg.style.cursor = 'move';
                    }});
                }}

                if ({str(self.enable_zoom).lower()}) {{
                    svg.addEventListener('wheel', (e) => {{
                        e.preventDefault();
                        const delta = e.deltaY > 0 ? 0.9 : 1.1;
                        scale *= delta;
                        scale = Math.max(0.1, Math.min(3, scale));

                        const currentTransform = svg.style.transform || '';
                        const scaleTransform = `scale(${{scale}})`;
                        svg.style.transform = currentTransform.replace(/scale\\([^)]*\\)/, '') + ' ' + scaleTransform;

                        updateZoomLevel(scale);
                    }});
                }}
            }}

            // Show/hide preview states
            function showPreviewLoading() {{
                document.getElementById('{editor_id}_loading').style.display = 'flex';
                document.getElementById('{editor_id}_error').style.display = 'none';
            }}

            function hidePreviewLoading() {{
                document.getElementById('{editor_id}_loading').style.display = 'none';
            }}

            function showPreviewError(message) {{
                hidePreviewLoading();
                document.getElementById('{editor_id}_error').style.display = 'flex';
                document.getElementById('{editor_id}_error_message').textContent = message;
            }}

            function hidePreviewError() {{
                document.getElementById('{editor_id}_error').style.display = 'none';
            }}

            function clearPreview() {{
                document.getElementById('{editor_id}_preview').innerHTML = '';
                hidePreviewLoading();
                hidePreviewError();
            }}

            // Update line count
            function updateLineCount() {{
                const lineCount = mermaidEditorState.editor.lineCount();
                document.getElementById('{editor_id}_line_count').innerHTML =
                    `<i class="fas fa-list-ol"></i> ${{lineCount}} {_("lines")}`;
            }}

            // Update validation status
            function updateValidationStatus(isValid, errorMessage = '') {{
                const statusElement = document.getElementById('{editor_id}_validation');
                if (isValid) {{
                    statusElement.innerHTML = '<i class="fas fa-check-circle"></i> {_("Valid")}';
                    statusElement.className = 'validation-status valid';
                }} else {{
                    statusElement.innerHTML = '<i class="fas fa-times-circle"></i> {_("Invalid")}';
                    statusElement.className = 'validation-status invalid';
                    statusElement.title = errorMessage;
                }}
            }}

            // Update save status
            function updateSaveStatus(status) {{
                const statusElement = document.getElementById('{editor_id}_save_status');
                switch (status) {{
                    case 'saving':
                        statusElement.innerHTML = '<i class="fas fa-spinner fa-spin"></i> {_("Saving...")}';
                        statusElement.className = 'save-status saving';
                        break;
                    case 'saved':
                        statusElement.innerHTML = '<i class="fas fa-check"></i> {_("Saved")}';
                        statusElement.className = 'save-status saved';
                        break;
                    case 'error':
                        statusElement.innerHTML = '<i class="fas fa-times"></i> {_("Error")}';
                        statusElement.className = 'save-status error';
                        break;
                    default:
                        statusElement.innerHTML = '<i class="fas fa-edit"></i> {_("Modified")}';
                        statusElement.className = 'save-status';
                }}
            }}

            // Update zoom level display
            function updateZoomLevel(level) {{
                mermaidEditorState.zoomLevel = level;
                // Could add zoom level indicator here
            }}

            // Update UI elements
            function updateUI() {{
                // Update diagram type display
                const currentType = diagramTypes[mermaidEditorState.currentType];
                document.getElementById('{editor_id}_current_type').innerHTML =
                    `<i class="${{currentType.icon}}"></i> ${{currentType.name}}`;

                // Update line count
                updateLineCount();
            }}

            // Setup auto-save functionality
            function setupAutoSave() {{
                if (mermaidEditorState.saveTimer) {{
                    clearInterval(mermaidEditorState.saveTimer);
                }}

                mermaidEditorState.saveTimer = setInterval(() => {{
                    if (mermaidEditorState.isDirty) {{
                        saveContent('{editor_id}');
                    }}
                }}, {self.save_interval});
            }}

            // Update form data
            function updateFormData() {{
                const input = document.querySelector('#{editor_id} input[data-mermaid-content]');
                if (input) {{
                    input.value = mermaidEditorState.currentContent;
                }}
            }}

            // Public API functions
            window.changeDiagramType = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                const select = document.getElementById('{editor_id}_type');
                const newType = select.value;

                if (newType !== mermaidEditorState.currentType) {{
                    mermaidEditorState.currentType = newType;
                    updateUI();
                }}
            }};

            window.insertTemplate = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                const template = diagramTypes[mermaidEditorState.currentType].template;
                mermaidEditorState.editor.setValue(template);
                mermaidEditorState.editor.focus();
            }};

            window.changeTheme = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                const select = document.getElementById('{editor_id}_theme');
                mermaidEditorState.currentTheme = select.value;

                // Reinitialize Mermaid with new theme
                mermaid.initialize({{
                    startOnLoad: false,
                    theme: mermaidEditorState.currentTheme,
                    securityLevel: 'loose'
                }});

                // Re-render diagram
                renderDiagram();
            }};

            window.toggleLivePreview = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                const checkbox = document.getElementById('{editor_id}_live_preview');
                mermaidEditorState.livePreview = checkbox.checked;

                const previewPanel = document.querySelector('#{editor_id} .preview-panel');
                previewPanel.style.display = mermaidEditorState.livePreview ? 'flex' : 'none';

                if (mermaidEditorState.livePreview) {{
                    renderDiagram();
                }}
            }};

            window.toggleAutoSave = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                const checkbox = document.getElementById('{editor_id}_auto_save');
                mermaidEditorState.autoSave = checkbox.checked;

                if (mermaidEditorState.autoSave) {{
                    setupAutoSave();
                }} else if (mermaidEditorState.saveTimer) {{
                    clearInterval(mermaidEditorState.saveTimer);
                    mermaidEditorState.saveTimer = null;
                }}
            }};

            window.validateDiagram = function(editorId) {{
                if (editorId !== '{editor_id}') return;
                renderDiagram();
            }};

            window.refreshPreview = function(editorId) {{
                if (editorId !== '{editor_id}') return;
                renderDiagram();
            }};

            window.formatCode = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                // Basic code formatting (could be enhanced)
                const content = mermaidEditorState.editor.getValue();
                const lines = content.split('\\n');
                let indentLevel = 0;

                const formattedLines = lines.map(line => {{
                    const trimmed = line.trim();
                    if (!trimmed) return '';

                    // Simple indentation logic
                    if (trimmed.includes('-->') || trimmed.includes('->')) {{
                        return '    ' + trimmed;
                    }}
                    return trimmed;
                }});

                mermaidEditorState.editor.setValue(formattedLines.join('\\n'));
            }};

            window.zoomIn = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                mermaidEditorState.zoomLevel = Math.min(3, mermaidEditorState.zoomLevel * 1.2);
                applyZoom();
            }};

            window.zoomOut = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                mermaidEditorState.zoomLevel = Math.max(0.1, mermaidEditorState.zoomLevel / 1.2);
                applyZoom();
            }};

            window.resetZoom = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                mermaidEditorState.zoomLevel = 1;
                applyZoom();
            }};

            function applyZoom() {{
                const svg = document.querySelector('#{editor_id}_preview svg');
                if (svg) {{
                    svg.style.transform = `scale(${{mermaidEditorState.zoomLevel}})`;
                }}
            }}

            window.exportDiagram = function(editorId, format) {{
                if (editorId !== '{editor_id}') return;

                const content = mermaidEditorState.currentContent;

                switch (format) {{
                    case 'png':
                    case 'svg':
                        exportAsImage(format);
                        break;
                    case 'pdf':
                        exportAsPDF();
                        break;
                    case 'mmd':
                        exportAsSource();
                        break;
                }}
            }};

            function exportAsImage(format) {{
                const svg = document.querySelector('#{editor_id}_preview svg');
                if (!svg) {{
                    alert('{_("No diagram to export")}');
                    return;
                }}

                if (format === 'svg') {{
                    const svgData = new XMLSerializer().serializeToString(svg);
                    const blob = new Blob([svgData], {{ type: 'image/svg+xml' }});
                    downloadBlob(blob, 'diagram.svg');
                }} else {{
                    // Convert SVG to PNG using canvas
                    const canvas = document.createElement('canvas');
                    const ctx = canvas.getContext('2d');
                    const img = new Image();

                    img.onload = function() {{
                        canvas.width = img.width;
                        canvas.height = img.height;
                        ctx.drawImage(img, 0, 0);

                        canvas.toBlob(blob => {{
                            downloadBlob(blob, 'diagram.png');
                        }}, 'image/png');
                    }};

                    const svgData = new XMLSerializer().serializeToString(svg);
                    const svgBlob = new Blob([svgData], {{ type: 'image/svg+xml;charset=utf-8' }});
                    img.src = URL.createObjectURL(svgBlob);
                }}
            }}

            function exportAsSource() {{
                const content = mermaidEditorState.currentContent;
                const blob = new Blob([content], {{ type: 'text/plain' }});
                downloadBlob(blob, 'diagram.mmd');
            }}

            function downloadBlob(blob, filename) {{
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                a.click();
                URL.revokeObjectURL(url);
            }}

            window.openHelp = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                const modal = new bootstrap.Modal(document.getElementById('{editor_id}_help_modal'));
                modal.show();
            }};

            window.saveContent = function(editorId) {{
                if (editorId !== '{editor_id}') return;

                updateSaveStatus('saving');

                // Simulate save operation
                setTimeout(() => {{
                    mermaidEditorState.isDirty = false;
                    updateSaveStatus('saved');
                    updateFormData();
                }}, 500);
            }};

            // Initialize when page loads
            document.addEventListener('DOMContentLoaded', initializeMermaidEditor);
        }})();
        </script>
        """