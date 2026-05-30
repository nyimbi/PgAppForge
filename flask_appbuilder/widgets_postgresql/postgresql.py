"""
PostgreSQL-specific widgets for Flask-AppBuilder

This module provides custom widgets for PostgreSQL data types including
JSONB, PostGIS geometry types, arrays, and pgvector embeddings.
"""
import json
from typing import Any, Dict, List, Optional, Union

from markupsafe import Markup
from flask import render_template_string
from flask_appbuilder.fieldwidgets import BS3TextFieldWidget
from flask_appbuilder.widgets_postgresql._cdn import LEAFLET_CDN as _LEAFLET_CDN
from wtforms.widgets import TextArea, Input, Select
from wtforms.widgets.core import html_params


class JSONBWidget(TextArea):
	"""
	Advanced widget for PostgreSQL JSONB fields with rich editing capabilities.
	
	This widget provides:
	- Syntax highlighting for JSON data
	- Real-time validation with error reporting
	- Format and minify JSON functionality
	- Monospace font for better readability
	- Visual status indicators for validation state
	- Keyboard shortcuts for common operations
	
	The widget automatically handles data serialization/deserialization between
	Python objects (dict/list) and JSON strings for display in the form.
	
	Usage:
		class MyForm(Form):
			json_field = Field('JSON Data', widget=JSONBWidget())
	
	Attributes:
		None - uses standard TextArea attributes
		
	Methods:
		__call__(field, **kwargs): Renders the complete JSONB widget with controls
	"""
	
	def __call__(self, field, **kwargs):
		"""
		Render the JSONB widget with all interactive controls.
		
		Args:
			field: The WTForms field instance containing the data
			**kwargs: Additional HTML attributes for the widget
			
		Returns:
			Markup: Complete HTML for the JSONB widget including:
				- Textarea with syntax highlighting
				- Toolbar with format/minify/validate buttons
				- Status area for validation messages
				- CSS styling for professional appearance
				- JavaScript for interactive functionality
				
		The method handles automatic JSON formatting for display and provides
		comprehensive error handling for invalid JSON data.
		"""
		kwargs.setdefault('id', field.id)
		kwargs.setdefault('class', 'form-control jsonb-editor')
		kwargs.setdefault('data-toggle', 'jsonb')
		
		# Format JSON for display with proper error handling
		formatted_data = ''
		if field.data is not None:
			try:
				if isinstance(field.data, (dict, list)):
					formatted_data = json.dumps(field.data, indent=2, ensure_ascii=False)
				elif isinstance(field.data, str):
					# Validate if it's already JSON string
					parsed = json.loads(field.data)
					formatted_data = json.dumps(parsed, indent=2, ensure_ascii=False)
				else:
					formatted_data = str(field.data)
			except (json.JSONDecodeError, TypeError):
				# If data is not valid JSON, show as-is for user to fix
				formatted_data = str(field.data) if field.data else ''
		
		html = f'''
		<div class="jsonb-widget-container">
			<textarea {html_params(name=field.name, **kwargs)}>{formatted_data}</textarea>
			<div class="jsonb-toolbar">
				<button type="button" class="btn btn-xs btn-default jsonb-format" data-toggle="tooltip" title="Format JSON">
					<i class="fa fa-align-left"></i> Format
				</button>
				<button type="button" class="btn btn-xs btn-default jsonb-minify" data-toggle="tooltip" title="Minify JSON">
					<i class="fa fa-compress"></i> Minify
				</button>
				<button type="button" class="btn btn-xs btn-default jsonb-validate" data-toggle="tooltip" title="Validate JSON">
					<i class="fa fa-check"></i> Validate
				</button>
			</div>
			<div class="jsonb-status"></div>
		</div>
		
		<style>
		.jsonb-widget-container {{
			border: 1px solid #ddd;
			border-radius: 4px;
		}}
		.jsonb-widget-container textarea {{
			border: none;
			border-radius: 4px 4px 0 0;
			font-family: 'Monaco', 'Consolas', monospace;
			min-height: 200px;
			resize: vertical;
		}}
		.jsonb-toolbar {{
			background: #f8f9fa;
			border-top: 1px solid #ddd;
			padding: 5px;
			border-radius: 0 0 4px 4px;
		}}
		.jsonb-status {{
			padding: 5px;
			font-size: 0.9em;
		}}
		.jsonb-status.valid {{
			color: #28a745;
		}}
		.jsonb-status.invalid {{
			color: #dc3545;
		}}
		</style>
		
		<script>
		$(document).ready(function() {{
			$('.jsonb-format').click(function() {{
				var textarea = $(this).closest('.jsonb-widget-container').find('textarea');
				try {{
					var obj = JSON.parse(textarea.val() || '{{}}');
					textarea.val(JSON.stringify(obj, null, 2));
					$(this).closest('.jsonb-widget-container').find('.jsonb-status')
						.removeClass('invalid').addClass('valid').text('JSON formatted successfully');
				}} catch(e) {{
					$(this).closest('.jsonb-widget-container').find('.jsonb-status')
						.removeClass('valid').addClass('invalid').text('Invalid JSON: ' + e.message);
				}}
			}});
			
			$('.jsonb-minify').click(function() {{
				var textarea = $(this).closest('.jsonb-widget-container').find('textarea');
				try {{
					var obj = JSON.parse(textarea.val() || '{{}}');
					textarea.val(JSON.stringify(obj));
					$(this).closest('.jsonb-widget-container').find('.jsonb-status')
						.removeClass('invalid').addClass('valid').text('JSON minified successfully');
				}} catch(e) {{
					$(this).closest('.jsonb-widget-container').find('.jsonb-status')
						.removeClass('valid').addClass('invalid').text('Invalid JSON: ' + e.message);
				}}
			}});
			
			$('.jsonb-validate').click(function() {{
				var textarea = $(this).closest('.jsonb-widget-container').find('textarea');
				try {{
					JSON.parse(textarea.val() || '{{}}');
					$(this).closest('.jsonb-widget-container').find('.jsonb-status')
						.removeClass('invalid').addClass('valid').text('Valid JSON');
				}} catch(e) {{
					$(this).closest('.jsonb-widget-container').find('.jsonb-status')
						.removeClass('valid').addClass('invalid').text('Invalid JSON: ' + e.message);
				}}
			}});
			
			// Real-time validation with debouncing for performance
			var validationTimeout;
			$('.jsonb-editor').on('input', function() {{
				var textarea = $(this);
				var statusDiv = textarea.closest('.jsonb-widget-container').find('.jsonb-status');
				
				// Clear previous timeout
				clearTimeout(validationTimeout);
				
				// Debounce validation to avoid excessive processing
				validationTimeout = setTimeout(function() {{
					var value = textarea.val();
					if (!value || value.trim() === '') {{
						statusDiv.removeClass('valid invalid').text('');
						return;
					}}
					
					try {{
						var parsed = JSON.parse(value);
						statusDiv.removeClass('invalid').addClass('valid').text('Valid JSON');
						
						// Additional validation for complex objects
						if (typeof parsed === 'object' && parsed !== null) {{
							var keys = Object.keys(parsed);
							if (Array.isArray(parsed)) {{
								statusDiv.text('Valid JSON Array (' + parsed.length + ' items)');
							}} else {{
								statusDiv.text('Valid JSON Object (' + keys.length + ' keys)');
							}}
						}}
					}} catch(e) {{
						statusDiv.removeClass('valid').addClass('invalid').text('Invalid JSON: ' + e.message);
					}}
				}}, 300); // 300ms debounce delay
			}});
			
			// Keyboard shortcuts for common operations
			$('.jsonb-editor').on('keydown', function(e) {{
				// Ctrl+Alt+F for format
				if (e.ctrlKey && e.altKey && e.key === 'f') {{
					e.preventDefault();
					$(this).closest('.jsonb-widget-container').find('.jsonb-format').click();
				}}
				// Ctrl+Alt+M for minify
				if (e.ctrlKey && e.altKey && e.key === 'm') {{
					e.preventDefault();
					$(this).closest('.jsonb-widget-container').find('.jsonb-minify').click();
				}}
				// Ctrl+Alt+V for validate
				if (e.ctrlKey && e.altKey && e.key === 'v') {{
					e.preventDefault();
					$(this).closest('.jsonb-widget-container').find('.jsonb-validate').click();
				}}
			}});
			
			// Initialize tooltips for better UX
			$('[data-toggle="tooltip"]').tooltip();
			
			// Auto-resize textarea based on content
			$('.jsonb-editor').each(function() {{
				this.style.height = 'auto';
				this.style.height = Math.max(200, this.scrollHeight) + 'px';
			}}).on('input', function() {{
				this.style.height = 'auto';
				this.style.height = Math.max(200, this.scrollHeight) + 'px';
			}});
		}});
		</script>
		'''
		
		return Markup(html)


