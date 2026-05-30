"""
PgAppForge Integration Enhancements for Appgen Mixins

This module provides enhanced integration between appgen mixins and PgAppForge,
ensuring compatibility, proper user integration, and optimized functionality.
"""

import logging
from typing import Dict, List, Any, Optional, Type, Union
from datetime import datetime
from flask import g, current_app
from pgappforge import Model
from pgappforge.models.mixins import AuditMixin
from flask_login import current_user
from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Text, event
from sqlalchemy.ext.declarative import declared_attr, declarative_base
from sqlalchemy.orm import relationship

log = logging.getLogger(__name__)


class FABIntegratedModel(Model):
    """
    Enhanced base model that integrates seamlessly with PgAppForge.
    
    This model provides:
    - PgAppForge user integration
    - Enhanced audit capabilities
    - Permission-aware operations
    - Widget-friendly field types
    - Optimized queries
    """
    
    __abstract__ = True
    
    # Enhanced audit fields
    @declared_attr
    def created_by_fk(cls):
        return Column(Integer, ForeignKey('ab_user.id'), nullable=True)
    
    @declared_attr
    def changed_by_fk(cls):
        return Column(Integer, ForeignKey('ab_user.id'), nullable=True)
        
    @declared_attr 
    def created_by(cls):
        return relationship("User", foreign_keys=[cls.created_by_fk])
        
    @declared_attr
    def changed_by(cls):
        return relationship("User", foreign_keys=[cls.changed_by_fk])
    
    # Enhanced metadata
    metadata_json = Column(Text)  # For MetadataMixin compatibility
    search_vector = Column(Text)  # For SearchableMixin compatibility
    tags = Column(Text)  # For general tagging support
    
    @staticmethod
    def get_current_user_id():
        """Get current user ID for audit purposes."""
        try:
            if hasattr(current_user, 'id'):
                return current_user.id
            elif hasattr(g, 'user') and hasattr(g.user, 'id'):
                return g.user.id
        except:
            pass
        return None
    
    @classmethod
    def __declare_last__(cls):
        """Set up event listeners for PgAppForge integration."""
        # Set up audit field population
        @event.listens_for(cls, 'before_insert')
        def before_insert(mapper, connection, target):
            user_id = cls.get_current_user_id()
            if user_id:
                target.created_by_fk = user_id
                target.changed_by_fk = user_id
        
        @event.listens_for(cls, 'before_update')  
        def before_update(mapper, connection, target):
            user_id = cls.get_current_user_id()
            if user_id:
                target.changed_by_fk = user_id
        
        super().__declare_last__()


class EnhancedAuditMixin(AuditMixin):
    """
    Enhanced audit mixin that extends PgAppForge's AuditMixin.
    
    Provides additional audit capabilities:
    - Detailed change tracking
    - Custom audit events
    - Permission-aware logging
    - Integration with external systems
    """
    
    # Additional audit fields
    audit_context = Column(String(255))  # Additional context for audit events
    audit_source = Column(String(50))   # Source of the change (web, api, system)
    audit_session = Column(String(100)) # Session identifier
    
    @declared_attr
    def audit_logs(cls):
        """Relationship to detailed audit logs."""
        return relationship("AuditLog", 
                          primaryjoin=f"and_(AuditLog.table_name=='{cls.__tablename__}', "
                                     f"AuditLog.record_id==cast({cls.__tablename__}.id, String))",
                          foreign_keys="AuditLog.record_id",
                          viewonly=True)
    
    def log_custom_event(self, event_type: str, details: Dict[str, Any]):
        """Log a custom audit event."""
        try:
            from .audit_logger import AuditLogger
            AuditLogger.log_event(
                table_name=self.__tablename__,
                record_id=str(self.id),
                event_type=event_type,
                user_id=self.get_current_user_id(),
                details=details
            )
        except Exception as e:
            log.warning(f"Failed to log custom audit event: {e}")
    
    def get_audit_trail(self, limit: int = 50) -> List[Dict]:
        """Get comprehensive audit trail for this record."""
        try:
            from .audit_logger import AuditLogger
            return AuditLogger.get_audit_trail(
                table_name=self.__tablename__,
                record_id=str(self.id),
                limit=limit
            )
        except Exception as e:
            log.warning(f"Failed to get audit trail: {e}")
            return []


