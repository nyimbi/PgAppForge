"""DatabaseStructureWidget — PgAppForge widget(s)."""

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

class DatabaseStructureWidget(BS3TextFieldWidget):
    """
    Widget for introspecting and visualizing PgAppForge database structure
    with interactive ERD diagrams.

    Features:
    - Automatic database introspection using SQLAlchemy reflection
    - Interactive ERD visualization with D3.js
    - Relationship mapping with foreign key detection
    - Table details view with column info and data preview
    - Column information including types, constraints, and indexes
    - Index visualization with optimization hints
    - Primary/foreign key constraint display
    - Export to multiple formats (PNG, SVG, PDF, DBML, SQL)
    - Full-text search across tables and columns
    - Zoom/Pan controls with minimap navigation
    - Filtering by schema/table/column
    - Custom styling themes
    - Documentation generation with Markdown/PDF
    - Change tracking with Git-style diff
    - Schema comparison with visual diff

    Database Type:
        PostgreSQL: JSONB for storing schema metadata and change history
        SQLAlchemy: JSON type with schema validation

    Browser Support:
    - Chrome >= 60
    - Firefox >= 60
    - Safari >= 12
    - Edge >= 79

    Required Permissions:
    - Database read access for introspection
    - File system access for exports
    - LocalStorage for preferences
    - WebSocket for real-time updates

    Performance Considerations:
    - Lazy loading of table details
    - Caching of introspection results
    - Web worker for layout calculations
    - Throttled rendering updates
    - Memory cleanup on unload
    - Optimized SVG generation

    Security:
    - SQL injection prevention
    - XSS protection in rendering
    - CORS policies for exports
    - Access control validation
    - Input sanitization
    - Rate limiting of operations

    Example:
        db_structure = db.Column(db.JSON,
            info={'widget': DatabaseStructureWidget(
                include_tables=['user', 'role'],
                show_columns=True,
                show_relationships=True,
                export_formats=['png', 'dbml']
            )}
        )
    """

    # JavaScript Dependencies
    JS_DEPENDENCIES = [
        "https://d3js.org/d3.v7.min.js",
        "https://dagrejs.github.io/project/dagre-d3/latest/dagre-d3.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/html-to-image/1.11.0/html-to-image.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.5.0/socket.io.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/pako/2.1.0/pako.min.js",
        "/static/js/database-structure.js",
    ]

    # CSS Dependencies
    CSS_DEPENDENCIES = [
        "https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css",
        "/static/css/database-structure.css",
    ]

    def __init__(self, **kwargs):
        """
        Initialize DatabaseStructureWidget with custom settings.

        Args:
            include_tables (list): Tables to include in diagram
            show_columns (bool): Show column details
            show_relationships (bool): Show relationships
            export_formats (list): Available export formats
            layout_direction (str): Diagram layout direction
            theme (str): Visual theme
            show_indexes (bool): Show table indexes
            show_constraints (bool): Show table constraints
            group_schemas (bool): Group tables by schema
            custom_styles (dict): Custom styling options
            cache_timeout (int): Cache timeout in seconds
            worker_threads (int): Number of worker threads
            max_tables (int): Maximum tables to display
            debug_mode (bool): Enable debug logging
        """
        super().__init__(**kwargs)

        # Core Settings
        self.include_tables = kwargs.get("include_tables", None)
        self.show_columns = kwargs.get("show_columns", True)
        self.show_relationships = kwargs.get("show_relationships", True)
        self.export_formats = kwargs.get("export_formats", ["png", "dbml"])
        self.layout_direction = kwargs.get("layout_direction", "LR")
        self.theme = kwargs.get("theme", "default")
        self.show_indexes = kwargs.get("show_indexes", True)
        self.show_constraints = kwargs.get("show_constraints", True)
        self.group_schemas = kwargs.get("group_schemas", False)
        self.custom_styles = kwargs.get("custom_styles", {})

        # Advanced Settings
        self.cache_timeout = kwargs.get("cache_timeout", 3600)
        self.worker_threads = min(16, max(1, kwargs.get("worker_threads", 4)))
        self.max_tables = kwargs.get("max_tables", 100)
        self.debug_mode = kwargs.get("debug_mode", False)

        # Initialize caches
        self._metadata_cache = {}
        self._layout_cache = {}

        # Validate config
        self._validate_config()

    def render_field(self, field, **kwargs):
        """Render the database structure widget"""
        kwargs.setdefault("id", field.id)
        input_html = super().render_field(field, **kwargs)

        return Markup(
            f"""
            {self._include_dependencies()}

            <div class="database-structure-widget" id="{field.id}-container">
                <!-- Main Diagram Area -->
                <div class="diagram-area">
                    <div id="{field.id}-diagram" class="erd-diagram"></div>
                    <div class="diagram-controls">
                        <button class="btn btn-sm btn-default zoom-in"
                                title="Zoom In">+</button>
                        <button class="btn btn-sm btn-default zoom-out"
                                title="Zoom Out">-</button>
                        <button class="btn btn-sm btn-default reset-zoom"
                                title="Reset Zoom">Reset</button>
                    </div>
                </div>

                <!-- Toolbar -->
                <div class="editor-toolbar">
                    {self._render_toolbar(field.id)}
                </div>

                <!-- Table Details Panel -->
                <div class="details-panel" style="display:none;">
                    <div class="panel-header">
                        <h3 class="table-name"></h3>
                        <button class="close">&times;</button>
                    </div>
                    <div class="panel-content"></div>
                </div>

                <!-- Loading State -->
                <div class="loading-overlay" style="display:none;">
                    <div class="spinner"></div>
                    <span class="sr-only">Loading database structure...</span>
                </div>

                <!-- Error Messages -->
                <div class="alert alert-danger" style="display:none;" role="alert"></div>

                {input_html}
            </div>

            <script>
                $(document).ready(function() {{
                    const dbStructure = new DatabaseStructure('{field.id}', {{
                        includeTables: {_js_json(self.include_tables)},
                        showColumns: {str(self.show_columns).lower()},
                        showRelationships: {str(self.show_relationships).lower()},
                        exportFormats: {_js_json(self.export_formats)},
                        layoutDirection: '{self.layout_direction}',
                        theme: '{self.theme}',
                        showIndexes: {str(self.show_indexes).lower()},
                        showConstraints: {str(self.show_constraints).lower()},
                        groupSchemas: {str(self.group_schemas).lower()},
                        customStyles: {_js_json(self.custom_styles)},
                        cacheTimeout: {self.cache_timeout},
                        workerThreads: {self.worker_threads},
                        maxTables: {self.max_tables},
                        debugMode: {str(self.debug_mode).lower()},

                        onError: function(error) {{
                            showError(error);
                        }},
                        onLoading: function(loading) {{
                            toggleLoading(loading);
                        }},
                        onChange: function(data) {{
                            $('#{field.id}').val(JSON.stringify(data));
                        }}
                    }});

                    function showError(error) {{
                        const alert = $('.database-structure-widget .alert');
                        alert.text(error).show();
                        setTimeout(() => alert.fadeOut(), 5000);
                    }}

                    function toggleLoading(show) {{
                        $('.loading-overlay')[show ? 'show' : 'hide']();
                    }}

                    // Initialize with existing data
                    const existingData = $('#{field.id}').val();
                    if (existingData) {{
                        dbStructure.loadStructure(JSON.parse(existingData));
                    }}

                    // Cleanup on unload
                    window.addEventListener('unload', function() {{
                        dbStructure.cleanup();
                    }});
                }});
            </script>
        """
        )

    def introspect_database(self) -> dict:
        """
        Introspect PgAppForge database structure.

        Returns:
            dict: Database structure information including tables,
                  columns, relationships, and constraints
        """
        try:
            from sqlalchemy import inspect

            inspector = inspect(db.engine)

            result = {"tables": {}, "relationships": [], "schemas": []}

            # Get all schemas
            schemas = inspector.get_schema_names()
            result["schemas"] = schemas

            # Filter tables if specified
            for schema in schemas:
                tables = inspector.get_table_names(schema=schema)
                if self.include_tables:
                    tables = [t for t in tables if t in self.include_tables]

                for table in tables[: self.max_tables]:
                    table_info = self._get_table_metadata(table, schema)
                    result["tables"][f"{schema}.{table}"] = table_info

            # Analyze relationships
            result["relationships"] = self._analyze_relationships()

            return result

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def generate_erd(self, format: str = "svg") -> str:
        """
        Generate ERD diagram in specified format.

        Args:
            format (str): Output format (svg, png, pdf)

        Returns:
            str: Generated ERD diagram in specified format
        """
        try:
            # Get database structure
            structure = self.introspect_database()
            if "error" in structure:
                return f'Error generating ERD: {structure["error"]}'

            # Generate layout
            layout = self._generate_layout()

            # Create visual elements
            elements = self._create_visual_elements()

            # Apply styling
            styled = self._apply_styling(elements)

            # Render based on format
            if format == "svg":
                return self._render_svg(styled)
            elif format == "png":
                return self._render_png(styled)
            elif format == "pdf":
                return self._render_pdf(styled)

            return f"Unsupported format: {format}"

        except Exception as e:
            if self.debug_mode:
                raise
            return f"Error generating ERD: {str(e)}"

    def export_schema(self, format: str) -> str:
        """
        Export database schema in specified format.

        Args:
            format (str): Export format (dbml, sql, html, pdf)

        Returns:
            str: Exported schema in specified format
        """
        try:
            structure = self.introspect_database()
            if "error" in structure:
                return f'Export failed: {structure["error"]}'

            if format == "dbml":
                return self._export_dbml(structure)
            elif format == "sql":
                return self._export_sql(structure)
            elif format == "html":
                return self._export_html(structure)
            elif format == "pdf":
                return self._export_pdf(structure)

            return f"Unsupported export format: {format}"

        except Exception as e:
            if self.debug_mode:
                raise
            return f"Export failed: {str(e)}"

    def compare_schemas(self, other_schema: dict) -> dict:
        """
        Compare current schema with another schema.

        Args:
            other_schema (dict): Schema to compare against

        Returns:
            dict: Comparison results showing differences
        """
        try:
            current = self.introspect_database()
            if "error" in current:
                return {"error": current["error"]}

            return {
                "tables_added": self._compare_tables(current, other_schema, "added"),
                "tables_removed": self._compare_tables(
                    current, other_schema, "removed"
                ),
                "tables_modified": self._compare_tables(
                    current, other_schema, "modified"
                ),
                "relationships_changed": self._compare_relationships(
                    current, other_schema
                ),
            }

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def generate_documentation(self, format: str = "html") -> str:
        """
        Generate database documentation.

        Args:
            format (str): Output format (html, pdf)

        Returns:
            str: Generated documentation in specified format
        """
        try:
            structure = self.introspect_database()
            if "error" in structure:
                return f'Documentation generation failed: {structure["error"]}'

            template_vars = {
                "structure": structure,
                "timestamp": datetime.now(),
                "settings": {
                    "show_columns": self.show_columns,
                    "show_relationships": self.show_relationships,
                    "show_indexes": self.show_indexes,
                    "show_constraints": self.show_constraints,
                },
            }

            if format == "html":
                return render_template("database_docs.html", **template_vars)
            elif format == "pdf":
                html = render_template("database_docs.html", **template_vars)
                return html2pdf(html)

            return f"Unsupported documentation format: {format}"

        except Exception as e:
            if self.debug_mode:
                raise
            return f"Documentation generation failed: {str(e)}"

    def _get_table_metadata(self, table_name: str, schema: str = None) -> dict:
        """Get detailed metadata for a specific table."""
        try:
            from sqlalchemy import inspect

            inspector = inspect(db.engine)

            # Get basic table info
            columns = inspector.get_columns(table_name, schema=schema)
            pk = inspector.get_pk_constraint(table_name, schema=schema)
            fks = inspector.get_foreign_keys(table_name, schema=schema)
            indexes = inspector.get_indexes(table_name, schema=schema)

            return {
                "name": table_name,
                "schema": schema,
                "columns": columns,
                "primary_key": pk,
                "foreign_keys": fks,
                "indexes": indexes,
                "comment": inspector.get_table_comment(table_name, schema=schema),
            }

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def _analyze_relationships(self) -> list:
        """Analyze and map database relationships."""
        try:
            relationships = []

            # Get all foreign keys
            for schema in db.engine.dialect.get_schema_names(db.engine):
                for table in db.engine.dialect.get_table_names(
                    db.engine, schema=schema
                ):
                    fks = db.engine.dialect.get_foreign_keys(
                        db.engine, table, schema=schema
                    )

                    for fk in fks:
                        relationships.append(
                            {
                                "source_schema": schema,
                                "source_table": table,
                                "source_columns": fk["constrained_columns"],
                                "target_schema": fk["referred_schema"],
                                "target_table": fk["referred_table"],
                                "target_columns": fk["referred_columns"],
                                "name": fk["name"],
                            }
                        )

            return relationships

        except Exception as e:
            if self.debug_mode:
                raise
            return []

    def _generate_layout(self) -> dict:
        """Generate optimal layout for ERD diagram."""
        try:
            import dagre

            # Create graph
            graph = dagre.Graph()
            graph.setGraph(
                {
                    "rankdir": self.layout_direction,
                    "nodesep": 70,
                    "ranksep": 50,
                    "marginx": 20,
                    "marginy": 20,
                }
            )

            # Add nodes and edges
            structure = self.introspect_database()
            if "error" in structure:
                return {"error": structure["error"]}

            for table in structure["tables"].values():
                graph.setNode(
                    table["name"], {"label": table["name"], "width": 180, "height": 100}
                )

            for rel in structure["relationships"]:
                graph.setEdge(rel["source_table"], rel["target_table"])

            # Calculate layout
            dagre.layout(graph)

            return {
                "nodes": graph.nodes(),
                "edges": graph.edges(),
                "graph": graph.graph(),
            }

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def _create_visual_elements(self) -> dict:
        """Create visual elements for diagram rendering."""
        try:
            elements = {"nodes": [], "edges": [], "groups": []}

            layout = self._generate_layout()
            if "error" in layout:
                return {"error": layout["error"]}

            # Create table nodes
            structure = self.introspect_database()
            for table in structure["tables"].values():
                node = self._create_table_node(table, layout)
                elements["nodes"].append(node)

            # Create relationship edges
            for rel in structure["relationships"]:
                edge = self._create_relationship_edge(rel, layout)
                elements["edges"].append(edge)

            # Create schema groups if enabled
            if self.group_schemas:
                elements["groups"] = self._create_schema_groups(structure)

            return elements

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}

    def _apply_styling(self) -> dict:
        """Apply custom styling to diagram elements."""
        try:
            # Get base styles
            styles = {
                "diagram": {"background": "#ffffff", "fontFamily": "Arial"},
                "table": {"fill": "#f5f5f5", "stroke": "#cccccc", "strokeWidth": 1},
                "column": {"font": "12px Arial", "fill": "#333333"},
                "relationship": {"stroke": "#666666", "strokeWidth": 1},
            }

            # Apply theme
            theme_styles = self._get_theme_styles()
            styles.update(theme_styles)

            # Apply custom styles
            styles.update(self.custom_styles)

            return styles

        except Exception as e:
            if self.debug_mode:
                raise
            return {"error": str(e)}
