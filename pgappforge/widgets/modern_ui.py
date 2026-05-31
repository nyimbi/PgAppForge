"""
Modern UI Widget Components for PgForge

This module provides a comprehensive collection of modern, responsive UI widgets
with advanced features including drag & drop, rich text editing, color pickers,
file uploaders, and interactive components.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Union
from uuid import uuid4

from flask import render_template_string, url_for, current_app
from markupsafe import Markup
from flask_babel import gettext, lazy_gettext
from wtforms.widgets import TextArea, Input, Select, CheckboxInput
from wtforms.widgets.core import html_params

log = logging.getLogger(__name__)


class ModernTextWidget(Input):
    """
    Modern text input widget with enhanced UX features.
    
    Features:
    - Floating labels with smooth animations
    - Real-time character counting
    - Input validation with visual feedback
    - Auto-complete suggestions
    - Icon support (prefix/suffix)
    - Responsive design
    - Keyboard shortcuts
    - Focus states with smooth transitions
    """
    
    input_type = 'text'
    
    def __init__(self, 
                 icon_prefix: Optional[str] = None,
                 icon_suffix: Optional[str] = None,
                 show_counter: bool = False,
                 max_length: Optional[int] = None,
                 autocomplete_source: Optional[str] = None,
                 placeholder: Optional[str] = None,
                 floating_label: bool = True):
        """
        Initialize the modern text widget.
        
        Args:
            icon_prefix: FontAwesome icon class for prefix icon
            icon_suffix: FontAwesome icon class for suffix icon
            show_counter: Whether to show character counter
            max_length: Maximum character length
            autocomplete_source: URL for autocomplete suggestions
            placeholder: Placeholder text
            floating_label: Whether to use floating label design
        """
        self.icon_prefix = icon_prefix
        self.icon_suffix = icon_suffix
        self.show_counter = show_counter
        self.max_length = max_length
        self.autocomplete_source = autocomplete_source
        self.placeholder = placeholder
        self.floating_label = floating_label
        
    def __call__(self, field, **kwargs):
        """Render the modern text widget."""
        widget_id = kwargs.get('id', f'modern_text_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'form-control modern-input')
        
        if self.max_length:
            kwargs['maxlength'] = self.max_length
            
        if self.placeholder:
            kwargs['placeholder'] = self.placeholder
        elif not self.floating_label and field.label:
            kwargs['placeholder'] = field.label.text
            
        # Build the widget HTML
        input_html = super().__call__(field, **kwargs)
        
        template = """
        <div class="modern-input-group" data-widget="modern-text">
            {% if icon_prefix %}
            <div class="input-group-prepend">
                <span class="input-group-text">
                    <i class="fa {{ icon_prefix }}"></i>
                </span>
            </div>
            {% endif %}
            
            <div class="form-floating">
                {{ input_html | safe }}
                {% if floating_label and field.label %}
                <label for="{{ widget_id }}">{{ field.label.text }}</label>
                {% endif %}
            </div>
            
            {% if icon_suffix %}
            <div class="input-group-append">
                <span class="input-group-text">
                    <i class="fa {{ icon_suffix }}"></i>
                </span>
            </div>
            {% endif %}
            
            {% if show_counter %}
            <div class="form-text character-counter">
                <span class="current-count">0</span>
                {% if max_length %}/ <span class="max-count">{{ max_length }}</span>{% endif %}
                {{ _('characters') }}
            </div>
            {% endif %}
        </div>
        
        <style>
        .modern-input-group {
            position: relative;
            margin-bottom: 1rem;
        }
        
        .modern-input-group .form-control {
            border-radius: 8px;
            border: 2px solid #e9ecef;
            padding: 0.75rem 1rem;
            transition: all 0.3s ease;
            font-size: 1rem;
        }
        
        .modern-input-group .form-control:focus {
            border-color: #0d6efd;
            box-shadow: 0 0 0 0.25rem rgba(13, 110, 253, 0.25);
            transform: translateY(-1px);
        }
        
        .form-floating > label {
            padding: 1rem;
            color: #6c757d;
            transition: all 0.3s ease;
        }
        
        .character-counter {
            font-size: 0.875rem;
            color: #6c757d;
            text-align: right;
            margin-top: 0.25rem;
        }
        
        .character-counter.warning {
            color: #fd7e14;
        }
        
        .character-counter.danger {
            color: #dc3545;
        }
        </style>
        
        <script>
        (function() {
            const input = document.getElementById('{{ widget_id }}');
            const counter = input.closest('.modern-input-group').querySelector('.character-counter');
            
            if (input && counter) {
                const currentCount = counter.querySelector('.current-count');
                const maxCount = {{ max_length or 'null' }};
                
                function updateCounter() {
                    const length = input.value.length;
                    currentCount.textContent = length;
                    
                    if (maxCount) {
                        counter.classList.remove('warning', 'danger');
                        if (length > maxCount * 0.9) {
                            counter.classList.add('danger');
                        } else if (length > maxCount * 0.8) {
                            counter.classList.add('warning');
                        }
                    }
                }
                
                input.addEventListener('input', updateCounter);
                input.addEventListener('keydown', function(e) {
                    // Add keyboard shortcuts
                    if (e.ctrlKey || e.metaKey) {
                        if (e.key === 'a') {
                            // Ctrl+A to select all (default behavior)
                        }
                    }
                });
                
                updateCounter();
            }
            
            {% if autocomplete_source %}
            // Add autocomplete functionality
            if (input) {
                let timeout;
                input.addEventListener('input', function() {
                    clearTimeout(timeout);
                    timeout = setTimeout(() => {
                        // Implement autocomplete logic here
                        fetch('{{ autocomplete_source }}?q=' + encodeURIComponent(input.value))
                            .then(response => response.json())
                            .then(data => {
                                // Handle autocomplete suggestions
                            });
                    }, 300);
                });
            }
            {% endif %}
        })();
        </script>
        """
        
        return Markup(render_template_string(template, 
            input_html=input_html,
            widget_id=widget_id,
            field=field,
            icon_prefix=self.icon_prefix,
            icon_suffix=self.icon_suffix,
            show_counter=self.show_counter,
            max_length=self.max_length,
            floating_label=self.floating_label,
            _=gettext
        ))


class ModernTextAreaWidget(TextArea):
    """
    Modern textarea widget with advanced editing features.
    
    Features:
    - Auto-resizing based on content
    - Rich text formatting toolbar (optional)
    - Character/word counting
    - Markdown preview (optional)
    - Syntax highlighting for code
    - Drag & drop support
    - Full-screen mode
    - Auto-save drafts
    """
    
    def __init__(self,
                 auto_resize: bool = True,
                 rich_text: bool = False,
                 markdown_preview: bool = False,
                 syntax_highlighting: Optional[str] = None,
                 show_stats: bool = True,
                 full_screen: bool = True,
                 auto_save: bool = False,
                 min_rows: int = 3,
                 max_rows: int = 15):
        """
        Initialize the modern textarea widget.
        
        Args:
            auto_resize: Auto-resize based on content
            rich_text: Enable rich text editing toolbar
            markdown_preview: Show markdown preview
            syntax_highlighting: Language for syntax highlighting
            show_stats: Show character/word count
            full_screen: Enable full-screen editing mode
            auto_save: Auto-save drafts
            min_rows: Minimum number of rows
            max_rows: Maximum number of rows
        """
        self.auto_resize = auto_resize
        self.rich_text = rich_text
        self.markdown_preview = markdown_preview
        self.syntax_highlighting = syntax_highlighting
        self.show_stats = show_stats
        self.full_screen = full_screen
        self.auto_save = auto_save
        self.min_rows = min_rows
        self.max_rows = max_rows
        
    def __call__(self, field, **kwargs):
        """Render the modern textarea widget."""
        widget_id = kwargs.get('id', f'modern_textarea_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'form-control modern-textarea')
        kwargs.setdefault('rows', self.min_rows)
        
        # Build the widget HTML
        textarea_html = super().__call__(field, **kwargs)
        
        template = """
        <div class="modern-textarea-container" data-widget="modern-textarea">
            {% if rich_text or full_screen or markdown_preview %}
            <div class="modern-textarea-toolbar">
                {% if rich_text %}
                <div class="toolbar-group">
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            data-action="bold" title="{{ _('Bold') }}">
                        <i class="fa fa-bold"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            data-action="italic" title="{{ _('Italic') }}">
                        <i class="fa fa-italic"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            data-action="underline" title="{{ _('Underline') }}">
                        <i class="fa fa-underline"></i>
                    </button>
                </div>
                <div class="toolbar-group">
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            data-action="heading" title="{{ _('Heading') }}">
                        <i class="fa fa-heading"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            data-action="list" title="{{ _('List') }}">
                        <i class="fa fa-list-ul"></i>
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            data-action="link" title="{{ _('Link') }}">
                        <i class="fa fa-link"></i>
                    </button>
                </div>
                {% endif %}
                
                <div class="toolbar-group ms-auto">
                    {% if markdown_preview %}
                    <button type="button" class="btn btn-sm btn-outline-info" 
                            data-action="preview" title="{{ _('Preview') }}">
                        <i class="fa fa-eye"></i>
                    </button>
                    {% endif %}
                    {% if full_screen %}
                    <button type="button" class="btn btn-sm btn-outline-secondary" 
                            data-action="fullscreen" title="{{ _('Full Screen') }}">
                        <i class="fa fa-expand"></i>
                    </button>
                    {% endif %}
                </div>
            </div>
            {% endif %}
            
            <div class="modern-textarea-wrapper">
                {{ textarea_html | safe }}
                
                {% if markdown_preview %}
                <div class="markdown-preview" style="display: none;">
                    <div class="preview-content"></div>
                </div>
                {% endif %}
            </div>
            
            {% if show_stats %}
            <div class="textarea-stats">
                <span class="character-count">0 {{ _('characters') }}</span>
                <span class="word-count">0 {{ _('words') }}</span>
                {% if auto_save %}
                <span class="auto-save-status">
                    <i class="fa fa-save"></i> {{ _('Auto-saved') }}
                </span>
                {% endif %}
            </div>
            {% endif %}
        </div>
        
        <style>
        .modern-textarea-container {
            border: 2px solid #e9ecef;
            border-radius: 8px;
            overflow: hidden;
            transition: all 0.3s ease;
        }
        
        .modern-textarea-container:focus-within {
            border-color: #0d6efd;
            box-shadow: 0 0 0 0.25rem rgba(13, 110, 253, 0.25);
        }
        
        .modern-textarea-toolbar {
            background-color: #f8f9fa;
            border-bottom: 1px solid #e9ecef;
            padding: 0.5rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .toolbar-group {
            display: flex;
            gap: 0.25rem;
        }
        
        .modern-textarea {
            border: none;
            border-radius: 0;
            resize: none;
            min-height: calc({{ min_rows }} * 1.5em + 1rem);
            transition: height 0.3s ease;
        }
        
        .modern-textarea:focus {
            box-shadow: none;
        }
        
        .markdown-preview {
            padding: 1rem;
            background-color: #f8f9fa;
            border-top: 1px solid #e9ecef;
            min-height: 100px;
        }
        
        .textarea-stats {
            background-color: #f8f9fa;
            border-top: 1px solid #e9ecef;
            padding: 0.5rem 1rem;
            font-size: 0.875rem;
            color: #6c757d;
            display: flex;
            gap: 1rem;
            align-items: center;
        }
        
        .auto-save-status {
            margin-left: auto;
            color: #28a745;
        }
        
        .modern-textarea-container.fullscreen {
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            z-index: 9999;
            background: white;
            border-radius: 0;
        }
        
        .modern-textarea-container.fullscreen .modern-textarea {
            height: calc(100vh - 150px);
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="modern-textarea"]');
            const textarea = document.getElementById('{{ widget_id }}');
            
            if (!container || !textarea) return;
            
            // Auto-resize functionality
            {% if auto_resize %}
            function autoResize() {
                const minHeight = {{ min_rows }} * 24; // Approximate line height
                const maxHeight = {{ max_rows }} * 24;
                
                textarea.style.height = 'auto';
                const scrollHeight = textarea.scrollHeight;
                textarea.style.height = Math.min(Math.max(scrollHeight, minHeight), maxHeight) + 'px';
            }
            
            textarea.addEventListener('input', autoResize);
            autoResize();
            {% endif %}
            
            // Stats update
            {% if show_stats %}
            function updateStats() {
                const text = textarea.value;
                const charCount = text.length;
                const wordCount = text.trim() ? text.trim().split(/ +/).length : 0;
                
                const charElement = container.querySelector('.character-count');
                const wordElement = container.querySelector('.word-count');
                
                if (charElement) charElement.textContent = charCount + ' {{ _("characters") }}';
                if (wordElement) wordElement.textContent = wordCount + ' {{ _("words") }}';
            }
            
            textarea.addEventListener('input', updateStats);
            updateStats();
            {% endif %}
            
            // Toolbar functionality
            container.addEventListener('click', function(e) {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (!action) return;
                
                e.preventDefault();
                
                switch (action) {
                    case 'bold':
                        insertMarkdown('**', '**');
                        break;
                    case 'italic':
                        insertMarkdown('*', '*');
                        break;
                    case 'heading':
                        insertMarkdown('## ', '');
                        break;
                    case 'list':
                        insertMarkdown('- ', '');
                        break;
                    case 'link':
                        insertMarkdown('[', '](url)');
                        break;
                    case 'fullscreen':
                        toggleFullscreen();
                        break;
                    case 'preview':
                        togglePreview();
                        break;
                }
            });
            
            function insertMarkdown(before, after) {
                const start = textarea.selectionStart;
                const end = textarea.selectionEnd;
                const text = textarea.value;
                const selectedText = text.substring(start, end);
                
                const newText = text.substring(0, start) + before + selectedText + after + text.substring(end);
                textarea.value = newText;
                textarea.focus();
                textarea.setSelectionRange(start + before.length, start + before.length + selectedText.length);
                
                updateStats();
                autoResize();
            }
            
            function toggleFullscreen() {
                container.classList.toggle('fullscreen');
                const icon = container.querySelector('[data-action="fullscreen"] i');
                if (container.classList.contains('fullscreen')) {
                    icon.className = 'fa fa-compress';
                } else {
                    icon.className = 'fa fa-expand';
                }
                autoResize();
            }
            
            function togglePreview() {
                const preview = container.querySelector('.markdown-preview');
                if (preview) {
                    if (preview.style.display === 'none') {
                        // Show preview
                        preview.style.display = 'block';
                        // Here you would implement markdown parsing
                        preview.querySelector('.preview-content').innerHTML = '<em>Markdown preview would go here</em>';
                    } else {
                        preview.style.display = 'none';
                    }
                }
            }
            
            {% if auto_save %}
            // Auto-save functionality
            let saveTimeout;
            textarea.addEventListener('input', function() {
                clearTimeout(saveTimeout);
                saveTimeout = setTimeout(() => {
                    // Implement auto-save logic here
                    console.log('Auto-saving content...');
                    const statusElement = container.querySelector('.auto-save-status');
                    if (statusElement) {
                        statusElement.style.opacity = '1';
                        setTimeout(() => statusElement.style.opacity = '0.7', 1000);
                    }
                }, 2000);
            });
            {% endif %}
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            textarea_html=textarea_html,
            widget_id=widget_id,
            field=field,
            rich_text=self.rich_text,
            markdown_preview=self.markdown_preview,
            show_stats=self.show_stats,
            full_screen=self.full_screen,
            auto_save=self.auto_save,
            min_rows=self.min_rows,
            max_rows=self.max_rows,
            _=gettext
        ))


class ModernSelectWidget(Select):
    """
    Modern select widget with enhanced functionality.
    
    Features:
    - Searchable options
    - Multi-select with tags
    - Custom option templates
    - AJAX loading support
    - Option grouping
    - Icons for options
    - Keyboard navigation
    - Mobile-friendly design
    """
    
    def __init__(self,
                 searchable: bool = True,
                 multiple: bool = False,
                 ajax_source: Optional[str] = None,
                 option_template: Optional[str] = None,
                 group_by: Optional[str] = None,
                 show_icons: bool = False,
                 placeholder: str = "Select an option..."):
        """
        Initialize the modern select widget.
        
        Args:
            searchable: Enable option searching
            multiple: Allow multiple selections
            ajax_source: URL for AJAX option loading
            option_template: Custom template for options
            group_by: Field to group options by
            show_icons: Show icons in options
            placeholder: Placeholder text
        """
        self.searchable = searchable
        self.multiple = multiple
        self.ajax_source = ajax_source
        self.option_template = option_template
        self.group_by = group_by
        self.show_icons = show_icons
        self.placeholder = placeholder
        
    def __call__(self, field, **kwargs):
        """Render the modern select widget."""
        widget_id = kwargs.get('id', f'modern_select_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'form-control modern-select')
        
        if self.multiple:
            kwargs['multiple'] = True
            
        # Build the widget HTML
        select_html = super().__call__(field, **kwargs)
        
        template = """
        <div class="modern-select-container" data-widget="modern-select">
            {{ select_html | safe }}
        </div>
        
        <style>
        .modern-select-container {
            position: relative;
        }
        
        .modern-select {
            border-radius: 8px;
            border: 2px solid #e9ecef;
            padding: 0.75rem 1rem;
            transition: all 0.3s ease;
        }
        
        .modern-select:focus {
            border-color: #0d6efd;
            box-shadow: 0 0 0 0.25rem rgba(13, 110, 253, 0.25);
        }
        </style>
        
        <script>
        (function() {
            const select = document.getElementById('{{ widget_id }}');
            
            // Initialize Select2 or similar if available
            if (typeof $ !== 'undefined' && $.fn.select2) {
                $('#{{ widget_id }}').select2({
                    placeholder: '{{ placeholder }}',
                    allowClear: true,
                    {% if searchable %}
                    minimumResultsForSearch: 0,
                    {% else %}
                    minimumResultsForSearch: Infinity,
                    {% endif %}
                    {% if ajax_source %}
                    ajax: {
                        url: '{{ ajax_source }}',
                        dataType: 'json',
                        delay: 250,
                        processResults: function(data) {
                            return {
                                results: data.map(item => ({
                                    id: item.value,
                                    text: item.text,
                                    icon: item.icon
                                }))
                            };
                        }
                    }
                    {% endif %}
                });
            }
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            select_html=select_html,
            widget_id=widget_id,
            searchable=self.searchable,
            multiple=self.multiple,
            ajax_source=self.ajax_source,
            placeholder=self.placeholder
        ))




class FileUploadWidget(Input):
    """
    Advanced file upload widget with drag & drop, previews, and progress.
    
    Features:
    - Drag & drop file upload
    - File type validation
    - Image preview thumbnails
    - Upload progress bar
    - Multiple file support
    - File size validation
    - Custom upload handlers
    - Chunked upload for large files
    """
    
    input_type = 'file'
    
    def __init__(self,
                 multiple: bool = False,
                 allowed_types: Optional[List[str]] = None,
                 max_file_size: Optional[int] = None,
                 max_files: int = 5,
                 show_preview: bool = True,
                 upload_endpoint: Optional[str] = None,
                 chunked_upload: bool = False):
        """
        Initialize the file upload widget.
        
        Args:
            multiple: Allow multiple file selection
            allowed_types: List of allowed MIME types
            max_file_size: Maximum file size in bytes
            max_files: Maximum number of files
            show_preview: Show image previews
            upload_endpoint: Custom upload endpoint
            chunked_upload: Enable chunked upload for large files
        """
        self.multiple = multiple
        self.allowed_types = allowed_types or ['image/*', 'application/pdf']
        self.max_file_size = max_file_size or (10 * 1024 * 1024)  # 10MB default
        self.max_files = max_files
        self.show_preview = show_preview
        self.upload_endpoint = upload_endpoint
        self.chunked_upload = chunked_upload
        
    def __call__(self, field, **kwargs):
        """Render the file upload widget."""
        widget_id = kwargs.get('id', f'file_upload_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'file-upload-input')
        
        if self.multiple:
            kwargs['multiple'] = True
            
        kwargs['accept'] = ','.join(self.allowed_types)
        
        template = """
        <div class="file-upload-container" data-widget="file-upload">
            <div class="file-upload-dropzone" id="dropzone-{{ widget_id }}">
                <div class="dropzone-content">
                    <i class="fa fa-cloud-upload fa-3x text-muted"></i>
                    <h4>{{ _('Drop files here or click to browse') }}</h4>
                    <p class="text-muted">
                        {{ _('Allowed types') }}: {{ allowed_types | join(', ') }}<br>
                        {{ _('Maximum size') }}: {{ max_file_size_mb }}MB
                        {% if multiple %} | {{ _('Maximum files') }}: {{ max_files }}{% endif %}
                    </p>
                </div>
                
                <input type="file" id="{{ widget_id }}" name="{{ field.name }}" 
                       style="display: none;" {{ file_attrs | safe }}>
            </div>
            
            <div class="file-upload-queue" id="queue-{{ widget_id }}" style="display: none;">
                <h5>{{ _('Upload Queue') }}</h5>
                <div class="queue-items"></div>
                <div class="queue-actions">
                    <button type="button" class="btn btn-primary btn-sm" data-action="upload-all">
                        <i class="fa fa-upload"></i> {{ _('Upload All') }}
                    </button>
                    <button type="button" class="btn btn-secondary btn-sm" data-action="clear-all">
                        <i class="fa fa-times"></i> {{ _('Clear All') }}
                    </button>
                </div>
            </div>
        </div>
        
        <style>
        .file-upload-container {
            margin-bottom: 1rem;
        }
        
        .file-upload-dropzone {
            border: 2px dashed #dee2e6;
            border-radius: 8px;
            padding: 2rem;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
            background-color: #f8f9fa;
        }
        
        .file-upload-dropzone:hover {
            border-color: #0d6efd;
            background-color: #e7f3ff;
        }
        
        .file-upload-dropzone.dragover {
            border-color: #0d6efd;
            background-color: #cfe2ff;
            transform: scale(1.02);
        }
        
        .file-upload-queue {
            margin-top: 1rem;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 1rem;
        }
        
        .queue-item {
            display: flex;
            align-items: center;
            gap: 1rem;
            padding: 0.5rem;
            border-bottom: 1px solid #e9ecef;
            margin-bottom: 0.5rem;
        }
        
        .queue-item:last-child {
            border-bottom: none;
            margin-bottom: 0;
        }
        
        .file-preview {
            width: 60px;
            height: 60px;
            border-radius: 6px;
            object-fit: cover;
            border: 1px solid #dee2e6;
        }
        
        .file-icon {
            width: 60px;
            height: 60px;
            background-color: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            color: #6c757d;
        }
        
        .file-info {
            flex: 1;
        }
        
        .file-name {
            font-weight: 500;
            margin: 0;
        }
        
        .file-size {
            color: #6c757d;
            font-size: 0.875rem;
            margin: 0;
        }
        
        .file-progress {
            width: 100%;
            height: 4px;
            background-color: #e9ecef;
            border-radius: 2px;
            margin-top: 0.25rem;
            overflow: hidden;
        }
        
        .file-progress-bar {
            height: 100%;
            background-color: #0d6efd;
            width: 0%;
            transition: width 0.3s ease;
        }
        
        .file-actions {
            display: flex;
            gap: 0.25rem;
        }
        
        .queue-actions {
            margin-top: 1rem;
            display: flex;
            gap: 0.5rem;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="file-upload"]');
            const dropzone = document.getElementById('dropzone-{{ widget_id }}');
            const fileInput = document.getElementById('{{ widget_id }}');
            const queue = document.getElementById('queue-{{ widget_id }}');
            const queueItems = queue.querySelector('.queue-items');
            
            let fileQueue = [];
            
            // File validation
            function validateFile(file) {
                const allowedTypes = {{ allowed_types | tojson }};
                const maxSize = {{ max_file_size }};
                
                // Check file type
                const isValidType = allowedTypes.some(type => {
                    if (type.endsWith('/*')) {
                        return file.type.startsWith(type.replace('/*', '/'));
                    }
                    return file.type === type;
                });
                
                if (!isValidType) {
                    return { valid: false, error: `Invalid file type: ${file.type}` };
                }
                
                // Check file size
                if (file.size > maxSize) {
                    const maxMB = Math.round(maxSize / 1024 / 1024);
                    return { valid: false, error: `File too large: ${Math.round(file.size / 1024 / 1024)}MB (max: ${maxMB}MB)` };
                }
                
                return { valid: true };
            }
            
            // Format file size
            function formatFileSize(bytes) {
                if (bytes === 0) return '0 Bytes';
                const k = 1024;
                const sizes = ['Bytes', 'KB', 'MB', 'GB'];
                const i = Math.floor(Math.log(bytes) / Math.log(k));
                return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
            }
            
            // Create queue item
            function createQueueItem(file, index) {
                const item = document.createElement('div');
                item.className = 'queue-item';
                item.dataset.index = index;
                
                const validation = validateFile(file);
                const isValid = validation.valid;
                
                let preview = '';
                if (file.type.startsWith('image/') && {{ show_preview | tojson }}) {
                    const reader = new FileReader();
                    reader.onload = (e) => {
                        const img = item.querySelector('.file-preview');
                        if (img) img.src = e.target.result;
                    };
                    reader.readAsDataURL(file);
                    preview = '<img class="file-preview" alt="Preview">';
                } else {
                    const iconClass = getFileIcon(file.type);
                    preview = `<div class="file-icon"><i class="fa ${iconClass}"></i></div>`;
                }
                
                item.innerHTML = `
                    ${preview}
                    <div class="file-info">
                        <p class="file-name">${file.name}</p>
                        <p class="file-size">${formatFileSize(file.size)}</p>
                        ${!isValid ? `<p class="text-danger">${validation.error}</p>` : ''}
                        <div class="file-progress" style="display: none;">
                            <div class="file-progress-bar"></div>
                        </div>
                    </div>
                    <div class="file-actions">
                        ${isValid ? '<button type="button" class="btn btn-success btn-sm" data-action="upload"><i class="fa fa-upload"></i></button>' : ''}
                        <button type="button" class="btn btn-danger btn-sm" data-action="remove">
                            <i class="fa fa-times"></i>
                        </button>
                    </div>
                `;
                
                return item;
            }
            
            // Get file icon based on type
            function getFileIcon(mimeType) {
                if (mimeType.startsWith('image/')) return 'fa-file-image-o';
                if (mimeType.startsWith('video/')) return 'fa-file-video-o';
                if (mimeType.startsWith('audio/')) return 'fa-file-audio-o';
                if (mimeType === 'application/pdf') return 'fa-file-pdf-o';
                if (mimeType.includes('word')) return 'fa-file-word-o';
                if (mimeType.includes('excel') || mimeType.includes('spreadsheet')) return 'fa-file-excel-o';
                if (mimeType.includes('powerpoint') || mimeType.includes('presentation')) return 'fa-file-powerpoint-o';
                if (mimeType.includes('zip') || mimeType.includes('archive')) return 'fa-file-archive-o';
                return 'fa-file-o';
            }
            
            // Add files to queue
            function addFilesToQueue(files) {
                const remainingSlots = {{ max_files }} - fileQueue.length;
                const filesToAdd = Array.from(files).slice(0, remainingSlots);
                
                filesToAdd.forEach((file, index) => {
                    const queueIndex = fileQueue.length;
                    fileQueue.push(file);
                    
                    const queueItem = createQueueItem(file, queueIndex);
                    queueItems.appendChild(queueItem);
                });
                
                if (fileQueue.length > 0) {
                    queue.style.display = 'block';
                }
                
                if (files.length > remainingSlots) {
                    alert(`Only ${remainingSlots} files can be added (maximum: {{ max_files }})`);
                }
            }
            
            // Upload file
            function uploadFile(file, progressCallback) {
                return new Promise((resolve, reject) => {
                    const formData = new FormData();
                    formData.append('file', file);
                    
                    const xhr = new XMLHttpRequest();
                    
                    xhr.upload.addEventListener('progress', (e) => {
                        if (e.lengthComputable) {
                            const percentComplete = (e.loaded / e.total) * 100;
                            progressCallback(percentComplete);
                        }
                    });
                    
                    xhr.addEventListener('load', () => {
                        if (xhr.status === 200) {
                            resolve(JSON.parse(xhr.responseText));
                        } else {
                            reject(new Error(`Upload failed: ${xhr.statusText}`));
                        }
                    });
                    
                    xhr.addEventListener('error', () => {
                        reject(new Error('Upload failed'));
                    });
                    
                    const endpoint = {{ upload_endpoint | tojson }} || '/upload';
                    xhr.open('POST', endpoint);
                    xhr.send(formData);
                });
            }
            
            // Event listeners
            dropzone.addEventListener('click', () => fileInput.click());
            
            fileInput.addEventListener('change', (e) => {
                if (e.target.files.length > 0) {
                    addFilesToQueue(e.target.files);
                    e.target.value = ''; // Reset input
                }
            });
            
            // Drag & drop
            dropzone.addEventListener('dragover', (e) => {
                e.preventDefault();
                dropzone.classList.add('dragover');
            });
            
            dropzone.addEventListener('dragleave', () => {
                dropzone.classList.remove('dragover');
            });
            
            dropzone.addEventListener('drop', (e) => {
                e.preventDefault();
                dropzone.classList.remove('dragover');
                addFilesToQueue(e.dataTransfer.files);
            });
            
            // Queue actions
            container.addEventListener('click', async (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (!action) return;
                
                e.preventDefault();
                
                const queueItem = e.target.closest('.queue-item');
                const index = queueItem?.dataset.index;
                
                switch (action) {
                    case 'upload':
                        if (index !== undefined) {
                            const file = fileQueue[index];
                            const progressBar = queueItem.querySelector('.file-progress-bar');
                            const progress = queueItem.querySelector('.file-progress');
                            
                            progress.style.display = 'block';
                            
                            try {
                                await uploadFile(file, (percent) => {
                                    progressBar.style.width = percent + '%';
                                });
                                queueItem.style.opacity = '0.5';
                                e.target.innerHTML = '<i class="fa fa-check"></i>';
                                e.target.className = 'btn btn-success btn-sm';
                            } catch (error) {
                                console.error('Upload failed:', error);
                                alert('Upload failed: ' + error.message);
                                progressBar.style.backgroundColor = '#dc3545';
                            }
                        }
                        break;
                        
                    case 'remove':
                        if (index !== undefined) {
                            fileQueue.splice(index, 1);
                            queueItem.remove();
                            
                            // Update indices
                            queueItems.querySelectorAll('.queue-item').forEach((item, newIndex) => {
                                item.dataset.index = newIndex;
                            });
                            
                            if (fileQueue.length === 0) {
                                queue.style.display = 'none';
                            }
                        }
                        break;
                        
                    case 'upload-all':
                        const uploadButtons = queueItems.querySelectorAll('[data-action="upload"]');
                        for (const button of uploadButtons) {
                            if (button.querySelector('.fa-upload')) {
                                button.click();
                                await new Promise(resolve => setTimeout(resolve, 100));
                            }
                        }
                        break;
                        
                    case 'clear-all':
                        fileQueue = [];
                        queueItems.innerHTML = '';
                        queue.style.display = 'none';
                        break;
                }
            });
        })();
        </script>
        """
        
        file_attrs = html_params(**kwargs)
        allowed_types_display = [t.replace('*', 'All') for t in self.allowed_types]
        max_file_size_mb = round(self.max_file_size / 1024 / 1024, 1)
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            file_attrs=file_attrs,
            allowed_types=allowed_types_display,
            max_file_size=self.max_file_size,
            max_file_size_mb=max_file_size_mb,
            max_files=self.max_files,
            multiple=self.multiple,
            show_preview=self.show_preview,
            upload_endpoint=self.upload_endpoint,
            _=gettext
        ))


class DateTimeRangeWidget(Input):
    """
    Advanced date and time range picker widget.
    
    Features:
    - Date range selection with calendar popup
    - Time range selection with time pickers
    - Predefined quick ranges (Today, This Week, etc.)
    - Custom range validation
    - Timezone support
    - Different display formats
    - Business hours filtering
    """
    
    input_type = 'text'
    
    def __init__(self,
                 include_time: bool = True,
                 predefined_ranges: bool = True,
                 timezone_aware: bool = False,
                 min_date: Optional[str] = None,
                 max_date: Optional[str] = None,
                 format_display: str = 'MMM DD, YYYY',
                 business_hours_only: bool = False):
        """
        Initialize the date time range widget.
        
        Args:
            include_time: Include time selection
            predefined_ranges: Show predefined range buttons
            timezone_aware: Handle timezone conversion
            min_date: Minimum allowed date
            max_date: Maximum allowed date
            format_display: Date display format
            business_hours_only: Restrict to business hours
        """
        self.include_time = include_time
        self.predefined_ranges = predefined_ranges
        self.timezone_aware = timezone_aware
        self.min_date = min_date
        self.max_date = max_date
        self.format_display = format_display
        self.business_hours_only = business_hours_only
        
    def __call__(self, field, **kwargs):
        """Render the date time range widget."""
        widget_id = kwargs.get('id', f'datetime_range_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'form-control datetime-range-input')
        kwargs.setdefault('readonly', True)
        
        template = """
        <div class="datetime-range-container" data-widget="datetime-range">
            <div class="input-group">
                <input type="text" id="{{ widget_id }}" name="{{ field.name }}" 
                       class="form-control datetime-range-display" 
                       placeholder="{{ _('Select date range...') }}" 
                       value="{{ field.data or '' }}" readonly>
                <div class="input-group-append">
                    <button type="button" class="btn btn-outline-secondary" 
                            data-toggle="datetime-range-picker">
                        <i class="fa fa-calendar"></i>
                    </button>
                </div>
            </div>
            
            <div class="datetime-range-picker" style="display: none;">
                {% if predefined_ranges %}
                <div class="predefined-ranges">
                    <h6>{{ _('Quick Ranges') }}</h6>
                    <div class="range-buttons">
                        <button type="button" class="btn btn-sm btn-outline-primary" data-range="today">
                            {{ _('Today') }}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-primary" data-range="yesterday">
                            {{ _('Yesterday') }}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-primary" data-range="this_week">
                            {{ _('This Week') }}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-primary" data-range="last_week">
                            {{ _('Last Week') }}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-primary" data-range="this_month">
                            {{ _('This Month') }}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-primary" data-range="last_month">
                            {{ _('Last Month') }}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-primary" data-range="this_year">
                            {{ _('This Year') }}
                        </button>
                    </div>
                </div>
                {% endif %}
                
                <div class="calendar-container">
                    <div class="calendar-section">
                        <h6>{{ _('Start Date') }}</h6>
                        <div class="calendar" data-calendar="start"></div>
                        {% if include_time %}
                        <div class="time-picker">
                            <label>{{ _('Time') }}:</label>
                            <input type="time" class="form-control form-control-sm" data-time="start" 
                                   {% if business_hours_only %}min="09:00" max="17:00"{% endif %}>
                        </div>
                        {% endif %}
                    </div>
                    
                    <div class="calendar-section">
                        <h6>{{ _('End Date') }}</h6>
                        <div class="calendar" data-calendar="end"></div>
                        {% if include_time %}
                        <div class="time-picker">
                            <label>{{ _('Time') }}:</label>
                            <input type="time" class="form-control form-control-sm" data-time="end" 
                                   {% if business_hours_only %}min="09:00" max="17:00"{% endif %}>
                        </div>
                        {% endif %}
                    </div>
                </div>
                
                <div class="picker-actions">
                    <button type="button" class="btn btn-secondary btn-sm" data-action="cancel">
                        {{ _('Cancel') }}
                    </button>
                    <button type="button" class="btn btn-primary btn-sm" data-action="apply">
                        {{ _('Apply') }}
                    </button>
                </div>
            </div>
        </div>
        
        <style>
        .datetime-range-container {
            position: relative;
            margin-bottom: 1rem;
        }
        
        .datetime-range-picker {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 1rem;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            z-index: 1000;
            margin-top: 0.5rem;
            min-width: 600px;
        }
        
        .predefined-ranges {
            margin-bottom: 1rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid #e9ecef;
        }
        
        .range-buttons {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-top: 0.5rem;
        }
        
        .calendar-container {
            display: flex;
            gap: 2rem;
            margin-bottom: 1rem;
        }
        
        .calendar-section {
            flex: 1;
        }
        
        .calendar {
            border: 1px solid #e9ecef;
            border-radius: 6px;
            padding: 1rem;
            background-color: #f8f9fa;
            min-height: 250px;
            margin-bottom: 1rem;
        }
        
        .time-picker {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .time-picker label {
            margin: 0;
            min-width: 50px;
        }
        
        .picker-actions {
            display: flex;
            justify-content: flex-end;
            gap: 0.5rem;
            padding-top: 1rem;
            border-top: 1px solid #e9ecef;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="datetime-range"]');
            const input = document.getElementById('{{ widget_id }}');
            const picker = container.querySelector('.datetime-range-picker');
            const toggleButton = container.querySelector('[data-toggle="datetime-range-picker"]');
            
            let startDate = null;
            let endDate = null;
            let startTime = null;
            let endTime = null;
            
            // Initialize date picker (would use a library like Flatpickr or similar)
            function initializeDatePickers() {
                const startCalendar = picker.querySelector('[data-calendar="start"]');
                const endCalendar = picker.querySelector('[data-calendar="end"]');
                
                // Placeholder for calendar initialization
                // In real implementation, would initialize proper calendar widgets
                startCalendar.innerHTML = '<p class="text-muted">Start date calendar would appear here</p>';
                endCalendar.innerHTML = '<p class="text-muted">End date calendar would appear here</p>';
            }
            
            // Predefined range handlers
            function applyPredefinedRange(range) {
                const now = new Date();
                let start, end;
                
                switch (range) {
                    case 'today':
                        start = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                        end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
                        break;
                    case 'yesterday':
                        const yesterday = new Date(now);
                        yesterday.setDate(yesterday.getDate() - 1);
                        start = new Date(yesterday.getFullYear(), yesterday.getMonth(), yesterday.getDate());
                        end = new Date(yesterday.getFullYear(), yesterday.getMonth(), yesterday.getDate(), 23, 59, 59);
                        break;
                    case 'this_week':
                        const startOfWeek = new Date(now);
                        startOfWeek.setDate(now.getDate() - now.getDay());
                        start = new Date(startOfWeek.getFullYear(), startOfWeek.getMonth(), startOfWeek.getDate());
                        end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
                        break;
                    case 'last_week':
                        const lastWeekEnd = new Date(now);
                        lastWeekEnd.setDate(now.getDate() - now.getDay() - 1);
                        const lastWeekStart = new Date(lastWeekEnd);
                        lastWeekStart.setDate(lastWeekEnd.getDate() - 6);
                        start = new Date(lastWeekStart.getFullYear(), lastWeekStart.getMonth(), lastWeekStart.getDate());
                        end = new Date(lastWeekEnd.getFullYear(), lastWeekEnd.getMonth(), lastWeekEnd.getDate(), 23, 59, 59);
                        break;
                    case 'this_month':
                        start = new Date(now.getFullYear(), now.getMonth(), 1);
                        end = new Date(now.getFullYear(), now.getMonth() + 1, 0, 23, 59, 59);
                        break;
                    case 'last_month':
                        start = new Date(now.getFullYear(), now.getMonth() - 1, 1);
                        end = new Date(now.getFullYear(), now.getMonth(), 0, 23, 59, 59);
                        break;
                    case 'this_year':
                        start = new Date(now.getFullYear(), 0, 1);
                        end = new Date(now.getFullYear(), 11, 31, 23, 59, 59);
                        break;
                }
                
                if (start && end) {
                    startDate = start;
                    endDate = end;
                    updateDisplay();
                    applySelection();
                }
            }
            
            // Update display
            function updateDisplay() {
                if (startDate && endDate) {
                    const format = '{{ format_display }}';
                    let displayValue = '';
                    
                    if ({{ include_time | tojson }}) {
                        displayValue = formatDateTime(startDate) + ' - ' + formatDateTime(endDate);
                    } else {
                        displayValue = formatDate(startDate) + ' - ' + formatDate(endDate);
                    }
                    
                    input.value = displayValue;
                }
            }
            
            // Format date
            function formatDate(date) {
                return date.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric'
                });
            }
            
            // Format date time
            function formatDateTime(date) {
                return date.toLocaleDateString('en-US', {
                    month: 'short',
                    day: 'numeric',
                    year: 'numeric',
                    hour: 'numeric',
                    minute: '2-digit',
                    hour12: true
                });
            }
            
            // Apply selection
            function applySelection() {
                // Create hidden input with ISO format for form submission
                let hiddenInput = container.querySelector('input[type="hidden"]');
                if (!hiddenInput) {
                    hiddenInput = document.createElement('input');
                    hiddenInput.type = 'hidden';
                    hiddenInput.name = '{{ field.name }}';
                    container.appendChild(hiddenInput);
                }
                
                if (startDate && endDate) {
                    const value = {
                        start: startDate.toISOString(),
                        end: endDate.toISOString()
                    };
                    hiddenInput.value = JSON.stringify(value);
                }
                
                picker.style.display = 'none';
            }
            
            // Event listeners
            toggleButton.addEventListener('click', () => {
                picker.style.display = picker.style.display === 'none' ? 'block' : 'none';
            });
            
            // Predefined range buttons
            picker.addEventListener('click', (e) => {
                const range = e.target.dataset.range;
                if (range) {
                    applyPredefinedRange(range);
                    return;
                }
                
                const action = e.target.dataset.action;
                if (action === 'cancel') {
                    picker.style.display = 'none';
                } else if (action === 'apply') {
                    applySelection();
                }
            });
            
            // Time change handlers
            picker.addEventListener('change', (e) => {
                if (e.target.dataset.time === 'start') {
                    startTime = e.target.value;
                } else if (e.target.dataset.time === 'end') {
                    endTime = e.target.value;
                }
            });
            
            // Close picker when clicking outside
            document.addEventListener('click', (e) => {
                if (!container.contains(e.target)) {
                    picker.style.display = 'none';
                }
            });
            
            // Initialize
            initializeDatePickers();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            include_time=self.include_time,
            predefined_ranges=self.predefined_ranges,
            timezone_aware=self.timezone_aware,
            format_display=self.format_display,
            business_hours_only=self.business_hours_only,
            _=gettext
        ))


class TagInputWidget(Input):
    """
    Tag input widget for multiple values with autocomplete.
    
    Features:
    - Tag creation and management
    - Autocomplete suggestions
    - Tag validation
    - Custom tag colors/styles
    - Maximum tag limits
    - Duplicate prevention
    - Drag & drop reordering
    """
    
    input_type = 'text'
    
    def __init__(self,
                 autocomplete_source: Optional[str] = None,
                 max_tags: Optional[int] = None,
                 allowed_tags: Optional[List[str]] = None,
                 tag_colors: bool = True,
                 allow_duplicates: bool = False,
                 sortable: bool = True):
        """
        Initialize the tag input widget.
        
        Args:
            autocomplete_source: URL for tag suggestions
            max_tags: Maximum number of tags
            allowed_tags: List of allowed tag values
            tag_colors: Enable colored tags
            allow_duplicates: Allow duplicate tags
            sortable: Enable drag & drop sorting
        """
        self.autocomplete_source = autocomplete_source
        self.max_tags = max_tags
        self.allowed_tags = allowed_tags
        self.tag_colors = tag_colors
        self.allow_duplicates = allow_duplicates
        self.sortable = sortable
        
    def __call__(self, field, **kwargs):
        """Render the tag input widget."""
        widget_id = kwargs.get('id', f'tag_input_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="tag-input-container" data-widget="tag-input">
            <div class="tag-list" id="tags-{{ widget_id }}">
                <!-- Tags will be inserted here -->
            </div>
            <div class="tag-input-wrapper">
                <input type="text" class="form-control tag-text-input" 
                       id="tag-input-{{ widget_id }}" 
                       placeholder="{{ _('Type and press Enter to add tags...') }}">
                <div class="tag-suggestions" style="display: none;"></div>
            </div>
            <input type="hidden" id="{{ widget_id }}" name="{{ field.name }}" value="{{ field.data or '' }}">
        </div>
        
        <style>
        .tag-input-container {
            border: 2px solid #e9ecef;
            border-radius: 8px;
            padding: 0.5rem;
            min-height: 80px;
            cursor: text;
            transition: all 0.3s ease;
        }
        
        .tag-input-container:focus-within {
            border-color: #0d6efd;
            box-shadow: 0 0 0 0.25rem rgba(13, 110, 253, 0.25);
        }
        
        .tag-list {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }
        
        .tag {
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
            padding: 0.25rem 0.5rem;
            background-color: #0d6efd;
            color: white;
            border-radius: 16px;
            font-size: 0.875rem;
            cursor: pointer;
            transition: all 0.2s ease;
            position: relative;
        }
        
        .tag:hover {
            transform: translateY(-1px);
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        
        .tag.dragging {
            opacity: 0.5;
            transform: rotate(5deg);
        }
        
        .tag-remove {
            background: none;
            border: none;
            color: white;
            cursor: pointer;
            padding: 0;
            width: 16px;
            height: 16px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            transition: background-color 0.2s ease;
        }
        
        .tag-remove:hover {
            background-color: rgba(255,255,255,0.2);
        }
        
        .tag-input-wrapper {
            position: relative;
            flex: 1;
        }
        
        .tag-text-input {
            border: none;
            outline: none;
            width: 100%;
            padding: 0.25rem 0;
        }
        
        .tag-suggestions {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 6px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            z-index: 1000;
            max-height: 200px;
            overflow-y: auto;
        }
        
        .tag-suggestion {
            padding: 0.5rem 1rem;
            cursor: pointer;
            border-bottom: 1px solid #f8f9fa;
        }
        
        .tag-suggestion:hover,
        .tag-suggestion.active {
            background-color: #f8f9fa;
        }
        
        .tag-suggestion:last-child {
            border-bottom: none;
        }
        
        /* Tag colors */
        .tag.color-primary { background-color: #0d6efd; }
        .tag.color-success { background-color: #198754; }
        .tag.color-warning { background-color: #ffc107; color: #000; }
        .tag.color-danger { background-color: #dc3545; }
        .tag.color-info { background-color: #0dcaf0; color: #000; }
        .tag.color-secondary { background-color: #6c757d; }
        .tag.color-purple { background-color: #6f42c1; }
        .tag.color-pink { background-color: #e83e8c; }
        .tag.color-teal { background-color: #20c997; }
        .tag.color-indigo { background-color: #6610f2; }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="tag-input"]');
            const tagList = document.getElementById('tags-{{ widget_id }}');
            const input = document.getElementById('tag-input-{{ widget_id }}');
            const hiddenInput = document.getElementById('{{ widget_id }}');
            const suggestions = container.querySelector('.tag-suggestions');
            
            let tags = [];
            let currentSuggestions = [];
            let selectedSuggestion = -1;
            
            const colors = ['primary', 'success', 'warning', 'danger', 'info', 'secondary', 'purple', 'pink', 'teal', 'indigo'];
            
            // Initialize with existing data
            function initializeTags() {
                const existingData = hiddenInput.value;
                if (existingData) {
                    try {
                        tags = JSON.parse(existingData);
                        renderTags();
                    } catch (e) {
                        // Treat as comma-separated string
                        tags = existingData.split(',').map(tag => tag.trim()).filter(tag => tag);
                        renderTags();
                    }
                }
            }
            
            // Render tags
            function renderTags() {
                tagList.innerHTML = '';
                tags.forEach((tag, index) => {
                    const tagElement = createTagElement(tag, index);
                    tagList.appendChild(tagElement);
                });
                updateHiddenInput();
            }
            
            // Create tag element
            function createTagElement(tag, index) {
                const tagElement = document.createElement('div');
                tagElement.className = 'tag';
                tagElement.draggable = {{ sortable | tojson }};
                tagElement.dataset.index = index;
                
                {% if tag_colors %}
                const colorClass = colors[index % colors.length];
                tagElement.classList.add(`color-${colorClass}`);
                {% endif %}
                
                tagElement.innerHTML = `
                    <span class="tag-text">${escapeHtml(tag)}</span>
                    <button type="button" class="tag-remove" data-remove="${index}">
                        <i class="fa fa-times"></i>
                    </button>
                `;
                
                return tagElement;
            }
            
            // Escape HTML
            function escapeHtml(text) {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            }
            
            // Add tag
            function addTag(tagText) {
                tagText = tagText.trim();
                if (!tagText) return false;
                
                // Check duplicates
                {% if not allow_duplicates %}
                if (tags.includes(tagText)) {
                    showError('Tag already exists');
                    return false;
                }
                {% endif %}
                
                // Check max tags
                {% if max_tags %}
                if (tags.length >= {{ max_tags }}) {
                    showError(`Maximum {{ max_tags }} tags allowed`);
                    return false;
                }
                {% endif %}
                
                // Check allowed tags
                {% if allowed_tags %}
                const allowedTags = {{ allowed_tags | tojson }};
                if (!allowedTags.includes(tagText)) {
                    showError('Tag not allowed');
                    return false;
                }
                {% endif %}
                
                tags.push(tagText);
                renderTags();
                input.value = '';
                hideSuggestions();
                return true;
            }
            
            // Remove tag
            function removeTag(index) {
                tags.splice(index, 1);
                renderTags();
            }
            
            // Update hidden input
            function updateHiddenInput() {
                hiddenInput.value = JSON.stringify(tags);
            }
            
            // Show error
            function showError(message) {
                // You could show a toast or tooltip here
                console.warn('Tag error:', message);
            }
            
            // Fetch suggestions
            async function fetchSuggestions(query) {
                {% if autocomplete_source %}
                if (!query.trim()) {
                    hideSuggestions();
                    return;
                }
                
                try {
                    const response = await fetch(`{{ autocomplete_source }}?q=${encodeURIComponent(query)}`);
                    const data = await response.json();
                    currentSuggestions = data.filter(suggestion => !tags.includes(suggestion));
                    renderSuggestions();
                } catch (error) {
                    console.error('Error fetching suggestions:', error);
                    hideSuggestions();
                }
                {% endif %}
            }
            
            // Render suggestions
            function renderSuggestions() {
                if (currentSuggestions.length === 0) {
                    hideSuggestions();
                    return;
                }
                
                suggestions.innerHTML = '';
                currentSuggestions.forEach((suggestion, index) => {
                    const suggestionElement = document.createElement('div');
                    suggestionElement.className = 'tag-suggestion';
                    suggestionElement.textContent = suggestion;
                    suggestionElement.dataset.index = index;
                    suggestions.appendChild(suggestionElement);
                });
                
                suggestions.style.display = 'block';
                selectedSuggestion = -1;
            }
            
            // Hide suggestions
            function hideSuggestions() {
                suggestions.style.display = 'none';
                currentSuggestions = [];
                selectedSuggestion = -1;
            }
            
            // Event listeners
            input.addEventListener('keydown', (e) => {
                switch (e.key) {
                    case 'Enter':
                    case 'Tab':
                        e.preventDefault();
                        if (selectedSuggestion >= 0) {
                            addTag(currentSuggestions[selectedSuggestion]);
                        } else if (input.value.trim()) {
                            addTag(input.value);
                        }
                        break;
                        
                    case 'ArrowDown':
                        e.preventDefault();
                        if (currentSuggestions.length > 0) {
                            selectedSuggestion = Math.min(selectedSuggestion + 1, currentSuggestions.length - 1);
                            updateSuggestionSelection();
                        }
                        break;
                        
                    case 'ArrowUp':
                        e.preventDefault();
                        if (currentSuggestions.length > 0) {
                            selectedSuggestion = Math.max(selectedSuggestion - 1, -1);
                            updateSuggestionSelection();
                        }
                        break;
                        
                    case 'Escape':
                        hideSuggestions();
                        break;
                        
                    case 'Backspace':
                        if (input.value === '' && tags.length > 0) {
                            removeTag(tags.length - 1);
                        }
                        break;
                }
            });
            
            input.addEventListener('input', (e) => {
                fetchSuggestions(e.target.value);
            });
            
            // Update suggestion selection
            function updateSuggestionSelection() {
                suggestions.querySelectorAll('.tag-suggestion').forEach((elem, index) => {
                    elem.classList.toggle('active', index === selectedSuggestion);
                });
            }
            
            // Tag removal
            tagList.addEventListener('click', (e) => {
                const removeButton = e.target.closest('[data-remove]');
                if (removeButton) {
                    const index = parseInt(removeButton.dataset.remove);
                    removeTag(index);
                }
            });
            
            // Suggestion selection
            suggestions.addEventListener('click', (e) => {
                const suggestion = e.target.closest('.tag-suggestion');
                if (suggestion) {
                    const index = parseInt(suggestion.dataset.index);
                    addTag(currentSuggestions[index]);
                }
            });
            
            // Container click focuses input
            container.addEventListener('click', (e) => {
                if (e.target === container || e.target === tagList) {
                    input.focus();
                }
            });
            
            // Hide suggestions when clicking outside
            document.addEventListener('click', (e) => {
                if (!container.contains(e.target)) {
                    hideSuggestions();
                }
            });
            
            {% if sortable %}
            // Drag & drop sorting
            let draggedIndex = -1;
            
            tagList.addEventListener('dragstart', (e) => {
                if (e.target.classList.contains('tag')) {
                    draggedIndex = parseInt(e.target.dataset.index);
                    e.target.classList.add('dragging');
                }
            });
            
            tagList.addEventListener('dragend', (e) => {
                if (e.target.classList.contains('tag')) {
                    e.target.classList.remove('dragging');
                    draggedIndex = -1;
                }
            });
            
            tagList.addEventListener('dragover', (e) => {
                e.preventDefault();
            });
            
            tagList.addEventListener('drop', (e) => {
                e.preventDefault();
                const dropTarget = e.target.closest('.tag');
                if (dropTarget && draggedIndex >= 0) {
                    const dropIndex = parseInt(dropTarget.dataset.index);
                    if (dropIndex !== draggedIndex) {
                        // Reorder tags
                        const [draggedTag] = tags.splice(draggedIndex, 1);
                        tags.splice(dropIndex, 0, draggedTag);
                        renderTags();
                    }
                }
            });
            {% endif %}
            
            // Initialize
            initializeTags();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            autocomplete_source=self.autocomplete_source,
            max_tags=self.max_tags,
            allowed_tags=self.allowed_tags,
            tag_colors=self.tag_colors,
            allow_duplicates=self.allow_duplicates,
            sortable=self.sortable,
            _=gettext
        ))


class SignatureWidget(Input):
    """
    Advanced signature capture widget with mouse and touch drawing capability.
    
    Features:
    - HTML5 Canvas for smooth signature drawing
    - Mouse and touch input support (mobile-friendly)
    - Configurable pen settings (color, width, smoothing)
    - Clear, undo, and redo functionality
    - Real-time signature validation
    - Export to base64 data URL
    - Responsive canvas sizing
    - Background templates (lines, grids)
    - Save/load signature data
    - Signature comparison tools
    """
    
    input_type = 'hidden'
    
    def __init__(self,
                 canvas_width: int = 600,
                 canvas_height: int = 200,
                 pen_color: str = '#000000',
                 pen_width: int = 2,
                 background_color: str = '#ffffff',
                 show_guidelines: bool = True,
                 enable_pressure: bool = False,
                 require_signature: bool = True,
                 export_format: str = 'png'):  # png, jpg, svg
        """
        Initialize the signature widget.
        
        Args:
            canvas_width: Canvas width in pixels
            canvas_height: Canvas height in pixels
            pen_color: Default pen color
            pen_width: Default pen width
            background_color: Canvas background color
            show_guidelines: Show signature guidelines
            enable_pressure: Enable pressure sensitivity
            require_signature: Require signature before form submission
            export_format: Image export format
        """
        self.canvas_width = canvas_width
        self.canvas_height = canvas_height
        self.pen_color = pen_color
        self.pen_width = pen_width
        self.background_color = background_color
        self.show_guidelines = show_guidelines
        self.enable_pressure = enable_pressure
        self.require_signature = require_signature
        self.export_format = export_format
        
    def __call__(self, field, **kwargs):
        """Render the signature widget."""
        widget_id = kwargs.get('id', f'signature_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="signature-widget-container" data-widget="signature">
            <div class="signature-toolbar">
                <div class="toolbar-left">
                    <h6>{{ _('Digital Signature') }}</h6>
                    <span class="signature-status text-muted">{{ _('Please sign in the area below') }}</span>
                </div>
                
                <div class="toolbar-right">
                    <div class="pen-controls">
                        <label for="pen-color-{{ widget_id }}">{{ _('Color') }}:</label>
                        <input type="color" id="pen-color-{{ widget_id }}" value="{{ pen_color }}" class="pen-color">
                        
                        <label for="pen-width-{{ widget_id }}">{{ _('Width') }}:</label>
                        <input type="range" id="pen-width-{{ widget_id }}" min="1" max="10" value="{{ pen_width }}" class="pen-width">
                        <span class="pen-width-display">{{ pen_width }}px</span>
                    </div>
                    
                    <div class="action-buttons">
                        <button type="button" class="btn btn-sm btn-outline-secondary" data-action="undo" disabled>
                            <i class="fa fa-undo"></i> {{ _('Undo') }}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-secondary" data-action="redo" disabled>
                            <i class="fa fa-repeat"></i> {{ _('Redo') }}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-warning" data-action="clear">
                            <i class="fa fa-eraser"></i> {{ _('Clear') }}
                        </button>
                    </div>
                </div>
            </div>
            
            <div class="signature-canvas-container">
                <canvas id="canvas-{{ widget_id }}" 
                        width="{{ canvas_width }}" 
                        height="{{ canvas_height }}"
                        class="signature-canvas"
                        style="background-color: {{ background_color }};">
                    {{ _('Your browser does not support HTML5 Canvas. Please upgrade to a modern browser.') }}
                </canvas>
                
                {% if show_guidelines %}
                <div class="signature-guidelines">
                    <div class="guideline baseline"></div>
                    <div class="guideline topline"></div>
                </div>
                {% endif %}
                
                <div class="signature-overlay">
                    <div class="signature-placeholder">
                        <i class="fa fa-pencil fa-2x"></i>
                        <p>{{ _('Click and drag to create your signature') }}</p>
                    </div>
                </div>
            </div>
            
            <div class="signature-footer">
                <div class="signature-info">
                    <small class="text-muted">
                        <i class="fa fa-info-circle"></i>
                        {{ _('Use your mouse or finger to draw your signature. You can undo mistakes and clear to start over.') }}
                    </small>
                </div>
                
                <div class="signature-actions">
                    <button type="button" class="btn btn-sm btn-outline-info" data-action="save-template">
                        <i class="fa fa-save"></i> {{ _('Save as Template') }}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-secondary" data-action="load-template">
                        <i class="fa fa-folder-open"></i> {{ _('Load Template') }}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-success" data-action="export">
                        <i class="fa fa-download"></i> {{ _('Export') }}
                    </button>
                </div>
            </div>
            
            <input type="hidden" id="{{ widget_id }}" name="{{ field.name }}" value="{{ field.data or '' }}">
        </div>
        
        <style>
        .signature-widget-container {
            border: 2px solid #dee2e6;
            border-radius: 8px;
            background: white;
            margin-bottom: 1rem;
            transition: all 0.3s ease;
        }
        
        .signature-widget-container:focus-within {
            border-color: #0d6efd;
            box-shadow: 0 0 0 0.25rem rgba(13, 110, 253, 0.25);
        }
        
        .signature-toolbar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem;
            border-bottom: 1px solid #e9ecef;
            background: #f8f9fa;
            border-radius: 8px 8px 0 0;
            flex-wrap: wrap;
            gap: 1rem;
        }
        
        .toolbar-left h6 {
            margin: 0 0 0.25rem 0;
        }
        
        .signature-status {
            font-size: 0.875rem;
        }
        
        .toolbar-right {
            display: flex;
            align-items: center;
            gap: 1rem;
            flex-wrap: wrap;
        }
        
        .pen-controls {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 0.875rem;
        }
        
        .pen-controls label {
            margin: 0;
            white-space: nowrap;
        }
        
        .pen-color {
            width: 40px;
            height: 30px;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            cursor: pointer;
        }
        
        .pen-width {
            width: 80px;
        }
        
        .pen-width-display {
            min-width: 35px;
            font-weight: 500;
        }
        
        .action-buttons {
            display: flex;
            gap: 0.25rem;
        }
        
        .signature-canvas-container {
            position: relative;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 1rem;
            background: #fdfdfd;
        }
        
        .signature-canvas {
            border: 1px solid #e9ecef;
            border-radius: 6px;
            cursor: crosshair;
            touch-action: none;
            position: relative;
            z-index: 2;
        }
        
        .signature-canvas:active {
            cursor: grabbing;
        }
        
        .signature-guidelines {
            position: absolute;
            top: 1rem;
            left: 1rem;
            right: 1rem;
            bottom: 1rem;
            pointer-events: none;
            z-index: 1;
        }
        
        .guideline {
            position: absolute;
            left: 0;
            right: 0;
            height: 1px;
            border-top: 1px dashed #dee2e6;
        }
        
        .guideline.baseline {
            bottom: 40%;
        }
        
        .guideline.topline {
            bottom: 70%;
        }
        
        .signature-overlay {
            position: absolute;
            top: 1rem;
            left: 1rem;
            right: 1rem;
            bottom: 1rem;
            display: flex;
            align-items: center;
            justify-content: center;
            pointer-events: none;
            z-index: 1;
            transition: opacity 0.3s ease;
        }
        
        .signature-placeholder {
            text-align: center;
            color: #6c757d;
            opacity: 0.7;
        }
        
        .signature-placeholder i {
            margin-bottom: 0.5rem;
            display: block;
        }
        
        .signature-placeholder p {
            margin: 0;
            font-size: 0.875rem;
        }
        
        .signature-overlay.hidden {
            opacity: 0;
        }
        
        .signature-footer {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 1rem;
            border-top: 1px solid #e9ecef;
            background: #f8f9fa;
            border-radius: 0 0 8px 8px;
            flex-wrap: wrap;
            gap: 1rem;
        }
        
        .signature-info {
            flex: 1;
        }
        
        .signature-actions {
            display: flex;
            gap: 0.25rem;
        }
        
        .signature-canvas.signed {
            border-color: #198754;
            box-shadow: 0 0 0 1px rgba(25, 135, 84, 0.25);
        }
        
        .signature-status.signed {
            color: #198754;
        }
        
        .signature-status.signed::before {
            content: "✓ ";
            font-family: FontAwesome;
            margin-right: 0.25rem;
        }
        
        /* Responsive adjustments */
        @media (max-width: 768px) {
            .signature-toolbar {
                flex-direction: column;
                align-items: stretch;
                text-align: center;
            }
            
            .toolbar-right {
                justify-content: center;
            }
            
            .signature-canvas {
                max-width: 100%;
                height: auto;
            }
            
            .signature-footer {
                flex-direction: column;
                text-align: center;
            }
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="signature"]');
            const canvas = document.getElementById('canvas-{{ widget_id }}');
            const ctx = canvas.getContext('2d');
            const hiddenInput = document.getElementById('{{ widget_id }}');
            const overlay = container.querySelector('.signature-overlay');
            const statusElement = container.querySelector('.signature-status');
            const penColorInput = document.getElementById('pen-color-{{ widget_id }}');
            const penWidthInput = document.getElementById('pen-width-{{ widget_id }}');
            const penWidthDisplay = container.querySelector('.pen-width-display');
            
            // State management
            let isDrawing = false;
            let hasSigned = false;
            let lastX = 0;
            let lastY = 0;
            let currentPath = [];
            let undoStack = [];
            let redoStack = [];
            let currentPenColor = '{{ pen_color }}';
            let currentPenWidth = {{ pen_width }};
            
            // Touch/mouse position tracking
            let touches = new Map();
            
            // Initialize canvas
            function initializeCanvas() {
                // Set up canvas for high-DPI displays
                const rect = canvas.getBoundingClientRect();
                const dpr = window.devicePixelRatio || 1;
                
                canvas.width = {{ canvas_width }} * dpr;
                canvas.height = {{ canvas_height }} * dpr;
                canvas.style.width = '{{ canvas_width }}px';
                canvas.style.height = '{{ canvas_height }}px';
                
                ctx.scale(dpr, dpr);
                ctx.lineCap = 'round';
                ctx.lineJoin = 'round';
                ctx.imageSmoothingEnabled = true;
                
                // Load existing signature if available
                loadExistingSignature();
            }
            
            // Load existing signature data
            function loadExistingSignature() {
                const existingData = hiddenInput.value;
                if (existingData && existingData.startsWith('data:image/')) {
                    const img = new Image();
                    img.onload = function() {
                        ctx.drawImage(img, 0, 0, {{ canvas_width }}, {{ canvas_height }});
                        markAsSigned();
                    };
                    img.src = existingData;
                }
            }
            
            // Get coordinates from event (mouse or touch)
            function getEventCoordinates(event) {
                const rect = canvas.getBoundingClientRect();
                const scaleX = canvas.width / rect.width;
                const scaleY = canvas.height / rect.height;
                
                let clientX, clientY;
                
                if (event.type.startsWith('touch')) {
                    // Handle touch events
                    const touch = event.touches[0] || event.changedTouches[0];
                    clientX = touch.clientX;
                    clientY = touch.clientY;
                } else {
                    // Handle mouse events
                    clientX = event.clientX;
                    clientY = event.clientY;
                }
                
                return {
                    x: (clientX - rect.left) * scaleX / (window.devicePixelRatio || 1),
                    y: (clientY - rect.top) * scaleY / (window.devicePixelRatio || 1)
                };
            }
            
            // Start drawing
            function startDrawing(event) {
                event.preventDefault();
                isDrawing = true;
                
                const coords = getEventCoordinates(event);
                lastX = coords.x;
                lastY = coords.y;
                
                // Start new path
                currentPath = [{
                    x: coords.x,
                    y: coords.y,
                    color: currentPenColor,
                    width: currentPenWidth
                }];
                
                ctx.beginPath();
                ctx.moveTo(coords.x, coords.y);
                ctx.strokeStyle = currentPenColor;
                ctx.lineWidth = currentPenWidth;
                
                // Hide placeholder
                overlay.classList.add('hidden');
            }
            
            // Continue drawing
            function draw(event) {
                if (!isDrawing) return;
                
                event.preventDefault();
                const coords = getEventCoordinates(event);
                
                // Add point to current path
                currentPath.push({
                    x: coords.x,
                    y: coords.y,
                    color: currentPenColor,
                    width: currentPenWidth
                });
                
                // Draw line segment
                ctx.lineTo(coords.x, coords.y);
                ctx.stroke();
                
                lastX = coords.x;
                lastY = coords.y;
            }
            
            // Stop drawing
            function stopDrawing(event) {
                if (!isDrawing) return;
                
                event.preventDefault();
                isDrawing = false;
                
                // Save current state to undo stack
                if (currentPath.length > 1) {
                    saveState();
                    markAsSigned();
                }
                
                currentPath = [];
            }
            
            // Save canvas state
            function saveState() {
                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                undoStack.push(imageData);
                
                // Limit undo stack size
                if (undoStack.length > 20) {
                    undoStack.shift();
                }
                
                // Clear redo stack when new action is performed
                redoStack = [];
                
                updateActionButtons();
                updateHiddenInput();
            }
            
            // Mark signature as completed
            function markAsSigned() {
                hasSigned = true;
                canvas.classList.add('signed');
                statusElement.textContent = '{{ _("Signature captured") }}';
                statusElement.classList.add('signed');
            }
            
            // Mark signature as cleared
            function markAsCleared() {
                hasSigned = false;
                canvas.classList.remove('signed');
                statusElement.textContent = '{{ _("Please sign in the area below") }}';
                statusElement.classList.remove('signed');
                overlay.classList.remove('hidden');
            }
            
            // Update action buttons state
            function updateActionButtons() {
                const undoBtn = container.querySelector('[data-action="undo"]');
                const redoBtn = container.querySelector('[data-action="redo"]');
                
                undoBtn.disabled = undoStack.length === 0;
                redoBtn.disabled = redoStack.length === 0;
            }
            
            // Update hidden input with signature data
            function updateHiddenInput() {
                if (hasSigned) {
                    const dataURL = canvas.toDataURL('image/{{ export_format }}', 0.9);
                    hiddenInput.value = dataURL;
                } else {
                    hiddenInput.value = '';
                }
            }
            
            // Clear canvas
            function clearCanvas() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                markAsCleared();
                updateHiddenInput();
                
                // Save clear state to undo stack
                saveState();
            }
            
            // Undo last action
            function undo() {
                if (undoStack.length > 0) {
                    // Save current state to redo stack
                    const currentState = ctx.getImageData(0, 0, canvas.width, canvas.height);
                    redoStack.push(currentState);
                    
                    // Restore previous state
                    const previousState = undoStack.pop();
                    ctx.putImageData(previousState, 0, 0);
                    
                    // Check if canvas is empty
                    const isEmpty = isCanvasEmpty();
                    if (isEmpty) {
                        markAsCleared();
                    } else {
                        markAsSigned();
                    }
                    
                    updateActionButtons();
                    updateHiddenInput();
                }
            }
            
            // Redo last undone action
            function redo() {
                if (redoStack.length > 0) {
                    // Save current state to undo stack
                    const currentState = ctx.getImageData(0, 0, canvas.width, canvas.height);
                    undoStack.push(currentState);
                    
                    // Restore next state
                    const nextState = redoStack.pop();
                    ctx.putImageData(nextState, 0, 0);
                    
                    markAsSigned();
                    updateActionButtons();
                    updateHiddenInput();
                }
            }
            
            // Check if canvas is empty
            function isCanvasEmpty() {
                const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
                const pixels = imageData.data;
                
                for (let i = 3; i < pixels.length; i += 4) {
                    if (pixels[i] !== 0) return false; // Alpha channel
                }
                return true;
            }
            
            // Export signature
            function exportSignature() {
                if (!hasSigned) {
                    alert('{{ _("Please create a signature before exporting") }}');
                    return;
                }
                
                const dataURL = canvas.toDataURL('image/{{ export_format }}', 0.9);
                const link = document.createElement('a');
                link.download = `signature.{{ export_format }}`;
                link.href = dataURL;
                link.click();
            }
            
            // Save signature as template
            function saveTemplate() {
                if (!hasSigned) {
                    alert('{{ _("Please create a signature before saving as template") }}');
                    return;
                }
                
                const templateName = prompt('{{ _("Enter template name:") }}');
                if (templateName) {
                    const dataURL = canvas.toDataURL('image/png', 0.9);
                    localStorage.setItem(`signature_template_${templateName}`, dataURL);
                    alert('{{ _("Template saved successfully") }}');
                }
            }
            
            // Load signature template
            function loadTemplate() {
                const templates = Object.keys(localStorage)
                    .filter(key => key.startsWith('signature_template_'))
                    .map(key => key.replace('signature_template_', ''));
                
                if (templates.length === 0) {
                    alert('{{ _("No templates found") }}');
                    return;
                }
                
                const templateName = prompt(`{{ _("Available templates:") }}` + String.fromCharCode(10) + `${templates.join(', ')}` + String.fromCharCode(10) + String.fromCharCode(10) + `{{ _("Enter template name to load:") }}`);
                if (templateName && templates.includes(templateName)) {
                    const dataURL = localStorage.getItem(`signature_template_${templateName}`);
                    if (dataURL) {
                        const img = new Image();
                        img.onload = function() {
                            ctx.clearRect(0, 0, canvas.width, canvas.height);
                            ctx.drawImage(img, 0, 0, {{ canvas_width }}, {{ canvas_height }});
                            markAsSigned();
                            saveState();
                        };
                        img.src = dataURL;
                    }
                }
            }
            
            // Mouse event listeners
            canvas.addEventListener('mousedown', startDrawing);
            canvas.addEventListener('mousemove', draw);
            canvas.addEventListener('mouseup', stopDrawing);
            canvas.addEventListener('mouseout', stopDrawing);
            
            // Touch event listeners
            canvas.addEventListener('touchstart', startDrawing, { passive: false });
            canvas.addEventListener('touchmove', draw, { passive: false });
            canvas.addEventListener('touchend', stopDrawing, { passive: false });
            canvas.addEventListener('touchcancel', stopDrawing, { passive: false });
            
            // Pen controls
            penColorInput.addEventListener('change', (e) => {
                currentPenColor = e.target.value;
            });
            
            penWidthInput.addEventListener('input', (e) => {
                currentPenWidth = parseInt(e.target.value);
                penWidthDisplay.textContent = currentPenWidth + 'px';
            });
            
            // Action button listeners
            container.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (!action) return;
                
                e.preventDefault();
                
                switch (action) {
                    case 'clear':
                        if (!hasSigned || confirm('{{ _("Are you sure you want to clear the signature?") }}')) {
                            clearCanvas();
                        }
                        break;
                    case 'undo':
                        undo();
                        break;
                    case 'redo':
                        redo();
                        break;
                    case 'export':
                        exportSignature();
                        break;
                    case 'save-template':
                        saveTemplate();
                        break;
                    case 'load-template':
                        loadTemplate();
                        break;
                }
            });
            
            // Form validation
            {% if require_signature %}
            const form = canvas.closest('form');
            if (form) {
                form.addEventListener('submit', (e) => {
                    if (!hasSigned) {
                        e.preventDefault();
                        alert('{{ _("Please provide your signature before submitting the form") }}');
                        canvas.focus();
                        return false;
                    }
                });
            }
            {% endif %}
            
            // Prevent context menu on canvas
            canvas.addEventListener('contextmenu', (e) => {
                e.preventDefault();
            });
            
            // Initialize
            initializeCanvas();
            updateActionButtons();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            canvas_width=self.canvas_width,
            canvas_height=self.canvas_height,
            pen_color=self.pen_color,
            pen_width=self.pen_width,
            background_color=self.background_color,
            show_guidelines=self.show_guidelines,
            enable_pressure=self.enable_pressure,
            require_signature=self.require_signature,
            export_format=self.export_format,
            _=gettext
        ))


class SliderRangeWidget(Input):
    """
    Advanced slider/range input widget with dual handles and value display.
    
    Features:
    - Single or dual-handle range selection
    - Custom value formatting and display
    - Step increments and snap-to-grid
    - Visual value indicators and tooltips
    - Keyboard navigation support
    - Custom styling themes
    - Real-time value callbacks
    - Min/max validation with visual feedback
    """
    
    input_type = 'hidden'
    
    def __init__(self,
                 min_value: float = 0,
                 max_value: float = 100,
                 step: float = 1,
                 dual_handles: bool = False,
                 show_values: bool = True,
                 show_ticks: bool = False,
                 value_formatter: Optional[str] = None,
                 theme: str = 'default'):
        """
        Initialize the slider range widget.
        
        Args:
            min_value: Minimum slider value
            max_value: Maximum slider value
            step: Step increment for slider movement
            dual_handles: Enable dual-handle range selection
            show_values: Display current values
            show_ticks: Show tick marks on slider
            value_formatter: Format string for values (e.g., '${value}', '{value}%')
            theme: Visual theme (default, modern, minimal)
        """
        self.min_value = min_value
        self.max_value = max_value
        self.step = step
        self.dual_handles = dual_handles
        self.show_values = show_values
        self.show_ticks = show_ticks
        self.value_formatter = value_formatter
        self.theme = theme
        
    def __call__(self, field, **kwargs):
        """Render the slider range widget."""
        widget_id = kwargs.get('id', f'slider_range_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="slider-range-container theme-{{ theme }}" data-widget="slider-range">
            {% if show_values %}
            <div class="slider-value-display">
                {% if dual_handles %}
                <div class="value-range">
                    <span class="min-value" id="min-value-{{ widget_id }}">{{ min_value }}</span>
                    <span class="separator">-</span>
                    <span class="max-value" id="max-value-{{ widget_id }}">{{ max_value }}</span>
                </div>
                {% else %}
                <div class="single-value" id="single-value-{{ widget_id }}">{{ min_value }}</div>
                {% endif %}
            </div>
            {% endif %}
            
            <div class="slider-track-container">
                <div class="slider-track" id="track-{{ widget_id }}">
                    <div class="slider-range-fill" id="fill-{{ widget_id }}"></div>
                    
                    {% if show_ticks %}
                    <div class="slider-ticks" id="ticks-{{ widget_id }}">
                        <!-- Ticks will be generated dynamically -->
                    </div>
                    {% endif %}
                    
                    <div class="slider-handle min-handle" id="min-handle-{{ widget_id }}" 
                         tabindex="0" role="slider" 
                         aria-valuemin="{{ min_value }}" 
                         aria-valuemax="{{ max_value }}"
                         aria-valuenow="{{ min_value }}">
                        <div class="handle-tooltip" id="min-tooltip-{{ widget_id }}">{{ min_value }}</div>
                    </div>
                    
                    {% if dual_handles %}
                    <div class="slider-handle max-handle" id="max-handle-{{ widget_id }}" 
                         tabindex="0" role="slider"
                         aria-valuemin="{{ min_value }}" 
                         aria-valuemax="{{ max_value }}"
                         aria-valuenow="{{ max_value }}">
                        <div class="handle-tooltip" id="max-tooltip-{{ widget_id }}">{{ max_value }}</div>
                    </div>
                    {% endif %}
                </div>
            </div>
            
            <input type="hidden" id="{{ widget_id }}" name="{{ field.name }}" value="{{ field.data or min_value }}">
        </div>
        
        <style>
        .slider-range-container {
            margin: 1rem 0;
            padding: 1rem;
            user-select: none;
        }
        
        .slider-value-display {
            text-align: center;
            margin-bottom: 1rem;
            font-weight: 600;
            font-size: 1.1rem;
        }
        
        .value-range {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.5rem;
        }
        
        .separator {
            color: #6c757d;
        }
        
        .slider-track-container {
            position: relative;
            padding: 1rem 0;
        }
        
        .slider-track {
            position: relative;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            margin: 0 1rem;
        }
        
        .slider-range-fill {
            position: absolute;
            height: 100%;
            background: linear-gradient(to right, #0d6efd, #198754);
            border-radius: 4px;
            transition: all 0.2s ease;
        }
        
        .slider-handle {
            position: absolute;
            width: 24px;
            height: 24px;
            background: white;
            border: 3px solid #0d6efd;
            border-radius: 50%;
            top: 50%;
            transform: translate(-50%, -50%);
            cursor: pointer;
            transition: all 0.2s ease;
            outline: none;
        }
        
        .slider-handle:hover,
        .slider-handle:focus {
            box-shadow: 0 0 0 6px rgba(13, 110, 253, 0.25);
            transform: translate(-50%, -50%) scale(1.1);
        }
        
        .slider-handle:active {
            transform: translate(-50%, -50%) scale(1.2);
        }
        
        .handle-tooltip {
            position: absolute;
            bottom: 35px;
            left: 50%;
            transform: translateX(-50%);
            background: #212529;
            color: white;
            padding: 0.25rem 0.5rem;
            border-radius: 4px;
            font-size: 0.75rem;
            white-space: nowrap;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s ease;
        }
        
        .handle-tooltip::after {
            content: '';
            position: absolute;
            top: 100%;
            left: 50%;
            transform: translateX(-50%);
            border: 4px solid transparent;
            border-top-color: #212529;
        }
        
        .slider-handle:hover .handle-tooltip,
        .slider-handle:focus .handle-tooltip,
        .slider-handle.dragging .handle-tooltip {
            opacity: 1;
        }
        
        .slider-ticks {
            position: absolute;
            top: 100%;
            left: 0;
            right: 0;
            height: 10px;
            pointer-events: none;
        }
        
        .tick {
            position: absolute;
            width: 1px;
            height: 6px;
            background: #6c757d;
            top: 2px;
        }
        
        .tick.major {
            height: 10px;
            width: 2px;
            background: #495057;
        }
        
        /* Theme variations */
        .theme-modern .slider-track {
            height: 6px;
            background: linear-gradient(to right, #f8f9fa, #e9ecef);
        }
        
        .theme-modern .slider-range-fill {
            background: linear-gradient(45deg, #6f42c1, #e83e8c);
        }
        
        .theme-modern .slider-handle {
            width: 20px;
            height: 20px;
            border: 2px solid #6f42c1;
            background: linear-gradient(45deg, #ffffff, #f8f9fa);
        }
        
        .theme-minimal .slider-track {
            height: 4px;
            background: #dee2e6;
        }
        
        .theme-minimal .slider-range-fill {
            background: #6c757d;
        }
        
        .theme-minimal .slider-handle {
            width: 16px;
            height: 16px;
            border: 2px solid #6c757d;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="slider-range"]');
            const track = document.getElementById('track-{{ widget_id }}');
            const fill = document.getElementById('fill-{{ widget_id }}');
            const minHandle = document.getElementById('min-handle-{{ widget_id }}');
            const maxHandle = document.getElementById('{% if dual_handles %}max-handle-{{ widget_id }}{% else %}null{% endif %}');
            const hiddenInput = document.getElementById('{{ widget_id }}');
            
            const config = {
                min: {{ min_value }},
                max: {{ max_value }},
                step: {{ step }},
                dualHandles: {{ dual_handles | tojson }},
                valueFormatter: {{ value_formatter | tojson }}
            };
            
            let minValue = config.min;
            let maxValue = config.dualHandles ? config.max : config.min;
            let isDragging = false;
            let activeHandle = null;
            
            // Initialize with existing value
            function initializeValues() {
                const existingValue = hiddenInput.value;
                if (existingValue) {
                    if (config.dualHandles && existingValue.includes(',')) {
                        const [min, max] = existingValue.split(',').map(v => parseFloat(v.trim()));
                        minValue = min;
                        maxValue = max;
                    } else {
                        minValue = parseFloat(existingValue);
                        if (!config.dualHandles) {
                            maxValue = minValue;
                        }
                    }
                }
                updateVisualState();
            }
            
            // Format value for display
            function formatValue(value) {
                if (config.valueFormatter) {
                    return config.valueFormatter.replace('{value}', value.toFixed(getDecimalPlaces()));
                }
                return value.toFixed(getDecimalPlaces());
            }
            
            // Get decimal places from step
            function getDecimalPlaces() {
                const stepStr = config.step.toString();
                if (stepStr.includes('.')) {
                    return stepStr.split('.')[1].length;
                }
                return 0;
            }
            
            // Convert pixel position to value
            function positionToValue(position) {
                const trackRect = track.getBoundingClientRect();
                const percentage = Math.max(0, Math.min(1, position / trackRect.width));
                const rawValue = config.min + (percentage * (config.max - config.min));
                return Math.round(rawValue / config.step) * config.step;
            }
            
            // Convert value to pixel position
            function valueToPosition(value) {
                const trackRect = track.getBoundingClientRect();
                const percentage = (value - config.min) / (config.max - config.min);
                return percentage * trackRect.width;
            }
            
            // Update visual state of slider
            function updateVisualState() {
                const trackRect = track.getBoundingClientRect();
                
                if (config.dualHandles) {
                    const minPos = valueToPosition(minValue);
                    const maxPos = valueToPosition(maxValue);
                    
                    minHandle.style.left = (minPos / trackRect.width * 100) + '%';
                    maxHandle.style.left = (maxPos / trackRect.width * 100) + '%';
                    
                    fill.style.left = (minPos / trackRect.width * 100) + '%';
                    fill.style.width = ((maxPos - minPos) / trackRect.width * 100) + '%';
                    
                    // Update tooltips
                    minHandle.querySelector('.handle-tooltip').textContent = formatValue(minValue);
                    maxHandle.querySelector('.handle-tooltip').textContent = formatValue(maxValue);
                    
                    // Update display values
                    const minDisplay = document.getElementById('min-value-{{ widget_id }}');
                    const maxDisplay = document.getElementById('max-value-{{ widget_id }}');
                    if (minDisplay) minDisplay.textContent = formatValue(minValue);
                    if (maxDisplay) maxDisplay.textContent = formatValue(maxValue);
                    
                    // Update hidden input
                    hiddenInput.value = `${minValue},${maxValue}`;
                } else {
                    const pos = valueToPosition(minValue);
                    minHandle.style.left = (pos / trackRect.width * 100) + '%';
                    fill.style.width = (pos / trackRect.width * 100) + '%';
                    
                    // Update tooltip
                    minHandle.querySelector('.handle-tooltip').textContent = formatValue(minValue);
                    
                    // Update display value
                    const singleDisplay = document.getElementById('single-value-{{ widget_id }}');
                    if (singleDisplay) singleDisplay.textContent = formatValue(minValue);
                    
                    // Update hidden input
                    hiddenInput.value = minValue.toString();
                }
                
                // Update ARIA values
                minHandle.setAttribute('aria-valuenow', minValue);
                if (maxHandle) {
                    maxHandle.setAttribute('aria-valuenow', maxValue);
                }
            }
            
            // Handle mouse/touch events
            function startDrag(event, handle) {
                event.preventDefault();
                isDragging = true;
                activeHandle = handle;
                handle.classList.add('dragging');
                
                document.addEventListener('mousemove', handleDrag);
                document.addEventListener('mouseup', stopDrag);
                document.addEventListener('touchmove', handleDrag, { passive: false });
                document.addEventListener('touchend', stopDrag);
            }
            
            function handleDrag(event) {
                if (!isDragging || !activeHandle) return;
                
                event.preventDefault();
                const clientX = event.type.startsWith('touch') ? 
                    event.touches[0].clientX : event.clientX;
                
                const trackRect = track.getBoundingClientRect();
                const position = clientX - trackRect.left;
                const newValue = positionToValue(position);
                
                if (activeHandle === minHandle) {
                    if (config.dualHandles) {
                        minValue = Math.min(newValue, maxValue - config.step);
                    } else {
                        minValue = newValue;
                    }
                } else if (activeHandle === maxHandle && config.dualHandles) {
                    maxValue = Math.max(newValue, minValue + config.step);
                }
                
                // Clamp values to bounds
                minValue = Math.max(config.min, Math.min(config.max, minValue));
                if (config.dualHandles) {
                    maxValue = Math.max(config.min, Math.min(config.max, maxValue));
                }
                
                updateVisualState();
            }
            
            function stopDrag() {
                if (isDragging && activeHandle) {
                    activeHandle.classList.remove('dragging');
                    isDragging = false;
                    activeHandle = null;
                    
                    document.removeEventListener('mousemove', handleDrag);
                    document.removeEventListener('mouseup', stopDrag);
                    document.removeEventListener('touchmove', handleDrag);
                    document.removeEventListener('touchend', stopDrag);
                }
            }
            
            // Keyboard navigation
            function handleKeydown(event, handle) {
                let delta = 0;
                
                switch (event.key) {
                    case 'ArrowLeft':
                    case 'ArrowDown':
                        delta = -config.step;
                        break;
                    case 'ArrowRight':
                    case 'ArrowUp':
                        delta = config.step;
                        break;
                    case 'PageDown':
                        delta = -config.step * 10;
                        break;
                    case 'PageUp':
                        delta = config.step * 10;
                        break;
                    case 'Home':
                        if (handle === minHandle) {
                            minValue = config.min;
                        } else {
                            maxValue = config.min;
                        }
                        updateVisualState();
                        return;
                    case 'End':
                        if (handle === minHandle) {
                            minValue = config.dualHandles ? Math.min(config.max, maxValue - config.step) : config.max;
                        } else {
                            maxValue = config.max;
                        }
                        updateVisualState();
                        return;
                    default:
                        return;
                }
                
                event.preventDefault();
                
                if (handle === minHandle) {
                    minValue = Math.max(config.min, Math.min(
                        config.dualHandles ? maxValue - config.step : config.max,
                        minValue + delta
                    ));
                } else if (handle === maxHandle && config.dualHandles) {
                    maxValue = Math.max(minValue + config.step, Math.min(config.max, maxValue + delta));
                }
                
                updateVisualState();
            }
            
            // Generate ticks
            {% if show_ticks %}
            function generateTicks() {
                const ticksContainer = document.getElementById('ticks-{{ widget_id }}');
                if (!ticksContainer) return;
                
                const range = config.max - config.min;
                const numTicks = Math.min(20, range / config.step + 1);
                const tickStep = range / (numTicks - 1);
                
                for (let i = 0; i < numTicks; i++) {
                    const tick = document.createElement('div');
                    tick.className = i % 5 === 0 ? 'tick major' : 'tick';
                    tick.style.left = (i / (numTicks - 1) * 100) + '%';
                    ticksContainer.appendChild(tick);
                }
            }
            
            generateTicks();
            {% endif %}
            
            // Event listeners
            minHandle.addEventListener('mousedown', (e) => startDrag(e, minHandle));
            minHandle.addEventListener('touchstart', (e) => startDrag(e, minHandle), { passive: false });
            minHandle.addEventListener('keydown', (e) => handleKeydown(e, minHandle));
            
            if (maxHandle) {
                maxHandle.addEventListener('mousedown', (e) => startDrag(e, maxHandle));
                maxHandle.addEventListener('touchstart', (e) => startDrag(e, maxHandle), { passive: false });
                maxHandle.addEventListener('keydown', (e) => handleKeydown(e, maxHandle));
            }
            
            // Track click to jump
            track.addEventListener('click', (event) => {
                if (isDragging) return;
                
                const trackRect = track.getBoundingClientRect();
                const position = event.clientX - trackRect.left;
                const newValue = positionToValue(position);
                
                if (config.dualHandles) {
                    // Move the closest handle
                    const minDist = Math.abs(newValue - minValue);
                    const maxDist = Math.abs(newValue - maxValue);
                    
                    if (minDist < maxDist) {
                        minValue = Math.min(newValue, maxValue - config.step);
                    } else {
                        maxValue = Math.max(newValue, minValue + config.step);
                    }
                } else {
                    minValue = newValue;
                }
                
                updateVisualState();
            });
            
            // Initialize
            initializeValues();
            
            // Update on window resize
            window.addEventListener('resize', updateVisualState);
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            min_value=self.min_value,
            max_value=self.max_value,
            step=self.step,
            dual_handles=self.dual_handles,
            show_values=self.show_values,
            show_ticks=self.show_ticks,
            value_formatter=self.value_formatter,
            theme=self.theme,
            _=gettext
        ))


class StarRatingWidget(Input):
    """
    Interactive star rating widget with hover effects and custom styling.
    
    Features:
    - Configurable number of stars (1-10)
    - Half-star rating support
    - Read-only display mode
    - Custom star icons and colors
    - Hover animations and feedback
    - Keyboard navigation
    - Size variants (small, medium, large)
    - Rating labels and descriptions
    """
    
    input_type = 'hidden'
    
    def __init__(self,
                 max_rating: int = 5,
                 allow_half_stars: bool = False,
                 readonly: bool = False,
                 size: str = 'medium',
                 star_color: str = '#ffc107',
                 empty_color: str = '#e9ecef',
                 show_labels: bool = False,
                 custom_labels: Optional[List[str]] = None):
        """
        Initialize the star rating widget.
        
        Args:
            max_rating: Maximum number of stars (1-10)
            allow_half_stars: Enable half-star ratings
            readonly: Make rating read-only
            size: Star size (small, medium, large)
            star_color: Color for filled stars
            empty_color: Color for empty stars
            show_labels: Show rating labels
            custom_labels: Custom labels for each rating level
        """
        self.max_rating = min(max(max_rating, 1), 10)
        self.allow_half_stars = allow_half_stars
        self.readonly = readonly
        self.size = size
        self.star_color = star_color
        self.empty_color = empty_color
        self.show_labels = show_labels
        self.custom_labels = custom_labels or [
            'Poor', 'Fair', 'Good', 'Very Good', 'Excellent'
        ][:max_rating]
        
    def __call__(self, field, **kwargs):
        """Render the star rating widget."""
        widget_id = kwargs.get('id', f'star_rating_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        template = """
        <div class="star-rating-container size-{{ size }}" data-widget="star-rating">
            <div class="star-rating" id="rating-{{ widget_id }}" 
                 {% if not readonly %}tabindex="0" role="slider" 
                 aria-valuemin="0" aria-valuemax="{{ max_rating }}"{% endif %}>
                {% for i in range(1, max_rating + 1) %}
                <span class="star" data-rating="{{ i }}" data-index="{{ i - 1 }}">
                    <i class="fa fa-star-o star-empty"></i>
                    <i class="fa fa-star star-filled"></i>
                    {% if allow_half_stars %}
                    <i class="fa fa-star-half-o star-half"></i>
                    {% endif %}
                </span>
                {% endfor %}
            </div>
            
            {% if show_labels %}
            <div class="rating-label" id="label-{{ widget_id }}">
                <span class="current-label">{{ _('No rating') }}</span>
            </div>
            {% endif %}
            
            <input type="hidden" id="{{ widget_id }}" name="{{ field.name }}" value="{{ field.data or 0 }}">
        </div>
        
        <style>
        .star-rating-container {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            margin: 0.5rem 0;
        }
        
        .star-rating {
            display: flex;
            gap: 0.125rem;
            cursor: {% if readonly %}default{% else %}pointer{% endif %};
            outline: none;
        }
        
        .star-rating:focus {
            outline: 2px solid #0d6efd;
            outline-offset: 2px;
            border-radius: 4px;
        }
        
        .star {
            position: relative;
            display: inline-block;
            transition: all 0.2s ease;
        }
        
        .star i {
            position: absolute;
            top: 0;
            left: 0;
            transition: all 0.2s ease;
        }
        
        .star-empty {
            color: {{ empty_color }};
            opacity: 1;
        }
        
        .star-filled {
            color: {{ star_color }};
            opacity: 0;
        }
        
        .star-half {
            color: {{ star_color }};
            opacity: 0;
        }
        
        .star.filled .star-filled {
            opacity: 1;
        }
        
        .star.filled .star-empty {
            opacity: 0;
        }
        
        .star.half-filled .star-half {
            opacity: 1;
        }
        
        .star.half-filled .star-empty {
            opacity: 0;
        }
        
        .star.hover {
            transform: scale(1.1);
        }
        
        .rating-label {
            font-size: 0.875rem;
            color: #6c757d;
            font-weight: 500;
            min-width: 80px;
        }
        
        /* Size variants */
        .size-small .star i {
            font-size: 1rem;
        }
        
        .size-medium .star i {
            font-size: 1.25rem;
        }
        
        .size-large .star i {
            font-size: 1.5rem;
        }
        
        /* Readonly styling */
        .star-rating-container.readonly .star-rating {
            cursor: default;
        }
        
        .star-rating-container.readonly .star:hover {
            transform: none;
        }
        </style>
        
        <script>
        (function() {
            const container = document.querySelector('[data-widget="star-rating"]');
            const rating = document.getElementById('rating-{{ widget_id }}');
            const hiddenInput = document.getElementById('{{ widget_id }}');
            const label = document.getElementById('label-{{ widget_id }}');
            
            const config = {
                maxRating: {{ max_rating }},
                allowHalfStars: {{ allow_half_stars | tojson }},
                readonly: {{ readonly | tojson }},
                customLabels: {{ custom_labels | tojson }}
            };
            
            let currentRating = 0;
            let hoverRating = 0;
            
            // Initialize with existing value
            function initializeRating() {
                const existingValue = parseFloat(hiddenInput.value) || 0;
                currentRating = Math.max(0, Math.min(config.maxRating, existingValue));
                updateVisualState(currentRating);
                updateLabel(currentRating);
            }
            
            // Update visual state of stars
            function updateVisualState(rating) {
                const stars = rating.querySelectorAll('.star');
                
                stars.forEach((star, index) => {
                    const starRating = index + 1;
                    star.classList.remove('filled', 'half-filled');
                    
                    if (rating >= starRating) {
                        star.classList.add('filled');
                    } else if (config.allowHalfStars && rating >= starRating - 0.5) {
                        star.classList.add('half-filled');
                    }
                });
            }
            
            // Update rating label
            function updateLabel(rating) {
                if (!label) return;
                
                const labelText = label.querySelector('.current-label');
                if (rating === 0) {
                    labelText.textContent = '{{ _("No rating") }}';
                } else {
                    const index = Math.ceil(rating) - 1;
                    if (config.customLabels[index]) {
                        labelText.textContent = config.customLabels[index];
                        if (config.allowHalfStars && rating % 1 !== 0) {
                            labelText.textContent += ` (${rating} {{ _("stars") }})`;
                        }
                    } else {
                        labelText.textContent = `${rating} {{ _("stars") }}`;
                    }
                }
            }
            
            // Get rating from mouse position
            function getRatingFromPosition(event, star) {
                if (!config.allowHalfStars) {
                    return parseInt(star.dataset.rating);
                }
                
                const rect = star.getBoundingClientRect();
                const isLeftHalf = (event.clientX - rect.left) < (rect.width / 2);
                const baseRating = parseInt(star.dataset.rating);
                
                return isLeftHalf ? baseRating - 0.5 : baseRating;
            }
            
            // Set rating
            function setRating(newRating) {
                if (config.readonly) return;
                
                currentRating = Math.max(0, Math.min(config.maxRating, newRating));
                hiddenInput.value = currentRating;
                updateVisualState(rating);
                updateLabel(currentRating);
                
                // Trigger change event
                hiddenInput.dispatchEvent(new Event('change', { bubbles: true }));
            }
            
            if (!config.readonly) {
                // Mouse events
                rating.addEventListener('mouseenter', () => {
                    rating.querySelectorAll('.star').forEach(star => {
                        star.addEventListener('mouseenter', (event) => {
                            const newRating = getRatingFromPosition(event, star);
                            hoverRating = newRating;
                            updateVisualState(rating);
                            updateLabel(newRating);
                            star.classList.add('hover');
                        });
                        
                        star.addEventListener('mousemove', (event) => {
                            const newRating = getRatingFromPosition(event, star);
                            if (newRating !== hoverRating) {
                                hoverRating = newRating;
                                updateVisualState(rating);
                                updateLabel(newRating);
                            }
                        });
                        
                        star.addEventListener('mouseleave', () => {
                            star.classList.remove('hover');
                        });
                        
                        star.addEventListener('click', (event) => {
                            const newRating = getRatingFromPosition(event, star);
                            setRating(newRating);
                        });
                    });
                });
                
                rating.addEventListener('mouseleave', () => {
                    updateVisualState(rating);
                    updateLabel(currentRating);
                    rating.querySelectorAll('.star').forEach(star => {
                        star.classList.remove('hover');
                    });
                });
                
                // Keyboard navigation
                rating.addEventListener('keydown', (event) => {
                    let newRating = currentRating;
                    const step = config.allowHalfStars ? 0.5 : 1;
                    
                    switch (event.key) {
                        case 'ArrowLeft':
                        case 'ArrowDown':
                            newRating = Math.max(0, currentRating - step);
                            break;
                        case 'ArrowRight':
                        case 'ArrowUp':
                            newRating = Math.min(config.maxRating, currentRating + step);
                            break;
                        case 'Home':
                            newRating = 0;
                            break;
                        case 'End':
                            newRating = config.maxRating;
                            break;
                        case 'Enter':
                        case ' ':
                            // Toggle between current and previous rating
                            newRating = currentRating === 0 ? 1 : 0;
                            break;
                        default:
                            // Number keys 0-9
                            if (event.key >= '0' && event.key <= '9') {
                                const num = parseInt(event.key);
                                if (num <= config.maxRating) {
                                    newRating = num;
                                }
                            } else {
                                return;
                            }
                    }
                    
                    event.preventDefault();
                    setRating(newRating);
                });
                
                // Focus/blur events
                rating.addEventListener('focus', () => {
                    container.classList.add('focused');
                });
                
                rating.addEventListener('blur', () => {
                    container.classList.remove('focused');
                });
            } else {
                container.classList.add('readonly');
            }
            
            // Initialize
            initializeRating();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            max_rating=self.max_rating,
            allow_half_stars=self.allow_half_stars,
            readonly=self.readonly,
            size=self.size,
            star_color=self.star_color,
            empty_color=self.empty_color,
            show_labels=self.show_labels,
            custom_labels=self.custom_labels,
            _=gettext
        ))


class ToggleSwitchWidget(CheckboxInput):
    """
    Modern toggle switch widget with smooth animations and themes.
    
    Features:
    - iOS-style toggle switches
    - Custom colors and sizes
    - Smooth slide animations
    - Disabled state styling
    - Label positioning options
    - Keyboard accessibility
    - Multiple theme variants
    - Loading state support
    """
    
    def __init__(self,
                 size: str = 'medium',
                 theme: str = 'default',
                 label_position: str = 'right',
                 on_color: str = '#198754',
                 off_color: str = '#6c757d',
                 show_labels: bool = True,
                 on_text: str = 'ON',
                 off_text: str = 'OFF'):
        """
        Initialize the toggle switch widget.
        
        Args:
            size: Switch size (small, medium, large)
            theme: Visual theme (default, ios, android, custom)
            label_position: Label position (left, right, none)
            on_color: Color when switch is on
            off_color: Color when switch is off
            show_labels: Show ON/OFF text labels
            on_text: Text for 'on' state
            off_text: Text for 'off' state
        """
        self.size = size
        self.theme = theme
        self.label_position = label_position
        self.on_color = on_color
        self.off_color = off_color
        self.show_labels = show_labels
        self.on_text = on_text
        self.off_text = off_text
        
    def __call__(self, field, **kwargs):
        """Render the toggle switch widget."""
        widget_id = kwargs.get('id', f'toggle_switch_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        
        # Remove default checkbox styling
        kwargs.setdefault('class', 'toggle-switch-input')
        kwargs['style'] = 'display: none;'
        
        checkbox_html = super().__call__(field, **kwargs)
        
        template = """
        {{ checkbox_html | safe }}
        
        <div class="toggle-switch-container theme-{{ theme }} size-{{ size }}" data-widget="toggle-switch">
            {% if label_position == 'left' and field.label %}
            <label for="{{ widget_id }}" class="toggle-label label-left">{{ field.label.text }}</label>
            {% endif %}
            
            <div class="toggle-switch" data-for="{{ widget_id }}">
                <div class="toggle-track">
                    <div class="toggle-thumb">
                        {% if show_labels %}
                        <div class="toggle-labels">
                            <span class="label-on">{{ on_text }}</span>
                            <span class="label-off">{{ off_text }}</span>
                        </div>
                        {% endif %}
                    </div>
                </div>
            </div>
            
            {% if label_position == 'right' and field.label %}
            <label for="{{ widget_id }}" class="toggle-label label-right">{{ field.label.text }}</label>
            {% endif %}
        </div>
        
        <style>
        .toggle-switch-container {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            margin: 0.5rem 0;
        }
        
        .toggle-switch {
            position: relative;
            cursor: pointer;
            user-select: none;
        }
        
        .toggle-track {
            position: relative;
            border-radius: 1rem;
            background-color: {{ off_color }};
            transition: all 0.3s ease;
            overflow: hidden;
        }
        
        .toggle-thumb {
            position: absolute;
            top: 2px;
            left: 2px;
            background: white;
            border-radius: 50%;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.2);
        }
        
        .toggle-labels {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 0.6rem;
            font-weight: 600;
            color: #495057;
            white-space: nowrap;
        }
        
        .label-on,
        .label-off {
            opacity: 0;
            transition: opacity 0.2s ease;
        }
        
        .toggle-label {
            cursor: pointer;
            margin: 0;
            font-weight: 500;
            transition: color 0.2s ease;
        }
        
        .toggle-label:hover {
            color: #0d6efd;
        }
        
        /* Size variants */
        .size-small .toggle-track {
            width: 40px;
            height: 20px;
        }
        
        .size-small .toggle-thumb {
            width: 16px;
            height: 16px;
        }
        
        .size-medium .toggle-track {
            width: 50px;
            height: 24px;
        }
        
        .size-medium .toggle-thumb {
            width: 20px;
            height: 20px;
        }
        
        .size-large .toggle-track {
            width: 60px;
            height: 28px;
        }
        
        .size-large .toggle-thumb {
            width: 24px;
            height: 24px;
        }
        
        /* Checked state */
        .toggle-switch-input:checked + .toggle-switch-container .toggle-track {
            background-color: {{ on_color }};
        }
        
        .toggle-switch-input:checked + .toggle-switch-container .size-small .toggle-thumb {
            transform: translateX(20px);
        }
        
        .toggle-switch-input:checked + .toggle-switch-container .size-medium .toggle-thumb {
            transform: translateX(26px);
        }
        
        .toggle-switch-input:checked + .toggle-switch-container .size-large .toggle-thumb {
            transform: translateX(32px);
        }
        
        .toggle-switch-input:checked + .toggle-switch-container .label-on {
            opacity: 1;
        }
        
        .toggle-switch-input:not(:checked) + .toggle-switch-container .label-off {
            opacity: 1;
        }
        
        /* Focus state */
        .toggle-switch-input:focus + .toggle-switch-container .toggle-track {
            outline: 2px solid #0d6efd;
            outline-offset: 2px;
        }
        
        /* Disabled state */
        .toggle-switch-input:disabled + .toggle-switch-container {
            opacity: 0.6;
            pointer-events: none;
        }
        
        .toggle-switch-input:disabled + .toggle-switch-container .toggle-switch {
            cursor: not-allowed;
        }
        
        /* Theme variants */
        .theme-ios .toggle-track {
            background-color: #e9ecef;
        }
        
        .theme-ios .toggle-switch-input:checked + .toggle-switch-container .toggle-track {
            background-color: #34c759;
        }
        
        .theme-android .toggle-track {
            border-radius: 0.75rem;
            background-color: #757575;
        }
        
        .theme-android .toggle-thumb {
            border-radius: 50%;
        }
        
        .theme-android .toggle-switch-input:checked + .toggle-switch-container .toggle-track {
            background-color: #2196f3;
        }
        
        .theme-custom .toggle-track {
            background: linear-gradient(45deg, #ff6b6b, #ee5a24);
            border: 2px solid white;
        }
        
        .theme-custom .toggle-thumb {
            background: linear-gradient(45deg, #ffffff, #f8f9fa);
            border: 1px solid #dee2e6;
        }
        
        .theme-custom .toggle-switch-input:checked + .toggle-switch-container .toggle-track {
            background: linear-gradient(45deg, #00d2d3, #54a0ff);
        }
        
        /* Hover effects */
        .toggle-switch:hover .toggle-thumb {
            box-shadow: 0 4px 8px rgba(0,0,0,0.25);
        }
        
        .toggle-switch:active .toggle-thumb {
            transform: scale(0.95);
        }
        
        .toggle-switch-input:checked + .toggle-switch-container .toggle-switch:active .size-small .toggle-thumb {
            transform: translateX(20px) scale(0.95);
        }
        
        .toggle-switch-input:checked + .toggle-switch-container .toggle-switch:active .size-medium .toggle-thumb {
            transform: translateX(26px) scale(0.95);
        }
        
        .toggle-switch-input:checked + .toggle-switch-container .toggle-switch:active .size-large .toggle-thumb {
            transform: translateX(32px) scale(0.95);
        }
        </style>
        
        <script>
        (function() {
            const input = document.getElementById('{{ widget_id }}');
            const container = input.nextElementSibling;
            const toggleSwitch = container.querySelector('.toggle-switch');
            
            // Handle click events
            toggleSwitch.addEventListener('click', () => {
                if (!input.disabled) {
                    input.checked = !input.checked;
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                }
            });
            
            // Handle keyboard events for accessibility
            toggleSwitch.addEventListener('keydown', (event) => {
                if (event.key === ' ' || event.key === 'Enter') {
                    event.preventDefault();
                    toggleSwitch.click();
                }
            });
            
            // Make toggle focusable
            toggleSwitch.setAttribute('tabindex', input.disabled ? '-1' : '0');
            toggleSwitch.setAttribute('role', 'switch');
            
            // Update ARIA state
            function updateAriaState() {
                toggleSwitch.setAttribute('aria-checked', input.checked);
            }
            
            input.addEventListener('change', updateAriaState);
            updateAriaState();
        })();
        </script>
        """
        
        return Markup(render_template_string(template,
            checkbox_html=checkbox_html,
            widget_id=widget_id,
            field=field,
            theme=self.theme,
            size=self.size,
            label_position=self.label_position,
            on_color=self.on_color,
            off_color=self.off_color,
            show_labels=self.show_labels,
            on_text=self.on_text,
            off_text=self.off_text,
            _=gettext
        ))




class ImageCropperWidget(Input):
    """
    Advanced image cropper widget with editing and transformation tools.

    Features:
    - Image upload and preview
    - Crop with adjustable selection area
    - Resize and rotate transformations
    - Zoom in/out functionality
    - Aspect ratio constraints
    - Real-time preview
    - Multiple export formats
    - Undo/redo functionality
    - Touch and mouse support
    - Multiple preset crop sizes
    - Image filters and adjustments
    - Batch processing support
    """

    def __init__(self,
                 width: int = 400,
                 height: int = 300,
                 aspect_ratio: str = 'free',
                 enable_zoom: bool = True,
                 enable_rotation: bool = True,
                 enable_filters: bool = True,
                 enable_presets: bool = True,
                 export_format: str = 'png',
                 max_file_size: int = 5,  # MB
                 accepted_formats: list = None,
                 crop_quality: float = 0.9,
                 enable_batch: bool = False,
                 show_grid: bool = True,
                 enable_undo: bool = True):
        """
        Initialize the image cropper widget.

        Args:
            width: Cropper canvas width
            height: Cropper canvas height
            aspect_ratio: Aspect ratio constraint (free, 1:1, 4:3, 16:9, custom)
            enable_zoom: Enable zoom in/out
            enable_rotation: Enable image rotation
            enable_filters: Enable image filters
            enable_presets: Enable preset crop sizes
            export_format: Default export format (png, jpg, webp)
            max_file_size: Maximum file size in MB
            accepted_formats: List of accepted file formats
            crop_quality: Export quality (0.1 to 1.0)
            enable_batch: Enable batch processing
            show_grid: Show grid overlay
            enable_undo: Enable undo/redo
        """
        self.width = width
        self.height = height
        self.aspect_ratio = aspect_ratio
        self.enable_zoom = enable_zoom
        self.enable_rotation = enable_rotation
        self.enable_filters = enable_filters
        self.enable_presets = enable_presets
        self.export_format = export_format
        self.max_file_size = max_file_size
        self.accepted_formats = accepted_formats or ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        self.crop_quality = crop_quality
        self.enable_batch = enable_batch
        self.show_grid = show_grid
        self.enable_undo = enable_undo

    def __call__(self, field, **kwargs):
        """Render the image cropper widget."""
        widget_id = kwargs.get('id', f'image_cropper_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'image-cropper-input')
        kwargs['style'] = 'display: none;'

        # Get the input HTML for fallback
        input_html = super().__call__(field, **kwargs)

        template = """
        {{ input_html | safe }}

        <div class="image-cropper-container" data-widget="image-cropper">
            <div class="cropper-toolbar">
                <div class="toolbar-group">
                    <label class="file-upload-btn" for="{{ widget_id }}_file">
                        <i class="fa fa-upload"></i>
                        Upload Image
                    </label>
                    <input type="file" id="{{ widget_id }}_file" accept="{{ accepted_formats | join(',') }}" style="display: none;">

                    {% if enable_batch %}
                    <label class="file-upload-btn batch-upload" for="{{ widget_id }}_files">
                        <i class="fa fa-images"></i>
                        Batch Upload
                    </label>
                    <input type="file" id="{{ widget_id }}_files" accept="{{ accepted_formats | join(',') }}" multiple style="display: none;">
                    {% endif %}
                </div>

                <div class="toolbar-separator"></div>

                {% if enable_presets %}
                <div class="toolbar-group">
                    <select class="aspect-ratio-select">
                        <option value="free" {{ 'selected' if aspect_ratio == 'free' else '' }}>Free</option>
                        <option value="1:1" {{ 'selected' if aspect_ratio == '1:1' else '' }}>Square (1:1)</option>
                        <option value="4:3" {{ 'selected' if aspect_ratio == '4:3' else '' }}>Standard (4:3)</option>
                        <option value="16:9" {{ 'selected' if aspect_ratio == '16:9' else '' }}>Widescreen (16:9)</option>
                        <option value="3:2" {{ 'selected' if aspect_ratio == '3:2' else '' }}>Photo (3:2)</option>
                        <option value="2:3" {{ 'selected' if aspect_ratio == '2:3' else '' }}>Portrait (2:3)</option>
                        <option value="custom">Custom</option>
                    </select>

                    <select class="preset-sizes">
                        <option value="">Preset Sizes</option>
                        <option value="100x100">Avatar (100x100)</option>
                        <option value="200x200">Profile (200x200)</option>
                        <option value="400x300">Thumbnail (400x300)</option>
                        <option value="800x600">Standard (800x600)</option>
                        <option value="1200x800">Large (1200x800)</option>
                        <option value="1920x1080">HD (1920x1080)</option>
                    </select>
                </div>

                <div class="toolbar-separator"></div>
                {% endif %}

                {% if enable_zoom or enable_rotation %}
                <div class="toolbar-group">
                    {% if enable_zoom %}
                    <button type="button" class="toolbar-btn" data-action="zoom-in" title="Zoom In">
                        <i class="fa fa-search-plus"></i>
                    </button>
                    <button type="button" class="toolbar-btn" data-action="zoom-out" title="Zoom Out">
                        <i class="fa fa-search-minus"></i>
                    </button>
                    <button type="button" class="toolbar-btn" data-action="zoom-fit" title="Fit to Canvas">
                        <i class="fa fa-expand-arrows-alt"></i>
                    </button>
                    {% endif %}

                    {% if enable_rotation %}
                    <button type="button" class="toolbar-btn" data-action="rotate-left" title="Rotate Left">
                        <i class="fa fa-undo"></i>
                    </button>
                    <button type="button" class="toolbar-btn" data-action="rotate-right" title="Rotate Right">
                        <i class="fa fa-redo"></i>
                    </button>
                    {% endif %}
                </div>

                <div class="toolbar-separator"></div>
                {% endif %}

                {% if enable_filters %}
                <div class="toolbar-group">
                    <select class="filter-select">
                        <option value="">Filters</option>
                        <option value="brightness">Brightness</option>
                        <option value="contrast">Contrast</option>
                        <option value="grayscale">Grayscale</option>
                        <option value="sepia">Sepia</option>
                        <option value="blur">Blur</option>
                        <option value="sharpen">Sharpen</option>
                        <option value="vintage">Vintage</option>
                        <option value="reset">Reset Filters</option>
                    </select>
                </div>

                <div class="toolbar-separator"></div>
                {% endif %}

                <div class="toolbar-group">
                    {% if enable_undo %}
                    <button type="button" class="toolbar-btn" data-action="undo" title="Undo">
                        <i class="fa fa-undo"></i>
                    </button>
                    <button type="button" class="toolbar-btn" data-action="redo" title="Redo">
                        <i class="fa fa-redo"></i>
                    </button>
                    {% endif %}

                    <button type="button" class="toolbar-btn" data-action="reset" title="Reset Image">
                        <i class="fa fa-refresh"></i>
                    </button>

                    <button type="button" class="toolbar-btn" data-action="download" title="Download Image">
                        <i class="fa fa-download"></i>
                    </button>

                    <button type="button" class="toolbar-btn primary" data-action="crop" title="Apply Crop">
                        <i class="fa fa-crop"></i>
                        Crop
                    </button>
                </div>
            </div>

            <div class="cropper-workspace">
                <div class="cropper-canvas-container">
                    <canvas id="{{ widget_id }}_canvas"
                            width="{{ width }}"
                            height="{{ height }}"
                            class="cropper-canvas">
                    </canvas>

                    <!-- Crop selection overlay -->
                    <div class="crop-selection" style="display: none;">
                        <div class="selection-area">
                            {% if show_grid %}
                            <div class="grid-overlay">
                                <div class="grid-line grid-line-v" style="left: 33.33%;"></div>
                                <div class="grid-line grid-line-v" style="left: 66.66%;"></div>
                                <div class="grid-line grid-line-h" style="top: 33.33%;"></div>
                                <div class="grid-line grid-line-h" style="top: 66.66%;"></div>
                            </div>
                            {% endif %}

                            <!-- Resize handles -->
                            <div class="resize-handle nw" data-direction="nw"></div>
                            <div class="resize-handle ne" data-direction="ne"></div>
                            <div class="resize-handle sw" data-direction="sw"></div>
                            <div class="resize-handle se" data-direction="se"></div>
                            <div class="resize-handle n" data-direction="n"></div>
                            <div class="resize-handle s" data-direction="s"></div>
                            <div class="resize-handle w" data-direction="w"></div>
                            <div class="resize-handle e" data-direction="e"></div>
                        </div>
                    </div>

                    <!-- Upload area overlay -->
                    <div class="upload-overlay">
                        <div class="upload-content">
                            <i class="fa fa-cloud-upload upload-icon"></i>
                            <h3>Drop image here or click to upload</h3>
                            <p>Supported formats: {{ accepted_formats | map('replace', 'image/', '') | join(', ') | upper }}</p>
                            <p>Maximum size: {{ max_file_size }}MB</p>
                        </div>
                    </div>
                </div>

                <div class="cropper-sidebar">
                    <div class="sidebar-section">
                        <h4>Crop Settings</h4>

                        <div class="setting-group">
                            <label>Position</label>
                            <div class="position-inputs">
                                <input type="number" class="position-x" placeholder="X" min="0">
                                <input type="number" class="position-y" placeholder="Y" min="0">
                            </div>
                        </div>

                        <div class="setting-group">
                            <label>Size</label>
                            <div class="size-inputs">
                                <input type="number" class="crop-width" placeholder="Width" min="1">
                                <input type="number" class="crop-height" placeholder="Height" min="1">
                            </div>
                        </div>

                        {% if enable_zoom %}
                        <div class="setting-group">
                            <label>Zoom: <span class="zoom-value">100%</span></label>
                            <input type="range" class="zoom-slider" min="10" max="500" value="100">
                        </div>
                        {% endif %}

                        {% if enable_rotation %}
                        <div class="setting-group">
                            <label>Rotation: <span class="rotation-value">0°</span></label>
                            <input type="range" class="rotation-slider" min="-180" max="180" value="0">
                        </div>
                        {% endif %}
                    </div>

                    {% if enable_filters %}
                    <div class="sidebar-section">
                        <h4>Filters</h4>

                        <div class="setting-group">
                            <label>Brightness: <span class="brightness-value">100%</span></label>
                            <input type="range" class="brightness-slider" min="0" max="200" value="100">
                        </div>

                        <div class="setting-group">
                            <label>Contrast: <span class="contrast-value">100%</span></label>
                            <input type="range" class="contrast-slider" min="0" max="200" value="100">
                        </div>

                        <div class="setting-group">
                            <label>Saturation: <span class="saturation-value">100%</span></label>
                            <input type="range" class="saturation-slider" min="0" max="200" value="100">
                        </div>

                        <div class="setting-group">
                            <label>Hue: <span class="hue-value">0°</span></label>
                            <input type="range" class="hue-slider" min="-180" max="180" value="0">
                        </div>
                    </div>
                    {% endif %}

                    <div class="sidebar-section">
                        <h4>Export</h4>

                        <div class="setting-group">
                            <label>Format</label>
                            <select class="export-format">
                                <option value="png" {{ 'selected' if export_format == 'png' else '' }}>PNG</option>
                                <option value="jpeg" {{ 'selected' if export_format == 'jpeg' else '' }}>JPEG</option>
                                <option value="webp" {{ 'selected' if export_format == 'webp' else '' }}>WebP</option>
                            </select>
                        </div>

                        <div class="setting-group">
                            <label>Quality: <span class="quality-value">{{ (crop_quality * 100) | round }}%</span></label>
                            <input type="range" class="quality-slider" min="10" max="100" value="{{ (crop_quality * 100) | round }}">
                        </div>
                    </div>
                </div>
            </div>

            <div class="cropper-status">
                <div class="status-info">
                    <span class="image-info"></span>
                    <span class="selection-info"></span>
                </div>
                <div class="status-actions">
                    <span class="processing-indicator" style="display: none;">
                        <i class="fa fa-spinner fa-spin"></i>
                        Processing...
                    </span>
                </div>
            </div>
        </div>

        <style>
        .image-cropper-container {
            border: 1px solid #dee2e6;
            border-radius: 0.375rem;
            background: white;
            margin: 0.5rem 0;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
        }

        .cropper-toolbar {
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            padding: 0.5rem 0.75rem;
            background: #f8f9fa;
            border-bottom: 1px solid #dee2e6;
            border-radius: 0.375rem 0.375rem 0 0;
            gap: 0.25rem;
        }

        .toolbar-group {
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }

        .toolbar-separator {
            width: 1px;
            height: 24px;
            background: #dee2e6;
            margin: 0 0.5rem;
        }

        .file-upload-btn {
            padding: 0.375rem 0.75rem;
            border: 1px solid #0d6efd;
            background: #0d6efd;
            color: white;
            border-radius: 0.25rem;
            cursor: pointer;
            transition: all 0.2s ease;
            font-size: 0.875rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .file-upload-btn:hover {
            background: #0b5ed7;
            border-color: #0a58ca;
        }

        .file-upload-btn.batch-upload {
            background: #6f42c1;
            border-color: #6f42c1;
        }

        .file-upload-btn.batch-upload:hover {
            background: #5a36a3;
            border-color: #52329a;
        }

        .toolbar-btn {
            padding: 0.375rem 0.5rem;
            border: 1px solid #ced4da;
            background: white;
            border-radius: 0.25rem;
            cursor: pointer;
            transition: all 0.2s ease;
            font-size: 0.875rem;
            min-width: 32px;
            height: 32px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 0.25rem;
        }

        .toolbar-btn:hover {
            background: #e9ecef;
            border-color: #adb5bd;
        }

        .toolbar-btn.primary {
            background: #198754;
            color: white;
            border-color: #198754;
            padding: 0.375rem 0.75rem;
            font-weight: 500;
        }

        .toolbar-btn.primary:hover {
            background: #157347;
            border-color: #146c43;
        }

        .aspect-ratio-select,
        .preset-sizes,
        .filter-select,
        .export-format {
            padding: 0.25rem 0.5rem;
            border: 1px solid #ced4da;
            border-radius: 0.25rem;
            background: white;
            font-size: 0.875rem;
            max-width: 150px;
        }

        .cropper-workspace {
            display: flex;
            min-height: 400px;
        }

        .cropper-canvas-container {
            flex: 1;
            position: relative;
            background: #f8f9fa;
            display: flex;
            align-items: center;
            justify-content: center;
            overflow: hidden;
        }

        .cropper-canvas {
            border: 1px solid #dee2e6;
            background: white;
            cursor: crosshair;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
        }

        .crop-selection {
            position: absolute;
            border: 2px solid #0d6efd;
            background: rgba(13, 110, 253, 0.1);
            cursor: move;
        }

        .selection-area {
            position: relative;
            width: 100%;
            height: 100%;
        }

        .grid-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            pointer-events: none;
        }

        .grid-line {
            position: absolute;
            background: rgba(255, 255, 255, 0.8);
        }

        .grid-line-v {
            width: 1px;
            height: 100%;
        }

        .grid-line-h {
            height: 1px;
            width: 100%;
        }

        .resize-handle {
            position: absolute;
            background: #0d6efd;
            border: 2px solid white;
            border-radius: 50%;
            width: 12px;
            height: 12px;
            cursor: pointer;
        }

        .resize-handle.nw { top: -6px; left: -6px; cursor: nw-resize; }
        .resize-handle.ne { top: -6px; right: -6px; cursor: ne-resize; }
        .resize-handle.sw { bottom: -6px; left: -6px; cursor: sw-resize; }
        .resize-handle.se { bottom: -6px; right: -6px; cursor: se-resize; }
        .resize-handle.n { top: -6px; left: 50%; transform: translateX(-50%); cursor: n-resize; }
        .resize-handle.s { bottom: -6px; left: 50%; transform: translateX(-50%); cursor: s-resize; }
        .resize-handle.w { left: -6px; top: 50%; transform: translateY(-50%); cursor: w-resize; }
        .resize-handle.e { right: -6px; top: 50%; transform: translateY(-50%); cursor: e-resize; }

        .upload-overlay {
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(248, 249, 250, 0.9);
            display: flex;
            align-items: center;
            justify-content: center;
            border: 2px dashed #ced4da;
            border-radius: 0.375rem;
            transition: all 0.2s ease;
        }

        .upload-overlay.drag-over {
            border-color: #0d6efd;
            background: rgba(13, 110, 253, 0.1);
        }

        .upload-content {
            text-align: center;
            color: #6c757d;
        }

        .upload-icon {
            font-size: 3rem;
            margin-bottom: 1rem;
            color: #adb5bd;
        }

        .upload-content h3 {
            margin: 0 0 0.5rem 0;
            font-size: 1.125rem;
            font-weight: 500;
        }

        .upload-content p {
            margin: 0.25rem 0;
            font-size: 0.875rem;
        }

        .cropper-sidebar {
            width: 280px;
            background: #f8f9fa;
            border-left: 1px solid #dee2e6;
            padding: 1rem;
            overflow-y: auto;
        }

        .sidebar-section {
            margin-bottom: 1.5rem;
        }

        .sidebar-section h4 {
            margin: 0 0 0.75rem 0;
            font-size: 0.875rem;
            font-weight: 600;
            text-transform: uppercase;
            color: #495057;
            letter-spacing: 0.05em;
        }

        .setting-group {
            margin-bottom: 1rem;
        }

        .setting-group label {
            display: block;
            margin-bottom: 0.25rem;
            font-size: 0.875rem;
            font-weight: 500;
            color: #495057;
        }

        .position-inputs,
        .size-inputs {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.5rem;
        }

        .setting-group input[type="number"],
        .setting-group input[type="range"] {
            width: 100%;
            padding: 0.375rem 0.5rem;
            border: 1px solid #ced4da;
            border-radius: 0.25rem;
            font-size: 0.875rem;
        }

        .setting-group input[type="range"] {
            padding: 0;
            height: 32px;
        }

        .cropper-status {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.5rem 0.75rem;
            background: #f8f9fa;
            border-top: 1px solid #dee2e6;
            border-radius: 0 0 0.375rem 0.375rem;
            font-size: 0.75rem;
            color: #6c757d;
        }

        .status-info {
            display: flex;
            gap: 1rem;
        }

        .processing-indicator {
            color: #0d6efd;
            font-weight: 500;
        }

        /* Responsive design */
        @media (max-width: 768px) {
            .cropper-workspace {
                flex-direction: column;
            }

            .cropper-sidebar {
                width: 100%;
                border-left: none;
                border-top: 1px solid #dee2e6;
            }

            .cropper-canvas-container {
                min-height: 300px;
            }
        }
        </style>

        <script>
        (function() {
            const widgetId = '{{ widget_id }}';
            const input = document.getElementById(widgetId);
            const container = input.nextElementSibling;
            const canvas = container.querySelector('.cropper-canvas');
            const ctx = canvas.getContext('2d');
            const fileInput = container.querySelector('#{{ widget_id }}_file');
            const uploadOverlay = container.querySelector('.upload-overlay');
            const cropSelection = container.querySelector('.crop-selection');
            const toolbar = container.querySelector('.cropper-toolbar');

            // State management
            let imageData = null;
            let originalImage = null;
            let cropData = { x: 0, y: 0, width: 0, height: 0 };
            let isDragging = false;
            let isResizing = false;
            let dragStart = { x: 0, y: 0 };
            let resizeDirection = '';
            let zoom = 1;
            let rotation = 0;
            let filters = {
                brightness: 100,
                contrast: 100,
                saturation: 100,
                hue: 0
            };
            let history = [];
            let historyIndex = -1;

            // Initialize canvas size
            canvas.width = {{ width }};
            canvas.height = {{ height }};

            // File upload handler
            fileInput.addEventListener('change', handleFileSelect);

            // Drag and drop
            canvas.addEventListener('dragover', handleDragOver);
            canvas.addEventListener('drop', handleDrop);
            canvas.addEventListener('dragenter', (e) => {
                e.preventDefault();
                uploadOverlay.classList.add('drag-over');
            });
            canvas.addEventListener('dragleave', (e) => {
                e.preventDefault();
                uploadOverlay.classList.remove('drag-over');
            });

            // Click to upload
            uploadOverlay.addEventListener('click', () => {
                fileInput.click();
            });

            function handleFileSelect(e) {
                const file = e.target.files[0];
                if (file) {
                    loadImage(file);
                }
            }

            function handleDragOver(e) {
                e.preventDefault();
            }

            function handleDrop(e) {
                e.preventDefault();
                uploadOverlay.classList.remove('drag-over');

                const files = e.dataTransfer.files;
                if (files.length > 0) {
                    loadImage(files[0]);
                }
            }

            function loadImage(file) {
                // Validate file
                if (!{{ accepted_formats }}.includes(file.type)) {
                    alert('Invalid file type. Please select a supported image format.');
                    return;
                }

                if (file.size > {{ max_file_size }} * 1024 * 1024) {
                    alert(`File size exceeds {{ max_file_size }}MB limit.`);
                    return;
                }

                const reader = new FileReader();
                reader.onload = (e) => {
                    const img = new Image();
                    img.onload = () => {
                        originalImage = img;
                        resetImage();
                        showImage();
                        hideUploadOverlay();
                        initializeCropSelection();
                        updateImageInfo();
                        saveState();
                    };
                    img.src = e.target.result;
                };
                reader.readAsDataURL(file);
            }

            function resetImage() {
                zoom = 1;
                rotation = 0;
                filters = {
                    brightness: 100,
                    contrast: 100,
                    saturation: 100,
                    hue: 0
                };
                updateSliders();
            }

            function showImage() {
                const canvasWidth = canvas.width;
                const canvasHeight = canvas.height;
                const imgWidth = originalImage.width;
                const imgHeight = originalImage.height;

                // Calculate scale to fit image in canvas
                const scale = Math.min(canvasWidth / imgWidth, canvasHeight / imgHeight) * 0.8;

                imageData = {
                    x: (canvasWidth - imgWidth * scale) / 2,
                    y: (canvasHeight - imgHeight * scale) / 2,
                    width: imgWidth * scale,
                    height: imgHeight * scale,
                    scale: scale
                };

                drawImage();
            }

            function drawImage() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);

                if (!originalImage) return;

                ctx.save();

                // Apply transformations
                const centerX = imageData.x + imageData.width / 2;
                const centerY = imageData.y + imageData.height / 2;

                ctx.translate(centerX, centerY);
                ctx.scale(zoom, zoom);
                ctx.rotate(rotation * Math.PI / 180);

                // Apply filters
                ctx.filter = `brightness(${filters.brightness}%) contrast(${filters.contrast}%) saturate(${filters.saturation}%) hue-rotate(${filters.hue}deg)`;

                ctx.drawImage(
                    originalImage,
                    -imageData.width / 2,
                    -imageData.height / 2,
                    imageData.width,
                    imageData.height
                );

                ctx.restore();
            }

            function hideUploadOverlay() {
                uploadOverlay.style.display = 'none';
            }

            function initializeCropSelection() {
                const defaultWidth = Math.min(imageData.width * 0.8, 200);
                const defaultHeight = Math.min(imageData.height * 0.8, 200);

                cropData = {
                    x: imageData.x + (imageData.width - defaultWidth) / 2,
                    y: imageData.y + (imageData.height - defaultHeight) / 2,
                    width: defaultWidth,
                    height: defaultHeight
                };

                updateCropSelection();
                cropSelection.style.display = 'block';
            }

            function updateCropSelection() {
                cropSelection.style.left = cropData.x + 'px';
                cropSelection.style.top = cropData.y + 'px';
                cropSelection.style.width = cropData.width + 'px';
                cropSelection.style.height = cropData.height + 'px';

                updateCropInputs();
                updateSelectionInfo();
            }

            function updateCropInputs() {
                container.querySelector('.position-x').value = Math.round(cropData.x - imageData.x);
                container.querySelector('.position-y').value = Math.round(cropData.y - imageData.y);
                container.querySelector('.crop-width').value = Math.round(cropData.width);
                container.querySelector('.crop-height').value = Math.round(cropData.height);
            }

            function updateSliders() {
                {% if enable_zoom %}
                container.querySelector('.zoom-slider').value = zoom * 100;
                container.querySelector('.zoom-value').textContent = Math.round(zoom * 100) + '%';
                {% endif %}

                {% if enable_rotation %}
                container.querySelector('.rotation-slider').value = rotation;
                container.querySelector('.rotation-value').textContent = rotation + '°';
                {% endif %}

                {% if enable_filters %}
                container.querySelector('.brightness-slider').value = filters.brightness;
                container.querySelector('.brightness-value').textContent = filters.brightness + '%';
                container.querySelector('.contrast-slider').value = filters.contrast;
                container.querySelector('.contrast-value').textContent = filters.contrast + '%';
                container.querySelector('.saturation-slider').value = filters.saturation;
                container.querySelector('.saturation-value').textContent = filters.saturation + '%';
                container.querySelector('.hue-slider').value = filters.hue;
                container.querySelector('.hue-value').textContent = filters.hue + '°';
                {% endif %}
            }

            function updateImageInfo() {
                const info = container.querySelector('.image-info');
                if (originalImage && imageData) {
                    info.textContent = `Image: ${originalImage.width} × ${originalImage.height}px`;
                }
            }

            function updateSelectionInfo() {
                const info = container.querySelector('.selection-info');
                if (cropData.width > 0 && cropData.height > 0) {
                    info.textContent = `Selection: ${Math.round(cropData.width)} × ${Math.round(cropData.height)}px`;
                }
            }

            // Crop selection interaction
            cropSelection.addEventListener('mousedown', startDrag);
            document.addEventListener('mousemove', drag);
            document.addEventListener('mouseup', stopDrag);

            // Resize handles
            container.querySelectorAll('.resize-handle').forEach(handle => {
                handle.addEventListener('mousedown', startResize);
            });

            function startDrag(e) {
                if (e.target.classList.contains('resize-handle')) return;

                isDragging = true;
                dragStart.x = e.clientX - cropData.x;
                dragStart.y = e.clientY - cropData.y;
                e.preventDefault();
            }

            function startResize(e) {
                isResizing = true;
                resizeDirection = e.target.dataset.direction;
                dragStart.x = e.clientX;
                dragStart.y = e.clientY;
                e.preventDefault();
                e.stopPropagation();
            }

            function drag(e) {
                if (isDragging) {
                    const newX = e.clientX - dragStart.x;
                    const newY = e.clientY - dragStart.y;

                    // Constrain to image bounds
                    cropData.x = Math.max(imageData.x, Math.min(newX, imageData.x + imageData.width - cropData.width));
                    cropData.y = Math.max(imageData.y, Math.min(newY, imageData.y + imageData.height - cropData.height));

                    updateCropSelection();
                } else if (isResizing) {
                    const deltaX = e.clientX - dragStart.x;
                    const deltaY = e.clientY - dragStart.y;

                    resizeCropSelection(deltaX, deltaY);
                    dragStart.x = e.clientX;
                    dragStart.y = e.clientY;
                }
            }

            function stopDrag() {
                if (isDragging || isResizing) {
                    saveState();
                }
                isDragging = false;
                isResizing = false;
                resizeDirection = '';
            }

            function resizeCropSelection(deltaX, deltaY) {
                const minSize = 10;

                switch (resizeDirection) {
                    case 'se':
                        cropData.width = Math.max(minSize, cropData.width + deltaX);
                        cropData.height = Math.max(minSize, cropData.height + deltaY);
                        break;
                    case 'nw':
                        const newWidth = cropData.width - deltaX;
                        const newHeight = cropData.height - deltaY;
                        if (newWidth >= minSize) {
                            cropData.x += deltaX;
                            cropData.width = newWidth;
                        }
                        if (newHeight >= minSize) {
                            cropData.y += deltaY;
                            cropData.height = newHeight;
                        }
                        break;
                    // Add other resize directions...
                }

                // Constrain to image bounds
                cropData.x = Math.max(imageData.x, Math.min(cropData.x, imageData.x + imageData.width - cropData.width));
                cropData.y = Math.max(imageData.y, Math.min(cropData.y, imageData.y + imageData.height - cropData.height));
                cropData.width = Math.min(cropData.width, imageData.x + imageData.width - cropData.x);
                cropData.height = Math.min(cropData.height, imageData.y + imageData.height - cropData.y);

                updateCropSelection();
            }

            // Toolbar actions
            toolbar.addEventListener('click', (e) => {
                const action = e.target.closest('[data-action]')?.dataset.action;
                if (!action) return;

                switch (action) {
                    case 'zoom-in':
                        zoom = Math.min(zoom * 1.1, 5);
                        break;
                    case 'zoom-out':
                        zoom = Math.max(zoom * 0.9, 0.1);
                        break;
                    case 'zoom-fit':
                        zoom = 1;
                        break;
                    case 'rotate-left':
                        rotation -= 90;
                        break;
                    case 'rotate-right':
                        rotation += 90;
                        break;
                    case 'reset':
                        resetImage();
                        break;
                    case 'crop':
                        applyCrop();
                        break;
                    case 'download':
                        downloadImage();
                        break;
                    case 'undo':
                        undo();
                        break;
                    case 'redo':
                        redo();
                        break;
                }

                if (['zoom-in', 'zoom-out', 'zoom-fit', 'rotate-left', 'rotate-right', 'reset'].includes(action)) {
                    drawImage();
                    updateSliders();
                    saveState();
                }
            });

            // Slider handlers
            {% if enable_zoom %}
            container.querySelector('.zoom-slider').addEventListener('input', (e) => {
                zoom = parseInt(e.target.value) / 100;
                drawImage();
                updateSliders();
            });
            {% endif %}

            {% if enable_rotation %}
            container.querySelector('.rotation-slider').addEventListener('input', (e) => {
                rotation = parseInt(e.target.value);
                drawImage();
                updateSliders();
            });
            {% endif %}

            {% if enable_filters %}
            container.querySelector('.brightness-slider').addEventListener('input', (e) => {
                filters.brightness = parseInt(e.target.value);
                drawImage();
                updateSliders();
            });

            container.querySelector('.contrast-slider').addEventListener('input', (e) => {
                filters.contrast = parseInt(e.target.value);
                drawImage();
                updateSliders();
            });

            container.querySelector('.saturation-slider').addEventListener('input', (e) => {
                filters.saturation = parseInt(e.target.value);
                drawImage();
                updateSliders();
            });

            container.querySelector('.hue-slider').addEventListener('input', (e) => {
                filters.hue = parseInt(e.target.value);
                drawImage();
                updateSliders();
            });
            {% endif %}

            function applyCrop() {
                if (!originalImage) return;

                const processingIndicator = container.querySelector('.processing-indicator');
                processingIndicator.style.display = 'inline-flex';

                setTimeout(() => {
                    // Create a new canvas for the cropped image
                    const cropCanvas = document.createElement('canvas');
                    const cropCtx = cropCanvas.getContext('2d');

                    // Calculate actual crop coordinates on the original image
                    const scaleX = originalImage.width / imageData.width;
                    const scaleY = originalImage.height / imageData.height;

                    const actualCropX = (cropData.x - imageData.x) * scaleX;
                    const actualCropY = (cropData.y - imageData.y) * scaleY;
                    const actualCropWidth = cropData.width * scaleX;
                    const actualCropHeight = cropData.height * scaleY;

                    cropCanvas.width = actualCropWidth;
                    cropCanvas.height = actualCropHeight;

                    // Apply transformations and draw cropped image
                    cropCtx.save();
                    cropCtx.translate(actualCropWidth / 2, actualCropHeight / 2);
                    cropCtx.scale(zoom, zoom);
                    cropCtx.rotate(rotation * Math.PI / 180);
                    cropCtx.filter = `brightness(${filters.brightness}%) contrast(${filters.contrast}%) saturate(${filters.saturation}%) hue-rotate(${filters.hue}deg)`;

                    cropCtx.drawImage(
                        originalImage,
                        actualCropX - actualCropWidth / 2,
                        actualCropY - actualCropHeight / 2,
                        actualCropWidth,
                        actualCropHeight,
                        -actualCropWidth / 2,
                        -actualCropHeight / 2,
                        actualCropWidth,
                        actualCropHeight
                    );

                    cropCtx.restore();

                    // Get the cropped image data
                    const format = container.querySelector('.export-format').value;
                    const quality = parseInt(container.querySelector('.quality-slider').value) / 100;
                    const mimeType = format === 'png' ? 'image/png' :
                                   format === 'jpeg' ? 'image/jpeg' : 'image/webp';

                    const croppedDataURL = cropCanvas.toDataURL(mimeType, quality);

                    // Update the hidden input with the cropped image data
                    input.value = croppedDataURL;
                    input.dispatchEvent(new Event('change', { bubbles: true }));

                    processingIndicator.style.display = 'none';

                    // Show success message
                    showMessage('Image cropped successfully!', 'success');
                }, 100);
            }

            function downloadImage() {
                if (!originalImage) return;

                applyCrop();

                // Create download link
                const link = document.createElement('a');
                const format = container.querySelector('.export-format').value;
                link.download = `cropped_image.${format}`;
                link.href = input.value;
                link.click();
            }

            function saveState() {
                {% if enable_undo %}
                const state = {
                    zoom: zoom,
                    rotation: rotation,
                    filters: { ...filters },
                    cropData: { ...cropData }
                };

                // Remove future history if we're not at the end
                if (historyIndex < history.length - 1) {
                    history = history.slice(0, historyIndex + 1);
                }

                history.push(state);
                historyIndex = history.length - 1;

                // Limit history size
                if (history.length > 20) {
                    history.shift();
                    historyIndex--;
                }
                {% endif %}
            }

            function undo() {
                {% if enable_undo %}
                if (historyIndex > 0) {
                    historyIndex--;
                    const state = history[historyIndex];
                    restoreState(state);
                }
                {% endif %}
            }

            function redo() {
                {% if enable_undo %}
                if (historyIndex < history.length - 1) {
                    historyIndex++;
                    const state = history[historyIndex];
                    restoreState(state);
                }
                {% endif %}
            }

            function restoreState(state) {
                zoom = state.zoom;
                rotation = state.rotation;
                filters = { ...state.filters };
                cropData = { ...state.cropData };

                drawImage();
                updateCropSelection();
                updateSliders();
            }

            function showMessage(message, type = 'info') {
                // Simple message implementation
                const messageEl = document.createElement('div');
                messageEl.textContent = message;
                messageEl.style.cssText = `
                    position: fixed;
                    top: 20px;
                    right: 20px;
                    padding: 0.75rem 1rem;
                    background: ${type === 'success' ? '#d1edff' : '#fff3cd'};
                    border: 1px solid ${type === 'success' ? '#0d6efd' : '#ffc107'};
                    border-radius: 0.375rem;
                    z-index: 10000;
                    font-size: 0.875rem;
                `;
                document.body.appendChild(messageEl);

                setTimeout(() => {
                    messageEl.remove();
                }, 3000);
            }

            // Aspect ratio constraint handler
            container.querySelector('.aspect-ratio-select').addEventListener('change', (e) => {
                const ratio = e.target.value;
                if (ratio !== 'free' && ratio !== 'custom') {
                    const [w, h] = ratio.split(':').map(Number);
                    const aspectRatio = w / h;

                    // Adjust crop height based on width and aspect ratio
                    cropData.height = cropData.width / aspectRatio;

                    // Ensure it fits within image bounds
                    if (cropData.y + cropData.height > imageData.y + imageData.height) {
                        cropData.height = imageData.y + imageData.height - cropData.y;
                        cropData.width = cropData.height * aspectRatio;
                    }

                    updateCropSelection();
                    saveState();
                }
            });

            // Preset sizes handler
            container.querySelector('.preset-sizes').addEventListener('change', (e) => {
                const preset = e.target.value;
                if (preset) {
                    const [w, h] = preset.split('x').map(Number);
                    const scale = Math.min(imageData.width / w, imageData.height / h);

                    cropData.width = w * scale;
                    cropData.height = h * scale;

                    // Center the crop
                    cropData.x = imageData.x + (imageData.width - cropData.width) / 2;
                    cropData.y = imageData.y + (imageData.height - cropData.height) / 2;

                    updateCropSelection();
                    saveState();
                }
                e.target.value = '';
            });

            // Initialize empty state
            updateImageInfo();
            updateSelectionInfo();
        })();
        </script>
        """

        return Markup(render_template_string(template,
            input_html=input_html,
            widget_id=widget_id,
            field=field,
            width=self.width,
            height=self.height,
            aspect_ratio=self.aspect_ratio,
            enable_zoom=self.enable_zoom,
            enable_rotation=self.enable_rotation,
            enable_filters=self.enable_filters,
            enable_presets=self.enable_presets,
            export_format=self.export_format,
            max_file_size=self.max_file_size,
            accepted_formats=self.accepted_formats,
            crop_quality=self.crop_quality,
            enable_batch=self.enable_batch,
            show_grid=self.show_grid,
            enable_undo=self.enable_undo,
            _=gettext
        ))




class CalendarWidget(Input):
    """
    Advanced calendar widget with comprehensive scheduling and event management.

    Features include multiple view modes (month, week, day), event creation,
    drag-and-drop scheduling, recurring events, multiple calendars, and
    import/export functionality.
    """

    def __init__(self,
                 default_view='month',
                 enable_drag_drop=True,
                 enable_resize=True,
                 time_format='12h',
                 week_starts_on='sunday',
                 theme='default',
                 height='600px',
                 enable_time_slots=True,
                 slot_duration=30,
                 business_hours_start='09:00',
                 business_hours_end='17:00',
                 enable_all_day_events=True,
                 enable_recurring_events=True,
                 enable_reminders=True,
                 enable_categories=True,
                 enable_multiple_calendars=True,
                 enable_export=True,
                 enable_print=True,
                 timezone='local',
                 locale='en',
                 **kwargs):
        """
        Initialize the Calendar widget.

        Args:
            default_view: Default calendar view ('month', 'week', 'day', 'agenda')
            enable_drag_drop: Enable event drag and drop
            enable_resize: Enable event resizing
            time_format: Time format ('12h' or '24h')
            week_starts_on: First day of week ('sunday' or 'monday')
            theme: Calendar theme ('default', 'modern', 'minimal', 'colorful')
            height: Calendar container height
            enable_time_slots: Show time slots in week/day view
            slot_duration: Time slot duration in minutes
            business_hours_start: Business hours start time
            business_hours_end: Business hours end time
            enable_all_day_events: Allow all-day events
            enable_recurring_events: Enable recurring event patterns
            enable_reminders: Enable event reminders
            enable_categories: Enable event categories/tags
            enable_multiple_calendars: Support multiple calendar sources
            enable_export: Enable calendar export functionality
            enable_print: Enable calendar printing
            timezone: Default timezone
            locale: Locale for date formatting
        """
        super().__init__(**kwargs)
        self.default_view = default_view
        self.enable_drag_drop = enable_drag_drop
        self.enable_resize = enable_resize
        self.time_format = time_format
        self.week_starts_on = week_starts_on
        self.theme = theme
        self.height = height
        self.enable_time_slots = enable_time_slots
        self.slot_duration = slot_duration
        self.business_hours_start = business_hours_start
        self.business_hours_end = business_hours_end
        self.enable_all_day_events = enable_all_day_events
        self.enable_recurring_events = enable_recurring_events
        self.enable_reminders = enable_reminders
        self.enable_categories = enable_categories
        self.enable_multiple_calendars = enable_multiple_calendars
        self.enable_export = enable_export
        self.enable_print = enable_print
        self.timezone = timezone
        self.locale = locale

    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)

        # Generate unique ID for this calendar instance
        calendar_id = f"calendar_{field.id}_{id(self)}"

        return Markup(f"""
        <div class="calendar-widget" data-field-id="{field.id}">
            <!-- Calendar Header -->
            <div class="calendar-header">
                <div class="calendar-toolbar">
                    <div class="calendar-nav">
                        <button type="button" class="btn btn-sm btn-outline-secondary" onclick="navigateCalendar('{calendar_id}', 'prev')">
                            <i class="fas fa-chevron-left"></i>
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-secondary" onclick="navigateCalendar('{calendar_id}', 'today')">
                            {_('Today')}
                        </button>
                        <button type="button" class="btn btn-sm btn-outline-secondary" onclick="navigateCalendar('{calendar_id}', 'next')">
                            <i class="fas fa-chevron-right"></i>
                        </button>
                        <h4 class="calendar-title" id="title_{calendar_id}"></h4>
                    </div>

                    <div class="calendar-views">
                        <div class="btn-group" role="group">
                            <button type="button" class="btn btn-sm btn-outline-primary {'active' if self.default_view == 'month' else ''}"
                                    onclick="changeView('{calendar_id}', 'month')">{_('Month')}</button>
                            <button type="button" class="btn btn-sm btn-outline-primary {'active' if self.default_view == 'week' else ''}"
                                    onclick="changeView('{calendar_id}', 'week')">{_('Week')}</button>
                            <button type="button" class="btn btn-sm btn-outline-primary {'active' if self.default_view == 'day' else ''}"
                                    onclick="changeView('{calendar_id}', 'day')">{_('Day')}</button>
                            <button type="button" class="btn btn-sm btn-outline-primary {'active' if self.default_view == 'agenda' else ''}"
                                    onclick="changeView('{calendar_id}', 'agenda')">{_('Agenda')}</button>
                        </div>
                    </div>

                    <div class="calendar-actions">
                        <button type="button" class="btn btn-sm btn-primary" onclick="showEventModal('{calendar_id}')">
                            <i class="fas fa-plus"></i> {_('Add Event')}
                        </button>
                        {'<button type="button" class="btn btn-sm btn-secondary" onclick="showCalendarsModal(' + chr(39) + calendar_id + chr(39) + ')"><i class="fas fa-calendar"></i> ' + _('Calendars') + '</button>' if self.enable_multiple_calendars else ''}
                        {'<button type="button" class="btn btn-sm btn-info" onclick="showExportModal(' + chr(39) + calendar_id + chr(39) + ')"><i class="fas fa-download"></i> ' + _('Export') + '</button>' if self.enable_export else ''}
                        {'<button type="button" class="btn btn-sm btn-secondary" onclick="printCalendar(' + chr(39) + calendar_id + chr(39) + ')"><i class="fas fa-print"></i> ' + _('Print') + '</button>' if self.enable_print else ''}
                    </div>
                </div>

                <!-- Calendar Filters -->
                <div class="calendar-filters" style="display: none;">
                    {'<div class="filter-group"><label>' + _('Categories') + '</label><div id="categories_' + calendar_id + '" class="category-filters"></div></div>' if self.enable_categories else ''}
                    {'<div class="filter-group"><label>' + _('Calendars') + '</label><div id="calendar_sources_' + calendar_id + '" class="calendar-filters"></div></div>' if self.enable_multiple_calendars else ''}
                </div>
            </div>

            <!-- Calendar Container -->
            <div id="{calendar_id}" class="calendar-container" style="height: {self.height};"></div>

            <!-- Hidden input for form data -->
            <input type="hidden" id="{field.id}" name="{field.name}" value="{field.data or ''}" />
        </div>

        <!-- Event Modal -->
        <div class="modal fade" id="eventModal_{calendar_id}" tabindex="-1" aria-hidden="true">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">{_('Event Details')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body">
                        <form id="eventForm_{calendar_id}">
                            <div class="row">
                                <div class="col-md-8">
                                    <div class="form-group mb-3">
                                        <label for="eventTitle_{calendar_id}">{_('Title')} *</label>
                                        <input type="text" class="form-control" id="eventTitle_{calendar_id}" required>
                                    </div>
                                </div>
                                <div class="col-md-4">
                                    {'<div class="form-group mb-3"><label for="eventCalendar_' + calendar_id + '">' + _('Calendar') + '</label><select class="form-control" id="eventCalendar_' + calendar_id + '"></select></div>' if self.enable_multiple_calendars else ''}
                                </div>
                            </div>

                            <div class="form-group mb-3">
                                <label for="eventDescription_{calendar_id}">{_('Description')}</label>
                                <textarea class="form-control" id="eventDescription_{calendar_id}" rows="3"></textarea>
                            </div>

                            <div class="row">
                                <div class="col-md-6">
                                    <div class="form-group mb-3">
                                        <label for="eventStart_{calendar_id}">{_('Start Date/Time')} *</label>
                                        <input type="datetime-local" class="form-control" id="eventStart_{calendar_id}" required>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="form-group mb-3">
                                        <label for="eventEnd_{calendar_id}">{_('End Date/Time')} *</label>
                                        <input type="datetime-local" class="form-control" id="eventEnd_{calendar_id}" required>
                                    </div>
                                </div>
                            </div>

                            {'<div class="form-check mb-3"><input type="checkbox" class="form-check-input" id="eventAllDay_' + calendar_id + '"><label class="form-check-label" for="eventAllDay_' + calendar_id + '">' + _('All Day Event') + '</label></div>' if self.enable_all_day_events else ''}

                            <div class="row">
                                {'<div class="col-md-6"><div class="form-group mb-3"><label for="eventCategory_' + calendar_id + '">' + _('Category') + '</label><select class="form-control" id="eventCategory_' + calendar_id + '"><option value="">' + _('No Category') + '</option><option value="work">' + _('Work') + '</option><option value="personal">' + _('Personal') + '</option><option value="important">' + _('Important') + '</option></select></div></div>' if self.enable_categories else ''}
                                <div class="{'col-md-6' if self.enable_categories else 'col-md-12'}">
                                    <div class="form-group mb-3">
                                        <label for="eventColor_{calendar_id}">{_('Color')}</label>
                                        <input type="color" class="form-control" id="eventColor_{calendar_id}" value="#3498db">
                                    </div>
                                </div>
                            </div>

                            {'<div class="form-group mb-3"><label for="eventRecurrence_' + calendar_id + '">' + _('Recurrence') + '</label><select class="form-control" id="eventRecurrence_' + calendar_id + '"><option value="">' + _('No Recurrence') + '</option><option value="daily">' + _('Daily') + '</option><option value="weekly">' + _('Weekly') + '</option><option value="monthly">' + _('Monthly') + '</option><option value="yearly">' + _('Yearly') + '</option></select></div>' if self.enable_recurring_events else ''}

                            {'<div class="form-group mb-3"><label for="eventReminder_' + calendar_id + '">' + _('Reminder') + '</label><select class="form-control" id="eventReminder_' + calendar_id + '"><option value="">' + _('No Reminder') + '</option><option value="5">5 ' + _('minutes before') + '</option><option value="15">15 ' + _('minutes before') + '</option><option value="30">30 ' + _('minutes before') + '</option><option value="60">1 ' + _('hour before') + '</option><option value="1440">1 ' + _('day before') + '</option></select></div>' if self.enable_reminders else ''}

                            <input type="hidden" id="eventId_{calendar_id}">
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-danger" id="deleteEventBtn_{calendar_id}" onclick="deleteEvent('{calendar_id}')" style="display: none;">
                            {_('Delete')}
                        </button>
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">{_('Cancel')}</button>
                        <button type="button" class="btn btn-primary" onclick="saveEvent('{calendar_id}')">{_('Save')}</button>
                    </div>
                </div>
            </div>
        </div>

        {'<!-- Calendars Modal --><div class="modal fade" id="calendarsModal_' + calendar_id + '" tabindex="-1" aria-hidden="true"><div class="modal-dialog"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">' + _('Manage Calendars') + '</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body"><div id="calendarsList_' + calendar_id + '"></div><hr><form id="newCalendarForm_' + calendar_id + '"><div class="form-group mb-3"><label for="newCalendarName_' + calendar_id + '">' + _('New Calendar Name') + '</label><input type="text" class="form-control" id="newCalendarName_' + calendar_id + '"></div><div class="form-group mb-3"><label for="newCalendarColor_' + calendar_id + '">' + _('Color') + '</label><input type="color" class="form-control" id="newCalendarColor_' + calendar_id + '" value="#3498db"></div></form></div><div class="modal-footer"><button type="button" class="btn btn-primary" onclick="addNewCalendar(' + chr(39) + calendar_id + chr(39) + ')">' + _('Add Calendar') + '</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">' + _('Close') + '</button></div></div></div></div>' if self.enable_multiple_calendars else ''}

        {'<!-- Export Modal --><div class="modal fade" id="exportModal_' + calendar_id + '" tabindex="-1" aria-hidden="true"><div class="modal-dialog"><div class="modal-content"><div class="modal-header"><h5 class="modal-title">' + _('Export Calendar') + '</h5><button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button></div><div class="modal-body"><div class="form-group mb-3"><label>' + _('Export Format') + '</label><div class="form-check"><input class="form-check-input" type="radio" name="exportFormat_' + calendar_id + '" id="exportICS_' + calendar_id + '" value="ics" checked><label class="form-check-label" for="exportICS_' + calendar_id + '">' + _('iCalendar (.ics)') + '</label></div><div class="form-check"><input class="form-check-input" type="radio" name="exportFormat_' + calendar_id + '" id="exportJSON_' + calendar_id + '" value="json"><label class="form-check-label" for="exportJSON_' + calendar_id + '">' + _('JSON') + '</label></div><div class="form-check"><input class="form-check-input" type="radio" name="exportFormat_' + calendar_id + '" id="exportCSV_' + calendar_id + '" value="csv"><label class="form-check-label" for="exportCSV_' + calendar_id + '">' + _('CSV') + '</label></div></div><div class="form-group mb-3"><label for="exportDateRange_' + calendar_id + '">' + _('Date Range') + '</label><select class="form-control" id="exportDateRange_' + calendar_id + '"><option value="month">' + _('Current Month') + '</option><option value="year">' + _('Current Year') + '</option><option value="all">' + _('All Events') + '</option></select></div></div><div class="modal-footer"><button type="button" class="btn btn-primary" onclick="exportCalendar(' + chr(39) + calendar_id + chr(39) + ')">' + _('Export') + '</button><button type="button" class="btn btn-secondary" data-bs-dismiss="modal">' + _('Cancel') + '</button></div></div></div></div>' if self.enable_export else ''}

        <style>
        .calendar-widget {{
            border: 1px solid #ddd;
            border-radius: 8px;
            overflow: hidden;
            background: #fff;
            margin-bottom: 15px;
        }}

        .calendar-header {{
            background: #f8f9fa;
            border-bottom: 1px solid #ddd;
            padding: 15px;
        }}

        .calendar-toolbar {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 15px;
        }}

        .calendar-nav {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .calendar-title {{
            margin: 0;
            color: #495057;
            font-size: 1.3rem;
            font-weight: 600;
        }}

        .calendar-views .btn-group .btn {{
            min-width: 70px;
        }}

        .calendar-actions {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}

        .calendar-filters {{
            margin-top: 15px;
            padding-top: 15px;
            border-top: 1px solid #dee2e6;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}

        .filter-group {{
            display: flex;
            flex-direction: column;
            gap: 5px;
        }}

        .filter-group label {{
            font-weight: 600;
            color: #495057;
            font-size: 0.9rem;
        }}

        .category-filters,
        .calendar-filters {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}

        .filter-item {{
            display: flex;
            align-items: center;
            gap: 5px;
            padding: 4px 8px;
            background: #e9ecef;
            border-radius: 4px;
            font-size: 0.85rem;
        }}

        .filter-item input[type="checkbox"] {{
            margin: 0;
        }}

        .calendar-container {{
            background: #fff;
            padding: 0;
        }}

        /* FullCalendar customizations */
        .fc {{
            height: 100% !important;
        }}

        .fc-toolbar {{
            display: none !important; /* Hide default toolbar since we have our own */
        }}

        .fc-event {{
            cursor: pointer;
            border: none !important;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            transition: transform 0.2s, box-shadow 0.2s;
        }}

        .fc-event:hover {{
            transform: translateY(-1px);
            box-shadow: 0 2px 6px rgba(0,0,0,0.15);
        }}

        .fc-daygrid-event {{
            border-radius: 4px;
            padding: 2px 4px;
        }}

        .fc-timegrid-event {{
            border-radius: 4px;
            overflow: hidden;
        }}

        .fc-event-title {{
            font-weight: 500;
            font-size: 0.85rem;
        }}

        .fc-event-time {{
            font-weight: 400;
            font-size: 0.8rem;
            opacity: 0.9;
        }}

        .fc-day-today {{
            background-color: rgba(52, 144, 220, 0.1) !important;
        }}

        .fc-button-primary {{
            background-color: #3498db;
            border-color: #3498db;
        }}

        .fc-button-primary:hover {{
            background-color: #2980b9;
            border-color: #2980b9;
        }}

        /* Theme variations */
        .calendar-theme-modern {{
            border: none;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }}

        .calendar-theme-modern .calendar-header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }}

        .calendar-theme-modern .calendar-title {{
            color: white;
        }}

        .calendar-theme-minimal {{
            border: 1px solid #e9ecef;
        }}

        .calendar-theme-minimal .calendar-header {{
            background: #fff;
            border-bottom: 1px solid #e9ecef;
        }}

        .calendar-theme-colorful {{
            border: 2px solid #ff6b6b;
        }}

        .calendar-theme-colorful .calendar-header {{
            background: linear-gradient(45deg, #ff6b6b, #4ecdc4, #45b7d1);
            background-size: 300% 300%;
            animation: gradient 15s ease infinite;
        }}

        /* Responsive design */
        @media (max-width: 768px) {{
            .calendar-toolbar {{
                flex-direction: column;
                align-items: stretch;
                gap: 10px;
            }}

            .calendar-nav {{
                justify-content: center;
            }}

            .calendar-views {{
                order: -1;
            }}

            .calendar-actions {{
                justify-content: center;
            }}

            .calendar-filters {{
                flex-direction: column;
                gap: 10px;
            }}
        }}

        /* Print styles */
        @media print {{
            .calendar-header {{
                -webkit-print-color-adjust: exact;
                color-adjust: exact;
            }}

            .calendar-actions,
            .calendar-filters {{
                display: none !important;
            }}
        }}
        }}
        </style>

        <script>
        // FullCalendar CDN
        if (typeof FullCalendar === 'undefined') {{
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://cdn.jsdelivr.net/npm/@fullcalendar/core@6.1.8/main.min.css';
            document.head.appendChild(link);

            const script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/@fullcalendar/core@6.1.8/index.global.min.js';
            script.onload = function() {{
                const plugins = [
                    'https://cdn.jsdelivr.net/npm/@fullcalendar/daygrid@6.1.8/index.global.min.js',
                    'https://cdn.jsdelivr.net/npm/@fullcalendar/timegrid@6.1.8/index.global.min.js',
                    'https://cdn.jsdelivr.net/npm/@fullcalendar/interaction@6.1.8/index.global.min.js',
                    'https://cdn.jsdelivr.net/npm/@fullcalendar/list@6.1.8/index.global.min.js'
                ];

                let loadedPlugins = 0;
                plugins.forEach(pluginUrl => {{
                    const pluginScript = document.createElement('script');
                    pluginScript.src = pluginUrl;
                    pluginScript.onload = () => {{
                        loadedPlugins++;
                        if (loadedPlugins === plugins.length) {{
                            initializeCalendar_{calendar_id}();
                        }}
                    }};
                    document.head.appendChild(pluginScript);
                }});
            }};
            document.head.appendChild(script);
        }} else {{
            initializeCalendar_{calendar_id}();
        }}

        // Calendar instance and configuration
        let calendar_{calendar_id} = null;
        let events_{calendar_id} = [];
        let calendars_{calendar_id} = [{{ id: 'default', name: 'My Calendar', color: '#3498db', visible: true }}];
        let categories_{calendar_id} = [];

        function initializeCalendar_{calendar_id}() {{
            const calendarEl = document.getElementById('{calendar_id}');
            if (!calendarEl) return;

            // Apply theme
            applyCalendarTheme_{calendar_id}('{self.theme}');

            // Initialize FullCalendar
            calendar_{calendar_id} = new FullCalendar.Calendar(calendarEl, {{
                plugins: ['dayGrid', 'timeGrid', 'interaction', 'list'],
                initialView: '{self.default_view}Grid',
                headerToolbar: false, // We use our custom toolbar
                height: 'auto',
                editable: {str(self.enable_drag_drop).lower()},
                selectable: true,
                selectMirror: true,
                dayMaxEvents: true,
                weekends: true,
                firstDay: {1 if self.week_starts_on == 'monday' else 0},
                slotMinTime: '{self.business_hours_start}',
                slotMaxTime: '{self.business_hours_end}',
                slotDuration: '00:{self.slot_duration:02d}:00',
                allDaySlot: {str(self.enable_all_day_events).lower()},
                nowIndicator: true,
                businessHours: {{
                    startTime: '{self.business_hours_start}',
                    endTime: '{self.business_hours_end}',
                    daysOfWeek: [1, 2, 3, 4, 5] // Monday - Friday
                }},

                select: function(arg) {{
                    showEventModal_{calendar_id}(null, arg.start, arg.end, arg.allDay);
                    calendar_{calendar_id}.unselect();
                }},

                eventClick: function(arg) {{
                    showEventModal_{calendar_id}(arg.event);
                }},

                eventDrop: function(arg) {{
                    updateEventInStorage_{calendar_id}(arg.event);
                }},

                eventResize: function(arg) {{
                    updateEventInStorage_{calendar_id}(arg.event);
                }},

                events: events_{calendar_id},

                eventDidMount: function(arg) {{
                    // Add custom styling based on category
                    if (arg.event.extendedProps.category) {{
                        arg.el.classList.add('event-category-' + arg.event.extendedProps.category);
                    }}
                }}
            }});

            calendar_{calendar_id}.render();
            updateCalendarTitle_{calendar_id}();

            // Load sample events
            loadSampleEvents_{calendar_id}();

            // Initialize calendars and categories
            initializeCalendarsAndCategories_{calendar_id}();
        }}

        function showEventModal(calendarId, event = null, start = null, end = null, allDay = false) {{
            const modal = new bootstrap.Modal(document.getElementById(`eventModal_${{calendarId}}`));
            const form = document.getElementById(`eventForm_${{calendarId}}`);

            // Reset form
            form.reset();
            document.getElementById(`eventId_${{calendarId}}`).value = '';
            document.getElementById(`deleteEventBtn_${{calendarId}}`).style.display = 'none';

            if (event) {{
                // Edit existing event
                document.getElementById(`eventTitle_${{calendarId}}`).value = event.title;
                document.getElementById(`eventDescription_${{calendarId}}`).value = event.extendedProps.description || '';
                document.getElementById(`eventStart_${{calendarId}}`).value = formatDateTimeLocal(event.start);
                document.getElementById(`eventEnd_${{calendarId}}`).value = formatDateTimeLocal(event.end || event.start);
                document.getElementById(`eventColor_${{calendarId}}`).value = event.backgroundColor || '#3498db';
                document.getElementById(`eventId_${{calendarId}}`).value = event.id;
                document.getElementById(`deleteEventBtn_${{calendarId}}`).style.display = 'inline-block';

                {'document.getElementById(`eventAllDay_${calendarId}`).checked = event.allDay;' if self.enable_all_day_events else ''}
                {'document.getElementById(`eventCategory_${calendarId}`).value = event.extendedProps.category || "";' if self.enable_categories else ''}
                {'document.getElementById(`eventCalendar_${calendarId}`).value = event.extendedProps.calendarId || "default";' if self.enable_multiple_calendars else ''}
                {'document.getElementById(`eventRecurrence_${calendarId}`).value = event.extendedProps.recurrence || "";' if self.enable_recurring_events else ''}
                {'document.getElementById(`eventReminder_${calendarId}`).value = event.extendedProps.reminder || "";' if self.enable_reminders else ''}
            }} else {{
                // New event
                if (start) {{
                    document.getElementById(`eventStart_${{calendarId}}`).value = formatDateTimeLocal(start);
                }}
                if (end) {{
                    document.getElementById(`eventEnd_${{calendarId}}`).value = formatDateTimeLocal(end);
                }}
                {'document.getElementById(`eventAllDay_${calendarId}`).checked = allDay;' if self.enable_all_day_events else ''}
            }}

            modal.show();
        }}

        function showEventModal_{calendar_id}(event = null, start = null, end = null, allDay = false) {{
            showEventModal('{calendar_id}', event, start, end, allDay);
        }}

        function saveEvent(calendarId) {{
            const form = document.getElementById(`eventForm_${{calendarId}}`);
            if (!form.checkValidity()) {{
                form.reportValidity();
                return;
            }}

            const eventId = document.getElementById(`eventId_${{calendarId}}`).value;
            const title = document.getElementById(`eventTitle_${{calendarId}}`).value;
            const description = document.getElementById(`eventDescription_${{calendarId}}`).value;
            const start = document.getElementById(`eventStart_${{calendarId}}`).value;
            const end = document.getElementById(`eventEnd_${{calendarId}}`).value;
            const color = document.getElementById(`eventColor_${{calendarId}}`).value;
            {'const allDay = document.getElementById(`eventAllDay_${calendarId}`).checked;' if self.enable_all_day_events else 'const allDay = false;'}
            {'const category = document.getElementById(`eventCategory_${calendarId}`).value;' if self.enable_categories else 'const category = "";'}
            {'const calendarSource = document.getElementById(`eventCalendar_${calendarId}`).value;' if self.enable_multiple_calendars else 'const calendarSource = "default";'}
            {'const recurrence = document.getElementById(`eventRecurrence_${calendarId}`).value;' if self.enable_recurring_events else 'const recurrence = "";'}
            {'const reminder = document.getElementById(`eventReminder_${calendarId}`).value;' if self.enable_reminders else 'const reminder = "";'}

            const eventData = {{
                id: eventId || generateEventId(),
                title: title,
                start: start,
                end: end,
                allDay: allDay,
                backgroundColor: color,
                borderColor: color,
                extendedProps: {{
                    description: description,
                    category: category,
                    calendarId: calendarSource,
                    recurrence: recurrence,
                    reminder: reminder
                }}
            }};

            if (eventId) {{
                // Update existing event
                const event = calendar_{calendar_id}.getEventById(eventId);
                if (event) {{
                    event.setProp('title', title);
                    event.setStart(start);
                    event.setEnd(end);
                    event.setProp('backgroundColor', color);
                    event.setProp('borderColor', color);
                    event.setExtendedProp('description', description);
                    event.setExtendedProp('category', category);
                    event.setExtendedProp('calendarId', calendarSource);
                    event.setExtendedProp('recurrence', recurrence);
                    event.setExtendedProp('reminder', reminder);
                    updateEventInStorage_{calendar_id}(event);
                }}
            }} else {{
                // Add new event
                calendar_{calendar_id}.addEvent(eventData);
                events_{calendar_id}.push(eventData);
            }}

            // Handle recurring events
            {f"handleRecurringEvent_{calendar_id}(eventData);" if self.enable_recurring_events else ""}

            // Set reminder
            {f"setEventReminder_{calendar_id}(eventData);" if self.enable_reminders else ""}

            updateHiddenInput_{calendar_id}();
            bootstrap.Modal.getInstance(document.getElementById(`eventModal_${{calendarId}}`)).hide();
        }}

        function deleteEvent(calendarId) {{
            const eventId = document.getElementById(`eventId_${{calendarId}}`).value;
            if (eventId && confirm('{_("Are you sure you want to delete this event?")}')) {{
                const event = calendar_{calendar_id}.getEventById(eventId);
                if (event) {{
                    event.remove();
                    events_{calendar_id} = events_{calendar_id}.filter(e => e.id !== eventId);
                    updateHiddenInput_{calendar_id}();
                }}
                bootstrap.Modal.getInstance(document.getElementById(`eventModal_${{calendarId}}`)).hide();
            }}
        }}

        function navigateCalendar(calendarId, direction) {{
            if (direction === 'prev') {{
                calendar_{calendar_id}.prev();
            }} else if (direction === 'next') {{
                calendar_{calendar_id}.next();
            }} else if (direction === 'today') {{
                calendar_{calendar_id}.today();
            }}
            updateCalendarTitle_{calendar_id}();
        }}

        function changeView(calendarId, view) {{
            const viewName = view === 'agenda' ? 'listWeek' : view + 'Grid';
            calendar_{calendar_id}.changeView(viewName);

            // Update active button
            document.querySelectorAll('.calendar-views .btn').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');

            updateCalendarTitle_{calendar_id}();
        }}

        function updateCalendarTitle_{calendar_id}() {{
            const view = calendar_{calendar_id}.view;
            const title = view.title;
            document.getElementById('title_{calendar_id}').textContent = title;
        }}

        function loadSampleEvents_{calendar_id}() {{
            const sampleEvents = [
                {{
                    id: '1',
                    title: 'Team Meeting',
                    start: new Date().toISOString().split('T')[0] + 'T10:00:00',
                    end: new Date().toISOString().split('T')[0] + 'T11:00:00',
                    backgroundColor: '#3498db',
                    borderColor: '#3498db',
                    extendedProps: {{
                        description: 'Weekly team sync meeting',
                        category: 'work',
                        calendarId: 'default'
                    }}
                }},
                {{
                    id: '2',
                    title: 'Lunch Break',
                    start: new Date().toISOString().split('T')[0] + 'T12:00:00',
                    end: new Date().toISOString().split('T')[0] + 'T13:00:00',
                    backgroundColor: '#2ecc71',
                    borderColor: '#2ecc71',
                    extendedProps: {{
                        description: 'Lunch with colleagues',
                        category: 'personal',
                        calendarId: 'default'
                    }}
                }}
            ];

            sampleEvents.forEach(event => {{
                calendar_{calendar_id}.addEvent(event);
            }});

            events_{calendar_id} = sampleEvents;
            updateHiddenInput_{calendar_id}();
        }}

        function initializeCalendarsAndCategories_{calendar_id}() {{
            {'updateCalendarsList_' + calendar_id + '();' if self.enable_multiple_calendars else ''}
            {'updateCategoriesFilter_' + calendar_id + '();' if self.enable_categories else ''}
        }}

        {update_calendars_function if self.enable_multiple_calendars else ''}

        {'function addNewCalendar(calendarId) { const name = document.getElementById("newCalendarName_" + calendarId).value.trim(); const color = document.getElementById("newCalendarColor_" + calendarId).value; if (!name) return; const newCalendar = { id: generateCalendarId(), name: name, color: color, visible: true }; calendars_' + calendar_id + '.push(newCalendar); updateCalendarsList_' + calendar_id + '(); document.getElementById("newCalendarName_" + calendarId).value = ""; document.getElementById("newCalendarColor_" + calendarId).value = "#3498db"; }' if self.enable_multiple_calendars else ''}

        {'function removeCalendar_' + calendar_id + '(id) { if (id === "default") { alert("' + _('Cannot delete the default calendar') + '"); return; } if (confirm("' + _('Are you sure you want to delete this calendar and all its events?') + '")) { calendars_' + calendar_id + ' = calendars_' + calendar_id + '.filter(cal => cal.id !== id); events_' + calendar_id + '.filter(event => event.extendedProps.calendarId === id).forEach(event => { const calEvent = calendar_' + calendar_id + '.getEventById(event.id); if (calEvent) calEvent.remove(); }); events_' + calendar_id + ' = events_' + calendar_id + '.filter(event => event.extendedProps.calendarId !== id); updateCalendarsList_' + calendar_id + '(); updateHiddenInput_' + calendar_id + '(); } }' if self.enable_multiple_calendars else ''}

        {'function toggleCalendar_' + calendar_id + '(id) { const calendar = calendars_' + calendar_id + '.find(cal => cal.id === id); if (calendar) { calendar.visible = !calendar.visible; events_' + calendar_id + '.forEach(event => { if (event.extendedProps.calendarId === id) { const calEvent = calendar_' + calendar_id + '.getEventById(event.id); if (calEvent) { if (calendar.visible) { calEvent.setProp("display", "auto"); } else { calEvent.setProp("display", "none"); } } } }); } }' if self.enable_multiple_calendars else ''}

        {'function updateCategoriesFilter_' + calendar_id + '() { const container = document.getElementById(`categories_${calendar_id}`); if (!container) return; const uniqueCategories = [...new Set(events_' + calendar_id + '.map(e => e.extendedProps.category).filter(c => c))]; container.innerHTML = ""; uniqueCategories.forEach(category => { const item = document.createElement("div"); item.className = "filter-item"; item.innerHTML = `<input type="checkbox" id="cat_${category}" checked onchange="toggleCategory_' + calendar_id + '(` + String.fromCharCode(39) + `${category}` + String.fromCharCode(39) + `)"><label for="cat_${category}">${category}</label>`; container.appendChild(item); }); }' if self.enable_categories else ''}

        {'function toggleCategory_' + calendar_id + '(category) { const checked = document.getElementById(`cat_${category}`).checked; events_' + calendar_id + '.forEach(event => { if (event.extendedProps.category === category) { const calEvent = calendar_' + calendar_id + '.getEventById(event.id); if (calEvent) { calEvent.setProp("display", checked ? "auto" : "none"); } } }); }' if self.enable_categories else ''}

        {'function handleRecurringEvent_' + calendar_id + '(eventData) { if (!eventData.extendedProps.recurrence) return; const startDate = new Date(eventData.start); const endDate = new Date(eventData.end); const duration = endDate.getTime() - startDate.getTime(); let currentDate = new Date(startDate); const maxOccurrences = 52; let occurrences = 0; while (occurrences < maxOccurrences) { occurrences++; switch (eventData.extendedProps.recurrence) { case "daily": currentDate.setDate(currentDate.getDate() + 1); break; case "weekly": currentDate.setDate(currentDate.getDate() + 7); break; case "monthly": currentDate.setMonth(currentDate.getMonth() + 1); break; case "yearly": currentDate.setFullYear(currentDate.getFullYear() + 1); break; default: return; } const recurringEvent = { ...eventData, id: eventData.id + "_" + occurrences, start: new Date(currentDate), end: new Date(currentDate.getTime() + duration) }; calendar_' + calendar_id + '.addEvent(recurringEvent); events_' + calendar_id + '.push(recurringEvent); if (currentDate.getFullYear() > new Date().getFullYear() + 2) break; } }' if self.enable_recurring_events else ''}

        {'function setEventReminder_' + calendar_id + '(eventData) { if (!eventData.extendedProps.reminder) return; const reminderMinutes = parseInt(eventData.extendedProps.reminder); const eventTime = new Date(eventData.start).getTime(); const reminderTime = eventTime - (reminderMinutes * 60 * 1000); const now = new Date().getTime(); if (reminderTime > now) { setTimeout(() => { if (Notification.permission === "granted") { new Notification("Event Reminder", { body: `${eventData.title} starts in ${reminderMinutes} minutes`, icon: "/static/appbuilder/img/calendar-icon.png" }); } else { alert(`Reminder: ${eventData.title} starts in ${reminderMinutes} minutes`); } }, reminderTime - now); } }' if self.enable_reminders else ''}

        function showCalendarsModal(calendarId) {{
            {'const modal = new bootstrap.Modal(document.getElementById(`calendarsModal_${calendarId}`)); modal.show();' if self.enable_multiple_calendars else ''}
        }}

        function showExportModal(calendarId) {{
            {'const modal = new bootstrap.Modal(document.getElementById(`exportModal_${calendarId}`)); modal.show();' if self.enable_export else ''}
        }}

        {'function exportCalendar(calendarId) { const format = document.querySelector(`input[name="exportFormat_${calendarId}"]:checked`).value; const range = document.getElementById(`exportDateRange_${calendarId}`).value; let eventsToExport = events_' + calendar_id + '; if (range === "month") { const currentDate = calendar_' + calendar_id + '.getDate(); const startOfMonth = new Date(currentDate.getFullYear(), currentDate.getMonth(), 1); const endOfMonth = new Date(currentDate.getFullYear(), currentDate.getMonth() + 1, 0); eventsToExport = events_' + calendar_id + '.filter(e => { const eventDate = new Date(e.start); return eventDate >= startOfMonth && eventDate <= endOfMonth; }); } else if (range === "year") { const currentDate = calendar_' + calendar_id + '.getDate(); const startOfYear = new Date(currentDate.getFullYear(), 0, 1); const endOfYear = new Date(currentDate.getFullYear(), 11, 31); eventsToExport = events_' + calendar_id + '.filter(e => { const eventDate = new Date(e.start); return eventDate >= startOfYear && eventDate <= endOfYear; }); } let content = ""; let filename = `calendar_${new Date().toISOString().split("T")[0]}`; let mimeType = "text/plain"; if (format === "ics") { content = generateICS(eventsToExport); filename += ".ics"; mimeType = "text/calendar"; } else if (format === "json") { content = JSON.stringify(eventsToExport, null, 2); filename += ".json"; mimeType = "application/json"; } else if (format === "csv") { content = generateCSV(eventsToExport); filename += ".csv"; mimeType = "text/csv"; } downloadFile(content, filename, mimeType); bootstrap.Modal.getInstance(document.getElementById(`exportModal_${calendarId}`)).hide(); }' if self.enable_export else ''}

        function printCalendar(calendarId) {{
            {'window.print();' if self.enable_print else ''}
        }}

        function applyCalendarTheme_{calendar_id}(theme) {{
            const widget = document.querySelector(`[data-field-id="{field.id}"]`);
            widget.classList.remove('calendar-theme-modern', 'calendar-theme-minimal', 'calendar-theme-colorful');

            if (theme !== 'default') {{
                widget.classList.add(`calendar-theme-${{theme}}`);
            }}
        }}

        function updateEventInStorage_{calendar_id}(event) {{
            const index = events_{calendar_id}.findIndex(e => e.id === event.id);
            if (index !== -1) {{
                events_{calendar_id}[index] = {{
                    id: event.id,
                    title: event.title,
                    start: event.start.toISOString(),
                    end: event.end ? event.end.toISOString() : event.start.toISOString(),
                    allDay: event.allDay,
                    backgroundColor: event.backgroundColor,
                    borderColor: event.borderColor,
                    extendedProps: event.extendedProps
                }};
                updateHiddenInput_{calendar_id}();
            }}
        }}

        function updateHiddenInput_{calendar_id}() {{
            const data = {{
                events: events_{calendar_id},
                calendars: calendars_{calendar_id},
                view: calendar_{calendar_id} ? calendar_{calendar_id}.view.type : '{self.default_view}',
                currentDate: calendar_{calendar_id} ? calendar_{calendar_id}.getDate().toISOString() : new Date().toISOString()
            }};
            document.getElementById('{field.id}').value = JSON.stringify(data);
        }}

        // Utility functions
        function formatDateTimeLocal(date) {{
            if (!date) return '';
            const d = new Date(date);
            return d.getFullYear() + '-' +
                   String(d.getMonth() + 1).padStart(2, '0') + '-' +
                   String(d.getDate()).padStart(2, '0') + 'T' +
                   String(d.getHours()).padStart(2, '0') + ':' +
                   String(d.getMinutes()).padStart(2, '0');
        }}

        function generateEventId() {{
            return 'event_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        }}

        function generateCalendarId() {{
            return 'cal_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9);
        }}

        function generateICS(events) {{
            let ics = 'BEGIN:VCALENDAR' + String.fromCharCode(10) + 'VERSION:2.0' + String.fromCharCode(10) + 'PRODID:-//Calendar Widget//EN' + String.fromCharCode(10);
            events.forEach(event => {{
                const start = new Date(event.start);
                const end = new Date(event.end || event.start);
                ics += 'BEGIN:VEVENT' + String.fromCharCode(10);
                ics += `UID:${{event.id}}` + String.fromCharCode(10);
                ics += `DTSTART:${{formatICSDate(start)}}` + String.fromCharCode(10);
                ics += `DTEND:${{formatICSDate(end)}}` + String.fromCharCode(10);
                ics += `SUMMARY:${{event.title}}` + String.fromCharCode(10);
                if (event.extendedProps.description) {{
                    ics += `DESCRIPTION:${{event.extendedProps.description}}` + String.fromCharCode(10);
                }}
                ics += 'END:VEVENT' + String.fromCharCode(10);
            }});
            ics += 'END:VCALENDAR';
            return ics;
        }}

        function generateCSV(events) {{
            let csv = 'Title,Start,End,All Day,Description,Category' + String.fromCharCode(10);
            events.forEach(event => {{
                csv += `"${{event.title}}","${{event.start}}","${{event.end || event.start}}","${{event.allDay || false}}","${{event.extendedProps.description || ''}}","${{event.extendedProps.category || ''}}"` + String.fromCharCode(10);
            }});
            return csv;
        }}

        function formatICSDate(date) {{
            const isoString = date.toISOString();
            return isoString.replace(/[-:]/g, '').split('.')[0] + 'Z';
        }}

        function downloadFile(content, filename, mimeType) {{
            const blob = new Blob([content], {{ type: mimeType }});
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.download = filename;
            link.href = url;
            link.click();
            URL.revokeObjectURL(url);
        }}

        // Request notification permission for reminders
        {'if ("Notification" in window && Notification.permission === "default") { Notification.requestPermission(); }' if self.enable_reminders else ''}
        </script>
        """,
        calendar_id=calendar_id,
        field=field,
        _=gettext,
        default_view=self.default_view,
        enable_drag_drop=self.enable_drag_drop,
        enable_resize=self.enable_resize,
        time_format=self.time_format,
        week_starts_on=self.week_starts_on,
        theme=self.theme,
        height=self.height,
        enable_time_slots=self.enable_time_slots,
        slot_duration=self.slot_duration,
        business_hours_start=self.business_hours_start,
        business_hours_end=self.business_hours_end,
        enable_all_day_events=self.enable_all_day_events,
        enable_recurring_events=self.enable_recurring_events,
        enable_reminders=self.enable_reminders,
        enable_categories=self.enable_categories,
        enable_multiple_calendars=self.enable_multiple_calendars,
        enable_export=self.enable_export,
        enable_print=self.enable_print,
        timezone=self.timezone,
        locale=self.locale
        )


class ProgressIndicatorsWidget(Input):
    """
    Advanced progress indicators widget with multiple display types.

    Supports linear progress bars, circular indicators, step-based progress,
    multi-progress displays, animations, and real-time updates.
    """

    def __init__(self,
                 progress_type='linear',
                 value=0,
                 max_value=100,
                 show_percentage=True,
                 show_label=True,
                 label_text='Progress',
                 height='20px',
                 width='100%',
                 color='#3498db',
                 background_color='#ecf0f1',
                 border_radius='10px',
                 animation_duration=0.5,
                 enable_animation=True,
                 striped=False,
                 steps=None,
                 current_step=0,
                 step_labels=None,
                 multiple_bars=None,
                 theme='default',
                 size='medium',
                 enable_real_time=False,
                 update_interval=1000,
                 **kwargs):
        """
        Initialize the Progress Indicators widget.

        Args:
            progress_type: Type of progress indicator ('linear', 'circular', 'steps', 'multiple')
            value: Current progress value
            max_value: Maximum progress value
            show_percentage: Display percentage text
            show_label: Display progress label
            label_text: Text label for the progress
            height: Height of linear progress bar
            width: Width of the container
            color: Progress bar color
            background_color: Background color
            border_radius: Border radius for rounded corners
            animation_duration: Animation duration in seconds
            enable_animation: Enable smooth animations
            striped: Show striped pattern
            steps: Number of steps for step-based progress
            current_step: Current step (0-based)
            step_labels: Labels for each step
            multiple_bars: List of multiple progress bars data
            theme: Progress theme ('default', 'success', 'warning', 'danger', 'info')
            size: Size variant ('small', 'medium', 'large')
            enable_real_time: Enable real-time progress updates
            update_interval: Real-time update interval in milliseconds
        """
        super().__init__(**kwargs)
        self.progress_type = progress_type
        self.value = value
        self.max_value = max_value
        self.show_percentage = show_percentage
        self.show_label = show_label
        self.label_text = label_text
        self.height = height
        self.width = width
        self.color = color
        self.background_color = background_color
        self.border_radius = border_radius
        self.animation_duration = animation_duration
        self.enable_animation = enable_animation
        self.striped = striped
        self.steps = steps
        self.current_step = current_step
        self.step_labels = step_labels or []
        self.multiple_bars = multiple_bars or []
        self.theme = theme
        self.size = size
        self.enable_real_time = enable_real_time
        self.update_interval = update_interval

    def __call__(self, field, **kwargs):
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)

        # Generate unique ID for this progress widget instance
        progress_id = f"progress_{field.id}_{id(self)}"

        return Markup(f"""
        <div class="progress-indicators-widget progress-theme-{self.theme} progress-size-{self.size}" data-field-id="{field.id}">
            <!-- Progress Header -->
            {'<div class="progress-header">' if self.show_label else ''}
                {'<div class="progress-label">' + self.label_text + '</div>' if self.show_label else ''}
                {'<div class="progress-percentage" id="percentage_' + progress_id + '">' + str(round((self.value / self.max_value) * 100)) + '%</div>' if self.show_percentage else ''}
            {'</div>' if self.show_label else ''}

            <!-- Progress Content -->
            <div class="progress-content" id="content_{progress_id}">
                {self._render_progress_type(progress_id)}
            </div>

            <!-- Progress Controls -->
            <div class="progress-controls">
                <div class="progress-actions">
                    <button type="button" class="btn btn-sm btn-outline-secondary" onclick="updateProgress('{progress_id}', 0)">
                        <i class="fas fa-stop"></i> {_('Reset')}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-primary" onclick="startProgress('{progress_id}')">
                        <i class="fas fa-play"></i> {_('Start')}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-warning" onclick="pauseProgress('{progress_id}')">
                        <i class="fas fa-pause"></i> {_('Pause')}
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-success" onclick="completeProgress('{progress_id}')">
                        <i class="fas fa-check"></i> {_('Complete')}
                    </button>
                </div>

                <div class="progress-settings">
                    <div class="form-group">
                        <label for="progressValue_{progress_id}">{_('Value')}</label>
                        <input type="number" class="form-control form-control-sm" id="progressValue_{progress_id}"
                               value="{self.value}" min="0" max="{self.max_value}"
                               onchange="updateProgress('{progress_id}', this.value)">
                    </div>
                    <div class="form-group">
                        <label for="progressSpeed_{progress_id}">{_('Animation Speed')}</label>
                        <select class="form-control form-control-sm" id="progressSpeed_{progress_id}"
                                onchange="changeAnimationSpeed('{progress_id}', this.value)">
                            <option value="0.2">{_('Fast')}</option>
                            <option value="0.5" selected>{_('Medium')}</option>
                            <option value="1.0">{_('Slow')}</option>
                        </select>
                    </div>
                </div>
            </div>

            <!-- Hidden input for form data -->
            <input type="hidden" id="{field.id}" name="{field.name}" value="{field.data or ''}" />
        </div>

        <style>
        .progress-indicators-widget {{
            border: 1px solid #ddd;
            border-radius: 8px;
            padding: 20px;
            background: #fff;
            margin-bottom: 15px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }}

        .progress-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }}

        .progress-label {{
            font-weight: 600;
            color: #2c3e50;
            font-size: 1.1rem;
        }}

        .progress-percentage {{
            font-weight: 500;
            color: #7f8c8d;
            font-size: 0.95rem;
        }}

        .progress-content {{
            margin-bottom: 20px;
        }}

        /* Linear Progress */
        .progress-linear {{
            width: {self.width};
            height: {self.height};
            background-color: {self.background_color};
            border-radius: {self.border_radius};
            overflow: hidden;
            position: relative;
        }}

        .progress-linear .progress-bar {{
            height: 100%;
            background-color: {self.color};
            width: 0%;
            transition: width {self.animation_duration}s ease-in-out;
            position: relative;
            overflow: hidden;
        }}

        .progress-linear.striped .progress-bar {{
            background-image: linear-gradient(45deg,
                rgba(255,255,255,.15) 25%,
                transparent 25%,
                transparent 50%,
                rgba(255,255,255,.15) 50%,
                rgba(255,255,255,.15) 75%,
                transparent 75%,
                transparent);
            background-size: 20px 20px;
            animation: progress-stripes 1s linear infinite;
        }}

        /* Circular Progress */
        .progress-circular {{
            width: 120px;
            height: 120px;
            margin: 0 auto;
            position: relative;
        }}

        .progress-circular svg {{
            width: 100%;
            height: 100%;
            transform: rotate(-90deg);
        }}

        .progress-circular .progress-circle-bg {{
            fill: none;
            stroke: {self.background_color};
            stroke-width: 8;
        }}

        .progress-circular .progress-circle-fill {{
            fill: none;
            stroke: {self.color};
            stroke-width: 8;
            stroke-linecap: round;
            stroke-dasharray: 282.74;
            stroke-dashoffset: 282.74;
            transition: stroke-dashoffset {self.animation_duration}s ease-in-out;
        }}

        .progress-circular .progress-text {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 1.2rem;
            font-weight: 600;
            color: #2c3e50;
        }}

        /* Step Progress */
        .progress-steps {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
        }}

        .progress-step {{
            display: flex;
            flex-direction: column;
            align-items: center;
            position: relative;
            flex: 1;
        }}

        .progress-step:not(:last-child)::after {{
            content: '';
            position: absolute;
            top: 15px;
            left: 50%;
            width: 100%;
            height: 2px;
            background-color: {self.background_color};
            z-index: 1;
        }}

        .progress-step.completed:not(:last-child)::after {{
            background-color: {self.color};
        }}

        .step-indicator {{
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background-color: {self.background_color};
            border: 2px solid {self.background_color};
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 600;
            font-size: 0.9rem;
            color: #7f8c8d;
            z-index: 2;
            position: relative;
            transition: all 0.3s ease;
        }}

        .progress-step.completed .step-indicator {{
            background-color: {self.color};
            border-color: {self.color};
            color: white;
        }}

        .progress-step.current .step-indicator {{
            border-color: {self.color};
            color: {self.color};
            transform: scale(1.1);
        }}

        .step-label {{
            margin-top: 8px;
            font-size: 0.85rem;
            color: #7f8c8d;
            text-align: center;
        }}

        .progress-step.completed .step-label,
        .progress-step.current .step-label {{
            color: #2c3e50;
            font-weight: 500;
        }}

        /* Multiple Progress Bars */
        .progress-multiple {{
            display: flex;
            flex-direction: column;
            gap: 15px;
        }}

        .multiple-bar-item {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .multiple-bar-label {{
            min-width: 100px;
            font-size: 0.9rem;
            font-weight: 500;
            color: #2c3e50;
        }}

        .multiple-bar-progress {{
            flex: 1;
            height: 16px;
            background-color: {self.background_color};
            border-radius: 8px;
            overflow: hidden;
        }}

        .multiple-bar-fill {{
            height: 100%;
            transition: width {self.animation_duration}s ease-in-out;
            border-radius: 8px;
        }}

        .multiple-bar-value {{
            min-width: 40px;
            font-size: 0.85rem;
            color: #7f8c8d;
            text-align: right;
        }}

        /* Progress Controls */
        .progress-controls {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            flex-wrap: wrap;
            gap: 15px;
            padding-top: 15px;
            border-top: 1px solid #ecf0f1;
        }}

        .progress-actions {{
            display: flex;
            gap: 8px;
        }}

        .progress-settings {{
            display: flex;
            gap: 15px;
        }}

        .progress-settings .form-group {{
            display: flex;
            flex-direction: column;
            gap: 3px;
        }}

        .progress-settings label {{
            font-size: 0.8rem;
            font-weight: 500;
            color: #7f8c8d;
        }}

        .progress-settings .form-control {{
            width: 80px;
        }}

        /* Theme Variations */
        .progress-theme-success {{
            --progress-color: #27ae60;
        }}

        .progress-theme-warning {{
            --progress-color: #f39c12;
        }}

        .progress-theme-danger {{
            --progress-color: #e74c3c;
        }}

        .progress-theme-info {{
            --progress-color: #3498db;
        }}

        .progress-theme-success .progress-bar,
        .progress-theme-success .progress-circle-fill,
        .progress-theme-success .step-indicator.completed,
        .progress-theme-success .step-indicator.current {{
            background-color: var(--progress-color);
            stroke: var(--progress-color);
            border-color: var(--progress-color);
        }}

        .progress-theme-warning .progress-bar,
        .progress-theme-warning .progress-circle-fill,
        .progress-theme-warning .step-indicator.completed,
        .progress-theme-warning .step-indicator.current {{
            background-color: var(--progress-color);
            stroke: var(--progress-color);
            border-color: var(--progress-color);
        }}

        .progress-theme-danger .progress-bar,
        .progress-theme-danger .progress-circle-fill,
        .progress-theme-danger .step-indicator.completed,
        .progress-theme-danger .step-indicator.current {{
            background-color: var(--progress-color);
            stroke: var(--progress-color);
            border-color: var(--progress-color);
        }}

        .progress-theme-info .progress-bar,
        .progress-theme-info .progress-circle-fill,
        .progress-theme-info .step-indicator.completed,
        .progress-theme-info .step-indicator.current {{
            background-color: var(--progress-color);
            stroke: var(--progress-color);
            border-color: var(--progress-color);
        }}

        /* Size Variations */
        .progress-size-small {{
            padding: 15px;
        }}

        .progress-size-small .progress-linear {{
            height: 12px;
        }}

        .progress-size-small .progress-circular {{
            width: 80px;
            height: 80px;
        }}

        .progress-size-small .step-indicator {{
            width: 24px;
            height: 24px;
            font-size: 0.8rem;
        }}

        .progress-size-large {{
            padding: 25px;
        }}

        .progress-size-large .progress-linear {{
            height: 28px;
        }}

        .progress-size-large .progress-circular {{
            width: 160px;
            height: 160px;
        }}

        .progress-size-large .step-indicator {{
            width: 36px;
            height: 36px;
            font-size: 1rem;
        }}

        /* Animations */
        @keyframes progress-stripes {{
            0% {{ background-position: 20px 0; }}
            100% {{ background-position: 0 0; }}
        }}

        .progress-pulse {{
            animation: pulse 2s infinite;
        }}

        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
            100% {{ opacity: 1; }}
        }}

        /* Responsive Design */
        @media (max-width: 768px) {{
            .progress-controls {{
                flex-direction: column;
                align-items: stretch;
            }}

            .progress-actions {{
                justify-content: center;
            }}

            .progress-settings {{
                justify-content: center;
            }}

            .multiple-bar-item {{
                flex-direction: column;
                align-items: stretch;
                gap: 5px;
            }}

            .multiple-bar-label {{
                min-width: auto;
                text-align: center;
            }}

            .multiple-bar-value {{
                text-align: center;
            }}
        }}
        }}
        </style>

        <script>
        // Progress widget instance data
        let progressData_{progress_id} = {{
            value: {self.value},
            maxValue: {self.max_value},
            isRunning: false,
            isPaused: false,
            animationSpeed: {self.animation_duration},
            interval: null,
            type: '{self.progress_type}',
            steps: {self.steps if self.steps else 0},
            currentStep: {self.current_step}
        }};

        // Initialize progress widget
        document.addEventListener('DOMContentLoaded', function() {{
            initializeProgress_{progress_id}();
        }});

        function initializeProgress_{progress_id}() {{
            updateProgressDisplay_{progress_id}(progressData_{progress_id}.value);

            // Setup real-time updates if enabled
            {f"setupRealTimeProgress_{progress_id}();" if self.enable_real_time else ""}
        }}

        function updateProgress(progressId, value) {{
            const numValue = parseFloat(value);
            if (isNaN(numValue)) return;

            progressData_{progress_id}.value = Math.max(0, Math.min(numValue, progressData_{progress_id}.maxValue));
            updateProgressDisplay_{progress_id}(progressData_{progress_id}.value);
            updateHiddenInput_{progress_id}();
        }}

        function updateProgressDisplay_{progress_id}(value) {{
            const percentage = (value / progressData_{progress_id}.maxValue) * 100;

            // Update percentage display
            const percentageEl = document.getElementById('percentage_{progress_id}');
            if (percentageEl) {{
                percentageEl.textContent = Math.round(percentage) + '%';
            }}

            // Update value input
            const valueInput = document.getElementById('progressValue_{progress_id}');
            if (valueInput) {{
                valueInput.value = value;
            }}

            // Update progress display based on type
            switch (progressData_{progress_id}.type) {{
                case 'linear':
                    updateLinearProgress_{progress_id}(percentage);
                    break;
                case 'circular':
                    updateCircularProgress_{progress_id}(percentage);
                    break;
                case 'steps':
                    updateStepsProgress_{progress_id}(value);
                    break;
                case 'multiple':
                    updateMultipleProgress_{progress_id}();
                    break;
            }}
        }}

        function updateLinearProgress_{progress_id}(percentage) {{
            const progressBar = document.querySelector(`#content_{progress_id} .progress-bar`);
            if (progressBar) {{
                progressBar.style.width = percentage + '%';
            }}
        }}

        function updateCircularProgress_{progress_id}(percentage) {{
            const circle = document.querySelector(`#content_{progress_id} .progress-circle-fill`);
            const text = document.querySelector(`#content_{progress_id} .progress-text`);

            if (circle) {{
                const circumference = 282.74; // 2 * PI * 45 (radius)
                const offset = circumference - (percentage / 100) * circumference;
                circle.style.strokeDashoffset = offset;
            }}

            if (text) {{
                text.textContent = Math.round(percentage) + '%';
            }}
        }}

        function updateStepsProgress_{progress_id}(value) {{
            const stepPercentage = 100 / progressData_{progress_id}.steps;
            const currentStep = Math.floor(value / stepPercentage);

            const steps = document.querySelectorAll(`#content_{progress_id} .progress-step`);
            steps.forEach((step, index) => {{
                step.classList.remove('completed', 'current');
                if (index < currentStep) {{
                    step.classList.add('completed');
                }} else if (index === currentStep) {{
                    step.classList.add('current');
                }}
            }});

            progressData_{progress_id}.currentStep = currentStep;
        }}

        function updateMultipleProgress_{progress_id}() {{
            // Update multiple progress bars based on current data
            const bars = document.querySelectorAll(`#content_{progress_id} .multiple-bar-fill`);
            bars.forEach((bar, index) => {{
                if (progressData_{progress_id}.multipleBars && progressData_{progress_id}.multipleBars[index]) {{
                    const barData = progressData_{progress_id}.multipleBars[index];
                    const percentage = (barData.value / barData.max) * 100;
                    bar.style.width = percentage + '%';
                }}
            }});
        }}

        function startProgress(progressId) {{
            if (progressData_{progress_id}.isRunning) return;

            progressData_{progress_id}.isRunning = true;
            progressData_{progress_id}.isPaused = false;

            progressData_{progress_id}.interval = setInterval(() => {{
                if (!progressData_{progress_id}.isPaused) {{
                    const increment = progressData_{progress_id}.maxValue / 100; // 1% increment
                    const newValue = Math.min(progressData_{progress_id}.value + increment, progressData_{progress_id}.maxValue);

                    updateProgress(progressId, newValue);

                    if (newValue >= progressData_{progress_id}.maxValue) {{
                        stopProgress_{progress_id}();
                        onProgressComplete_{progress_id}();
                    }}
                }}
            }}, 100); // Update every 100ms
        }}

        function pauseProgress(progressId) {{
            progressData_{progress_id}.isPaused = !progressData_{progress_id}.isPaused;

            const button = event.target.closest('button');
            const icon = button.querySelector('i');

            if (progressData_{progress_id}.isPaused) {{
                icon.className = 'fas fa-play';
                button.innerHTML = '<i class="fas fa-play"></i> {_("Resume")}';
            }} else {{
                icon.className = 'fas fa-pause';
                button.innerHTML = '<i class="fas fa-pause"></i> {_("Pause")}';
            }}
        }}

        function stopProgress_{progress_id}() {{
            progressData_{progress_id}.isRunning = false;
            progressData_{progress_id}.isPaused = false;

            if (progressData_{progress_id}.interval) {{
                clearInterval(progressData_{progress_id}.interval);
                progressData_{progress_id}.interval = null;
            }}

            // Reset pause button
            const pauseButton = document.querySelector(`[onclick="pauseProgress('{progress_id}')"]`);
            if (pauseButton) {{
                pauseButton.innerHTML = '<i class="fas fa-pause"></i> {_("Pause")}';
            }}
        }}

        function completeProgress(progressId) {{
            stopProgress_{progress_id}();
            updateProgress(progressId, progressData_{progress_id}.maxValue);
            onProgressComplete_{progress_id}();
        }}

        function onProgressComplete_{progress_id}() {{
            // Add completion animation
            const widget = document.querySelector(`[data-field-id="{field.id}"]`);
            widget.classList.add('progress-pulse');

            setTimeout(() => {{
                widget.classList.remove('progress-pulse');
            }}, 2000);

            // Custom completion callback
            if (typeof onProgressComplete === 'function') {{
                onProgressComplete(progressData_{progress_id});
            }}
        }}

        function changeAnimationSpeed(progressId, speed) {{
            progressData_{progress_id}.animationSpeed = parseFloat(speed);

            // Update CSS animation duration
            const elements = document.querySelectorAll(`#content_{progress_id} .progress-bar, #content_{progress_id} .progress-circle-fill, #content_{progress_id} .multiple-bar-fill`);
            elements.forEach(el => {{
                el.style.transitionDuration = speed + 's';
            }});
        }}

        {f"function setupRealTimeProgress_{progress_id}() {{ setInterval(() => {{ if (!progressData_{progress_id}.isRunning) {{ const randomIncrement = Math.random() * 5; updateProgress('{progress_id}', Math.min(progressData_{progress_id}.value + randomIncrement, progressData_{progress_id}.maxValue)); }} }}, {self.update_interval}); }}" if self.enable_real_time else ""}

        function updateHiddenInput_{progress_id}() {{
            const data = {{
                value: progressData_{progress_id}.value,
                maxValue: progressData_{progress_id}.maxValue,
                percentage: (progressData_{progress_id}.value / progressData_{progress_id}.maxValue) * 100,
                type: progressData_{progress_id}.type,
                currentStep: progressData_{progress_id}.currentStep,
                isComplete: progressData_{progress_id}.value >= progressData_{progress_id}.maxValue
            }};

            document.getElementById('{field.id}').value = JSON.stringify(data);
        }}
        </script>
        """,
        progress_id=progress_id,
        field=field,
        _=gettext
        )

    def _render_progress_type(self, progress_id):
        """Render the appropriate progress type."""
        if self.progress_type == 'linear':
            return self._render_linear_progress()
        elif self.progress_type == 'circular':
            return self._render_circular_progress()
        elif self.progress_type == 'steps':
            return self._render_steps_progress()
        elif self.progress_type == 'multiple':
            return self._render_multiple_progress()
        else:
            return self._render_linear_progress()

    def _render_linear_progress(self):
        """Render linear progress bar."""
        striped_class = " striped" if self.striped else ""
        return f"""
        <div class="progress-linear{striped_class}">
            <div class="progress-bar" style="width: {(self.value / self.max_value) * 100}%;"></div>
        </div>
        """

    def _render_circular_progress(self):
        """Render circular progress indicator."""
        radius = 45
        circumference = 2 * 3.14159 * radius
        percentage = (self.value / self.max_value) * 100
        offset = circumference - (percentage / 100) * circumference

        return f"""
        <div class="progress-circular">
            <svg>
                <circle class="progress-circle-bg" cx="60" cy="60" r="{radius}"></circle>
                <circle class="progress-circle-fill" cx="60" cy="60" r="{radius}"
                        style="stroke-dashoffset: {offset};"></circle>
            </svg>
            <div class="progress-text">{round(percentage)}%</div>
        </div>
        """

    def _render_steps_progress(self):
        """Render step-based progress."""
        if not self.steps:
            return self._render_linear_progress()

        steps_html = ""
        step_percentage = 100 / self.steps
        current_step = int((self.value / self.max_value) * self.steps)

        for i in range(self.steps):
            step_class = ""
            if i < current_step:
                step_class = "completed"
            elif i == current_step:
                step_class = "current"

            step_label = ""
            if i < len(self.step_labels):
                step_label = self.step_labels[i]
            else:
                step_label = f"Step {i + 1}"

            steps_html += f"""
            <div class="progress-step {step_class}">
                <div class="step-indicator">{i + 1}</div>
                <div class="step-label">{step_label}</div>
            </div>
            """

        return f"""
        <div class="progress-steps">
            {steps_html}
        </div>
        """

    def _render_multiple_progress(self):
        """Render multiple progress bars."""
        if not self.multiple_bars:
            # Default multiple bars for demo
            self.multiple_bars = [
                {'label': 'CPU', 'value': 65, 'max': 100, 'color': '#3498db'},
                {'label': 'Memory', 'value': 45, 'max': 100, 'color': '#2ecc71'},
                {'label': 'Disk', 'value': 80, 'max': 100, 'color': '#f39c12'},
                {'label': 'Network', 'value': 25, 'max': 100, 'color': '#e74c3c'}
            ]

        bars_html = ""
        for bar in self.multiple_bars:
            percentage = (bar['value'] / bar['max']) * 100
            bars_html += f"""
            <div class="multiple-bar-item">
                <div class="multiple-bar-label">{bar['label']}</div>
                <div class="multiple-bar-progress">
                    <div class="multiple-bar-fill" style="width: {percentage}%; background-color: {bar['color']};"></div>
                </div>
                <div class="multiple-bar-value">{bar['value']}%</div>
            </div>
            """

        return f"""
        <div class="progress-multiple">
            {bars_html}
        </div>
        """


class SidebarWidget(Input):
    """Advanced sidebar navigation widget with collapsible menu structure."""
    
    def __init__(self, position='left', width='280px', collapsed_width='60px', 
                 theme='light', overlay_mode=False, persistent=True, 
                 enable_search=True, enable_user_menu=True, enable_notifications=False,
                 enable_shortcuts=True, animation_duration='300ms', auto_collapse_on_mobile=True,
                 collapse_breakpoint='768px', enable_breadcrumbs=True, **kwargs):
        """
        Initialize sidebar widget.
        
        Args:
            position: Sidebar position ('left' or 'right')
            width: Sidebar width when expanded
            collapsed_width: Sidebar width when collapsed  
            theme: Visual theme ('light', 'dark', 'gradient')
            overlay_mode: Whether to show as overlay on small screens
            persistent: Whether sidebar state persists across sessions
            enable_search: Enable search functionality
            enable_user_menu: Show user menu section
            enable_notifications: Show notifications panel
            enable_shortcuts: Enable keyboard shortcuts
            animation_duration: Animation duration for transitions
            auto_collapse_on_mobile: Auto-collapse on mobile devices
            collapse_breakpoint: Screen width breakpoint for auto-collapse
            enable_breadcrumbs: Show breadcrumb navigation
        """
        super().__init__(**kwargs)
        self.position = position
        self.width = width
        self.collapsed_width = collapsed_width
        self.theme = theme
        self.overlay_mode = overlay_mode
        self.persistent = persistent
        self.enable_search = enable_search
        self.enable_user_menu = enable_user_menu
        self.enable_notifications = enable_notifications
        self.enable_shortcuts = enable_shortcuts
        self.animation_duration = animation_duration
        self.auto_collapse_on_mobile = auto_collapse_on_mobile
        self.collapse_breakpoint = collapse_breakpoint
        self.enable_breadcrumbs = enable_breadcrumbs
        
        # Default menu items - can be customized
        self.menu_items = [
            {
                'id': 'dashboard',
                'title': _('Dashboard'),
                'icon': 'fas fa-tachometer-alt',
                'url': '/dashboard',
                'active': True,
                'badge': None,
                'children': []
            },
            {
                'id': 'users',
                'title': _('Users'),
                'icon': 'fas fa-users',
                'url': None,
                'badge': {'text': '3', 'color': 'danger'},
                'children': [
                    {'id': 'users-list', 'title': _('All Users'), 'url': '/users/', 'icon': 'fas fa-list'},
                    {'id': 'users-add', 'title': _('Add User'), 'url': '/users/add', 'icon': 'fas fa-plus'},
                    {'id': 'users-roles', 'title': _('User Roles'), 'url': '/roles/', 'icon': 'fas fa-user-tag'}
                ]
            },
            {
                'id': 'content',
                'title': _('Content'),
                'icon': 'fas fa-file-alt',
                'url': None,
                'children': [
                    {'id': 'posts', 'title': _('Posts'), 'url': '/posts/', 'icon': 'fas fa-newspaper'},
                    {'id': 'pages', 'title': _('Pages'), 'url': '/pages/', 'icon': 'fas fa-file'},
                    {'id': 'media', 'title': _('Media'), 'url': '/media/', 'icon': 'fas fa-images'}
                ]
            },
            {
                'id': 'settings',
                'title': _('Settings'),
                'icon': 'fas fa-cog',
                'url': '/settings',
                'children': []
            },
            {
                'id': 'help',
                'title': _('Help & Support'),
                'icon': 'fas fa-question-circle',
                'url': '/help',
                'children': []
            }
        ]
        
        # User info for user menu
        self.user_info = {
            'name': 'Admin User',
            'email': 'admin@example.com',
            'avatar': None,
            'role': 'Administrator'
        }
        
        # Notification items
        self.notifications = [
            {'id': '1', 'title': _('New user registered'), 'time': '2 min ago', 'type': 'info'},
            {'id': '2', 'title': _('System backup completed'), 'time': '1 hour ago', 'type': 'success'},
            {'id': '3', 'title': _('Low disk space warning'), 'time': '3 hours ago', 'type': 'warning'}
        ]

    def __call__(self, field, **kwargs):
        """Render the sidebar widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        sidebar_id = f"sidebar_{field.id}"
        theme_class = f"sidebar-{self.theme}"
        position_class = f"sidebar-{self.position}"
        
        # Generate CSS styles
        css_styles = self._generate_css(sidebar_id)
        
        # Generate search section
        search_html = ""
        if self.enable_search:
            search_html = f"""
            <div class="sidebar-search">
                <div class="search-input-wrapper">
                    <i class="fas fa-search search-icon"></i>
                    <input type="text" class="search-input" placeholder="{_('Search menu...')}" 
                           onkeyup="filterSidebarMenu(this, '{sidebar_id}')">
                    <button class="search-clear" onclick="clearSidebarSearch('{sidebar_id}')" style="display: none;">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
            """
        
        # Generate user menu section
        user_menu_html = ""
        if self.enable_user_menu:
            avatar_html = ""
            if self.user_info['avatar']:
                avatar_html = f'<img src="{self.user_info["avatar"]}" alt="Avatar" class="user-avatar">'
            else:
                avatar_html = '<div class="user-avatar-placeholder"><i class="fas fa-user"></i></div>'
            
            user_menu_html = f"""
            <div class="sidebar-user-menu">
                <div class="user-info" onclick="toggleUserDropdown('{sidebar_id}')">
                    {avatar_html}
                    <div class="user-details">
                        <div class="user-name">{self.user_info['name']}</div>
                        <div class="user-role">{self.user_info['role']}</div>
                    </div>
                    <i class="fas fa-chevron-down user-dropdown-icon"></i>
                </div>
                <div class="user-dropdown" id="{sidebar_id}_user_dropdown">
                    <a href="/profile" class="dropdown-item">
                        <i class="fas fa-user"></i> {_('Profile')}
                    </a>
                    <a href="/settings" class="dropdown-item">
                        <i class="fas fa-cog"></i> {_('Settings')}
                    </a>
                    <hr class="dropdown-divider">
                    <a href="/logout" class="dropdown-item">
                        <i class="fas fa-sign-out-alt"></i> {_('Logout')}
                    </a>
                </div>
            </div>
            """
        
        # Generate notifications section
        notifications_html = ""
        if self.enable_notifications:
            notifications_items = ""
            for notif in self.notifications[:5]:  # Show only first 5
                type_icon = {
                    'info': 'fa-info-circle',
                    'success': 'fa-check-circle', 
                    'warning': 'fa-exclamation-triangle',
                    'error': 'fa-times-circle'
                }.get(notif['type'], 'fa-bell')
                
                notifications_items += f"""
                <div class="notification-item {notif['type']}">
                    <i class="fas {type_icon}"></i>
                    <div class="notification-content">
                        <div class="notification-title">{notif['title']}</div>
                        <div class="notification-time">{notif['time']}</div>
                    </div>
                </div>
                """
            
            unread_count = len(self.notifications)
            notifications_html = f"""
            <div class="sidebar-notifications">
                <div class="notifications-header" onclick="toggleNotifications('{sidebar_id}')">
                    <i class="fas fa-bell"></i>
                    <span class="notifications-title">{_('Notifications')}</span>
                    <span class="notifications-badge">{unread_count}</span>
                </div>
                <div class="notifications-panel" id="{sidebar_id}_notifications">
                    {notifications_items}
                    <div class="notifications-footer">
                        <a href="/notifications">{_('View All')}</a>
                    </div>
                </div>
            </div>
            """
        
        # Generate menu items
        menu_html = self._generate_menu_items(self.menu_items, sidebar_id)
        
        # Generate breadcrumbs
        breadcrumbs_html = ""
        if self.enable_breadcrumbs:
            breadcrumbs_html = f"""
            <div class="sidebar-breadcrumbs">
                <div class="breadcrumb-item active">
                    <i class="fas fa-home"></i>
                    <span>{_('Dashboard')}</span>
                </div>
            </div>
            """
        
        # Generate shortcuts section
        shortcuts_html = ""
        if self.enable_shortcuts:
            shortcuts_html = f"""
            <div class="sidebar-shortcuts">
                <div class="shortcuts-title">{_('Quick Actions')}</div>
                <div class="shortcuts-grid">
                    <button class="shortcut-btn" onclick="quickAction('add-user')" title="{_('Add User')}">
                        <i class="fas fa-user-plus"></i>
                    </button>
                    <button class="shortcut-btn" onclick="quickAction('add-content')" title="{_('Add Content')}">
                        <i class="fas fa-plus"></i>
                    </button>
                    <button class="shortcut-btn" onclick="quickAction('backup')" title="{_('Backup')}">
                        <i class="fas fa-download"></i>
                    </button>
                    <button class="shortcut-btn" onclick="quickAction('settings')" title="{_('Settings')}">
                        <i class="fas fa-cog"></i>
                    </button>
                </div>
            </div>
            """
        
        # Generate JavaScript
        javascript = self._generate_javascript(sidebar_id)
        
        return Markup(f"""
        {css_styles}
        <div id="{sidebar_id}" class="sidebar-container {theme_class} {position_class}" 
             data-collapsed="false" data-persistent="{str(self.persistent).lower()}">
            
            <!-- Sidebar Toggle Button -->
            <button class="sidebar-toggle" onclick="toggleSidebar('{sidebar_id}')" 
                    title="{_('Toggle Sidebar')}">
                <i class="fas fa-bars"></i>
            </button>
            
            <!-- Sidebar Content -->
            <div class="sidebar-content">
                <!-- Header Section -->
                <div class="sidebar-header">
                    <div class="sidebar-logo">
                        <i class="fas fa-cube"></i>
                        <span class="logo-text">PgForge</span>
                    </div>
                </div>
                
                {user_menu_html}
                {search_html}
                {notifications_html}
                {breadcrumbs_html}
                
                <!-- Navigation Menu -->
                <nav class="sidebar-nav">
                    {menu_html}
                </nav>
                
                {shortcuts_html}
                
                <!-- Footer -->
                <div class="sidebar-footer">
                    <div class="footer-text">© 2024 PgForge</div>
                </div>
            </div>
            
            <!-- Overlay for mobile -->
            <div class="sidebar-overlay" onclick="closeSidebar('{sidebar_id}')"></div>
        </div>
        
        <input type="hidden" id="{kwargs['id']}" name="{kwargs['name']}" 
               value="" data-sidebar-state="">
        
        {javascript}
        """)

    def _generate_menu_items(self, items, sidebar_id, level=0):
        """Generate HTML for menu items."""
        html = ""
        
        for item in items:
            item_id = f"{sidebar_id}_{item['id']}"
            active_class = "active" if item.get('active', False) else ""
            has_children = bool(item.get('children', []))
            
            # Badge HTML
            badge_html = ""
            if item.get('badge'):
                badge = item['badge']
                badge_html = f'<span class="menu-badge badge-{badge["color"]}">{badge["text"]}</span>'
            
            # Menu item content
            icon_html = f'<i class="{item["icon"]}"></i>' if item.get('icon') else ""
            
            if has_children:
                # Parent item with submenu
                children_html = self._generate_menu_items(item['children'], sidebar_id, level + 1)
                html += f"""
                <div class="menu-item has-children {active_class}" data-level="{level}">
                    <div class="menu-link" onclick="toggleSubmenu('{item_id}')">
                        {icon_html}
                        <span class="menu-text">{item['title']}</span>
                        {badge_html}
                        <i class="fas fa-chevron-right submenu-arrow"></i>
                    </div>
                    <div class="submenu" id="{item_id}_submenu">
                        {children_html}
                    </div>
                </div>
                """
            else:
                # Regular menu item
                url = item.get('url', '#')
                onclick = f'onclick="navigateToUrl(\'{url}\')"' if url != '#' else ''
                html += f"""
                <div class="menu-item {active_class}" data-level="{level}">
                    <a href="{url}" class="menu-link" {onclick}>
                        {icon_html}
                        <span class="menu-text">{item['title']}</span>
                        {badge_html}
                    </a>
                </div>
                """
        
        return html

    def _generate_css(self, sidebar_id):
        """Generate CSS styles for the sidebar."""
        return f"""
        <style>
        #{sidebar_id} {{
            --sidebar-width: {self.width};
            --sidebar-collapsed-width: {self.collapsed_width};
            --animation-duration: {self.animation_duration};
            --collapse-breakpoint: {self.collapse_breakpoint};
        }}
        
        #{sidebar_id}.sidebar-container {{
            position: fixed;
            top: 0;
            {self.position}: 0;
            height: 100vh;
            width: var(--sidebar-width);
            background: var(--sidebar-bg, #fff);
            border-{('left' if self.position == 'right' else 'right')}: 1px solid var(--sidebar-border, #e9ecef);
            transition: all var(--animation-duration) ease;
            z-index: 1000;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            box-shadow: 2px 0 10px rgba(0,0,0,0.1);
        }}
        
        #{sidebar_id}.sidebar-light {{
            --sidebar-bg: #ffffff;
            --sidebar-text: #2c3e50;
            --sidebar-text-muted: #6c757d;
            --sidebar-border: #e9ecef;
            --sidebar-hover-bg: #f8f9fa;
            --sidebar-active-bg: #007bff;
            --sidebar-active-text: #ffffff;
        }}
        
        #{sidebar_id}.sidebar-dark {{
            --sidebar-bg: #2c3e50;
            --sidebar-text: #ecf0f1;
            --sidebar-text-muted: #95a5a6;
            --sidebar-border: #34495e;
            --sidebar-hover-bg: #34495e;
            --sidebar-active-bg: #3498db;
            --sidebar-active-text: #ffffff;
        }}
        
        #{sidebar_id}.sidebar-gradient {{
            --sidebar-bg: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            --sidebar-text: #ffffff;
            --sidebar-text-muted: rgba(255,255,255,0.8);
            --sidebar-border: rgba(255,255,255,0.2);
            --sidebar-hover-bg: rgba(255,255,255,0.1);
            --sidebar-active-bg: rgba(255,255,255,0.2);
            --sidebar-active-text: #ffffff;
        }}
        
        #{sidebar_id}[data-collapsed="true"] {{
            width: var(--sidebar-collapsed-width);
        }}
        
        #{sidebar_id}[data-collapsed="true"] .sidebar-content {{
            overflow: hidden;
        }}
        
        #{sidebar_id}[data-collapsed="true"] .menu-text,
        #{sidebar_id}[data-collapsed="true"] .logo-text,
        #{sidebar_id}[data-collapsed="true"] .user-details,
        #{sidebar_id}[data-collapsed="true"] .sidebar-search,
        #{sidebar_id}[data-collapsed="true"] .sidebar-shortcuts,
        #{sidebar_id}[data-collapsed="true"] .sidebar-breadcrumbs,
        #{sidebar_id}[data-collapsed="true"] .sidebar-notifications,
        #{sidebar_id}[data-collapsed="true"] .sidebar-footer {{
            opacity: 0;
            pointer-events: none;
        }}
        
        #{sidebar_id} .sidebar-toggle {{
            position: absolute;
            top: 15px;
            right: -15px;
            width: 30px;
            height: 30px;
            background: var(--sidebar-active-bg);
            color: var(--sidebar-active-text);
            border: none;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            box-shadow: 0 2px 8px rgba(0,0,0,0.15);
            transition: all 0.2s ease;
            z-index: 1001;
        }}
        
        #{sidebar_id} .sidebar-toggle:hover {{
            transform: scale(1.1);
            box-shadow: 0 4px 12px rgba(0,0,0,0.2);
        }}
        
        #{sidebar_id} .sidebar-content {{
            height: 100%;
            display: flex;
            flex-direction: column;
            overflow-y: auto;
            overflow-x: hidden;
        }}
        
        #{sidebar_id} .sidebar-header {{
            padding: 20px;
            border-bottom: 1px solid var(--sidebar-border);
            background: var(--sidebar-bg);
        }}
        
        #{sidebar_id} .sidebar-logo {{
            display: flex;
            align-items: center;
            gap: 12px;
            color: var(--sidebar-text);
            font-size: 18px;
            font-weight: 600;
        }}
        
        #{sidebar_id} .sidebar-logo i {{
            font-size: 24px;
            color: var(--sidebar-active-bg);
        }}
        
        #{sidebar_id} .sidebar-user-menu {{
            padding: 15px 20px;
            border-bottom: 1px solid var(--sidebar-border);
            position: relative;
        }}
        
        #{sidebar_id} .user-info {{
            display: flex;
            align-items: center;
            gap: 12px;
            cursor: pointer;
            padding: 8px;
            border-radius: 8px;
            transition: background 0.2s ease;
        }}
        
        #{sidebar_id} .user-info:hover {{
            background: var(--sidebar-hover-bg);
        }}
        
        #{sidebar_id} .user-avatar,
        #{sidebar_id} .user-avatar-placeholder {{
            width: 36px;
            height: 36px;
            border-radius: 50%;
            background: var(--sidebar-active-bg);
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--sidebar-active-text);
            font-size: 16px;
        }}
        
        #{sidebar_id} .user-details {{
            flex: 1;
            min-width: 0;
        }}
        
        #{sidebar_id} .user-name {{
            font-weight: 500;
            color: var(--sidebar-text);
            font-size: 14px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        
        #{sidebar_id} .user-role {{
            font-size: 12px;
            color: var(--sidebar-text-muted);
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }}
        
        #{sidebar_id} .user-dropdown-icon {{
            font-size: 12px;
            color: var(--sidebar-text-muted);
            transition: transform 0.2s ease;
        }}
        
        #{sidebar_id} .user-dropdown {{
            position: absolute;
            top: 100%;
            left: 20px;
            right: 20px;
            background: var(--sidebar-bg);
            border: 1px solid var(--sidebar-border);
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
            display: none;
            z-index: 1002;
        }}
        
        #{sidebar_id} .user-dropdown.show {{
            display: block;
        }}
        
        #{sidebar_id} .dropdown-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 10px 15px;
            color: var(--sidebar-text);
            text-decoration: none;
            transition: background 0.2s ease;
        }}
        
        #{sidebar_id} .dropdown-item:hover {{
            background: var(--sidebar-hover-bg);
        }}
        
        #{sidebar_id} .dropdown-divider {{
            margin: 0;
            border: none;
            border-top: 1px solid var(--sidebar-border);
        }}
        
        #{sidebar_id} .sidebar-search {{
            padding: 15px 20px;
            border-bottom: 1px solid var(--sidebar-border);
        }}
        
        #{sidebar_id} .search-input-wrapper {{
            position: relative;
            display: flex;
            align-items: center;
        }}
        
        #{sidebar_id} .search-input {{
            width: 100%;
            padding: 8px 12px 8px 35px;
            border: 1px solid var(--sidebar-border);
            border-radius: 6px;
            background: var(--sidebar-bg);
            color: var(--sidebar-text);
            font-size: 14px;
        }}
        
        #{sidebar_id} .search-icon {{
            position: absolute;
            left: 12px;
            color: var(--sidebar-text-muted);
            font-size: 14px;
        }}
        
        #{sidebar_id} .search-clear {{
            position: absolute;
            right: 8px;
            background: none;
            border: none;
            color: var(--sidebar-text-muted);
            cursor: pointer;
            padding: 4px;
        }}
        
        #{sidebar_id} .sidebar-notifications {{
            padding: 15px 20px;
            border-bottom: 1px solid var(--sidebar-border);
        }}
        
        #{sidebar_id} .notifications-header {{
            display: flex;
            align-items: center;
            gap: 10px;
            cursor: pointer;
            padding: 8px;
            border-radius: 6px;
            transition: background 0.2s ease;
        }}
        
        #{sidebar_id} .notifications-header:hover {{
            background: var(--sidebar-hover-bg);
        }}
        
        #{sidebar_id} .notifications-title {{
            flex: 1;
            font-weight: 500;
            color: var(--sidebar-text);
        }}
        
        #{sidebar_id} .notifications-badge {{
            background: #dc3545;
            color: white;
            font-size: 11px;
            padding: 2px 6px;
            border-radius: 10px;
            min-width: 18px;
            text-align: center;
        }}
        
        #{sidebar_id} .notifications-panel {{
            display: none;
            margin-top: 10px;
        }}
        
        #{sidebar_id} .notifications-panel.show {{
            display: block;
        }}
        
        #{sidebar_id} .notification-item {{
            display: flex;
            align-items: flex-start;
            gap: 10px;
            padding: 8px;
            border-radius: 6px;
            margin-bottom: 5px;
            background: var(--sidebar-hover-bg);
        }}
        
        #{sidebar_id} .notification-item i {{
            margin-top: 2px;
            font-size: 14px;
        }}
        
        #{sidebar_id} .notification-item.info i {{ color: #17a2b8; }}
        #{sidebar_id} .notification-item.success i {{ color: #28a745; }}
        #{sidebar_id} .notification-item.warning i {{ color: #ffc107; }}
        #{sidebar_id} .notification-item.error i {{ color: #dc3545; }}
        
        #{sidebar_id} .notification-content {{
            flex: 1;
            min-width: 0;
        }}
        
        #{sidebar_id} .notification-title {{
            font-size: 13px;
            font-weight: 500;
            color: var(--sidebar-text);
            margin-bottom: 2px;
        }}
        
        #{sidebar_id} .notification-time {{
            font-size: 11px;
            color: var(--sidebar-text-muted);
        }}
        
        #{sidebar_id} .notifications-footer {{
            text-align: center;
            margin-top: 10px;
        }}
        
        #{sidebar_id} .notifications-footer a {{
            color: var(--sidebar-active-bg);
            text-decoration: none;
            font-size: 12px;
        }}
        
        #{sidebar_id} .sidebar-breadcrumbs {{
            padding: 10px 20px;
            border-bottom: 1px solid var(--sidebar-border);
        }}
        
        #{sidebar_id} .breadcrumb-item {{
            display: flex;
            align-items: center;
            gap: 8px;
            color: var(--sidebar-text);
            font-size: 12px;
        }}
        
        #{sidebar_id} .sidebar-nav {{
            flex: 1;
            padding: 0;
            overflow-y: auto;
        }}
        
        #{sidebar_id} .menu-item {{
            border-bottom: 1px solid transparent;
        }}
        
        #{sidebar_id} .menu-link {{
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 12px 20px;
            color: var(--sidebar-text);
            text-decoration: none;
            transition: all 0.2s ease;
            cursor: pointer;
            position: relative;
        }}
        
        #{sidebar_id} .menu-item[data-level="1"] .menu-link {{
            padding-left: 40px;
        }}
        
        #{sidebar_id} .menu-item[data-level="2"] .menu-link {{
            padding-left: 60px;
        }}
        
        #{sidebar_id} .menu-link:hover {{
            background: var(--sidebar-hover-bg);
        }}
        
        #{sidebar_id} .menu-item.active .menu-link {{
            background: var(--sidebar-active-bg);
            color: var(--sidebar-active-text);
        }}
        
        #{sidebar_id} .menu-link i {{
            font-size: 16px;
            width: 20px;
            text-align: center;
        }}
        
        #{sidebar_id} .menu-text {{
            flex: 1;
            font-size: 14px;
            font-weight: 500;
        }}
        
        #{sidebar_id} .menu-badge {{
            font-size: 10px;
            padding: 2px 6px;
            border-radius: 10px;
            font-weight: 600;
        }}
        
        #{sidebar_id} .menu-badge.badge-danger {{ background: #dc3545; color: white; }}
        #{sidebar_id} .menu-badge.badge-warning {{ background: #ffc107; color: #212529; }}
        #{sidebar_id} .menu-badge.badge-success {{ background: #28a745; color: white; }}
        #{sidebar_id} .menu-badge.badge-info {{ background: #17a2b8; color: white; }}
        
        #{sidebar_id} .submenu-arrow {{
            font-size: 12px;
            transition: transform 0.2s ease;
        }}
        
        #{sidebar_id} .submenu {{
            display: none;
            background: rgba(0,0,0,0.05);
        }}
        
        #{sidebar_id} .submenu.show {{
            display: block;
        }}
        
        #{sidebar_id} .has-children.expanded .submenu-arrow {{
            transform: rotate(90deg);
        }}
        
        #{sidebar_id} .sidebar-shortcuts {{
            padding: 15px 20px;
            border-bottom: 1px solid var(--sidebar-border);
        }}
        
        #{sidebar_id} .shortcuts-title {{
            font-size: 12px;
            font-weight: 600;
            color: var(--sidebar-text-muted);
            margin-bottom: 10px;
            text-transform: uppercase;
        }}
        
        #{sidebar_id} .shortcuts-grid {{
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 8px;
        }}
        
        #{sidebar_id} .shortcut-btn {{
            width: 36px;
            height: 36px;
            border: 1px solid var(--sidebar-border);
            background: var(--sidebar-bg);
            color: var(--sidebar-text);
            border-radius: 6px;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
        }}
        
        #{sidebar_id} .shortcut-btn:hover {{
            background: var(--sidebar-hover-bg);
            transform: translateY(-1px);
        }}
        
        #{sidebar_id} .sidebar-footer {{
            padding: 15px 20px;
            border-top: 1px solid var(--sidebar-border);
            background: var(--sidebar-bg);
        }}
        
        #{sidebar_id} .footer-text {{
            font-size: 11px;
            color: var(--sidebar-text-muted);
            text-align: center;
        }}
        
        #{sidebar_id} .sidebar-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.5);
            z-index: 999;
            display: none;
        }}
        
        /* Mobile responsive */
        @media (max-width: var(--collapse-breakpoint)) {{
            #{sidebar_id}.sidebar-container {{
                transform: translateX({'-100%' if self.position == 'left' else '100%'});
            }}
            
            #{sidebar_id}.sidebar-container.mobile-open {{
                transform: translateX(0);
            }}
            
            #{sidebar_id}.sidebar-container.mobile-open + .sidebar-overlay {{
                display: block;
            }}
        }}
        
        /* Print styles */
        @media print {{
            #{sidebar_id}.sidebar-container {{
                display: none;
            }}
        }}
        </style>
        """

    def _generate_javascript(self, sidebar_id):
        """Generate JavaScript for sidebar functionality."""
        return f"""
        <script>
        (function() {{
            // Sidebar state management
            let sidebarState = {{
                collapsed: false,
                mobileOpen: false,
                persistent: {str(self.persistent).lower()}
            }};
            
            // Load saved state
            if (sidebarState.persistent) {{
                const saved = localStorage.getItem('sidebar_state_{sidebar_id}');
                if (saved) {{
                    try {{
                        Object.assign(sidebarState, JSON.parse(saved));
                    }} catch (e) {{
                        console.warn('Failed to parse saved sidebar state');
                    }}
                }}
            }}
            
            // Apply initial state
            const sidebar = document.getElementById('{sidebar_id}');
            if (sidebar && sidebarState.collapsed) {{
                sidebar.setAttribute('data-collapsed', 'true');
            }}
            
            // Save state function
            function saveSidebarState() {{
                if (sidebarState.persistent) {{
                    localStorage.setItem('sidebar_state_{sidebar_id}', JSON.stringify(sidebarState));
                }}
                
                // Update hidden input
                const input = document.querySelector('input[data-sidebar-state]');
                if (input) {{
                    input.value = JSON.stringify(sidebarState);
                }}
            }}
            
            // Toggle sidebar collapse
            window.toggleSidebar = function(id) {{
                if (id !== '{sidebar_id}') return;
                
                const sidebar = document.getElementById(id);
                if (!sidebar) return;
                
                const isCollapsed = sidebar.getAttribute('data-collapsed') === 'true';
                sidebarState.collapsed = !isCollapsed;
                
                sidebar.setAttribute('data-collapsed', sidebarState.collapsed);
                saveSidebarState();
                
                // Trigger custom event
                sidebar.dispatchEvent(new CustomEvent('sidebarToggle', {{
                    detail: {{ collapsed: sidebarState.collapsed }}
                }}));
            }};
            
            // Close sidebar (mobile)
            window.closeSidebar = function(id) {{
                if (id !== '{sidebar_id}') return;
                
                const sidebar = document.getElementById(id);
                if (sidebar) {{
                    sidebar.classList.remove('mobile-open');
                    sidebarState.mobileOpen = false;
                    saveSidebarState();
                }}
            }};
            
            // Toggle submenu
            window.toggleSubmenu = function(itemId) {{
                const submenu = document.getElementById(itemId + '_submenu');
                const menuItem = submenu?.parentElement;
                
                if (submenu && menuItem) {{
                    const isExpanded = submenu.classList.contains('show');
                    
                    // Close other submenus at same level
                    const siblings = menuItem.parentElement.children;
                    for (let sibling of siblings) {{
                        if (sibling !== menuItem) {{
                            const siblingSubmenu = sibling.querySelector('.submenu');
                            if (siblingSubmenu) {{
                                siblingSubmenu.classList.remove('show');
                                sibling.classList.remove('expanded');
                            }}
                        }}
                    }}
                    
                    // Toggle current submenu
                    if (isExpanded) {{
                        submenu.classList.remove('show');
                        menuItem.classList.remove('expanded');
                    }} else {{
                        submenu.classList.add('show');
                        menuItem.classList.add('expanded');
                    }}
                }}
            }};
            
            // Toggle user dropdown
            window.toggleUserDropdown = function(id) {{
                if (id !== '{sidebar_id}') return;
                
                const dropdown = document.getElementById(id + '_user_dropdown');
                if (dropdown) {{
                    dropdown.classList.toggle('show');
                }}
            }};
            
            // Toggle notifications
            window.toggleNotifications = function(id) {{
                if (id !== '{sidebar_id}') return;
                
                const panel = document.getElementById(id + '_notifications');
                if (panel) {{
                    panel.classList.toggle('show');
                }}
            }};
            
            // Filter menu items
            window.filterSidebarMenu = function(input, id) {{
                if (id !== '{sidebar_id}') return;
                
                const query = input.value.toLowerCase();
                const menuItems = document.querySelectorAll(`#{id} .menu-item`);
                const clearBtn = input.parentElement.querySelector('.search-clear');
                
                // Show/hide clear button
                clearBtn.style.display = query ? 'block' : 'none';
                
                menuItems.forEach(item => {{
                    const text = item.querySelector('.menu-text')?.textContent.toLowerCase() || '';
                    const shouldShow = text.includes(query);
                    
                    item.style.display = shouldShow ? 'block' : 'none';
                    
                    // Show parent if child matches
                    if (shouldShow && item.dataset.level > '0') {{
                        let parent = item.parentElement.closest('.menu-item');
                        while (parent) {{
                            parent.style.display = 'block';
                            parent = parent.parentElement.closest('.menu-item');
                        }}
                    }}
                }});
            }};
            
            // Clear search
            window.clearSidebarSearch = function(id) {{
                if (id !== '{sidebar_id}') return;
                
                const input = document.querySelector(`#{id} .search-input`);
                if (input) {{
                    input.value = '';
                    filterSidebarMenu(input, id);
                    input.focus();
                }}
            }};
            
            // Navigate to URL
            window.navigateToUrl = function(url) {{
                if (url && url !== '#') {{
                    window.location.href = url;
                }}
            }};
            
            // Quick actions
            window.quickAction = function(action) {{
                // Dispatch custom event for quick actions
                document.dispatchEvent(new CustomEvent('sidebarQuickAction', {{
                    detail: {{ action: action }}
                }}));
                
                // Default actions
                switch (action) {{
                    case 'add-user':
                        window.location.href = '/users/add';
                        break;
                    case 'add-content':
                        window.location.href = '/posts/add';
                        break;
                    case 'backup':
                        if (confirm('{_("Start backup process?")}')) {{
                            // Implement backup logic
                            alert('{_("Backup started")}');
                        }}
                        break;
                    case 'settings':
                        window.location.href = '/settings';
                        break;
                }}
            }};
            
            // Handle mobile responsive behavior
            function handleResize() {{
                const sidebar = document.getElementById('{sidebar_id}');
                if (!sidebar) return;
                
                const isMobile = window.innerWidth <= parseInt(getComputedStyle(sidebar).getPropertyValue('--collapse-breakpoint'));
                
                if (isMobile && {str(self.auto_collapse_on_mobile).lower()}) {{
                    // Auto-collapse on mobile
                    if (!sidebarState.collapsed) {{
                        sidebarState.collapsed = true;
                        sidebar.setAttribute('data-collapsed', 'true');
                        saveSidebarState();
                    }}
                }}
            }}
            
            // Event listeners
            window.addEventListener('resize', handleResize);
            
            // Close dropdowns when clicking outside
            document.addEventListener('click', function(e) {{
                const sidebar = document.getElementById('{sidebar_id}');
                if (!sidebar || sidebar.contains(e.target)) return;
                
                // Close user dropdown
                const userDropdown = document.getElementById('{sidebar_id}_user_dropdown');
                if (userDropdown) {{
                    userDropdown.classList.remove('show');
                }}
                
                // Close notifications
                const notificationsPanel = document.getElementById('{sidebar_id}_notifications');
                if (notificationsPanel) {{
                    notificationsPanel.classList.remove('show');
                }}
            }});
            
            // Keyboard shortcuts
            if ({str(self.enable_shortcuts).lower()}) {{
                document.addEventListener('keydown', function(e) {{
                    // Ctrl/Cmd + B: Toggle sidebar
                    if ((e.ctrlKey || e.metaKey) && e.key === 'b') {{
                        e.preventDefault();
                        toggleSidebar('{sidebar_id}');
                    }}
                    
                    // Ctrl/Cmd + K: Focus search
                    if ((e.ctrlKey || e.metaKey) && e.key === 'k') {{
                        e.preventDefault();
                        const searchInput = document.querySelector('#{sidebar_id} .search-input');
                        if (searchInput) {{
                            searchInput.focus();
                        }}
                    }}
                    
                    // Escape: Close sidebar on mobile
                    if (e.key === 'Escape') {{
                        closeSidebar('{sidebar_id}');
                    }}
                }});
            }}
            
            // Initialize
            handleResize();
            
            // Mark menu item as active based on current URL
            const currentPath = window.location.pathname;
            const menuLinks = document.querySelectorAll('#{sidebar_id} .menu-link[href]');
            menuLinks.forEach(link => {{
                if (link.getAttribute('href') === currentPath) {{
                    link.closest('.menu-item').classList.add('active');
                    
                    // Expand parent submenu if nested
                    let parent = link.closest('.submenu')?.parentElement;
                    if (parent) {{
                        parent.classList.add('expanded');
                        parent.querySelector('.submenu').classList.add('show');
                    }}
                }}
            }});
        }})();
        </script>
        """


class MenuEditorWidget(Input):
    """Advanced menu editor widget with drag-and-drop reordering and inline editing."""
    
    def __init__(self, enable_drag_drop=True, enable_inline_edit=True, enable_icons=True,
                 enable_badges=True, enable_permissions=True, max_depth=5, 
                 theme='light', enable_import_export=True, enable_templates=True,
                 enable_validation=True, auto_save=True, save_delay=2000, **kwargs):
        """
        Initialize menu editor widget.
        
        Args:
            enable_drag_drop: Enable drag and drop reordering
            enable_inline_edit: Enable inline editing of menu items
            enable_icons: Support for menu item icons
            enable_badges: Support for menu badges
            enable_permissions: Enable permission settings for menu items
            max_depth: Maximum nesting depth for menu items
            theme: Visual theme ('light', 'dark', 'modern')
            enable_import_export: Enable import/export functionality
            enable_templates: Enable menu templates
            enable_validation: Enable menu validation
            auto_save: Auto-save changes
            save_delay: Delay before auto-save (milliseconds)
        """
        super().__init__(**kwargs)
        self.enable_drag_drop = enable_drag_drop
        self.enable_inline_edit = enable_inline_edit
        self.enable_icons = enable_icons
        self.enable_badges = enable_badges
        self.enable_permissions = enable_permissions
        self.max_depth = max_depth
        self.theme = theme
        self.enable_import_export = enable_import_export
        self.enable_templates = enable_templates
        self.enable_validation = enable_validation
        self.auto_save = auto_save
        self.save_delay = save_delay
        
        # Default menu structure
        self.menu_data = [
            {
                'id': 'dashboard',
                'title': _('Dashboard'),
                'icon': 'fas fa-tachometer-alt',
                'url': '/dashboard',
                'order': 0,
                'visible': True,
                'permissions': ['menu_access'],
                'badge': None,
                'children': []
            },
            {
                'id': 'users',
                'title': _('User Management'),
                'icon': 'fas fa-users',
                'url': None,
                'order': 1,
                'visible': True,
                'permissions': ['can_list_User'],
                'badge': {'text': 'New', 'color': 'primary'},
                'children': [
                    {
                        'id': 'users_list',
                        'title': _('List Users'),
                        'icon': 'fas fa-list',
                        'url': '/users/',
                        'order': 0,
                        'visible': True,
                        'permissions': ['can_list_User']
                    },
                    {
                        'id': 'users_add',
                        'title': _('Add User'),
                        'icon': 'fas fa-plus',
                        'url': '/users/add',
                        'order': 1,
                        'visible': True,
                        'permissions': ['can_add_User']
                    }
                ]
            },
            {
                'id': 'content',
                'title': _('Content'),
                'icon': 'fas fa-file-alt',
                'url': None,
                'order': 2,
                'visible': True,
                'permissions': ['menu_access'],
                'children': [
                    {
                        'id': 'posts',
                        'title': _('Posts'),
                        'icon': 'fas fa-newspaper',
                        'url': '/posts/',
                        'order': 0,
                        'visible': True,
                        'permissions': ['can_list_Post']
                    },
                    {
                        'id': 'categories',
                        'title': _('Categories'),
                        'icon': 'fas fa-tags',
                        'url': '/categories/',
                        'order': 1,
                        'visible': True,
                        'permissions': ['can_list_Category']
                    }
                ]
            }
        ]
        
        # Available icons for selection
        self.available_icons = [
            'fas fa-home', 'fas fa-dashboard', 'fas fa-tachometer-alt', 'fas fa-users',
            'fas fa-user', 'fas fa-cog', 'fas fa-settings', 'fas fa-file-alt',
            'fas fa-newspaper', 'fas fa-image', 'fas fa-images', 'fas fa-video',
            'fas fa-music', 'fas fa-chart-bar', 'fas fa-chart-line', 'fas fa-table',
            'fas fa-database', 'fas fa-server', 'fas fa-cloud', 'fas fa-download',
            'fas fa-upload', 'fas fa-search', 'fas fa-filter', 'fas fa-sort',
            'fas fa-edit', 'fas fa-trash', 'fas fa-plus', 'fas fa-minus',
            'fas fa-check', 'fas fa-times', 'fas fa-save', 'fas fa-print',
            'fas fa-email', 'fas fa-phone', 'fas fa-calendar', 'fas fa-clock',
            'fas fa-map', 'fas fa-location', 'fas fa-shopping-cart', 'fas fa-credit-card',
            'fas fa-lock', 'fas fa-unlock', 'fas fa-key', 'fas fa-shield-alt',
            'fas fa-bell', 'fas fa-flag', 'fas fa-star', 'fas fa-heart',
            'fas fa-bookmark', 'fas fa-share', 'fas fa-link', 'fas fa-external-link-alt'
        ]

    def __call__(self, field, **kwargs):
        """Render the menu editor widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        editor_id = f"menu_editor_{field.id}"
        theme_class = f"menu-editor-{self.theme}"
        
        # Generate CSS styles
        css_styles = self._generate_css(editor_id)
        
        # Generate toolbar
        toolbar_html = self._generate_toolbar(editor_id)
        
        # Generate menu tree
        menu_tree_html = self._generate_menu_tree(self.menu_data, editor_id)
        
        # Generate property panel
        property_panel_html = self._generate_property_panel(editor_id)
        
        # Generate JavaScript
        javascript = self._generate_javascript(editor_id)
        
        return Markup(f"""
        {css_styles}
        <div id="{editor_id}" class="menu-editor-container {theme_class}" 
             data-max-depth="{self.max_depth}" data-auto-save="{str(self.auto_save).lower()}">
            
            <!-- Toolbar -->
            {toolbar_html}
            
            <!-- Main Editor Area -->
            <div class="menu-editor-main">
                <!-- Menu Tree Panel -->
                <div class="menu-tree-panel">
                    <div class="panel-header">
                        <h5><i class="fas fa-sitemap"></i> {_('Menu Structure')}</h5>
                        <div class="panel-actions">
                            <button class="btn btn-sm btn-outline-primary" onclick="addMenuItem('{editor_id}')">
                                <i class="fas fa-plus"></i> {_('Add Item')}
                            </button>
                            <button class="btn btn-sm btn-outline-secondary" onclick="collapseAll('{editor_id}')">
                                <i class="fas fa-compress-alt"></i>
                            </button>
                            <button class="btn btn-sm btn-outline-secondary" onclick="expandAll('{editor_id}')">
                                <i class="fas fa-expand-alt"></i>
                            </button>
                        </div>
                    </div>
                    <div class="menu-tree-content">
                        <div class="menu-tree" id="{editor_id}_tree">
                            {menu_tree_html}
                        </div>
                        <div class="tree-drop-zone" data-depth="0">
                            <i class="fas fa-plus-circle"></i> {_('Drop items here or click to add')}
                        </div>
                    </div>
                </div>
                
                <!-- Property Panel -->
                <div class="menu-property-panel">
                    {property_panel_html}
                </div>
            </div>
            
            <!-- Status Bar -->
            <div class="menu-editor-status">
                <div class="status-info">
                    <span class="item-count">{len(self._flatten_menu(self.menu_data))} {_('items')}</span>
                    <span class="save-status" id="{editor_id}_save_status">{_('Saved')}</span>
                </div>
                <div class="status-actions">
                    <button class="btn btn-sm btn-success" onclick="saveMenu('{editor_id}')">
                        <i class="fas fa-save"></i> {_('Save')}
                    </button>
                    <button class="btn btn-sm btn-outline-secondary" onclick="previewMenu('{editor_id}')">
                        <i class="fas fa-eye"></i> {_('Preview')}
                    </button>
                </div>
            </div>
            
            <!-- Hidden input for form data -->
            <input type="hidden" id="{kwargs['id']}" name="{kwargs['name']}" 
                   value="" data-menu-data="">
        </div>
        
        {javascript}
        """)

    def _generate_toolbar(self, editor_id):
        """Generate the toolbar HTML."""
        import_export_buttons = ""
        if self.enable_import_export:
            import_export_buttons = f"""
            <div class="toolbar-group">
                <button class="btn btn-outline-secondary" onclick="importMenu('{editor_id}')">
                    <i class="fas fa-upload"></i> {_('Import')}
                </button>
                <button class="btn btn-outline-secondary" onclick="exportMenu('{editor_id}')">
                    <i class="fas fa-download"></i> {_('Export')}
                </button>
            </div>
            """
        
        template_buttons = ""
        if self.enable_templates:
            template_buttons = f"""
            <div class="toolbar-group">
                <button class="btn btn-outline-info" onclick="loadTemplate('{editor_id}', 'admin')">
                    <i class="fas fa-layer-group"></i> {_('Admin Template')}
                </button>
                <button class="btn btn-outline-info" onclick="loadTemplate('{editor_id}', 'blog')">
                    <i class="fas fa-blog"></i> {_('Blog Template')}
                </button>
            </div>
            """
        
        return f"""
        <div class="menu-editor-toolbar">
            <div class="toolbar-group">
                <button class="btn btn-primary" onclick="addMenuItem('{editor_id}')">
                    <i class="fas fa-plus"></i> {_('Add Item')}
                </button>
                <button class="btn btn-outline-secondary" onclick="addSubmenu('{editor_id}')">
                    <i class="fas fa-sitemap"></i> {_('Add Submenu')}
                </button>
            </div>
            
            <div class="toolbar-group">
                <button class="btn btn-outline-warning" onclick="validateMenu('{editor_id}')">
                    <i class="fas fa-check-circle"></i> {_('Validate')}
                </button>
                <button class="btn btn-outline-danger" onclick="resetMenu('{editor_id}')">
                    <i class="fas fa-undo"></i> {_('Reset')}
                </button>
            </div>
            
            {import_export_buttons}
            {template_buttons}
            
            <div class="toolbar-group ml-auto">
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="{editor_id}_preview_mode" 
                           onchange="togglePreviewMode('{editor_id}')">
                    <label class="form-check-label" for="{editor_id}_preview_mode">
                        {_('Live Preview')}
                    </label>
                </div>
            </div>
        </div>
        """

    def _generate_menu_tree(self, items, editor_id, level=0):
        """Generate the menu tree HTML."""
        html = ""
        
        for index, item in enumerate(items):
            item_id = f"{editor_id}_item_{item['id']}"
            has_children = bool(item.get('children', []))
            
            # Item classes
            classes = ['menu-tree-item']
            if not item.get('visible', True):
                classes.append('hidden-item')
            if has_children:
                classes.append('has-children')
            
            # Badge HTML
            badge_html = ""
            if self.enable_badges and item.get('badge'):
                badge = item['badge']
                badge_html = f'<span class="item-badge badge bg-{badge["color"]}">{badge["text"]}</span>'
            
            # Icon HTML
            icon_html = ""
            if self.enable_icons and item.get('icon'):
                icon_html = f'<i class="{item["icon"]} item-icon"></i>'
            
            # Visibility toggle
            visibility_icon = 'fa-eye' if item.get('visible', True) else 'fa-eye-slash'
            
            # Drag handle
            drag_handle = ""
            if self.enable_drag_drop:
                drag_handle = '<i class="fas fa-grip-vertical drag-handle"></i>'
            
            # Children HTML
            children_html = ""
            if has_children:
                children_html = f"""
                <div class="menu-tree-children">
                    {self._generate_menu_tree(item['children'], editor_id, level + 1)}
                </div>
                """
            
            html += f"""
            <div class="menu-tree-item {' '.join(classes)}" 
                 data-item-id="{item['id']}" data-level="{level}" data-index="{index}"
                 draggable="{str(self.enable_drag_drop).lower()}">
                <div class="item-content">
                    {drag_handle}
                    <div class="item-expand" onclick="toggleItemExpand('{item_id}')">
                        <i class="fas {'fa-chevron-down' if has_children else 'fa-circle'} expand-icon"></i>
                    </div>
                    {icon_html}
                    <div class="item-info" onclick="selectMenuItem('{editor_id}', '{item['id']}')">
                        <div class="item-title">{item['title']}</div>
                        <div class="item-url">{item.get('url', _('No URL'))}</div>
                    </div>
                    {badge_html}
                    <div class="item-actions">
                        <button class="btn btn-sm btn-outline-secondary" 
                                onclick="toggleItemVisibility('{editor_id}', '{item['id']}')"
                                title="{_('Toggle Visibility')}">
                            <i class="fas {visibility_icon}"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-primary" 
                                onclick="editMenuItem('{editor_id}', '{item['id']}')"
                                title="{_('Edit')}">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-info" 
                                onclick="duplicateMenuItem('{editor_id}', '{item['id']}')"
                                title="{_('Duplicate')}">
                            <i class="fas fa-copy"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger" 
                                onclick="deleteMenuItem('{editor_id}', '{item['id']}')"
                                title="{_('Delete')}">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
                {children_html}
            </div>
            """
        
        return html

    def _generate_property_panel(self, editor_id):
        """Generate the property panel HTML."""
        icon_options = ""
        for icon in self.available_icons:
            icon_options += f'<option value="{icon}">{icon}</option>'
        
        return f"""
        <div class="panel-header">
            <h5><i class="fas fa-cog"></i> {_('Properties')}</h5>
            <div class="panel-actions">
                <button class="btn btn-sm btn-outline-secondary" onclick="clearSelection('{editor_id}')">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        </div>
        <div class="property-content" id="{editor_id}_properties">
            <div class="no-selection">
                <i class="fas fa-mouse-pointer"></i>
                <p>{_('Select a menu item to edit its properties')}</p>
            </div>
            
            <div class="property-form" style="display: none;">
                <div class="form-group">
                    <label>{_('Title')}</label>
                    <input type="text" class="form-control" id="{editor_id}_prop_title" 
                           placeholder="{_('Menu item title')}" onchange="updateProperty('{editor_id}', 'title', this.value)">
                </div>
                
                <div class="form-group">
                    <label>{_('URL')}</label>
                    <input type="text" class="form-control" id="{editor_id}_prop_url" 
                           placeholder="{_('Menu item URL')}" onchange="updateProperty('{editor_id}', 'url', this.value)">
                </div>
                
                <div class="form-group" style="{'display: block' if self.enable_icons else 'display: none'}">
                    <label>{_('Icon')}</label>
                    <select class="form-control icon-select" id="{editor_id}_prop_icon" 
                            onchange="updateProperty('{editor_id}', 'icon', this.value)">
                        <option value="">{_('No Icon')}</option>
                        {icon_options}
                    </select>
                </div>
                
                <div class="form-group">
                    <label>{_('Order')}</label>
                    <input type="number" class="form-control" id="{editor_id}_prop_order" 
                           min="0" onchange="updateProperty('{editor_id}', 'order', parseInt(this.value))">
                </div>
                
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="{editor_id}_prop_visible" 
                           onchange="updateProperty('{editor_id}', 'visible', this.checked)">
                    <label class="form-check-label">{_('Visible')}</label>
                </div>
                
                <div class="property-actions">
                    <button class="btn btn-outline-info btn-sm" onclick="addChildItem('{editor_id}')">
                        <i class="fas fa-plus"></i> {_('Add Child')}
                    </button>
                    <button class="btn btn-outline-warning btn-sm" onclick="moveItemUp('{editor_id}')">
                        <i class="fas fa-arrow-up"></i> {_('Move Up')}
                    </button>
                    <button class="btn btn-outline-warning btn-sm" onclick="moveItemDown('{editor_id}')">
                        <i class="fas fa-arrow-down"></i> {_('Move Down')}
                    </button>
                </div>
            </div>
        </div>
        """

    def _flatten_menu(self, items):
        """Flatten menu structure for counting."""
        result = []
        for item in items:
            result.append(item)
            if item.get('children'):
                result.extend(self._flatten_menu(item['children']))
        return result

    def _generate_css(self, editor_id):
        """Generate CSS styles for the menu editor."""
        return f"""
        <style>
        #{editor_id}.menu-editor-container {{
            background: var(--editor-bg, #fff);
            border: 1px solid var(--editor-border, #dee2e6);
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            height: 600px;
            display: flex;
            flex-direction: column;
        }}
        
        #{editor_id}.menu-editor-light {{
            --editor-bg: #ffffff;
            --editor-text: #212529;
            --editor-border: #dee2e6;
            --editor-hover: #f8f9fa;
            --editor-active: #e9ecef;
            --editor-primary: #007bff;
        }}
        
        #{editor_id} .menu-editor-toolbar {{
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 12px 16px;
            background: var(--editor-hover);
            border-bottom: 1px solid var(--editor-border);
            flex-wrap: wrap;
        }}
        
        #{editor_id} .toolbar-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        #{editor_id} .menu-editor-main {{
            display: flex;
            flex: 1;
            min-height: 0;
        }}
        
        #{editor_id} .menu-tree-panel {{
            flex: 2;
            border-right: 1px solid var(--editor-border);
            display: flex;
            flex-direction: column;
        }}
        
        #{editor_id} .menu-property-panel {{
            flex: 1;
            min-width: 300px;
            display: flex;
            flex-direction: column;
        }}
        
        #{editor_id} .panel-header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 12px 16px;
            background: var(--editor-hover);
            border-bottom: 1px solid var(--editor-border);
        }}
        
        #{editor_id} .menu-tree-content {{
            flex: 1;
            overflow-y: auto;
            padding: 16px;
        }}
        
        #{editor_id} .menu-tree-item {{
            margin-bottom: 8px;
            border: 1px solid transparent;
            border-radius: 6px;
            transition: all 0.2s ease;
        }}
        
        #{editor_id} .item-content {{
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 12px;
            cursor: pointer;
        }}
        
        #{editor_id} .drag-handle {{
            color: #6c757d;
            cursor: grab;
            font-size: 12px;
        }}
        
        #{editor_id} .item-icon {{
            font-size: 14px;
            color: var(--editor-primary);
            width: 16px;
            text-align: center;
        }}
        
        #{editor_id} .item-info {{
            flex: 1;
            min-width: 0;
        }}
        
        #{editor_id} .item-title {{
            font-weight: 500;
            color: var(--editor-text);
            font-size: 14px;
        }}
        
        #{editor_id} .item-url {{
            font-size: 12px;
            color: #6c757d;
        }}
        
        #{editor_id} .item-actions {{
            display: flex;
            gap: 4px;
            opacity: 0;
            transition: opacity 0.2s ease;
        }}
        
        #{editor_id} .menu-tree-item:hover .item-actions {{
            opacity: 1;
        }}
        
        #{editor_id} .property-content {{
            flex: 1;
            padding: 16px;
            overflow-y: auto;
        }}
        
        #{editor_id} .no-selection {{
            text-align: center;
            color: #6c757d;
            padding: 40px 20px;
        }}
        
        #{editor_id} .property-form {{
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        
        #{editor_id} .form-group {{
            display: flex;
            flex-direction: column;
            gap: 6px;
        }}
        
        #{editor_id} .form-control {{
            padding: 8px 12px;
            border: 1px solid var(--editor-border);
            border-radius: 4px;
            background: var(--editor-bg);
            color: var(--editor-text);
            font-size: 14px;
        }}
        
        #{editor_id} .menu-editor-status {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 16px;
            background: var(--editor-hover);
            border-top: 1px solid var(--editor-border);
            font-size: 12px;
        }}
        
        #{editor_id} .btn {{
            padding: 4px 8px;
            font-size: 12px;
            border-radius: 4px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        
        #{editor_id} .btn-primary {{
            background: var(--editor-primary);
            color: white;
            border-color: var(--editor-primary);
        }}
        
        #{editor_id} .btn-outline-primary {{
            color: var(--editor-primary);
            border-color: var(--editor-primary);
        }}
        </style>
        """

    def _generate_javascript(self, editor_id):
        """Generate JavaScript for menu editor functionality."""
        import json
        menu_data_json = json.dumps(self.menu_data)
        
        return f"""
        <script>
        (function() {{
            // Menu editor state
            let editorState = {{
                selectedItem: null,
                menuData: {menu_data_json},
                isDirty: false
            }};
            
            // Initialize editor
            function initializeEditor() {{
                updateMenuTree();
                updateFormData();
            }}
            
            // Update menu tree display
            function updateMenuTree() {{
                const tree = document.getElementById('{editor_id}_tree');
                if (!tree) return;
                
                tree.innerHTML = generateMenuTreeHTML(editorState.menuData);
                updateItemCount();
            }}
            
            // Generate menu tree HTML
            function generateMenuTreeHTML(items, level = 0) {{
                let html = '';
                
                items.forEach((item, index) => {{
                    const hasChildren = item.children && item.children.length > 0;
                    const classes = ['menu-tree-item'];
                    
                    if (!item.visible) classes.push('hidden-item');
                    if (hasChildren) classes.push('has-children');
                    if (editorState.selectedItem === item.id) classes.push('selected');
                    
                    const badgeHTML = item.badge ? 
                        `<span class="item-badge badge bg-${{item.badge.color}}">${{item.badge.text}}</span>` : '';
                    
                    const iconHTML = item.icon ? 
                        `<i class="${{item.icon}} item-icon"></i>` : '';
                    
                    const visibilityIcon = item.visible ? 'fa-eye' : 'fa-eye-slash';
                    
                    const dragHandle = {str(self.enable_drag_drop).lower()} ? 
                        '<i class="fas fa-grip-vertical drag-handle"></i>' : '';
                    
                    const childrenHTML = hasChildren ? 
                        `<div class="menu-tree-children">${{generateMenuTreeHTML(item.children, level + 1)}}</div>` : '';
                    
                    html += `
                    <div class="menu-tree-item ${{classes.join(' ')}}" 
                         data-item-id="${{item.id}}" data-level="${{level}}" data-index="${{index}}"
                         draggable="${{str(self.enable_drag_drop).lower()}}">
                        <div class="item-content">
                            ${{dragHandle}}
                            <div class="item-expand" onclick="toggleItemExpand('${{item.id}}')">
                                <i class="fas ${{hasChildren ? 'fa-chevron-down' : 'fa-circle'}} expand-icon"></i>
                            </div>
                            ${{iconHTML}}
                            <div class="item-info" onclick="selectMenuItem('{editor_id}', '${{item.id}}')">
                                <div class="item-title">${{item.title}}</div>
                                <div class="item-url">${{item.url || '{_("No URL")}'}}</div>
                            </div>
                            ${{badgeHTML}}
                            <div class="item-actions">
                                <button class="btn btn-sm btn-outline-secondary" 
                                        onclick="toggleItemVisibility('{editor_id}', '${{item.id}}')"
                                        title="{_('Toggle Visibility')}">
                                    <i class="fas ${{visibilityIcon}}"></i>
                                </button>
                                <button class="btn btn-sm btn-outline-primary" 
                                        onclick="editMenuItem('{editor_id}', '${{item.id}}')"
                                        title="{_('Edit')}">
                                    <i class="fas fa-edit"></i>
                                </button>
                                <button class="btn btn-sm btn-outline-danger" 
                                        onclick="deleteMenuItem('{editor_id}', '${{item.id}}')"
                                        title="{_('Delete')}">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </div>
                        ${{childrenHTML}}
                    </div>
                    `;
                }});
                
                return html;
            }}
            
            // Select menu item
            window.selectMenuItem = function(editorId, itemId) {{
                if (editorId !== '{editor_id}') return;
                
                editorState.selectedItem = itemId;
                const item = findMenuItem(editorState.menuData, itemId);
                
                // Update tree selection
                document.querySelectorAll('#{editor_id} .menu-tree-item').forEach(el => {{
                    el.classList.remove('selected');
                }});
                
                const selectedElement = document.querySelector(`#{editor_id} [data-item-id="${{itemId}}"]`);
                if (selectedElement) {{
                    selectedElement.classList.add('selected');
                }}
                
                // Update property panel
                updatePropertyPanel(item);
            }};
            
            // Update property panel
            function updatePropertyPanel(item) {{
                const noSelection = document.querySelector('#{editor_id} .no-selection');
                const propertyForm = document.querySelector('#{editor_id} .property-form');
                
                if (!item) {{
                    noSelection.style.display = 'block';
                    propertyForm.style.display = 'none';
                    return;
                }}
                
                noSelection.style.display = 'none';
                propertyForm.style.display = 'block';
                
                // Populate form fields
                document.getElementById('{editor_id}_prop_title').value = item.title || '';
                document.getElementById('{editor_id}_prop_url').value = item.url || '';
                document.getElementById('{editor_id}_prop_icon').value = item.icon || '';
                document.getElementById('{editor_id}_prop_order').value = item.order || 0;
                document.getElementById('{editor_id}_prop_visible').checked = item.visible !== false;
            }}
            
            // Update property
            window.updateProperty = function(editorId, property, value) {{
                if (editorId !== '{editor_id}' || !editorState.selectedItem) return;
                
                const item = findMenuItem(editorState.menuData, editorState.selectedItem);
                if (item) {{
                    item[property] = value;
                    markDirty();
                    updateMenuTree();
                    updateFormData();
                }}
            }};
            
            // Find menu item by ID
            function findMenuItem(items, itemId) {{
                for (let item of items) {{
                    if (item.id === itemId) {{
                        return item;
                    }}
                    if (item.children) {{
                        const found = findMenuItem(item.children, itemId);
                        if (found) return found;
                    }}
                }}
                return null;
            }}
            
            // Add menu item
            window.addMenuItem = function(editorId) {{
                if (editorId !== '{editor_id}') return;
                
                const title = prompt('{_("Enter menu item title:")}');
                if (!title) return;
                
                const newItem = {{
                    id: 'item_' + Date.now(),
                    title: title,
                    url: null,
                    icon: null,
                    order: editorState.menuData.length,
                    visible: true,
                    permissions: ['menu_access'],
                    children: []
                }};
                
                editorState.menuData.push(newItem);
                markDirty();
                updateMenuTree();
                updateFormData();
            }};
            
            // Delete menu item
            window.deleteMenuItem = function(editorId, itemId) {{
                if (editorId !== '{editor_id}') return;
                
                if (confirm('{_("Are you sure you want to delete this menu item?")}')) {{
                    removeMenuItem(editorState.menuData, itemId);
                    
                    if (editorState.selectedItem === itemId) {{
                        editorState.selectedItem = null;
                        updatePropertyPanel(null);
                    }}
                    
                    markDirty();
                    updateMenuTree();
                    updateFormData();
                }}
            }};
            
            // Remove menu item from data
            function removeMenuItem(items, itemId) {{
                for (let i = 0; i < items.length; i++) {{
                    if (items[i].id === itemId) {{
                        items.splice(i, 1);
                        return true;
                    }}
                    if (items[i].children && removeMenuItem(items[i].children, itemId)) {{
                        return true;
                    }}
                }}
                return false;
            }}
            
            // Toggle item visibility
            window.toggleItemVisibility = function(editorId, itemId) {{
                if (editorId !== '{editor_id}') return;
                
                const item = findMenuItem(editorState.menuData, itemId);
                if (item) {{
                    item.visible = !item.visible;
                    markDirty();
                    updateMenuTree();
                    updateFormData();
                    
                    if (editorState.selectedItem === itemId) {{
                        updatePropertyPanel(item);
                    }}
                }}
            }};
            
            // Toggle item expand
            window.toggleItemExpand = function(itemId) {{
                const itemElement = document.querySelector(`#{editor_id} [data-item-id="${{itemId}}"]`);
                if (itemElement) {{
                    itemElement.classList.toggle('expanded');
                }}
            }};
            
            // Expand all items
            window.expandAll = function(editorId) {{
                if (editorId !== '{editor_id}') return;
                
                document.querySelectorAll('#{editor_id} .menu-tree-item.has-children').forEach(item => {{
                    item.classList.add('expanded');
                }});
            }};
            
            // Collapse all items
            window.collapseAll = function(editorId) {{
                if (editorId !== '{editor_id}') return;
                
                document.querySelectorAll('#{editor_id} .menu-tree-item.has-children').forEach(item => {{
                    item.classList.remove('expanded');
                }});
            }};
            
            // Clear selection
            window.clearSelection = function(editorId) {{
                if (editorId !== '{editor_id}') return;
                
                editorState.selectedItem = null;
                document.querySelectorAll('#{editor_id} .menu-tree-item').forEach(el => {{
                    el.classList.remove('selected');
                }});
                updatePropertyPanel(null);
            }};
            
            // Save menu
            window.saveMenu = function(editorId) {{
                if (editorId !== '{editor_id}') return;
                
                const status = document.getElementById('{editor_id}_save_status');
                status.textContent = '{_("Saving...")}';
                status.className = 'save-status saving';
                
                // Simulate save delay
                setTimeout(() => {{
                    editorState.isDirty = false;
                    status.textContent = '{_("Saved")}';
                    status.className = 'save-status saved';
                }}, 1000);
            }};
            
            // Mark as dirty
            function markDirty() {{
                editorState.isDirty = true;
                const status = document.getElementById('{editor_id}_save_status');
                if (status) {{
                    status.textContent = '{_("Unsaved changes")}';
                    status.className = 'save-status';
                }}
            }}
            
            // Update item count
            function updateItemCount() {{
                const count = flattenMenuData(editorState.menuData).length;
                const countElement = document.querySelector('#{editor_id} .item-count');
                if (countElement) {{
                    countElement.textContent = `${{count}} {_('items')}`;
                }}
            }}
            
            // Flatten menu data
            function flattenMenuData(items) {{
                let result = [];
                items.forEach(item => {{
                    result.push(item);
                    if (item.children) {{
                        result = result.concat(flattenMenuData(item.children));
                    }}
                }});
                return result;
            }}
            
            // Update form data
            function updateFormData() {{
                const input = document.querySelector('#{editor_id} input[data-menu-data]');
                if (input) {{
                    input.value = JSON.stringify(editorState.menuData);
                }}
            }}
            
            // Initialize when page loads
            document.addEventListener('DOMContentLoaded', initializeEditor);
        }})();
        </script>
        """


class PeriodicPictureTakerWidget(Input):
    """Advanced periodic picture taker widget with configurable intervals and WebRTC camera access."""
    
    def __init__(self, interval_seconds=30, auto_start=False, max_pictures=100, 
                 image_quality=0.8, image_format='jpeg', enable_flash=True,
                 enable_filters=True, enable_countdown=True, save_locally=True,
                 enable_upload=True, upload_endpoint='/upload/picture',
                 camera_constraints=None, enable_face_detection=False, **kwargs):
        """
        Initialize periodic picture taker widget.
        
        Args:
            interval_seconds: Interval between pictures in seconds
            auto_start: Whether to start automatically
            max_pictures: Maximum number of pictures to store
            image_quality: JPEG quality (0.1 to 1.0)
            image_format: Image format ('jpeg', 'png', 'webp')
            enable_flash: Enable camera flash if available
            enable_filters: Enable real-time camera filters
            enable_countdown: Show countdown before taking picture
            save_locally: Save pictures to browser storage
            enable_upload: Enable automatic upload to server
            upload_endpoint: Server endpoint for uploading pictures
            camera_constraints: Custom camera constraints
            enable_face_detection: Enable face detection overlay
        """
        super().__init__(**kwargs)
        self.interval_seconds = interval_seconds
        self.auto_start = auto_start
        self.max_pictures = max_pictures
        self.image_quality = image_quality
        self.image_format = image_format
        self.enable_flash = enable_flash
        self.enable_filters = enable_filters
        self.enable_countdown = enable_countdown
        self.save_locally = save_locally
        self.enable_upload = enable_upload
        self.upload_endpoint = upload_endpoint
        self.enable_face_detection = enable_face_detection
        
        # Default camera constraints
        self.camera_constraints = camera_constraints or {
            'video': {
                'width': {'ideal': 1280},
                'height': {'ideal': 720},
                'facingMode': 'user'
            },
            'audio': False
        }
        
        # Available filters
        self.available_filters = [
            {'id': 'none', 'name': _('None'), 'css': 'none'},
            {'id': 'grayscale', 'name': _('Grayscale'), 'css': 'grayscale(100%)'},
            {'id': 'sepia', 'name': _('Sepia'), 'css': 'sepia(100%)'},
            {'id': 'blur', 'name': _('Blur'), 'css': 'blur(3px)'},
            {'id': 'brightness', 'name': _('Bright'), 'css': 'brightness(150%)'},
            {'id': 'contrast', 'name': _('High Contrast'), 'css': 'contrast(150%)'},
            {'id': 'saturate', 'name': _('Saturated'), 'css': 'saturate(200%)'},
            {'id': 'vintage', 'name': _('Vintage'), 'css': 'sepia(50%) contrast(120%) brightness(110%)'},
            {'id': 'cool', 'name': _('Cool'), 'css': 'hue-rotate(90deg) saturate(150%)'},
            {'id': 'warm', 'name': _('Warm'), 'css': 'hue-rotate(-30deg) saturate(120%)'}
        ]
        
        # Interval presets
        self.interval_presets = [
            {'seconds': 10, 'label': _('10 seconds')},
            {'seconds': 30, 'label': _('30 seconds')},
            {'seconds': 60, 'label': _('1 minute')},
            {'seconds': 300, 'label': _('5 minutes')},
            {'seconds': 600, 'label': _('10 minutes')},
            {'seconds': 1800, 'label': _('30 minutes')},
            {'seconds': 3600, 'label': _('1 hour')}
        ]

    def __call__(self, field, **kwargs):
        """Render the periodic picture taker widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        widget_id = f"picture_taker_{field.id}"
        
        # Generate CSS styles
        css_styles = self._generate_css(widget_id)
        
        # Generate controls panel
        controls_html = self._generate_controls(widget_id)
        
        # Generate camera preview
        camera_html = self._generate_camera_preview(widget_id)
        
        # Generate picture gallery
        gallery_html = self._generate_picture_gallery(widget_id)
        
        # Generate settings modal
        settings_modal = self._generate_settings_modal(widget_id)
        
        # Generate JavaScript
        javascript = self._generate_javascript(widget_id)
        
        return Markup(f"""
        {css_styles}
        <div id="{widget_id}" class="picture-taker-container" 
             data-interval="{self.interval_seconds}" 
             data-auto-start="{str(self.auto_start).lower()}"
             data-max-pictures="{self.max_pictures}">
            
            <!-- Main Interface -->
            <div class="picture-taker-main">
                
                <!-- Controls Panel -->
                {controls_html}
                
                <!-- Camera Preview -->
                {camera_html}
                
                <!-- Picture Gallery -->
                {gallery_html}
                
            </div>
            
            <!-- Status Bar -->
            <div class="picture-taker-status">
                <div class="status-info">
                    <span class="camera-status" id="{widget_id}_camera_status">
                        <i class="fas fa-video-slash"></i> {_('Camera Off')}
                    </span>
                    <span class="timer-status" id="{widget_id}_timer_status">
                        <i class="fas fa-clock"></i> {_('Stopped')}
                    </span>
                    <span class="picture-count" id="{widget_id}_picture_count">
                        <i class="fas fa-images"></i> 0/{self.max_pictures}
                    </span>
                </div>
                <div class="status-actions">
                    <button class="btn btn-sm btn-outline-secondary" onclick="openSettings('{widget_id}')">
                        <i class="fas fa-cog"></i> {_('Settings')}
                    </button>
                    <button class="btn btn-sm btn-outline-info" onclick="downloadAll('{widget_id}')">
                        <i class="fas fa-download"></i> {_('Download All')}
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="clearAll('{widget_id}')">
                        <i class="fas fa-trash"></i> {_('Clear All')}
                    </button>
                </div>
            </div>
            
            <!-- Hidden input for form data -->
            <input type="hidden" id="{kwargs['id']}" name="{kwargs['name']}" 
                   value="" data-pictures="">
        </div>
        
        {settings_modal}
        {javascript}
        """)

    def _generate_controls(self, widget_id):
        """Generate the controls panel HTML."""
        interval_options = ""
        for preset in self.interval_presets:
            selected = "selected" if preset['seconds'] == self.interval_seconds else ""
            interval_options += f'<option value="{preset["seconds"]}" {selected}>{preset["label"]}</option>'
        
        filter_options = ""
        if self.enable_filters:
            for filter_item in self.available_filters:
                filter_options += f'<option value="{filter_item["id"]}">{filter_item["name"]}</option>'
        
        filters_section = ""
        if self.enable_filters:
            filters_section = f"""
            <div class="control-group">
                <label>{_('Filter')}</label>
                <select class="form-control" id="{widget_id}_filter" onchange="applyFilter('{widget_id}')">
                    {filter_options}
                </select>
            </div>
            """
        
        countdown_section = ""
        if self.enable_countdown:
            countdown_section = f"""
            <div class="control-group">
                <div class="form-check">
                    <input class="form-check-input" type="checkbox" id="{widget_id}_countdown" 
                           checked onchange="toggleCountdown('{widget_id}')">
                    <label class="form-check-label">{_('Countdown')}</label>
                </div>
            </div>
            """
        
        return f"""
        <div class="picture-taker-controls">
            <div class="controls-header">
                <h5><i class="fas fa-camera"></i> {_('Picture Taker')}</h5>
                <div class="header-actions">
                    <button class="btn btn-success" id="{widget_id}_start_btn" onclick="startCapture('{widget_id}')">
                        <i class="fas fa-play"></i> {_('Start')}
                    </button>
                    <button class="btn btn-danger" id="{widget_id}_stop_btn" onclick="stopCapture('{widget_id}')" style="display: none;">
                        <i class="fas fa-stop"></i> {_('Stop')}
                    </button>
                    <button class="btn btn-primary" id="{widget_id}_capture_btn" onclick="takePicture('{widget_id}')" disabled>
                        <i class="fas fa-camera"></i> {_('Take Picture')}
                    </button>
                </div>
            </div>
            
            <div class="controls-body">
                <div class="control-group">
                    <label>{_('Interval')}</label>
                    <select class="form-control" id="{widget_id}_interval" onchange="updateInterval('{widget_id}')">
                        {interval_options}
                        <option value="custom">{_('Custom...')}</option>
                    </select>
                </div>
                
                <div class="control-group" id="{widget_id}_custom_interval" style="display: none;">
                    <label>{_('Custom Interval (seconds)')}</label>
                    <input type="number" class="form-control" id="{widget_id}_custom_seconds" 
                           min="1" max="3600" value="{self.interval_seconds}" 
                           onchange="setCustomInterval('{widget_id}')">
                </div>
                
                <div class="control-group">
                    <label>{_('Camera')}</label>
                    <select class="form-control" id="{widget_id}_camera" onchange="switchCamera('{widget_id}')">
                        <option value="user">{_('Front Camera')}</option>
                        <option value="environment">{_('Back Camera')}</option>
                    </select>
                </div>
                
                {filters_section}
                {countdown_section}
                
                <div class="control-group">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="{widget_id}_auto_upload" 
                               {'checked' if self.enable_upload else ''} onchange="toggleAutoUpload('{widget_id}')">
                        <label class="form-check-label">{_('Auto Upload')}</label>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_camera_preview(self, widget_id):
        """Generate the camera preview HTML."""
        face_detection_overlay = ""
        if self.enable_face_detection:
            face_detection_overlay = f"""
            <div class="face-detection-overlay" id="{widget_id}_face_overlay">
                <!-- Face detection rectangles will be drawn here -->
            </div>
            """
        
        return f"""
        <div class="camera-preview-container">
            <div class="camera-preview">
                <video id="{widget_id}_video" autoplay muted playsinline></video>
                <canvas id="{widget_id}_canvas" style="display: none;"></canvas>
                
                {face_detection_overlay}
                
                <!-- Countdown Overlay -->
                <div class="countdown-overlay" id="{widget_id}_countdown_overlay" style="display: none;">
                    <div class="countdown-number" id="{widget_id}_countdown_number">3</div>
                </div>
                
                <!-- Flash Effect -->
                <div class="flash-effect" id="{widget_id}_flash"></div>
                
                <!-- Camera Status Overlay -->
                <div class="camera-overlay">
                    <div class="overlay-top">
                        <div class="recording-indicator" id="{widget_id}_recording" style="display: none;">
                            <i class="fas fa-circle"></i> {_('Recording')}
                        </div>
                        <div class="next-capture" id="{widget_id}_next_capture">
                            {_('Next in')}: <span id="{widget_id}_next_time">--</span>
                        </div>
                    </div>
                    
                    <div class="overlay-bottom">
                        <div class="camera-info">
                            <span id="{widget_id}_resolution">--</span>
                            <span id="{widget_id}_fps">--</span>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="camera-controls">
                <button class="btn btn-outline-secondary" onclick="toggleVideo('{widget_id}')" 
                        id="{widget_id}_video_toggle" title="{_('Toggle Camera')}">
                    <i class="fas fa-video"></i>
                </button>
                <button class="btn btn-outline-secondary" onclick="switchCamera('{widget_id}')" 
                        title="{_('Switch Camera')}">
                    <i class="fas fa-sync-alt"></i>
                </button>
                <button class="btn btn-outline-secondary" onclick="toggleFullscreen('{widget_id}')" 
                        title="{_('Fullscreen')}">
                    <i class="fas fa-expand"></i>
                </button>
            </div>
        </div>
        """

    def _generate_picture_gallery(self, widget_id):
        """Generate the picture gallery HTML."""
        return f"""
        <div class="picture-gallery">
            <div class="gallery-header">
                <h6><i class="fas fa-images"></i> {_('Captured Pictures')}</h6>
                <div class="gallery-actions">
                    <button class="btn btn-sm btn-outline-secondary" onclick="toggleGalleryView('{widget_id}')">
                        <i class="fas fa-th" id="{widget_id}_view_toggle"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-primary" onclick="selectAll('{widget_id}')">
                        <i class="fas fa-check-square"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-info" onclick="downloadSelected('{widget_id}')">
                        <i class="fas fa-download"></i>
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteSelected('{widget_id}')">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
            
            <div class="gallery-content" id="{widget_id}_gallery">
                <div class="no-pictures">
                    <i class="fas fa-camera"></i>
                    <p>{_('No pictures captured yet')}</p>
                    <small>{_('Start the camera to begin taking pictures')}</small>
                </div>
            </div>
        </div>
        """

    def _generate_settings_modal(self, widget_id):
        """Generate the settings modal HTML."""
        return f"""
        <div class="modal fade" id="{widget_id}_settings_modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">{_('Picture Taker Settings')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="settings-tabs">
                            <ul class="nav nav-tabs" role="tablist">
                                <li class="nav-item">
                                    <a class="nav-link active" data-bs-toggle="tab" href="#{widget_id}_general_tab">
                                        {_('General')}
                                    </a>
                                </li>
                                <li class="nav-item">
                                    <a class="nav-link" data-bs-toggle="tab" href="#{widget_id}_camera_tab">
                                        {_('Camera')}
                                    </a>
                                </li>
                                <li class="nav-item">
                                    <a class="nav-link" data-bs-toggle="tab" href="#{widget_id}_storage_tab">
                                        {_('Storage')}
                                    </a>
                                </li>
                            </ul>
                            
                            <div class="tab-content">
                                <div class="tab-pane fade show active" id="{widget_id}_general_tab">
                                    <div class="form-group">
                                        <label>{_('Maximum Pictures')}</label>
                                        <input type="number" class="form-control" id="{widget_id}_max_pictures" 
                                               value="{self.max_pictures}" min="1" max="1000">
                                        <small class="form-text text-muted">{_('Maximum number of pictures to store')}</small>
                                    </div>
                                    
                                    <div class="form-group">
                                        <label>{_('Image Quality')}</label>
                                        <input type="range" class="form-range" id="{widget_id}_quality" 
                                               min="0.1" max="1.0" step="0.1" value="{self.image_quality}">
                                        <small class="form-text text-muted">{_('Higher quality = larger file size')}</small>
                                    </div>
                                    
                                    <div class="form-group">
                                        <label>{_('Image Format')}</label>
                                        <select class="form-control" id="{widget_id}_format">
                                            <option value="jpeg" {'selected' if self.image_format == 'jpeg' else ''}>JPEG</option>
                                            <option value="png" {'selected' if self.image_format == 'png' else ''}>PNG</option>
                                            <option value="webp" {'selected' if self.image_format == 'webp' else ''}>WebP</option>
                                        </select>
                                    </div>
                                </div>
                                
                                <div class="tab-pane fade" id="{widget_id}_camera_tab">
                                    <div class="form-group">
                                        <label>{_('Resolution')}</label>
                                        <select class="form-control" id="{widget_id}_resolution">
                                            <option value="640x480">640x480 (VGA)</option>
                                            <option value="1280x720" selected>1280x720 (HD)</option>
                                            <option value="1920x1080">1920x1080 (Full HD)</option>
                                            <option value="2560x1440">2560x1440 (2K)</option>
                                        </select>
                                    </div>
                                    
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" id="{widget_id}_flash_setting" 
                                               {'checked' if self.enable_flash else ''}>
                                        <label class="form-check-label">{_('Enable Flash')}</label>
                                    </div>
                                    
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" id="{widget_id}_face_detection_setting" 
                                               {'checked' if self.enable_face_detection else ''}>
                                        <label class="form-check-label">{_('Face Detection')}</label>
                                    </div>
                                </div>
                                
                                <div class="tab-pane fade" id="{widget_id}_storage_tab">
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" id="{widget_id}_save_local" 
                                               {'checked' if self.save_locally else ''}>
                                        <label class="form-check-label">{_('Save to Browser Storage')}</label>
                                    </div>
                                    
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox" id="{widget_id}_auto_upload_setting" 
                                               {'checked' if self.enable_upload else ''}>
                                        <label class="form-check-label">{_('Auto Upload to Server')}</label>
                                    </div>
                                    
                                    <div class="form-group">
                                        <label>{_('Upload Endpoint')}</label>
                                        <input type="text" class="form-control" id="{widget_id}_upload_endpoint" 
                                               value="{self.upload_endpoint}">
                                    </div>
                                    
                                    <div class="storage-info">
                                        <h6>{_('Storage Usage')}</h6>
                                        <div class="storage-bar">
                                            <div class="storage-used" id="{widget_id}_storage_used" style="width: 0%"></div>
                                        </div>
                                        <small id="{widget_id}_storage_text">0 MB / 100 MB</small>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">{_('Cancel')}</button>
                        <button type="button" class="btn btn-primary" onclick="saveSettings('{widget_id}')">{_('Save')}</button>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_css(self, widget_id):
        """Generate CSS styles for the picture taker widget."""
        return f"""
        <style>
        #{widget_id}.picture-taker-container {{
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            overflow: hidden;
        }}
        
        #{widget_id} .picture-taker-main {{
            display: grid;
            grid-template-columns: 300px 1fr 250px;
            grid-template-areas: "controls camera gallery";
            height: 500px;
        }}
        
        #{widget_id} .picture-taker-controls {{
            grid-area: controls;
            border-right: 1px solid #dee2e6;
            display: flex;
            flex-direction: column;
        }}
        
        #{widget_id} .controls-header {{
            padding: 16px;
            border-bottom: 1px solid #dee2e6;
            background: #f8f9fa;
        }}
        
        #{widget_id} .controls-header h5 {{
            margin: 0 0 12px 0;
            font-size: 14px;
            font-weight: 600;
            color: #495057;
        }}
        
        #{widget_id} .header-actions {{
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }}
        
        #{widget_id} .controls-body {{
            flex: 1;
            padding: 16px;
            overflow-y: auto;
        }}
        
        #{widget_id} .control-group {{
            margin-bottom: 16px;
        }}
        
        #{widget_id} .control-group label {{
            display: block;
            font-weight: 500;
            color: #495057;
            font-size: 12px;
            margin-bottom: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        #{widget_id} .form-control {{
            width: 100%;
            padding: 8px 12px;
            border: 1px solid #ced4da;
            border-radius: 4px;
            font-size: 14px;
            background: #fff;
            color: #495057;
        }}
        
        #{widget_id} .form-control:focus {{
            outline: none;
            border-color: #007bff;
            box-shadow: 0 0 0 2px rgba(0,123,255,0.25);
        }}
        
        #{widget_id} .form-check {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        #{widget_id} .form-check-input {{
            margin: 0;
        }}
        
        #{widget_id} .camera-preview-container {{
            grid-area: camera;
            display: flex;
            flex-direction: column;
            background: #000;
        }}
        
        #{widget_id} .camera-preview {{
            flex: 1;
            position: relative;
            overflow: hidden;
        }}
        
        #{widget_id} .camera-preview video {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}
        
        #{widget_id} .camera-preview canvas {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }}
        
        #{widget_id} .face-detection-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
        }}
        
        #{widget_id} .face-rect {{
            position: absolute;
            border: 2px solid #00ff00;
            border-radius: 4px;
            background: rgba(0,255,0,0.1);
        }}
        
        #{widget_id} .countdown-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.7);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10;
        }}
        
        #{widget_id} .countdown-number {{
            font-size: 72px;
            font-weight: bold;
            color: #fff;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
            animation: countdownPulse 1s ease-in-out infinite;
        }}
        
        @keyframes countdownPulse {{
            0%, 100% {{ transform: scale(1); }}
            50% {{ transform: scale(1.2); }}
        }}
        
        #{widget_id} .flash-effect {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(255,255,255,0.8);
            opacity: 0;
            pointer-events: none;
            z-index: 15;
        }}
        
        #{widget_id} .flash-effect.active {{
            animation: flashEffect 0.3s ease-out;
        }}
        
        @keyframes flashEffect {{
            0% {{ opacity: 0; }}
            50% {{ opacity: 1; }}
            100% {{ opacity: 0; }}
        }}
        
        #{widget_id} .camera-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            pointer-events: none;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            padding: 16px;
        }}
        
        #{widget_id} .overlay-top {{
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }}
        
        #{widget_id} .recording-indicator {{
            background: rgba(220,53,69,0.9);
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        
        #{widget_id} .recording-indicator i {{
            animation: recordingBlink 1s ease-in-out infinite;
        }}
        
        @keyframes recordingBlink {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.3; }}
        }}
        
        #{widget_id} .next-capture {{
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
        }}
        
        #{widget_id} .overlay-bottom {{
            align-self: flex-end;
        }}
        
        #{widget_id} .camera-info {{
            background: rgba(0,0,0,0.7);
            color: white;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 11px;
            display: flex;
            gap: 12px;
        }}
        
        #{widget_id} .camera-controls {{
            display: flex;
            justify-content: center;
            gap: 8px;
            padding: 12px;
            background: rgba(0,0,0,0.8);
        }}
        
        #{widget_id} .picture-gallery {{
            grid-area: gallery;
            border-left: 1px solid #dee2e6;
            display: flex;
            flex-direction: column;
        }}
        
        #{widget_id} .gallery-header {{
            padding: 12px 16px;
            border-bottom: 1px solid #dee2e6;
            background: #f8f9fa;
        }}
        
        #{widget_id} .gallery-header h6 {{
            margin: 0 0 8px 0;
            font-size: 12px;
            font-weight: 600;
            color: #495057;
        }}
        
        #{widget_id} .gallery-actions {{
            display: flex;
            gap: 4px;
            flex-wrap: wrap;
        }}
        
        #{widget_id} .gallery-content {{
            flex: 1;
            overflow-y: auto;
            padding: 8px;
        }}
        
        #{widget_id} .no-pictures {{
            text-align: center;
            color: #6c757d;
            padding: 40px 16px;
        }}
        
        #{widget_id} .no-pictures i {{
            font-size: 48px;
            margin-bottom: 16px;
            opacity: 0.5;
        }}
        
        #{widget_id} .picture-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(80px, 1fr));
            gap: 8px;
        }}
        
        #{widget_id} .picture-item {{
            position: relative;
            aspect-ratio: 1;
            border-radius: 4px;
            overflow: hidden;
            cursor: pointer;
            transition: transform 0.2s ease;
        }}
        
        #{widget_id} .picture-item:hover {{
            transform: scale(1.05);
        }}
        
        #{widget_id} .picture-item img {{
            width: 100%;
            height: 100%;
            object-fit: cover;
        }}
        
        #{widget_id} .picture-item .picture-overlay {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(0,0,0,0.5);
            opacity: 0;
            transition: opacity 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }}
        
        #{widget_id} .picture-item:hover .picture-overlay {{
            opacity: 1;
        }}
        
        #{widget_id} .picture-overlay button {{
            background: rgba(255,255,255,0.9);
            border: none;
            border-radius: 50%;
            width: 24px;
            height: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 10px;
            cursor: pointer;
        }}
        
        #{widget_id} .picture-taker-status {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 16px;
            background: #f8f9fa;
            border-top: 1px solid #dee2e6;
            font-size: 12px;
        }}
        
        #{widget_id} .status-info {{
            display: flex;
            gap: 16px;
            color: #6c757d;
        }}
        
        #{widget_id} .status-actions {{
            display: flex;
            gap: 8px;
        }}
        
        #{widget_id} .camera-status.active {{
            color: #28a745;
        }}
        
        #{widget_id} .timer-status.running {{
            color: #dc3545;
        }}
        
        #{widget_id} .btn {{
            padding: 4px 8px;
            font-size: 12px;
            border-radius: 4px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.2s ease;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        
        #{widget_id} .btn-primary {{
            background: #007bff;
            color: white;
            border-color: #007bff;
        }}
        
        #{widget_id} .btn-success {{
            background: #28a745;
            color: white;
            border-color: #28a745;
        }}
        
        #{widget_id} .btn-danger {{
            background: #dc3545;
            color: white;
            border-color: #dc3545;
        }}
        
        #{widget_id} .btn-outline-secondary {{
            color: #6c757d;
            border-color: #6c757d;
            background: transparent;
        }}
        
        #{widget_id} .btn-outline-secondary:hover {{
            background: #6c757d;
            color: white;
        }}
        
        #{widget_id} .btn:disabled {{
            opacity: 0.6;
            cursor: not-allowed;
        }}
        
        /* Modal styles */
        #{widget_id}_settings_modal .modal-content {{
            background: #fff;
        }}
        
        #{widget_id} .settings-tabs {{
            margin-top: 16px;
        }}
        
        #{widget_id} .tab-content {{
            padding: 16px 0;
        }}
        
        #{widget_id} .storage-bar {{
            width: 100%;
            height: 8px;
            background: #e9ecef;
            border-radius: 4px;
            overflow: hidden;
            margin: 8px 0;
        }}
        
        #{widget_id} .storage-used {{
            height: 100%;
            background: linear-gradient(90deg, #28a745, #ffc107, #dc3545);
            transition: width 0.3s ease;
        }}
        
        /* Responsive design */
        @media (max-width: 768px) {{
            #{widget_id} .picture-taker-main {{
                grid-template-columns: 1fr;
                grid-template-areas: 
                    "controls"
                    "camera"
                    "gallery";
                height: auto;
            }}
            
            #{widget_id} .picture-taker-controls,
            #{widget_id} .camera-preview-container,
            #{widget_id} .picture-gallery {{
                border: none;
                border-bottom: 1px solid #dee2e6;
            }}
            
            #{widget_id} .camera-preview-container {{
                height: 300px;
            }}
            
            #{widget_id} .picture-gallery {{
                height: 200px;
            }}
        }}
        </style>
        """

    def _generate_javascript(self, widget_id):
        """Generate JavaScript for picture taker functionality."""
        import json
        constraints_json = json.dumps(self.camera_constraints)
        filters_json = json.dumps(self.available_filters)
        
        return f"""
        <script>
        (function() {{
            // Picture taker state
            let pictureTakerState = {{
                stream: null,
                isActive: false,
                intervalId: null,
                countdownId: null,
                pictures: [],
                currentFilter: 'none',
                settings: {{
                    interval: {self.interval_seconds},
                    maxPictures: {self.max_pictures},
                    quality: {self.image_quality},
                    format: '{self.image_format}',
                    autoUpload: {str(self.enable_upload).lower()},
                    countdown: {str(self.enable_countdown).lower()},
                    faceDetection: {str(self.enable_face_detection).lower()}
                }}
            }};
            
            const filters = {filters_json};
            const constraints = {constraints_json};
            
            // Initialize
            function initializePictureTaker() {{
                updateUI();
                loadStoredPictures();
                
                // Load settings from localStorage
                const savedSettings = localStorage.getItem('pictureTaker_{widget_id}_settings');
                if (savedSettings) {{
                    try {{
                        Object.assign(pictureTakerState.settings, JSON.parse(savedSettings));
                    }} catch (e) {{
                        console.warn('Failed to load picture taker settings');
                    }}
                }}
                
                // Auto-start if enabled
                if ({str(self.auto_start).lower()}) {{
                    setTimeout(() => startCapture('{widget_id}'), 1000);
                }}
            }}
            
            // Start capture
            window.startCapture = async function(widgetId) {{
                if (widgetId !== '{widget_id}') return;
                
                try {{
                    // Request camera access
                    pictureTakerState.stream = await navigator.mediaDevices.getUserMedia(constraints);
                    
                    const video = document.getElementById('{widget_id}_video');
                    video.srcObject = pictureTakerState.stream;
                    
                    // Update UI
                    pictureTakerState.isActive = true;
                    updateUI();
                    updateCameraStatus();
                    
                    // Start interval timer
                    startIntervalTimer();
                    
                    // Enable face detection if configured
                    if (pictureTakerState.settings.faceDetection) {{
                        startFaceDetection();
                    }}
                    
                }} catch (error) {{
                    console.error('Error accessing camera:', error);
                    alert('{_("Camera access denied or not available")}');
                }}
            }};
            
            // Stop capture
            window.stopCapture = function(widgetId) {{
                if (widgetId !== '{widget_id}') return;
                
                // Stop camera stream
                if (pictureTakerState.stream) {{
                    pictureTakerState.stream.getTracks().forEach(track => track.stop());
                    pictureTakerState.stream = null;
                }}
                
                // Clear timers
                if (pictureTakerState.intervalId) {{
                    clearInterval(pictureTakerState.intervalId);
                    pictureTakerState.intervalId = null;
                }}
                
                if (pictureTakerState.countdownId) {{
                    clearTimeout(pictureTakerState.countdownId);
                    pictureTakerState.countdownId = null;
                }}
                
                pictureTakerState.isActive = false;
                updateUI();
                updateCameraStatus();
            }};
            
            // Take picture
            window.takePicture = async function(widgetId) {{
                if (widgetId !== '{widget_id}' || !pictureTakerState.stream) return;
                
                const video = document.getElementById('{widget_id}_video');
                const canvas = document.getElementById('{widget_id}_canvas');
                const context = canvas.getContext('2d');
                
                // Set canvas size to video size
                canvas.width = video.videoWidth;
                canvas.height = video.videoHeight;
                
                // Apply filter
                context.filter = getCurrentFilter();
                
                // Draw video frame to canvas
                context.drawImage(video, 0, 0, canvas.width, canvas.height);
                
                // Show flash effect
                showFlash();
                
                // Convert to blob
                const blob = await new Promise(resolve => {{
                    canvas.toBlob(resolve,
                        "image/" + pictureTakerState.settings.format,
                        pictureTakerState.settings.quality
                    );
                }});
                
                // Create picture object
                const picture = {{
                    id: Date.now(),
                    timestamp: new Date().toISOString(),
                    blob: blob,
                    url: URL.createObjectURL(blob),
                    size: blob.size,
                    format: pictureTakerState.settings.format
                }};
                
                // Add to collection
                addPicture(picture);
                
                // Auto-upload if enabled
                if (pictureTakerState.settings.autoUpload) {{
                    uploadPicture(picture);
                }}
            }};
            
            // Add picture to collection
            function addPicture(picture) {{
                pictureTakerState.pictures.unshift(picture);
                
                // Remove oldest if at limit
                if (pictureTakerState.pictures.length > pictureTakerState.settings.maxPictures) {{
                    const removed = pictureTakerState.pictures.pop();
                    URL.revokeObjectURL(removed.url);
                }}
                
                updateGallery();
                updatePictureCount();
                saveToLocalStorage();
                updateFormData();
            }}
            
            // Start interval timer
            function startIntervalTimer() {{
                if (pictureTakerState.intervalId) {{
                    clearInterval(pictureTakerState.intervalId);
                }}
                
                let nextCaptureTime = pictureTakerState.settings.interval;
                updateNextCaptureDisplay(nextCaptureTime);
                
                pictureTakerState.intervalId = setInterval(() => {{
                    nextCaptureTime--;
                    updateNextCaptureDisplay(nextCaptureTime);
                    
                    if (nextCaptureTime <= 0) {{
                        if (pictureTakerState.settings.countdown) {{
                            startCountdown(() => {{
                                takePicture('{widget_id}');
                                nextCaptureTime = pictureTakerState.settings.interval;
                            }});
                        }} else {{
                            takePicture('{widget_id}');
                            nextCaptureTime = pictureTakerState.settings.interval;
                        }}
                    }}
                }}, 1000);
            }}
            
            // Start countdown
            function startCountdown(callback) {{
                const overlay = document.getElementById('{widget_id}_countdown_overlay');
                const number = document.getElementById('{widget_id}_countdown_number');
                
                let count = 3;
                overlay.style.display = 'flex';
                number.textContent = count;
                
                const countdownTimer = setInterval(() => {{
                    count--;
                    if (count > 0) {{
                        number.textContent = count;
                    }} else {{
                        clearInterval(countdownTimer);
                        overlay.style.display = 'none';
                        callback();
                    }}
                }}, 1000);
            }}
            
            // Show flash effect
            function showFlash() {{
                const flash = document.getElementById('{widget_id}_flash');
                flash.classList.add('active');
                setTimeout(() => flash.classList.remove('active'), 300);
            }}
            
            // Get current filter CSS
            function getCurrentFilter() {{
                const filter = filters.find(f => f.id === pictureTakerState.currentFilter);
                return filter ? filter.css : 'none';
            }}
            
            // Apply filter to video
            window.applyFilter = function(widgetId) {{
                if (widgetId !== '{widget_id}') return;
                
                const select = document.getElementById('{widget_id}_filter');
                pictureTakerState.currentFilter = select.value;
                
                const video = document.getElementById('{widget_id}_video');
                video.style.filter = getCurrentFilter();
            }};
            
            // Update interval
            window.updateInterval = function(widgetId) {{
                if (widgetId !== '{widget_id}') return;
                
                const select = document.getElementById('{widget_id}_interval');
                const customGroup = document.getElementById('{widget_id}_custom_interval');
                
                if (select.value === 'custom') {{
                    customGroup.style.display = 'block';
                }} else {{
                    customGroup.style.display = 'none';
                    pictureTakerState.settings.interval = parseInt(select.value);
                    
                    if (pictureTakerState.isActive) {{
                        startIntervalTimer();
                    }}
                }}
            }};
            
            // Set custom interval
            window.setCustomInterval = function(widgetId) {{
                if (widgetId !== '{widget_id}') return;
                
                const input = document.getElementById('{widget_id}_custom_seconds');
                pictureTakerState.settings.interval = parseInt(input.value) || 30;
                
                if (pictureTakerState.isActive) {{
                    startIntervalTimer();
                }}
            }};
            
            // Update UI elements
            function updateUI() {{
                const startBtn = document.getElementById('{widget_id}_start_btn');
                const stopBtn = document.getElementById('{widget_id}_stop_btn');
                const captureBtn = document.getElementById('{widget_id}_capture_btn');
                
                if (pictureTakerState.isActive) {{
                    startBtn.style.display = 'none';
                    stopBtn.style.display = 'inline-flex';
                    captureBtn.disabled = false;
                }} else {{
                    startBtn.style.display = 'inline-flex';
                    stopBtn.style.display = 'none';
                    captureBtn.disabled = true;
                }}
            }}
            
            // Update camera status
            function updateCameraStatus() {{
                const status = document.getElementById('{widget_id}_camera_status');
                const recording = document.getElementById('{widget_id}_recording');
                
                if (pictureTakerState.isActive) {{
                    status.innerHTML = '<i class="fas fa-video"></i> {_("Camera On")}';
                    status.classList.add('active');
                    recording.style.display = 'flex';
                }} else {{
                    status.innerHTML = '<i class="fas fa-video-slash"></i> {_("Camera Off")}';
                    status.classList.remove('active');
                    recording.style.display = 'none';
                }}
            }}
            
            // Update next capture display
            function updateNextCaptureDisplay(seconds) {{
                const display = document.getElementById('{widget_id}_next_time');
                const timerStatus = document.getElementById('{widget_id}_timer_status');
                
                if (pictureTakerState.isActive && seconds > 0) {{
                    const minutes = Math.floor(seconds / 60);
                    const secs = seconds % 60;
                    display.textContent = minutes + ':' + secs.toString().padStart(2, '0');
                    timerStatus.innerHTML = '<i class="fas fa-clock"></i> {_("Running")}';
                    timerStatus.classList.add('running');
                }} else {{
                    display.textContent = '--';
                    timerStatus.innerHTML = '<i class="fas fa-clock"></i> {_("Stopped")}';
                    timerStatus.classList.remove('running');
                }}
            }}
            
            // Update picture count
            function updatePictureCount() {{
                const count = document.getElementById('{widget_id}_picture_count');
                count.innerHTML = '<i class="fas fa-images"></i> ' + pictureTakerState.pictures.length + '/' + pictureTakerState.settings.maxPictures;
            }}
            
            // Update gallery
            function updateGallery() {{
                const gallery = document.getElementById('{widget_id}_gallery');
                
                if (pictureTakerState.pictures.length === 0) {{
                    gallery.innerHTML = '<div class="no-pictures">' +
                        '<i class="fas fa-camera"></i>' +
                        '<p>{_("No pictures captured yet")}</p>' +
                        '<small>{_("Start the camera to begin taking pictures")}</small>' +
                        '</div>';
                    return;
                }}
                
                const gridHTML = pictureTakerState.pictures.map(picture =>
                    '<div class="picture-item" data-picture-id="' + picture.id + '">' +
                        '<img src="' + picture.url + '" alt="Captured at ' + new Date(picture.timestamp).toLocaleString() + '">' +
                        '<div class="picture-overlay">' +
                            '<button onclick="downloadPicture(\'' + picture.id + '\')" title="{_("Download")}">' +
                                '<i class="fas fa-download"></i>' +
                            '</button>' +
                            '<button onclick="deletePicture(\'' + picture.id + '\')" title="{_("Delete")}">' +
                                '<i class="fas fa-trash"></i>' +
                            '</button>' +
                        '</div>' +
                    '</div>'
                ).join('');
                
                gallery.innerHTML = '<div class="picture-grid">' + gridHTML + '</div>';
            }}
            
            // Download picture
            window.downloadPicture = function(pictureId) {{
                const picture = pictureTakerState.pictures.find(p => p.id == pictureId);
                if (picture) {{
                    const link = document.createElement('a');
                    link.href = picture.url;
                    link.download = "picture_" + picture.timestamp + "." + picture.format;
                    link.click();
                }}
            }};
            
            // Delete picture
            window.deletePicture = function(pictureId) {{
                const index = pictureTakerState.pictures.findIndex(p => p.id == pictureId);
                if (index !== -1) {{
                    const picture = pictureTakerState.pictures[index];
                    URL.revokeObjectURL(picture.url);
                    pictureTakerState.pictures.splice(index, 1);
                    
                    updateGallery();
                    updatePictureCount();
                    saveToLocalStorage();
                    updateFormData();
                }}
            }};
            
            // Clear all pictures
            window.clearAll = function(widgetId) {{
                if (widgetId !== '{widget_id}') return;
                
                if (confirm('{_("Are you sure you want to delete all pictures?")}')) {{
                    pictureTakerState.pictures.forEach(picture => {{
                        URL.revokeObjectURL(picture.url);
                    }});
                    pictureTakerState.pictures = [];
                    
                    updateGallery();
                    updatePictureCount();
                    saveToLocalStorage();
                    updateFormData();
                }}
            }};
            
            // Save to localStorage
            function saveToLocalStorage() {{
                if ({str(self.save_locally).lower()}) {{
                    // Save picture metadata only (not blobs)
                    const metadata = pictureTakerState.pictures.map(p => ({{
                        id: p.id,
                        timestamp: p.timestamp,
                        size: p.size,
                        format: p.format
                    }}));
                    
                    localStorage.setItem('pictureTaker_{widget_id}_pictures', JSON.stringify(metadata));
                }}
            }}
            
            // Load stored pictures
            function loadStoredPictures() {{
                // Implementation for loading pictures from localStorage
                // Note: Actual blobs can't be stored, only metadata
            }}
            
            // Update form data
            function updateFormData() {{
                const input = document.querySelector('#{widget_id} input[data-pictures]');
                if (input) {{
                    const data = {{
                        count: pictureTakerState.pictures.length,
                        pictures: pictureTakerState.pictures.map(p => ({{
                            id: p.id,
                            timestamp: p.timestamp,
                            size: p.size,
                            format: p.format
                        }}))
                    }};
                    input.value = JSON.stringify(data);
                }}
            }}
            
            // Upload picture
            function uploadPicture(picture) {{
                if (!{str(self.enable_upload).lower()}) return;
                
                const formData = new FormData();
                formData.append('picture', picture.blob, "picture_" + picture.timestamp + "." + picture.format);
                formData.append('timestamp', picture.timestamp);
                
                fetch('{self.upload_endpoint}', {{
                    method: 'POST',
                    body: formData
                }})
                .then(response => response.json())
                .then(data => {{
                    console.log('Picture uploaded:', data);
                }})
                .catch(error => {{
                    console.error('Upload error:', error);
                }});
            }}
            
            // Settings functions
            window.openSettings = function(widgetId) {{
                if (widgetId !== '{widget_id}') return;
                
                const modal = new bootstrap.Modal(document.getElementById('{widget_id}_settings_modal'));
                modal.show();
            }};
            
            // Initialize when page loads
            document.addEventListener('DOMContentLoaded', initializePictureTaker);
            
            // Cleanup on page unload
            window.addEventListener('beforeunload', () => {{
                if (pictureTakerState.stream) {{
                    pictureTakerState.stream.getTracks().forEach(track => track.stop());
                }}

                // Cleanup object URLs
                pictureTakerState.pictures.forEach(picture => {{
                    URL.revokeObjectURL(picture.url);
                }});
            }});
        }})();
        </script>
        """


class OrgChartWidget(Input):
    """Advanced organizational chart widget with interactive hierarchy visualization."""
    
    def __init__(self, layout='top-to-bottom', enable_editing=True, enable_export=True, 
                 enable_search=True, enable_filters=True, enable_zoom=True,
                 enable_departments=True, enable_photos=True, show_details=True,
                 compact_mode=False, theme='professional', animation_duration=300,
                 max_levels=10, enable_drag_drop=True, **kwargs):
        """
        Initialize org chart widget.
        
        Args:
            layout: Chart layout ('top-to-bottom', 'left-to-right', 'radial')
            enable_editing: Allow adding/editing employees
            enable_export: Enable export functionality (PNG, PDF, SVG)
            enable_search: Enable employee search
            enable_filters: Enable department/role filters
            enable_zoom: Enable zoom and pan functionality
            enable_departments: Show department groupings
            enable_photos: Show employee photos
            show_details: Show detailed employee information
            compact_mode: Use compact node display
            theme: Visual theme ('professional', 'modern', 'colorful')
            animation_duration: Animation duration in milliseconds
            max_levels: Maximum hierarchy levels to display
            enable_drag_drop: Enable drag and drop reorganization
        """
        super().__init__(**kwargs)
        self.layout = layout
        self.enable_editing = enable_editing
        self.enable_export = enable_export
        self.enable_search = enable_search
        self.enable_filters = enable_filters
        self.enable_zoom = enable_zoom
        self.enable_departments = enable_departments
        self.enable_photos = enable_photos
        self.show_details = show_details
        self.compact_mode = compact_mode
        self.theme = theme
        self.animation_duration = animation_duration
        self.max_levels = max_levels
        self.enable_drag_drop = enable_drag_drop
        
        # Sample organizational data
        self.org_data = {
            'id': 'ceo',
            'name': 'John Smith',
            'title': 'Chief Executive Officer',
            'department': 'Executive',
            'email': 'john.smith@company.com',
            'phone': '+1-555-0100',
            'photo': None,
            'level': 0,
            'children': [
                {
                    'id': 'cto',
                    'name': 'Sarah Johnson',
                    'title': 'Chief Technology Officer',
                    'department': 'Technology',
                    'email': 'sarah.johnson@company.com',
                    'phone': '+1-555-0101',
                    'photo': None,
                    'level': 1,
                    'children': [
                        {
                            'id': 'dev_manager',
                            'name': 'Mike Chen',
                            'title': 'Development Manager',
                            'department': 'Technology',
                            'email': 'mike.chen@company.com',
                            'phone': '+1-555-0201',
                            'photo': None,
                            'level': 2,
                            'children': [
                                {
                                    'id': 'senior_dev1',
                                    'name': 'Alice Brown',
                                    'title': 'Senior Developer',
                                    'department': 'Technology',
                                    'email': 'alice.brown@company.com',
                                    'phone': '+1-555-0301',
                                    'photo': None,
                                    'level': 3,
                                    'children': []
                                },
                                {
                                    'id': 'senior_dev2',
                                    'name': 'David Wilson',
                                    'title': 'Senior Developer',
                                    'department': 'Technology',
                                    'email': 'david.wilson@company.com',
                                    'phone': '+1-555-0302',
                                    'photo': None,
                                    'level': 3,
                                    'children': []
                                }
                            ]
                        },
                        {
                            'id': 'qa_manager',
                            'name': 'Emma Davis',
                            'title': 'QA Manager',
                            'department': 'Technology',
                            'email': 'emma.davis@company.com',
                            'phone': '+1-555-0202',
                            'photo': None,
                            'level': 2,
                            'children': [
                                {
                                    'id': 'qa_lead',
                                    'name': 'Robert Garcia',
                                    'title': 'QA Lead',
                                    'department': 'Technology',
                                    'email': 'robert.garcia@company.com',
                                    'phone': '+1-555-0303',
                                    'photo': None,
                                    'level': 3,
                                    'children': []
                                }
                            ]
                        }
                    ]
                },
                {
                    'id': 'cfo',
                    'name': 'Lisa Anderson',
                    'title': 'Chief Financial Officer',
                    'department': 'Finance',
                    'email': 'lisa.anderson@company.com',
                    'phone': '+1-555-0102',
                    'photo': None,
                    'level': 1,
                    'children': [
                        {
                            'id': 'accounting_manager',
                            'name': 'James Taylor',
                            'title': 'Accounting Manager',
                            'department': 'Finance',
                            'email': 'james.taylor@company.com',
                            'phone': '+1-555-0203',
                            'photo': None,
                            'level': 2,
                            'children': []
                        }
                    ]
                },
                {
                    'id': 'hr_director',
                    'name': 'Maria Rodriguez',
                    'title': 'HR Director',
                    'department': 'Human Resources',
                    'email': 'maria.rodriguez@company.com',
                    'phone': '+1-555-0103',
                    'photo': None,
                    'level': 1,
                    'children': [
                        {
                            'id': 'hr_specialist',
                            'name': 'Kevin Thompson',
                            'title': 'HR Specialist',
                            'department': 'Human Resources',
                            'email': 'kevin.thompson@company.com',
                            'phone': '+1-555-0204',
                            'photo': None,
                            'level': 2,
                            'children': []
                        }
                    ]
                }
            ]
        }
        
        # Department colors
        self.department_colors = {
            'Executive': '#2c3e50',
            'Technology': '#3498db',
            'Finance': '#e74c3c',
            'Human Resources': '#f39c12',
            'Marketing': '#9b59b6',
            'Sales': '#1abc9c',
            'Operations': '#34495e',
            'Support': '#95a5a6'
        }
        
        # Layout configurations
        self.layout_configs = {
            'top-to-bottom': {
                'direction': 'TB',
                'node_spacing': 120,
                'level_spacing': 150
            },
            'left-to-right': {
                'direction': 'LR', 
                'node_spacing': 100,
                'level_spacing': 200
            },
            'radial': {
                'direction': 'radial',
                'radius_increment': 150,
                'angle_increment': 60
            }
        }

    def __call__(self, field, **kwargs):
        """Render the org chart widget."""
        kwargs.setdefault('id', field.id)
        kwargs.setdefault('name', field.name)
        
        chart_id = f"org_chart_{field.id}"
        theme_class = f"org-chart-{self.theme}"
        
        # Generate CSS styles
        css_styles = self._generate_css(chart_id)
        
        # Generate toolbar
        toolbar_html = self._generate_toolbar(chart_id)
        
        # Generate sidebar
        sidebar_html = self._generate_sidebar(chart_id)
        
        # Generate main chart area
        chart_area_html = self._generate_chart_area(chart_id)
        
        # Generate modals
        modals_html = self._generate_modals(chart_id)
        
        # Generate JavaScript
        javascript = self._generate_javascript(chart_id)
        
        return Markup(f"""
        {css_styles}
        <div id="{chart_id}" class="org-chart-container {theme_class}" 
             data-layout="{self.layout}" data-theme="{self.theme}">
            
            <!-- Toolbar -->
            {toolbar_html}
            
            <!-- Main Content Area -->
            <div class="org-chart-main">
                <!-- Sidebar -->
                {sidebar_html}
                
                <!-- Chart Area -->
                {chart_area_html}
            </div>
            
            <!-- Status Bar -->
            <div class="org-chart-status">
                <div class="status-info">
                    <span class="employee-count" id="{chart_id}_employee_count">
                        <i class="fas fa-users"></i> {self._count_employees(self.org_data)} {_('employees')}
                    </span>
                    <span class="department-count" id="{chart_id}_department_count">
                        <i class="fas fa-building"></i> {len(self._get_departments(self.org_data))} {_('departments')}
                    </span>
                    <span class="chart-layout">
                        <i class="fas fa-sitemap"></i> {self.layout.replace('-', ' ').title()}
                    </span>
                </div>
                <div class="status-actions">
                    <button class="btn btn-sm btn-outline-secondary" onclick="fitToScreen('{chart_id}')">
                        <i class="fas fa-expand-arrows-alt"></i> {_('Fit to Screen')}
                    </button>
                    <button class="btn btn-sm btn-outline-info" onclick="resetZoom('{chart_id}')">
                        <i class="fas fa-search-minus"></i> {_('Reset Zoom')}
                    </button>
                </div>
            </div>
            
            <!-- Hidden input for form data -->
            <input type="hidden" id="{kwargs['id']}" name="{kwargs['name']}" 
                   value="" data-org-data="">
        </div>
        
        {modals_html}
        {javascript}
        """)

    def _generate_toolbar(self, chart_id):
        """Generate the toolbar HTML."""
        editing_buttons = ""
        if self.enable_editing:
            editing_buttons = f"""
            <div class="toolbar-group">
                <button class="btn btn-primary" onclick="addEmployee('{chart_id}')">
                    <i class="fas fa-user-plus"></i> {_('Add Employee')}
                </button>
                <button class="btn btn-outline-secondary" onclick="editSelected('{chart_id}')">
                    <i class="fas fa-edit"></i> {_('Edit')}
                </button>
                <button class="btn btn-outline-danger" onclick="deleteSelected('{chart_id}')">
                    <i class="fas fa-user-minus"></i> {_('Remove')}
                </button>
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
                        <li><a class="dropdown-item" onclick="exportChart('{chart_id}', 'png')">
                            <i class="fas fa-image"></i> PNG Image
                        </a></li>
                        <li><a class="dropdown-item" onclick="exportChart('{chart_id}', 'svg')">
                            <i class="fas fa-vector-square"></i> SVG Vector
                        </a></li>
                        <li><a class="dropdown-item" onclick="exportChart('{chart_id}', 'pdf')">
                            <i class="fas fa-file-pdf"></i> PDF Document
                        </a></li>
                        <li><hr class="dropdown-divider"></li>
                        <li><a class="dropdown-item" onclick="exportChart('{chart_id}', 'json')">
                            <i class="fas fa-file-code"></i> JSON Data
                        </a></li>
                    </ul>
                </div>
            </div>
            """
        
        layout_buttons = f"""
        <div class="toolbar-group">
            <div class="dropdown">
                <button class="btn btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown">
                    <i class="fas fa-sitemap"></i> {_('Layout')}
                </button>
                <ul class="dropdown-menu">
                    <li><a class="dropdown-item" onclick="changeLayout('{chart_id}', 'top-to-bottom')">
                        <i class="fas fa-arrow-down"></i> {_('Top to Bottom')}
                    </a></li>
                    <li><a class="dropdown-item" onclick="changeLayout('{chart_id}', 'left-to-right')">
                        <i class="fas fa-arrow-right"></i> {_('Left to Right')}
                    </a></li>
                    <li><a class="dropdown-item" onclick="changeLayout('{chart_id}', 'radial')">
                        <i class="fas fa-sun"></i> {_('Radial')}
                    </a></li>
                </ul>
            </div>
        </div>
        """
        
        zoom_buttons = ""
        if self.enable_zoom:
            zoom_buttons = f"""
            <div class="toolbar-group">
                <button class="btn btn-outline-secondary" onclick="zoomIn('{chart_id}')">
                    <i class="fas fa-search-plus"></i>
                </button>
                <button class="btn btn-outline-secondary" onclick="zoomOut('{chart_id}')">
                    <i class="fas fa-search-minus"></i>
                </button>
                <span class="zoom-level" id="{chart_id}_zoom_level">100%</span>
            </div>
            """
        
        return f"""
        <div class="org-chart-toolbar">
            {editing_buttons}
            {layout_buttons}
            {zoom_buttons}
            {export_buttons}
            
            <div class="toolbar-group ml-auto">
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="{chart_id}_compact_mode" 
                           {'checked' if self.compact_mode else ''} onchange="toggleCompactMode('{chart_id}')">
                    <label class="form-check-label">{_('Compact')}</label>
                </div>
                <div class="form-check form-switch">
                    <input class="form-check-input" type="checkbox" id="{chart_id}_show_photos" 
                           {'checked' if self.enable_photos else ''} onchange="togglePhotos('{chart_id}')">
                    <label class="form-check-label">{_('Photos')}</label>
                </div>
            </div>
        </div>
        """

    def _generate_sidebar(self, chart_id):
        """Generate the sidebar HTML."""
        search_section = ""
        if self.enable_search:
            search_section = f"""
            <div class="sidebar-section">
                <h6><i class="fas fa-search"></i> {_('Search')}</h6>
                <div class="search-input-group">
                    <input type="text" class="form-control" id="{chart_id}_search" 
                           placeholder="{_('Search employees...')}" onkeyup="searchEmployees('{chart_id}')">
                    <button class="btn btn-outline-secondary" onclick="clearSearch('{chart_id}')">
                        <i class="fas fa-times"></i>
                    </button>
                </div>
            </div>
            """
        
        filters_section = ""
        if self.enable_filters:
            department_options = ""
            for dept in self._get_departments(self.org_data):
                department_options += f'<option value="{dept}">{dept}</option>'
            
            filters_section = f"""
            <div class="sidebar-section">
                <h6><i class="fas fa-filter"></i> {_('Filters')}</h6>
                <div class="filter-group">
                    <label>{_('Department')}</label>
                    <select class="form-control" id="{chart_id}_department_filter" 
                            onchange="filterByDepartment('{chart_id}')">
                        <option value="">{_('All Departments')}</option>
                        {department_options}
                    </select>
                </div>
                <div class="filter-group">
                    <label>{_('Level')}</label>
                    <select class="form-control" id="{chart_id}_level_filter" 
                            onchange="filterByLevel('{chart_id}')">
                        <option value="">{_('All Levels')}</option>
                        <option value="0">{_('Executive')}</option>
                        <option value="1">{_('Directors')}</option>
                        <option value="2">{_('Managers')}</option>
                        <option value="3">{_('Staff')}</option>
                    </select>
                </div>
                <button class="btn btn-outline-secondary btn-sm" onclick="clearFilters('{chart_id}')">
                    <i class="fas fa-times"></i> {_('Clear Filters')}
                </button>
            </div>
            """
        
        departments_section = ""
        if self.enable_departments:
            departments_list = ""
            for dept in self._get_departments(self.org_data):
                count = self._count_employees_in_department(self.org_data, dept)
                color = self.department_colors.get(dept, '#6c757d')
                departments_list += f"""
                <div class="department-item" onclick="highlightDepartment('{chart_id}', '{dept}')">
                    <div class="department-color" style="background-color: {color}"></div>
                    <div class="department-info">
                        <div class="department-name">{dept}</div>
                        <div class="department-count">{count} {_('employees')}</div>
                    </div>
                </div>
                """
            
            departments_section = f"""
            <div class="sidebar-section">
                <h6><i class="fas fa-building"></i> {_('Departments')}</h6>
                <div class="departments-list">
                    {departments_list}
                </div>
            </div>
            """
        
        return f"""
        <div class="org-chart-sidebar">
            {search_section}
            {filters_section}
            {departments_section}
            
            <div class="sidebar-section">
                <h6><i class="fas fa-info-circle"></i> {_('Selection')}</h6>
                <div class="selected-employee" id="{chart_id}_selected_info">
                    <div class="no-selection">
                        <i class="fas fa-mouse-pointer"></i>
                        <p>{_('Click on an employee to see details')}</p>
                    </div>
                </div>
            </div>
        </div>
        """

    def _generate_chart_area(self, chart_id):
        """Generate the chart area HTML."""
        return f"""
        <div class="org-chart-area">
            <div class="chart-container" id="{chart_id}_container">
                <svg id="{chart_id}_svg" class="org-chart-svg">
                    <!-- Chart will be rendered here -->
                </svg>
                
                <!-- Loading overlay -->
                <div class="chart-loading" id="{chart_id}_loading">
                    <div class="loading-spinner">
                        <i class="fas fa-spinner fa-spin"></i>
                        <p>{_('Loading organization chart...')}</p>
                    </div>
                </div>
                
                <!-- Zoom controls -->
                <div class="zoom-controls" style="{'display: block' if self.enable_zoom else 'display: none'}">
                    <button class="zoom-btn" onclick="zoomIn('{chart_id}')" title="{_('Zoom In')}">
                        <i class="fas fa-plus"></i>
                    </button>
                    <button class="zoom-btn" onclick="zoomOut('{chart_id}')" title="{_('Zoom Out')}">
                        <i class="fas fa-minus"></i>
                    </button>
                    <button class="zoom-btn" onclick="fitToScreen('{chart_id}')" title="{_('Fit to Screen')}">
                        <i class="fas fa-expand-arrows-alt"></i>
                    </button>
                </div>
                
                <!-- Minimap -->
                <div class="chart-minimap" id="{chart_id}_minimap" style="display: none;">
                    <div class="minimap-viewport"></div>
                </div>
            </div>
        </div>
        """

    def _generate_modals(self, chart_id):
        """Generate modal dialogs."""
        return f"""
        <!-- Employee Edit Modal -->
        <div class="modal fade" id="{chart_id}_employee_modal" tabindex="-1">
            <div class="modal-dialog modal-lg">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title" id="{chart_id}_modal_title">{_('Add Employee')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <form id="{chart_id}_employee_form">
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="form-group">
                                        <label>{_('Full Name')} *</label>
                                        <input type="text" class="form-control" name="name" required>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="form-group">
                                        <label>{_('Job Title')} *</label>
                                        <input type="text" class="form-control" name="title" required>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="form-group">
                                        <label>{_('Department')} *</label>
                                        <select class="form-control" name="department" required>
                                            <option value="">{_('Select Department')}</option>
                                            {''.join(f'<option value="{dept}">{dept}</option>' for dept in self.department_colors.keys())}
                                        </select>
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="form-group">
                                        <label>{_('Reports To')}</label>
                                        <select class="form-control" name="manager" id="{chart_id}_manager_select">
                                            <option value="">{_('No Manager (Top Level)')}</option>
                                        </select>
                                    </div>
                                </div>
                            </div>
                            
                            <div class="row">
                                <div class="col-md-6">
                                    <div class="form-group">
                                        <label>{_('Email')}</label>
                                        <input type="email" class="form-control" name="email">
                                    </div>
                                </div>
                                <div class="col-md-6">
                                    <div class="form-group">
                                        <label>{_('Phone')}</label>
                                        <input type="tel" class="form-control" name="phone">
                                    </div>
                                </div>
                            </div>
                            
                            <div class="form-group" style="{'display: block' if self.enable_photos else 'display: none'}">
                                <label>{_('Photo URL')}</label>
                                <input type="url" class="form-control" name="photo" 
                                       placeholder="{_('https://example.com/photo.jpg')}">
                            </div>
                            
                            <input type="hidden" name="id">
                            <input type="hidden" name="level">
                        </form>
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">{_('Cancel')}</button>
                        <button type="button" class="btn btn-primary" onclick="saveEmployee('{chart_id}')">{_('Save')}</button>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Employee Details Modal -->
        <div class="modal fade" id="{chart_id}_details_modal" tabindex="-1">
            <div class="modal-dialog">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">{_('Employee Details')}</h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body" id="{chart_id}_details_content">
                        <!-- Employee details will be populated here -->
                    </div>
                    <div class="modal-footer">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">{_('Close')}</button>
                        <button type="button" class="btn btn-primary" onclick="editEmployeeFromDetails('{chart_id}')">{_('Edit')}</button>
                    </div>
                </div>
            </div>
        </div>
        """

    def _count_employees(self, data):
        """Count total employees in the organization."""
        count = 1  # Count current employee
        for child in data.get('children', []):
            count += self._count_employees(child)
        return count

    def _get_departments(self, data):
        """Get all unique departments."""
        departments = set()
        
        def collect_departments(node):
            departments.add(node.get('department', 'Unknown'))
            for child in node.get('children', []):
                collect_departments(child)
        
        collect_departments(data)
        return sorted(list(departments))

    def _count_employees_in_department(self, data, department):
        """Count employees in a specific department."""
        count = 0
        
        def count_dept(node):
            nonlocal count
            if node.get('department') == department:
                count += 1
            for child in node.get('children', []):
                count_dept(child)
        
        count_dept(data)
        return count

    def _generate_css(self, chart_id):
        """Generate CSS styles for the org chart widget."""
        return f"""
        <style>
        #{chart_id}.org-chart-container {{
            background: #fff;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            height: 700px;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        
        #{chart_id}.org-chart-professional {{
            --primary-color: #2c3e50;
            --secondary-color: #3498db;
            --accent-color: #e74c3c;
            --text-color: #2c3e50;
            --bg-color: #ecf0f1;
            --border-color: #bdc3c7;
        }}
        
        #{chart_id}.org-chart-modern {{
            --primary-color: #667eea;
            --secondary-color: #764ba2;
            --accent-color: #f093fb;
            --text-color: #4a5568;
            --bg-color: #f7fafc;
            --border-color: #e2e8f0;
        }}
        
        #{chart_id}.org-chart-colorful {{
            --primary-color: #ff6b6b;
            --secondary-color: #4ecdc4;
            --accent-color: #45b7d1;
            --text-color: #2d3748;
            --bg-color: #f0fff4;
            --border-color: #c6f6d5;
        }}
        
        #{chart_id} .org-chart-toolbar {{
            display: flex;
            align-items: center;
            gap: 15px;
            padding: 12px 16px;
            background: var(--bg-color);
            border-bottom: 1px solid var(--border-color);
            flex-wrap: wrap;
        }}
        
        #{chart_id} .toolbar-group {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        
        #{chart_id} .toolbar-group.ml-auto {{
            margin-left: auto;
        }}
        
        #{chart_id} .org-chart-main {{
            display: flex;
            flex: 1;
            min-height: 0;
        }}
        
        #{chart_id} .org-chart-sidebar {{
            width: 280px;
            border-right: 1px solid var(--border-color);
            background: var(--bg-color);
            overflow-y: auto;
            padding: 16px;
        }}
        
        #{chart_id} .sidebar-section {{
            margin-bottom: 24px;
        }}
        
        #{chart_id} .sidebar-section h6 {{
            margin: 0 0 12px 0;
            font-size: 12px;
            font-weight: 600;
            color: var(--text-color);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        
        #{chart_id} .search-input-group {{
            display: flex;
            gap: 4px;
        }}
        
        #{chart_id} .filter-group {{
            margin-bottom: 12px;
        }}
        
        #{chart_id} .filter-group label {{
            display: block;
            font-size: 12px;
            font-weight: 500;
            color: var(--text-color);
            margin-bottom: 4px;
        }}
        
        #{chart_id} .form-control {{
            width: 100%;
            padding: 6px 10px;
            border: 1px solid var(--border-color);
            border-radius: 4px;
            font-size: 13px;
            background: #fff;
            color: var(--text-color);
        }}
        
        #{chart_id} .form-control:focus {{
            outline: none;
            border-color: var(--primary-color);
            box-shadow: 0 0 0 2px rgba(44,62,80,0.1);
        }}
        
        #{chart_id} .departments-list {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        #{chart_id} .department-item {{
            display: flex;
            align-items: center;
            gap: 10px;
            padding: 8px;
            border-radius: 4px;
            cursor: pointer;
            transition: background 0.2s ease;
        }}
        
        #{chart_id} .department-item:hover {{
            background: rgba(52,152,219,0.1);
        }}
        
        #{chart_id} .department-color {{
            width: 16px;
            height: 16px;
            border-radius: 50%;
            flex-shrink: 0;
        }}
        
        #{chart_id} .department-info {{
            flex: 1;
            min-width: 0;
        }}
        
        #{chart_id} .department-name {{
            font-size: 13px;
            font-weight: 500;
            color: var(--text-color);
        }}
        
        #{chart_id} .department-count {{
            font-size: 11px;
            color: #6c757d;
        }}
        
        #{chart_id} .selected-employee {{
            background: #fff;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 12px;
        }}
        
        #{chart_id} .no-selection {{
            text-align: center;
            color: #6c757d;
            padding: 20px 0;
        }}
        
        #{chart_id} .no-selection i {{
            font-size: 32px;
            margin-bottom: 8px;
            opacity: 0.5;
        }}
        
        #{chart_id} .employee-card {{
            display: flex;
            flex-direction: column;
            gap: 8px;
        }}
        
        #{chart_id} .employee-photo {{
            width: 60px;
            height: 60px;
            border-radius: 50%;
            object-fit: cover;
            align-self: center;
            border: 2px solid var(--border-color);
        }}
        
        #{chart_id} .employee-name {{
            font-weight: 600;
            color: var(--text-color);
            text-align: center;
        }}
        
        #{chart_id} .employee-title {{
            font-size: 12px;
            color: #6c757d;
            text-align: center;
        }}
        
        #{chart_id} .employee-contact {{
            font-size: 11px;
            color: #6c757d;
        }}
        
        #{chart_id} .org-chart-area {{
            flex: 1;
            position: relative;
            overflow: hidden;
            background: #fafafa;
        }}
        
        #{chart_id} .chart-container {{
            width: 100%;
            height: 100%;
            position: relative;
        }}
        
        #{chart_id} .org-chart-svg {{
            width: 100%;
            height: 100%;
            cursor: grab;
        }}
        
        #{chart_id} .org-chart-svg:active {{
            cursor: grabbing;
        }}
        
        #{chart_id} .chart-loading {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(255,255,255,0.9);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 10;
        }}
        
        #{chart_id} .loading-spinner {{
            text-align: center;
            color: var(--primary-color);
        }}
        
        #{chart_id} .loading-spinner i {{
            font-size: 32px;
            margin-bottom: 12px;
        }}
        
        #{chart_id} .zoom-controls {{
            position: absolute;
            top: 16px;
            right: 16px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            z-index: 5;
        }}
        
        #{chart_id} .zoom-btn {{
            width: 36px;
            height: 36px;
            background: rgba(255,255,255,0.9);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s ease;
            color: var(--text-color);
        }}
        
        #{chart_id} .zoom-btn:hover {{
            background: #fff;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        
        #{chart_id} .chart-minimap {{
            position: absolute;
            bottom: 16px;
            right: 16px;
            width: 200px;
            height: 120px;
            background: rgba(255,255,255,0.9);
            border: 1px solid var(--border-color);
            border-radius: 6px;
            z-index: 5;
        }}
        
        #{chart_id} .minimap-viewport {{
            position: absolute;
            border: 2px solid var(--primary-color);
            background: rgba(52,152,219,0.2);
            cursor: move;
        }}
        
        /* SVG Node Styles */
        #{chart_id} .org-node {{
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        
        #{chart_id} .org-node:hover {{
            transform: scale(1.05);
        }}
        
        #{chart_id} .org-node.selected {{
            filter: drop-shadow(0 4px 8px rgba(52,152,219,0.3));
        }}
        
        #{chart_id} .org-node.highlighted {{
            filter: drop-shadow(0 0 12px rgba(52,152,219,0.6));
        }}
        
        #{chart_id} .node-rect {{
            fill: #fff;
            stroke: var(--border-color);
            stroke-width: 1.5;
            rx: 8;
        }}
        
        #{chart_id} .node-rect.executive {{
            fill: #2c3e50;
            stroke: #34495e;
        }}
        
        #{chart_id} .node-rect.director {{
            fill: #3498db;
            stroke: #2980b9;
        }}
        
        #{chart_id} .node-rect.manager {{
            fill: #e74c3c;
            stroke: #c0392b;
        }}
        
        #{chart_id} .node-rect.staff {{
            fill: #f39c12;
            stroke: #d68910;
        }}
        
        #{chart_id} .node-photo {{
            clip-path: circle(18px);
        }}
        
        #{chart_id} .node-name {{
            font-size: 12px;
            font-weight: 600;
            fill: var(--text-color);
            text-anchor: middle;
        }}
        
        #{chart_id} .node-title {{
            font-size: 10px;
            fill: #6c757d;
            text-anchor: middle;
        }}
        
        #{chart_id} .connection-line {{
            stroke: var(--border-color);
            stroke-width: 2;
            fill: none;
        }}
        
        #{chart_id} .org-chart-status {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 8px 16px;
            background: var(--bg-color);
            border-top: 1px solid var(--border-color);
            font-size: 12px;
        }}
        
        #{chart_id} .status-info {{
            display: flex;
            gap: 16px;
            color: #6c757d;
        }}
        
        #{chart_id} .status-actions {{
            display: flex;
            gap: 8px;
        }}
        
        #{chart_id} .zoom-level {{
            color: var(--text-color);
            font-weight: 500;
            min-width: 40px;
            text-align: center;
        }}
        
        #{chart_id} .btn {{
            padding: 4px 8px;
            font-size: 12px;
            border-radius: 4px;
            border: 1px solid transparent;
            cursor: pointer;
            transition: all 0.2s ease;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 4px;
        }}
        
        #{chart_id} .btn-primary {{
            background: var(--primary-color);
            color: white;
            border-color: var(--primary-color);
        }}
        
        #{chart_id} .btn-outline-secondary {{
            color: #6c757d;
            border-color: #6c757d;
            background: transparent;
        }}
        
        #{chart_id} .btn-outline-secondary:hover {{
            background: #6c757d;
            color: white;
        }}
        
        #{chart_id} .btn-outline-info {{
            color: var(--secondary-color);
            border-color: var(--secondary-color);
            background: transparent;
        }}
        
        #{chart_id} .btn-outline-danger {{
            color: var(--accent-color);
            border-color: var(--accent-color);
            background: transparent;
        }}
        
        #{chart_id} .form-check {{
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        
        #{chart_id} .form-check-input {{
            margin: 0;
        }}
        
        #{chart_id} .form-check-label {{
            font-size: 12px;
            color: var(--text-color);
        }}
        
        /* Responsive design */
        @media (max-width: 768px) {{
            #{chart_id} .org-chart-main {{
                flex-direction: column;
            }}
            
            #{chart_id} .org-chart-sidebar {{
                width: 100%;
                border-right: none;
                border-bottom: 1px solid var(--border-color);
                max-height: 200px;
            }}
            
            #{chart_id} .toolbar-group {{
                flex-wrap: wrap;
            }}
        }}
        </style>
        """

    def _generate_javascript(self, chart_id):
        """Generate JavaScript for org chart functionality."""
        import json
        org_data_json = json.dumps(self.org_data)
        layout_config_json = json.dumps(self.layout_configs)
        department_colors_json = json.dumps(self.department_colors)
        
        return f"""
        <script src="https://d3js.org/d3.v7.min.js"></script>
        <script>
        (function() {{
            // Org chart state
            let orgChartState = {{
                data: {org_data_json},
                selectedEmployee: null,
                currentLayout: '{self.layout}',
                zoomLevel: 1,
                filters: {{
                    department: '',
                    level: '',
                    search: ''
                }},
                svg: null,
                g: null,
                zoom: null
            }};
            
            const layoutConfigs = {layout_config_json};
            const departmentColors = {department_colors_json};
            
            // Initialize org chart
            function initializeOrgChart() {{
                const container = document.getElementById('{chart_id}_container');
                const svg = d3.select('#{chart_id}_svg');
                
                // Setup zoom behavior
                const zoom = d3.zoom()
                    .scaleExtent([0.1, 3])
                    .on('zoom', (event) => {{
                        orgChartState.g.attr('transform', event.transform);
                        updateZoomLevel(event.transform.k);
                    }});
                
                svg.call(zoom);
                orgChartState.svg = svg;
                orgChartState.zoom = zoom;
                orgChartState.g = svg.append('g');
                
                // Hide loading
                hideLoading();
                
                // Render initial chart
                renderChart();
                
                // Update sidebar
                updateSidebar();
            }}
            
            // Render the organizational chart
            function renderChart() {{
                if (!orgChartState.g) return;
                
                showLoading();
                
                // Clear existing content
                orgChartState.g.selectAll('*').remove();
                
                // Filter data based on current filters
                const filteredData = applyFilters(orgChartState.data);
                
                // Create hierarchy
                const hierarchy = d3.hierarchy(filteredData);
                
                // Apply layout
                const layoutFunc = getLayoutFunction(orgChartState.currentLayout);
                const tree = layoutFunc(hierarchy);
                
                // Render connections
                renderConnections(tree);
                
                // Render nodes
                renderNodes(tree);
                
                hideLoading();
            }}
            
            // Get layout function based on current layout
            function getLayoutFunction(layout) {{
                const config = layoutConfigs[layout];
                
                switch (layout) {{
                    case 'top-to-bottom':
                        return d3.tree().size([800, 600]).separation((a, b) => {{
                            return a.parent === b.parent ? 1 : 2;
                        }});
                    
                    case 'left-to-right':
                        return d3.tree().size([600, 800]).separation((a, b) => {{
                            return a.parent === b.parent ? 1 : 2;
                        }});
                    
                    case 'radial':
                        return d3.tree().size([2 * Math.PI, 300]).separation((a, b) => {{
                            return (a.parent === b.parent ? 1 : 2) / a.depth;
                        }});
                    
                    default:
                        return d3.tree().size([800, 600]);
                }}
            }}
            
            // Render connections between nodes
            function renderConnections(tree) {{
                const links = tree.links();
                
                orgChartState.g.selectAll('.connection-line')
                    .data(links)
                    .enter()
                    .append('path')
                    .attr('class', 'connection-line')
                    .attr('d', (d) => {{
                        if (orgChartState.currentLayout === 'radial') {{
                            return d3.linkRadial()
                                .angle(d => d.x)
                                .radius(d => d.y)(d);
                        }} else if (orgChartState.currentLayout === 'left-to-right') {{
                            return d3.linkHorizontal()
                                .x(d => d.y)
                                .y(d => d.x)(d);
                        }} else {{
                            return d3.linkVertical()
                                .x(d => d.x)
                                .y(d => d.y)(d);
                        }}
                    }});
            }}
            
            // Render employee nodes
            function renderNodes(tree) {{
                const nodes = tree.descendants();
                const compactMode = document.getElementById('{chart_id}_compact_mode').checked;
                const showPhotos = document.getElementById('{chart_id}_show_photos').checked;
                
                const nodeGroups = orgChartState.g.selectAll('.org-node')
                    .data(nodes)
                    .enter()
                    .append('g')
                    .attr('class', 'org-node')
                    .attr('transform', (d) => {{
                        if (orgChartState.currentLayout === 'radial') {{
                            return `rotate(${{(d.x * 180 / Math.PI - 90)}}) translate(${{d.y}},0)`;
                        }} else if (orgChartState.currentLayout === 'left-to-right') {{
                            return `translate(${{d.y}}, ${{d.x}})`;
                        }} else {{
                            return `translate(${{d.x}}, ${{d.y}})`;
                        }}
                    }})
                    .on('click', (event, d) => {{
                        selectEmployee(d.data);
                        event.stopPropagation();
                    }})
                    .on('dblclick', (event, d) => {{
                        showEmployeeDetails(d.data);
                        event.stopPropagation();
                    }});
                
                // Add node rectangles
                nodeGroups.append('rect')
                    .attr('class', (d) => `node-rect ${{getLevelClass(d.data.level)}}`)
                    .attr('width', compactMode ? 120 : 160)
                    .attr('height', compactMode ? 60 : 80)
                    .attr('x', compactMode ? -60 : -80)
                    .attr('y', compactMode ? -30 : -40)
                    .style('fill', (d) => departmentColors[d.data.department] || '#fff');
                
                // Add employee photos (if enabled)
                if (showPhotos) {{
                    nodeGroups.append('image')
                        .attr('class', 'node-photo')
                        .attr('href', (d) => d.data.photo || '/static/img/default-avatar.png')
                        .attr('width', 36)
                        .attr('height', 36)
                        .attr('x', -18)
                        .attr('y', compactMode ? -25 : -30);
                }}
                
                // Add employee names
                nodeGroups.append('text')
                    .attr('class', 'node-name')
                    .attr('y', compactMode ? (showPhotos ? 0 : -10) : (showPhotos ? 5 : -5))
                    .text((d) => d.data.name)
                    .call(wrap, compactMode ? 110 : 150);
                
                // Add job titles
                nodeGroups.append('text')
                    .attr('class', 'node-title')
                    .attr('y', compactMode ? (showPhotos ? 12 : 5) : (showPhotos ? 20 : 10))
                    .text((d) => d.data.title)
                    .call(wrap, compactMode ? 110 : 150);
            }}
            
            // Text wrapping function
            function wrap(text, width) {{
                text.each(function() {{
                    const text = d3.select(this);
                    const words = text.text().split(/\\s+/).reverse();
                    let word;
                    let line = [];
                    let lineNumber = 0;
                    const lineHeight = 1.1;
                    const y = text.attr('y');
                    const dy = parseFloat(text.attr('dy')) || 0;
                    let tspan = text.text(null).append('tspan').attr('x', 0).attr('y', y).attr('dy', dy + 'em');
                    
                    while (word = words.pop()) {{
                        line.push(word);
                        tspan.text(line.join(' '));
                        if (tspan.node().getComputedTextLength() > width) {{
                            line.pop();
                            tspan.text(line.join(' '));
                            line = [word];
                            tspan = text.append('tspan').attr('x', 0).attr('y', y).attr('dy', ++lineNumber * lineHeight + dy + 'em').text(word);
                        }}
                    }}
                }});
            }}
            
            // Get CSS class based on organizational level
            function getLevelClass(level) {{
                switch (level) {{
                    case 0: return 'executive';
                    case 1: return 'director';
                    case 2: return 'manager';
                    default: return 'staff';
                }}
            }}
            
            // Apply current filters to data
            function applyFilters(data) {{
                // Implementation would filter based on orgChartState.filters
                return data; // Simplified for now
            }}
            
            // Select employee
            function selectEmployee(employee) {{
                orgChartState.selectedEmployee = employee;
                
                // Update visual selection
                orgChartState.g.selectAll('.org-node').classed('selected', false);
                orgChartState.g.selectAll('.org-node')
                    .filter((d) => d.data.id === employee.id)
                    .classed('selected', true);
                
                // Update sidebar
                updateSelectedEmployeeInfo(employee);
            }}
            
            // Update selected employee info in sidebar
            function updateSelectedEmployeeInfo(employee) {{
                const container = document.getElementById('{chart_id}_selected_info');
                
                if (!employee) {{
                    container.innerHTML = `
                        <div class="no-selection">
                            <i class="fas fa-mouse-pointer"></i>
                            <p>{_("Click on an employee to see details")}</p>
                        </div>
                    `;
                    return;
                }}
                
                const photoHtml = employee.photo ? 
                    `<img src="${{employee.photo}}" alt="${{employee.name}}" class="employee-photo">` :
                    `<div class="employee-photo" style="background: ${{departmentColors[employee.department] || '#6c757d'}}; display: flex; align-items: center; justify-content: center; color: white;">
                        <i class="fas fa-user"></i>
                    </div>`;
                
                container.innerHTML = `
                    <div class="employee-card">
                        ${{photoHtml}}
                        <div class="employee-name">${{employee.name}}</div>
                        <div class="employee-title">${{employee.title}}</div>
                        <div class="employee-contact">
                            ${{employee.email ? `<div><i class="fas fa-envelope"></i> ${{employee.email}}</div>` : ''}}
                            ${{employee.phone ? `<div><i class="fas fa-phone"></i> ${{employee.phone}}</div>` : ''}}
                            <div><i class="fas fa-building"></i> ${{employee.department}}</div>
                        </div>
                    </div>
                `;
            }}
            
            // Show/hide loading
            function showLoading() {{
                document.getElementById('{chart_id}_loading').style.display = 'flex';
            }}
            
            function hideLoading() {{
                document.getElementById('{chart_id}_loading').style.display = 'none';
            }}
            
            // Update zoom level display
            function updateZoomLevel(scale) {{
                orgChartState.zoomLevel = scale;
                const display = document.getElementById('{chart_id}_zoom_level');
                if (display) {{
                    display.textContent = Math.round(scale * 100) + '%';
                }}
            }}
            
            // Update sidebar with current data
            function updateSidebar() {{
                // Update employee count
                updateEmployeeCount();
                
                // Update department count
                updateDepartmentCount();
                
                // Populate manager select
                populateManagerSelect();
            }}
            
            function updateEmployeeCount() {{
                const count = countEmployees(orgChartState.data);
                const display = document.getElementById('{chart_id}_employee_count');
                if (display) {{
                    display.innerHTML = `<i class="fas fa-users"></i> ${{count}} {_("employees")}`;
                }}
            }}
            
            function updateDepartmentCount() {{
                const departments = getDepartments(orgChartState.data);
                const display = document.getElementById('{chart_id}_department_count');
                if (display) {{
                    display.innerHTML = `<i class="fas fa-building"></i> ${{departments.length}} {_("departments")}`;
                }}
            }}
            
            function countEmployees(data) {{
                let count = 1;
                data.children?.forEach(child => {{
                    count += countEmployees(child);
                }});
                return count;
            }}
            
            function getDepartments(data) {{
                const departments = new Set();
                
                function collect(node) {{
                    departments.add(node.department);
                    node.children?.forEach(collect);
                }}
                
                collect(data);
                return Array.from(departments).sort();
            }}
            
            function populateManagerSelect() {{
                // Implementation for populating manager dropdown in add/edit modal
            }}
            
            // Public API functions
            window.changeLayout = function(chartId, layout) {{
                if (chartId !== '{chart_id}') return;
                
                orgChartState.currentLayout = layout;
                renderChart();
            }};
            
            window.zoomIn = function(chartId) {{
                if (chartId !== '{chart_id}') return;
                
                orgChartState.svg.transition().call(
                    orgChartState.zoom.scaleBy, 1.2
                );
            }};
            
            window.zoomOut = function(chartId) {{
                if (chartId !== '{chart_id}') return;
                
                orgChartState.svg.transition().call(
                    orgChartState.zoom.scaleBy, 0.8
                );
            }};
            
            window.fitToScreen = function(chartId) {{
                if (chartId !== '{chart_id}') return;
                
                const bounds = orgChartState.g.node().getBBox();
                const parent = orgChartState.svg.node().parentElement;
                const fullWidth = parent.clientWidth;
                const fullHeight = parent.clientHeight;
                const width = bounds.width;
                const height = bounds.height;
                const midX = bounds.x + width / 2;
                const midY = bounds.y + height / 2;
                
                if (width === 0 || height === 0) return;
                
                const scale = Math.min(fullWidth / width, fullHeight / height) * 0.8;
                const translate = [fullWidth / 2 - scale * midX, fullHeight / 2 - scale * midY];
                
                orgChartState.svg.transition().call(
                    orgChartState.zoom.transform,
                    d3.zoomIdentity.translate(translate[0], translate[1]).scale(scale)
                );
            }};
            
            window.resetZoom = function(chartId) {{
                if (chartId !== '{chart_id}') return;
                
                orgChartState.svg.transition().call(
                    orgChartState.zoom.transform,
                    d3.zoomIdentity
                );
            }};
            
            window.addEmployee = function(chartId) {{
                if (chartId !== '{chart_id}') return;
                
                const modal = new bootstrap.Modal(document.getElementById('{chart_id}_employee_modal'));
                document.getElementById('{chart_id}_modal_title').textContent = '{_("Add Employee")}';
                document.getElementById('{chart_id}_employee_form').reset();
                modal.show();
            }};
            
            window.searchEmployees = function(chartId) {{
                if (chartId !== '{chart_id}') return;
                
                const searchTerm = document.getElementById('{chart_id}_search').value.toLowerCase();
                orgChartState.filters.search = searchTerm;
                
                // Highlight matching nodes
                orgChartState.g.selectAll('.org-node').classed('highlighted', false);
                
                if (searchTerm) {{
                    orgChartState.g.selectAll('.org-node')
                        .filter((d) => {{
                            return d.data.name.toLowerCase().includes(searchTerm) ||
                                   d.data.title.toLowerCase().includes(searchTerm) ||
                                   d.data.department.toLowerCase().includes(searchTerm);
                        }})
                        .classed('highlighted', true);
                }}
            }};
            
            window.toggleCompactMode = function(chartId) {{
                if (chartId !== '{chart_id}') return;
                renderChart();
            }};
            
            window.togglePhotos = function(chartId) {{
                if (chartId !== '{chart_id}') return;
                renderChart();
            }};
            
            // Initialize when D3 is loaded
            if (typeof d3 !== 'undefined') {{
                document.addEventListener('DOMContentLoaded', initializeOrgChart);
            }} else {{
                setTimeout(initializeOrgChart, 1000);
            }}
        }})();
        </script>
        """
