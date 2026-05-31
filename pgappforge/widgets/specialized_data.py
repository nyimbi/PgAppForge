"""
Specialized Data Type Widget Components for PgForge

This module provides widgets specifically designed for complex data types
including JSON, arrays, spatial data, and other specialized formats.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from flask import render_template_string, url_for
from markupsafe import Markup
from flask_babel import gettext, lazy_gettext
from wtforms.widgets import TextArea, Input, Select
from wtforms.widgets.core import html_params

log = logging.getLogger(__name__)


class JSONEditorWidget(TextArea):
    """
    Advanced JSON editor widget with syntax highlighting and validation.
    
    Features:
    - JSON syntax highlighting
    - Real-time validation
    - Collapsible tree view
    - Search and replace
    - Formatting and minification
    - Schema validation
    - Import/export functionality
    - Undo/redo support
    """
    
    def __init__(self,
                 schema: Optional[Dict] = None,
                 show_tree_view: bool = True,
                 enable_search: bool = True,
                 auto_format: bool = True,
                 readonly: bool = False):
        """
        Initialize the JSON editor widget.
        
        Args:
            schema: JSON schema for validation
            show_tree_view: Show tree view panel
            enable_search: Enable search functionality
            auto_format: Auto-format JSON on change
            readonly: Make editor read-only
        """
        self.schema = schema
        self.show_tree_view = show_tree_view
        self.enable_search = enable_search
        self.auto_format = auto_format
        self.readonly = readonly
        
    def __call__(self, field, **kwargs):
        """Render the JSON editor widget."""
        widget_id = kwargs.get('id', f'json_editor_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="json-editor-container" data-widget="json-editor">
            <div class="json-editor-toolbar">
                <div class="toolbar-group">
                    <button type="button" class="btn btn-sm btn-outline-secondary" data-action="format">
                        <i class="fa fa-code"></i> {{ _('Format') }}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" data-action="minify">
                        <i class="fa fa-compress"></i> {{ _('Minify') }}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" data-action="validate">
                        <i class="fa fa-check"></i> {{ _('Validate') }}
                    </button>
                </div>
                
                {% if enable_search %}
                <div class="toolbar-group">
                    <div class="search-box">
                        <input type="text" class="form-control form-control-sm" 
                               placeholder="{{ _('Search...') }}" data-search="json">
                        <button type="button" class="btn btn-sm btn-outline-secondary" data-action="find-next">
                            <i class="fa fa-chevron-down"></i>
                        </button>
                    </div>
                </div>
                {% endif %}
                
                <div class="toolbar-group">
                    <button type="button" class="btn btn-sm btn-outline-info" data-action="toggle-tree">
                        <i class="fa fa-tree"></i> {{ _('Tree View') }}
                    </button>
                    {% if show_tree_view %}
                    <button type="button" class="btn btn-sm btn-outline-secondary" data-action="expand-all">
                        <i class="fa fa-plus-square-o"></i> {{ _('Expand All') }}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" data-action="collapse-all">
                        <i class="fa fa-minus-square-o"></i> {{ _('Collapse All') }}
                    </button>
                    {% endif %}
                </div>
            </div>
            
            <div class="json-editor-main">
                <div class="json-editor-panel">
                    <div class="editor-wrapper">
                        <textarea id="{{ widget_id }}" name="{{ field.name }}" 
                                  class="form-control json-textarea"
                                  {% if readonly %}readonly{% endif %}>{{ field.data or '{}' }}</textarea>
                        
                        <div class="editor-overlay">
                            <div class="line-numbers"></div>
                            <div class="syntax-highlights"></div>
                        </div>
                    </div>
                    
                    <div class="validation-panel">
                        <div class="validation-messages"></div>
                    </div>
                </div>
                
                {% if show_tree_view %}
                <div class="json-tree-panel">
                    <h6>{{ _('Tree View') }}</h6>
                    <div class="json-tree" id="tree-{{ widget_id }}">
                        <!-- Tree view will be rendered here -->
                    </div>
                </div>
                {% endif %}
            </div>
        </div>
        
        <style>
        .json-editor-container {
            border: 1px solid #dee2e6;
            border-radius: 8px;
            background: white;
            min-height: 400px;
        }
        
        .json-editor-toolbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem 1rem;
            border-bottom: 1px solid #e9ecef;
            background: #f8f9fa;
            border-radius: 8px 8px 0 0;
        }
        
        .toolbar-group {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .search-box {
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }
        
        .search-box input {
            width: 200px;
        }
        
        .json-editor-main {
            display: flex;
            height: 350px;
        }
        
        .json-editor-panel {
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        
        .editor-wrapper {
            flex: 1;
            position: relative;
            overflow: hidden;
        }
        
        .json-textarea {
            width: 100%;
            height: 100%;
            border: none;
            border-radius: 0;
            resize: none;
            font-family: 'Monaco', 'Consolas', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.4;
            padding: 1rem;
            background: transparent;
            z-index: 2;
            position: relative;
        }
        
        .json-textarea:focus {
            outline: none;
            box-shadow: none;
        }
        
        .editor-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            pointer-events: none;
            z-index: 1;
        }
        
        .line-numbers {
            position: absolute;
            left: 0;
            top: 0;
            width: 50px;
            height: 100%;
            background: #f8f9fa;
            border-right: 1px solid #e9ecef;
            font-family: 'Monaco', 'Consolas', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.4;
            padding: 1rem 0.5rem;
            color: #6c757d;
            text-align: right;
        }
        
        .syntax-highlights {
            position: absolute;
            left: 50px;
            top: 0;
            right: 0;
            bottom: 0;
            font-family: 'Monaco', 'Consolas', 'Courier New', monospace;
            font-size: 14px;
            line-height: 1.4;
            padding: 1rem;
            color: transparent;
            white-space: pre;
            overflow: hidden;
        }
        
        .validation-panel {
            border-top: 1px solid #e9ecef;
            padding: 0.5rem 1rem;
            background: #f8f9fa;
            min-height: 40px;
            max-height: 100px;
            overflow-y: auto;
        }
        
        .validation-messages {
            font-size: 0.875rem;
        }
        
        .validation-message {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.25rem;
        }
        
        .validation-message.error {
            color: #dc3545;
        }
        
        .validation-message.success {
            color: #198754;
        }
        
        .json-tree-panel {
            width: 300px;
            border-left: 1px solid #e9ecef;
            padding: 1rem;
            background: #fdfdfd;
            overflow-y: auto;
        }
        
        .json-tree-panel h6 {
            margin-bottom: 1rem;
        }
        
        .json-tree {
            font-family: 'Monaco', 'Consolas', 'Courier New', monospace;
            font-size: 13px;
        }
        
        .tree-node {
            margin-left: 1rem;
            margin-bottom: 0.25rem;
        }
        
        .tree-node.root {
            margin-left: 0;
        }
        
        .tree-key {
            font-weight: 600;
            color: #0d6efd;
            cursor: pointer;
        }
        
        .tree-value {
            margin-left: 0.5rem;
        }
        
        .tree-value.string {
            color: #198754;
        }
        
        .tree-value.number {
            color: #fd7e14;
        }
        
        .tree-value.boolean {
            color: #6f42c1;
        }
        
        .tree-value.null {
            color: #6c757d;
            font-style: italic;
        }
        
        .tree-toggle {
            cursor: pointer;
            color: #6c757d;
            margin-right: 0.25rem;
        }
        
        .tree-node.collapsed .tree-children {
            display: none;
        }
        
        /* JSON Syntax Highlighting */
        .json-string { color: #198754; }
        .json-number { color: #fd7e14; }
        .json-boolean { color: #6f42c1; }
        .json-null { color: #6c757d; font-style: italic; }
        .json-key { color: #0d6efd; font-weight: 600; }
        .json-punctuation { color: #495057; }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="json-editor"]');
            const textarea = document.getElementById('{{ widget_id }}');
            const treePanel = document.getElementById('tree-{{ widget_id }}');
            const validationMessages = container.querySelector('.validation-messages');
            const lineNumbers = container.querySelector('.line-numbers');
            const syntaxHighlights = container.querySelector('.syntax-highlights');
            
            let jsonData = {};
            let validationTimeout;
            
            // Initialize editor
            function initializeEditor() {
                try {
                    jsonData = JSON.parse(textarea.value || '{}');
                    updateLineNumbers();
                    updateSyntaxHighlighting();
                    updateTreeView();
                    validateJSON();
                } catch (e) {
                    showValidationError('Invalid JSON: ' + e.message);
                }
            }
            
            // Update line numbers
            function updateLineNumbers() {
                const lines = textarea.value.split('\\n');
                const lineNumbersHtml = lines.map((_, index) => index + 1).join('\\n');
                lineNumbers.textContent = lineNumbersHtml;
            }
            
            // Update syntax highlighting
            function updateSyntaxHighlighting() {
                const content = textarea.value;
                const highlighted = highlightJSON(content);
                syntaxHighlights.innerHTML = highlighted;
            }
            
            // Simple JSON syntax highlighting
            function highlightJSON(json) {
                return json
                    .replace(/("(\\\\.|[^"\\\\])*")(\\s*:)/g, '<span class="json-key">$1</span>$3')
                    .replace(/("(\\\\.|[^"\\\\])*")(?!\\s*:)/g, '<span class="json-string">$1</span>')
                    .replace(/(\\b\\d+(\\.\\d+)?\\b)/g, '<span class="json-number">$1</span>')
                    .replace(/(\\b(true|false)\\b)/g, '<span class="json-boolean">$1</span>')
                    .replace(/(\\bnull\\b)/g, '<span class="json-null">$1</span>')
                    .replace(/([{}\\[\\],:])/g, '<span class="json-punctuation">$1</span>');
            }
            
            // Update tree view
            function updateTreeView() {
                {% if show_tree_view %}
                if (treePanel) {
                    try {
                        const data = JSON.parse(textarea.value || '{}');
                        treePanel.innerHTML = renderTreeNode(data, '', true);
                    } catch (e) {
                        treePanel.innerHTML = '<p class="text-muted">Invalid JSON</p>';
                    }
                }
                {% endif %}
            }
            
            // Render tree node
            function renderTreeNode(value, key, isRoot = false) {
                const nodeClass = isRoot ? 'tree-node root' : 'tree-node';
                
                if (value === null) {
                    return `<div class="${nodeClass}">
                        ${key ? `<span class="tree-key">${key}:</span>` : ''}
                        <span class="tree-value null">null</span>
                    </div>`;
                }
                
                if (typeof value === 'object' && !Array.isArray(value)) {
                    const keys = Object.keys(value);
                    const hasChildren = keys.length > 0;
                    
                    let html = `<div class="${nodeClass}">`;
                    if (hasChildren) {
                        html += `<span class="tree-toggle"><i class="fa fa-minus-square-o"></i></span>`;
                    }
                    if (key) {
                        html += `<span class="tree-key">${key}:</span> `;
                    }
                    html += `<span class="tree-value">{${keys.length} ${keys.length === 1 ? 'item' : 'items'}}</span>`;
                    
                    if (hasChildren) {
                        html += '<div class="tree-children">';
                        keys.forEach(k => {
                            html += renderTreeNode(value[k], k);
                        });
                        html += '</div>';
                    }
                    
                    html += '</div>';
                    return html;
                }
                
                if (Array.isArray(value)) {
                    const hasChildren = value.length > 0;
                    
                    let html = `<div class="${nodeClass}">`;
                    if (hasChildren) {
                        html += `<span class="tree-toggle"><i class="fa fa-minus-square-o"></i></span>`;
                    }
                    if (key) {
                        html += `<span class="tree-key">${key}:</span> `;
                    }
                    html += `<span class="tree-value">[${value.length} ${value.length === 1 ? 'item' : 'items'}]</span>`;
                    
                    if (hasChildren) {
                        html += '<div class="tree-children">';
                        value.forEach((item, index) => {
                            html += renderTreeNode(item, `[${index}]`);
                        });
                        html += '</div>';
                    }
                    
                    html += '</div>';
                    return html;
                }
                
                // Primitive values
                const valueType = typeof value;
                const valueClass = valueType === 'string' ? 'string' : 
                                 valueType === 'number' ? 'number' : 
                                 valueType === 'boolean' ? 'boolean' : '';
                
                const displayValue = valueType === 'string' ? `"${value}"` : String(value);
                
                return `<div class="${nodeClass}">
                    ${key ? `<span class="tree-key">${key}:</span>` : ''}
                    <span class="tree-value ${valueClass}">${displayValue}</span>
                </div>`;
            }
            
            // Validate JSON
            function validateJSON() {
                validationMessages.innerHTML = '';
                
                try {
                    const parsed = JSON.parse(textarea.value);
                    
                    // Schema validation if provided
                    {% if schema %}
                    const schema = {{ schema | tojson }};
                    const validation = validateAgainstSchema(parsed, schema);
                    if (!validation.valid) {
                        validation.errors.forEach(error => {
                            showValidationError(error);
                        });
                        return;
                    }
                    {% endif %}
                    
                    showValidationSuccess('Valid JSON');
                } catch (e) {
                    showValidationError('Invalid JSON: ' + e.message);
                }
            }
            
            // Show validation error
            function showValidationError(message) {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'validation-message error';
                messageDiv.innerHTML = `<i class="fa fa-times"></i> ${message}`;
                validationMessages.appendChild(messageDiv);
            }
            
            // Show validation success
            function showValidationSuccess(message) {
                const messageDiv = document.createElement('div');
                messageDiv.className = 'validation-message success';
                messageDiv.innerHTML = `<i class="fa fa-check"></i> ${message}`;
                validationMessages.appendChild(messageDiv);
            }
            
            // Format JSON
            function formatJSON() {
                try {
                    const parsed = JSON.parse(textarea.value);
                    textarea.value = JSON.stringify(parsed, null, 2);
                    updateEditor();
                } catch (e) {
                    showValidationError('Cannot format invalid JSON');
                }
            }
            
            // Minify JSON
            function minifyJSON() {
                try {
                    const parsed = JSON.parse(textarea.value);
                    textarea.value = JSON.stringify(parsed);
                    updateEditor();
                } catch (e) {
                    showValidationError('Cannot minify invalid JSON');
                }
            }
            
            // Update all editor components
            function updateEditor() {
                updateLineNumbers();
                updateSyntaxHighlighting();
                updateTreeView();
                
                // Debounced validation
                clearTimeout(validationTimeout);
                validationTimeout = setTimeout(validateJSON, 500);
            }
            
            // Event listeners
            textarea.addEventListener('input', updateEditor);
            textarea.addEventListener('scroll', () => {
                syntaxHighlights.scrollTop = textarea.scrollTop;
                lineNumbers.scrollTop = textarea.scrollTop;
            });
            
            // Toolbar actions
            container.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (!action) return;
                
                switch (action) {
                    case 'format':
                        formatJSON();
                        break;
                    case 'minify':
                        minifyJSON();
                        break;
                    case 'validate':
                        validateJSON();
                        break;
                    case 'toggle-tree':
                        {% if show_tree_view %}
                        const treePanel = container.querySelector('.json-tree-panel');
                        if (treePanel) {
                            treePanel.style.display = treePanel.style.display === 'none' ? 'block' : 'none';
                        }
                        {% endif %}
                        break;
                    case 'expand-all':
                        container.querySelectorAll('.tree-node.collapsed').forEach(node => {
                            node.classList.remove('collapsed');
                            const icon = node.querySelector('.tree-toggle i');
                            if (icon) icon.className = 'fa fa-minus-square-o';
                        });
                        break;
                    case 'collapse-all':
                        container.querySelectorAll('.tree-node').forEach(node => {
                            if (node.querySelector('.tree-children')) {
                                node.classList.add('collapsed');
                                const icon = node.querySelector('.tree-toggle i');
                                if (icon) icon.className = 'fa fa-plus-square-o';
                            }
                        });
                        break;
                }
            });
            
            // Tree toggle functionality
            container.addEventListener('click', (e) => {
                if (e.target.closest('.tree-toggle')) {
                    const node = e.target.closest('.tree-node');
                    const icon = node.querySelector('.tree-toggle i');
                    
                    if (node.classList.contains('collapsed')) {
                        node.classList.remove('collapsed');
                        icon.className = 'fa fa-minus-square-o';
                    } else {
                        node.classList.add('collapsed');
                        icon.className = 'fa fa-plus-square-o';
                    }
                }
            });
            
            // Search functionality
            {% if enable_search %}
            const searchInput = container.querySelector('[data-search="json"]');
            if (searchInput) {
                searchInput.addEventListener('input', (e) => {
                    const query = e.target.value.toLowerCase();
                    if (!query) return;
                    
                    const content = textarea.value.toLowerCase();
                    const index = content.indexOf(query);
                    if (index !== -1) {
                        textarea.focus();
                        textarea.setSelectionRange(index, index + query.length);
                    }
                });
            }
            {% endif %}
            
            // Initialize
            initializeEditor();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            schema=self.schema,
            show_tree_view=self.show_tree_view,
            enable_search=self.enable_search,
            auto_format=self.auto_format,
            readonly=self.readonly,
            _=gettext
        ))


class ArrayEditorWidget(Input):
    """
    Dynamic array editor widget for managing lists of items.
    
    Features:
    - Add/remove array items
    - Drag & drop reordering
    - Different input types per item
    - Nested array support
    - Bulk operations
    - Import/export
    - Validation per item
    """
    
    input_type = 'hidden'
    
    def __init__(self,
                 item_type: str = 'text',
                 item_options: Optional[Dict] = None,
                 sortable: bool = True,
                 max_items: Optional[int] = None,
                 min_items: int = 0,
                 allow_duplicates: bool = True):
        """
        Initialize the array editor widget.
        
        Args:
            item_type: Type of items in the array
            item_options: Options for item widgets
            sortable: Enable drag & drop sorting
            max_items: Maximum number of items
            min_items: Minimum number of items
            allow_duplicates: Allow duplicate values
        """
        self.item_type = item_type
        self.item_options = item_options or {}
        self.sortable = sortable
        self.max_items = max_items
        self.min_items = min_items
        self.allow_duplicates = allow_duplicates
        
    def __call__(self, field, **kwargs):
        """Render the array editor widget."""
        widget_id = kwargs.get('id', f'array_editor_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="array-editor-container" data-widget="array-editor">
            <div class="array-editor-header">
                <h6>{{ _('Array Editor') }}</h6>
                <div class="array-actions">
                    <button type="button" class="btn btn-primary btn-sm" data-action="add-item">
                        <i class="fa fa-plus"></i> {{ _('Add Item') }}
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm" data-action="clear-all">
                        <i class="fa fa-trash"></i> {{ _('Clear All') }}
                    </button>
                </div>
            </div>
            
            <div class="array-items" id="items-{{ widget_id }}">
                <!-- Array items will be rendered here -->
            </div>
            
            <div class="array-footer">
                <small class="text-muted">
                    <span class="item-count">0</span> {{ _('items') }}
                    {% if min_items > 0 %} | {{ _('Minimum') }}: {{ min_items }}{% endif %}
                    {% if max_items %} | {{ _('Maximum') }}: {{ max_items }}{% endif %}
                </small>
            </div>
            
            <input type="hidden" id="{{ widget_id }}" name="{{ field.name }}" value="{{ field.data or '[]' }}">
        </div>
        
        <style>
        .array-editor-container {
            border: 1px solid #dee2e6;
            border-radius: 8px;
            background: white;
        }
        
        .array-editor-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem;
            border-bottom: 1px solid #e9ecef;
            background: #f8f9fa;
            border-radius: 8px 8px 0 0;
        }
        
        .array-editor-header h6 {
            margin: 0;
        }
        
        .array-actions {
            display: flex;
            gap: 0.5rem;
        }
        
        .array-items {
            padding: 1rem;
            min-height: 100px;
            max-height: 400px;
            overflow-y: auto;
        }
        
        .array-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            background: #fdfdfd;
            transition: all 0.2s ease;
        }
        
        .array-item:hover {
            border-color: #0d6efd;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        
        .array-item.dragging {
            opacity: 0.5;
            transform: rotate(2deg);
        }
        
        .item-index {
            min-width: 30px;
            font-weight: 600;
            color: #6c757d;
            text-align: center;
        }
        
        .item-input {
            flex: 1;
        }
        
        .item-input .form-control {
            border: none;
            background: transparent;
            padding: 0.25rem 0.5rem;
        }
        
        .item-input .form-control:focus {
            background: white;
            border: 1px solid #0d6efd;
            box-shadow: 0 0 0 0.2rem rgba(13, 110, 253, 0.25);
        }
        
        .item-actions {
            display: flex;
            gap: 0.25rem;
        }
        
        .drag-handle {
            cursor: grab;
            color: #6c757d;
            padding: 0.25rem;
        }
        
        .drag-handle:active {
            cursor: grabbing;
        }
        
        .array-footer {
            padding: 0.5rem 1rem;
            border-top: 1px solid #e9ecef;
            background: #f8f9fa;
            border-radius: 0 0 8px 8px;
        }
        
        .empty-array {
            text-align: center;
            padding: 2rem;
            color: #6c757d;
        }
        
        .empty-array i {
            font-size: 2rem;
            margin-bottom: 0.5rem;
            display: block;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="array-editor"]');
            const itemsContainer = document.getElementById('items-{{ widget_id }}');
            const hiddenInput = document.getElementById('{{ widget_id }}');
            const itemCount = container.querySelector('.item-count');
            
            let arrayItems = [];
            let itemIdCounter = 0;
            
            // Initialize with existing data
            function initializeArray() {
                const existingData = hiddenInput.value;
                if (existingData && existingData !== '[]') {
                    try {
                        arrayItems = JSON.parse(existingData);
                        renderItems();
                    } catch (e) {
                        console.warn('Invalid array data:', e);
                        arrayItems = [];
                    }
                } else {
                    arrayItems = [];
                }
                
                // Ensure minimum items
                while (arrayItems.length < {{ min_items }}) {
                    addItem('');
                }
                
                renderItems();
            }
            
            // Add new item
            function addItem(value = '') {
                // Check maximum limit
                {% if max_items %}
                if (arrayItems.length >= {{ max_items }}) {
                    alert(`Maximum {{ max_items }} items allowed`);
                    return;
                }
                {% endif %}
                
                itemIdCounter++;
                const newItem = {
                    id: `item_${itemIdCounter}`,
                    value: value
                };
                
                arrayItems.push(newItem);
                renderItems();
                
                // Focus on new item
                const newItemElement = itemsContainer.querySelector(`[data-item-id="${newItem.id}"] input`);
                if (newItemElement) {
                    newItemElement.focus();
                }
            }
            
            // Remove item
            function removeItem(itemId) {
                const index = arrayItems.findIndex(item => item.id === itemId);
                if (index !== -1) {
                    // Check minimum limit
                    if (arrayItems.length <= {{ min_items }}) {
                        alert(`Minimum {{ min_items }} items required`);
                        return;
                    }
                    
                    arrayItems.splice(index, 1);
                    renderItems();
                }
            }
            
            // Move item
            function moveItem(fromIndex, toIndex) {
                if (fromIndex === toIndex) return;
                
                const item = arrayItems.splice(fromIndex, 1)[0];
                arrayItems.splice(toIndex, 0, item);
                renderItems();
            }
            
            // Render all items
            function renderItems() {
                if (arrayItems.length === 0) {
                    itemsContainer.innerHTML = `
                        <div class="empty-array">
                            <i class="fa fa-list"></i>
                            <p>{{ _('No items in array. Click "Add Item" to get started.') }}</p>
                        </div>
                    `;
                } else {
                    itemsContainer.innerHTML = '';
                    arrayItems.forEach((item, index) => {
                        const itemElement = createItemElement(item, index);
                        itemsContainer.appendChild(itemElement);
                    });
                }
                
                updateItemCount();
                updateHiddenInput();
            }
            
            // Create item element
            function createItemElement(item, index) {
                const itemDiv = document.createElement('div');
                itemDiv.className = 'array-item';
                itemDiv.dataset.itemId = item.id;
                itemDiv.dataset.index = index;
                itemDiv.draggable = {{ sortable | tojson }};
                
                let inputHtml = '';
                switch ('{{ item_type }}') {
                    case 'textarea':
                        inputHtml = `<textarea class="form-control" placeholder="{{ _('Enter value...') }}">${item.value || ''}</textarea>`;
                        break;
                    case 'number':
                        inputHtml = `<input type="number" class="form-control" placeholder="{{ _('Enter number...') }}" value="${item.value || ''}">`;
                        break;
                    case 'email':
                        inputHtml = `<input type="email" class="form-control" placeholder="{{ _('Enter email...') }}" value="${item.value || ''}">`;
                        break;
                    case 'url':
                        inputHtml = `<input type="url" class="form-control" placeholder="{{ _('Enter URL...') }}" value="${item.value || ''}">`;
                        break;
                    case 'date':
                        inputHtml = `<input type="date" class="form-control" value="${item.value || ''}">`;
                        break;
                    default:
                        inputHtml = `<input type="text" class="form-control" placeholder="{{ _('Enter value...') }}" value="${item.value || ''}">`;
                }
                
                itemDiv.innerHTML = `
                    <div class="item-index">${index + 1}</div>
                    {% if sortable %}
                    <div class="drag-handle">
                        <i class="fa fa-bars"></i>
                    </div>
                    {% endif %}
                    <div class="item-input">
                        ${inputHtml}
                    </div>
                    <div class="item-actions">
                        <button type="button" class="btn btn-sm btn-outline-success" data-action="duplicate">
                            <i class="fa fa-copy"></i>
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-danger" data-action="remove">
                            <i class="fa fa-times"></i>
                        </button>
                    </div>
                `;
                
                return itemDiv;
            }
            
            // Update item count display
            function updateItemCount() {
                itemCount.textContent = arrayItems.length;
            }
            
            // Update hidden input
            function updateHiddenInput() {
                const values = arrayItems.map(item => item.value);
                hiddenInput.value = JSON.stringify(values);
            }
            
            // Validate for duplicates
            function validateDuplicates(value, currentItemId) {
                {% if not allow_duplicates %}
                const duplicateExists = arrayItems.some(item => 
                    item.id !== currentItemId && item.value === value
                );
                
                if (duplicateExists) {
                    alert('{{ _("Duplicate values are not allowed") }}');
                    return false;
                }
                {% endif %}
                
                return true;
            }
            
            // Event listeners
            container.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (!action) return;
                
                const itemElement = e.target.closest('.array-item');
                const itemId = itemElement?.dataset.itemId;
                
                switch (action) {
                    case 'add-item':
                        addItem();
                        break;
                        
                    case 'remove':
                        if (itemId) {
                            removeItem(itemId);
                        }
                        break;
                        
                    case 'duplicate':
                        if (itemId) {
                            const originalItem = arrayItems.find(item => item.id === itemId);
                            if (originalItem) {
                                addItem(originalItem.value);
                            }
                        }
                        break;
                        
                    case 'clear-all':
                        if (confirm('{{ _("Are you sure you want to clear all items?") }}')) {
                            arrayItems = [];
                            // Add minimum items back
                            while (arrayItems.length < {{ min_items }}) {
                                addItem('');
                            }
                            renderItems();
                        }
                        break;
                }
            });
            
            // Input changes
            itemsContainer.addEventListener('input', (e) => {
                const itemElement = e.target.closest('.array-item');
                if (!itemElement) return;
                
                const itemId = itemElement.dataset.itemId;
                const item = arrayItems.find(item => item.id === itemId);
                
                if (item) {
                    const newValue = e.target.value;
                    if (validateDuplicates(newValue, itemId)) {
                        item.value = newValue;
                        updateHiddenInput();
                    } else {
                        // Revert to previous value
                        e.target.value = item.value;
                    }
                }
            });
            
            {% if sortable %}
            // Drag & drop functionality
            let draggedIndex = -1;
            
            itemsContainer.addEventListener('dragstart', (e) => {
                const itemElement = e.target.closest('.array-item');
                if (itemElement) {
                    draggedIndex = parseInt(itemElement.dataset.index);
                    itemElement.classList.add('dragging');
                    e.dataTransfer.effectAllowed = 'move';
                }
            });
            
            itemsContainer.addEventListener('dragend', (e) => {
                const itemElement = e.target.closest('.array-item');
                if (itemElement) {
                    itemElement.classList.remove('dragging');
                    draggedIndex = -1;
                }
            });
            
            itemsContainer.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
            });
            
            itemsContainer.addEventListener('drop', (e) => {
                e.preventDefault();
                const dropTarget = e.target.closest('.array-item');
                if (dropTarget && draggedIndex >= 0) {
                    const dropIndex = parseInt(dropTarget.dataset.index);
                    moveItem(draggedIndex, dropIndex);
                }
            });
            {% endif %}
            
            // Initialize
            initializeArray();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            item_type=self.item_type,
            item_options=self.item_options,
            sortable=self.sortable,
            max_items=self.max_items,
            min_items=self.min_items,
            allow_duplicates=self.allow_duplicates,
            _=gettext
        ))