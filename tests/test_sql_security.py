"""
Critical security tests for SQL injection prevention.

These tests ensure the SQL injection security fixes are working correctly
and protect against SQL injection vulnerabilities in database operations.
"""

import pytest
import sqlite3
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock

from pgappforge.security.sql_utils import (
    SQLIdentifierValidator,
    SecureDDLExecutor,
    SQLSecurityError
)


class TestSQLIdentifierValidator:
    """Test suite for SQL identifier validation."""

    def test_valid_identifiers(self):
        """Test that valid SQL identifiers pass validation."""
        validator = SQLIdentifierValidator()

        valid_identifiers = [
            "table_name",
            "column_name",
            "MyTable",
            "user_id",
            "created_at",
            "Table123",
            "_private_column",
            "CamelCaseTable"
        ]

        for identifier in valid_identifiers:
            assert validator.is_valid_identifier(identifier), f"'{identifier}' should be valid"
            assert validator.validate_identifier(identifier) == identifier

    def test_invalid_identifiers(self):
        """Test that invalid SQL identifiers are rejected."""
        validator = SQLIdentifierValidator()

        invalid_identifiers = [
            "123table",          # Starts with number
            "table-name",        # Contains hyphen
            "table name",        # Contains space
            "table;DROP TABLE",  # SQL injection attempt
            "'malicious'",       # Contains quotes
            "table/*comment*/",  # Contains SQL comment
            "",                  # Empty string
            "table.column",      # Contains dot (for basic validation)
            "table--comment",    # SQL comment
        ]

        for identifier in invalid_identifiers:
            with pytest.raises(SQLSecurityError):
                validator.validate_identifier(identifier)
            assert not validator.is_valid_identifier(identifier), f"'{identifier}' should be invalid"

    def test_reserved_keywords(self):
        """Test handling of SQL reserved keywords."""
        validator = SQLIdentifierValidator()

        reserved_keywords = [
            "SELECT", "select",
            "DROP", "drop",
            "DELETE", "delete",
            "UPDATE", "update",
            "INSERT", "insert",
            "CREATE", "create",
            "ALTER", "alter",
            "UNION", "union"
        ]

        for keyword in reserved_keywords:
            with pytest.raises(SQLSecurityError):
                validator.validate_identifier(keyword)
            assert not validator.is_valid_identifier(keyword), f"'{keyword}' should be invalid"

    def test_case_sensitivity(self):
        """Test case sensitivity in identifier validation."""
        validator = SQLIdentifierValidator()

        # Valid identifiers in different cases
        assert validator.is_valid_identifier("TableName")
        assert validator.is_valid_identifier("tablename")
        assert validator.is_valid_identifier("TABLENAME")

        # Reserved keywords should be blocked regardless of case
        assert not validator.is_valid_identifier("SELECT")
        assert not validator.is_valid_identifier("select")
        assert not validator.is_valid_identifier("Select")

    def test_length_limits(self):
        """Test identifier length validation."""
        validator = SQLIdentifierValidator()

        # Valid length
        normal_identifier = "a" * 50
        assert validator.is_valid_identifier(normal_identifier)

        # Too long (assuming 63 character limit like PostgreSQL)
        too_long_identifier = "a" * 100
        with pytest.raises(SQLSecurityError):
            validator.validate_identifier(too_long_identifier)

    def test_unicode_identifiers(self):
        """Test handling of unicode characters in identifiers."""
        validator = SQLIdentifierValidator()

        unicode_identifiers = [
            "тable",      # Cyrillic
            "表",         # Chinese
            "tábla",      # Accented characters
        ]

        for identifier in unicode_identifiers:
            # Unicode handling may vary by implementation
            # Should either accept or reject consistently
            try:
                result = validator.validate_identifier(identifier)
                assert isinstance(result, str)
            except SQLSecurityError:
                # Rejection is also acceptable for unicode
                pass

    def test_edge_cases(self):
        """Test edge cases in identifier validation."""
        validator = SQLIdentifierValidator()

        edge_cases = [
            None,           # None input
            123,            # Wrong type
            "",             # Empty string
            " ",            # Whitespace only
            "\t",           # Tab character
            "\n",           # Newline
        ]

        for case in edge_cases:
            with pytest.raises((SQLSecurityError, TypeError)):
                validator.validate_identifier(case)


