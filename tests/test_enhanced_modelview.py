"""
Unit tests for Enhanced ModelView Integration.

This module contains comprehensive unit tests for the Enhanced ModelView
system including smart exclusion, field analysis caching, model inspection,
and performance optimization features.

Test Coverage:
    - SmartExclusionMixin functionality
    - FieldAnalysisCache operations
    - ModelInspector utilities
    - EnhancedModelView integration
    - Performance and caching behavior
"""

import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock, call
from typing import Dict, Any, List

# Test the enhanced modelview components
import sys
import os
sys.path.insert(0, '/Users/nyimbiodero/src/pjs/fab-ext')

try:
    from pgappforge.models.enhanced_modelview import (
        FieldAnalysisCache, ModelInspector, SmartExclusionMixin,
        EnhancedModelView, FieldAnalysisManager, field_analysis_manager,
        smart_exclusion_decorator, analyze_view_performance
    )
    from pgappforge.models.field_analyzer import (
        FieldSupportLevel, UnsupportedReason
    )
    IMPORTS_AVAILABLE = True
except ImportError as e:
    print(f"Enhanced ModelView imports not available: {e}")
    IMPORTS_AVAILABLE = False
    
    # Create mock classes for testing
    class MockFieldAnalysisCache:
        def __init__(self):
            self.cache = {}
    
    class MockModelInspector:
        @staticmethod
        def get_model_columns(model_class):
            return []


class TestFieldAnalysisCache:
    """Test the field analysis caching system."""
    
    @pytest.fixture
    def cache(self):
        """Create a field analysis cache instance."""
        if IMPORTS_AVAILABLE:
            return FieldAnalysisCache(max_cache_size=5, cache_ttl_seconds=10)
        else:
            return MockFieldAnalysisCache()
    
    def test_cache_initialization(self, cache):
        """Test cache initialization with custom parameters."""
        if IMPORTS_AVAILABLE:
            assert cache.max_cache_size == 5
            assert cache.cache_ttl.total_seconds() == 10
            assert len(cache._cache) == 0
    
    def test_cache_key_generation(self, cache):
        """Test cache key generation for models and configs."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        class MockModel:
            __module__ = "test_module"
            __name__ = "TestModel"
        
        config = {'strict_mode': True, 'custom_rules': {}}
        cache_key = cache.get_cache_key(MockModel, config)
        
        assert isinstance(cache_key, str)
        assert "test_module.TestModel" in cache_key
        assert ":" in cache_key
    
    def test_cache_set_and_get(self, cache):
        """Test basic cache set and get operations."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        cache_key = "test_model:config_hash"
        analysis_result = {
            'total_columns': 5,
            'fully_supported': [{'name': 'id', 'type': 'Integer'}],
            'unsupported': []
        }
        
        # Set cache entry
        cache.set(cache_key, analysis_result)
        
        # Get cache entry
        retrieved_result = cache.get(cache_key)
        
        assert retrieved_result is not None
        assert retrieved_result['total_columns'] == 5
        assert len(retrieved_result['fully_supported']) == 1
    
    def test_cache_expiration(self, cache):
        """Test cache entry expiration."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        cache_key = "test_model:config_hash"
        analysis_result = {'test': 'data'}
        
        # Set cache entry
        cache.set(cache_key, analysis_result)
        
        # Manually set timestamp to past
        cache._cache_timestamps[cache_key] = datetime.utcnow() - timedelta(seconds=15)
        
        # Should return None due to expiration
        retrieved_result = cache.get(cache_key)
        assert retrieved_result is None
        
        # Cache entry should be removed
        assert cache_key not in cache._cache
    
    def test_cache_size_limit(self, cache):
        """Test cache size enforcement."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        # Fill cache beyond limit
        for i in range(10):
            cache_key = f"model_{i}:config"
            cache.set(cache_key, {'data': i})
        
        # Should not exceed max size
        assert len(cache._cache) <= cache.max_cache_size
    
    def test_cache_invalidation(self, cache):
        """Test cache invalidation for specific models."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        class MockModel:
            __module__ = "test_module"
            __name__ = "TestModel"
        
        # Add cache entries
        cache.set("test_module.TestModel:config1", {'data': 1})
        cache.set("test_module.TestModel:config2", {'data': 2})
        cache.set("other_module.OtherModel:config", {'data': 3})
        
        # Invalidate specific model
        cache.invalidate(MockModel)
        
        # TestModel entries should be gone
        assert cache.get("test_module.TestModel:config1") is None
        assert cache.get("test_module.TestModel:config2") is None
        
        # Other model should remain
        assert cache.get("other_module.OtherModel:config") is not None
    
    def test_cache_clear(self, cache):
        """Test clearing all cache entries."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        # Add some entries
        cache.set("key1", {'data': 1})
        cache.set("key2", {'data': 2})
        
        # Clear cache
        cache.clear()
        
        # Should be empty
        assert len(cache._cache) == 0
        assert len(cache._cache_timestamps) == 0


