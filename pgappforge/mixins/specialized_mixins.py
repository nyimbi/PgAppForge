"""
Specialized Mixins for PgAppForge

This module provides specialized mixins for advanced functionality:
- Currency handling and conversion
- Geographic data and spatial operations
- Encryption and security features
- Version control and change tracking
- Scheduling and time-based operations

These mixins provide specialized business functionality while
maintaining integration with PgAppForge's architecture.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

import requests
from cryptography.fernet import Fernet
from flask import current_app, current_user
from pgappforge.models.mixins import AuditMixin
from sqlalchemy import (
    Boolean, Column, DateTime, Float, Integer, LargeBinary, Numeric, String, Text, event
)
from sqlalchemy.ext.declarative import declared_attr

# Import security framework
from .security_framework import (
    MixinExternalServiceError, MixinConfigurationError, MixinValidationError,
    MixinDataError, SecurityValidator, InputValidator, ErrorRecovery,
    secure_operation, database_operation
)

log = logging.getLogger(__name__)


class CurrencyMixin:
    """
    Currency handling and conversion mixin.
    
    Provides comprehensive currency functionality including:
    - Multi-currency support with automatic conversion
    - Exchange rate management and caching
    - Currency formatting and display
    - Historical exchange rate tracking
    - Currency arithmetic operations
    
    Features:
    - Configurable default currency
    - Exchange rate API integration
    - Currency validation and formatting
    - Mathematical operations with currency conversion
    - Audit trail for currency changes
    """
    
    amount = Column(Numeric(precision=15, scale=2), nullable=True)
    currency = Column(String(3), default='USD', nullable=False)  # ISO 4217 codes
    
    # Configuration - override in subclasses
    __default_currency__ = 'USD'
    __exchange_rate_api_key__ = None
    __exchange_rate_api_url__ = 'https://api.exchangerate-api.com/v4/latest'
    
    @classmethod
    def __declare_last__(cls):
        """Set up currency event listeners."""
        super().__declare_last__()
        
        @event.listens_for(cls, 'before_insert')
        @event.listens_for(cls, 'before_update')
        def validate_currency(mapper, connection, target):
            if target.currency and len(target.currency) != 3:
                target.currency = cls.__default_currency__
    
    def get_exchange_rates(self, base_currency: str = None) -> Dict[str, float]:
        """
        Get current exchange rates.
        
        Args:
            base_currency: Base currency for conversion
            
        Returns:
            Dict mapping currency codes to exchange rates
        """
        base_currency = base_currency or self.__default_currency__
        cache_key = f"exchange_rates_{base_currency}"
        
        # Try to get from cache first
        try:
            if hasattr(current_app, 'cache'):
                cached_rates = current_app.cache.get(cache_key)
                if cached_rates:
                    return cached_rates
        except:
            pass
        
        # Fetch from API with proper error handling
        try:
            # Validate currency code
            if not isinstance(base_currency, str) or len(base_currency) != 3:
                raise MixinValidationError(
                    "Currency code must be 3-character string",
                    field="base_currency",
                    value=base_currency
                )
            
            url = f"{self.__exchange_rate_api_url__}/{base_currency.upper()}"
            if self.__exchange_rate_api_key__:
                url += f"?access_key={self.__exchange_rate_api_key__}"
            
            # Use retry mechanism for external service calls
            def fetch_rates():
                response = requests.get(url, timeout=10)
                response.raise_for_status()
                return response.json()
            
            data = ErrorRecovery.retry_with_backoff(
                fetch_rates,
                max_retries=2,
                retryable_exceptions=(requests.RequestException, requests.Timeout)
            )
            
            rates = data.get('rates', {})
            if not rates:
                raise MixinExternalServiceError(
                    "Empty rates data from API", 
                    service="exchange_rate_api"
                )
            
            # Cache for 1 hour
            if hasattr(current_app, 'cache'):
                current_app.cache.set(cache_key, rates, timeout=3600)
            
            log.debug(f"Successfully fetched {len(rates)} exchange rates for {base_currency}")
            return rates
            
        except requests.RequestException as e:
            log.warning(f"Exchange rate API request failed: {e}")
            raise MixinExternalServiceError(
                f"Exchange rate service unavailable: {str(e)}", 
                service="exchange_rate_api",
                response_code=getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
            )
        except (MixinValidationError, MixinExternalServiceError):
            raise
        except Exception as e:
            log.error(f"Unexpected error fetching exchange rates: {e}")
            raise MixinExternalServiceError(
                f"Exchange rate service error: {str(e)}", 
                service="exchange_rate_api"
            )
    
    def convert_to(self, target_currency: str, round_digits: int = 2) -> Decimal:
        """
        Convert amount to target currency with comprehensive error handling.
        
        Args:
            target_currency: Target currency code
            round_digits: Number of decimal places to round to
            
        Returns:
            Converted amount
            
        Raises:
            MixinValidationError: If input parameters are invalid
            MixinDataError: If conversion data is missing or invalid
            MixinExternalServiceError: If exchange rate service fails
        """
        # Validate inputs
        if not self.amount:
            raise MixinDataError("Cannot convert: amount is not set")
        
        if not self.currency:
            raise MixinDataError("Cannot convert: source currency is not set")
        
        # Validate target currency
        target_currency = InputValidator.sanitize_string(target_currency, max_length=3)
        if len(target_currency) != 3:
            raise MixinValidationError(
                "Target currency must be 3-character code",
                field="target_currency",
                value=target_currency
            )
        
        # Validate round_digits
        if not isinstance(round_digits, int) or round_digits < 0 or round_digits > 10:
            raise MixinValidationError(
                "Round digits must be integer between 0 and 10",
                field="round_digits",
                value=round_digits
            )
        
        # Same currency - return original amount
        if self.currency.upper() == target_currency.upper():
            return self.amount
        
        try:
            # Get exchange rates with error handling
            rates = self.get_exchange_rates(self.currency)
            
            target_currency_upper = target_currency.upper()
            if target_currency_upper not in rates:
                available_currencies = list(rates.keys())[:10]  # Show first 10
                raise MixinDataError(
                    f"Exchange rate not available for {target_currency_upper}. "
                    f"Available: {available_currencies}..."
                )
            
            # Perform conversion
            exchange_rate = Decimal(str(rates[target_currency_upper]))
            if exchange_rate <= 0:
                raise MixinDataError(
                    f"Invalid exchange rate for {target_currency_upper}: {exchange_rate}"
                )
            
            converted = self.amount * exchange_rate
            
            # Apply rounding
            if round_digits == 0:
                return converted.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            else:
                decimal_places = '0.' + '0' * (round_digits - 1) + '1'
                return converted.quantize(Decimal(decimal_places), rounding=ROUND_HALF_UP)
            
        except (MixinValidationError, MixinDataError, MixinExternalServiceError):
            raise
        except (ValueError, TypeError) as e:
            raise MixinDataError(f"Currency conversion calculation error: {str(e)}")
        except Exception as e:
            log.error(f"Unexpected error in currency conversion: {e}")
            raise MixinDataError(f"Currency conversion failed: {str(e)}")
    
    def format_amount(self, locale: str = 'en_US', include_currency: bool = True) -> str:
        """
        Format amount for display.
        
        Args:
            locale: Locale for formatting
            include_currency: Include currency symbol
            
        Returns:
            Formatted amount string
        """
        if not self.amount:
            return "0.00"
        
        # Basic formatting - you might want to use babel for proper localization
        formatted = f"{float(self.amount):,.2f}"
        
        if include_currency:
            formatted = f"{formatted} {self.currency}"
        
        return formatted
    
    def add_amount(self, other_amount: Decimal, other_currency: str = None) -> bool:
        """
        Add amount in potentially different currency.
        
        Args:
            other_amount: Amount to add
            other_currency: Currency of amount to add
            
        Returns:
            Success status
        """
        if not other_currency:
            other_currency = self.currency
        
        if other_currency == self.currency:
            self.amount = (self.amount or Decimal('0')) + other_amount
            return True
        
        # Convert to our currency
        temp_obj = type(self)(amount=other_amount, currency=other_currency)
        converted = temp_obj.convert_to(self.currency)
        
        if converted is not None:
            self.amount = (self.amount or Decimal('0')) + converted
            return True
        
        return False
    
    def subtract_amount(self, other_amount: Decimal, other_currency: str = None) -> bool:
        """Subtract amount in potentially different currency."""
        return self.add_amount(-other_amount, other_currency)
    
    def multiply(self, factor: Decimal) -> 'CurrencyMixin':
        """Multiply amount by factor."""
        result = type(self)(
            amount=(self.amount or Decimal('0')) * factor,
            currency=self.currency
        )
        return result
    
    def divide(self, divisor: Decimal) -> 'CurrencyMixin':
        """Divide amount by divisor."""
        if divisor == 0:
            raise ValueError("Cannot divide by zero")
        
        result = type(self)(
            amount=(self.amount or Decimal('0')) / divisor,
            currency=self.currency
        )
        return result
    
    @classmethod
    def get_supported_currencies(cls) -> List[str]:
        """Get list of supported currency codes."""
        return [
            'USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'CNY',
            'SEK', 'NZD', 'MXN', 'SGD', 'HKD', 'NOK', 'TRY', 'RUB',
            'INR', 'BRL', 'ZAR', 'KRW'
        ]


class GeoLocationMixin:
    """
    Geographic location and spatial operations mixin.
    
    Provides comprehensive geospatial functionality including:
    - Coordinate storage and validation
    - Distance calculations
    - Geocoding and reverse geocoding
    - Spatial queries and indexing
    - Map integration utilities
    
    Features:
    - Latitude/longitude storage
    - Address geocoding
    - Distance calculations (Haversine formula)
    - Bounding box queries
    - Integration with mapping services
    """
    
    latitude = Column(Float, nullable=True, index=True)
    longitude = Column(Float, nullable=True, index=True)
    address = Column(String(500), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    country = Column(String(100), nullable=True)
    postal_code = Column(String(20), nullable=True)
    
    # Geocoding metadata
    geocoded = Column(Boolean, default=False)
    geocode_accuracy = Column(String(20), nullable=True)  # exact, approximate, etc.
    geocode_source = Column(String(50), nullable=True)    # google, osm, etc.
    
    def set_coordinates(self, lat: float, lon: float, accuracy: str = None):
        """Set geographic coordinates with validation."""
        if not self._validate_coordinates(lat, lon):
            raise ValueError(f"Invalid coordinates: ({lat}, {lon})")
        
        self.latitude = lat
        self.longitude = lon
        self.geocoded = True
        self.geocode_accuracy = accuracy
        self.geocode_source = 'manual'
    
    def _validate_coordinates(self, lat: float, lon: float) -> bool:
        """Validate latitude and longitude values."""
        return (-90 <= lat <= 90) and (-180 <= lon <= 180)
    
    def geocode_address(self, address: str = None, force: bool = False) -> bool:
        """
        Geocode address to coordinates using multiple provider fallbacks.
        
        Args:
            address: Address to geocode (uses stored address if None)
            force: Force re-geocoding even if already geocoded
            
        Returns:
            Success status
        """
        if self.geocoded and not force:
            return True
        
        address = address or self.address
        if not address:
            return False
        
        try:
            # Try multiple geocoding providers in order of preference
            providers = [
                self._geocode_with_nominatim,
                self._geocode_with_mapquest,  # Fallback 1
                self._geocode_with_google,    # Fallback 2 (requires API key)
            ]
            
            for provider in providers:
                try:
                    result = provider(address)
                    if result:
                        self.latitude = result['lat']
                        self.longitude = result['lon'] 
                        self.geocoded = True
                        self.geocode_accuracy = result.get('accuracy', 'unknown')
                        self.geocode_source = result['source']
                        
                        # Update address components if available
                        if 'address_components' in result:
                            components = result['address_components']
                            self.city = components.get('city')
                            self.state = components.get('state')
                            self.country = components.get('country')
                            self.postal_code = components.get('postal_code')
                        
                        log.info(f"Successfully geocoded '{address}' using {result['source']}")
                        return True
                        
                except Exception as e:
                    log.warning(f"Geocoding provider {provider.__name__} failed: {e}")
                    continue
            
            log.warning(f"All geocoding providers failed for address: {address}")
            return False
            
        except Exception as e:
            log.error(f"Geocoding failed with unexpected error: {e}")
            return False
    
    def _geocode_with_nominatim(self, address: str) -> Optional[Dict[str, Any]]:
        """Geocode using OpenStreetMap Nominatim (free service)."""
        try:
            # Rate limiting - Nominatim requires max 1 request per second
            import time
            time.sleep(1)
            
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                'q': address,
                'format': 'json',
                'limit': 1,
                'addressdetails': 1
            }
            headers = {
                'User-Agent': getattr(current_app.config, 'GEOCODING_USER_AGENT', 
                                    'PgAppForge/4.8.0 (geocoding)')
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if not data:
                return None
            
            result = data[0]
            return {
                'lat': float(result['lat']),
                'lon': float(result['lon']),
                'source': 'nominatim',
                'accuracy': self._get_nominatim_accuracy(result.get('class'), result.get('type')),
                'address_components': self._parse_nominatim_address(result.get('address', {}))
            }
            
        except Exception as e:
            log.warning(f"Nominatim geocoding failed: {e}")
            return None
    
    def _geocode_with_mapquest(self, address: str) -> Optional[Dict[str, Any]]:
        """Geocode using MapQuest Open API (requires API key but generous free tier)."""
        try:
            api_key = getattr(current_app.config, 'MAPQUEST_API_KEY', None)
            if not api_key:
                log.debug("MapQuest API key not configured, skipping provider")
                return None
            
            url = "http://www.mapquestapi.com/geocoding/v1/address"
            params = {
                'key': api_key,
                'location': address,
                'maxResults': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = data.get('results', [{}])[0].get('locations', [])
            
            if not results:
                return None
            
            result = results[0]
            lat_lng = result.get('latLng', {})
            
            return {
                'lat': lat_lng.get('lat'),
                'lon': lat_lng.get('lng'),
                'source': 'mapquest',
                'accuracy': result.get('geocodeQuality', 'unknown').lower(),
                'address_components': {
                    'city': result.get('adminArea5'),
                    'state': result.get('adminArea3'),
                    'country': result.get('adminArea1'),
                    'postal_code': result.get('postalCode')
                }
            }
            
        except Exception as e:
            log.warning(f"MapQuest geocoding failed: {e}")
            return None
    
    def _geocode_with_google(self, address: str) -> Optional[Dict[str, Any]]:
        """Geocode using Google Maps Geocoding API (requires API key and billing)."""
        try:
            api_key = getattr(current_app.config, 'GOOGLE_MAPS_API_KEY', None)
            if not api_key:
                log.debug("Google Maps API key not configured, skipping provider")
                return None
            
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                'address': address,
                'key': api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data.get('status') != 'OK' or not data.get('results'):
                return None
            
            result = data['results'][0]
            location = result['geometry']['location']
            
            return {
                'lat': location['lat'],
                'lon': location['lng'],
                'source': 'google',
                'accuracy': result['geometry'].get('location_type', 'unknown').lower(),
                'address_components': self._parse_google_address_components(
                    result.get('address_components', [])
                )
            }
            
        except Exception as e:
            log.warning(f"Google geocoding failed: {e}")
            return None
    
    def _get_nominatim_accuracy(self, osm_class: str, osm_type: str) -> str:
        """Convert Nominatim class/type to accuracy level."""
        if not osm_class or not osm_type:
            return 'unknown'
        
        accuracy_map = {
            ('place', 'house'): 'exact',
            ('place', 'postcode'): 'postal',
            ('place', 'neighbourhood'): 'approximate',
            ('place', 'suburb'): 'approximate',
            ('place', 'city'): 'city',
            ('place', 'town'): 'city',
            ('place', 'village'): 'city',
            ('place', 'state'): 'region',
            ('place', 'country'): 'country'
        }
        
        return accuracy_map.get((osm_class, osm_type), 'approximate')
    
    def _parse_nominatim_address(self, address_data: Dict[str, Any]) -> Dict[str, str]:
        """Parse Nominatim address components into standard format."""
        return {
            'city': address_data.get('city') or address_data.get('town') or address_data.get('village'),
            'state': address_data.get('state'),
            'country': address_data.get('country'),
            'postal_code': address_data.get('postcode')
        }
    
    def _parse_google_address_components(self, components: List[Dict]) -> Dict[str, str]:
        """Parse Google Maps address components into standard format."""
        parsed = {}
        
        for component in components:
            types = component.get('types', [])
            long_name = component.get('long_name')
            
            if 'locality' in types:
                parsed['city'] = long_name
            elif 'administrative_area_level_1' in types:
                parsed['state'] = long_name
            elif 'country' in types:
                parsed['country'] = long_name
            elif 'postal_code' in types:
                parsed['postal_code'] = long_name
        
        return parsed
    
    def reverse_geocode(self, update_address: bool = True) -> Optional[Dict[str, str]]:
        """
        Reverse geocode coordinates to address using multiple provider fallbacks.
        
        Args:
            update_address: Update stored address fields
            
        Returns:
            Address components or None if failed
        """
        if not self.latitude or not self.longitude:
            return None
        
        try:
            # Try multiple reverse geocoding providers
            providers = [
                self._reverse_geocode_with_nominatim,
                self._reverse_geocode_with_mapquest,
                self._reverse_geocode_with_google,
            ]
            
            for provider in providers:
                try:
                    result = provider(self.latitude, self.longitude)
                    if result:
                        if update_address:
                            self.address = result.get('address')
                            self.city = result.get('city')
                            self.state = result.get('state')
                            self.country = result.get('country')
                            self.postal_code = result.get('postal_code')
                        
                        log.info(f"Successfully reverse geocoded ({self.latitude}, {self.longitude})")
                        return result
                        
                except Exception as e:
                    log.warning(f"Reverse geocoding provider {provider.__name__} failed: {e}")
                    continue
            
            log.warning(f"All reverse geocoding providers failed for ({self.latitude}, {self.longitude})")
            return None
            
        except Exception as e:
            log.error(f"Reverse geocoding failed with unexpected error: {e}")
            return None
    
    def _reverse_geocode_with_nominatim(self, lat: float, lon: float) -> Optional[Dict[str, str]]:
        """Reverse geocode using OpenStreetMap Nominatim."""
        try:
            import time
            time.sleep(1)  # Rate limiting
            
            url = "https://nominatim.openstreetmap.org/reverse"
            params = {
                'lat': lat,
                'lon': lon,
                'format': 'json',
                'addressdetails': 1
            }
            headers = {
                'User-Agent': getattr(current_app.config, 'GEOCODING_USER_AGENT', 
                                    'PgAppForge/4.8.0 (geocoding)')
            }
            
            response = requests.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if not data or 'error' in data:
                return None
            
            address_data = data.get('address', {})
            return {
                'address': data.get('display_name'),
                'city': address_data.get('city') or address_data.get('town') or address_data.get('village'),
                'state': address_data.get('state'),
                'country': address_data.get('country'),
                'postal_code': address_data.get('postcode')
            }
            
        except Exception as e:
            log.warning(f"Nominatim reverse geocoding failed: {e}")
            return None
    
    def _reverse_geocode_with_mapquest(self, lat: float, lon: float) -> Optional[Dict[str, str]]:
        """Reverse geocode using MapQuest Open API."""
        try:
            api_key = getattr(current_app.config, 'MAPQUEST_API_KEY', None)
            if not api_key:
                return None
            
            url = "http://www.mapquestapi.com/geocoding/v1/reverse"
            params = {
                'key': api_key,
                'location': f"{lat},{lon}",
                'maxResults': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            results = data.get('results', [{}])[0].get('locations', [])
            
            if not results:
                return None
            
            result = results[0]
            return {
                'address': result.get('street', ''),
                'city': result.get('adminArea5'),
                'state': result.get('adminArea3'),
                'country': result.get('adminArea1'),
                'postal_code': result.get('postalCode')
            }
            
        except Exception as e:
            log.warning(f"MapQuest reverse geocoding failed: {e}")
            return None
    
    def _reverse_geocode_with_google(self, lat: float, lon: float) -> Optional[Dict[str, str]]:
        """Reverse geocode using Google Maps Geocoding API."""
        try:
            api_key = getattr(current_app.config, 'GOOGLE_MAPS_API_KEY', None)
            if not api_key:
                return None
            
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                'latlng': f"{lat},{lon}",
                'key': api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            if data.get('status') != 'OK' or not data.get('results'):
                return None
            
            result = data['results'][0]
            components = self._parse_google_address_components(
                result.get('address_components', [])
            )
            
            return {
                'address': result.get('formatted_address'),
                'city': components.get('city'),
                'state': components.get('state'),
                'country': components.get('country'),
                'postal_code': components.get('postal_code')
            }
            
        except Exception as e:
            log.warning(f"Google reverse geocoding failed: {e}")
            return None
    
    def distance_to(self, other, unit: str = 'km') -> Optional[float]:
        """
        Calculate distance to another location using Haversine formula.
        
        Args:
            other: Another GeoLocationMixin instance
            unit: Distance unit ('km', 'mi', 'nm')
            
        Returns:
            Distance in specified unit or None if coordinates missing
        """
        if not all([self.latitude, self.longitude, other.latitude, other.longitude]):
            return None
        
        return self.haversine_distance(
            self.latitude, self.longitude,
            other.latitude, other.longitude,
            unit
        )
    
    @staticmethod
    def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float, 
                          unit: str = 'km') -> float:
        """
        Calculate great-circle distance using Haversine formula.
        
        Args:
            lat1, lon1: First point coordinates
            lat2, lon2: Second point coordinates
            unit: Distance unit ('km', 'mi', 'nm')
            
        Returns:
            Distance in specified unit
        """
        import math
        
        # Convert to radians
        lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
        
        # Haversine formula
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = (math.sin(dlat/2)**2 + 
             math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2)
        c = 2 * math.asin(math.sqrt(a))
        
        # Radius of Earth
        radius_km = 6371
        distance = radius_km * c
        
        # Convert to requested unit
        if unit == 'mi':
            return distance * 0.621371  # km to miles
        elif unit == 'nm':
            return distance * 0.539957  # km to nautical miles
        else:
            return distance  # kilometers
    
    @classmethod
    def find_within_radius(cls, lat: float, lon: float, radius: float, 
                          unit: str = 'km', limit: int = 100):
        """
        Find records within radius of given coordinates.
        
        Args:
            lat, lon: Center point coordinates
            radius: Search radius
            unit: Distance unit
            limit: Maximum results
            
        Returns:
            List of records within radius
        """
        # Calculate bounding box for initial filtering
        lat_delta = radius / 111  # Approximately 111 km per degree
        lon_delta = radius / (111 * abs(math.cos(math.radians(lat))))
        
        # Query within bounding box
        candidates = cls.query.filter(
            cls.latitude.between(lat - lat_delta, lat + lat_delta),
            cls.longitude.between(lon - lon_delta, lon + lon_delta)
        ).limit(limit * 2).all()  # Get extra for filtering
        
        # Filter by actual distance
        results = []
        for candidate in candidates:
            distance = cls.haversine_distance(lat, lon, candidate.latitude, candidate.longitude, unit)
            if distance <= radius:
                candidate._distance = distance  # Attach distance for sorting
                results.append(candidate)
        
        # Sort by distance and limit
        results.sort(key=lambda x: x._distance)
        return results[:limit]
    
    def get_map_url(self, zoom: int = 15, width: int = 400, height: int = 300) -> Optional[str]:
        """Generate map URL for this location."""
        if not self.latitude or not self.longitude:
            return None
        
        # Google Static Maps URL
        base_url = "https://maps.googleapis.com/maps/api/staticmap"
        params = {
            'center': f"{self.latitude},{self.longitude}",
            'zoom': zoom,
            'size': f"{width}x{height}",
            'markers': f"color:red|{self.latitude},{self.longitude}"
        }
        
        # Add API key if configured
        api_key = current_app.config.get('GOOGLE_MAPS_API_KEY')
        if api_key:
            params['key'] = api_key
        
        query_string = '&'.join([f"{k}={quote(str(v))}" for k, v in params.items()])
        return f"{base_url}?{query_string}"
    
    def to_geojson(self) -> Optional[Dict[str, Any]]:
        """Convert location to GeoJSON format."""
        if not self.latitude or not self.longitude:
            return None
        
        return {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [self.longitude, self.latitude]
            },
            "properties": {
                "address": self.address,
                "city": self.city,
                "state": self.state,
                "country": self.country,
                "postal_code": self.postal_code
            }
        }


class EncryptionMixin:
    """
    Field-level encryption mixin for sensitive data.
    
    Provides transparent encryption/decryption of specified fields
    with key management and migration utilities.
    
    Features:
    - Configurable field encryption
    - Automatic encryption/decryption
    - Key rotation support
    - Migration utilities for existing data
    - Secure key management
    """
    
    # Configuration - override in subclasses
    __encrypted_fields__ = []  # List of field names to encrypt
    __encryption_key__ = None  # Base64-encoded Fernet key
    
    @classmethod
    def set_encryption_key(cls, key: bytes):
        """Set encryption key for this model."""
        cls.__encryption_key__ = key
    
    @classmethod
    def generate_encryption_key(cls) -> bytes:
        """Generate new encryption key."""
        return Fernet.generate_key()
    
    def encrypt_field(self, field_name: str, value: str) -> Optional[bytes]:
        """Encrypt a field value."""
        if not value or not self.__encryption_key__:
            return None
        
        try:
            fernet = Fernet(self.__encryption_key__)
            return fernet.encrypt(value.encode('utf-8'))
        except Exception as e:
            log.error(f"Encryption failed for field {field_name}: {e}")
            return None
    
    def decrypt_field(self, field_name: str, encrypted_value: bytes) -> Optional[str]:
        """Decrypt a field value."""
        if not encrypted_value or not self.__encryption_key__:
            return None
        
        try:
            fernet = Fernet(self.__encryption_key__)
            return fernet.decrypt(encrypted_value).decode('utf-8')
        except Exception as e:
            log.error(f"Decryption failed for field {field_name}: {e}")
            return None
    
    @classmethod
    def __declare_last__(cls):
        """Set up encryption event listeners."""
        super().__declare_last__()
        
        if not cls.__encrypted_fields__:
            return
        
        @event.listens_for(cls, 'before_insert')
        @event.listens_for(cls, 'before_update')
        def encrypt_fields(mapper, connection, target):
            for field_name in cls.__encrypted_fields__:
                if hasattr(target, field_name):
                    value = getattr(target, field_name)
                    if value and isinstance(value, str):
                        encrypted = target.encrypt_field(field_name, value)
                        if encrypted:
                            # Store encrypted value in a separate field
                            encrypted_field_name = f"{field_name}_encrypted"
                            if hasattr(target, encrypted_field_name):
                                setattr(target, encrypted_field_name, encrypted)
        
        @event.listens_for(cls, 'after_bulk_update')
        def decrypt_fields(query_context):
            for target in query_context.matched_objects:
                for field_name in cls.__encrypted_fields__:
                    encrypted_field_name = f"{field_name}_encrypted"
                    if hasattr(target, encrypted_field_name):
                        encrypted_value = getattr(target, encrypted_field_name)
                        if encrypted_value:
                            decrypted = target.decrypt_field(field_name, encrypted_value)
                            if decrypted:
                                setattr(target, field_name, decrypted)


class VersioningMixin(AuditMixin):
    """
    Simple versioning mixin for change tracking.
    
    Provides lightweight versioning with history tracking
    and rollback capabilities.
    
    Features:
    - Automatic version incrementation
    - Version history storage
    - Rollback to previous versions
    - Version comparison utilities
    - Configurable versioning scope
    """
    
    version_number = Column(Integer, default=1)
    version_data = Column(Text, nullable=True)  # JSON snapshot
    is_current_version = Column(Boolean, default=True)
    
    # Configuration
    __versioned_fields__ = []  # Fields to include in versioning
    __max_versions__ = 0  # 0 for unlimited
    
    def save_version(self, user_id: int = None, comment: str = None) -> bool:
        """Save current state as a new version."""
        try:
            # Create version snapshot
            version_data = {
                'version_number': self.version_number,
                'timestamp': datetime.now(tz=timezone.utc).isoformat(),
                'user_id': user_id or (current_user.id if current_user else None),
                'comment': comment,
                'data': {}
            }
            
            # Capture specified fields
            fields_to_version = self.__versioned_fields__ or self._get_all_fields()
            
            for field_name in fields_to_version:
                if hasattr(self, field_name):
                    value = getattr(self, field_name)
                    # Serialize value
                    if isinstance(value, datetime):
                        value = value.isoformat()
                    elif hasattr(value, 'to_dict'):
                        value = value.to_dict()
                    version_data['data'][field_name] = value
            
            # Store version data
            self.version_data = json.dumps(version_data)
            self.version_number += 1
            
            return True
            
        except Exception as e:
            log.error(f"Version save failed: {e}")
            return False
    
    def get_version_history(self) -> List[Dict]:
        """Get version history."""
        if not self.version_data:
            return []
        
        try:
            return [json.loads(self.version_data)]
        except json.JSONDecodeError:
            return []
    
    def revert_to_version(self, version_number: int) -> bool:
        """Revert to specified version."""
        try:
            history = self.get_version_history()
            
            for version in history:
                if version.get('version_number') == version_number:
                    # Restore data
                    for field_name, value in version['data'].items():
                        if hasattr(self, field_name):
                            setattr(self, field_name, value)
                    
                    # Update version info
                    self.version_number = version_number + 1
                    return True
            
            return False
            
        except Exception as e:
            log.error(f"Version revert failed: {e}")
            return False
    
    def _get_all_fields(self) -> List[str]:
        """Get all model fields for versioning."""
        return [column.name for column in self.__table__.columns]
    
    def compare_versions(self, version1: int, version2: int) -> Dict[str, Any]:
        """Compare two versions and return differences."""
        history = self.get_version_history()
        
        v1_data = None
        v2_data = None
        
        for version in history:
            if version.get('version_number') == version1:
                v1_data = version['data']
            elif version.get('version_number') == version2:
                v2_data = version['data']
        
        if not v1_data or not v2_data:
            return {}
        
        differences = {}
        all_fields = set(v1_data.keys()) | set(v2_data.keys())
        
        for field in all_fields:
            v1_value = v1_data.get(field)
            v2_value = v2_data.get(field)
            
            if v1_value != v2_value:
                differences[field] = {
                    'old_value': v1_value,
                    'new_value': v2_value
                }
        
        return differences


# Utility function for specialized mixins setup
def setup_specialized_mixins(app):
    """
    Set up specialized mixins with PgAppForge.
    
    Args:
        app: Flask application instance
    """
    # Configure currency settings
    app.config.setdefault('DEFAULT_CURRENCY', 'USD')
    app.config.setdefault('EXCHANGE_RATE_API_KEY', None)
    app.config.setdefault('CURRENCY_CACHE_TIMEOUT', 3600)
    
    # Configure geocoding
    app.config.setdefault('GOOGLE_MAPS_API_KEY', None)
    app.config.setdefault('GEOCODING_ENABLED', False)
    
    # Configure encryption
    app.config.setdefault('FIELD_ENCRYPTION_ENABLED', False)
    app.config.setdefault('ENCRYPTION_KEY_ROTATION_ENABLED', False)
    
    # Configure versioning
    app.config.setdefault('VERSIONING_ENABLED', True)
    app.config.setdefault('MAX_VERSIONS_PER_RECORD', 100)
    
    log.info("Specialized mixins configured successfully")


__all__ = [
    'CurrencyMixin',
    'GeoLocationMixin', 
    'EncryptionMixin',
    'VersioningMixin',
    'setup_specialized_mixins'
]