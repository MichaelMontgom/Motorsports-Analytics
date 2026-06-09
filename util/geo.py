"""Geometry helpers with no project dependencies."""

import math
from typing import Optional, Tuple


FEET_PER_METER = 3.28084
EARTH_RADIUS_M = 6_371_000  # mean Earth radius in meters


def haversine_feet(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return distance in feet between two WGS-84 coordinates."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a)) * FEET_PER_METER


def to_local_xy(lat: float, lon: float, ref_lat: float, ref_lon: float) -> Tuple[float, float]:
    """Equirectangular projection (meters) of a point about a reference origin.

    Returns (x_m, y_m) where +x is east and +y is north. Accurate over the
    small distances involved in a single autocross course.
    """
    x = math.radians(lon - ref_lon) * math.cos(math.radians(ref_lat)) * EARTH_RADIUS_M
    y = math.radians(lat - ref_lat) * EARTH_RADIUS_M
    return x, y


def offset_point(lat: float, lon: float, bearing_deg: float, distance_ft: float) -> Tuple[float, float]:
    """Return the (lat, lon) reached by moving `distance_ft` along `bearing_deg`.

    Bearing is compass-style: 0° = north, 90° = east. Uses a flat-earth
    approximation, which is exact enough for gate-width offsets.
    """
    d_m = distance_ft / FEET_PER_METER
    north_m = d_m * math.cos(math.radians(bearing_deg))
    east_m = d_m * math.sin(math.radians(bearing_deg))
    dlat = math.degrees(north_m / EARTH_RADIUS_M)
    dlon = math.degrees(east_m / (EARTH_RADIUS_M * math.cos(math.radians(lat))))
    return lat + dlat, lon + dlon


def build_gate_from_crossing(
    lat: float, lon: float, heading_deg: float, width_ft: float
) -> Tuple[float, float, float, float]:
    """Build a gate line perpendicular to `heading_deg`, centered on (lat, lon).

    Returns (latA, lonA, latB, lonB) — the two endpoints offset ±width/2 along
    the directions `heading_deg ± 90°`.
    """
    half = width_ft / 2.0
    latA, lonA = offset_point(lat, lon, heading_deg + 90.0, half)
    latB, lonB = offset_point(lat, lon, heading_deg - 90.0, half)
    return latA, lonA, latB, lonB


def _orient(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    """Signed area (z of cross product) of segment AB vs point C."""
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)


def gate_crossing(prev, cur, gate) -> Optional[float]:
    """Return the fraction t∈[0,1] along prev→cur where it crosses `gate`, else None.

    `prev` and `cur` are objects with `.latitude`/`.longitude`; `gate` is duck-typed
    with `.lat1/.lon1/.lat2/.lon2/.heading_deg`. The crossing must be in the gate's
    forward direction (car bearing within 90° of the gate's stored heading).
    """
    ref_lat, ref_lon = gate.lat1, gate.lon1
    p1x, p1y = to_local_xy(prev.latitude, prev.longitude, ref_lat, ref_lon)
    p2x, p2y = to_local_xy(cur.latitude, cur.longitude, ref_lat, ref_lon)
    g1x, g1y = to_local_xy(gate.lat1, gate.lon1, ref_lat, ref_lon)
    g2x, g2y = to_local_xy(gate.lat2, gate.lon2, ref_lat, ref_lon)

    # Direction gate: movement vector must point the same way as the gate heading.
    move_x, move_y = p2x - p1x, p2y - p1y
    head_x = math.sin(math.radians(gate.heading_deg))  # east component
    head_y = math.cos(math.radians(gate.heading_deg))  # north component
    if move_x * head_x + move_y * head_y <= 0:
        return None

    # Segment intersection: p1→p2 against g1→g2 via orientation signs.
    d1 = _orient(g1x, g1y, g2x, g2y, p1x, p1y)
    d2 = _orient(g1x, g1y, g2x, g2y, p2x, p2y)
    d3 = _orient(p1x, p1y, p2x, p2y, g1x, g1y)
    d4 = _orient(p1x, p1y, p2x, p2y, g2x, g2y)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        denom = d1 - d2
        if denom == 0:
            return None
        return d1 / denom
    return None