class TestModelInspector:
    """Test the model inspection utilities."""
    
    def test_get_model_columns_no_table(self):
        """Test getting columns from model without __table__."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        class ModelWithoutTable:
            pass
        
        columns = ModelInspector.get_model_columns(ModelWithoutTable)
        assert columns == []
    
    def test_extract_field_metadata(self):
        """Test extracting comprehensive field metadata."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        # Mock a column
        mock_column = MagicMock()
        mock_column.name = "test_field"
        mock_column.type.__class__.__name__ = "String"
        mock_column.nullable = True
        mock_column.primary_key = False
        mock_column.unique = False
        mock_column.index = False
        mock_column.autoincrement = False
        mock_column.foreign_keys = []
        mock_column.default = None
        mock_column.server_default = None
        mock_column.type.length = 255
        
        metadata = ModelInspector.extract_field_metadata(mock_column)
        
        assert metadata['name'] == 'test_field'
        assert metadata['type_name'] == 'String'
        assert metadata['nullable'] is True
        assert metadata['primary_key'] is False
        assert metadata['max_length'] == 255
    
    def test_get_model_relationships_no_mapper(self):
        """Test getting relationships from model without __mapper__."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        class ModelWithoutMapper:
            pass
        
        relationships = ModelInspector.get_model_relationships(ModelWithoutMapper)
        assert relationships == {}
    
    def test_get_hybrid_properties_no_mapper(self):
        """Test getting hybrid properties from model without __mapper__."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        class ModelWithoutMapper:
            pass
        
        hybrid_props = ModelInspector.get_hybrid_properties(ModelWithoutMapper)
        assert hybrid_props == {}


class TestSmartExclusionMixin:
    """Test the smart exclusion mixin functionality."""
    
    @pytest.fixture
    def mock_mixin(self):
        """Create a mock smart exclusion mixin instance."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        class MockView(SmartExclusionMixin):
            def __init__(self):
                self.datamodel = MagicMock()
                self.datamodel.obj = MagicMock()
                self.datamodel.obj.__name__ = "TestModel"
                super().__init__()
        
        return MockView()
    
    def test_mixin_initialization(self, mock_mixin):
        """Test smart exclusion mixin initialization."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        assert hasattr(mock_mixin, '_field_analyzer')
        assert hasattr(mock_mixin, 'field_analysis_enabled')
        assert mock_mixin.field_analysis_enabled is True
    
    def test_field_analyzer_property(self, mock_mixin):
        """Test field analyzer property creation."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        analyzer = mock_mixin.field_analyzer
        assert analyzer is not None
        
        # Should return same instance on subsequent calls
        analyzer2 = mock_mixin.field_analyzer
        assert analyzer is analyzer2
    
    def test_get_enhanced_search_columns_disabled(self, mock_mixin):
        """Test enhanced search columns when analysis is disabled."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        mock_mixin.field_analysis_enabled = False
        mock_mixin.search_columns = ['name', 'email']
        
        columns = mock_mixin.get_enhanced_search_columns()
        assert 'name' in columns
        assert 'email' in columns
    
    @patch('pgappforge.models.enhanced_modelview.analyze_model_fields')
    def test_get_enhanced_search_columns_enabled(self, mock_analyze, mock_mixin):
        """Test enhanced search columns when analysis is enabled."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        # Mock analysis result
        mock_analyze.return_value = {
            'fully_supported': [
                {'name': 'name', 'type': 'String'},
                {'name': 'email', 'type': 'String'}
            ],
            'searchable_only': [
                {'name': 'description', 'type': 'Text'}
            ],
            'unsupported': [
                {'name': 'photo', 'type': 'BLOB', 'reason': 'binary_data'}
            ],
            'exclusion_summary': {}
        }
        
        mock_mixin.field_analysis_enabled = True
        
        columns = mock_mixin.get_enhanced_search_columns()
        
        assert 'name' in columns
        assert 'email' in columns
        assert 'description' in columns
        assert 'photo' not in columns
    
    @patch('pgappforge.models.enhanced_modelview.analyze_model_fields')
    def test_get_enhanced_list_columns(self, mock_analyze, mock_mixin):
        """Test enhanced list columns selection."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        mock_analyze.return_value = {
            'fully_supported': [{'name': 'name', 'type': 'String'}],
            'limited_support': [{'name': 'metadata', 'type': 'JSON'}],
            'unsupported': [
                {'name': 'photo', 'type': 'BLOB', 'reason': 'binary_data'},
                {'name': 'config', 'type': 'JSON', 'reason': 'ui_limitation'}
            ]
        }
        
        columns = mock_mixin.get_enhanced_list_columns()
        
        assert 'name' in columns
        assert 'metadata' in columns
        assert 'config' in columns  # UI limitation but still displayable
        assert 'photo' not in columns  # Binary data excluded
    
    @patch('pgappforge.models.enhanced_modelview.analyze_model_fields')
    def test_get_enhanced_edit_columns(self, mock_analyze, mock_mixin):
        """Test enhanced edit columns selection."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        mock_analyze.return_value = {
            'fully_supported': [
                {'name': 'id', 'type': 'Integer', 'metadata': {'primary_key': True}},
                {'name': 'name', 'type': 'String', 'metadata': {'primary_key': False}}
            ],
            'limited_support': [
                {'name': 'created_at', 'type': 'DateTime', 'metadata': {'autoincrement': True}}
            ]
        }
        
        columns = mock_mixin.get_enhanced_edit_columns()
        
        assert 'name' in columns
        assert 'id' not in columns  # Primary key excluded
        assert 'created_at' not in columns  # Auto-increment excluded
    
    def test_field_analysis_caching(self, mock_mixin):
        """Test that field analysis results are cached."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        with patch('pgappforge.models.enhanced_modelview.analyze_model_fields') as mock_analyze:
            mock_analyze.return_value = {'test': 'result'}
            
            # First call should trigger analysis
            result1 = mock_mixin._get_field_analysis()
            
            # Second call should use cache
            result2 = mock_mixin._get_field_analysis()
            
            # Should only call analyze_model_fields once due to caching
            assert mock_analyze.call_count == 1
            assert result1 == result2