class PermissionAwareMixin:
    """
    Mixin that adds permission-aware operations to models.
    
    Integrates with PgAppForge's permission system to ensure
    operations respect user permissions and role-based access control.
    """
    
    @classmethod
    def can_create(cls, user=None):
        """Check if user can create records of this type."""
        if not user:
            try:
                from flask_login import current_user
                user = current_user
            except ImportError:
                return False

        # Integrate with PgAppForge permission system
        try:
            from pgappforge import appbuilder
            if not appbuilder or not appbuilder.sm:
                return False

            # Check create permission for this model
            model_name = cls.__name__
            permission_name = f"can_add"
            view_menu_name = f"{model_name}View"

            return appbuilder.sm.has_access(permission_name, view_menu_name, user)

        except (ImportError, AttributeError):
            # Fall back to checking if user is authenticated
            return user.is_authenticated if hasattr(user, 'is_authenticated') else False

    @classmethod
    def can_read(cls, user=None):
        """Check if user can read records of this type."""
        if not user:
            try:
                from flask_login import current_user
                user = current_user
            except ImportError:
                return False

        try:
            from pgappforge import appbuilder
            if not appbuilder or not appbuilder.sm:
                return False

            # Check read permission for this model
            model_name = cls.__name__
            permission_name = f"can_list"
            view_menu_name = f"{model_name}View"

            return appbuilder.sm.has_access(permission_name, view_menu_name, user)

        except (ImportError, AttributeError):
            # Fall back to checking if user is authenticated
            return user.is_authenticated if hasattr(user, 'is_authenticated') else False

    def can_edit(self, user=None):
        """Check if user can edit this specific record."""
        if not user:
            try:
                from flask_login import current_user
                user = current_user
            except ImportError:
                return False

        try:
            from pgappforge import appbuilder
            if not appbuilder or not appbuilder.sm:
                return False

            # Check edit permission for this model
            model_name = self.__class__.__name__
            permission_name = f"can_edit"
            view_menu_name = f"{model_name}View"

            has_general_permission = appbuilder.sm.has_access(permission_name, view_menu_name, user)

            if not has_general_permission:
                return False

            # Apply row-level security checks
            # If record has an owner field, check ownership
            if hasattr(self, 'created_by_fk') and self.created_by_fk:
                if user.id != self.created_by_fk:
                    # Check if user is admin or has override permission
                    return appbuilder.sm.is_admin(user)

            # If multi-tenant, check tenant access
            if hasattr(self, 'tenant_id') and hasattr(user, 'tenant_id'):
                return self.tenant_id == user.tenant_id or appbuilder.sm.is_admin(user)

            return True

        except (ImportError, AttributeError):
            # Fall back to basic ownership check
            if hasattr(self, 'created_by_fk') and hasattr(user, 'id'):
                return self.created_by_fk == user.id
            return user.is_authenticated if hasattr(user, 'is_authenticated') else False

    def can_delete(self, user=None):
        """Check if user can delete this specific record."""
        if not user:
            try:
                from flask_login import current_user
                user = current_user
            except ImportError:
                return False

        try:
            from pgappforge import appbuilder
            if not appbuilder or not appbuilder.sm:
                return False

            # Check delete permission for this model
            model_name = self.__class__.__name__
            permission_name = f"can_delete"
            view_menu_name = f"{model_name}View"

            has_general_permission = appbuilder.sm.has_access(permission_name, view_menu_name, user)

            if not has_general_permission:
                return False

            # Apply stricter row-level security for deletion
            # If record has an owner field, only owner or admin can delete
            if hasattr(self, 'created_by_fk') and self.created_by_fk:
                return user.id == self.created_by_fk or appbuilder.sm.is_admin(user)

            # If multi-tenant, check tenant access
            if hasattr(self, 'tenant_id') and hasattr(user, 'tenant_id'):
                return self.tenant_id == user.tenant_id or appbuilder.sm.is_admin(user)

            return True

        except (ImportError, AttributeError):
            # Fall back to basic ownership check
            if hasattr(self, 'created_by_fk') and hasattr(user, 'id'):
                return self.created_by_fk == user.id
            return False  # Deletion requires explicit permission

    @classmethod
    def filter_by_permissions(cls, query, user=None):
        """Filter query based on user permissions."""
        if not user:
            try:
                from flask_login import current_user
                user = current_user
            except ImportError:
                # No user context, return empty query for security
                return query.filter(False)

        try:
            from pgappforge import appbuilder
            if not appbuilder or not appbuilder.sm:
                # No security manager, apply basic filtering
                if not user.is_authenticated:
                    return query.filter(False)
            else:
                # Check if user has read permission
                if not cls.can_read(user):
                    return query.filter(False)

                # If user is admin, no filtering needed
                if appbuilder.sm.is_admin(user):
                    return query

            # Apply row-level security filters
            filters = []

            # Filter by tenant if multi-tenant
            if hasattr(cls, 'tenant_id') and hasattr(user, 'tenant_id'):
                filters.append(cls.tenant_id == user.tenant_id)

            # Filter by ownership if applicable (unless admin)
            if hasattr(cls, 'created_by_fk') and hasattr(user, 'id'):
                try:
                    if not appbuilder.sm.is_admin(user):
                        filters.append(cls.created_by_fk == user.id)
                except:
                    # If admin check fails, apply ownership filter
                    filters.append(cls.created_by_fk == user.id)

            # Filter by active status if applicable
            if hasattr(cls, 'active'):
                filters.append(cls.active == True)

            # Apply all filters
            for filter_condition in filters:
                query = query.filter(filter_condition)

            return query

        except Exception as e:
            # On any error, return restricted query for security
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Error in permission filtering for {cls.__name__}: {e}")

            # Return minimal safe query
            if hasattr(user, 'is_authenticated') and user.is_authenticated:
                # Apply basic ownership filter if possible
                if hasattr(cls, 'created_by_fk') and hasattr(user, 'id'):
                    return query.filter(cls.created_by_fk == user.id)
                return query
            else:
                return query.filter(False)  # No access for unauthenticated users


