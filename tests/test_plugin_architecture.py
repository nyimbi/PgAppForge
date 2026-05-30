"""
Comprehensive tests for the enhanced plugin architecture.

These tests ensure the new plugin system works correctly and provides
proper security, isolation, and lifecycle management.
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from flask import Flask

from pgappforge import AppBuilder
from pgappforge.plugins import (
    BasePlugin, PluginManager, PluginRegistry, PluginLoader, SecurePluginLoader,
    PluginValidator, PluginMetadata, PluginDependency, PluginPriority, PluginStatus
)
from pgappforge.plugins.exceptions import (
    PluginError, PluginLoadError, PluginValidationError, PluginSecurityError
)


class TestPluginMetadata:
    """Test plugin metadata functionality."""

    def test_plugin_metadata_creation(self):
        """Test plugin metadata creation with all fields."""
        metadata = PluginMetadata(
            name="test_plugin",
            version="1.0.0",
            description="Test plugin description",
            author="Test Author",
            author_email="test@example.com",
            url="https://example.com",
            license="MIT",
            tags=["test", "example"],
            api_version="1.0.0",
            priority=PluginPriority.NORMAL,
            dependencies=[],
            permissions=["read", "write"],
            safe_mode_compatible=True,
            trusted_source=False
        )

        assert metadata.name == "test_plugin"
        assert metadata.version == "1.0.0"
        assert metadata.priority == PluginPriority.NORMAL
        assert metadata.safe_mode_compatible is True

    def test_plugin_dependency(self):
        """Test plugin dependency functionality."""
        dependency = PluginDependency(
            name="required_plugin",
            version="2.0.0",
            optional=False,
            minimum_version="1.5.0",
            maximum_version="3.0.0"
        )

        assert dependency.name == "required_plugin"
        assert dependency.optional is False

        # Test version satisfaction
        assert dependency.is_satisfied_by("2.0.0") is True
        assert dependency.is_satisfied_by("1.8.0") is True
        assert dependency.is_satisfied_by("1.0.0") is False  # Below minimum
        assert dependency.is_satisfied_by("4.0.0") is False  # Above maximum


class TestBasePlugin:
    """Test BasePlugin functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        self.appbuilder = Mock()

    def test_concrete_plugin_implementation(self):
        """Test concrete plugin implementation."""

        class TestPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="test_plugin",
                    version="1.0.0",
                    description="Test plugin",
                    author="Test Author"
                )

            def initialize(self):
                self.initialized = True

        plugin = TestPlugin(self.appbuilder)
        assert plugin.status == PluginStatus.UNLOADED
        assert hasattr(plugin, 'config')
        assert plugin.appbuilder == self.appbuilder

    def test_plugin_lifecycle(self):
        """Test plugin lifecycle management."""

        class TestPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="lifecycle_test",
                    version="1.0.0",
                    description="Lifecycle test plugin",
                    author="Test"
                )

            def initialize(self):
                self.initialization_called = True

            def cleanup(self):
                self.cleanup_called = True

        plugin = TestPlugin(self.appbuilder)

        # Test activation
        success = plugin.activate()
        assert success is True
        assert plugin.status == PluginStatus.ACTIVE
        assert hasattr(plugin, 'initialization_called')
        assert plugin.load_time is not None

        # Test deactivation
        success = plugin.deactivate()
        assert success is True
        assert plugin.status == PluginStatus.UNLOADED
        assert hasattr(plugin, 'cleanup_called')

    def test_plugin_configuration(self):
        """Test plugin configuration management."""

        class ConfigurablePlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="configurable",
                    version="1.0.0",
                    description="Configurable plugin",
                    author="Test"
                )

            def initialize(self):
                self.feature_enabled = self.config.get('feature_enabled', False)

        config = {'feature_enabled': True, 'timeout': 30}
        plugin = ConfigurablePlugin(self.appbuilder, config)

        assert plugin.config == config

        # Test configuration update
        new_config = {'feature_enabled': False, 'debug': True}
        plugin.configure(new_config)
        assert plugin.config['feature_enabled'] is False
        assert plugin.config['debug'] is True
        assert plugin.config['timeout'] == 30  # Should be preserved

    def test_plugin_status_tracking(self):
        """Test plugin status tracking."""

        class StatusTestPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="status_test",
                    version="1.0.0",
                    description="Status test plugin",
                    author="Test"
                )

            def initialize(self):
                pass

        plugin = StatusTestPlugin(self.appbuilder)

        # Get status info
        status = plugin.get_status()
        assert status['name'] == "status_test"
        assert status['version'] == "1.0.0"
        assert status['status'] == PluginStatus.UNLOADED.value
        assert 'load_time' in status
        assert 'resources' in status

    def test_plugin_resource_tracking(self):
        """Test plugin resource tracking."""

        class ResourcePlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="resource_test",
                    version="1.0.0",
                    description="Resource test plugin",
                    author="Test"
                )

            def initialize(self):
                # Mock adding resources
                self._registered_views.append(("TestView", "Test View"))
                self._registered_blueprints.append("test_blueprint")

        plugin = ResourcePlugin(Mock())
        plugin.initialize()

        status = plugin.get_status()
        assert status['resources']['views'] == 1
        assert status['resources']['blueprints'] == 1


