"""
Migration Tools for Single-Tenant to Multi-Tenant Conversion.

This module provides tools to migrate existing single-tenant PgForge
applications to multi-tenant SaaS architecture with data migration and
schema transformation capabilities.
"""

import logging
import os
import sys
import json
import shutil
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import click

from flask import current_app
from flask.cli import with_appcontext
from sqlalchemy import create_engine, text, inspect, MetaData, Table, Column, Integer, ForeignKey
from sqlalchemy.schema import CreateTable
from alembic.config import Config
from alembic import command
from alembic.script import ScriptDirectory
from alembic.migration import MigrationContext
from alembic.operations import Operations

log = logging.getLogger(__name__)


@dataclass
class MigrationPlan:
    """Migration plan for single-tenant to multi-tenant conversion."""
    source_database: str
    target_database: str
    tenant_slug: str
    tenant_name: str
    tenant_email: str
    tables_to_migrate: List[str]
    tables_to_skip: List[str]
    custom_mappings: Dict[str, str]
    data_transformations: Dict[str, Any]
    backup_location: str
    rollback_enabled: bool


@dataclass
class MigrationResult:
    """Result of migration operation."""
    success: bool
    tenant_id: Optional[int]
    tables_migrated: int
    records_migrated: int
    errors: List[str]
    warnings: List[str]
    execution_time: float
    backup_file: Optional[str]


