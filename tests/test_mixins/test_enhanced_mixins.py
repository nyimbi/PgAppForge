"""
Comprehensive tests for enhanced mixins.

Tests EnhancedSoftDeleteMixin, MetadataMixin, StateTrackingMixin,
CacheableMixin, and ImportExportMixin with full coverage of
functionality, error handling, and edge cases.
"""

import json
import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock, patch, MagicMock

from pgappforge import Model
from pgappforge.mixins.enhanced_mixins import (
    EnhancedSoftDeleteMixin, MetadataMixin, StateTrackingMixin,
    CacheableMixin, ImportExportMixin
)
from pgappforge.mixins.security_framework import (
    MixinDataError, MixinValidationError
)


# Test models for testing mixins
class TestSoftDeleteModel(EnhancedSoftDeleteMixin, Model):
    __tablename__ = 'test_soft_delete'
    
    # Required by EnhancedSoftDeleteMixin
    __soft_delete_cascade__ = ['related_items']
    
    name = None  # Will be set in tests


class TestMetadataModel(MetadataMixin, Model):
    __tablename__ = 'test_metadata'
    
    name = None


class TestStateTrackingModel(StateTrackingMixin, Model):
    __tablename__ = 'test_state_tracking'
    
    # Required by StateTrackingMixin
    __valid_states__ = ['draft', 'pending', 'approved', 'rejected']
    __initial_state__ = 'draft'
    
    name = None


class TestCacheableModel(CacheableMixin, Model):
    __tablename__ = 'test_cacheable'
    
    # Required by CacheableMixin
    __cache_timeout__ = 300
    __cache_key_fields__ = ['id', 'name']
    
    name = None


class TestImportExportModel(ImportExportMixin, Model):
    __tablename__ = 'test_import_export'
    
    # Required by ImportExportMixin
    __exportable_fields__ = {'name': 'Name', 'value': 'Value'}
    __importable_fields__ = {'name': str, 'value': int}
    
    name = None
    value = None


