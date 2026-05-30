"""
Collaborative Widgets

Enhanced widgets that add real-time collaboration features to PgAppForge forms
including live cursors, presence indicators, and change synchronization.
"""

import logging
from typing import Dict, Any, Optional, List
from flask import g, request
from pgappforge.widgets.core import FormWidget, RenderTemplateWidget

log = logging.getLogger(__name__)


class CollaborativeFormWidget(FormWidget):
    """
    Enhanced form widget with real-time collaboration features.
    
    Adds presence indicators, live cursors, change synchronization,
    and conflict resolution to standard PgAppForge forms.
    """
    
    template = "appbuilder/collaboration/widgets/collaborative_form.html"
    
    def __init__(self, form=None, include_cols=None, exclude_cols=None, 
                 fieldsets=None, collaboration_config=None, **kwargs):
        """
        Initialize collaborative form widget.
        
        :param form: Form instance to render
        :param include_cols: Columns to include
        :param exclude_cols: Columns to exclude
        :param fieldsets: Fieldset configuration
        :param collaboration_config: Collaboration-specific configuration
        :param kwargs: Additional template arguments
        """
        super().__init__(form, include_cols, exclude_cols, fieldsets, **kwargs)
        
        # Collaboration configuration
        self.collaboration_config = collaboration_config or {}
        self.enable_collaboration = self.collaboration_config.get('enabled', True)
        self.session_id = self.collaboration_config.get('session_id')
        self.model_name = self.collaboration_config.get('model_name')
        self.record_id = self.collaboration_config.get('record_id')
        self.websocket_url = self.collaboration_config.get('websocket_url', '/collaboration')
        
        # Add collaboration context to template args
        if self.enable_collaboration:
            self.template_args.update({
                'collaboration_enabled': True,
                'collaboration_session_id': self.session_id,
                'collaboration_model': self.model_name,
                'collaboration_record_id': self.record_id,
                'collaboration_websocket_url': self.websocket_url,
                'collaboration_fields': self._get_collaboration_fields(),
                'collaboration_permissions': self.collaboration_config.get('permissions', ['can_edit']),
                'collaboration_user_info': self._get_current_user_info()
            })
            
    def _get_collaboration_fields(self) -> List[str]:
        """Get list of fields enabled for collaboration"""
        try:
            # If specific fields are configured, use those
            if 'fields' in self.collaboration_config:
                return self.collaboration_config['fields']
                
            # Otherwise, get all form fields
            if self.form:
                return [field.name for field in self.form if field.type != 'CSRFTokenField']
                
            return []
            
        except Exception as e:
            log.error(f"Error getting collaboration fields: {e}")
            return []
            
    def _get_current_user_info(self) -> Dict[str, Any]:
        """Get current user information for collaboration"""
        try:
            if hasattr(g, 'user') and g.user:
                return {
                    'user_id': g.user.id,
                    'username': g.user.username,
                    'first_name': getattr(g.user, 'first_name', ''),
                    'last_name': getattr(g.user, 'last_name', ''),
                    'email': getattr(g.user, 'email', '')
                }
            return {}
        except Exception as e:
            log.error(f"Error getting user info: {e}")
            return {}
            
    def __call__(self, **kwargs):
        """Render collaborative form with enhanced features"""
        # Add any additional collaboration context from kwargs
        collaboration_kwargs = {
            key: value for key, value in kwargs.items() 
            if key.startswith('collaboration_')
        }
        
        if collaboration_kwargs:
            self.template_args.update(collaboration_kwargs)
            
        return super().__call__(**kwargs)