class TestPluginRegistry:
    """Test plugin registry functionality."""

    def setup_method(self):
        """Set up test registry."""
        self.registry = PluginRegistry()

    def test_plugin_class_registration(self):
        """Test plugin class registration."""

        class TestPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="registry_test",
                    version="1.0.0",
                    description="Registry test",
                    author="Test"
                )

            def initialize(self):
                pass

        self.registry.register_plugin_class(TestPlugin)

        assert "registry_test" in self.registry.list_plugins()
        assert self.registry.get_plugin_class("registry_test") == TestPlugin
        metadata = self.registry.get_metadata("registry_test")
        assert metadata.name == "registry_test"

    def test_plugin_instance_registration(self):
        """Test plugin instance registration."""

        class TestPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="instance_test",
                    version="1.0.0",
                    description="Instance test",
                    author="Test"
                )

            def initialize(self):
                pass

        plugin = TestPlugin(Mock())
        self.registry.register_plugin_instance(plugin)

        assert "instance_test" in self.registry.list_active_plugins()
        assert self.registry.get_plugin("instance_test") == plugin

    def test_registry_status_summary(self):
        """Test registry status summary."""

        class TestPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="summary_test",
                    version="1.0.0",
                    description="Summary test",
                    author="Test"
                )

            def initialize(self):
                pass

        # Register plugin class
        self.registry.register_plugin_class(TestPlugin)

        # Create and register instance
        plugin = TestPlugin(Mock())
        plugin.status = PluginStatus.ACTIVE
        self.registry.register_plugin_instance(plugin)

        summary = self.registry.get_status_summary()
        assert summary['total_registered'] == 1
        assert summary['active_instances'] == 1
        assert PluginStatus.ACTIVE.value in summary['status_counts']


