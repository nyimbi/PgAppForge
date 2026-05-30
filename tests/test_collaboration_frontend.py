"""
Frontend JavaScript Tests for PgAppForge Collaboration Engine

Tests JavaScript components including collaboration manager, presence indicators,
conflict resolution UI, and browser-based functionality.
"""

import unittest
import os
import json
from unittest.mock import Mock, patch, MagicMock
from flask import Flask, render_template_string
from pgappforge import AppBuilder, SQLA


class TestCollaborationFrontend(unittest.TestCase):
    """Test frontend JavaScript components and templates"""
    
    def setUp(self):
        """Set up test environment"""
        self.app = Flask(__name__)
        self.app.config.update({
            'SECRET_KEY': 'frontend-test-key',
            'TESTING': True,
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'COLLABORATION_ENABLED': True
        })
        
        self.db = SQLA(self.app)
        self.appbuilder = AppBuilder(self.app, self.db.session)
        
        self.app_context = self.app.app_context()
        self.app_context.push()
        self.db.create_all()
        
        # Create test user
        self.test_user = self.appbuilder.sm.add_user(
            username='frontend_user',
            first_name='Frontend',
            last_name='User',
            email='frontend@example.com',
            role=self.appbuilder.sm.find_role('Admin')
        )
        self.db.session.commit()
    
    def tearDown(self):
        """Clean up test environment"""
        self.db.session.remove()
        self.db.drop_all()
        self.app_context.pop()
    
    def test_javascript_files_exist(self):
        """Test that required JavaScript files exist"""
        js_files = [
            'pgappforge/static/appbuilder/js/collaboration/collaboration-manager.js',
            'pgappforge/static/appbuilder/js/collaboration/presence-manager.js',
            'pgappforge/static/appbuilder/js/collaboration/conflict-resolver.js'
        ]
        
        for js_file in js_files:
            file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), js_file)
            self.assertTrue(os.path.exists(file_path), f"JavaScript file missing: {js_file}")
    
    def test_css_files_exist(self):
        """Test that required CSS files exist"""
        css_files = [
            'pgappforge/static/appbuilder/css/collaboration.css'
        ]
        
        for css_file in css_files:
            file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), css_file)
            self.assertTrue(os.path.exists(file_path), f"CSS file missing: {css_file}")
    
    def test_template_files_exist(self):
        """Test that required template files exist"""
        template_files = [
            'pgappforge/templates/appbuilder/collaboration/widgets/collaborative_form.html',
            'pgappforge/templates/appbuilder/collaboration/widgets/presence_indicator.html',
            'pgappforge/templates/appbuilder/collaboration/widgets/conflict_resolution.html',
            'pgappforge/templates/appbuilder/collaboration/widgets/collaboration_toolbar.html'
        ]
        
        for template_file in template_files:
            file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), template_file)
            self.assertTrue(os.path.exists(file_path), f"Template file missing: {template_file}")
    
    def test_collaborative_form_template_rendering(self):
        """Test collaborative form template renders correctly"""
        template_content = '''
        {% extends "appbuilder/general/widgets/form.html" %}
        {% block content %}
        <div class="collaboration-form-container" 
             data-collaboration-enabled="{{ collaboration_enabled|tojson }}"
             data-session-id="{{ collaboration_session_id or '' }}"
             data-model-name="{{ collaboration_model or '' }}">
            <div class="form-container">Test Form</div>
        </div>
        {% endblock %}
        '''
        
        with self.app.test_request_context():
            rendered = render_template_string(
                template_content,
                collaboration_enabled=True,
                collaboration_session_id='test-session-123',
                collaboration_model='TestModel'
            )
            
            self.assertIn('data-collaboration-enabled="true"', rendered)
            self.assertIn('data-session-id="test-session-123"', rendered)
            self.assertIn('data-model-name="TestModel"', rendered)
            self.assertIn('collaboration-form-container', rendered)
    
    def test_presence_indicator_template_rendering(self):
        """Test presence indicator template renders correctly"""
        template_content = '''
        <div class="collaboration-presence-widget" 
             data-session-id="{{ session_id or '' }}"
             data-show-avatars="{{ show_avatars|tojson }}"
             data-max-users="{{ max_users or 10 }}">
            <div class="presence-users" id="presence-users"></div>
            <div class="presence-status" id="presence-status">
                <span class="status-indicator"></span>
            </div>
        </div>
        '''
        
        with self.app.test_request_context():
            rendered = render_template_string(
                template_content,
                session_id='test-session',
                show_avatars=True,
                max_users=5
            )
            
            self.assertIn('data-session-id="test-session"', rendered)
            self.assertIn('data-show-avatars="true"', rendered)
            self.assertIn('data-max-users="5"', rendered)
            self.assertIn('presence-users', rendered)
    
    def test_conflict_resolution_template_rendering(self):
        """Test conflict resolution template renders correctly"""
        template_content = '''
        <div class="collaboration-conflict-widget">
            <div class="conflict-overlay">
                <div class="conflict-modal">
                    <div class="conflict-header">
                        <h4>Merge Conflict Detected</h4>
                    </div>
                    <div class="conflict-versions">
                        <div class="conflict-version" data-version="local">
                            <div class="version-header">Your Version</div>
                            <div class="version-content">
                                <textarea id="local-content"></textarea>
                            </div>
                        </div>
                        <div class="conflict-version" data-version="remote">
                            <div class="version-header">Their Version</div>
                            <div class="version-content">
                                <textarea id="remote-content"></textarea>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        '''
        
        with self.app.test_request_context():
            rendered = render_template_string(template_content)
            
            self.assertIn('collaboration-conflict-widget', rendered)
            self.assertIn('Merge Conflict Detected', rendered)
            self.assertIn('data-version="local"', rendered)
            self.assertIn('data-version="remote"', rendered)
            self.assertIn('id="local-content"', rendered)
            self.assertIn('id="remote-content"', rendered)
    
    def test_collaboration_toolbar_template_rendering(self):
        """Test collaboration toolbar template renders correctly"""
        template_content = '''
        <div class="collaboration-toolbar-widget {{ toolbar_position|default('top') }}"
             data-session-id="{{ session_id or '' }}"
             data-show-participant-count="{{ show_participant_count|tojson }}">
            <div class="toolbar-status">
                <div class="status-indicator"></div>
                <span class="status-text">Connected</span>
            </div>
            {% if show_participant_count %}
            <div class="toolbar-participants">
                <span class="participant-count">0</span>
            </div>
            {% endif %}
            <div class="toolbar-controls">
                <button class="toolbar-btn collaboration-toggle">Collaborate</button>
            </div>
        </div>
        '''
        
        with self.app.test_request_context():
            rendered = render_template_string(
                template_content,
                session_id='toolbar-session',
                toolbar_position='bottom',
                show_participant_count=True
            )
            
            self.assertIn('collaboration-toolbar-widget bottom', rendered)
            self.assertIn('data-session-id="toolbar-session"', rendered)
            self.assertIn('data-show-participant-count="true"', rendered)
            self.assertIn('toolbar-participants', rendered)
            self.assertIn('participant-count', rendered)
    
    def test_javascript_configuration_injection(self):
        """Test JavaScript configuration data injection"""
        template_content = '''
        <script type="text/javascript">
        document.addEventListener('DOMContentLoaded', function() {
            const config = {
                sessionId: '{{ collaboration_session_id }}',
                modelName: '{{ collaboration_model }}',
                websocketUrl: '{{ collaboration_websocket_url }}',
                userInfo: {{ collaboration_user_info|tojson }},
                fields: {{ collaboration_fields|tojson }},
                permissions: {{ collaboration_permissions|tojson }}
            };
            
            console.log('Collaboration config:', config);
        });
        </script>
        '''
        
        user_info = {
            'user_id': self.test_user.id,
            'username': self.test_user.username,
            'display_name': f"{self.test_user.first_name} {self.test_user.last_name}"
        }
        
        collaboration_fields = ['name', 'description', 'status']
        collaboration_permissions = ['can_collaborate', 'can_comment']
        
        with self.app.test_request_context():
            rendered = render_template_string(
                template_content,
                collaboration_session_id='config-test-session',
                collaboration_model='ConfigTestModel',
                collaboration_websocket_url='/config-ws',
                collaboration_user_info=user_info,
                collaboration_fields=collaboration_fields,
                collaboration_permissions=collaboration_permissions
            )
            
            self.assertIn("sessionId: 'config-test-session'", rendered)
            self.assertIn("modelName: 'ConfigTestModel'", rendered)
            self.assertIn("websocketUrl: '/config-ws'", rendered)
            
            # Check JSON serialization
            self.assertIn(f'"user_id": {self.test_user.id}', rendered)
            self.assertIn(f'"username": "{self.test_user.username}"', rendered)
            self.assertIn('"name", "description", "status"', rendered)
            self.assertIn('"can_collaborate", "can_comment"', rendered)
    
    def test_widget_template_integration(self):
        """Test widget template integration with PgAppForge"""
        from pgappforge.collaboration.widgets import (
            CollaborativeFormWidget,
            PresenceIndicatorWidget,
            ConflictResolutionWidget,
            CollaborationToolbarWidget
        )
        
        # Test CollaborativeFormWidget
        form_widget = CollaborativeFormWidget(
            collaboration_config={
                'enabled': True,
                'session_id': 'widget-test-session',
                'model_name': 'WidgetTestModel'
            }
        )
        
        self.assertEqual(form_widget.template, "appbuilder/collaboration/widgets/collaborative_form.html")
        self.assertTrue(form_widget.template_args['collaboration_enabled'])
        self.assertEqual(form_widget.template_args['collaboration_session_id'], 'widget-test-session')
        
        # Test PresenceIndicatorWidget
        presence_widget = PresenceIndicatorWidget(
            session_id='presence-session',
            show_avatars=True,
            max_users=8
        )
        
        self.assertEqual(presence_widget.template, "appbuilder/collaboration/widgets/presence_indicator.html")
        self.assertEqual(presence_widget.template_args['session_id'], 'presence-session')
        self.assertTrue(presence_widget.template_args['show_avatars'])
        self.assertEqual(presence_widget.template_args['max_users'], 8)
        
        # Test ConflictResolutionWidget
        conflict_widget = ConflictResolutionWidget(
            conflict_data={
                'conflict_id': 'test-conflict',
                'field_name': 'test_field'
            }
        )
        
        self.assertEqual(conflict_widget.template, "appbuilder/collaboration/widgets/conflict_resolution.html")
        self.assertEqual(conflict_widget.template_args['conflict_data']['conflict_id'], 'test-conflict')
        
        # Test CollaborationToolbarWidget
        toolbar_widget = CollaborationToolbarWidget(
            session_id='toolbar-session',
            show_participant_count=True,
            show_connection_status=True
        )
        
        self.assertEqual(toolbar_widget.template, "appbuilder/collaboration/widgets/collaboration_toolbar.html")
        self.assertEqual(toolbar_widget.template_args['session_id'], 'toolbar-session')
        self.assertTrue(toolbar_widget.template_args['show_participant_count'])
    
    def test_css_class_integration(self):
        """Test CSS class integration and styling"""
        template_content = '''
        <div class="collaboration-form-container collaboration-enabled">
            <div class="collaboration-field being-edited being-edited-by-user-1">
                <input type="text" name="test_field" class="form-control">
                <div class="collaboration-field-label">User is editing</div>
            </div>
            
            <div class="collaboration-presence">
                <img class="collaboration-user-avatar active" src="/static/img/avatar.png">
            </div>
            
            <div class="collaboration-cursor" style="color: #FF6B6B;" data-username="TestUser">
            </div>
            
            <div class="collaboration-notification success">
                <div>Collaboration started</div>
            </div>
        </div>
        '''
        
        with self.app.test_request_context():
            rendered = render_template_string(template_content)
            
            # Check that all collaboration CSS classes are present
            expected_classes = [
                'collaboration-form-container',
                'collaboration-enabled',
                'collaboration-field',
                'being-edited',
                'being-edited-by-user-1',
                'collaboration-field-label',
                'collaboration-presence',
                'collaboration-user-avatar',
                'collaboration-cursor',
                'collaboration-notification'
            ]
            
            for css_class in expected_classes:
                self.assertIn(css_class, rendered)
    
    def test_accessibility_features(self):
        """Test accessibility features in templates"""
        template_content = '''
        <div class="collaboration-toolbar-widget">
            <button class="toolbar-btn" title="Toggle Collaboration" aria-label="Toggle collaboration mode">
                <i class="fa fa-share-alt" aria-hidden="true"></i>
                <span class="btn-text">Collaborate</span>
            </button>
            
            <div class="toolbar-participants" role="status" aria-live="polite">
                <span class="participant-count" aria-label="Number of active participants">3</span>
            </div>
            
            <div class="status-indicator" role="status" aria-label="Connection status" 
                 title="Connected to collaboration server"></div>
        </div>
        
        <div class="collaboration-conflict-modal" role="dialog" aria-modal="true" 
             aria-labelledby="conflict-title">
            <div class="conflict-header">
                <h4 id="conflict-title">Merge Conflict Detected</h4>
                <button class="conflict-close" aria-label="Close conflict resolution dialog">
                    <i class="fa fa-times" aria-hidden="true"></i>
                </button>
            </div>
        </div>
        '''
        
        with self.app.test_request_context():
            rendered = render_template_string(template_content)
            
            # Check accessibility attributes
            accessibility_features = [
                'aria-label="Toggle collaboration mode"',
                'aria-hidden="true"',
                'role="status"',
                'aria-live="polite"',
                'role="dialog"',
                'aria-modal="true"',
                'aria-labelledby="conflict-title"',
                'title="Connected to collaboration server"'
            ]
            
            for feature in accessibility_features:
                self.assertIn(feature, rendered)
    
    def test_responsive_design_elements(self):
        """Test responsive design elements in templates"""
        template_content = '''
        <div class="collaboration-toolbar-widget">
            <div class="toolbar-controls d-flex d-md-inline-flex">
                <button class="toolbar-btn d-none d-sm-inline-block">
                    <span class="btn-text d-none d-md-inline">Full Text</span>
                    <span class="btn-text-short d-inline d-md-none">Short</span>
                </button>
            </div>
        </div>
        
        <div class="collaboration-conflict-modal">
            <div class="conflict-versions row">
                <div class="conflict-version col-12 col-md-6">Local Version</div>
                <div class="conflict-version col-12 col-md-6">Remote Version</div>
            </div>
        </div>
        
        <div class="collaboration-presence d-block d-lg-flex">
            <div class="presence-users flex-wrap"></div>
        </div>
        '''
        
        with self.app.test_request_context():
            rendered = render_template_string(template_content)
            
            # Check responsive classes (Bootstrap-style)
            responsive_classes = [
                'd-flex d-md-inline-flex',
                'd-none d-sm-inline-block',
                'd-none d-md-inline',
                'd-inline d-md-none',
                'col-12 col-md-6',
                'd-block d-lg-flex'
            ]
            
            for css_class in responsive_classes:
                self.assertIn(css_class, rendered)
    
    def test_error_handling_in_templates(self):
        """Test error handling and fallback values in templates"""
        template_content = '''
        <div class="collaboration-form-container" 
             data-collaboration-enabled="{{ collaboration_enabled|default(false)|tojson }}"
             data-session-id="{{ collaboration_session_id or '' }}"
             data-user-info="{{ collaboration_user_info|default({})|tojson }}"
             data-fields="{{ collaboration_fields|default([])|tojson }}">
            
            {% if collaboration_enabled %}
                <div class="collaboration-active">Collaboration enabled</div>
            {% else %}
                <div class="collaboration-disabled">Collaboration disabled</div>
            {% endif %}
            
            <div class="user-display">
                {{ collaboration_user_info.display_name or collaboration_user_info.username or 'Anonymous' }}
            </div>
            
            <div class="field-count">
                {{ collaboration_fields|length if collaboration_fields else 0 }} fields
            </div>
        </div>
        '''
        
        # Test with missing values
        with self.app.test_request_context():
            rendered = render_template_string(template_content)
            
            self.assertIn('data-collaboration-enabled="false"', rendered)
            self.assertIn('data-session-id=""', rendered)
            self.assertIn('data-user-info="{}"', rendered)
            self.assertIn('data-fields="[]"', rendered)
            self.assertIn('collaboration-disabled', rendered)
            self.assertIn('Anonymous', rendered)
            self.assertIn('0 fields', rendered)
        
        # Test with provided values
        with self.app.test_request_context():
            rendered = render_template_string(
                template_content,
                collaboration_enabled=True,
                collaboration_session_id='test-session',
                collaboration_user_info={'display_name': 'Test User'},
                collaboration_fields=['field1', 'field2']
            )
            
            self.assertIn('data-collaboration-enabled="true"', rendered)
            self.assertIn('data-session-id="test-session"', rendered)
            self.assertIn('collaboration-active', rendered)
            self.assertIn('Test User', rendered)
            self.assertIn('2 fields', rendered)
    
    def test_security_considerations(self):
        """Test security considerations in template rendering"""
        template_content = '''
        <div class="collaboration-form-container">
            <!-- Test XSS protection -->
            <div class="user-name">{{ user_name|e }}</div>
            <div class="session-id" data-session="{{ session_id|e }}">{{ session_id|e }}</div>
            
            <!-- Test JSON escaping -->
            <script>
                var config = {{ config|tojson }};
                var userInfo = {{ user_info|tojson }};
            </script>
            
            <!-- Test attribute escaping -->
            <input type="hidden" value="{{ hidden_value|e }}">
        </div>
        '''
        
        # Test with potentially malicious input
        malicious_input = '<script>alert("xss")</script>'
        
        with self.app.test_request_context():
            rendered = render_template_string(
                template_content,
                user_name=malicious_input,
                session_id=malicious_input,
                config={'test': malicious_input},
                user_info={'name': malicious_input},
                hidden_value=malicious_input
            )
            
            # Check that HTML is escaped
            self.assertIn('&lt;script&gt;alert("xss")&lt;/script&gt;', rendered)
            self.assertNotIn('<script>alert("xss")</script>', rendered)
            
            # Check JSON escaping
            self.assertIn(r'\"<script>alert(\\\"xss\\\")</script>\"', rendered)


