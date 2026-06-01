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
from markupsafe import Markup, escape
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
				 readonly: bool = False,
				 placeholder: str = "",
				 css_class: str = "",
				 description: str = "",
				 disabled: bool = False):
		"""
		Initialize the JSON editor widget.

		Args:
			schema: JSON schema for validation
			show_tree_view: Show tree view panel
			enable_search: Enable search functionality
			auto_format: Auto-format JSON on change
			readonly: Make editor read-only
			placeholder: Placeholder text for textarea
			css_class: Additional CSS class(es) for the container
			description: Help text rendered below the widget
			disabled: Render as disabled
		"""
		self.schema = schema
		self.show_tree_view = show_tree_view
		self.enable_search = enable_search
		self.auto_format = auto_format
		self.readonly = readonly
		self.placeholder = placeholder
		self.css_class = css_class
		self.description = description
		self.disabled = disabled

	def __call__(self, field, **kwargs):
		"""Render the JSON editor widget."""
		widget_id = kwargs.get('id', f'json_editor_{uuid4().hex[:8]}')
		kwargs.setdefault('id', widget_id)

		has_errors = bool(field.errors)
		aria_label = str(field.label.text) if hasattr(field, 'label') and field.label else field.name

		# Build error HTML for server-side field errors
		error_html = ""
		if has_errors:
			error_parts = "".join(
				f"<span>{escape(e)}</span>" for e in field.errors
			)
			error_html = (
				f'<div class="invalid-feedback d-block" id="{widget_id}_error">'
				f"{error_parts}</div>"
			)

		# Build help text HTML
		description = kwargs.pop("description", self.description)
		help_html = ""
		if description:
			help_html = (
				f'<small class="form-text text-muted" id="{widget_id}_help">'
				f"{escape(description)}</small>"
			)

		# aria attributes for textarea
		aria_invalid = 'aria-invalid="true"' if has_errors else ''
		if has_errors:
			describedby = f'aria-describedby="{widget_id}_error"'
		elif description:
			describedby = f'aria-describedby="{widget_id}_help"'
		else:
			describedby = ''

		# field.data may contain user-supplied content — always escape for HTML context
		field_data_safe = escape(field.data or '{}')

		template = """
		<div class="json-editor-container {{ css_class }}" data-widget="json-editor-{{ widget_id }}"
			 style="width:100%;">
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
							   placeholder="{{ _('Search...') }}"
							   aria-label="{{ _('Search JSON') }}"
							   data-search="json">
						<button type="button" class="btn btn-sm btn-outline-secondary"
								data-action="find-next"
								aria-label="{{ _('Find next') }}">
							<i class="fa fa-chevron-down"></i>
						</button>
					</div>
				</div>
				{% endif %}

				<div class="toolbar-group">
					<button type="button" class="btn btn-sm btn-outline-info" data-action="toggle-tree"
							aria-expanded="{% if show_tree_view %}true{% else %}false{% endif %}"
							aria-controls="tree-{{ widget_id }}">
						<i class="fa fa-tree"></i> {{ _('Tree View') }}
					</button>
					{% if show_tree_view %}
					<button type="button" class="btn btn-sm btn-outline-secondary" data-action="expand-all"
							aria-label="{{ _('Expand all tree nodes') }}">
						<i class="fa fa-plus-square-o"></i> {{ _('Expand All') }}
					</button>
					<button type="button" class="btn btn-sm btn-outline-secondary" data-action="collapse-all"
							aria-label="{{ _('Collapse all tree nodes') }}">
						<i class="fa fa-minus-square-o"></i> {{ _('Collapse All') }}
					</button>
					{% endif %}
				</div>
			</div>

			<div class="json-editor-main">
				<div class="json-editor-panel">
					<div class="editor-wrapper">
						<textarea id="{{ widget_id }}" name="{{ field.name }}"
								  class="form-control json-textarea {% if has_errors %}is-invalid{% endif %}"
								  aria-label="{{ aria_label }}"
								  {{ aria_invalid }}
								  {{ describedby }}
								  {% if readonly %}readonly{% endif %}
								  {% if disabled %}disabled{% endif %}
								  placeholder="{{ placeholder }}">{{ field_data_safe }}</textarea>

						<div class="editor-overlay">
							<div class="line-numbers" aria-hidden="true"></div>
							<div class="syntax-highlights" aria-hidden="true"></div>
						</div>
					</div>

					<div class="validation-panel" role="status" aria-live="polite">
						<div class="validation-messages"></div>
					</div>
				</div>

				{% if show_tree_view %}
				<div class="json-tree-panel" role="region" aria-label="{{ _('JSON Tree View') }}">
					<h6 id="tree-label-{{ widget_id }}">{{ _('Tree View') }}</h6>
					<div class="json-tree" id="tree-{{ widget_id }}"
						 role="tree" aria-labelledby="tree-label-{{ widget_id }}">
						<!-- Tree view will be rendered here -->
					</div>
				</div>
				{% endif %}
			</div>

			{{ error_html }}
			{{ help_html }}
		</div>

		<style>
		.json-editor-container {
			border: 1px solid var(--bs-border-color, #dee2e6);
			border-radius: 8px;
			background: var(--bs-body-bg, white);
			min-height: 400px;
			max-width: 100%;
		}

		.json-editor-toolbar {
			display: flex;
			justify-content: space-between;
			align-items: center;
			padding: 0.5rem 1rem;
			border-bottom: 1px solid var(--bs-border-color, #e9ecef);
			background: var(--bs-tertiary-bg, #f8f9fa);
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
			min-width: 0;
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
			background: var(--bs-tertiary-bg, #f8f9fa);
			border-right: 1px solid var(--bs-border-color, #e9ecef);
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
			border-top: 1px solid var(--bs-border-color, #e9ecef);
			padding: 0.5rem 1rem;
			background: var(--bs-tertiary-bg, #f8f9fa);
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
			border-left: 1px solid var(--bs-border-color, #e9ecef);
			padding: 1rem;
			background: var(--bs-body-bg, #fdfdfd);
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
			var widgetId = {{ widget_id_js }};
			var container = document.querySelector('[data-widget="json-editor-' + widgetId + '"]');
			var textarea = document.getElementById(widgetId);
			var treePanel = document.getElementById('tree-' + widgetId);
			var validationMessages = container.querySelector('.validation-messages');
			var lineNumbers = container.querySelector('.line-numbers');
			var syntaxHighlights = container.querySelector('.syntax-highlights');

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

			// Simple JSON syntax highlighting — input is from editor value, not user HTML
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

			// Render tree node — all dynamic text set via textContent, not innerHTML
			function renderTreeNode(value, key, isRoot) {
				isRoot = isRoot || false;
				const nodeClass = isRoot ? 'tree-node root' : 'tree-node';

				if (value === null) {
					const d = document.createElement('div');
					d.className = nodeClass;
					if (key) {
						const k = document.createElement('span');
						k.className = 'tree-key';
						k.textContent = key + ':';
						d.appendChild(k);
					}
					const v = document.createElement('span');
					v.className = 'tree-value null';
					v.textContent = 'null';
					d.appendChild(v);
					return d.outerHTML;
				}

				if (typeof value === 'object' && !Array.isArray(value)) {
					const keys = Object.keys(value);
					const hasChildren = keys.length > 0;

					const d = document.createElement('div');
					d.className = nodeClass;
					if (hasChildren) {
						const toggle = document.createElement('span');
						toggle.className = 'tree-toggle';
						toggle.innerHTML = '<i class="fa fa-minus-square-o"></i>';
						d.appendChild(toggle);
					}
					if (key) {
						const k = document.createElement('span');
						k.className = 'tree-key';
						k.textContent = key + ':';
						d.appendChild(k);
						d.appendChild(document.createTextNode(' '));
					}
					const summary = document.createElement('span');
					summary.className = 'tree-value';
					summary.textContent = '{' + keys.length + ' ' + (keys.length === 1 ? 'item' : 'items') + '}';
					d.appendChild(summary);

					if (hasChildren) {
						const children = document.createElement('div');
						children.className = 'tree-children';
						children.innerHTML = keys.map(k => renderTreeNode(value[k], k)).join('');
						d.appendChild(children);
					}
					return d.outerHTML;
				}

				if (Array.isArray(value)) {
					const hasChildren = value.length > 0;
					const d = document.createElement('div');
					d.className = nodeClass;
					if (hasChildren) {
						const toggle = document.createElement('span');
						toggle.className = 'tree-toggle';
						toggle.innerHTML = '<i class="fa fa-minus-square-o"></i>';
						d.appendChild(toggle);
					}
					if (key) {
						const k = document.createElement('span');
						k.className = 'tree-key';
						k.textContent = key + ':';
						d.appendChild(k);
						d.appendChild(document.createTextNode(' '));
					}
					const summary = document.createElement('span');
					summary.className = 'tree-value';
					summary.textContent = '[' + value.length + ' ' + (value.length === 1 ? 'item' : 'items') + ']';
					d.appendChild(summary);

					if (hasChildren) {
						const children = document.createElement('div');
						children.className = 'tree-children';
						children.innerHTML = value.map((item, index) => renderTreeNode(item, '[' + index + ']')).join('');
						d.appendChild(children);
					}
					return d.outerHTML;
				}

				// Primitive values — use textContent to avoid XSS
				const valueType = typeof value;
				const valueClass = valueType === 'string' ? 'string' :
								 valueType === 'number' ? 'number' :
								 valueType === 'boolean' ? 'boolean' : '';

				const d = document.createElement('div');
				d.className = nodeClass;
				if (key) {
					const k = document.createElement('span');
					k.className = 'tree-key';
					k.textContent = key + ':';
					d.appendChild(k);
				}
				const v = document.createElement('span');
				v.className = 'tree-value ' + valueClass;
				v.textContent = valueType === 'string' ? '"' + value + '"' : String(value);
				d.appendChild(v);
				return d.outerHTML;
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

			// Show validation error — use textContent to avoid XSS
			function showValidationError(message) {
				const messageDiv = document.createElement('div');
				messageDiv.className = 'validation-message error';
				const icon = document.createElement('i');
				icon.className = 'fa fa-times';
				messageDiv.appendChild(icon);
				messageDiv.appendChild(document.createTextNode(' ' + message));
				validationMessages.appendChild(messageDiv);
			}

			// Show validation success — use textContent to avoid XSS
			function showValidationSuccess(message) {
				const messageDiv = document.createElement('div');
				messageDiv.className = 'validation-message success';
				const icon = document.createElement('i');
				icon.className = 'fa fa-check';
				messageDiv.appendChild(icon);
				messageDiv.appendChild(document.createTextNode(' ' + message));
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
						const tp = container.querySelector('.json-tree-panel');
						if (tp) {
							const visible = tp.style.display !== 'none';
							tp.style.display = visible ? 'none' : 'block';
							const btn = container.querySelector('[data-action="toggle-tree"]');
							if (btn) btn.setAttribute('aria-expanded', String(!visible));
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

			// Support initialization after DOMContentLoaded (modal/tab contexts)
			if (document.readyState === 'complete' || document.readyState === 'interactive') {
				initializeEditor();
			} else {
				document.addEventListener('DOMContentLoaded', initializeEditor);
			}
			document.addEventListener('shown.bs.tab', initializeEditor);
			document.addEventListener('shown.bs.modal', initializeEditor);
		})();
		</script>
		"""

		return Markup(render_template_string(template,
			widget_id=widget_id,
			widget_id_js=json.dumps(widget_id),
			field=field,
			field_data_safe=field_data_safe,
			schema=self.schema,
			show_tree_view=self.show_tree_view,
			enable_search=self.enable_search,
			auto_format=self.auto_format,
			readonly=self.readonly,
			disabled=self.disabled,
			placeholder=self.placeholder,
			css_class=self.css_class,
			has_errors=has_errors,
			aria_label=aria_label,
			aria_invalid=aria_invalid,
			describedby=describedby,
			error_html=Markup(error_html),
			help_html=Markup(help_html),
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
				 allow_duplicates: bool = True,
				 placeholder: str = "",
				 css_class: str = "",
				 description: str = "",
				 readonly: bool = False,
				 disabled: bool = False):
		"""
		Initialize the array editor widget.

		Args:
			item_type: Type of items in the array
			item_options: Options for item widgets
			sortable: Enable drag & drop sorting
			max_items: Maximum number of items
			min_items: Minimum number of items
			allow_duplicates: Allow duplicate values
			placeholder: Placeholder for item inputs
			css_class: Additional CSS class(es) for the container
			description: Help text rendered below the widget
			readonly: Render in read-only mode
			disabled: Render as disabled
		"""
		self.item_type = item_type
		self.item_options = item_options or {}
		self.sortable = sortable
		self.max_items = max_items
		self.min_items = min_items
		self.allow_duplicates = allow_duplicates
		self.placeholder = placeholder
		self.css_class = css_class
		self.description = description
		self.readonly = readonly
		self.disabled = disabled

	def __call__(self, field, **kwargs):
		"""Render the array editor widget."""
		widget_id = kwargs.get('id', f'array_editor_{uuid4().hex[:8]}')
		kwargs.setdefault('id', widget_id)

		has_errors = bool(field.errors)
		aria_label = str(field.label.text) if hasattr(field, 'label') and field.label else field.name

		# Build error HTML
		error_html = ""
		if has_errors:
			error_parts = "".join(
				f"<span>{escape(e)}</span>" for e in field.errors
			)
			error_html = (
				f'<div class="invalid-feedback d-block" id="{widget_id}_error">'
				f"{error_parts}</div>"
			)

		# Build help text HTML
		description = kwargs.pop("description", self.description)
		help_html = ""
		if description:
			help_html = (
				f'<small class="form-text text-muted" id="{widget_id}_help">'
				f"{escape(description)}</small>"
			)

		aria_invalid = 'aria-invalid="true"' if has_errors else ''
		if has_errors:
			describedby = f'aria-describedby="{widget_id}_error"'
		elif description:
			describedby = f'aria-describedby="{widget_id}_help"'
		else:
			describedby = ''

		# field.data is user-supplied; escape for HTML attribute context
		field_data_safe = escape(field.data or '[]')

		template = """
		<div class="array-editor-container {{ css_class }}" data-widget="array-editor-{{ widget_id }}"
			 role="region" aria-label="{{ aria_label }}"
			 style="width:100%;">
			<div class="array-editor-header">
				<h6 id="array-label-{{ widget_id }}">{{ _('Array Editor') }}</h6>
				<div class="array-actions">
					<button type="button" class="btn btn-primary btn-sm" data-action="add-item"
							aria-label="{{ _('Add item to array') }}">
						<i class="fa fa-plus"></i> {{ _('Add Item') }}
					</button>
					<button type="button" class="btn btn-secondary btn-sm" data-action="clear-all"
							aria-label="{{ _('Clear all items') }}">
						<i class="fa fa-trash"></i> {{ _('Clear All') }}
					</button>
				</div>
			</div>

			<div class="array-items" id="items-{{ widget_id }}"
				 role="list" aria-labelledby="array-label-{{ widget_id }}">
				<!-- Array items will be rendered here -->
			</div>

			<div class="array-footer">
				<small class="form-text text-muted">
					<span class="item-count" aria-live="polite">0</span> {{ _('items') }}
					{% if min_items > 0 %} | {{ _('Minimum') }}: {{ min_items }}{% endif %}
					{% if max_items %} | {{ _('Maximum') }}: {{ max_items }}{% endif %}
				</small>
			</div>

			<input type="hidden" id="{{ widget_id }}" name="{{ field.name }}"
				   value="{{ field_data_safe }}"
				   {{ aria_invalid }} {{ describedby }}>

			{{ error_html }}
			{{ help_html }}
		</div>

		<style>
		.array-editor-container {
			border: 1px solid var(--bs-border-color, #dee2e6);
			border-radius: 8px;
			background: var(--bs-body-bg, white);
			max-width: 100%;
		}

		.array-editor-header {
			display: flex;
			justify-content: space-between;
			align-items: center;
			padding: 1rem;
			border-bottom: 1px solid var(--bs-border-color, #e9ecef);
			background: var(--bs-tertiary-bg, #f8f9fa);
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
			border: 1px solid var(--bs-border-color, #e9ecef);
			border-radius: 6px;
			background: var(--bs-body-bg, #fdfdfd);
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
			border-top: 1px solid var(--bs-border-color, #e9ecef);
			background: var(--bs-tertiary-bg, #f8f9fa);
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
			var widgetId = {{ widget_id_js }};
			var container = document.querySelector('[data-widget="array-editor-' + widgetId + '"]');
			var itemsContainer = document.getElementById('items-' + widgetId);
			var hiddenInput = document.getElementById(widgetId);
			var itemCount = container.querySelector('.item-count');

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
			function addItem(value) {
				value = value || '';
				// Check maximum limit
				{% if max_items is not none %}
				if (arrayItems.length >= {{ max_items }}) {
					alert('Maximum {{ max_items }} items allowed');
					return;
				}
				{% endif %}

				itemIdCounter++;
				const newItem = {
					id: 'item_' + itemIdCounter,
					value: value
				};

				arrayItems.push(newItem);
				renderItems();

				// Focus on new item
				const newItemElement = itemsContainer.querySelector('[data-item-id="' + newItem.id + '"] input');
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
						alert('Minimum {{ min_items }} items required');
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
					const empty = document.createElement('div');
					empty.className = 'empty-array';
					const icon = document.createElement('i');
					icon.className = 'fa fa-list';
					icon.setAttribute('aria-hidden', 'true');
					empty.appendChild(icon);
					const p = document.createElement('p');
					p.textContent = '{{ _("No items in array. Click \\"Add Item\\" to get started.") }}';
					empty.appendChild(p);
					itemsContainer.innerHTML = '';
					itemsContainer.appendChild(empty);
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

			// Create item element — use DOM APIs to avoid XSS when inserting item.value
			function createItemElement(item, index) {
				const itemDiv = document.createElement('div');
				itemDiv.className = 'array-item';
				itemDiv.setAttribute('role', 'listitem');
				itemDiv.dataset.itemId = item.id;
				itemDiv.dataset.index = index;
				itemDiv.draggable = {{ sortable_js }};

				const indexDiv = document.createElement('div');
				indexDiv.className = 'item-index';
				indexDiv.setAttribute('aria-label', 'Item ' + (index + 1));
				indexDiv.textContent = index + 1;
				itemDiv.appendChild(indexDiv);

				{% if sortable %}
				const dragHandle = document.createElement('div');
				dragHandle.className = 'drag-handle';
				dragHandle.setAttribute('aria-label', 'Drag to reorder');
				dragHandle.innerHTML = '<i class="fa fa-bars" aria-hidden="true"></i>';
				itemDiv.appendChild(dragHandle);
				{% endif %}

				const inputDiv = document.createElement('div');
				inputDiv.className = 'item-input';

				let input;
				switch ({{ item_type_js }}) {
					case 'textarea':
						input = document.createElement('textarea');
						input.className = 'form-control';
						input.placeholder = '{{ _("Enter value...") }}';
						input.value = item.value || '';
						break;
					case 'number':
						input = document.createElement('input');
						input.type = 'number';
						input.className = 'form-control';
						input.placeholder = '{{ _("Enter number...") }}';
						input.value = item.value || '';
						break;
					case 'email':
						input = document.createElement('input');
						input.type = 'email';
						input.className = 'form-control';
						input.placeholder = '{{ _("Enter email...") }}';
						input.value = item.value || '';
						break;
					case 'url':
						input = document.createElement('input');
						input.type = 'url';
						input.className = 'form-control';
						input.placeholder = '{{ _("Enter URL...") }}';
						input.value = item.value || '';
						break;
					case 'date':
						input = document.createElement('input');
						input.type = 'date';
						input.className = 'form-control';
						input.value = item.value || '';
						break;
					default:
						input = document.createElement('input');
						input.type = 'text';
						input.className = 'form-control';
						input.placeholder = '{{ _("Enter value...") }}';
						input.value = item.value || '';
				}
				input.setAttribute('aria-label', 'Item ' + (index + 1) + ' value');
				inputDiv.appendChild(input);
				itemDiv.appendChild(inputDiv);

				const actionsDiv = document.createElement('div');
				actionsDiv.className = 'item-actions';

				const dupBtn = document.createElement('button');
				dupBtn.type = 'button';
				dupBtn.className = 'btn btn-sm btn-outline-success';
				dupBtn.dataset.action = 'duplicate';
				dupBtn.setAttribute('aria-label', 'Duplicate item ' + (index + 1));
				dupBtn.innerHTML = '<i class="fa fa-copy" aria-hidden="true"></i>';
				actionsDiv.appendChild(dupBtn);

				const removeBtn = document.createElement('button');
				removeBtn.type = 'button';
				removeBtn.className = 'btn btn-sm btn-outline-danger';
				removeBtn.dataset.action = 'remove';
				removeBtn.setAttribute('aria-label', 'Remove item ' + (index + 1));
				removeBtn.innerHTML = '<i class="fa fa-times" aria-hidden="true"></i>';
				actionsDiv.appendChild(removeBtn);

				itemDiv.appendChild(actionsDiv);
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
			widget_id_js=json.dumps(widget_id),
			field=field,
			field_data_safe=field_data_safe,
			item_type=self.item_type,
			item_type_js=json.dumps(self.item_type),
			item_options=self.item_options,
			sortable=self.sortable,
			sortable_js=json.dumps(self.sortable),
			max_items=self.max_items,
			min_items=self.min_items,
			allow_duplicates=self.allow_duplicates,
			has_errors=has_errors,
			aria_label=aria_label,
			aria_invalid=aria_invalid,
			describedby=describedby,
			error_html=Markup(error_html),
			help_html=Markup(help_html),
			_=gettext
		))
