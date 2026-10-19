"""Geocode incoming calls and pick the ambulance that should respond."""
import logging
import math
import re
from typing import NamedTuple, Optional

import googlemaps
from googlemaps.exceptions import ApiError, Timeout, TransportError

logger = logging.getLogger(__name__)

# San Francisco's ZIP code polygons, slightly padded. Used to bias geocoding
# and to reject locations outside the service area.
SF_BOUNDS = {"southwest": (37.70, -122.53), "northeast": (37.84, -122.35)}
COORDINATES = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$")
# The Distance Matrix API accepts at most 25 origins per request.
MAX_ORIGINS = 25
GOOGLE_ERRORS = (ApiError, Timeout, TransportError, ValueError)


class GeocodingError(Exception):
    """An address couldn't be turned into a location; the message is shown to the user."""


class Choice(NamedTuple):
    amb_id: int
    seconds: Optional[int]
    method: str


def in_service_area(lat, lon):
    south, west = SF_BOUNDS["southwest"]
    north, east = SF_BOUNDS["northeast"]
    return south <= lat <= north and west <= lon <= east


def geocode(address, api_key, client=None):
    """Return ``(lat, lon)`` for an address in San Francisco.

    Input of the form ``"37.77, -122.42"`` is used as coordinates directly,
    which also lets the app run without a Google Maps API key.
    """
    match = COORDINATES.match(address)
    if match:
        lat, lon = float(match[1]), float(match[2])
    else:
        if client is None and not api_key:
            raise GeocodingError(
                "Address lookup needs a Google Maps API key (GGL_API_KEY). "
                "You can enter coordinates as 'lat, long' instead."
            )
        try:
            client = client or googlemaps.Client(key=api_key)
            results = client.geocode(address, bounds=SF_BOUNDS, components={"country": "US", "administrative_area": "CA"})
        except GOOGLE_ERRORS:
            logger.exception("Geocoding %r failed", address)
            raise GeocodingError("Address lookup failed. Please try again.")
        if not results:
            raise GeocodingError(f"Couldn't find {address!r}.")
        location = results[0]["geometry"]["location"]
        lat, lon = location["lat"], location["lng"]
    if not in_service_area(lat, lon):
        raise GeocodingError("That location is outside the San Francisco service area.")
    return lat, lon


def haversine_m(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def drive_times(available, lat, lon, client):
    """Seconds from each ambulance to the call in current traffic, keyed by ``amb_id``.

    Ambulances without a usable route are left out.
    """
    times = {}
    for start in range(0, len(available), MAX_ORIGINS):
        batch = available[start:start + MAX_ORIGINS]
        response = client.distance_matrix(
            [(a_lat, a_lon) for _, a_lat, a_lon in batch], [(lat, lon)], mode="driving", departure_time="now"
        )
        for (amb_id, _, _), row in zip(batch, response["rows"]):
            element = row["elements"][0]
            duration = element.get("duration_in_traffic") or element.get("duration")
            if element.get("status") == "OK" and duration:
                times[amb_id] = duration["value"]
    return times


def choose_ambulance(available, lat, lon, api_key, client=None):
    """Pick the ambulance that can reach ``(lat, lon)`` soonest.

    ``available`` is a list of ``(amb_id, lat, lon)`` tuples. Uses Google
    drive times in current traffic, and falls back to straight-line
    distance when no API key is set or the API returns no usable route.
    Returns ``None`` when no ambulance is available.
    """
    if not available:
        return None
    times = {}
    if client is not None or api_key:
        try:
            times = drive_times(available, lat, lon, client or googlemaps.Client(key=api_key))
        except GOOGLE_ERRORS:
            logger.exception("Distance Matrix request failed; using straight-line distance")
    if times:
        amb_id = min(times, key=times.get)
        return Choice(amb_id, times[amb_id], "drive time in traffic")
    amb_id = min(available, key=lambda a: haversine_m(a[1], a[2], lat, lon))[0]
    return Choice(amb_id, None, "straight-line distance")
