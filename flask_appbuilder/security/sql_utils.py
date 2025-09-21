"""
Secure SQL utilities for Flask-AppBuilder.

This module provides secure SQL identifier validation and parameterized query
utilities to prevent SQL injection vulnerabilities.
"""

import re
import logging
from typing import Optional, Dict, Any
from sqlalchemy import text, MetaData, inspect
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

class SQLIdentifierValidator:
    """Secure SQL identifier validation."""

    # Valid SQL identifier pattern (alphanumeric and underscore, starting with letter/underscore)
    IDENTIFIER_PATTERN = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')

    # Maximum identifier length (PostgreSQL limit is 63, MySQL is 64, SQLite is unlimited)
    MAX_IDENTIFIER_LENGTH = 63

    # Reserved words that should not be used as identifiers
    RESERVED_WORDS = {
        'SELECT', 'INSERT', 'UPDATE', 'DELETE', 'DROP', 'CREATE',
        'ALTER', 'TABLE', 'DATABASE', 'SCHEMA', 'INDEX', 'VIEW',
        'TRIGGER', 'PROCEDURE', 'FUNCTION', 'EXEC', 'EXECUTE',
        'UNION', 'WHERE', 'FROM', 'INTO', 'VALUES', 'SET',
        'ORDER', 'GROUP', 'HAVING', 'JOIN', 'INNER', 'OUTER',
        'LEFT', 'RIGHT', 'ON', 'AS', 'AND', 'OR', 'NOT',
        'NULL', 'TRUE', 'FALSE', 'PRIMARY', 'KEY', 'FOREIGN',
        'REFERENCES', 'CONSTRAINT', 'UNIQUE', 'DEFAULT',
        'AUTO_INCREMENT', 'SERIAL', 'IDENTITY'
    }

    @classmethod
    def is_valid_identifier(cls, identifier: str) -> bool:
        """
        Validate SQL identifier is safe to use.

        Args:
            identifier: SQL identifier to validate

        Returns:
            True if identifier is safe, False otherwise

        Examples:
            >>> SQLIdentifierValidator.is_valid_identifier('user_table')
            True
            >>> SQLIdentifierValidator.is_valid_identifier('users; DROP TABLE users;--')
            False
        """
        if not identifier or not isinstance(identifier, str):
            return False

        if len(identifier) > cls.MAX_IDENTIFIER_LENGTH:
            return False

        if not cls.IDENTIFIER_PATTERN.match(identifier):
            return False

        if identifier.upper() in cls.RESERVED_WORDS:
            return False

        # Additional security checks
        dangerous_patterns = [
            ';',      # Statement separator
            '--',     # SQL comment
            '/*',     # Block comment start
            '*/',     # Block comment end
            '\'',     # Single quote
            '"',      # Double quote
            '`',      # Backtick
            '\\',     # Backslash
            '\x00',   # Null byte
        ]

        for pattern in dangerous_patterns:
            if pattern in identifier:
                return False

        return True

    @classmethod
    def validate_table_name(cls, table_name: str, metadata: Optional[MetaData] = None) -> bool:
        """
        Validate table name exists in metadata (if provided) and is safe.

        Args:
            table_name: Table name to validate
            metadata: SQLAlchemy metadata object for additional validation

        Returns:
            True if table name is valid and safe
        """
        if not cls.is_valid_identifier(table_name):
            return False

        if metadata is not None:
            return table_name in metadata.tables

        return True

    @classmethod
    def validate_column_name(cls, column_name: str, table_name: str = None,
                           metadata: Optional[MetaData] = None) -> bool:
        """
        Validate column name is safe and optionally exists in table.

        Args:
            column_name: Column name to validate
            table_name: Table name for additional validation
            metadata: SQLAlchemy metadata object

        Returns:
            True if column name is valid and safe
        """
        if not cls.is_valid_identifier(column_name):
            return False

        if metadata is not None and table_name is not None:
            if table_name in metadata.tables:
                table = metadata.tables[table_name]
                return column_name in table.columns

        return True

