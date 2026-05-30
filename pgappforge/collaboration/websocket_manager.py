"""
WebSocket Manager for Real-Time Collaboration

Handles WebSocket connections, room management, and real-time event broadcasting
using Flask-SocketIO for reliable real-time communication.
"""

import logging
from collections import defaultdict
from typing import Dict, Set, Any, Optional, Callable
from datetime import datetime, timezone

try:
    from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
    from flask import request, current_app, g
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False

from pgappforge.security.decorators import has_access

log = logging.getLogger(__name__)


class CollaborationWebSocketManager:
    """Manages WebSocket connections and real-time communication for collaboration"""
    
    def __init__(self, app=None, security_manager=None):
        self.socketio = None
        self.security_manager = security_manager
        self.active_connections: Dict[str, str] = {}  # {socket_id: user_id}
        self.user_connections: Dict[str, Set[str]] = defaultdict(set)  # {user_id: {socket_ids}}
        self.room_participants: Dict[str, Set[str]] = defaultdict(set)  # {room_id: {user_ids}}
        self.event_handlers: Dict[str, Callable] = {}
        self.app = app
        
        if app and SOCKETIO_AVAILABLE:
            self.init_app(app)
            
    def init_app(self, app):
        """Initialize WebSocket manager with Flask application"""
        if not SOCKETIO_AVAILABLE:
            log.warning("Flask-SocketIO not available. Collaboration features disabled.")
            return
            
        # Configure SocketIO
        socketio_config = {
            'cors_allowed_origins': app.config.get('COLLABORATION_CORS_ORIGINS', "*"),
            'async_mode': app.config.get('COLLABORATION_ASYNC_MODE', 'threading'),
            'logger': app.config.get('COLLABORATION_LOGGER', False),
            'engineio_logger': app.config.get('COLLABORATION_ENGINEIO_LOGGER', False)
        }
        
        # Add message queue for scaling if configured
        if app.config.get('COLLABORATION_MESSAGE_QUEUE'):
            socketio_config['message_queue'] = app.config['COLLABORATION_MESSAGE_QUEUE']
            
        self.socketio = SocketIO(app, **socketio_config)
        self._register_event_handlers()
        
        log.info("Collaboration WebSocket manager initialized")
        
    def _register_event_handlers(self):
        """Register SocketIO event handlers"""
        if not self.socketio:
            return
            
        @self.socketio.on('connect', namespace='/collaboration')
        def on_connect(auth):
            """Handle new WebSocket connection"""
            user = self._authenticate_socket_user(auth)
            if not user:
                log.warning(f"Unauthenticated connection attempt from {request.remote_addr}")
                return False
                
            # Store connection mapping
            self.active_connections[request.sid] = user.id
            self.user_connections[user.id].add(request.sid)
            
            log.info(f"User {user.username} connected via WebSocket: {request.sid}")
            
            # Send connection confirmation
            emit('connection_confirmed', {
                'user_id': user.id,
                'username': user.username,
                'timestamp': datetime.now(tz=timezone.utc).isoformat()
            })
            
        @self.socketio.on('disconnect', namespace='/collaboration')
        def on_disconnect():
            """Handle WebSocket disconnection"""
            if request.sid in self.active_connections:
                user_id = self.active_connections[request.sid]
                
                # Clean up connection mappings
                del self.active_connections[request.sid]
                self.user_connections[user_id].discard(request.sid)
                
                # Remove from all rooms and notify participants
                self._handle_user_disconnect(user_id, request.sid)
                
                log.info(f"User {user_id} disconnected: {request.sid}")
                
        @self.socketio.on('join_collaboration', namespace='/collaboration')
        def on_join_collaboration(data):
            """Handle joining a collaboration session"""
            try:
                session_id = data.get('session_id')
                model_name = data.get('model')
                record_id = data.get('record_id')
                
                if not all([session_id, model_name]):
                    emit('error', {'message': 'Missing required data for collaboration'})
                    return
                    
                user_id = self.active_connections.get(request.sid)
                if not user_id:
                    emit('error', {'message': 'Not authenticated'})
                    return
                    
                # Check permissions
                if not self._check_collaboration_permission(user_id, model_name, record_id, 'can_edit'):
                    emit('error', {'message': 'Permission denied for collaboration'})
                    return
                    
                # Join collaboration room
                room_id = f"collaboration_{model_name}_{record_id or 'new'}"
                join_room(room_id)
                self.room_participants[room_id].add(user_id)
                
                # Notify other participants
                self.socketio.emit('user_joined', {
                    'user_id': user_id,
                    'username': self._get_username(user_id),
                    'session_id': session_id,
                    'timestamp': datetime.now(tz=timezone.utc).isoformat()
                }, room=room_id, include_self=False, namespace='/collaboration')
                
                # Send current participants to new user
                participants = []
                for participant_id in self.room_participants[room_id]:
                    if participant_id != user_id:
                        participants.append({
                            'user_id': participant_id,
                            'username': self._get_username(participant_id)
                        })
                        
                emit('collaboration_joined', {
                    'room_id': room_id,
                    'participants': participants,
                    'timestamp': datetime.now(tz=timezone.utc).isoformat()
                })
                
                log.info(f"User {user_id} joined collaboration room: {room_id}")
                
            except Exception as e:
                log.error(f"Error joining collaboration: {e}")
                emit('error', {'message': 'Failed to join collaboration'})
                
        @self.socketio.on('leave_collaboration', namespace='/collaboration')
        def on_leave_collaboration(data):
            """Handle leaving a collaboration session"""
            try:
                model_name = data.get('model')
                record_id = data.get('record_id')
                user_id = self.active_connections.get(request.sid)
                
                if not user_id:
                    return
                    
                room_id = f"collaboration_{model_name}_{record_id or 'new'}"
                leave_room(room_id)
                self.room_participants[room_id].discard(user_id)
                
                # Notify other participants
                self.socketio.emit('user_left', {
                    'user_id': user_id,
                    'username': self._get_username(user_id),
                    'timestamp': datetime.now(tz=timezone.utc).isoformat()
                }, room=room_id, namespace='/collaboration')
                
                log.info(f"User {user_id} left collaboration room: {room_id}")
                
            except Exception as e:
                log.error(f"Error leaving collaboration: {e}")
                
        @self.socketio.on('field_change', namespace='/collaboration')
        def on_field_change(data):
            """Handle real-time field changes"""
            try:
                user_id = self.active_connections.get(request.sid)
                if not user_id:
                    return
                    
                model_name = data.get('model')
                record_id = data.get('record_id')
                field_name = data.get('field_name')
                new_value = data.get('new_value')
                old_value = data.get('old_value')
                
                # Broadcast change to room participants
                room_id = f"collaboration_{model_name}_{record_id or 'new'}"
                change_event = {
                    'type': 'field_change',
                    'user_id': user_id,
                    'username': self._get_username(user_id),
                    'model': model_name,
                    'record_id': record_id,
                    'field_name': field_name,
                    'new_value': new_value,
                    'old_value': old_value,
                    'timestamp': datetime.now(tz=timezone.utc).isoformat()
                }
                
                self.socketio.emit('field_changed', change_event, 
                                 room=room_id, include_self=False, namespace='/collaboration')
                
                # Trigger custom event handlers
                if 'field_change' in self.event_handlers:
                    self.event_handlers['field_change'](change_event)
                    
            except Exception as e:
                log.error(f"Error handling field change: {e}")
                
        @self.socketio.on('cursor_move', namespace='/collaboration')
        def on_cursor_move(data):
            """Handle cursor position updates"""
            try:
                user_id = self.active_connections.get(request.sid)
                if not user_id:
                    return
                    
                model_name = data.get('model')
                record_id = data.get('record_id')
                field_name = data.get('field_name')
                position = data.get('position')
                
                room_id = f"collaboration_{model_name}_{record_id or 'new'}"
                cursor_event = {
                    'user_id': user_id,
                    'username': self._get_username(user_id),
                    'field_name': field_name,
                    'position': position,
                    'timestamp': datetime.now(tz=timezone.utc).isoformat()
                }
                
                self.socketio.emit('cursor_moved', cursor_event,
                                 room=room_id, include_self=False, namespace='/collaboration')
                                 
            except Exception as e:
                log.error(f"Error handling cursor move: {e}")
                
    def _authenticate_socket_user(self, auth):
        """Authenticate WebSocket connection using JWT token"""
        try:
            if not auth or 'token' not in auth:
                return None
                
            # Use PgAppForge's security manager to verify token
            if self.security_manager:
                return self.security_manager.verify_jwt_token(auth['token'])
                
            return None
            
        except Exception as e:
            log.error(f"Socket authentication error: {e}")
            return None
            
    def _check_collaboration_permission(self, user_id: str, model_name: str, 
                                      record_id: str, permission: str) -> bool:
        """Check if user has permission for collaboration on specific model/record"""
        try:
            if not self.security_manager:
                return True  # Default allow if no security manager
                
            # Check model-level permissions
            user = self.security_manager.get_user_by_id(user_id)
            if not user:
                return False
                
            # Check if user has required permission on the model
            permission_name = f"{permission}_{model_name}"
            if not self.security_manager.has_access(permission_name, f"{model_name}View"):
                return False
                
            return True
            
        except Exception as e:
            log.error(f"Error checking collaboration permission: {e}")
            return False
            
    def _get_username(self, user_id: str) -> str:
        """Get username from user ID"""
        try:
            if self.security_manager:
                user = self.security_manager.get_user_by_id(user_id)
                if user:
                    return user.username
            return f"User{user_id}"
            
        except Exception as e:
            log.error(f"Error getting username: {e}")
            return f"User{user_id}"
            
    def _handle_user_disconnect(self, user_id: str, socket_id: str):
        """Handle cleanup when user disconnects"""
        try:
            # Remove user from all rooms they were in
            rooms_to_clean = []
            for room_id, participants in self.room_participants.items():
                if user_id in participants:
                    participants.discard(user_id)
                    rooms_to_clean.append(room_id)
                    
            # Notify other participants of disconnection
            for room_id in rooms_to_clean:
                self.socketio.emit('user_disconnected', {
                    'user_id': user_id,
                    'username': self._get_username(user_id),
                    'timestamp': datetime.now(tz=timezone.utc).isoformat()
                }, room=room_id, namespace='/collaboration')
                
        except Exception as e:
            log.error(f"Error handling user disconnect: {e}")
            
    def register_event_handler(self, event_type: str, handler: Callable):
        """Register custom event handler"""
        self.event_handlers[event_type] = handler
        
    def broadcast_to_room(self, room_id: str, event: str, data: Dict[str, Any]):
        """Broadcast event to all participants in a room"""
        if self.socketio:
            self.socketio.emit(event, data, room=room_id, namespace='/collaboration')
            
    def get_room_participants(self, room_id: str) -> Set[str]:
        """Get list of participants in a collaboration room"""
        return self.room_participants.get(room_id, set())
        
    def is_user_online(self, user_id: str) -> bool:
        """Check if user is currently connected"""
        return user_id in self.user_connections and len(self.user_connections[user_id]) > 0
        
    def get_connection_stats(self) -> Dict[str, int]:
        """Get current connection statistics"""
        return {
            'total_connections': len(self.active_connections),
            'unique_users': len([uid for uid in self.user_connections.keys() if self.user_connections[uid]]),
            'active_rooms': len([room for room, participants in self.room_participants.items() if participants])
        }


class MockWebSocketManager:
    """Mock WebSocket manager for when Flask-SocketIO is not available"""
    
    def __init__(self, app=None, security_manager=None):
        self.app = app
        self.security_manager = security_manager
        log.warning("Using mock WebSocket manager - real-time features disabled")
        
    def init_app(self, app):
        pass
        
    def register_event_handler(self, event_type: str, handler: Callable):
        pass
        
    def broadcast_to_room(self, room_id: str, event: str, data: Dict[str, Any]):
        log.debug(f"Mock broadcast to room {room_id}: {event}")
        
    def get_room_participants(self, room_id: str) -> Set[str]:
        return set()
        
    def is_user_online(self, user_id: str) -> bool:
        return False
        
    def get_connection_stats(self) -> Dict[str, int]:
        return {'total_connections': 0, 'unique_users': 0, 'active_rooms': 0}


def create_websocket_manager(app=None, security_manager=None):
    """Factory function to create appropriate WebSocket manager"""
    if SOCKETIO_AVAILABLE:
        return CollaborationWebSocketManager(app, security_manager)
    else:
        return MockWebSocketManager(app, security_manager)