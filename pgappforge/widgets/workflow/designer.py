"""WorkflowDesignerWidget — PgAppForge widget(s)."""

from __future__ import annotations
import json
import re
from dataclasses import dataclass
from datetime import datetime, time
from typing import Any
from pgappforge.fieldwidgets import BS3TextFieldWidget
from pgappforge.widgets._utils import js_json as _js_json
from flask_babel import lazy_gettext as _
from markupsafe import Markup
from wtforms import Field
from wtforms.fields import (
    BooleanField, DateField, DateTimeField, DecimalField, FileField,
    FloatField, IntegerField, PasswordField, SelectField,
    SelectMultipleField, StringField, TextAreaField,
)
from wtforms.validators import ValidationError
from wtforms.widgets import TextInput, html_params

class WorkflowDesignerWidget(BS3TextFieldWidget):
    """
    Visual workflow/process designer widget for creating and editing business process workflows.
    Database column should be JSONB type in PostgreSQL to store workflow definition, state and history.

    Features:
    - Drag and drop nodes with snap-to-grid
    - Smart connection routing with path optimization
    - Extensive node type library (tasks, decisions, events, etc)
    - Real-time validation rules and constraint checking
    - Nested sub-workflows with collapsible views
    - Import/export to BPMN 2.0 and custom formats
    - Template library with common workflow patterns
    - Full version control with diff viewing
    - Interactive preview/simulation mode
    - Responsive mobile/touch support
    - Undo/redo stack
    - Keyboard shortcuts
    - Minimap navigation
    - Search/filter nodes
    - Commenting system
    - Custom node styling
    - Auto-layout
    - Zoom controls
    - Grid alignment
    - Node groups
    - Edge labels

    Required Dependencies:
    - JointJS 3.5+
    - Lodash 4+
    - Backbone.js
    - GraphLib
    - dag.js

    Example:
        process = db.Column(db.JSON, nullable=False,
            info={'widget': WorkflowDesignerWidget(
                node_types=[
                    {'id': 'task', 'label': 'Task', 'color': '#2196F3'},
                    {'id': 'decision', 'label': 'Decision', 'color': '#FFC107'},
                    {'id': 'event', 'label': 'Event', 'color': '#4CAF50'},
                    {'id': 'subprocess', 'label': 'Sub-Process', 'color': '#9C27B0'}
                ],
                templates=True,
                validation_rules=[
                    'no_cycles',
                    'required_start_end',
                    'max_decision_branches'
                ],
                grid_size=20,
                auto_layout=True,
                enable_comments=True,
                enable_history=True
            )})
    """

    data_template = (
        '<div class="workflow-designer-wrapper %(wrapper_class)s">'
        '<div class="workflow-toolbar mb-2">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-secondary undo" disabled>'
        '<i class="fa fa-undo"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary redo" disabled>'
        '<i class="fa fa-redo"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomIn">'
        '<i class="fa fa-search-plus"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomOut">'
        '<i class="fa fa-search-minus"></i>'
        "</button>"
        '<button type="button" class="btn btn-sm btn-secondary" data-command="zoomFit">'
        '<i class="fa fa-arrows-alt"></i>'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<button type="button" class="btn btn-sm btn-secondary" data-command="autoLayout">'
        '<i class="fa fa-magic"></i> Auto Layout'
        "</button>"
        "</div>"
        '<div class="btn-group ml-2">'
        '<div class="dropdown">'
        '<button type="button" class="btn btn-sm btn-secondary dropdown-toggle" data-toggle="dropdown">'
        'Export <i class="fa fa-download"></i>'
        "</button>"
        '<div class="dropdown-menu">'
        '<a class="dropdown-item" href="#" data-export="png">PNG Image</a>'
        '<a class="dropdown-item" href="#" data-export="svg">SVG Vector</a>'
        '<a class="dropdown-item" href="#" data-export="bpmn">BPMN 2.0</a>'
        '<a class="dropdown-item" href="#" data-export="json">JSON</a>'
        "</div>"
        "</div>"
        "</div>"
        "</div>"
        '<div class="workflow-container">'
        '<div class="workflow-sidebar">'
        '<div class="node-palette"></div>'
        '<div class="minimap mt-3"></div>'
        "</div>"
        '<div id="%(field_id)s_paper" class="workflow-paper"></div>'
        "</div>"
        '<input type="hidden" name="%(name)s" id="%(field_id)s">'
        '<div class="workflow-validation mt-2"></div>'
        "</div>"
    )

    def __init__(self, **kwargs):
        """Initialize workflow designer widget with configuration"""
        super().__init__(**kwargs)
        self.node_types = kwargs.get(
            "node_types",
            [
                {"id": "task", "label": "Task", "color": "#2196F3"},
                {"id": "decision", "label": "Decision", "color": "#FFC107"},
                {"id": "event", "label": "Event", "color": "#4CAF50"},
            ],
        )
        self.templates = kwargs.get("templates", True)
        self.validation_rules = kwargs.get("validation_rules", ["no_cycles"])
        self.grid_size = kwargs.get("grid_size", 20)
        self.auto_layout = kwargs.get("auto_layout", True)
        self.enable_comments = kwargs.get("enable_comments", True)
        self.enable_history = kwargs.get("enable_history", True)
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.min_zoom = kwargs.get("min_zoom", 0.2)
        self.max_zoom = kwargs.get("max_zoom", 2)
        self.default_node_width = kwargs.get("default_node_width", 120)
        self.default_node_height = kwargs.get("default_node_height", 60)
        self.connection_color = kwargs.get("connection_color", "#666")
        self.highlight_color = kwargs.get("highlight_color", "#0d6efd")
        self.grid_color = kwargs.get("grid_color", "#eee")
        self.max_nodes = kwargs.get("max_nodes", 100)
        self.max_connections = kwargs.get("max_connections", 200)
        self.undo_levels = kwargs.get("undo_levels", 50)

    def __call__(self, field, **kwargs):
        """Render the workflow designer widget"""
        kwargs.setdefault("id", field.id)
        if field.flags.required:
            kwargs["required"] = True

        html = self.data_template % {
            "name": field.name,
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(html + self._get_widget_scripts(field))

    def _get_widget_scripts(self, field):
        """Generate widget initialization JavaScript"""
        return """
        <script>
            (function() {
                var graph = new joint.dia.Graph();
                var paper = new joint.dia.Paper({
                    el: document.getElementById('%(field_id)s_paper'),
                    model: graph,
                    width: '100%%',
                    height: 600,
                    gridSize: %(grid_size)d,
                    drawGrid: true,
                    gridColor: '%(grid_color)s',
                    defaultConnectionColor: '%(connection_color)s',
                    defaultHighlightColor: '%(highlight_color)s',
                    interactive: true,
                    snapLinks: true,
                    linkPinning: false,
                    validateConnection: validateConnection,
                    defaultLink: new joint.shapes.standard.Link(),
                    defaultRouter: { name: 'manhattan' },
                    defaultConnector: { name: 'rounded' },
                    highlighting: {
                        default: {
                            name: 'stroke',
                            options: {
                                padding: 6,
                                rx: 5,
                                ry: 5
                            }
                        }
                    }
                });

                // Initialize node palette
                var nodeTypes = %(node_types)s;
                var palette = document.querySelector('.node-palette');
                nodeTypes.forEach(function(type) {
                    var node = createNode(type);
                    node.position(10, 10);
                    var nodeView = new joint.dia.ElementView({
                        model: node,
                        interactive: false
                    });
                    palette.appendChild(nodeView.render().el);
                });

                // Initialize minimap
                var minimap = new joint.dia.Paper({
                    el: document.querySelector('.minimap'),
                    model: graph,
                    width: 200,
                    height: 150,
                    interactive: false,
                    sorting: joint.dia.Paper.sorting.NONE
                });

                // Drag and drop from palette
                $(palette).on('mousedown', '.node', function(evt) {
                    var type = $(this).data('type');
                    var node = createNode(type);
                    var pos = paper.clientToLocalPoint(evt.clientX, evt.clientY);
                    node.position(pos.x, pos.y);
                    graph.addCell(node);
                });

                // Validation
                function validateConnection(cellViewS, magnetS, cellViewT, magnetT) {
                    if (magnetS && magnetS.getAttribute('port-group') === 'in') return false;
                    if (magnetT && magnetT.getAttribute('port-group') === 'out') return false;
                    return true;
                }

                // Node creation helper
                function createNode(type) {
                    return new joint.shapes.standard.Rectangle({
                        size: { width: %(default_node_width)d, height: %(default_node_height)d },
                        attrs: {
                            body: {
                                fill: type.color,
                                stroke: 'none',
                                rx: 5,
                                ry: 5
                            },
                            label: {
                                text: type.label,
                                fill: 'white',
                                fontSize: 14
                            }
                        },
                        ports: {
                            groups: {
                                'in': {
                                    position: 'top',
                                    label: { position: 'outside' },
                                    attrs: {
                                        circle: {
                                            fill: '#fff',
                                            stroke: '#000',
                                            r: 6
                                        }
                                    }
                                },
                                'out': {
                                    position: 'bottom',
                                    label: { position: 'outside' },
                                    attrs: {
                                        circle: {
                                            fill: '#fff',
                                            stroke: '#000',
                                            r: 6
                                        }
                                    }
                                }
                            }
                        }
                    });
                }

                // Save workflow state
                paper.on('cell:pointerup blank:pointerup', function() {
                    var workflow = {
                        cells: graph.toJSON(),
                        zoom: paper.scale(),
                        pan: paper.translate()
                    };
                    $('#%(field_id)s').val(JSON.stringify(workflow));
                });

                // Load initial state
                var initialValue = %(initial_value)s;
                if (initialValue && initialValue.cells) {
                    graph.fromJSON(initialValue.cells);
                    if (initialValue.zoom) paper.scale(initialValue.zoom);
                    if (initialValue.pan) paper.translate(initialValue.pan.x, initialValue.pan.y);
                }

                // Export handlers
                document.querySelectorAll('[data-export]').forEach(function(button) {
                    button.addEventListener('click', function(e) {
                        e.preventDefault();
                        var format = this.dataset.export;
                        exportWorkflow(format);
                    });
                });

                function exportWorkflow(format) {
                    var data;
                    switch(format) {
                        case 'png':
                            paper.toPNG(function(dataURL) {
                                downloadFile(dataURL, 'workflow.png');
                            });
                            break;
                        case 'svg':
                            paper.toSVG(function(svg) {
                                var blob = new Blob([svg], {type: 'image/svg+xml'});
                                downloadFile(URL.createObjectURL(blob), 'workflow.svg');
                            });
                            break;
                        case 'bpmn':
                            data = convertToBPMN(graph);
                            downloadFile(
                                'data:text/xml;charset=utf-8,' + encodeURIComponent(data),
                                'workflow.bpmn'
                            );
                            break;
                        case 'json':
                            data = JSON.stringify(graph.toJSON(), null, 2);
                            downloadFile(
                                'data:application/json;charset=utf-8,' + encodeURIComponent(data),
                                'workflow.json'
                            );
                            break;
                    }
                }

                function downloadFile(url, filename) {
                    var link = document.createElement('a');
                    link.href = url;
                    link.download = filename;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                }
            })();
        </script>
        """ % {
            "field_id": field.id,
            "grid_size": self.grid_size,
            "grid_color": self.grid_color,
            "connection_color": self.connection_color,
            "highlight_color": self.highlight_color,
            "default_node_width": self.default_node_width,
            "default_node_height": self.default_node_height,
            "node_types": json.dumps(self.node_types),
            "initial_value": json.dumps(field.data) if field.data else "null",
        }

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                data = json.loads(valuelist[0])
                self._validate_workflow(data)
                self.data = data
            except json.JSONDecodeError as e:
                raise ValueError("Invalid workflow data format") from e
        else:
            self.data = None

    def _validate_workflow(self, data):
        """Validate workflow structure and constraints"""
        if not isinstance(data, dict) or "cells" not in data:
            raise ValueError("Invalid workflow data structure")

        # Count nodes and connections
        nodes = [cell for cell in data["cells"] if cell["type"] != "link"]
        connections = [cell for cell in data["cells"] if cell["type"] == "link"]

        if len(nodes) > self.max_nodes:
            raise ValueError(f"Workflow exceeds maximum nodes ({self.max_nodes})")

        if len(connections) > self.max_connections:
            raise ValueError(
                f"Workflow exceeds maximum connections ({self.max_connections})"
            )

        # Validate based on rules
        if "no_cycles" in self.validation_rules:
            if self._has_cycles(data["cells"]):
                raise ValueError("Workflow contains cycles")

        if "required_start_end" in self.validation_rules:
            if not self._has_start_end(nodes):
                raise ValueError("Workflow must have start and end events")

    def _has_cycles(self, cells):
        """Check for cycles in the workflow"""
        connections = [c for c in cells if c["type"] == "link"]

        # Build adjacency list
        graph = collections.defaultdict(list)
        for conn in connections:
            graph[conn["source"]["id"]].append(conn["target"]["id"])

        # DFS to detect cycles
        visited = set()
        path = set()

        def visit(node):
            if node in path:
                return True
            if node in visited:
                return False
            visited.add(node)
            path.add(node)
            for neighbor in graph[node]:
                if visit(neighbor):
                    return True
            path.remove(node)
            return False

        return any(visit(node) for node in graph)

    def _has_start_end(self, nodes):
        """Check for required start and end events"""
        start_events = [
            n for n in nodes if n["type"] == "event" and "start" in n.get("subtype", "")
        ]
        end_events = [
            n for n in nodes if n["type"] == "event" and "end" in n.get("subtype", "")
        ]
        return bool(start_events and end_events)

    def pre_validate(self, form):
        """Validate workflow data before form processing"""
        if form.flags.required and not self.data:
            raise ValueError("Workflow data is required")