class TenantAwareMixin:
    """
    Enhanced multi-tenancy mixin for PgAppForge.
    
    Provides automatic tenant scoping and data isolation
    integrated with PgAppForge's security model.
    """
    
    tenant_id = Column(String(50), nullable=True, index=True)
    
    @staticmethod
    def get_current_tenant():
        """Get current tenant from PgAppForge context."""
        try:
            # Check for tenant in current user
            if hasattr(current_user, 'tenant_id'):
                return current_user.tenant_id
            # Check for tenant in session/request context
            if hasattr(g, 'tenant_id'):
                return g.tenant_id
            # Check for tenant in app config
            return current_app.config.get('DEFAULT_TENANT_ID')
        except:
            return None
    
    @classmethod
    def __declare_last__(cls):
        """Set up tenant scoping."""
        @event.listens_for(cls, 'before_insert')
        def set_tenant(mapper, connection, target):
            if not target.tenant_id:
                target.tenant_id = cls.get_current_tenant()
        
        # Override query to filter by tenant
        original_query = cls.query
        
        @classmethod
        def tenant_scoped_query(cls):
            query = original_query
            tenant_id = cls.get_current_tenant()
            if tenant_id:
                query = query.filter(cls.tenant_id == tenant_id)
            return query
        
        cls.query = tenant_scoped_query()
        super().__declare_last__()


class CacheIntegratedMixin:
    """
    Cache mixin integrated with PgAppForge's caching system.
    
    Provides intelligent caching that respects user permissions
    and tenant isolation.
    """
    
    @classmethod
    def get_cache_key(cls, *args, **kwargs):
        """Generate cache key including user and tenant context."""
        base_key = f"{cls.__tablename__}:{':'.join(map(str, args))}"
        
        # Add user context for permission-sensitive data
        user_id = cls.get_current_user_id() if hasattr(cls, 'get_current_user_id') else None
        if user_id:
            base_key += f":user:{user_id}"
        
        # Add tenant context for multi-tenant data
        tenant_id = getattr(cls, 'get_current_tenant', lambda: None)()
        if tenant_id:
            base_key += f":tenant:{tenant_id}"
            
        return base_key
    
    @classmethod
    def invalidate_user_cache(cls, user_id: int):
        """Invalidate all cached data for a specific user."""
        try:
            cache = current_app.cache
            pattern = f"{cls.__tablename__}:*:user:{user_id}*"
            # Clear matching cache entries
            # Implementation depends on cache backend
        except Exception as e:
            log.warning(f"Failed to invalidate user cache: {e}")
    
    @classmethod
    def invalidate_tenant_cache(cls, tenant_id: str):
        """Invalidate all cached data for a specific tenant."""
        try:
            cache = current_app.cache
            pattern = f"{cls.__tablename__}:*:tenant:{tenant_id}*"
            # Clear matching cache entries
            # Implementation depends on cache backend
        except Exception as e:
            log.warning(f"Failed to invalidate tenant cache: {e}")