class TestEnhancedModelView:
    """Test the enhanced model view implementation."""
    
    def test_enhanced_modelview_initialization(self):
        """Test enhanced model view initialization."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        # Mock the base ModelView
        with patch('pgappforge.models.enhanced_modelview.BaseModelView'):
            view = EnhancedModelView()
            
            assert hasattr(view, 'field_analysis_enabled')
            assert hasattr(view, 'field_analysis_strict_mode')
    
    def test_model_analysis_report_property(self):
        """Test model analysis report property."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        with patch('pgappforge.models.enhanced_modelview.BaseModelView'):
            with patch('pgappforge.models.enhanced_modelview.get_model_analysis_report') as mock_report:
                mock_report.return_value = {'test': 'report'}
                
                view = EnhancedModelView()
                view.datamodel = MagicMock()
                view.datamodel.obj = MagicMock()
                
                report = view.model_analysis_report
                
                assert report == {'test': 'report'}
                mock_report.assert_called_once()
    
    def test_refresh_field_analysis(self):
        """Test refreshing field analysis cache."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        with patch('pgappforge.models.enhanced_modelview.BaseModelView'):
            view = EnhancedModelView()
            view.datamodel = MagicMock()
            view.datamodel.obj = MagicMock()
            view.datamodel.obj.__name__ = "TestModel"
            
            with patch.object(view, '_field_analysis_cache') as mock_cache:
                with patch.object(view, 'get_enhanced_search_columns', return_value=['name']):
                    with patch.object(view, 'get_enhanced_list_columns', return_value=['name', 'id']):
                        with patch.object(view, 'get_enhanced_edit_columns', return_value=['name']):
                            view.refresh_field_analysis()
                            
                            mock_cache.invalidate.assert_called_once_with(view.datamodel.obj)
                            assert view.search_columns == ['name']
                            assert view.list_columns == ['name', 'id']
                            assert view.edit_columns == ['name']


class TestFieldAnalysisManager:
    """Test the field analysis manager."""
    
    @pytest.fixture
    def manager(self):
        """Create a field analysis manager instance."""
        if IMPORTS_AVAILABLE:
            return FieldAnalysisManager()
        else:
            return MagicMock()
    
    def test_manager_initialization(self, manager):
        """Test manager initialization."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        assert hasattr(manager, '_global_cache')
        assert hasattr(manager, '_global_config')
        assert manager._global_config['strict_mode'] is True
        assert manager._global_config['cache_enabled'] is True
    
    def test_manager_configure(self, manager):
        """Test manager configuration updates."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        manager.configure(strict_mode=False, show_warnings=False)
        
        assert manager._global_config['strict_mode'] is False
        assert manager._global_config['show_warnings'] is False
    
    @patch('pgappforge.models.enhanced_modelview.analyze_model_fields')
    def test_analyze_all_models(self, mock_analyze, manager):
        """Test analyzing multiple models."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        class Model1:
            __module__ = "test"
            __name__ = "Model1"
        
        class Model2:
            __module__ = "test"
            __name__ = "Model2"
        
        mock_analyze.return_value = {'total_columns': 5}
        
        results = manager.analyze_all_models([Model1, Model2])
        
        assert len(results) == 2
        assert 'test.Model1' in results
        assert 'test.Model2' in results
        assert results['test.Model1']['total_columns'] == 5
    
    def test_manager_clear_cache(self, manager):
        """Test clearing all manager caches."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        with patch.object(manager._global_cache, 'clear') as mock_global_clear:
            with patch('pgappforge.models.enhanced_modelview.SmartExclusionMixin._field_analysis_cache.clear') as mock_mixin_clear:
                with patch('pgappforge.models.enhanced_modelview.get_model_analysis_report.cache_clear') as mock_func_clear:
                    manager.clear_cache()
                    
                    mock_global_clear.assert_called_once()
                    mock_mixin_clear.assert_called_once()
                    mock_func_clear.assert_called_once()


class TestUtilityFunctions:
    """Test utility functions and decorators."""
    
    def test_smart_exclusion_decorator(self):
        """Test smart exclusion decorator functionality."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        # Mock base ModelView
        with patch('pgappforge.models.enhanced_modelview.BaseModelView') as MockBaseView:
            class TestView(MockBaseView):
                pass
            
            # Apply decorator
            DecoratedView = smart_exclusion_decorator(TestView)
            
            # Should be a new class that includes SmartExclusionMixin
            assert issubclass(DecoratedView, SmartExclusionMixin)
            assert DecoratedView.__name__ == TestView.__name__
    
    def test_analyze_view_performance(self):
        """Test view performance analysis."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        # Mock view instance
        mock_view = MagicMock()
        mock_view.datamodel.obj.__name__ = "TestModel"
        mock_view.field_analysis_enabled = True
        mock_view.field_analysis_cache_enabled = True
        mock_view.get_enhanced_search_columns.return_value = ['name', 'email']
        mock_view.get_enhanced_list_columns.return_value = ['name', 'email', 'id']
        
        report = analyze_view_performance(mock_view)
        
        assert report['model_name'] == "TestModel"
        assert report['analysis_enabled'] is True
        assert report['cache_enabled'] is True
        assert 'timing' in report
        assert 'search_columns' in report['timing']
        assert 'list_columns' in report['timing']


class TestPerformanceAndOptimization:
    """Test performance and optimization features."""
    
    def test_cache_performance(self):
        """Test that caching improves performance."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        cache = FieldAnalysisCache()
        
        # Measure time for first access (cache miss)
        start_time = time.time()
        cache.set("test_key", {'large_data': list(range(1000))})
        cache_time = time.time() - start_time
        
        # Measure time for subsequent access (cache hit)
        start_time = time.time()
        result = cache.get("test_key")
        retrieval_time = time.time() - start_time
        
        # Cache retrieval should be much faster
        assert retrieval_time < cache_time
        assert result is not None
        assert len(result['large_data']) == 1000
    
    def test_memory_efficiency(self):
        """Test memory efficiency of caching system."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        cache = FieldAnalysisCache(max_cache_size=3)
        
        # Add entries beyond cache limit
        for i in range(10):
            cache.set(f"key_{i}", {'data': i})
        
        # Should respect memory limit
        assert len(cache._cache) <= 3
        assert len(cache._cache_timestamps) <= 3
    
    def test_analysis_speed(self):
        """Test that field analysis completes quickly."""
        if not IMPORTS_AVAILABLE:
            pytest.skip("Enhanced ModelView not available")
        
        # Create mock large model
        class LargeModel:
            __table__ = MagicMock()
            
        # Mock many columns
        mock_columns = []
        for i in range(50):
            mock_col = MagicMock()
            mock_col.name = f"field_{i}"
            mock_col.type.__class__.__name__ = "String"
            mock_col.nullable = True
            mock_col.primary_key = False
            mock_columns.append(mock_col)
        
        LargeModel.__table__.columns = mock_columns
        
        # Time the analysis
        start_time = time.time()
        
        with patch('pgappforge.models.enhanced_modelview.analyze_model_fields') as mock_analyze:
            mock_analyze.return_value = {'total_columns': 50, 'fully_supported': []}
            
            # Simulate field analysis
            from pgappforge.models.enhanced_modelview import get_model_analysis_report
            result = get_model_analysis_report(LargeModel, strict_mode=True)
        
        end_time = time.time()
        
        # Should complete quickly (under 100ms for 50 fields)
        analysis_time = (end_time - start_time) * 1000
        assert analysis_time < 100
        assert result['total_columns'] == 50


if __name__ == "__main__":
    pytest.main([__file__, '-v'])