class PresenceIndicatorWidget(RenderTemplateWidget):
    """
    Widget that displays presence indicators showing active users.
    Shows user avatars, names, and current activity status.
    """
    
    template = "appbuilder/collaboration/widgets/presence_indicator.html"
    
    def __init__(self, session_id=None, show_avatars=True, show_cursors=True, 
                 max_users=10, **kwargs):
        """
        Initialize presence indicator widget.
        
        :param session_id: Collaboration session ID
        :param show_avatars: Whether to show user avatars
        :param show_cursors: Whether to show live cursors
        :param max_users: Maximum number of users to display
        :param kwargs: Additional template arguments
        """
        super().__init__(**kwargs)
        
        self.template_args.update({
            'session_id': session_id,
            'show_avatars': show_avatars,
            'show_cursors': show_cursors,
            'max_users': max_users,
            'current_user': self._get_current_user_info()
        })
        
    def _get_current_user_info(self) -> Dict[str, Any]:
        """Get current user information"""
        try:
            if hasattr(g, 'user') and g.user:
                return {
                    'user_id': g.user.id,
                    'username': g.user.username,
                    'avatar_url': getattr(g.user, 'avatar_url', '/static/img/default-avatar.png')
                }
            return {}
        except Exception as e:
            log.error(f"Error getting user info for presence: {e}")
            return {}


class LiveCursorWidget(RenderTemplateWidget):
    """
    Widget that displays live cursors showing where other users are focused.
    Provides visual feedback for real-time collaboration.
    """
    
    template = "appbuilder/collaboration/widgets/live_cursor.html"
    
    def __init__(self, session_id=None, field_selector=".collaboration-field", **kwargs):
        """
        Initialize live cursor widget.
        
        :param session_id: Collaboration session ID
        :param field_selector: CSS selector for collaborative fields
        :param kwargs: Additional template arguments
        """
        super().__init__(**kwargs)
        
        self.template_args.update({
            'session_id': session_id,
            'field_selector': field_selector,
            'cursor_colors': self._get_cursor_colors()
        })
        
    def _get_cursor_colors(self) -> List[str]:
        """Get color palette for user cursors"""
        return [
            '#FF6B6B',  # Red
            '#4ECDC4',  # Teal
            '#45B7D1',  # Blue
            '#96CEB4',  # Green
            '#FFEAA7',  # Yellow
            '#DDA0DD',  # Plum
            '#98D8C8',  # Mint
            '#F7DC6F',  # Light Yellow
            '#BB8FCE',  # Light Purple
            '#85C1E9'   # Light Blue
        ]


class ConflictResolutionWidget(RenderTemplateWidget):
    """
    Widget that handles conflict resolution UI when concurrent edits occur.
    Provides options for merging changes or choosing between versions.
    """
    
    template = "appbuilder/collaboration/widgets/conflict_resolution.html"
    
    def __init__(self, conflict_data=None, **kwargs):
        """
        Initialize conflict resolution widget.
        
        :param conflict_data: Information about the conflict
        :param kwargs: Additional template arguments
        """
        super().__init__(**kwargs)
        
        self.template_args.update({
            'conflict_data': conflict_data or {},
            'resolution_strategies': self._get_resolution_strategies()
        })
        
    def _get_resolution_strategies(self) -> List[Dict[str, str]]:
        """Get available conflict resolution strategies"""
        return [
            {
                'id': 'local',
                'name': 'Keep My Version',
                'description': 'Use your changes and discard the other version'
            },
            {
                'id': 'remote',
                'name': 'Use Their Version',
                'description': 'Accept the other user\'s changes'
            },
            {
                'id': 'merge',
                'name': 'Merge Both',
                'description': 'Combine both versions automatically'
            },
            {
                'id': 'custom',
                'name': 'Custom Resolution',
                'description': 'Create a custom merged version'
            }
        ]


class CollaborationToolbarWidget(RenderTemplateWidget):
    """
    Widget that provides collaboration controls and status information.
    Shows connection status, participant count, and collaboration toggles.
    """
    
    template = "appbuilder/collaboration/widgets/collaboration_toolbar.html"
    
    def __init__(self, session_id=None, show_participant_count=True, 
                 show_connection_status=True, show_collaboration_toggle=True, **kwargs):
        """
        Initialize collaboration toolbar widget.
        
        :param session_id: Collaboration session ID
        :param show_participant_count: Whether to show participant count
        :param show_connection_status: Whether to show connection status
        :param show_collaboration_toggle: Whether to show collaboration toggle
        :param kwargs: Additional template arguments
        """
        super().__init__(**kwargs)
        
        self.template_args.update({
            'session_id': session_id,
            'show_participant_count': show_participant_count,
            'show_connection_status': show_connection_status,
            'show_collaboration_toggle': show_collaboration_toggle,
            'toolbar_position': kwargs.get('position', 'top'),
            'compact_mode': kwargs.get('compact', False)
        })