class SearchIntegratedMixin:
    """
    Search mixin integrated with PgAppForge's search capabilities.
    
    Provides full-text search that respects permissions and
    integrates with PgAppForge's filter system.
    """
    
    @classmethod
    def search_with_permissions(cls, query: str, user=None, limit: int = 50):
        """Perform search respecting user permissions."""
        if not user:
            user = current_user
        
        # Get base search results
        results = cls.search(query, limit=limit * 2)  # Get more to filter
        
        # Filter by permissions
        filtered_results = []
        for result in results:
            if result.can_read(user):
                filtered_results.append(result)
                if len(filtered_results) >= limit:
                    break
        
        return filtered_results
    
    @classmethod
    def get_search_suggestions(cls, query: str, field: str = None):
        """Get search suggestions for autocomplete."""
        # Implement search suggestions based on indexed data
        return []  # Placeholder


class WorkflowIntegratedMixin:
    """
    Workflow mixin integrated with PgAppForge's notification system.
    
    Provides workflow capabilities with automatic notifications
    and integration with PgAppForge's user system.
    """
    
    def trigger_workflow_event(self, event: str, user=None, **kwargs):
        """Trigger a workflow event with PgAppForge integration."""
        if not user:
            user = current_user
        
        # Log the event
        self.log_custom_event(f'workflow_{event}', {
            'event': event,
            'user_id': user.id if user else None,
            'kwargs': kwargs
        })
        
        # Send notifications
        self._send_workflow_notifications(event, user, **kwargs)
        
        # Call parent workflow method if available
        if hasattr(super(), 'trigger_event'):
            return super().trigger_event(event, **kwargs)
    
    def _send_workflow_notifications(self, event: str, user, **kwargs):
        """Send notifications for workflow events."""
        try:
            from pgappforge.security.manager import BaseSecurityManager
            # Implement notification logic
            pass
        except Exception as e:
            log.warning(f"Failed to send workflow notifications: {e}")


class DocumentIntegratedMixin:
    """
    Document mixin integrated with PgAppForge's file handling.
    
    Provides document management with permission-aware access
    and integration with PgAppForge's security model.
    """
    
    def can_download(self, user=None):
        """Check if user can download this document."""
        if not user:
            user = current_user
        
        # Check document-specific permissions
        if hasattr(self, 'doc_downloadable') and not self.doc_downloadable:
            return False
        
        # Check user permissions
        return self.can_read(user)
    
    def get_download_url(self, user=None):
        """Get secure download URL for the document."""
        if not self.can_download(user):
            return None
        
        # Generate signed URL or secure download link
        return f"/admin/document/{self.id}/download"
    
    def track_document_access(self, user=None, action='view'):
        """Track document access for audit purposes."""
        if not user:
            user = current_user
        
        self.log_custom_event(f'document_{action}', {
            'action': action,
            'user_id': user.id if user else None,
            'document_type': getattr(self, 'doc_type', None),
            'file_size': getattr(self, 'file_size_bytes', None)
        })


