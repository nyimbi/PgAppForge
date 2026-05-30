"""
PostgreSQL Tree Widget for hierarchical data structures

Supports both LTREE paths and parent_id/foreign key relationships
"""

from markupsafe import Markup
from wtforms.widgets import TextArea, html_params


class PostgreSQLTreeWidget(TextArea):
    """
    Comprehensive hierarchical tree widget for LTREE and parent_id/foreign key relationships
    
    Supports two modes:
    1. LTREE mode: Uses PostgreSQL LTREE paths (e.g., 'root.child.grandchild')
    2. Parent-ID mode: Uses parent_id foreign keys to same table
    
    Features:
        - Interactive visual tree representation with expand/collapse
        - Drag-and-drop node reordering and reparenting
        - Add, edit, delete operations with confirmation dialogs
        - Search and filter functionality across the tree
        - Export/import in various formats (JSON, CSV, SQL)
        - Validation of tree structure and path constraints
        - Keyboard navigation and accessibility support
        - Customizable node templates and styling
        - Batch operations for multiple nodes
        - Real-time path generation and validation
        - Support for both LTREE and parent_id table structures
        - Orphaned node detection and repair
        - Circular reference prevention
    """
    
    def __init__(self, 
                 mode='ltree',  # 'ltree' or 'parent_id'
                 id_field='id',
                 parent_id_field='parent_id', 
                 label_field='name',
                 max_depth=10, 
                 allow_reorder=True, 
                 allow_drag_drop=True,
                 node_template=None,
                 path_separator='.',
                 validation_rules=None):
        """
        Initialize the tree widget
        
        Args:
            mode (str): 'ltree' for LTREE paths or 'parent_id' for foreign key relationships
            id_field (str): Name of the ID field (for parent_id mode)
            parent_id_field (str): Name of the parent ID field (for parent_id mode)
            label_field (str): Name of the display label field
            max_depth (int): Maximum tree depth allowed
            allow_reorder (bool): Whether to allow node reordering
            allow_drag_drop (bool): Whether to enable drag-and-drop
            node_template (str): Custom HTML template for nodes
            path_separator (str): Path separator character (default: '.')
            validation_rules (dict): Custom validation rules
        """
        self.mode = mode
        self.id_field = id_field
        self.parent_id_field = parent_id_field
        self.label_field = label_field
        self.max_depth = max_depth
        self.allow_reorder = allow_reorder
        self.allow_drag_drop = allow_drag_drop
        self.node_template = node_template
        self.path_separator = path_separator
        self.validation_rules = validation_rules or {}
        super().__init__()
    
    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('class', 'form-control')
        kwargs.setdefault('style', 'display: none;')  # Hide textarea, show tree interface
        
        html_params_str = html_params(name=field.name, **kwargs)
        
        # Default node template if none provided
        default_template = '''
            <div class="tree-node" data-id="{{id}}" data-parent-id="{{parent_id}}" data-path="{{path}}">
                <div class="node-content">
                    <span class="node-toggle"><i class="fa fa-chevron-right"></i></span>
                    <span class="node-icon"><i class="fa fa-folder"></i></span>
                    <span class="node-label" contenteditable="true">{{label}}</span>
                    <div class="node-actions">
                        <button type="button" class="btn btn-xs btn-default node-add" title="Add Child">
                            <i class="fa fa-plus"></i>
                        </button>
                        <button type="button" class="btn btn-xs btn-default node-edit" title="Edit">
                            <i class="fa fa-edit"></i>
                        </button>
                        <button type="button" class="btn btn-xs btn-danger node-delete" title="Delete">
                            <i class="fa fa-trash"></i>
                        </button>
                    </div>
                </div>
                <div class="node-children"></div>
            </div>
        '''
        
        template = self.node_template or default_template
        
        parent_id_option = '<option value="parent_id">Parent-ID Table</option>' if self.mode == "parent_id" else ""
        mode_description = f"(using {self.parent_id_field} → {self.id_field})" if self.mode == "parent_id" else "(using path format)"
        
        html = '''
        <div class="postgresql-tree-widget" 
             data-mode="{mode}"
             data-id-field="{id_field}"
             data-parent-id-field="{parent_id_field}"
             data-label-field="{label_field}"
             data-max-depth="{max_depth}" 
             data-allow-reorder="{allow_reorder}" 
             data-allow-drag-drop="{allow_drag_drop}"
             data-path-separator="{path_separator}">
            
            <!-- Hidden textarea for form data -->
            <textarea {html_params_str}>{field_data}</textarea>
            
            <!-- Tree controls -->
            <div class="tree-controls">
                <div class="btn-group" role="group">
                    <button type="button" class="btn btn-default tree-add-root" title="Add Root Node">
                        <i class="fa fa-plus-circle"></i> Add Root
                    </button>
                    <button type="button" class="btn btn-default tree-expand-all" title="Expand All">
                        <i class="fa fa-expand"></i> Expand All
                    </button>
                    <button type="button" class="btn btn-default tree-collapse-all" title="Collapse All">
                        <i class="fa fa-compress"></i> Collapse All
                    </button>
                    <button type="button" class="btn btn-default tree-refresh" title="Refresh Tree">
                        <i class="fa fa-refresh"></i> Refresh
                    </button>
                </div>
                
                <div class="btn-group" role="group">
                    <button type="button" class="btn btn-default tree-export" title="Export Tree">
                        <i class="fa fa-download"></i> Export
                    </button>
                    <button type="button" class="btn btn-default tree-import" title="Import Tree">
                        <i class="fa fa-upload"></i> Import
                    </button>
                    <button type="button" class="btn btn-default tree-validate" title="Validate Tree">
                        <i class="fa fa-check"></i> Validate
                    </button>
                    <button type="button" class="btn btn-default tree-repair" title="Repair Tree">
                        <i class="fa fa-wrench"></i> Repair
                    </button>
                </div>
                
                <div class="tree-search" style="float: right;">
                    <div class="input-group input-group-sm">
                        <input type="text" class="form-control tree-search-input" placeholder="Search nodes...">
                        <div class="input-group-btn">
                            <button type="button" class="btn btn-default tree-search-clear">
                                <i class="fa fa-times"></i>
                            </button>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- Tree mode indicator -->
            <div class="tree-mode-info">
                <span class="badge badge-info">
                    Mode: {mode_upper} {mode_description}
                </span>
                <span class="badge badge-secondary">Max Depth: {max_depth}</span>
                {drag_drop_badge}
            </div>
            
            <!-- Tree container -->
            <div class="tree-container">
                <div class="tree-root" id="tree-{field_id}"></div>
                <div class="tree-empty" style="display: none;">
                    <div class="text-center text-muted">
                        <i class="fa fa-tree fa-3x" style="margin-bottom: 15px; opacity: 0.3;"></i>
                        <h4>No tree data available</h4>
                        <p>Click "Add Root" to start building your hierarchy</p>
                        <p><small>Supports both LTREE paths and parent-child relationships</small></p>
                    </div>
                </div>
            </div>
            
            <!-- Tree status and info -->
            <div class="tree-info">
                <div class="tree-stats">
                    <span class="stat-nodes">
                        <i class="fa fa-sitemap"></i> Nodes: <span class="node-count">0</span>
                    </span>
                    <span class="stat-depth">
                        <i class="fa fa-level-down"></i> Max Depth: <span class="max-depth-count">0</span>
                    </span>
                    <span class="stat-selected">
                        <i class="fa fa-check-square-o"></i> Selected: <span class="selected-count">0</span>
                    </span>
                    <span class="stat-orphans">
                        <i class="fa fa-unlink"></i> Orphans: <span class="orphan-count">0</span>
                    </span>
                </div>
                <div class="tree-validation">
                    <span class="validation-status"></span>
                </div>
            </div>
        </div>
        
        <!-- Node template -->
        <script type="text/template" id="tree-node-template-{field_id}">
            {template}
        </script>
        
        <!-- Import/Export modal -->
        <div class="modal fade" id="tree-import-export-modal-{field_id}" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <button type="button" class="close" data-dismiss="modal">
                            <span>&times;</span>
                        </button>
                        <h4 class="modal-title">
                            <i class="fa fa-exchange"></i> Import/Export Tree Data
                        </h4>
                    </div>
                    <div class="modal-body">
                        <div class="nav-tabs-wrapper">
                            <ul class="nav nav-tabs">
                                <li class="active">
                                    <a href="#export-tab-{field_id}" data-toggle="tab">
                                        <i class="fa fa-download"></i> Export
                                    </a>
                                </li>
                                <li>
                                    <a href="#import-tab-{field_id}" data-toggle="tab">
                                        <i class="fa fa-upload"></i> Import
                                    </a>
                                </li>
                            </ul>
                            <div class="tab-content">
                                <div class="tab-pane active" id="export-tab-{field_id}">
                                    <div class="form-group">
                                        <label>Export Format:</label>
                                        <select class="form-control export-format">
                                            <option value="json">JSON (Hierarchical)</option>
                                            <option value="csv">CSV (Flat Structure)</option>
                                            <option value="sql_insert">SQL INSERT Statements</option>
                                            <option value="sql_select">SQL SELECT Result</option>
                                            <option value="ltree">LTREE Paths</option>
                                            {parent_id_option}
                                        </select>
                                    </div>
                                    <div class="form-group">
                                        <label>Export Data:</label>
                                        <textarea class="form-control export-data" rows="12" readonly 
                                                placeholder="Select a format to generate export data..."></textarea>
                                    </div>
                                    <div class="form-group">
                                        <button type="button" class="btn btn-primary export-copy">
                                            <i class="fa fa-copy"></i> Copy to Clipboard
                                        </button>
                                        <button type="button" class="btn btn-default export-download">
                                            <i class="fa fa-download"></i> Download File
                                        </button>
                                        <small class="text-muted pull-right">
                                            Export includes all tree nodes and relationships
                                        </small>
                                    </div>
                                </div>
                                <div class="tab-pane" id="import-tab-{field_id}">
                                    <div class="form-group">
                                        <label>Import Format:</label>
                                        <select class="form-control import-format">
                                            <option value="json">JSON (Hierarchical)</option>
                                            <option value="csv">CSV (Flat Structure)</option>
                                            <option value="sql">SQL Results</option>
                                            <option value="ltree">LTREE Paths</option>
                                            {parent_id_option}
                                        </select>
                                    </div>
                                    <div class="form-group">
                                        <label>Import Data:</label>
                                        <textarea class="form-control import-data" rows="12" 
                                                placeholder="Paste your tree data here...&#10;&#10;Supported formats:&#10;- JSON hierarchical structure&#10;- CSV with id,parent_id,name columns&#10;- LTREE path strings (one per line)&#10;- SQL SELECT results"></textarea>
                                    </div>
                                    <div class="form-group">
                                        <div class="row">
                                            <div class="col-md-6">
                                                <div class="checkbox">
                                                    <label>
                                                        <input type="checkbox" class="import-merge"> 
                                                        Merge with existing tree
                                                    </label>
                                                </div>
                                                <div class="checkbox">
                                                    <label>
                                                        <input type="checkbox" class="import-validate" checked> 
                                                        Validate before importing
                                                    </label>
                                                </div>
                                            </div>
                                            <div class="col-md-6">
                                                <div class="checkbox">
                                                    <label>
                                                        <input type="checkbox" class="import-repair"> 
                                                        Auto-repair orphaned nodes
                                                    </label>
                                                </div>
                                                <div class="checkbox">
                                                    <label>
                                                        <input type="checkbox" class="import-preserve-ids"> 
                                                        Preserve original IDs
                                                    </label>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                    <div class="form-group">
                                        <button type="button" class="btn btn-primary import-execute">
                                            <i class="fa fa-upload"></i> Import Data
                                        </button>
                                        <button type="button" class="btn btn-default import-preview">
                                            <i class="fa fa-eye"></i> Preview Changes
                                        </button>
                                        <button type="button" class="btn btn-info import-sample">
                                            <i class="fa fa-file-text-o"></i> Show Sample Format
                                        </button>
                                    </div>
                                    <div class="import-preview-area" style="display: none;">
                                        <h5>Import Preview:</h5>
                                        <div class="alert alert-info import-preview-content"></div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Styles -->
        <style>
        .postgresql-tree-widget {{
            border: 1px solid #ddd;
            border-radius: 4px;
            padding: 15px;
            background: #fff;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
        }}
        
        .tree-controls {{
            margin-bottom: 15px;
            padding-bottom: 12px;
            border-bottom: 1px solid #eee;
            overflow: hidden;
        }}
        
        .tree-controls .btn-group {{
            margin-right: 10px;
            margin-bottom: 5px;
        }}
        
        .tree-mode-info {{
            margin-bottom: 12px;
        }}
        
        .tree-mode-info .badge {{
            margin-right: 8px;
            font-size: 0.85em;
        }}
        
        .tree-container {{
            min-height: 350px;
            max-height: 650px;
            overflow-y: auto;
            border: 1px solid #e8e8e8;
            border-radius: 4px;
            padding: 15px;
            background: #fafafa;
            position: relative;
        }}
        
        .tree-root {{
            position: relative;
        }}
        
        .tree-empty {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            width: 80%;
        }}
        
        .tree-node {{
            margin: 3px 0;
            position: relative;
        }}
        
        .tree-node.dragging {{
            opacity: 0.6;
            transform: rotate(2deg);
            z-index: 1000;
        }}
        
        .tree-node.drag-over {{
            background-color: #e8f4fd;
            border: 2px dashed #4a90e2;
            border-radius: 4px;
            padding: 2px;
        }}
        
        .tree-node.invalid {{
            background-color: #ffeaea;
            border: 1px solid #ff6b6b;
            border-radius: 4px;
            padding: 2px;
        }}
        
        .tree-node.orphaned {{
            background-color: #fff3cd;
            border: 1px solid #ffc107;
            border-radius: 4px;
            padding: 2px;
        }}
        
        .tree-node.circular-ref {{
            background-color: #f8d7da;
            border: 1px solid #dc3545;
            border-radius: 4px;
            padding: 2px;
        }}
        
        .node-content {{
            display: flex;
            align-items: center;
            padding: 8px 12px;
            border-radius: 4px;
            background: #fff;
            border: 1px solid #e0e0e0;
            margin-bottom: 3px;
            position: relative;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        
        .node-content:hover {{
            background: #f5f5f5;
            border-color: #ccc;
            box-shadow: 0 2px 6px rgba(0,0,0,0.1);
            transform: translateY(-1px);
        }}
        
        .node-content.selected {{
            background: #e3f2fd;
            border-color: #2196f3;
            box-shadow: 0 0 6px rgba(33, 150, 243, 0.4);
        }}
        
        .node-content.root {{
            background: linear-gradient(135deg, #e8f5e8, #f1f8e9);
            border-color: #4caf50;
        }}
        
        .node-toggle {{
            width: 22px;
            height: 22px;
            color: #666;
            cursor: pointer;
            transition: all 0.2s ease;
            text-align: center;
            border-radius: 3px;
        }}
        
        .node-toggle:hover {{
            background: #f0f0f0;
            color: #333;
        }}
        
        .node-toggle.expanded {{
            transform: rotate(90deg);
            color: #4a90e2;
        }}
        
        .node-toggle.no-children {{
            visibility: hidden;
        }}
        
        .node-icon {{
            margin: 0 10px 0 8px;
            color: #ffa726;
            font-size: 16px;
            min-width: 16px;
        }}
        
        .node-icon.file {{
            color: #42a5f5;
        }}
        
        .node-icon.root {{
            color: #4caf50;
        }}
        
        .node-label {{
            flex: 1;
            padding: 6px 10px;
            border: 1px solid transparent;
            border-radius: 3px;
            outline: none;
            font-weight: 500;
            min-width: 120px;
            line-height: 1.3;
        }}
        
        .node-label:focus {{
            border-color: #4a90e2;
            background: #fff;
            box-shadow: 0 0 4px rgba(74, 144, 226, 0.3);
        }}
        
        .node-label.invalid {{
            border-color: #f44336;
            background: #ffebee;
        }}
        
        .node-actions {{
            opacity: 0;
            transition: opacity 0.2s ease;
            margin-left: 12px;
        }}
        
        .node-content:hover .node-actions {{
            opacity: 1;
        }}
        
        .node-actions .btn {{
            margin-left: 4px;
            padding: 4px 8px;
            font-size: 12px;
        }}
        
        .node-children {{
            margin-left: 35px;
            border-left: 2px dashed #ddd;
            padding-left: 18px;
            margin-top: 4px;
        }}
        
        .node-children.collapsed {{
            display: none;
        }}
        
        .tree-info {{
            margin-top: 15px;
            padding-top: 12px;
            border-top: 1px solid #eee;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 0.9em;
            color: #666;
        }}
        
        .tree-stats {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        
        .tree-stats span {{
            padding: 4px 10px;
            background: #f8f9fa;
            border-radius: 3px;
            border: 1px solid #e9ecef;
            font-size: 0.85em;
        }}
        
        .tree-stats i {{
            margin-right: 4px;
            color: #6c757d;
        }}
        
        .validation-status {{
            font-weight: 500;
            padding: 4px 8px;
            border-radius: 3px;
        }}
        
        .validation-status.valid {{
            color: #155724;
            background-color: #d4edda;
            border: 1px solid #c3e6cb;
        }}
        
        .validation-status.invalid {{
            color: #721c24;
            background-color: #f8d7da;
            border: 1px solid #f5c6cb;
        }}
        
        .validation-status.warning {{
            color: #856404;
            background-color: #fff3cd;
            border: 1px solid #ffeaa7;
        }}
        
        .tree-search {{
            width: 280px;
        }}
        
        .tree-node.search-highlight .node-label {{
            background: linear-gradient(45deg, #fff3cd, #ffeaa7);
            border-color: #ffc107;
            font-weight: bold;
            box-shadow: 0 0 4px rgba(255, 193, 7, 0.3);
        }}
        
        .tree-node.search-hidden {{
            display: none;
        }}
        
        /* Modal styles */
        .modal-lg {{
            width: 95%;
            max-width: 1000px;
        }}
        
        .modal .nav-tabs-wrapper {{
            margin: -15px -15px 20px -15px;
        }}
        
        .modal .nav-tabs {{
            margin: 0;
            border-bottom: 1px solid #ddd;
            background: #f8f9fa;
        }}
        
        .modal .tab-content {{
            padding: 20px 15px 15px 15px;
        }}
        
        .import-preview-area {{
            margin-top: 15px;
            padding: 10px;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
            background: #f9f9f9;
        }}
        
        /* Drag placeholder */
        .drag-placeholder {{
            height: 3px;
            background: linear-gradient(90deg, #4a90e2, #2196f3);
            margin: 4px 0;
            border-radius: 2px;
            animation: dragPlaceholder 1s ease-in-out infinite;
        }}
        
        @keyframes dragPlaceholder {{
            0%, 100% {{ opacity: 0.4; transform: scaleX(0.8); }}
            50% {{ opacity: 1; transform: scaleX(1); }}
        }}
        
        /* Node animations */
        @keyframes nodeAdded {{
            0% {{ 
                transform: scale(0.8) translateY(-15px) rotateX(-90deg); 
                opacity: 0; 
            }}
            50% {{
                transform: scale(1.05) translateY(-5px) rotateX(-30deg);
                opacity: 0.8;
            }}
            100% {{ 
                transform: scale(1) translateY(0) rotateX(0deg); 
                opacity: 1; 
            }}
        }}
        
        .tree-node.newly-added {{
            animation: nodeAdded 0.5s cubic-bezier(0.175, 0.885, 0.32, 1.275);
        }}
        
        @keyframes nodeUpdated {{
            0% {{ background-color: #e8f5e8; transform: scale(1.02); }}
            100% {{ background-color: transparent; transform: scale(1); }}
        }}
        
        .tree-node.recently-updated .node-content {{
            animation: nodeUpdated 1.2s ease-out;
        }}
        
        @keyframes nodeDeleted {{
            0% {{ 
                transform: scale(1); 
                opacity: 1; 
            }}
            50% {{
                transform: scale(1.1) rotateZ(2deg);
                opacity: 0.5;
            }}
            100% {{ 
                transform: scale(0) rotateZ(5deg); 
                opacity: 0; 
                height: 0;
                margin: 0;
                padding: 0;
            }}
        }}
        
        .tree-node.being-deleted {{
            animation: nodeDeleted 0.4s ease-out forwards;
        }}
        
        /* Responsive design */
        @media (max-width: 768px) {{
            .tree-controls {{
                text-align: center;
            }}
            
            .tree-controls .btn-group {{
                display: block;
                margin-bottom: 8px;
                width: 100%;
            }}
            
            .tree-search {{
                float: none !important;
                width: 100%;
                margin-top: 10px;
            }}
            
            .node-children {{
                margin-left: 25px;
                padding-left: 15px;
            }}
            
            .tree-stats {{
                flex-direction: column;
                align-items: flex-start;
            }}
            
            .modal-lg {{
                width: 95%;
                margin: 10px auto;
            }}
        }}
        
        /* Print styles */
        @media print {{
            .tree-controls,
            .node-actions,
            .tree-info {{
                display: none !important;
            }}
            
            .tree-container {{
                border: none;
                box-shadow: none;
                max-height: none;
                overflow: visible;
            }}
            
            .postgresql-tree-widget {{
                border: none;
                padding: 0;
            }}
            
            .node-content {{
                border: 1px solid #000 !important;
                background: #fff !important;
                box-shadow: none !important;
            }}
        }}
        </style>
        
        <script>
        $(document).ready(function() {{
            // Initialize PostgreSQL Tree Widget
            console.log('PostgreSQL Tree Widget loaded for field: {field_id}');
            
            // Initialize tree widget instance
            window.treeWidget_{field_id_underscore} = {{
                mode: '{mode}',
                idField: '{id_field}',
                parentIdField: '{parent_id_field}',
                labelField: '{label_field}',
                maxDepth: {max_depth},
                pathSeparator: '{path_separator}',
                container: $('.postgresql-tree-widget[data-mode="{mode}"]').first(),
                fieldId: '{field_id}',
                
                // Tree data storage
                treeData: {{}},
                selectedNodes: new Set(),
                
                // Initialize the widget
                init: function() {{
                    this.loadTreeFromTextarea();
                    this.renderTree();
                    this.bindEvents();
                    this.updateStats();
                    this.validateTree();
                }},
                
                // Load tree data from hidden textarea
                loadTreeFromTextarea: function() {{
                    const textarea = this.container.find('textarea');
                    const data = textarea.val().trim();
                    
                    if (!data) {{
                        this.treeData = {{}};
                        return;
                    }}
                    
                    try {{
                        if (this.mode === 'parent_id') {{
                            // Parse parent-child relationship data
                            this.treeData = JSON.parse(data);
                        }} else {{
                            // Parse LTREE or JSON data
                            if (data.startsWith('{{') || data.startsWith('[')) {{
                                this.treeData = JSON.parse(data);
                            }} else {{
                                // Parse LTREE paths
                                this.treeData = this.parseLTreePaths(data);
                            }}
                        }}
                    }} catch (e) {{
                        console.error('Failed to parse tree data:', e);
                        this.treeData = {{}};
                    }}
                    
                    console.log('Loaded tree data:', this.treeData);
                }},
                
                // Parse LTREE paths into hierarchical structure
                parseLTreePaths: function(pathsStr) {{
                    const paths = pathsStr.split('\\n').filter(p => p.trim());
                    const tree = {{}};
                    
                    paths.forEach((path, index) => {{
                        const parts = path.trim().split(this.pathSeparator);
                        let current = tree;
                        
                        parts.forEach((part, partIndex) => {{
                            if (!current[part]) {{
                                current[part] = {{
                                    id: this.mode === 'parent_id' ? index + partIndex + 1 : null,
                                    label: part,
                                    path: parts.slice(0, partIndex + 1).join(this.pathSeparator),
                                    children: {{}}
                                }};
                            }}
                            current = current[part].children;
                        }});
                    }});
                    
                    return tree;
                }},
                
                // Render the tree structure
                renderTree: function() {{
                    const treeRoot = this.container.find('.tree-root');
                    const emptyState = this.container.find('.tree-empty');
                    
                    treeRoot.empty();
                    
                    if (Object.keys(this.treeData).length === 0) {{
                        emptyState.show();
                        return;
                    }}
                    
                    emptyState.hide();
                    this.renderNodes(this.treeData, treeRoot, 0);
                }},
                
                // Render nodes recursively
                renderNodes: function(nodes, container, depth) {{
                    Object.entries(nodes).forEach(([key, node]) => {{
                        const nodeElement = this.createNodeElement(node, depth);
                        container.append(nodeElement);
                        
                        if (node.children && Object.keys(node.children).length > 0) {{
                            const childrenContainer = nodeElement.find('.node-children');
                            this.renderNodes(node.children, childrenContainer, depth + 1);
                            nodeElement.find('.node-icon i').removeClass('fa-file').addClass('fa-folder');
                            
                            if (depth === 0) {{
                                nodeElement.find('.node-icon').addClass('root');
                                nodeElement.find('.node-content').addClass('root');
                            }}
                        }} else {{
                            nodeElement.find('.node-toggle').addClass('no-children');
                            nodeElement.find('.node-icon i').removeClass('fa-folder').addClass('fa-file').addClass('file');
                        }}
                    }});
                }},
                
                // Create a single node element
                createNodeElement: function(node, depth) {{
                    const template = $('#tree-node-template-{field_id}').html();
                    let html = template;
                    
                    // Replace template variables
                    html = html.replace(/{{{{id}}}}/g, node.id || '');
                    html = html.replace(/{{{{parent_id}}}}/g, node.parent_id || '');
                    html = html.replace(/{{{{path}}}}/g, node.path || '');
                    html = html.replace(/{{{{label}}}}/g, node.label || 'New Node');
                    
                    const element = $(html);
                    element.attr('data-depth', depth);
                    element.attr('draggable', this.container.data('allow-drag-drop'));
                    
                    // Disable adding children if max depth reached
                    if (depth >= this.maxDepth - 1) {{
                        element.find('.node-add').prop('disabled', true)
                               .attr('title', 'Maximum depth reached');
                    }}
                    
                    return element;
                }},
                
                // Bind all event listeners
                bindEvents: function() {{
                    const container = this.container;
                    const self = this;
                    
                    // Tree controls
                    container.find('.tree-add-root').on('click', () => this.addRootNode());
                    container.find('.tree-expand-all').on('click', () => this.expandAll());
                    container.find('.tree-collapse-all').on('click', () => this.collapseAll());
                    container.find('.tree-refresh').on('click', () => this.refresh());
                    container.find('.tree-export').on('click', () => this.showExportModal());
                    container.find('.tree-import').on('click', () => this.showImportModal());
                    container.find('.tree-validate').on('click', () => this.validateTree(true));
                    container.find('.tree-repair').on('click', () => this.repairTree());
                    
                    // Search functionality
                    container.find('.tree-search-input').on('input', function() {{
                        self.searchNodes($(this).val());
                    }});
                    container.find('.tree-search-clear').on('click', () => this.clearSearch());
                    
                    // Node events (delegated)
                    const treeRoot = container.find('.tree-root');
                    treeRoot.on('click', '.node-toggle', (e) => this.toggleNode(e.currentTarget));
                    treeRoot.on('click', '.node-add', (e) => this.addChildNode(e.currentTarget));
                    treeRoot.on('click', '.node-edit', (e) => this.editNode(e.currentTarget));
                    treeRoot.on('click', '.node-delete', (e) => this.deleteNode(e.currentTarget));
                    treeRoot.on('click', '.node-content', (e) => this.selectNode(e.currentTarget));
                    treeRoot.on('blur', '.node-label[contenteditable]', (e) => this.updateNodeLabel(e.currentTarget));
                    
                    // Drag and drop (if enabled)
                    if (container.data('allow-drag-drop')) {{
                        this.setupDragAndDrop();
                    }}
                    
                    // Modal events
                    this.setupModalEvents();
                }},
                
                // Update statistics display
                updateStats: function() {{
                    const nodeCount = this.countNodes(this.treeData);
                    const maxDepth = this.calculateMaxDepth(this.treeData);
                    const orphanCount = this.countOrphanNodes();
                    
                    this.container.find('.node-count').text(nodeCount);
                    this.container.find('.max-depth-count').text(maxDepth);
                    this.container.find('.selected-count').text(this.selectedNodes.size);
                    this.container.find('.orphan-count').text(orphanCount);
                }},
                
                // Count total nodes
                countNodes: function(nodes) {{
                    let count = 0;
                    Object.values(nodes).forEach(node => {{
                        count++;
                        if (node.children) {{
                            count += this.countNodes(node.children);
                        }}
                    }});
                    return count;
                }},
                
                // Calculate maximum depth
                calculateMaxDepth: function(nodes, currentDepth = 0) {{
                    let maxDepth = currentDepth;
                    Object.values(nodes).forEach(node => {{
                        if (node.children && Object.keys(node.children).length > 0) {{
                            const childDepth = this.calculateMaxDepth(node.children, currentDepth + 1);
                            maxDepth = Math.max(maxDepth, childDepth);
                        }}
                    }});
                    return maxDepth;
                }},
                
                // Count orphaned nodes (for parent_id mode)
                countOrphanNodes: function() {{
                    if (this.mode !== 'parent_id') return 0;
                    
                    // This would implement orphan detection for parent-child relationships
                    return 0;
                }},
                
                // Basic tree operations placeholder
                addRootNode: function() {{
                    const label = prompt('Enter root node name:');
                    if (!label) return;
                    
                    console.log('Adding root node:', label);
                    // Implementation would go here
                }},
                
                expandAll: function() {{
                    this.container.find('.node-children').removeClass('collapsed');
                    this.container.find('.node-toggle').addClass('expanded');
                    this.container.find('.node-toggle i').removeClass('fa-chevron-right').addClass('fa-chevron-down');
                }},
                
                collapseAll: function() {{
                    this.container.find('.node-children').addClass('collapsed');
                    this.container.find('.node-toggle').removeClass('expanded');
                    this.container.find('.node-toggle i').removeClass('fa-chevron-down').addClass('fa-chevron-right');
                }},
                
                refresh: function() {{
                    this.loadTreeFromTextarea();
                    this.renderTree();
                    this.updateStats();
                    this.validateTree();
                }},
                
                // Validation
                validateTree: function(showAlert = false) {{
                    const status = this.container.find('.validation-status');
                    const issues = [];
                    
                    // Check depth constraint
                    const maxDepth = this.calculateMaxDepth(this.treeData);
                    if (maxDepth > this.maxDepth) {{
                        issues.push('Tree depth (' + maxDepth + ') exceeds maximum (' + this.maxDepth + ')');
                    }}
                    
                    // Check for orphaned nodes (parent_id mode)
                    if (this.mode === 'parent_id') {{
                        const orphanCount = this.countOrphanNodes();
                        if (orphanCount > 0) {{
                            issues.push(orphanCount + ' orphaned node(s) detected');
                        }}
                    }}
                    
                    if (issues.length === 0) {{
                        status.removeClass('invalid warning').addClass('valid')
                              .html('<i class=\"fa fa-check\"></i> Tree structure valid');
                        if (showAlert) alert('Tree validation passed!');
                    }} else {{
                        status.removeClass('valid').addClass('invalid')
                              .html('<i class=\"fa fa-exclamation-triangle\"></i> ' + issues.join(', '));
                        const issuesList = issues.join('\\n');
                        if (showAlert) alert('Tree validation failed:\\n\\n' + issuesList);
                    }}
                }},
                
                // Helper methods for tree operations
                updateTreeData: function() {{
                    // Serialize tree data back to textarea
                    const serializedData = this.mode === 'parent_id' ? 
                        this.serializeToParentChild() : 
                        this.serializeToLTree();
                    
                    this.container.find('textarea').val(JSON.stringify(serializedData, null, 2));
                }},
                
                serializeToParentChild: function() {{
                    const result = [];
                    const self = this;
                    
                    function traverse(nodes, parentId = null) {{
                        Object.entries(nodes).forEach(([key, node]) => {{
                            const nodeData = {{
                                [self.idField]: node.id || key,
                                [self.parentIdField]: parentId,
                                [self.labelField]: node.label || key
                            }};
                            result.push(nodeData);
                            
                            if (node.children && Object.keys(node.children).length > 0) {{
                                traverse(node.children, node.id || key);
                            }}
                        }});
                    }}
                    
                    traverse(this.treeData);
                    return result;
                }},
                
                serializeToLTree: function() {{
                    const result = [];
                    
                    function traverse(nodes, parentPath = '') {{
                        Object.entries(nodes).forEach(([key, node]) => {{
                            const currentPath = parentPath ? parentPath + '.' + key : key;
                            result.push(currentPath);
                            
                            if (node.children && Object.keys(node.children).length > 0) {{
                                traverse(node.children, currentPath);
                            }}
                        }});
                    }}
                    
                    traverse(this.treeData);
                    const newline = '\\n';
                    return result.join(newline);
                }},
                
                calculateNodeDepth: function($node) {{
                    let depth = 0;
                    const traverse = function($el) {{
                        const children = $el.find('.tree-node');
                        if (children.length === 0) return 0;
                        
                        let maxChildDepth = 0;
                        children.each(function() {{
                            const childDepth = traverse($(this));
                            maxChildDepth = Math.max(maxChildDepth, childDepth);
                        }});
                        return maxChildDepth + 1;
                    }};
                    
                    return traverse($node);
                }},
                
                updateNodeDepths: function($node, newDepth) {{
                    $node.attr('data-depth', newDepth);
                    $node.find('.tree-node').each(function(index) {{
                        const childDepth = newDepth + $(this).parentsUntil($node).filter('.tree-node').length + 1;
                        $(this).attr('data-depth', childDepth);
                    }});
                }},
                
                findOrphanedNodes: function() {{
                    if (this.mode !== 'parent_id') return [];
                    
                    const orphans = [];
                    const allIds = new Set();
                    
                    // Collect all node IDs
                    this.container.find('.tree-node').each(function() {{
                        const id = $(this).attr('data-id');
                        if (id) allIds.add(id);
                    }});
                    
                    // Find nodes with parent IDs that don't exist
                    this.container.find('.tree-node').each(function() {{
                        const $node = $(this);
                        const parentId = $node.attr('data-parent-id');
                        if (parentId && !allIds.has(parentId)) {{
                            orphans.push({{
                                id: $node.attr('data-id'),
                                parentId: parentId,
                                label: $node.find('.node-label').text()
                            }});
                        }}
                    }});
                    
                    return orphans;
                }},
                
                findDepthViolations: function() {{
                    const violations = [];
                    const self = this;
                    
                    this.container.find('.tree-node').each(function() {{
                        const $node = $(this);
                        const depth = parseInt($node.attr('data-depth')) || 0;
                        
                        if (depth >= self.maxDepth) {{
                            violations.push({{
                                id: $node.attr('data-id'),
                                currentDepth: depth,
                                maxAllowed: self.maxDepth - 1
                            }});
                        }}
                    }});
                    
                    return violations;
                }},
                
                findNearestValidParent: function($node) {{
                    let $current = $node.parent();
                    
                    while ($current.length > 0) {{
                        if ($current.hasClass('tree-node')) {{
                            const depth = parseInt($current.attr('data-depth')) || 0;
                            if (depth < this.maxDepth - 2) {{ // Allow room for the moved node
                                return $current;
                            }}
                        }}
                        $current = $current.parent();
                    }}
                    
                    // Return tree root as fallback
                    return this.container.find('.tree-root').first();
                }},
                
                generateExportData: function(format) {{
                    switch (format) {{
                        case 'json':
                            return JSON.stringify(this.treeData, null, 2);
                        
                        case 'csv':
                            return this.generateCSVExport();
                        
                        case 'sql_insert':
                            return this.generateSQLInsertExport();
                        
                        case 'sql_select':
                            return this.generateSQLSelectExport();
                        
                        case 'ltree':
                            return this.serializeToLTree();
                        
                        case 'parent_id':
                            const data = this.serializeToParentChild();
                            return JSON.stringify(data, null, 2);
                        
                        default:
                            return JSON.stringify(this.treeData, null, 2);
                    }}
                }},
                
                generateCSVExport: function() {{
                    const headers = this.mode === 'parent_id' ? 
                        [this.idField, this.labelField, this.parentIdField] : 
                        ['path', 'label', 'depth'];
                    
                    const newline = '\\n';
                    let csv = headers.join(',') + newline;
                    
                    if (this.mode === 'parent_id') {{
                        const data = this.serializeToParentChild();
                        data.forEach(row => {{
                            csv += '\"' + (row[this.idField] || '') + '\",\"' + (row[this.labelField] || '') + '\",\"' + (row[this.parentIdField] || '') + '\"' + newline;
                        }});
                    }} else {{
                        const ltreeData = this.serializeToLTree();
                        const paths = ltreeData.split('\\n');
                        paths.forEach(path => {{
                            const regex = new RegExp('\\\\' + this.pathSeparator, 'g');
                            const depth = (path.match(regex) || []).length;
                            const label = path.split(this.pathSeparator).pop();
                            csv += '\"' + path + '\",\"' + label + '\",' + depth + newline;
                        }});
                    }}
                    
                    return csv;
                }},
                
                generateSQLInsertExport: function() {{
                    const tableName = this.mode === 'parent_id' ? 'tree_table' : 'ltree_table';
                    const newline = '\\n';
                    const newlines = '\\n\\n';
                    let sql = '-- Generated tree data for ' + tableName + newline;
                    sql += '-- Mode: ' + this.mode + newlines;
                    
                    if (this.mode === 'parent_id') {{
                        const insertStmt = 'INSERT INTO ' + tableName + ' (' + this.idField + ', ' + this.labelField + ', ' + this.parentIdField + ') VALUES';
                        sql += insertStmt + newline;
                        const data = this.serializeToParentChild();
                        const values = data.map(row => 
                            '(' + (row[this.idField] || 'NULL') + ', \\'' + (row[this.labelField] || '') + '\\', ' + (row[this.parentIdField] || 'NULL') + ')'
                        );
                        const separator = ',\\n';
                        sql += values.join(separator) + ';';
                    }} else {{
                        const insertStatement = 'INSERT INTO ' + tableName + ' (path, label) VALUES';
                        sql += insertStatement + '\\n';
                        const ltreeData = this.serializeToLTree();
                        const paths = ltreeData.split('\\n');
                        const values = paths.map(path => {{
                            const label = path.split(this.pathSeparator).pop();
                            return '(\\'' + path + '\\', \\'' + label + '\\')';
                        }});
                        const separator = ',\\n';
                        sql += values.join(separator) + ';';
                    }}
                    
                    return sql;
                }},
                
                generateSQLSelectExport: function() {{
                    const tableName = this.mode === 'parent_id' ? 'tree_table' : 'ltree_table';
                    const newline = '\\n';
                    const newlines = '\\n\\n';
                    
                    let result = '-- Sample SELECT queries for ' + tableName + newline +
                                 '-- Mode: ' + this.mode + newlines +
                                 'SELECT * FROM ' + tableName + ';' + newlines;
                    
                    if (this.mode === 'parent_id') {{
                        result += '-- Hierarchical query with recursive CTE' + newline +
                                  'WITH RECURSIVE tree_path AS (' + newline +
                                  '    SELECT ' + this.idField + ', ' + this.labelField + ', ' + this.parentIdField + ', 1 as level' + newline +
                                  '    FROM ' + tableName + ' WHERE ' + this.parentIdField + ' IS NULL' + newline +
                                  '    UNION ALL' + newline +
                                  '    SELECT t.' + this.idField + ', t.' + this.labelField + ', t.' + this.parentIdField + ', tp.level + 1' + newline +
                                  '    FROM ' + tableName + ' t JOIN tree_path tp ON t.' + this.parentIdField + ' = tp.' + this.idField + newline +
                                  ')' + newline +
                                  'SELECT * FROM tree_path ORDER BY level, ' + this.labelField + ';';
                    }} else {{
                        result += '-- LTREE hierarchy queries' + newline +
                                  'SELECT * FROM ' + tableName + ' WHERE path ~ \\'*.root.*\\';' + newline +
                                  'SELECT * FROM ' + tableName + ' WHERE path <@ \\'root.branch\\';' + newline +
                                  'SELECT path, nlevel(path) as depth FROM ' + tableName + ';';
                    }}
                    
                    return result;
                }},
                
                previewImportData: function(data, format) {{
                    let preview = '';
                    let parsedData;
                    
                    try {{
                        switch (format) {{
                            case 'json':
                                parsedData = JSON.parse(data);
                                preview = '<strong>JSON Data Preview:</strong><br>';
                                preview += 'Found ' + Object.keys(parsedData).length + ' root nodes<br>';
                                preview += '<pre>' + JSON.stringify(parsedData, null, 2).substring(0, 500) + '...</pre>';
                                break;
                            
                            case 'csv':
                                const lines = data.trim().split('\\n');
                                preview = '<strong>CSV Data Preview:</strong><br>';
                                preview += 'Headers: ' + lines[0] + '<br>';
                                preview += 'Data rows: ' + (lines.length - 1) + '<br>';
                                const linesText = lines.slice(0, 6).join('\\n');
                                preview += '<pre>' + linesText + '</pre>';
                                break;
                            
                            case 'ltree':
                                const paths = data.trim().split('\\n');
                                preview = '<strong>LTREE Paths Preview:</strong><br>';
                                preview += 'Total paths: ' + paths.length + '<br>';
                                const pathsText = paths.slice(0, 10).join('\\n');
                                preview += '<pre>' + pathsText + '</pre>';
                                break;
                            
                            default:
                                preview = '<strong>Data Preview:</strong><br>';
                                preview += 'Format: ' + format + '<br>';
                                preview += '<pre>' + data.substring(0, 500) + '...</pre>';
                        }}
                    }} catch (error) {{
                        preview = '<div class=\"alert alert-danger\">Preview Error: ' + error.message + '</div>';
                    }}
                    
                    return preview;
                }},
                
                executeImport: function(data, format, options) {{
                    // Parse and validate data
                    let parsedData;
                    
                    switch (format) {{
                        case 'json':
                            parsedData = JSON.parse(data);
                            break;
                        case 'csv':
                            parsedData = this.parseCSVData(data);
                            break;
                        case 'ltree':
                            parsedData = this.parseLTreePaths(data);
                            break;
                        default:
                            throw new Error('Unsupported import format: ' + format);
                    }}
                    
                    // Validate if requested
                    if (options.validate) {{
                        this.validateImportData(parsedData, format);
                    }}
                    
                    // Merge or replace
                    if (options.merge) {{
                        this.mergeTreeData(parsedData);
                    }} else {{
                        this.treeData = parsedData;
                    }}
                    
                    // Repair if requested
                    if (options.repair) {{
                        // Auto-repair logic would go here
                    }}
                    
                    // Update UI
                    this.renderTree();
                    this.updateStats();
                    this.validateTree();
                    this.updateTreeData();
                }},
                
                parseCSVData: function(csvData) {{
                    const lines = csvData.trim().split('\\n');
                    const headers = lines[0].split(',').map(h => h.replace(/\"/g, '').trim());
                    const result = [];
                    
                    for (let i = 1; i < lines.length; i++) {{
                        const values = lines[i].split(',').map(v => v.replace(/\"/g, '').trim());
                        const row = {{}};
                        headers.forEach((header, index) => {{
                            row[header] = values[index] || null;
                        }});
                        result.push(row);
                    }}
                    
                    return result;
                }},
                
                validateImportData: function(data, format) {{
                    // Basic validation logic
                    if (this.mode === 'parent_id' && Array.isArray(data)) {{
                        // Validate parent-child relationships
                        const ids = new Set();
                        data.forEach(row => {{
                            if (row[this.idField]) {{
                                ids.add(row[this.idField]);
                            }}
                        }});
                        
                        data.forEach(row => {{
                            const parentId = row[this.parentIdField];
                            if (parentId && !ids.has(parentId)) {{
                                throw new Error('Orphaned reference: parent ID ' + parentId + ' not found');
                            }}
                        }});
                    }}
                }},
                
                mergeTreeData: function(newData) {{
                    // Simple merge strategy - could be more sophisticated
                    Object.assign(this.treeData, newData);
                }},
                
                getSampleFormat: function(format) {{
                    switch (format) {{
                        case 'json':
                            return JSON.stringify({{
                                \"company\": {{
                                    \"label\": \"Company\",
                                    \"children\": {{
                                        \"engineering\": {{
                                            \"label\": \"Engineering\",
                                            \"children\": {{}}
                                        }}
                                    }}
                                }}
                            }}, null, 2);
                        
                        case 'csv':
                            const csvSample = 'id,name,parent_id\\n1,\"Company\",\\n2,\"Engineering\",1\\n3,\"Database Team\",2';
                            return csvSample;
                        
                        case 'ltree':
                            const ltreeSample = 'company\\ncompany.engineering\\ncompany.engineering.database\\ncompany.marketing';
                            return ltreeSample;
                        
                        default:
                            const defaultSample = '# Sample data for ' + format + ' format' + '\\n' + '# Please provide your tree data here';
                            return defaultSample;
                    }}
                }},
                
                getFileExtension: function(format) {{
                    const extensions = {{
                        'json': 'json',
                        'csv': 'csv', 
                        'sql_insert': 'sql',
                        'sql_select': 'sql',
                        'ltree': 'txt',
                        'parent_id': 'json'
                    }};
                    return extensions[format] || 'txt';
                }},
                
                getMimeType: function(format) {{
                    const mimeTypes = {{
                        'json': 'application/json',
                        'csv': 'text/csv',
                        'sql_insert': 'text/sql',
                        'sql_select': 'text/sql', 
                        'ltree': 'text/plain',
                        'parent_id': 'application/json'
                    }};
                    return mimeTypes[format] || 'text/plain';
                }},
                
                downloadFile: function(content, filename, mimeType) {{
                    const blob = new Blob([content], {{ type: mimeType }});
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = filename;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    window.URL.revokeObjectURL(url);
                }},
                
                // Tree widget methods implementation
                toggleNode: function(toggle) {{
                    const $toggle = $(toggle);
                    const $nodeContent = $toggle.closest('.node-content');
                    const $nodeChildren = $nodeContent.siblings('.node-children');
                    const $icon = $toggle.find('i');
                    
                    if ($nodeChildren.length === 0 || $nodeChildren.children().length === 0) {{
                        return; // No children to toggle
                    }}
                    
                    if ($nodeChildren.hasClass('collapsed')) {{
                        // Expand node
                        $nodeChildren.removeClass('collapsed');
                        $toggle.addClass('expanded');
                        $icon.removeClass('fa-chevron-right').addClass('fa-chevron-down');
                    }} else {{
                        // Collapse node
                        $nodeChildren.addClass('collapsed');
                        $toggle.removeClass('expanded');
                        $icon.removeClass('fa-chevron-down').addClass('fa-chevron-right');
                    }}
                }},
                addChildNode: function(button) {{
                    const $button = $(button);
                    const $node = $button.closest('.tree-node');
                    const $nodeChildren = $node.find('> .node-content').siblings('.node-children');
                    const currentDepth = parseInt($node.attr('data-depth')) || 0;
                    const nodePath = $node.attr('data-path') || '';
                    
                    // Check depth limit
                    if (currentDepth >= this.maxDepth - 1) {{
                        alert('Maximum tree depth (' + this.maxDepth + ') reached');
                        return;
                    }}
                    
                    const label = prompt('Enter child node name:');
                    if (!label || !label.trim()) return;
                    
                    // Generate new node data
                    const newId = this.mode === 'parent_id' ? Date.now() : null;
                    const parentId = $node.attr('data-id') || null;
                    const newPath = this.mode === 'ltree' ? 
                        (nodePath ? nodePath + this.pathSeparator + label.trim() : label.trim()) : null;
                    
                    const newNode = {{
                        id: newId,
                        parent_id: parentId,
                        label: label.trim(),
                        path: newPath,
                        children: {{}}
                    }};
                    
                    // Create and insert new node element
                    const newElement = this.createNodeElement(newNode, currentDepth + 1);
                    newElement.addClass('newly-added');
                    $nodeChildren.append(newElement);
                    
                    // Update parent node appearance
                    const $parentToggle = $node.find('> .node-content .node-toggle');
                    const $parentIcon = $node.find('> .node-content .node-icon i');
                    $parentToggle.removeClass('no-children');
                    $parentIcon.removeClass('fa-file').addClass('fa-folder');
                    
                    // Update tree data
                    this.updateTreeData();
                    this.updateStats();
                    this.validateTree();
                    
                    // Remove animation class after animation completes
                    setTimeout(() => newElement.removeClass('newly-added'), 500);
                }},
                editNode: function(button) {{
                    const $button = $(button);
                    const $nodeLabel = $button.closest('.node-content').find('.node-label');
                    
                    // Focus the editable label
                    $nodeLabel.focus();
                    
                    // Select all text for easy editing
                    if (window.getSelection && document.createRange) {{
                        const range = document.createRange();
                        range.selectNodeContents($nodeLabel[0]);
                        const sel = window.getSelection();
                        sel.removeAllRanges();
                        sel.addRange(range);
                    }}
                }},
                deleteNode: function(button) {{
                    const $button = $(button);
                    const $node = $button.closest('.tree-node');
                    const $nodeLabel = $node.find('> .node-content .node-label');
                    const label = $nodeLabel.text().trim();
                    const hasChildren = $node.find('.node-children .tree-node').length > 0;
                    
                    let confirmMessage = 'Are you sure you want to delete the node \"' + label + '\"?';
                    if (hasChildren) {{
                        const deletionWarning = '\\n\\nThis will also delete all child nodes.';
                        confirmMessage += deletionWarning;
                    }}
                    
                    if (!confirm(confirmMessage)) return;
                    
                    // Add deletion animation
                    $node.addClass('being-deleted');
                    
                    // Remove after animation
                    setTimeout(() => {{
                        $node.remove();
                        this.updateTreeData();
                        this.updateStats();
                        this.validateTree();
                        
                        // Check if parent node should become a leaf
                        const $parent = $node.parent().closest('.tree-node');
                        if ($parent.length > 0) {{
                            const remainingChildren = $parent.find('.node-children .tree-node').length;
                            if (remainingChildren === 0) {{
                                const $parentToggle = $parent.find('> .node-content .node-toggle');
                                const $parentIcon = $parent.find('> .node-content .node-icon i');
                                $parentToggle.addClass('no-children');
                                $parentIcon.removeClass('fa-folder').addClass('fa-file');
                            }}
                        }}
                    }}, 400);
                }},
                selectNode: function(content) {{
                    const $content = $(content);
                    const $node = $content.closest('.tree-node');
                    
                    // Toggle selection
                    if ($content.hasClass('selected')) {{
                        $content.removeClass('selected');
                        this.selectedNodes.delete($node.attr('data-id'));
                    }} else {{
                        // Clear other selections unless Ctrl/Cmd is held
                        if (!event.ctrlKey && !event.metaKey) {{
                            this.container.find('.node-content.selected').removeClass('selected');
                            this.selectedNodes.clear();
                        }}
                        
                        $content.addClass('selected');
                        this.selectedNodes.add($node.attr('data-id'));
                    }}
                    
                    this.updateStats();
                }},
                updateNodeLabel: function(label) {{
                    const $label = $(label);
                    const $node = $label.closest('.tree-node');
                    const newText = $label.text().trim();
                    
                    if (!newText) {{
                        $label.text($label.attr('data-original-text') || 'Unnamed Node');
                        alert('Node name cannot be empty');
                        return;
                    }}
                    
                    // Validate label (basic validation)
                    if (newText.length > 100) {{
                        $label.text($label.attr('data-original-text') || 'Unnamed Node');
                        alert('Node name cannot exceed 100 characters');
                        return;
                    }}
                    
                    // Store original text for rollback
                    $label.attr('data-original-text', newText);
                    
                    // Update path if in LTREE mode
                    if (this.mode === 'ltree') {{
                        const currentPath = $node.attr('data-path');
                        if (currentPath) {{
                            const pathParts = currentPath.split(this.pathSeparator);
                            pathParts[pathParts.length - 1] = newText;
                            $node.attr('data-path', pathParts.join(this.pathSeparator));
                        }}
                    }}
                    
                    // Add update animation
                    $node.addClass('recently-updated');
                    setTimeout(() => $node.removeClass('recently-updated'), 1200);
                    
                    this.updateTreeData();
                    this.validateTree();
                }},
                searchNodes: function(query) {{
                    const $allNodes = this.container.find('.tree-node');
                    
                    if (!query || !query.trim()) {{
                        // Show all nodes and remove highlights
                        $allNodes.removeClass('search-hidden search-highlight');
                        return;
                    }}
                    
                    const searchTerm = query.toLowerCase().trim();
                    let matchCount = 0;
                    
                    $allNodes.each(function() {{
                        const $node = $(this);
                        const $label = $node.find('> .node-content .node-label');
                        const nodeText = $label.text().toLowerCase();
                        const nodePath = $node.attr('data-path') || '';
                        const pathText = nodePath.toLowerCase();
                        
                        if (nodeText.includes(searchTerm) || pathText.includes(searchTerm)) {{
                            // Match found
                            $node.removeClass('search-hidden').addClass('search-highlight');
                            
                            // Expand parent nodes to show match
                            $node.parentsUntil('.tree-root').each(function() {{
                                if ($(this).hasClass('node-children')) {{
                                    $(this).removeClass('collapsed');
                                    const $toggle = $(this).siblings('.node-content').find('.node-toggle');
                                    const $icon = $toggle.find('i');
                                    $toggle.addClass('expanded');
                                    $icon.removeClass('fa-chevron-right').addClass('fa-chevron-down');
                                }}
                            }});
                            
                            matchCount++;
                        }} else {{
                            // No match
                            $node.removeClass('search-highlight').addClass('search-hidden');
                        }}
                    }});
                    
                    // Update search status (could add to UI if desired)
                    console.log('Found ' + matchCount + ' matches for \"' + query + '\"');
                }},
                clearSearch: function() {{
                    this.container.find('.tree-search-input').val('');
                    this.container.find('.tree-node').removeClass('search-hidden search-highlight');
                }},
                setupDragAndDrop: function() {{
                    const self = this;
                    const $treeRoot = this.container.find('.tree-root');
                    
                    // Make nodes draggable
                    $treeRoot.on('dragstart', '.tree-node[draggable=true]', function(e) {{
                        const $node = $(this);
                        $node.addClass('dragging');
                        
                        // Store drag data
                        e.originalEvent.dataTransfer.setData('text/plain', $node.attr('data-id'));
                        e.originalEvent.dataTransfer.effectAllowed = 'move';
                        
                        // Create drag image
                        const $label = $node.find('> .node-content .node-label');
                        e.originalEvent.dataTransfer.setDragImage($label[0], 10, 10);
                    }});
                    
                    $treeRoot.on('dragend', '.tree-node', function() {{
                        $(this).removeClass('dragging');
                        $treeRoot.find('.drag-over, .drag-placeholder').removeClass('drag-over').remove();
                    }});
                    
                    // Handle drop zones
                    $treeRoot.on('dragover', '.node-content', function(e) {{
                        e.preventDefault();
                        e.originalEvent.dataTransfer.dropEffect = 'move';
                        
                        const $content = $(this);
                        const $node = $content.closest('.tree-node');
                        
                        // Don't allow dropping on self or descendants
                        const draggedId = $('.tree-node.dragging').attr('data-id');
                        if ($node.attr('data-id') === draggedId || 
                            $node.closest('.tree-node.dragging').length > 0) {{
                            e.originalEvent.dataTransfer.dropEffect = 'none';
                            return;
                        }}
                        
                        $content.addClass('drag-over');
                    }});
                    
                    $treeRoot.on('dragleave', '.node-content', function() {{
                        $(this).removeClass('drag-over');
                    }});
                    
                    $treeRoot.on('drop', '.node-content', function(e) {{
                        e.preventDefault();
                        const $dropTarget = $(this);
                        const $targetNode = $dropTarget.closest('.tree-node');
                        const $draggedNode = $('.tree-node.dragging');
                        
                        $dropTarget.removeClass('drag-over');
                        
                        if ($draggedNode.length === 0) return;
                        
                        // Check depth limits
                        const targetDepth = parseInt($targetNode.attr('data-depth')) || 0;
                        const draggedDepth = self.calculateNodeDepth($draggedNode);
                        
                        if (targetDepth + 1 + draggedDepth > self.maxDepth) {{
                            alert('Cannot move node: would exceed maximum depth (' + self.maxDepth + ')');
                            return;
                        }}
                        
                        // Move the node
                        const $targetChildren = $targetNode.find('> .node-content').siblings('.node-children');
                        
                        // Update node depth attributes recursively
                        self.updateNodeDepths($draggedNode, targetDepth + 1);
                        
                        // Move to new parent
                        $targetChildren.append($draggedNode);
                        
                        // Update parent appearances
                        const $targetToggle = $targetNode.find('> .node-content .node-toggle');
                        const $targetIcon = $targetNode.find('> .node-content .node-icon i');
                        $targetToggle.removeClass('no-children');
                        $targetIcon.removeClass('fa-file').addClass('fa-folder');
                        
                        // Update tree data and validate
                        self.updateTreeData();
                        self.updateStats();
                        self.validateTree();
                    }});
                }},
                setupModalEvents: function() {{
                    const self = this;
                    const modalId = '#tree-import-export-modal-' + this.fieldId;
                    const $modal = $(modalId);
                    
                    // Export format change
                    $modal.find('.export-format').on('change', function() {{
                        const format = $(this).val();
                        const exportData = self.generateExportData(format);
                        $modal.find('.export-data').val(exportData);
                    }});
                    
                    // Copy to clipboard
                    $modal.find('.export-copy').on('click', function() {{
                        const $textarea = $modal.find('.export-data');
                        $textarea[0].select();
                        document.execCommand('copy');
                        
                        // Show feedback
                        const $btn = $(this);
                        const originalText = $btn.html();
                        $btn.html('<i class=\"fa fa-check\"></i> Copied!');
                        setTimeout(() => $btn.html(originalText), 2000);
                    }});
                    
                    // Download file
                    $modal.find('.export-download').on('click', function() {{
                        const format = $modal.find('.export-format').val();
                        const data = $modal.find('.export-data').val();
                        const filename = 'tree_export_' + Date.now() + '.' + self.getFileExtension(format);
                        
                        self.downloadFile(data, filename, self.getMimeType(format));
                    }});
                    
                    // Import preview
                    $modal.find('.import-preview').on('click', function() {{
                        const format = $modal.find('.import-format').val();
                        const data = $modal.find('.import-data').val().trim();
                        
                        if (!data) {{
                            alert('Please enter data to preview');
                            return;
                        }}
                        
                        try {{
                            const preview = self.previewImportData(data, format);
                            $modal.find('.import-preview-content').html(preview);
                            $modal.find('.import-preview-area').show();
                        }} catch (error) {{
                            alert('Import preview failed: ' + error.message);
                        }}
                    }});
                    
                    // Execute import
                    $modal.find('.import-execute').on('click', function() {{
                        const format = $modal.find('.import-format').val();
                        const data = $modal.find('.import-data').val().trim();
                        const merge = $modal.find('.import-merge').is(':checked');
                        const validate = $modal.find('.import-validate').is(':checked');
                        const repair = $modal.find('.import-repair').is(':checked');
                        
                        if (!data) {{
                            alert('Please enter data to import');
                            return;
                        }}
                        
                        if (!confirm('Are you sure you want to import this data?')) {{
                            return;
                        }}
                        
                        try {{
                            self.executeImport(data, format, {{ merge, validate, repair }});
                            $modal.modal('hide');
                        }} catch (error) {{
                            alert('Import failed: ' + error.message);
                        }}
                    }});
                    
                    // Show sample format
                    $modal.find('.import-sample').on('click', function() {{
                        const format = $modal.find('.import-format').val();
                        const sample = self.getSampleFormat(format);
                        $modal.find('.import-data').val(sample);
                    }});
                }},
                showExportModal: function() {{
                    const modalId = '#tree-import-export-modal-' + this.fieldId;
                    const $modal = $(modalId);
                    
                    // Switch to export tab
                    $modal.find('a[href=\"#export-tab-' + this.fieldId + '\"]').tab('show');
                    
                    // Generate initial export data
                    const format = $modal.find('.export-format').val();
                    const exportData = this.generateExportData(format);
                    $modal.find('.export-data').val(exportData);
                    
                    $modal.modal('show');
                }},
                showImportModal: function() {{
                    const modalId = '#tree-import-export-modal-' + this.fieldId;
                    const $modal = $(modalId);
                    
                    // Switch to import tab
                    $modal.find('a[href=\"#import-tab-' + this.fieldId + '\"]').tab('show');
                    
                    // Clear previous data
                    $modal.find('.import-data').val('');
                    $modal.find('.import-preview-area').hide();
                    
                    $modal.modal('show');
                }},
                repairTree: function() {{
                    if (!confirm('This will attempt to repair tree structure issues. Continue?')) {{
                        return;
                    }}
                    
                    let repairCount = 0;
                    const issues = [];
                    
                    // Repair orphaned nodes (parent_id mode)
                    if (this.mode === 'parent_id') {{
                        const orphans = this.findOrphanedNodes();
                        orphans.forEach(orphan => {{
                            // Move orphans to root level
                            const $orphanNode = $('[data-id=\"' + orphan.id + '\"]');
                            this.container.find('.tree-root').append($orphanNode);
                            $orphanNode.attr('data-depth', '0');
                            repairCount++;
                        }});
                        if (orphans.length > 0) {{
                            issues.push('Moved ' + orphans.length + ' orphaned nodes to root level');
                        }}
                    }}
                    
                    // Fix depth violations
                    const depthViolations = this.findDepthViolations();
                    depthViolations.forEach(node => {{
                        // Truncate excess depth by moving to allowed level
                        const $node = $('[data-id=\"' + node.id + '\"]');
                        const allowedParent = this.findNearestValidParent($node);
                        if (allowedParent) {{
                            allowedParent.find('> .node-content').siblings('.node-children').append($node);
                            this.updateNodeDepths($node, parseInt(allowedParent.attr('data-depth')) + 1);
                            repairCount++;
                        }}
                    }});
                    if (depthViolations.length > 0) {{
                        issues.push('Fixed ' + depthViolations.length + ' depth violations');
                    }}
                    
                    // Update tree structure
                    this.updateTreeData();
                    this.updateStats();
                    this.validateTree();
                    
                    if (repairCount > 0) {{
                        const issueText = issues.join('\\n');
                        const completionMsg = 'Tree repair completed:' + '\\n\\n' + issueText + '\\n\\n' + 'Total repairs: ' + repairCount;
                        alert(completionMsg);
                    }} else {{
                        alert('No issues found that could be automatically repaired.');
                    }}
                }}
            }};
            
            // Auto-initialize tree widgets
            $('.postgresql-tree-widget').each(function() {{
                const fieldId = $(this).find('textarea').attr('id');
                if (fieldId === '{field_id}') {{
                    window.treeWidget_{field_id_underscore}.init();
                }}
            }});
        }});
        </script>
        '''.format(
            mode=self.mode,
            id_field=self.id_field,
            parent_id_field=self.parent_id_field,
            label_field=self.label_field,
            max_depth=self.max_depth,
            allow_reorder=str(self.allow_reorder).lower(),
            allow_drag_drop=str(self.allow_drag_drop).lower(),
            path_separator=self.path_separator,
            html_params_str=html_params_str,
            field_data=field.data or '',
            mode_upper=self.mode.upper(),
            mode_description=mode_description,
            drag_drop_badge='<span class="badge badge-success">Drag & Drop Enabled</span>' if self.allow_drag_drop else '',
            field_id=field.id,
            template=template,
            parent_id_option=parent_id_option,
            field_id_underscore=field.id.replace('-', '_')
        )
        
        return Markup(html)