class CommentThreadWidget(RenderTemplateWidget):
    """
    Widget that displays comment threads for collaborative discussions.
    Supports threaded replies, mentions, and real-time updates.
    """
    
    template = "appbuilder/collaboration/widgets/comment_thread.html"
    
    def __init__(self, session_id=None, field_name=None, comments=None, 
                 enable_mentions=True, **kwargs):
        """
        Initialize comment thread widget.
        
        :param session_id: Collaboration session ID
        :param field_name: Field name for field-specific comments (optional)
        :param comments: List of existing comments
        :param enable_mentions: Whether to enable @mentions
        :param kwargs: Additional template arguments
        """
        super().__init__(**kwargs)
        
        self.template_args.update({
            'session_id': session_id,
            'field_name': field_name,
            'comments': comments or [],
            'enable_mentions': enable_mentions,
            'current_user': self._get_current_user_info(),
            'comment_permissions': self._get_comment_permissions()
        })
        
    def _get_current_user_info(self) -> Dict[str, Any]:
        """Get current user information for comments"""
        try:
            if hasattr(g, 'user') and g.user:
                return {
                    'user_id': g.user.id,
                    'username': g.user.username,
                    'display_name': f"{getattr(g.user, 'first_name', '')} {getattr(g.user, 'last_name', '')}".strip() or g.user.username,
                    'avatar_url': getattr(g.user, 'avatar_url', '/static/img/default-avatar.png')
                }
            return {}
        except Exception as e:
            log.error(f"Error getting user info for comments: {e}")
            return {}
            
    def _get_comment_permissions(self) -> Dict[str, bool]:
        """Get comment permissions for current user"""
        try:
            # This would check actual permissions
            return {
                'can_comment': True,
                'can_edit_own': True,
                'can_delete_own': True,
                'can_moderate': False  # Would check admin permissions
            }
        except Exception as e:
            log.error(f"Error getting comment permissions: {e}")
            return {'can_comment': False}


class CollaborationStatusWidget(RenderTemplateWidget):
    """
    Widget that shows detailed collaboration status and statistics.
    Useful for debugging and monitoring collaboration health.
    """
    
    template = "appbuilder/collaboration/widgets/collaboration_status.html"
    
    def __init__(self, session_id=None, show_detailed_stats=False, **kwargs):
        """
        Initialize collaboration status widget.
        
        :param session_id: Collaboration session ID
        :param show_detailed_stats: Whether to show detailed statistics
        :param kwargs: Additional template arguments
        """
        super().__init__(**kwargs)
        
        self.template_args.update({
            'session_id': session_id,
            'show_detailed_stats': show_detailed_stats,
            'refresh_interval': kwargs.get('refresh_interval', 5000)  # 5 seconds
        })


class FieldHighlightWidget(RenderTemplateWidget):
    """
    Widget that provides visual highlighting for fields being edited by other users.
    Shows colored borders and labels indicating who is editing what.
    """
    
    template = "appbuilder/collaboration/widgets/field_highlight.html"
    
    def __init__(self, session_id=None, highlight_style='border', 
                 show_user_labels=True, **kwargs):
        """
        Initialize field highlight widget.
        
        :param session_id: Collaboration session ID
        :param highlight_style: Style of highlighting ('border', 'background', 'glow')
        :param show_user_labels: Whether to show user labels on highlighted fields
        :param kwargs: Additional template arguments
        """
        super().__init__(**kwargs)
        
        self.template_args.update({
            'session_id': session_id,
            'highlight_style': highlight_style,
            'show_user_labels': show_user_labels,
            'highlight_colors': self._get_highlight_colors()
        })
        
    def _get_highlight_colors(self) -> Dict[str, str]:
        """Get color scheme for field highlighting"""
        return {
            'editing': '#4ECDC4',      # Teal for actively editing
            'focused': '#45B7D1',      # Blue for focused
            'changed': '#96CEB4',      # Green for recently changed
            'conflict': '#FF6B6B',     # Red for conflicts
            'locked': '#DDA0DD'        # Purple for locked fields
        }