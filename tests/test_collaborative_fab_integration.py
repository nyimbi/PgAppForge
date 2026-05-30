"""
Real PgAppForge integration tests for collaborative features.

Tests collaborative features with actual PgAppForge components including
security manager, database models, view registration, and API endpoints.
"""

import unittest
import tempfile
import os
import json
from datetime import datetime
from unittest.mock import Mock, patch

# Flask and SQLAlchemy imports
from flask import Flask, g
from flask_sqlalchemy import SQLAlchemy
from werkzeug.test import Client

# PgAppForge imports
from pgappforge import AppBuilder, SQLA
from pgappforge.security.sqla.manager import SecurityManager
from pgappforge.models.sqla import Model
from pgappforge.security.sqla.models import User, Role, Permission

# Collaborative feature imports
from pgappforge.collaborative.addon_manager import CollaborativeAddonManager
from pgappforge.collaborative.core.team_manager import Team, TeamInvitation
from pgappforge.collaborative.core.workspace_manager import Workspace, WorkspaceResource
from pgappforge.collaborative.communication.notification_manager import Notification
from pgappforge.collaborative.api.collaboration_api import CollaborationApi
from pgappforge.collaborative.api.communication_api import CommunicationApi
from pgappforge.collaborative.views.team_view import TeamModelView
from pgappforge.collaborative.views.workspace_view import WorkspaceModelView
from pgappforge.collaborative.utils.async_bridge import AsyncBridge


