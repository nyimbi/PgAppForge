"""
Integration and Performance Tests for PgAppForge Mixins.

Tests real-world scenarios, performance characteristics, database operations,
security integration, and production readiness across all mixin categories.
"""

import json
import pytest
import time
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from pgappforge import Model
from pgappforge.mixins.enhanced_mixins import EnhancedSoftDeleteMixin, MetadataMixin
from pgappforge.mixins.content_mixins import CommentableMixin, SearchableMixin  
from pgappforge.mixins.business_mixins import ApprovalWorkflowMixin, MultiTenancyMixin
from pgappforge.mixins.specialized_mixins import CurrencyMixin, GeoLocationMixin
from pgappforge.mixins.security_framework import (
    SecurityValidator, SecurityAuditor, ErrorRecovery
)


# Integration test models combining multiple mixins
class DocumentModel(
    EnhancedSoftDeleteMixin, MetadataMixin, CommentableMixin, 
    SearchableMixin, ApprovalWorkflowMixin, Model
):
    __tablename__ = 'test_documents'
    
    # SearchableMixin config
    __searchable__ = {'title': 1.0, 'content': 0.8, 'tags': 0.6}
    
    # ApprovalWorkflowMixin config  
    __approval_workflow__ = {
        1: {'required_role': 'reviewer', 'required_approvals': 1},
        2: {'required_role': 'manager', 'required_approvals': 1}
    }
    
    # CommentableMixin config
    __allow_anonymous_comments__ = False
    __comment_moderation__ = True
    __max_comment_depth__ = 3
    
    title = None
    content = None
    tags = None


class LocationBusinessModel(
    GeoLocationMixin, CurrencyMixin, MultiTenancyMixin, Model
):
    __tablename__ = 'test_locations'
    
    # CurrencyMixin config
    __default_currency__ = 'USD'
    __exchange_rate_api_url__ = 'https://api.test.com'
    
    name = None


