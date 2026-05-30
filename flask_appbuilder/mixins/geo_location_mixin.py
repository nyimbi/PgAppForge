"""
geo_location_mixin.py

GeoLocationMixin for SQLAlchemy models in Flask-AppBuilder applications.
Stores geographic coordinates, performs distance calculations, and supports
geospatial queries via PostGIS (optional) or pure-Python fallbacks.

Hard dependencies: geoalchemy2, shapely, geopy (PostGIS path)
Soft dependency: PostGIS-enabled PostgreSQL for spatial index and ST_* queries.
Pure-Python haversine and bounding-box helpers work without any spatial DB.

Author: Nyimbi Odero
Version: 2.0 (SQLAlchemy 2.x, Python 3.12+)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Column, Float, Index, func
from sqlalchemy.ext.declarative import declared_attr

# ---------------------------------------------------------------------------
# Optional GeoAlchemy2 / Shapely / geopy — degrade gracefully when absent
# ---------------------------------------------------------------------------
try:
	from geoalchemy2 import Geometry
	from geoalchemy2.shape import from_shape
	from shapely.geometry import Point

	_GEOALCHEMY2_AVAILABLE = True
except ImportError:
	_GEOALCHEMY2_AVAILABLE = False
	Geometry = None  # type: ignore[assignment,misc]

try:
	from geopy.distance import geodesic
	from geopy.exc import GeocoderServiceError, GeocoderTimedOut
	from geopy.geocoders import Nominatim

	_GEOPY_AVAILABLE = True
except ImportError:
	_GEOPY_AVAILABLE = False

# ---------------------------------------------------------------------------
# SQLAlchemy 2.x Mapped / mapped_column — fall back to Column for 1.x
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.orm import Mapped, mapped_column

	_SA2 = True
except ImportError:
	_SA2 = False

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
	"""Timezone-aware UTC datetime (replaces deprecated datetime.utcnow())."""
	return datetime.now(tz=timezone.utc)


class GeoLocationMixin:
	"""
	Mixin that adds geographic coordinates, PostGIS geometry, and spatial query
	helpers to any Flask-AppBuilder / SQLAlchemy model.

	Columns added
	-------------
	latitude  : Float(9)   – decimal degrees, -90 … 90
	longitude : Float(9)   – decimal degrees, -180 … 180
	location  : Geometry   – PostGIS POINT (SRID 4326); None when GeoAlchemy2 absent
	altitude  : Float(6)   – metres above sea level (optional)
	accuracy  : Float(6)   – accuracy radius in metres (optional)
	geo_timestamp : Float  – UTC timestamp of last coordinate fix

	Indexes (created via __declare_last__)
	---------------------------------------
	- GIST spatial index on *location* (PostGIS)
	- Composite B-tree on (latitude, longitude)
	"""

	# ------------------------------------------------------------------
	# Column declarations
	# ------------------------------------------------------------------

	@declared_attr
	def latitude(cls):
		"""Latitude in decimal degrees, range -90 to 90."""
		return Column(
			Float(precision=9),
			nullable=True,
			default=0.0,
			info={
				"label": "Latitude",
				"validators": [lambda x: -90 <= x <= 90 if x is not None else True],
			},
		)

	@declared_attr
	def longitude(cls):
		"""Longitude in decimal degrees, range -180 to 180."""
		return Column(
			Float(precision=9),
			nullable=True,
			default=0.0,
			info={
				"label": "Longitude",
				"validators": [lambda x: -180 <= x <= 180 if x is not None else True],
			},
		)

	@declared_attr
	def location(cls):
		"""PostGIS geometry point with spatial index (None when GeoAlchemy2 absent)."""
		if _GEOALCHEMY2_AVAILABLE:
			return Column(
				Geometry(geometry_type="POINT", srid=4326, spatial_index=True),
				nullable=True,
			)
		# Fallback: store as two separate floats (latitude/longitude); no geometry col.
		return None  # type: ignore[return-value]

	@declared_attr
	def altitude(cls):
		"""Optional altitude in metres above sea level."""
		return Column(Float(precision=6), nullable=True, info={"label": "Altitude (m)"})

	@declared_attr
	def accuracy(cls):
		"""Optional accuracy radius in metres."""
		return Column(Float(precision=6), nullable=True, info={"label": "Accuracy (m)"})

	@declared_attr
	def geo_timestamp(cls):
		"""UTC timestamp (stored as float epoch) of the last coordinate fix."""
		return Column(Float, nullable=True, info={"label": "Geo Timestamp"})

	# ------------------------------------------------------------------
	# Declarative hooks
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""Register indexes and before-save event listener after mapping."""
		from sqlalchemy import event

		if _GEOALCHEMY2_AVAILABLE:
			Index(
				f"idx_{cls.__tablename__}_location",
				cls.location,
				postgresql_using="gist",
			)

		Index(f"idx_{cls.__tablename__}_lat_long", cls.latitude, cls.longitude)

		@event.listens_for(cls, "before_insert")
		@event.listens_for(cls, "before_update")
		def _sync_geometry(mapper, connection, instance) -> None:
			"""Keep PostGIS geometry column in sync with lat/lon fields."""
			if instance.latitude is None or instance.longitude is None:
				return
			try:
				if not (-90 <= instance.latitude <= 90):
					raise ValueError(f"Invalid latitude: {instance.latitude}")
				if not (-180 <= instance.longitude <= 180):
					raise ValueError(f"Invalid longitude: {instance.longitude}")
				if _GEOALCHEMY2_AVAILABLE:
					point = Point(instance.longitude, instance.latitude)
					instance.location = from_shape(point, srid=4326)
				instance.geo_timestamp = _utcnow().timestamp()
			except Exception:
				logger.exception("Error syncing geometry for %s", cls.__name__)
				raise

	# ------------------------------------------------------------------
	# Instance helpers
	# ------------------------------------------------------------------

	def set_coordinates(
		self,
		latitude: float,
		longitude: float,
		altitude: float | None = None,
		accuracy: float | None = None,
	) -> None:
		"""
		Set geographic coordinates on this instance.

		Raises ValueError for out-of-range inputs. Updates the PostGIS
		geometry column when GeoAlchemy2 is available.
		"""
		if not (-90 <= latitude <= 90):
			raise ValueError(f"Invalid latitude: {latitude}")
		if not (-180 <= longitude <= 180):
			raise ValueError(f"Invalid longitude: {longitude}")

		self.latitude = latitude
		self.longitude = longitude
		self.altitude = altitude
		self.accuracy = accuracy
		self.geo_timestamp = _utcnow().timestamp()

		if _GEOALCHEMY2_AVAILABLE:
			point = Point(longitude, latitude)
			self.location = from_shape(point, srid=4326)

	def distance_to(
		self,
		other: tuple[float, float] | Any,
		method: str = "geodesic",
	) -> float:
		"""
		Distance in kilometres to *other* (another mixin instance or a
		(latitude, longitude) tuple).

		Methods
		-------
		geodesic  : geopy WGS-84 ellipsoid (most accurate; requires geopy)
		haversine : great-circle via stdlib math (no external dep)
		postgis   : returns a SQLAlchemy expression for use in queries
		"""
		if isinstance(other, tuple):
			other_lat, other_lon = other
		else:
			other_lat, other_lon = other.latitude, other.longitude

		if not (-90 <= other_lat <= 90):
			raise ValueError(f"Invalid latitude: {other_lat}")
		if not (-180 <= other_lon <= 180):
			raise ValueError(f"Invalid longitude: {other_lon}")

		if method == "geodesic":
			if not _GEOPY_AVAILABLE:
				raise RuntimeError("geopy is required for method='geodesic'")
			return geodesic(
				(self.latitude, self.longitude), (other_lat, other_lon)
			).kilometers

		if method == "haversine":
			return self.haversine_distance(
				self.latitude, self.longitude, other_lat, other_lon
			)

		if method == "postgis":
			if not _GEOALCHEMY2_AVAILABLE:
				raise RuntimeError("geoalchemy2 is required for method='postgis'")
			if not getattr(self, "location", None):
				raise ValueError("PostGIS location not set on this instance")
			# Returns a SQLAlchemy column expression (metres → km)
			return (
				func.ST_Distance(
					func.ST_Transform(self.location, 3857),
					func.ST_Transform(
						func.ST_SetSRID(
							func.ST_MakePoint(other_lon, other_lat), 4326
						),
						3857,
					),
				)
				/ 1000
			)

		raise ValueError(f"Unknown distance method: {method!r}")

	def to_geojson(self, include_props: bool = True) -> dict[str, Any]:
		"""
		Serialize this instance as a GeoJSON Feature dict.

		Raises ValueError when coordinates are not set.
		"""
		if self.latitude is None or self.longitude is None:
			raise ValueError("Instance is missing coordinates")

		geo_ts = self.geo_timestamp
		ts_iso: str | None = (
			datetime.fromtimestamp(geo_ts, tz=timezone.utc).isoformat()
			if geo_ts is not None
			else None
		)

		feature: dict[str, Any] = {
			"type": "Feature",
			"geometry": {
				"type": "Point",
				"coordinates": [self.longitude, self.latitude],
			},
			"properties": {
				"id": getattr(self, "id", None),
				"altitude": self.altitude,
				"accuracy": self.accuracy,
				"timestamp": ts_iso,
			},
		}

		if include_props:
			_skip = {"latitude", "longitude", "location", "altitude", "accuracy", "geo_timestamp"}
			for key, value in self.__dict__.items():
				if not key.startswith("_") and key not in _skip:
					feature["properties"][key] = value

		return feature

	# ------------------------------------------------------------------
	# Class-level helpers
	# ------------------------------------------------------------------

	@classmethod
	def from_geojson(cls, feature: dict[str, Any]) -> "GeoLocationMixin":
		"""
		Construct an instance from a GeoJSON Feature dict.

		Raises ValueError for malformed input.
		"""
		if not isinstance(feature, dict):
			raise ValueError("Invalid GeoJSON: expected a dict")
		if feature.get("type") != "Feature":
			raise ValueError("Invalid GeoJSON: 'type' must be 'Feature'")

		geometry = feature.get("geometry") or {}
		if geometry.get("type") != "Point":
			raise ValueError("Invalid GeoJSON: geometry type must be 'Point'")

		coords = geometry.get("coordinates", [])
		if len(coords) < 2:
			raise ValueError("Invalid GeoJSON: coordinates require at least [lon, lat]")

		instance = cls()
		instance.set_coordinates(
			latitude=coords[1],
			longitude=coords[0],
			altitude=coords[2] if len(coords) > 2 else None,
		)

		for key, value in (feature.get("properties") or {}).items():
			if hasattr(instance, key):
				setattr(instance, key, value)

		return instance

	@classmethod
	def get_by_coordinates(
		cls,
		session,
		latitude: float,
		longitude: float,
		distance_km: float = 1.0,
		limit: int | None = None,
		order_by_distance: bool = True,
	) -> list[Any]:
		"""
		Find instances within *distance_km* kilometres of the given point.

		Uses ST_Distance on the EPSG:3857 (web-mercator) projection for
		metric distance filtering, then optionally orders by geographic
		distance from the centre. Requires PostGIS + GeoAlchemy2.
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			raise RuntimeError("geoalchemy2 + PostGIS required for get_by_coordinates")
		if not (-90 <= latitude <= 90):
			raise ValueError(f"Invalid latitude: {latitude}")
		if not (-180 <= longitude <= 180):
			raise ValueError(f"Invalid longitude: {longitude}")
		if distance_km <= 0:
			raise ValueError(f"distance_km must be positive, got {distance_km}")

		from sqlalchemy import select

		centre = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), 4326)
		distance_m = distance_km * 1000

		stmt = select(cls).where(
			func.ST_Distance(
				func.ST_Transform(cls.location, 3857),
				func.ST_Transform(centre, 3857),
			)
			<= distance_m
		)

		if order_by_distance:
			stmt = stmt.order_by(func.ST_Distance(cls.location, centre))

		if limit is not None:
			stmt = stmt.limit(limit)

		return list(session.execute(stmt).scalars())

	@classmethod
	def get_by_bounding_box(
		cls,
		session,
		min_lat: float,
		min_lon: float,
		max_lat: float,
		max_lon: float,
	) -> list[Any]:
		"""
		Find all instances whose PostGIS geometry falls within the bounding box.

		Requires PostGIS + GeoAlchemy2.
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			raise RuntimeError("geoalchemy2 + PostGIS required for get_by_bounding_box")
		if not all(-90 <= lat <= 90 for lat in (min_lat, max_lat)):
			raise ValueError("Latitude values must be in [-90, 90]")
		if not all(-180 <= lon <= 180 for lon in (min_lon, max_lon)):
			raise ValueError("Longitude values must be in [-180, 180]")

		from sqlalchemy import select

		bbox = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, 4326)
		stmt = select(cls).where(func.ST_Within(cls.location, bbox))
		return list(session.execute(stmt).scalars())

	@classmethod
	def geocode_address(
		cls,
		address: str,
		timeout: int = 10,
		exactly_one: bool = True,
	) -> tuple[float, float] | None:
		"""
		Forward-geocode *address* → (latitude, longitude) via Nominatim.

		Returns None when no result is found.
		Raises GeocoderTimedOut / GeocoderServiceError on service failure.
		"""
		if not _GEOPY_AVAILABLE:
			raise RuntimeError("geopy is required for geocode_address")
		try:
			geolocator = Nominatim(user_agent="flask-appbuilder")
			loc = geolocator.geocode(address, timeout=timeout, exactly_one=exactly_one)
			if loc:
				return loc.latitude, loc.longitude
			return None
		except (GeocoderTimedOut, GeocoderServiceError):
			logger.exception("Geocoding failed for %r", address)
			raise

	@classmethod
	def reverse_geocode(
		cls,
		latitude: float,
		longitude: float,
		timeout: int = 10,
		language: str = "en",
	) -> str | None:
		"""
		Reverse-geocode (latitude, longitude) → address string via Nominatim.

		Returns None when no result is found.
		"""
		if not _GEOPY_AVAILABLE:
			raise RuntimeError("geopy is required for reverse_geocode")
		if not (-90 <= latitude <= 90):
			raise ValueError(f"Invalid latitude: {latitude}")
		if not (-180 <= longitude <= 180):
			raise ValueError(f"Invalid longitude: {longitude}")

		try:
			geolocator = Nominatim(user_agent="flask-appbuilder")
			loc = geolocator.reverse(
				f"{latitude}, {longitude}", timeout=timeout, language=language
			)
			return loc.address if loc else None
		except (GeocoderTimedOut, GeocoderServiceError):
			logger.exception("Reverse geocoding failed for (%s, %s)", latitude, longitude)
			raise

	@classmethod
	def get_bounding_box(
		cls,
		center_lat: float,
		center_lon: float,
		distance_km: float,
	) -> tuple[float, float, float, float]:
		"""
		Approximate bounding box around a centre point.

		Returns (min_lat, min_lon, max_lat, max_lon). Handles polar clamping
		and 180° meridian wraparound for the longitude extent.
		"""
		if not (-90 <= center_lat <= 90):
			raise ValueError(f"Invalid latitude: {center_lat}")
		if not (-180 <= center_lon <= 180):
			raise ValueError(f"Invalid longitude: {center_lon}")
		if distance_km <= 0:
			raise ValueError(f"distance_km must be positive, got {distance_km}")

		lat_change = distance_km / 111.32
		cos_lat = math.cos(math.radians(center_lat))
		lon_change = distance_km / (111.32 * cos_lat) if cos_lat > 1e-10 else 180.0

		min_lat = max(center_lat - lat_change, -90.0)
		max_lat = min(center_lat + lat_change, 90.0)
		min_lon = center_lon - lon_change
		max_lon = center_lon + lon_change

		# Normalise to [-180, 180]
		if min_lon < -180:
			min_lon += 360
		if max_lon > 180:
			max_lon -= 360

		return (min_lat, min_lon, max_lat, max_lon)

	# ------------------------------------------------------------------
	# Pure-Python distance (no external deps)
	# ------------------------------------------------------------------

	@staticmethod
	def haversine_distance(
		lat1: float,
		lon1: float,
		lat2: float,
		lon2: float,
	) -> float:
		"""
		Great-circle distance between two WGS-84 points using the haversine
		formula. Returns kilometres. No external dependencies.
		"""
		if not all(-90 <= lat <= 90 for lat in (lat1, lat2)):
			raise ValueError("Latitude values must be in [-90, 90]")
		if not all(-180 <= lon <= 180 for lon in (lon1, lon2)):
			raise ValueError("Longitude values must be in [-180, 180]")

		R = 6_371.0  # Earth mean radius, km
		dlat = math.radians(lat2 - lat1)
		dlon = math.radians(lon2 - lon1)
		a = (
			math.sin(dlat / 2) ** 2
			+ math.cos(math.radians(lat1))
			* math.cos(math.radians(lat2))
			* math.sin(dlon / 2) ** 2
		)
		return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
