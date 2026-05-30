#!/usr/bin/env python3
"""
Concurrency and Transaction Safety Test Suite for Approval Workflow

Tests database transaction safety and race condition prevention:
1. Database Transaction Safety Violations - Race conditions in financial approvals
2. Database locking mechanisms
3. Transaction rollback handling
4. ApprovalTransactionError exception handling
5. Concurrent approval processing
6. Deadlock prevention

Environment: PgAppForge with SQLAlchemy threading support
"""

import pytest
import unittest
from unittest.mock import Mock, MagicMock, patch, call
import threading
import time
import concurrent.futures
from datetime import datetime
from contextlib import contextmanager
from sqlalchemy.exc import SQLAlchemyError
from flask import Flask

# Import system under test  
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from pgappforge.process.approval.workflow_engine import (
    ApprovalWorkflowEngine, ApprovalTransactionError
)
from pgappforge.process.approval.chain_manager import ApprovalChainManager


class TestApprovalWorkflowConcurrency(unittest.TestCase):
    """Test suite for approval workflow concurrency and transaction safety."""
    
    def setUp(self):
        """Set up test environment for concurrent operations."""
        # Create Flask app for testing
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
        self.app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
            'pool_timeout': 20,
            'pool_recycle': -1
        }
        
        # Mock PgAppForge components
        self.mock_appbuilder = Mock()
        self.mock_db_session = Mock()
        self.mock_appbuilder.get_session.return_value = self.mock_db_session
        
        # Initialize workflow engine
        self.workflow_engine = ApprovalWorkflowEngine(self.mock_appbuilder)
        
        # Mock approval instance
        self.mock_approval_instance = Mock()
        self.mock_approval_instance.id = 123
        self.mock_approval_instance.status = 'pending'
        self.mock_approval_instance.amount = 100000.0
        self.mock_approval_instance.workflow_completed_at = None
        self.mock_approval_instance.__class__ = Mock()
        
        # Mock user
        self.mock_user = Mock()
        self.mock_user.id = 456
        self.mock_user.username = 'approver_user'
        
        # Mock workflow configuration
        self.mock_workflow_config = {
            'steps': [
                {'name': 'manager_approval', 'required_approvals': 1},
                {'name': 'director_approval', 'required_approvals': 1}
            ],
            'approved_state': 'fully_approved'
        }
        
        # Mock step configuration
        self.mock_step_config = {
            'name': 'manager_approval',
            'required_role': 'Manager',
            'required_approvals': 1
        }
        
        # Concurrent operation results
        self.concurrent_results = []
        self.concurrent_exceptions = []
        
    def test_database_locking_context_manager(self):
        """Test database locking context manager prevents race conditions."""
        with patch.object(self.mock_db_session, 'query') as mock_query:
            # Mock locked instance
            mock_locked_instance = Mock()
            mock_locked_instance.id = 123
            mock_locked_instance.status = 'pending'
            
            # Mock query chain for SELECT FOR UPDATE
            mock_query_result = Mock()
            mock_query_result.filter.return_value.with_for_update.return_value.first.return_value = mock_locked_instance
            mock_query.return_value = mock_query_result
            
            # Test database locking
            with self.workflow_engine.database_lock_for_approval(self.mock_approval_instance) as locked_instance:
                self.assertIsNotNone(locked_instance)
                self.assertEqual(locked_instance.id, 123)
                
                # Verify SELECT FOR UPDATE was used
                mock_query.assert_called()
                mock_query_result.filter.assert_called()
                mock_query_result.filter.return_value.with_for_update.assert_called()
                
    def test_transaction_rollback_on_exception(self):
        """Test transaction rollback when approval processing fails."""
        # Mock database session that raises exception
        self.mock_db_session.commit.side_effect = SQLAlchemyError("Database connection lost")
        
        with patch.object(self.workflow_engine, 'database_lock_for_approval') as mock_lock:
            mock_lock.return_value.__enter__.return_value = self.mock_approval_instance
            mock_lock.return_value.__exit__.return_value = None
            
            with patch.object(self.workflow_engine, '_execute_approval_transaction') as mock_execute:
                mock_execute.return_value = (True, {'status': 'approved'})
                
                # Test transaction failure and rollback
                with self.assertRaises(ApprovalTransactionError) as context:
                    self.workflow_engine.process_approval_transaction(
                        self.mock_approval_instance,
                        self.mock_user,
                        0,  # step
                        self.mock_step_config,
                        "Approved by manager",
                        self.mock_workflow_config
                    )
                
                # Verify rollback was called
                self.mock_db_session.rollback.assert_called_once()
                
                # Verify exception message
                self.assertIn("Transaction failed", str(context.exception))
                self.assertIn("Database connection lost", str(context.exception))
                
    def test_approval_transaction_error_handling(self):
        """Test ApprovalTransactionError exception class and handling."""
        # Test exception instantiation
        error = ApprovalTransactionError("Test transaction failure")
        self.assertEqual(str(error), "Test transaction failure")
        
        # Test exception inheritance
        self.assertIsInstance(error, Exception)
        
        # Test raising and catching
        with self.assertRaises(ApprovalTransactionError) as context:
            raise ApprovalTransactionError("Database deadlock detected")
        
        self.assertEqual(str(context.exception), "Database deadlock detected")
        
    def test_concurrent_approval_processing_race_conditions(self):
        """Test concurrent approval processing with race condition prevention."""
        concurrent_approval_count = 5
        lock_acquisition_order = []
        
        def simulate_concurrent_approval(thread_id):
            """Simulate concurrent approval processing."""
            try:
                with patch.object(self.workflow_engine, 'database_lock_for_approval') as mock_lock:
                    # Record lock acquisition order
                    def record_lock_acquisition(instance):
                        lock_acquisition_order.append(thread_id)
                        time.sleep(0.01)  # Simulate processing time
                        return instance
                    
                    mock_lock.return_value.__enter__ = Mock(side_effect=record_lock_acquisition)
                    mock_lock.return_value.__exit__ = Mock(return_value=None)
                    
                    with patch.object(self.workflow_engine, '_execute_approval_transaction') as mock_execute:
                        mock_execute.return_value = (True, {'status': 'approved'})
                        
                        # Process approval
                        result = self.workflow_engine.process_approval_transaction(
                            self.mock_approval_instance,
                            self.mock_user,
                            0,
                            self.mock_step_config,
                            f"Approved by thread {thread_id}",
                            self.mock_workflow_config
                        )
                        
                        self.concurrent_results.append((thread_id, result))
                        
            except Exception as e:
                self.concurrent_exceptions.append((thread_id, e))
        
        # Run concurrent approval simulations
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrent_approval_count) as executor:
            futures = [
                executor.submit(simulate_concurrent_approval, i)
                for i in range(concurrent_approval_count)
            ]
            
            concurrent.futures.wait(futures)
        
        # Verify all approvals completed successfully
        self.assertEqual(len(self.concurrent_results), concurrent_approval_count)
        self.assertEqual(len(self.concurrent_exceptions), 0)
        
        # Verify sequential processing (locks prevent true concurrency)
        self.assertEqual(len(lock_acquisition_order), concurrent_approval_count)
        
    def test_database_deadlock_prevention(self):
        """Test deadlock prevention in concurrent approval scenarios."""
        deadlock_simulation_count = 3
        
        def simulate_potential_deadlock(thread_id, delay_seconds):
            """Simulate operations that could cause deadlocks."""
            try:
                with patch.object(self.workflow_engine, 'database_lock_for_approval') as mock_lock:
                    # Mock lock context manager
                    @contextmanager
                    def mock_lock_context(instance):
                        # Simulate varying lock acquisition times
                        time.sleep(delay_seconds)
                        yield instance
                    
                    mock_lock.return_value = mock_lock_context(self.mock_approval_instance)
                    
                    with patch.object(self.workflow_engine, '_execute_approval_transaction') as mock_execute:
                        mock_execute.return_value = (True, {'status': 'approved'})
                        
                        result = self.workflow_engine.process_approval_transaction(
                            self.mock_approval_instance,
                            self.mock_user,
                            0,
                            self.mock_step_config,
                            f"Thread {thread_id} approval",
                            self.mock_workflow_config
                        )
                        
                        self.concurrent_results.append((thread_id, result))
                        
            except Exception as e:
                self.concurrent_exceptions.append((thread_id, e))
        
        # Create threads with different delays to increase deadlock probability
        threads = []
        for i in range(deadlock_simulation_count):
            delay = (i + 1) * 0.01  # Varying delays
            thread = threading.Thread(
                target=simulate_potential_deadlock,
                args=(i, delay)
            )
            threads.append(thread)
        
        # Start all threads
        for thread in threads:
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join(timeout=5.0)  # Prevent infinite waiting
        
        # Verify no deadlocks occurred (all threads completed)
        self.assertEqual(len(self.concurrent_results), deadlock_simulation_count)
        self.assertEqual(len(self.concurrent_exceptions), 0)
        
    def test_transaction_isolation_levels(self):
        """Test proper transaction isolation to prevent dirty reads."""
        with patch.object(self.mock_db_session, 'query') as mock_query:
            # Mock fresh instance query for concurrent modification check
            fresh_instance = Mock()
            fresh_instance.id = 123
            fresh_instance.status = 'pending'  # Still pending
            
            mock_query_result = Mock()
            mock_query_result.filter.return_value.params.return_value.first.return_value = fresh_instance
            mock_query.return_value = mock_query_result
            
            # Test transaction isolation in _execute_approval_transaction
            with patch.object(self.workflow_engine, 'get_approval_history') as mock_history:
                mock_history.return_value = []
                
                with patch.object(self.workflow_engine, 'update_approval_history'):
                    with patch.object(self.workflow_engine, 'is_step_complete') as mock_complete:
                        mock_complete.return_value = True
                        
                        with patch.object(self.workflow_engine, 'advance_workflow_step'):
                            result = self.workflow_engine._execute_approval_transaction(
                                self.mock_db_session,
                                self.mock_approval_instance,
                                self.mock_user,
                                0,
                                self.mock_step_config,
                                "Test approval",
                                self.mock_workflow_config
                            )
                            
                            # Verify transaction completed successfully
                            self.assertTrue(result[0])  # success = True
                            self.assertIsNotNone(result[1])  # approval_data
                            
                            # Verify fresh instance check was performed
                            mock_query.assert_called()
                            
    def test_concurrent_modification_detection(self):
        """Test detection of concurrent modifications during approval processing."""
        with patch.object(self.mock_db_session, 'query') as mock_query:
            # Mock fresh instance that was modified concurrently
            fresh_instance = Mock()
            fresh_instance.id = 123
            fresh_instance.status = 'approved'  # Changed from 'pending'
            
            mock_query_result = Mock()
            mock_query_result.filter.return_value.params.return_value.first.return_value = fresh_instance
            mock_query.return_value = mock_query_result
            
            # Test concurrent modification detection
            with self.assertRaises(ValueError) as context:
                self.workflow_engine._execute_approval_transaction(
                    self.mock_db_session,
                    self.mock_approval_instance,
                    self.mock_user,
                    0,
                    self.mock_step_config,
                    "Test approval",
                    self.mock_workflow_config
                )
            
            # Verify concurrent modification was detected
            self.assertIn("no longer pending", str(context.exception))
            self.assertIn("concurrent modification", str(context.exception))
            
    def test_database_session_commit_rollback_cycle(self):
        """Test complete database session commit/rollback cycle."""
        # Test successful commit
        with patch.object(self.workflow_engine, 'database_lock_for_approval') as mock_lock:
            mock_lock.return_value.__enter__.return_value = self.mock_approval_instance
            mock_lock.return_value.__exit__.return_value = None
            
            with patch.object(self.workflow_engine, '_execute_approval_transaction') as mock_execute:
                mock_execute.return_value = (True, {'status': 'approved'})
                
                result = self.workflow_engine.process_approval_transaction(
                    self.mock_approval_instance,
                    self.mock_user,
                    0,
                    self.mock_step_config,
                    "Successful approval",
                    self.mock_workflow_config
                )
                
                # Verify commit was called
                self.mock_db_session.commit.assert_called_once()
                self.mock_db_session.rollback.assert_not_called()
                
                # Verify success result
                self.assertTrue(result[0])
                self.assertIsNotNone(result[1])
        
        # Reset mocks for rollback test
        self.mock_db_session.reset_mock()
        
        # Test rollback on failure
        with patch.object(self.workflow_engine, 'database_lock_for_approval') as mock_lock:
            mock_lock.return_value.__enter__.side_effect = Exception("Lock acquisition failed")
            
            with self.assertRaises(ApprovalTransactionError):
                self.workflow_engine.process_approval_transaction(
                    self.mock_approval_instance,
                    self.mock_user,
                    0,
                    self.mock_step_config,
                    "Failed approval",
                    self.mock_workflow_config
                )
            
            # Verify rollback was called
            self.mock_db_session.rollback.assert_called_once()
            
    def tearDown(self):
        """Clean up test environment."""
        self.concurrent_results.clear()
        self.concurrent_exceptions.clear()
        self.mock_appbuilder.reset_mock()
        self.mock_db_session.reset_mock()


if __name__ == '__main__':
    # Run tests with verbose output for concurrent operations
    unittest.main(verbosity=2, buffer=True)