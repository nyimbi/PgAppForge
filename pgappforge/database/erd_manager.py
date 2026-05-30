"""
Comprehensive Entity Relationship Diagram (ERD) Database Management System

Provides advanced database schema visualization, table structure editing, 
relationship management, and comprehensive database administration tools.
Admin-only access with full CRUD capabilities for database structures.
"""

import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import sqlalchemy as sa
from sqlalchemy import (
    inspect,
    create_engine,
    MetaData,
    Table,
    Column,
    ForeignKey,
    Index,
    UniqueConstraint,
    CheckConstraint,
    text,
    desc,
    asc,
)
from sqlalchemy.sql import sqltypes
from sqlalchemy.schema import CreateTable, DropTable, CreateIndex, DropIndex
from sqlalchemy.engine.reflection import Inspector

logger = logging.getLogger(__name__)


class TableOperationType(Enum):
    """Types of table operations"""

    CREATE = "create"
    ALTER = "alter"
    DROP = "drop"
    RENAME = "rename"


class ColumnType(Enum):
    """Supported column types"""

    INTEGER = "INTEGER"
    BIGINT = "BIGINT"
    SMALLINT = "SMALLINT"
    VARCHAR = "VARCHAR"
    TEXT = "TEXT"
    CHAR = "CHAR"
    BOOLEAN = "BOOLEAN"
    DATE = "DATE"
    DATETIME = "DATETIME"
    TIMESTAMP = "TIMESTAMP"
    TIME = "TIME"
    FLOAT = "FLOAT"
    DECIMAL = "DECIMAL"
    NUMERIC = "NUMERIC"
    BLOB = "BLOB"
    JSON = "JSON"


class RelationshipType(Enum):
    """Types of database relationships"""

    ONE_TO_ONE = "one_to_one"
    ONE_TO_MANY = "one_to_many"
    MANY_TO_ONE = "many_to_one"
    MANY_TO_MANY = "many_to_many"


@dataclass
class DatabaseColumn:
    """
    Represents a database column with complete metadata

    Attributes:
        name: Column name
        type: Column data type (VARCHAR, INTEGER, etc.)
        nullable: Whether column accepts NULL values
        primary_key: Whether column is part of primary key
        foreign_key: Foreign key reference table.column format
        default: Default value for the column
        autoincrement: Whether column auto-increments
        unique: Whether column has unique constraint
        index: Whether column has index
        length: Maximum length for string types
        precision: Precision for numeric types
        scale: Scale for numeric types
        comment: Column comment/documentation
    """

    name: str
    type: str
    nullable: bool = True
    primary_key: bool = False
    foreign_key: Optional[str] = None
    default: Optional[str] = None
    autoincrement: bool = False
    unique: bool = False
    index: bool = False
    length: Optional[int] = None
    precision: Optional[int] = None
    scale: Optional[int] = None
    comment: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert column to dictionary for serialization"""
        return asdict(self)

    def get_sql_type_definition(self) -> str:
        """Get SQL type definition string for this column"""
        type_def = self.type.upper()

        if self.length and type_def in ["VARCHAR", "CHAR"]:
            type_def = f"{type_def}({self.length})"
        elif self.precision and type_def in ["DECIMAL", "NUMERIC"]:
            if self.scale:
                type_def = f"{type_def}({self.precision},{self.scale})"
            else:
                type_def = f"{type_def}({self.precision})"

        return type_def


@dataclass
class DatabaseTable:
    """
    Represents a database table with complete metadata

    Attributes:
        name: Table name
        schema: Database schema name (optional)
        columns: List of table columns
        primary_keys: List of primary key column names
        foreign_keys: List of foreign key definitions
        indexes: List of index definitions
        constraints: List of constraint definitions
        comment: Table comment/documentation
        row_count: Approximate number of rows
    """

    name: str
    schema: Optional[str] = None
    columns: List[DatabaseColumn] = None
    primary_keys: List[str] = None
    foreign_keys: List[Dict[str, Any]] = None
    indexes: List[Dict[str, Any]] = None
    constraints: List[Dict[str, Any]] = None
    comment: Optional[str] = None
    row_count: Optional[int] = None

    def __post_init__(self):
        if self.columns is None:
            self.columns = []
        if self.primary_keys is None:
            self.primary_keys = []
        if self.foreign_keys is None:
            self.foreign_keys = []
        if self.indexes is None:
            self.indexes = []
        if self.constraints is None:
            self.constraints = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert table to dictionary for serialization"""
        return {
            "name": self.name,
            "schema": self.schema,
            "columns": [col.to_dict() for col in self.columns],
            "primary_keys": self.primary_keys,
            "foreign_keys": self.foreign_keys,
            "indexes": self.indexes,
            "constraints": self.constraints,
            "comment": self.comment,
            "row_count": self.row_count,
        }

    def get_column(self, column_name: str) -> Optional[DatabaseColumn]:
        """Get column by name"""
        for column in self.columns:
            if column.name == column_name:
                return column
        return None

    def get_primary_key_columns(self) -> List[DatabaseColumn]:
        """Get all primary key columns"""
        return [col for col in self.columns if col.primary_key]

    def get_foreign_key_columns(self) -> List[DatabaseColumn]:
        """Get all foreign key columns"""
        return [col for col in self.columns if col.foreign_key]


