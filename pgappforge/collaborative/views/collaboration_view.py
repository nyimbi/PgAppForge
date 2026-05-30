"""
Collaboration Dashboard Views for PgAppForge collaborative features.

Provides dashboard and overview interfaces for collaborative features,
including activity feeds, real-time collaboration status, and analytics.
"""

from flask import flash, redirect, url_for, request, jsonify, render_template
from pgappforge import BaseView, expose, has_access
from pgappforge.security.decorators import protect
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from ..interfaces.base_interfaces import (
    ICollaborationService, ITeamService, IWorkspaceService, ICommunicationService
)
from ..utils.error_handling import CollaborativeError, ErrorHandlingMixin
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType


class CollaborationView(BaseView, ErrorHandlingMixin, CollaborativeAuditMixin):
    """
    Dashboard view for collaborative features.
    
    Provides overview interfaces, activity feeds, real-time collaboration
    status, and analytics for collaborative features.
    """

    route_base = "/collaboration"
    default_view = "dashboard"
    
    def __init__(self):
        super().__init__()
        self._collaboration_service: Optional[ICollaborationService] = None
        self._team_service: Optional[ITeamService] = None
        self._workspace_service: Optional[IWorkspaceService] = None
        self._communication_service: Optional[ICommunicationService] = None

    @property
    def collaboration_service(self) -> Optional[ICollaborationService]:
        """Get collaboration service from addon manager."""
        if self._collaboration_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._collaboration_service = self.appbuilder.collaborative_services.get_service(ICollaborationService)
                except Exception as e:
                    self.logger.error(f"Collaboration service not available: {e}")
        return self._collaboration_service

    @property
    def team_service(self) -> Optional[ITeamService]:
        """Get team service from addon manager."""
        if self._team_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._team_service = self.appbuilder.collaborative_services.get_service(ITeamService)
                except Exception as e:
                    self.logger.error(f"Team service not available: {e}")
        return self._team_service

    @property
    def workspace_service(self) -> Optional[IWorkspaceService]:
        """Get workspace service from addon manager."""
        if self._workspace_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._workspace_service = self.appbuilder.collaborative_services.get_service(IWorkspaceService)
                except Exception as e:
                    self.logger.error(f"Workspace service not available: {e}")
        return self._workspace_service

    @property
    def communication_service(self) -> Optional[ICommunicationService]:
        """Get communication service from addon manager."""
        if self._communication_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._communication_service = self.appbuilder.collaborative_services.get_service(ICommunicationService)
                except Exception as e:
                    self.logger.error(f"Communication service not available: {e}")
        return self._communication_service

    @expose('/')
    @expose('/dashboard')
    @has_access
    def dashboard(self):
        """Main collaboration dashboard."""
        try:
            user_id = self.appbuilder.sm.user.id
            dashboard_data = {}
            
            # Get user's teams
            if self.team_service:
                try:
                    user_teams = self.team_service.get_user_teams(user_id)
                    dashboard_data['teams'] = user_teams[:5]  # Show top 5 teams
                    dashboard_data['total_teams'] = len(user_teams)
                except Exception as e:
                    self.logger.error(f"Error loading user teams: {e}")
                    dashboard_data['teams'] = []
                    dashboard_data['total_teams'] = 0
            
            # Get user's workspaces
            if self.workspace_service:
                try:
                    user_workspaces = self.workspace_service.get_user_workspaces(user_id)
                    dashboard_data['workspaces'] = user_workspaces[:5]  # Show top 5 workspaces
                    dashboard_data['total_workspaces'] = len(user_workspaces)
                except Exception as e:
                    self.logger.error(f"Error loading user workspaces: {e}")
                    dashboard_data['workspaces'] = []
                    dashboard_data['total_workspaces'] = 0
            
            # Get recent activity (placeholder)
            dashboard_data['recent_activity'] = [
                {
                    'type': 'team_joined',
                    'description': 'You joined the Development team',
                    'timestamp': datetime.now() - timedelta(hours=2),
                    'icon': 'fa-users'
                },
                {
                    'type': 'workspace_created',
                    'description': 'You created workspace "Project Alpha"',
                    'timestamp': datetime.now() - timedelta(days=1),
                    'icon': 'fa-folder'
                },
                {
                    'type': 'message_received',
                    'description': 'New message in General channel',
                    'timestamp': datetime.now() - timedelta(hours=6),
                    'icon': 'fa-comment'
                }
            ]
            
            # Get active collaboration sessions (placeholder)
            dashboard_data['active_sessions'] = []
            
            # Get communication summary
            if self.communication_service:
                try:
                    # This would need to aggregate across all user's workspaces
                    dashboard_data['communication_summary'] = {
                        'unread_messages': 5,
                        'unread_notifications': 3,
                        'active_threads': 2
                    }
                except Exception as e:
                    self.logger.error(f"Error loading communication summary: {e}")
                    dashboard_data['communication_summary'] = {
                        'unread_messages': 0,
                        'unread_notifications': 0,
                        'active_threads': 0
                    }
            
            return self.render_template(
                'collaborative/dashboard.html',
                dashboard_data=dashboard_data,
                user=self.appbuilder.sm.user
            )
            
        except Exception as e:
            self.logger.error(f"Error in dashboard: {e}")
            flash("An error occurred while loading the collaboration dashboard", "error")
            return self.render_template('collaborative/dashboard_error.html')

    @expose('/activity')
    @has_access
    def activity_feed(self):
        """Detailed activity feed for collaborative features."""
        try:
            user_id = self.appbuilder.sm.user.id
            page = request.args.get('page', 1, type=int)
            page_size = 20
            
            # Get activity data (placeholder)
            activities = [
                {
                    'id': i,
                    'type': 'team_member_added',
                    'description': f'John Doe was added to the Marketing team',
                    'timestamp': datetime.now() - timedelta(hours=i),
                    'icon': 'fa-user-plus',
                    'user': 'Jane Smith',
                    'details': {'team_name': 'Marketing', 'added_user': 'John Doe'}
                }
                for i in range(1, 21)
            ]
            
            # Apply pagination
            start = (page - 1) * page_size
            end = start + page_size
            paginated_activities = activities[start:end]
            
            return self.render_template(
                'collaborative/activity_feed.html',
                activities=paginated_activities,
                page=page,
                total_pages=(len(activities) + page_size - 1) // page_size,
                total_activities=len(activities)
            )
            
        except Exception as e:
            self.logger.error(f"Error in activity_feed: {e}")
            flash("An error occurred while loading the activity feed", "error")
            return redirect(url_for('CollaborationView.dashboard'))

    @expose('/sessions')
    @has_access
    def active_sessions(self):
        """View active collaboration sessions."""
        try:
            user_id = self.appbuilder.sm.user.id
            
            # Get active sessions (placeholder)
            sessions = []
            
            if self.collaboration_service:
                try:
                    # This would need to be implemented in the collaboration service
                    # sessions = self.collaboration_service.get_user_active_sessions(user_id)
                    pass
                except Exception as e:
                    self.logger.error(f"Error loading active sessions: {e}")
            
            return self.render_template(
                'collaborative/active_sessions.html',
                sessions=sessions
            )
            
        except Exception as e:
            self.logger.error(f"Error in active_sessions: {e}")
            flash("An error occurred while loading active sessions", "error")
            return redirect(url_for('CollaborationView.dashboard'))

    @expose('/analytics')
    @has_access
    def analytics(self):
        """Collaboration analytics and insights."""
        try:
            user_id = self.appbuilder.sm.user.id
            
            # Check if user has permission to view analytics
            if not self.appbuilder.sm.has_access("can_view", "CollaborationAnalytics"):
                flash("You don't have permission to view collaboration analytics", "error")
                return redirect(url_for('CollaborationView.dashboard'))
            
            # Get analytics data (placeholder)
            analytics_data = {
                'team_participation': {
                    'labels': ['Week 1', 'Week 2', 'Week 3', 'Week 4'],
                    'data': [12, 19, 15, 22]
                },
                'workspace_activity': {
                    'labels': ['Documents', 'Comments', 'Meetings', 'Messages'],
                    'data': [45, 23, 12, 67]
                },
                'collaboration_metrics': {
                    'total_collaborations': 156,
                    'active_users': 23,
                    'messages_sent': 1204,
                    'documents_shared': 89
                },
                'top_teams': [
                    {'name': 'Development', 'activity_score': 95},
                    {'name': 'Design', 'activity_score': 87},
                    {'name': 'Marketing', 'activity_score': 76}
                ],
                'top_workspaces': [
                    {'name': 'Project Alpha', 'activity_score': 92},
                    {'name': 'Website Redesign', 'activity_score': 84},
                    {'name': 'Product Launch', 'activity_score': 78}
                ]
            }
            
            return self.render_template(
                'collaborative/analytics.html',
                analytics_data=analytics_data
            )
            
        except Exception as e:
            self.logger.error(f"Error in analytics: {e}")
            flash("An error occurred while loading analytics", "error")
            return redirect(url_for('CollaborationView.dashboard'))

    @expose('/notifications')
    @has_access
    def notifications(self):
        """User notifications for collaborative activities."""
        try:
            user_id = self.appbuilder.sm.user.id
            
            # Get user notifications (placeholder)
            notifications = [
                {
                    'id': 1,
                    'type': 'team_invitation',
                    'title': 'Team Invitation',
                    'message': 'You have been invited to join the Development team',
                    'timestamp': datetime.now() - timedelta(hours=1),
                    'is_read': False,
                    'priority': 'high',
                    'action_url': url_for('TeamModelView.list')
                },
                {
                    'id': 2,
                    'type': 'workspace_shared',
                    'title': 'Workspace Shared',
                    'message': 'Project Alpha workspace has been shared with you',
                    'timestamp': datetime.now() - timedelta(hours=3),
                    'is_read': True,
                    'priority': 'normal',
                    'action_url': url_for('WorkspaceModelView.list')
                },
                {
                    'id': 3,
                    'type': 'comment_mention',
                    'title': 'You were mentioned',
                    'message': 'John mentioned you in a comment on the design document',
                    'timestamp': datetime.now() - timedelta(hours=5),
                    'is_read': False,
                    'priority': 'normal',
                    'action_url': '#'
                }
            ]
            
            return self.render_template(
                'collaborative/notifications.html',
                notifications=notifications
            )
            
        except Exception as e:
            self.logger.error(f"Error in notifications: {e}")
            flash("An error occurred while loading notifications", "error")
            return redirect(url_for('CollaborationView.dashboard'))

    @expose('/api/dashboard_data')
    @protect()
    def api_dashboard_data(self):
        """API endpoint for real-time dashboard data."""
        try:
            user_id = self.appbuilder.sm.user.id
            
            # Get real-time data
            data = {
                'online_users': 15,  # Would be calculated from active sessions
                'active_sessions': 3,
                'unread_notifications': 2,
                'recent_activity_count': 8,
                'timestamp': datetime.now().isoformat()
            }
            
            return jsonify(data)
            
        except Exception as e:
            self.logger.error(f"Error in api_dashboard_data: {e}")
            return jsonify({'error': 'Failed to load dashboard data'}), 500

    @expose('/api/mark_notification_read/<int:notification_id>', methods=['POST'])
    @protect()
    def mark_notification_read(self, notification_id: int):
        """Mark a notification as read."""
        try:
            user_id = self.appbuilder.sm.user.id
            
            # This would need to be implemented in the communication service
            # success = self.communication_service.mark_notification_read(notification_id, user_id)
            success = True  # Placeholder
            
            if success:
                self.audit_user_action(
                    "notification_read",
                    user_id=user_id,
                    resource_type="notification",
                    resource_id=str(notification_id),
                    outcome="success"
                )
                return jsonify({'status': 'success'})
            else:
                return jsonify({'status': 'error', 'message': 'Failed to mark notification as read'}), 400
                
        except Exception as e:
            self.logger.error(f"Error marking notification as read: {e}")
            return jsonify({'status': 'error', 'message': 'Internal server error'}), 500

    @expose('/settings')
    @has_access
    def collaboration_settings(self):
        """User settings for collaborative features."""
        try:
            user_id = self.appbuilder.sm.user.id
            
            # Get user's collaboration preferences (placeholder)
            user_settings = {
                'email_notifications': True,
                'desktop_notifications': False,
                'collaboration_visibility': 'team_members',
                'auto_join_team_workspaces': True,
                'presence_sharing': True,
                'activity_tracking': True
            }
            
            return self.render_template(
                'collaborative/settings.html',
                user_settings=user_settings
            )
            
        except Exception as e:
            self.logger.error(f"Error in collaboration_settings: {e}")
            flash("An error occurred while loading collaboration settings", "error")
            return redirect(url_for('CollaborationView.dashboard'))

    @expose('/help')
    @has_access
    def help_guide(self):
        """Help and documentation for collaborative features."""
        try:
            return self.render_template('collaborative/help.html')
            
        except Exception as e:
            self.logger.error(f"Error in help_guide: {e}")
            flash("An error occurred while loading the help guide", "error")
            return redirect(url_for('CollaborationView.dashboard'))

    def _get_user_summary(self, user_id: int) -> Dict[str, Any]:
        """Get summary data for a specific user."""
        try:
            summary = {
                'teams': 0,
                'workspaces': 0,
                'active_sessions': 0,
                'unread_notifications': 0
            }
            
            # Get team count
            if self.team_service:
                try:
                    user_teams = self.team_service.get_user_teams(user_id)
                    summary['teams'] = len(user_teams)
                except Exception as e:
                    self.logger.error(f"Error getting team count: {e}")
            
            # Get workspace count
            if self.workspace_service:
                try:
                    user_workspaces = self.workspace_service.get_user_workspaces(user_id)
                    summary['workspaces'] = len(user_workspaces)
                except Exception as e:
                    self.logger.error(f"Error getting workspace count: {e}")
            
            return summary
            
        except Exception as e:
            self.logger.error(f"Error getting user summary: {e}")
            return {'teams': 0, 'workspaces': 0, 'active_sessions': 0, 'unread_notifications': 0}