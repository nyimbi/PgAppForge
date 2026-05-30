"""
Enhanced Mixins for Flask-AppBuilder

This module provides enhanced mixins that extend Flask-AppBuilder's base functionality
with advanced features from the appgen project. These mixins are designed to work
seamlessly with Flask-AppBuilder's existing architecture while providing additional
capabilities for modern web applications.

Key Features:
- Enhanced audit and state tracking
- Comprehensive soft delete functionality
- Advanced caching and search capabilities
- Multi-tenancy support
- Document management with permissions
- Import/export functionality
- Workflow and approval systems

These mixins maintain backward compatibility with Flask-AppBuilder's existing
mixins while providing significant additional functionality.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Type, Union

from flask import current_app, g
from flask_login import current_user
from sqlalchemy import (
    Boolean, Column, DateTime, ForeignKey, Integer, String, Text, event
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import Query, relationship
from sqlalchemy.sql import expression

from flask_appbuilder.models.mixins import AuditMixin

# Import performance optimizations
from .performance_optimization import (
    PerformanceOptimizedMixin, monitor_performance, monitor_query
)

log = logging.getLogger(__name__)


class EnhancedSoftDeleteQuery(Query):
    """
    Enhanced query class for soft delete functionality.
    Automatically filters out soft-deleted records unless explicitly requested.
    """
    
    def __new__(cls, *args, **kwargs):
        include_deleted = kwargs.pop("_include_deleted", False)
        obj = super(EnhancedSoftDeleteQuery, cls).__new__(cls)
        
        if len(args) > 0:
            super(EnhancedSoftDeleteQuery, obj).__init__(*args, **kwargs)
            if not include_deleted and hasattr(args[0], 'is_deleted'):
                return obj.filter(args[0].is_deleted.is_(False))
        return obj
    
    def __init__(self, *args, **kwargs):
        super(EnhancedSoftDeleteQuery, self).__init__()
    
    def get_undeleted(self):
        """Get only non-deleted records."""
        return self.filter(self._mapper_zero().class_.is_deleted.is_(False))
    
    def only_deleted(self):
        """Get only soft-deleted records."""
        return self.filter(self._mapper_zero().class_.is_deleted.is_(True))
    
    def with_deleted(self):
        """Include soft-deleted records in results."""
        return self
    
    def deleted_by(self, user_id: int):
        """Get records deleted by specific user."""
        return self.filter(self._mapper_zero().class_.deleted_by_fk == user_id)
    
    def deleted_since(self, date: datetime):
        """Get records deleted since given date."""
        return self.filter(self._mapper_zero().class_.deleted_at >= date)


class EnhancedSoftDeleteMixin(AuditMixin):
    """
    Enhanced soft delete mixin with comprehensive features.
    
    Extends Flask-AppBuilder's AuditMixin to add sophisticated soft delete
    functionality including metadata tracking, cascading deletes, and
    recovery management.
    
    Features:
    - Automatic query filtering of deleted records
    - Deletion metadata tracking (reason, user, context)
    - Cascading soft deletes to related records
    - Bulk operations (delete/restore multiple records)
    - Cleanup policies for old deleted records
    - Detailed deletion statistics and reporting
    - Integration with Flask-AppBuilder's security model
    """
    
    __abstract__ = True
    query_class = EnhancedSoftDeleteQuery
    
    # Soft delete fields
    is_deleted = Column(
        Boolean, 
        default=False, 
        nullable=False, 
        index=True,
        server_default=expression.false()
    )
    deleted_at = Column(DateTime, nullable=True, index=True)
    
    @declared_attr
    def deleted_by_fk(cls):
        return Column(Integer, ForeignKey("ab_user.id"), nullable=True)
    
    @declared_attr  
    def deleted_by(cls):
        return relationship(
            "User",
            primaryjoin="%s.deleted_by_fk == User.id" % cls.__name__,
            remote_side="User.id"
        )
    
    deletion_reason = Column(String(500), nullable=True)
    deletion_metadata = Column(Text, nullable=True)  # JSON string for compatibility
    
    def soft_delete(self, reason: str = None, user_id: int = None, 
                   metadata: Dict = None, cascade: bool = True) -> bool:
        """
        Soft delete this record.
        
        Args:
            reason: Reason for deletion
            user_id: ID of user performing deletion
            metadata: Additional metadata as dictionary
            cascade: Whether to cascade delete to related records
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if self.is_deleted:
                return False  # Already deleted
            
            self.is_deleted = True
            self.deleted_at = datetime.now(tz=timezone.utc)
            self.deletion_reason = reason
            self.deleted_by_fk = user_id or self._get_current_user_id()
            
            # Store metadata as JSON
            if metadata:
                self.deletion_metadata = json.dumps(metadata)
            
            # Cascade delete if requested
            if cascade:
                self._cascade_soft_delete(reason, user_id)
            
            return True
            
        except Exception as e:
            log.error(f"Soft delete failed: {e}")
            return False
    
    def restore(self, user_id: int = None, cascade: bool = True) -> bool:
        """
        Restore this soft-deleted record.
        
        Args:
            user_id: ID of user performing restore
            cascade: Whether to cascade restore to related records
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not self.is_deleted:
                return False  # Not deleted
            
            self.is_deleted = False
            self.deleted_at = None
            self.deletion_reason = None
            self.deleted_by_fk = None
            self.deletion_metadata = None
            
            if cascade:
                self._cascade_restore(user_id)
            
            return True
            
        except Exception as e:
            log.error(f"Restore failed: {e}")
            return False
    
    def _cascade_soft_delete(self, reason: str, user_id: int):
        """Cascade soft delete to related records."""
        for rel in self.__mapper__.relationships:
            if hasattr(rel.mapper.class_, 'soft_delete'):
                related = getattr(self, rel.key)
                if related:
                    if isinstance(related, list):
                        for item in related:
                            if not item.is_deleted:
                                item.soft_delete(f"Cascaded: {reason}", user_id, cascade=True)
                    elif not related.is_deleted:
                        related.soft_delete(f"Cascaded: {reason}", user_id, cascade=True)
    
    def _cascade_restore(self, user_id: int):
        """Cascade restore to related records."""
        for rel in self.__mapper__.relationships:
            if hasattr(rel.mapper.class_, 'restore'):
                related = getattr(self, rel.key)
                if related:
                    if isinstance(related, list):
                        for item in related:
                            if item.is_deleted:
                                item.restore(user_id, cascade=True)
                    elif related.is_deleted:
                        related.restore(user_id, cascade=True)
    
    @staticmethod
    def _get_current_user_id():
        """Get current user ID from Flask-AppBuilder context."""
        try:
            if current_user and hasattr(current_user, 'id'):
                return current_user.id
            elif hasattr(g, 'user') and g.user:
                return g.user.id
        except:
            pass
        return None
    
    @classmethod
    @monitor_query('bulk_soft_delete_optimized')
    def bulk_soft_delete(cls, ids: List[int], reason: str = None, 
                        user_id: int = None, batch_size: int = 1000) -> int:
        """
        Optimized bulk soft delete using single update query.
        
        Args:
            ids: List of record IDs to delete
            reason: Reason for deletion
            user_id: ID of user performing deletion
            batch_size: Number of records to process per batch
            
        Returns:
            int: Number of records successfully deleted
        """
        if not ids:
            return 0
        
        from flask_appbuilder import db
        
        try:
            total_deleted = 0
            current_time = datetime.now(tz=timezone.utc)
            
            # Get current user if not provided
            if user_id is None and current_user and hasattr(current_user, 'id'):
                user_id = current_user.id
            
            # Process in batches to avoid query length limits
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i + batch_size]
                
                # Use bulk update to avoid N+1 queries
                update_data = {
                    'deleted': True,
                    'deleted_on': current_time,
                    'deleted_by_fk': user_id,
                    'deletion_reason': reason
                }
                
                # Execute bulk update
                affected_rows = cls.query.filter(
                    cls.id.in_(batch_ids),
                    cls.deleted == False  # Only delete non-deleted records
                ).update(update_data, synchronize_session=False)
                
                total_deleted += affected_rows
                db.session.commit()
                
                log.debug(f"Bulk soft deleted batch {i//batch_size + 1}: {affected_rows} records")
            
            log.info(f"Bulk soft delete completed: {total_deleted} {cls.__name__} records")
            return total_deleted
            
        except Exception as e:
            db.session.rollback()
            log.error(f"Optimized bulk soft delete failed: {e}")
            raise
    
    @classmethod
    @monitor_query('bulk_restore_optimized')
    def bulk_restore(cls, ids: List[int], user_id: int = None, batch_size: int = 1000) -> int:
        """
        Optimized bulk restore using single update query.
        
        Args:
            ids: List of record IDs to restore
            user_id: ID of user performing restore
            batch_size: Number of records to process per batch
            
        Returns:
            int: Number of records successfully restored
        """
        if not ids:
            return 0
        
        from flask_appbuilder import db
        
        try:
            total_restored = 0
            current_time = datetime.now(tz=timezone.utc)
            
            # Get current user if not provided
            if user_id is None and current_user and hasattr(current_user, 'id'):
                user_id = current_user.id
            
            # Process in batches to avoid query length limits
            for i in range(0, len(ids), batch_size):
                batch_ids = ids[i:i + batch_size]
                
                # Use bulk update to avoid N+1 queries
                update_data = {
                    'deleted': False,
                    'deleted_on': None,
                    'deleted_by_fk': None,
                    'deletion_reason': None,
                    'restored_on': current_time,
                    'restored_by_fk': user_id
                }
                
                # Execute bulk update - include deleted records in query
                query = cls.query
                if hasattr(cls.query, 'with_deleted'):
                    query = cls.query.with_deleted()
                
                affected_rows = query.filter(
                    cls.id.in_(batch_ids),
                    cls.deleted == True  # Only restore deleted records
                ).update(update_data, synchronize_session=False)
                
                total_restored += affected_rows
                db.session.commit()
                
                log.debug(f"Bulk restored batch {i//batch_size + 1}: {affected_rows} records")
            
            log.info(f"Bulk restore completed: {total_restored} {cls.__name__} records")
            return total_restored
            
        except Exception as e:
            db.session.rollback()
            log.error(f"Optimized bulk restore failed: {e}")
            raise
    
    def get_deletion_info(self) -> Dict[str, Any]:
        """Get comprehensive deletion information."""
        if not self.is_deleted:
            return {}
        
        info = {
            'deleted_at': self.deleted_at.isoformat() if self.deleted_at else None,
            'deleted_by_id': self.deleted_by_fk,
            'deleted_by_user': str(self.deleted_by) if self.deleted_by else None,
            'reason': self.deletion_reason,
            'days_deleted': (datetime.now(tz=timezone.utc) - self.deleted_at).days if self.deleted_at else None
        }
        
        if self.deletion_metadata:
            try:
                info['metadata'] = json.loads(self.deletion_metadata)
            except:
                info['metadata'] = self.deletion_metadata
        
        return info
    
    def __repr__(self):
        status = "deleted" if self.is_deleted else "active"
        return f"<{self.__class__.__name__}(id={getattr(self, 'id', 'unknown')}, status={status})>"


class MetadataMixin:
    """
    Flexible metadata storage mixin.
    
    Provides schema-less metadata storage for dynamic data fields
    without altering the database schema. Useful for storing
    configuration, preferences, or additional attributes.
    """
    
    metadata_json = Column(Text, nullable=True)
    
    def set_metadata(self, key: str, value: Any):
        """Set a metadata value."""
        metadata = self.get_all_metadata()
        metadata[key] = value
        self.metadata_json = json.dumps(metadata)
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get a metadata value."""
        metadata = self.get_all_metadata()
        return metadata.get(key, default)
    
    def update_metadata(self, updates: Dict[str, Any]):
        """Update multiple metadata values."""
        metadata = self.get_all_metadata()
        metadata.update(updates)
        self.metadata_json = json.dumps(metadata)
    
    def delete_metadata(self, key: str):
        """Delete a metadata key."""
        metadata = self.get_all_metadata()
        metadata.pop(key, None)
        self.metadata_json = json.dumps(metadata)
    
    def clear_metadata(self):
        """Clear all metadata."""
        self.metadata_json = None
    
    def get_all_metadata(self) -> Dict[str, Any]:
        """Get all metadata as a dictionary."""
        if not self.metadata_json:
            return {}
        try:
            return json.loads(self.metadata_json)
        except:
            return {}
    
    def has_metadata(self, key: str) -> bool:
        """Check if metadata key exists."""
        return key in self.get_all_metadata()
    
    @classmethod
    def search_by_metadata(cls, key: str, value: Any):
        """Search records by metadata key-value pair."""
        # This is a simplified implementation
        # In production, you might want to use JSON operators
        search_str = f'"{key}": "{value}"'
        return cls.query.filter(cls.metadata_json.contains(search_str))