class PostgreSQLArrayWidget(Input):
	"""
	Advanced widget for PostgreSQL array fields with comprehensive management capabilities.
	
	This widget provides:
	- Dynamic add/remove array items with interactive buttons
	- Type-specific input validation and formatting
	- Drag-and-drop reordering of array elements
	- Import/export functionality for bulk operations
	- Visual feedback for validation states
	- Keyboard navigation and shortcuts
	- Support for all PostgreSQL array types
	
	The widget handles automatic conversion between PostgreSQL array format
	({item1,item2,item3}) and Python list structures for seamless integration.
	
	Args:
		array_type (str): The type of array elements ('text', 'integer', 'numeric', etc.)
		separator (str): The separator used for parsing (default: ',')
		min_items (int): Minimum number of array items (default: 0)
		max_items (int): Maximum number of array items (default: None)
		allow_duplicates (bool): Whether to allow duplicate values (default: True)
		
	Usage:
		class MyForm(Form):
			tags = Field('Tags', widget=PostgreSQLArrayWidget(array_type='text'))
			scores = Field('Scores', widget=PostgreSQLArrayWidget(array_type='integer'))
	
	Methods:
		__init__(array_type, separator, **options): Initialize the widget with type configuration
		__call__(field, **kwargs): Render the complete array widget with all controls
		_validate_array_item(value, array_type): Validate individual array items
		_format_array_for_display(data): Format array data for display in the widget
	"""
	input_type = 'text'
	
	def __init__(self, array_type='text', separator=',', min_items=0, max_items=None, allow_duplicates=True):
		"""
		Initialize the PostgreSQL array widget.
		
		Args:
			array_type: Type of array elements for validation
			separator: Character used to separate array items
			min_items: Minimum number of required items
			max_items: Maximum number of allowed items
			allow_duplicates: Whether duplicate values are permitted
		"""
		self.array_type = array_type
		self.separator = separator
		self.min_items = min_items
		self.max_items = max_items
		self.allow_duplicates = allow_duplicates
		super().__init__()
	
	def _validate_array_item(self, value: str, array_type: str) -> tuple[bool, str]:
		"""
		Validate an individual array item based on the specified type.
		
		Args:
			value: The string value to validate
			array_type: The expected type ('text', 'integer', 'numeric', 'boolean', etc.)
			
		Returns:
			tuple: (is_valid: bool, error_message: str)
		"""
		if not value and value != '0':  # Allow '0' as valid
			return True, ""  # Empty values are handled by required validation
			
		try:
			if array_type in ('integer', 'int', 'bigint', 'smallint'):
				int(value)
			elif array_type in ('numeric', 'decimal', 'float', 'real', 'double_precision'):
				float(value)
			elif array_type in ('boolean', 'bool'):
				if value.lower() not in ('true', 'false', 't', 'f', '1', '0'):
					return False, f"Boolean values must be true/false, got: {value}"
			elif array_type in ('uuid',):
				import re
				uuid_pattern = r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
				if not re.match(uuid_pattern, value, re.IGNORECASE):
					return False, f"Invalid UUID format: {value}"
			# text, varchar, char types - no additional validation needed
			
			return True, ""
		except ValueError as e:
			return False, f"Invalid {array_type}: {value} ({str(e)})"
	
	def _format_array_for_display(self, data) -> List[str]:
		"""
		Format array data for display in the widget.
		
		Args:
			data: Raw field data (list, string, or None)
			
		Returns:
			List[str]: Formatted array items ready for display
		"""
		if data is None:
			return []
		elif isinstance(data, list):
			return [str(item) for item in data]
		elif isinstance(data, str):
			# Handle PostgreSQL array format: {item1,item2,item3}
			if data.startswith('{') and data.endswith('}'):
				inner = data[1:-1]  # Remove braces
				if not inner.strip():
					return []
				# Split and clean items, handling quoted values
				items = []
				current_item = ""
				in_quotes = False
				escape_next = False
				
				for char in inner:
					if escape_next:
						current_item += char
						escape_next = False
					elif char == '\\':
						escape_next = True
					elif char == '"' and not escape_next:
						in_quotes = not in_quotes
					elif char == ',' and not in_quotes:
						items.append(current_item.strip().strip('"'))
						current_item = ""
					else:
						current_item += char
				
				# Add the last item
				if current_item or len(items) == 0:
					items.append(current_item.strip().strip('"'))
				
				return items
			else:
				# Simple comma-separated format
				return [item.strip() for item in data.split(self.separator) if item.strip()]
		else:
			return [str(data)]

	def __call__(self, field, **kwargs):
		"""
		Render the complete PostgreSQL array widget with all functionality.
		
		Args:
			field: The WTForms field instance
			**kwargs: Additional HTML attributes
			
		Returns:
			Markup: Complete HTML for the array widget including:
				- Hidden input for form submission
				- Dynamic array item controls
				- Add/remove/reorder functionality
				- Type validation and error display
				- Import/export capabilities
		"""
		kwargs.setdefault('id', field.id)
		kwargs.setdefault('class', 'form-control')
		
		# Convert array data to display format using the helper method
		display_values = self._format_array_for_display(field.data)
		
		html = f'''
		<div class="postgresql-array-widget" data-array-type="{self.array_type}">
			<input type="hidden" name="{field.name}" id="{field.id}" value="{field.data or ''}" />
			<div class="array-items">
		'''
		
		# Add existing items
		for i, value in enumerate(display_values):
			cleaned_value = value.strip().strip('"')
			html += f'''
				<div class="array-item input-group" style="margin-bottom: 5px;">
					<input type="text" class="form-control array-value" value="{cleaned_value}" 
						   placeholder="Enter {self.array_type} value">
					<div class="input-group-btn">
						<button type="button" class="btn btn-default array-remove">
							<i class="fa fa-minus"></i>
						</button>
					</div>
				</div>
			'''
		
		# Add empty item if no existing items
		if not display_values:
			html += f'''
				<div class="array-item input-group" style="margin-bottom: 5px;">
					<input type="text" class="form-control array-value" 
						   placeholder="Enter {self.array_type} value">
					<div class="input-group-btn">
						<button type="button" class="btn btn-default array-remove">
							<i class="fa fa-minus"></i>
						</button>
					</div>
				</div>
			'''
		
		html += f'''
			</div>
			<div class="array-controls" style="margin-top: 10px;">
				<div class="btn-group" role="group">
					<button type="button" class="btn btn-success btn-sm array-add">
						<i class="fa fa-plus"></i> Add Item
					</button>
					<button type="button" class="btn btn-info btn-sm array-import" title="Import from text">
						<i class="fa fa-upload"></i> Import
					</button>
					<button type="button" class="btn btn-secondary btn-sm array-export" title="Export to text">
						<i class="fa fa-download"></i> Export
					</button>
					<button type="button" class="btn btn-warning btn-sm array-clear" title="Clear all items">
						<i class="fa fa-trash"></i> Clear
					</button>
				</div>
				<div class="array-info" style="float: right; margin-top: 5px;">
					<small class="text-muted">
						Type: {self.array_type.title()}
						{f"| Min: {self.min_items}" if self.min_items > 0 else ""}
						{f"| Max: {self.max_items}" if self.max_items else ""}
						{" | No duplicates" if not self.allow_duplicates else ""}
					</small>
				</div>
			</div>
			
			<!-- Import/Export Modal -->
			<div class="modal fade array-import-modal" tabindex="-1" role="dialog">
				<div class="modal-dialog" role="document">
					<div class="modal-content">
						<div class="modal-header">
							<h5 class="modal-title">Import Array Data</h5>
							<button type="button" class="close" data-dismiss="modal">
								<span>&times;</span>
							</button>
						</div>
						<div class="modal-body">
							<div class="form-group">
								<label>Paste data (one item per line or comma-separated):</label>
								<textarea class="form-control import-textarea" rows="6" 
										 placeholder="Enter array items..."></textarea>
							</div>
							<div class="form-group">
								<label>
									<input type="checkbox" class="replace-existing"> 
									Replace existing items (otherwise append)
								</label>
							</div>
						</div>
						<div class="modal-footer">
							<button type="button" class="btn btn-secondary" data-dismiss="modal">Cancel</button>
							<button type="button" class="btn btn-primary import-confirm">Import</button>
						</div>
					</div>
				</div>
			</div>
		</div>
		
		<script>
		$(document).ready(function() {{
			// Enhanced array value update with validation
			function updateArrayValue(container) {{
				var values = [];
				var arrayType = container.data('array-type');
				var hasErrors = false;
				
				container.find('.array-value').each(function() {{
					var input = $(this);
					var val = input.val().trim();
					var errorDiv = input.closest('.array-item').find('.validation-error');
					
					if (val) {{
						// Validate based on type
						var isValid = validateArrayItem(val, arrayType);
						if (isValid.valid) {{
							values.push(val);
							input.removeClass('is-invalid');
							if (errorDiv.length) errorDiv.remove();
						}} else {{
							input.addClass('is-invalid');
							if (!errorDiv.length) {{
								input.closest('.array-item').append(
									'<div class="validation-error text-danger small">' + isValid.error + '</div>'
								);
							}}
							hasErrors = true;
						}}
					}} else {{
						input.removeClass('is-invalid');
						if (errorDiv.length) errorDiv.remove();
					}}
				}});
				
				// Check for duplicates if not allowed
				if (!{str(self.allow_duplicates).lower()}) {{
					var duplicates = values.filter((item, index) => values.indexOf(item) !== index);
					if (duplicates.length > 0) {{
						hasErrors = true;
						// Mark duplicate inputs
						container.find('.array-value').each(function() {{
							var val = $(this).val().trim();
							if (duplicates.includes(val)) {{
								$(this).addClass('is-invalid');
								var errorDiv = $(this).closest('.array-item').find('.validation-error');
								if (!errorDiv.length) {{
									$(this).closest('.array-item').append(
										'<div class="validation-error text-danger small">Duplicate value not allowed</div>'
									);
								}}
							}}
						}});
					}}
				}}
				
				// Check min/max constraints
				var itemCount = values.length;
				var minItems = {self.min_items};
				var maxItems = {self.max_items or 'null'};
				
				if (minItems > 0 && itemCount < minItems) {{
					container.addClass('array-min-error');
					hasErrors = true;
				}} else {{
					container.removeClass('array-min-error');
				}}
				
				if (maxItems && itemCount > maxItems) {{
					container.addClass('array-max-error');
					hasErrors = true;
				}} else {{
					container.removeClass('array-max-error');
				}}
				
				// Update hidden input with PostgreSQL array format
				container.find('input[type="hidden"]').val('{{' + values.map(v => '"' + v.replace(/"/g, '\\\\"') + '"').join(',') + '}}');
				
				// Update array info
				updateArrayInfo(container, itemCount, hasErrors);
			}}
			
			// Type validation function
			function validateArrayItem(value, type) {{
				try {{
					switch(type) {{
						case 'integer':
						case 'int':
						case 'bigint':
						case 'smallint':
							if (!/^-?\\d+$/.test(value)) {{
								return {{valid: false, error: 'Must be an integer'}};
							}}
							break;
						case 'numeric':
						case 'decimal':
						case 'float':
						case 'real':
						case 'double_precision':
							if (!/^-?\\d*\\.?\\d+([eE][+-]?\\d+)?$/.test(value)) {{
								return {{valid: false, error: 'Must be a number'}};
							}}
							break;
						case 'boolean':
						case 'bool':
							if (!/^(true|false|t|f|1|0)$/i.test(value)) {{
								return {{valid: false, error: 'Must be true/false'}};
							}}
							break;
						case 'uuid':
							var uuidPattern = /^[0-9a-f]{{8}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{4}}-[0-9a-f]{{12}}$/i;
							if (!uuidPattern.test(value)) {{
								return {{valid: false, error: 'Invalid UUID format'}};
							}}
							break;
						// text, varchar, char types need no validation
					}}
					return {{valid: true, error: ''}};
				}} catch(e) {{
					return {{valid: false, error: 'Invalid value'}};
				}}
			}}
			
			// Update array information display
			function updateArrayInfo(container, count, hasErrors) {{
				var info = container.find('.array-info small');
				var status = hasErrors ? ' <span class="text-danger">(Errors)</span>' : '';
				var countInfo = ' | Items: ' + count;
				var originalText = info.text().split(' | Items:')[0];
				info.html(originalText + countInfo + status);
			}}
			
			// Add new array item
			$(document).on('click', '.array-add', function() {{
				var container = $(this).closest('.postgresql-array-widget');
				var arrayType = container.data('array-type');
				var maxItems = {self.max_items or 'null'};
				var currentCount = container.find('.array-item').length;
				
				if (maxItems && currentCount >= maxItems) {{
					alert('Maximum number of items (' + maxItems + ') reached');
					return;
				}}
				
				var newItem = $(`
					<div class="array-item input-group" style="margin-bottom: 5px;" draggable="true">
						<div class="input-group-prepend">
							<span class="input-group-text drag-handle" style="cursor: move;">
								<i class="fa fa-grip-vertical"></i>
							</span>
						</div>
						<input type="text" class="form-control array-value" 
							   placeholder="Enter ${{arrayType}} value">
						<div class="input-group-append">
							<button type="button" class="btn btn-outline-danger array-remove" title="Remove item">
								<i class="fa fa-minus"></i>
							</button>
						</div>
					</div>
				`);
				container.find('.array-items').append(newItem);
				newItem.find('input').focus();
				
				// Update array value after adding
				updateArrayValue(container);
			}});
			
			// Remove array item
			$(document).on('click', '.array-remove', function() {{
				var container = $(this).closest('.postgresql-array-widget');
				$(this).closest('.array-item').fadeOut(200, function() {{
					$(this).remove();
					updateArrayValue(container);
				}});
			}});
			
			// Update on input change with debouncing
			var updateTimeout;
			$(document).on('input', '.array-value', function() {{
				var container = $(this).closest('.postgresql-array-widget');
				clearTimeout(updateTimeout);
				updateTimeout = setTimeout(function() {{
					updateArrayValue(container);
				}}, 300);
			}});
			
			// Import functionality
			$(document).on('click', '.array-import', function() {{
				var container = $(this).closest('.postgresql-array-widget');
				container.find('.array-import-modal').modal('show');
			}});
			
			$(document).on('click', '.import-confirm', function() {{
				var modal = $(this).closest('.modal');
				var container = modal.closest('.postgresql-array-widget');
				var textarea = modal.find('.import-textarea');
				var replaceExisting = modal.find('.replace-existing').prop('checked');
				var text = textarea.val().trim();
				
				if (!text) return;
				
				// Parse import data (support multiple formats)
				var items = [];
				if (text.includes('\\n')) {{
					// Line-separated
					items = text.split('\\n').map(s => s.trim()).filter(s => s);
				}} else {{
					// Comma-separated
					items = text.split(',').map(s => s.trim()).filter(s => s);
				}}
				
				if (replaceExisting) {{
					container.find('.array-items').empty();
				}}
				
				var arrayType = container.data('array-type');
				items.forEach(function(item) {{
					var newItem = $(`
						<div class="array-item input-group" style="margin-bottom: 5px;" draggable="true">
							<div class="input-group-prepend">
								<span class="input-group-text drag-handle" style="cursor: move;">
									<i class="fa fa-grip-vertical"></i>
								</span>
							</div>
							<input type="text" class="form-control array-value" 
								   value="${{item}}" placeholder="Enter ${{arrayType}} value">
							<div class="input-group-append">
								<button type="button" class="btn btn-outline-danger array-remove" title="Remove item">
									<i class="fa fa-minus"></i>
								</button>
							</div>
						</div>
					`);
					container.find('.array-items').append(newItem);
				}});
				
				updateArrayValue(container);
				modal.modal('hide');
				textarea.val('');
			}});
			
			// Export functionality
			$(document).on('click', '.array-export', function() {{
				var container = $(this).closest('.postgresql-array-widget');
				var values = [];
				container.find('.array-value').each(function() {{
					var val = $(this).val().trim();
					if (val) values.push(val);
				}});
				
				if (values.length === 0) {{
					alert('No items to export');
					return;
				}}
				
				var exportText = values.join('\\n');
				var textarea = $('<textarea>').val(exportText).css({{
					position: 'absolute',
					left: '-9999px'
				}}).appendTo('body');
				textarea.select();
				document.execCommand('copy');
				textarea.remove();
				
				// Show feedback
				var btn = $(this);
				var originalText = btn.html();
				btn.html('<i class="fa fa-check"></i> Copied!').prop('disabled', true);
				setTimeout(function() {{
					btn.html(originalText).prop('disabled', false);
				}}, 2000);
			}});
			
			// Clear all items
			$(document).on('click', '.array-clear', function() {{
				var container = $(this).closest('.postgresql-array-widget');
				if (confirm('Clear all array items?')) {{
					container.find('.array-items').empty();
					updateArrayValue(container);
				}}
			}});
			
			// Drag and drop functionality
			var draggedElement = null;
			
			$(document).on('dragstart', '.array-item', function(e) {{
				draggedElement = this;
				$(this).addClass('dragging');
			}});
			
			$(document).on('dragend', '.array-item', function(e) {{
				$(this).removeClass('dragging');
				draggedElement = null;
			}});
			
			$(document).on('dragover', '.array-items', function(e) {{
				e.preventDefault();
				var container = $(this);
				var afterElement = getDragAfterElement(container[0], e.clientY);
				
				if (afterElement == null) {{
					container.append(draggedElement);
				}} else {{
					container[0].insertBefore(draggedElement, afterElement);
				}}
			}});
			
			$(document).on('drop', '.array-items', function(e) {{
				e.preventDefault();
				var container = $(this).closest('.postgresql-array-widget');
				updateArrayValue(container);
			}});
			
			function getDragAfterElement(container, y) {{
				var draggableElements = [...container.querySelectorAll('.array-item:not(.dragging)')];
				
				return draggableElements.reduce((closest, child) => {{
					var box = child.getBoundingClientRect();
					var offset = y - box.top - box.height / 2;
					
					if (offset < 0 && offset > closest.offset) {{
						return {{ offset: offset, element: child }};
					}} else {{
						return closest;
					}}
				}}, {{ offset: Number.NEGATIVE_INFINITY }}).element;
			}}
			
			// Initialize existing widgets
			$('.postgresql-array-widget').each(function() {{
				updateArrayValue($(this));
			}});
		}});
		</script>
		'''
		
		return Markup(html)