@dataclass
class DatabaseRelationship:
    """
    Represents a relationship between database tables

    Attributes:
        id: Unique relationship identifier
        source_table: Source table name (child/foreign key table)
        target_table: Target table name (parent/referenced table)
        source_columns: Column names in source table
        target_columns: Column names in target table
        relationship_type: Type of relationship (one-to-one, one-to-many, etc.)
        constraint_name: Foreign key constraint name
        on_delete: ON DELETE action (CASCADE, SET NULL, etc.)
        on_update: ON UPDATE action (CASCADE, SET NULL, etc.)
        comment: Relationship documentation
    """

    id: str
    source_table: str
    target_table: str
    source_columns: List[str]
    target_columns: List[str]
    relationship_type: RelationshipType
    constraint_name: Optional[str] = None
    on_delete: Optional[str] = None
    on_update: Optional[str] = None
    comment: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert relationship to dictionary for serialization"""
        return {
            "id": self.id,
            "source_table": self.source_table,
            "target_table": self.target_table,
            "source_columns": self.source_columns,
            "target_columns": self.target_columns,
            "relationship_type": self.relationship_type.value,
            "constraint_name": self.constraint_name,
            "on_delete": self.on_delete,
            "on_update": self.on_update,
            "comment": self.comment,
        }

    def is_self_referencing(self) -> bool:
        """Check if relationship is self-referencing"""
        return self.source_table == self.target_table


@dataclass
class DatabaseSchema:
    """
    Represents the complete database schema with all metadata

    Attributes:
        name: Database name
        tables: List of database tables
        relationships: List of table relationships
        views: List of database views
        procedures: List of stored procedures
        functions: List of database functions
        triggers: List of database triggers
    """

    name: str
    tables: List[DatabaseTable]
    relationships: List[DatabaseRelationship]
    views: List[Dict[str, Any]] = None
    procedures: List[Dict[str, Any]] = None
    functions: List[Dict[str, Any]] = None
    triggers: List[Dict[str, Any]] = None

    def __post_init__(self):
        if self.views is None:
            self.views = []
        if self.procedures is None:
            self.procedures = []
        if self.functions is None:
            self.functions = []
        if self.triggers is None:
            self.triggers = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert schema to dictionary for serialization"""
        return {
            "name": self.name,
            "tables": [table.to_dict() for table in self.tables],
            "relationships": [rel.to_dict() for rel in self.relationships],
            "views": self.views,
            "procedures": self.procedures,
            "functions": self.functions,
            "triggers": self.triggers,
        }

    def get_table(self, table_name: str) -> Optional[DatabaseTable]:
        """Get table by name"""
        for table in self.tables:
            if table.name == table_name:
                return table
        return None

    def get_relationships_for_table(
        self, table_name: str
    ) -> List[DatabaseRelationship]:
        """Get all relationships involving a specific table"""
        return [
            rel
            for rel in self.relationships
            if rel.source_table == table_name or rel.target_table == table_name
        ]

    def get_table_dependencies(self, table_name: str) -> List[str]:
        """Get list of tables that this table depends on (via foreign keys)"""
        dependencies = []
        for rel in self.relationships:
            if rel.source_table == table_name and rel.target_table != table_name:
                dependencies.append(rel.target_table)
        return list(set(dependencies))

    def get_table_dependents(self, table_name: str) -> List[str]:
        """Get list of tables that depend on this table"""
        dependents = []
        for rel in self.relationships:
            if rel.target_table == table_name and rel.source_table != table_name:
                dependents.append(rel.source_table)
        return list(set(dependents))


