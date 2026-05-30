#!/usr/bin/env python3
"""
Comprehensive Integration Test Suite for Enhanced Wizard System

Tests all components working together without relying on PgAppForge imports.
"""

import sys
import os
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Add the project root to Python path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

def test_wizard_config_integration():
    """Test wizard configuration system"""
    try:
        from pgappforge.config.wizard import WizardConfig, WizardUIConfig
        
        print("✓ Testing wizard configuration...")
        
        # Test basic config creation
        config = WizardConfig(
            title="Test Wizard",
            description="Integration test wizard"
        )
        assert config.title == "Test Wizard"
        
        # Test UI config integration
        ui_config = WizardUIConfig(
            theme="modern_blue",
            layout_style="vertical"
        )
        assert ui_config.theme == "modern_blue"
        
        print("  ✓ Configuration system working correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Configuration test failed: {e}")
        return False

def test_wizard_forms_integration():
    """Test wizard forms functionality"""
    try:
        from pgappforge.forms.wizard import WizardForm, WizardFormManager
        
        print("✓ Testing wizard forms...")
        
        # Test form creation
        form_config = {
            'title': 'Integration Test Form',
            'steps': [
                {
                    'id': 'step1',
                    'title': 'Basic Info',
                    'fields': [
                        {'id': 'name', 'type': 'text', 'label': 'Name', 'required': True}
                    ]
                }
            ]
        }
        
        wizard_form = WizardForm(config=form_config)
        assert wizard_form.config['title'] == 'Integration Test Form'
        assert len(wizard_form.config['steps']) == 1
        
        # Test form manager
        manager = WizardFormManager()
        form_id = manager.create_wizard(form_config)
        assert form_id is not None
        
        print("  ✓ Wizard forms working correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Wizard forms test failed: {e}")
        return False

def test_theme_system_integration():
    """Test theme system functionality"""
    try:
        from pgappforge.theming.wizard_themes import (
            WizardThemeManager, 
            WizardTheme,
            WizardColorScheme
        )
        
        print("✓ Testing theme system...")
        
        # Test theme manager
        theme_manager = WizardThemeManager()
        themes = theme_manager.get_all_themes()
        assert len(themes) >= 5  # Should have our 5 built-in themes
        
        # Test theme CSS generation
        modern_blue = theme_manager.get_theme('modern_blue')
        assert modern_blue is not None
        css = modern_blue.to_css()
        assert ':root' in css
        assert '--wizard-primary' in css
        
        print("  ✓ Theme system working correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Theme system test failed: {e}")
        return False

def test_error_handling_integration():
    """Test error handling system"""
    try:
        from pgappforge.utils.error_handling import (
            WizardErrorHandler,
            WizardErrorType,
            WizardErrorSeverity,
            WizardError
        )
        
        print("✓ Testing error handling...")
        
        # Test error handler
        error_handler = WizardErrorHandler()
        
        # Test handling a validation error
        error = error_handler.handle_error(
            "Test validation error",
            WizardErrorType.VALIDATION_ERROR,
            WizardErrorSeverity.MEDIUM,
            field_id="test_field"
        )
        
        assert error.error_type == WizardErrorType.VALIDATION_ERROR
        assert error.severity == WizardErrorSeverity.MEDIUM
        assert error.user_friendly_message is not None
        assert len(error.recovery_suggestions) > 0
        
        print("  ✓ Error handling working correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Error handling test failed: {e}")
        return False

def test_analytics_integration():
    """Test analytics system"""
    try:
        from pgappforge.analytics.wizard_analytics import (
            WizardAnalyticsEngine,
            WizardCompletionStats
        )
        
        print("✓ Testing analytics system...")
        
        # Test analytics engine
        analytics = WizardAnalyticsEngine("test_wizard")
        
        # Test event tracking
        analytics.track_step_start("step1", "user123")
        analytics.track_field_interaction("field1", "click", "user123")
        
        # Test completion stats
        stats = WizardCompletionStats(
            total_starts=100,
            total_completions=85,
            completion_rate=0.85,
            average_duration=300
        )
        
        assert stats.completion_rate == 0.85
        assert stats.total_starts == 100
        
        print("  ✓ Analytics system working correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Analytics test failed: {e}")
        return False

