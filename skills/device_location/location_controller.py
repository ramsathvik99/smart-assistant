"""
Location Intelligence Controller
Comprehensive controller supporting:
- Current location & status diagnostics
- Geocoding & reverse geocoding
- Interactive maps & navigation URLs
- Routing & turn-by-turn navigation (Fastest vs Shortest, modes, multi-stop)
- Distance calculations (Straight-line vs Road network)
- Nearby place discovery (Hospitals, fuel stations, restaurants, etc.)
- Saved places & persistent location history
- Contextual navigation dialogue follow-ups
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .location_detector import DeviceLocationDetector, get_location_detector

logger = logging.getLogger(__name__)

_file_storage_lock = threading.RLock()


def _get_ssl_context() -> ssl.SSLContext:
    """Creates a strictly verified SSL context using certifi CA bundle or system trust roots."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _fetch_json(url: str, data: Optional[bytes] = None, timeout: float = 7.0) -> Any:
    """Fetches and parses JSON over HTTPS with mandatory TLS certificate verification and bounded retry on 429."""
    headers = {"User-Agent": "SmartAssistant-LocationIntelligence/1.0 (contact: admin@local.assistant)"}
    req = urllib.request.Request(url, data=data, headers=headers)
    ctx = _get_ssl_context() if url.startswith("https") else None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt == 0:
                time.sleep(1.0)
                continue
            raise
        except Exception:
            if attempt == 0:
                time.sleep(0.5)
                continue
            raise


def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle straight-line distance in kilometers."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r * c


