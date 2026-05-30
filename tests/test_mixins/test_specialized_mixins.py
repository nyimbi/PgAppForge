"""
Comprehensive tests for specialized mixins.

Tests CurrencyMixin, GeoLocationMixin, EncryptionMixin, and VersioningMixin
with full coverage including external service integrations, security, and
error handling scenarios.
"""

import json
import pytest
from decimal import Decimal
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock
from cryptography.fernet import Fernet

from pgappforge import Model
from pgappforge.mixins.specialized_mixins import (
    CurrencyMixin, GeoLocationMixin, EncryptionMixin, VersioningMixin
)
from pgappforge.mixins.security_framework import (
    MixinExternalServiceError, MixinValidationError, MixinDataError,
    MixinConfigurationError
)


# Test models for testing mixins
class TestCurrencyModel(CurrencyMixin, Model):
    __tablename__ = 'test_currency'
    
    # Currency mixin configuration
    __default_currency__ = 'USD'
    __exchange_rate_api_url__ = 'https://api.exchangeratesapi.io/v1/latest'
    __exchange_rate_api_key__ = 'test_key'
    
    name = None


class TestGeoLocationModel(GeoLocationMixin, Model):
    __tablename__ = 'test_geolocation'
    
    name = None


class TestEncryptionModel(EncryptionMixin, Model):
    __tablename__ = 'test_encryption'
    
    name = None


class TestVersioningModel(VersioningMixin, Model):
    __tablename__ = 'test_versioning'
    
    name = None
    content = None


