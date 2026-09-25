"""Turn city/state strings into coordinates for map artifacts.

Lead lists from Data Axle carry city and state but no coordinates, so the
map tool resolves them here: exact lat/lng if given, otherwise a cached
OpenStreetMap (Nominatim) lookup of "city, state, country", otherwise the
centre of the state. Every lookup is cached in the ``geocode_cache`` table
so a place is fetched from the network at most once per machine.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from src.database import get_geocode, save_geocode

logger = logging.getLogger(__name__)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "DAXAGENT/1.0 (local outbound-sales assistant)"
MIN_INTERVAL_S = 1.1  # Nominatim usage policy: at most one request per second
MAX_LOOKUPS_PER_CALL = 150

# Geographic centres of the US states (plus DC and PR), used when a city cannot be resolved.
STATE_CENTERS: dict[str, tuple[float, float]] = {
    "AL": (32.806671, -86.791130), "AK": (61.370716, -152.404419), "AZ": (33.729759, -111.431221),
    "AR": (34.969704, -92.373123), "CA": (36.116203, -119.681564), "CO": (39.059811, -105.311104),
    "CT": (41.597782, -72.755371), "DE": (39.318523, -75.507141), "DC": (38.897438, -77.026817),
    "FL": (27.766279, -81.686783), "GA": (33.040619, -83.643074), "HI": (21.094318, -157.498337),
    "ID": (44.240459, -114.478828), "IL": (40.349457, -88.986137), "IN": (39.849426, -86.258278),
    "IA": (42.011539, -93.210526), "KS": (38.526600, -96.726486), "KY": (37.668140, -84.670067),
    "LA": (31.169546, -91.867805), "ME": (44.693947, -69.381927), "MD": (39.063946, -76.802101),
    "MA": (42.230171, -71.530106), "MI": (43.326618, -84.536095), "MN": (45.694454, -93.900192),
    "MS": (32.741646, -89.678696), "MO": (38.456085, -92.288368), "MT": (46.921925, -110.454353),
    "NE": (41.125370, -98.268082), "NV": (38.313515, -117.055374), "NH": (43.452492, -71.563896),
    "NJ": (40.298904, -74.521011), "NM": (34.840515, -106.248482), "NY": (42.165726, -74.948051),
    "NC": (35.630066, -79.806419), "ND": (47.528912, -99.784012), "OH": (40.388783, -82.764915),
    "OK": (35.565342, -96.928917), "OR": (44.572021, -122.070938), "PA": (40.590752, -77.209755),
    "RI": (41.680893, -71.511780), "SC": (33.856892, -80.945007), "SD": (44.299782, -99.438828),
    "TN": (35.747845, -86.692345), "TX": (31.054487, -97.563461), "UT": (40.150032, -111.862434),
    "VT": (44.045876, -72.710686), "VA": (37.769337, -78.169968), "WA": (47.400902, -121.490494),
    "WV": (38.491226, -80.954453), "WI": (44.268543, -89.616508), "WY": (42.755966, -107.302490),
    "PR": (18.220833, -66.590149),
}

STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA", "colorado": "CO",
    "connecticut": "CT", "delaware": "DE", "district of columbia": "DC", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC", "south dakota": "SD",
    "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY", "puerto rico": "PR",
}

_lock = asyncio.Lock()
_last_request = 0.0


def normalize_state(value: Any) -> str:
    """'Texas' / 'tx' / ' TX ' -> 'TX'; anything unknown is returned upper-cased and stripped."""
    s = str(value or "").strip()
    if not s:
        return ""
    if len(s) == 2:
        return s.upper()
    return STATE_NAMES.get(s.lower(), s.upper())


def _num(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def _cache_key(city: str, state: str, country: str) -> str:
    return "|".join(p.strip().lower() for p in (city, state, country))


async def _nominatim(query: str) -> tuple[float, float] | None:
    global _last_request
    async with _lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_request)
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=8.0, headers={"User-Agent": USER_AGENT}) as client:
                r = await client.get(NOMINATIM_URL, params={"q": query, "format": "json", "limit": 1})
            _last_request = time.monotonic()
            r.raise_for_status()
            hits = r.json()
        except Exception as e:  # network, quota, malformed
            logger.warning(f"Geocode failed for {query!r}: {e}")
            return None
    if not hits:
        return None
    lat, lng = _num(hits[0].get("lat")), _num(hits[0].get("lon"))
    return (lat, lng) if lat is not None and lng is not None else None


async def geocode_place(city: str, state: str, country: str = "USA") -> tuple[float, float, str]:
    """Coordinates for a city/state, with the resolution source: geocoded | state_center | none."""
    state = normalize_state(state)
    city = str(city or "").strip()
    if city:
        key = _cache_key(city, state, country)
        cached = await get_geocode(key)
        if cached is not None:
            if cached["lat"] is not None:
                return cached["lat"], cached["lng"], "geocoded"
        else:
            query = ", ".join(p for p in (city, state, country) if p)
            hit = await _nominatim(query)
            await save_geocode(key, hit[0] if hit else None, hit[1] if hit else None)
            if hit:
                return hit[0], hit[1], "geocoded"
    if state in STATE_CENTERS:
        lat, lng = STATE_CENTERS[state]
        return lat, lng, "state_center"
    return 0.0, 0.0, "none"


async def locate_points(points: list[dict[str, Any]]) -> dict[str, int]:
    """Fill lat/lng/geo_source on each point in place; returns counts per source."""
    counts = {"given": 0, "geocoded": 0, "state_center": 0, "none": 0}
    lookups = 0
    for p in points:
        lat = _num(p.get("lat", p.get("latitude")))
        lng = _num(p.get("lng", p.get("lon", p.get("longitude"))))
        if lat is not None and lng is not None and -90 <= lat <= 90 and -180 <= lng <= 180:
            p["lat"], p["lng"], p["geo_source"] = lat, lng, "given"
            counts["given"] += 1
            continue
        city, state = p.get("city", ""), p.get("state", "")
        if lookups >= MAX_LOOKUPS_PER_CALL:
            # Past the per-call budget only the state centre is used; nothing hits the network.
            st = normalize_state(state)
            if st in STATE_CENTERS:
                p["lat"], p["lng"], p["geo_source"] = *STATE_CENTERS[st], "state_center"
            else:
                p["lat"], p["lng"], p["geo_source"] = None, None, "none"
        else:
            lookups += 1
            lat, lng, src = await geocode_place(city, state, p.get("country", "USA"))
            p["lat"], p["lng"], p["geo_source"] = (lat, lng, src) if src != "none" else (None, None, "none")
        counts[p["geo_source"]] += 1
    return counts