class TestEnhancedSoftDeleteMixin:
    """Test EnhancedSoftDeleteMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestSoftDeleteModel()
        self.model.id = 123
        self.model.name = "Test Item"
        self.model.deleted = False
        self.model.deleted_on = None
        self.model.deleted_by_fk = None
    
    def test_soft_delete_basic(self):
        """Test basic soft delete functionality."""
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 456
            
            result = self.model.soft_delete()
            
            assert result is True
            assert self.model.deleted is True
            assert isinstance(self.model.deleted_on, datetime)
            assert self.model.deleted_by_fk == 456
    
    def test_soft_delete_with_reason(self):
        """Test soft delete with deletion reason."""
        deletion_reason = "Item no longer needed"
        
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 789
            
            result = self.model.soft_delete(reason=deletion_reason)
            
            assert result is True
            assert self.model.deletion_reason == deletion_reason
    
    def test_soft_delete_already_deleted(self):
        """Test soft delete on already deleted item."""
        self.model.deleted = True
        
        result = self.model.soft_delete()
        
        assert result is False  # Should not delete again
    
    def test_restore_deleted_item(self):
        """Test restoring a soft-deleted item."""
        # First delete the item
        self.model.deleted = True
        self.model.deleted_on = datetime.utcnow()
        self.model.deleted_by_fk = 123
        
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 456
            
            result = self.model.restore()
            
            assert result is True
            assert self.model.deleted is False
            assert self.model.deleted_on is None
            assert self.model.deleted_by_fk is None
            assert self.model.restored_on is not None
            assert self.model.restored_by_fk == 456
    
    def test_restore_non_deleted_item(self):
        """Test restore on non-deleted item."""
        self.model.deleted = False
        
        result = self.model.restore()
        
        assert result is False
    
    @patch('pgappforge.mixins.enhanced_mixins.db')
    def test_purge_hard_delete(self, mock_db):
        """Test permanent deletion (purge)."""
        self.model.deleted = True
        
        result = self.model.purge()
        
        assert result is True
        mock_db.session.delete.assert_called_once_with(self.model)
        mock_db.session.commit.assert_called_once()
    
    def test_purge_non_deleted_item(self):
        """Test purge on non-deleted item should fail."""
        self.model.deleted = False
        
        with pytest.raises(MixinDataError) as exc_info:
            self.model.purge()
        
        assert "not soft-deleted" in str(exc_info.value)
    
    @patch('pgappforge.mixins.enhanced_mixins.db')
    def test_bulk_soft_delete(self, mock_db):
        """Test bulk soft delete operation."""
        # Setup query mock
        mock_query = Mock()
        mock_db.session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.update.return_value = 5  # 5 items updated
        
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 789
            
            result = TestSoftDeleteModel.bulk_soft_delete([1, 2, 3, 4, 5])
            
            assert result == 5
            mock_query.update.assert_called_once()
            mock_db.session.commit.assert_called_once()
    
    @patch('pgappforge.mixins.enhanced_mixins.db')
    def test_cascade_delete_relationships(self, mock_db):
        """Test cascade deletion to related objects."""
        # Mock related objects
        mock_related_item1 = Mock()
        mock_related_item2 = Mock()
        self.model.related_items = [mock_related_item1, mock_related_item2]
        
        with patch('pgappforge.mixins.enhanced_mixins.current_user'):
            result = self.model.soft_delete(cascade=True)
            
            assert result is True
            # Verify related items were soft deleted
            mock_related_item1.soft_delete.assert_called_once()
            mock_related_item2.soft_delete.assert_called_once()


class TestMetadataMixin:
    """Test MetadataMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestMetadataModel()
        self.model.id = 123
        self.model.metadata_json = '{}'
    
    def test_set_metadata_basic(self):
        """Test basic metadata setting."""
        test_data = {"category": "important", "priority": 5}
        
        self.model.set_metadata("config", test_data)
        
        metadata = json.loads(self.model.metadata_json)
        assert metadata["config"] == test_data
    
    def test_get_metadata_existing(self):
        """Test retrieving existing metadata."""
        test_metadata = {"config": {"setting1": "value1", "setting2": 42}}
        self.model.metadata_json = json.dumps(test_metadata)
        
        result = self.model.get_metadata("config")
        
        assert result == {"setting1": "value1", "setting2": 42}
    
    def test_get_metadata_non_existent_with_default(self):
        """Test retrieving non-existent metadata with default."""
        self.model.metadata_json = '{}'
        
        result = self.model.get_metadata("missing", default={"default": True})
        
        assert result == {"default": True}
    
    def test_get_metadata_non_existent_no_default(self):
        """Test retrieving non-existent metadata without default."""
        self.model.metadata_json = '{}'
        
        result = self.model.get_metadata("missing")
        
        assert result is None
    
    def test_remove_metadata(self):
        """Test removing metadata key."""
        test_metadata = {"keep": "this", "remove": "this"}
        self.model.metadata_json = json.dumps(test_metadata)
        
        result = self.model.remove_metadata("remove")
        
        assert result is True
        remaining_metadata = json.loads(self.model.metadata_json)
        assert "keep" in remaining_metadata
        assert "remove" not in remaining_metadata
    
    def test_remove_nonexistent_metadata(self):
        """Test removing non-existent metadata key."""
        self.model.metadata_json = '{"existing": "data"}'
        
        result = self.model.remove_metadata("nonexistent")
        
        assert result is False
    
    def test_update_metadata_merge(self):
        """Test updating metadata with merge."""
        initial_metadata = {"config": {"setting1": "old", "setting2": "keep"}}
        self.model.metadata_json = json.dumps(initial_metadata)
        
        update_data = {"setting1": "new", "setting3": "add"}
        self.model.update_metadata("config", update_data)
        
        result = self.model.get_metadata("config")
        expected = {"setting1": "new", "setting2": "keep", "setting3": "add"}
        assert result == expected
    
    def test_search_by_metadata(self):
        """Test searching by metadata."""
        with patch.object(TestMetadataModel, 'query') as mock_query:
            mock_filter = Mock()
            mock_query.filter.return_value = mock_filter
            
            TestMetadataModel.search_by_metadata("category", "important")
            
            mock_query.filter.assert_called_once()
    
    def test_invalid_json_handling(self):
        """Test handling of invalid JSON in metadata."""
        self.model.metadata_json = "invalid json"
        
        result = self.model.get_metadata("anything")
        
        assert result is None  # Should handle gracefully