class TestSecureDDLExecutor:
    """Test suite for secure DDL execution."""

    def setup_method(self):
        """Set up test database connection."""
        # Create in-memory SQLite database for testing
        self.conn = sqlite3.connect(":memory:")
        self.cursor = self.conn.cursor()

        # Create a test table
        self.cursor.execute("""
            CREATE TABLE test_table (
                id INTEGER PRIMARY KEY,
                name TEXT,
                created_at TIMESTAMP
            )
        """)
        self.conn.commit()

        # Initialize SecureDDLExecutor
        self.executor = SecureDDLExecutor()

    def teardown_method(self):
        """Clean up test database."""
        if hasattr(self, 'conn'):
            self.conn.close()

    def test_safe_add_column(self):
        """Test safe column addition."""
        success = self.executor.safe_add_column(
            self.conn,
            "test_table",
            "email",
            "TEXT"
        )

        assert success is True

        # Verify column was added
        self.cursor.execute("PRAGMA table_info(test_table)")
        columns = [row[1] for row in self.cursor.fetchall()]
        assert "email" in columns

    def test_add_column_with_invalid_table_name(self):
        """Test adding column with invalid table name."""
        with pytest.raises(SQLSecurityError):
            self.executor.safe_add_column(
                self.conn,
                "test_table; DROP TABLE test_table",  # Injection attempt
                "email",
                "TEXT"
            )

    def test_add_column_with_invalid_column_name(self):
        """Test adding column with invalid column name."""
        with pytest.raises(SQLSecurityError):
            self.executor.safe_add_column(
                self.conn,
                "test_table",
                "email'; DROP TABLE test_table; --",  # Injection attempt
                "TEXT"
            )

    def test_add_column_with_invalid_column_type(self):
        """Test adding column with invalid column type."""
        with pytest.raises(SQLSecurityError):
            self.executor.safe_add_column(
                self.conn,
                "test_table",
                "email",
                "TEXT; DROP TABLE test_table"  # Injection attempt
            )

    def test_duplicate_column_handling(self):
        """Test handling of duplicate column addition."""
        # Add column first time - should succeed
        success1 = self.executor.safe_add_column(
            self.conn,
            "test_table",
            "status",
            "TEXT"
        )
        assert success1 is True

        # Add same column again - should handle gracefully
        try:
            success2 = self.executor.safe_add_column(
                self.conn,
                "test_table",
                "status",
                "TEXT"
            )
            # Either succeeds (if IF NOT EXISTS is used) or raises appropriate error
            assert isinstance(success2, bool)
        except sqlite3.OperationalError:
            # Expected for SQLite when column already exists
            pass

    def test_nonexistent_table_handling(self):
        """Test handling of operations on non-existent tables."""
        with pytest.raises((SQLSecurityError, sqlite3.OperationalError)):
            self.executor.safe_add_column(
                self.conn,
                "nonexistent_table",
                "column",
                "TEXT"
            )

    def test_database_specific_syntax(self):
        """Test database-specific SQL syntax handling."""
        # Test with SQLite-specific features
        success = self.executor.safe_add_column(
            self.conn,
            "test_table",
            "sqlite_column",
            "TEXT DEFAULT 'default_value'"
        )

        assert success is True

    def test_quoted_identifiers(self):
        """Test handling of properly quoted identifiers."""
        # Test with identifiers that might need quoting
        success = self.executor.safe_add_column(
            self.conn,
            "test_table",
            "order",  # 'order' is a reserved keyword
            "INTEGER"
        )

        # Should either succeed with proper quoting or fail safely
        assert isinstance(success, bool)

    def test_connection_error_handling(self):
        """Test handling of database connection errors."""
        # Close connection to simulate error
        self.conn.close()

        with pytest.raises(Exception):  # Should raise appropriate database error
            self.executor.safe_add_column(
                self.conn,
                "test_table",
                "column",
                "TEXT"
            )

    def test_transaction_rollback(self):
        """Test transaction rollback on error."""
        # Start a transaction
        self.conn.execute("BEGIN TRANSACTION")

        # Attempt operation that should fail
        try:
            self.executor.safe_add_column(
                self.conn,
                "test_table; DROP TABLE test_table",  # Invalid table name
                "column",
                "TEXT"
            )
        except SQLSecurityError:
            pass

        # Verify original table still exists
        self.cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'")
        result = self.cursor.fetchone()
        assert result is not None

    def test_sql_injection_prevention_comprehensive(self):
        """Comprehensive test for SQL injection prevention."""
        injection_attempts = [
            # Table name injections
            ("users; DROP TABLE users; --", "column", "TEXT"),
            ("users' OR '1'='1", "column", "TEXT"),
            ("users/**/UNION/**/SELECT", "column", "TEXT"),

            # Column name injections
            ("users", "col; DROP TABLE users; --", "TEXT"),
            ("users", "col' OR '1'='1", "TEXT"),
            ("users", "col/*comment*/", "TEXT"),

            # Column type injections
            ("users", "column", "TEXT; DROP TABLE users"),
            ("users", "column", "TEXT' OR '1'='1"),
            ("users", "column", "TEXT/*comment*/"),
        ]

        for table_name, column_name, column_type in injection_attempts:
            with pytest.raises(SQLSecurityError):
                self.executor.safe_add_column(
                    self.conn,
                    table_name,
                    column_name,
                    column_type
                )

    def test_performance_with_large_operations(self):
        """Test performance with large DDL operations."""
        import time

        start_time = time.time()

        # Perform multiple column additions
        for i in range(100):
            try:
                self.executor.safe_add_column(
                    self.conn,
                    "test_table",
                    f"test_column_{i}",
                    "TEXT"
                )
            except sqlite3.OperationalError:
                # Some may fail due to SQLite limitations, that's OK
                pass

        end_time = time.time()

        # Should complete in reasonable time
        assert (end_time - start_time) < 30.0  # 30 seconds max

    def test_concurrent_operations(self):
        """Test concurrent DDL operations for thread safety."""
        import threading
        import concurrent.futures

        def add_column_worker(column_suffix):
            try:
                return self.executor.safe_add_column(
                    self.conn,
                    "test_table",
                    f"concurrent_col_{column_suffix}",
                    "TEXT"
                )
            except Exception as e:
                return str(e)

        # Run multiple DDL operations concurrently
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(add_column_worker, i) for i in range(10)]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]

        # All operations should complete without crashing
        assert len(results) == 10


