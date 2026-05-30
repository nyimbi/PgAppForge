"""
Entity Relationship Diagram (ERD) View for Database Management

Provides comprehensive visual database schema management interface
with interactive ERD diagrams, table editing, and relationship management.
Admin-only access with full database administration capabilities.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from flask import request, jsonify, render_template, flash, redirect, url_for
from flask_appbuilder import permission_name
from flask_appbuilder.security.decorators import has_access
from flask_appbuilder.baseviews import BaseView, expose, expose_api
from flask_appbuilder.utils.base import get_random_string
from werkzeug.exceptions import BadRequest, Forbidden, NotFound

from ..database.erd_manager import (
    get_erd_manager,
    DatabaseTable,
    DatabaseColumn,
    DatabaseRelationship,
)
from ..database.activity_tracker import (
    get_activity_tracker,
    track_database_activity,
    ActivityType,
    ActivitySeverity,
)
from ..utils.error_handling import (
    WizardErrorHandler,
    WizardErrorType,
    WizardErrorSeverity,
)

logger = logging.getLogger(__name__)


class DatabaseERDView(BaseView):
    """
    Comprehensive database ERD management view

    Provides visual database schema management with interactive diagrams,
    table structure editing, relationship management, and admin tools.
    """

    route_base = "/database/erd"
    default_view = "index"

    def __init__(self):
        """Initialize ERD view with error handling"""
        super().__init__()
        self.error_handler = WizardErrorHandler()
        self.erd_manager = None

    def _ensure_admin_access(self):
        """Ensure current user has admin privileges"""
        try:
            from flask_login import current_user

            if not current_user or not current_user.is_authenticated:
                raise Forbidden("Authentication required")

            # Check if user has admin role
            if hasattr(current_user, "roles"):
                admin_roles = ["Admin", "admin", "Administrator", "administrator"]
                user_roles = [
                    role.name if hasattr(role, "name") else str(role)
                    for role in current_user.roles
                ]

                if not any(role in admin_roles for role in user_roles):
                    raise Forbidden("Administrator privileges required")
            else:
                # Fallback check for is_admin attribute
                if not getattr(current_user, "is_admin", False):
                    raise Forbidden("Administrator privileges required")

        except Exception as e:
            logger.error(f"Admin access check failed: {e}")
            raise Forbidden("Access denied")

    def _get_erd_manager(self):
        """Get or initialize ERD manager"""
        if self.erd_manager is None:
            try:
                self.erd_manager = get_erd_manager()
            except Exception as e:
                logger.error(f"Failed to initialize ERD manager: {e}")
                self.error_handler.handle_error(
                    e, WizardErrorType.SYSTEM_ERROR, WizardErrorSeverity.HIGH
                )
                raise
        return self.erd_manager

    @expose("/")
    @has_access
    @permission_name("can_manage_database")
    def index(self):
        """Main ERD dashboard with schema overview"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            # Get database schema
            schema = erd_manager.get_database_schema()

            # Prepare dashboard data
            dashboard_data = {
                "database_name": schema.name,
                "total_tables": len(schema.tables),
                "total_relationships": len(schema.relationships),
                "total_views": len(schema.views),
                "total_procedures": len(schema.procedures),
                "tables": [
                    {
                        "name": table.name,
                        "columns": len(table.columns),
                        "row_count": table.row_count or 0,
                        "primary_keys": len(table.primary_keys),
                        "foreign_keys": len(table.foreign_keys),
                        "indexes": len(table.indexes),
                    }
                    for table in schema.tables[:20]  # Limit for overview
                ],
                "recent_activity": self._get_recent_activity(),
                "system_stats": self._get_system_stats(schema),
            }

            return render_template(
                "erd/index.html",
                title="Database ERD Management",
                dashboard=dashboard_data,
                schema=schema,
            )

        except Exception as e:
            logger.error(f"Error in ERD index view: {e}")
            flash(f"Error loading database ERD: {str(e)}", "error")
            return render_template("erd/error.html", error=str(e))

    @expose("/schema/")
    @has_access
    @permission_name("can_manage_database")
    def schema(self):
        """Interactive database schema visualization"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            schema = erd_manager.get_database_schema()

            # Prepare data for ERD visualization
            erd_data = {"tables": [], "relationships": []}

            # Process tables for visualization
            for table in schema.tables:
                table_data = {
                    "id": table.name,
                    "name": table.name,
                    "columns": [
                        {
                            "name": col.name,
                            "type": col.type,
                            "nullable": col.nullable,
                            "primary_key": col.primary_key,
                            "foreign_key": col.foreign_key,
                            "unique": col.unique,
                            "length": col.length,
                        }
                        for col in table.columns
                    ],
                    "position": self._get_table_position(table.name),
                    "row_count": table.row_count or 0,
                }
                erd_data["tables"].append(table_data)

            # Process relationships for visualization
            for rel in schema.relationships:
                rel_data = {
                    "id": rel.id,
                    "source": rel.source_table,
                    "target": rel.target_table,
                    "source_columns": rel.source_columns,
                    "target_columns": rel.target_columns,
                    "type": rel.relationship_type.value,
                    "constraint_name": rel.constraint_name,
                }
                erd_data["relationships"].append(rel_data)

            return render_template(
                "erd/schema.html",
                title="Database Schema Diagram",
                erd_data=erd_data,
                schema=schema,
            )

        except Exception as e:
            logger.error(f"Error in schema view: {e}")
            flash(f"Error loading schema: {str(e)}", "error")
            return render_template("erd/error.html", error=str(e))

    @expose("/table/<table_name>/")
    @has_access
    @permission_name("can_manage_database")
    def table_detail(self, table_name: str):
        """Detailed view of a specific table"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            schema = erd_manager.get_database_schema()

            # Find the table
            table = None
            for t in schema.tables:
                if t.name == table_name:
                    table = t
                    break

            if not table:
                raise NotFound(f"Table '{table_name}' not found")

            # Get sample data
            sample_data = erd_manager.get_table_data_sample(table_name, 50)

            # Get relationships involving this table
            table_relationships = [
                rel
                for rel in schema.relationships
                if rel.source_table == table_name or rel.target_table == table_name
            ]

            return render_template(
                "erd/table_detail.html",
                title=f"Table: {table_name}",
                table=table,
                sample_data=sample_data,
                relationships=table_relationships,
            )

        except Exception as e:
            logger.error(f"Error in table detail view: {e}")
            flash(f"Error loading table details: {str(e)}", "error")
            return render_template("erd/error.html", error=str(e))

    @expose("/table/<table_name>/edit/")
    @has_access
    @permission_name("can_manage_database")
    def edit_table(self, table_name: str):
        """Edit table structure interface"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            schema = erd_manager.get_database_schema()

            # Find the table
            table = None
            for t in schema.tables:
                if t.name == table_name:
                    table = t
                    break

            if not table:
                raise NotFound(f"Table '{table_name}' not found")

            # Get available column types
            column_types = [
                {"value": "INTEGER", "label": "Integer"},
                {"value": "BIGINT", "label": "Big Integer"},
                {"value": "VARCHAR", "label": "Variable Character"},
                {"value": "TEXT", "label": "Text"},
                {"value": "BOOLEAN", "label": "Boolean"},
                {"value": "DATE", "label": "Date"},
                {"value": "DATETIME", "label": "Date Time"},
                {"value": "TIMESTAMP", "label": "Timestamp"},
                {"value": "FLOAT", "label": "Float"},
                {"value": "DECIMAL", "label": "Decimal"},
                {"value": "JSON", "label": "JSON"},
            ]

            # Get available reference tables for foreign keys
            reference_tables = [
                {"name": t.name, "columns": [col.name for col in t.columns]}
                for t in schema.tables
                if t.name != table_name
            ]

            return render_template(
                "erd/edit_table.html",
                title=f"Edit Table: {table_name}",
                table=table,
                column_types=column_types,
                reference_tables=reference_tables,
            )

        except Exception as e:
            logger.error(f"Error in edit table view: {e}")
            flash(f"Error loading table editor: {str(e)}", "error")
            return render_template("erd/error.html", error=str(e))

    @expose("/create-table/")
    @has_access
    @permission_name("can_manage_database")
    def create_table(self):
        """Create new table interface"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            # Get column types
            column_types = [
                {"value": "INTEGER", "label": "Integer"},
                {"value": "BIGINT", "label": "Big Integer"},
                {"value": "VARCHAR", "label": "Variable Character"},
                {"value": "TEXT", "label": "Text"},
                {"value": "BOOLEAN", "label": "Boolean"},
                {"value": "DATE", "label": "Date"},
                {"value": "DATETIME", "label": "Date Time"},
                {"value": "TIMESTAMP", "label": "Timestamp"},
                {"value": "FLOAT", "label": "Float"},
                {"value": "DECIMAL", "label": "Decimal"},
                {"value": "JSON", "label": "JSON"},
            ]

            # Get existing tables for reference
            schema = erd_manager.get_database_schema()
            reference_tables = [
                {"name": t.name, "columns": [col.name for col in t.columns]}
                for t in schema.tables
            ]

            return render_template(
                "erd/create_table.html",
                title="Create New Table",
                column_types=column_types,
                reference_tables=reference_tables,
            )

        except Exception as e:
            logger.error(f"Error in create table view: {e}")
            flash(f"Error loading table creator: {str(e)}", "error")
            return render_template("erd/error.html", error=str(e))

    @expose("/query/")
    @has_access
    @permission_name("can_manage_database")
    def query_interface(self):
        """SQL query interface for advanced operations"""
        try:
            self._ensure_admin_access()

            return render_template(
                "erd/query_interface.html", title="SQL Query Interface"
            )

        except Exception as e:
            logger.error(f"Error in query interface view: {e}")
            flash(f"Error loading query interface: {str(e)}", "error")
            return render_template("erd/error.html", error=str(e))

    # API Endpoints
    @expose_api("get", "/api/schema/")
    @has_access
    @permission_name("can_manage_database")
    def api_get_schema(self):
        """API endpoint to get database schema"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            schema = erd_manager.get_database_schema()

            # Convert to JSON-serializable format
            schema_data = {
                "name": schema.name,
                "tables": [
                    {
                        "name": table.name,
                        "columns": [
                            {
                                "name": col.name,
                                "type": col.type,
                                "nullable": col.nullable,
                                "primary_key": col.primary_key,
                                "foreign_key": col.foreign_key,
                                "unique": col.unique,
                                "default": col.default,
                                "length": col.length,
                            }
                            for col in table.columns
                        ],
                        "row_count": table.row_count,
                        "comment": table.comment,
                    }
                    for table in schema.tables
                ],
                "relationships": [
                    {
                        "id": rel.id,
                        "source_table": rel.source_table,
                        "target_table": rel.target_table,
                        "source_columns": rel.source_columns,
                        "target_columns": rel.target_columns,
                        "type": rel.relationship_type.value,
                        "constraint_name": rel.constraint_name,
                    }
                    for rel in schema.relationships
                ],
            }

            return jsonify({"success": True, "schema": schema_data})

        except Exception as e:
            logger.error(f"API error getting schema: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @expose_api("post", "/api/table/create/")
    @has_access
    @permission_name("can_manage_database")
    def api_create_table(self):
        """API endpoint to create a new table"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")

            # Parse table definition
            table_name = data.get("name")
            if not table_name:
                raise BadRequest("Table name is required")

            columns_data = data.get("columns", [])
            if not columns_data:
                raise BadRequest("At least one column is required")

            # Build table definition
            columns = []
            for col_data in columns_data:
                column = DatabaseColumn(
                    name=col_data.get("name"),
                    type=col_data.get("type"),
                    nullable=col_data.get("nullable", True),
                    primary_key=col_data.get("primary_key", False),
                    unique=col_data.get("unique", False),
                    default=col_data.get("default"),
                    length=col_data.get("length"),
                    comment=col_data.get("comment"),
                )
                columns.append(column)

            table_def = DatabaseTable(
                name=table_name, columns=columns, comment=data.get("comment")
            )

            # Create the table
            success = erd_manager.create_table(table_def)

            if success:
                # Track the activity
                track_database_activity(
                    activity_type=ActivityType.TABLE_CREATED,
                    target=table_name,
                    description=f'Created table "{table_name}" with {len(columns)} columns',
                    details={
                        "table_name": table_name,
                        "column_count": len(columns),
                        "columns": [col.name for col in columns],
                        "primary_keys": [
                            col.name for col in columns if col.primary_key
                        ],
                        "comment": data.get("comment"),
                    },
                    success=True,
                )

                return jsonify(
                    {
                        "success": True,
                        "message": f'Table "{table_name}" created successfully',
                    }
                )
            else:
                # Track failed operation
                track_database_activity(
                    activity_type=ActivityType.TABLE_CREATED,
                    target=table_name,
                    description=f'Failed to create table "{table_name}"',
                    details={"table_name": table_name, "column_count": len(columns)},
                    success=False,
                    error_message="Table creation failed",
                )
                return (
                    jsonify({"success": False, "error": "Failed to create table"}),
                    500,
                )

        except Exception as e:
            logger.error(f"API error creating table: {e}")
            # Track error
            track_database_activity(
                activity_type=ActivityType.TABLE_CREATED,
                target=table_name if "table_name" in locals() else "unknown",
                description=f"Error creating table: {str(e)}",
                success=False,
                error_message=str(e),
            )
            return jsonify({"success": False, "error": str(e)}), 500

    @expose_api("put", "/api/table/<table_name>/")
    @has_access
    @permission_name("can_manage_database")
    def api_alter_table(self, table_name: str):
        """API endpoint to alter a table structure"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")

            modifications = data.get("modifications", [])
            if not modifications:
                raise BadRequest("No modifications specified")

            # Apply modifications
            success = erd_manager.alter_table(table_name, modifications)

            if success:
                # Track the activity
                track_database_activity(
                    activity_type=ActivityType.TABLE_ALTERED,
                    target=table_name,
                    description=f'Modified table "{table_name}" with {len(modifications)} changes',
                    details={"table_name": table_name, "modifications": modifications},
                    success=True,
                )

                return jsonify(
                    {
                        "success": True,
                        "message": f'Table "{table_name}" altered successfully',
                    }
                )
            else:
                return (
                    jsonify({"success": False, "error": "Failed to alter table"}),
                    500,
                )

        except Exception as e:
            logger.error(f"API error altering table: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @expose_api("delete", "/api/table/<table_name>/")
    @has_access
    @permission_name("can_manage_database")
    def api_drop_table(self, table_name: str):
        """API endpoint to drop a table"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            # Get cascade option from query parameters
            cascade = request.args.get("cascade", "false").lower() == "true"

            success = erd_manager.drop_table(table_name, cascade)

            if success:
                # Track the activity
                track_database_activity(
                    activity_type=ActivityType.TABLE_DROPPED,
                    target=table_name,
                    description=f'Dropped table "{table_name}"'
                    + (" with CASCADE" if cascade else ""),
                    details={"table_name": table_name, "cascade": cascade},
                    success=True,
                    severity=ActivitySeverity.HIGH,
                )

                return jsonify(
                    {
                        "success": True,
                        "message": f'Table "{table_name}" dropped successfully',
                    }
                )
            else:
                return jsonify({"success": False, "error": "Failed to drop table"}), 500

        except Exception as e:
            logger.error(f"API error dropping table: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @expose_api("get", "/api/table/<table_name>/data/")
    @has_access
    @permission_name("can_manage_database")
    def api_get_table_data(self, table_name: str):
        """API endpoint to get table data sample"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            limit = int(request.args.get("limit", 100))
            data = erd_manager.get_table_data_sample(table_name, limit)

            return jsonify(
                {
                    "success": True,
                    "table_name": table_name,
                    "data": data,
                    "count": len(data),
                }
            )

        except Exception as e:
            logger.error(f"API error getting table data: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @expose_api("post", "/api/query/execute/")
    @has_access
    @permission_name("can_manage_database")
    def api_execute_query(self):
        """API endpoint to execute custom SQL queries"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")

            query = data.get("query")
            if not query:
                raise BadRequest("SQL query is required")

            # Execute the query
            result = erd_manager.execute_custom_query(query)

            # Track the activity
            track_database_activity(
                activity_type=ActivityType.QUERY_EXECUTED,
                target=f"Query: {query[:50]}..."
                if len(query) > 50
                else f"Query: {query}",
                description=f"Executed SQL query ({len(query)} characters)",
                details={
                    "query": query,
                    "query_length": len(query),
                    "result_success": result.get("success", False),
                },
                success=result.get("success", False),
                error_message=result.get("error")
                if not result.get("success", False)
                else None,
            )

            return jsonify(result)

        except Exception as e:
            logger.error(f"API error executing query: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @expose_api("get", "/api/backup/schema/")
    @has_access
    @permission_name("can_manage_database")
    def api_backup_schema(self):
        """API endpoint to backup database schema"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            backup_sql = erd_manager.backup_database_schema()

            # Track the activity
            track_database_activity(
                activity_type=ActivityType.BACKUP_CREATED,
                target="Database Schema",
                description="Generated database schema backup",
                details={
                    "backup_size": len(backup_sql),
                    "generated_at": datetime.now(tz=timezone.utc).isoformat(),
                },
                success=True,
            )

            return jsonify(
                {
                    "success": True,
                    "backup_sql": backup_sql,
                    "generated_at": datetime.now(tz=timezone.utc).isoformat(),
                }
            )

        except Exception as e:
            logger.error(f"API error backing up schema: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @expose_api("post", "/api/table-position/")
    @has_access
    @permission_name("can_manage_database")
    def api_save_table_position(self):
        """API endpoint to save table positions for ERD layout"""
        try:
            self._ensure_admin_access()

            data = request.get_json()
            if not data:
                raise BadRequest("No JSON data provided")

            positions = data.get("positions", {})
            if not positions:
                raise BadRequest("No positions provided")

            # Save table positions to database
            erd_manager = self._get_erd_manager()
            saved_count = self._save_table_positions(positions)

            return jsonify(
                {
                    "success": True,
                    "message": f"Saved positions for {saved_count} tables",
                }
            )

        except Exception as e:
            logger.error(f"API error saving table positions: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    # Helper methods
    def _get_table_position(self, table_name: str) -> Dict[str, int]:
        """
        Get stored position for a table in ERD diagram

        Args:
            table_name: Name of the table to get position for

        Returns:
            Dictionary with x and y coordinates
        """
        try:
            # Try to get stored position from database
            erd_manager = self._get_erd_manager()
            if erd_manager and erd_manager.engine:
                with erd_manager.engine.connect() as conn:
                    result = conn.execute(
                        text(
                            """
                        SELECT position_x, position_y 
                        FROM erd_table_positions 
                        WHERE table_name = :table_name
                    """
                        ),
                        {"table_name": table_name},
                    )

                    row = result.fetchone()
                    if row:
                        return {"x": row.position_x, "y": row.position_y}
        except Exception:
            # Table positions table might not exist yet, that's OK
            pass

        # Generate deterministic position based on table name for consistent layout
        import hashlib

        hash_val = int(hashlib.md5(table_name.encode()).hexdigest()[:8], 16)
        return {"x": (hash_val % 800) + 50, "y": ((hash_val // 800) % 600) + 50}

    def _save_table_positions(self, positions: Dict[str, Dict[str, int]]) -> int:
        """
        Save table positions to database

        Args:
            positions: Dictionary mapping table names to {x, y} coordinates

        Returns:
            Number of positions saved
        """
        erd_manager = self._get_erd_manager()
        if not erd_manager or not erd_manager.engine:
            return 0

        try:
            with erd_manager.engine.begin() as conn:
                # Create positions table if it doesn't exist
                conn.execute(
                    text(
                        """
                    CREATE TABLE IF NOT EXISTS erd_table_positions (
                        table_name VARCHAR(255) PRIMARY KEY,
                        position_x INTEGER NOT NULL,
                        position_y INTEGER NOT NULL,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_by VARCHAR(255)
                    )
                """
                    )
                )

                saved_count = 0
                current_user_id = "unknown"

                # Get current user if available
                try:
                    from flask_login import current_user

                    if current_user and current_user.is_authenticated:
                        current_user_id = getattr(
                            current_user,
                            "username",
                            getattr(current_user, "email", str(current_user.id)),
                        )
                except Exception:
                    pass

                for table_name, position in positions.items():
                    if (
                        not isinstance(position, dict)
                        or "x" not in position
                        or "y" not in position
                    ):
                        continue

                    # Use UPSERT (INSERT ... ON DUPLICATE KEY UPDATE for MySQL,
                    # INSERT ... ON CONFLICT for PostgreSQL, REPLACE for others)
                    try:
                        # Try PostgreSQL/SQLite style first
                        conn.execute(
                            text(
                                """
                            INSERT INTO erd_table_positions (table_name, position_x, position_y, updated_by)
                            VALUES (:table_name, :x, :y, :user)
                            ON CONFLICT (table_name) DO UPDATE SET
                                position_x = EXCLUDED.position_x,
                                position_y = EXCLUDED.position_y,
                                updated_at = CURRENT_TIMESTAMP,
                                updated_by = EXCLUDED.updated_by
                        """
                            ),
                            {
                                "table_name": table_name,
                                "x": int(position["x"]),
                                "y": int(position["y"]),
                                "user": current_user_id,
                            },
                        )
                    except Exception:
                        try:
                            # Try MySQL style
                            conn.execute(
                                text(
                                    """
                                INSERT INTO erd_table_positions (table_name, position_x, position_y, updated_by)
                                VALUES (:table_name, :x, :y, :user)
                                ON DUPLICATE KEY UPDATE
                                    position_x = VALUES(position_x),
                                    position_y = VALUES(position_y),
                                    updated_at = CURRENT_TIMESTAMP,
                                    updated_by = VALUES(updated_by)
                            """
                                ),
                                {
                                    "table_name": table_name,
                                    "x": int(position["x"]),
                                    "y": int(position["y"]),
                                    "user": current_user_id,
                                },
                            )
                        except Exception:
                            # Fall back to separate DELETE/INSERT
                            conn.execute(
                                text(
                                    "DELETE FROM erd_table_positions WHERE table_name = :table_name"
                                ),
                                {"table_name": table_name},
                            )
                            conn.execute(
                                text(
                                    """
                                INSERT INTO erd_table_positions (table_name, position_x, position_y, updated_by)
                                VALUES (:table_name, :x, :y, :user)
                            """
                                ),
                                {
                                    "table_name": table_name,
                                    "x": int(position["x"]),
                                    "y": int(position["y"]),
                                    "user": current_user_id,
                                },
                            )

                    saved_count += 1

                logger.info(f"Saved positions for {saved_count} tables")
                return saved_count

        except Exception as e:
            logger.error(f"Failed to save table positions: {e}")
            return 0

    def _get_recent_activity(self) -> List[Dict[str, Any]]:
        """
        Get recent database activity for dashboard

        Returns:
            List of recent database activities with user info and timestamps
        """
        try:
            activity_tracker = get_activity_tracker()
            activities = activity_tracker.get_recent_activities(limit=10, hours_back=24)

            formatted_activities = []
            for activity in activities:
                # Convert activity type to user-friendly action
                action_map = {
                    ActivityType.TABLE_CREATED: "Table Created",
                    ActivityType.TABLE_DROPPED: "Table Dropped",
                    ActivityType.TABLE_ALTERED: "Table Modified",
                    ActivityType.TABLE_RENAMED: "Table Renamed",
                    ActivityType.COLUMN_ADDED: "Column Added",
                    ActivityType.COLUMN_DROPPED: "Column Removed",
                    ActivityType.COLUMN_MODIFIED: "Column Modified",
                    ActivityType.INDEX_ADDED: "Index Created",
                    ActivityType.INDEX_DROPPED: "Index Dropped",
                    ActivityType.CONSTRAINT_ADDED: "Constraint Added",
                    ActivityType.CONSTRAINT_DROPPED: "Constraint Removed",
                    ActivityType.QUERY_EXECUTED: "Query Executed",
                    ActivityType.BACKUP_CREATED: "Backup Created",
                    ActivityType.BACKUP_RESTORED: "Backup Restored",
                    ActivityType.DATA_IMPORTED: "Data Imported",
                    ActivityType.DATA_EXPORTED: "Data Exported",
                }

                formatted_activity = {
                    "action": action_map.get(
                        activity.activity_type,
                        activity.activity_type.value.replace("_", " ").title(),
                    ),
                    "target": activity.target,
                    "user": activity.username,
                    "timestamp": activity.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                    "success": activity.success,
                    "severity": activity.severity.value,
                }
                formatted_activities.append(formatted_activity)

            return formatted_activities

        except Exception as e:
            logger.warning(f"Failed to get recent activity: {e}")
            # Fallback to empty list if activity tracking fails
            return []

    def _get_system_stats(self, schema) -> Dict[str, Any]:
        """Get system statistics for dashboard"""
        total_columns = sum(len(table.columns) for table in schema.tables)
        total_rows = sum(table.row_count or 0 for table in schema.tables)

        return {
            "total_columns": total_columns,
            "total_rows": total_rows,
            "avg_columns_per_table": round(total_columns / len(schema.tables), 1)
            if schema.tables
            else 0,
            "tables_with_data": len(
                [t for t in schema.tables if (t.row_count or 0) > 0]
            ),
        }


# API-only view for external integrations
class DatabaseERDAPIView(BaseView):
    """API-only endpoints for ERD management"""

    route_base = "/api/v1/database/erd"

    def __init__(self):
        super().__init__()
        self.error_handler = WizardErrorHandler()
        self.erd_manager = None

    def _ensure_admin_access(self):
        """Ensure current user has admin privileges"""
        try:
            from flask_login import current_user

            if not current_user or not current_user.is_authenticated:
                raise Forbidden("Authentication required")

            # Check admin role
            if hasattr(current_user, "roles"):
                admin_roles = ["Admin", "admin", "Administrator", "administrator"]
                user_roles = [
                    role.name if hasattr(role, "name") else str(role)
                    for role in current_user.roles
                ]

                if not any(role in admin_roles for role in user_roles):
                    raise Forbidden("Administrator privileges required")
            else:
                if not getattr(current_user, "is_admin", False):
                    raise Forbidden("Administrator privileges required")

        except Exception as e:
            logger.error(f"Admin access check failed: {e}")
            raise Forbidden("Access denied")

    def _get_erd_manager(self):
        """Get or initialize ERD manager"""
        if self.erd_manager is None:
            self.erd_manager = get_erd_manager()
        return self.erd_manager

    @expose_api("get", "/schema/tables/")
    @has_access
    @permission_name("can_manage_database")
    def api_list_tables(self):
        """List all database tables"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            schema = erd_manager.get_database_schema()

            tables = [
                {
                    "name": table.name,
                    "columns": len(table.columns),
                    "row_count": table.row_count,
                    "comment": table.comment,
                }
                for table in schema.tables
            ]

            return jsonify({"success": True, "tables": tables, "total": len(tables)})

        except Exception as e:
            logger.error(f"API error listing tables: {e}")
            return jsonify({"success": False, "error": str(e)}), 500

    @expose_api("get", "/schema/relationships/")
    @has_access
    @permission_name("can_manage_database")
    def api_list_relationships(self):
        """List all database relationships"""
        try:
            self._ensure_admin_access()
            erd_manager = self._get_erd_manager()

            schema = erd_manager.get_database_schema()

            relationships = [
                {
                    "id": rel.id,
                    "source_table": rel.source_table,
                    "target_table": rel.target_table,
                    "type": rel.relationship_type.value,
                    "constraint_name": rel.constraint_name,
                }
                for rel in schema.relationships
            ]

            return jsonify(
                {
                    "success": True,
                    "relationships": relationships,
                    "total": len(relationships),
                }
            )

        except Exception as e:
            logger.error(f"API error listing relationships: {e}")
            return jsonify({"success": False, "error": str(e)}), 500
