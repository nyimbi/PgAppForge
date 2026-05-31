"""
Advanced Form Widget Components for PgForge

This module provides sophisticated form widgets with enhanced functionality
including form builders, validation widgets, and complex form layouts.
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


class FormBuilderWidget(Input):
    """
    Dynamic form builder widget for creating forms at runtime.
    
    Features:
    - Drag & drop form field creation
    - Live preview of forms
    - Field validation rules
    - Custom field types
    - Form templates and layouts
    - Export/import form definitions
    - Conditional field logic
    - Multi-step form support
    """
    
    input_type = 'hidden'
    
    def __init__(self,
                 available_fields: Optional[List[Dict]] = None,
                 form_templates: Optional[List[Dict]] = None,
                 enable_conditional_logic: bool = True,
                 max_fields: int = 50,
                 enable_validation: bool = True):
        """
        Initialize the form builder widget.
        
        Args:
            available_fields: List of available field types
            form_templates: Predefined form templates
            enable_conditional_logic: Enable conditional field display
            max_fields: Maximum number of fields per form
            enable_validation: Enable field validation
        """
        self.available_fields = available_fields or self._get_default_fields()
        self.form_templates = form_templates or []
        self.enable_conditional_logic = enable_conditional_logic
        self.max_fields = max_fields
        self.enable_validation = enable_validation
        
    def _get_default_fields(self):
        """Get default available field types."""
        return [
            {'type': 'text', 'label': 'Text Input', 'icon': 'fa-font'},
            {'type': 'textarea', 'label': 'Textarea', 'icon': 'fa-align-left'},
            {'type': 'email', 'label': 'Email', 'icon': 'fa-envelope'},
            {'type': 'number', 'label': 'Number', 'icon': 'fa-hashtag'},
            {'type': 'date', 'label': 'Date', 'icon': 'fa-calendar'},
            {'type': 'select', 'label': 'Select Dropdown', 'icon': 'fa-list'},
            {'type': 'radio', 'label': 'Radio Buttons', 'icon': 'fa-dot-circle-o'},
            {'type': 'checkbox', 'label': 'Checkbox', 'icon': 'fa-check-square-o'},
            {'type': 'file', 'label': 'File Upload', 'icon': 'fa-upload'},
            {'type': 'divider', 'label': 'Section Divider', 'icon': 'fa-minus'},
            {'type': 'heading', 'label': 'Heading', 'icon': 'fa-header'},
            {'type': 'paragraph', 'label': 'Paragraph Text', 'icon': 'fa-paragraph'}
        ]
        
    def __call__(self, field, **kwargs):
        """Render the form builder widget."""
        widget_id = kwargs.get('id', f'form_builder_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="form-builder-container" data-widget="form-builder">
            <div class="form-builder-toolbar">
                <div class="toolbar-section">
                    <h5>{{ _('Form Builder') }}</h5>
                    <div class="btn-group" role="group">
                        <button type="button" class="btn btn-outline-primary btn-sm" data-action="new-form">
                            <i class="fa fa-plus"></i> {{ _('New Form') }}
                        </button>
                        <button type="button" class="btn btn-outline-secondary btn-sm" data-action="save-template">
                            <i class="fa fa-save"></i> {{ _('Save Template') }}
                        </button>
                        <button type="button" class="btn btn-outline-info btn-sm" data-action="preview">
                            <i class="fa fa-eye"></i> {{ _('Preview') }}
                        </button>
                    </div>
                </div>
                
                <div class="toolbar-section">
                    <div class="form-settings">
                        <label for="form-name-{{ widget_id }}">{{ _('Form Name') }}:</label>
                        <input type="text" id="form-name-{{ widget_id }}" class="form-control form-control-sm" 
                               placeholder="{{ _('Enter form name...') }}">
                    </div>
                </div>
            </div>
            
            <div class="form-builder-main">
                <div class="field-palette">
                    <h6>{{ _('Available Fields') }}</h6>
                    <div class="field-types">
                        {% for field_type in available_fields %}
                        <div class="field-type-item" draggable="true" data-field-type="{{ field_type.type }}">
                            <i class="fa {{ field_type.icon }}"></i>
                            <span>{{ field_type.label }}</span>
                        </div>
                        {% endfor %}
                    </div>
                    
                    {% if form_templates %}
                    <h6>{{ _('Form Templates') }}</h6>
                    <div class="form-templates">
                        {% for template in form_templates %}
                        <button type="button" class="btn btn-outline-secondary btn-sm mb-2" 
                                data-template="{{ loop.index0 }}">
                            <i class="fa fa-file-o"></i> {{ template.name }}
                        </button>
                        {% endfor %}
                    </div>
                    {% endif %}
                </div>
                
                <div class="form-canvas">
                    <div class="canvas-header">
                        <h6>{{ _('Form Design') }}</h6>
                        <small class="text-muted">{{ _('Drag fields from the left panel to build your form') }}</small>
                    </div>
                    
                    <div class="form-drop-zone" id="form-canvas-{{ widget_id }}">
                        <div class="empty-canvas">
                            <i class="fa fa-plus-circle fa-3x text-muted"></i>
                            <p class="text-muted">{{ _('Drag fields here to start building your form') }}</p>
                        </div>
                    </div>
                </div>
                
                <div class="field-properties">
                    <h6>{{ _('Field Properties') }}</h6>
                    <div class="properties-content">
                        <p class="text-muted">{{ _('Select a field to edit its properties') }}</p>
                    </div>
                </div>
            </div>
            
            <input type="hidden" id="{{ widget_id }}" name="{{ field.name }}" value="{{ field.data or '' }}">
        </div>
        
        <!-- Field Properties Panel Template -->
        <template id="field-properties-template-{{ widget_id }}">
            <div class="field-property-group">
                <label>{{ _('Field Label') }}:</label>
                <input type="text" class="form-control form-control-sm" data-property="label">
            </div>
            
            <div class="field-property-group">
                <label>{{ _('Field Name') }}:</label>
                <input type="text" class="form-control form-control-sm" data-property="name">
            </div>
            
            <div class="field-property-group">
                <label>{{ _('Placeholder') }}:</label>
                <input type="text" class="form-control form-control-sm" data-property="placeholder">
            </div>
            
            <div class="field-property-group">
                <div class="form-check">
                    <input type="checkbox" class="form-check-input" data-property="required">
                    <label class="form-check-label">{{ _('Required Field') }}</label>
                </div>
            </div>
            
            <div class="field-property-group validation-rules" style="display: none;">
                <label>{{ _('Validation Rules') }}:</label>
                <select class="form-control form-control-sm" data-property="validation">
                    <option value="">{{ _('No validation') }}</option>
                    <option value="email">{{ _('Email format') }}</option>
                    <option value="number">{{ _('Numbers only') }}</option>
                    <option value="minLength">{{ _('Minimum length') }}</option>
                    <option value="maxLength">{{ _('Maximum length') }}</option>
                    <option value="pattern">{{ _('Custom pattern') }}</option>
                </select>
            </div>
            
            <div class="field-property-group conditional-logic" style="display: none;">
                <label>{{ _('Show field when') }}:</label>
                <select class="form-control form-control-sm" data-property="condition-field">
                    <option value="">{{ _('Always show') }}</option>
                </select>
                <select class="form-control form-control-sm mt-1" data-property="condition-operator">
                    <option value="equals">{{ _('equals') }}</option>
                    <option value="not-equals">{{ _('does not equal') }}</option>
                    <option value="contains">{{ _('contains') }}</option>
                </select>
                <input type="text" class="form-control form-control-sm mt-1" data-property="condition-value" 
                       placeholder="{{ _('Condition value') }}">
            </div>
            
            <div class="field-actions">
                <button type="button" class="btn btn-danger btn-sm" data-action="delete-field">
                    <i class="fa fa-trash"></i> {{ _('Delete Field') }}
                </button>
                <button type="button" class="btn btn-secondary btn-sm" data-action="duplicate-field">
                    <i class="fa fa-copy"></i> {{ _('Duplicate') }}
                </button>
            </div>
        </template>
        
        <style>
        .form-builder-container {
            border: 1px solid #dee2e6;
            border-radius: 8px;
            background: #f8f9fa;
            min-height: 600px;
        }
        
        .form-builder-toolbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem;
            border-bottom: 1px solid #dee2e6;
            background: white;
            border-radius: 8px 8px 0 0;
        }
        
        .toolbar-section {
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .toolbar-section h5 {
            margin: 0;
        }
        
        .form-settings {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .form-settings label {
            margin: 0;
            white-space: nowrap;
        }
        
        .form-settings input {
            width: 200px;
        }
        
        .form-builder-main {
            display: flex;
            height: 500px;
        }
        
        .field-palette {
            width: 250px;
            padding: 1rem;
            border-right: 1px solid #dee2e6;
            background: white;
            overflow-y: auto;
        }
        
        .field-palette h6 {
            margin-bottom: 1rem;
            color: #495057;
        }
        
        .field-types {
            margin-bottom: 2rem;
        }
        
        .field-type-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            background: #f8f9fa;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            cursor: grab;
            transition: all 0.2s ease;
        }
        
        .field-type-item:hover {
            background: #e9ecef;
            transform: translateX(2px);
        }
        
        .field-type-item:active {
            cursor: grabbing;
        }
        
        .field-type-item i {
            width: 16px;
            text-align: center;
            color: #6c757d;
        }
        
        .form-canvas {
            flex: 1;
            padding: 1rem;
            background: white;
        }
        
        .canvas-header {
            margin-bottom: 1rem;
        }
        
        .canvas-header h6 {
            margin: 0;
        }
        
        .form-drop-zone {
            min-height: 400px;
            border: 2px dashed #dee2e6;
            border-radius: 8px;
            padding: 2rem;
            background: #fdfdfd;
        }
        
        .form-drop-zone.drag-over {
            border-color: #0d6efd;
            background: #f0f8ff;
        }
        
        .empty-canvas {
            text-align: center;
            padding: 4rem 2rem;
        }
        
        .form-field-item {
            margin-bottom: 1rem;
            padding: 1rem;
            border: 1px solid #e9ecef;
            border-radius: 6px;
            background: white;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
        }
        
        .form-field-item:hover {
            border-color: #0d6efd;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .form-field-item.selected {
            border-color: #0d6efd;
            box-shadow: 0 0 0 2px rgba(13, 110, 253, 0.25);
        }
        
        .field-drag-handle {
            position: absolute;
            top: 1rem;
            right: 1rem;
            cursor: grab;
            color: #6c757d;
        }
        
        .field-drag-handle:active {
            cursor: grabbing;
        }
        
        .field-properties {
            width: 300px;
            padding: 1rem;
            border-left: 1px solid #dee2e6;
            background: white;
            overflow-y: auto;
        }
        
        .field-properties h6 {
            margin-bottom: 1rem;
        }
        
        .field-property-group {
            margin-bottom: 1rem;
        }
        
        .field-property-group label {
            display: block;
            margin-bottom: 0.25rem;
            font-size: 0.875rem;
            font-weight: 500;
        }
        
        .field-actions {
            padding-top: 1rem;
            border-top: 1px solid #e9ecef;
            display: flex;
            gap: 0.5rem;
        }
        
        .form-templates button {
            display: block;
            width: 100%;
            text-align: left;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="form-builder"]');
            const canvas = document.getElementById('form-canvas-{{ widget_id }}');
            const hiddenInput = document.getElementById('{{ widget_id }}');
            const propertiesPanel = container.querySelector('.properties-content');
            const propertiesTemplate = document.getElementById('field-properties-template-{{ widget_id }}');
            
            let formFields = [];
            let selectedFieldId = null;
            let draggedFieldType = null;
            let fieldIdCounter = 0;
            
            // Initialize with existing data
            function initializeBuilder() {
                const existingData = hiddenInput.value;
                if (existingData) {
                    try {
                        const formData = JSON.parse(existingData);
                        formFields = formData.fields || [];
                        renderForm();
                    } catch (e) {
                        console.warn('Invalid form data:', e);
                    }
                }
            }
            
            // Create field instance
            function createField(fieldType, options = {}) {
                fieldIdCounter++;
                return {
                    id: `field_${fieldIdCounter}`,
                    type: fieldType,
                    label: options.label || getDefaultLabel(fieldType),
                    name: options.name || `field_${fieldIdCounter}`,
                    placeholder: options.placeholder || '',
                    required: options.required || false,
                    validation: options.validation || '',
                    condition: options.condition || null,
                    options: options.fieldOptions || []
                };
            }
            
            // Get default label for field type
            function getDefaultLabel(fieldType) {
                const fieldTypes = {{ available_fields | tojson }};
                const fieldDef = fieldTypes.find(f => f.type === fieldType);
                return fieldDef ? fieldDef.label : fieldType.charAt(0).toUpperCase() + fieldType.slice(1);
            }
            
            // Render form in canvas
            function renderForm() {
                if (formFields.length === 0) {
                    canvas.innerHTML = `
                        <div class="empty-canvas">
                            <i class="fa fa-plus-circle fa-3x text-muted"></i>
                            <p class="text-muted">{{ _('Drag fields here to start building your form') }}</p>
                        </div>
                    `;
                    return;
                }
                
                canvas.innerHTML = '';
                formFields.forEach((field, index) => {
                    const fieldElement = createFieldElement(field, index);
                    canvas.appendChild(fieldElement);
                });
                
                updateHiddenInput();
            }
            
            // Create field element for canvas
            function createFieldElement(field, index) {
                const fieldDiv = document.createElement('div');
                fieldDiv.className = 'form-field-item';
                fieldDiv.dataset.fieldId = field.id;
                fieldDiv.dataset.index = index;
                
                let fieldHTML = '';
                switch (field.type) {
                    case 'text':
                    case 'email':
                    case 'number':
                        fieldHTML = `
                            <label class="form-label">${field.label} ${field.required ? '<span class="text-danger">*</span>' : ''}</label>
                            <input type="${field.type}" class="form-control" placeholder="${field.placeholder}" readonly>
                        `;
                        break;
                    case 'textarea':
                        fieldHTML = `
                            <label class="form-label">${field.label} ${field.required ? '<span class="text-danger">*</span>' : ''}</label>
                            <textarea class="form-control" placeholder="${field.placeholder}" readonly></textarea>
                        `;
                        break;
                    case 'select':
                        fieldHTML = `
                            <label class="form-label">${field.label} ${field.required ? '<span class="text-danger">*</span>' : ''}</label>
                            <select class="form-control" disabled>
                                <option>{{ _('Option 1') }}</option>
                                <option>{{ _('Option 2') }}</option>
                            </select>
                        `;
                        break;
                    case 'date':
                        fieldHTML = `
                            <label class="form-label">${field.label} ${field.required ? '<span class="text-danger">*</span>' : ''}</label>
                            <input type="date" class="form-control" readonly>
                        `;
                        break;
                    case 'heading':
                        fieldHTML = `<h4>${field.label}</h4>`;
                        break;
                    case 'paragraph':
                        fieldHTML = `<p class="text-muted">${field.label}</p>`;
                        break;
                    case 'divider':
                        fieldHTML = `<hr>`;
                        break;
                    default:
                        fieldHTML = `
                            <label class="form-label">${field.label} ${field.required ? '<span class="text-danger">*</span>' : ''}</label>
                            <input type="text" class="form-control" placeholder="${field.placeholder}" readonly>
                        `;
                }
                
                fieldDiv.innerHTML = `
                    ${fieldHTML}
                    <div class="field-drag-handle">
                        <i class="fa fa-bars"></i>
                    </div>
                `;
                
                return fieldDiv;
            }
            
            // Update hidden input with form data
            function updateHiddenInput() {
                const formData = {
                    name: container.querySelector(`#form-name-{{ widget_id }}`).value,
                    fields: formFields
                };
                hiddenInput.value = JSON.stringify(formData);
            }
            
            // Show field properties
            function showFieldProperties(fieldId) {
                selectedFieldId = fieldId;
                const field = formFields.find(f => f.id === fieldId);
                if (!field) return;
                
                // Highlight selected field
                canvas.querySelectorAll('.form-field-item').forEach(item => {
                    item.classList.toggle('selected', item.dataset.fieldId === fieldId);
                });
                
                // Populate properties panel
                propertiesPanel.innerHTML = propertiesTemplate.innerHTML;
                
                // Fill current values
                const labelInput = propertiesPanel.querySelector('[data-property="label"]');
                const nameInput = propertiesPanel.querySelector('[data-property="name"]');
                const placeholderInput = propertiesPanel.querySelector('[data-property="placeholder"]');
                const requiredCheckbox = propertiesPanel.querySelector('[data-property="required"]');
                
                if (labelInput) labelInput.value = field.label;
                if (nameInput) nameInput.value = field.name;
                if (placeholderInput) placeholderInput.value = field.placeholder;
                if (requiredCheckbox) requiredCheckbox.checked = field.required;
                
                // Show/hide relevant property groups based on field type
                const validationGroup = propertiesPanel.querySelector('.validation-rules');
                const conditionalGroup = propertiesPanel.querySelector('.conditional-logic');
                
                if (validationGroup && {{ enable_validation | tojson }}) {
                    const showValidation = ['text', 'email', 'number', 'textarea'].includes(field.type);
                    validationGroup.style.display = showValidation ? 'block' : 'none';
                }
                
                if (conditionalGroup && {{ enable_conditional_logic | tojson }}) {
                    conditionalGroup.style.display = 'block';
                    // Populate condition field options
                    const conditionSelect = conditionalGroup.querySelector('[data-property="condition-field"]');
                    conditionSelect.innerHTML = '<option value="">{{ _("Always show") }}</option>';
                    formFields.forEach(f => {
                        if (f.id !== fieldId) {
                            conditionSelect.innerHTML += `<option value="${f.id}">${f.label}</option>`;
                        }
                    });
                }
            }
            
            // Drag & drop functionality
            container.addEventListener('dragstart', (e) => {
                if (e.target.classList.contains('field-type-item')) {
                    draggedFieldType = e.target.dataset.fieldType;
                    e.dataTransfer.effectAllowed = 'copy';
                }
            });\n            
            canvas.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'copy';
                canvas.classList.add('drag-over');
            });
            
            canvas.addEventListener('dragleave', () => {
                canvas.classList.remove('drag-over');
            });
            
            canvas.addEventListener('drop', (e) => {
                e.preventDefault();
                canvas.classList.remove('drag-over');
                
                if (draggedFieldType) {
                    // Check field limit
                    if (formFields.length >= {{ max_fields }}) {
                        alert(`Maximum {{ max_fields }} fields allowed`);
                        return;
                    }
                    
                    const newField = createField(draggedFieldType);
                    formFields.push(newField);
                    renderForm();
                    showFieldProperties(newField.id);
                    draggedFieldType = null;
                }
            });
            
            // Field selection
            canvas.addEventListener('click', (e) => {
                const fieldItem = e.target.closest('.form-field-item');
                if (fieldItem) {
                    showFieldProperties(fieldItem.dataset.fieldId);
                }
            });
            
            // Property changes
            propertiesPanel.addEventListener('input', (e) => {
                const property = e.target.dataset.property;
                if (!property || !selectedFieldId) return;
                
                const field = formFields.find(f => f.id === selectedFieldId);
                if (!field) return;
                
                switch (property) {
                    case 'label':
                        field.label = e.target.value;
                        break;
                    case 'name':
                        field.name = e.target.value;
                        break;
                    case 'placeholder':
                        field.placeholder = e.target.value;
                        break;
                    case 'required':
                        field.required = e.target.checked;
                        break;
                    case 'validation':
                        field.validation = e.target.value;
                        break;
                }
                
                renderForm();
                showFieldProperties(selectedFieldId);
            });
            
            // Field actions
            propertiesPanel.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (!action || !selectedFieldId) return;
                
                const fieldIndex = formFields.findIndex(f => f.id === selectedFieldId);
                if (fieldIndex === -1) return;
                
                switch (action) {
                    case 'delete-field':
                        if (confirm('{{ _("Are you sure you want to delete this field?") }}')) {
                            formFields.splice(fieldIndex, 1);
                            selectedFieldId = null;
                            propertiesPanel.innerHTML = '<p class="text-muted">{{ _("Select a field to edit its properties") }}</p>';
                            renderForm();
                        }
                        break;
                        
                    case 'duplicate-field':
                        const originalField = formFields[fieldIndex];
                        const duplicatedField = { ...originalField };
                        duplicatedField.id = `field_${++fieldIdCounter}`;
                        duplicatedField.label += ' (Copy)';
                        duplicatedField.name += '_copy';
                        formFields.splice(fieldIndex + 1, 0, duplicatedField);
                        renderForm();
                        break;
                }
            });
            
            // Toolbar actions
            container.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (!action) return;
                
                switch (action) {
                    case 'new-form':
                        if (formFields.length > 0 && !confirm('{{ _("This will clear the current form. Continue?") }}')) {
                            break;
                        }
                        formFields = [];
                        selectedFieldId = null;
                        container.querySelector(`#form-name-{{ widget_id }}`).value = '';
                        propertiesPanel.innerHTML = '<p class="text-muted">{{ _("Select a field to edit its properties") }}</p>';
                        renderForm();
                        break;
                        
                    case 'preview':
                        // Open preview in new window/modal
                        const previewData = {
                            name: container.querySelector(`#form-name-{{ widget_id }}`).value,
                            fields: formFields
                        };
                        console.log('Form Preview:', previewData);
                        // In real implementation, would open preview modal
                        alert('{{ _("Preview functionality would open here") }}');
                        break;
                        
                    case 'save-template':
                        const templateName = prompt('{{ _("Enter template name:") }}');
                        if (templateName && formFields.length > 0) {
                            console.log('Saving template:', templateName, formFields);
                            // In real implementation, would save to database
                            alert('{{ _("Template saved successfully") }}');
                        }
                        break;
                }
            });
            
            // Form name change
            container.querySelector(`#form-name-{{ widget_id }}`).addEventListener('input', updateHiddenInput);
            
            // Initialize
            initializeBuilder();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            available_fields=self.available_fields,
            form_templates=self.form_templates,
            enable_conditional_logic=self.enable_conditional_logic,
            enable_validation=self.enable_validation,
            max_fields=self.max_fields,
            _=gettext
        ))


class ValidationWidget(Input):
    """
    Advanced validation widget with real-time feedback.
    
    Features:
    - Real-time validation
    - Multiple validation rules
    - Custom error messages
    - Visual feedback indicators
    - Async validation support
    - Custom validation functions
    - Progressive enhancement
    """
    
    input_type = 'text'
    
    def __init__(self,
                 validation_rules: Optional[List[Dict]] = None,
                 show_progress: bool = True,
                 async_validation: Optional[str] = None,
                 debounce_delay: int = 300):
        """
        Initialize the validation widget.
        
        Args:
            validation_rules: List of validation rules
            show_progress: Show validation progress indicator
            async_validation: URL for async validation
            debounce_delay: Delay before validation in milliseconds
        """
        self.validation_rules = validation_rules or []
        self.show_progress = show_progress
        self.async_validation = async_validation
        self.debounce_delay = debounce_delay
        
    def __call__(self, field, **kwargs):
        """Render the validation widget."""
        widget_id = kwargs.get('id', f'validation_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'form-control validation-input')
        
        input_html = super().__call__(field, **kwargs)
        
        template = """
        <div class="validation-container" data-widget="validation">
            {{ input_html | safe }}
            
            {% if show_progress %}
            <div class="validation-progress">
                <div class="progress-bar"></div>
            </div>
            {% endif %}
            
            <div class="validation-feedback">
                <div class="validation-messages"></div>
                {% if show_progress %}
                <div class="validation-strength">
                    <div class="strength-meter">
                        <div class="strength-bar"></div>
                    </div>
                    <span class="strength-text">{{ _('Enter value...') }}</span>
                </div>
                {% endif %}
            </div>
        </div>
        
        <style>
        .validation-container {
            position: relative;
        }
        
        .validation-input {
            transition: all 0.3s ease;
        }
        
        .validation-input.validating {
            border-color: #ffc107;
        }
        
        .validation-input.valid {
            border-color: #198754;
            background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 8 8'%3e%3cpath fill='%23198754' d='m2.3 6.73.94-.94 1.88 1.88 3.06-3.06.94.94-4 4z'/%3e%3c/svg%3e");
            background-repeat: no-repeat;
            background-position: right calc(0.375em + 0.1875rem) center;
            background-size: calc(0.75em + 0.375rem) calc(0.75em + 0.375rem);
        }
        
        .validation-input.invalid {
            border-color: #dc3545;
            background-image: url("data:image/svg+xml,%3csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 12 12' width='12' height='12' fill='none' stroke='%23dc3545'%3e%3ccircle cx='6' cy='6' r='4.5'/%3e%3cpath d='m5.8 4.6 2.4 2.4M8.2 4.6l-2.4 2.4'/%3e%3c/svg%3e");
            background-repeat: no-repeat;
            background-position: right calc(0.375em + 0.1875rem) center;
            background-size: calc(0.75em + 0.375rem) calc(0.75em + 0.375rem);
        }
        
        .validation-progress {
            height: 2px;
            background-color: #e9ecef;
            margin-top: 0.25rem;
            border-radius: 1px;
            overflow: hidden;
        }
        
        .progress-bar {
            height: 100%;
            background-color: #0d6efd;
            width: 0%;
            transition: all 0.3s ease;
        }
        
        .validation-feedback {
            margin-top: 0.5rem;
        }
        
        .validation-messages {
            font-size: 0.875rem;
        }
        
        .validation-message {
            display: flex;
            align-items: center;
            gap: 0.25rem;
            margin-bottom: 0.25rem;
        }
        
        .validation-message.success {
            color: #198754;
        }
        
        .validation-message.error {
            color: #dc3545;
        }
        
        .validation-message.warning {
            color: #ffc107;
        }
        
        .validation-strength {
            margin-top: 0.5rem;
        }
        
        .strength-meter {
            height: 4px;
            background-color: #e9ecef;
            border-radius: 2px;
            overflow: hidden;
            margin-bottom: 0.25rem;
        }
        
        .strength-bar {
            height: 100%;
            width: 0%;
            transition: all 0.3s ease;
            background: linear-gradient(to right, #dc3545, #ffc107, #198754);
        }
        
        .strength-text {
            font-size: 0.75rem;
            color: #6c757d;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="validation"]');
            const input = document.getElementById('{{ widget_id }}');
            const messages = container.querySelector('.validation-messages');
            const progressBar = container.querySelector('.progress-bar');
            const strengthBar = container.querySelector('.strength-bar');
            const strengthText = container.querySelector('.strength-text');
            
            const validationRules = {{ validation_rules | tojson }};
            let validationTimeout;
            let isValid = false;
            
            // Built-in validation functions
            const validators = {
                required: (value) => ({
                    valid: value.trim().length > 0,
                    message: '{{ _("This field is required") }}'
                }),
                
                email: (value) => ({
                    valid: /^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(value),
                    message: '{{ _("Please enter a valid email address") }}'
                }),
                
                minLength: (value, options) => ({
                    valid: value.length >= (options.min || 0),
                    message: `{{ _("Minimum length is") }} ${options.min || 0} {{ _("characters") }}`
                }),
                
                maxLength: (value, options) => ({
                    valid: value.length <= (options.max || Infinity),
                    message: `{{ _("Maximum length is") }} ${options.max || 0} {{ _("characters") }}`
                }),
                
                pattern: (value, options) => ({
                    valid: new RegExp(options.pattern).test(value),
                    message: options.message || '{{ _("Invalid format") }}'
                }),
                
                number: (value) => ({
                    valid: !isNaN(value) && !isNaN(parseFloat(value)),
                    message: '{{ _("Please enter a valid number") }}'
                }),
                
                url: (value) => ({
                    valid: /^https?:\\/\\/.+/.test(value),
                    message: '{{ _("Please enter a valid URL") }}'
                }),
                
                strongPassword: (value) => {
                    const hasLower = /[a-z]/.test(value);
                    const hasUpper = /[A-Z]/.test(value);
                    const hasNumber = /\\d/.test(value);
                    const hasSpecial = /[!@#$%^&*(),.?\":{}|<>]/.test(value);
                    const minLength = value.length >= 8;
                    
                    return {
                        valid: hasLower && hasUpper && hasNumber && hasSpecial && minLength,
                        message: '{{ _("Password must contain uppercase, lowercase, number, and special character") }}',
                        strength: [hasLower, hasUpper, hasNumber, hasSpecial, minLength].filter(Boolean).length
                    };
                }
            };
            
            // Validate input
            function validateInput(value) {
                const results = [];
                let overallValid = true;
                let strength = 0;
                
                validationRules.forEach(rule => {
                    const validator = validators[rule.type];
                    if (validator) {
                        const result = validator(value, rule.options || {});
                        results.push({
                            ...result,
                            type: rule.type,
                            priority: rule.priority || 'error'
                        });
                        
                        if (!result.valid) {
                            overallValid = false;
                        }
                        
                        if (result.strength !== undefined) {
                            strength = result.strength;
                        }
                    }
                });
                
                return { results, valid: overallValid, strength };
            }
            
            // Update UI with validation results
            function updateValidationUI(validation) {
                // Update input styling
                input.classList.remove('valid', 'invalid', 'validating');
                if (input.value) {
                    input.classList.add(validation.valid ? 'valid' : 'invalid');
                }
                
                // Update messages
                messages.innerHTML = '';
                validation.results.forEach(result => {
                    const messageDiv = document.createElement('div');
                    messageDiv.className = `validation-message ${result.valid ? 'success' : result.priority}`;
                    
                    const icon = result.valid ? 
                        '<i class="fa fa-check"></i>' : 
                        '<i class="fa fa-times"></i>';
                    
                    messageDiv.innerHTML = `${icon} ${result.message}`;
                    messages.appendChild(messageDiv);
                });
                
                // Update progress
                if (progressBar) {
                    const progress = validation.valid ? 100 : 
                        (validation.results.filter(r => r.valid).length / validation.results.length) * 100;
                    progressBar.style.width = progress + '%';
                    progressBar.style.backgroundColor = validation.valid ? '#198754' : '#ffc107';
                }
                
                // Update strength meter
                if (strengthBar && validation.strength !== undefined) {
                    const strengthPercent = (validation.strength / 5) * 100;
                    strengthBar.style.width = strengthPercent + '%';
                    
                    if (strengthText) {
                        const strengthLabels = ['{{ _("Very Weak") }}', '{{ _("Weak") }}', '{{ _("Fair") }}', '{{ _("Good") }}', '{{ _("Strong") }}'];
                        strengthText.textContent = strengthLabels[validation.strength - 1] || '{{ _("Enter value...") }}';
                    }
                }
                
                isValid = validation.valid;
            }
            
            // Async validation
            async function performAsyncValidation(value) {
                {% if async_validation %}
                try {
                    const response = await fetch('{{ async_validation }}', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ value, field: '{{ field.name }}' })
                    });
                    
                    const result = await response.json();
                    if (!result.valid) {
                        const messageDiv = document.createElement('div');
                        messageDiv.className = 'validation-message error';
                        messageDiv.innerHTML = `<i class="fa fa-times"></i> ${result.message}`;
                        messages.appendChild(messageDiv);
                        
                        input.classList.remove('valid');
                        input.classList.add('invalid');
                        isValid = false;
                    }
                } catch (error) {
                    console.error('Async validation error:', error);
                }
                {% endif %}
            }
            
            // Input event handler
            input.addEventListener('input', () => {
                const value = input.value;
                
                // Clear previous timeout
                clearTimeout(validationTimeout);
                
                // Show validating state
                input.classList.add('validating');
                
                // Debounce validation
                validationTimeout = setTimeout(async () => {
                    input.classList.remove('validating');
                    
                    // Perform validation
                    const validation = validateInput(value);
                    updateValidationUI(validation);
                    
                    // Perform async validation if available
                    if (isValid && value) {
                        await performAsyncValidation(value);
                    }
                }, {{ debounce_delay }});
            });
            
            // Initial validation if field has value
            if (input.value) {
                const validation = validateInput(input.value);
                updateValidationUI(validation);
            }
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            input_html=input_html,
            validation_rules=self.validation_rules,
            show_progress=self.show_progress,
            async_validation=self.async_validation,
            debounce_delay=self.debounce_delay,
            _=gettext
        ))