class TestCurrencyMixin:
    """Test CurrencyMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestCurrencyModel()
        self.model.amount = Decimal('100.00')
        self.model.currency = 'USD'
    
    @patch('pgappforge.mixins.specialized_mixins.requests.get')
    @patch('pgappforge.mixins.specialized_mixins.current_app')
    def test_get_exchange_rates_success(self, mock_app, mock_requests):
        """Test successful exchange rate fetching."""
        # Setup mocks
        mock_app.cache = Mock()
        mock_app.cache.get.return_value = None  # No cached data
        
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'rates': {'EUR': 0.85, 'GBP': 0.73, 'JPY': 110.0}
        }
        mock_requests.return_value = mock_response
        
        # Test rate fetching
        rates = self.model.get_exchange_rates('USD')
        
        assert 'EUR' in rates
        assert 'GBP' in rates
        assert 'JPY' in rates
        assert rates['EUR'] == 0.85
        
        # Verify caching
        mock_app.cache.set.assert_called_once()
    
    @patch('pgappforge.mixins.specialized_mixins.requests.get')
    def test_get_exchange_rates_api_failure(self, mock_requests):
        """Test exchange rate API failure handling."""
        # Setup request failure
        mock_requests.side_effect = Exception("API unavailable")
        
        # Should raise MixinExternalServiceError
        with pytest.raises(MixinExternalServiceError) as exc_info:
            self.model.get_exchange_rates('USD')
        
        assert "Exchange rate service error" in str(exc_info.value)
        assert exc_info.value.service == "exchange_rate_api"
    
    def test_get_exchange_rates_invalid_currency(self):
        """Test exchange rate fetch with invalid currency code."""
        with pytest.raises(MixinValidationError) as exc_info:
            self.model.get_exchange_rates('INVALID')
        
        assert "Currency code must be 3-character string" in str(exc_info.value)
        assert exc_info.value.field == "base_currency"
    
    @patch.object(TestCurrencyModel, 'get_exchange_rates')
    def test_convert_to_success(self, mock_get_rates):
        """Test successful currency conversion."""
        # Setup exchange rates
        mock_get_rates.return_value = {'EUR': 0.85, 'GBP': 0.73}
        
        # Test conversion
        result = self.model.convert_to('EUR', round_digits=2)
        
        expected = Decimal('100.00') * Decimal('0.85')
        assert result == expected.quantize(Decimal('0.01'))
        mock_get_rates.assert_called_once_with('USD')
    
    def test_convert_to_same_currency(self):
        """Test conversion to same currency."""
        result = self.model.convert_to('USD')
        
        assert result == self.model.amount
    
    def test_convert_to_missing_amount(self):
        """Test conversion with missing amount."""
        self.model.amount = None
        
        with pytest.raises(MixinDataError) as exc_info:
            self.model.convert_to('EUR')
        
        assert "amount is not set" in str(exc_info.value)
    
    def test_convert_to_invalid_target_currency(self):
        """Test conversion with invalid target currency."""
        with pytest.raises(MixinValidationError) as exc_info:
            self.model.convert_to('XY')  # Only 2 characters
        
        assert "Target currency must be 3-character code" in str(exc_info.value)
        assert exc_info.value.field == "target_currency"
    
    @patch.object(TestCurrencyModel, 'get_exchange_rates')
    def test_convert_to_unavailable_currency(self, mock_get_rates):
        """Test conversion to unavailable currency."""
        # Setup exchange rates without target currency
        mock_get_rates.return_value = {'EUR': 0.85, 'GBP': 0.73}
        
        with pytest.raises(MixinDataError) as exc_info:
            self.model.convert_to('JPY')
        
        assert "Exchange rate not available for JPY" in str(exc_info.value)
    
    def test_convert_to_invalid_round_digits(self):
        """Test conversion with invalid round digits."""
        with pytest.raises(MixinValidationError) as exc_info:
            self.model.convert_to('EUR', round_digits=-1)
        
        assert "Round digits must be integer between 0 and 10" in str(exc_info.value)
    
    def test_format_amount_basic(self):
        """Test basic amount formatting."""
        result = self.model.format_amount()
        
        # Should format with currency symbol
        assert 'USD' in result or '$' in result
        assert '100' in result
    
    def test_get_supported_currencies(self):
        """Test getting list of supported currencies."""
        currencies = TestCurrencyModel.get_supported_currencies()
        
        assert isinstance(currencies, list)
        assert 'USD' in currencies
        assert 'EUR' in currencies
        assert 'GBP' in currencies
        assert len(currencies) > 10  # Should have many currencies


class TestGeoLocationMixin:
    """Test GeoLocationMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestGeoLocationModel()
        self.model.latitude = None
        self.model.longitude = None
        self.model.address = "1600 Amphitheatre Parkway, Mountain View, CA"
        self.model.geocoded = False
    
    def test_set_coordinates_valid(self):
        """Test setting valid coordinates."""
        self.model.set_coordinates(37.4419, -122.1430, accuracy='exact')
        
        assert self.model.latitude == 37.4419
        assert self.model.longitude == -122.1430
        assert self.model.geocoded is True
        assert self.model.geocode_accuracy == 'exact'
        assert self.model.geocode_source == 'manual'
    
    def test_set_coordinates_invalid_latitude(self):
        """Test setting invalid latitude."""
        with pytest.raises(ValueError) as exc_info:
            self.model.set_coordinates(91.0, -122.0)  # Latitude > 90
        
        assert "Invalid coordinates" in str(exc_info.value)
    
    def test_set_coordinates_invalid_longitude(self):
        """Test setting invalid longitude."""
        with pytest.raises(ValueError):
            self.model.set_coordinates(37.0, 181.0)  # Longitude > 180
    
    def test_validate_coordinates_valid(self):
        """Test coordinate validation."""
        assert self.model._validate_coordinates(0, 0) is True
        assert self.model._validate_coordinates(90, 180) is True
        assert self.model._validate_coordinates(-90, -180) is True
        assert self.model._validate_coordinates(37.4419, -122.1430) is True
    
    def test_validate_coordinates_invalid(self):
        """Test invalid coordinate validation."""
        assert self.model._validate_coordinates(91, 0) is False
        assert self.model._validate_coordinates(-91, 0) is False
        assert self.model._validate_coordinates(0, 181) is False
        assert self.model._validate_coordinates(0, -181) is False
    
    @patch('pgappforge.mixins.specialized_mixins.requests.get')
    @patch('time.sleep')  # Mock sleep to speed up tests
    def test_geocode_with_nominatim_success(self, mock_sleep, mock_requests):
        """Test successful geocoding with Nominatim."""
        # Setup mock response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = [{
            'lat': '37.4419',
            'lon': '-122.1430',
            'class': 'place',
            'type': 'house',
            'address': {
                'city': 'Mountain View',
                'state': 'California',
                'country': 'United States',
                'postcode': '94043'
            }
        }]
        mock_requests.return_value = mock_response
        
        # Test geocoding
        result = self.model.geocode_address()
        
        assert result is True
        assert self.model.latitude == 37.4419
        assert self.model.longitude == -122.1430
        assert self.model.geocoded is True
        assert self.model.geocode_source == 'nominatim'
        assert self.model.city == 'Mountain View'
        assert self.model.state == 'California'
    
    @patch('pgappforge.mixins.specialized_mixins.requests.get')
    @patch('time.sleep')
    def test_geocode_nominatim_no_results(self, mock_sleep, mock_requests):
        """Test geocoding with no results from Nominatim."""
        # Setup mock response with empty results
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = []
        mock_requests.return_value = mock_response
        
        # Mock other providers to fail so we test the fallback chain
        with patch.object(self.model, '_geocode_with_mapquest', return_value=None):
            with patch.object(self.model, '_geocode_with_google', return_value=None):
                result = self.model.geocode_address()
        
        assert result is False
        assert self.model.geocoded is False
    
    def test_geocode_already_geocoded(self):
        """Test geocoding when already geocoded."""
        self.model.geocoded = True
        
        result = self.model.geocode_address()
        
        assert result is True  # Should return True without re-geocoding
    
    def test_geocode_force_regeocode(self):
        """Test forcing re-geocoding."""
        self.model.geocoded = True
        
        with patch.object(self.model, '_geocode_with_nominatim') as mock_nominatim:
            mock_nominatim.return_value = {
                'lat': 40.7128, 'lon': -74.0060, 'source': 'nominatim',
                'accuracy': 'exact', 'address_components': {}
            }
            
            result = self.model.geocode_address(force=True)
            
            assert result is True
            mock_nominatim.assert_called_once()
    
    def test_geocode_no_address(self):
        """Test geocoding without address."""
        self.model.address = None
        
        result = self.model.geocode_address()
        
        assert result is False
    
    @patch('pgappforge.mixins.specialized_mixins.requests.get')
    @patch('time.sleep')
    def test_reverse_geocode_success(self, mock_sleep, mock_requests):
        """Test successful reverse geocoding."""
        # Setup coordinates
        self.model.latitude = 37.4419
        self.model.longitude = -122.1430
        
        # Setup mock response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            'display_name': '1600 Amphitheatre Parkway, Mountain View, CA 94043, USA',
            'address': {
                'city': 'Mountain View',
                'state': 'California',
                'country': 'United States',
                'postcode': '94043'
            }
        }
        mock_requests.return_value = mock_response
        
        # Test reverse geocoding
        result = self.model.reverse_geocode()
        
        assert result is not None
        assert 'address' in result
        assert result['city'] == 'Mountain View'
        assert self.model.address is not None  # Should update address
        assert self.model.city == 'Mountain View'
    
    def test_reverse_geocode_no_coordinates(self):
        """Test reverse geocoding without coordinates."""
        self.model.latitude = None
        self.model.longitude = None
        
        result = self.model.reverse_geocode()
        
        assert result is None
    
    def test_distance_to_calculation(self):
        """Test distance calculation between two points."""
        # Setup two points
        self.model.latitude = 40.7128  # New York
        self.model.longitude = -74.0060
        
        other_model = TestGeoLocationModel()
        other_model.latitude = 34.0522  # Los Angeles
        other_model.longitude = -118.2437
        
        # Test distance calculation
        distance_km = self.model.distance_to(other_model, unit='km')
        distance_mi = self.model.distance_to(other_model, unit='mi')
        
        # Approximate distance between NYC and LA is ~3940 km / 2450 mi
        assert distance_km is not None
        assert distance_mi is not None
        assert 3900 < distance_km < 4000  # Approximate range
        assert 2400 < distance_mi < 2500  # Approximate range
    
    def test_distance_to_missing_coordinates(self):
        """Test distance calculation with missing coordinates."""
        self.model.latitude = 40.7128
        self.model.longitude = -74.0060
        
        other_model = TestGeoLocationModel()
        other_model.latitude = None  # Missing coordinate
        other_model.longitude = -118.2437
        
        result = self.model.distance_to(other_model)
        
        assert result is None
    
    def test_haversine_distance_calculation(self):
        """Test Haversine formula calculation directly."""
        # Test known distance: NYC to LA
        distance = TestGeoLocationModel.haversine_distance(
            40.7128, -74.0060,  # New York
            34.0522, -118.2437,  # Los Angeles
            unit='km'
        )
        
        # Should be approximately 3940 km
        assert 3900 < distance < 4000
    
    def test_get_nominatim_accuracy_mapping(self):
        """Test Nominatim accuracy level mapping."""
        assert self.model._get_nominatim_accuracy('place', 'house') == 'exact'
        assert self.model._get_nominatim_accuracy('place', 'city') == 'city'
        assert self.model._get_nominatim_accuracy('place', 'country') == 'country'
        assert self.model._get_nominatim_accuracy('unknown', 'unknown') == 'approximate'


