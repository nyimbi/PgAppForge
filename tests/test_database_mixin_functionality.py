#!/usr/bin/env python3
"""
Test Database Session Management with DatabaseMixin

This script tests the DatabaseMixin class to ensure it properly implements
the PgAppForge database session patterns identified in Phase 1.1 of
the remediation plan.
"""

import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from contextlib import contextmanager

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from tests.proper_pgappforge_extensions import DatabaseMixin
    HAS_MAIN_MODULE = True
except ImportError as e:
    print(f"Could not import DatabaseMixin: {e}")
    HAS_MAIN_MODULE = False

class TestDatabaseMixin(unittest.TestCase):
    """Test the DatabaseMixin functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not HAS_MAIN_MODULE:
            self.skipTest("DatabaseMixin not available")
        
        self.mixin = DatabaseMixin()
        
        # Mock PgAppForge session
        self.mock_session = MagicMock()
        self.mock_appbuilder = MagicMock()
        self.mock_appbuilder.get_session = self.mock_session
        self.mixin.appbuilder = self.mock_appbuilder
    
    def test_get_db_session_with_appbuilder(self):
        """Test getting database session when appbuilder is available."""
        session = self.mixin.get_db_session()
        self.assertEqual(session, self.mock_session)
    
    def test_get_db_session_without_appbuilder(self):
        """Test fallback when appbuilder is not available."""
        self.mixin.appbuilder = None
        
        with patch('flask.current_app') as mock_app:
            mock_app.appbuilder.get_session = self.mock_session
            session = self.mixin.get_db_session()
            self.assertEqual(session, self.mock_session)
    
    def test_execute_with_transaction_success(self):
        """Test successful transaction execution."""
        def test_operation(db_session, test_arg):
            self.assertEqual(db_session, self.mock_session)
            self.assertEqual(test_arg, "test_value")
            return "success"
        
        result = self.mixin.execute_with_transaction(test_operation, "test_value")
        
        self.assertEqual(result, "success")
        self.mock_session.commit.assert_called_once()
        self.mock_session.rollback.assert_not_called()
    
    def test_execute_with_transaction_failure(self):
        """Test transaction rollback on failure."""
        def failing_operation(db_session):
            raise ValueError("Test error")
        
        with self.assertRaises(ValueError):
            self.mixin.execute_with_transaction(failing_operation)
        
        self.mock_session.rollback.assert_called_once()
        self.mock_session.commit.assert_not_called()
    
    def test_safe_database_operation_success(self):
        """Test safe operation that returns result on success."""
        def test_operation(db_session):
            return "success"
        
        result = self.mixin.safe_database_operation(test_operation)
        
        self.assertEqual(result, "success")
        self.mock_session.commit.assert_called_once()
    
    def test_safe_database_operation_failure(self):
        """Test safe operation that returns None on failure."""
        def failing_operation(db_session):
            raise ValueError("Test error")
        
        result = self.mixin.safe_database_operation(failing_operation)
        
        self.assertIsNone(result)
        self.mock_session.rollback.assert_called_once()
    
    def test_batch_database_operations_success(self):
        """Test successful batch operations."""
        def op1(db_session, arg1):
            return f"result1_{arg1}"
        
        def op2(db_session, arg2):
            return f"result2_{arg2}"
        
        operations = [
            (op1, ("test1",), {}),
            (op2, ("test2",), {})
        ]
        
        results = self.mixin.batch_database_operations(operations)
        
        self.assertEqual(results, ["result1_test1", "result2_test2"])
        self.mock_session.commit.assert_called_once()
        self.mock_session.rollback.assert_not_called()
    
    def test_batch_database_operations_failure(self):
        """Test batch operations rollback on any failure."""
        def op1(db_session):
            return "result1"
        
        def failing_op(db_session):
            raise ValueError("Batch operation failed")
        
        operations = [
            (op1, (), {}),
            (failing_op, (), {})
        ]
        
        with self.assertRaises(ValueError):
            self.mixin.batch_database_operations(operations)
        
        self.mock_session.rollback.assert_called_once()
        self.mock_session.commit.assert_not_called()


class TestManagerIntegration(unittest.TestCase):
    """Test that managers properly integrate with DatabaseMixin."""
    
    def setUp(self):
        """Set up test fixtures."""
        if not HAS_MAIN_MODULE:
            self.skipTest("Main module not available")
    
    def test_search_manager_inherits_database_mixin(self):
        """Test that SearchManager inherits from DatabaseMixin."""
        from tests.proper_pgappforge_extensions import SearchManager
        
        # Check inheritance
        self.assertTrue(issubclass(SearchManager, DatabaseMixin))
        
        # Check that DatabaseMixin methods are available
        mock_appbuilder = MagicMock()
        manager = SearchManager(mock_appbuilder)
        
        self.assertTrue(hasattr(manager, 'get_db_session'))
        self.assertTrue(hasattr(manager, 'execute_with_transaction'))
        self.assertTrue(hasattr(manager, 'safe_database_operation'))
        self.assertTrue(hasattr(manager, 'batch_database_operations'))
    
    def test_geocoding_manager_inherits_database_mixin(self):
        """Test that GeocodingManager inherits from DatabaseMixin."""
        from tests.proper_pgappforge_extensions import GeocodingManager
        
        # Check inheritance
        self.assertTrue(issubclass(GeocodingManager, DatabaseMixin))
        
        # Check methods available
        mock_appbuilder = MagicMock()
        manager = GeocodingManager(mock_appbuilder)
        
        self.assertTrue(hasattr(manager, 'get_db_session'))
        self.assertTrue(hasattr(manager, 'execute_with_transaction'))
    
    def test_approval_workflow_manager_inherits_database_mixin(self):
        """Test that ApprovalWorkflowManager inherits from DatabaseMixin."""
        from tests.proper_pgappforge_extensions import ApprovalWorkflowManager
        
        # Check inheritance
        self.assertTrue(issubclass(ApprovalWorkflowManager, DatabaseMixin))
        
        # Check methods available
        mock_appbuilder = MagicMock()
        manager = ApprovalWorkflowManager(mock_appbuilder)
        
        self.assertTrue(hasattr(manager, 'get_db_session'))
        self.assertTrue(hasattr(manager, 'safe_database_operation'))
    
    def test_comment_manager_inherits_database_mixin(self):
        """Test that CommentManager inherits from DatabaseMixin.""" 
        from tests.proper_pgappforge_extensions import CommentManager
        
        # Check inheritance
        self.assertTrue(issubclass(CommentManager, DatabaseMixin))
        
        # Check methods available
        mock_appbuilder = MagicMock()
        manager = CommentManager(mock_appbuilder)
        
        self.assertTrue(hasattr(manager, 'batch_database_operations'))
        self.assertTrue(hasattr(manager, 'execute_with_transaction'))


def run_database_mixin_tests():
    """Run all database mixin tests."""
    print("=" * 80)
    print("DATABASE MIXIN FUNCTIONALITY TESTS")
    print("=" * 80)
    
    if not HAS_MAIN_MODULE:
        print("❌ Cannot run tests - DatabaseMixin module not available")
        return False
    
    # Create test suite
    suite = unittest.TestSuite()
    
    # Add test classes
    test_classes = [TestDatabaseMixin, TestManagerIntegration]
    
    for test_class in test_classes:
        tests = unittest.TestLoader().loadTestsFromTestCase(test_class)
        suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2, buffer=True)
    result = runner.run(suite)
    
    # Print summary
    print("\n" + "=" * 80)
    print("DATABASE MIXIN TEST SUMMARY")
    print("=" * 80)
    
    total_tests = result.testsRun
    failures = len(result.failures)
    errors = len(result.errors)
    skipped = len(result.skipped)
    passed = total_tests - failures - errors - skipped
    
    print(f"Total Tests: {total_tests}")
    print(f"Passed: {passed}")
    print(f"Failed: {failures}")
    print(f"Errors: {errors}")
    print(f"Skipped: {skipped}")
    
    if result.wasSuccessful():
        print("\n✅ ALL DATABASE MIXIN TESTS PASSED!")
        print("\nDatabase Session Management Status: READY")
        print("✓ DatabaseMixin class implementation working")
        print("✓ Transaction context management functional")
        print("✓ Error handling and rollback working")
        print("✓ All manager classes inherit DatabaseMixin")
        print("✓ Batch operations support implemented")
        
        print("\nPhase 1.1 Complete - Key Fixes Verified:")
        print("• Consistent database session access patterns")
        print("• Proper transaction management with automatic rollback")
        print("• Safe database operations with error handling")
        print("• Manager classes updated to use DatabaseMixin")
        print("• PgAppForge integration patterns maintained")
        
    else:
        print("\n❌ SOME DATABASE MIXIN TESTS FAILED")
        
        if failures:
            print(f"\nFailed Tests ({failures}):")
            for test, traceback in result.failures:
                print(f"  • {test}")
                
        if errors:
            print(f"\nError Tests ({errors}):")
            for test, traceback in result.errors:
                print(f"  • {test}")
    
    print("=" * 80)
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_database_mixin_tests()
    sys.exit(0 if success else 1)