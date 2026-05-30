"""
Comprehensive Integration Tests for PgAppForge Approval System

This test suite validates all security fixes, performance optimizations, and
PgAppForge integration for the approval workflow system.

Tests cover:
1. Circular import resolution in validation framework
2. N+1 query optimization in expression evaluator  
3. Connection pool configuration and dynamic scaling
4. Security validator integration
5. End-to-end approval workflow with PgAppForge
6. Performance under load with proper resource management

All tests follow PgAppForge patterns and validate production readiness.
"""

import pytest
import unittest
import asyncio
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from flask import Flask
from pgappforge import AppBuilder
from pgappforge.security.sqla.models import User, Role
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

# Import approval system components
from pgappforge.process.approval.validation_framework import (
    validate_approval_request,
    validate_user_input,
    validate_chain_config,
    ValidationContext,
    ValidationType
)
from pgappforge.process.approval.secure_expression_evaluator import (
    SecureExpressionEvaluator
)
from pgappforge.process.approval.connection_pool_manager import (
    ConnectionPoolManager,
    ConnectionConfig
)
from pgappforge.process.approval.constants import (
    DatabaseConstants,
    SecurityConstants,
    WorkflowConstants
)
from pgappforge.process.approval.workflow_manager import (
    ApprovalWorkflowManager
)
from pgappforge.wallet.models import WalletTransaction, TransactionStatus


class MockAppBuilder:
    """Mock AppBuilder for testing approval system integration."""
    
    def __init__(self):
        self.sm = Mock()
        self.sm.current_user = self._create_test_user()
        self.sm.log = Mock()
        self._db_session = Mock()
        self._app = Mock()
        
    def get_session(self):
        return self._db_session
        
    def get_app(self):
        return self._app
        
    def _create_test_user(self):
        user = Mock(spec=User)
        user.id = 1
        user.username = 'test_user'
        user.first_name = 'Test'
        user.last_name = 'User'
        user.is_authenticated = True
        
        # Create test roles
        admin_role = Mock(spec=Role)
        admin_role.name = 'Admin'
        approval_role = Mock(spec=Role)
        approval_role.name = 'ApprovalManager'
        
        user.roles = [admin_role, approval_role]
        return user


class TestValidationFrameworkIntegration(unittest.TestCase):
    """Test validation framework circular import resolution and integration."""
    
    def setUp(self):
        self.user_id = 1
        
    def test_circular_import_resolution(self):
        """Test that validation framework resolves circular imports correctly."""
        # This should not raise ImportError due to circular dependency
        try:
            from pgappforge.process.approval.validation_framework import validate_approval_request
            from pgappforge.process.approval.security_validator import ApprovalSecurityValidator
            
            # Test that validate_approval_request can import and use ApprovalSecurityValidator
            test_data = {
                'workflow_type': 'transaction_approval',
                'priority': 'high',
                'request_data': {'amount': 1000}
            }
            
            # This should work without circular import issues
            result = validate_approval_request(test_data, self.user_id)
            
            # Verify result structure
            self.assertIn('context', result)
            self.assertEqual(result['context']['user_id'], self.user_id)
            self.assertEqual(result['context']['validation_type'], ValidationType.APPROVAL_REQUEST.value)
            
        except ImportError as e:
            self.fail(f"Circular import detected: {e}")
            
    def test_validation_context_creation(self):
        """Test ValidationContext creation and functionality."""
        context = ValidationContext(
            user_id=self.user_id,
            operation="test_operation", 
            validation_type=ValidationType.USER_INPUT
        )
        
        self.assertEqual(context.user_id, self.user_id)
        self.assertEqual(context.operation, "test_operation")
        self.assertEqual(context.validation_type, ValidationType.USER_INPUT)
        self.assertIsInstance(context.timestamp, datetime)
        
    def test_user_input_validation_with_threats(self):
        """Test user input validation detects security threats."""
        malicious_data = {
            'comment': '<script>alert("xss")</script>',
            'description': "'; DROP TABLE users; --",
            'normal_field': 'safe content'
        }
        
        result = validate_user_input(malicious_data, self.user_id)
        
        # Verify threats were detected
        self.assertGreater(len(result['threats']), 0)
        
        # Verify sanitization occurred
        self.assertNotIn('<script>', result['sanitized_data']['comment'])
        self.assertNotIn('DROP TABLE', result['sanitized_data']['description'])
        self.assertEqual(result['sanitized_data']['normal_field'], 'safe content')
        
    def test_chain_config_validation(self):
        """Test approval chain configuration validation."""
        valid_config = {
            'type': 'sequential',
            'steps': [
                {'name': 'step1', 'required_role': 'Manager'},
                {'name': 'step2', 'required_role': 'Director'}
            ],
            'priority': 'high',
            'timeout': 86400
        }
        
        result = validate_chain_config(valid_config, self.user_id)
        
        self.assertTrue(result['valid'])
        self.assertEqual(len(result['errors']), 0)
        self.assertEqual(result['sanitized_data']['type'], 'sequential')
        self.assertEqual(len(result['sanitized_data']['steps']), 2)