class TenantMigrationEngine:
    """Core engine for migrating single-tenant data to multi-tenant structure."""
    
    def __init__(self, source_db_url: str, target_db_url: str):
        self.source_engine = create_engine(source_db_url)
        self.target_engine = create_engine(target_db_url)
        self.errors = []
        self.warnings = []
    
    def analyze_source_schema(self) -> Dict[str, Any]:
        """Analyze source database schema for migration compatibility."""
        log.info("Analyzing source database schema...")
        
        inspector = inspect(self.source_engine)
        schema_info = {
            'tables': {},
            'foreign_keys': {},
            'indexes': {},
            'constraints': {}
        }
        
        # Get all table information
        for table_name in inspector.get_table_names():
            table_info = {
                'columns': inspector.get_columns(table_name),
                'primary_key': inspector.get_pk_constraint(table_name),
                'foreign_keys': inspector.get_foreign_keys(table_name),
                'indexes': inspector.get_indexes(table_name),
                'unique_constraints': inspector.get_unique_constraints(table_name)
            }
            
            schema_info['tables'][table_name] = table_info
            
            # Check if table already has tenant_id column
            column_names = [col['name'] for col in table_info['columns']]
            if 'tenant_id' in column_names:
                self.warnings.append(f"Table {table_name} already has tenant_id column")
        
        log.info(f"Found {len(schema_info['tables'])} tables in source database")
        return schema_info
    
    def create_migration_plan(self, schema_info: Dict[str, Any], 
                            tenant_info: Dict[str, str]) -> MigrationPlan:
        """Create a migration plan based on schema analysis."""
        
        # Determine which tables to migrate
        tables_to_migrate = []
        tables_to_skip = []
        
        # Skip system tables and already multi-tenant tables
        system_tables = {
            'ab_user', 'ab_role', 'ab_user_role', 'ab_permission',
            'ab_view_menu', 'ab_permission_view', 'ab_permission_view_role',
            'alembic_version', 'ab_register_user'
        }
        
        multi_tenant_tables = {
            'ab_tenants', 'ab_tenant_users', 'ab_tenant_configs',
            'ab_tenant_subscriptions', 'ab_tenant_usage'
        }
        
        for table_name in schema_info['tables']:
            if table_name in system_tables:
                tables_to_skip.append(table_name)
                log.info(f"Skipping system table: {table_name}")
            elif table_name in multi_tenant_tables:
                tables_to_skip.append(table_name)
                log.info(f"Skipping multi-tenant table: {table_name}")
            elif table_name.endswith('_mt'):
                tables_to_skip.append(table_name)
                log.info(f"Skipping already multi-tenant table: {table_name}")
            else:
                tables_to_migrate.append(table_name)
        
        # Create migration plan
        plan = MigrationPlan(
            source_database=str(self.source_engine.url),
            target_database=str(self.target_engine.url),
            tenant_slug=tenant_info['slug'],
            tenant_name=tenant_info['name'],
            tenant_email=tenant_info['email'],
            tables_to_migrate=tables_to_migrate,
            tables_to_skip=tables_to_skip,
            custom_mappings={},
            data_transformations={},
            backup_location=f"/tmp/migration_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            rollback_enabled=True
        )
        
        log.info(f"Migration plan created: {len(tables_to_migrate)} tables to migrate")
        return plan
    
    def create_tenant_schema(self, plan: MigrationPlan) -> Tuple[bool, Optional[int]]:
        """Create multi-tenant schema in target database."""
        log.info("Creating multi-tenant schema in target database...")
        
        try:
            with self.target_engine.connect() as conn:
                # Create multi-tenant tables if they don't exist
                self._create_core_tenant_tables(conn)
                
                # Create tenant record
                tenant_id = self._create_tenant_record(conn, plan)
                
                # Create multi-tenant versions of application tables
                self._create_application_tables_mt(conn, plan)
                
                conn.commit()
                log.info(f"Multi-tenant schema created successfully, tenant_id: {tenant_id}")
                return True, tenant_id
                
        except Exception as e:
            log.error(f"Failed to create multi-tenant schema: {e}")
            self.errors.append(f"Schema creation failed: {str(e)}")
            return False, None
    
    def migrate_data(self, plan: MigrationPlan, tenant_id: int) -> MigrationResult:
        """Migrate data from single-tenant to multi-tenant structure."""
        log.info(f"Starting data migration for tenant {tenant_id}...")
        
        start_time = datetime.now()
        tables_migrated = 0
        records_migrated = 0
        
        try:
            # Create backup if enabled
            backup_file = None
            if plan.rollback_enabled:
                backup_file = self._create_backup(plan)
            
            # Migrate each table
            for table_name in plan.tables_to_migrate:
                try:
                    migrated_records = self._migrate_table_data(
                        table_name, tenant_id, plan
                    )
                    records_migrated += migrated_records
                    tables_migrated += 1
                    log.info(f"Migrated {migrated_records} records from {table_name}")
                    
                except Exception as e:
                    error_msg = f"Failed to migrate table {table_name}: {str(e)}"
                    log.error(error_msg)
                    self.errors.append(error_msg)
            
            execution_time = (datetime.now() - start_time).total_seconds()
            
            result = MigrationResult(
                success=len(self.errors) == 0,
                tenant_id=tenant_id,
                tables_migrated=tables_migrated,
                records_migrated=records_migrated,
                errors=self.errors.copy(),
                warnings=self.warnings.copy(),
                execution_time=execution_time,
                backup_file=backup_file
            )
            
            log.info(f"Data migration completed in {execution_time:.2f} seconds")
            log.info(f"Migrated {records_migrated} records from {tables_migrated} tables")
            
            return result
            
        except Exception as e:
            log.error(f"Data migration failed: {e}")
            self.errors.append(f"Migration failed: {str(e)}")
            
            return MigrationResult(
                success=False,
                tenant_id=tenant_id,
                tables_migrated=tables_migrated,
                records_migrated=records_migrated,
                errors=self.errors.copy(),
                warnings=self.warnings.copy(),
                execution_time=(datetime.now() - start_time).total_seconds(),
                backup_file=None
            )
    
    def _create_core_tenant_tables(self, conn):
        """Create core multi-tenant tables."""
        
        # Core tenant tables DDL
        tenant_tables_sql = [
            """
            CREATE TABLE IF NOT EXISTS ab_tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_on DATETIME,
                changed_on DATETIME,
                created_by_fk INTEGER,
                changed_by_fk INTEGER,
                slug VARCHAR(50) NOT NULL UNIQUE,
                name VARCHAR(100) NOT NULL,
                description TEXT,
                status VARCHAR(20) DEFAULT 'active',
                activated_at DATETIME,
                suspended_at DATETIME,
                primary_contact_email VARCHAR(120) NOT NULL,
                billing_email VARCHAR(120),
                phone VARCHAR(50),
                branding_config TEXT,
                custom_domain VARCHAR(100),
                subscription_id VARCHAR(100),
                plan_id VARCHAR(50),
                resource_limits TEXT,
                FOREIGN KEY (created_by_fk) REFERENCES ab_user(id),
                FOREIGN KEY (changed_by_fk) REFERENCES ab_user(id)
            )
            """,
            
            """
            CREATE TABLE IF NOT EXISTS ab_tenant_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_on DATETIME,
                changed_on DATETIME,
                created_by_fk INTEGER,
                changed_by_fk INTEGER,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role_within_tenant VARCHAR(50) DEFAULT 'member',
                is_active BOOLEAN DEFAULT 1,
                joined_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                last_login_at DATETIME,
                FOREIGN KEY (tenant_id) REFERENCES ab_tenants(id),
                FOREIGN KEY (user_id) REFERENCES ab_user(id),
                FOREIGN KEY (created_by_fk) REFERENCES ab_user(id),
                FOREIGN KEY (changed_by_fk) REFERENCES ab_user(id),
                UNIQUE(tenant_id, user_id)
            )
            """,
            
            """
            CREATE TABLE IF NOT EXISTS ab_tenant_configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_on DATETIME,
                changed_on DATETIME,
                created_by_fk INTEGER,
                changed_by_fk INTEGER,
                tenant_id INTEGER NOT NULL,
                config_key VARCHAR(100) NOT NULL,
                config_value TEXT NOT NULL,
                config_type VARCHAR(20) DEFAULT 'string',
                description TEXT,
                is_sensitive BOOLEAN DEFAULT 0,
                category VARCHAR(50),
                FOREIGN KEY (tenant_id) REFERENCES ab_tenants(id),
                FOREIGN KEY (created_by_fk) REFERENCES ab_user(id),
                FOREIGN KEY (changed_by_fk) REFERENCES ab_user(id),
                UNIQUE(tenant_id, config_key)
            )
            """
        ]
        
        for sql in tenant_tables_sql:
            conn.execute(text(sql))
    
    def _create_tenant_record(self, conn, plan: MigrationPlan) -> int:
        """Create tenant record and return tenant_id."""
        
        # Insert tenant record
        insert_sql = text("""
            INSERT INTO ab_tenants 
            (created_on, slug, name, primary_contact_email, status, plan_id, resource_limits)
            VALUES 
            (:created_on, :slug, :name, :email, :status, :plan_id, :limits)
        """)
        
        result = conn.execute(insert_sql, {
            'created_on': datetime.now(tz=timezone.utc),
            'slug': plan.tenant_slug,
            'name': plan.tenant_name,
            'email': plan.tenant_email,
            'status': 'active',
            'plan_id': 'professional',  # Default plan for migrated tenants
            'limits': json.dumps({
                'max_users': 100,
                'max_records': 100000,
                'storage_gb': 10
            })
        })
        
        # Get the inserted tenant_id
        tenant_id = result.lastrowid
        
        return tenant_id
    
    def _create_application_tables_mt(self, conn, plan: MigrationPlan):
        """Create multi-tenant versions of application tables."""
        
        # Get source schema information
        source_inspector = inspect(self.source_engine)
        
        for table_name in plan.tables_to_migrate:
            mt_table_name = f"{table_name}_mt"
            
            # Get original table structure
            columns = source_inspector.get_columns(table_name)
            primary_key = source_inspector.get_pk_constraint(table_name)
            foreign_keys = source_inspector.get_foreign_keys(table_name)
            
            # Build CREATE TABLE statement for multi-tenant version
            column_defs = []
            
            # Add tenant_id column first
            column_defs.append("tenant_id INTEGER NOT NULL")
            
            # Add original columns
            for col in columns:
                col_def = f"{col['name']} {self._get_column_type_sqlite(col)}"
                
                # Add constraints
                if col.get('nullable') == False:
                    col_def += " NOT NULL"
                if col.get('default') is not None:
                    col_def += f" DEFAULT {col['default']}"
                
                column_defs.append(col_def)
            
            # Add foreign key to tenant table
            column_defs.append("FOREIGN KEY (tenant_id) REFERENCES ab_tenants(id)")
            
            # Add original foreign keys
            for fk in foreign_keys:
                fk_def = f"FOREIGN KEY ({', '.join(fk['constrained_columns'])}) REFERENCES {fk['referred_table']}({', '.join(fk['referred_columns'])})"
                column_defs.append(fk_def)
            
            # Create the table
            create_sql = f"CREATE TABLE IF NOT EXISTS {mt_table_name} ({', '.join(column_defs)})"
            
            try:
                conn.execute(text(create_sql))
                log.info(f"Created multi-tenant table: {mt_table_name}")
            except Exception as e:
                log.warning(f"Could not create table {mt_table_name}: {e}")
    
    def _migrate_table_data(self, table_name: str, tenant_id: int, plan: MigrationPlan) -> int:
        """Migrate data from source table to multi-tenant table."""
        
        mt_table_name = f"{table_name}_mt"
        
        # Get all data from source table
        with self.source_engine.connect() as source_conn:
            result = source_conn.execute(text(f"SELECT * FROM {table_name}"))
            rows = result.fetchall()
            columns = result.keys()
        
        if not rows:
            log.info(f"No data to migrate from {table_name}")
            return 0
        
        # Insert data into multi-tenant table with tenant_id
        with self.target_engine.connect() as target_conn:
            # Build INSERT statement
            mt_columns = ['tenant_id'] + list(columns)
            placeholders = ', '.join([f':{col}' for col in mt_columns])
            
            insert_sql = text(
                f"INSERT INTO {mt_table_name} ({', '.join(mt_columns)}) VALUES ({placeholders})"
            )
            
            # Prepare data with tenant_id
            data_with_tenant = []
            for row in rows:
                row_dict = dict(zip(columns, row))
                row_dict['tenant_id'] = tenant_id
                data_with_tenant.append(row_dict)
            
            # Execute batch insert
            target_conn.execute(insert_sql, data_with_tenant)
            target_conn.commit()
        
        log.info(f"Migrated {len(rows)} records from {table_name} to {mt_table_name}")
        return len(rows)
    
    def _get_column_type_sqlite(self, column_info: Dict) -> str:
        """Convert column type to SQLite format."""
        col_type = str(column_info.get('type', 'TEXT')).upper()
        
        # Map common types
        type_mapping = {
            'VARCHAR': 'VARCHAR',
            'INTEGER': 'INTEGER',
            'BOOLEAN': 'BOOLEAN',
            'DATETIME': 'DATETIME',
            'DATE': 'DATE',
            'TEXT': 'TEXT',
            'FLOAT': 'REAL',
            'DECIMAL': 'NUMERIC'
        }
        
        for db_type, sqlite_type in type_mapping.items():
            if db_type in col_type:
                return sqlite_type
        
        return 'TEXT'  # Default fallback
    
    def _create_backup(self, plan: MigrationPlan) -> str:
        """Create backup of source database with SQL injection protection."""
        log.info("Creating backup of source database...")
        
        backup_dir = Path(plan.backup_location)
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # Sanitize tenant slug for filename
        safe_tenant_slug = re.sub(r'[^a-zA-Z0-9_-]', '_', plan.tenant_slug)
        backup_file = backup_dir / f"backup_{safe_tenant_slug}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.sql"
        
        try:
            # This is a simplified backup - in production, use proper database backup tools
            with self.source_engine.connect() as conn:
                # Export schema and data to SQL file
                with open(backup_file, 'w', encoding='utf-8') as f:
                    f.write(f"-- Backup created on {datetime.now()}\n")
                    f.write(f"-- Source: {plan.source_database}\n")
                    f.write("-- WARNING: This backup was created by PgForge migration tools\n")
                    f.write("-- For production use, prefer database-native backup tools (pg_dump, mysqldump, etc.)\n\n")
                    
                    # Get table names with validation
                    inspector = inspect(self.source_engine)
                    available_tables = inspector.get_table_names()
                    
                    for table_name in available_tables:
                        if table_name in plan.tables_to_migrate:
                            # Validate table name to prevent injection
                            if not self._is_safe_table_name(table_name):
                                log.warning(f"Skipping table with unsafe name: {table_name}")
                                continue
                            
                            try:
                                # Use parameterized query construction
                                safe_table_name = self._escape_identifier(table_name)
                                result = conn.execute(text(f"SELECT * FROM {safe_table_name}"))
                                rows = result.fetchall()
                                
                                if rows:
                                    columns = list(result.keys())
                                    # Validate column names
                                    safe_columns = []
                                    for col in columns:
                                        if self._is_safe_column_name(col):
                                            safe_columns.append(self._escape_identifier(col))
                                        else:
                                            log.warning(f"Skipping column with unsafe name: {col} in table {table_name}")
                                    
                                    if not safe_columns:
                                        log.warning(f"No safe columns found in table {table_name}, skipping")
                                        continue
                                    
                                    f.write(f"-- Data for table {safe_table_name}\n")
                                    
                                    # Process rows with proper SQL escaping
                                    for row in rows:
                                        try:
                                            values = []
                                            for i, val in enumerate(row):
                                                if i >= len(safe_columns):
                                                    break  # Safety check
                                                escaped_val = self._escape_sql_value(val)
                                                values.append(escaped_val)
                                            
                                            if len(values) == len(safe_columns):
                                                values_str = ', '.join(values)
                                                columns_str = ', '.join(safe_columns)
                                                f.write(f"INSERT INTO {safe_table_name} ({columns_str}) VALUES ({values_str});\n")
                                            else:
                                                log.warning(f"Column count mismatch in table {table_name}, skipping row")
                                        
                                        except Exception as row_error:
                                            log.error(f"Error processing row in table {table_name}: {row_error}")
                                            continue
                                    
                                    f.write("\n")
                                    
                            except Exception as table_error:
                                log.error(f"Error backing up table {table_name}: {table_error}")
                                continue
            
            log.info(f"Backup created: {backup_file}")
            return str(backup_file)
            
        except Exception as e:
            log.error(f"Failed to create backup: {e}")
            return None
    
    def _is_safe_table_name(self, table_name: str) -> bool:
        """Validate that table name is safe from SQL injection."""
        if not table_name or len(table_name) > 128:
            return False
        
        # Allow alphanumeric, underscore, and hyphen
        # Reject SQL keywords and dangerous patterns
        if not re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', table_name):
            return False
        
        # Reject common SQL keywords that could be dangerous
        dangerous_keywords = {
            'select', 'insert', 'update', 'delete', 'drop', 'create', 'alter',
            'truncate', 'exec', 'execute', 'sp_', 'xp_', 'union', 'script',
            'declare', 'cursor', 'procedure', 'function'
        }
        
        return table_name.lower() not in dangerous_keywords
    
    def _is_safe_column_name(self, column_name: str) -> bool:
        """Validate that column name is safe from SQL injection."""
        if not column_name or len(column_name) > 128:
            return False
        
        # Allow alphanumeric, underscore, and hyphen
        return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', column_name))
    
    def _escape_identifier(self, identifier: str) -> str:
        """Escape SQL identifier (table/column name) for safe use in queries."""
        # Remove any existing quotes and escape internal quotes
        clean_identifier = identifier.replace('"', '""')
        # Wrap in double quotes for SQL standard identifier escaping
        return f'"{clean_identifier}"'
    
    def _escape_sql_value(self, value: Any) -> str:
        """Properly escape SQL values to prevent injection."""
        if value is None:
            return 'NULL'
        
        if isinstance(value, bool):
            return 'TRUE' if value else 'FALSE'
        
        if isinstance(value, (int, float)):
            # Validate numeric values
            try:
                # Convert to string and validate it's actually numeric
                str_val = str(value)
                if re.match(r'^-?\d+(\.\d+)?([eE][+-]?\d+)?$', str_val):
                    return str_val
                else:
                    # Fallback to string escaping for invalid numeric formats
                    escaped = str(value).replace("'", "''")
                    return f"'{escaped}'"
            except:
                return 'NULL'
        
        if isinstance(value, (str, bytes)):
            # Handle string/binary data with proper escaping
            try:
                if isinstance(value, bytes):
                    # Convert bytes to hex string for safe storage
                    hex_val = value.hex()
                    return f"decode('{hex_val}', 'hex')"
                else:
                    # Escape single quotes by doubling them (SQL standard)
                    escaped = str(value).replace("'", "''")
                    # Also escape backslashes for databases that interpret them
                    escaped = escaped.replace("\\", "\\\\")
                    return f"'{escaped}'"
            except Exception:
                # If string processing fails, treat as NULL
                return 'NULL'
        
        # For datetime and other types, convert to string and escape
        try:
            str_val = str(value)
            escaped = str_val.replace("'", "''")
            escaped = escaped.replace("\\", "\\\\")
            return f"'{escaped}'"
        except Exception:
            return 'NULL'