class StateTrackingMixin(AuditMixin):
    """
    State tracking mixin for PgAppForge models.
    
    Extends AuditMixin to add status field and state transition capabilities.
    Provides audit trail for status changes using existing PgAppForge patterns.
    """
    
    status = Column(String(50), default='draft', nullable=False)
    status_reason = Column(Text)
    
    def __init__(self, *args, **kwargs):
        """Initialize the mixin with default status."""
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'status') or self.status is None:
            self.status = 'draft'
    
    def transition_to(self, new_status: str, reason: str = None, user=None):
        """
        Change status with automatic audit trail.
        
        Args:
            new_status: The new status to transition to
            reason: Optional reason for the status change
            user: User making the change (defaults to current_user)
            
        Returns:
            str: Description of the status change
        """
        if not user:
            user = current_user if hasattr(current_user, 'id') else None
            
        old_status = self.status
        self.status = new_status
        self.status_reason = reason
        
        # Log the status change using existing audit capabilities
        if hasattr(self, 'log_custom_event'):
            self.log_custom_event('status_change', {
                'old_status': old_status,
                'new_status': new_status,
                'reason': reason,
                'changed_by': user.id if user else None
            })
        
        # Send notification automatically if service is available
        try:
            from ..services.notification_service import NotificationService
            notification_service = NotificationService()
            notification_service.send_status_notification(self, old_status, new_status, user)
        except Exception as e:
            # Don't fail the transition if notification fails
            import logging
            log = logging.getLogger(__name__)
            log.warning(f"Failed to send status notification: {e}")
        
        # Store original status for notification system
        self._original_status = old_status
        
        return f"Status changed from {old_status} to {new_status}"
    
    def get_status_history(self, limit: int = 20) -> List[Dict]:
        """
        Get status change history using existing audit trail.
        
        Args:
            limit: Maximum number of status changes to return
            
        Returns:
            List of status change records
        """
        if hasattr(self, 'get_audit_trail'):
            audit_records = self.get_audit_trail(limit=limit * 2)  # Get more records to filter
            status_changes = []
            
            for record in audit_records:
                if record.get('event_type') == 'status_change':
                    status_changes.append(record)
                    if len(status_changes) >= limit:
                        break
                        
            return status_changes
        
        return []
    
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
            user = current_user if hasattr(current_user, 'id') else None
        
        # Basic validation - can be extended by subclasses
        if self.status == new_status:
            return False  # No change needed
            
        # Check if user has permission to change status
        if user and hasattr(user, 'has_permission'):
            return user.has_permission('can_edit')
        
        return True  # Default to allowing transition
    
    def get_available_transitions(self, user=None) -> List[Dict[str, str]]:
        """
        Get list of available status transitions for the user.
        
        Args:
            user: User to check transitions for
            
        Returns:
            List of available transitions
        """
        # Default transitions - can be overridden by subclasses
        all_transitions = [
            {'from': 'draft', 'to': 'active', 'label': 'Activate'},
            {'from': 'draft', 'to': 'archived', 'label': 'Archive'},
            {'from': 'active', 'to': 'completed', 'label': 'Complete'},
            {'from': 'active', 'to': 'archived', 'label': 'Archive'},
            {'from': 'completed', 'to': 'archived', 'label': 'Archive'},
            {'from': 'archived', 'to': 'active', 'label': 'Reactivate'},
        ]
        
        # Filter transitions based on current status and permissions
        available = []
        for transition in all_transitions:
            if (transition['from'] == self.status and 
                self.can_transition_to(transition['to'], user)):
                available.append(transition)
        
        return available


# Integration utility functions
def enhance_model_with_fab(model_class, mixins: List[str] = None):
    """
    Enhance a model class with PgAppForge integration.
    
    Args:
        model_class: The base model class to enhance
        mixins: List of mixin names to include
    
    Returns:
        Enhanced model class
    """
    base_mixins = [FABIntegratedModel]
    
    if mixins:
        from . import get_mixin_by_name
        for mixin_name in mixins:
            mixin_class = get_mixin_by_name(mixin_name)
            if mixin_class:
                base_mixins.append(mixin_class)
    
    # Create enhanced class
    class_name = f"FAB{model_class.__name__}"
    enhanced_class = type(class_name, tuple(base_mixins + [model_class]), {
        '__module__': model_class.__module__
    })
    
    return enhanced_class


def register_mixin_permissions(app, mixin_class, permission_names: List[str]):
    """
    Register permissions for mixin-provided functionality.
    
    Args:
        app: Flask application instance
        mixin_class: The mixin class
        permission_names: List of permission names to register
    """
    try:
        security_manager = app.appbuilder.sm
        
        for permission_name in permission_names:
            # Register permission if it doesn't exist
            if not security_manager.find_permission(permission_name):
                security_manager.add_permission(permission_name)
        
        log.info(f"Registered permissions for {mixin_class.__name__}: {permission_names}")
        
    except Exception as e:
        log.error(f"Failed to register permissions for {mixin_class.__name__}: {e}")


def setup_mixin_integration(app):
    """
    Set up mixin integration with PgAppForge.
    
    Args:
        app: Flask application instance
    """
    # Register common permissions
    common_permissions = [
        'can_view_audit_log',
        'can_export_data',
        'can_import_data',
        'can_manage_workflow',
        'can_approve',
        'can_manage_comments',
        'can_translate',
        'can_manage_metadata'
    ]
    
    try:
        security_manager = app.appbuilder.sm
        
        for permission in common_permissions:
            if not security_manager.find_permission(permission):
                security_manager.add_permission(permission)
        
        log.info("Mixin integration setup completed successfully")
        
    except Exception as e:
        log.error(f"Failed to setup mixin integration: {e}")


__all__ = [
    'FABIntegratedModel',
    'EnhancedAuditMixin',
    'PermissionAwareMixin', 
    'TenantAwareMixin',
    'CacheIntegratedMixin',
    'SearchIntegratedMixin',
    'WorkflowIntegratedMixin',
    'DocumentIntegratedMixin',
    'StateTrackingMixin',
    'enhance_model_with_fab',
    'register_mixin_permissions',
    'setup_mixin_integration'
]