class TestJavaScriptModules(unittest.TestCase):
    """Test JavaScript module structure and API"""
    
    def setUp(self):
        """Set up test environment"""
        self.js_base_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            'pgappforge/static/appbuilder/js/collaboration'
        )
    
    def test_javascript_module_exports(self):
        """Test JavaScript module exports and global registration"""
        js_files = {
            'collaboration-manager.js': ['CollaborationManager'],
            'presence-manager.js': ['PresenceManager', 'CollaborationPresenceManager'],
            'conflict-resolver.js': ['ConflictResolver', 'CollaborationConflictResolver']
        }
        
        for js_file, expected_exports in js_files.items():
            file_path = os.path.join(self.js_base_path, js_file)
            
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    
                    for export_name in expected_exports:
                        # Check global registration
                        self.assertIn(f'window.{export_name}', content,
                                    f"Global registration missing for {export_name} in {js_file}")
    
    def test_javascript_error_handling(self):
        """Test JavaScript error handling patterns"""
        js_files = ['collaboration-manager.js', 'presence-manager.js', 'conflict-resolver.js']
        
        for js_file in js_files:
            file_path = os.path.join(self.js_base_path, js_file)
            
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    
                    # Check for try-catch blocks
                    self.assertIn('try {', content, f"Error handling missing in {js_file}")
                    self.assertIn('catch', content, f"Error handling missing in {js_file}")
                    
                    # Check for console.error logging
                    self.assertIn('console.error', content, f"Error logging missing in {js_file}")
    
    def test_javascript_initialization_patterns(self):
        """Test JavaScript initialization patterns"""
        js_files = ['collaboration-manager.js', 'presence-manager.js', 'conflict-resolver.js']
        
        for js_file in js_files:
            file_path = os.path.join(self.js_base_path, js_file)
            
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    content = f.read()
                    
                    # Check for DOM ready initialization
                    dom_ready_patterns = [
                        'DOMContentLoaded',
                        'document.addEventListener',
                        'window.addEventListener'
                    ]
                    
                    has_initialization = any(pattern in content for pattern in dom_ready_patterns)
                    self.assertTrue(has_initialization, 
                                  f"Initialization pattern missing in {js_file}")


if __name__ == '__main__':
    unittest.main(verbosity=2)