class MigrationValidator:
    """Validates migration results and data integrity."""
    
    def __init__(self, source_engine, target_engine):
        self.source_engine = source_engine
        self.target_engine = target_engine
    
    def validate_migration(self, plan: MigrationPlan, tenant_id: int) -> Dict[str, Any]:
        """Validate that migration completed successfully."""
        log.info("Validating migration results...")
        
        validation_results = {
            'success': True,
            'table_validations': {},
            'data_integrity_checks': {},
            'errors': [],
            'warnings': []
        }
        
        for table_name in plan.tables_to_migrate:
            try:
                # Validate table structure
                table_result = self._validate_table(table_name, tenant_id)
                validation_results['table_validations'][table_name] = table_result
                
                if not table_result['success']:
                    validation_results['success'] = False
                    validation_results['errors'].extend(table_result['errors'])
                
            except Exception as e:
                error_msg = f"Validation failed for table {table_name}: {str(e)}"
                validation_results['errors'].append(error_msg)
                validation_results['success'] = False
        
        return validation_results
    
    def _validate_table(self, table_name: str, tenant_id: int) -> Dict[str, Any]:
        """Validate individual table migration."""
        mt_table_name = f"{table_name}_mt"
        
        result = {
            'success': True,
            'source_count': 0,
            'target_count': 0,
            'errors': [],
            'warnings': []
        }
        
        try:
            # Count records in source table
            with self.source_engine.connect() as conn:
                source_result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                result['source_count'] = source_result.scalar()
            
            # Count records in target table for this tenant
            with self.target_engine.connect() as conn:
                target_result = conn.execute(
                    text(f"SELECT COUNT(*) FROM {mt_table_name} WHERE tenant_id = :tenant_id"),
                    {'tenant_id': tenant_id}
                )
                result['target_count'] = target_result.scalar()
            
            # Compare counts
            if result['source_count'] != result['target_count']:
                error_msg = f"Record count mismatch: source={result['source_count']}, target={result['target_count']}"
                result['errors'].append(error_msg)
                result['success'] = False
            
        except Exception as e:
            result['errors'].append(f"Validation error: {str(e)}")
            result['success'] = False
        
        return result