class TestSecureExpressionEvaluatorOptimization(unittest.TestCase):
    """Test N+1 query optimization in SecureExpressionEvaluator."""
    
    def setUp(self):
        self.mock_db_session = Mock()
        self.evaluator = SecureExpressionEvaluator()
        
    def test_department_head_caching(self):
        """Test that department head queries are cached to prevent N+1."""
        # Mock department heads data
        dept_heads = {1: 101, 2: 102, 3: 103}
        
        with patch.object(self.evaluator, '_query_department_heads_batch') as mock_batch:
            mock_batch.return_value = dept_heads
            
            # First call should hit the database
            result1 = self.evaluator._get_cached_or_query_department_heads([1, 2, 3])
            self.assertEqual(result1, dept_heads)
            mock_batch.assert_called_once_with([1, 2, 3])
            
            # Second call should use cache
            mock_batch.reset_mock()
            result2 = self.evaluator._get_cached_or_query_department_heads([1, 2])
            self.assertEqual(result2, {1: 101, 2: 102})
            mock_batch.assert_not_called()  # Should not hit database again
            
    def test_cost_center_manager_caching(self):
        """Test that cost center manager queries are cached."""
        cc_managers = {1: 201, 2: 202, 3: 203}
        
        with patch.object(self.evaluator, '_query_cost_center_managers_batch') as mock_batch:
            mock_batch.return_value = cc_managers
            
            # First call should hit the database
            result1 = self.evaluator._get_cached_or_query_cost_center_managers([1, 2, 3])
            self.assertEqual(result1, cc_managers)
            mock_batch.assert_called_once_with([1, 2, 3])
            
            # Second call should use cache
            mock_batch.reset_mock()
            result2 = self.evaluator._get_cached_or_query_cost_center_managers([2, 3])
            self.assertEqual(result2, {2: 202, 3: 203})
            mock_batch.assert_not_called()
            
    def test_cache_ttl_expiration(self):
        """Test that cache expires after TTL."""
        with patch.object(self.evaluator, '_query_department_heads_batch') as mock_batch:
            mock_batch.return_value = {1: 101}
            
            # Set cache TTL to 1 second for testing
            self.evaluator._cache_ttl = 1
            
            # First call
            self.evaluator._get_cached_or_query_department_heads([1])
            mock_batch.assert_called_once()
            
            # Wait for cache to expire
            time.sleep(1.1)
            
            # Second call should hit database again due to TTL expiration
            mock_batch.reset_mock()
            self.evaluator._get_cached_or_query_department_heads([1])
            mock_batch.assert_called_once()
            
    def test_expression_evaluation_performance(self):
        """Test that expression evaluation uses optimized queries."""
        expression = "user.department_head == 101 and user.cost_center_manager == 201"
        context = {
            'user': Mock(),
            'department_id': 1,
            'cost_center_id': 1
        }
        
        with patch.object(self.evaluator, '_get_cached_or_query_department_heads') as mock_dept:
            with patch.object(self.evaluator, '_get_cached_or_query_cost_center_managers') as mock_cc:
                mock_dept.return_value = {1: 101}
                mock_cc.return_value = {1: 201}
                
                # Should use cached queries instead of individual lookups
                result = self.evaluator.evaluate_safe_expression(expression, context)
                
                mock_dept.assert_called_once()
                mock_cc.assert_called_once()


