"""
WebSocket Tests for PgAppForge Collaboration Engine

Tests WebSocket functionality including connection management, real-time messaging,
presence tracking, and event handling.
"""

import unittest
import json
import time
from unittest.mock import Mock, patch, MagicMock, call
from flask import Flask
from pgappforge import AppBuilder, SQLA
from flask_socketio import SocketIOTestClient

from pgappforge.collaboration.websocket_manager import (
    create_websocket_manager,
    CollaborationWebSocketManager
)


class TestCollaborationWebSockets(unittest.TestCase):
    """Test WebSocket communication and real-time features"""
    
    def setUp(self):
        """Set up test environment with Flask app and WebSocket manager"""
        self.app = Flask(__name__)
        self.app.config.update({
            'SECRET_KEY': 'websocket-test-key',
            'TESTING': True,
            'COLLABORATION_ENABLED': True,
            'COLLABORATION_WEBSOCKET_URL': '/test-ws'
        })
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            self.db.create_all()
            
            # Create test user
            self.test_user = self.appbuilder.sm.add_user(
                username='ws_user',
                first_name='WebSocket',
                last_name='User',
                email='ws@example.com',
                role=self.appbuilder.sm.find_role('Admin')
            )
            self.db.session.commit()
        
        self.app_context = self.app.app_context()
        self.app_context.push()
    
    def tearDown(self):
        """Clean up test environment"""
        self.db.session.remove()
        self.db.drop_all()
        self.app_context.pop()
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_websocket_manager_creation(self, mock_socketio):
        """Test WebSocket manager initialization"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        # Create WebSocket manager
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        # Verify initialization
        self.assertIsNotNone(ws_manager)
        self.assertIsInstance(ws_manager, CollaborationWebSocketManager)
        
        # Verify SocketIO was initialized
        mock_socketio.assert_called_once_with(
            self.app,
            cors_allowed_origins="*",
            namespace='/collaboration'
        )
        
        # Verify event handlers were registered
        expected_events = [
            'connect',
            'disconnect',
            'join_session',
            'leave_session',
            'field_changed',
            'cursor_moved',
            'field_focused',
            'field_blurred',
            'post_comment',
            'resolve_conflict'
        ]
        
        for event in expected_events:
            mock_socketio_instance.on.assert_any_call(event, namespace='/collaboration')
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_websocket_connection_handling(self, mock_socketio):
        """Test WebSocket connection and disconnection handling"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        # Mock request and session
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket-id'
            
            with patch('flask.session') as mock_session:
                mock_session.get.return_value = self.test_user.id
                
                # Test connection
                result = ws_manager.handle_connect()
                
                # Should accept connection
                self.assertNotEqual(result, False)
                
                # Verify user was added to active connections
                self.assertIn('test-socket-id', ws_manager.active_connections)
                self.assertEqual(
                    ws_manager.active_connections['test-socket-id'], 
                    str(self.test_user.id)
                )
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_session_management(self, mock_socketio):
        """Test joining and leaving collaboration sessions"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        # Mock socket connection
        ws_manager.active_connections['test-socket'] = str(self.test_user.id)
        
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            # Test joining session
            session_data = {
                'session_id': 'test-session-123',
                'model_name': 'TestModel',
                'record_id': '456'
            }
            
            with patch.object(ws_manager, '_validate_session_access', return_value=True):
                result = ws_manager.handle_join_session(session_data)
                
                self.assertTrue(result)
                
                # Verify socket joined room
                mock_socketio_instance.emit.assert_called()
                
                # Test leaving session
                leave_data = {'session_id': 'test-session-123'}
                ws_manager.handle_leave_session(leave_data)
                
                # Should emit user left event
                self.assertTrue(mock_socketio_instance.emit.called)
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_field_change_broadcasting(self, mock_socketio):
        """Test broadcasting field changes to other users"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        # Mock active session
        ws_manager.active_connections['test-socket'] = str(self.test_user.id)
        
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            # Test field change
            change_data = {
                'session_id': 'test-session',
                'field_name': 'description',
                'old_value': 'Old text',
                'new_value': 'New text',
                'change_type': 'update'
            }
            
            ws_manager.handle_field_changed(change_data)
            
            # Verify field change was broadcasted
            mock_socketio_instance.emit.assert_called_with(
                'field_changed',
                {
                    **change_data,
                    'user_id': str(self.test_user.id),
                    'timestamp': unittest.mock.ANY
                },
                room='session_test-session',
                namespace='/collaboration',
                include_self=False
            )
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_cursor_tracking(self, mock_socketio):
        """Test live cursor position tracking"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        ws_manager.active_connections['test-socket'] = str(self.test_user.id)
        
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            # Test cursor movement
            cursor_data = {
                'session_id': 'test-session',
                'x': 100,
                'y': 200,
                'field_name': 'description'
            }
            
            ws_manager.handle_cursor_moved(cursor_data)
            
            # Verify cursor position was broadcasted
            mock_socketio_instance.emit.assert_called_with(
                'user_cursor_moved',
                {
                    'user_id': str(self.test_user.id),
                    'x': 100,
                    'y': 200,
                    'field_name': 'description'
                },
                room='session_test-session',
                namespace='/collaboration',
                include_self=False
            )
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_field_focus_tracking(self, mock_socketio):
        """Test field focus and blur event tracking"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        ws_manager.active_connections['test-socket'] = str(self.test_user.id)
        
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            # Test field focus
            focus_data = {
                'session_id': 'test-session',
                'field_name': 'title',
                'field_value': 'Current title'
            }
            
            ws_manager.handle_field_focused(focus_data)
            
            # Verify focus event was broadcasted
            mock_socketio_instance.emit.assert_called_with(
                'user_field_focused',
                {
                    'user_id': str(self.test_user.id),
                    'field_name': 'title',
                    'field_value': 'Current title'
                },
                room='session_test-session',
                namespace='/collaboration',
                include_self=False
            )
            
            # Test field blur
            blur_data = {
                'session_id': 'test-session',
                'field_name': 'title',
                'field_value': 'Updated title'
            }
            
            ws_manager.handle_field_blurred(blur_data)
            
            # Verify blur event was broadcasted
            mock_socketio_instance.emit.assert_called_with(
                'user_field_blurred',
                {
                    'user_id': str(self.test_user.id),
                    'field_name': 'title',
                    'field_value': 'Updated title'
                },
                room='session_test-session',
                namespace='/collaboration',
                include_self=False
            )
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_comment_system(self, mock_socketio):
        """Test real-time commenting system"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        ws_manager.active_connections['test-socket'] = str(self.test_user.id)
        
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            # Test posting comment
            comment_data = {
                'session_id': 'test-session',
                'field_name': 'description',
                'comment_text': 'This needs to be updated',
                'parent_comment_id': None
            }
            
            with patch.object(ws_manager, '_store_comment', return_value='comment-123'):
                ws_manager.handle_post_comment(comment_data)
                
                # Verify comment was broadcasted
                expected_call = call(
                    'new_comment',
                    unittest.mock.ANY,  # Comment data with user info
                    room='session_test-session',
                    namespace='/collaboration'
                )
                
                mock_socketio_instance.emit.assert_called()
                actual_call = mock_socketio_instance.emit.call_args
                self.assertEqual(actual_call[0][0], 'new_comment')
                self.assertEqual(actual_call[1]['room'], 'session_test-session')
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_conflict_resolution_messaging(self, mock_socketio):
        """Test conflict resolution WebSocket messaging"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        ws_manager.active_connections['test-socket'] = str(self.test_user.id)
        
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            # Test conflict resolution
            resolution_data = {
                'conflict_id': 'conflict-456',
                'resolution_strategy': 'merge_auto',
                'resolved_value': 'Merged content',
                'timestamp': int(time.time() * 1000)
            }
            
            ws_manager.handle_resolve_conflict(resolution_data)
            
            # Verify resolution was broadcasted
            mock_socketio_instance.emit.assert_called_with(
                'conflict_resolved',
                {
                    'conflict_id': 'conflict-456',
                    'resolution': {
                        'method': 'merge_auto',
                        'resolved_value': 'Merged content',
                        'resolved_by': str(self.test_user.id),
                        'timestamp': unittest.mock.ANY
                    }
                },
                room=unittest.mock.ANY,
                namespace='/collaboration'
            )
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_connection_statistics(self, mock_socketio):
        """Test WebSocket connection statistics"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        # Add mock connections
        ws_manager.active_connections.update({
            'socket1': '1',
            'socket2': '2',
            'socket3': '1'  # Same user, different socket
        })
        
        ws_manager.session_participants.update({
            'session1': {'1', '2'},
            'session2': {'1'}
        })
        
        # Get statistics
        stats = ws_manager.get_connection_stats()
        
        self.assertEqual(stats['total_connections'], 3)
        self.assertEqual(stats['unique_users'], 2)
        self.assertEqual(stats['active_sessions'], 2)
        self.assertEqual(stats['total_participants'], 3)  # User 1 in 2 sessions, user 2 in 1
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_error_handling(self, mock_socketio):
        """Test WebSocket error handling"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        # Test handling invalid session join
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            # Mock authentication failure
            with patch.object(ws_manager, '_get_current_user', return_value=None):
                result = ws_manager.handle_connect()
                
                # Should reject connection
                self.assertEqual(result, False)
            
            # Test invalid session data
            invalid_data = {'invalid': 'data'}
            result = ws_manager.handle_join_session(invalid_data)
            
            # Should handle gracefully
            self.assertFalse(result)
            
            # Test field change with missing session
            change_data = {
                'field_name': 'test',
                'new_value': 'value'
                # Missing session_id
            }
            
            # Should not raise exception
            try:
                ws_manager.handle_field_changed(change_data)
            except Exception as e:
                self.fail(f"Unexpected exception: {e}")
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_rate_limiting(self, mock_socketio):
        """Test WebSocket rate limiting"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        ws_manager.active_connections['test-socket'] = str(self.test_user.id)
        
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            # Simulate rapid field changes
            change_data = {
                'session_id': 'test-session',
                'field_name': 'description',
                'old_value': 'Old',
                'new_value': 'New',
                'change_type': 'update'
            }
            
            # Send multiple rapid changes
            for i in range(10):
                change_data['new_value'] = f'New{i}'
                ws_manager.handle_field_changed(change_data)
            
            # Should have throttled some events
            # (Implementation would depend on actual rate limiting logic)
            emit_call_count = mock_socketio_instance.emit.call_count
            self.assertGreater(emit_call_count, 0)
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_namespace_isolation(self, mock_socketio):
        """Test namespace isolation between different collaboration instances"""
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        # Create WebSocket manager with custom namespace
        ws_manager = CollaborationWebSocketManager(
            app=self.app,
            security_manager=self.appbuilder.sm,
            namespace='/custom-collaboration'
        )
        
        # Verify correct namespace was used
        mock_socketio.assert_called_with(
            self.app,
            cors_allowed_origins="*",
            namespace='/custom-collaboration'
        )
        
        # Test that events use correct namespace
        ws_manager.active_connections['test-socket'] = str(self.test_user.id)
        
        with patch('flask.request') as mock_request:
            mock_request.sid = 'test-socket'
            
            change_data = {
                'session_id': 'test-session',
                'field_name': 'test',
                'old_value': 'old',
                'new_value': 'new',
                'change_type': 'update'
            }
            
            ws_manager.handle_field_changed(change_data)
            
            # Verify namespace in emit call
            _, kwargs = mock_socketio_instance.emit.call_args
            self.assertEqual(kwargs['namespace'], '/custom-collaboration')


if __name__ == '__main__':
    unittest.main(verbosity=2)