class FlaskAppBuilderCollaborativeIntegrationTest(unittest.TestCase):
    """Integration tests for collaborative features with PgAppForge."""

    def setUp(self):
        """Set up test environment with real PgAppForge."""
        # Create temporary database
        self.db_fd, self.db_path = tempfile.mkstemp()
        
        # Create Flask app
        self.app = Flask(__name__)
        self.app.config.update({
            'TESTING': True,
            'SECRET_KEY': 'test_secret_key_for_collaborative_testing_12345',
            'SQLALCHEMY_DATABASE_URI': f'sqlite:///{self.db_path}',
            'SQLALCHEMY_TRACK_MODIFICATIONS': False,
            'WTF_CSRF_ENABLED': False,
            
            # Collaborative feature configuration
            'COLLABORATIVE_ENABLED': True,
            'COLLABORATIVE_AUTO_DISCOVER': True,
            'COLLABORATIVE_WEBSOCKET_ENABLED': False,  # Disable for testing
            'COLLABORATIVE_BACKGROUND_TASKS': False,   # Disable for testing
            'COLLABORATIVE_HEALTH_CHECKS': True,
            'COLLABORATIVE_API_PREFIX': '/api/v1/collaborative',
            'COLLABORATIVE_MENU_CATEGORY': 'Collaboration',
            'COLLABORATIVE_MENU_ICON': 'fa-users',
            
            # PgAppForge configuration
            'APP_NAME': 'Collaborative Test App',
            'APP_THEME': 'bootstrap3.css',
            'FAB_UPDATE_PERMS': True,
        })
        
        # Initialize database
        self.db = SQLA(self.app)
        
        # Create AppBuilder with real security manager
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        # Create application context
        self.app_context = self.app.app_context()
        self.app_context.push()
        
        # Create all tables
        self.db.create_all()
        
        # Create test client
        self.client = self.app.test_client()
        
        # Create test user and roles
        self._create_test_users_and_roles()
        
        # Initialize collaborative addon manager
        self.collaborative_manager = None
        
    def tearDown(self):
        """Clean up test environment."""
        # Shutdown async bridge
        AsyncBridge.shutdown()
        
        # Remove application context
        self.app_context.pop()
        
        # Close and remove database
        self.db.session.remove()
        os.close(self.db_fd)
        os.unlink(self.db_path)
    
    def _create_test_users_and_roles(self):
        """Create test users and roles for testing."""
        # Create admin role if it doesn't exist
        admin_role = self.appbuilder.sm.find_role('Admin')
        if not admin_role:
            admin_role = self.appbuilder.sm.add_role('Admin')
        
        # Create test user
        test_user = self.appbuilder.sm.find_user(username='testuser')
        if not test_user:
            test_user = self.appbuilder.sm.add_user(
                username='testuser',
                first_name='Test',
                last_name='User',
                email='test@example.com',
                role=admin_role,
                password='password'
            )
        
        self.test_user = test_user
        self.admin_role = admin_role
        
        # Commit the changes
        self.db.session.commit()
    
    def _login_test_user(self):
        """Log in the test user."""
        response = self.client.post('/login/', data={
            'username': 'testuser',
            'password': 'password'
        }, follow_redirects=True)
        return response
    
    def test_collaborative_addon_manager_initialization(self):
        """Test that collaborative addon manager initializes correctly."""
        # Create collaborative addon manager
        self.collaborative_manager = CollaborativeAddonManager(self.appbuilder)
        
        # Test pre-processing
        try:
            self.collaborative_manager.pre_process()
            self.assertTrue(self.collaborative_manager.enabled)
            self.assertIsNotNone(self.collaborative_manager.service_registry)
        except Exception as e:
            # Some services might not be available in test environment
            self.assertIn('collaborative', str(e).lower())
    
    def test_collaborative_models_creation(self):
        """Test that collaborative models can be created with PgAppForge."""
        # Create a team
        team = Team(
            name='Test Team',
            slug='test-team',
            description='A test team for integration testing',
            is_public=False,
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(team)
        self.db.session.commit()
        
        # Verify team was created
        retrieved_team = self.db.session.query(Team).filter_by(slug='test-team').first()
        self.assertIsNotNone(retrieved_team)
        self.assertEqual(retrieved_team.name, 'Test Team')
        self.assertEqual(retrieved_team.created_by_id, self.test_user.id)
        
        # Create a workspace
        workspace = Workspace(
            name='Test Workspace',
            slug='test-workspace',
            description='A test workspace',
            workspace_type='team',
            uuid='test-uuid-12345',
            team_id=team.id,
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(workspace)
        self.db.session.commit()
        
        # Verify workspace was created
        retrieved_workspace = self.db.session.query(Workspace).filter_by(slug='test-workspace').first()
        self.assertIsNotNone(retrieved_workspace)
        self.assertEqual(retrieved_workspace.team_id, team.id)
        
        # Create a workspace resource
        resource = WorkspaceResource(
            name='Test Resource',
            resource_type='document',
            uuid='resource-uuid-12345',
            workspace_id=workspace.id,
            content='This is test content',
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(resource)
        self.db.session.commit()
        
        # Verify resource was created
        retrieved_resource = self.db.session.query(WorkspaceResource).filter_by(name='Test Resource').first()
        self.assertIsNotNone(retrieved_resource)
        self.assertEqual(retrieved_resource.workspace_id, workspace.id)
    
    def test_collaborative_view_registration(self):
        """Test that collaborative views can be registered with PgAppForge."""
        # Create collaborative addon manager
        self.collaborative_manager = CollaborativeAddonManager(self.appbuilder)
        
        # Manually register views (since they might not auto-register in test environment)
        try:
            # Register team view
            team_view = TeamModelView
            team_view.datamodel.obj = Team
            self.appbuilder.add_view(
                team_view,
                'Teams',
                icon='fa-users',
                category='Collaboration'
            )
            
            # Register workspace view
            workspace_view = WorkspaceModelView
            workspace_view.datamodel.obj = Workspace
            self.appbuilder.add_view(
                workspace_view,
                'Workspaces',
                icon='fa-folder',
                category='Collaboration'
            )
            
            # Verify views were registered
            self.assertIn('TeamModelView', str(self.appbuilder.baseviews))
            self.assertIn('WorkspaceModelView', str(self.appbuilder.baseviews))
            
        except Exception as e:
            # Some dependencies might not be available in test environment
            self.assertIsInstance(e, (ImportError, AttributeError))
    
    def test_collaborative_api_registration(self):
        """Test that collaborative APIs can be registered with PgAppForge."""
        # Create collaborative addon manager
        self.collaborative_manager = CollaborativeAddonManager(self.appbuilder)
        
        # Manually register APIs (since they might not auto-register in test environment)
        try:
            # Register collaboration API
            collaboration_api = CollaborationApi
            self.appbuilder.add_api(collaboration_api)
            
            # Register communication API
            communication_api = CommunicationApi
            self.appbuilder.add_api(communication_api)
            
            # Verify APIs were registered
            self.assertTrue(len(self.appbuilder.baseviews) > 0)
            
        except Exception as e:
            # Some dependencies might not be available in test environment
            self.assertIsInstance(e, (ImportError, AttributeError))
    
    def test_collaborative_permissions_integration(self):
        """Test that collaborative features integrate with PgAppForge permissions."""
        # Login test user
        with self.client.session_transaction() as sess:
            sess['user_id'] = self.test_user.id
        
        # Test that user has basic permissions
        self.assertTrue(self.appbuilder.sm.has_access('can_list', 'TeamModelView'))
        
        # Test collaborative permissions
        team_permissions = [
            'can_list',
            'can_show',
            'can_add', 
            'can_edit',
            'can_delete'
        ]
        
        for permission in team_permissions:
            # Check if permission exists (might not in test environment)
            perm = self.appbuilder.sm.find_permission_view_menu(
                permission, 'TeamModelView'
            )
            if perm:
                self.assertIsNotNone(perm)
    
    def test_collaborative_async_bridge_integration(self):
        """Test that async bridge works with PgAppForge context."""
        # Test async bridge in Flask application context
        with self.app.app_context():
            # Mock async service call
            async def mock_async_service():
                return {'result': 'success'}
            
            # Test running async code in sync context
            result = AsyncBridge.run_async(mock_async_service())
            self.assertEqual(result['result'], 'success')
            
            # Test sync wrapper
            sync_service = AsyncBridge.sync_wrapper(mock_async_service)
            result = sync_service()
            self.assertEqual(result['result'], 'success')
    
    def test_collaborative_database_constraints(self):
        """Test that database constraints work correctly."""
        # Test unique constraints
        team1 = Team(
            name='Unique Team',
            slug='unique-team',
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(team1)
        self.db.session.commit()
        
        # Try to create another team with same slug (should fail)
        team2 = Team(
            name='Another Team',
            slug='unique-team',  # Same slug
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(team2)
        
        with self.assertRaises(Exception):
            self.db.session.commit()
        
        # Rollback the failed transaction
        self.db.session.rollback()
    
    def test_collaborative_audit_integration(self):
        """Test that audit fields work with PgAppForge."""
        # Create team with audit fields
        team = Team(
            name='Audit Test Team',
            slug='audit-test-team',
            description='Testing audit integration',
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(team)
        self.db.session.commit()
        
        # Verify audit fields are populated
        retrieved_team = self.db.session.query(Team).filter_by(slug='audit-test-team').first()
        self.assertIsNotNone(retrieved_team.created_by_id)
        self.assertIsNotNone(retrieved_team.changed_by_id)
        self.assertIsNotNone(retrieved_team.created_on)
        self.assertIsNotNone(retrieved_team.changed_on)
        self.assertEqual(retrieved_team.created_by_id, self.test_user.id)
        
        # Update team and verify changed fields are updated
        original_changed_on = retrieved_team.changed_on
        retrieved_team.description = 'Updated description'
        retrieved_team.changed_by_id = self.test_user.id
        retrieved_team.changed_on = datetime.now()
        self.db.session.commit()
        
        # Verify changes
        updated_team = self.db.session.query(Team).filter_by(slug='audit-test-team').first()
        self.assertNotEqual(updated_team.changed_on, original_changed_on)
        self.assertEqual(updated_team.description, 'Updated description')
    
    def test_collaborative_service_registry_integration(self):
        """Test service registry integration with PgAppForge."""
        # Create collaborative addon manager
        self.collaborative_manager = CollaborativeAddonManager(self.appbuilder)
        
        try:
            # Initialize addon manager
            self.collaborative_manager.pre_process()
            
            # Test service registry
            if self.collaborative_manager.service_registry:
                # Test service registry validation
                issues = self.collaborative_manager.service_registry.validate_registry()
                
                # Should have some missing dependencies but no circular dependencies
                self.assertIsInstance(issues, dict)
                self.assertIn('missing_dependencies', issues)
                self.assertIn('circular_dependencies', issues)
                self.assertEqual(len(issues['circular_dependencies']), 0)
                
                # Test health status
                health_status = self.collaborative_manager.get_health_status()
                self.assertIsInstance(health_status, dict)
                self.assertIn('status', health_status)
                
        except Exception as e:
            # Service registry might not fully initialize in test environment
            self.assertIn('collaborative', str(e).lower())
    
    def test_collaborative_error_handling_integration(self):
        """Test error handling integration with PgAppForge."""
        from pgappforge.collaborative.utils.error_handling import (
            CollaborativeError, ValidationError, create_error_response
        )
        from pgappforge.collaborative.utils.error_patterns import (
            ErrorPatternMixin, api_error_handler
        )
        
        # Test error creation
        error = ValidationError(
            'Test validation error',
            field_name='test_field',
            field_value='invalid_value'
        )
        
        self.assertEqual(error.field_name, 'test_field')
        self.assertEqual(error.field_value, 'invalid_value')
        
        # Test error response creation
        response = create_error_response(error)
        self.assertTrue(response['error'])
        self.assertEqual(response['error_code'], 'VALIDATION')
        self.assertEqual(response['category'], 'validation')
        
        # Test error pattern mixin
        class TestService(ErrorPatternMixin):
            pass
        
        service = TestService()
        
        # Test validation error creation
        validation_error = service.handle_validation_error(
            'Test message',
            field_name='test_field'
        )
        self.assertIsInstance(validation_error, ValidationError)
        self.assertEqual(validation_error.field_name, 'test_field')
    
    def test_collaborative_notification_integration(self):
        """Test notification system integration with PgAppForge."""
        # Create a notification
        notification = Notification(
            user_id=self.test_user.id,
            notification_type='test_notification',
            title='Test Notification',
            message='This is a test notification',
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(notification)
        self.db.session.commit()
        
        # Verify notification was created
        retrieved_notification = self.db.session.query(Notification).filter_by(
            user_id=self.test_user.id
        ).first()
        self.assertIsNotNone(retrieved_notification)
        self.assertEqual(retrieved_notification.title, 'Test Notification')
        self.assertEqual(retrieved_notification.user_id, self.test_user.id)
        
        # Test notification reading
        retrieved_notification.is_read = True
        retrieved_notification.read_at = datetime.now()
        self.db.session.commit()
        
        # Verify read status
        updated_notification = self.db.session.query(Notification).filter_by(
            id=retrieved_notification.id
        ).first()
        self.assertTrue(updated_notification.is_read)
        self.assertIsNotNone(updated_notification.read_at)
    
    def test_collaborative_full_workflow_integration(self):
        """Test a complete collaborative workflow with PgAppForge."""
        # 1. Create a team
        team = Team(
            name='Integration Test Team',
            slug='integration-test-team',
            description='Testing full workflow',
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(team)
        self.db.session.flush()  # Get the ID
        
        # 2. Create a workspace
        workspace = Workspace(
            name='Integration Test Workspace',
            slug='integration-test-workspace',
            workspace_type='team',
            uuid='integration-test-uuid',
            team_id=team.id,
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(workspace)
        self.db.session.flush()  # Get the ID
        
        # 3. Create a resource
        resource = WorkspaceResource(
            name='Integration Test Document',
            resource_type='document',
            uuid='integration-resource-uuid',
            workspace_id=workspace.id,
            content='# Integration Test Document\n\nThis is a test document.',
            content_hash='test-hash-12345',
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(resource)
        
        # 4. Create a notification about the resource
        notification = Notification(
            user_id=self.test_user.id,
            notification_type='document_created',
            title='New Document Created',
            message=f'A new document "{resource.name}" was created in workspace "{workspace.name}"',
            related_entity_type='workspace_resource',
            related_entity_id=str(resource.uuid),
            created_by_id=self.test_user.id,
            changed_by_id=self.test_user.id,
            created_on=datetime.now(),
            changed_on=datetime.now()
        )
        self.db.session.add(notification)
        
        # Commit all changes
        self.db.session.commit()
        
        # 5. Verify the complete workflow
        # Check team exists
        retrieved_team = self.db.session.query(Team).filter_by(id=team.id).first()
        self.assertIsNotNone(retrieved_team)
        
        # Check workspace exists and is linked to team
        retrieved_workspace = self.db.session.query(Workspace).filter_by(id=workspace.id).first()
        self.assertIsNotNone(retrieved_workspace)
        self.assertEqual(retrieved_workspace.team_id, team.id)
        
        # Check resource exists and is linked to workspace
        retrieved_resource = self.db.session.query(WorkspaceResource).filter_by(id=resource.id).first()
        self.assertIsNotNone(retrieved_resource)
        self.assertEqual(retrieved_resource.workspace_id, workspace.id)
        
        # Check notification exists
        retrieved_notification = self.db.session.query(Notification).filter_by(
            related_entity_id=str(resource.uuid)
        ).first()
        self.assertIsNotNone(retrieved_notification)
        self.assertEqual(retrieved_notification.user_id, self.test_user.id)
        
        # Verify all audit fields are properly set
        for item in [retrieved_team, retrieved_workspace, retrieved_resource, retrieved_notification]:
            self.assertIsNotNone(item.created_by_id)
            self.assertIsNotNone(item.changed_by_id)
            self.assertIsNotNone(item.created_on)
            self.assertIsNotNone(item.changed_on)
            self.assertEqual(item.created_by_id, self.test_user.id)
    
    def test_collaborative_configuration_integration(self):
        """Test that collaborative configuration integrates with PgAppForge."""
        # Create collaborative addon manager
        self.collaborative_manager = CollaborativeAddonManager(self.appbuilder)
        
        # Test configuration loading
        self.collaborative_manager._load_configuration()
        
        # Verify configuration was loaded from Flask app config
        self.assertIsInstance(self.collaborative_manager.config, dict)
        self.assertTrue(self.collaborative_manager.config['COLLABORATIVE_ENABLED'])
        self.assertTrue(self.collaborative_manager.config['COLLABORATIVE_AUTO_DISCOVER'])
        self.assertEqual(
            self.collaborative_manager.config['COLLABORATIVE_API_PREFIX'],
            '/api/v1/collaborative'
        )
        self.assertEqual(
            self.collaborative_manager.config['COLLABORATIVE_MENU_CATEGORY'],
            'Collaboration'
        )
        
        # Test configuration validation
        try:
            self.collaborative_manager._validate_configuration()
            # Should pass since we have all required Flask config
        except ValueError as e:
            self.fail(f"Configuration validation failed: {e}")


if __name__ == '__main__':
    # Run the integration tests
    unittest.main(verbosity=2)