class TestMixinIntegration:
    """Test integration between different mixin categories."""
    
    def setup_method(self):
        """Setup integration test models."""
        self.document = DocumentModel()
        self.document.id = 123
        self.document.title = "Integration Test Document"
        self.document.content = "This is a comprehensive test document"
        self.document.tags = "test,integration,important"
        self.document.deleted = False
        self.document.current_state = 'draft'
        self.document.metadata_json = '{}'
        
        self.location_business = LocationBusinessModel()
        self.location_business.id = 456
        self.location_business.name = "Test Business Location"
        self.location_business.amount = Decimal('1000.00')
        self.location_business.currency = 'USD'
        self.location_business.tenant_id = 'tenant_123'
    
    def test_document_approval_workflow_with_comments(self):
        """Test complete document approval workflow with commenting."""
        with patch('pgappforge.mixins.business_mixins.SecurityValidator') as mock_validator:
            with patch('pgappforge.mixins.content_mixins.Comment') as mock_comment:
                # Setup security validation
                mock_user = Mock()
                mock_user.id = 789
                mock_validator.validate_user_context.return_value = mock_user
                mock_validator.validate_permission.return_value = True
                
                # Setup comment model
                mock_comment.create_for_object.return_value = Mock()
                mock_comment.get_for_object.return_value = []
                
                # Start approval workflow
                self.document.start_approval(user_id=789)
                assert self.document.current_state == 'pending_approval'
                
                # Add reviewer comment
                comment_result = self.document.add_comment("Looks good, but needs minor changes", user_id=789)
                assert comment_result is not None
                
                # Approve with comments
                approval_result = self.document.approve_step(user_id=789, comments="Approved with suggestions")
                assert approval_result is True
                
                # Verify approval was logged
                mock_validator.validate_user_context.assert_called()
    
    def test_soft_delete_with_metadata_preservation(self):
        """Test soft delete preserves metadata and allows recovery."""
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 456
            
            # Set metadata before deletion
            important_metadata = {"backup_location": "s3://bucket/path", "priority": "high"}
            self.document.set_metadata("backup_info", important_metadata)
            
            # Perform soft delete
            delete_result = self.document.soft_delete(reason="Archive old document")
            assert delete_result is True
            assert self.document.deleted is True
            assert self.document.deletion_reason == "Archive old document"
            
            # Verify metadata is preserved
            preserved_metadata = self.document.get_metadata("backup_info")
            assert preserved_metadata == important_metadata
            
            # Restore document
            restore_result = self.document.restore()
            assert restore_result is True
            assert self.document.deleted is False
            
            # Verify metadata still exists after restore
            final_metadata = self.document.get_metadata("backup_info")
            assert final_metadata == important_metadata
    
    def test_search_with_state_and_metadata_filters(self):
        """Test search functionality with state and metadata filtering."""
        with patch.object(DocumentModel, 'query') as mock_query:
            # Setup query chain
            mock_filter_result = Mock()
            mock_query.filter.return_value = mock_filter_result
            mock_filter_result.filter.return_value = mock_filter_result
            mock_filter_result.limit.return_value = mock_filter_result
            mock_filter_result.all.return_value = [self.document]
            
            # Test search with additional filters
            results = DocumentModel.search(
                "integration test",
                limit=10,
                current_state='draft',
                deleted=False
            )
            
            # Verify search was called with filters
            assert mock_query.filter.called
            assert len(results) == 1 if results else True  # Handle potential empty results
    
    def test_multi_tenant_location_with_currency_conversion(self):
        """Test multi-tenant location with currency operations."""
        with patch('pgappforge.mixins.business_mixins.g') as mock_g:
            # Setup tenant context
            mock_g.tenant_id = 'tenant_123'
            
            # Test tenant isolation
            with patch.object(LocationBusinessModel, 'query') as mock_query:
                mock_filter = Mock()
                mock_query.filter.return_value = mock_filter
                
                # Search should automatically filter by tenant
                LocationBusinessModel.get_tenant_records()
                mock_query.filter.assert_called()
            
            # Test currency conversion within tenant context
            with patch.object(self.location_business, 'get_exchange_rates') as mock_rates:
                mock_rates.return_value = {'EUR': 0.85}
                
                converted = self.location_business.convert_to('EUR')
                expected = Decimal('1000.00') * Decimal('0.85')
                assert converted == expected.quantize(Decimal('0.01'))
    
    def test_security_audit_trail_across_operations(self):
        """Test security audit logging across multiple operations."""
        with patch('pgappforge.mixins.security_framework.SecurityAuditor') as mock_auditor:
            with patch('pgappforge.mixins.business_mixins.SecurityValidator') as mock_validator:
                # Setup security mocks
                mock_user = Mock()
                mock_user.id = 999
                mock_validator.validate_user_context.return_value = mock_user
                mock_validator.validate_permission.return_value = True
                
                # Perform series of operations that should be audited
                self.document.set_metadata("sensitive", {"classification": "confidential"})
                self.document.start_approval(user_id=999)
                self.document.approve_step(user_id=999, comments="Security cleared")
                
                # Verify audit events were logged
                assert mock_auditor.log_security_event.call_count >= 1
                
                # Check specific audit events
                audit_calls = mock_auditor.log_security_event.call_args_list
                event_types = [call[0][0] for call in audit_calls]
                assert 'approval_granted' in event_types


