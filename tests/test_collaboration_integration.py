"""
Comprehensive Integration Tests for PgAppForge Collaboration Engine

Tests the complete collaboration system including WebSocket communication,
session management, conflict resolution, and security integration.
"""

import unittest
import json
import time
from unittest.mock import Mock, patch, MagicMock
from flask import Flask, g
from pgappforge import AppBuilder, SQLA
from pgappforge.security.sqla.models import User, Role
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIOTestClient

# Import collaboration components
from pgappforge.collaboration.collaboration_manager import CollaborationManager
from pgappforge.collaboration.security_integration import (
    CollaborationSecurityManager, 
    CollaborationSecuritySession,
    CollaborationParticipant,
    COLLABORATION_PERMISSIONS,
    COLLABORATION_ROLES
)
from pgappforge.collaboration.websocket_manager import create_websocket_manager
from pgappforge.collaboration.session_manager import CollaborationSessionManager
from pgappforge.collaboration.conflict_resolver import ConflictResolutionEngine
from pgappforge.collaboration.sync_engine import RealtimeDataSyncEngine


class TestCollaborationIntegration(unittest.TestCase):
    """Integration tests for the complete collaboration system"""
    
    def setUp(self):
        """Set up test environment with Flask app and collaboration system"""
        # Create Flask app
        self.app = Flask(__name__)
        self.app.config.update({
            'SECRET_KEY': 'test-secret-key-for-collaboration-tests',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'WTF_CSRF_ENABLED': False,
            'COLLABORATION_ENABLED': True,
            'COLLABORATION_WEBSOCKET_URL': '/test-collaboration',
            'COLLABORATION_SESSION_TIMEOUT': 3600,
            'COLLABORATION_MAX_PARTICIPANTS': 10,
            'TESTING': True
        })
        
        # Initialize SQLAlchemy and AppBuilder
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        with self.app.app_context():
            # Create all tables
            self.db.create_all()
            
            # Create test users and roles
            self._create_test_data()
            
            # Initialize collaboration manager
            self.collaboration_manager = CollaborationManager(
                app=self.app,
                db_session=self.db.session,
                security_manager=self.appbuilder.sm
            )
        
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
    
    def tearDown(self):
        """Clean up test environment"""
        with self.app.app_context():
            self.db.session.remove()
            self.db.drop_all()
        
        self.app_context.pop()
    
    def _create_test_data(self):
        """Create test users and roles"""
        # Create collaboration roles
        for role_name, permissions in COLLABORATION_ROLES.items():
            role = self.appbuilder.sm.add_role(role_name)
            
            for perm_name in permissions:
                # Add permission if it doesn't exist
                perm = self.appbuilder.sm.add_permission(perm_name)
                if perm and perm not in role.permissions:
                    role.permissions.append(perm)
        
        # Create test users
        self.test_user1 = self.appbuilder.sm.add_user(
            username='collaborator1',
            first_name='John',
            last_name='Doe',
            email='john@example.com',
            role=self.appbuilder.sm.find_role('Collaboration User')
        )
        
        self.test_user2 = self.appbuilder.sm.add_user(
            username='collaborator2',
            first_name='Jane',
            last_name='Smith',
            email='jane@example.com',
            role=self.appbuilder.sm.find_role('Collaboration Moderator')
        )
        
        self.test_admin = self.appbuilder.sm.add_user(
            username='collab_admin',
            first_name='Admin',
            last_name='User',
            email='admin@example.com',
            role=self.appbuilder.sm.find_role('Collaboration Admin')
        )
        
        self.db.session.commit()
    
    def _login_user(self, user):
        """Helper to simulate user login"""
        g.user = user
        return user
    
    def test_collaboration_manager_initialization(self):
        """Test collaboration manager initializes correctly"""
        self.assertIsNotNone(self.collaboration_manager)
        self.assertTrue(self.collaboration_manager.is_enabled())
        self.assertIsNotNone(self.collaboration_manager.security_integration)
        self.assertIsNotNone(self.collaboration_manager.websocket_manager)
        self.assertIsNotNone(self.collaboration_manager.session_manager)
        self.assertIsNotNone(self.collaboration_manager.sync_engine)
        self.assertIsNotNone(self.collaboration_manager.conflict_resolver)
    
    def test_security_permissions_registration(self):
        """Test that collaboration permissions are properly registered"""
        for perm_name, menu_name in COLLABORATION_PERMISSIONS:
            permission = self.appbuilder.sm.find_permission(perm_name)
            self.assertIsNotNone(permission, f"Permission {perm_name} not found")
    
    def test_collaboration_roles_creation(self):
        """Test that collaboration roles are created with correct permissions"""
        for role_name, expected_permissions in COLLABORATION_ROLES.items():
            role = self.appbuilder.sm.find_role(role_name)
            self.assertIsNotNone(role, f"Role {role_name} not found")
            
            role_permissions = [perm.name for perm in role.permissions]
            for expected_perm in expected_permissions:
                self.assertIn(expected_perm, role_permissions, 
                            f"Permission {expected_perm} missing from role {role_name}")
    
    def test_user_collaboration_permissions(self):
        """Test user permission checking"""
        security_mgr = self.collaboration_manager.security_integration
        
        # Test user with basic collaboration role
        self.assertTrue(security_mgr.check_collaboration_permission('can_collaborate', self.test_user1.id))
        self.assertTrue(security_mgr.check_collaboration_permission('can_join_session', self.test_user1.id))
        self.assertFalse(security_mgr.check_collaboration_permission('can_create_session', self.test_user1.id))
        
        # Test user with moderator role
        self.assertTrue(security_mgr.check_collaboration_permission('can_create_session', self.test_user2.id))
        self.assertTrue(security_mgr.check_collaboration_permission('can_moderate_session', self.test_user2.id))
        
        # Test admin user
        self.assertTrue(security_mgr.check_collaboration_permission('can_admin_collaboration', self.test_admin.id))
    
    def test_secure_session_creation(self):
        """Test creating collaboration sessions with security checks"""
        security_mgr = self.collaboration_manager.security_integration
        
        # Login as moderator (can create sessions)
        self._login_user(self.test_user2)
        
        # Create session
        session_id = security_mgr.create_secure_session(
            model_name='TestModel',
            record_id='123',
            permissions_required=['can_collaborate'],
            max_participants=5
        )
        
        self.assertIsNotNone(session_id)
        
        # Verify session was created in database
        session = self.db.session.query(CollaborationSecuritySession).filter_by(id=session_id).first()
        self.assertIsNotNone(session)
        self.assertEqual(session.model_name, 'TestModel')
        self.assertEqual(session.record_id, '123')
        self.assertEqual(session.created_by, self.test_user2.id)
        self.assertEqual(session.max_participants, 5)
    
    def test_session_access_validation(self):
        """Test session access validation with different user roles"""
        security_mgr = self.collaboration_manager.security_integration
        
        # Create session as moderator
        self._login_user(self.test_user2)
        session_id = security_mgr.create_secure_session(
            model_name='TestModel',
            record_id='123'
        )
        
        # Test creator access
        access_info = security_mgr.validate_session_access(session_id, self.test_user2.id)
        self.assertTrue(access_info['can_join'])
        self.assertTrue(access_info['can_moderate'])
        self.assertEqual(access_info['user_role'], 'moderator')
        
        # Test regular user access
        access_info = security_mgr.validate_session_access(session_id, self.test_user1.id)
        self.assertTrue(access_info['can_join'])
        self.assertFalse(access_info['can_moderate'])
        self.assertEqual(access_info['user_role'], 'participant')
    
    def test_collaboration_api_endpoints(self):
        """Test collaboration REST API endpoints"""
        # Login as user with collaboration permissions
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.test_user1.id
        
        # Mock g.user for API calls
        with patch('flask.g') as mock_g:
            mock_g.user = self.test_user1
            
            # Test status endpoint
            response = self.client.get('/api/collaboration/status')
            self.assertEqual(response.status_code, 200)
            
            data = json.loads(response.data)
            self.assertTrue(data['enabled'])
            self.assertIn('user_info', data)
            self.assertIn('components', data)
    
    def test_session_creation_api(self):
        """Test collaboration session creation via API"""
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.test_user2.id  # Moderator can create sessions
        
        with patch('flask.g') as mock_g:
            mock_g.user = self.test_user2
            
            # Create session via API
            response = self.client.post('/api/collaboration/sessions/create',
                json={
                    'model_name': 'TestModel',
                    'record_id': '456',
                    'max_participants': 8
                })
            
            self.assertEqual(response.status_code, 200)
            
            data = json.loads(response.data)
            self.assertIn('session_id', data)
            self.assertIn('session_info', data)
            self.assertIn('websocket_url', data)
    
    def test_session_join_api(self):
        """Test joining collaboration session via API"""
        # Create session first
        security_mgr = self.collaboration_manager.security_integration
        self._login_user(self.test_user2)
        session_id = security_mgr.create_secure_session(
            model_name='TestModel',
            record_id='789'
        )
        
        # Join session as different user
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.test_user1.id
        
        with patch('flask.g') as mock_g:
            mock_g.user = self.test_user1
            
            response = self.client.post(f'/api/collaboration/sessions/{session_id}/join')
            self.assertEqual(response.status_code, 200)
            
            data = json.loads(response.data)
            self.assertTrue(data['access_granted'])
            self.assertEqual(data['session_id'], session_id)
            self.assertEqual(data['user_role'], 'participant')
    
    def test_conflict_resolution_engine(self):
        """Test conflict resolution functionality"""
        conflict_resolver = self.collaboration_manager.conflict_resolver
        
        # Mock conflict data
        conflict_data = {
            'session_id': 'test-session',
            'field_name': 'description',
            'local_change': {
                'new_value': 'Local version of text',
                'timestamp': int(time.time() * 1000)
            },
            'remote_change': {
                'new_value': 'Remote version of text',
                'timestamp': int(time.time() * 1000) + 1000
            },
            'base_value': 'Original text'
        }
        
        # Test automatic resolution
        resolution = conflict_resolver.resolve_conflict(
            session_id='test-session',
            field_name='description',
            local_change=conflict_data['local_change'],
            remote_change=conflict_data['remote_change'],
            base_value='Original text',
            strategy='auto'
        )
        
        self.assertIsNotNone(resolution)
        self.assertIn('resolved_value', resolution)
        self.assertIn('resolution_method', resolution)
    
    @patch('pgappforge.collaboration.websocket_manager.SocketIO')
    def test_websocket_integration(self, mock_socketio):
        """Test WebSocket manager integration"""
        # Mock SocketIO instance
        mock_socketio_instance = Mock()
        mock_socketio.return_value = mock_socketio_instance
        
        # Test WebSocket manager creation
        ws_manager = create_websocket_manager(
            app=self.app,
            security_manager=self.appbuilder.sm
        )
        
        self.assertIsNotNone(ws_manager)
        mock_socketio.assert_called_once()
        
        # Test event handlers registration
        self.assertTrue(mock_socketio_instance.on.called)
    
    def test_sync_engine_model_registration(self):
        """Test data synchronization engine model registration"""
        sync_engine = self.collaboration_manager.sync_engine
        
        # Mock model class
        class TestModel:
            __tablename__ = 'test_model'
            id = 1
            name = 'test'
            description = 'test description'
        
        # Register model for synchronization
        sync_engine.register_model_sync(TestModel, ['name', 'description'])
        
        # Verify model is registered
        stats = sync_engine.get_sync_stats()
        self.assertGreaterEqual(stats.get('registered_models', 0), 1)
    
    def test_session_expiration_cleanup(self):
        """Test expired session cleanup"""
        security_mgr = self.collaboration_manager.security_integration
        
        # Create session with past expiration
        from datetime import datetime, timedelta
        past_time = datetime.utcnow() - timedelta(hours=1)
        
        session = CollaborationSecuritySession(
            id='expired-session',
            model_name='TestModel',
            created_by=self.test_user1.id,
            expires_at=past_time,
            is_active=True
        )
        
        self.db.session.add(session)
        self.db.session.commit()
        
        # Run cleanup
        cleaned_count = security_mgr.cleanup_expired_sessions()
        
        # Verify session was marked as inactive
        updated_session = self.db.session.query(CollaborationSecuritySession).filter_by(
            id='expired-session'
        ).first()
        
        self.assertIsNotNone(updated_session)
        self.assertFalse(updated_session.is_active)
        self.assertEqual(cleaned_count, 1)
    
    def test_collaboration_widget_integration(self):
        """Test collaboration widgets integration"""
        from pgappforge.collaboration.widgets import (
            CollaborativeFormWidget,
            PresenceIndicatorWidget,
            ConflictResolutionWidget
        )
        
        # Test collaborative form widget
        form_widget = CollaborativeFormWidget(
            collaboration_config={
                'enabled': True,
                'session_id': 'test-session',
                'model_name': 'TestModel',
                'websocket_url': '/test-collaboration'
            }
        )
        
        self.assertTrue(form_widget.enable_collaboration)
        self.assertEqual(form_widget.session_id, 'test-session')
        self.assertEqual(form_widget.model_name, 'TestModel')
        
        # Test presence indicator widget
        presence_widget = PresenceIndicatorWidget(
            session_id='test-session',
            show_avatars=True,
            max_users=5
        )
        
        self.assertEqual(presence_widget.template_args['session_id'], 'test-session')
        self.assertTrue(presence_widget.template_args['show_avatars'])
        self.assertEqual(presence_widget.template_args['max_users'], 5)
    
    def test_collaboration_mixins(self):
        """Test collaboration mixins for ModelView"""
        from pgappforge.collaboration.mixins import CollaborativeModelViewMixin
        
        # Create test class with mixin
        class TestCollaborativeView(CollaborativeModelViewMixin):
            enable_collaboration = True
            collaboration_fields = ['name', 'description']
        
        view = TestCollaborativeView()
        
        self.assertTrue(view.enable_collaboration)
        self.assertEqual(view.collaboration_fields, ['name', 'description'])
        
        # Test collaboration configuration generation
        config = view._get_collaboration_config()
        self.assertIsInstance(config, dict)
        self.assertIn('enabled', config)
        self.assertTrue(config['enabled'])
    
    def test_error_handling(self):
        """Test error handling in various collaboration scenarios"""
        security_mgr = self.collaboration_manager.security_integration
        
        # Test creating session without proper permissions
        self._login_user(self.test_user1)  # Regular user, can't create sessions
        
        session_id = security_mgr.create_secure_session(
            model_name='TestModel',
            record_id='error-test'
        )
        
        # Should return None due to insufficient permissions
        self.assertIsNone(session_id)
        
        # Test joining non-existent session
        access_info = security_mgr.validate_session_access('non-existent-session')
        self.assertFalse(access_info['can_join'])
        
        # Test invalid conflict resolution
        conflict_resolver = self.collaboration_manager.conflict_resolver
        
        with patch.object(conflict_resolver, 'db') as mock_db:
            mock_db.session.query.side_effect = Exception("Database error")
            
            resolution = conflict_resolver.resolve_conflict(
                session_id='error-session',
                field_name='test_field',
                local_change={'new_value': 'local'},
                remote_change={'new_value': 'remote'},
                strategy='auto'
            )
            
            # Should handle error gracefully
            self.assertIsNotNone(resolution)
            self.assertEqual(resolution.get('status'), 'error')
    
    def test_performance_and_scalability(self):
        """Test performance characteristics of collaboration system"""
        import threading
        import time
        
        security_mgr = self.collaboration_manager.security_integration
        self._login_user(self.test_user2)
        
        # Test creating multiple sessions concurrently
        session_ids = []
        threads = []
        
        def create_session(index):
            session_id = security_mgr.create_secure_session(
                model_name=f'TestModel{index}',
                record_id=f'{index}'
            )
            if session_id:
                session_ids.append(session_id)
        
        # Create 5 sessions concurrently
        for i in range(5):
            thread = threading.Thread(target=create_session, args=(i,))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Verify all sessions were created
        self.assertEqual(len(session_ids), 5)
        
        # Test session access performance
        start_time = time.time()
        
        for session_id in session_ids:
            access_info = security_mgr.validate_session_access(session_id, self.test_user1.id)
            self.assertTrue(access_info['can_join'])
        
        end_time = time.time()
        access_time = end_time - start_time
        
        # Should complete within reasonable time (< 1 second for 5 sessions)
        self.assertLess(access_time, 1.0)
    
    def test_collaboration_system_stats(self):
        """Test system statistics collection"""
        stats = self.collaboration_manager._get_system_stats()
        
        self.assertIsInstance(stats, dict)
        self.assertIn('total_sessions', stats)
        self.assertIn('active_participants', stats)
        self.assertIn('total_conflicts', stats)
        
        # All stats should be non-negative integers or floats
        for key, value in stats.items():
            self.assertIsInstance(value, (int, float))
            self.assertGreaterEqual(value, 0)