class DatabaseERDManager:
    """
    Comprehensive database ERD management system

    Provides full database schema introspection, visualization,
    and modification capabilities with admin-level security.
    """

    def __init__(self, database_uri: str = None):
        """
        Initialize the ERD manager with database connection.

        Args:
            database_uri: Database connection URI, defaults to Flask app config
        """
        self.database_uri = database_uri
        self.engine = None
        self.inspector = None
        self.metadata = None
        self._initialize_connection()

    def _initialize_connection(self):
        """Initialize database connection and inspector"""
        try:
            if self.database_uri:
                self.engine = create_engine(self.database_uri)
            else:
                # Try to get from Flask app context
                from flask import current_app

                if current_app and hasattr(current_app, "extensions"):
                    if "sqlalchemy" in current_app.extensions:
                        self.engine = current_app.extensions["sqlalchemy"].db.engine

            if self.engine:
                self.inspector = inspect(self.engine)
                self.metadata = MetaData()
                logger.info("Database ERD manager initialized successfully")
            else:
                logger.warning("No database connection available")

        except Exception as e:
            logger.error(f"Failed to initialize database connection: {e}")

    def get_database_schema(self) -> DatabaseSchema:
        """Get complete database schema with all tables and relationships"""
        if not self.inspector:
            raise RuntimeError("Database inspector not available")

        try:
            # Get all table names
            table_names = self.inspector.get_table_names()

            # Build tables with full metadata
            tables = []
            relationships = []

            for table_name in table_names:
                table_info = self._get_table_info(table_name)
                tables.append(table_info)

                # Extract relationships from this table
                table_relationships = self._extract_table_relationships(table_name)
                relationships.extend(table_relationships)

            # Get views
            views = self._get_database_views()

            # Get stored procedures and functions (if supported)
            procedures = self._get_stored_procedures()
            functions = self._get_functions()
            triggers = self._get_triggers()

            schema = DatabaseSchema(
                name=self._get_database_name(),
                tables=tables,
                relationships=relationships,
                views=views,
                procedures=procedures,
                functions=functions,
                triggers=triggers,
            )

            logger.info(
                f"Retrieved schema with {len(tables)} tables and {len(relationships)} relationships"
            )
            return schema

        except Exception as e:
            logger.error(f"Error retrieving database schema: {e}")
            raise

    def _get_table_info(self, table_name: str) -> DatabaseTable:
        """Get detailed information about a specific table"""
        try:
            # Get column information
            columns_info = self.inspector.get_columns(table_name)
            columns = []

            for col_info in columns_info:
                column = DatabaseColumn(
                    name=col_info["name"],
                    type=str(col_info["type"]),
                    nullable=col_info.get("nullable", True),
                    primary_key=col_info.get("primary_key", False),
                    default=str(col_info["default"])
                    if col_info.get("default") is not None
                    else None,
                    autoincrement=col_info.get("autoincrement", False),
                    comment=col_info.get("comment"),
                )

                # Add type-specific attributes
                if hasattr(col_info["type"], "length"):
                    column.length = col_info["type"].length
                if hasattr(col_info["type"], "precision"):
                    column.precision = col_info["type"].precision
                if hasattr(col_info["type"], "scale"):
                    column.scale = col_info["type"].scale

                columns.append(column)

            # Get primary keys
            pk_info = self.inspector.get_pk_constraint(table_name)
            primary_keys = pk_info.get("constrained_columns", []) if pk_info else []

            # Get foreign keys
            fk_info = self.inspector.get_foreign_keys(table_name)
            foreign_keys = []
            for fk in fk_info:
                foreign_keys.append(
                    {
                        "name": fk.get("name"),
                        "constrained_columns": fk.get("constrained_columns", []),
                        "referred_table": fk.get("referred_table"),
                        "referred_columns": fk.get("referred_columns", []),
                        "options": fk.get("options", {}),
                    }
                )

            # Get indexes
            index_info = self.inspector.get_indexes(table_name)
            indexes = []
            for idx in index_info:
                indexes.append(
                    {
                        "name": idx.get("name"),
                        "column_names": idx.get("column_names", []),
                        "unique": idx.get("unique", False),
                        "dialect_options": idx.get("dialect_options", {}),
                    }
                )

            # Get unique constraints
            unique_info = self.inspector.get_unique_constraints(table_name)
            constraints = []
            for constraint in unique_info:
                constraints.append(
                    {
                        "type": "unique",
                        "name": constraint.get("name"),
                        "column_names": constraint.get("column_names", []),
                    }
                )

            # Get check constraints (if supported)
            try:
                check_info = self.inspector.get_check_constraints(table_name)
                for constraint in check_info:
                    constraints.append(
                        {
                            "type": "check",
                            "name": constraint.get("name"),
                            "sqltext": constraint.get("sqltext"),
                        }
                    )
            except Exception:
                pass  # Check constraints may not be supported

            # Get row count
            row_count = self._get_table_row_count(table_name)

            # Get table comment
            try:
                table_info = self.inspector.get_table_comment(table_name)
                table_comment = table_info.get("text") if table_info else None
            except Exception:
                table_comment = None

            return DatabaseTable(
                name=table_name,
                columns=columns,
                primary_keys=primary_keys,
                foreign_keys=foreign_keys,
                indexes=indexes,
                constraints=constraints,
                comment=table_comment,
                row_count=row_count,
            )

        except Exception as e:
            logger.error(f"Error getting table info for {table_name}: {e}")
            raise

    def _extract_table_relationships(
        self, table_name: str
    ) -> List[DatabaseRelationship]:
        """Extract relationships from a table's foreign keys"""
        relationships = []

        try:
            foreign_keys = self.inspector.get_foreign_keys(table_name)

            for fk in foreign_keys:
                relationship_id = (
                    f"{table_name}_{fk.get('referred_table')}_{fk.get('name', 'fk')}"
                )

                # Determine relationship type (simplified logic)
                relationship_type = RelationshipType.MANY_TO_ONE  # Default assumption

                # Check if it's one-to-one (unique foreign key)
                if len(fk.get("constrained_columns", [])) == 1:
                    col_name = fk["constrained_columns"][0]
                    indexes = self.inspector.get_indexes(table_name)
                    for idx in indexes:
                        if col_name in idx.get("column_names", []) and idx.get(
                            "unique", False
                        ):
                            relationship_type = RelationshipType.ONE_TO_ONE
                            break

                relationship = DatabaseRelationship(
                    id=relationship_id,
                    source_table=table_name,
                    target_table=fk.get("referred_table"),
                    source_columns=fk.get("constrained_columns", []),
                    target_columns=fk.get("referred_columns", []),
                    relationship_type=relationship_type,
                    constraint_name=fk.get("name"),
                    on_delete=fk.get("options", {}).get("ondelete"),
                    on_update=fk.get("options", {}).get("onupdate"),
                )

                relationships.append(relationship)

        except Exception as e:
            logger.error(f"Error extracting relationships for {table_name}: {e}")

        return relationships

    def _get_table_row_count(self, table_name: str) -> Optional[int]:
        """Get approximate row count for a table"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                return result.scalar()
        except Exception as e:
            logger.warning(f"Could not get row count for {table_name}: {e}")
            return None

    def _get_database_views(self) -> List[Dict[str, Any]]:
        """Get database views information"""
        try:
            view_names = self.inspector.get_view_names()
            views = []

            for view_name in view_names:
                try:
                    view_definition = self.inspector.get_view_definition(view_name)
                    views.append(
                        {
                            "name": view_name,
                            "definition": view_definition,
                            "columns": self.inspector.get_columns(view_name),
                        }
                    )
                except Exception as e:
                    logger.warning(
                        f"Could not get view definition for {view_name}: {e}"
                    )
                    views.append({"name": view_name, "definition": None, "columns": []})

            return views

        except Exception as e:
            logger.warning(f"Error getting views: {e}")
            return []

    def _get_stored_procedures(self) -> List[Dict[str, Any]]:
        """Get stored procedures (database-specific implementation)"""
        try:
            # This is database-specific - implement based on your database
            if self.engine.dialect.name == "mysql":
                return self._get_mysql_procedures()
            elif self.engine.dialect.name == "postgresql":
                return self._get_postgresql_procedures()
            elif self.engine.dialect.name == "mssql":
                return self._get_mssql_procedures()
            else:
                return []
        except Exception as e:
            logger.warning(f"Error getting stored procedures: {e}")
            return []

    def _get_functions(self) -> List[Dict[str, Any]]:
        """Get database functions"""
        try:
            # Database-specific implementation
            if self.engine.dialect.name == "postgresql":
                return self._get_postgresql_functions()
            else:
                return []
        except Exception as e:
            logger.warning(f"Error getting functions: {e}")
            return []

    def _get_triggers(self) -> List[Dict[str, Any]]:
        """Get database triggers"""
        try:
            # Database-specific implementation
            if self.engine.dialect.name == "mysql":
                return self._get_mysql_triggers()
            elif self.engine.dialect.name == "postgresql":
                return self._get_postgresql_triggers()
            else:
                return []
        except Exception as e:
            logger.warning(f"Error getting triggers: {e}")
            return []

    def _get_database_name(self) -> str:
        """Get the database name"""
        try:
            if self.engine.url.database:
                return self.engine.url.database
            else:
                return "Unknown Database"
        except Exception:
            return "Unknown Database"

    def _add_foreign_key_to_table(self, conn, table_name: str, fk_def: Dict[str, Any]):
        """
        Add a foreign key constraint to a table during creation

        Args:
            conn: Database connection
            table_name: Name of the table to add constraint to
            fk_def: Foreign key definition dictionary
        """
        try:
            constraint_name = (
                fk_def.get("name") or f"fk_{table_name}_{fk_def.get('referred_table')}"
            )
            local_columns = ", ".join(fk_def.get("constrained_columns", []))
            foreign_table = fk_def.get("referred_table")
            foreign_columns = ", ".join(fk_def.get("referred_columns", []))

            sql = f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} "
            sql += f"FOREIGN KEY ({local_columns}) REFERENCES {foreign_table} ({foreign_columns})"

            options = fk_def.get("options", {})
            if options.get("ondelete"):
                sql += f" ON DELETE {options['ondelete']}"
            if options.get("onupdate"):
                sql += f" ON UPDATE {options['onupdate']}"

            conn.execute(text(sql))
            logger.info(
                f"Added foreign key constraint {constraint_name} to table {table_name}"
            )

        except Exception as e:
            logger.warning(f"Failed to add foreign key constraint to {table_name}: {e}")

    # Database-specific implementations
    def _get_mysql_procedures(self) -> List[Dict[str, Any]]:
        """Get MySQL stored procedures"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT ROUTINE_NAME, ROUTINE_DEFINITION, ROUTINE_TYPE
                    FROM information_schema.ROUTINES
                    WHERE ROUTINE_SCHEMA = DATABASE() AND ROUTINE_TYPE = 'PROCEDURE'
                """
                    )
                )

                procedures = []
                for row in result:
                    procedures.append(
                        {"name": row[0], "definition": row[1], "type": row[2]}
                    )
                return procedures
        except Exception as e:
            logger.warning(f"Error getting MySQL procedures: {e}")
            return []

    def _get_postgresql_procedures(self) -> List[Dict[str, Any]]:
        """Get PostgreSQL stored procedures"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT proname, prosrc, prokind
                    FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public' AND prokind = 'p'
                """
                    )
                )

                procedures = []
                for row in result:
                    procedures.append(
                        {"name": row[0], "definition": row[1], "type": "procedure"}
                    )
                return procedures
        except Exception as e:
            logger.warning(f"Error getting PostgreSQL procedures: {e}")
            return []

    def _get_postgresql_functions(self) -> List[Dict[str, Any]]:
        """Get PostgreSQL functions"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT proname, prosrc, prokind
                    FROM pg_proc p
                    JOIN pg_namespace n ON p.pronamespace = n.oid
                    WHERE n.nspname = 'public' AND prokind = 'f'
                """
                    )
                )

                functions = []
                for row in result:
                    functions.append(
                        {"name": row[0], "definition": row[1], "type": "function"}
                    )
                return functions
        except Exception as e:
            logger.warning(f"Error getting PostgreSQL functions: {e}")
            return []

    def _get_mysql_triggers(self) -> List[Dict[str, Any]]:
        """Get MySQL triggers"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT TRIGGER_NAME, EVENT_MANIPULATION, EVENT_OBJECT_TABLE, 
                           ACTION_STATEMENT, ACTION_TIMING
                    FROM information_schema.TRIGGERS
                    WHERE TRIGGER_SCHEMA = DATABASE()
                """
                    )
                )

                triggers = []
                for row in result:
                    triggers.append(
                        {
                            "name": row[0],
                            "event": row[1],
                            "table": row[2],
                            "definition": row[3],
                            "timing": row[4],
                        }
                    )
                return triggers
        except Exception as e:
            logger.warning(f"Error getting MySQL triggers: {e}")
            return []

    def _get_postgresql_triggers(self) -> List[Dict[str, Any]]:
        """Get PostgreSQL triggers"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT trigger_name, event_manipulation, event_object_table,
                           action_statement, action_timing
                    FROM information_schema.triggers
                    WHERE trigger_schema = 'public'
                """
                    )
                )

                triggers = []
                for row in result:
                    triggers.append(
                        {
                            "name": row[0],
                            "event": row[1],
                            "table": row[2],
                            "definition": row[3],
                            "timing": row[4],
                        }
                    )
                return triggers
        except Exception as e:
            logger.warning(f"Error getting PostgreSQL triggers: {e}")
            return []

    def _get_mssql_procedures(self) -> List[Dict[str, Any]]:
        """Get SQL Server stored procedures"""
        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT p.name, m.definition
                    FROM sys.procedures p
                    LEFT JOIN sys.sql_modules m ON p.object_id = m.object_id
                """
                    )
                )

                procedures = []
                for row in result:
                    procedures.append(
                        {"name": row[0], "definition": row[1], "type": "procedure"}
                    )
                return procedures
        except Exception as e:
            logger.warning(f"Error getting SQL Server procedures: {e}")
            return []

    # Table modification operations
    def create_table(self, table_definition: DatabaseTable) -> bool:
        """Create a new table in the database"""
        if not self.engine:
            raise RuntimeError("Database engine not available")

        try:
            # Build SQLAlchemy table definition
            columns = []

            for col_def in table_definition.columns:
                # Map column type
                col_type = self._map_column_type(
                    col_def.type, col_def.length, col_def.precision, col_def.scale
                )

                # Create column
                column_kwargs = {
                    "nullable": col_def.nullable,
                    "primary_key": col_def.primary_key,
                    "autoincrement": col_def.autoincrement,
                    "unique": col_def.unique,
                    "index": col_def.index,
                }

                if col_def.default:
                    column_kwargs["default"] = col_def.default

                if col_def.comment:
                    column_kwargs["comment"] = col_def.comment

                column = Column(col_def.name, col_type, **column_kwargs)
                columns.append(column)

            # Create table
            table = Table(table_definition.name, self.metadata, *columns)

            # Add foreign key constraints after table creation
            for fk_def in table_definition.foreign_keys:
                self._add_foreign_key_to_table(conn, table_definition.name, fk_def)

            # Generate and execute CREATE TABLE statement
            create_sql = CreateTable(table)

            with self.engine.begin() as conn:
                conn.execute(create_sql)

                # Create additional indexes
                for idx_def in table_definition.indexes:
                    if not idx_def.get("primary", False):  # Skip primary key indexes
                        index_name = idx_def.get(
                            "name",
                            f"idx_{table_definition.name}_{'_'.join(idx_def['column_names'])}",
                        )
                        index = Index(
                            index_name,
                            *idx_def["column_names"],
                            unique=idx_def.get("unique", False),
                        )
                        conn.execute(CreateIndex(index))

            logger.info(f"Successfully created table: {table_definition.name}")
            return True

        except Exception as e:
            logger.error(f"Error creating table {table_definition.name}: {e}")
            raise

    def alter_table(self, table_name: str, modifications: List[Dict[str, Any]]) -> bool:
        """Alter an existing table structure"""
        if not self.engine:
            raise RuntimeError("Database engine not available")

        try:
            with self.engine.begin() as conn:
                for modification in modifications:
                    mod_type = modification.get("type")

                    if mod_type == "add_column":
                        self._add_column(conn, table_name, modification["column"])
                    elif mod_type == "drop_column":
                        self._drop_column(conn, table_name, modification["column_name"])
                    elif mod_type == "modify_column":
                        self._modify_column(conn, table_name, modification["column"])
                    elif mod_type == "add_index":
                        self._add_index(conn, table_name, modification["index"])
                    elif mod_type == "drop_index":
                        self._drop_index(conn, table_name, modification["index_name"])
                    elif mod_type == "add_constraint":
                        self._add_constraint(
                            conn, table_name, modification["constraint"]
                        )
                    elif mod_type == "drop_constraint":
                        self._drop_constraint(
                            conn, table_name, modification["constraint_name"]
                        )

            logger.info(f"Successfully altered table: {table_name}")
            return True

        except Exception as e:
            logger.error(f"Error altering table {table_name}: {e}")
            raise

    def drop_table(self, table_name: str, cascade: bool = False) -> bool:
        """Drop a table from the database"""
        if not self.engine:
            raise RuntimeError("Database engine not available")

        try:
            # Create table reference for dropping
            table = Table(table_name, self.metadata, autoload_with=self.engine)

            with self.engine.begin() as conn:
                if cascade:
                    # Handle cascading deletes (database-specific)
                    if self.engine.dialect.name == "postgresql":
                        conn.execute(text(f"DROP TABLE {table_name} CASCADE"))
                    else:
                        conn.execute(DropTable(table))
                else:
                    conn.execute(DropTable(table))

            logger.info(f"Successfully dropped table: {table_name}")
            return True

        except Exception as e:
            logger.error(f"Error dropping table {table_name}: {e}")
            raise

    def rename_table(self, old_name: str, new_name: str) -> bool:
        """Rename a table"""
        if not self.engine:
            raise RuntimeError("Database engine not available")

        try:
            with self.engine.begin() as conn:
                # Database-specific rename syntax
                if self.engine.dialect.name == "mysql":
                    conn.execute(text(f"RENAME TABLE {old_name} TO {new_name}"))
                elif self.engine.dialect.name == "postgresql":
                    conn.execute(text(f"ALTER TABLE {old_name} RENAME TO {new_name}"))
                elif self.engine.dialect.name == "sqlite":
                    conn.execute(text(f"ALTER TABLE {old_name} RENAME TO {new_name}"))
                else:
                    conn.execute(text(f"ALTER TABLE {old_name} RENAME TO {new_name}"))

            logger.info(f"Successfully renamed table from {old_name} to {new_name}")
            return True

        except Exception as e:
            logger.error(f"Error renaming table from {old_name} to {new_name}: {e}")
            raise

    def _map_column_type(
        self,
        type_str: str,
        length: Optional[int] = None,
        precision: Optional[int] = None,
        scale: Optional[int] = None,
    ):
        """Map string column type to SQLAlchemy type"""
        type_str = type_str.upper()

        type_mapping = {
            "INTEGER": sa.Integer,
            "BIGINT": sa.BigInteger,
            "SMALLINT": sa.SmallInteger,
            "VARCHAR": lambda: sa.String(length) if length else sa.String(255),
            "TEXT": sa.Text,
            "CHAR": lambda: sa.CHAR(length) if length else sa.CHAR(1),
            "BOOLEAN": sa.Boolean,
            "DATE": sa.Date,
            "DATETIME": sa.DateTime,
            "TIMESTAMP": sa.TIMESTAMP,
            "TIME": sa.Time,
            "FLOAT": sa.Float,
            "DECIMAL": lambda: sa.NUMERIC(precision, scale)
            if precision
            else sa.NUMERIC,
            "NUMERIC": lambda: sa.NUMERIC(precision, scale)
            if precision
            else sa.NUMERIC,
            "BLOB": sa.LargeBinary,
            "JSON": sa.JSON if hasattr(sa, "JSON") else sa.Text,
        }

        if type_str in type_mapping:
            type_class = type_mapping[type_str]
            return type_class() if callable(type_class) else type_class
        else:
            logger.warning(f"Unknown column type: {type_str}, defaulting to String")
            return sa.String(255)

    def _add_column(self, conn, table_name: str, column_def: DatabaseColumn):
        """Add a column to an existing table"""
        col_type = self._map_column_type(
            column_def.type, column_def.length, column_def.precision, column_def.scale
        )

        # Build ALTER TABLE ADD COLUMN statement
        sql_parts = [f"ALTER TABLE {table_name} ADD COLUMN {column_def.name}"]
        sql_parts.append(str(col_type))

        if not column_def.nullable:
            sql_parts.append("NOT NULL")

        if column_def.default:
            sql_parts.append(f"DEFAULT {column_def.default}")

        sql = " ".join(sql_parts)
        conn.execute(text(sql))

    def _drop_column(self, conn, table_name: str, column_name: str):
        """Drop a column from a table"""
        sql = f"ALTER TABLE {table_name} DROP COLUMN {column_name}"
        conn.execute(text(sql))

    def _modify_column(self, conn, table_name: str, column_def: DatabaseColumn):
        """Modify an existing column"""
        # This is database-specific and complex
        # Implementation would vary by database type
        if self.engine.dialect.name == "mysql":
            self._modify_column_mysql(conn, table_name, column_def)
        elif self.engine.dialect.name == "postgresql":
            self._modify_column_postgresql(conn, table_name, column_def)
        else:
            logger.warning(
                f"Column modification not implemented for {self.engine.dialect.name}"
            )

    def _modify_column_mysql(self, conn, table_name: str, column_def: DatabaseColumn):
        """Modify column in MySQL"""
        col_type = self._map_column_type(
            column_def.type, column_def.length, column_def.precision, column_def.scale
        )

        sql_parts = [f"ALTER TABLE {table_name} MODIFY COLUMN {column_def.name}"]
        sql_parts.append(str(col_type))

        if not column_def.nullable:
            sql_parts.append("NOT NULL")
        else:
            sql_parts.append("NULL")

        if column_def.default:
            sql_parts.append(f"DEFAULT {column_def.default}")

        sql = " ".join(sql_parts)
        conn.execute(text(sql))

    def _modify_column_postgresql(
        self, conn, table_name: str, column_def: DatabaseColumn
    ):
        """Modify column in PostgreSQL"""
        # PostgreSQL requires separate ALTER statements for different changes
        col_type = self._map_column_type(
            column_def.type, column_def.length, column_def.precision, column_def.scale
        )

        # Change type
        sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_def.name} TYPE {col_type}"
        conn.execute(text(sql))

        # Change nullable
        if column_def.nullable:
            sql = (
                f"ALTER TABLE {table_name} ALTER COLUMN {column_def.name} DROP NOT NULL"
            )
        else:
            sql = (
                f"ALTER TABLE {table_name} ALTER COLUMN {column_def.name} SET NOT NULL"
            )
        conn.execute(text(sql))

        # Change default
        if column_def.default:
            sql = f"ALTER TABLE {table_name} ALTER COLUMN {column_def.name} SET DEFAULT {column_def.default}"
            conn.execute(text(sql))

    def _add_index(self, conn, table_name: str, index_def: Dict[str, Any]):
        """Add an index to a table"""
        index_name = index_def.get(
            "name", f"idx_{table_name}_{'_'.join(index_def['columns'])}"
        )
        columns = ", ".join(index_def["columns"])

        if index_def.get("unique", False):
            sql = f"CREATE UNIQUE INDEX {index_name} ON {table_name} ({columns})"
        else:
            sql = f"CREATE INDEX {index_name} ON {table_name} ({columns})"

        conn.execute(text(sql))

    def _drop_index(self, conn, table_name: str, index_name: str):
        """Drop an index from a table"""
        if self.engine.dialect.name == "mysql":
            sql = f"DROP INDEX {index_name} ON {table_name}"
        else:
            sql = f"DROP INDEX {index_name}"

        conn.execute(text(sql))

    def _add_constraint(self, conn, table_name: str, constraint_def: Dict[str, Any]):
        """Add a constraint to a table"""
        constraint_type = constraint_def.get("type")
        constraint_name = constraint_def.get("name")

        if constraint_type == "foreign_key":
            columns = ", ".join(constraint_def["columns"])
            ref_table = constraint_def["referenced_table"]
            ref_columns = ", ".join(constraint_def["referenced_columns"])

            sql = f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} "
            sql += f"FOREIGN KEY ({columns}) REFERENCES {ref_table} ({ref_columns})"

            if constraint_def.get("on_delete"):
                sql += f" ON DELETE {constraint_def['on_delete']}"
            if constraint_def.get("on_update"):
                sql += f" ON UPDATE {constraint_def['on_update']}"

        elif constraint_type == "unique":
            columns = ", ".join(constraint_def["columns"])
            sql = f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} UNIQUE ({columns})"

        elif constraint_type == "check":
            condition = constraint_def["condition"]
            sql = f"ALTER TABLE {table_name} ADD CONSTRAINT {constraint_name} CHECK ({condition})"

        else:
            raise ValueError(f"Unknown constraint type: {constraint_type}")

        conn.execute(text(sql))

    def _drop_constraint(self, conn, table_name: str, constraint_name: str):
        """Drop a constraint from a table"""
        sql = f"ALTER TABLE {table_name} DROP CONSTRAINT {constraint_name}"
        conn.execute(text(sql))

    def get_table_data_sample(
        self, table_name: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get a sample of data from a table for preview"""
        if not self.engine:
            raise RuntimeError("Database engine not available")

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(f"SELECT * FROM {table_name} LIMIT {limit}"))
                columns = result.keys()
                rows = result.fetchall()

                data = []
                for row in rows:
                    data.append(dict(zip(columns, row)))

                return data

        except Exception as e:
            logger.error(f"Error getting table data sample for {table_name}: {e}")
            raise

    def execute_custom_query(self, query: str) -> Dict[str, Any]:
        """Execute a custom SQL query (admin only)"""
        if not self.engine:
            raise RuntimeError("Database engine not available")

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(query))

                if result.returns_rows:
                    columns = result.keys()
                    rows = result.fetchall()

                    data = []
                    for row in rows:
                        data.append(dict(zip(columns, row)))

                    return {
                        "success": True,
                        "data": data,
                        "columns": list(columns),
                        "row_count": len(data),
                    }
                else:
                    return {
                        "success": True,
                        "message": f"Query executed successfully. Rows affected: {result.rowcount}",
                        "rows_affected": result.rowcount,
                    }

        except Exception as e:
            logger.error(f"Error executing custom query: {e}")
            return {"success": False, "error": str(e)}

    def backup_database_schema(self) -> str:
        """Create a backup of the database schema as SQL"""
        if not self.engine:
            raise RuntimeError("Database engine not available")

        try:
            schema = self.get_database_schema()

            # Generate DDL statements
            ddl_statements = []

            # Add table creation statements
            for table in schema.tables:
                ddl = self._generate_create_table_ddl(table)
                ddl_statements.append(ddl)

            # Add relationship/foreign key statements
            for relationship in schema.relationships:
                if relationship.constraint_name:
                    ddl = self._generate_foreign_key_ddl(relationship)
                    ddl_statements.append(ddl)

            # Add view creation statements
            for view in schema.views:
                if view.get("definition"):
                    ddl = f"CREATE VIEW {view['name']} AS {view['definition']};"
                    ddl_statements.append(ddl)

            backup_sql = "\n\n".join(ddl_statements)

            logger.info("Database schema backup generated successfully")
            return backup_sql

        except Exception as e:
            logger.error(f"Error creating database schema backup: {e}")
            raise

    def _generate_create_table_ddl(self, table: DatabaseTable) -> str:
        """Generate CREATE TABLE DDL statement"""
        lines = [f"CREATE TABLE {table.name} ("]

        # Add columns
        column_lines = []
        for column in table.columns:
            col_line = f"  {column.name} {column.type}"

            if column.length:
                col_line = f"  {column.name} {column.type}({column.length})"
            elif column.precision and column.scale:
                col_line = (
                    f"  {column.name} {column.type}({column.precision},{column.scale})"
                )
            elif column.precision:
                col_line = f"  {column.name} {column.type}({column.precision})"

            if not column.nullable:
                col_line += " NOT NULL"

            if column.primary_key:
                col_line += " PRIMARY KEY"

            if column.autoincrement:
                col_line += " AUTO_INCREMENT"

            if column.unique:
                col_line += " UNIQUE"

            if column.default:
                col_line += f" DEFAULT {column.default}"

            column_lines.append(col_line)

        lines.append(",\n".join(column_lines))
        lines.append(");")

        return "\n".join(lines)

    def _generate_foreign_key_ddl(self, relationship: DatabaseRelationship) -> str:
        """Generate ALTER TABLE ADD FOREIGN KEY DDL statement"""
        source_cols = ", ".join(relationship.source_columns)
        target_cols = ", ".join(relationship.target_columns)

        ddl = f"ALTER TABLE {relationship.source_table} "
        ddl += f"ADD CONSTRAINT {relationship.constraint_name} "
        ddl += f"FOREIGN KEY ({source_cols}) "
        ddl += f"REFERENCES {relationship.target_table} ({target_cols})"

        if relationship.on_delete:
            ddl += f" ON DELETE {relationship.on_delete}"
        if relationship.on_update:
            ddl += f" ON UPDATE {relationship.on_update}"

        ddl += ";"
        return ddl


# Global ERD manager instance
database_erd_manager = None


def get_erd_manager(database_uri: str = None) -> DatabaseERDManager:
    """Get or create the global ERD manager instance"""
    global database_erd_manager
    if database_erd_manager is None:
        database_erd_manager = DatabaseERDManager(database_uri)
    return database_erd_manager
