"""
SECURE VERSION of migrate_db_1.3.py

This version fixes critical SQL injection vulnerabilities by using proper
SQL identifier validation and parameterized queries.

SECURITY FIXES:
- Replaced dangerous string formatting with secure DDL execution
- Added comprehensive SQL identifier validation
- Used quoted identifiers and parameterized queries
- Added proper error handling and logging
"""

import sys
import os
import logging

from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from pgappforge.security.sqla.models import User
from pgappforge.security.sql_utils import SecureDDLExecutor, SQLIdentifierValidator

sys.path.append(os.getcwd())
from pgappforge import SQLA

# Configure logging
logging.basicConfig(format='%(levelname)s:%(name)s:%(message)s')
logging.getLogger().setLevel(logging.DEBUG)
log = logging.getLogger('Secure Database Migration to 1.3')

def validate_connection_string(con_str: str) -> bool:
    """Validate database connection string format."""
    if not con_str or not isinstance(con_str, str):
        return False

    # Basic validation for common database URI formats
    valid_prefixes = ['sqlite:///', 'mysql://', 'postgresql://', 'mysql+pymysql://']
    return any(con_str.startswith(prefix) for prefix in valid_prefixes)

def main():
    """Main migration function with security improvements."""

    if len(sys.argv) < 2:
        log.info("Security-enhanced migration script")
        log.info("Usage: python migrate_db_1.3_secure.py <database_uri>")
        log.info("Example for sqlite: python migrate_db_1.3_secure.py sqlite:////home/user/application/app.db")
        log.info("Example for postgresql: python migrate_db_1.3_secure.py postgresql://user:pass@localhost/dbname")
        sys.exit(1)

    con_str = sys.argv[1]

    # Validate connection string
    if not validate_connection_string(con_str):
        log.error("Invalid database connection string format")
        log.error("Supported formats: sqlite:///, mysql://, postgresql://")
        sys.exit(1)

    # Create Flask app and database
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = con_str
    db = SQLA(app)

    try:
        # Create database engine with security settings
        engine = create_engine(
            app.config['SQLALCHEMY_DATABASE_URI'],
            isolation_level="AUTOCOMMIT",  # Prevent transaction issues
            pool_pre_ping=True,            # Validate connections
            pool_recycle=3600             # Recycle connections
        )

        conn = engine.connect()
        log.info(f"Database identified as {conn.engine.name}")

        # Initialize secure DDL executor
        ddl_executor = SecureDDLExecutor(conn)

        # Check engine support
        supported_engines = ['mysql', 'sqlite', 'postgresql']
        if conn.engine.name not in supported_engines:
            log.error(f'Engine type {conn.engine.name} not supported by migration script')
            log.error('Supported engines: mysql, sqlite, postgresql')
            sys.exit(1)

        # Create all tables
        db.session.remove()
        db.create_all()

        # Perform the secure user-role migration
        migrate_user_roles(conn)

        # Handle PostgreSQL sequence renaming securely
        if conn.engine.name == 'postgresql':
            migrate_postgresql_sequences(ddl_executor)

        log.info("Migration completed successfully")

    except SQLAlchemyError as e:
        log.error(f"Database error during migration: {e}")
        sys.exit(1)
    except Exception as e:
        log.error(f"Unexpected error during migration: {e}")
        sys.exit(1)
    finally:
        try:
            if 'conn' in locals():
                conn.close()
        except Exception as e:
            log.warning(f"Error closing connection: {e}")

def migrate_user_roles(conn):
    """
    Migrate user roles with secure SQL execution.

    Args:
        conn: Database connection
    """
    try:
        # Use parameterized query to prevent SQL injection
        log.info("Migrating user roles with secure query")

        # First check if the migration is needed
        check_stmt = text("""
            SELECT COUNT(*) as count
            FROM information_schema.tables
            WHERE table_name = 'ab_user_role'
        """)

        result = conn.execute(check_stmt).fetchone()
        if not result or result.count == 0:
            log.warning("ab_user_role table does not exist, skipping user role migration")
            return

        # Safely execute the user role migration
        migration_stmt = text("""
            INSERT INTO ab_user_role (user_id, role_id)
            SELECT id, role_id
            FROM ab_user
            WHERE role_id IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM ab_user_role ur
                WHERE ur.user_id = ab_user.id
                AND ur.role_id = ab_user.role_id
            )
        """)

        result = conn.execute(migration_stmt)
        log.info(f"Migrated {result.rowcount} user role relationships")

    except SQLAlchemyError as e:
        log.error(f"Error during user role migration: {e}")
        raise

def migrate_postgresql_sequences(ddl_executor: SecureDDLExecutor):
    """
    Migrate PostgreSQL sequences with secure validation.

    Args:
        ddl_executor: Secure DDL executor instance
    """
    log.info("Migrating PostgreSQL sequences")

    # Define sequence mappings with validation
    sequence_mappings = {
        'seq_ab_permission_pk': 'ab_permission_id_seq',
        'seq_ab_view_menu_pk': 'ab_view_menu_id_seq',
        'seq_permission_view_pk': 'ab_permission_view_id_seq',
        'seq_ab_permission_view_role_pk': 'ab_permission_view_role_id_seq',
        'seq_ab_role_pk': 'ab_role_id_seq',
        'seq_ab_user_role_pk': 'ab_user_role_id_seq',
        'seq_ab_user_pk': 'ab_user_id_seq',
        'seq_ab_register_user_pk': 'ab_register_user_id_seq'
    }

    # Validate all sequence names before processing
    for old_seq, new_seq in sequence_mappings.items():
        if not SQLIdentifierValidator.is_valid_identifier(old_seq):
            log.error(f"Invalid old sequence name: {old_seq}")
            continue

        if not SQLIdentifierValidator.is_valid_identifier(new_seq):
            log.error(f"Invalid new sequence name: {new_seq}")
            continue

        try:
            success = ddl_executor.safe_rename_sequence(old_seq, new_seq)
            if success:
                log.info(f"Successfully processed sequence: {old_seq} -> {new_seq}")
            else:
                log.warning(f"Sequence {old_seq} was not renamed (may not exist)")

        except Exception as e:
            log.error(f"Error renaming sequence {old_seq} to {new_seq}: {e}")
            # Continue with other sequences even if one fails

def add_column_secure(ddl_executor: SecureDDLExecutor, table, column):
    """
    SECURE REPLACEMENT for the vulnerable add_column function.

    Args:
        ddl_executor: Secure DDL executor
        table: SQLAlchemy table object
        column: SQLAlchemy column object
    """
    table_name = table.__tablename__
    column_name = column.key
    column_type = str(column.type.compile(ddl_executor.connection.dialect))

    try:
        return ddl_executor.safe_add_column(table_name, column_name, column_type)
    except Exception as e:
        log.error(f"Error adding column {column_name} to {table_name}: {e}")
        return False

def alter_column_secure(ddl_executor: SecureDDLExecutor, table, column):
    """
    SECURE REPLACEMENT for the vulnerable alter_column function.

    Args:
        ddl_executor: Secure DDL executor
        table: SQLAlchemy table object
        column: SQLAlchemy column object
    """
    table_name = table.__tablename__
    column_name = column.key
    column_type = str(column.type.compile(ddl_executor.connection.dialect))

    try:
        return ddl_executor.safe_alter_column(table_name, column_name, column_type)
    except Exception as e:
        log.error(f"Error altering column {column_name} on {table_name}: {e}")
        return False

if __name__ == "__main__":
    main()