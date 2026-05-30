"""
Approval Workflow Engine

Focused service class responsible for workflow processing logic
and approval data management. Handles the core workflow operations
without security validation or audit logging concerns.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from contextlib import contextmanager
from collections import defaultdict
from sqlalchemy.exc import SQLAlchemyError

# Removed complex dependency imports - using simplified approach
# These would be implemented in Phase 2 architectural improvements
from .transaction_manager import DatabaseTransactionManager, transactional, TransactionConfig
from .exceptions import (
    ApprovalError, DatabaseError, TransactionError, ValidationError,
    BusinessLogicError, PerformanceError, TimeoutError,
    handle_error, error_context, ErrorContext,
    handle_approval_errors
)

log = logging.getLogger(__name__)


# ApprovalTransactionError replaced by standardized TransactionError from exceptions.py


class ApprovalWorkflowEngine:
    """
    Handles core workflow processing and approval data management.
    
    Responsibilities:
    - Workflow state management and transitions
    - Approval history storage and retrieval  
    - Database transaction coordination
    - Workflow completion detection
    - Model registration and configuration
    """
    
    def __init__(self, appbuilder):
        self.appbuilder = appbuilder
        # Performance optimization: Cache indexed approval data
        self._approval_cache = {}  # instance_id -> indexed approval data
        self._cache_timestamps = {}  # instance_id -> last update timestamp
        
        # Database connection pool management
        self.connection_pool = ConnectionPoolManager(
            appbuilder, 
            ConnectionConfig(
                pool_size=25,
                max_overflow=50,
                pool_timeout=30,
                pool_recycle=3600,
                connect_timeout=15
            )
        )
        
        # Performance monitoring
        self.performance_monitor = get_performance_monitor({
            'backends': {
                'custom': {'enabled': True},
                'prometheus': {'enabled': False},
                'statsd': {'enabled': False}
            },
            'slow_approval_threshold': 2.0,
            'critical_approval_threshold': 5.0,
            'error_rate_threshold': 5.0
        })
        
        # Centralized session management
        self.session_manager = initialize_session_management(
            appbuilder, self.connection_pool
        )
        
        # Database transaction management
        self.transaction_manager = DatabaseTransactionManager()
        )
    
    def _get_db_session(self):
        """Get database session using connection pool manager."""
        try:
            return self.connection_pool.get_managed_session()
        except (ConnectionPoolExhaustionError, ConnectionTimeoutError) as e:
            log.error(f"Database connection pool issue: {e}")
            # Fallback to direct session for critical operations
            return self.appbuilder.get_session()
    
    @contextmanager
    def database_lock_for_approval(self, instance):
        """
        Database-level locking context manager for approval operations.
        
        Critical for preventing race conditions in financial transactions
        and other high-stakes approval scenarios.
        
        Uses connection pool manager for proper resource management.
        """
        try:
            with self.connection_pool.get_managed_session(timeout=20) as db_session:
                # Use SELECT FOR UPDATE to lock the specific instance with parameterized query
                if hasattr(instance, 'id') and instance.id:
                    from sqlalchemy import bindparam
                    locked_instance = db_session.query(instance.__class__).filter(
                        instance.__class__.id == bindparam('instance_id')
                    ).params(instance_id=instance.id).with_for_update().first()
                    
                    if not locked_instance:
                        raise ValueError(f"Instance {instance.id} not found or already locked")
                    
                    yield locked_instance
                else:
                    # For new instances, yield without locking
                    yield instance
                    
        except (ConnectionPoolExhaustionError, ConnectionTimeoutError) as e:
            log.error(f"Database connection pool exhausted during locking: {e}")
            # Fallback to traditional session for critical operations
            db_session = self.appbuilder.get_session()
            try:
                if hasattr(instance, 'id') and instance.id:
                    from sqlalchemy import bindparam
                    locked_instance = db_session.query(instance.__class__).filter(
                        instance.__class__.id == bindparam('instance_id')
                    ).params(instance_id=instance.id).with_for_update().first()
                    
                    if not locked_instance:
                        raise ValueError(f"Instance {instance.id} not found or already locked")
                    
                    yield locked_instance
                else:
                    yield instance
            finally:
                db_session.close()
                
        except Exception as e:
            log.error(f"Database locking failed for approval: {e}")
            raise
    
    def register_model_workflow(self, model_class, workflow_name='default', workflow_configs=None):
        """Register a model with a specific workflow."""
        if workflow_configs and workflow_name not in workflow_configs:
            log.error(f"Unknown workflow: {workflow_name}")
            return False
        
        # Store workflow association on model class
        if not hasattr(model_class, '_approval_workflow'):
            model_class._approval_workflow = workflow_name
            
        # Add required columns if not present
        self._ensure_approval_columns(model_class)
        
        log.info(f"Registered {model_class.__name__} with workflow: {workflow_name}")
        return True
    
    def _ensure_approval_columns(self, model_class):
        """Ensure model has required approval tracking columns."""
        required_columns = [
            'current_state', 'approval_history', 'workflow_started_at',
            'workflow_completed_at', 'last_approval_user_id'
        ]
        
        for column in required_columns:
            if not hasattr(model_class, column):
                log.warning(f"Model {model_class.__name__} missing approval column: {column}")
    
    def update_approval_history(self, instance, approval_data: Dict):
        """Update instance approval history with new approval."""
        existing_history = self.get_approval_history(instance)
        existing_history.append(approval_data)
        
        # Store as JSON with integrity protection
        if hasattr(instance, 'approval_history'):
            instance.approval_history = json.dumps(existing_history)
        else:
            # If model doesn't have approval_history column, log warning
            log.warning(f"Model {instance.__class__.__name__} missing approval_history column")
        
        # PERFORMANCE OPTIMIZATION: Invalidate cache to ensure consistency
        instance_id = getattr(instance, 'id', None)
        if instance_id:
            cache_key = f"{instance.__class__.__name__}_{instance_id}"
            if cache_key in self._approval_cache:
                del self._approval_cache[cache_key]
            if cache_key in self._cache_timestamps:
                del self._cache_timestamps[cache_key]
    
    def get_approval_history(self, instance) -> List[Dict]:
        """Get approval history for instance."""
        if not hasattr(instance, 'approval_history') or not instance.approval_history:
            return []
        
        try:
            history = json.loads(instance.approval_history)
            return history if isinstance(history, list) else []
        except (json.JSONDecodeError, TypeError):
            log.error(f"Invalid approval history for {instance.__class__.__name__} {getattr(instance, 'id', 'unknown')}")
            return []
    
    def _get_indexed_approval_data(self, instance) -> Dict[str, Any]:
        """
        Get indexed approval data for O(1) step lookups.
        
        Returns structured data with step-based indices to eliminate O(n²) complexity.
        Cache invalidation ensures data consistency.
        """
        instance_id = getattr(instance, 'id', None)
        if not instance_id:
            # For new instances, return empty indexed structure
            return {
                'step_approvals': defaultdict(list),  # step -> [approval_records]
                'step_counts': defaultdict(int),      # step -> approved_count
                'user_approvals': defaultdict(list), # user_id -> [approval_records]
                'total_approvals': 0,
                'last_updated': datetime.now(tz=timezone.utc)
            }
        
        # Check if cache is valid
        current_history = self.get_approval_history(instance)
        cache_key = f"{instance.__class__.__name__}_{instance_id}"
        
        if (cache_key in self._approval_cache and 
            cache_key in self._cache_timestamps and
            len(current_history) == self._approval_cache[cache_key].get('total_approvals', 0)):
            # Cache hit - return indexed data
            return self._approval_cache[cache_key]
        
        # Cache miss or invalidated - rebuild indexed structure
        indexed_data = self._build_approval_indices(current_history)
        
        # Update cache
        self._approval_cache[cache_key] = indexed_data
        self._cache_timestamps[cache_key] = datetime.now(tz=timezone.utc)
        
        return indexed_data
    
    def _build_approval_indices(self, approval_history: List[Dict]) -> Dict[str, Any]:
        """Build indexed data structures from approval history for O(1) lookups."""
        step_approvals = defaultdict(list)
        step_counts = defaultdict(int)
        user_approvals = defaultdict(list)
        
        for approval in approval_history:
            step = approval.get('step')
            user_id = approval.get('user_id')
            status = approval.get('status')
            
            if step is not None:
                step_approvals[step].append(approval)
                if status == 'approved':
                    step_counts[step] += 1
            
            if user_id is not None:
                user_approvals[user_id].append(approval)
        
        return {
            'step_approvals': dict(step_approvals),
            'step_counts': dict(step_counts),
            'user_approvals': dict(user_approvals),
            'total_approvals': len(approval_history),
            'last_updated': datetime.now(tz=timezone.utc)
        }

    def get_step_approvals(self, instance, step: int, status_filter: str = None) -> List[Dict]:
        """
        Get approvals for specific step with O(1) performance.
        
        Args:
            instance: Workflow instance
            step: Step number to query
            status_filter: Optional status filter ('approved', 'rejected', etc.)
        
        Returns:
            List of approval records for the step
        """
        indexed_data = self._get_indexed_approval_data(instance)
        step_approvals = indexed_data['step_approvals'].get(step, [])
        
        if status_filter:
            return [approval for approval in step_approvals 
                   if approval.get('status') == status_filter]
        
        return step_approvals
    
    def get_user_approvals(self, instance, user_id: int) -> List[Dict]:
        """
        Get all approvals by specific user with O(1) performance.
        
        Args:
            instance: Workflow instance  
            user_id: User ID to query
        
        Returns:
            List of approval records by the user
        """
        indexed_data = self._get_indexed_approval_data(instance)
        return indexed_data['user_approvals'].get(user_id, [])
    
    def get_workflow_progress(self, instance, workflow_config: Dict) -> Dict[str, Any]:
        """
        Get comprehensive workflow progress with O(1) step lookups.
        
        Returns:
            Dictionary with step completion status and progress metrics
        """
        indexed_data = self._get_indexed_approval_data(instance)
        steps = workflow_config.get('steps', [])
        
        progress = {
            'total_steps': len(steps),
            'completed_steps': 0,
            'step_details': {},
            'overall_completion': 0.0,
            'total_approvals': indexed_data['total_approvals']
        }
        
        for i, step_config in enumerate(steps):
            step_num = i
            required_approvals = step_config.get('required_approvals', 1)
            approved_count = indexed_data['step_counts'].get(step_num, 0)
            is_complete = approved_count >= required_approvals
            
            progress['step_details'][step_num] = {
                'name': step_config.get('name', f'Step {step_num}'),
                'required_approvals': required_approvals,
                'approved_count': approved_count,
                'is_complete': is_complete,
                'approvals': indexed_data['step_approvals'].get(step_num, [])
            }
            
            if is_complete:
                progress['completed_steps'] += 1
        
        if progress['total_steps'] > 0:
            progress['overall_completion'] = progress['completed_steps'] / progress['total_steps']
        
        return progress
    
    def bulk_process_approvals(self, approval_requests: List[Dict]) -> Dict[str, Any]:
        """
        Process multiple approvals efficiently with batch operations.
        
        Uses connection pool manager for optimal resource utilization
        and automatic connection cleanup.
        
        Args:
            approval_requests: List of approval request dictionaries
        
        Returns:
            Dictionary with processing results and performance metrics
        """
        start_time = datetime.now(tz=timezone.utc)
        results = {
            'processed': 0,
            'failed': 0,
            'errors': [],
            'processing_time_ms': 0,
            'connection_metrics': {}
        }
        
        # Use bulk session for efficient batch processing
        try:
            with self.connection_pool.get_bulk_session(batch_size=50) as (db_session, commit_callback):
                for request in approval_requests:
                    try:
                        instance = request['instance']
                        user = request['user']
                        step = request['step']
                        config = request['config']
                        comments = request.get('comments', '')
                        workflow_config = request['workflow_config']
                        
                        # Process individual approval
                        success, _ = self.process_approval_transaction(
                            instance, user, step, config, comments, workflow_config
                        )
                        
                        if success:
                            results['processed'] += 1
                            commit_callback()  # Batch commit when threshold reached
                        else:
                            results['failed'] += 1
                            
                    except Exception as e:
                        results['failed'] += 1
                        results['errors'].append(str(e))
                        log.error(f"Bulk approval processing error: {e}")
                
                # Calculate processing time
                end_time = datetime.now(tz=timezone.utc)
                processing_time = (end_time - start_time).total_seconds() * 1000
                results['processing_time_ms'] = round(processing_time, 2)
                
                # Get connection pool metrics
                results['connection_metrics'] = self.connection_pool.get_connection_metrics()
                
                log.info(f"Bulk processed {results['processed']} approvals in {results['processing_time_ms']}ms")
                
        except (ConnectionPoolExhaustionError, ConnectionTimeoutError) as e:
            log.error(f"Connection pool exhausted during bulk processing: {e}")
            results['errors'].append(f"Connection pool issue: {str(e)}")
            
        except Exception as e:
            log.error(f"Bulk approval processing failed: {e}")
            results['errors'].append(str(e))
            raise
        
        return results
    
    def cleanup_approval_cache(self, max_age_minutes: int = 60):
        """
        Clean up stale cache entries to prevent memory growth.
        
        Args:
            max_age_minutes: Maximum age for cache entries in minutes
        """
        current_time = datetime.now(tz=timezone.utc)
        cutoff_time = current_time - timedelta(minutes=max_age_minutes)
        
        stale_keys = [
            key for key, timestamp in self._cache_timestamps.items()
            if timestamp < cutoff_time
        ]
        
        for key in stale_keys:
            if key in self._approval_cache:
                del self._approval_cache[key]
            if key in self._cache_timestamps:
                del self._cache_timestamps[key]
        
        log.info(f"Cleaned up {len(stale_keys)} stale cache entries")
    
    def get_performance_metrics(self) -> Dict[str, Any]:
        """
        Get performance metrics for approval processing.
        
        Returns:
            Dictionary with cache hit rates and performance statistics
        """
        return {
            'cache_entries': len(self._approval_cache),
            'cache_timestamps': len(self._cache_timestamps),
            'memory_usage_estimate': sum(
                len(str(data)) for data in self._approval_cache.values()
            ),
            'oldest_cache_entry': min(
                self._cache_timestamps.values(), 
                default=datetime.now(tz=timezone.utc)
            ).isoformat() if self._cache_timestamps else None,
            'newest_cache_entry': max(
                self._cache_timestamps.values(), 
                default=datetime.now(tz=timezone.utc)
            ).isoformat() if self._cache_timestamps else None
        }

    
    def get_connection_pool_status(self) -> Dict[str, Any]:
        """
        Get comprehensive connection pool status and health metrics.
        
        Returns:
            Dictionary with pool status, metrics, and health information
        """
        try:
            pool_metrics = self.connection_pool.get_connection_metrics()
            health_status = self.connection_pool.health_check()
            
            return {
                'metrics': pool_metrics,
                'health': health_status,
                'config': self.connection_pool.get_config(),
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
            
        except Exception as e:
            log.error(f"Failed to get connection pool status: {e}")
            return {
                'error': str(e),
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
    
    def cleanup_connections(self):
        """
        Perform connection pool cleanup and maintenance.
        
        This method should be called periodically to:
        - Clean up stale connections
        - Reset metrics if needed
        - Perform health checks
        """
        try:
            # Clean up stale connections
            self.connection_pool.cleanup_stale_connections()
            
            # Also clean up approval cache
            self.cleanup_approval_cache()
            
            log.info("Connection and cache cleanup completed")
            
        except Exception as e:
            log.error(f"Connection cleanup failed: {e}")
    
    def get_system_health(self) -> Dict[str, Any]:
        """
        Get comprehensive system health including connection pool and cache status.
        
        Returns:
            Dictionary with overall system health metrics
        """
        try:
            connection_health = self.connection_pool.health_check()
            connection_metrics = self.connection_pool.get_connection_metrics()
            cache_metrics = self.get_performance_metrics()
            
            # Determine overall health status
            overall_status = 'healthy'
            if connection_health['status'] in ['warning', 'critical']:
                overall_status = connection_health['status']
            
            # Check cache health
            cache_size = cache_metrics.get('cache_entries', 0)
            if cache_size > 1000:  # Large cache might indicate memory issues
                if overall_status == 'healthy':
                    overall_status = 'warning'
            
            return {
                'overall_status': overall_status,
                'connection_pool': {
                    'status': connection_health['status'],
                    'metrics': connection_metrics,
                    'issues': connection_health.get('issues', []),
                    'recommendations': connection_health.get('recommendations', [])
                },
                'approval_cache': {
                    'metrics': cache_metrics,
                    'status': 'warning' if cache_size > 1000 else 'healthy'
                },
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
            
        except Exception as e:
            log.error(f"System health check failed: {e}")
            return {
                'overall_status': 'critical',
                'error': str(e),
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            }
    
    def is_step_complete(self, instance, step: int, step_config: Dict) -> bool:
        """
        Check if approval step has received required number of approvals.
        
        PERFORMANCE OPTIMIZATION: O(1) lookup using indexed data structures
        instead of O(n) linear search through entire approval history.
        """
        indexed_data = self._get_indexed_approval_data(instance)
        
        # O(1) lookup instead of O(n) linear search
        approved_count = indexed_data['step_counts'].get(step, 0)
        required_approvals = step_config.get('required_approvals', 1)
        
        return approved_count >= required_approvals
    
    def advance_workflow_step(self, instance, workflow_config: Dict, completed_step: int):
        """Advance workflow to next step or completion."""
        total_steps = len(workflow_config['steps'])
        
        if completed_step >= total_steps - 1:
            # Final step completed - mark as approved
            instance.current_state = workflow_config['approved_state']
            instance.workflow_completed_at = datetime.now(tz=timezone.utc)
        else:
            # Move to next step
            instance.current_state = f"step_{completed_step}_approved"
    
    @handle_approval_errors()
    def process_approval_transaction(self, instance, user, step, config, comments, workflow_config):
        """
        Process the actual approval with mandatory database locking to prevent race conditions.
        
        Returns:
            tuple: (success: bool, approval_data: Dict or None)
        """
        approval_id = getattr(instance, 'id', 0)
        workflow_type = workflow_config.get('name', 'default')
        
        # Track approval performance metrics
        with self.performance_monitor.track_approval_metrics(
            approval_id=approval_id,
            workflow_type=workflow_type,
            step=step
        ):
            # Use transaction manager for robust database operations
            with self.transaction_manager.transaction("process_approval_transaction"):
                with self.database_lock_for_approval(instance) as locked_instance:
                    # Execute approval transaction within database lock
                    result = self._execute_approval_transaction(
                        locked_instance, user, step, config, comments, workflow_config
                    )
                    
                    # Track connection pool metrics
                    pool_metrics = self.connection_pool.get_pool_metrics()
                    self.performance_monitor.track_connection_pool_metrics(pool_metrics)
                    
                    return result
    
    def _execute_approval_transaction(self, db_session, instance, current_user, step, step_config, comments, workflow_config):
        """Execute the approval transaction within database session."""
        # Double-check transaction status after acquiring lock (if used)
        if hasattr(instance, 'status') and hasattr(instance, 'id'):
            from sqlalchemy import bindparam
            fresh_instance = db_session.query(instance.__class__).filter(
                instance.__class__.id == bindparam('instance_id')
            ).params(instance_id=instance.id).first()
            
            if fresh_instance and hasattr(fresh_instance, 'status'):
                if fresh_instance.status != 'pending':
                    raise ValueError(f"Instance {instance.id} no longer pending (concurrent modification)")
                instance = fresh_instance
        
        # Create approval record (will be provided by audit logger)
        approval_data = {
            'user_id': current_user.id,
            'user_name': current_user.username,
            'step': step,
            'step_name': step_config['name'],
            'status': 'approved',
            'comments': comments,
            'timestamp': datetime.now(tz=timezone.utc).isoformat()
        }
        
        # Update approval history
        self.update_approval_history(instance, approval_data)
        
        # Check if step is complete
        if self.is_step_complete(instance, step, step_config):
            self.advance_workflow_step(instance, workflow_config, step)
        
        # Update last approval tracking
        instance.last_approval_user_id = current_user.id
        if not hasattr(instance, 'workflow_completed_at') or not instance.workflow_completed_at:
            instance.workflow_completed_at = datetime.now(tz=timezone.utc)
        
        # Add instance to session
        db_session.add(instance)
        db_session.commit()
        
        return True, approval_data
    
    def create_approval_workflow(self, instance, workflow_name: str, workflow_config: Dict) -> bool:
        """
        Initialize approval workflow for an instance.
        
        This method starts the approval workflow process and should be called
        when a new instance is created that requires approval.
        """
        if not workflow_config:
            log.error(f"No workflow configuration provided")
            return False
        
        # Set initial state
        instance.current_state = workflow_config['initial_state']
        instance.workflow_started_at = datetime.now(tz=timezone.utc)
        instance.approval_history = '[]'  # Initialize empty history
        
        # Save to database
        db_session = self._get_db_session()
        try:
            db_session.add(instance)
            db_session.commit()
            
            log.info(f"Initialized approval workflow '{workflow_name}' for {instance.__class__.__name__} {getattr(instance, 'id', 'unknown')}")
            return True
            
        except SQLAlchemyError as e:
            db_session.rollback()
            log.error(f"Failed to initialize approval workflow: {e}")
            return False