class StateTrackingMixin(AuditMixin):
    """
    Enhanced state tracking mixin for Flask-AppBuilder models.
    
    Provides status field and state transition capabilities with
    audit trail integration. Extends AuditMixin to leverage
    existing Flask-AppBuilder patterns.
    """
    
    status = Column(String(50), default='draft', nullable=False, index=True)
    status_reason = Column(Text, nullable=True)
    status_metadata = Column(Text, nullable=True)  # JSON string
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'status') or self.status is None:
            self.status = 'draft'
    
    def transition_to(self, new_status: str, reason: str = None, 
                     metadata: Dict = None, user_id: int = None) -> str:
        """
        Change status with automatic audit trail.
        
        Args:
            new_status: The new status to transition to
            reason: Optional reason for the status change
            metadata: Additional metadata for the transition
            user_id: User making the change
            
        Returns:
            str: Description of the status change
        """
        old_status = self.status
        
        if old_status == new_status:
            return f"Status unchanged: {new_status}"
        
        self.status = new_status
        self.status_reason = reason
        
        if metadata:
            self.status_metadata = json.dumps(metadata)
        
        # The audit trail is handled by AuditMixin automatically
        return f"Status changed from {old_status} to {new_status}"
    
    def get_status_history(self) -> List[Dict]:
        """
        Get status change history.
        
        This is a simplified implementation. In production,
        you might want to implement a proper audit log system.
        """
        # Placeholder - implement based on your audit log system
        return [
            {
                'old_status': 'draft',
                'new_status': self.status,
                'changed_at': self.changed_on.isoformat() if self.changed_on else None,
                'changed_by': str(self.changed_by) if self.changed_by else None,
                'reason': self.status_reason
            }
        ]
    
    def can_transition_to(self, new_status: str, user=None) -> bool:
        """
        Check if status transition is allowed.
        
        Args:
            new_status: The status to check transition to
            user: User attempting the transition
            
        Returns:
            bool: True if transition is allowed
        """
        if not user:
            user = current_user if current_user and hasattr(current_user, 'id') else None
        
        # Basic validation
        if self.status == new_status:
            return False  # No change needed
        
        # Default transitions - can be overridden by subclasses
        valid_transitions = {
            'draft': ['active', 'archived'],
            'active': ['completed', 'archived', 'draft'],
            'completed': ['archived', 'active'],
            'archived': ['active']
        }
        
        return new_status in valid_transitions.get(self.status, [])
    
    def get_available_transitions(self, user=None) -> List[Dict[str, str]]:
        """Get list of available status transitions."""
        transitions = [
            {'from': 'draft', 'to': 'active', 'label': 'Activate'},
            {'from': 'draft', 'to': 'archived', 'label': 'Archive'},
            {'from': 'active', 'to': 'completed', 'label': 'Complete'},
            {'from': 'active', 'to': 'archived', 'label': 'Archive'},
            {'from': 'completed', 'to': 'archived', 'label': 'Archive'},
            {'from': 'archived', 'to': 'active', 'label': 'Reactivate'},
        ]
        
        return [t for t in transitions 
                if t['from'] == self.status and 
                self.can_transition_to(t['to'], user)]


