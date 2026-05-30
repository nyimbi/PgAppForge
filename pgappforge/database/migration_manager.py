"""
Database Migration and Backup Management System

Provides comprehensive database migration, backup, restoration, and
schema versioning capabilities with admin-level security controls.
"""

import json
import logging
import os
import gzip
import shutil
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
import hashlib
import uuid

from sqlalchemy import create_engine, text, inspect, MetaData, Table
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .erd_manager import DatabaseERDManager, DatabaseSchema, DatabaseTable

logger = logging.getLogger(__name__)


class MigrationType(Enum):
    """Types of database migrations"""

    SCHEMA_CHANGE = "schema_change"
    DATA_MIGRATION = "data_migration"
    INDEX_OPTIMIZATION = "index_optimization"
    CONSTRAINT_UPDATE = "constraint_update"
    ROLLBACK = "rollback"


class MigrationStatus(Enum):
    """Migration execution status"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class BackupType(Enum):
    """Types of database backups"""

    FULL = "full"
    SCHEMA_ONLY = "schema_only"
    DATA_ONLY = "data_only"
    INCREMENTAL = "incremental"


@dataclass
class DatabaseBackup:
    """Represents a database backup"""

    backup_id: str
    name: str
    backup_type: BackupType
    created_at: datetime
    created_by: str
    file_path: str
    file_size: int
    compressed: bool
    checksum: str
    database_name: str
    tables_included: List[str]
    schema_version: Optional[str] = None
    description: Optional[str] = None
    retention_days: int = 30
    is_automated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "backup_id": self.backup_id,
            "name": self.name,
            "backup_type": self.backup_type.value,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "compressed": self.compressed,
            "checksum": self.checksum,
            "database_name": self.database_name,
            "tables_included": self.tables_included,
            "schema_version": self.schema_version,
            "description": self.description,
            "retention_days": self.retention_days,
            "is_automated": self.is_automated,
        }


@dataclass
class DatabaseMigration:
    """Represents a database migration"""

    migration_id: str
    name: str
    description: str
    migration_type: MigrationType
    created_at: datetime
    created_by: str
    status: MigrationStatus
    up_script: str  # SQL to apply migration
    down_script: str  # SQL to rollback migration
    checksum: str
    dependencies: List[str] = None
    executed_at: Optional[datetime] = None
    execution_time_ms: Optional[int] = None
    error_message: Optional[str] = None
    backup_id: Optional[str] = None  # Backup created before migration

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "migration_id": self.migration_id,
            "name": self.name,
            "description": self.description,
            "migration_type": self.migration_type.value,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "status": self.status.value,
            "up_script": self.up_script,
            "down_script": self.down_script,
            "checksum": self.checksum,
            "dependencies": self.dependencies,
            "executed_at": self.executed_at.isoformat() if self.executed_at else None,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
            "backup_id": self.backup_id,
        }


@dataclass
class SchemaVersion:
    """Represents a database schema version"""

    version_id: str
    version_number: str
    created_at: datetime
    created_by: str
    description: str
    schema_checksum: str
    migrations_applied: List[str]
    is_current: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization"""
        return {
            "version_id": self.version_id,
            "version_number": self.version_number,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
            "description": self.description,
            "schema_checksum": self.schema_checksum,
            "migrations_applied": self.migrations_applied,
            "is_current": self.is_current,
        }