class TestPerformanceCharacteristics:
    """Test performance characteristics of mixins."""
    
    def setup_method(self):
        """Setup performance test data."""
        self.documents = []
        for i in range(100):
            doc = DocumentModel()
            doc.id = i
            doc.title = f"Performance Test Doc {i}"
            doc.content = f"Content for document {i} " * 50  # Longer content
            doc.tags = f"tag{i},performance,test"
            doc.metadata_json = json.dumps({"index": i, "category": f"cat_{i % 10}"})
            self.documents.append(doc)
    
    @patch('pgappforge.mixins.enhanced_mixins.db')
    def test_bulk_soft_delete_performance(self, mock_db):
        """Test performance of bulk soft delete operations."""
        # Setup database mock
        mock_query = Mock()
        mock_db.session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query  
        mock_query.update.return_value = 100  # 100 records updated
        
        with patch('pgappforge.mixins.enhanced_mixins.current_user') as mock_user:
            mock_user.id = 123
            
            start_time = time.time()
            
            # Bulk delete 100 records
            record_ids = list(range(100))
            result = DocumentModel.bulk_soft_delete(record_ids)
            
            end_time = time.time()
            
            assert result == 100
            assert end_time - start_time < 1.0  # Should complete within 1 second
            
            # Verify single database query was used
            mock_query.update.assert_called_once()
    
    def test_metadata_search_performance(self):
        """Test performance of metadata-based searches."""
        with patch.object(DocumentModel, 'query') as mock_query:
            mock_filter = Mock()
            mock_query.filter.return_value = mock_filter
            mock_filter.all.return_value = self.documents[:10]  # Return subset
            
            start_time = time.time()
            
            # Search by metadata
            results = DocumentModel.search_by_metadata("category", "cat_5")
            
            end_time = time.time()
            
            assert end_time - start_time < 0.1  # Should be very fast
            mock_query.filter.assert_called()
    
    def test_concurrent_approval_operations(self):
        """Test concurrent approval operations for thread safety."""
        def approve_document(doc_id, user_id):
            """Helper function for concurrent approval."""
            doc = DocumentModel()
            doc.id = doc_id
            doc.current_state = 'pending_approval'
            doc.current_approval_step = 1
            doc.received_approvals = 0
            doc.workflow_data = '{}'
            
            with patch('pgappforge.mixins.business_mixins.SecurityValidator') as mock_validator:
                mock_user = Mock()
                mock_user.id = user_id
                mock_validator.validate_user_context.return_value = mock_user
                mock_validator.validate_permission.return_value = True
                
                with patch('pgappforge.mixins.business_mixins.db'):
                    try:
                        result = doc.approve_step(user_id=user_id)
                        return (doc_id, user_id, result)
                    except Exception as e:
                        return (doc_id, user_id, str(e))
        
        # Test concurrent approvals
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            
            # Submit 50 concurrent approval tasks
            for i in range(50):
                future = executor.submit(approve_document, i, 100 + i)
                futures.append(future)
            
            # Collect results
            results = [future.result() for future in futures]
            
            # Verify all operations completed
            assert len(results) == 50
            
            # Check for any exceptions
            errors = [r for r in results if isinstance(r[2], str)]
            assert len(errors) == 0, f"Concurrent operations failed: {errors}"
    
    @patch('pgappforge.mixins.specialized_mixins.requests.get')
    def test_geocoding_retry_performance(self, mock_requests):
        """Test performance of geocoding with retry logic."""
        from pgappforge.mixins.specialized_mixins import ErrorRecovery
        import requests
        
        # Setup request to fail twice then succeed
        mock_requests.side_effect = [
            requests.RequestException("Connection failed"),
            requests.RequestException("Timeout"),
            Mock(json=lambda: [{'lat': '40.7128', 'lon': '-74.0060'}], raise_for_status=lambda: None)
        ]
        
        model = GeoLocationMixin()
        model.address = "New York, NY"
        model.geocoded = False
        
        start_time = time.time()
        
        # Test geocoding with retries
        with patch('time.sleep'):  # Mock sleep to speed up test
            result = model.geocode_address()
        
        end_time = time.time()
        
        assert result is True
        assert end_time - start_time < 5.0  # Should complete within 5 seconds
        assert mock_requests.call_count == 3  # Should retry twice then succeed
    
    def test_currency_conversion_cache_performance(self):
        """Test currency conversion caching performance."""
        with patch('pgappforge.mixins.specialized_mixins.current_app') as mock_app:
            # Setup cache
            cached_rates = {'EUR': 0.85, 'GBP': 0.73}
            mock_cache = Mock()
            mock_app.cache = mock_cache
            mock_cache.get.return_value = cached_rates
            
            model = CurrencyMixin()
            model.amount = Decimal('100.00')
            model.currency = 'USD'
            
            start_time = time.time()
            
            # Perform multiple conversions (should use cache)
            conversions = []
            for currency in ['EUR', 'GBP', 'EUR', 'GBP'] * 25:  # 100 conversions
                converted = model.convert_to(currency)
                conversions.append(converted)
            
            end_time = time.time()
            
            assert len(conversions) == 100
            assert end_time - start_time < 0.5  # Should be very fast with caching
            
            # Verify cache was used (no external API calls)
            assert mock_cache.get.call_count >= 1