# CLI Commands
@click.group()
def migration():
    """Multi-tenant migration commands."""
    pass


@migration.command()
@click.option('--source-db', required=True, help='Source database URL')
@click.option('--target-db', required=True, help='Target database URL') 
@click.option('--tenant-slug', required=True, help='Tenant slug for migrated data')
@click.option('--tenant-name', required=True, help='Tenant name')
@click.option('--tenant-email', required=True, help='Tenant admin email')
@click.option('--dry-run', is_flag=True, help='Perform dry run without actual migration')
@click.option('--backup/--no-backup', default=True, help='Create backup before migration')
@with_appcontext
def convert_to_multitenant(source_db, target_db, tenant_slug, tenant_name, 
                          tenant_email, dry_run, backup):
    """Convert single-tenant application to multi-tenant."""
    
    click.echo(f"Starting single-tenant to multi-tenant conversion...")
    click.echo(f"Source DB: {source_db}")
    click.echo(f"Target DB: {target_db}")
    click.echo(f"Tenant: {tenant_slug} ({tenant_name})")
    
    if dry_run:
        click.echo("DRY RUN MODE - No actual changes will be made")
    
    try:
        # Initialize migration engine
        engine = TenantMigrationEngine(source_db, target_db)
        
        # Analyze source schema
        schema_info = engine.analyze_source_schema()
        
        # Create migration plan
        tenant_info = {
            'slug': tenant_slug,
            'name': tenant_name,
            'email': tenant_email
        }
        
        plan = engine.create_migration_plan(schema_info, tenant_info)
        plan.rollback_enabled = backup
        
        # Display migration plan
        click.echo("\nMigration Plan:")
        click.echo(f"Tables to migrate: {len(plan.tables_to_migrate)}")
        for table in plan.tables_to_migrate:
            click.echo(f"  - {table} -> {table}_mt")
        
        click.echo(f"Tables to skip: {len(plan.tables_to_skip)}")
        for table in plan.tables_to_skip:
            click.echo(f"  - {table} (system/already multi-tenant)")
        
        if dry_run:
            click.echo("\nDry run completed. No changes made.")
            return
        
        # Confirm before proceeding
        if not click.confirm("\nProceed with migration?"):
            click.echo("Migration cancelled.")
            return
        
        # Create multi-tenant schema
        click.echo("\nCreating multi-tenant schema...")
        schema_success, tenant_id = engine.create_tenant_schema(plan)
        
        if not schema_success:
            click.echo("Failed to create schema. Aborting migration.")
            for error in engine.errors:
                click.echo(f"Error: {error}")
            return
        
        click.echo(f"Schema created successfully. Tenant ID: {tenant_id}")
        
        # Migrate data
        click.echo("\nMigrating data...")
        result = engine.migrate_data(plan, tenant_id)
        
        # Display results
        if result.success:
            click.echo(f"\n✓ Migration completed successfully!")
            click.echo(f"  - Tenant ID: {result.tenant_id}")
            click.echo(f"  - Tables migrated: {result.tables_migrated}")
            click.echo(f"  - Records migrated: {result.records_migrated}")
            click.echo(f"  - Execution time: {result.execution_time:.2f} seconds")
            
            if result.backup_file:
                click.echo(f"  - Backup created: {result.backup_file}")
        else:
            click.echo(f"\n✗ Migration failed!")
            for error in result.errors:
                click.echo(f"Error: {error}")
        
        # Show warnings
        if result.warnings:
            click.echo("\nWarnings:")
            for warning in result.warnings:
                click.echo(f"Warning: {warning}")
        
        # Validate migration
        if result.success:
            click.echo("\nValidating migration...")
            validator = MigrationValidator(engine.source_engine, engine.target_engine)
            validation_results = validator.validate_migration(plan, tenant_id)
            
            if validation_results['success']:
                click.echo("✓ Migration validation passed")
            else:
                click.echo("✗ Migration validation failed")
                for error in validation_results['errors']:
                    click.echo(f"Validation error: {error}")
        
    except Exception as e:
        click.echo(f"Migration failed with exception: {str(e)}")
        log.error(f"Migration exception: {e}", exc_info=True)


