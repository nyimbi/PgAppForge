"""
State Persistence and Recovery System for Flask-AppBuilder Workflows

Provides robust state management and recovery capabilities including:
- Automatic state snapshots and checkpoints
- Disaster recovery and workflow restoration
- Cross-session state persistence
- Conflict resolution for concurrent modifications
- State versioning and rollback capabilities
- Backup and restore functionality
- Transaction-safe state operations
- Recovery from system failures
"""

import logging
import json
import pickle
import gzip
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional, Union, TYPE_CHECKING
from dataclasses import dataclass, asdict
from enum import Enum
import threading
from contextlib import contextmanager
import asyncio

from flask import current_app, g
from sqlalchemy import Column, String, Text, DateTime, Boolean, Integer, LargeBinary, JSON, ForeignKey
from sqlalchemy.orm import relationship, sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from redis import Redis
import celery

from ..models.mixins import AuditMixin
from .core import WorkflowState, get_workflow_engine

if TYPE_CHECKING:
    from .core import WorkflowDefinition

log = logging.getLogger(__name__)


class PersistenceStrategy(Enum):
    """Persistence strategies for workflow state."""
    DATABASE_ONLY = "database_only"
    REDIS_CACHE = "redis_cache"
    HYBRID = "hybrid"
    FILE_SYSTEM = "file_system"
    DISTRIBUTED = "distributed"


class RecoveryLevel(Enum):
    """Levels of recovery operations."""
    STEP_LEVEL = "step_level"
    WORKFLOW_LEVEL = "workflow_level"
    SESSION_LEVEL = "session_level"
    SYSTEM_LEVEL = "system_level"


@dataclass
class StateSnapshot:
    """Represents a workflow state snapshot."""
    snapshot_id: str
    workflow_state_id: str
    workflow_name: str
    step_id: str
    form_data: Dict[str, Any]
    metadata: Dict[str, Any]
    timestamp: datetime
    user_id: Optional[str]
    checksum: str


@dataclass
class RecoveryPoint:
    """Represents a recovery point for workflows."""
    recovery_id: str
    workflow_state_id: str
    recovery_level: RecoveryLevel
    snapshot_data: bytes
    metadata: Dict[str, Any]
    created_at: datetime
    expires_at: Optional[datetime]


class WorkflowStateSnapshot(AuditMixin):
    """
    Stores workflow state snapshots for recovery.
    """
    __tablename__ = 'ab_workflow_state_snapshots'

    id = Column(String(36), primary_key=True)
    workflow_state_id = Column(String(36), ForeignKey('ab_workflow_states.id'), nullable=False)
    snapshot_type = Column(String(20), default='checkpoint')  # checkpoint, backup, rollback_point
    step_id = Column(String(100), nullable=True)
    form_data = Column(JSON, default=lambda: {})
    state_data = Column(LargeBinary, nullable=True)  # Compressed serialized state
    metadata = Column(JSON, default=lambda: {})
    checksum = Column(String(64), nullable=False)
    user_id = Column(Integer, nullable=True)
    is_recoverable = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)

    # Relationships
    workflow_state = relationship("WorkflowState", backref="snapshots")


class WorkflowRecoveryLog(AuditMixin):
    """
    Logs workflow recovery operations.
    """
    __tablename__ = 'ab_workflow_recovery_log'

    id = Column(String(36), primary_key=True)
    workflow_state_id = Column(String(36), ForeignKey('ab_workflow_states.id'), nullable=False)
    recovery_type = Column(String(50), nullable=False)  # auto_recovery, manual_recovery, rollback
    recovery_level = Column(String(20), nullable=False)
    snapshot_id = Column(String(36), nullable=True)
    success = Column(Boolean, default=False)
    error_message = Column(Text, nullable=True)
    recovery_data = Column(JSON, default=lambda: {})
    user_id = Column(Integer, nullable=True)

    # Relationships
    workflow_state = relationship("WorkflowState", backref="recovery_logs")


