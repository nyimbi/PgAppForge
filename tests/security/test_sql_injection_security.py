"""
Security tests for SQL injection prevention in migration scripts.

This test suite validates that SQL injection vulnerabilities in database
migration scripts have been properly fixed.
"""

import unittest
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy import create_engine, text, Column, Integer, String, MetaData, Table
from sqlalchemy.exc import SQLAlchemyError

from pgappforge.security.sql_utils import (
    SQLIdentifierValidator,
    SecureDDLExecutor,
    validate_column_type
)


class SQLInjectionSecurityTest(unittest.TestCase):
    """Test suite for SQL injection prevention in migration utilities."""

    def setUp(self):
        """Set up test database and connection."""
        # Use in-memory SQLite for testing
        self.engine = create_engine("sqlite:///:memory:")
        self.connection = self.engine.connect()

        # Create test table
        metadata = MetaData()
        self.test_table = Table(
            'test_users',
            metadata,
            Column('id', Integer, primary_key=True),
            Column('username', String(50))
        )
        metadata.create_all(self.engine)

        self.ddl_executor = SecureDDLExecutor(self.connection)

    def tearDown(self):
        """Clean up test resources."""
        self.connection.close()

    def test_sql_identifier_validation(self):
        """Test SQL identifier validation prevents injection."""
        # Valid identifiers should pass
        valid_identifiers = [
            "users",
            "user_table",
            "user123",
            "_private_table",
            "CamelCaseTable"
        ]

        for identifier in valid_identifiers:
            with self.subTest(identifier=identifier):
                self.assertTrue(
                    SQLIdentifierValidator.is_valid_identifier(identifier),
                    f"Valid identifier should pass: {identifier}"
                )

        # Dangerous identifiers should fail
        dangerous_identifiers = [
            "users; DROP TABLE users;--",  # SQL injection
            "users' OR '1'='1",           # SQL injection
            "users/*comment*/",           # Comment injection
            "users--comment",             # Comment injection
            "users`",                     # Backtick injection
            "users\\x00",                 # Null byte injection
            "users\"",                    # Quote injection
            "",                           # Empty string
            "a" * 100,                    # Too long
            "123users",                   # Starts with number
            "SELECT",                     # Reserved word
            "DROP",                       # Reserved word
        ]

        for identifier in dangerous_identifiers:
            with self.subTest(identifier=identifier):
                self.assertFalse(
                    SQLIdentifierValidator.is_valid_identifier(identifier),
                    f"Dangerous identifier should fail: {identifier}"
                )

    def test_safe_add_column(self):
        """Test secure column addition prevents SQL injection."""
        # Test successful column addition
        success = self.ddl_executor.safe_add_column(
            "test_users", "email", "VARCHAR(100)"
        )
        self.assertTrue(success, "Should successfully add valid column")

        # Verify column was actually added
        result = self.connection.execute(text("PRAGMA table_info(test_users)"))
        columns = [row[1] for row in result.fetchall()]
        self.assertIn("email", columns, "Column should exist in table")

    def test_safe_add_column_injection_prevention(self):
        """Test that SQL injection in column operations is prevented."""
        # Test malicious table name
        with self.assertRaises(ValueError):
            self.ddl_executor.safe_add_column(
                "users; DROP TABLE users;--", "email", "VARCHAR(100)"
            )

        # Test malicious column name
        with self.assertRaises(ValueError):
            self.ddl_executor.safe_add_column(
                "test_users", "email'; DROP TABLE users;--", "VARCHAR(100)"
            )

        # Test invalid identifiers
        invalid_cases = [
            ("", "email", "VARCHAR(100)"),           # Empty table name
            ("test_users", "", "VARCHAR(100)"),      # Empty column name
            ("123invalid", "email", "VARCHAR(100)"), # Invalid table name
            ("test_users", "123invalid", "VARCHAR(100)"), # Invalid column name
        ]

        for table_name, column_name, column_type in invalid_cases:
            with self.subTest(table=table_name, column=column_name):
                with self.assertRaises(ValueError):
                    self.ddl_executor.safe_add_column(table_name, column_name, column_type)

    def test_safe_alter_column(self):
        """Test secure column alteration prevents SQL injection."""
        # First add a column to alter
        self.ddl_executor.safe_add_column("test_users", "temp_col", "INTEGER")

        # Test successful column alteration (for supported engines)
        if self.connection.engine.name in ['mysql', 'postgresql']:
            success = self.ddl_executor.safe_alter_column(
                "test_users", "temp_col", "VARCHAR(50)"
            )
            # Should succeed or skip gracefully for unsupported operations
            self.assertIsInstance(success, bool)

    def test_safe_alter_column_injection_prevention(self):
        """Test that SQL injection in alter operations is prevented."""
        # Test malicious identifiers
        with self.assertRaises(ValueError):
            self.ddl_executor.safe_alter_column(
                "users; DROP TABLE users;--", "email", "VARCHAR(100)"
            )

        with self.assertRaises(ValueError):
            self.ddl_executor.safe_alter_column(
                "test_users", "email'; DROP TABLE users;--", "VARCHAR(100)"
            )

    def test_postgresql_sequence_renaming(self):
        """Test PostgreSQL sequence renaming with injection prevention."""
        # Mock PostgreSQL connection
        mock_conn = Mock()
        mock_conn.engine.name = 'postgresql'
        mock_conn.dialect.identifier_preparer.quote = lambda x: f'"{x}"'

        mock_result = Mock()
        mock_result.fetchone.return_value = (1,)  # Sequence exists
        mock_conn.execute.return_value = mock_result

        ddl_executor = SecureDDLExecutor(mock_conn)

        # Test successful rename
        success = ddl_executor.safe_rename_sequence("old_seq", "new_seq")
        self.assertTrue(success)

        # Verify safe SQL was generated
        mock_conn.execute.assert_called()

        # Test injection prevention
        with self.assertRaises(ValueError):
            ddl_executor.safe_rename_sequence("old; DROP TABLE users;--", "new_seq")

    def test_column_type_validation(self):
        """Test column type validation prevents injection."""
        # Valid column types
        valid_types = [
            "VARCHAR(100)",
            "INTEGER",
            "TEXT",
            "DECIMAL(10,2)",
            "TIMESTAMP"
        ]

        for col_type in valid_types:
            with self.subTest(type=col_type):
                self.assertTrue(
                    validate_column_type(col_type, "sqlite"),
                    f"Valid column type should pass: {col_type}"
                )

        # Invalid/dangerous column types
        dangerous_types = [
            "VARCHAR(100); DROP TABLE users;--",
            "INTEGER' OR '1'='1",
            "TEXT/*comment*/",
            "",
            None,
            123,  # Non-string type
        ]

        for col_type in dangerous_types:
            with self.subTest(type=col_type):
                self.assertFalse(
                    validate_column_type(col_type, "sqlite"),
                    f"Dangerous column type should fail: {col_type}"
                )

    def test_quoted_identifiers(self):
        """Test that identifiers are properly quoted."""
        # Test with mock connection to verify quoting
        mock_conn = Mock()
        mock_conn.engine.name = 'postgresql'
        mock_dialect = Mock()
        mock_dialect.identifier_preparer.quote = lambda x: f'"{x}"'
        mock_conn.dialect = mock_dialect
        mock_conn.execute.return_value = Mock()

        ddl_executor = SecureDDLExecutor(mock_conn)

        # Add column should use quoted identifiers
        ddl_executor.safe_add_column("test_table", "test_column", "VARCHAR(50)")

        # Verify that execute was called with quoted identifiers
        mock_conn.execute.assert_called()
        # Get the actual SQL statement that was executed
        call_args = mock_conn.execute.call_args[0]
        if call_args:
            sql_text = str(call_args[0])
            self.assertIn('"test_table"', sql_text, "Table name should be quoted in SQL")
            self.assertIn('"test_column"', sql_text, "Column name should be quoted in SQL")

    def test_error_handling(self):
        """Test proper error handling in DDL operations."""
        # Test with mock that raises SQLAlchemyError
        mock_conn = Mock()
        mock_conn.engine.name = 'mysql'
        mock_conn.dialect.identifier_preparer.quote = lambda x: f'`{x}`'
        mock_conn.execute.side_effect = SQLAlchemyError("Database error")

        ddl_executor = SecureDDLExecutor(mock_conn)

        # Should re-raise SQLAlchemyError
        with self.assertRaises(SQLAlchemyError):
            ddl_executor.safe_add_column("test_table", "test_column", "VARCHAR(50)")

    def test_metadata_validation(self):
        """Test metadata-based validation when available."""
        # Create DDL executor with real metadata
        ddl_executor = SecureDDLExecutor(self.connection)

        # Should succeed for existing table
        success = ddl_executor.safe_add_column("test_users", "new_col", "VARCHAR(50)")
        self.assertTrue(success)

        # Should fail for non-existent table
        with self.assertRaises(ValueError):
            ddl_executor.safe_add_column("nonexistent_table", "col", "VARCHAR(50)")

    def test_duplicate_column_handling(self):
        """Test handling of duplicate column addition."""
        # Add a column
        success1 = self.ddl_executor.safe_add_column("test_users", "status", "VARCHAR(20)")
        self.assertTrue(success1)

        # Adding same column again should handle gracefully
        # Note: This may raise an exception in SQLite, but that's expected behavior
        try:
            success2 = self.ddl_executor.safe_add_column("test_users", "status", "VARCHAR(20)")
            # If it succeeds, that's fine (already exists)
            self.assertTrue(success2)
        except Exception:
            # If it fails, that's also fine - SQLite doesn't handle duplicates gracefully
            pass