class TestCollaborationComponents(unittest.TestCase):
    """Unit tests for individual collaboration components"""
    
    def setUp(self):
        """Set up minimal test environment"""
        self.app = Flask(__name__)
        self.app.config.update({
            'SECRET_KEY': 'test-key',
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'TESTING': True
        })
        
        self.db = SQLA(self.app)
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.db.create_all()
    
    def tearDown(self):
        """Clean up test environment"""
        self.db.session.remove()
        self.db.drop_all()
        self.app_context.pop()
    
    def test_session_manager_isolation(self):
        """Test session manager in isolation"""
        session_manager = CollaborationSessionManager(
            db_session=self.db.session,
            redis_client=None,
            websocket_manager=None
        )
        
        self.assertIsNotNone(session_manager)
        
        # Test session creation without dependencies
        session_data = {
            'model_name': 'TestModel',
            'record_id': '123',
            'user_id': 1,
            'permissions': ['can_collaborate']
        }
        
        session_id = session_manager.create_collaboration_session(**session_data)
        self.assertIsNotNone(session_id)
    
    def test_conflict_resolver_algorithms(self):
        """Test conflict resolution algorithms in detail"""
        conflict_resolver = ConflictResolutionEngine(
            session_manager=None,
            db_session=self.db.session,
            websocket_manager=None
        )
        
        # Test text conflict resolution
        local_text = "Hello world from local"
        remote_text = "Hello world from remote"
        base_text = "Hello world"
        
        resolution = conflict_resolver._resolve_text_conflict(
            local_text, remote_text, base_text
        )
        
        self.assertIsNotNone(resolution)
        self.assertIn('resolved_value', resolution)
        
        # Test JSON conflict resolution
        local_json = {"name": "John", "age": 30}
        remote_json = {"name": "John", "age": 31, "email": "john@example.com"}
        base_json = {"name": "John", "age": 25}
        
        resolution = conflict_resolver._resolve_json_conflict(
            local_json, remote_json, base_json
        )
        
        self.assertIsNotNone(resolution)
        self.assertIsInstance(resolution['resolved_value'], dict)
    
    @patch('redis.from_url')
    def test_redis_integration(self, mock_redis):
        """Test Redis integration for scaling"""
        mock_redis_client = Mock()
        mock_redis.return_value = mock_redis_client
        mock_redis_client.ping.return_value = True
        
        session_manager = CollaborationSessionManager(
            db_session=self.db.session,
            redis_client=mock_redis_client,
            websocket_manager=None
        )
        
        # Test Redis operations
        session_manager._store_session_in_redis('test-session', {'data': 'test'})
        mock_redis_client.setex.assert_called()
        
        # Test Redis retrieval
        mock_redis_client.get.return_value = json.dumps({'data': 'test'})
        data = session_manager._get_session_from_redis('test-session')
        
        self.assertEqual(data['data'], 'test')


if __name__ == '__main__':
    # Create test suite
    test_suite = unittest.TestSuite()
    
    # Add integration tests
    test_suite.addTest(unittest.makeSuite(TestCollaborationIntegration))
    test_suite.addTest(unittest.makeSuite(TestCollaborationComponents))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # Print summary
    print(f"\nTest Summary:")
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success rate: {(result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun * 100:.1f}%")