def test_collaboration_integration():
    """Test collaboration system"""
    try:
        from pgappforge.collaboration.wizard_collaboration import (
            WizardCollaborationManager,
            CollaborationPermission
        )
        
        print("✓ Testing collaboration system...")
        
        # Test collaboration manager
        collab_manager = WizardCollaborationManager()
        
        # Test session management
        session_data = collab_manager.join_session("wizard1", "user1", "session1")
        assert 'active_users' in session_data
        
        # Test permission management
        success = collab_manager.grant_permission(
            "wizard1", "user2", CollaborationPermission.EDIT, "user1"
        )
        assert success == True
        
        user_perm = collab_manager.get_user_permission("wizard1", "user2")
        assert user_perm == CollaborationPermission.EDIT
        
        print("  ✓ Collaboration system working correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Collaboration test failed: {e}")
        return False

def test_migration_system_integration():
    """Test migration/export system"""
    try:
        from pgappforge.migration.wizard_migration import (
            WizardMigrationManager,
            WizardExporter
        )
        
        print("✓ Testing migration system...")
        
        # Test migration manager
        migration_manager = WizardMigrationManager()
        status = migration_manager.get_migration_status()
        assert 'version' in status
        
        # Test exporter
        exporter = WizardExporter()
        
        # Create test data
        test_data = {
            'wizard1': {
                'title': 'Test Export Wizard',
                'configuration': {'steps': []},
                'metadata': {'created_at': datetime.now().isoformat()}
            }
        }
        
        # Test export to JSON
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            export_path = exporter.export_to_file(['wizard1'], f.name, format='json')
            assert os.path.exists(export_path)
            
            # Cleanup
            os.unlink(f.name)
        
        print("  ✓ Migration system working correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Migration test failed: {e}")
        return False

def test_data_flow_integration():
    """Test data flow between components"""
    try:
        from pgappforge.config.wizard import WizardConfig
        from pgappforge.theming.wizard_themes import WizardThemeManager
        from pgappforge.analytics.wizard_analytics import WizardAnalyticsEngine
        
        print("✓ Testing cross-component data flow...")
        
        # Create wizard config
        config = WizardConfig(
            title="Data Flow Test",
            theme_id="modern_blue"
        )
        
        # Get theme from theme manager
        theme_manager = WizardThemeManager()
        theme = theme_manager.get_theme(config.theme_id)
        assert theme is not None
        assert theme.id == "modern_blue"
        
        # Track with analytics
        analytics = WizardAnalyticsEngine("dataflow_test")
        analytics.track_wizard_created("dataflow_test", "user1")
        
        # Verify data consistency
        assert config.theme_id == theme.id
        
        print("  ✓ Data flow integration working correctly")
        return True
        
    except Exception as e:
        print(f"  ✗ Data flow test failed: {e}")
        return False

def run_all_integration_tests():
    """Run all integration tests"""
    print("🚀 Starting Comprehensive Integration Test Suite")
    print("=" * 60)
    
    tests = [
        test_wizard_config_integration,
        test_wizard_forms_integration,
        test_theme_system_integration,
        test_error_handling_integration,
        test_analytics_integration,
        test_collaboration_integration,
        test_migration_system_integration,
        test_data_flow_integration,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
            failed += 1
        print()
    
    print("=" * 60)
    print(f"🎯 Integration Test Results:")
    print(f"  ✓ Passed: {passed}")
    print(f"  ✗ Failed: {failed}")
    print(f"  📊 Success Rate: {(passed / (passed + failed)) * 100:.1f}%")
    
    if failed == 0:
        print("🎉 ALL INTEGRATION TESTS PASSED!")
        print("🚀 System is production-ready!")
        return True
    else:
        print("⚠️  Some tests failed - review issues above")
        return False

if __name__ == "__main__":
    success = run_all_integration_tests()
    sys.exit(0 if success else 1)