class WorkflowStatePersistence:
    """
    Manages workflow state persistence and recovery.
    """

    def __init__(self, strategy: PersistenceStrategy = PersistenceStrategy.HYBRID):
        self.strategy = strategy
        self.redis_client = None
        self.auto_snapshot_enabled = True
        self.snapshot_interval = 300  # 5 minutes
        self.max_snapshots_per_workflow = 10
        self.recovery_timeout = 30  # seconds
        self._locks = {}
        self._setup_persistence_backends()

    def _setup_persistence_backends(self):
        """Setup persistence backends based on strategy."""
        
        # Setup Redis if using cache or hybrid strategy
        if self.strategy in [PersistenceStrategy.REDIS_CACHE, PersistenceStrategy.HYBRID]:
            redis_config = current_app.config.get('REDIS_CONFIG', {})
            if redis_config:
                try:
                    self.redis_client = Redis(
                        host=redis_config.get('host', 'localhost'),
                        port=redis_config.get('port', 6379),
                        db=redis_config.get('db', 0),
                        password=redis_config.get('password'),
                        decode_responses=True
                    )
                    # Test connection
                    self.redis_client.ping()
                    log.info("Redis connection established for workflow persistence")
                except Exception as e:
                    log.warning(f"Failed to connect to Redis: {e}")
                    self.redis_client = None

    def create_snapshot(self, workflow_state: WorkflowState, 
                       snapshot_type: str = 'checkpoint',
                       metadata: Optional[Dict[str, Any]] = None) -> str:
        """Create a snapshot of workflow state."""
        from ..models import db
        from uuid_extensions import uuid7str
        import hashlib

        try:
            snapshot_id = uuid7str()
            
            # Serialize state data
            state_data = {
                'id': workflow_state.id,
                'workflow_name': workflow_state.workflow_name,
                'current_step': workflow_state.current_step,
                'completed_steps': workflow_state.completed_steps,
                'available_next_steps': workflow_state.available_next_steps,
                'form_data': workflow_state.form_data,
                'history': workflow_state.history,
                'status': workflow_state.status,
                'progress_percentage': workflow_state.progress_percentage,
                'entity_type': workflow_state.entity_type,
                'entity_id': workflow_state.entity_id,
                'expires_at': workflow_state.expires_at.isoformat() if workflow_state.expires_at else None,
                'metadata': workflow_state.metadata
            }

            # Compress and serialize
            serialized_data = pickle.dumps(state_data)
            compressed_data = gzip.compress(serialized_data)

            # Calculate checksum
            checksum = hashlib.sha256(compressed_data).hexdigest()

            # Create snapshot record
            snapshot = WorkflowStateSnapshot(
                id=snapshot_id,
                workflow_state_id=workflow_state.id,
                snapshot_type=snapshot_type,
                step_id=workflow_state.current_step,
                form_data=workflow_state.form_data or {},
                state_data=compressed_data,
                metadata=metadata or {},
                checksum=checksum,
                user_id=getattr(g, 'user', {}).get('id') if hasattr(g, 'user') else None,
                expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30)  # Default 30-day retention
            )

            db.session.add(snapshot)
            db.session.commit()

            # Store in Redis cache if available
            if self.redis_client and self.strategy in [PersistenceStrategy.REDIS_CACHE, PersistenceStrategy.HYBRID]:
                cache_key = f"workflow_snapshot:{workflow_state.id}:{snapshot_id}"
                cache_data = {
                    'snapshot_id': snapshot_id,
                    'workflow_state_id': workflow_state.id,
                    'form_data': workflow_state.form_data,
                    'current_step': workflow_state.current_step,
                    'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                    'checksum': checksum
                }
                self.redis_client.setex(cache_key, 3600, json.dumps(cache_data))  # 1-hour cache

            log.info(f"Created snapshot {snapshot_id} for workflow {workflow_state.id}")
            return snapshot_id

        except Exception as e:
            log.error(f"Failed to create snapshot for workflow {workflow_state.id}: {e}")
            db.session.rollback()
            raise

    def restore_from_snapshot(self, workflow_state_id: str, 
                            snapshot_id: Optional[str] = None) -> Optional[WorkflowState]:
        """Restore workflow state from snapshot."""
        from ..models import db

        try:
            # Get snapshot
            if snapshot_id:
                snapshot = db.session.query(WorkflowStateSnapshot).filter(
                    WorkflowStateSnapshot.id == snapshot_id,
                    WorkflowStateSnapshot.workflow_state_id == workflow_state_id
                ).first()
            else:
                # Get latest snapshot
                snapshot = db.session.query(WorkflowStateSnapshot).filter(
                    WorkflowStateSnapshot.workflow_state_id == workflow_state_id,
                    WorkflowStateSnapshot.is_recoverable == True
                ).order_by(WorkflowStateSnapshot.created_on.desc()).first()

            if not snapshot:
                log.warning(f"No snapshot found for workflow {workflow_state_id}")
                return None

            # Verify checksum
            if not self._verify_snapshot_integrity(snapshot):
                log.error(f"Snapshot {snapshot.id} integrity check failed")
                return None

            # Deserialize state data
            decompressed_data = gzip.decompress(snapshot.state_data)
            state_data = pickle.loads(decompressed_data)

            # Get or create workflow state
            workflow_state = db.session.query(WorkflowState).filter(
                WorkflowState.id == workflow_state_id
            ).first()

            if not workflow_state:
                # Create new workflow state from snapshot
                workflow_state = WorkflowState(
                    id=state_data['id'],
                    workflow_name=state_data['workflow_name'],
                    entity_type=state_data['entity_type'],
                    entity_id=state_data['entity_id']
                )
                db.session.add(workflow_state)

            # Restore state
            workflow_state.current_step = state_data['current_step']
            workflow_state.completed_steps = state_data['completed_steps']
            workflow_state.available_next_steps = state_data['available_next_steps']
            workflow_state.form_data = state_data['form_data']
            workflow_state.history = state_data['history']
            workflow_state.status = state_data['status']
            workflow_state.progress_percentage = state_data['progress_percentage']
            workflow_state.metadata = state_data['metadata']
            
            if state_data['expires_at']:
                workflow_state.expires_at = datetime.fromisoformat(state_data['expires_at'])

            workflow_state.last_activity_at = datetime.now(tz=timezone.utc)

            db.session.commit()

            # Log recovery operation
            self._log_recovery_operation(
                workflow_state_id=workflow_state_id,
                recovery_type='manual_recovery',
                recovery_level=RecoveryLevel.WORKFLOW_LEVEL,
                snapshot_id=snapshot.id,
                success=True
            )

            log.info(f"Restored workflow {workflow_state_id} from snapshot {snapshot.id}")
            return workflow_state

        except Exception as e:
            log.error(f"Failed to restore workflow {workflow_state_id} from snapshot: {e}")
            db.session.rollback()
            
            # Log failed recovery
            self._log_recovery_operation(
                workflow_state_id=workflow_state_id,
                recovery_type='manual_recovery',
                recovery_level=RecoveryLevel.WORKFLOW_LEVEL,
                snapshot_id=snapshot_id,
                success=False,
                error_message=str(e)
            )
            return None

    def auto_recover_workflow(self, workflow_state_id: str) -> bool:
        """Automatically recover workflow from the latest valid snapshot."""
        
        try:
            workflow_state = self.restore_from_snapshot(workflow_state_id)
            
            if workflow_state:
                # Validate recovered state
                if self._validate_recovered_state(workflow_state):
                    log.info(f"Auto-recovery successful for workflow {workflow_state_id}")
                    return True
                else:
                    log.warning(f"Auto-recovery validation failed for workflow {workflow_state_id}")
                    return False
            
            return False

        except Exception as e:
            log.error(f"Auto-recovery failed for workflow {workflow_state_id}: {e}")
            return False

    def _verify_snapshot_integrity(self, snapshot: WorkflowStateSnapshot) -> bool:
        """Verify snapshot data integrity."""
        import hashlib

        try:
            if not snapshot.state_data or not snapshot.checksum:
                return False

            # Calculate checksum of stored data
            calculated_checksum = hashlib.sha256(snapshot.state_data).hexdigest()
            return calculated_checksum == snapshot.checksum

        except Exception as e:
            log.error(f"Error verifying snapshot integrity: {e}")
            return False

    def _validate_recovered_state(self, workflow_state: WorkflowState) -> bool:
        """Validate recovered workflow state."""
        
        try:
            # Basic validation
            if not workflow_state.workflow_name or not workflow_state.current_step:
                return False

            # Validate against workflow definition
            engine = get_workflow_engine()
            workflow_def = engine.workflow_definitions.get(workflow_state.workflow_name)
            
            if not workflow_def:
                log.warning(f"Workflow definition not found for {workflow_state.workflow_name}")
                return False

            # Validate current step exists
            step_exists = any(step.id == workflow_state.current_step for step in workflow_def.steps)
            if not step_exists:
                log.warning(f"Current step {workflow_state.current_step} not found in workflow definition")
                return False

            # Validate form data structure
            if workflow_state.form_data and not isinstance(workflow_state.form_data, dict):
                return False

            return True

        except Exception as e:
            log.error(f"Error validating recovered state: {e}")
            return False

    def _log_recovery_operation(self, workflow_state_id: str, recovery_type: str,
                              recovery_level: RecoveryLevel, snapshot_id: Optional[str] = None,
                              success: bool = False, error_message: Optional[str] = None,
                              recovery_data: Optional[Dict[str, Any]] = None):
        """Log recovery operation."""
        from ..models import db
        from uuid_extensions import uuid7str

        try:
            recovery_log = WorkflowRecoveryLog(
                id=uuid7str(),
                workflow_state_id=workflow_state_id,
                recovery_type=recovery_type,
                recovery_level=recovery_level.value,
                snapshot_id=snapshot_id,
                success=success,
                error_message=error_message,
                recovery_data=recovery_data or {},
                user_id=getattr(g, 'user', {}).get('id') if hasattr(g, 'user') else None
            )

            db.session.add(recovery_log)
            db.session.commit()

        except Exception as e:
            log.error(f"Failed to log recovery operation: {e}")

    @contextmanager
    def transaction_safe_operation(self, workflow_state_id: str):
        """Context manager for transaction-safe workflow operations."""
        from ..models import db

        # Create pre-operation snapshot
        workflow_state = db.session.query(WorkflowState).filter(
            WorkflowState.id == workflow_state_id
        ).first()

        if not workflow_state:
            raise ValueError(f"Workflow state {workflow_state_id} not found")

        pre_snapshot_id = self.create_snapshot(workflow_state, 'pre_operation')
        
        try:
            yield workflow_state
            # Operation completed successfully
            
        except Exception as e:
            # Operation failed, restore from pre-operation snapshot
            log.warning(f"Operation failed for workflow {workflow_state_id}, restoring from snapshot")
            self.restore_from_snapshot(workflow_state_id, pre_snapshot_id)
            raise

    def get_workflow_lock(self, workflow_state_id: str, timeout: int = 30) -> bool:
        """Acquire distributed lock for workflow operations."""
        
        if not self.redis_client:
            # Fallback to in-memory locking
            return self._get_memory_lock(workflow_state_id, timeout)

        lock_key = f"workflow_lock:{workflow_state_id}"
        lock_value = f"{threading.current_thread().ident}:{datetime.now(tz=timezone.utc).timestamp()}"
        
        # Try to acquire lock
        acquired = self.redis_client.set(lock_key, lock_value, nx=True, ex=timeout)
        
        if acquired:
            log.debug(f"Acquired lock for workflow {workflow_state_id}")
            return True
        else:
            log.warning(f"Failed to acquire lock for workflow {workflow_state_id}")
            return False

    def release_workflow_lock(self, workflow_state_id: str):
        """Release distributed lock for workflow operations."""
        
        if not self.redis_client:
            return self._release_memory_lock(workflow_state_id)

        lock_key = f"workflow_lock:{workflow_state_id}"
        self.redis_client.delete(lock_key)
        log.debug(f"Released lock for workflow {workflow_state_id}")

    def _get_memory_lock(self, workflow_state_id: str, timeout: int) -> bool:
        """Fallback in-memory locking."""
        if workflow_state_id not in self._locks:
            self._locks[workflow_state_id] = threading.Lock()
        
        return self._locks[workflow_state_id].acquire(timeout=timeout)

    def _release_memory_lock(self, workflow_state_id: str):
        """Release in-memory lock."""
        if workflow_state_id in self._locks:
            try:
                self._locks[workflow_state_id].release()
            except RuntimeError:
                # Lock was not held
                pass

    def cleanup_expired_snapshots(self):
        """Clean up expired snapshots."""
        from ..models import db

        try:
            cutoff_date = datetime.now(tz=timezone.utc)
            
            expired_snapshots = db.session.query(WorkflowStateSnapshot).filter(
                WorkflowStateSnapshot.expires_at <= cutoff_date
            ).all()

            for snapshot in expired_snapshots:
                # Remove from Redis cache if present
                if self.redis_client:
                    cache_key = f"workflow_snapshot:{snapshot.workflow_state_id}:{snapshot.id}"
                    self.redis_client.delete(cache_key)
                
                db.session.delete(snapshot)

            db.session.commit()
            
            if expired_snapshots:
                log.info(f"Cleaned up {len(expired_snapshots)} expired workflow snapshots")

        except Exception as e:
            log.error(f"Error cleaning up expired snapshots: {e}")
            db.session.rollback()

    def backup_workflow_states(self, workflow_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """Create backup of workflow states."""
        from ..models import db

        try:
            query = db.session.query(WorkflowState)
            
            if workflow_names:
                query = query.filter(WorkflowState.workflow_name.in_(workflow_names))

            workflow_states = query.all()
            
            backup_data = {
                'backup_timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'workflow_count': len(workflow_states),
                'workflows': []
            }

            for state in workflow_states:
                # Create snapshot for each workflow
                snapshot_id = self.create_snapshot(state, 'backup')
                
                workflow_backup = {
                    'id': state.id,
                    'workflow_name': state.workflow_name,
                    'current_step': state.current_step,
                    'status': state.status,
                    'entity_type': state.entity_type,
                    'entity_id': state.entity_id,
                    'snapshot_id': snapshot_id,
                    'created_on': state.created_on.isoformat() if state.created_on else None
                }
                backup_data['workflows'].append(workflow_backup)

            log.info(f"Created backup of {len(workflow_states)} workflow states")
            return backup_data

        except Exception as e:
            log.error(f"Error creating workflow backup: {e}")
            raise

    def restore_from_backup(self, backup_data: Dict[str, Any]) -> bool:
        """Restore workflow states from backup."""
        
        try:
            restored_count = 0
            
            for workflow_backup in backup_data.get('workflows', []):
                workflow_state_id = workflow_backup['id']
                snapshot_id = workflow_backup['snapshot_id']
                
                # Restore from snapshot
                restored_state = self.restore_from_snapshot(workflow_state_id, snapshot_id)
                
                if restored_state:
                    restored_count += 1
                    log.debug(f"Restored workflow {workflow_state_id} from backup")
                else:
                    log.warning(f"Failed to restore workflow {workflow_state_id} from backup")

            log.info(f"Restored {restored_count} workflows from backup")
            return restored_count > 0

        except Exception as e:
            log.error(f"Error restoring from backup: {e}")
            return False

    def get_recovery_statistics(self, days: int = 30) -> Dict[str, Any]:
        """Get recovery operation statistics."""
        from ..models import db

        try:
            cutoff_date = datetime.now(tz=timezone.utc) - timedelta(days=days)
            
            recovery_logs = db.session.query(WorkflowRecoveryLog).filter(
                WorkflowRecoveryLog.created_on >= cutoff_date
            ).all()

            stats = {
                'total_recovery_operations': len(recovery_logs),
                'successful_recoveries': sum(1 for log in recovery_logs if log.success),
                'failed_recoveries': sum(1 for log in recovery_logs if not log.success),
                'recovery_types': {},
                'recovery_levels': {},
                'most_recovered_workflows': {}
            }

            # Calculate success rate
            if stats['total_recovery_operations'] > 0:
                stats['success_rate'] = stats['successful_recoveries'] / stats['total_recovery_operations']
            else:
                stats['success_rate'] = 0.0

            # Group by recovery type and level
            for log in recovery_logs:
                # Recovery types
                if log.recovery_type not in stats['recovery_types']:
                    stats['recovery_types'][log.recovery_type] = {'count': 0, 'success': 0}
                stats['recovery_types'][log.recovery_type]['count'] += 1
                if log.success:
                    stats['recovery_types'][log.recovery_type]['success'] += 1

                # Recovery levels
                if log.recovery_level not in stats['recovery_levels']:
                    stats['recovery_levels'][log.recovery_level] = {'count': 0, 'success': 0}
                stats['recovery_levels'][log.recovery_level]['count'] += 1
                if log.success:
                    stats['recovery_levels'][log.recovery_level]['success'] += 1

                # Most recovered workflows
                workflow_id = log.workflow_state_id
                if workflow_id not in stats['most_recovered_workflows']:
                    stats['most_recovered_workflows'][workflow_id] = 0
                stats['most_recovered_workflows'][workflow_id] += 1

            return stats

        except Exception as e:
            log.error(f"Error generating recovery statistics: {e}")
            return {}


# Global persistence manager instance
_persistence_manager = None


def get_persistence_manager() -> WorkflowStatePersistence:
    """Get the global persistence manager instance."""
    global _persistence_manager
    if _persistence_manager is None:
        strategy = PersistenceStrategy(
            current_app.config.get('WORKFLOW_PERSISTENCE_STRATEGY', 'hybrid')
        )
        _persistence_manager = WorkflowStatePersistence(strategy)
    return _persistence_manager


# Convenience functions
def create_workflow_snapshot(workflow_state: WorkflowState, 
                           snapshot_type: str = 'checkpoint') -> str:
    """Create a snapshot of workflow state."""
    manager = get_persistence_manager()
    return manager.create_snapshot(workflow_state, snapshot_type)


def recover_workflow(workflow_state_id: str, snapshot_id: Optional[str] = None) -> bool:
    """Recover workflow from snapshot."""
    manager = get_persistence_manager()
    restored_state = manager.restore_from_snapshot(workflow_state_id, snapshot_id)
    return restored_state is not None


def auto_recover_workflow(workflow_state_id: str) -> bool:
    """Auto-recover workflow from latest snapshot."""
    manager = get_persistence_manager()
    return manager.auto_recover_workflow(workflow_state_id)


# Celery tasks for background operations
def register_persistence_tasks(celery_app):
    """Register Celery tasks for persistence operations."""

    @celery_app.task(name='cleanup_expired_snapshots')
    def cleanup_expired_snapshots_task():
        """Background task to clean up expired snapshots."""
        manager = get_persistence_manager()
        manager.cleanup_expired_snapshots()

    @celery_app.task(name='auto_snapshot_workflows')
    def auto_snapshot_workflows_task():
        """Background task to create automatic snapshots."""
        from ..models import db
        
        manager = get_persistence_manager()
        
        # Get active workflows
        active_workflows = db.session.query(WorkflowState).filter(
            WorkflowState.status == 'in_progress',
            WorkflowState.last_activity_at >= datetime.now(tz=timezone.utc) - timedelta(hours=1)
        ).all()

        snapshot_count = 0
        for workflow_state in active_workflows:
            try:
                manager.create_snapshot(workflow_state, 'auto_checkpoint')
                snapshot_count += 1
            except Exception as e:
                log.error(f"Failed to create auto-snapshot for workflow {workflow_state.id}: {e}")

        log.info(f"Created {snapshot_count} automatic snapshots")
        return snapshot_count


# Decorator for automatic snapshot creation
def auto_snapshot(snapshot_type: str = 'checkpoint'):
    """Decorator to automatically create snapshots after operations."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            result = func(*args, **kwargs)
            
            # Extract workflow_state from args/kwargs
            workflow_state = None
            for arg in args:
                if isinstance(arg, WorkflowState):
                    workflow_state = arg
                    break
            
            if not workflow_state and 'workflow_state' in kwargs:
                workflow_state = kwargs['workflow_state']

            # Create snapshot if workflow_state found
            if workflow_state:
                try:
                    manager = get_persistence_manager()
                    manager.create_snapshot(workflow_state, snapshot_type)
                except Exception as e:
                    log.error(f"Failed to create auto-snapshot: {e}")

            return result
        return wrapper
    return decorator


# Context manager for safe workflow operations
@contextmanager
def safe_workflow_operation(workflow_state_id: str):
    """Context manager for safe workflow operations with automatic recovery."""
    manager = get_persistence_manager()
    
    # Acquire lock
    if not manager.get_workflow_lock(workflow_state_id):
        raise RuntimeError(f"Could not acquire lock for workflow {workflow_state_id}")
    
    try:
        with manager.transaction_safe_operation(workflow_state_id) as workflow_state:
            yield workflow_state
    finally:
        manager.release_workflow_lock(workflow_state_id)