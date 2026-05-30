"""
Color Picker Widget for PgForge

Advanced color picker widget with multiple input methods and accessibility features.
"""

import json
import logging
from typing import List, Optional
from uuid import uuid4

from flask import Markup, render_template_string
from flask_babel import gettext
from wtforms.widgets import Input

log = logging.getLogger(__name__)


class ColorPickerWidget(Input):
    """
    Advanced color picker widget with multiple input methods.

    Features:
    - Color palette selector
    - RGB/HSL/Hex input modes
    - Color history/favorites
    - Eyedropper tool (where supported)
    - Gradient picker
    - Accessibility features
    - Custom color swatches
    """

    input_type = 'color'

    def __init__(self,
                 show_palette: bool = True,
                 show_input: bool = True,
                 show_history: bool = True,
                 custom_colors: Optional[List[str]] = None,
                 format_output: str = 'hex'):  # hex, rgb, hsl
        """
        Initialize the color picker widget.

        Args:
            show_palette: Show color palette
            show_input: Show text input for color values
            show_history: Show recently used colors
            custom_colors: List of custom color swatches
            format_output: Output format (hex, rgb, hsl)
        """
        self.show_palette = show_palette
        self.show_input = show_input
        self.show_history = show_history
        self.custom_colors = custom_colors or []
        self.format_output = format_output

    def __call__(self, field, **kwargs):
        """Render the color picker widget."""
        widget_id = kwargs.get('id', f'color_picker_{uuid4().hex[:8]}')
        kwargs.setdefault('id', widget_id)
        kwargs.setdefault('class', 'form-control color-picker')

        template = """
        <div class="color-picker-container" data-widget="color-picker">
            <div class="color-input-group">
                <input type="color" id="{{ widget_id }}" name="{{ field.name }}"
                       value="{{ field.data or '#000000' }}" class="native-color-picker">

                {% if show_input %}
                <input type="text" class="form-control color-text-input"
                       value="{{ field.data or '#000000' }}"
                       placeholder="#000000">
                {% endif %}

                <button type="button" class="btn btn-outline-secondary color-preview"
                        style="background-color: {{ field.data or '#000000' }};">
                    <i class="fa fa-palette"></i>
                </button>
            </div>

            {% if show_palette or show_history %}
            <div class="color-picker-panel" style="display: none;">
                {% if show_palette %}
                <div class="color-palette">
                    <h6>{{ _('Color Palette') }}</h6>
                    <div class="palette-grid">
                        {% for color in default_colors %}
                        <button type="button" class="color-swatch"
                                style="background-color: {{ color }};"
                                data-color="{{ color }}" title="{{ color }}"></button>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}

                {% if custom_colors %}
                <div class="custom-colors">
                    <h6>{{ _('Custom Colors') }}</h6>
                    <div class="custom-grid">
                        {% for color in custom_colors %}
                        <button type="button" class="color-swatch"
                                style="background-color: {{ color }};"
                                data-color="{{ color }}" title="{{ color }}"></button>
                        {% endfor %}
                    </div>
                </div>
                {% endif %}

                {% if show_history %}
                <div class="color-history">
                    <h6>{{ _('Recent Colors') }}</h6>
                    <div class="history-grid" id="color-history-{{ widget_id }}">
                        <!-- Recent colors will be populated here -->
                    </div>
                </div>
                {% endif %}
            </div>
            {% endif %}
        </div>

        <style>
        .color-picker-container {
            position: relative;
            margin-bottom: 1rem;
        }

        .color-input-group {
            display: flex;
            gap: 0.5rem;
            align-items: center;
        }

        .native-color-picker {
            width: 50px;
            height: 40px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
        }

        .color-text-input {
            flex: 1;
            font-family: monospace;
        }

        .color-preview {
            width: 40px;
            height: 40px;
            border-radius: 6px;
            border: 2px solid #dee2e6;
            position: relative;
            overflow: hidden;
        }

        .color-picker-panel {
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
        }

        .palette-grid, .custom-grid, .history-grid {
            display: grid;
            grid-template-columns: repeat(8, 1fr);
            gap: 4px;
            margin-top: 0.5rem;
        }

        .color-swatch {
            width: 32px;
            height: 32px;
            border: 2px solid #fff;
            border-radius: 4px;
            cursor: pointer;
            transition: all 0.2s ease;
            box-shadow: 0 1px 3px rgba(0,0,0,0.2);
        }

        .color-swatch:hover {
            transform: scale(1.1);
            box-shadow: 0 2px 6px rgba(0,0,0,0.3);
        }

        .color-swatch.active {
            border-color: #0d6efd;
            box-shadow: 0 0 0 2px rgba(13, 110, 253, 0.25);
        }
        </style>

        <script>
        (function() {
            const container = document.querySelector('[data-widget="color-picker"]');
            const nativeInput = document.getElementById('{{ widget_id }}');
            const textInput = container.querySelector('.color-text-input');
            const preview = container.querySelector('.color-preview');
            const panel = container.querySelector('.color-picker-panel');

            const defaultColors = [
                '#FF0000', '#FF8000', '#FFFF00', '#80FF00', '#00FF00', '#00FF80', '#00FFFF', '#0080FF',
                '#0000FF', '#8000FF', '#FF00FF', '#FF0080', '#800000', '#804000', '#808000', '#408000',
                '#008000', '#008040', '#008080', '#004080', '#000080', '#400080', '#800080', '#800040',
                '#000000', '#404040', '#808080', '#C0C0C0', '#FFFFFF', '#FF8080', '#FFFF80', '#80FF80'
            ];

            // Initialize with default colors
            if (panel) {
                const paletteGrid = panel.querySelector('.palette-grid');
                if (paletteGrid) {
                    defaultColors.forEach(color => {
                        const swatch = document.createElement('button');
                        swatch.type = 'button';
                        swatch.className = 'color-swatch';
                        swatch.style.backgroundColor = color;
                        swatch.dataset.color = color;
                        swatch.title = color;
                        paletteGrid.appendChild(swatch);
                    });
                }
            }

            // Color change handlers
            function updateColor(color) {
                nativeInput.value = color;
                if (textInput) textInput.value = color;
                preview.style.backgroundColor = color;

                // Update active swatch
                container.querySelectorAll('.color-swatch').forEach(swatch => {
                    swatch.classList.toggle('active', swatch.dataset.color === color);
                });

                // Add to history
                addToHistory(color);
            }

            function addToHistory(color) {
                {% if show_history %}
                const historyGrid = document.getElementById('color-history-{{ widget_id }}');
                if (historyGrid) {
                    // Remove if already exists
                    const existing = historyGrid.querySelector(`[data-color="${color}"]`);
                    if (existing) existing.remove();

                    // Add to beginning
                    const swatch = document.createElement('button');
                    swatch.type = 'button';
                    swatch.className = 'color-swatch';
                    swatch.style.backgroundColor = color;
                    swatch.dataset.color = color;
                    swatch.title = color;
                    historyGrid.insertBefore(swatch, historyGrid.firstChild);

                    // Limit to 8 colors
                    while (historyGrid.children.length > 8) {
                        historyGrid.removeChild(historyGrid.lastChild);
                    }
                }
                {% endif %}
            }

            // Event listeners
            nativeInput.addEventListener('change', () => updateColor(nativeInput.value));

            if (textInput) {
                textInput.addEventListener('change', () => {
                    const color = textInput.value;
                    if (/^#[0-9A-F]{6}$/i.test(color)) {
                        updateColor(color);
                    }
                });
            }

            preview.addEventListener('click', () => {
                if (panel) {
                    panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
                }
            });

            container.addEventListener('click', (e) => {
                if (e.target.classList.contains('color-swatch')) {
                    updateColor(e.target.dataset.color);
                }
            });

            // Close panel when clicking outside
            document.addEventListener('click', (e) => {
                if (panel && !container.contains(e.target)) {
                    panel.style.display = 'none';
                }
            });

            // Initialize
            updateColor(nativeInput.value || '#000000');
        })();
        </script>
        """

        return Markup(render_template_string(template,
            widget_id=widget_id,
            field=field,
            show_palette=self.show_palette,
            show_input=self.show_input,
            show_history=self.show_history,
            custom_colors=self.custom_colors,
            _=gettext
        ))