@migration.command()
@click.option('--source-db', required=True, help='Source database URL')
@with_appcontext
def analyze_schema(source_db):
    """Analyze source database schema for migration compatibility."""
    
    click.echo(f"Analyzing database schema: {source_db}")
    
    try:
        engine = TenantMigrationEngine(source_db, source_db)  # Same DB for analysis
        schema_info = engine.analyze_source_schema()
        
        click.echo(f"\nSchema Analysis Results:")
        click.echo(f"Total tables found: {len(schema_info['tables'])}")
        
        # Categorize tables
        system_tables = []
        migratable_tables = []
        existing_mt_tables = []
        
        for table_name in schema_info['tables']:
            if table_name.startswith('ab_') and 'tenant' not in table_name:
                system_tables.append(table_name)
            elif table_name.endswith('_mt') or 'tenant' in table_name:
                existing_mt_tables.append(table_name)
            else:
                migratable_tables.append(table_name)
        
        click.echo(f"\nTable Categories:")
        click.echo(f"System tables (will be skipped): {len(system_tables)}")
        for table in system_tables:
            click.echo(f"  - {table}")
        
        click.echo(f"\nExisting multi-tenant tables: {len(existing_mt_tables)}")
        for table in existing_mt_tables:
            click.echo(f"  - {table}")
        
        click.echo(f"\nTables ready for migration: {len(migratable_tables)}")
        for table in migratable_tables:
            columns = schema_info['tables'][table]['columns']
            click.echo(f"  - {table} ({len(columns)} columns)")
        
        # Show warnings
        if engine.warnings:
            click.echo(f"\nWarnings:")
            for warning in engine.warnings:
                click.echo(f"  - {warning}")
        
        click.echo(f"\nMigration Readiness: {'Ready' if migratable_tables else 'No tables to migrate'}")
        
    except Exception as e:
        click.echo(f"Schema analysis failed: {str(e)}")
        log.error(f"Schema analysis exception: {e}", exc_info=True)


@migration.command()
@click.option('--config-file', required=True, help='Migration configuration JSON file')
@with_appcontext
def migrate_from_config(config_file):
    """Migrate using configuration file."""
    
    click.echo(f"Loading migration configuration from: {config_file}")
    
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        # Extract configuration
        source_db = config['source_database']
        target_db = config['target_database']
        tenant_slug = config['tenant_slug']
        tenant_name = config['tenant_name']
        tenant_email = config['tenant_email']
        
        # Run migration
        ctx = click.get_current_context()
        ctx.invoke(convert_to_multitenant,
                  source_db=source_db,
                  target_db=target_db,
                  tenant_slug=tenant_slug,
                  tenant_name=tenant_name,
                  tenant_email=tenant_email,
                  dry_run=config.get('dry_run', False),
                  backup=config.get('backup', True))
        
    except Exception as e:
        click.echo(f"Configuration-based migration failed: {str(e)}")
        log.error(f"Config migration exception: {e}", exc_info=True)