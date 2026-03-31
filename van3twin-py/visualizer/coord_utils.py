import math

R = 6_371_000  # Earth radius in meters


def meters_to_latlon(
    x: float,
    y: float,
    center_lat: float,
    center_lon: float,
    origin_x: float = 0.0,
    origin_y: float = 0.0,
) -> tuple[float, float]:
    """Convert local meter coordinates to geographic lat/lon.

    The local coordinate system has its origin at (origin_x, origin_y) meters,
    which corresponds to (center_lat, center_lon) in geographic coordinates.
    +X is East, +Y is North.
    """
    dx = x - origin_x
    dy = y - origin_y
    lat = center_lat + math.degrees(dy / R)
    lon = center_lon + math.degrees(dx / (R * math.cos(math.radians(center_lat))))
    return lat, lon