class TestEncryptionMixin:
    """Test EncryptionMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestEncryptionModel()
        self.model.name = "Test Item"
        # Generate a test encryption key
        self.test_key = Fernet.generate_key()
    
    @patch('pgappforge.mixins.specialized_mixins.current_app')
    def test_encrypt_field_success(self, mock_app):
        """Test successful field encryption."""
        # Setup app config
        mock_app.config = {'ENCRYPTION_KEY': self.test_key}
        
        sensitive_data = "This is sensitive information"
        
        result = self.model.encrypt_field(sensitive_data)
        
        assert result != sensitive_data  # Should be encrypted
        assert isinstance(result, bytes)  # Encrypted data is bytes
    
    @patch('pgappforge.mixins.specialized_mixins.current_app')
    def test_decrypt_field_success(self, mock_app):
        """Test successful field decryption."""
        # Setup app config
        mock_app.config = {'ENCRYPTION_KEY': self.test_key}
        
        original_data = "This is sensitive information"
        
        # First encrypt the data
        encrypted_data = self.model.encrypt_field(original_data)
        
        # Then decrypt it
        decrypted_data = self.model.decrypt_field(encrypted_data)
        
        assert decrypted_data == original_data
    
    def test_encrypt_field_no_encryption_key(self):
        """Test encryption without encryption key configured."""
        with patch('pgappforge.mixins.specialized_mixins.current_app') as mock_app:
            mock_app.config = {}  # No encryption key
            
            with pytest.raises(MixinConfigurationError) as exc_info:
                self.model.encrypt_field("data")
            
            assert "ENCRYPTION_KEY not configured" in str(exc_info.value)
    
    def test_decrypt_field_invalid_data(self):
        """Test decryption of invalid/corrupted data."""
        with patch('pgappforge.mixins.specialized_mixins.current_app') as mock_app:
            mock_app.config = {'ENCRYPTION_KEY': self.test_key}
            
            invalid_data = b"this_is_not_encrypted_data"
            
            with pytest.raises(MixinDataError) as exc_info:
                self.model.decrypt_field(invalid_data)
            
            assert "Failed to decrypt" in str(exc_info.value)
    
    @patch('pgappforge.mixins.specialized_mixins.current_app')
    def test_is_field_encrypted(self, mock_app):
        """Test checking if field is encrypted."""
        mock_app.config = {'ENCRYPTION_KEY': self.test_key}
        
        original_data = "sensitive data"
        encrypted_data = self.model.encrypt_field(original_data)
        
        assert self.model.is_field_encrypted(encrypted_data) is True
        assert self.model.is_field_encrypted(original_data) is False
        assert self.model.is_field_encrypted("plain text") is False
    
    @patch('pgappforge.mixins.specialized_mixins.current_app')
    def test_rotate_encryption_key(self, mock_app):
        """Test encryption key rotation."""
        # Setup original key
        old_key = self.test_key
        new_key = Fernet.generate_key()
        
        mock_app.config = {'ENCRYPTION_KEY': old_key}
        
        # Encrypt data with old key
        original_data = "sensitive information"
        old_encrypted = self.model.encrypt_field(original_data)
        
        # Update to new key
        mock_app.config = {'ENCRYPTION_KEY': new_key}
        
        # Test key rotation
        new_encrypted = self.model.rotate_encryption_key(old_encrypted, old_key)
        
        # Should be able to decrypt with new key
        decrypted = self.model.decrypt_field(new_encrypted)
        assert decrypted == original_data
    
    def test_generate_encryption_key(self):
        """Test encryption key generation."""
        key = TestEncryptionModel.generate_encryption_key()
        
        assert isinstance(key, bytes)
        assert len(key) == 44  # Fernet keys are 44 bytes when base64 encoded
        
        # Should be a valid Fernet key
        fernet = Fernet(key)
        test_data = b"test"
        encrypted = fernet.encrypt(test_data)
        decrypted = fernet.decrypt(encrypted)
        assert decrypted == test_data


class TestVersioningMixin:
    """Test VersioningMixin functionality."""
    
    def setup_method(self):
        """Setup test instance."""
        self.model = TestVersioningModel()
        self.model.id = 123
        self.model.name = "Test Document"
        self.model.content = "Original content"
        self.model.version_number = 1
        self.model.version_history = '[]'
    
    @patch('pgappforge.mixins.specialized_mixins.current_user')
    @patch('pgappforge.mixins.specialized_mixins.db')
    def test_create_version_basic(self, mock_db, mock_user):
        """Test basic version creation."""
        mock_user.id = 456
        
        # Make changes and create version
        self.model.content = "Updated content"
        
        result = self.model.create_version("Updated content for v2")
        
        assert result is True
        assert self.model.version_number == 2
        
        # Check version history
        history = json.loads(self.model.version_history)
        assert len(history) == 1
        assert history[0]['version'] == 1
        assert history[0]['changes'] == "Updated content for v2"
        assert history[0]['created_by'] == 456
    
    def test_get_version_history(self):
        """Test retrieving version history."""
        # Setup version history
        history_data = [
            {
                'version': 1,
                'timestamp': '2023-01-01T12:00:00',
                'changes': 'Initial version',
                'created_by': 123
            },
            {
                'version': 2,
                'timestamp': '2023-01-02T12:00:00',
                'changes': 'Updated content',
                'created_by': 456
            }
        ]
        self.model.version_history = json.dumps(history_data)
        
        result = self.model.get_version_history()
        
        assert len(result) == 2
        assert result[0]['version'] == 1
        assert result[1]['version'] == 2
    
    def test_get_version_history_limit(self):
        """Test retrieving limited version history."""
        # Setup multiple versions
        history_data = [{'version': i, 'changes': f'Version {i}'} for i in range(1, 6)]
        self.model.version_history = json.dumps(history_data)
        
        result = self.model.get_version_history(limit=3)
        
        assert len(result) == 3
        # Should return most recent versions first
        assert result[0]['version'] == 5
        assert result[1]['version'] == 4
        assert result[2]['version'] == 3
    
    @patch('pgappforge.mixins.specialized_mixins.db')
    def test_rollback_to_version(self, mock_db):
        """Test rolling back to previous version."""
        # Setup version history
        history_data = [
            {
                'version': 1,
                'snapshot': {
                    'name': 'Original Document',
                    'content': 'Original content'
                },
                'timestamp': '2023-01-01T12:00:00',
                'changes': 'Initial version'
            }
        ]
        self.model.version_history = json.dumps(history_data)
        self.model.version_number = 2
        self.model.name = "Modified Document"
        self.model.content = "Modified content"
        
        # Test rollback
        result = self.model.rollback_to_version(1, "Rolling back to original")
        
        assert result is True
        assert self.model.name == "Original Document"
        assert self.model.content == "Original content"
        assert self.model.version_number == 3  # New version created
        
        # Check that rollback was recorded in history
        history = json.loads(self.model.version_history)
        assert len(history) == 2  # Original + rollback record
        assert history[-1]['changes'] == "Rolling back to original"
    
    def test_rollback_to_nonexistent_version(self):
        """Test rollback to non-existent version."""
        self.model.version_history = '[]'
        
        result = self.model.rollback_to_version(5)
        
        assert result is False
    
    def test_compare_versions(self):
        """Test comparing different versions."""
        # Setup version history with snapshots
        history_data = [
            {
                'version': 1,
                'snapshot': {'content': 'Version 1 content'},
                'timestamp': '2023-01-01T12:00:00'
            },
            {
                'version': 2,
                'snapshot': {'content': 'Version 2 content'},
                'timestamp': '2023-01-02T12:00:00'
            }
        ]
        self.model.version_history = json.dumps(history_data)
        
        result = self.model.compare_versions(1, 2)
        
        assert result is not None
        assert 'version_1' in result
        assert 'version_2' in result
        assert 'differences' in result
        assert result['version_1']['content'] == 'Version 1 content'
        assert result['version_2']['content'] == 'Version 2 content'
    
    def test_compare_invalid_versions(self):
        """Test comparing with invalid version numbers."""
        self.model.version_history = '[]'
        
        result = self.model.compare_versions(1, 999)
        
        assert result is None
    
    def test_get_version_info(self):
        """Test getting information about specific version."""
        # Setup version history
        history_data = [
            {
                'version': 1,
                'timestamp': '2023-01-01T12:00:00',
                'changes': 'Initial version',
                'created_by': 123,
                'snapshot': {'name': 'Original', 'content': 'Original content'}
            }
        ]
        self.model.version_history = json.dumps(history_data)
        
        result = self.model.get_version_info(1)
        
        assert result is not None
        assert result['version'] == 1
        assert result['changes'] == 'Initial version'
        assert result['created_by'] == 123
        assert 'snapshot' in result
    
    def test_get_version_info_nonexistent(self):
        """Test getting info for non-existent version."""
        self.model.version_history = '[]'
        
        result = self.model.get_version_info(999)
        
        assert result is None


class TestMixinCombinations:
    """Test combinations of specialized mixins."""
    
    def setup_method(self):
        """Setup combined model."""
        class CombinedSpecializedModel(CurrencyMixin, GeoLocationMixin, EncryptionMixin, Model):
            __tablename__ = 'combined_specialized'
            __default_currency__ = 'USD'
            __exchange_rate_api_url__ = 'https://api.test.com'
            
            name = None
        
        self.model = CombinedSpecializedModel()
        self.model.amount = Decimal('100.00')
        self.model.currency = 'USD'
        self.model.address = "Test Address"
    
    def test_currency_and_location_integration(self):
        """Test using currency and location together."""
        # Set coordinates for a specific location
        self.model.set_coordinates(40.7128, -74.0060)  # NYC
        
        # Convert currency (could be location-aware in advanced scenarios)
        with patch.object(self.model, 'get_exchange_rates') as mock_rates:
            mock_rates.return_value = {'EUR': 0.85}
            
            converted_amount = self.model.convert_to('EUR')
            
            assert converted_amount == Decimal('85.00')
            assert self.model.latitude == 40.7128
    
    @patch('pgappforge.mixins.specialized_mixins.current_app')
    def test_encryption_with_location_data(self, mock_app):
        """Test encrypting location-sensitive data."""
        mock_app.config = {'ENCRYPTION_KEY': Fernet.generate_key()}
        
        # Encrypt sensitive location data
        sensitive_location = "Secret facility coordinates"
        encrypted_data = self.model.encrypt_field(sensitive_location)
        
        # Verify it's encrypted and can be decrypted
        assert encrypted_data != sensitive_location
        decrypted = self.model.decrypt_field(encrypted_data)
        assert decrypted == sensitive_location


class TestPerformanceScenarios:
    """Test performance-critical scenarios."""
    
    @patch('pgappforge.mixins.specialized_mixins.requests.get')
    def test_geocoding_timeout_handling(self, mock_requests):
        """Test geocoding with network timeouts."""
        import requests
        
        # Setup timeout exception
        mock_requests.side_effect = requests.Timeout("Request timed out")
        
        model = TestGeoLocationModel()
        model.address = "Test Address"
        
        # Should handle timeout gracefully and try next provider
        with patch.object(model, '_geocode_with_mapquest', return_value=None):
            with patch.object(model, '_geocode_with_google', return_value=None):
                result = model.geocode_address()
        
        assert result is False
    
    @patch('pgappforge.mixins.specialized_mixins.current_app')
    def test_currency_rate_caching(self, mock_app):
        """Test that currency rates are properly cached."""
        # Setup cache mock
        mock_cache = Mock()
        mock_app.cache = mock_cache
        
        # First call - should fetch from API and cache
        mock_cache.get.return_value = None
        with patch('pgappforge.mixins.specialized_mixins.requests.get') as mock_requests:
            mock_response = Mock()
            mock_response.json.return_value = {'rates': {'EUR': 0.85}}
            mock_requests.return_value = mock_response
            
            model = TestCurrencyModel()
            rates1 = model.get_exchange_rates('USD')
        
        # Second call - should use cache
        mock_cache.get.return_value = {'EUR': 0.85}
        rates2 = model.get_exchange_rates('USD')
        
        assert rates1 == rates2
        # Cache should have been checked on second call
        assert mock_cache.get.call_count >= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])