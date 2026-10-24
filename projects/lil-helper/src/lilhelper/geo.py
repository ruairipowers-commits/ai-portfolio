"""Where a household (or a chef) is: an address, and a point for "chefs near me" / "households near me".

Distances are worked out here, on the server; the marketplace shows a town and a distance in whole miles, never an
address. Geocoding (address → point, point → address) uses a public service only when HELPER_GEOCODER is set:
  census     US Census Bureau geocoder (free, no key): address → point
  nominatim  OpenStreetMap Nominatim (free, 1 request a second, needs HELPER_GEOCODER_CONTACT): both directions
Without it, the phone's own location fills the point, the person types the address, and places without a point are
matched by ZIP code (same ZIP, then the same first three digits).
"""
from __future__ import annotations

import math
import os

import httpx

UA = "DinnerPeace/0.6 (meal planner; {contact})"


def miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def point(addr: dict | None) -> tuple[float, float] | None:
    if addr and addr.get("lat") is not None and addr.get("lon") is not None:
        return float(addr["lat"]), float(addr["lon"])
    return None


def distance(a: dict | None, b: dict | None) -> float | None:
    """Miles between two addresses: by their points, else by ZIP (0 for the same ZIP, ~15 for the same area)."""
    pa, pb = point(a), point(b)
    if pa and pb:
        return miles(pa, pb)
    za, zb = str((a or {}).get("zip") or "")[:5], str((b or {}).get("zip") or "")[:5]
    if za and zb:
        if za == zb:
            return 0.0
        if za[:3] == zb[:3]:
            return 15.0
    return None


def place(addr: dict | None) -> str:
    """What other people see: the town and state, never the street."""
    if not addr:
        return ""
    return ", ".join(x for x in (addr.get("city"), (addr.get("state") or "").upper()) if x)


def _mode() -> str:
    return os.getenv("HELPER_GEOCODER", "").lower()


def forward(addr: dict) -> tuple[float, float] | None:
    one = ", ".join(str(addr.get(k)) for k in ("line1", "city", "state", "zip") if addr.get(k))
    if not one:
        return None
    try:
        if _mode() == "census":
            r = httpx.get("https://geocoding.geo.census.gov/geocoder/locations/onelineaddress", timeout=10,
                          params={"address": one, "benchmark": "Public_AR_Current", "format": "json"})
            m = r.json()["result"]["addressMatches"]
            return (m[0]["coordinates"]["y"], m[0]["coordinates"]["x"]) if m else None
        if _mode() == "nominatim":
            r = httpx.get("https://nominatim.openstreetmap.org/search", timeout=10,
                          params={"q": one, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
                          headers={"User-Agent": UA.format(contact=os.getenv("HELPER_GEOCODER_CONTACT", ""))})
            js = r.json()
            return (float(js[0]["lat"]), float(js[0]["lon"])) if js else None
    except (httpx.HTTPError, KeyError, ValueError, IndexError):
        return None
    return None


def reverse(lat: float, lon: float) -> dict | None:
    """A point → street, town, state, ZIP (Nominatim only; the Census geocoder doesn't return streets)."""
    if _mode() != "nominatim":
        return None
    try:
        r = httpx.get("https://nominatim.openstreetmap.org/reverse", timeout=10,
                      params={"lat": lat, "lon": lon, "format": "jsonv2", "addressdetails": 1},
                      headers={"User-Agent": UA.format(contact=os.getenv("HELPER_GEOCODER_CONTACT", ""))})
        a = r.json().get("address", {})
    except (httpx.HTTPError, ValueError):
        return None
    states = STATE_CODES
    return {"line1": " ".join(x for x in (a.get("house_number"), a.get("road")) if x),
            "city": a.get("city") or a.get("town") or a.get("village") or a.get("hamlet") or "",
            "state": states.get(a.get("state", ""), ""), "zip": (a.get("postcode") or "")[:5]}


STATE_CODES = {"Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR", "California": "CA",
               "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE", "District of Columbia": "DC", "Florida": "FL",
               "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
               "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
               "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS", "Missouri": "MO",
               "Montana": "MT", "Nebraska": "NE", "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ",
               "New Mexico": "NM", "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
               "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
               "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT", "Vermont": "VT",
               "Virginia": "VA", "Washington": "WA", "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY"}