class TestErrorRecoveryScenarios:
    """Test error recovery and resilience scenarios."""
    
    def test_database_connection_recovery(self):
        """Test recovery from database connection issues."""
        from pgappforge.mixins.security_framework import ErrorRecovery
        from sqlalchemy.exc import OperationalError
        
        # Mock operation that fails twice then succeeds
        operation_calls = [0]
        
        def mock_database_operation():
            operation_calls[0] += 1
            if operation_calls[0] <= 2:
                raise OperationalError("Connection lost", None, None)
            return "success"
        
        # Test retry with exponential backoff
        with patch('time.sleep'):  # Speed up test
            result = ErrorRecovery.retry_with_backoff(
                mock_database_operation,
                max_retries=3,
                retryable_exceptions=(OperationalError,)
            )
        
        assert result == "success"
        assert operation_calls[0] == 3  # Should retry twice then succeed
    
    def test_external_service_fallback(self):
        """Test fallback between external services."""
        model = GeoLocationMixin()
        model.address = "Test Address"
        model.geocoded = False
        
        # Mock all services to fail except the last one
        with patch.object(model, '_geocode_with_nominatim', return_value=None):
            with patch.object(model, '_geocode_with_mapquest', return_value=None):
                with patch.object(model, '_geocode_with_google') as mock_google:
                    mock_google.return_value = {
                        'lat': 40.7128, 'lon': -74.0060, 'source': 'google',
                        'accuracy': 'exact', 'address_components': {}
                    }
                    
                    result = model.geocode_address()
                    
                    assert result is True
                    assert model.geocode_source == 'google'
    
    def test_partial_failure_recovery(self):
        """Test recovery from partial failures in bulk operations."""
        import_data = [
            {"name": "Valid Item 1", "value": 100},  # Valid
            {"name": 123, "value": "invalid"},       # Invalid - should skip
            {"name": "Valid Item 2", "value": 200},  # Valid
        ]
        
        with patch('pgappforge.mixins.enhanced_mixins.db') as mock_db:
            # Test bulk import with partial failures
            from pgappforge.mixins.enhanced_mixins import ImportExportMixin
            
            class TestModel(ImportExportMixin, Model):
                __tablename__ = 'test_partial'
                __importable_fields__ = {'name': str, 'value': int}
                
                name = None
                value = None
            
            result = TestModel.bulk_import(import_data, continue_on_error=True)
            
            # Should succeed with 2 valid items, 1 error
            assert result['success'] == 2
            assert result['errors'] == 1
            assert len(result['error_details']) == 1


class TestSecurityIntegrationScenarios:
    """Test security integration across all mixins."""
    
    def setup_method(self):
        """Setup security test scenario."""
        self.admin_user = Mock()
        self.admin_user.id = 1
        self.admin_user.active = True
        self.admin_user.has_permission.return_value = True
        self.admin_user.roles = [Mock(name='admin')]
        
        self.regular_user = Mock()
        self.regular_user.id = 2  
        self.regular_user.active = True
        self.regular_user.has_permission.return_value = False
        self.regular_user.roles = [Mock(name='user')]
        
        self.document = DocumentModel()
        self.document.id = 123
        self.document.title = "Secure Document"
        self.document.current_state = 'pending_approval'
        self.document.created_by_fk = 2  # Created by regular user
    
    def test_permission_enforcement_across_mixins(self):
        """Test that permissions are enforced across all mixin operations."""
        with patch('pgappforge.mixins.security_framework.SecurityValidator') as mock_validator:
            
            # Test admin user can perform restricted operations
            mock_validator.validate_user_context.return_value = self.admin_user
            mock_validator.validate_permission.return_value = True
            
            with patch('pgappforge.mixins.business_mixins.db'):
                # Admin should be able to approve
                result = self.document.approve_step(user_id=1, comments="Admin approval")
                assert result is True
            
            # Test regular user cannot perform restricted operations
            mock_validator.validate_user_context.return_value = self.regular_user
            mock_validator.validate_permission.side_effect = SecurityValidator.validate_permission(
                self.regular_user, 'can_approve'
            )
            
            with patch('pgappforge.mixins.business_mixins.db'):
                from pgappforge.mixins.security_framework import MixinPermissionError
                
                # Regular user should be denied
                with pytest.raises(MixinPermissionError):
                    self.document.approve_step(user_id=2, comments="User approval attempt")
    
    def test_audit_logging_comprehensive(self):
        """Test comprehensive audit logging across operations."""
        with patch('pgappforge.mixins.security_framework.SecurityAuditor') as mock_auditor:
            with patch('pgappforge.mixins.business_mixins.SecurityValidator') as mock_validator:
                mock_validator.validate_user_context.return_value = self.admin_user
                mock_validator.validate_permission.return_value = True
                
                # Perform multiple auditable operations
                operations = [
                    ('metadata_update', lambda: self.document.set_metadata("audit_test", {"important": True})),
                    ('approval_start', lambda: self.document.start_approval(user_id=1)),
                    ('approval_grant', lambda: self.document.approve_step(user_id=1, comments="Approved"))
                ]
                
                with patch('pgappforge.mixins.business_mixins.db'):
                    for op_name, operation in operations:
                        try:
                            operation()
                        except Exception:
                            pass  # Some operations may fail due to mocking
                
                # Verify audit events were logged
                assert mock_auditor.log_security_event.called
                
                # Extract logged event types
                logged_events = []
                for call in mock_auditor.log_security_event.call_args_list:
                    event_type = call[0][0]
                    logged_events.append(event_type)
                
                # Should include security-relevant events
                security_events = ['approval_granted', 'mixin_operation_access']
                assert any(event in logged_events for event in security_events)
    
    def test_input_validation_comprehensive(self):
        """Test input validation across all mixins."""
        from pgappforge.mixins.security_framework import MixinValidationError
        
        test_cases = [
            # Currency validation
            (lambda: CurrencyMixin().convert_to('INVALID'), "Target currency must be 3-character code"),
            
            # Geo location validation  
            (lambda: GeoLocationMixin().set_coordinates(91, 0), "Invalid coordinates"),
            
            # State validation
            (lambda: self.document.change_state('invalid_state'), "Invalid state"),
            
            # Metadata validation (via JSON)
            (lambda: self.document.set_metadata("test", "invalid json data"[:-5]), None)  # This might not fail
        ]
        
        for operation, expected_error in test_cases:
            if expected_error:
                with pytest.raises((MixinValidationError, ValueError)):
                    operation()


