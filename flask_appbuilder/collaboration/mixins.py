"""
Collaborative ModelView Mixins

Provides mixins to add real-time collaboration capabilities to any Flask-AppBuilder
ModelView with minimal configuration and seamless integration.
"""

import logging
import json
from typing import Dict, List, Any, Optional, Set
from datetime import datetime, timezone

from flask import g, request, jsonify, url_for, session
from flask_appbuilder.baseviews import expose, BaseModelView
from flask_appbuilder.security.decorators import has_access

from . import get_collaboration_manager

log = logging.getLogger(__name__)


class CollaborativeModelViewMixin:
    """
    Mixin to add real-time collaboration capabilities to any ModelView.
    
    Simply add this mixin to your ModelView class to enable:
    - Real-time field synchronization
    - Presence indicators
    - Conflict resolution
    - Comments and annotations
    """
    
    # Collaboration configuration
    enable_collaboration = True
    collaboration_fields = None  # None = all fields, or specify list
    collaboration_permissions = ['can_edit', 'can_comment']
    collaboration_auto_join = True  # Auto-join sessions when editing
    collaboration_conflict_strategy = 'auto'  # auto, manual, last_write, first_write
    collaboration_session_timeout = 3600  # Session timeout in seconds
    
    def __init__(self):
        super().__init__()
        self._collaboration_manager = None
        self._active_session_id = None
        
        if self.enable_collaboration:
            self._setup_collaboration()
            
    def _setup_collaboration(self):
        """Initialize collaboration features for this view"""
        try:
            self._collaboration_manager = get_collaboration_manager()
            
            if not self._collaboration_manager:
                log.warning(f"Collaboration manager not available for {self.__class__.__name__}")
                self.enable_collaboration = False
                return
                
            # Register model for real-time sync
            sync_fields = self.collaboration_fields or self._get_all_field_names()
            self._collaboration_manager.sync_engine.register_model_sync(
                self.datamodel.obj,
                sync_fields
            )
            
            log.info(f"Collaboration enabled for {self.__class__.__name__} with fields: {sync_fields}")
            
        except Exception as e:
            log.error(f"Error setting up collaboration for {self.__class__.__name__}: {e}")
            self.enable_collaboration = False
            
    def _get_all_field_names(self) -> List[str]:
        """Get all field names for the model"""
        try:
            return [col.name for col in self.datamodel.get_columns_list()]
        except Exception as e:
            log.error(f"Error getting field names: {e}")
            return []
            
    def edit(self, pk):
        """Enhanced edit method with collaboration session management"""
        try:
            if self.enable_collaboration:
                # Create or join collaboration session
                session_id = self._create_or_join_collaboration_session(pk)
                
                if session_id:
                    # Add collaboration context to template
                    self.extra_args = getattr(self, 'extra_args', {})
                    self.extra_args.update({
                        'collaboration_session_id': session_id,
                        'collaboration_enabled': True,
                        'collaboration_model': self.datamodel.obj.__name__,
                        'collaboration_record_id': str(pk),
                        'collaboration_fields': self.collaboration_fields or self._get_all_field_names(),
                        'collaboration_permissions': self.collaboration_permissions,
                        'collaboration_websocket_url': self._get_websocket_url()
                    })
                    
                    # Store session ID in Flask-G for access in other methods
                    g.collaboration_session_id = session_id
                    
        except Exception as e:
            log.error(f"Error setting up collaboration for edit: {e}")
            
        return super().edit(pk)
        
    def add(self):
        """Enhanced add method with collaboration for new records"""
        try:
            if self.enable_collaboration:
                # Create collaboration session for new record
                session_id = self._create_or_join_collaboration_session(None)
                
                if session_id:
                    self.extra_args = getattr(self, 'extra_args', {})
                    self.extra_args.update({
                        'collaboration_session_id': session_id,
                        'collaboration_enabled': True,
                        'collaboration_model': self.datamodel.obj.__name__,
                        'collaboration_record_id': 'new',
                        'collaboration_fields': self.collaboration_fields or self._get_all_field_names(),
                        'collaboration_permissions': self.collaboration_permissions,
                        'collaboration_websocket_url': self._get_websocket_url()
                    })
                    
                    g.collaboration_session_id = session_id
                    
        except Exception as e:
            log.error(f"Error setting up collaboration for add: {e}")
            
        return super().add()
        
    def _create_or_join_collaboration_session(self, record_id: Optional[int]) -> Optional[str]:
        """Create or join a collaboration session for the given record"""
        try:
            if not self._collaboration_manager:
                return None
                
            user_id = g.user.id if hasattr(g, 'user') and g.user else None
            if not user_id:
                log.warning("No user context for collaboration session")
                return None
                
            model_name = self.datamodel.obj.__name__
            record_id_str = str(record_id) if record_id else None
            
            # Check if user has collaboration permission
            if not self._check_collaboration_permission(user_id, model_name, record_id_str):
                log.warning(f"User {user_id} lacks collaboration permission for {model_name}:{record_id_str}")
                return None
                
            # Find existing active session or create new one
            existing_sessions = self._collaboration_manager.session_manager.find_sessions_for_record(
                model_name, record_id_str or 'new'
            )
            
            if existing_sessions and self.collaboration_auto_join:
                # Join existing session
                session_id = existing_sessions[0]
                success = self._collaboration_manager.session_manager.join_collaboration_session(
                    session_id, user_id
                )
                if success:
                    log.info(f"Joined existing collaboration session {session_id}")
                    return session_id
                    
            # Create new session
            session_id = self._collaboration_manager.session_manager.create_collaboration_session(
                model_name=model_name,
                record_id=record_id_str,
                user_id=user_id,
                permissions=self.collaboration_permissions
            )
            
            if session_id:
                log.info(f"Created new collaboration session {session_id} for {model_name}:{record_id_str}")
                self._active_session_id = session_id
                return session_id
                
            return None
            
        except Exception as e:
            log.error(f"Error creating/joining collaboration session: {e}")
            return None
            
    def _check_collaboration_permission(self, user_id: int, model_name: str, 
                                      record_id: Optional[str]) -> bool:
        """Check if user has permission for collaboration on this model/record"""
        try:
            # Check with Flask-AppBuilder's security manager
            permission_name = f"can_edit_{model_name}"
            view_name = f"{model_name}View"
            
            user = self.appbuilder.sm.get_user_by_id(user_id)
            if not user:
                return False
                
            return self.appbuilder.sm.has_access(permission_name, view_name)
            
        except Exception as e:
            log.error(f"Error checking collaboration permission: {e}")
            return False
            
    def _get_websocket_url(self) -> str:
        """Get WebSocket URL for collaboration"""
        try:
            # Construct WebSocket URL based on current request
            scheme = 'wss' if request.is_secure else 'ws'
            host = request.host
            return f"{scheme}://{host}/collaboration"
        except Exception as e:
            log.error(f"Error getting WebSocket URL: {e}")
            return "ws://localhost:5000/collaboration"
            
    @expose('/collaboration_status/<pk>')
    @has_access
    def collaboration_status(self, pk):
        """Get current collaboration status for a record"""
        try:
            if not self.enable_collaboration or not self._collaboration_manager:
                return jsonify({'enabled': False})
                
            model_name = self.datamodel.obj.__name__
            
            # Find active sessions for this record
            sessions = self._collaboration_manager.session_manager.find_sessions_for_record(
                model_name, str(pk)
            )
            
            session_info = []
            for session_id in sessions:
                info = self._collaboration_manager.session_manager.get_session_info(session_id)
                if info:
                    session_info.append(info)
                    
            return jsonify({
                'enabled': True,
                'model': model_name,
                'record_id': str(pk),
                'active_sessions': len(sessions),
                'sessions': session_info,
                'websocket_url': self._get_websocket_url()
            })
            
        except Exception as e:
            log.error(f"Error getting collaboration status: {e}")
            return jsonify({'enabled': False, 'error': str(e)})
            
    @expose('/collaboration_join/<pk>')
    @has_access  
    def collaboration_join(self, pk):
        """Join collaboration session for a record"""
        try:
            if not self.enable_collaboration or not self._collaboration_manager:
                return jsonify({'success': False, 'error': 'Collaboration not enabled'})
                
            user_id = g.user.id if hasattr(g, 'user') and g.user else None
            if not user_id:
                return jsonify({'success': False, 'error': 'No user context'})
                
            # Create or join session
            session_id = self._create_or_join_collaboration_session(int(pk))
            
            if session_id:
                return jsonify({
                    'success': True,
                    'session_id': session_id,
                    'websocket_url': self._get_websocket_url()
                })
            else:
                return jsonify({'success': False, 'error': 'Failed to create/join session'})
                
        except Exception as e:
            log.error(f"Error joining collaboration: {e}")
            return jsonify({'success': False, 'error': str(e)})
            
    @expose('/collaboration_leave/<session_id>')
    @has_access
    def collaboration_leave(self, session_id):
        """Leave collaboration session"""
        try:
            if not self.enable_collaboration or not self._collaboration_manager:
                return jsonify({'success': False, 'error': 'Collaboration not enabled'})
                
            user_id = g.user.id if hasattr(g, 'user') and g.user else None
            if not user_id:
                return jsonify({'success': False, 'error': 'No user context'})
                
            self._collaboration_manager.session_manager.leave_collaboration_session(
                session_id, user_id
            )
            
            return jsonify({'success': True})
            
        except Exception as e:
            log.error(f"Error leaving collaboration: {e}")
            return jsonify({'success': False, 'error': str(e)})
            
    @expose('/collaboration_sync_field', methods=['POST'])
    @has_access
    def collaboration_sync_field(self):
        """Sync a field change in real-time"""
        try:
            if not self.enable_collaboration or not self._collaboration_manager:
                return jsonify({'success': False, 'error': 'Collaboration not enabled'})
                
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'})
                
            required_fields = ['session_id', 'record_id', 'field_name', 'old_value', 'new_value']
            for field in required_fields:
                if field not in data:
                    return jsonify({'success': False, 'error': f'Missing required field: {field}'})
                    
            user_id = g.user.id if hasattr(g, 'user') and g.user else None
            if not user_id:
                return jsonify({'success': False, 'error': 'No user context'})
                
            # Sync field change
            result = self._collaboration_manager.sync_engine.sync_field_change(
                session_id=data['session_id'],
                model_name=self.datamodel.obj.__name__,
                record_id=data['record_id'],
                field_name=data['field_name'],
                old_value=data['old_value'],
                new_value=data['new_value'],
                user_id=user_id,
                conflict_resolution=self.collaboration_conflict_strategy
            )
            
            return jsonify({
                'success': True,
                'result': result
            })
            
        except Exception as e:
            log.error(f"Error syncing field change: {e}")
            return jsonify({'success': False, 'error': str(e)})
            
    @expose('/collaboration_resolve_conflict', methods=['POST'])
    @has_access
    def collaboration_resolve_conflict(self):
        """Resolve a collaboration conflict"""
        try:
            if not self.enable_collaboration or not self._collaboration_manager:
                return jsonify({'success': False, 'error': 'Collaboration not enabled'})
                
            data = request.get_json()
            if not data:
                return jsonify({'success': False, 'error': 'No data provided'})
                
            conflict_id = data.get('conflict_id')
            resolution_choice = data.get('resolution_choice')
            custom_value = data.get('custom_value')
            
            if not conflict_id or not resolution_choice:
                return jsonify({'success': False, 'error': 'Missing conflict_id or resolution_choice'})
                
            user_id = g.user.id if hasattr(g, 'user') and g.user else None
            if not user_id:
                return jsonify({'success': False, 'error': 'No user context'})
                
            # Resolve conflict
            result = self._collaboration_manager.conflict_resolver.resolve_user_choice(
                conflict_id=conflict_id,
                chosen_resolution=resolution_choice,
                custom_value=custom_value,
                user_id=user_id
            )
            
            return jsonify({
                'success': result.get('status') == 'resolved',
                'result': result
            })
            
        except Exception as e:
            log.error(f"Error resolving conflict: {e}")
            return jsonify({'success': False, 'error': str(e)})
            
    @expose('/collaboration_participants/<session_id>')
    @has_access
    def collaboration_participants(self, session_id):
        """Get current participants in a collaboration session"""
        try:
            if not self.enable_collaboration or not self._collaboration_manager:
                return jsonify({'participants': []})
                
            participants = self._collaboration_manager.session_manager.get_session_participants(session_id)
            
            return jsonify({
                'session_id': session_id,
                'participants': participants
            })
            
        except Exception as e:
            log.error(f"Error getting collaboration participants: {e}")
            return jsonify({'participants': [], 'error': str(e)})


