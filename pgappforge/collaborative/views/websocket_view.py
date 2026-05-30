"""
WebSocket Views for PgAppForge collaborative features.

Provides WebSocket endpoints for real-time communication, collaboration events,
and live updates in collaborative workspaces.
"""

from flask import request, session, g
from pgappforge import BaseView, expose
from pgappforge.security.decorators import protect
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from typing import Any, Dict, List, Optional
import json
import logging
from datetime import datetime

from ..interfaces.base_interfaces import IWebSocketService, ICollaborationService
from ..utils.error_handling import CollaborativeError, ErrorHandlingMixin
from ..utils.audit_logging import CollaborativeAuditMixin, AuditEventType
from ..utils.validation import ValidationHelper
from ..utils.async_bridge import AsyncServiceMixin


class WebSocketView(BaseView, ErrorHandlingMixin, CollaborativeAuditMixin, AsyncServiceMixin):
    """
    WebSocket view for real-time collaborative features.
    
    Provides WebSocket endpoints and handlers for real-time communication,
    collaboration events, presence tracking, and live updates.
    """

    route_base = "/ws"
    default_view = "connect"
    
    def __init__(self):
        super().__init__()
        self.socketio: Optional[SocketIO] = None
        self._websocket_service: Optional[IWebSocketService] = None
        self._collaboration_service: Optional[ICollaborationService] = None
        
        # Track active connections
        self.active_connections: Dict[str, Dict[str, Any]] = {}
        self.user_sessions: Dict[int, List[str]] = {}  # user_id -> list of session_ids

    def init_socketio(self, socketio: SocketIO):
        """Initialize SocketIO instance and register event handlers."""
        self.socketio = socketio
        self._register_event_handlers()

    @property
    def websocket_service(self) -> Optional[IWebSocketService]:
        """Get WebSocket service from addon manager."""
        if self._websocket_service is None:
            if hasattr(self.appbuilder, 'collaborative_services'):
                try:
                    self._websocket_service = self.appbuilder.collaborative_services.get_service(IWebSocketService)
                except Exception as e:
                    self.logger.error(f"WebSocket service not available: {e}")
        return self._websocket_service

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

    def _register_event_handlers(self):
        """Register WebSocket event handlers with SocketIO."""
        if not self.socketio:
            return

        @self.socketio.on('connect')
        def handle_connect(auth):
            """Handle WebSocket connection."""
            try:
                # Authenticate user
                user = self._authenticate_websocket_user(auth)
                if not user:
                    self.logger.warning("WebSocket connection rejected: invalid authentication")
                    disconnect()
                    return False

                # Create connection record
                connection_id = request.sid
                connection_data = {
                    'user_id': user.id,
                    'username': user.username,
                    'connected_at': datetime.now().isoformat(),
                    'rooms': [],
                    'last_activity': datetime.now().isoformat()
                }
                
                self.active_connections[connection_id] = connection_data
                
                # Track user sessions
                if user.id not in self.user_sessions:
                    self.user_sessions[user.id] = []
                self.user_sessions[user.id].append(connection_id)

                # Handle connection in service layer
                if self.websocket_service:
                    try:
                        self.call_async_service(
                            self.websocket_service.handle_connection,
                            websocket=request,
                            auth_data=auth or {}
                        )
                    except Exception as e:
                        self.logger.error(f"Error in websocket service handle_connection: {e}")

                # Audit connection
                self.audit_user_action(
                    "websocket_connected",
                    user_id=user.id,
                    resource_type="websocket_connection",
                    resource_id=connection_id,
                    outcome="success"
                )

                # Emit connection success
                emit('connection_established', {
                    'status': 'connected',
                    'user_id': user.id,
                    'connection_id': connection_id,
                    'timestamp': datetime.now().isoformat()
                })

                self.logger.info(f"WebSocket connection established for user {user.username} (ID: {user.id})")
                return True

            except Exception as e:
                self.logger.error(f"Error handling WebSocket connection: {e}")
                disconnect()
                return False

        @self.socketio.on('disconnect')
        def handle_disconnect():
            """Handle WebSocket disconnection."""
            try:
                connection_id = request.sid
                connection_data = self.active_connections.get(connection_id)
                
                if connection_data:
                    user_id = connection_data['user_id']
                    
                    # Leave all rooms
                    for room in connection_data.get('rooms', []):
                        leave_room(room)
                        emit('user_left_room', {
                            'user_id': user_id,
                            'room': room,
                            'timestamp': datetime.now().isoformat()
                        }, room=room, include_self=False)

                    # Handle disconnection in service layer
                    if self.websocket_service:
                        try:
                            self.call_async_service(
                                self.websocket_service.disconnect_user,
                                user_id=user_id,
                                reason="client_disconnect"
                            )
                        except Exception as e:
                            self.logger.error(f"Error in websocket service disconnect: {e}")

                    # Clean up tracking
                    if user_id in self.user_sessions:
                        if connection_id in self.user_sessions[user_id]:
                            self.user_sessions[user_id].remove(connection_id)
                        if not self.user_sessions[user_id]:
                            del self.user_sessions[user_id]

                    del self.active_connections[connection_id]

                    # Audit disconnection
                    self.audit_user_action(
                        "websocket_disconnected",
                        user_id=user_id,
                        resource_type="websocket_connection",
                        resource_id=connection_id,
                        outcome="success"
                    )

                    self.logger.info(f"WebSocket connection closed for user ID: {user_id}")

            except Exception as e:
                self.logger.error(f"Error handling WebSocket disconnection: {e}")

        @self.socketio.on('join_collaboration_session')
        def handle_join_session(data):
            """Handle joining a collaboration session."""
            try:
                connection_id = request.sid
                connection_data = self.active_connections.get(connection_id)
                
                if not connection_data:
                    emit('error', {'message': 'Not authenticated'})
                    return

                user_id = connection_data['user_id']
                session_id = data.get('session_id')
                
                # Validate session ID
                validation_result = ValidationHelper.validate_session_id(session_id)
                if not validation_result.is_valid:
                    emit('error', {'message': validation_result.error_message})
                    return

                # Join collaboration session through service
                if self.collaboration_service:
                    try:
                        # This would need to be implemented to handle WebSocket users
                        success = self.call_async_service(
                            self.collaboration_service.join_session,
                            session_id=session_id,
                            user={'id': user_id, 'connection_id': connection_id}
                        )
                        
                        if success:
                            # Join SocketIO room
                            join_room(f"session_{session_id}")
                            connection_data['rooms'].append(f"session_{session_id}")
                            connection_data['current_session'] = session_id
                            
                            # Notify others in the session
                            emit('user_joined_session', {
                                'user_id': user_id,
                                'session_id': session_id,
                                'timestamp': datetime.now().isoformat()
                            }, room=f"session_{session_id}", include_self=False)
                            
                            # Confirm to user
                            emit('session_joined', {
                                'session_id': session_id,
                                'status': 'success',
                                'timestamp': datetime.now().isoformat()
                            })
                            
                            self.audit_user_action(
                                "collaboration_session_joined",
                                user_id=user_id,
                                resource_type="collaboration_session",
                                resource_id=session_id,
                                outcome="success"
                            )
                        else:
                            emit('error', {'message': 'Failed to join collaboration session'})
                    except Exception as e:
                        self.logger.error(f"Error joining collaboration session: {e}")
                        emit('error', {'message': 'Internal server error'})
                else:
                    emit('error', {'message': 'Collaboration service not available'})

            except Exception as e:
                self.logger.error(f"Error in handle_join_session: {e}")
                emit('error', {'message': 'Internal server error'})

        @self.socketio.on('leave_collaboration_session')
        def handle_leave_session(data):
            """Handle leaving a collaboration session."""
            try:
                connection_id = request.sid
                connection_data = self.active_connections.get(connection_id)
                
                if not connection_data:
                    emit('error', {'message': 'Not authenticated'})
                    return

                user_id = connection_data['user_id']
                session_id = data.get('session_id') or connection_data.get('current_session')
                
                if not session_id:
                    emit('error', {'message': 'No session to leave'})
                    return

                # Leave collaboration session through service
                if self.collaboration_service:
                    try:
                        success = self.call_async_service(
                            self.collaboration_service.leave_session,
                            session_id=session_id,
                            user_id=user_id
                        )
                        
                        if success:
                            # Leave SocketIO room
                            leave_room(f"session_{session_id}")
                            if f"session_{session_id}" in connection_data.get('rooms', []):
                                connection_data['rooms'].remove(f"session_{session_id}")
                            if connection_data.get('current_session') == session_id:
                                del connection_data['current_session']
                            
                            # Notify others in the session
                            emit('user_left_session', {
                                'user_id': user_id,
                                'session_id': session_id,
                                'timestamp': datetime.now().isoformat()
                            }, room=f"session_{session_id}")
                            
                            # Confirm to user
                            emit('session_left', {
                                'session_id': session_id,
                                'status': 'success',
                                'timestamp': datetime.now().isoformat()
                            })
                            
                            self.audit_user_action(
                                "collaboration_session_left",
                                user_id=user_id,
                                resource_type="collaboration_session",
                                resource_id=session_id,
                                outcome="success"
                            )
                        else:
                            emit('error', {'message': 'Failed to leave collaboration session'})
                    except Exception as e:
                        self.logger.error(f"Error leaving collaboration session: {e}")
                        emit('error', {'message': 'Internal server error'})

            except Exception as e:
                self.logger.error(f"Error in handle_leave_session: {e}")
                emit('error', {'message': 'Internal server error'})

        @self.socketio.on('collaboration_event')
        def handle_collaboration_event(data):
            """Handle collaboration events (cursor, selection, edit, etc.)."""
            try:
                connection_id = request.sid
                connection_data = self.active_connections.get(connection_id)
                
                if not connection_data:
                    emit('error', {'message': 'Not authenticated'})
                    return

                user_id = connection_data['user_id']
                event_type = data.get('event_type')
                session_id = data.get('session_id') or connection_data.get('current_session')
                
                if not session_id:
                    emit('error', {'message': 'Not in a collaboration session'})
                    return

                # Validate event data
                if not event_type or event_type not in ['cursor', 'selection', 'edit', 'comment', 'presence']:
                    emit('error', {'message': 'Invalid event type'})
                    return

                # Handle event through service
                if self.collaboration_service:
                    try:
                        event_data = {
                            'session_id': session_id,
                            'event_type': event_type,
                            'data': data.get('data', {}),
                            'user_id': user_id,
                            'timestamp': datetime.now().isoformat(),
                            'connection_id': connection_id
                        }
                        
                        self.call_async_service(
                            self.collaboration_service.emit_event,
                            event_data
                        )
                        
                        # Broadcast to session participants (except sender for non-persistent events)
                        include_self = event_type in ['edit', 'comment']  # Include sender for persistent events
                        
                        emit('collaboration_event', {
                            'event_type': event_type,
                            'data': data.get('data', {}),
                            'user_id': user_id,
                            'session_id': session_id,
                            'timestamp': datetime.now().isoformat()
                        }, room=f"session_{session_id}", include_self=include_self)

                        # Update connection activity
                        connection_data['last_activity'] = datetime.now().isoformat()

                    except Exception as e:
                        self.logger.error(f"Error handling collaboration event: {e}")
                        emit('error', {'message': 'Failed to process collaboration event'})

            except Exception as e:
                self.logger.error(f"Error in handle_collaboration_event: {e}")
                emit('error', {'message': 'Internal server error'})

        @self.socketio.on('chat_message')
        def handle_chat_message(data):
            """Handle chat messages in workspace channels."""
            try:
                connection_id = request.sid
                connection_data = self.active_connections.get(connection_id)
                
                if not connection_data:
                    emit('error', {'message': 'Not authenticated'})
                    return

                user_id = connection_data['user_id']
                username = connection_data['username']
                channel_id = data.get('channel_id')
                content = data.get('content', '').strip()
                
                if not channel_id or not content:
                    emit('error', {'message': 'Missing channel or message content'})
                    return

                # Validate message content
                validation_result = ValidationHelper.validate_message_content(content)
                if not validation_result.is_valid:
                    emit('error', {'message': validation_result.error_message})
                    return

                # Send message through communication service (would need WebSocket integration)
                message_data = {
                    'id': f"ws_{datetime.now().timestamp()}",  # Temporary ID for WebSocket messages
                    'channel_id': channel_id,
                    'user_id': user_id,
                    'username': username,
                    'content': content,
                    'message_type': data.get('message_type', 'text'),
                    'timestamp': datetime.now().isoformat()
                }

                # Broadcast to channel participants
                emit('chat_message', message_data, room=f"channel_{channel_id}")

                # Update connection activity
                connection_data['last_activity'] = datetime.now().isoformat()

            except Exception as e:
                self.logger.error(f"Error in handle_chat_message: {e}")
                emit('error', {'message': 'Internal server error'})

        @self.socketio.on('join_channel')
        def handle_join_channel(data):
            """Handle joining a chat channel."""
            try:
                connection_id = request.sid
                connection_data = self.active_connections.get(connection_id)
                
                if not connection_data:
                    emit('error', {'message': 'Not authenticated'})
                    return

                user_id = connection_data['user_id']
                channel_id = data.get('channel_id')
                
                # Validate channel access (would need to check permissions)
                # For now, allow all authenticated users to join channels
                
                # Join SocketIO room
                join_room(f"channel_{channel_id}")
                connection_data['rooms'].append(f"channel_{channel_id}")
                
                # Notify others in the channel
                emit('user_joined_channel', {
                    'user_id': user_id,
                    'channel_id': channel_id,
                    'timestamp': datetime.now().isoformat()
                }, room=f"channel_{channel_id}", include_self=False)
                
                # Confirm to user
                emit('channel_joined', {
                    'channel_id': channel_id,
                    'status': 'success',
                    'timestamp': datetime.now().isoformat()
                })

            except Exception as e:
                self.logger.error(f"Error in handle_join_channel: {e}")
                emit('error', {'message': 'Internal server error'})

    def _authenticate_websocket_user(self, auth_data: Dict[str, Any]):
        """Authenticate WebSocket connection using auth data or session."""
        try:
            # Try to get user from Flask session first
            if hasattr(g, 'user') and g.user:
                return g.user

            # Try to authenticate using token from auth_data
            if auth_data and 'token' in auth_data:
                # This would need to be implemented with proper token validation
                # user = self.appbuilder.sm.validate_token(auth_data['token'])
                # return user
                pass

            # Try to authenticate using session data
            if 'user_id' in session:
                user = self.appbuilder.sm.get_user_by_id(session['user_id'])
                return user

            return None

        except Exception as e:
            self.logger.error(f"Error authenticating WebSocket user: {e}")
            return None

    @expose('/status')
    def websocket_status(self):
        """Show WebSocket connection status and statistics."""
        try:
            # Check if user is admin
            if not self.appbuilder.sm.has_access("can_view", "WebSocketStatus"):
                flash("You don't have permission to view WebSocket status", "error")
                return redirect(url_for('index'))

            # Get connection statistics
            stats = {
                'active_connections': len(self.active_connections),
                'active_users': len(self.user_sessions),
                'total_rooms': len(set(room for conn in self.active_connections.values() for room in conn.get('rooms', []))),
                'connections_by_user': [(user_id, len(sessions)) for user_id, sessions in self.user_sessions.items()]
            }

            # Get service statistics
            if self.websocket_service:
                try:
                    service_stats = self.websocket_service.get_connection_stats()
                    stats.update(service_stats)
                except Exception as e:
                    self.logger.error(f"Error getting service stats: {e}")

            return self.render_template(
                'collaborative/websocket_status.html',
                stats=stats,
                active_connections=self.active_connections
            )

        except Exception as e:
            self.logger.error(f"Error in websocket_status: {e}")
            return self.render_template('collaborative/websocket_error.html')

    @expose('/test')
    def websocket_test(self):
        """Test page for WebSocket functionality."""
        try:
            return self.render_template('collaborative/websocket_test.html')

        except Exception as e:
            self.logger.error(f"Error in websocket_test: {e}")
            return self.render_template('collaborative/websocket_error.html')

    def get_user_connections(self, user_id: int) -> List[str]:
        """Get all active connection IDs for a user."""
        return self.user_sessions.get(user_id, [])

    def broadcast_to_user(self, user_id: int, event: str, data: Dict[str, Any]):
        """Broadcast a message to all connections of a specific user."""
        if not self.socketio:
            return False

        connections = self.get_user_connections(user_id)
        for connection_id in connections:
            try:
                self.socketio.emit(event, data, room=connection_id)
            except Exception as e:
                self.logger.error(f"Error broadcasting to user {user_id}, connection {connection_id}: {e}")

        return len(connections) > 0

    def broadcast_to_session(self, session_id: str, event: str, data: Dict[str, Any], exclude_user_id: Optional[int] = None):
        """Broadcast a message to all users in a collaboration session."""
        if not self.socketio:
            return 0

        room = f"session_{session_id}"
        
        try:
            if exclude_user_id:
                # Find connections to exclude
                exclude_connections = self.get_user_connections(exclude_user_id)
                # This would need a more sophisticated approach to exclude specific connections
                # For now, broadcast to all
                self.socketio.emit(event, data, room=room)
            else:
                self.socketio.emit(event, data, room=room)
            return 1  # Placeholder return value
        except Exception as e:
            self.logger.error(f"Error broadcasting to session {session_id}: {e}")
            return 0