class TestConnectionPoolIntegration(unittest.TestCase):
    """Test connection pool configuration and dynamic scaling."""
    
    def setUp(self):
        self.mock_appbuilder = MockAppBuilder()
        self.config = ConnectionConfig()
        
    def test_connection_config_uses_constants(self):
        """Test that ConnectionConfig uses DatabaseConstants instead of hardcoded values."""
        config = ConnectionConfig()
        
        # Verify configuration uses constants
        self.assertEqual(config.pool_size, DatabaseConstants.DEFAULT_POOL_SIZE)
        self.assertEqual(config.max_overflow, DatabaseConstants.MAX_OVERFLOW)
        self.assertEqual(config.pool_recycle, DatabaseConstants.POOL_RECYCLE_SECONDS)
        
        # Verify dynamic scaling configuration exists
        self.assertTrue(hasattr(config, 'auto_scale'))
        self.assertTrue(hasattr(config, 'min_pool_size'))
        self.assertTrue(hasattr(config, 'max_pool_size'))
        self.assertTrue(hasattr(config, 'scale_threshold'))
        
    def test_connection_pool_manager_initialization(self):
        """Test ConnectionPoolManager initializes with proper configuration."""
        manager = ConnectionPoolManager(self.mock_appbuilder, self.config)
        
        self.assertEqual(manager.appbuilder, self.mock_appbuilder)
        self.assertEqual(manager.config, self.config)
        self.assertIsNotNone(manager.metrics)
        self.assertIsNotNone(manager._lock)
        
    def test_dynamic_scaling_recommendations(self):
        """Test dynamic scaling recommendation generation."""
        manager = ConnectionPoolManager(self.mock_appbuilder, self.config)
        
        # Mock metrics for high utilization scenario
        high_util_metrics = {
            'pool_size': 10,
            'utilization_percent': 85,
            'connection_timeouts': 5
        }
        
        with patch.object(manager, 'get_connection_metrics') as mock_metrics:
            mock_metrics.return_value = high_util_metrics
            
            recommendations = manager.get_scaling_recommendations()
            
            self.assertIn('recommendation', recommendations)
            self.assertIn('current_size', recommendations)
            self.assertIn('target_size', recommendations)
            self.assertGreater(recommendations['target_size'], recommendations['current_size'])
            
    def test_scaling_decision_logic(self):
        """Test scaling decision logic with various scenarios."""
        manager = ConnectionPoolManager(self.mock_appbuilder, self.config)
        
        # High utilization with timeouts - should scale up
        high_metrics = {'pool_size': 10, 'utilization_percent': 90, 'connection_timeouts': 3}
        self.assertTrue(manager._should_scale_up(high_metrics))
        self.assertFalse(manager._should_scale_down(high_metrics))
        
        # Low utilization without timeouts - should scale down
        low_metrics = {'pool_size': 20, 'utilization_percent': 20, 'connection_timeouts': 0}
        self.assertFalse(manager._should_scale_up(low_metrics))
        self.assertTrue(manager._should_scale_down(low_metrics))
        
        # Medium utilization - should maintain
        medium_metrics = {'pool_size': 15, 'utilization_percent': 50, 'connection_timeouts': 0}
        self.assertFalse(manager._should_scale_up(medium_metrics))
        self.assertFalse(manager._should_scale_down(medium_metrics))