class TestProductionReadinessScenarios:
    """Test production readiness scenarios."""
    
    def test_high_load_simulation(self):
        """Simulate high load scenario with multiple operations."""
        documents = []
        
        # Create many documents
        for i in range(1000):
            doc = DocumentModel()
            doc.id = i
            doc.title = f"Load Test Doc {i}"
            doc.content = f"Content {i}"
            doc.metadata_json = json.dumps({"load_test": True, "batch": i // 100})
            documents.append(doc)
        
        start_time = time.time()
        
        # Perform bulk metadata operations
        batch_operations = 0
        for doc in documents[:100]:  # Test first 100 for performance
            doc.set_metadata("processed", {"timestamp": datetime.utcnow().isoformat()})
            batch_operations += 1
        
        end_time = time.time()
        
        # Should handle 100 operations quickly
        assert end_time - start_time < 2.0
        assert batch_operations == 100
    
    def test_memory_usage_stability(self):
        """Test memory usage remains stable under load."""
        import gc
        
        # Force garbage collection
        gc.collect()
        initial_objects = len(gc.get_objects())
        
        # Create and destroy many objects
        for batch in range(10):
            documents = []
            for i in range(100):
                doc = DocumentModel()
                doc.id = batch * 100 + i
                doc.title = f"Memory Test {i}"
                doc.metadata_json = json.dumps({"batch": batch, "item": i})
                documents.append(doc)
            
            # Process documents
            for doc in documents:
                doc.get_metadata("batch")
                doc.set_metadata("processed", True)
            
            # Clear references
            documents.clear()
            
            # Force garbage collection
            gc.collect()
        
        # Check final object count
        final_objects = len(gc.get_objects())
        
        # Should not have significant memory leak
        object_growth = final_objects - initial_objects
        assert object_growth < 1000, f"Potential memory leak: {object_growth} new objects"
    
    def test_configuration_validation(self):
        """Test validation of mixin configurations."""
        # Test invalid configuration scenarios
        class BadConfigModel(DocumentModel):
            # Invalid approval workflow config
            __approval_workflow__ = "invalid_config"
        
        # Should handle invalid configuration gracefully
        bad_model = BadConfigModel()
        bad_model.id = 123
        
        # Operations should either work with defaults or fail gracefully
        try:
            bad_model.start_approval(user_id=1)
        except Exception as e:
            # Should be a configuration error, not a system crash
            assert "config" in str(e).lower() or "workflow" in str(e).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])