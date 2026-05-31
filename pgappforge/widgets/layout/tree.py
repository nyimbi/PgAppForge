"""TreeViewWidget — PgAppForge widget(s)."""

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

class TreeViewWidget(BS3TextFieldWidget):
    """
    Advanced treeview widget for self-referencing foreign keys in PgAppForge.

    Features:
    - Hierarchical display using jsTree for parent-child relationships
    - Drag and drop reordering using jsTree's drag and drop plugin
    - Expand/collapse nodes for better navigation in large trees
    - Custom node formatting to tailor the appearance of each node
    - Search/filter functionality using jsTree's search plugin
    - Lazy loading of large trees to efficiently handle extensive datasets
    - Contextual operations via right-click context menus
    - Multiple selection of nodes using checkboxes or standard selection
    - Node state persistence to remember expanded/selected nodes across sessions
    - AJAX updates for dynamic data loading and interaction
    - Enhanced Accessibility support following ARIA standards

    Database Type:
        PostgreSQL: ltree
        SQLAlchemy: LTREE or Integer (foreign key)

    Example Usage:
        parent_id = db.Column(db.Integer, db.ForeignKey('mytable.id'),
                            info={'widget': TreeViewWidget(
                                order_field='sort_order',
                                label_field='name'
                            )})
    """

    data_template = (
        '<div class="treeview-wrapper %(wrapper_class)s">'
        '<div class="treeview-toolbar">'
        '<input type="text" class="form-control search-input" placeholder="Search Nodes...">'
        '<div class="btn-group">'
        '<button type="button" class="btn btn-sm btn-outline-secondary expand-all">'
        '<i class="fa fa-plus-square-o"></i> Expand All'
        "</button>"
        '<button type="button" class="btn btn-sm btn-outline-secondary collapse-all">'
        '<i class="fa fa-minus-square-o"></i> Collapse All'
        "</button>"
        "</div>"
        "</div>"
        "<input %(hidden)s>"
        '<div id="%(field_id)s-tree" class="treeview"></div>'
        '<div class="treeview-error"></div>'
        "</div>"
    )

    JS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jstree/3.3.12/jstree.min.js"
    ]

    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/jstree/3.3.12/themes/default/style.min.css"
    ]

    def __init__(self, label=None, validators=None, **kwargs):
        """Initialize treeview widget with custom settings"""
        super().__init__(label, validators, **kwargs)
        self.order_field = kwargs.get("order_field", "id")
        self.label_field = kwargs.get("label_field", "name")
        self.parent_field = kwargs.get("parent_field", "parent_id")
        self.icon_field = kwargs.get("icon_field", None)
        self.max_depth = kwargs.get("max_depth", 10)
        self.wrapper_class = kwargs.get("wrapper_class", "")
        self.allow_drag = kwargs.get("allow_drag", True)
        self.allow_multi_select = kwargs.get("allow_multi_select", False)
        self.persist_state = kwargs.get("persist_state", True)
        self.lazy_load = kwargs.get("lazy_load", True)
        self.min_search_chars = kwargs.get("min_search_chars", 2)
        self.default_expanded = kwargs.get("default_expanded", False)
        self.show_checkbox = kwargs.get("show_checkbox", False)
        self.custom_actions = kwargs.get("custom_actions", [])
        self.node_formatter = kwargs.get("node_formatter", None)

    def __call__(self, field, **kwargs):
        """Render the treeview widget"""
        kwargs.setdefault("id", field.id)
        kwargs.setdefault("type", "hidden")
        kwargs.setdefault("role", "tree")  # Set role attribute for accessibility

        # Initialize tree data
        tree_data = self._get_tree_data(field)

        html = self.data_template % {
            "hidden": self.html_params(name=field.name, **kwargs),
            "field_id": field.id,
            "wrapper_class": self.wrapper_class,
        }

        return Markup(
            html
            + """
        <style>
            .treeview-wrapper {
                margin-bottom: 1.5rem;
            }
            .treeview-toolbar {
                margin-bottom: 1rem;
                display: flex;
                gap: 1rem;
                align-items: center;
            }
            .treeview-toolbar .search-input {
                max-width: 200px;
            }
            .treeview {
                max-height: 500px;
                overflow-y: auto;
                border: 1px solid #dee2e6;
                padding: 1rem;
            }
            .treeview .jstree-anchor.jstree-hovered {
                background-color: #cde4f8;
            }
            .treeview .jstree-anchor.jstree-clicked {
                background-color: #b8d7ef;
            }
            .treeview-error {
                color: #dc3545;
                font-size: 0.875rem;
                margin-top: 0.5rem;
                display: none;
            }
            .node-drag-hover {
                background-color: #ffc10726;
            }
            .node-loading::after {
                content: "Loading...";
                font-style: italic;
                color: #6c757d;
                margin-left: 0.5rem;
            }
        </style>
        <script>
            (function() {
                var $tree = $('#%(field_id)s-tree');
                var $input = $('#%(field_id)s');
                var $wrapper = $tree.closest('.treeview-wrapper');
                var $error = $wrapper.find('.treeview-error');
                var $search = $wrapper.find('.search-input');
                var treeInstance;

                function initTree() {
                    $tree.jstree({
                        'core' : {
                            'data' : %(tree_data)s,
                            'themes' : { 'icons': true },
                            'multiple' : %(allow_multi_select)s,
                            'check_callback' : function(operation, node, node_parent, position, more) {
                                if (operation === 'move_node' && !%(allow_drag)s) { return false; }
                                return true;
                            },
                            'error' : function(e) {
                                $error.text('jsTree error: ' + e.reason).show();
                            }
                        },
                        'plugins' : ['themes','contextmenu', 'dnd', 'search', 'state', 'wholerow', 'checkbox', 'sort', 'types', 'accessibility'],
                        'checkbox' : { 'tie_selection': false, 'whole_node': false, 'three_state': false },
                        'search' : { 'show_only_matches' : true, 'searchCallback' : function(str, node) {
                                return node.text.toLowerCase().indexOf(str.toLowerCase()) !== -1;
                            }
                        },
                        'sort' : function(a, b) {
                            return this.get_node(a).data.order - this.get_node(b).data.order;
                        },
                        'contextmenu' : {
                            'items' : %(custom_actions_js)s
                        },
                        'state' : { "key" : 'tree_%(field_id)s_state' },
                        'dnd' : { 'dnd_start_timeout' : 500 },
                        'types' : {
                             'default' : { 'icon' : 'fa fa-folder icon-state-warning', 'valid_children' : ['default','file'] },
                             'file' : { 'icon' : 'fa fa-file icon-state-default', 'max_children' : 0 }
                        },
                        'accessibility' : { 'tabindex' : 0, 'aria': { 'role': 'tree'} }
                    }).on('changed.jstree', function (e, data) {
                        if (data.action === 'select_node' || data.action === 'deselect_node') {
                            updateSelectedNodes();
                        }
                    }).on('move_node.jstree', function (e, data) {
                         handleNodeDrop(data);
                    });

                    treeInstance = $tree.jstree(true);
                    if(%(default_expanded)s) { treeInstance.open_all(); }


                }

                function updateSelectedNodes() {
                    var selectedNodes = treeInstance.get_selected();
                    $input.val(JSON.stringify(selectedNodes));
                }

                function handleNodeDrop(data) {
                    if (!%(allow_drag)s) return;

                    $.ajax({
                        url: window.location.pathname + '/reorder',
                        method: 'POST',
                        data: {
                            node_id: data.node.id,
                            parent_id: data.parent === '#' ? null : data.parent,
                            position: data.position,
                            order_field: '%(order_field)s'
                        },
                        success: function(response) {
                             // Optional: Handle success, maybe refresh tree or node
                        },
                        error: function(xhr) {
                            $error.text('Error updating node position').show();
                            treeInstance.refresh(); // Revert on error
                            setTimeout(function() { $error.hide(); }, 3000);
                        }
                    });
                }


                // Initialize tree
                initTree();


                // Search functionality
                var searchTimeout;
                $search.on('keyup', function() {
                    var pattern = $(this).val();
                    clearTimeout(searchTimeout);


                    searchTimeout = setTimeout(function() {
                        treeInstance.search(pattern);
                    }, 300);


                });


                // Expand/Collapse buttons
                $wrapper.find('.expand-all').on('click', function() {
                    treeInstance.open_all();
                });


                $wrapper.find('.collapse-all').on('click', function() {
                    treeInstance.close_all();
                });


            })();
        </script>
        """
            % {
                "field_id": field.id,
                "tree_data": json.dumps(tree_data),
                "allow_drag": str(self.allow_drag).lower(),
                "allow_multi_select": str(self.allow_multi_select).lower(),
                "show_checkbox": str(self.show_checkbox).lower(),
                "persist_state": str(self.persist_state).lower(),
                "default_expanded": str(self.default_expanded).lower(),
                "min_search_chars": self.min_search_chars,
                "order_field": self.order_field,
                "custom_actions_js": self._get_custom_actions_js(),
            }
        )

    def _get_tree_data(self, field):
        """Get hierarchical tree data from database"""
        try:
            model = field.model
            query = model.query.order_by(getattr(model, self.order_field))

            if self.lazy_load:
                # Only load first level
                query = query.filter(getattr(model, self.parent_field) == None)

            nodes = []
            for item in query.all():
                nodes.append(self._format_node(item))

            return nodes
        except Exception as e:
            import traceback

            traceback.print_exc()
            return []

    def _format_node(self, item, depth=0):
        """Format database item as tree node for jsTree"""
        if depth > self.max_depth:
            return None

        try:
            node = {
                "id": str(item.id),  # jsTree uses 'id'
                "text": str(getattr(item, self.label_field)),  # jsTree uses 'text'
                "icon": getattr(item, self.icon_field)
                if self.icon_field
                else "fa fa-folder",
                "state": {"opened": self.default_expanded, "selected": False},
                "li_attr": {"role": "treeitem"},  # Accessibility attributes
                "a_attr": {
                    "href": "#",
                    "aria-label": str(getattr(item, self.label_field)),
                },  # Accessibility attributes
                "data": {
                    "depth": depth,
                    "parent_id": getattr(item, self.parent_field),
                    "order": getattr(item, self.order_field),
                },
            }

            # Apply custom node formatting if provided
            if self.node_formatter:
                node = self.node_formatter(node, item)

            # Add children if not lazy loading
            if not self.lazy_load:
                children = (
                    item.query.filter(getattr(item, self.parent_field) == item.id)
                    .order_by(getattr(item, self.order_field))
                    .all()
                )

                if children:
                    child_nodes = []
                    for child in children:
                        formatted_child = self._format_node(child, depth + 1)
                        if formatted_child:  # Ensure _format_node doesn't return None
                            child_nodes.append(formatted_child)
                    node["children"] = child_nodes

            return node
        except Exception as e:
            import traceback

            traceback.print_exc()
            return None

    def _get_custom_actions_js(self):
        """Generate JavaScript for custom node actions for jsTree context menu"""
        if not self.custom_actions:
            return "null"  # jsTree expects null for no contextmenu

        actions = {}
        for action in self.custom_actions:
            action_def = {
                "label": action["label"],
                "action": Markup(f"""function(data) {{
                    var inst = $.jstree.reference(data.reference);
                    var node = inst.get_node(data.reference);
                    {action["handler"]}
                }}""").unescape(),  # Use unescape to handle JavaScript code safely
            }
            if action.get("icon"):  # Include icon if provided
                action_def["icon"] = action["icon"]
            actions[action["name"]] = action_def  # Use action name as key

        return Markup(
            json.dumps(actions)
        ).unescape()  # Return serialized JSON, unescape for HTML context

    def process_formdata(self, valuelist):
        """Process form data to database format"""
        if valuelist:
            try:
                self.data = json.loads(valuelist[0])
            except json.JSONDecodeError as e:
                self.data = None
                raise ValidationError("Invalid JSON for TreeView data") from e
        else:
            self.data = None

    def pre_validate(self, form):
        """Validate field before form processing"""
        if form.flags.required and not self.data:
            raise ValidationError(_("This field is required"))