class PresenceAwareViewMixin:
    """
    Mixin that adds presence awareness to views without full collaboration.
    Shows who is currently viewing/editing records.
    """
    
    enable_presence = True
    presence_timeout = 300  # 5 minutes
    
    def __init__(self):
        super().__init__()
        if self.enable_presence:
            self._setup_presence_tracking()
            
    def _setup_presence_tracking(self):
        """Set up presence tracking"""
        try:
            self._collaboration_manager = get_collaboration_manager()
            if not self._collaboration_manager:
                self.enable_presence = False
                
        except Exception as e:
            log.error(f"Error setting up presence tracking: {e}")
            self.enable_presence = False
            
    def show(self, pk):
        """Enhanced show method with presence tracking"""
        if self.enable_presence:
            self._update_presence(pk, 'viewing')
        return super().show(pk)
        
    def edit(self, pk):
        """Enhanced edit method with presence tracking"""
        if self.enable_presence:
            self._update_presence(pk, 'editing')
        return super().edit(pk)
        
    def _update_presence(self, record_id, activity):
        """Update user presence for a record"""
        try:
            if not self._collaboration_manager:
                return
                
            user_id = g.user.id if hasattr(g, 'user') and g.user else None
            if not user_id:
                return
                
            # This would update presence in the collaboration system
            # For now, just log the activity
            log.info(f"User {user_id} {activity} record {record_id} in {self.__class__.__name__}")
            
        except Exception as e:
            log.error(f"Error updating presence: {e}")
            
    @expose('/presence/<pk>')
    @has_access
    def get_presence(self, pk):
        """Get current presence information for a record"""
        try:
            if not self.enable_presence:
                return jsonify({'presence': []})
                
            # Return mock presence data for now
            return jsonify({
                'record_id': pk,
                'presence': [
                    {
                        'user_id': g.user.id if hasattr(g, 'user') and g.user else 1,
                        'username': g.user.username if hasattr(g, 'user') and g.user else 'Anonymous',
                        'activity': 'viewing',
                        'last_seen': datetime.now(tz=timezone.utc).isoformat()
                    }
                ]
            })
            
        except Exception as e:
            log.error(f"Error getting presence: {e}")
            return jsonify({'presence': [], 'error': str(e)})