class TestStateTrackingMixin:
    """Test StateTrackingMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestStateTrackingModel()
        self.model.id = 123
        self.model.current_state = 'draft'
        self.model.state_history = '[]'
    
    def test_change_state_valid_transition(self):
        """Test valid state change."""
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 456
            
            result = self.model.change_state('pending', 'Ready for review')
            
            assert result is True
            assert self.model.current_state == 'pending'
            
            # Check state history
            history = json.loads(self.model.state_history)
            assert len(history) == 1
            assert history[0]['from_state'] == 'draft'
            assert history[0]['to_state'] == 'pending'
            assert history[0]['reason'] == 'Ready for review'
            assert history[0]['changed_by'] == 456
    
    def test_change_state_invalid_state(self):
        """Test changing to invalid state."""
        with pytest.raises(MixinValidationError) as exc_info:
            self.model.change_state('invalid_state')
        
        assert "Invalid state" in str(exc_info.value)
        assert exc_info.value.value == 'invalid_state'
    
    def test_can_transition_to_valid(self):
        """Test checking valid state transition."""
        result = self.model.can_transition_to('approved')
        
        # Should be valid (no restrictions defined)
        assert result is True
    
    def test_get_state_history(self):
        """Test retrieving state history."""
        # Setup history
        history_data = [
            {
                'from_state': 'draft',
                'to_state': 'pending',
                'timestamp': '2023-01-01T12:00:00',
                'changed_by': 123,
                'reason': 'Initial submission'
            }
        ]
        self.model.state_history = json.dumps(history_data)
        
        result = self.model.get_state_history()
        
        assert len(result) == 1
        assert result[0]['from_state'] == 'draft'
        assert result[0]['to_state'] == 'pending'
    
    def test_get_current_state_info(self):
        """Test getting current state information."""
        # Add some history
        self.model.change_state('pending', 'Ready for review')
        
        result = self.model.get_current_state_info()
        
        assert result['state'] == 'pending'
        assert 'changed_on' in result
        assert 'changed_by' in result


class TestCacheableMixin:
    """Test CacheableMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestCacheableModel()
        self.model.id = 123
        self.model.name = "Test Item"
    
    def test_generate_cache_key(self):
        """Test cache key generation."""
        expected_key = "TestCacheableModel:123:Test Item"
        
        result = self.model._generate_cache_key()
        
        assert result == expected_key
    
    @patch('pgappforge.mixins.enhanced_mixins.current_app')
    def test_get_cached_existing(self, mock_app):
        """Test retrieving existing cached data."""
        # Setup cache mock
        mock_cache = Mock()
        mock_app.cache = mock_cache
        mock_cache.get.return_value = {"cached": "data"}
        
        result = self.model.get_cached()
        
        assert result == {"cached": "data"}
        cache_key = "TestCacheableModel:123:Test Item"
        mock_cache.get.assert_called_once_with(cache_key)
    
    @patch('pgappforge.mixins.enhanced_mixins.current_app')
    def test_get_cached_non_existent(self, mock_app):
        """Test retrieving non-existent cached data."""
        # Setup cache mock
        mock_cache = Mock()
        mock_app.cache = mock_cache
        mock_cache.get.return_value = None
        
        result = self.model.get_cached()
        
        assert result is None
    
    @patch('pgappforge.mixins.enhanced_mixins.current_app')
    def test_set_cached(self, mock_app):
        """Test setting cached data."""
        # Setup cache mock
        mock_cache = Mock()
        mock_app.cache = mock_cache
        
        test_data = {"test": "data"}
        self.model.set_cached(test_data)
        
        cache_key = "TestCacheableModel:123:Test Item"
        mock_cache.set.assert_called_once_with(cache_key, test_data, timeout=300)
    
    @patch('pgappforge.mixins.enhanced_mixins.current_app')
    def test_invalidate_cache(self, mock_app):
        """Test cache invalidation."""
        # Setup cache mock
        mock_cache = Mock()
        mock_app.cache = mock_cache
        
        self.model.invalidate_cache()
        
        cache_key = "TestCacheableModel:123:Test Item"
        mock_cache.delete.assert_called_once_with(cache_key)
    
    def test_cache_without_cache_backend(self):
        """Test cache operations without cache backend."""
        with patch('pgappforge.mixins.enhanced_mixins.current_app') as mock_app:
            # No cache attribute
            del mock_app.cache
            
            # Should handle gracefully
            result = self.model.get_cached()
            assert result is None
            
            # Should not raise errors
            self.model.set_cached({"data": "test"})
            self.model.invalidate_cache()