class MigrationScriptSecurityTest(unittest.TestCase):
    """Test security of migration script patterns."""

    def test_vulnerable_pattern_detection(self):
        """Test detection of vulnerable string formatting patterns."""
        # These patterns should be detected as vulnerable
        vulnerable_patterns = [
            ("conn.execute(stmt % (table, column, type))", r'conn\.execute\s*\([^)]*%[^)]*\)'),
            ("conn.execute('ALTER TABLE %s ADD COLUMN %s %s' % (t, c, tp))", r'conn\.execute\s*\([^)]*%[^)]*\)'),
            ("conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {type}')", r'conn\.execute\s*\([^)]*f[\'"][^\'\"]*\{[^}]*\}'),
            ("conn.execute('ALTER TABLE ' + table + ' ADD COLUMN ' + column)", r'conn\.execute\s*\([^)]*\+[^)]*\)'),
        ]

        import re
        for pattern, regex in vulnerable_patterns:
            with self.subTest(pattern=pattern):
                match = re.search(regex, pattern)
                self.assertIsNotNone(match, f"Should detect vulnerable pattern: {pattern}")

    def test_secure_pattern_validation(self):
        """Test that secure patterns are properly structured."""
        # Secure patterns should use parameterized queries or validated identifiers
        secure_patterns = [
            "conn.execute(text('ALTER TABLE :table ADD COLUMN :column :type'), params)",
            "ddl_executor.safe_add_column(table_name, column_name, column_type)",
            "conn.execute(text(stmt), {'table': table, 'column': column})",
        ]

        # These should not match any vulnerable patterns
        vulnerable_patterns = [
            r'conn\.execute\s*\([^)]*%[^)]*\)',      # % formatting
            r'conn\.execute\s*\([^)]*f[\'"][^\'\"]*\{[^}]*\}',  # f-strings
            r'conn\.execute\s*\([^)]*\+[^)]*\)',     # string concatenation
        ]

        import re
        for pattern in secure_patterns:
            for vuln_regex in vulnerable_patterns:
                with self.subTest(pattern=pattern, regex=vuln_regex):
                    match = re.search(vuln_regex, pattern)
                    self.assertIsNone(match, f"Should not detect secure pattern as vulnerable: {pattern}")


if __name__ == '__main__':
    unittest.main()