class LocationController:
    def __init__(self, detector: Optional[DeviceLocationDetector] = None):
        self.detector = detector or get_location_detector()
        self._lock = threading.RLock()
        project_root = Path(__file__).resolve().parent.parent.parent
        self.data_dir = project_root / "data" / "location"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.saved_places_file = self.data_dir / "saved_places.json"
        self.history_file = self.data_dir / "location_history.json"

        # Contextual navigation session state
        self.active_navigation: Optional[Dict[str, Any]] = None
        # Authoritative persistent map state manager & spatial results tracking
        from .map_state import get_map_state_manager
        self.map_state = get_map_state_manager()
        self.spatial_results: List[Dict[str, Any]] = []
        self.active_categories: List[str] = []

    # ─────────────────────────────────────────────────────────────────────────
    # SAVED PLACES & HISTORY STORAGE (PER-USER ISOLATED)
    # ─────────────────────────────────────────────────────────────────────────

    def _load_all_saved_places(self) -> Dict[str, Dict[str, Any]]:
        with _file_storage_lock:
            if self.saved_places_file.exists():
                try:
                    data = json.loads(self.saved_places_file.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        # Migrate flat dictionary to user "1" if needed
                        if data and not any(isinstance(v, dict) and "latitude" not in v for v in data.values()):
                            first_val = next(iter(data.values()))
                            if isinstance(first_val, dict) and "latitude" in first_val:
                                return {"1": data}
                        return data
                except Exception:
                    pass
            return {}

    def _save_all_saved_places(self, store: Dict[str, Dict[str, Any]]) -> None:
        with _file_storage_lock:
            try:
                content = json.dumps(store, indent=2)
                tmp_file = self.saved_places_file.with_suffix(".tmp")
                tmp_file.write_text(content, encoding="utf-8")
                os.replace(tmp_file, self.saved_places_file)
            except Exception as e:
                logger.debug(f"Failed to write saved places: {e}")

    def get_saved_places(self, user_id: Optional[Any] = None) -> Dict[str, Any]:
        with _file_storage_lock:
            store = self._load_all_saved_places()
            uid_key = str(user_id or 1)
            return dict(store.get(uid_key, {}))

    def save_place(self, name: str, lat: float, lon: float, address: str = "", user_id: Optional[Any] = None) -> Dict[str, Any]:
        with _file_storage_lock:
            store = self._load_all_saved_places()
            uid_key = str(user_id or 1)
            user_places = store.setdefault(uid_key, {})
            clean_name = name.strip().lower()
            user_places[clean_name] = {
                "name": name.strip(),
                "latitude": float(lat),
                "longitude": float(lon),
                "address": address,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            self._save_all_saved_places(store)
            return {"success": True, "place": user_places[clean_name]}

    def resolve_saved_place(self, query: str, user_id: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        clean = query.strip().lower()
        places = self.get_saved_places(user_id=user_id)
        # Check exact match first
        if clean in places:
            return places[clean]
        # Fallback to substring containment
        for k, v in places.items():
            if k in clean or clean in k:
                return v
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # GEOCODING & REVERSE GEOCODING
    # ─────────────────────────────────────────────────────────────────────────

    def geocode(self, query: str, limit: int = 3, user_id: Optional[Any] = None) -> List[Dict[str, Any]]:
        """Resolves an address, landmark, or place name into geographic coordinates."""
        saved = self.resolve_saved_place(query, user_id=user_id)
        if saved:
            return [{
                "display_name": saved.get("address") or saved["name"],
                "name": saved["name"],
                "latitude": saved["latitude"],
                "longitude": saved["longitude"],
                "is_saved": True,
            }]

        clean_q = urllib.parse.quote(query.strip())
        url = f"https://nominatim.openstreetmap.org/search?format=json&q={clean_q}&limit={limit}&addressdetails=1"
        try:
            results = _fetch_json(url, timeout=5.0)
            parsed = []
            if isinstance(results, list):
                for item in results:
                    parsed.append({
                        "display_name": item.get("display_name", ""),
                        "latitude": float(item.get("lat")),
                        "longitude": float(item.get("lon")),
                        "type": item.get("type", "place"),
                        "category": item.get("class", "place"),
                        "importance": float(item.get("importance", 0.0)),
                    })
            return parsed
        except Exception as e:
            logger.debug(f"[LOCATION] Geocode error for '{query}': {e}")
            return []

    def reverse_geocode(self, lat: float, lon: float) -> Dict[str, Any]:
        """Resolves coordinates into human-readable address."""
        return self.detector._reverse_geocode_osm(lat, lon)

    # ─────────────────────────────────────────────────────────────────────────
    # ROUTING & NAVIGATION
    # ─────────────────────────────────────────────────────────────────────────

    def get_route(
        self,
        origin_lat: float,
        origin_lon: float,
        dest_lat: float,
        dest_lon: float,
        mode: str = "driving",
        waypoints: Optional[List[Tuple[float, float]]] = None,
        avoid_tolls: bool = False,
    ) -> Dict[str, Any]:
        """
        Calculates multimodal routes between origin and destination.
        Uses genuine OpenStreetMap routing profiles (driving, walking, cycling) via FOSSGIS OSM
        and OSRM, ensuring walking and cycling use genuine non-motorized graphs.
        Distinguishes between Fastest and Shortest route options.
        """
        valid_modes = {
            "driving": "driving", "car": "driving",
            "walking": "walking", "walk": "walking", "foot": "walking",
            "cycling": "cycling", "bike": "cycling", "bicycle": "cycling"
        }
        routing_mode = valid_modes.get(mode.lower(), "driving")

        # Build coordinate string: lon,lat;lon,lat
        coord_pairs = [f"{origin_lon:.6f},{origin_lat:.6f}"]
        if waypoints:
            for wlat, wlon in waypoints:
                coord_pairs.append(f"{wlon:.6f},{wlat:.6f}")
        coord_pairs.append(f"{dest_lon:.6f},{dest_lat:.6f}")
        coords_str = ";".join(coord_pairs)

        # Primary endpoint selection based on mode
        # FOSSGIS OSM hosts separate pedestrian (routed-foot), bicycle (routed-bike), and car (routed-car) graphs
        endpoints = []
        if routing_mode == "walking":
            endpoints.append(("https://routing.openstreetmap.de/routed-foot/route/v1/foot", "walking_graph"))
        elif routing_mode == "cycling":
            endpoints.append(("https://routing.openstreetmap.de/routed-bike/route/v1/bike", "cycling_graph"))
        else:  # driving
            endpoints.append(("https://routing.openstreetmap.de/routed-car/route/v1/car", "driving_graph"))
            endpoints.append(("https://router.project-osrm.org/route/v1/driving", "driving_osrm"))

        data = None
        used_profile = None
        for base_url, prof in endpoints:
            url = f"{base_url}/{coords_str}?overview=full&geometries=geojson&steps=true&alternatives=true"
            try:
                data = _fetch_json(url, timeout=7.0)
                if data and data.get("code") == "Ok" and data.get("routes"):
                    used_profile = prof
                    break
            except Exception as e:
                logger.debug(f"[ROUTING] Endpoint {base_url} failed: {e}")
                data = None

        # Fallback if dedicated walking/cycling server is unreachable:
        # Fetch road geometry from car engine, but calculate realistic pedestrian/cyclist travel time
        # and explicitly disclose the limitation without labeling a car route as walking/cycling.
        is_mode_estimated = False
        mode_disclaimer = ""
        if (not data or not data.get("routes")) and routing_mode in ("walking", "cycling"):
            fallback_url = f"https://router.project-osrm.org/route/v1/driving/{coords_str}?overview=full&geometries=geojson&steps=true&alternatives=true"
            try:
                data = _fetch_json(fallback_url, timeout=7.0)
                if data and data.get("code") == "Ok" and data.get("routes"):
                    is_mode_estimated = True
                    if routing_mode == "walking":
                        mode_disclaimer = "Dedicated pedestrian graph unreachable; route estimated along road network at standard walking speed (4.8 km/h)."
                    else:
                        mode_disclaimer = "Dedicated cycling graph unreachable; route estimated along road network at standard cycling speed (15 km/h)."
            except Exception:
                pass

        if not data or data.get("code") != "Ok" or not data.get("routes"):
            return {"success": False, "error": f"No {routing_mode} route found between specified points."}

        routes_raw = data.get("routes", [])
        parsed_routes = []

        for idx, r in enumerate(routes_raw):
            dist_meters = float(r.get("distance", 0.0))
            dist_km = dist_meters / 1000.0

            if is_mode_estimated:
                if routing_mode == "walking":
                    dur_seconds = dist_meters / 1.3333
                else:  # cycling
                    dur_seconds = dist_meters / 4.1667
                dur_mins = dur_seconds / 60.0
            else:
                dur_seconds = float(r.get("duration", 0.0))
                dur_mins = dur_seconds / 60.0

            # Extract turn-by-turn steps summary
            steps_summary = []
            legs = r.get("legs", [])
            for leg in legs:
                for step in leg.get("steps", []):
                    maneuver = step.get("maneuver", {})
                    instruction = maneuver.get("type", "")
                    modifier = maneuver.get("modifier", "")
                    name = step.get("name", "")
                    step_dist = step.get("distance", 0)
                    if name or instruction:
                        dir_desc = f"{instruction} {modifier}".strip()
                        road_desc = f"onto {name}" if name else ""
                        steps_summary.append(f"{dir_desc} {road_desc} ({int(step_dist)}m)".strip())

            parsed_routes.append({
                "route_index": idx,
                "distance_km": round(dist_km, 2),
                "duration_minutes": round(dur_mins, 1),
                "geometry": r.get("geometry"),
                "steps": steps_summary[:12],  # First 12 key maneuvers
                "raw_steps_count": len(steps_summary),
            })

        # Identify fastest vs shortest
        fastest_route = min(parsed_routes, key=lambda x: x["duration_minutes"])
        shortest_route = min(parsed_routes, key=lambda x: x["distance_km"])

        # Calculate ETA from now
        now_local = datetime.now()
        eta_fastest = (now_local + timedelta(minutes=fastest_route["duration_minutes"])).strftime("%I:%M %p")
        eta_shortest = (now_local + timedelta(minutes=shortest_route["duration_minutes"])).strftime("%I:%M %p")

        # Google Maps & OSM navigation deep-links
        gmaps_nav = f"https://www.google.com/maps/dir/?api=1&origin={origin_lat},{origin_lon}&destination={dest_lat},{dest_lon}&travelmode={routing_mode}"
        osm_nav = f"https://www.openstreetmap.org/directions?engine=fossgis_osrm_{routing_mode}&route={origin_lat}%2C{origin_lon}%3B{dest_lat}%2C{dest_lon}"

        return {
            "success": True,
            "mode": routing_mode,
            "avoid_tolls": avoid_tolls,
            "is_mode_estimated": is_mode_estimated,
            "mode_disclaimer": mode_disclaimer,
            "fastest_route": fastest_route,
            "shortest_route": shortest_route,
            "eta_fastest": eta_fastest,
            "eta_shortest": eta_shortest,
            "alternative_count": len(parsed_routes),
            "routes": parsed_routes,
            "google_maps_url": gmaps_nav,
            "openstreetmap_url": osm_nav,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # NEARBY PLACES DISCOVERY
    # ─────────────────────────────────────────────────────────────────────────

    def search_nearby(
        self,
        category_or_term: str,
        lat: float,
        lon: float,
        radius_km: float = 5.0,
        limit: int = 6,
    ) -> List[Dict[str, Any]]:
        """Searches for points of interest nearby using bounded OpenStreetMap search."""
        term_clean = category_or_term.strip().lower()
        amenity_synonyms = {
            "hospital": "hospital",
            "hospitals": "hospital",
            "doctor": "hospital",
            "clinic": "clinic",
            "pharmacy": "pharmacy",
            "chemist": "pharmacy",
            "fuel": "fuel",
            "gas station": "fuel",
            "petrol pump": "fuel",
            "restaurant": "restaurant",
            "restaurants": "restaurant",
            "food": "restaurant",
            "atm": "atm",
            "atms": "atm",
            "bank": "bank",
            "parking": "parking",
            "hotel": "hotel",
            "supermarket": "supermarket",
            "grocery": "supermarket",
        }
        search_kw = amenity_synonyms.get(term_clean, term_clean)

        # Approximate bounding box degrees: 1 deg lat ~ 111 km, 1 deg lon ~ 111 km * cos(lat)
        deg_lat = radius_km / 111.0
        deg_lon = radius_km / (111.0 * max(0.1, math.cos(math.radians(lat))))

        left = lon - deg_lon
        bottom = lat - deg_lat
        right = lon + deg_lon
        top = lat + deg_lat

        url = (
            f"https://nominatim.openstreetmap.org/search?format=json&q={urllib.parse.quote(search_kw)}"
            f"&viewbox={left:.4f},{top:.4f},{right:.4f},{bottom:.4f}&bounded=1&limit={limit * 2}&addressdetails=1"
        )

        try:
            results = _fetch_json(url, timeout=7.0)
            items = []
            seen_names = set()
            seen_coords: List[Tuple[float, float, str]] = []

            if isinstance(results, list):
                for r in results:
                    r_lat = float(r.get("lat"))
                    r_lon = float(r.get("lon"))
                    dist = haversine_distance_km(lat, lon, r_lat, r_lon)
                    if dist <= radius_km * 1.25:  # small buffer
                        addr = r.get("address", {})
                        name = (
                            r.get("name")
                            or addr.get("hospital")
                            or addr.get("amenity")
                            or r.get("display_name", "").split(",")[0]
                        )
                        norm_name = re.sub(r'\s+', ' ', re.sub(r'[^a-zA-Z0-9\s]', '', name)).strip().lower()

                        # Deduplicate: Skip if identical normalized name or within 50m of an existing result
                        is_dupe = False
                        if norm_name in seen_names:
                            is_dupe = True
                        else:
                            for prev_lat, prev_lon, prev_name in seen_coords:
                                c_dist = haversine_distance_km(prev_lat, prev_lon, r_lat, r_lon)
                                if c_dist < 0.05 or (c_dist < 0.2 and (norm_name in prev_name or prev_name in norm_name)):
                                    is_dupe = True
                                    break

                        if not is_dupe:
                            seen_names.add(norm_name)
                            seen_coords.append((r_lat, r_lon, norm_name))
                            items.append({
                                "name": name.strip(),
                                "display_name": r.get("display_name", ""),
                                "latitude": r_lat,
                                "longitude": r_lon,
                                "distance_km": round(dist, 2),
                                "maps_url": f"https://www.google.com/maps?q={r_lat},{r_lon}",
                            })
            if not items:
                amenity_url = (
                    f"https://nominatim.openstreetmap.org/search?format=json&amenity={urllib.parse.quote(search_kw)}"
                    f"&viewbox={left:.4f},{top:.4f},{right:.4f},{bottom:.4f}&bounded=1&limit={limit * 2}&addressdetails=1"
                )
                try:
                    results2 = _fetch_json(amenity_url, timeout=7.0)
                    if isinstance(results2, list):
                        for r in results2:
                            r_lat = float(r.get("lat"))
                            r_lon = float(r.get("lon"))
                            dist = haversine_distance_km(lat, lon, r_lat, r_lon)
                            if dist <= radius_km * 1.5:
                                addr = r.get("address", {})
                                name = r.get("name") or addr.get("hospital") or addr.get("amenity") or r.get("display_name", "").split(",")[0]
                                norm_name = re.sub(r'\s+', ' ', re.sub(r'[^a-zA-Z0-9\s]', '', name)).strip().lower()
                                if norm_name not in seen_names:
                                    seen_names.add(norm_name)
                                    items.append({
                                        "name": name.strip(),
                                        "display_name": r.get("display_name", ""),
                                        "latitude": r_lat,
                                        "longitude": r_lon,
                                        "distance_km": round(dist, 2),
                                        "maps_url": f"https://www.google.com/maps?q={r_lat},{r_lon}",
                                    })
                except Exception:
                    pass

            items.sort(key=lambda x: x["distance_km"])
            return items[:limit]
        except Exception as e:
            logger.debug(f"[NEARBY] POI search error: {e}")
            return []

    def _normalize_category(self, cat: str) -> str:
        """Normalizes place category names to canonical keys."""
        c = (cat or "").lower().strip()
        if any(k in c for k in ["hospital", "clinic", "doctor"]):
            return "hospital"
        if any(k in c for k in ["pharmacy", "chemist", "medical"]):
            return "pharmacy"
        if any(k in c for k in ["restaurant", "food", "cafe", "dining"]):
            return "restaurant"
        if any(k in c for k in ["petrol", "gas", "fuel"]):
            return "fuel station"
        if any(k in c for k in ["atm", "cash"]):
            return "atm"
        if any(k in c for k in ["bank"]):
            return "bank"
        if any(k in c for k in ["hotel", "lodging"]):
            return "hotel"
        if any(k in c for k in ["supermarket", "grocery"]):
            return "supermarket"
        return c

    # ─────────────────────────────────────────────────────────────────────────
    # COMMAND INTERPRETATION & EXECUTION
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_ordinal(ordinal: Any) -> int:
        """Parses words ('first', 'second', '2nd', 'last') into integer index."""
        ord_map = {
            "first": 1, "1st": 1, "nearest": 1, "closest": 1,
            "second": 2, "2nd": 2,
            "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4,
            "fifth": 5, "5th": 5,
            "sixth": 6, "6th": 6,
            "seventh": 7, "7th": 7,
            "eighth": 8, "8th": 8,
            "ninth": 9, "9th": 9,
            "tenth": 10, "10th": 10,
            "eleventh": 11, "11th": 11,
            "twelfth": 12, "12th": 12,
            "thirteenth": 13, "13th": 13,
            "fourteenth": 14, "14th": 14,
            "fifteenth": 15, "15th": 15,
            "sixteenth": 16, "16th": 16,
            "seventeenth": 17, "17th": 17,
            "eighteenth": 18, "18th": 18,
            "nineteenth": 19, "19th": 19,
            "twentieth": 20, "20th": 20,
            "last": -1
        }
        if isinstance(ordinal, int):
            return ordinal
        if isinstance(ordinal, str):
            ord_clean = ordinal.strip().lower()
            num_clean = re.sub(r'(?:st|nd|rd|th)$', '', ord_clean)
            if num_clean.isdigit():
                return int(num_clean)
            return ord_map.get(ord_clean, 0)
        return 1

    def navigate_to_ordinal(
        self,
        ordinal: Any,
        category: Optional[str] = None,
        user_id: Optional[Any] = None
    ) -> Dict[str, Any]:
        """
        Navigates to an ordinal place (first, second, third, last, etc.) optionally filtered by category.
        Ensures:
        1. Exact category filtering when specified (e.g. 'second hospital' selects the 2nd hospital).
        2. Preserves global numbered presentation (#1..#N) when no category specified.
        3. Strict out-of-range detection and clear diagnostic messaging.
        4. Selected map marker ID, route destination coordinates, and response text refer to the exact same place.
        5. Consistent distance reporting (driving road distance via OSRM, straight-line distance noted).
        """
        ord_map = {
            "first": 1, "1st": 1, "nearest": 1, "closest": 1,
            "second": 2, "2nd": 2,
            "third": 3, "3rd": 3,
            "fourth": 4, "4th": 4,
            "fifth": 5, "5th": 5,
            "sixth": 6, "6th": 6,
            "seventh": 7, "7th": 7,
            "eighth": 8, "8th": 8,
            "ninth": 9, "9th": 9,
            "tenth": 10, "10th": 10,
            "eleventh": 11, "11th": 11,
            "twelfth": 12, "12th": 12,
            "thirteenth": 13, "13th": 13,
            "fourteenth": 14, "14th": 14,
            "fifteenth": 15, "15th": 15,
            "sixteenth": 16, "16th": 16,
            "seventeenth": 17, "17th": 17,
            "eighteenth": 18, "18th": 18,
            "nineteenth": 19, "19th": 19,
            "twentieth": 20, "20th": 20,
            "last": -1
        }
        if isinstance(ordinal, int):
            target_idx = ordinal
        elif isinstance(ordinal, str):
            ord_clean = ordinal.strip().lower()
            num_clean = re.sub(r'(?:st|nd|rd|th)$', '', ord_clean)
            if num_clean.isdigit():
                target_idx = int(num_clean)
            else:
                target_idx = ord_map.get(ord_clean, 0)
        else:
            target_idx = 1

        cat_filter = self._normalize_category(category) if category else None

        state = self.map_state.get_state()
        visible_markers = state.get("visible_markers", [])
        pool = list(self.spatial_results) if self.spatial_results else list(visible_markers)

        if not pool:
            return {
                "success": False,
                "action": "navigate_to_ordinal",
                "message": "No active search results or map markers found. Search for nearby places first."
            }

        if cat_filter:
            candidates = [p for p in pool if (p.get("category") or "").lower() == cat_filter]
            cat_label = cat_filter
        else:
            candidates = pool
            cat_label = "place"

        if not candidates:
            return {
                "success": False,
                "action": "navigate_to_ordinal",
                "category": cat_filter,
                "message": f"No {cat_filter}s were found in your recent search results."
            }

        total_cands = len(candidates)

        if target_idx == -1:
            resolved_index = total_cands
            target_place = candidates[-1]
            ord_label = f"last {cat_label}"
        elif 1 <= target_idx <= total_cands:
            resolved_index = target_idx
            target_place = candidates[target_idx - 1]
            ord_label = f"#{target_idx} {cat_label}"
        else:
            return {
                "success": False,
                "action": "navigate_to_ordinal",
                "index": target_idx,
                "category": cat_filter,
                "total_available": total_cands,
                "message": (
                    f"Selection #{target_idx} is out of range. "
                    f"There {'is' if total_cands == 1 else 'are'} only {total_cands} {cat_label}{'' if total_cands == 1 else 's'} "
                    f"available in your active search results."
                )
            }

        loc = self.detector.get_current_location(user_id=user_id)
        o_lat, o_lon = loc.get("latitude", 0.0), loc.get("longitude", 0.0)
        d_lat = float(target_place["latitude"])
        d_lon = float(target_place["longitude"])
        d_name = target_place["name"]
        target_id = target_place.get("id") or f"poi_{resolved_index}"
        straight_dist = float(target_place.get("distance_km") or haversine_distance_km(o_lat, o_lon, d_lat, d_lon))

        route_res = self.get_route(o_lat, o_lon, d_lat, d_lon, mode="driving")
        if not route_res.get("success"):
            return {
                "success": False,
                "action": "navigate_to_ordinal",
                "target": target_place,
                "message": f"Could not calculate driving route to {d_name}: {route_res.get('error', 'Routing service unreachable')}."
            }

        self.active_navigation = route_res
        self.active_navigation["origin_lat"] = o_lat
        self.active_navigation["origin_lon"] = o_lon
        self.active_navigation["dest_lat"] = d_lat
        self.active_navigation["dest_lon"] = d_lon
        self.active_navigation["destination_label"] = d_name
        self.selected_poi = target_place

        fastest = route_res["fastest_route"]
        dur = fastest["duration_minutes"]
        dist = fastest["distance_km"]
        eta = route_res["eta_fastest"]

        self.map_state.select_marker(target_id)
        self.map_state.set_active_route({
            "origin": "Your Location",
            "destination": d_name,
            "mode": "driving",
            "distance_km": dist,
            "duration_minutes": dur,
            "eta": eta,
            "geometry": fastest.get("geometry"),
            "steps": fastest.get("steps", [])
        })

        msg = (
            f"Navigating to {ord_label}: {d_name} ({dist:.2f} km driving distance, ~{int(dur)} mins, ETA {eta}). "
            f"Straight-line distance is {straight_dist:.2f} km. "
            f"Destination marker selected and route displayed on map."
        )

        return {
            "success": True,
            "action": "navigate_to_ordinal",
            "index": resolved_index,
            "requested_ordinal": ordinal,
            "category": cat_filter,
            "destination": d_name,
            "place_id": target_id,
            "latitude": d_lat,
            "longitude": d_lon,
            "distance_km": dist,
            "straight_line_km": straight_dist,
            "duration_minutes": dur,
            "eta": eta,
            "target": target_place,
            "route": route_res,
            "message": msg
        }

    def handle_command(self, user_input: str, user_id: Optional[Any] = None) -> Dict[str, Any]:
        """
        Central command handler for all location, routing, map, distance, and nearby place intents.
        """
        text = user_input.strip()
        text_low = text.lower()
        force_refresh = any(w in text_low for w in ["refresh", "update", "reload"])

        # ── 1. DIAGNOSTICS: Why is location unavailable? ──────────────────────
        if any(k in text_low for k in [
            "why is my location unavailable", "why can't you get my", "why cant you get my",
            "why is location unavailable", "why is my live location unavailable",
            "why can't you get my live location", "why cant you get my live location",
            "location diagnostics", "check location status"
        ]):
            diag = self.detector.get_diagnostics(user_id=user_id)
            phone_stat = diag.get("phone_status")
            phone_det = diag.get("phone_details")
            act_src = diag.get("active_source")

            reasons = []
            if phone_stat != "available":
                reasons.append(f"Phone GPS is not providing fresh coordinates ({phone_det}).")
            if diag.get("windows_location_status") != "available":
                reasons.append("Windows Location Services is disabled or unsupported on this platform.")

            msg = (
                f"Location service diagnostics:\n"
                f"• Active position source: {act_src}\n"
                f"• Mobile device GPS: {phone_stat} ({phone_det})\n"
                f"• Windows hardware positioning: {diag.get('windows_location_status')}\n"
            )
            if reasons:
                msg += "Causes: " + " ".join(reasons)
            else:
                msg += "All location providers are responding normally."

            return {
                "success": True,
                "action": "location_diagnostics",
                "diagnostics": diag,
                "message": msg,
            }

        # ── 1B. LOCATE CONNECTED PHONE ────────────────────────────────────────
        if any(k in text_low for k in [
            "locate my connected phone", "locate my phone", "locate phone",
            "find my phone", "track my phone", "where is my phone", "where is my connected phone",
            "phone location", "phone's location"
        ]):
            res = self.detector.get_phone_location(user_id=user_id)
            res_copy = dict(res)
            res_copy["action"] = "phone_location"
            res_copy["alias_action"] = "locate_phone"
            return res_copy

        # ── 1D. LOCATE COMPUTER / PC ──────────────────────────────────────────
        if any(k in text_low for k in [
            "where is my computer", "where is my pc", "locate my computer", "locate my pc",
            "find my computer", "find my pc", "track my computer", "track my pc",
            "computer location", "pc location", "computer's location", "pc's location"
        ]):
            res = self.detector.get_computer_location()
            return res

        # ── 1E. HOME / RESIDENCE LOCATION ("Where do I live?", "What is my home address?") ──
        if any(k in text_low for k in [
            "where do i live", "where is my home", "what is my home address",
            "my home location", "show my home", "where's my home", "what's my home address",
            "where do you think i live", "where am i living"
        ]):
            saved = self.resolve_saved_place("home", user_id=user_id) or self.resolve_saved_place("house", user_id=user_id)
            if not saved:
                all_saved = self.get_saved_places(user_id=user_id)
                for k, v in all_saved.items():
                    if k.lower() in ("home", "house", "residence", "apartment"):
                        saved = v
                        break

            mem_home = None
            try:
                from core.chatgpt_memory import get_chatgpt_memory
                uid_int = int(user_id) if (user_id and str(user_id).isdigit()) else 1
                facts = get_chatgpt_memory().get_user_facts(uid_int)
                mem_home = facts.get("home_address") or facts.get("home") or facts.get("address") or facts.get("city")
            except Exception:
                pass

            if saved:
                addr = saved.get("address") or f"{saved.get('latitude'):.4f}, {saved.get('longitude'):.4f}"
                msg = f"According to your saved places, your home is at {addr} (Coordinates: {saved.get('latitude'):.4f}, {saved.get('longitude'):.4f})."
                return {
                    "success": True,
                    "action": "home_location",
                    "home_saved": True,
                    "place": saved,
                    "latitude": saved.get("latitude"),
                    "longitude": saved.get("longitude"),
                    "address": addr,
                    "message": msg,
                }
            elif mem_home:
                msg = f"According to your saved profile information, you live in {mem_home}."
                return {
                    "success": True,
                    "action": "home_location",
                    "home_saved": True,
                    "address": mem_home,
                    "message": msg,
                }
            else:
                cur_loc = self.detector.get_current_location(user_id=user_id)
                cur_city = cur_loc.get("city") or "your current area"
                cur_src = cur_loc.get("source") or "detected location"
                msg = (
                    f"You do not have a home address saved in your settings or saved places yet. "
                    f"Your currently detected location is {cur_city} ({cur_loc.get('latitude'):.4f}, {cur_loc.get('longitude'):.4f}, via {cur_src}). "
                    f"You can say 'Save this place as Home' to save your current location as your home address."
                )
                return {
                    "success": True,
                    "action": "home_location",
                    "home_saved": False,
                    "current_location": cur_loc,
                    "message": msg,
                }


        # ── 1C. LAST UPDATED TIMESTAMP ────────────────────────────────────────
        if any(k in text_low for k in [
            "when was my location last updated", "when was location updated",
            "last location update", "location last updated"
        ]):
            loc = self.detector.get_current_location(user_id=user_id)
            ts = loc.get("measurement_timestamp")
            lbl = loc.get("freshness_label", "")
            src = loc.get("source", "")
            if ts:
                msg = f"Your location was last updated at {ts} ({lbl}, source: {src})."
            else:
                msg = f"Your location is currently marked as {lbl} (source: {src})."
            return {"success": True, "action": "last_updated", "timestamp": ts, "freshness_label": lbl, "source": src, "message": msg}

        # ── 2. EXACT COORDINATES & ACCURACY QUERIES ────────────────────────────
        if any(k in text_low for k in ["exact coordinates", "show my coordinates", "what are my coordinates", "my coordinates"]):
            loc = self.detector.get_current_location(force_refresh=force_refresh, user_id=user_id)
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            acc = loc.get("accuracy_m")
            src = loc.get("source")
            freshness = loc.get("freshness_label", "")

            if lat and lon and abs(lat) > 0.0001:
                acc_txt = f" with horizontal accuracy ±{int(acc)}m" if acc else ""
                msg = f"Your exact coordinates are {lat:.6f}, {lon:.6f} ({freshness}{acc_txt}, source: {src})."
                return {
                    "success": True,
                    "action": "coordinates",
                    "latitude": lat,
                    "longitude": lon,
                    "accuracy_m": acc,
                    "source": src,
                    "location": loc,
                    "message": msg,
                }
            return {"success": False, "message": "Could not retrieve exact geographic coordinates."}

        if any(k in text_low for k in ["how accurate", "accuracy of my location", "location accuracy"]):
            loc = self.detector.get_current_location(force_refresh=force_refresh, user_id=user_id)
            acc = loc.get("accuracy_m")
            src = loc.get("source")
            if acc:
                msg = f"Your current location accuracy is ±{int(acc)} meters (determined via {src})."
            elif src == "ip_geolocation":
                msg = "Your location is determined via IP geolocation, which is approximate (estimated accuracy ±5-20 km)."
            else:
                msg = f"Location accuracy is currently unspecified for source '{src}'."
            return {"success": True, "action": "accuracy", "accuracy_m": acc, "source": src, "message": msg}

        # ── 3. PROVIDER / SOURCE / DEVICE QUERY ────────────────────────────────
        if any(k in text_low for k in ["which device is providing", "location source", "location provider", "how do you know my location", "what device"]):
            loc = self.detector.get_current_location(force_refresh=force_refresh, user_id=user_id)
            src = loc.get("source")
            dev_name = loc.get("device_name") or loc.get("device_id") or "device"
            city = loc.get("city")
            if src == "phone_gps":
                msg = f"Your location is being provided by your connected {dev_name} via real-time GPS telemetry (Current area: {city})."
            elif src == "windows_hardware_location":
                msg = f"Your location is being provided by Windows Location Services using PC Wi-Fi and hardware positioning (Current area: {city})."
            elif src == "ip_geolocation":
                msg = f"Your location is currently determined using approximate IP network geolocation (ISP routing). Detected area: {city}."
            else:
                msg = "Location services are currently using fallback system status."
            return {"success": True, "action": "provider", "source": src, "device_name": dev_name, "message": msg}

        # ── 4. PERSISTENT MAP VIEW CONTROLS & DISPLAY ─────────────────────────
        # Keep map open persistently
        if any(k in text_low for k in ["keep the map open", "keep map open", "leave the map open", "pin the map"]):
            self.map_state.keep_map_open()
            return {
                "success": True,
                "action": "map_keep_open",
                "message": "The assistant's interactive map will remain open persistently in your dashboard."
            }

        # Close / hide map view cleanly
        if any(k in text_low for k in ["close the map", "close map", "hide the map", "hide map"]):
            self.map_state.close_map()
            return {
                "success": True,
                "action": "map_close",
                "message": "Closed the map view."
            }

        # Clear route polyline and active navigation
        if any(k in text_low for k in ["clear the route", "clear route", "stop navigation", "cancel navigation", "end route"]):
            self.active_navigation = None
            self.map_state.clear_route()
            return {
                "success": True,
                "action": "clear_route",
                "message": "Cleared the active navigation route and path from the map."
            }

        # Zoom in / out controls
        if re.search(r'\bzoom\s+in\b', text_low):
            new_zoom = self.map_state.adjust_zoom(+2)
            return {
                "success": True,
                "action": "map_zoom_in",
                "zoom": new_zoom,
                "message": f"Zoomed in on the map (zoom level {new_zoom})."
            }

        if re.search(r'\bzoom\s+out\b', text_low):
            new_zoom = self.map_state.adjust_zoom(-2)
            return {
                "success": True,
                "action": "map_zoom_out",
                "zoom": new_zoom,
                "message": f"Zoomed out on the map (zoom level {new_zoom})."
            }

        # ── 4A. CONTEXTUAL SPATIAL FOLLOW-UPS & ADDRESS RESOLUTION ────────────
        # "Show me the address", "Show me its address", "What is the address", "What is its address"
        if any(k in text_low for k in [
            "show me the address", "show me its address", "show the address", "show its address",
            "what is the address", "what is its address", "whats the address", "what's the address",
            "whats its address", "what's its address", "tell me the address", "tell me its address",
            "give me the address", "give me its address", "the address", "its address"
        ]) or (text_low.strip() == "address"):
            target = None
            if self.active_navigation and self.active_navigation.get("destination_label"):
                d_label = self.active_navigation.get("destination_label")
                for p in (self.spatial_results or self.map_state.markers):
                    if p.get("name") == d_label:
                        target = p
                        break
            if not target:
                target = self.selected_poi
            if not target and (self.spatial_results or self.map_state.markers):
                target = (self.spatial_results or self.map_state.markers)[0]

            if target:
                name = target.get("name", "Selected place")
                cat = target.get("category", "place").title()
                addr = target.get("address") or target.get("display_name") or f"{target.get('latitude', 0.0):.4f}, {target.get('longitude', 0.0):.4f}"
                dist = target.get("distance_km")
                dist_str = f" ({dist:.2f} km away)" if dist is not None else ""
                msg = f"The address of {name} ({cat}) is {addr}{dist_str}."
                return {
                    "success": True,
                    "action": "address_query",
                    "target_type": "place",
                    "name": name,
                    "address": addr,
                    "place": target,
                    "message": msg
                }

            loc = self.detector.get_current_location(user_id=user_id)
            addr = loc.get("display_name") or loc.get("address")
            city = loc.get("city", "your current city")
            src = loc.get("source", "detected")
            acc = loc.get("accuracy_m")
            acc_str = f" (accuracy ±{int(acc)}m)" if acc else ""
            if addr:
                msg = f"Your current address is {addr}{acc_str} (via {src})."
            else:
                locality = loc.get("locality") or ""
                parts = [p for p in [locality, city, loc.get("district"), loc.get("state"), loc.get("country")] if p]
                place_str = ", ".join(parts) if parts else city
                msg = f"Your current detected location is {place_str}{acc_str} (via {src})."
            return {
                "success": True,
                "action": "address_query",
                "target_type": "current_location",
                "address": addr or place_str,
                "location": loc,
                "message": msg
            }

        # "What are there?" / "What is there?" / "Show them" / "List them"
        if any(k in text_low for k in [
            "what are there", "what is there", "whats there", "what's there",
            "what places are there", "show them", "list them", "what did you find",
            "show the places", "tell me the places", "what are the places"
        ]):
            places = self.spatial_results or self.map_state.markers
            if places:
                cat_name = self.active_categories[0].title() + "s" if self.active_categories else "places"
                lines = [f"Here are the {len(places)} {cat_name} near your location:"]
                for p in places:
                    idx = p.get("index", "")
                    name = p.get("name", "Unknown")
                    dist = p.get("distance_km", 0.0)
                    addr = p.get("address", "")
                    addr_short = f" on {addr.split(',')[1].strip()}" if "," in addr else ""
                    lines.append(f"• #{idx}. {name} ({dist:.2f} km away{addr_short})")
                return {
                    "success": True,
                    "action": "list_discovered_places",
                    "places": places,
                    "message": "\n".join(lines)
                }
            return {
                "success": False,
                "action": "list_discovered_places",
                "message": "No places were recently discovered. Ask to find nearby restaurants, hospitals, or pharmacies first."
            }

        # "Which is closest?" / "Which one is closest?" / "Which is nearest?"
        if any(k in text_low for k in [
            "which is closest", "which one is closest", "what is closest", "what is the closest",
            "which is nearest", "which one is nearest", "what is nearest", "what is the nearest",
            "find the nearest one", "closest one", "nearest one"
        ]):
            places = self.spatial_results or self.map_state.markers
            if places:
                closest = min(places, key=lambda p: float(p.get("distance_km", 9999.0)))
                self.selected_poi = closest
                self.map_state.select_marker(closest.get("id"))
                c_name = closest.get("name")
                c_cat = closest.get("category", "place").title()
                c_dist = float(closest.get("distance_km", 0.0))
                c_addr = closest.get("address") or f"{closest.get('latitude', 0.0):.4f}, {closest.get('longitude', 0.0):.4f}"
                msg = f"The closest one is #{closest.get('index', 1)}. {c_name} ({c_cat}), located {c_dist:.2f} km away at {c_addr}."
                return {
                    "success": True,
                    "action": "closest_place",
                    "place": closest,
                    "selected_poi": closest,
                    "message": msg
                }
            return {
                "success": False,
                "action": "closest_place",
                "message": "No discovered places found to determine which is closest. Search for nearby places first."
            }

        # "Tell me about the first one" / "Tell me about the second one"
        m_tell_about = re.search(
            r'\b(?:tell\s+me\s+about|info\s+(?:on|about)|details\s+(?:on|about|for)|show\s+details\s+of)\s+(?:the\s+)?(\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|closest|nearest|last)\s*(?:one|place|restaurant|hospital|pharmacy)?\b',
            text_low
        )
        if m_tell_about:
            ord_word = m_tell_about.group(1).lower().strip()
            target_idx = self._parse_ordinal(ord_word)
            places = self.spatial_results or self.map_state.markers
            if places:
                if target_idx == -1:
                    chosen = places[-1]
                elif 1 <= target_idx <= len(places):
                    chosen = places[target_idx - 1]
                else:
                    chosen = places[0]
                self.selected_poi = chosen
                self.map_state.select_marker(chosen.get("id"))
                name = chosen.get("name")
                cat = chosen.get("category", "place").title()
                dist = chosen.get("distance_km", 0.0)
                addr = chosen.get("address") or f"{chosen.get('latitude', 0.0):.4f}, {chosen.get('longitude', 0.0):.4f}"
                msg = f"Details for #{chosen.get('index', target_idx)}. {name} ({cat}): Located at {addr}, approximately {dist:.2f} km away."
                return {
                    "success": True,
                    "action": "place_details",
                    "place": chosen,
                    "message": msg
                }

        # Display current location on single persistent map
        if any(k in text_low for k in [
            "show my current location on the map", "show my location on the map",
            "show my device location on the map", "show device location on the map",
            "show on map", "open map", "view on map", "open my location in maps",
            "open in google maps", "open my location in google maps", "open google maps",
            "show the map", "open the map", "show map", "display the map", "open map window",
            "show desktop map", "show my location", "show my current location"
        ]):
            loc = self.detector.get_current_location(force_refresh=force_refresh, user_id=user_id)
            lat = loc.get("latitude")
            lon = loc.get("longitude")
            city = loc.get("city")
            maps_url = loc.get("maps_url") or f"https://www.google.com/maps?q={lat},{lon}"
            osm_url = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=15/{lat}/{lon}"

            # Update authoritative map state in place
            self.map_state.update_user_location(loc)

            # Check if external Google Maps specifically requested
            is_google_external = "google maps" in text_low or "in google maps" in text_low
            if is_google_external:
                try:
                    from modules.browser.browser_controller import open_url
                    open_url(maps_url)
                except Exception:
                    try:
                        import webbrowser
                        webbrowser.open(maps_url)
                    except Exception:
                        pass
                msg = f"Opened your current location ({city}) in Google Maps: {maps_url}"
                opened = True
            else:
                # Open or reuse single persistent map instance
                opened = self.map_state.open_map(force_browser=False)
                if opened:
                    msg = f"Displaying your current location ({city}) on the assistant's interactive map."
                    success_val = True
                else:
                    msg = f"Your current location is {city}, but the native desktop map window could not be opened."
                    success_val = False

            return {
                "success": success_val,
                "action": "map_view",
                "latitude": lat,
                "longitude": lon,
                "city": city,
                "google_maps_url": maps_url,
                "openstreetmap_url": osm_url,
                "maps_url": maps_url,
                "map_opened": opened,
                "message": msg,
            }

        # ── 4D. SPATIAL & MAP CONVERSATIONAL FOLLOW-UPS ──────────────────────
        # "Show only hospitals", "Filter to pharmacies"
        m_filter = re.search(r'\b(?:show\s+only|filter\s+(?:by|to)|only\s+show)\s+(hospitals?|pharmacies|pharmacy|restaurants?|petrol\s+stations?|gas\s+stations?|fuel\s+stations?|atms?|hotels?|banks?)\b', text_low)
        if m_filter:
            raw_cat = m_filter.group(1).strip()
            cat = self._normalize_category(raw_cat)
            self.map_state.filter_categories([cat])
            state = self.map_state.get_state()
            visible = state["visible_markers"]
            msg = f"Filtered the map to show only {raw_cat} ({len(visible)} places visible on the map)."
            return {
                "success": True,
                "action": "filter_map_category",
                "category": cat,
                "visible_count": len(visible),
                "visible_places": visible,
                "message": msg
            }

        # "Add pharmacies"
        m_add = re.search(r'\b(?:add|include)\s+(hospitals?|pharmacies|pharmacy|restaurants?|petrol\s+stations?|gas\s+stations?|fuel\s+stations?|atms?|hotels?|banks?)\b|\bshow\s+(hospitals?|pharmacies|pharmacy|restaurants?|petrol\s+stations?|gas\s+stations?|fuel\s+stations?|atms?|hotels?|banks?)\s+(?:too|as\s+well|also)\b', text_low)
        if m_add and not any(w in text_low for w in ["stop", "waypoint"]):
            raw_cat = (m_add.group(1) or m_add.group(2)).strip()
            cat = self._normalize_category(raw_cat)
            # Check if this category is already in the map discovery cache
            state_before = self.map_state.get_state()
            cached_matching = [m for m in state_before["cached_markers"] if (m.get("category") or "").lower() == cat]
            if cached_matching:
                self.map_state.add_category(cat)
                state_after = self.map_state.get_state()
                msg = f"Added {raw_cat} to the map ({len(cached_matching)} places shown, {len(state_after['visible_markers'])} total visible)."
                return {
                    "success": True,
                    "action": "add_map_category",
                    "category": cat,
                    "places": cached_matching,
                    "added_count": len(cached_matching),
                    "visible_count": len(state_after["visible_markers"]),
                    "message": msg
                }
            else:
                loc = self.detector.get_current_location(user_id=user_id)
                lat, lon = loc.get("latitude", 0.0), loc.get("longitude", 0.0)
                new_places = self.search_nearby(cat, lat, lon, radius_km=5.0, limit=5)
                for p in new_places:
                    p["category"] = cat
                self.map_state.set_markers(new_places, category=cat, append=True)
                self.map_state.add_category(cat)
                state_after = self.map_state.get_state()
                msg = f"Added {raw_cat} to the map ({len(new_places)} places displayed, {len(state_after['visible_markers'])} total visible)."
                return {
                    "success": True,
                    "action": "add_map_category",
                    "category": cat,
                    "places": new_places,
                    "added_count": len(new_places),
                    "visible_count": len(state_after["visible_markers"]),
                    "message": msg
                }

        # "Remove restaurants"
        m_rem = re.search(r'\b(?:remove|hide|exclude)\s+(hospitals?|pharmacies|pharmacy|restaurants?|petrol\s+stations?|gas\s+stations?|fuel\s+stations?|atms?|hotels?|banks?)\b', text_low)
        if m_rem:
            raw_cat = m_rem.group(1).strip()
            cat = self._normalize_category(raw_cat)
            self.map_state.remove_category(cat)
            state_after = self.map_state.get_state()
            msg = f"Removed {raw_cat} from the map display ({len(state_after['visible_markers'])} places remaining visible)."
            return {
                "success": True,
                "action": "remove_map_category",
                "category": cat,
                "visible_count": len(state_after["visible_markers"]),
                "message": msg
            }

        # "Show all of them" / "Show all places"
        if any(k in text_low for k in ["show all of them", "show all places", "show all markers", "show all", "reset filters", "clear filters"]):
            self.map_state.show_all()
            total = len(self.map_state.markers)
            msg = f"Showing all {total} discovered places on the map."
            return {
                "success": True,
                "action": "show_all_places",
                "total_places": total,
                "message": msg
            }

        # "Go to the second hospital" / "Navigate to the second one" / "Go to the first one" / "Go to the last pharmacy"
        is_discovery_lead = bool(re.search(r'\b(?:find|search|look\s+for|show\s+me)\b', text_low) and any(c in text_low for c in ["hospital", "pharmacy", "restaurant", "places", "nearby"]))
        m_ordinal = None if is_discovery_lead else re.search(
            r'\b(?:go\s+to|navigate\s+to|take\s+me\s+to|select)\s+(?:the\s+)?(\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|seventeenth|eighteenth|nineteenth|twentieth|last)(?:\s+(one|place|hospital|pharmacy|restaurant|petrol\s+station|gas\s+station|fuel\s+station|atm|hotel|bank|stop|candidate|option|result))?\b',
            text_low
        )
        if m_ordinal:
            ord_word = m_ordinal.group(1).lower()
            raw_target_type = m_ordinal.group(2).lower() if m_ordinal.group(2) else ""
            if raw_target_type in ("one", "place", "stop", "candidate", "option", "result"):
                cat_spec = None
            elif raw_target_type:
                cat_spec = self._normalize_category(raw_target_type)
            else:
                cat_spec = None
            return self.navigate_to_ordinal(ord_word, category=cat_spec, user_id=user_id)

        # "Navigate there" / "Take me there"
        if any(k in text_low for k in ["navigate there", "take me there", "route there", "directions there"]):
            if self.spatial_results or self.map_state.markers:
                target_place = self.spatial_results[0] if self.spatial_results else self.map_state.markers[0]
                loc = self.detector.get_current_location(user_id=user_id)
                o_lat, o_lon = loc.get("latitude", 0.0), loc.get("longitude", 0.0)
                d_lat = float(target_place["latitude"])
                d_lon = float(target_place["longitude"])
                d_name = target_place["name"]

                route_res = self.get_route(o_lat, o_lon, d_lat, d_lon, mode="driving")
                if route_res.get("success"):
                    self.active_navigation = route_res
                    fastest = route_res["fastest_route"]
                    dur = fastest["duration_minutes"]
                    dist = fastest["distance_km"]
                    eta = route_res["eta_fastest"]

                    self.map_state.select_marker(target_place.get("id") or 1)
                    self.map_state.set_active_route({
                        "origin": "Your Location",
                        "destination": d_name,
                        "mode": "driving",
                        "distance_km": dist,
                        "duration_minutes": dur,
                        "eta": eta,
                        "geometry": fastest.get("geometry"),
                        "steps": fastest.get("steps", [])
                    })

                    msg = (
                        f"Navigating to {d_name} ({dist:.1f} km away). "
                        f"Estimated travel time is ~{int(dur)} minutes (ETA {eta}). Route displayed on map."
                    )
                    return {
                        "success": True,
                        "action": "navigate_there",
                        "destination": d_name,
                        "distance_km": dist,
                        "duration_minutes": dur,
                        "eta": eta,
                        "message": msg
                    }

        # Place details ("show details of that hospital", "show details of that place", "details of that hospital")
        if any(k in text_low for k in [
            "show details of that hospital", "show details of that restaurant", "show details of that place",
            "details of that hospital", "details of that place", "place details", "tell me more about that hospital",
            "tell me more about that place", "details of the second hospital", "show details"
        ]):
            chosen = self.selected_poi
            if not chosen:
                state = self.map_state.get_state()
                if state.get("selected_place_id"):
                    sel_id = state.get("selected_place_id")
                    for m in state.get("cached_markers", []):
                        if m.get("id") == sel_id:
                            chosen = m
                            break
            if not chosen and (self.spatial_results or self.map_state.markers):
                chosen = (self.spatial_results or self.map_state.markers)[0]

            if chosen:
                name = chosen.get("name", "Selected place")
                cat = chosen.get("category", "place").title()
                dist = chosen.get("distance_km")
                addr = chosen.get("address") or chosen.get("display_name") or f"{chosen.get('latitude', 0.0):.4f}, {chosen.get('longitude', 0.0):.4f}"
                dist_str = f", approximately {dist:.2f} km away" if dist is not None else ""
                route_str = ""
                if self.active_navigation and self.active_navigation.get("destination_label") == name:
                    fastest = self.active_navigation.get("fastest_route", {})
                    dur = fastest.get("duration_minutes", 0)
                    route_str = f" An active route is planned ({dur:.0f} mins, ETA: {self.active_navigation.get('eta_fastest')})."

                msg = f"Details for {name} ({cat}): Located at {addr}{dist_str}.{route_str}"
                return {
                    "success": True,
                    "action": "place_details",
                    "place": chosen,
                    "name": name,
                    "category": cat,
                    "distance_km": dist,
                    "address": addr,
                    "message": msg
                }
            return {
                "success": False,
                "action": "place_details",
                "message": "No place is currently selected or discovered. Ask to find nearby places first."
            }

        # ── 4B. ETA QUERIES ("What is the ETA from Guntur to Tenali by car?") ─
        m_eta = re.search(r'\b(?:what\s+is\s+(?:the\s+)?eta|eta)\s+(?:from\s+)?(.+?)\s+(?:to)\s+(.+)', text_low)
        if m_eta:
            orig_name = m_eta.group(1).strip()
            rest = m_eta.group(2).strip()
            mode = "driving"
            if "walk" in rest or "foot" in rest:
                mode = "walking"
            elif "cycle" in rest or "bike" in rest:
                mode = "cycling"
            dest_name = re.sub(r'\s+by\s+(?:car|driving|bike|cycle|walking|foot)\b.*', '', rest, flags=re.IGNORECASE).strip()
            dest_name = re.sub(r'[?.!]+$', '', dest_name).strip()

            clean_orig = re.sub(r'^(?:my\s+|the\s+)?', '', orig_name).strip().lower()
            if orig_name and clean_orig not in ("current location", "location", "here", "where i am"):
                orig_candidates = self.geocode(orig_name)
                if not orig_candidates:
                    return {"success": False, "message": f"Could not find origin place '{orig_name}'."}
                o_lat, o_lon = orig_candidates[0]["latitude"], orig_candidates[0]["longitude"]
                o_label = orig_candidates[0]["display_name"].split(",")[0]
            else:
                cur_loc = self.detector.get_current_location(user_id=user_id)
                o_lat, o_lon = cur_loc.get("latitude", 0.0), cur_loc.get("longitude", 0.0)
                o_label = "your current location"

            dest_candidates = self.geocode(dest_name)
            if not dest_candidates:
                return {"success": False, "message": f"Could not find destination place '{dest_name}'."}
            d_lat, d_lon = dest_candidates[0]["latitude"], dest_candidates[0]["longitude"]
            d_label = dest_candidates[0]["display_name"].split(",")[0]

            route_res = self.get_route(o_lat, o_lon, d_lat, d_lon, mode=mode)
            if route_res.get("success"):
                fastest = route_res["fastest_route"]
                dur = fastest["duration_minutes"]
                dist = fastest["distance_km"]
                eta_str = route_res["eta_fastest"]
                msg = f"The estimated travel time from {o_label} to {d_label} by {mode} is approximately {int(dur)} minutes ({dist:.1f} km). Estimated arrival time is {eta_str}."
                return {
                    "success": True,
                    "action": "eta",
                    "origin": o_label,
                    "destination": d_label,
                    "mode": mode,
                    "duration_minutes": dur,
                    "distance_km": dist,
                    "eta": eta_str,
                    "message": msg,
                }

        # ── 5. DISTANCE QUERIES ("How far is X?", "Distance between A and B") ──
        m_dist_between = re.search(r'\b(?:distance\s+between|how\s+far\s+is\s+it\s+from|calculate\s+(?:the\s+)?distance\s+between)\s+(.+?)\s+(?:and|to)\s+(.+)', text_low)
        m_dist_single = re.search(r'\b(?:how\s+far\s+is|distance\s+to)\s+(.+)', text_low)

        if m_dist_between or m_dist_single:
            if m_dist_between:
                orig_name = m_dist_between.group(1).strip()
                dest_name = m_dist_between.group(2).strip()
                orig_candidates = self.geocode(orig_name)
                if not orig_candidates:
                    return {"success": False, "message": f"Could not find coordinates for origin place '{orig_name}'."}
                o_lat, o_lon = orig_candidates[0]["latitude"], orig_candidates[0]["longitude"]
                o_label = orig_candidates[0]["display_name"].split(",")[0]
            else:
                dest_name = m_dist_single.group(1).strip()
                # Remove question mark or punctuation
                dest_name = re.sub(r'[?.!]+$', '', dest_name).strip()
                # If destination is "the destination" and we have an active route
                if dest_name in ("the destination", "destination", "it", "there") and self.active_navigation:
                    dest_name = self.active_navigation.get("destination_label", dest_name)
                    d_lat = self.active_navigation.get("dest_lat")
                    d_lon = self.active_navigation.get("dest_lon")
                cur_loc = self.detector.get_current_location(user_id=user_id)
                o_lat, o_lon = cur_loc.get("latitude", 0.0), cur_loc.get("longitude", 0.0)
                o_label = "your current location"

            # Resolve destination
            dest_candidates = self.geocode(dest_name)
            if not dest_candidates:
                return {"success": False, "message": f"Could not locate destination place '{dest_name}'."}
            d_lat, d_lon = dest_candidates[0]["latitude"], dest_candidates[0]["longitude"]
            d_label = dest_candidates[0]["display_name"].split(",")[0]

            # Calculate straight-line Haversine
            straight_km = haversine_distance_km(o_lat, o_lon, d_lat, d_lon)

            # Calculate road distance via OSRM
            route_res = self.get_route(o_lat, o_lon, d_lat, d_lon, mode="driving")
            if route_res.get("success"):
                fastest = route_res["fastest_route"]
                road_km = fastest["distance_km"]
                dur_mins = fastest["duration_minutes"]
                msg = (
                    f"The distance from {o_label} to {d_label} is {road_km:.1f} km by road "
                    f"(approximately {int(dur_mins)} minutes driving). "
                    f"Straight-line distance is {straight_km:.1f} km."
                )
                return {
                    "success": True,
                    "action": "distance",
                    "origin": o_label,
                    "destination": d_label,
                    "straight_distance_km": round(straight_km, 2),
                    "road_distance_km": road_km,
                    "duration_minutes": dur_mins,
                    "message": msg,
                }
            else:
                msg = f"The straight-line distance from {o_label} to {d_label} is {straight_km:.1f} km."
                return {
                    "success": True,
                    "action": "distance",
                    "origin": o_label,
                    "destination": d_label,
                    "straight_distance_km": round(straight_km, 2),
                    "road_distance_km": None,
                    "message": msg,
                }

        # ── 6. MULTI-INTENT SPATIAL DISCOVERY & NEARBY PLACES ─────────────────
        categories_dict = {
            "hospital": ["hospital", "hospitals", "hospitel", "hospitels", "clinic", "clinics", "doctor"],
            "pharmacy": ["pharmacy", "pharmacies", "farmacy", "farmacies", "parmacy", "parmacies", "chemist", "chemists", "medical shop", "medical store", "medical stores"],
            "restaurant": ["restaurant", "restaurants", "restarent", "restarents", "restarant", "restarants", "resturant", "resturants", "restaraunt", "restaraunts", "resteraunt", "resteraunts", "restraunt", "restraunts", "food", "dining", "cafe", "cafes", "eatery", "eateries"],
            "fuel station": ["petrol station", "petrol stations", "petrol pump", "petrol pumps", "gas station", "gas stations", "fuel station", "fuel stations", "fuel"],
            "atm": ["atm", "atms", "cash machine"],
            "bank": ["bank", "banks"],
            "hotel": ["hotel", "hotels", "lodging"],
            "supermarket": ["supermarket", "supermarkets", "grocery", "groceries"],
            "parking": ["parking", "parking lot"]
        }

        matched_categories = []
        for cat_canon, keywords in categories_dict.items():
            for kw in keywords:
                if re.search(r'\b' + re.escape(kw) + r'\b', text_low):
                    if cat_canon not in matched_categories:
                        matched_categories.append(cat_canon)
                    break

        # Fallback to restaurant if user asks for nearby food/places without explicit category match
        if not matched_categories and any(k in text_low for k in ["nearby", "near me", "around me", "around here"]):
            if any(w in text_low for w in ["restar", "restur", "restra", "resten", "food", "eat", "dining", "lunch", "dinner"]):
                matched_categories = ["restaurant"]

        is_spatial_discovery = (
            bool(matched_categories)
            and (
                any(k in text_low for k in [
                    "find", "search", "show", "look for", "where is", "where are", "locate",
                    "near me", "nearby", "around here", "around me", "close by", "closest", "nearest", "filter out", "route"
                ])
                or len(matched_categories) > 1
            )
        )

        if is_spatial_discovery:
            # 1. Acquire user location fix ONCE
            loc = self.detector.get_current_location(user_id=user_id)
            lat, lon = loc.get("latitude", 0.0), loc.get("longitude", 0.0)
            if abs(lat) < 0.0001:
                return {"success": False, "message": "Cannot search nearby places without your current location."}
            self.map_state.update_user_location(loc)

            # 2. Extract distance filter (e.g. "filter out anything more than 5 km away", "within 5 km")
            m_dist_filter = re.search(r'\b(?:filter\s+out\s+anything\s+more\s+than|within|under|less\s+than|max\s+distance\s+(?:of\s+)?)\s*(\d+(?:\.\d+)?)\s*(?:km|kilometers|miles)?', text_low)
            max_dist_km = float(m_dist_filter.group(1)) if m_dist_filter else None

            # 3. Extract route / ETA intent for closest or ordinal target
            wants_route = any(w in text_low for w in ["route", "how long it takes", "travel time", "duration", "eta", "navigate"])
            m_ordinal_route = re.search(
                r'\b(?:navigate|route|go|directions?)\s+(?:to\s+)?(?:the\s+)?(\d+(?:st|nd|rd|th)?|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|last)\s+(hospital|pharmacy|restaurant|petrol\s+station|gas\s+station|fuel\s+station|atm|hotel|one|place)?\b',
                text_low
            )
            m_target_route_cat = re.search(r'(?:closest|nearest)\s+(hospital|pharmacy|restaurant|petrol\s+station|gas\s+station|petrol\s+pump|fuel\s+station|atm|hotel)', text_low)
            route_target_cat = self._normalize_category(m_target_route_cat.group(1)) if m_target_route_cat else (matched_categories[0] if matched_categories else "hospital")

            # 4. Extract map display intent
            wants_map = any(w in text_low for w in ["show on map", "show them on the map", "show on the map", "on the map", "in maps", "open map", "view on map"])

            # 5. Search nearby for each requested category using the single location fix
            search_radius = max(5.0, (max_dist_km * 1.2) if max_dist_km else 5.0)
            all_discovered = []
            places_by_cat = {}
            for cat in matched_categories:
                cat_results = self.search_nearby(cat, lat, lon, radius_km=search_radius, limit=5)
                for p in cat_results:
                    p["category"] = cat
                places_by_cat[cat] = cat_results
                all_discovered.extend(cat_results)

            # 6. Apply distance filter
            kept_places = []
            excluded_places = []
            if max_dist_km is not None:
                for p in all_discovered:
                    if p["distance_km"] <= max_dist_km:
                        kept_places.append(p)
                    else:
                        excluded_places.append(p)
            else:
                kept_places = list(all_discovered)

            # Assign 1-based indexing
            for idx, p in enumerate(kept_places):
                p["index"] = idx + 1
                p["id"] = f"poi_{idx+1}"

            self.spatial_results = kept_places
            self.active_categories = matched_categories

            # 7. Calculate route to requested candidate (ordinal or closest) if requested
            route_info = None
            closest_target = None
            if wants_route and kept_places:
                if m_ordinal_route:
                    ord_word = m_ordinal_route.group(1).lower().strip()
                    target_idx = self._parse_ordinal(ord_word)
                    cat_word = m_ordinal_route.group(2)
                    if cat_word and self._normalize_category(cat_word) in matched_categories:
                        route_cat = self._normalize_category(cat_word)
                    elif m_target_route_cat:
                        route_cat = self._normalize_category(m_target_route_cat.group(1))
                    else:
                        route_cat = route_target_cat

                    cat_cands = [p for p in kept_places if (p.get("category") or "").lower() == route_cat]
                    if not cat_cands:
                        cat_cands = kept_places
                    cat_cands.sort(key=lambda x: x.get("distance_km", 0.0))

                    if target_idx == -1:
                        closest_target = cat_cands[-1]
                    elif 1 <= target_idx <= len(cat_cands):
                        closest_target = cat_cands[target_idx - 1]
                    else:
                        closest_target = cat_cands[0]
                else:
                    cat_cands = [p for p in kept_places if (p.get("category") or "").lower() == route_target_cat]
                    if not cat_cands:
                        cat_cands = kept_places
                    cat_cands.sort(key=lambda x: x.get("distance_km", 0.0))
                    closest_target = cat_cands[0]

                self.selected_poi = closest_target
                d_lat = float(closest_target["latitude"])
                d_lon = float(closest_target["longitude"])
                d_name = closest_target["name"]

                route_res = self.get_route(lat, lon, d_lat, d_lon, mode="driving")
                if route_res.get("success"):
                    self.active_navigation = route_res
                    self.active_navigation["origin_lat"] = lat
                    self.active_navigation["origin_lon"] = lon
                    self.active_navigation["dest_lat"] = d_lat
                    self.active_navigation["dest_lon"] = d_lon
                    self.active_navigation["destination_label"] = d_name

                    fastest = route_res["fastest_route"]
                    dur = fastest["duration_minutes"]
                    dist = fastest["distance_km"]
                    eta = route_res["eta_fastest"]

                    route_info = {
                        "origin": "Your Location",
                        "destination": d_name,
                        "mode": "driving",
                        "distance_km": dist,
                        "duration_minutes": dur,
                        "eta": eta,
                        "geometry": fastest.get("geometry"),
                        "steps": fastest.get("steps", [])
                    }

            # 8. Update authoritative persistent map state in place
            self.map_state.set_markers(kept_places, append=False)
            if route_info:
                self.map_state.set_active_route(route_info)
                if closest_target:
                    self.map_state.select_marker(closest_target.get("id"))

            if wants_map or len(matched_categories) > 1 or wants_route:
                self.map_state.open_map(force_browser=False)

            # 9. Build consolidated natural-language response
            lines = []
            lines.append(f"Found {len(kept_places)} places across {len(matched_categories)} categories near your location:")
            for cat in matched_categories:
                items = [p for p in kept_places if (p.get("category") or "").lower() == cat]
                cat_name = cat.title() + "s"
                lines.append(f"\n• {cat_name} ({len(items)} found):")
                if items:
                    for p in items:
                        lines.append(f"   #{p['index']}. {p['name']} ({p['distance_km']} km away)")
                else:
                    lines.append("   (None found within range)")

            if max_dist_km is not None:
                lines.append(f"\n(Distance filter applied: Filtered out {len(excluded_places)} places located beyond {max_dist_km:.1f} km).")

            if route_info and closest_target:
                dest_label = f"#{closest_target.get('index', '')} {closest_target['name']}" if closest_target.get('index') else closest_target['name']
                lines.append(
                    f"\nRoute to {dest_label} ({closest_target.get('category', '').title()}): "
                    f"{route_info['distance_km']} km, estimated travel time {int(route_info['duration_minutes'])} minutes (ETA {route_info['eta']})."
                )

            lines.append("\nAll markers and active routes have been updated in your assistant's persistent map.")
            msg = "\n".join(lines)

            return {
                "success": True,
                "action": "multi_intent_spatial_discovery",
                "categories": matched_categories,
                "places": kept_places,
                "total_found": len(kept_places),
                "filter_max_dist_km": max_dist_km,
                "excluded_count": len(excluded_places),
                "route": route_info,
                "closest_target": closest_target,
                "map_updated": True,
                "message": msg
            }

        # ── 6B. ROUTE COMPARISON ("Compare the fastest and shortest routes to Vijayawada") ──
        m_comp = re.search(r'\bcompare\s+(?:the\s+)?fastest\s+and\s+shortest\s+routes\s+(?:to\s+)?(.+)', text_low)
        if m_comp:
            dest_raw = m_comp.group(1).strip().rstrip('?.!')
            cur_loc = self.detector.get_current_location(user_id=user_id)
            o_lat, o_lon = cur_loc.get("latitude", 0.0), cur_loc.get("longitude", 0.0)
            o_label = "your current location"

            dest_candidates = self.geocode(dest_raw)
            if not dest_candidates:
                return {"success": False, "message": f"Could not find destination place '{dest_raw}'."}
            d_lat, d_lon = dest_candidates[0]["latitude"], dest_candidates[0]["longitude"]
            d_label = dest_candidates[0]["display_name"].split(",")[0]

            route_res = self.get_route(o_lat, o_lon, d_lat, d_lon, mode="driving")
            if route_res.get("success"):
                fastest = route_res["fastest_route"]
                shortest = route_res["shortest_route"]
                # Check if fastest and shortest are actually the same route
                same_route = (
                    abs(fastest["distance_km"] - shortest["distance_km"]) < 0.05
                    and abs(fastest["duration_minutes"] - shortest["duration_minutes"]) < 0.5
                )
                if same_route:
                    msg = (
                        f"Route comparison from {o_label} to {d_label}:\n"
                        f"• The optimal route is simultaneously both the fastest and shortest route available: "
                        f"{fastest['distance_km']} km, ~{int(fastest['duration_minutes'])} mins (ETA {route_res['eta_fastest']}).\n"
                        f"(No faster or shorter detour was found by the road network engine)."
                    )
                else:
                    msg = (
                        f"Route comparison from {o_label} to {d_label}:\n"
                        f"• Fastest route: {fastest['distance_km']} km, ~{int(fastest['duration_minutes'])} mins (ETA {route_res['eta_fastest']}).\n"
                        f"• Shortest route: {shortest['distance_km']} km, ~{int(shortest['duration_minutes'])} mins (ETA {route_res['eta_shortest']}).\n"
                        f"The fastest route saves ~{int(shortest['duration_minutes'] - fastest['duration_minutes'])} minutes."
                    )
                return {
                    "success": True,
                    "action": "compare_routes",
                    "origin": o_label,
                    "destination": d_label,
                    "fastest_route": fastest,
                    "shortest_route": shortest,
                    "message": msg,
                }

        # ── 7. CONTEXTUAL NAVIGATION FOLLOW-UPS ────────────────────────────────
        if self.active_navigation:
            if "shortest" in text_low and any(w in text_low for w in ["route", "path", "instead", "find", "show"]):
                shortest = self.active_navigation.get("shortest_route")
                fastest = self.active_navigation.get("fastest_route")
                if shortest and fastest:
                    msg = (
                        f"Switching to the shortest route: {shortest['distance_km']} km "
                        f"(estimated {int(shortest['duration_minutes'])} mins, ETA {self.active_navigation.get('eta_shortest')}). "
                        f"Note: The fastest route is {fastest['distance_km']} km in {int(fastest['duration_minutes'])} mins."
                    )
                    return {"success": True, "action": "navigation_switch_shortest", "selected_route": shortest, "message": msg}

            if "fastest" in text_low and any(w in text_low for w in ["which", "is", "route", "faster"]):
                fastest = self.active_navigation.get("fastest_route")
                shortest = self.active_navigation.get("shortest_route")
                if fastest and shortest:
                    diff_mins = shortest["duration_minutes"] - fastest["duration_minutes"]
                    diff_str = f"It is {int(diff_mins)} minutes faster than the shortest route." if diff_mins > 0 else "It is the optimal route."
                    msg = (
                        f"The fastest route takes ~{int(fastest['duration_minutes'])} mins ({fastest['distance_km']} km, ETA {self.active_navigation.get('eta_fastest')}). "
                        f"{diff_str}"
                    )
                    return {"success": True, "action": "navigation_fastest_info", "fastest_route": fastest, "message": msg}

            if any(k in text_low for k in ["avoid tolls", "avoid toll roads", "no tolls"]):
                self.active_navigation["avoid_tolls"] = True
                msg = f"Updated route preferences to avoid toll roads for navigation to {self.active_navigation.get('destination_label')}."
                return {"success": True, "action": "avoid_tolls", "message": msg}

            if any(k in text_low for k in ["what is my eta now", "update my eta", "current eta", "eta now", "what's my eta"]):
                cur_loc = self.detector.get_current_location(force_refresh=True, user_id=user_id)
                c_lat, c_lon = cur_loc.get("latitude", 0.0), cur_loc.get("longitude", 0.0)
                d_lat = self.active_navigation.get("dest_lat")
                d_lon = self.active_navigation.get("dest_lon")
                if c_lat and d_lat:
                    up_route = self.get_route(c_lat, c_lon, d_lat, d_lon)
                    if up_route.get("success"):
                        self.active_navigation["fastest_route"] = up_route["fastest_route"]
                        self.active_navigation["eta_fastest"] = up_route["eta_fastest"]
                        dur = up_route["fastest_route"]["duration_minutes"]
                        dist = up_route["fastest_route"]["distance_km"]
                        msg = f"Your updated ETA is {up_route['eta_fastest']} ({dist:.1f} km and ~{int(dur)} minutes remaining)."
                        return {"success": True, "action": "eta_update", "eta": up_route["eta_fastest"], "distance_km": dist, "message": msg}

            if any(k in text_low for k in ["how much farther", "how much further", "distance remaining"]):
                cur_loc = self.detector.get_current_location(force_refresh=True, user_id=user_id)
                c_lat, c_lon = cur_loc.get("latitude", 0.0), cur_loc.get("longitude", 0.0)
                d_lat = self.active_navigation.get("dest_lat")
                d_lon = self.active_navigation.get("dest_lon")
                if c_lat and d_lat:
                    up_route = self.get_route(c_lat, c_lon, d_lat, d_lon)
                    if up_route.get("success"):
                        dist = up_route["fastest_route"]["distance_km"]
                        dur = up_route["fastest_route"]["duration_minutes"]
                        msg = f"You have {dist:.1f} km remaining to your destination (approx. {int(dur)} mins)."
                        return {"success": True, "action": "distance_remaining", "distance_km": dist, "duration_minutes": dur, "message": msg}

            if re.search(r'\b(?:add\s+a\s+(?:fuel\s+|gas\s+)?stop|stop\s+at)\b', text_low):
                m_stop = re.search(r'\b(?:add\s+a\s+(?:fuel\s+|gas\s+)?stop(?:\s+at)?|stop\s+at)\s+(.+)', text_low)
                stop_name = m_stop.group(1).strip() if m_stop else "fuel station"
                stop_candidates = self.geocode(stop_name)
                if stop_candidates:
                    s_lat = stop_candidates[0]["latitude"]
                    s_lon = stop_candidates[0]["longitude"]
                    orig_lat = self.active_navigation.get("origin_lat")
                    orig_lon = self.active_navigation.get("origin_lon")
                    dest_lat = self.active_navigation.get("dest_lat")
                    dest_lon = self.active_navigation.get("dest_lon")
                    multi_route = self.get_route(orig_lat, orig_lon, dest_lat, dest_lon, waypoints=[(s_lat, s_lon)])
                    if multi_route.get("success"):
                        self.active_navigation = multi_route
                        self.active_navigation["origin_lat"] = orig_lat
                        self.active_navigation["origin_lon"] = orig_lon
                        self.active_navigation["dest_lat"] = dest_lat
                        self.active_navigation["dest_lon"] = dest_lon
                        self.active_navigation["destination_label"] = self.active_navigation.get("destination_label", "")
                        dur = multi_route["fastest_route"]["duration_minutes"]
                        dist = multi_route["fastest_route"]["distance_km"]
                        msg = f"Added stop at {stop_candidates[0]['display_name'].split(',')[0]}. Updated route is {dist:.1f} km, estimated {int(dur)} mins (ETA {multi_route['eta_fastest']})."
                        return {"success": True, "action": "multi_stop_route", "route": multi_route, "message": msg}
        else:
            # When no active route is set, inform user rather than falling through to generic location
            if any(k in text_low for k in ["find the shortest route", "shortest route instead", "shortest route"]):
                return {"success": False, "message": "No active navigation route is currently set. Say 'Navigate to [destination]' to plan a route."}
            if any(k in text_low for k in ["which route is fastest", "fastest route"]):
                return {"success": False, "message": "No active navigation route is currently set. Say 'Navigate to [destination]' to compare route speeds."}
            if any(k in text_low for k in ["avoid tolls", "avoid toll roads"]):
                return {"success": False, "message": "No active navigation route is currently set. Say 'Navigate to [destination]' first."}
            if any(k in text_low for k in ["update my eta", "what is my eta now", "current eta"]):
                return {"success": False, "message": "No active navigation route is currently set to calculate an ETA for."}
            if any(k in text_low for k in ["how much farther", "distance remaining"]):
                return {"success": False, "message": "No active navigation route is currently set. Say 'Navigate to [destination]' to begin."}

        # ── 7B. MULTI-STOP ROUTE PLANNING ─────────────────────────────────────
        m_multi = re.search(r'\b(?:plan\s+(?:a\s+)?route|route)\s+(?:through|via|across)\s+(.+)', text_low)
        if m_multi:
            places_str = m_multi.group(1).strip()
            # Clean up introductory words like "these three locations"
            places_str = re.sub(r'^(?:these\s+)?(?:\w+\s+)?(?:locations|places|stops)[:\s]*', '', places_str)
            parts = [p.strip() for p in re.split(r'[,;]|\band\s+then\b|\band\b', places_str) if p.strip()]
            if len(parts) >= 2:
                resolved_pts = []
                for pt in parts:
                    cands = self.geocode(pt)
                    if cands:
                        resolved_pts.append((cands[0]["latitude"], cands[0]["longitude"], cands[0]["display_name"].split(",")[0]))
                if len(resolved_pts) >= 2:
                    origin = resolved_pts[0]
                    dest = resolved_pts[-1]
                    waypoints = [(p[0], p[1]) for p in resolved_pts[1:-1]]
                    route_res = self.get_route(origin[0], origin[1], dest[0], dest[1], waypoints=waypoints)
                    if route_res.get("success"):
                        fastest = route_res["fastest_route"]
                        via_str = " -> ".join([p[2] for p in resolved_pts])
                        msg = (
                            f"Multi-stop route planned ({via_str}):\n"
                            f"• Total distance: {fastest['distance_km']} km\n"
                            f"• Estimated travel time: ~{int(fastest['duration_minutes'])} mins (ETA {route_res['eta_fastest']})\n"
                            f"Navigation link: {route_res['google_maps_url']}"
                        )
                        return {
                            "success": True,
                            "action": "multi_stop_route",
                            "stops": [p[2] for p in resolved_pts],
                            "route": route_res,
                            "message": msg,
                        }

        # ── 8. NAVIGATION & ROUTING COMMANDS ──────────────────────────────────
        m_nav = re.search(r'\b(?:navigate|directions?|route|drive|walk|cycle)(?:\s+(?:from|start\s+from)\s+(.+?))?\s+(?:to|towards)\s+(.+)', text_low)
        if m_nav or any(text_low.startswith(w) for w in ["navigate to", "directions to", "route to", "drive to", "walk to"]):
            orig_str = m_nav.group(1).strip() if (m_nav and m_nav.group(1)) else ""
            dest_str = m_nav.group(2).strip() if (m_nav and m_nav.group(2)) else ""

            if not dest_str:
                dest_str = re.sub(r'^(?:navigate|directions?|route|drive|walk|cycle)\s+(?:to|towards)?\s*', '', text_low).strip()

            # Determine mode
            mode = "driving"
            if "walk" in text_low or "foot" in text_low:
                mode = "walking"
            elif "cycle" in text_low or "bike" in text_low:
                mode = "cycling"

            # Strip travel mode suffixes from destination
            dest_str = re.sub(r'\s+by\s+(?:car|driving|bike|cycle|cycling|walking|foot)\b.*', '', dest_str, flags=re.IGNORECASE).strip()
            dest_str = re.sub(r'\s+on\s+foot\b.*', '', dest_str, flags=re.IGNORECASE).strip()
            dest_str = re.sub(r'[?.!]+$', '', dest_str).strip()

            # Determine origin
            clean_orig = re.sub(r'^(?:my\s+|the\s+)?', '', orig_str).strip().lower()
            if orig_str and clean_orig not in ("current location", "location", "here", "where i am"):
                orig_candidates = self.geocode(orig_str)
                if not orig_candidates:
                    return {"success": False, "message": f"Could not find origin location '{orig_str}'."}
                o_lat, o_lon = orig_candidates[0]["latitude"], orig_candidates[0]["longitude"]
                o_label = orig_candidates[0]["display_name"].split(",")[0]
            else:
                cur_loc = self.detector.get_current_location(user_id=user_id)
                o_lat, o_lon = cur_loc.get("latitude", 0.0), cur_loc.get("longitude", 0.0)
                o_label = "your current location"

            # Determine destination
            clean_dest = re.sub(r'^(?:the\s+|a\s+)?', '', dest_str).strip().lower()
            dest_candidates = []
            if clean_dest in ("airport", "nearest airport", "flight"):
                nearby_airports = self.search_nearby("airport", o_lat, o_lon, radius_km=80.0)
                if nearby_airports:
                    dest_candidates = [{
                        "display_name": nearby_airports[0]["display_name"],
                        "latitude": nearby_airports[0]["latitude"],
                        "longitude": nearby_airports[0]["longitude"],
                    }]
            if not dest_candidates:
                dest_candidates = self.geocode(dest_str)

            if not dest_candidates:
                return {"success": False, "message": f"Could not find destination place '{dest_str}'."}
            d_lat, d_lon = dest_candidates[0]["latitude"], dest_candidates[0]["longitude"]
            d_label = dest_candidates[0]["display_name"].split(",")[0]

            route_res = self.get_route(o_lat, o_lon, d_lat, d_lon, mode=mode)
            if not route_res.get("success"):
                return {"success": False, "message": f"Could not compute route to {d_label}: {route_res.get('error')}"}

            fastest = route_res["fastest_route"]
            shortest = route_res["shortest_route"]

            # Store active navigation context
            self.active_navigation = {
                "origin_lat": o_lat,
                "origin_lon": o_lon,
                "dest_lat": d_lat,
                "dest_lon": d_lon,
                "origin_label": o_label,
                "destination_label": d_label,
                "mode": mode,
                "fastest_route": fastest,
                "shortest_route": shortest,
                "eta_fastest": route_res["eta_fastest"],
                "eta_shortest": route_res["eta_shortest"],
                "google_maps_url": route_res["google_maps_url"],
                "routes": route_res["routes"],
            }

            diff_str = ""
            if shortest["distance_km"] < fastest["distance_km"] and shortest["duration_minutes"] > fastest["duration_minutes"]:
                diff_str = f" (Shortest route is {shortest['distance_km']} km, but takes ~{int(shortest['duration_minutes'])} mins)."

            first_maneuvers = ""
            if fastest.get("steps"):
                first_maneuvers = f" Start by heading {fastest['steps'][0]}."

            mode_label = "by car (driving)"
            if mode == "walking":
                mode_label = "on foot (walking)"
            elif mode == "cycling":
                mode_label = "by bicycle (cycling)"

            disclaimer_txt = f"\nNote: {route_res['mode_disclaimer']}" if route_res.get("mode_disclaimer") else ""
            msg = (
                f"Routing from {o_label} to {d_label} {mode_label}:\n"
                f"• Fastest route: {fastest['distance_km']} km, ~{int(fastest['duration_minutes'])} mins (ETA {route_res['eta_fastest']}){diff_str}.\n"
                f"{first_maneuvers}\n"
                f"Navigation link: {route_res['google_maps_url']}{disclaimer_txt}"
            )

            return {
                "success": True,
                "action": "navigation",
                "mode": mode,
                "origin": o_label,
                "destination": d_label,
                "fastest_route": fastest,
                "shortest_route": shortest,
                "eta": route_res["eta_fastest"],
                "maps_url": route_res["google_maps_url"],
                "route_data": route_res,
                "message": msg,
            }

        # ── 9. SAVED PLACES COMMANDS ("Save this place as Home") ────────────
        m_save = re.search(r'\bsave\s+(?:this\s+place|this\s+location|current\s+location|here)\s+as\s+([a-zA-Z0-9_\-\s]+)', text_low)
        if m_save:
            name = m_save.group(1).strip().rstrip('.!?')
            loc = self.detector.get_current_location(user_id=user_id)
            lat, lon = loc.get("latitude", 0.0), loc.get("longitude", 0.0)
            addr = loc.get("display_name", "")
            if abs(lat) > 0.0001:
                res = self.save_place(name, lat, lon, address=addr, user_id=user_id)
                msg = f"Saved your current location ({loc.get('city')}) as '{name}'."
                return {"success": True, "action": "save_place", "place": res["place"], "message": msg}

        # ── 9B. WHERE IS MY SAVED PLACE ───────────────────────────────────────
        m_where_saved = re.search(r'\bwhere\s+is\s+(?:my\s+)?saved\s+([a-zA-Z0-9_\-\s]+)', text_low)
        if m_where_saved:
            name = m_where_saved.group(1).strip().rstrip('?.!')
            places = self.get_saved_places(user_id=user_id)
            matched = places.get(name) or places.get(name.lower()) or places.get(name.capitalize())
            if matched:
                msg = f"Your saved place '{name}' is at coordinates {matched.get('latitude'):.4f}, {matched.get('longitude'):.4f} ({matched.get('address', 'Saved location')})."
                return {"success": True, "action": "get_saved_place", "place": matched, "message": msg}
            else:
                msg = f"You do not have a saved place named '{name}'. Saved places: {', '.join(places.keys()) if places else 'None'}."
                return {"success": False, "action": "get_saved_place", "message": msg}

        # ── 9C. LIST SAVED PLACES ─────────────────────────────────────────────
        if any(k in text_low for k in ["saved places", "list saved places", "show saved places"]):
            places = self.get_saved_places(user_id=user_id)
            if not places:
                return {"success": True, "action": "list_saved_places", "places": {}, "message": "You have no saved places yet. Say 'Save this location as [name]' to save one."}
            lines = [f"• {name.title()}: {p.get('address', 'Coordinates')} ({p.get('latitude'):.4f}, {p.get('longitude'):.4f})" for name, p in places.items()]
            msg = "Here are your saved places:\n" + "\n".join(lines)
            return {"success": True, "action": "list_saved_places", "places": places, "message": msg}

        # ── 10. DEFAULT: CURRENT LOCATION QUERY ───────────────────────────────
        loc = self.detector.get_current_location(force_refresh=force_refresh, user_id=user_id)
        city = loc.get("city", "Unknown Location")
        state = loc.get("state") or loc.get("region") or ""
        country = loc.get("country", "")
        src = loc.get("source", "detected")
        is_device = loc.get("is_device_location", False)
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        acc = loc.get("accuracy_m")
        freshness_label = loc.get("freshness_label", "")
        dev_name = loc.get("device_name", "")

        locality = loc.get("locality") or ""
        district = loc.get("district") or ""
        parts = [p for p in [locality, city, district, state, country] if p and p != "Unknown Location"]
        place_str = ", ".join(parts) if parts else city
        prefix = "Location refreshed. " if force_refresh else ""

        if src == "phone_gps":
            acc_str = f" (accuracy ±{int(acc)}m)" if acc else ""
            msg = f"{prefix}Your current location is {place_str}{acc_str} ({freshness_label}, via {dev_name} GPS)."
        elif src == "windows_hardware_location":
            acc_str = f" (accuracy ±{int(acc)}m)" if acc else ""
            msg = f"{prefix}Your current location is {place_str}{acc_str} (via Windows Location Services)."
        elif src == "ip_geolocation":
            msg = f"{prefix}Your approximate location is {place_str}, based on IP network geolocation (note: IP geolocation is approximate and may not reflect your exact street address)."
        else:
            msg = "Could not determine your physical location. Device location services and network geolocation are unavailable."

        return {
            "success": loc.get("status") == "success",
            "action": "user_current_location",
            "alias_action": "current_location",
            "city": city,
            "state": state,
            "country": country,
            "display_name": loc.get("display_name", ""),
            "latitude": lat,
            "longitude": lon,
            "accuracy": acc,
            "source": src,
            "device_name": dev_name,
            "is_device_location": is_device,
            "freshness": loc.get("freshness"),
            "freshness_label": freshness_label,
            "location": loc,
            "message": msg,
        }


_controller_instance: Optional[LocationController] = None
_controller_lock = threading.Lock()


def get_location_controller() -> LocationController:
    global _controller_instance
    with _controller_lock:
        if _controller_instance is None:
            _controller_instance = LocationController()
        return _controller_instance