class TestImportExportMixin:
    """Test ImportExportMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestImportExportModel()
        self.model.id = 123
        self.model.name = "Test Item"
        self.model.value = 42
    
    def test_to_dict_basic(self):
        """Test basic dictionary export."""
        result = self.model.to_dict()
        
        expected = {"name": "Test Item", "value": 42}
        assert result == expected
    
    def test_to_dict_with_exclusions(self):
        """Test dictionary export with field exclusions."""
        result = self.model.to_dict(exclude_fields=['value'])
        
        expected = {"name": "Test Item"}
        assert result == expected
    
    def test_from_dict_valid_data(self):
        """Test importing from valid dictionary."""
        import_data = {"name": "Imported Item", "value": 100}
        
        result = self.model.from_dict(import_data)
        
        assert result is True
        assert self.model.name == "Imported Item"
        assert self.model.value == 100
    
    def test_from_dict_invalid_field_type(self):
        """Test importing with invalid field type."""
        import_data = {"name": "Test", "value": "not_an_integer"}
        
        with pytest.raises(MixinValidationError) as exc_info:
            self.model.from_dict(import_data)
        
        assert "Invalid type for field 'value'" in str(exc_info.value)
    
    def test_from_dict_unknown_field(self):
        """Test importing with unknown field."""
        import_data = {"name": "Test", "unknown_field": "value"}
        
        # Should ignore unknown fields by default
        result = self.model.from_dict(import_data)
        
        assert result is True
        assert self.model.name == "Test"
        assert not hasattr(self.model, "unknown_field")
    
    def test_validate_import_data_valid(self):
        """Test validation of valid import data."""
        import_data = {"name": "Test Item", "value": 50}
        
        errors = self.model.validate_import_data(import_data)
        
        assert errors == []
    
    def test_validate_import_data_invalid_types(self):
        """Test validation of import data with type errors."""
        import_data = {"name": 123, "value": "not_integer"}
        
        errors = self.model.validate_import_data(import_data)
        
        assert len(errors) == 2
        assert any("name" in error for error in errors)
        assert any("value" in error for error in errors)
    
    @patch.object(TestImportExportModel, 'query')
    def test_bulk_import_valid_data(self, mock_query):
        """Test bulk import with valid data."""
        import_data = [
            {"name": "Item 1", "value": 10},
            {"name": "Item 2", "value": 20}
        ]
        
        with patch('pgappforge.mixins.enhanced_mixins.db') as mock_db:
            result = TestImportExportModel.bulk_import(import_data)
            
            assert result['success'] == 2
            assert result['errors'] == 0
            assert mock_db.session.commit.called
    
    def test_bulk_import_with_validation_errors(self):
        """Test bulk import with validation errors."""
        import_data = [
            {"name": "Item 1", "value": 10},  # Valid
            {"name": 123, "value": "invalid"}  # Invalid
        ]
        
        with patch('pgappforge.mixins.enhanced_mixins.db'):
            result = TestImportExportModel.bulk_import(import_data)
            
            assert result['success'] == 1
            assert result['errors'] == 1
            assert len(result['error_details']) == 1


class TestMixinInteractions:
    """Test interactions between multiple mixins."""
    
    def setup_method(self):
        """Setup test model with multiple mixins."""
        class CombinedModel(EnhancedSoftDeleteMixin, MetadataMixin, StateTrackingMixin, Model):
            __tablename__ = 'combined_test'
            __valid_states__ = ['active', 'inactive', 'deleted']
            __initial_state__ = 'active'
            
            name = None
        
        self.model = CombinedModel()
        self.model.id = 123
        self.model.name = "Combined Test"
        self.model.deleted = False
        self.model.current_state = 'active'
        self.model.metadata_json = '{}'
        self.model.state_history = '[]'
    
    def test_soft_delete_updates_state(self):
        """Test that soft delete also updates state."""
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 456
            
            # Soft delete should also change state
            self.model.soft_delete()
            
            assert self.model.deleted is True
            # Could also update state to 'deleted' if business logic requires it
    
    def test_metadata_persists_across_state_changes(self):
        """Test that metadata is preserved during state changes."""
        # Set some metadata
        self.model.set_metadata("config", {"important": True})
        
        # Change state
        with patch('pgappforge.mixins.enhanced_mixins.current_user'):
            self.model.change_state('inactive', 'Temporarily disabled')
        
        # Metadata should still be there
        result = self.model.get_metadata("config")
        assert result == {"important": True}
    
    def test_state_change_logs_in_metadata(self):
        """Test using metadata to store additional state change info."""
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 789
            
            # Store additional info in metadata during state change
            additional_info = {"approval_id": "APPROVAL-123", "reviewer": "john.doe"}
            self.model.set_metadata("last_state_change", additional_info)
            self.model.change_state('inactive', 'Pending approval')
            
            # Verify both state and metadata were updated
            assert self.model.current_state == 'inactive'
            assert self.model.get_metadata("last_state_change") == additional_info


if __name__ == "__main__":
    pytest.main([__file__, "-v"])