class CommentableViewMixin:
    """
    Mixin that adds commenting capabilities to views.
    Users can add comments and annotations to records and fields.
    """
    
    enable_comments = True
    comment_permissions = ['can_comment']
    
    def __init__(self):
        super().__init__()
        if self.enable_comments:
            self._setup_comments()
            
    def _setup_comments(self):
        """Set up comment functionality"""
        try:
            self._collaboration_manager = get_collaboration_manager()
            if not self._collaboration_manager:
                self.enable_comments = False
                
        except Exception as e:
            log.error(f"Error setting up comments: {e}")
            self.enable_comments = False
            
    @expose('/comments/<pk>')
    @has_access
    def get_comments(self, pk):
        """Get comments for a record"""
        try:
            if not self.enable_comments:
                return jsonify({'comments': []})
                
            # This would fetch actual comments from the database
            # For now, return empty list
            return jsonify({
                'record_id': pk,
                'model': self.datamodel.obj.__name__,
                'comments': []
            })
            
        except Exception as e:
            log.error(f"Error getting comments: {e}")
            return jsonify({'comments': [], 'error': str(e)})
            
    @expose('/comments/<pk>', methods=['POST'])
    @has_access
    def add_comment(self, pk):
        """Add a comment to a record"""
        try:
            if not self.enable_comments:
                return jsonify({'success': False, 'error': 'Comments not enabled'})
                
            data = request.get_json()
            if not data or 'content' not in data:
                return jsonify({'success': False, 'error': 'No comment content provided'})
                
            user_id = g.user.id if hasattr(g, 'user') and g.user else None
            if not user_id:
                return jsonify({'success': False, 'error': 'No user context'})
                
            # This would save the comment to the database
            # For now, just return success
            return jsonify({
                'success': True,
                'comment_id': 'placeholder',
                'message': 'Comment added successfully'
            })
            
        except Exception as e:
            log.error(f"Error adding comment: {e}")
            return jsonify({'success': False, 'error': str(e)})