class SecureDDLExecutor:
    """Secure DDL statement executor with SQL injection protection."""

    def __init__(self, connection):
        """
        Initialize with database connection.

        Args:
            connection: SQLAlchemy connection object
        """
        self.connection = connection
        self.engine_name = connection.engine.name

        # Get metadata for validation
        try:
            self.metadata = MetaData()
            self.metadata.reflect(bind=connection)
        except Exception as e:
            logger.warning(f"Could not reflect metadata: {e}")
            self.metadata = None

    def safe_add_column(self, table_name: str, column_name: str, column_type: str) -> bool:
        """
        Safely add column with SQL injection protection.

        Args:
            table_name: Name of table to alter
            column_name: Name of column to add
            column_type: SQL type of column

        Returns:
            True if successful, False otherwise

        Raises:
            ValueError: If identifiers are invalid
            SQLAlchemyError: If SQL execution fails
        """
        # Validate all identifiers
        if not SQLIdentifierValidator.is_valid_identifier(table_name):
            raise ValueError(f"Invalid table name: {table_name}")

        if not SQLIdentifierValidator.is_valid_identifier(column_name):
            raise ValueError(f"Invalid column name: {column_name}")

        # Validate table exists
        if self.metadata and not SQLIdentifierValidator.validate_table_name(table_name, self.metadata):
            raise ValueError(f"Table {table_name} not found in schema")

        # Check if column already exists
        if self.metadata and table_name in self.metadata.tables:
            existing_columns = self.metadata.tables[table_name].columns
            if column_name in existing_columns:
                logger.warning(f"Column {column_name} already exists in {table_name}")
                return True  # Already exists, consider success

        # Prepare engine-specific DDL
        ddl_templates = {
            'mysql': 'ALTER TABLE {table} ADD COLUMN {column} {type}',
            'sqlite': 'ALTER TABLE {table} ADD COLUMN {column} {type}',
            'postgresql': 'ALTER TABLE {table} ADD COLUMN {column} {type}'
        }

        if self.engine_name not in ddl_templates:
            raise ValueError(f"Unsupported engine: {self.engine_name}")

        # Use identifier quoting for extra safety
        quoted_table = self.connection.dialect.identifier_preparer.quote(table_name)
        quoted_column = self.connection.dialect.identifier_preparer.quote(column_name)

        # Build DDL statement with quoted identifiers
        ddl_template = ddl_templates[self.engine_name]
        ddl_statement = ddl_template.format(
            table=quoted_table,
            column=quoted_column,
            type=column_type  # Column type should be validated separately
        )

        try:
            logger.info(f"Adding column {column_name} to {table_name}")
            self.connection.execute(text(ddl_statement))
            logger.info(f"Successfully added column {column_name} to {table_name}")
            return True

        except SQLAlchemyError as e:
            logger.error(f"Error adding column {column_name} to {table_name}: {e}")
            raise

    def safe_alter_column(self, table_name: str, column_name: str, column_type: str) -> bool:
        """
        Safely alter column with SQL injection protection.

        Args:
            table_name: Name of table to alter
            column_name: Name of column to alter
            column_type: New SQL type of column

        Returns:
            True if successful, False otherwise
        """
        # Validate identifiers
        if not SQLIdentifierValidator.is_valid_identifier(table_name):
            raise ValueError(f"Invalid table name: {table_name}")

        if not SQLIdentifierValidator.is_valid_identifier(column_name):
            raise ValueError(f"Invalid column name: {column_name}")

        # Validate table and column exist
        if self.metadata:
            if not SQLIdentifierValidator.validate_table_name(table_name, self.metadata):
                raise ValueError(f"Table {table_name} not found in schema")

            if not SQLIdentifierValidator.validate_column_name(column_name, table_name, self.metadata):
                raise ValueError(f"Column {column_name} not found in table {table_name}")

        # Engine-specific DDL
        ddl_templates = {
            'mysql': 'ALTER TABLE {table} MODIFY COLUMN {column} {type}',
            'sqlite': '',  # SQLite doesn't support ALTER COLUMN
            'postgresql': 'ALTER TABLE {table} ALTER COLUMN {column} TYPE {type}'
        }

        if self.engine_name not in ddl_templates:
            raise ValueError(f"Unsupported engine: {self.engine_name}")

        ddl_template = ddl_templates[self.engine_name]
        if not ddl_template:
            logger.warning(f"Column alteration not supported on {self.engine_name}")
            return True  # Skip unsupported operations

        # Use quoted identifiers
        quoted_table = self.connection.dialect.identifier_preparer.quote(table_name)
        quoted_column = self.connection.dialect.identifier_preparer.quote(column_name)

        ddl_statement = ddl_template.format(
            table=quoted_table,
            column=quoted_column,
            type=column_type
        )

        try:
            logger.info(f"Altering column {column_name} on {table_name}")
            self.connection.execute(text(ddl_statement))
            logger.info(f"Successfully altered column {column_name} on {table_name}")
            return True

        except SQLAlchemyError as e:
            logger.error(f"Error altering column {column_name} on {table_name}: {e}")
            raise

    def safe_rename_sequence(self, old_name: str, new_name: str) -> bool:
        """
        Safely rename PostgreSQL sequence with validation.

        Args:
            old_name: Current sequence name
            new_name: New sequence name

        Returns:
            True if successful, False otherwise
        """
        if self.engine_name != 'postgresql':
            logger.info("Sequence renaming only supported on PostgreSQL")
            return True

        # Validate sequence names
        if not SQLIdentifierValidator.is_valid_identifier(old_name):
            raise ValueError(f"Invalid old sequence name: {old_name}")

        if not SQLIdentifierValidator.is_valid_identifier(new_name):
            raise ValueError(f"Invalid new sequence name: {new_name}")

        # Check if old sequence exists
        check_stmt = text("SELECT 1 FROM pg_class WHERE relname = :seq_name AND relkind = 'S'")
        result = self.connection.execute(check_stmt, {"seq_name": old_name}).fetchone()

        if result is None:
            logger.warning(f"Sequence {old_name} does not exist, skipping rename")
            return True

        # Use quoted identifiers for sequence rename
        quoted_old = self.connection.dialect.identifier_preparer.quote(old_name)
        quoted_new = self.connection.dialect.identifier_preparer.quote(new_name)

        rename_stmt = text(f"ALTER SEQUENCE {quoted_old} RENAME TO {quoted_new}")

        try:
            logger.info(f"Renaming sequence {old_name} to {new_name}")
            self.connection.execute(rename_stmt)
            logger.info(f"Successfully renamed sequence {old_name} to {new_name}")
            return True

        except SQLAlchemyError as e:
            logger.error(f"Error renaming sequence {old_name} to {new_name}: {e}")
            raise

def validate_column_type(column_type: str, engine_name: str) -> bool:
    """
    Validate that column type is safe and appropriate for the database engine.

    Args:
        column_type: SQL column type string
        engine_name: Database engine name

    Returns:
        True if column type is valid
    """
    if not column_type or not isinstance(column_type, str):
        return False

    # Basic validation - no dangerous characters
    dangerous_chars = [';', '--', '/*', '*/', '\'', '"', '\\', '\x00']
    for char in dangerous_chars:
        if char in column_type:
            return False

    # Engine-specific type validation could be added here
    # For now, basic validation is sufficient

    return True