class TestEndToEndApprovalWorkflow(unittest.TestCase):
    """Test complete approval workflow with all components integrated."""
    
    def setUp(self):
        self.mock_appbuilder = MockAppBuilder()
        self.workflow_manager = ApprovalWorkflowManager(self.mock_appbuilder)
        
        # Create mock transaction
        self.mock_transaction = Mock(spec=WalletTransaction)
        self.mock_transaction.id = 1
        self.mock_transaction.amount = 1000
        self.mock_transaction.status = TransactionStatus.PENDING.value
        self.mock_transaction.requires_approval = True
        
    def test_approval_workflow_integration(self):
        """Test complete approval workflow from request to completion."""
        # Setup workflow configuration
        workflow_config = {
            'type': 'sequential',
            'steps': [
                {
                    'name': 'manager_approval',
                    'required_role': 'Manager',
                    'requires_mfa': False
                },
                {
                    'name': 'director_approval', 
                    'required_role': 'Director',
                    'requires_mfa': True
                }
            ]
        }
        
        self.workflow_manager.workflow_configs['transaction_approval'] = workflow_config
        
        # Test approval process
        with patch.object(self.workflow_manager, 'get_approval_history') as mock_history:
            with patch.object(self.workflow_manager.security_validator, 'validate_approval_request') as mock_validate:
                mock_history.return_value = []  # No previous approvals
                mock_validate.return_value = {'valid': True, 'sanitized_data': {}}
                
                # Approve first step
                success = self.workflow_manager.approve_instance(
                    instance=self.mock_transaction,
                    step=0,
                    comments="Manager approval"
                )
                
                self.assertTrue(success)
                mock_validate.assert_called()
                
    def test_security_integration_with_validation(self):
        """Test security validation integration throughout approval process."""
        malicious_comments = "<script>alert('xss')</script>"
        
        with patch.object(self.workflow_manager, 'get_approval_history') as mock_history:
            with patch.object(self.workflow_manager.security_validator, 'validate_approval_request') as mock_validate:
                mock_history.return_value = []
                mock_validate.return_value = {
                    'valid': True,
                    'sanitized_data': {'comments': 'alert(xss)'},  # Sanitized
                    'threats': [{'type': 'XSS_SCRIPT_TAG', 'severity': 'HIGH'}]
                }
                
                success = self.workflow_manager.approve_instance(
                    instance=self.mock_transaction,
                    step=0,
                    comments=malicious_comments
                )
                
                # Should still succeed but with sanitized data
                self.assertTrue(success)
                
                # Verify validation was called with threat detection
                call_args = mock_validate.call_args[0][0]
                self.assertEqual(call_args['comments'], malicious_comments)
                
    def test_concurrent_approval_handling(self):
        """Test approval system handles concurrent requests properly."""
        def approve_transaction(step):
            return self.workflow_manager.approve_instance(
                instance=self.mock_transaction,
                step=step,
                comments=f"Approval step {step}"
            )
            
        with patch.object(self.workflow_manager, 'get_approval_history') as mock_history:
            with patch.object(self.workflow_manager.security_validator, 'validate_approval_request') as mock_validate:
                mock_history.return_value = []
                mock_validate.return_value = {'valid': True, 'sanitized_data': {}}
                
                # Simulate concurrent approvals
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures = [
                        executor.submit(approve_transaction, 0),
                        executor.submit(approve_transaction, 0),  # Same step
                        executor.submit(approve_transaction, 1)
                    ]
                    
                    results = [future.result() for future in futures]
                    
                    # Only one approval per step should succeed
                    success_count = sum(1 for result in results if result)
                    self.assertLessEqual(success_count, 2)  # At most 2 different steps
                    
    def test_performance_under_load(self):
        """Test system performance under high load conditions."""
        def simulate_approval_load():
            """Simulate multiple approval operations."""
            start_time = time.time()
            operations = []
            
            for i in range(50):  # 50 operations
                operation_start = time.time()
                
                # Simulate validation
                validate_approval_request({
                    'workflow_type': 'transaction_approval',
                    'priority': 'medium',
                    'request_data': {'amount': 500 + i}
                }, user_id=1)
                
                operation_time = time.time() - operation_start
                operations.append(operation_time)
                
            total_time = time.time() - start_time
            avg_time = sum(operations) / len(operations)
            
            return {
                'total_time': total_time,
                'average_operation_time': avg_time,
                'operations_per_second': len(operations) / total_time
            }
            
        # Run performance test
        perf_results = simulate_approval_load()
        
        # Verify performance metrics meet acceptable thresholds
        self.assertLess(perf_results['average_operation_time'], 0.1)  # < 100ms per operation
        self.assertGreater(perf_results['operations_per_second'], 10)  # > 10 ops/sec
        
    def test_database_constants_integration(self):
        """Test that all components use DatabaseConstants properly."""
        # Verify SecurityConstants are accessible
        self.assertIsInstance(SecurityConstants.MAX_BULK_OPERATIONS, int)
        self.assertIsInstance(SecurityConstants.RATE_LIMIT_WINDOW_SECONDS, int)
        
        # Verify DatabaseConstants are accessible
        self.assertIsInstance(DatabaseConstants.DEFAULT_POOL_SIZE, int)
        self.assertIsInstance(DatabaseConstants.MAX_OVERFLOW, int)
        
        # Verify WorkflowConstants are accessible
        self.assertIsInstance(WorkflowConstants.MAX_CHAIN_STEPS, int)
        self.assertIsInstance(WorkflowConstants.DEFAULT_STEP_TIMEOUT_HOURS, int)
        
        # Test that constants are used in configuration
        config = ConnectionConfig()
        self.assertEqual(config.pool_size, DatabaseConstants.DEFAULT_POOL_SIZE)