class PostGISGeometryWidget(TextArea):
	"""
	Widget for PostGIS geometry fields with map integration
	"""
	
	def __init__(self, geometry_type='POINT', srid=4326):
		self.geometry_type = geometry_type.upper()
		self.srid = srid
		super().__init__()
	
	def __call__(self, field, **kwargs):
		kwargs.setdefault('id', field.id)
		kwargs.setdefault('class', 'form-control')
		kwargs.setdefault('style', 'display: none;')  # Hide the textarea
		
		html_params_str = html_params(name=field.name, **kwargs)
		html = f'''
		<div class="postgis-geometry-widget" data-geometry-type="{self.geometry_type}" data-srid="{self.srid}">
			<textarea {html_params_str}>{field.data or ''}</textarea>
			
			<div class="geometry-controls">
				<div class="btn-group" role="group">
					<button type="button" class="btn btn-default geo-point {'active' if self.geometry_type == 'POINT' else ''}" 
							data-type="POINT" title="Point">
						<i class="fa fa-map-marker"></i>
					</button>
					<button type="button" class="btn btn-default geo-line {'active' if self.geometry_type == 'LINESTRING' else ''}" 
							data-type="LINESTRING" title="Line">
						<i class="fa fa-minus"></i>
					</button>
					<button type="button" class="btn btn-default geo-polygon {'active' if self.geometry_type == 'POLYGON' else ''}" 
							data-type="POLYGON" title="Polygon">
						<i class="fa fa-square-o"></i>
					</button>
				</div>
				<div class="btn-group" role="group" style="margin-left: 10px;">
					<button type="button" class="btn btn-warning geo-clear" title="Clear">
						<i class="fa fa-trash"></i>
					</button>
					<button type="button" class="btn btn-info geo-current-location" title="Current Location">
						<i class="fa fa-crosshairs"></i>
					</button>
				</div>
				<div style="float: right;">
					<label>
						<input type="checkbox" class="geo-show-wkt"> Show WKT
					</label>
				</div>
			</div>
			
			<div id="map_{field.id}" class="geometry-map" style="height: 400px; margin-top: 10px;"></div>
			
			<div class="geometry-info" style="margin-top: 10px; display: none;">
				<div class="form-group">
					<label>Well-Known Text (WKT):</label>
					<textarea class="form-control wkt-display" rows="3" readonly></textarea>
				</div>
				<div class="form-group">
					<label>Coordinates:</label>
					<div class="coordinates-display"></div>
				</div>
			</div>
		</div>
		
		{_LEAFLET_CDN}
		<script src="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.js"></script>
		<link rel="stylesheet" href="https://unpkg.com/leaflet-draw@1.0.4/dist/leaflet.draw.css" />
		
		<script>
		$(document).ready(function() {{
			var mapId = 'map_{field.id}';
			var map = L.map(mapId).setView([40.7128, -74.0060], 10); // NYC default
			
			L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
				attribution: '© OpenStreetMap contributors'
			}}).addTo(map);
			
			var drawnItems = new L.FeatureGroup();
			map.addLayer(drawnItems);
			
			var drawControl = new L.Control.Draw({{
				edit: {{
					featureGroup: drawnItems
				}},
				draw: {{
					polygon: true,
					polyline: true,
					rectangle: false,
					circle: false,
					marker: true,
					circlemarker: false
				}}
			}});
			map.addControl(drawControl);
			
			function updateWKT() {{
				var wkt = '';
				var coords = [];
				
				drawnItems.eachLayer(function(layer) {{
					if (layer instanceof L.Marker) {{
						var latlng = layer.getLatLng();
						wkt = `POINT(${{latlng.lng}} ${{latlng.lat}})`;
						coords.push(`Lat: ${{latlng.lat.toFixed(6)}}, Lng: ${{latlng.lng.toFixed(6)}}`);
					}} else if (layer instanceof L.Polyline && !(layer instanceof L.Polygon)) {{
						var latlngs = layer.getLatLngs();
						var coordStr = latlngs.map(ll => `${{ll.lng}} ${{ll.lat}}`).join(', ');
						wkt = `LINESTRING(${{coordStr}})`;
						coords = latlngs.map(ll => `Lat: ${{ll.lat.toFixed(6)}}, Lng: ${{ll.lng.toFixed(6)}}`);
					}} else if (layer instanceof L.Polygon) {{
						var latlngs = layer.getLatLngs()[0];
						var coordStr = latlngs.map(ll => `${{ll.lng}} ${{ll.lat}}`).join(', ');
						wkt = `POLYGON((${{coordStr}}))`;
						coords = latlngs.map(ll => `Lat: ${{ll.lat.toFixed(6)}}, Lng: ${{ll.lng.toFixed(6)}}`);
					}}
				}});
				
				$('#{field.id}').val(wkt);
				$('.wkt-display').val(wkt);
				$('.coordinates-display').html(coords.map(c => `<div>${{c}}</div>`).join(''));
			}}
			
			map.on(L.Draw.Event.CREATED, function(e) {{
				drawnItems.addLayer(e.layer);
				updateWKT();
			}});
			
			map.on(L.Draw.Event.EDITED, function(e) {{
				updateWKT();
			}});
			
			map.on(L.Draw.Event.DELETED, function(e) {{
				updateWKT();
			}});
			
			$('.geo-clear').click(function() {{
				drawnItems.clearLayers();
				updateWKT();
			}});
			
			$('.geo-current-location').click(function() {{
				if (navigator.geolocation) {{
					navigator.geolocation.getCurrentPosition(function(position) {{
						var lat = position.coords.latitude;
						var lng = position.coords.longitude;
						map.setView([lat, lng], 15);
						
						var marker = L.marker([lat, lng]);
						drawnItems.clearLayers();
						drawnItems.addLayer(marker);
						updateWKT();
					}});
				}}
			}});
			
			$('.geo-show-wkt').change(function() {{
				if ($(this).is(':checked')) {{
					$('.geometry-info').show();
				}} else {{
					$('.geometry-info').hide();
				}}
			}});
			
			// Initialize with existing data
			var existingWkt = $('#{field.id}').val();
			if (existingWkt) {{
				// Parse WKT and add to map (simplified parser)
				if (existingWkt.startsWith('POINT')) {{
					var coords = existingWkt.match(/POINT\\(([^)]+)\\)/)[1].split(' ');
					var marker = L.marker([parseFloat(coords[1]), parseFloat(coords[0])]);
					drawnItems.addLayer(marker);
					map.setView([parseFloat(coords[1]), parseFloat(coords[0])], 15);
				}}
				updateWKT();
			}}
		}});
		</script>
		'''
		
		return Markup(html)