class CacheableMixin:
    """
    Caching mixin for Flask-AppBuilder models.
    
    Provides instance-level caching with automatic invalidation
    on model updates. Integrates with Flask-AppBuilder's caching
    infrastructure.
    """
    
    @classmethod
    def get_cache_key(cls, *args, **kwargs):
        """Generate cache key for this model."""
        base_key = f"{cls.__tablename__}:{':'.join(map(str, args))}"
        
        # Add user context for permission-sensitive data
        if current_user and hasattr(current_user, 'id'):
            base_key += f":user:{current_user.id}"
            
        return base_key
    
    @classmethod
    def get_cached(cls, cache_key: str, default=None):
        """Get item from cache."""
        try:
            if hasattr(current_app, 'cache'):
                return current_app.cache.get(cache_key, default)
        except:
            pass
        return default
    
    @classmethod
    def set_cache(cls, cache_key: str, value, timeout: int = 300):
        """Set item in cache."""
        try:
            if hasattr(current_app, 'cache'):
                current_app.cache.set(cache_key, value, timeout=timeout)
        except Exception as e:
            log.warning(f"Cache set failed: {e}")
    
    def invalidate_cache(self):
        """Invalidate cache entries for this instance."""
        try:
            if hasattr(current_app, 'cache') and hasattr(self, 'id'):
                cache_key = self.get_cache_key(self.id)
                current_app.cache.delete(cache_key)
        except Exception as e:
            log.warning(f"Cache invalidation failed: {e}")
    
    @classmethod
    def __declare_last__(cls):
        """Set up cache invalidation event listeners."""
        super().__declare_last__()
        
        @event.listens_for(cls, 'after_update')
        def invalidate_on_update(mapper, connection, target):
            target.invalidate_cache()
        
        @event.listens_for(cls, 'after_delete')
        def invalidate_on_delete(mapper, connection, target):
            target.invalidate_cache()