class DatabaseMigrationManager:
    """
    Comprehensive database migration and backup management system

    Provides enterprise-grade database migration, backup, restoration,
    and schema versioning capabilities with comprehensive logging and
    rollback support.
    """

    def __init__(self, database_uri: str = None, backup_directory: str = None):
        """
        Initialize the migration manager with database connection and backup storage.

        Args:
            database_uri: Database connection URI
            backup_directory: Directory for storing backups and migration files
        """
        self.database_uri = database_uri
        self.backup_directory = backup_directory or "./database_backups"
        self.engine = None
        self.erd_manager = None

        # Ensure backup directory exists
        Path(self.backup_directory).mkdir(parents=True, exist_ok=True)

        # Internal storage (in production, this would be in database tables)
        self.backups: List[DatabaseBackup] = []
        self.migrations: List[DatabaseMigration] = []
        self.schema_versions: List[SchemaVersion] = []

        self._initialize_connection()
        self._initialize_migration_tables()

    def _initialize_connection(self):
        """Initialize database connection"""
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
                from .erd_manager import DatabaseERDManager

                self.erd_manager = DatabaseERDManager(self.database_uri)
                logger.info("Migration manager initialized successfully")
            else:
                logger.warning("No database connection available")

        except Exception as e:
            logger.error(f"Failed to initialize migration manager: {e}")

    def _initialize_migration_tables(self):
        """Create migration tracking tables if they don't exist"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                # Create migrations table
                conn.execute(
                    text(
                        """
                    CREATE TABLE IF NOT EXISTS db_migrations (
                        migration_id VARCHAR(36) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        description TEXT,
                        migration_type VARCHAR(50) NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        created_by VARCHAR(255) NOT NULL,
                        status VARCHAR(50) NOT NULL DEFAULT 'pending',
                        up_script TEXT NOT NULL,
                        down_script TEXT NOT NULL,
                        checksum VARCHAR(64) NOT NULL,
                        dependencies TEXT,
                        executed_at TIMESTAMP NULL,
                        execution_time_ms INTEGER NULL,
                        error_message TEXT NULL,
                        backup_id VARCHAR(36) NULL
                    )
                """
                    )
                )

                # Create schema versions table
                conn.execute(
                    text(
                        """
                    CREATE TABLE IF NOT EXISTS db_schema_versions (
                        version_id VARCHAR(36) PRIMARY KEY,
                        version_number VARCHAR(50) NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        created_by VARCHAR(255) NOT NULL,
                        description TEXT,
                        schema_checksum VARCHAR(64) NOT NULL,
                        migrations_applied TEXT,
                        is_current BOOLEAN DEFAULT FALSE
                    )
                """
                    )
                )

                # Create backups registry table
                conn.execute(
                    text(
                        """
                    CREATE TABLE IF NOT EXISTS db_backups (
                        backup_id VARCHAR(36) PRIMARY KEY,
                        name VARCHAR(255) NOT NULL,
                        backup_type VARCHAR(50) NOT NULL,
                        created_at TIMESTAMP NOT NULL,
                        created_by VARCHAR(255) NOT NULL,
                        file_path VARCHAR(500) NOT NULL,
                        file_size BIGINT NOT NULL,
                        compressed BOOLEAN DEFAULT FALSE,
                        checksum VARCHAR(64) NOT NULL,
                        database_name VARCHAR(255) NOT NULL,
                        tables_included TEXT,
                        schema_version VARCHAR(50) NULL,
                        description TEXT,
                        retention_days INTEGER DEFAULT 30,
                        is_automated BOOLEAN DEFAULT FALSE
                    )
                """
                    )
                )

                logger.info("Migration tracking tables initialized")

        except Exception as e:
            logger.error(f"Failed to initialize migration tables: {e}")

    # Backup Operations
    def create_backup(
        self,
        backup_name: str,
        backup_type: BackupType,
        created_by: str,
        tables: Optional[List[str]] = None,
        description: Optional[str] = None,
        compress: bool = True,
        retention_days: int = 30,
    ) -> str:
        """
        Create a database backup

        Args:
            backup_name: Name for the backup
            backup_type: Type of backup (full, schema_only, etc.)
            created_by: User creating the backup
            tables: Specific tables to backup (None for all)
            description: Optional backup description
            compress: Whether to compress the backup
            retention_days: Days to retain the backup

        Returns:
            Backup ID
        """
        if not self.engine or not self.erd_manager:
            raise RuntimeError("Database connection not available")

        backup_id = str(uuid.uuid4())
        timestamp = datetime.now(tz=timezone.utc)

        try:
            # Generate filename
            filename = f"{backup_name}_{timestamp.strftime('%Y%m%d_%H%M%S')}"
            if compress:
                filename += ".sql.gz"
            else:
                filename += ".sql"

            file_path = os.path.join(self.backup_directory, filename)

            # Get schema for backup
            schema = self.erd_manager.get_database_schema()

            # Determine tables to include
            if tables is None:
                tables_to_backup = [table.name for table in schema.tables]
            else:
                tables_to_backup = tables

            # Generate backup content
            backup_content = self._generate_backup_content(
                schema, backup_type, tables_to_backup
            )

            # Write backup file
            if compress:
                with gzip.open(file_path, "wt", encoding="utf-8") as f:
                    f.write(backup_content)
            else:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(backup_content)

            # Calculate file size and checksum
            file_size = os.path.getsize(file_path)
            checksum = self._calculate_file_checksum(file_path)

            # Create backup record
            backup = DatabaseBackup(
                backup_id=backup_id,
                name=backup_name,
                backup_type=backup_type,
                created_at=timestamp,
                created_by=created_by,
                file_path=file_path,
                file_size=file_size,
                compressed=compress,
                checksum=checksum,
                database_name=schema.name,
                tables_included=tables_to_backup,
                description=description,
                retention_days=retention_days,
            )

            # Store backup record
            self._store_backup_record(backup)
            self.backups.append(backup)

            logger.info(f"Backup created successfully: {backup_id}")
            return backup_id

        except Exception as e:
            logger.error(f"Failed to create backup: {e}")
            # Cleanup partial backup file
            if "file_path" in locals() and os.path.exists(file_path):
                os.remove(file_path)
            raise

    def _generate_backup_content(
        self, schema: DatabaseSchema, backup_type: BackupType, tables: List[str]
    ) -> str:
        """Generate backup content based on type"""
        content_parts = []

        # Add header
        content_parts.append(
            f"""