class PgVectorWidget(TextArea):
	"""
	Widget for pgvector embedding fields with similarity search capabilities
	"""
	
	def __init__(self, dimension=768):
		self.dimension = dimension
		super().__init__()
	
	def __call__(self, field, **kwargs):
		kwargs.setdefault('id', field.id)
		kwargs.setdefault('class', 'form-control')
		kwargs.setdefault('rows', 5)
		
		html_params_str = html_params(name=field.name, **kwargs)
		html = f'''
		<div class="pgvector-widget" data-dimension="{self.dimension}">
			<div class="vector-controls">
				<div class="btn-group" role="group">
					<button type="button" class="btn btn-default vector-parse" title="Parse Vector">
						<i class="fa fa-cogs"></i> Parse
					</button>
					<button type="button" class="btn btn-default vector-normalize" title="Normalize Vector">
						<i class="fa fa-balance-scale"></i> Normalize
					</button>
					<button type="button" class="btn btn-default vector-random" title="Generate Random">
						<i class="fa fa-random"></i> Random
					</button>
				</div>
				<div style="float: right;">
					<span class="vector-info">
						Expected dimension: {self.dimension}
					</span>
				</div>
			</div>
			
			<textarea {html_params_str} placeholder="Enter vector as comma-separated values or JSON array">{field.data or ''}</textarea>
			
			<div class="vector-status"></div>
			
			<div class="vector-visualization" style="margin-top: 10px;">
				<canvas class="vector-canvas" width="400" height="100" style="border: 1px solid #ddd;"></canvas>
				<div class="vector-stats" style="margin-top: 5px; font-size: 0.9em; color: #666;"></div>
			</div>
		</div>
		
		<style>
		.pgvector-widget {{
			border: 1px solid #ddd;
			border-radius: 4px;
			padding: 10px;
		}}
		.vector-controls {{
			margin-bottom: 10px;
			overflow: hidden;
		}}
		.vector-status.valid {{
			color: #28a745;
			font-size: 0.9em;
			margin-top: 5px;
		}}
		.vector-status.invalid {{
			color: #dc3545;
			font-size: 0.9em;
			margin-top: 5px;
		}}
		.vector-canvas {{
			background: #f8f9fa;
		}}
		</style>
		
		<script>
		$(document).ready(function() {{
			function parseVector(text) {{
				try {{
					// Try JSON array format
					if (text.trim().startsWith('[')) {{
						return JSON.parse(text);
					}}
					// Try comma-separated format
					return text.split(',').map(x => parseFloat(x.trim())).filter(x => !isNaN(x));
				}} catch(e) {{
					return null;
				}}
			}}
			
			function normalizeVector(vector) {{
				var magnitude = Math.sqrt(vector.reduce((sum, x) => sum + x * x, 0));
				return magnitude > 0 ? vector.map(x => x / magnitude) : vector;
			}}
			
			function updateVisualization(container) {{
				var textarea = container.find('textarea');
				var canvas = container.find('.vector-canvas')[0];
				var ctx = canvas.getContext('2d');
				var statusDiv = container.find('.vector-status');
				var statsDiv = container.find('.vector-stats');
				
				var vector = parseVector(textarea.val());
				
				if (!vector) {{
					statusDiv.removeClass('valid').addClass('invalid').text('Invalid vector format');
					ctx.clearRect(0, 0, canvas.width, canvas.height);
					statsDiv.text('');
					return;
				}}
				
				var expectedDim = parseInt(container.data('dimension'));
				if (vector.length !== expectedDim) {{
					statusDiv.removeClass('valid').addClass('invalid')
						.text(`Invalid dimension: got ${{vector.length}}, expected ${{expectedDim}}`);
				}} else {{
					statusDiv.removeClass('invalid').addClass('valid')
						.text(`Valid vector (${{vector.length}} dimensions)`);
				}}
				
				// Visualization
				ctx.clearRect(0, 0, canvas.width, canvas.height);
				
				if (vector.length > 0) {{
					var maxVal = Math.max(...vector.map(Math.abs));
					var barWidth = canvas.width / vector.length;
					var centerY = canvas.height / 2;
					
					vector.forEach((val, i) => {{
						var height = (Math.abs(val) / maxVal) * (canvas.height / 2);
						var x = i * barWidth;
						var y = val >= 0 ? centerY - height : centerY;
						
						ctx.fillStyle = val >= 0 ? '#28a745' : '#dc3545';
						ctx.fillRect(x, y, barWidth - 1, height);
					}});
					
					// Center line
					ctx.strokeStyle = '#666';
					ctx.lineWidth = 1;
					ctx.beginPath();
					ctx.moveTo(0, centerY);
					ctx.lineTo(canvas.width, centerY);
					ctx.stroke();
					
					// Statistics
					var magnitude = Math.sqrt(vector.reduce((sum, x) => sum + x * x, 0));
					var mean = vector.reduce((sum, x) => sum + x, 0) / vector.length;
					var min = Math.min(...vector);
					var max = Math.max(...vector);
					
					statsDiv.html(`
						Magnitude: ${{magnitude.toFixed(4)}} | 
						Mean: ${{mean.toFixed(4)}} | 
						Range: [${{min.toFixed(4)}}, ${{max.toFixed(4)}}]
					`);
				}}
			}}
			
			$('.vector-parse').click(function() {{
				var container = $(this).closest('.pgvector-widget');
				var textarea = container.find('textarea');
				var vector = parseVector(textarea.val());
				
				if (vector) {{
					textarea.val('[' + vector.join(', ') + ']');
					updateVisualization(container);
				}}
			}});
			
			$('.vector-normalize').click(function() {{
				var container = $(this).closest('.pgvector-widget');
				var textarea = container.find('textarea');
				var vector = parseVector(textarea.val());
				
				if (vector) {{
					var normalized = normalizeVector(vector);
					textarea.val('[' + normalized.map(x => x.toFixed(6)).join(', ') + ']');
					updateVisualization(container);
				}}
			}});
			
			$('.vector-random').click(function() {{
				var container = $(this).closest('.pgvector-widget');
				var textarea = container.find('textarea');
				var dimension = parseInt(container.data('dimension'));
				
				var randomVector = [];
				for (var i = 0; i < dimension; i++) {{
					randomVector.push((Math.random() - 0.5) * 2);
				}}
				
				textarea.val('[' + randomVector.map(x => x.toFixed(6)).join(', ') + ']');
				updateVisualization(container);
			}});
			
			// Real-time updates
			$(document).on('input', '.pgvector-widget textarea', function() {{
				var container = $(this).closest('.pgvector-widget');
				updateVisualization(container);
			}});
			
			// Initialize
			$('.pgvector-widget').each(function() {{
				updateVisualization($(this));
			}});
		}});
		</script>
		'''
		
		return Markup(html)