class ConditionalFieldWidget(Input):
    """
    Conditional field widget that shows/hides based on other field values.
    
    Features:
    - Field dependency management
    - Multiple condition types (equals, contains, greater than, etc.)
    - Nested condition logic (AND/OR)
    - Smooth animations for show/hide
    - Form value synchronization
    - Dynamic validation updates
    """
    
    input_type = 'text'
    
    def __init__(self,
                 conditions: List[Dict],
                 animation_duration: int = 300,
                 show_by_default: bool = False):
        """
        Initialize the conditional field widget.
        
        Args:
            conditions: List of condition objects
            animation_duration: Animation duration in milliseconds
            show_by_default: Whether to show field by default
        """
        self.conditions = conditions
        self.animation_duration = animation_duration
        self.show_by_default = show_by_default
        
    def __call__(self, field, **kwargs):
        """Render the conditional field widget."""
        widget_id = kwargs.get('id', f'conditional_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'form-control conditional-field')
        
        input_html = super().__call__(field, **kwargs)
        
        template = """
        <div class="conditional-field-container" 
             data-widget="conditional-field" 
             data-conditions="{{ conditions | tojson | escape }}"
             style="{% if not show_by_default %}display: none;{% endif %}">
             
            <div class="conditional-field-wrapper">
                {{ input_html | safe }}
            </div>
        </div>
        
        <style>
        .conditional-field-container {
            transition: all {{ animation_duration }}ms ease;
            overflow: hidden;
        }
        
        .conditional-field-container.hiding {
            opacity: 0;
            transform: translateY(-10px);
        }
        
        .conditional-field-container.showing {
            opacity: 1;
            transform: translateY(0);
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="conditional-field"]');
            const input = document.getElementById('{{ widget_id }}');
            const conditions = {{ conditions | tojson }};
            
            // Monitor form changes
            function initializeConditionalLogic() {
                const form = input.closest('form');
                if (!form) return;
                
                // Get all fields that this field depends on
                const dependencyFields = new Set();
                conditions.forEach(condition => {
                    if (condition.field) {
                        dependencyFields.add(condition.field);
                    }
                });
                
                // Add listeners to dependency fields
                dependencyFields.forEach(fieldName => {
                    const dependencyField = form.querySelector(`[name="${fieldName}"]`);
                    if (dependencyField) {
                        dependencyField.addEventListener('change', checkConditions);
                        dependencyField.addEventListener('input', checkConditions);
                    }
                });
                
                // Initial check
                checkConditions();
            }
            
            // Check if conditions are met
            function checkConditions() {
                const form = input.closest('form');
                if (!form) return;
                
                let shouldShow = conditions.length === 0; // Show by default if no conditions
                
                if (conditions.length > 0) {
                    // Evaluate conditions (assuming OR logic for simplicity)
                    shouldShow = conditions.some(condition => evaluateCondition(condition, form));
                }
                
                toggleVisibility(shouldShow);
            }
            
            // Evaluate single condition
            function evaluateCondition(condition, form) {
                const field = form.querySelector(`[name="${condition.field}"]`);
                if (!field) return false;
                
                const fieldValue = getFieldValue(field);
                const conditionValue = condition.value;
                
                switch (condition.operator) {
                    case 'equals':
                        return fieldValue === conditionValue;
                    case 'not-equals':
                        return fieldValue !== conditionValue;
                    case 'contains':
                        return fieldValue.toString().includes(conditionValue);
                    case 'greater-than':
                        return parseFloat(fieldValue) > parseFloat(conditionValue);
                    case 'less-than':
                        return parseFloat(fieldValue) < parseFloat(conditionValue);
                    case 'is-empty':
                        return !fieldValue || fieldValue.toString().trim() === '';
                    case 'is-not-empty':
                        return fieldValue && fieldValue.toString().trim() !== '';
                    default:
                        return false;
                }
            }
            
            // Get field value regardless of field type
            function getFieldValue(field) {
                if (field.type === 'checkbox' || field.type === 'radio') {
                    return field.checked ? field.value : '';
                } else if (field.tagName === 'SELECT') {
                    return field.value;
                } else {
                    return field.value;
                }
            }
            
            // Toggle field visibility with animation
            function toggleVisibility(shouldShow) {
                if (shouldShow) {
                    showField();
                } else {
                    hideField();
                }
            }
            
            function showField() {
                if (container.style.display === 'none') {
                    container.style.display = 'block';
                    container.classList.add('showing');
                    container.classList.remove('hiding');
                    
                    // Re-enable validation if applicable
                    input.disabled = false;
                }
            }
            
            function hideField() {
                if (container.style.display !== 'none') {
                    container.classList.add('hiding');
                    container.classList.remove('showing');
                    
                    setTimeout(() => {
                        container.style.display = 'none';
                        // Disable validation when hidden
                        input.disabled = true;
                        input.value = ''; // Clear value when hidden
                    }, {{ animation_duration }});
                }
            }
            
            // Initialize when DOM is ready
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', initializeConditionalLogic);
            } else {
                initializeConditionalLogic();
            }
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            input_html=input_html,
            conditions=self.conditions,
            animation_duration=self.animation_duration,
            show_by_default=self.show_by_default,
            _=gettext
        ))


class MultiStepFormWidget(Input):
    """
    Multi-step form wizard widget with progress tracking.
    
    Features:
    - Step-by-step form navigation
    - Progress indicator
    - Step validation
    - Data persistence between steps
    - Custom step templates
    - Conditional step logic
    - Review step before submission
    """
    
    input_type = 'hidden'
    
    def __init__(self,
                 steps: List[Dict],
                 show_progress: bool = True,
                 save_progress: bool = True,
                 linear_navigation: bool = True):
        """
        Initialize the multi-step form widget.
        
        Args:
            steps: List of step definitions
            show_progress: Show progress indicator
            save_progress: Save progress to localStorage
            linear_navigation: Require completing steps in order
        """
        self.steps = steps
        self.show_progress = show_progress
        self.save_progress = save_progress
        self.linear_navigation = linear_navigation
        
    def __call__(self, field, **kwargs):
        """Render the multi-step form widget."""
        widget_id = kwargs.get('id', f'multistep_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="multistep-form-container" data-widget="multistep-form">
            {% if show_progress %}
            <div class="multistep-progress">
                <div class="progress-header">
                    <h5>{{ _('Form Progress') }}</h5>
                    <span class="step-counter">
                        <span class="current-step">1</span> {{ _('of') }} <span class="total-steps">{{ steps | length }}</span>
                    </span>
                </div>
                <div class="progress-bar-container">
                    <div class="progress-bar" style="width: {{ 100 / steps | length }}%;"></div>
                </div>
                <div class="step-indicators">
                    {% for step in steps %}
                    <div class="step-indicator {% if loop.index == 1 %}active{% endif %}" data-step="{{ loop.index }}">
                        <div class="step-number">{{ loop.index }}</div>
                        <div class="step-title">{{ step.title }}</div>
                    </div>
                    {% endfor %}
                </div>
            </div>
            {% endif %}
            
            <div class="multistep-content">
                {% for step in steps %}
                <div class="step-panel" data-step="{{ loop.index }}" 
                     style="{% if loop.index != 1 %}display: none;{% endif %}">
                    <div class="step-header">
                        <h4>{{ step.title }}</h4>
                        {% if step.description %}
                        <p class="text-muted">{{ step.description }}</p>
                        {% endif %}
                    </div>
                    
                    <div class="step-content">
                        <!-- Step fields would be rendered here -->
                        <div class="step-fields" data-step-fields="{{ loop.index }}">
                            <!-- Dynamic content based on step configuration -->
                        </div>
                    </div>
                </div>
                {% endfor %}
            </div>
            
            <div class="multistep-navigation">
                <button type="button" class="btn btn-secondary" id="prev-btn-{{ widget_id }}" 
                        style="display: none;">
                    <i class="fa fa-arrow-left"></i> {{ _('Previous') }}
                </button>
                
                <div class="nav-center">
                    <button type="button" class="btn btn-outline-secondary" id="save-draft-{{ widget_id }}">
                        <i class="fa fa-save"></i> {{ _('Save Draft') }}
                    </button>
                </div>
                
                <button type="button" class="btn btn-primary" id="next-btn-{{ widget_id }}">
                    {{ _('Next') }} <i class="fa fa-arrow-right"></i>
                </button>
            </div>
            
            <input type="hidden" id="{{ widget_id }}" name="{{ field.name }}" value="{{ field.data or '' }}">
        </div>
        
        <style>
        .multistep-form-container {
            border: 1px solid #dee2e6;
            border-radius: 8px;
            background: white;
            overflow: hidden;
        }
        
        .multistep-progress {
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            padding: 1.5rem;
        }
        
        .progress-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }
        
        .progress-header h5 {
            margin: 0;
        }
        
        .step-counter {
            font-size: 0.875rem;
            color: #6c757d;
        }
        
        .progress-bar-container {
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            margin-bottom: 1rem;
            overflow: hidden;
        }
        
        .progress-bar {
            height: 100%;
            background: linear-gradient(to right, #0d6efd, #198754);
            transition: width 0.3s ease;
        }
        
        .step-indicators {
            display: flex;
            justify-content: space-between;
            gap: 1rem;
        }
        
        .step-indicator {
            flex: 1;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
        }
        
        .step-indicator.completed .step-number {
            background: #198754;
            color: white;
        }
        
        .step-indicator.active .step-number {
            background: #0d6efd;
            color: white;
        }
        
        .step-number {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            background: #e9ecef;
            color: #6c757d;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            margin: 0 auto 0.5rem;
            transition: all 0.3s ease;
        }
        
        .step-title {
            font-size: 0.875rem;
            color: #6c757d;
            font-weight: 500;
        }
        
        .step-indicator.active .step-title,
        .step-indicator.completed .step-title {
            color: #212529;
        }
        
        .multistep-content {
            padding: 2rem;
            min-height: 400px;
        }
        
        .step-panel {
            animation: fadeIn 0.3s ease;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateX(20px); }
            to { opacity: 1; transform: translateX(0); }
        }
        
        .step-header {
            margin-bottom: 2rem;
        }
        
        .step-header h4 {
            margin: 0 0 0.5rem 0;
        }
        
        .multistep-navigation {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1.5rem;
            border-top: 1px solid #dee2e6;
            background: #f8f9fa;
        }
        
        .nav-center {
            flex: 1;
            text-align: center;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="multistep-form"]');
            const hiddenInput = document.getElementById('{{ widget_id }}');
            const prevBtn = document.getElementById('prev-btn-{{ widget_id }}');
            const nextBtn = document.getElementById('next-btn-{{ widget_id }}');
            const saveDraftBtn = document.getElementById('save-draft-{{ widget_id }}');
            
            const steps = {{ steps | tojson }};
            let currentStep = 1;
            let formData = {};
            
            // Initialize multi-step form
            function initializeForm() {
                updateNavigation();
                loadSavedData();
                
                // Add event listeners
                prevBtn.addEventListener('click', previousStep);
                nextBtn.addEventListener('click', nextStep);
                saveDraftBtn.addEventListener('click', saveDraft);
                
                // Step indicator click handlers
                container.querySelectorAll('.step-indicator').forEach((indicator, index) => {
                    indicator.addEventListener('click', () => {
                        if (!{{ linear_navigation | tojson }} || index + 1 <= getCompletedSteps()) {
                            goToStep(index + 1);
                        }
                    });
                });
            }
            
            // Navigate to specific step
            function goToStep(stepNumber) {
                if (stepNumber < 1 || stepNumber > steps.length) return;
                
                // Validate current step before moving
                if (stepNumber > currentStep && !validateCurrentStep()) {
                    return;
                }
                
                // Hide current step
                const currentPanel = container.querySelector(`[data-step="${currentStep}"]`);
                if (currentPanel) currentPanel.style.display = 'none';
                
                // Show new step
                const newPanel = container.querySelector(`[data-step="${stepNumber}"]`);
                if (newPanel) newPanel.style.display = 'block';
                
                // Update step indicators
                updateStepIndicators(stepNumber);
                
                // Update progress
                updateProgress(stepNumber);
                
                currentStep = stepNumber;
                updateNavigation();
                
                // Save progress
                if ({{ save_progress | tojson }}) {
                    saveProgress();
                }
            }
            
            // Previous step
            function previousStep() {
                if (currentStep > 1) {
                    goToStep(currentStep - 1);
                }
            }
            
            // Next step
            function nextStep() {
                if (currentStep < steps.length) {
                    if (validateCurrentStep()) {
                        saveStepData();
                        goToStep(currentStep + 1);
                    }
                } else {
                    // Final step - submit form
                    if (validateCurrentStep()) {
                        saveStepData();
                        submitForm();
                    }
                }
            }
            
            // Validate current step
            function validateCurrentStep() {
                const currentPanel = container.querySelector(`[data-step="${currentStep}"]`);
                if (!currentPanel) return true;
                
                const requiredFields = currentPanel.querySelectorAll('[required]');
                let isValid = true;
                
                requiredFields.forEach(field => {
                    if (!field.value.trim()) {
                        field.classList.add('is-invalid');
                        isValid = false;
                    } else {
                        field.classList.remove('is-invalid');
                    }
                });
                
                return isValid;
            }
            
            // Save current step data
            function saveStepData() {
                const currentPanel = container.querySelector(`[data-step="${currentStep}"]`);
                if (!currentPanel) return;
                
                const stepData = {};
                const fields = currentPanel.querySelectorAll('input, select, textarea');
                
                fields.forEach(field => {
                    if (field.type === 'checkbox' || field.type === 'radio') {
                        if (field.checked) {
                            stepData[field.name] = field.value;
                        }
                    } else {
                        stepData[field.name] = field.value;
                    }
                });
                
                formData[`step_${currentStep}`] = stepData;
                hiddenInput.value = JSON.stringify(formData);
            }
            
            // Update step indicators
            function updateStepIndicators(activeStep) {
                container.querySelectorAll('.step-indicator').forEach((indicator, index) => {
                    const stepNum = index + 1;
                    indicator.classList.remove('active', 'completed');
                    
                    if (stepNum === activeStep) {
                        indicator.classList.add('active');
                    } else if (stepNum < activeStep) {
                        indicator.classList.add('completed');
                    }
                });
            }
            
            // Update progress bar
            function updateProgress(stepNumber) {
                const progressBar = container.querySelector('.progress-bar');
                const currentStepSpan = container.querySelector('.current-step');
                
                if (progressBar) {
                    const progressPercent = (stepNumber / steps.length) * 100;
                    progressBar.style.width = progressPercent + '%';
                }
                
                if (currentStepSpan) {
                    currentStepSpan.textContent = stepNumber;
                }
            }
            
            // Update navigation buttons
            function updateNavigation() {
                prevBtn.style.display = currentStep > 1 ? 'inline-block' : 'none';
                
                if (currentStep === steps.length) {
                    nextBtn.innerHTML = '<i class="fa fa-check"></i> {{ _("Submit") }}';
                    nextBtn.classList.remove('btn-primary');
                    nextBtn.classList.add('btn-success');
                } else {
                    nextBtn.innerHTML = '{{ _("Next") }} <i class="fa fa-arrow-right"></i>';
                    nextBtn.classList.remove('btn-success');
                    nextBtn.classList.add('btn-primary');
                }
            }
            
            // Get completed steps count
            function getCompletedSteps() {
                return Object.keys(formData).length;
            }
            
            // Save draft
            function saveDraft() {
                saveStepData();
                if ({{ save_progress | tojson }}) {
                    saveProgress();
                }
                alert('{{ _("Draft saved successfully") }}');
            }
            
            // Save progress to localStorage
            function saveProgress() {
                const progressData = {
                    currentStep,
                    formData,
                    timestamp: new Date().toISOString()
                };
                localStorage.setItem('multistep_form_{{ widget_id }}', JSON.stringify(progressData));
            }
            
            // Load saved data
            function loadSavedData() {
                if ({{ save_progress | tojson }}) {
                    const savedData = localStorage.getItem('multistep_form_{{ widget_id }}');
                    if (savedData) {
                        try {
                            const progress = JSON.parse(savedData);
                            formData = progress.formData || {};
                            // Optionally restore to saved step
                            // currentStep = progress.currentStep || 1;
                        } catch (e) {
                            console.warn('Could not load saved form data:', e);
                        }
                    }
                }
            }
            
            // Submit final form
            function submitForm() {
                // All data is already in hiddenInput.value
                const form = container.closest('form');
                if (form) {
                    // Trigger form submission
                    form.dispatchEvent(new Event('submit'));
                } else {
                    console.log('Form submission data:', formData);
                    alert('{{ _("Form submitted successfully") }}');
                }
            }
            
            // Initialize
            initializeForm();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            steps=self.steps,
            show_progress=self.show_progress,
            save_progress=self.save_progress,
            linear_navigation=self.linear_navigation,
            _=gettext
        ))


class DataTableWidget(Input):
    """
    Advanced data table widget with inline editing capabilities.
    
    Features:
    - Inline cell editing
    - Row add/remove functionality
    - Column sorting and filtering
    - Data validation
    - Export functionality
    - Custom cell renderers
    - Bulk operations
    - Responsive design
    """
    
    input_type = 'hidden'
    
    def __init__(self,
                 columns: List[Dict],
                 editable: bool = True,
                 sortable: bool = True,
                 filterable: bool = True,
                 paginated: bool = True,
                 page_size: int = 10):
        """
        Initialize the data table widget.
        
        Args:
            columns: Column definitions
            editable: Enable inline editing
            sortable: Enable column sorting
            filterable: Enable column filtering
            paginated: Enable pagination
            page_size: Number of rows per page
        """
        self.columns = columns
        self.editable = editable
        self.sortable = sortable
        self.filterable = filterable
        self.paginated = paginated
        self.page_size = page_size
        
    def __call__(self, field, **kwargs):
        """Render the data table widget."""
        widget_id = kwargs.get('id', f'datatable_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="datatable-container" data-widget="datatable">
            <div class="datatable-toolbar">
                <div class="toolbar-left">
                    <h6>{{ _('Data Table') }}</h6>
                    {% if editable %}
                    <button type="button" class="btn btn-primary btn-sm" data-action="add-row">
                        <i class="fa fa-plus"></i> {{ _('Add Row') }}
                    </button>
                    <button type="button" class="btn btn-danger btn-sm" data-action="delete-selected" disabled>
                        <i class="fa fa-trash"></i> {{ _('Delete Selected') }}
                    </button>
                    {% endif %}
                </div>
                
                <div class="toolbar-right">
                    <button type="button" class="btn btn-outline-secondary btn-sm" data-action="export">
                        <i class="fa fa-download"></i> {{ _('Export') }}
                    </button>
                    <button type="button" class="btn btn-outline-info btn-sm" data-action="refresh">
                        <i class="fa fa-refresh"></i> {{ _('Refresh') }}
                    </button>
                </div>
            </div>
            
            {% if filterable %}
            <div class="datatable-filters">
                {% for column in columns %}
                {% if column.filterable != false %}
                <div class="filter-group">
                    <label>{{ column.title }}:</label>
                    <input type="text" class="form-control form-control-sm" 
                           data-filter="{{ column.key }}" placeholder="{{ _('Filter...') }}">
                </div>
                {% endif %}
                {% endfor %}
            </div>
            {% endif %}
            
            <div class="table-responsive">
                <table class="table table-striped table-hover datatable" id="table-{{ widget_id }}">
                    <thead>
                        <tr>
                            {% if editable %}
                            <th width="40">
                                <input type="checkbox" class="select-all-checkbox">
                            </th>
                            {% endif %}
                            {% for column in columns %}
                            <th data-column="{{ column.key }}" 
                                {% if sortable and column.sortable != false %}class="sortable"{% endif %}>
                                {{ column.title }}
                                {% if sortable and column.sortable != false %}
                                <i class="fa fa-sort sort-icon"></i>
                                {% endif %}
                            </th>
                            {% endfor %}
                            {% if editable %}
                            <th width="100">{{ _('Actions') }}</th>
                            {% endif %}
                        </tr>
                    </thead>
                    <tbody id="tbody-{{ widget_id }}">
                        <!-- Table rows will be populated here -->
                    </tbody>
                </table>
            </div>
            
            {% if paginated %}
            <div class="datatable-pagination">
                <div class="pagination-info">
                    {{ _('Showing') }} <span class="current-range">1-{{ page_size }}</span> 
                    {{ _('of') }} <span class="total-records">0</span> {{ _('records') }}
                </div>
                <nav>
                    <ul class="pagination pagination-sm">
                        <li class="page-item disabled" data-page="prev">
                            <a class="page-link" href="#"><i class="fa fa-chevron-left"></i></a>
                        </li>
                        <!-- Page numbers will be populated here -->
                        <li class="page-item" data-page="next">
                            <a class="page-link" href="#"><i class="fa fa-chevron-right"></i></a>
                        </li>
                    </ul>
                </nav>
            </div>
            {% endif %}
            
            <input type="hidden" id="{{ widget_id }}" name="{{ field.name }}" value="{{ field.data or '[]' }}">
        </div>
        
        <style>
        .datatable-container {
            border: 1px solid #dee2e6;
            border-radius: 8px;
            background: white;
        }
        
        .datatable-toolbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem;
            border-bottom: 1px solid #dee2e6;
            background: #f8f9fa;
        }
        
        .toolbar-left, .toolbar-right {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .toolbar-left h6 {
            margin: 0 1rem 0 0;
        }
        
        .datatable-filters {
            display: flex;
            flex-wrap: wrap;
            gap: 1rem;
            padding: 1rem;
            border-bottom: 1px solid #dee2e6;
            background: #f8f9fa;
        }
        
        .filter-group {
            display: flex;
            flex-direction: column;
            min-width: 150px;
        }
        
        .filter-group label {
            font-size: 0.875rem;
            margin-bottom: 0.25rem;
        }
        
        .datatable {
            margin: 0;
        }
        
        .sortable {
            cursor: pointer;
            user-select: none;
        }
        
        .sortable:hover {
            background-color: #f8f9fa;
        }
        
        .sort-icon {
            margin-left: 0.5rem;
            color: #6c757d;
        }
        
        .sortable.sort-asc .sort-icon::before {
            content: "\\f0de"; /* fa-sort-up */
        }
        
        .sortable.sort-desc .sort-icon::before {
            content: "\\f0dd"; /* fa-sort-down */
        }
        
        .editable-cell {
            cursor: pointer;
            position: relative;
        }
        
        .editable-cell:hover {
            background-color: #f8f9fa;
        }
        
        .editable-cell.editing {
            padding: 0;
        }
        
        .cell-editor {
            width: 100%;
            border: none;
            padding: 0.5rem;
            background: white;
            border: 2px solid #0d6efd;
        }
        
        .datatable-pagination {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem;
            border-top: 1px solid #dee2e6;
            background: #f8f9fa;
        }
        
        .pagination-info {
            font-size: 0.875rem;
            color: #6c757d;
        }
        
        .table-responsive {
            max-height: 500px;
            overflow-y: auto;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="datatable"]');
            const table = document.getElementById('table-{{ widget_id }}');
            const tbody = document.getElementById('tbody-{{ widget_id }}');
            const hiddenInput = document.getElementById('{{ widget_id }}');
            
            const columns = {{ columns | tojson }};
            let tableData = [];
            let filteredData = [];
            let currentPage = 1;
            let sortColumn = null;
            let sortDirection = 'asc';
            
            // Initialize table
            function initializeTable() {
                loadData();
                renderTable();
                bindEvents();
            }
            
            // Load existing data
            function loadData() {
                try {
                    tableData = JSON.parse(hiddenInput.value || '[]');
                } catch (e) {
                    tableData = [];
                }
                filteredData = [...tableData];
            }
            
            // Render table rows
            function renderTable() {
                tbody.innerHTML = '';
                
                const startIndex = (currentPage - 1) * {{ page_size }};
                const endIndex = startIndex + {{ page_size }};
                const pageData = filteredData.slice(startIndex, endIndex);
                
                pageData.forEach((row, index) => {
                    const tr = createTableRow(row, startIndex + index);
                    tbody.appendChild(tr);
                });
                
                updatePagination();
                updateRowSelection();
            }
            
            // Create table row
            function createTableRow(rowData, rowIndex) {
                const tr = document.createElement('tr');
                tr.dataset.index = rowIndex;
                
                let html = '';
                
                // Selection checkbox
                {% if editable %}
                html += '<td><input type="checkbox" class="row-checkbox" data-index="' + rowIndex + '"></td>';
                {% endif %}
                
                // Data columns
                columns.forEach(column => {
                    const cellValue = rowData[column.key] || '';
                    const cellClass = {{ editable | tojson }} && column.editable !== false ? 'editable-cell' : '';
                    html += `<td class="${cellClass}" data-column="${column.key}" data-index="${rowIndex}">${escapeHtml(cellValue)}</td>`;
                });
                
                // Actions column
                {% if editable %}
                html += `
                    <td>
                        <button type="button" class="btn btn-danger btn-sm" data-action="delete" data-index="${rowIndex}">
                            <i class="fa fa-trash"></i>
                        </button>
                    </td>
                `;
                {% endif %}
                
                tr.innerHTML = html;
                return tr;
            }
            
            // Escape HTML
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            
            // Add new row
            function addRow() {
                const newRow = {};
                columns.forEach(column => {
                    newRow[column.key] = '';
                });
                
                tableData.push(newRow);
                applyFilters();
                renderTable();
                saveData();
            }
            
            // Delete row
            function deleteRow(index) {
                if (confirm('{{ _("Are you sure you want to delete this row?") }}')) {
                    tableData.splice(index, 1);
                    applyFilters();
                    renderTable();
                    saveData();
                }
            }
            
            // Edit cell
            function editCell(cell) {
                if (cell.classList.contains('editing')) return;
                
                const currentValue = cell.textContent;
                const input = document.createElement('input');
                input.type = 'text';
                input.className = 'cell-editor';
                input.value = currentValue;
                
                cell.innerHTML = '';
                cell.appendChild(input);
                cell.classList.add('editing');
                input.focus();
                input.select();
                
                function finishEdit() {
                    const newValue = input.value;
                    const rowIndex = parseInt(cell.dataset.index);
                    const columnKey = cell.dataset.column;
                    
                    // Update data
                    if (tableData[rowIndex]) {
                        tableData[rowIndex][columnKey] = newValue;
                        saveData();
                    }
                    
                    // Update cell
                    cell.textContent = newValue;
                    cell.classList.remove('editing');
                }
                
                input.addEventListener('blur', finishEdit);
                input.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter') {
                        finishEdit();
                    } else if (e.key === 'Escape') {
                        cell.textContent = currentValue;
                        cell.classList.remove('editing');
                    }
                });
            }
            
            // Apply filters
            function applyFilters() {
                const filters = {};
                container.querySelectorAll('[data-filter]').forEach(input => {
                    if (input.value.trim()) {
                        filters[input.dataset.filter] = input.value.toLowerCase();
                    }
                });
                
                filteredData = tableData.filter(row => {
                    return Object.keys(filters).every(key => {
                        const cellValue = (row[key] || '').toString().toLowerCase();
                        return cellValue.includes(filters[key]);
                    });
                });
                
                currentPage = 1;
                renderTable();
            }
            
            // Sort data
            function sortData(columnKey) {
                if (sortColumn === columnKey) {
                    sortDirection = sortDirection === 'asc' ? 'desc' : 'asc';
                } else {
                    sortColumn = columnKey;
                    sortDirection = 'asc';
                }
                
                filteredData.sort((a, b) => {
                    const aValue = a[columnKey] || '';
                    const bValue = b[columnKey] || '';
                    
                    const comparison = aValue.toString().localeCompare(bValue.toString(), undefined, { numeric: true });
                    return sortDirection === 'asc' ? comparison : -comparison;
                });
                
                // Update sort indicators
                container.querySelectorAll('.sortable').forEach(th => {
                    th.classList.remove('sort-asc', 'sort-desc');
                });
                
                const sortedHeader = container.querySelector(`[data-column="${columnKey}"]`);
                if (sortedHeader) {
                    sortedHeader.classList.add(`sort-${sortDirection}`);
                }
                
                renderTable();
            }
            
            // Update pagination
            function updatePagination() {
                {% if paginated %}
                const totalRecords = filteredData.length;
                const totalPages = Math.ceil(totalRecords / {{ page_size }});
                const startRecord = (currentPage - 1) * {{ page_size }} + 1;
                const endRecord = Math.min(currentPage * {{ page_size }}, totalRecords);
                
                // Update info
                container.querySelector('.current-range').textContent = `${startRecord}-${endRecord}`;
                container.querySelector('.total-records').textContent = totalRecords;
                
                // Update pagination buttons
                const pagination = container.querySelector('.pagination');
                const prevBtn = pagination.querySelector('[data-page="prev"]');
                const nextBtn = pagination.querySelector('[data-page="next"]');
                
                prevBtn.classList.toggle('disabled', currentPage === 1);
                nextBtn.classList.toggle('disabled', currentPage === totalPages);
                {% endif %}
            }
            
            // Update row selection
            function updateRowSelection() {
                const selectAllCheckbox = container.querySelector('.select-all-checkbox');
                const rowCheckboxes = container.querySelectorAll('.row-checkbox');
                const deleteSelectedBtn = container.querySelector('[data-action="delete-selected"]');
                
                if (selectAllCheckbox && rowCheckboxes.length > 0) {
                    const checkedCount = Array.from(rowCheckboxes).filter(cb => cb.checked).length;
                    selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < rowCheckboxes.length;
                    selectAllCheckbox.checked = checkedCount === rowCheckboxes.length;
                    
                    if (deleteSelectedBtn) {
                        deleteSelectedBtn.disabled = checkedCount === 0;
                    }
                }
            }
            
            // Save data
            function saveData() {
                hiddenInput.value = JSON.stringify(tableData);
            }
            
            // Bind events
            function bindEvents() {
                // Toolbar actions
                container.addEventListener('click', (e) => {
                    const action = e.target.closest('[data-action]')?.dataset.action;
                    
                    switch (action) {
                        case 'add-row':
                            addRow();
                            break;
                        case 'delete':
                            const index = parseInt(e.target.closest('[data-action]').dataset.index);
                            deleteRow(index);
                            break;
                        case 'delete-selected':
                            deleteSelectedRows();
                            break;
                        case 'export':
                            exportData();
                            break;
                        case 'refresh':
                            renderTable();
                            break;
                    }
                });
                
                // Cell editing
                tbody.addEventListener('dblclick', (e) => {
                    const cell = e.target.closest('.editable-cell');
                    if (cell) {
                        editCell(cell);
                    }
                });
                
                // Column sorting
                container.addEventListener('click', (e) => {
                    const sortableHeader = e.target.closest('.sortable');
                    if (sortableHeader) {
                        sortData(sortableHeader.dataset.column);
                    }
                });
                
                // Filtering
                container.addEventListener('input', (e) => {
                    if (e.target.dataset.filter) {
                        applyFilters();
                    }
                });
                
                // Row selection
                container.addEventListener('change', (e) => {
                    if (e.target.classList.contains('select-all-checkbox')) {
                        const checked = e.target.checked;
                        container.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = checked);
                        updateRowSelection();
                    } else if (e.target.classList.contains('row-checkbox')) {
                        updateRowSelection();
                    }
                });
            }
            
            // Delete selected rows
            function deleteSelectedRows() {
                const selectedIndices = Array.from(container.querySelectorAll('.row-checkbox:checked'))
                    .map(cb => parseInt(cb.dataset.index))
                    .sort((a, b) => b - a); // Sort descending to remove from end first
                
                if (selectedIndices.length > 0 && confirm(`{{ _("Delete") }} ${selectedIndices.length} {{ _("selected rows?") }}`)) {
                    selectedIndices.forEach(index => {
                        tableData.splice(index, 1);
                    });
                    applyFilters();
                    renderTable();
                    saveData();
                }
            }
            
            // Export data
            function exportData() {
                const csv = convertToCSV(filteredData);
                downloadCSV(csv, 'table-data.csv');
            }
            
            // Convert to CSV
            function convertToCSV(data) {
                const headers = columns.map(col => col.title).join(',');
                const rows = data.map(row => 
                    columns.map(col => `"${(row[col.key] || '').toString().replace(/"/g, '""')}"`).join(',')
                ).join('\\n');
                return headers + '\\n' + rows;
            }
            
            // Download CSV
            function downloadCSV(csv, filename) {
                const blob = new Blob([csv], { type: 'text/csv' });
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = filename;
                a.click();
                window.URL.revokeObjectURL(url);
            }
            
            // Initialize
            initializeTable();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            columns=self.columns,
            editable=self.editable,
            sortable=self.sortable,
            filterable=self.filterable,
            paginated=self.paginated,
            page_size=self.page_size,
            _=gettext
        ))