"""
geo_location_mixin.py

GeoLocationMixin for SQLAlchemy models in Flask-AppBuilder applications.

Provides first-class PostGIS support via GeoAlchemy2 with graceful fallback to
plain Float columns (lat/lon) when PostGIS is absent. Supports both GEOMETRY
and GEOGRAPHY column types, a full suite of ST_* function helpers, spatial
indexes (GiST for geometry, SP-GiST for geography), bounding-box queries, and
KNN ordering.

Hard dependencies (PostGIS path): geoalchemy2, shapely
Soft dependency: geopy (geocoding helpers only)
Fallback: pure-Python haversine + bounding-box work with any RDBMS.

Author: Nyimbi Odero
Version: 3.0 (SQLAlchemy 2.x, Python 3.12+, PostGIS-first)
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import Column, Float, Index, Integer, String, Text, event, func, text
from sqlalchemy.orm import declared_attr

if TYPE_CHECKING:
	from sqlalchemy.orm import Session

# ---------------------------------------------------------------------------
# Optional GeoAlchemy2 / Shapely — degrade gracefully when absent
# ---------------------------------------------------------------------------
try:
	from geoalchemy2 import Geography, Geometry
	from geoalchemy2.functions import (
		ST_AsGeoJSON,
		ST_Buffer,
		ST_Contains,
		ST_Covers,
		ST_DWithin,
		ST_Distance,
		ST_Envelope,
		ST_GeogFromText,
		ST_GeomFromText,
		ST_Intersects,
		ST_MakeEnvelope,
		ST_MakePoint,
		ST_SetSRID,
		ST_Transform,
		ST_Within,
	)
	from geoalchemy2.shape import from_shape, to_shape

	try:
		from shapely.geometry import Point, Polygon, mapping, shape
		_SHAPELY_AVAILABLE = True
	except ImportError:
		_SHAPELY_AVAILABLE = False

	_GEOALCHEMY2_AVAILABLE = True
except ImportError:
	_GEOALCHEMY2_AVAILABLE = False
	_SHAPELY_AVAILABLE = False
	Geography = None  # type: ignore[assignment,misc]
	Geometry = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Optional geopy — geocoding only, never used in model/query paths
# ---------------------------------------------------------------------------
try:
	from geopy.distance import geodesic as _geodesic
	from geopy.exc import GeocoderServiceError, GeocoderTimedOut
	from geopy.geocoders import Nominatim

	_GEOPY_AVAILABLE = True
except ImportError:
	_GEOPY_AVAILABLE = False

# ---------------------------------------------------------------------------
# SQLAlchemy 2.x Mapped / mapped_column
# ---------------------------------------------------------------------------
try:
	from sqlalchemy.orm import Mapped, mapped_column

	_SA2 = True
except ImportError:
	_SA2 = False

logger = logging.getLogger(__name__)

# EPSG codes used throughout
_SRID_WGS84 = 4326   # geographic CRS: degrees lat/lon
_SRID_MERCATOR = 3857  # web-mercator: metres (used for metric ST_Distance)

# Earth mean radius in km (IUGG)
_EARTH_RADIUS_KM = 6_371.0088


def _utcnow() -> datetime:
	"""Timezone-aware UTC datetime (avoids deprecated datetime.now(tz=timezone.utc))."""
	return datetime.now(tz=timezone.utc)


def _validate_lat(v: float, name: str = "latitude") -> None:
	if not (-90.0 <= v <= 90.0):
		raise ValueError(f"{name} must be in [-90, 90], got {v!r}")


def _validate_lon(v: float, name: str = "longitude") -> None:
	if not (-180.0 <= v <= 180.0):
		raise ValueError(f"{name} must be in [-180, 180], got {v!r}")


def _make_wkb_point(lon: float, lat: float, srid: int = _SRID_WGS84):
	"""Return a GeoAlchemy2 WKBElement for a 2-D point."""
	if not _GEOALCHEMY2_AVAILABLE or not _SHAPELY_AVAILABLE:
		raise RuntimeError("geoalchemy2 and shapely are required for PostGIS operations")
	return from_shape(Point(lon, lat), srid=srid)


class GeoLocationMixin:
	"""
	SQLAlchemy declarative mixin adding PostGIS-backed geospatial capabilities
	to Flask-AppBuilder models.

	Column layout
	-------------
	latitude      Float(9)      – WGS-84 decimal degrees, -90 … 90
	longitude     Float(9)      – WGS-84 decimal degrees, -180 … 180
	altitude      Float(6)      – metres above WGS-84 ellipsoid (optional)
	accuracy_m    Float(6)      – horizontal accuracy radius in metres (optional)
	geo_timestamp Float         – Unix epoch (seconds) of last fix
	address_text  Text          – reverse-geocoded human-readable address (optional)

	PostGIS columns (present only when GeoAlchemy2 is installed)
	-------------------------------------------------------------
	geom          Geometry(POINT, 4326)    – GEOMETRY column, GiST indexed
	geog          Geography(POINT, 4326)   – GEOGRAPHY column, enables native
	                                         metric ST_DWithin / ST_Distance
	                                         without EPSG:3857 projection

	Indexes
	-------
	GiST  on geom  (PostGIS geometry index — fast bounding-box + KNN)
	GiST  on geog  (PostGIS geography index — great-circle metric queries)
	BTree on (latitude, longitude) — fallback for non-PostGIS deployments

	Key query class-methods
	-----------------------
	find_within_radius()   – DWithin / haversine radius search
	find_in_bbox()         – ST_Within / coordinate range scan
	find_knn()             – K-nearest-neighbour (KNN) ORDER BY <-> operator
	find_intersecting()    – ST_Intersects polygon/geometry filter
	cluster_by_grid()      – server-side grid clustering via ST_SnapToGrid
	extent()               – ST_Extent bounding box of entire result set

	Instance helpers
	----------------
	set_coordinates()      – validated coordinate setter, syncs PostGIS columns
	distance_to()          – point-to-point distance (geodesic / haversine / ST_)
	to_geojson()           – GeoJSON Feature dict
	as_shapely()           – Shapely Point (requires shapely)
	buffer_geom()          – ST_Buffer expression around this point

	Class helpers
	-------------
	from_geojson()         – construct instance from GeoJSON Feature dict
	haversine_distance()   – static great-circle distance (no external deps)
	get_bounding_box()     – approximate bbox around a centre point
	geocode_address()      – forward geocoding via Nominatim (requires geopy)
	reverse_geocode()      – reverse geocoding via Nominatim (requires geopy)
	"""

	# ------------------------------------------------------------------
	# Scalar coordinate columns — always present, any RDBMS
	# ------------------------------------------------------------------

	@declared_attr
	def latitude(cls) -> Column:
		"""WGS-84 latitude in decimal degrees, range -90 to 90."""
		return Column(
			Float(precision=9),
			nullable=True,
			default=None,
			info={"label": "Latitude", "description": "Decimal degrees, WGS-84"},
		)

	@declared_attr
	def longitude(cls) -> Column:
		"""WGS-84 longitude in decimal degrees, range -180 to 180."""
		return Column(
			Float(precision=9),
			nullable=True,
			default=None,
			info={"label": "Longitude", "description": "Decimal degrees, WGS-84"},
		)

	@declared_attr
	def altitude(cls) -> Column:
		"""Altitude in metres above the WGS-84 ellipsoid (optional)."""
		return Column(
			Float(precision=6),
			nullable=True,
			info={"label": "Altitude (m)"},
		)

	@declared_attr
	def accuracy_m(cls) -> Column:
		"""Horizontal accuracy radius in metres (optional)."""
		return Column(
			Float(precision=6),
			nullable=True,
			info={"label": "Accuracy (m)"},
		)

	@declared_attr
	def geo_timestamp(cls) -> Column:
		"""Unix epoch seconds of the most recent coordinate fix."""
		return Column(Float, nullable=True, info={"label": "Geo Timestamp (epoch)"})

	@declared_attr
	def address_text(cls) -> Column:
		"""Human-readable address from reverse geocoding (TEXT, optional)."""
		return Column(Text, nullable=True, info={"label": "Address"})

	# ------------------------------------------------------------------
	# PostGIS GEOMETRY column — indexed with GiST
	# ------------------------------------------------------------------

	@declared_attr
	def geom(cls):
		"""
		PostGIS GEOMETRY(POINT, 4326) column.

		Use for 2-D spatial queries that benefit from planar operators
		(ST_Within, ST_Intersects, ST_Buffer, ST_Envelope, KNN <->).
		A GiST index is declared in __declare_last__.

		Returns None silently when GeoAlchemy2 is not installed.
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			return None  # type: ignore[return-value]
		return Column(
			Geometry(geometry_type="POINT", srid=_SRID_WGS84, spatial_index=False),
			nullable=True,
			info={"label": "Geometry (PostGIS)"},
		)

	# ------------------------------------------------------------------
	# PostGIS GEOGRAPHY column — native great-circle metric queries
	# ------------------------------------------------------------------

	@declared_attr
	def geog(cls):
		"""
		PostGIS GEOGRAPHY(POINT, 4326) column.

		Geography columns store data on the spheroid and natively return
		distances in metres without requiring a projection transform.
		Use for ST_DWithin and ST_Distance when metric accuracy matters and
		the search radius is large (> tens of km).

		A GiST index is declared in __declare_last__.

		Returns None silently when GeoAlchemy2 is not installed.
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			return None  # type: ignore[return-value]
		return Column(
			Geography(geometry_type="POINT", srid=_SRID_WGS84),
			nullable=True,
			info={"label": "Geography (PostGIS)"},
		)

	# ------------------------------------------------------------------
	# Declarative hook — indexes + event listeners
	# ------------------------------------------------------------------

	@classmethod
	def __declare_last__(cls) -> None:
		"""
		Called after mapper configuration is complete.

		Registers:
		- GiST index on geom (PostGIS geometry index)
		- GiST index on geog (PostGIS geography index)
		- Composite BTree on (latitude, longitude) for fallback queries
		- before_insert / before_update event to sync PostGIS columns
		"""
		tbl = cls.__tablename__

		if _GEOALCHEMY2_AVAILABLE:
			# Geometry GiST — supports bounding-box, KNN, ST_Within, etc.
			Index(
				f"idx_{tbl}_geom_gist",
				cls.geom,
				postgresql_using="gist",
			)
			# Geography GiST — supports great-circle metric ST_DWithin natively
			Index(
				f"idx_{tbl}_geog_gist",
				cls.geog,
				postgresql_using="gist",
			)

		# Always create a composite BTree — useful on non-PostGIS deployments
		# and as a covering index for coordinate range scans.
		Index(f"idx_{tbl}_lat_lon", cls.latitude, cls.longitude)

		@event.listens_for(cls, "before_insert")
		@event.listens_for(cls, "before_update")
		def _sync_postgis(mapper, connection, instance) -> None:
			"""Keep geom/geog columns in sync with latitude/longitude scalars."""
			lat = instance.latitude
			lon = instance.longitude
			if lat is None or lon is None:
				return
			try:
				_validate_lat(lat)
				_validate_lon(lon)
				if _GEOALCHEMY2_AVAILABLE and _SHAPELY_AVAILABLE:
					wkb = _make_wkb_point(lon, lat)
					instance.geom = wkb
					instance.geog = wkb
				instance.geo_timestamp = _utcnow().timestamp()
			except Exception:
				logger.exception(
					"Error syncing PostGIS columns for %s", cls.__name__
				)
				raise

	# ------------------------------------------------------------------
	# Instance helpers
	# ------------------------------------------------------------------

	def set_coordinates(
		self,
		latitude: float,
		longitude: float,
		altitude: float | None = None,
		accuracy_m: float | None = None,
		address_text: str | None = None,
	) -> None:
		"""
		Set geographic coordinates on this instance with full validation.

		Syncs the PostGIS geom/geog columns immediately when GeoAlchemy2
		and Shapely are available. The ORM before_insert/before_update
		listener will also re-sync on flush, so both paths are covered.

		Raises
		------
		ValueError  – coordinate out of valid WGS-84 range
		"""
		_validate_lat(latitude)
		_validate_lon(longitude)

		self.latitude = latitude
		self.longitude = longitude
		self.altitude = altitude
		self.accuracy_m = accuracy_m
		self.geo_timestamp = _utcnow().timestamp()

		if address_text is not None:
			self.address_text = address_text

		if _GEOALCHEMY2_AVAILABLE and _SHAPELY_AVAILABLE:
			wkb = _make_wkb_point(longitude, latitude)
			self.geom = wkb
			self.geog = wkb

	def distance_to(
		self,
		other: tuple[float, float] | Any,
		method: str = "haversine",
	) -> float:
		"""
		Distance from this instance to *other* in kilometres.

		Parameters
		----------
		other   : (lat, lon) tuple or another GeoLocationMixin instance
		method  : 'haversine'  — stdlib math, no deps (default)
		          'geodesic'   — geopy WGS-84 ellipsoid, most accurate
		          'geography'  — returns a SQLAlchemy ST_Distance expression
		                        (metres, uses GEOGRAPHY column on spheroid)
		          'geometry'   — returns a SQLAlchemy ST_Distance expression
		                        (metres, projects to EPSG:3857 for metric)

		Returns
		-------
		float   – kilometres (haversine / geodesic paths)
		ColumnElement – for 'geography' / 'geometry' paths (use in query)
		"""
		if isinstance(other, tuple):
			other_lat, other_lon = other
		else:
			other_lat, other_lon = other.latitude, other.longitude

		_validate_lat(float(other_lat), "other latitude")
		_validate_lon(float(other_lon), "other longitude")

		if method == "haversine":
			return self.haversine_distance(
				self.latitude, self.longitude, other_lat, other_lon
			)

		if method == "geodesic":
			if not _GEOPY_AVAILABLE:
				raise RuntimeError("geopy is required for method='geodesic'")
			return _geodesic(
				(self.latitude, self.longitude), (other_lat, other_lon)
			).kilometers

		if method == "geography":
			if not _GEOALCHEMY2_AVAILABLE:
				raise RuntimeError("geoalchemy2 is required for method='geography'")
			if self.geog is None:
				raise ValueError("PostGIS geography column not populated on this instance")
			other_geog = func.ST_GeogFromText(
				f"SRID={_SRID_WGS84};POINT({other_lon} {other_lat})"
			)
			# ST_Distance on geography returns metres
			return func.ST_Distance(self.geog, other_geog)

		if method == "geometry":
			if not _GEOALCHEMY2_AVAILABLE:
				raise RuntimeError("geoalchemy2 is required for method='geometry'")
			if self.geom is None:
				raise ValueError("PostGIS geometry column not populated on this instance")
			other_geom = func.ST_SetSRID(
				func.ST_MakePoint(other_lon, other_lat), _SRID_WGS84
			)
			# Project to web-mercator for metric distance
			return (
				func.ST_Distance(
					func.ST_Transform(self.geom, _SRID_MERCATOR),
					func.ST_Transform(other_geom, _SRID_MERCATOR),
				)
			)

		raise ValueError(f"Unknown distance method: {method!r}")

	def to_geojson(self, include_props: bool = True) -> dict[str, Any]:
		"""
		Serialize this instance as a GeoJSON Feature dict (RFC 7946).

		Raises ValueError when coordinates are not set.
		"""
		if self.latitude is None or self.longitude is None:
			raise ValueError("Instance is missing coordinates; cannot build GeoJSON")

		geo_ts = self.geo_timestamp
		ts_iso: str | None = (
			datetime.fromtimestamp(geo_ts, tz=timezone.utc).isoformat()
			if geo_ts is not None
			else None
		)

		coords: list[float] = [float(self.longitude), float(self.latitude)]
		if self.altitude is not None:
			coords.append(float(self.altitude))

		feature: dict[str, Any] = {
			"type": "Feature",
			"geometry": {"type": "Point", "coordinates": coords},
			"properties": {
				"id": getattr(self, "id", None),
				"altitude": self.altitude,
				"accuracy_m": self.accuracy_m,
				"timestamp": ts_iso,
				"address": self.address_text,
			},
		}

		if include_props:
			_skip = frozenset(
				{
					"latitude",
					"longitude",
					"geom",
					"geog",
					"altitude",
					"accuracy_m",
					"geo_timestamp",
					"address_text",
				}
			)
			for key, value in self.__dict__.items():
				if not key.startswith("_") and key not in _skip:
					feature["properties"][key] = value

		return feature

	def as_shapely(self):
		"""
		Return a Shapely Point for this instance.

		Requires shapely. Raises ImportError when absent, ValueError when
		coordinates are not set.
		"""
		if not _SHAPELY_AVAILABLE:
			raise ImportError("shapely is required for as_shapely()")
		if self.latitude is None or self.longitude is None:
			raise ValueError("Coordinates not set on this instance")
		return Point(self.longitude, self.latitude)

	def buffer_geom(self, radius_degrees: float):
		"""
		Return a SQLAlchemy ST_Buffer expression around this instance's geom.

		*radius_degrees* is in CRS units (degrees for SRID 4326).
		Use :meth:`find_within_radius` for metric searches instead.

		Requires GeoAlchemy2.
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			raise RuntimeError("geoalchemy2 is required for buffer_geom()")
		if self.geom is None:
			raise ValueError("PostGIS geometry column not populated on this instance")
		return func.ST_Buffer(self.geom, radius_degrees)

	def postgis_as_geojson(self) -> Any:
		"""
		Return a SQLAlchemy ST_AsGeoJSON column expression for use in queries.

		Requires GeoAlchemy2. Example usage::

		    stmt = select(MyModel.id, MyModel.postgis_as_geojson())
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			raise RuntimeError("geoalchemy2 is required for postgis_as_geojson()")
		return func.ST_AsGeoJSON(self.__class__.geom)

	# ------------------------------------------------------------------
	# Class-level query methods
	# ------------------------------------------------------------------

	@classmethod
	def find_within_radius(
		cls,
		session: Session,
		latitude: float,
		longitude: float,
		radius_km: float,
		*,
		use_geography: bool = True,
		order_by_distance: bool = True,
		limit: int | None = None,
	) -> list[Any]:
		"""
		Return all instances within *radius_km* kilometres of the given point.

		Strategy
		--------
		use_geography=True  (default)
		  Uses ST_DWithin on the GEOGRAPHY column. PostgreSQL evaluates
		  this entirely on the spheroid — no projection required. Accurate
		  at any scale; fast with the GiST geography index.

		use_geography=False
		  Projects both geometries to EPSG:3857 (web-mercator) and applies
		  ST_DWithin in metres. Slightly faster at small radii; loses
		  accuracy near poles.

		Requires PostGIS + GeoAlchemy2. Falls back to a haversine-filtered
		coordinate range scan when PostGIS is unavailable.

		Parameters
		----------
		session           – SQLAlchemy session
		latitude          – centre point latitude
		longitude         – centre point longitude
		radius_km         – search radius in kilometres
		use_geography     – True: spheroid ST_DWithin; False: projected 3857
		order_by_distance – include ORDER BY distance (KNN-friendly with GiST)
		limit             – cap the number of returned rows

		Returns
		-------
		list of model instances ordered by ascending distance
		"""
		_validate_lat(latitude)
		_validate_lon(longitude)
		if radius_km <= 0:
			raise ValueError(f"radius_km must be positive, got {radius_km!r}")

		from sqlalchemy import select

		if not _GEOALCHEMY2_AVAILABLE:
			return cls._haversine_radius_scan(
				session, latitude, longitude, radius_km, limit
			)

		radius_m = radius_km * 1_000.0

		if use_geography:
			# GEOGRAPHY path — spheroid, no transform needed
			centre_geog = func.ST_GeogFromText(
				f"SRID={_SRID_WGS84};POINT({longitude} {latitude})"
			)
			stmt = select(cls).where(
				func.ST_DWithin(cls.geog, centre_geog, radius_m)
			)
			if order_by_distance:
				stmt = stmt.order_by(
					func.ST_Distance(cls.geog, centre_geog)
				)
		else:
			# GEOMETRY path — project to EPSG:3857
			centre_geom = func.ST_Transform(
				func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), _SRID_WGS84),
				_SRID_MERCATOR,
			)
			stmt = select(cls).where(
				func.ST_DWithin(
					func.ST_Transform(cls.geom, _SRID_MERCATOR),
					centre_geom,
					radius_m,
				)
			)
			if order_by_distance:
				# KNN distance operator <-> on original SRID for index use
				centre_ref = func.ST_SetSRID(
					func.ST_MakePoint(longitude, latitude), _SRID_WGS84
				)
				stmt = stmt.order_by(cls.geom.op("<->")(centre_ref))

		if limit is not None:
			stmt = stmt.limit(limit)

		return list(session.execute(stmt).scalars())

	@classmethod
	def find_in_bbox(
		cls,
		session: Session,
		min_lat: float,
		min_lon: float,
		max_lat: float,
		max_lon: float,
		*,
		strict: bool = True,
	) -> list[Any]:
		"""
		Return all instances whose location falls inside the given bounding box.

		Parameters
		----------
		session           – SQLAlchemy session
		min_lat, min_lon  – south-west corner
		max_lat, max_lon  – north-east corner
		strict            – True: ST_Within (point strictly inside polygon)
		                    False: ST_Intersects (includes boundary touches)

		PostGIS path uses ST_Within / ST_Intersects against ST_MakeEnvelope.
		Fallback uses scalar coordinate BETWEEN filters.

		Raises ValueError for invalid coordinate ranges.
		"""
		if min_lat >= max_lat:
			raise ValueError(f"min_lat ({min_lat}) must be less than max_lat ({max_lat})")
		if min_lon >= max_lon:
			raise ValueError(f"min_lon ({min_lon}) must be less than max_lon ({max_lon})")
		_validate_lat(min_lat, "min_lat")
		_validate_lat(max_lat, "max_lat")
		_validate_lon(min_lon, "min_lon")
		_validate_lon(max_lon, "max_lon")

		from sqlalchemy import and_, between, select

		if not _GEOALCHEMY2_AVAILABLE:
			stmt = select(cls).where(
				and_(
					between(cls.latitude, min_lat, max_lat),
					between(cls.longitude, min_lon, max_lon),
				)
			)
			return list(session.execute(stmt).scalars())

		envelope = func.ST_MakeEnvelope(min_lon, min_lat, max_lon, max_lat, _SRID_WGS84)
		fn = func.ST_Within if strict else func.ST_Intersects
		stmt = select(cls).where(fn(cls.geom, envelope))
		return list(session.execute(stmt).scalars())

	@classmethod
	def find_knn(
		cls,
		session: Session,
		latitude: float,
		longitude: float,
		k: int = 10,
	) -> list[Any]:
		"""
		K-Nearest-Neighbour query using the PostGIS KNN distance operator <->.

		Unlike ST_DWithin, KNN always returns exactly *k* rows (or fewer if
		the table has fewer rows). The GiST index on geom is used for O(log n)
		traversal, making this efficient even on large tables.

		Requires PostGIS + GeoAlchemy2.

		Parameters
		----------
		session   – SQLAlchemy session
		latitude  – centre latitude
		longitude – centre longitude
		k         – number of nearest neighbours to return
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			raise RuntimeError("geoalchemy2 + PostGIS required for find_knn()")
		_validate_lat(latitude)
		_validate_lon(longitude)
		if k <= 0:
			raise ValueError(f"k must be a positive integer, got {k!r}")

		from sqlalchemy import select

		centre = func.ST_SetSRID(func.ST_MakePoint(longitude, latitude), _SRID_WGS84)
		stmt = (
			select(cls)
			.order_by(cls.geom.op("<->")(centre))
			.limit(k)
		)
		return list(session.execute(stmt).scalars())

	@classmethod
	def find_intersecting(
		cls,
		session: Session,
		wkt_geometry: str,
		srid: int = _SRID_WGS84,
	) -> list[Any]:
		"""
		Return instances whose geom intersects the given WKT geometry.

		*wkt_geometry* may be any PostGIS-parseable WKT string: POLYGON,
		MULTIPOLYGON, LINESTRING, etc. Useful for arbitrary polygon filters
		(admin boundaries, catchment areas, route corridors).

		Requires PostGIS + GeoAlchemy2.

		Example
		-------
		polygon_wkt = "POLYGON((...))"
		results = MyModel.find_intersecting(session, polygon_wkt)
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			raise RuntimeError("geoalchemy2 + PostGIS required for find_intersecting()")

		from sqlalchemy import select

		geom_filter = func.ST_SetSRID(func.ST_GeomFromText(wkt_geometry), srid)
		if srid != _SRID_WGS84:
			geom_filter = func.ST_Transform(geom_filter, _SRID_WGS84)
		stmt = select(cls).where(func.ST_Intersects(cls.geom, geom_filter))
		return list(session.execute(stmt).scalars())

	@classmethod
	def cluster_by_grid(
		cls,
		session: Session,
		cell_size_degrees: float = 0.01,
		*,
		min_lat: float | None = None,
		max_lat: float | None = None,
		min_lon: float | None = None,
		max_lon: float | None = None,
	) -> list[dict[str, Any]]:
		"""
		Server-side grid clustering via ST_SnapToGrid.

		Groups points into grid cells of *cell_size_degrees* and returns
		cluster centroids with counts. Useful for map heatmap / marker
		clustering without materialising all rows client-side.

		Requires PostGIS + GeoAlchemy2.

		Returns
		-------
		List of dicts: {
		    "centroid_lon": float,
		    "centroid_lat": float,
		    "count": int,
		}
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			raise RuntimeError("geoalchemy2 + PostGIS required for cluster_by_grid()")

		from sqlalchemy import and_, select

		snapped = func.ST_SnapToGrid(cls.geom, cell_size_degrees)
		centroid = func.ST_Centroid(snapped)

		stmt = (
			select(
				func.ST_X(centroid).label("centroid_lon"),
				func.ST_Y(centroid).label("centroid_lat"),
				func.count().label("count"),
			)
			.group_by(snapped)
		)

		conditions = []
		if min_lat is not None:
			conditions.append(cls.latitude >= min_lat)
		if max_lat is not None:
			conditions.append(cls.latitude <= max_lat)
		if min_lon is not None:
			conditions.append(cls.longitude >= min_lon)
		if max_lon is not None:
			conditions.append(cls.longitude <= max_lon)
		if conditions:
			stmt = stmt.where(and_(*conditions))

		rows = session.execute(stmt).all()
		return [
			{
				"centroid_lon": float(r.centroid_lon),
				"centroid_lat": float(r.centroid_lat),
				"count": int(r.count),
			}
			for r in rows
		]

	@classmethod
	def extent(
		cls,
		session: Session,
		*,
		min_lat: float | None = None,
		max_lat: float | None = None,
		min_lon: float | None = None,
		max_lon: float | None = None,
	) -> tuple[float, float, float, float] | None:
		"""
		Compute the bounding-box extent of all (optionally filtered) instances.

		Returns (min_lon, min_lat, max_lon, max_lat) in WGS-84 degrees, or
		None when the table/filter produces no rows.

		Requires PostGIS + GeoAlchemy2.
		"""
		if not _GEOALCHEMY2_AVAILABLE:
			raise RuntimeError("geoalchemy2 + PostGIS required for extent()")

		from sqlalchemy import and_, select

		box_expr = func.Box2D(func.ST_Extent(cls.geom)).cast(Text)

		conditions = []
		if min_lat is not None:
			conditions.append(cls.latitude >= min_lat)
		if max_lat is not None:
			conditions.append(cls.latitude <= max_lat)
		if min_lon is not None:
			conditions.append(cls.longitude >= min_lon)
		if max_lon is not None:
			conditions.append(cls.longitude <= max_lon)

		stmt = select(box_expr)
		if conditions:
			stmt = stmt.where(and_(*conditions))

		raw = session.execute(stmt).scalar()
		if raw is None:
			return None

		# PostGIS returns "BOX(lon_min lat_min,lon_max lat_max)"
		inner = raw[4:-1]  # strip "BOX(" and ")"
		sw, ne = inner.split(",")
		lon_min, lat_min = map(float, sw.split())
		lon_max, lat_max = map(float, ne.split())
		return (lon_min, lat_min, lon_max, lat_max)

	@classmethod
	def from_geojson(cls, feature: dict[str, Any]) -> GeoLocationMixin:
		"""
		Construct an instance from a GeoJSON Feature dict (RFC 7946).

		Raises ValueError for malformed or non-Point geometry input.
		Sets all properties found in feature["properties"] that correspond
		to valid attributes on the model.
		"""
		if not isinstance(feature, dict):
			raise ValueError("Invalid GeoJSON: expected a dict")
		if feature.get("type") != "Feature":
			raise ValueError("Invalid GeoJSON: 'type' must be 'Feature'")

		geometry = feature.get("geometry") or {}
		if geometry.get("type") != "Point":
			raise ValueError(
				f"Invalid GeoJSON geometry type {geometry.get('type')!r}; "
				"expected 'Point'"
			)

		coords = geometry.get("coordinates") or []
		if len(coords) < 2:
			raise ValueError(
				"Invalid GeoJSON: coordinates must have at least [longitude, latitude]"
			)

		instance = cls()
		instance.set_coordinates(
			latitude=float(coords[1]),
			longitude=float(coords[0]),
			altitude=float(coords[2]) if len(coords) > 2 else None,
		)

		_protected = frozenset({"latitude", "longitude", "geom", "geog", "geo_timestamp"})
		for key, value in (feature.get("properties") or {}).items():
			if key in _protected:
				continue
			# Use __dict__ lookup + type inspection to avoid triggering
			# SQLAlchemy descriptor machinery on non-mapped stubs.
			if key in instance.__dict__ or key in type(instance).__dict__:
				try:
					setattr(instance, key, value)
				except (AttributeError, TypeError):
					pass

		return instance

	# ------------------------------------------------------------------
	# Pure-Python spatial utilities (no external deps)
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
		formula. Returns kilometres. Accurate to ~0.5 % globally.

		No external dependencies; works on any RDBMS.

		Raises ValueError for out-of-range coordinate inputs.
		"""
		_validate_lat(lat1, "lat1")
		_validate_lat(lat2, "lat2")
		_validate_lon(lon1, "lon1")
		_validate_lon(lon2, "lon2")

		dlat = math.radians(lat2 - lat1)
		dlon = math.radians(lon2 - lon1)
		rlat1 = math.radians(lat1)
		rlat2 = math.radians(lat2)

		a = math.sin(dlat / 2) ** 2 + math.cos(rlat1) * math.cos(rlat2) * math.sin(dlon / 2) ** 2
		return _EARTH_RADIUS_KM * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

	@staticmethod
	def vincenty_distance(
		lat1: float,
		lon1: float,
		lat2: float,
		lon2: float,
	) -> float:
		"""
		Vincenty direct formula for ellipsoidal (WGS-84) distance in km.

		More accurate than haversine near the poles. Still no external deps.
		Returns haversine result if Vincenty fails to converge (antipodal pts).
		"""
		_validate_lat(lat1, "lat1")
		_validate_lat(lat2, "lat2")
		_validate_lon(lon1, "lon1")
		_validate_lon(lon2, "lon2")

		# WGS-84 ellipsoid parameters
		a = 6_378_137.0          # semi-major axis, m
		f = 1 / 298.257223563    # flattening
		b = a * (1 - f)          # semi-minor axis

		L = math.radians(lon2 - lon1)
		U1 = math.atan((1 - f) * math.tan(math.radians(lat1)))
		U2 = math.atan((1 - f) * math.tan(math.radians(lat2)))
		sinU1, cosU1 = math.sin(U1), math.cos(U1)
		sinU2, cosU2 = math.sin(U2), math.cos(U2)

		lam = L
		for _ in range(200):
			sinLam, cosLam = math.sin(lam), math.cos(lam)
			sinSig = math.sqrt(
				(cosU2 * sinLam) ** 2 + (cosU1 * sinU2 - sinU1 * cosU2 * cosLam) ** 2
			)
			if sinSig == 0:
				return 0.0  # coincident points
			cosSig = sinU1 * sinU2 + cosU1 * cosU2 * cosLam
			sig = math.atan2(sinSig, cosSig)
			sinAlpha = cosU1 * cosU2 * sinLam / sinSig
			cos2Alpha = 1 - sinAlpha ** 2
			cos2SigM = cosSig - 2 * sinU1 * sinU2 / cos2Alpha if cos2Alpha else 0.0
			C = f / 16 * cos2Alpha * (4 + f * (4 - 3 * cos2Alpha))
			lam_prev = lam
			lam = L + (1 - C) * f * sinAlpha * (
				sig + C * sinSig * (cos2SigM + C * cosSig * (-1 + 2 * cos2SigM ** 2))
			)
			if abs(lam - lam_prev) < 1e-12:
				break
		else:
			# Failed to converge — fall back to haversine
			return GeoLocationMixin.haversine_distance(lat1, lon1, lat2, lon2)

		u2 = cos2Alpha * (a ** 2 - b ** 2) / (b ** 2)
		A_v = 1 + u2 / 16384 * (4096 + u2 * (-768 + u2 * (320 - 175 * u2)))
		B_v = u2 / 1024 * (256 + u2 * (-128 + u2 * (74 - 47 * u2)))
		deltaSig = B_v * sinSig * (
			cos2SigM + B_v / 4 * (
				cosSig * (-1 + 2 * cos2SigM ** 2)
				- B_v / 6 * cos2SigM * (-3 + 4 * sinSig ** 2) * (-3 + 4 * cos2SigM ** 2)
			)
		)
		return b * A_v * (sig - deltaSig) / 1_000.0

	@staticmethod
	def get_bounding_box(
		center_lat: float,
		center_lon: float,
		distance_km: float,
	) -> tuple[float, float, float, float]:
		"""
		Approximate bounding box for a centre point and radius.

		Handles polar latitude clamping and 180° meridian wraparound.

		Returns
		-------
		(min_lat, min_lon, max_lat, max_lon) in WGS-84 degrees.
		"""
		_validate_lat(center_lat, "center_lat")
		_validate_lon(center_lon, "center_lon")
		if distance_km <= 0:
			raise ValueError(f"distance_km must be positive, got {distance_km!r}")

		lat_deg = distance_km / 111.32
		cos_lat = math.cos(math.radians(center_lat))
		lon_deg = distance_km / (111.32 * cos_lat) if cos_lat > 1e-10 else 180.0

		min_lat = max(center_lat - lat_deg, -90.0)
		max_lat = min(center_lat + lat_deg, 90.0)
		min_lon = center_lon - lon_deg
		max_lon = center_lon + lon_deg

		# Normalise to [-180, 180]
		if min_lon < -180.0:
			min_lon += 360.0
		if max_lon > 180.0:
			max_lon -= 360.0

		return (min_lat, min_lon, max_lat, max_lon)

	# ------------------------------------------------------------------
	# Geocoding helpers (require geopy; never called by model/query paths)
	# ------------------------------------------------------------------

	@classmethod
	def geocode_address(
		cls,
		address: str,
		timeout: int = 10,
		exactly_one: bool = True,
	) -> tuple[float, float] | None:
		"""
		Forward-geocode *address* → (latitude, longitude) via Nominatim.

		Returns None when no match is found.
		Re-raises GeocoderTimedOut / GeocoderServiceError on service failure.

		Requires geopy; raises RuntimeError when absent.

		Warning: Nominatim enforces a 1 req/s rate limit. Use a dedicated
		geocoding service or caching layer in production.
		"""
		if not _GEOPY_AVAILABLE:
			raise RuntimeError("geopy is required for geocode_address()")
		try:
			geolocator = Nominatim(user_agent="flask-appbuilder-geo")
			loc = geolocator.geocode(address, timeout=timeout, exactly_one=exactly_one)
			return (loc.latitude, loc.longitude) if loc else None
		except (GeocoderTimedOut, GeocoderServiceError):
			logger.exception("Forward geocoding failed for %r", address)
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
		Reverse-geocode (latitude, longitude) → human-readable address string.

		Returns None when no match is found.
		Re-raises GeocoderTimedOut / GeocoderServiceError on service failure.

		Requires geopy; raises RuntimeError when absent.
		"""
		if not _GEOPY_AVAILABLE:
			raise RuntimeError("geopy is required for reverse_geocode()")
		_validate_lat(latitude)
		_validate_lon(longitude)
		try:
			geolocator = Nominatim(user_agent="flask-appbuilder-geo")
			loc = geolocator.reverse(
				f"{latitude},{longitude}", timeout=timeout, language=language
			)
			return loc.address if loc else None
		except (GeocoderTimedOut, GeocoderServiceError):
			logger.exception("Reverse geocoding failed for (%s, %s)", latitude, longitude)
			raise

	# ------------------------------------------------------------------
	# Internal fallback for non-PostGIS environments
	# ------------------------------------------------------------------

	@classmethod
	def _haversine_radius_scan(
		cls,
		session: Session,
		latitude: float,
		longitude: float,
		radius_km: float,
		limit: int | None,
	) -> list[Any]:
		"""
		Pure-Python radius search fallback (no PostGIS).

		Applies a fast bounding-box pre-filter on scalar lat/lon columns
		then computes haversine distance in Python. Accurate but O(n) on
		the pre-filtered set; use PostGIS for production at scale.
		"""
		from sqlalchemy import and_, between, select

		min_lat, min_lon, max_lat, max_lon = cls.get_bounding_box(
			latitude, longitude, radius_km
		)
		stmt = select(cls).where(
			and_(
				between(cls.latitude, min_lat, max_lat),
				between(cls.longitude, min_lon, max_lon),
			)
		)
		candidates = list(session.execute(stmt).scalars())

		results = [
			(
				inst,
				GeoLocationMixin.haversine_distance(
					latitude, longitude, inst.latitude, inst.longitude
				),
			)
			for inst in candidates
			if inst.latitude is not None and inst.longitude is not None
		]
		results.sort(key=lambda x: x[1])
		results = [inst for inst, d in results if d <= radius_km]

		return results[:limit] if limit is not None else results