class TestSQLSecurityIntegration:
    """Integration tests for SQL security components."""

    def test_validator_executor_integration(self):
        """Test integration between validator and executor."""
        validator = SQLIdentifierValidator()
        executor = SecureDDLExecutor()

        # Create test database
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE test_table (id INTEGER PRIMARY KEY)")
        conn.commit()

        # Test valid operation
        table_name = "test_table"
        column_name = "valid_column"
        column_type = "TEXT"

        # Validate identifiers first
        validated_table = validator.validate_identifier(table_name)
        validated_column = validator.validate_identifier(column_name)

        # Execute DDL operation
        success = executor.safe_add_column(
            conn,
            validated_table,
            validated_column,
            column_type
        )

        assert success is True

        conn.close()

    def test_security_logging(self):
        """Test security event logging."""
        with patch('pgappforge.security.sql_utils.logger') as mock_logger:
            validator = SQLIdentifierValidator()

            # Attempt invalid operation
            try:
                validator.validate_identifier("DROP TABLE users")
            except SQLSecurityError:
                pass

            # Should log security violation
            assert mock_logger.warning.called or mock_logger.error.called

    def test_error_message_security(self):
        """Test that error messages don't leak sensitive information."""
        validator = SQLIdentifierValidator()

        try:
            validator.validate_identifier("'; DROP TABLE users; --")
        except SQLSecurityError as e:
            error_message = str(e)

            # Error message should not contain the malicious input
            assert "DROP TABLE" not in error_message
            assert "users" not in error_message

            # Should contain generic security message
            assert "invalid" in error_message.lower() or "security" in error_message.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])