-- Database Backup
-- Generated: {datetime.now(tz=timezone.utc).isoformat()}
-- Database: {schema.name}
-- Backup Type: {backup_type.value}
-- Tables: {', '.join(tables)}

SET FOREIGN_KEY_CHECKS = 0;
"""
        )

        if backup_type in [BackupType.FULL, BackupType.SCHEMA_ONLY]:
            # Add table structure
            for table in schema.tables:
                if table.name in tables:
                    table_ddl = self._generate_table_ddl(table)
                    content_parts.append(f"\n-- Table: {table.name}\n")
                    content_parts.append(f"DROP TABLE IF EXISTS {table.name};\n")
                    content_parts.append(table_ddl)

        if backup_type in [BackupType.FULL, BackupType.DATA_ONLY]:
            # Add table data
            for table_name in tables:
                try:
                    data_sql = self._generate_table_data_sql(table_name)
                    if data_sql:
                        content_parts.append(f"\n-- Data for table: {table_name}\n")
                        content_parts.append(data_sql)
                except Exception as e:
                    logger.warning(f"Could not backup data for table {table_name}: {e}")

        # Add foreign key constraints (after all tables are created)
        if backup_type in [BackupType.FULL, BackupType.SCHEMA_ONLY]:
            constraint_sql = self._generate_foreign_key_constraints(schema, tables)
            if constraint_sql:
                content_parts.append("\n-- Foreign Key Constraints\n")
                content_parts.append(constraint_sql)

        content_parts.append("\nSET FOREIGN_KEY_CHECKS = 1;\n")

        return "\n".join(content_parts)

    def _generate_table_ddl(self, table: DatabaseTable) -> str:
        """Generate CREATE TABLE DDL for a table"""
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
                if column.type.upper() in ["VARCHAR", "TEXT", "CHAR"]:
                    col_line += f" DEFAULT '{column.default}'"
                else:
                    col_line += f" DEFAULT {column.default}"

            if column.comment:
                col_line += f" COMMENT '{column.comment}'"

            column_lines.append(col_line)

        lines.append(",\n".join(column_lines))
        lines.append(")")

        if table.comment:
            lines.append(f" COMMENT='{table.comment}'")

        lines.append(";")

        return "\n".join(lines)

    def _generate_table_data_sql(self, table_name: str) -> str:
        """Generate INSERT statements for table data"""
        if not self.engine:
            return ""

        try:
            with self.engine.connect() as conn:
                # Get table structure
                result = conn.execute(text(f"DESCRIBE {table_name}"))
                columns = [row[0] for row in result]

                if not columns:
                    return ""

                # Get data
                result = conn.execute(text(f"SELECT * FROM {table_name}"))
                rows = result.fetchall()

                if not rows:
                    return ""

                sql_parts = []
                sql_parts.append(f"-- Data for table {table_name}")

                # Disable foreign key checks for data insertion
                columns_str = ", ".join(columns)

                for row in rows:
                    values = []
                    for value in row:
                        if value is None:
                            values.append("NULL")
                        elif isinstance(value, str):
                            # Escape single quotes
                            escaped_value = value.replace("'", "''")
                            values.append(f"'{escaped_value}'")
                        elif isinstance(value, (int, float)):
                            values.append(str(value))
                        else:
                            values.append(f"'{str(value)}'")

                    values_str = ", ".join(values)
                    sql_parts.append(
                        f"INSERT INTO {table_name} ({columns_str}) VALUES ({values_str});"
                    )

                return "\n".join(sql_parts) + "\n"

        except Exception as e:
            logger.warning(f"Could not generate data SQL for {table_name}: {e}")
            return ""

    def _generate_foreign_key_constraints(
        self, schema: DatabaseSchema, tables: List[str]
    ) -> str:
        """Generate foreign key constraint statements"""
        constraints = []

        for relationship in schema.relationships:
            if (
                relationship.source_table in tables
                and relationship.target_table in tables
                and relationship.constraint_name
            ):
                source_cols = ", ".join(relationship.source_columns)
                target_cols = ", ".join(relationship.target_columns)

                sql = f"ALTER TABLE {relationship.source_table} "
                sql += f"ADD CONSTRAINT {relationship.constraint_name} "
                sql += f"FOREIGN KEY ({source_cols}) "
                sql += f"REFERENCES {relationship.target_table} ({target_cols})"

                if relationship.on_delete:
                    sql += f" ON DELETE {relationship.on_delete}"
                if relationship.on_update:
                    sql += f" ON UPDATE {relationship.on_update}"

                sql += ";"
                constraints.append(sql)

        return "\n".join(constraints)

    def restore_backup(self, backup_id: str, restored_by: str) -> bool:
        """
        Restore a database from backup

        Args:
            backup_id: ID of the backup to restore
            restored_by: User performing the restoration

        Returns:
            True if successful
        """
        if not self.engine:
            raise RuntimeError("Database connection not available")

        backup = self.get_backup(backup_id)
        if not backup:
            raise ValueError(f"Backup not found: {backup_id}")

        if not os.path.exists(backup.file_path):
            raise FileNotFoundError(f"Backup file not found: {backup.file_path}")

        try:
            # Verify backup integrity
            current_checksum = self._calculate_file_checksum(backup.file_path)
            if current_checksum != backup.checksum:
                raise ValueError("Backup file integrity check failed")

            logger.info(f"Starting restore from backup: {backup_id}")

            # Read backup content
            if backup.compressed:
                with gzip.open(backup.file_path, "rt", encoding="utf-8") as f:
                    backup_content = f.read()
            else:
                with open(backup.file_path, "r", encoding="utf-8") as f:
                    backup_content = f.read()

            # Execute restore
            with self.engine.begin() as conn:
                # Split content into individual statements
                statements = [
                    stmt.strip() for stmt in backup_content.split(";") if stmt.strip()
                ]

                for statement in statements:
                    if statement.strip():
                        try:
                            conn.execute(text(statement))
                        except Exception as e:
                            logger.warning(
                                f"Failed to execute statement: {statement[:100]}... Error: {e}"
                            )

            logger.info(f"Backup restored successfully: {backup_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to restore backup {backup_id}: {e}")
            raise

    def get_backup(self, backup_id: str) -> Optional[DatabaseBackup]:
        """Get backup by ID"""
        for backup in self.backups:
            if backup.backup_id == backup_id:
                return backup

        # Try to load from database
        return self._load_backup_from_db(backup_id)

    def list_backups(
        self, backup_type: Optional[BackupType] = None, limit: int = 50
    ) -> List[DatabaseBackup]:
        """List available backups"""
        try:
            backups = self._load_backups_from_db(limit)

            if backup_type:
                backups = [b for b in backups if b.backup_type == backup_type]

            return sorted(backups, key=lambda x: x.created_at, reverse=True)

        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []

    def delete_backup(self, backup_id: str, deleted_by: str) -> bool:
        """Delete a backup"""
        backup = self.get_backup(backup_id)
        if not backup:
            return False

        try:
            # Remove file
            if os.path.exists(backup.file_path):
                os.remove(backup.file_path)

            # Remove from database
            self._delete_backup_from_db(backup_id)

            # Remove from memory
            self.backups = [b for b in self.backups if b.backup_id != backup_id]

            logger.info(f"Backup deleted: {backup_id} by {deleted_by}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete backup {backup_id}: {e}")
            return False

    # Migration Operations
    def create_migration(
        self,
        name: str,
        description: str,
        migration_type: MigrationType,
        up_script: str,
        down_script: str,
        created_by: str,
        dependencies: Optional[List[str]] = None,
    ) -> str:
        """
        Create a new migration

        Args:
            name: Migration name
            description: Migration description
            migration_type: Type of migration
            up_script: SQL script to apply migration
            down_script: SQL script to rollback migration
            created_by: User creating the migration
            dependencies: List of migration IDs this depends on

        Returns:
            Migration ID
        """
        migration_id = str(uuid.uuid4())
        checksum = hashlib.sha256((up_script + down_script).encode()).hexdigest()

        migration = DatabaseMigration(
            migration_id=migration_id,
            name=name,
            description=description,
            migration_type=migration_type,
            created_at=datetime.now(tz=timezone.utc),
            created_by=created_by,
            status=MigrationStatus.PENDING,
            up_script=up_script,
            down_script=down_script,
            checksum=checksum,
            dependencies=dependencies or [],
        )

        # Store migration
        self._store_migration_record(migration)
        self.migrations.append(migration)

        logger.info(f"Migration created: {migration_id}")
        return migration_id

    def execute_migration(self, migration_id: str, executed_by: str) -> bool:
        """
        Execute a migration

        Args:
            migration_id: ID of migration to execute
            executed_by: User executing the migration

        Returns:
            True if successful
        """
        if not self.engine:
            raise RuntimeError("Database connection not available")

        migration = self.get_migration(migration_id)
        if not migration:
            raise ValueError(f"Migration not found: {migration_id}")

        if migration.status != MigrationStatus.PENDING:
            raise ValueError(f"Migration {migration_id} is not in pending state")

        # Check dependencies
        for dep_id in migration.dependencies:
            dep_migration = self.get_migration(dep_id)
            if not dep_migration or dep_migration.status != MigrationStatus.COMPLETED:
                raise ValueError(f"Dependency migration {dep_id} not completed")

        try:
            # Create backup before migration (optional but recommended)
            backup_id = None
            try:
                backup_id = self.create_backup(
                    backup_name=f"pre_migration_{migration.name}",
                    backup_type=BackupType.FULL,
                    created_by=executed_by,
                    description=f"Automatic backup before migration {migration.name}",
                    retention_days=7,
                )
                migration.backup_id = backup_id
            except Exception as e:
                logger.warning(f"Could not create pre-migration backup: {e}")

            # Update migration status
            migration.status = MigrationStatus.RUNNING
            self._update_migration_record(migration)

            start_time = datetime.now(tz=timezone.utc)

            # Execute migration
            with self.engine.begin() as conn:
                statements = [
                    stmt.strip()
                    for stmt in migration.up_script.split(";")
                    if stmt.strip()
                ]

                for statement in statements:
                    if statement.strip():
                        conn.execute(text(statement))

            # Update migration as completed
            end_time = datetime.now(tz=timezone.utc)
            execution_time = int((end_time - start_time).total_seconds() * 1000)

            migration.status = MigrationStatus.COMPLETED
            migration.executed_at = end_time
            migration.execution_time_ms = execution_time

            self._update_migration_record(migration)

            logger.info(f"Migration executed successfully: {migration_id}")
            return True

        except Exception as e:
            # Mark migration as failed
            migration.status = MigrationStatus.FAILED
            migration.error_message = str(e)
            migration.executed_at = datetime.now(tz=timezone.utc)

            self._update_migration_record(migration)

            logger.error(f"Migration failed: {migration_id} - {e}")
            raise

    def rollback_migration(self, migration_id: str, rolled_back_by: str) -> bool:
        """
        Rollback a migration

        Args:
            migration_id: ID of migration to rollback
            rolled_back_by: User performing the rollback

        Returns:
            True if successful
        """
        if not self.engine:
            raise RuntimeError("Database connection not available")

        migration = self.get_migration(migration_id)
        if not migration:
            raise ValueError(f"Migration not found: {migration_id}")

        if migration.status != MigrationStatus.COMPLETED:
            raise ValueError(f"Migration {migration_id} is not in completed state")

        try:
            logger.info(f"Starting rollback of migration: {migration_id}")

            # Execute rollback script
            with self.engine.begin() as conn:
                statements = [
                    stmt.strip()
                    for stmt in migration.down_script.split(";")
                    if stmt.strip()
                ]

                for statement in statements:
                    if statement.strip():
                        conn.execute(text(statement))

            # Update migration status
            migration.status = MigrationStatus.ROLLED_BACK
            self._update_migration_record(migration)

            logger.info(f"Migration rolled back successfully: {migration_id}")
            return True

        except Exception as e:
            logger.error(f"Migration rollback failed: {migration_id} - {e}")
            raise

    def get_migration(self, migration_id: str) -> Optional[DatabaseMigration]:
        """Get migration by ID"""
        for migration in self.migrations:
            if migration.migration_id == migration_id:
                return migration

        # Try to load from database
        return self._load_migration_from_db(migration_id)

    def list_migrations(
        self, status: Optional[MigrationStatus] = None, limit: int = 50
    ) -> List[DatabaseMigration]:
        """List migrations"""
        try:
            migrations = self._load_migrations_from_db(limit)

            if status:
                migrations = [m for m in migrations if m.status == status]

            return sorted(migrations, key=lambda x: x.created_at, reverse=True)

        except Exception as e:
            logger.error(f"Failed to list migrations: {e}")
            return []

    # Schema Version Management
    def create_schema_version(
        self, version_number: str, description: str, created_by: str
    ) -> str:
        """Create a new schema version"""
        if not self.erd_manager:
            raise RuntimeError("ERD manager not available")

        version_id = str(uuid.uuid4())

        # Get current schema
        schema = self.erd_manager.get_database_schema()
        schema_content = self.erd_manager.backup_database_schema()
        schema_checksum = hashlib.sha256(schema_content.encode()).hexdigest()

        # Get applied migrations
        applied_migrations = [
            m.migration_id
            for m in self.migrations
            if m.status == MigrationStatus.COMPLETED
        ]

        # Mark all other versions as not current
        for version in self.schema_versions:
            version.is_current = False
            self._update_schema_version_record(version)

        schema_version = SchemaVersion(
            version_id=version_id,
            version_number=version_number,
            created_at=datetime.now(tz=timezone.utc),
            created_by=created_by,
            description=description,
            schema_checksum=schema_checksum,
            migrations_applied=applied_migrations,
            is_current=True,
        )

        # Store version
        self._store_schema_version_record(schema_version)
        self.schema_versions.append(schema_version)

        logger.info(f"Schema version created: {version_id}")
        return version_id

    def get_current_schema_version(self) -> Optional[SchemaVersion]:
        """Get current schema version"""
        for version in self.schema_versions:
            if version.is_current:
                return version

        # Try to load from database
        return self._load_current_schema_version_from_db()

    # Utility Methods
    def _calculate_file_checksum(self, file_path: str) -> str:
        """Calculate SHA256 checksum of a file"""
        sha256_hash = hashlib.sha256()

        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)

        return sha256_hash.hexdigest()

    def _store_backup_record(self, backup: DatabaseBackup):
        """Store backup record in database"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                    INSERT INTO db_backups (
                        backup_id, name, backup_type, created_at, created_by,
                        file_path, file_size, compressed, checksum, database_name,
                        tables_included, schema_version, description, retention_days, is_automated
                    ) VALUES (
                        :backup_id, :name, :backup_type, :created_at, :created_by,
                        :file_path, :file_size, :compressed, :checksum, :database_name,
                        :tables_included, :schema_version, :description, :retention_days, :is_automated
                    )
                """
                    ),
                    {
                        "backup_id": backup.backup_id,
                        "name": backup.name,
                        "backup_type": backup.backup_type.value,
                        "created_at": backup.created_at,
                        "created_by": backup.created_by,
                        "file_path": backup.file_path,
                        "file_size": backup.file_size,
                        "compressed": backup.compressed,
                        "checksum": backup.checksum,
                        "database_name": backup.database_name,
                        "tables_included": json.dumps(backup.tables_included),
                        "schema_version": backup.schema_version,
                        "description": backup.description,
                        "retention_days": backup.retention_days,
                        "is_automated": backup.is_automated,
                    },
                )
        except Exception as e:
            logger.error(f"Failed to store backup record: {e}")

    def _store_migration_record(self, migration: DatabaseMigration):
        """Store migration record in database"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                    INSERT INTO db_migrations (
                        migration_id, name, description, migration_type, created_at, created_by,
                        status, up_script, down_script, checksum, dependencies,
                        executed_at, execution_time_ms, error_message, backup_id
                    ) VALUES (
                        :migration_id, :name, :description, :migration_type, :created_at, :created_by,
                        :status, :up_script, :down_script, :checksum, :dependencies,
                        :executed_at, :execution_time_ms, :error_message, :backup_id
                    )
                """
                    ),
                    {
                        "migration_id": migration.migration_id,
                        "name": migration.name,
                        "description": migration.description,
                        "migration_type": migration.migration_type.value,
                        "created_at": migration.created_at,
                        "created_by": migration.created_by,
                        "status": migration.status.value,
                        "up_script": migration.up_script,
                        "down_script": migration.down_script,
                        "checksum": migration.checksum,
                        "dependencies": json.dumps(migration.dependencies),
                        "executed_at": migration.executed_at,
                        "execution_time_ms": migration.execution_time_ms,
                        "error_message": migration.error_message,
                        "backup_id": migration.backup_id,
                    },
                )
        except Exception as e:
            logger.error(f"Failed to store migration record: {e}")

    def _store_schema_version_record(self, version: SchemaVersion):
        """Store schema version record in database"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                    INSERT INTO db_schema_versions (
                        version_id, version_number, created_at, created_by,
                        description, schema_checksum, migrations_applied, is_current
                    ) VALUES (
                        :version_id, :version_number, :created_at, :created_by,
                        :description, :schema_checksum, :migrations_applied, :is_current
                    )
                """
                    ),
                    {
                        "version_id": version.version_id,
                        "version_number": version.version_number,
                        "created_at": version.created_at,
                        "created_by": version.created_by,
                        "description": version.description,
                        "schema_checksum": version.schema_checksum,
                        "migrations_applied": json.dumps(version.migrations_applied),
                        "is_current": version.is_current,
                    },
                )
        except Exception as e:
            logger.error(f"Failed to store schema version record: {e}")

    def _update_migration_record(self, migration: DatabaseMigration):
        """Update migration record in database"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                    UPDATE db_migrations SET
                        status = :status,
                        executed_at = :executed_at,
                        execution_time_ms = :execution_time_ms,
                        error_message = :error_message,
                        backup_id = :backup_id
                    WHERE migration_id = :migration_id
                """
                    ),
                    {
                        "migration_id": migration.migration_id,
                        "status": migration.status.value,
                        "executed_at": migration.executed_at,
                        "execution_time_ms": migration.execution_time_ms,
                        "error_message": migration.error_message,
                        "backup_id": migration.backup_id,
                    },
                )
        except Exception as e:
            logger.error(f"Failed to update migration record: {e}")

    def _update_schema_version_record(self, version: SchemaVersion):
        """Update schema version record in database"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                    UPDATE db_schema_versions SET
                        is_current = :is_current
                    WHERE version_id = :version_id
                """
                    ),
                    {
                        "version_id": version.version_id,
                        "is_current": version.is_current,
                    },
                )
        except Exception as e:
            logger.error(f"Failed to update schema version record: {e}")

    def _load_backup_from_db(self, backup_id: str) -> Optional[DatabaseBackup]:
        """Load backup record from database"""
        if not self.engine:
            return None

        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT * FROM db_backups WHERE backup_id = :backup_id
                """
                    ),
                    {"backup_id": backup_id},
                )

                row = result.fetchone()
                if row:
                    return self._row_to_backup(row)

        except Exception as e:
            logger.error(f"Failed to load backup from database: {e}")

        return None

    def _load_backups_from_db(self, limit: int) -> List[DatabaseBackup]:
        """Load backup records from database"""
        if not self.engine:
            return []

        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT * FROM db_backups 
                    ORDER BY created_at DESC 
                    LIMIT :limit
                """
                    ),
                    {"limit": limit},
                )

                return [self._row_to_backup(row) for row in result]

        except Exception as e:
            logger.error(f"Failed to load backups from database: {e}")
            return []

    def _load_migration_from_db(self, migration_id: str) -> Optional[DatabaseMigration]:
        """Load migration record from database"""
        if not self.engine:
            return None

        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT * FROM db_migrations WHERE migration_id = :migration_id
                """
                    ),
                    {"migration_id": migration_id},
                )

                row = result.fetchone()
                if row:
                    return self._row_to_migration(row)

        except Exception as e:
            logger.error(f"Failed to load migration from database: {e}")

        return None

    def _load_migrations_from_db(self, limit: int) -> List[DatabaseMigration]:
        """Load migration records from database"""
        if not self.engine:
            return []

        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT * FROM db_migrations 
                    ORDER BY created_at DESC 
                    LIMIT :limit
                """
                    ),
                    {"limit": limit},
                )

                return [self._row_to_migration(row) for row in result]

        except Exception as e:
            logger.error(f"Failed to load migrations from database: {e}")
            return []

    def _load_current_schema_version_from_db(self) -> Optional[SchemaVersion]:
        """Load current schema version from database"""
        if not self.engine:
            return None

        try:
            with self.engine.connect() as conn:
                result = conn.execute(
                    text(
                        """
                    SELECT * FROM db_schema_versions WHERE is_current = TRUE
                """
                    )
                )

                row = result.fetchone()
                if row:
                    return self._row_to_schema_version(row)

        except Exception as e:
            logger.error(f"Failed to load current schema version from database: {e}")

        return None

    def _delete_backup_from_db(self, backup_id: str):
        """Delete backup record from database"""
        if not self.engine:
            return

        try:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        """
                    DELETE FROM db_backups WHERE backup_id = :backup_id
                """
                    ),
                    {"backup_id": backup_id},
                )
        except Exception as e:
            logger.error(f"Failed to delete backup from database: {e}")

    def _row_to_backup(self, row) -> DatabaseBackup:
        """Convert database row to DatabaseBackup object"""
        return DatabaseBackup(
            backup_id=row.backup_id,
            name=row.name,
            backup_type=BackupType(row.backup_type),
            created_at=row.created_at,
            created_by=row.created_by,
            file_path=row.file_path,
            file_size=row.file_size,
            compressed=row.compressed,
            checksum=row.checksum,
            database_name=row.database_name,
            tables_included=json.loads(row.tables_included),
            schema_version=row.schema_version,
            description=row.description,
            retention_days=row.retention_days,
            is_automated=row.is_automated,
        )

    def _row_to_migration(self, row) -> DatabaseMigration:
        """Convert database row to DatabaseMigration object"""
        return DatabaseMigration(
            migration_id=row.migration_id,
            name=row.name,
            description=row.description,
            migration_type=MigrationType(row.migration_type),
            created_at=row.created_at,
            created_by=row.created_by,
            status=MigrationStatus(row.status),
            up_script=row.up_script,
            down_script=row.down_script,
            checksum=row.checksum,
            dependencies=json.loads(row.dependencies) if row.dependencies else [],
            executed_at=row.executed_at,
            execution_time_ms=row.execution_time_ms,
            error_message=row.error_message,
            backup_id=row.backup_id,
        )

    def _row_to_schema_version(self, row) -> SchemaVersion:
        """Convert database row to SchemaVersion object"""
        return SchemaVersion(
            version_id=row.version_id,
            version_number=row.version_number,
            created_at=row.created_at,
            created_by=row.created_by,
            description=row.description,
            schema_checksum=row.schema_checksum,
            migrations_applied=json.loads(row.migrations_applied)
            if row.migrations_applied
            else [],
            is_current=row.is_current,
        )


# Global migration manager instance
database_migration_manager = None


def get_migration_manager(
    database_uri: str = None, backup_directory: str = None
) -> DatabaseMigrationManager:
    """Get or create the global migration manager instance"""
    global database_migration_manager
    if database_migration_manager is None:
        database_migration_manager = DatabaseMigrationManager(
            database_uri, backup_directory
        )
    return database_migration_manager