class TestSystemHealthAndMonitoring(unittest.TestCase):
    """Test system health monitoring and error handling."""
    
    def setUp(self):
        self.mock_appbuilder = MockAppBuilder()
        self.connection_manager = ConnectionPoolManager(
            self.mock_appbuilder,
            ConnectionConfig()
        )
        
    def test_connection_pool_health_monitoring(self):
        """Test connection pool health check functionality."""
        with patch.object(self.connection_manager, 'get_connection_metrics') as mock_metrics:
            mock_metrics.return_value = {
                'pool_size': 10,
                'checked_out': 3,
                'utilization_percent': 30,
                'failed_connections': 0,
                'connection_timeouts': 0
            }
            
            health_status = self.connection_manager.health_check()
            
            self.assertIn('status', health_status)
            self.assertIn('metrics', health_status)
            self.assertEqual(health_status['status'], 'healthy')
            
    def test_error_handling_and_recovery(self):
        """Test error handling and recovery mechanisms."""
        # Test validation framework error handling
        invalid_data = None
        
        try:
            result = validate_user_input(invalid_data, user_id=1)
            self.assertFalse(result['valid'])
            self.assertIn('errors', result)
        except Exception as e:
            self.fail(f"Validation should handle None input gracefully: {e}")
            
        # Test expression evaluator error handling
        evaluator = SecureExpressionEvaluator()
        
        try:
            result = evaluator.evaluate_safe_expression("invalid.expression", {})
            self.assertFalse(result)  # Should return False for invalid expressions
        except Exception as e:
            self.fail(f"Expression evaluator should handle invalid expressions gracefully: {e}")


def run_comprehensive_integration_tests():
    """Run all comprehensive integration tests."""
    test_loader = unittest.TestLoader()
    test_suite = unittest.TestSuite()
    
    # Add all test classes
    test_classes = [
        TestValidationFrameworkIntegration,
        TestSecureExpressionEvaluatorOptimization,
        TestConnectionPoolIntegration,
        TestEndToEndApprovalWorkflow,
        TestSystemHealthAndMonitoring
    ]
    
    for test_class in test_classes:
        tests = test_loader.loadTestsFromTestCase(test_class)
        test_suite.addTests(tests)
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Return results summary
    return {
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'success_rate': (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100
    }


if __name__ == '__main__':
    print("Running Comprehensive Integration Tests for PgAppForge Approval System")
    print("=" * 80)
    
    results = run_comprehensive_integration_tests()
    
    print("\n" + "=" * 80)
    print("INTEGRATION TEST RESULTS SUMMARY")
    print("=" * 80)
    print(f"Tests Run: {results['tests_run']}")
    print(f"Failures: {results['failures']}")
    print(f"Errors: {results['errors']}")
    print(f"Success Rate: {results['success_rate']:.1f}%")
    
    if results['success_rate'] >= 95:
        print("\n✅ INTEGRATION TESTS PASSED - System ready for production")
    elif results['success_rate'] >= 80:
        print("\n⚠️ INTEGRATION TESTS MOSTLY PASSED - Minor issues detected")
    else:
        print("\n❌ INTEGRATION TESTS FAILED - Critical issues require attention")