class TestPluginManager:
    """Test plugin manager functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test_secret'
        self.appbuilder = Mock()
        self.manager = PluginManager(self.appbuilder)

    def test_plugin_loading(self):
        """Test plugin loading."""

        class LoadTestPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="load_test",
                    version="1.0.0",
                    description="Load test plugin",
                    author="Test"
                )

            def initialize(self):
                self.loaded = True

        # Register plugin class
        self.manager.register_plugin_class(LoadTestPlugin)

        # Load plugin
        success = self.manager.load_plugin("load_test")
        assert success is True

        # Check plugin is loaded
        plugin = self.manager.registry.get_plugin("load_test")
        assert plugin is not None
        assert hasattr(plugin, 'loaded')

    def test_plugin_dependency_resolution(self):
        """Test plugin dependency resolution."""

        class DependentPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="dependent",
                    version="1.0.0",
                    description="Dependent plugin",
                    author="Test",
                    dependencies=[
                        PluginDependency(name="required_plugin", version="1.0.0")
                    ]
                )

            def initialize(self):
                pass

        class RequiredPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="required_plugin",
                    version="1.0.0",
                    description="Required plugin",
                    author="Test"
                )

            def initialize(self):
                pass

        # Register plugins
        self.manager.register_plugin_class(RequiredPlugin)
        self.manager.register_plugin_class(DependentPlugin)

        # Load required plugin first
        self.manager.load_plugin("required_plugin")

        # Load dependent plugin - should succeed
        success = self.manager.load_plugin("dependent")
        assert success is True

    def test_plugin_unloading_with_dependencies(self):
        """Test plugin unloading with dependency checking."""

        class RequiredPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="required",
                    version="1.0.0",
                    description="Required plugin",
                    author="Test"
                )

            def initialize(self):
                pass

        class DependentPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="dependent",
                    version="1.0.0",
                    description="Dependent plugin",
                    author="Test",
                    dependencies=[
                        PluginDependency(name="required", version="1.0.0")
                    ]
                )

            def initialize(self):
                pass

        # Register and load plugins
        self.manager.register_plugin_class(RequiredPlugin)
        self.manager.register_plugin_class(DependentPlugin)
        self.manager.load_plugin("required")
        self.manager.load_plugin("dependent")

        # Try to unload required plugin - should fail
        success = self.manager.unload_plugin("required")
        assert success is False  # Should fail due to dependency

        # Unload dependent first, then required
        self.manager.unload_plugin("dependent")
        success = self.manager.unload_plugin("required")
        assert success is True

    def test_batch_plugin_loading(self):
        """Test batch plugin loading with dependency order."""

        class PluginA(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="plugin_a",
                    version="1.0.0",
                    description="Plugin A",
                    author="Test"
                )

            def initialize(self):
                pass

        class PluginB(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="plugin_b",
                    version="1.0.0",
                    description="Plugin B",
                    author="Test",
                    dependencies=[PluginDependency(name="plugin_a")]
                )

            def initialize(self):
                pass

        # Register plugins
        self.manager.register_plugin_class(PluginA)
        self.manager.register_plugin_class(PluginB)

        # Load plugins in batch (wrong order)
        plugin_configs = {
            "plugin_b": {},
            "plugin_a": {}
        }

        results = self.manager.load_plugins_batch(plugin_configs)

        # Both should load successfully despite wrong order
        assert results["plugin_a"] is True
        assert results["plugin_b"] is True

    def test_plugin_status_reporting(self):
        """Test plugin status reporting."""

        class StatusPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="status_plugin",
                    version="1.0.0",
                    description="Status plugin",
                    author="Test"
                )

            def initialize(self):
                pass

        self.manager.register_plugin_class(StatusPlugin)
        self.manager.load_plugin("status_plugin")

        # Get plugin status
        status = self.manager.get_plugin_status("status_plugin")
        assert status is not None
        assert status['name'] == "status_plugin"
        assert status['status'] == PluginStatus.ACTIVE.value

        # List all plugins
        plugins = self.manager.list_plugins()
        assert len(plugins) >= 1
        assert any(p['name'] == "status_plugin" for p in plugins)


class TestPluginValidator:
    """Test plugin validator functionality."""

    def setup_method(self):
        """Set up test validator."""
        self.validator = PluginValidator()

    def test_valid_plugin_validation(self):
        """Test validation of a valid plugin."""

        class ValidPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="valid_plugin",
                    version="1.0.0",
                    description="A valid test plugin",
                    author="Test Author"
                )

            def initialize(self):
                self.initialized = True

        result = self.validator.validate_plugin_class(ValidPlugin)

        assert result['valid'] is True
        assert len(result['validation_errors']) == 0
        assert result['metadata']['name'] == "valid_plugin"

    def test_invalid_plugin_validation(self):
        """Test validation of an invalid plugin."""

        class InvalidPlugin:  # Doesn't inherit from BasePlugin
            pass

        with pytest.raises(PluginValidationError):
            self.validator.validate_plugin_class(InvalidPlugin)

    def test_plugin_security_validation(self):
        """Test plugin security validation."""

        class PotentiallyDangerousPlugin(BasePlugin):
            @property
            def metadata(self):
                return PluginMetadata(
                    name="dangerous_plugin",
                    version="1.0.0",
                    description="Potentially dangerous plugin",
                    author="Test"
                )

            def initialize(self):
                # This would contain dangerous code in a real scenario
                import json  # Safe import for testing
                self.data = json.dumps({"test": True})

        # Validation should complete without security errors for safe code
        result = self.validator.validate_plugin_class(PotentiallyDangerousPlugin)
        assert isinstance(result, dict)

    def test_plugin_file_validation(self):
        """Test plugin file validation."""
        # Create temporary plugin file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write("""
from pgappforge.plugins import BasePlugin, PluginMetadata

class FileTestPlugin(BasePlugin):
    @property
    def metadata(self):
        return PluginMetadata(
            name="file_test",
            version="1.0.0",
            description="File test plugin",
            author="Test"
        )

    def initialize(self):
        pass