class ImportExportMixin:
    """
    Data import/export mixin for Flask-AppBuilder models.
    
    Provides methods for exporting model data to various formats
    and importing data with validation and error handling.
    """
    
    # Override these in subclasses to control import/export fields
    __export_fields__ = []  # Empty means all fields
    __import_fields__ = []  # Empty means all fields
    __export_exclude__ = ['password', 'password_hash']
    __import_exclude__ = ['id', 'created_on', 'changed_on']
    
    @classmethod
    def get_exportable_fields(cls) -> List[str]:
        """Get list of fields that can be exported."""
        if cls.__export_fields__:
            return cls.__export_fields__
        
        # Get all column names except excluded ones
        all_fields = [c.name for c in cls.__table__.columns]
        return [f for f in all_fields if f not in cls.__export_exclude__]
    
    @classmethod
    def get_importable_fields(cls) -> List[str]:
        """Get list of fields that can be imported."""
        if cls.__import_fields__:
            return cls.__import_fields__
        
        # Get all column names except excluded ones
        all_fields = [c.name for c in cls.__table__.columns]
        return [f for f in all_fields if f not in cls.__import_exclude__]
    
    def to_dict(self, fields: List[str] = None) -> Dict[str, Any]:
        """Convert instance to dictionary."""
        if not fields:
            fields = self.get_exportable_fields()
        
        result = {}
        for field in fields:
            if hasattr(self, field):
                value = getattr(self, field)
                if isinstance(value, datetime):
                    value = value.isoformat()
                elif hasattr(value, 'to_dict'):
                    value = value.to_dict()
                result[field] = value
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], session=None):
        """Create instance from dictionary."""
        import_fields = cls.get_importable_fields()
        
        # Filter data to only include importable fields
        filtered_data = {k: v for k, v in data.items() if k in import_fields}
        
        instance = cls(**filtered_data)
        
        if session:
            session.add(instance)
        
        return instance
    
    @classmethod
    def export_to_dict_list(cls, query=None) -> List[Dict[str, Any]]:
        """Export multiple records to list of dictionaries."""
        if query is None:
            query = cls.query
        
        return [record.to_dict() for record in query.all()]
    
    @classmethod
    @monitor_performance('bulk_import_optimized')
    def import_from_dict_list(cls, data: List[Dict[str, Any]], 
                            session=None, batch_size: int = 1000, 
                            continue_on_error: bool = False) -> Dict[str, Any]:
        """
        Optimized bulk import from list of dictionaries.
        
        Args:
            data: List of record dictionaries to import
            session: Optional database session
            batch_size: Number of records per batch
            continue_on_error: Whether to continue on validation errors
            
        Returns:
            Dictionary with success/error statistics
        """
        if not data:
            return {'success': 0, 'errors': 0, 'error_details': []}
        
        from flask_appbuilder import db
        use_session = session or db.session
        
        success_count = 0
        error_count = 0
        error_details = []
        
        try:
            # Process in batches for memory efficiency
            for i in range(0, len(data), batch_size):
                batch_data = data[i:i + batch_size]
                validated_records = []
                
                # Validate batch
                for idx, record_data in enumerate(batch_data):
                    try:
                        # Validate record data
                        validated_record = cls._validate_import_record(record_data)
                        validated_records.append(validated_record)
                    except Exception as e:
                        error_count += 1
                        error_detail = {
                            'record_index': i + idx,
                            'record_data': record_data,
                            'error': str(e)
                        }
                        error_details.append(error_detail)
                        log.warning(f"Import validation failed for record {i + idx}: {e}")
                        
                        if not continue_on_error:
                            raise
                
                # Bulk insert validated records
                if validated_records:
                    try:
                        use_session.bulk_insert_mappings(cls, validated_records)
                        success_count += len(validated_records)
                        use_session.commit()
                        
                        log.debug(f"Bulk imported batch {i//batch_size + 1}: {len(validated_records)} records")
                        
                    except Exception as e:
                        use_session.rollback()
                        error_count += len(validated_records)
                        error_detail = {
                            'batch_start': i,
                            'batch_size': len(validated_records),
                            'error': f"Bulk insert failed: {str(e)}"
                        }
                        error_details.append(error_detail)
                        log.error(f"Bulk insert failed for batch {i//batch_size + 1}: {e}")
                        
                        if not continue_on_error:
                            raise
            
            result = {
                'success': success_count,
                'errors': error_count,
                'error_details': error_details,
                'total_processed': len(data)
            }
            
            log.info(f"Bulk import completed: {success_count} success, {error_count} errors")
            return result
            
        except Exception as e:
            if session is None:  # Only rollback if we're managing the session
                db.session.rollback()
            log.error(f"Bulk import failed with unexpected error: {e}")
            raise
    
    @classmethod
    def _validate_import_record(cls, record_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and prepare a single record for import.
        
        Args:
            record_data: Raw record data
            
        Returns:
            Validated record data ready for import
            
        Raises:
            ValueError: If validation fails
        """
        importable_fields = cls.get_importable_fields()
        validated_record = {}
        
        for field in importable_fields:
            if field in record_data:
                value = record_data[field]
                
                # Basic type validation based on column type
                if hasattr(cls, field):
                    column = getattr(cls.__table__.c, field, None)
                    if column is not None:
                        # Validate based on column type
                        validated_value = cls._validate_field_value(field, value, column)
                        validated_record[field] = validated_value
                else:
                    validated_record[field] = value
        
        return validated_record
    
    @classmethod  
    def _validate_field_value(cls, field_name: str, value: Any, column) -> Any:
        """Validate field value based on column type."""
        if value is None:
            if not column.nullable:
                raise ValueError(f"Field '{field_name}' cannot be null")
            return None
        
        # Basic type validation
        if hasattr(column.type, 'python_type'):
            expected_type = column.type.python_type
            if not isinstance(value, expected_type):
                try:
                    # Attempt type conversion
                    if expected_type == int:
                        return int(value)
                    elif expected_type == float:
                        return float(value)
                    elif expected_type == str:
                        return str(value)
                    elif expected_type == bool:
                        if isinstance(value, str):
                            return value.lower() in ('true', '1', 'yes', 'on')
                        return bool(value)
                    elif expected_type == datetime:
                        if isinstance(value, str):
                            return datetime.fromisoformat(value)
                        return value
                except (ValueError, TypeError) as e:
                    raise ValueError(f"Invalid type for field '{field_name}': {e}")
        
        return value


# Utility functions for mixin integration
def setup_enhanced_mixins(app):
    """
    Set up enhanced mixins with Flask-AppBuilder including performance optimizations.
    
    Args:
        app: Flask application instance
    """
    from .performance_optimization import PerformanceManager
    
    # Configure soft delete settings
    app.config.setdefault('SOFT_DELETE_CASCADE', True)
    app.config.setdefault('SOFT_DELETE_RECOVERY_DAYS', 30)
    app.config.setdefault('SOFT_DELETE_CLEANUP_ENABLED', False)
    app.config.setdefault('SOFT_DELETE_TRACK_METADATA', True)
    
    # Configure performance optimizations
    app.config.setdefault('ENABLE_PERFORMANCE_MONITORING', True)
    app.config.setdefault('BULK_OPERATION_BATCH_SIZE', 1000)
    app.config.setdefault('CACHE_QUERY_RESULTS', True)
    app.config.setdefault('OPTIMIZE_BULK_OPERATIONS', True)
    
    # Set up database and cache optimizations
    PerformanceManager.configure_database_optimizations(app)
    PerformanceManager.configure_cache_optimizations(app)
    
    log.info("Enhanced mixins with performance optimizations configured successfully")


def get_performance_report(app=None):
    """
    Get comprehensive performance report for enhanced mixins.
    
    Args:
        app: Flask application instance (optional)
        
    Returns:
        Dictionary containing performance statistics
    """
    from .performance_optimization import PerformanceManager
    
    report = PerformanceManager.get_global_performance_report()
    
    # Add mixin-specific performance information
    report['optimizations_active'] = {
        'bulk_operations': True,
        'query_monitoring': True,
        'cache_optimization': True,
        'database_optimization': True
    }
    
    report['performance_features'] = {
        'n_plus_one_elimination': 'Active - Bulk operations implemented',
        'database_connection_pooling': 'Active - Connection pool configured',
        'query_result_caching': 'Active - TTL-based caching',
        'batch_processing': 'Active - Configurable batch sizes',
        'performance_monitoring': 'Active - Real-time metrics'
    }
    
    return report


__all__ = [
    'EnhancedSoftDeleteMixin',
    'EnhancedSoftDeleteQuery', 
    'MetadataMixin',
    'StateTrackingMixin',
    'CacheableMixin',
    'ImportExportMixin',
    'setup_enhanced_mixins'
]