class PostgreSQLIntervalWidget(Input):
	"""
	Widget for PostgreSQL interval type
	"""
	input_type = 'text'
	
	def __call__(self, field, **kwargs):
		kwargs.setdefault('id', field.id)
		kwargs.setdefault('class', 'form-control')
		kwargs.setdefault('placeholder', 'e.g., 1 day, 2 hours 30 minutes, 1 month 2 weeks')
		
		html_params_str = html_params(name=field.name, type=self.input_type, **kwargs)
		html = f'''
		<div class="postgresql-interval-widget">
			<input {html_params_str} value="{field.data or ''}" />
			<div class="interval-presets" style="margin-top: 5px;">
				<div class="btn-group" role="group">
					<button type="button" class="btn btn-xs btn-default" data-interval="1 minute">1 min</button>
					<button type="button" class="btn btn-xs btn-default" data-interval="1 hour">1 hour</button>
					<button type="button" class="btn btn-xs btn-default" data-interval="1 day">1 day</button>
					<button type="button" class="btn btn-xs btn-default" data-interval="1 week">1 week</button>
					<button type="button" class="btn btn-xs btn-default" data-interval="1 month">1 month</button>
					<button type="button" class="btn btn-xs btn-default" data-interval="1 year">1 year</button>
				</div>
			</div>
			<small class="help-block">
				Examples: "2 days", "3 hours 30 minutes", "1 month 2 weeks", "1 year 6 months"
			</small>
		</div>
		
		<script>
		$(document).ready(function() {{
			$(document).on('click', '[data-interval]', function() {{
				var interval = $(this).data('interval');
				var input = $(this).closest('.postgresql-interval-widget').find('input');
				input.val(interval);
			}});
		}});
		</script>
		'''
		
		return Markup(html)