""")
            plugin_file = Path(f.name)

        try:
            result = self.validator.validate_plugin_file(plugin_file)
            assert result['valid'] is True
            assert result['metadata']['name'] == "file_test"
        finally:
            os.unlink(plugin_file)


class TestPluginLoader:
    """Test plugin loader functionality."""

    def setup_method(self):
        """Set up test loader."""
        self.loader = PluginLoader()

    def test_plugin_loading_from_module(self):
        """Test loading plugin from module name."""
        # This would normally load from an actual module
        # For testing, we'll mock the import process
        with patch('importlib.import_module') as mock_import:
            # Mock module with plugin class
            mock_module = Mock()

            class MockPlugin(BasePlugin):
                @property
                def metadata(self):
                    return PluginMetadata(
                        name="mock_plugin",
                        version="1.0.0",
                        description="Mock plugin",
                        author="Test"
                    )

                def initialize(self):
                    pass

            # Set up mock module attributes
            mock_module.MockPlugin = MockPlugin
            mock_import.return_value = mock_module

            # Mock dir() to return our plugin class
            with patch('builtins.dir', return_value=['MockPlugin']):
                with patch('builtins.getattr', return_value=MockPlugin):
                    plugin_class = self.loader.load_plugin_from_module("test.module")
                    assert plugin_class == MockPlugin

    def test_plugin_discovery(self):
        """Test plugin discovery."""
        # Create temporary directory with plugin files
        with tempfile.TemporaryDirectory() as temp_dir:
            plugin_path = Path(temp_dir)
            self.loader.add_plugin_path(plugin_path)

            # Create a mock plugin file
            plugin_file = plugin_path / "test_plugin.py"
            plugin_file.write_text("""
# Mock plugin file
class TestPlugin:
    pass
""")

            discovered = self.loader.discover_plugins()
            assert "test_plugin" in discovered


class TestSecurePluginLoader:
    """Test secure plugin loader functionality."""

    def setup_method(self):
        """Set up secure loader."""
        with tempfile.TemporaryDirectory() as temp_dir:
            self.allowed_path = Path(temp_dir)
            self.loader = SecurePluginLoader(
                strict_security=True,
                allowed_paths=[self.allowed_path]
            )

    def test_path_security_validation(self):
        """Test path security validation."""
        # Create file outside allowed path
        with tempfile.NamedTemporaryFile(suffix='.py', delete=False) as f:
            f.write("# Test plugin")
            unauthorized_file = Path(f.name)

        try:
            with pytest.raises(PluginSecurityError):
                self.loader.load_plugin_from_file(unauthorized_file)
        finally:
            os.unlink(unauthorized_file)

    def test_file_permission_validation(self):
        """Test file permission validation."""
        # This test is platform-specific and may not work on all systems
        if os.name == 'posix':  # Unix-like systems
            plugin_file = self.allowed_path / "test_plugin.py"
            plugin_file.write_text("# Test plugin")

            # Make file world-writable (security risk)
            os.chmod(plugin_file, 0o666)

            # Should raise security error in strict mode
            with pytest.raises(PluginSecurityError):
                self.loader.load_plugin_from_file(plugin_file)

    def test_security_violations_tracking(self):
        """Test security violations tracking."""
        # Attempt unsafe operations
        violations_before = len(self.loader.get_security_violations())

        # Try to load from unsafe module
        with pytest.raises(PluginSecurityError):
            self.loader.load_plugin_from_module("os")

        violations_after = len(self.loader.get_security_violations())
        assert violations_after > violations_before


class TestPluginIntegration:
    """Test plugin system integration with AppBuilder."""

    def setup_method(self):
        """Set up test environment."""
        self.app = Flask(__name__)
        self.app.config['SECRET_KEY'] = 'test_secret_key'
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

    def test_plugin_system_initialization(self):
        """Test plugin system initialization in AppBuilder."""
        with self.app.app_context():
            appbuilder = AppBuilder(self.app)

            # Plugin system should be initialized
            assert appbuilder.plugin_manager is not None
            assert appbuilder.plugin_loader is not None

    def test_plugin_configuration_integration(self):
        """Test plugin configuration through Flask config."""
        with self.app.app_context():
            # Configure plugins
            self.app.config['PGAF_PLUGINS'] = [
                {
                    'name': 'test_plugin',
                    'module': 'fake.module',
                    'config': {'enabled': True}
                }
            ]

            appbuilder = AppBuilder(self.app)

            # Plugin system should process configuration
            assert appbuilder.plugin_manager is not None

    def test_legacy_addon_compatibility(self):
        """Test compatibility with legacy ADDON_MANAGERS."""
        with self.app.app_context():
            # Mock legacy addon
            class LegacyAddon:
                def __init__(self, appbuilder):
                    self.appbuilder = appbuilder

                def pre_process(self):
                    pass

                def register_views(self):
                    pass

                def post_process(self):
                    pass

            # Configure legacy addon
            self.app.config['ADDON_MANAGERS'] = ['test.LegacyAddon']

            with patch('pgappforge.base.dynamic_class_import', return_value=LegacyAddon):
                appbuilder = AppBuilder(self.app)

                # Should handle legacy addons gracefully
                assert 'test.LegacyAddon' in appbuilder.addon_managers


if __name__ == "__main__":
    pytest.main([__file__, "-v"])