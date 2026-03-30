"""
Geospatial utility functions.

Standalone utilities with no app dependencies for easy testing.
"""

import math


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance in kilometres between two lat/lon points.
    
    Uses the Haversine formula for spherical Earth approximation.
    
    Args:
        lat1: Latitude of first point in degrees
        lon1: Longitude of first point in degrees
        lat2: Latitude of second point in degrees
        lon2: Longitude of second point in degrees
    
    Returns:
        Distance in kilometres
    """
    R = 6371.0  # Earth's radius in kilometres
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def approximate_lat_lon_bounds(latitude: float, longitude: float, radius_km: float) -> tuple[float, float, float, float]:
    """
    Coarse axis-aligned bounding box (min_lat, max_lat, min_lon, max_lon) for pre-filtering
    before Haversine. Not exact on antimeridian; sufficient for typical regional radii.
    """
    r = max(float(radius_km), 0.1)
    dlat = r / 111.0
    cos_lat = max(0.2, abs(math.cos(math.radians(latitude))))
    dlon = r / (111.0 * cos_lat)
    return latitude - dlat, latitude + dlat, longitude - dlon, longitude + dlon