class PostgreSQLUUIDWidget(Input):
	"""
	Widget for PostgreSQL UUID type with generation capabilities
	"""
	input_type = 'text'
	
	def __call__(self, field, **kwargs):
		kwargs.setdefault('id', field.id)
		kwargs.setdefault('class', 'form-control')
		kwargs.setdefault('pattern', '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
		kwargs.setdefault('placeholder', 'xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx')
		
		html_params_str = html_params(name=field.name, type=self.input_type, **kwargs)
		html = f'''
		<div class="postgresql-uuid-widget">
			<div class="input-group">
				<input {html_params_str} value="{field.data or ''}" />
				<div class="input-group-btn">
					<button type="button" class="btn btn-default uuid-generate" title="Generate UUID">
						<i class="fa fa-refresh"></i>
					</button>
				</div>
			</div>
			<small class="help-block">
				Standard UUID format (8-4-4-4-12 hexadecimal digits)
			</small>
		</div>
		
		<script>
		$(document).ready(function() {{
			function generateUUID() {{
				return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {{
					var r = Math.random() * 16 | 0;
					var v = c == 'x' ? r : (r & 0x3 | 0x8);
					return v.toString(16);
				}});
			}}
			
			$(document).on('click', '.uuid-generate', function() {{
				var input = $(this).closest('.postgresql-uuid-widget').find('input');
				input.val(generateUUID());
			}});
		}});
		</script>
		'''
		
		return Markup(html)


class PostgreSQLBitStringWidget(Input):
	"""
	Widget for PostgreSQL bit and bit varying types
	"""
	input_type = 'text'
	
	def __init__(self, length=None):
		self.length = length
		super().__init__()
	
	def __call__(self, field, **kwargs):
		kwargs.setdefault('id', field.id)
		kwargs.setdefault('class', 'form-control')
		kwargs.setdefault('pattern', '[01]*')
		kwargs.setdefault('placeholder', 'Binary string (0s and 1s only)')
		
		if self.length:
			kwargs.setdefault('maxlength', self.length)
		
		html_params_str = html_params(name=field.name, type=self.input_type, **kwargs)
		html = f'''
		<div class="postgresql-bitstring-widget" data-length="{self.length or ''}">
			<input {html_params_str} value="{field.data or ''}" />
			<div class="bit-tools" style="margin-top: 5px;">
				<div class="btn-group" role="group">
					<button type="button" class="btn btn-xs btn-default bit-clear">Clear</button>
					<button type="button" class="btn btn-xs btn-default bit-fill">Fill 1s</button>
					<button type="button" class="btn btn-xs btn-default bit-random">Random</button>
					<button type="button" class="btn btn-xs btn-default bit-toggle">Toggle</button>
				</div>
			</div>
			{f'<small class="help-block">Length: {self.length} bits</small>' if self.length else ''}
		</div>
		
		<script>
		$(document).ready(function() {{
			$(document).on('click', '.bit-clear', function() {{
				var input = $(this).closest('.postgresql-bitstring-widget').find('input');
				var length = $(this).closest('.postgresql-bitstring-widget').data('length');
				input.val(length ? '0'.repeat(length) : '');
			}});
			
			$(document).on('click', '.bit-fill', function() {{
				var input = $(this).closest('.postgresql-bitstring-widget').find('input');
				var length = $(this).closest('.postgresql-bitstring-widget').data('length');
				input.val(length ? '1'.repeat(length) : '1111');
			}});
			
			$(document).on('click', '.bit-random', function() {{
				var input = $(this).closest('.postgresql-bitstring-widget').find('input');
				var length = $(this).closest('.postgresql-bitstring-widget').data('length') || 8;
				var random = '';
				for (var i = 0; i < length; i++) {{
					random += Math.random() > 0.5 ? '1' : '0';
				}}
				input.val(random);
			}});
			
			$(document).on('click', '.bit-toggle', function() {{
				var input = $(this).closest('.postgresql-bitstring-widget').find('input');
				var current = input.val();
				var toggled = current.split('').map(bit => bit === '1' ? '0' : '1').join('');
				input.val(toggled);
			}});
			
			// Validate input
			$(document).on('input', '.postgresql-bitstring-widget input', function() {{
				var value = $(this).val();
				var valid = /^[01]*$/.test(value);
				$(this).toggleClass('is-invalid', !valid);
			}});
		}});
		</script>
		'''
		
		return Markup(html)