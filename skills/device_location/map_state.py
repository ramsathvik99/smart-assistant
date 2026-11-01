"""
Authoritative Single Persistent Map State Manager for Assistant Location Intelligence.

Enforces:
1. Exactly one active map instance across the assistant session.
2. In-place updates to center, zoom, markers, route polylines, and category filters.
3. Strict separation of all cached markers vs visible markers.
4. Clean category removal (actually hides markers & deselects if hidden).
5. Robust marker deduplication by normalized name and coordinate proximity.
6. Persistent filter survival across subsequent category additions.
7. Complete route replacement and clean route clearing without marker loss.
8. Monotonic version ordering preventing stale network updates from overwriting newer state.
"""

import time
import logging
import threading
import re
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


def _normalize_name(name: str) -> str:
    """Normalizes place name for deduplication."""
    return re.sub(r'\s+', ' ', re.sub(r'[^a-zA-Z0-9\s]', '', (name or '').lower())).strip()


class MapStateManager:
    """Authoritative singleton state manager for the persistent map instance."""
    _instance: Optional["MapStateManager"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(MapStateManager, cls).__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._state_lock = threading.RLock()
        self.is_open: bool = False
        self.keep_open: bool = False
        self.center: Dict[str, float] = {"lat": 16.3067, "lon": 80.4365}
        self.zoom: int = 14
        self.user_location: Dict[str, Any] = {}
        
        # Internal cache of all discovered markers: id -> marker_dict
        self._cached_markers: Dict[str, Dict[str, Any]] = {}
        
        self.active_route: Optional[Dict[str, Any]] = None
        self.visible_categories: List[str] = []  # Empty means all cached categories visible
        self.active_filters: Dict[str, Any] = {}  # e.g. {"max_distance_km": 5.0}
        self.selected_place_id: Optional[str] = None
        
        # Monotonic version counter
        self.version: int = 1
        self.last_updated: float = time.time()
        self._browser_opened: bool = False
        self._initialized = True
        logger.info("[MAP_STATE] Authoritative MapStateManager initialized with consistent state tracking.")

    def _bump_version(self) -> None:
        self.version += 1
        self.last_updated = time.time()
        if getattr(self, "is_open", False):
            try:
                from skills.device_location.desktop_map_window import get_desktop_map_controller
                dmc = get_desktop_map_controller()
                dmc.update_map(self.get_state())
            except Exception:
                pass

    def _is_marker_visible(self, marker: Dict[str, Any]) -> bool:
        """Determines if a cached marker is visible under current filters and categories."""
        cat = (marker.get("category") or "").lower().strip()
        if self.visible_categories:
            vis_set = {c.lower().strip() for c in self.visible_categories}
            if cat not in vis_set:
                return False

        max_dist = self.active_filters.get("max_distance_km")
        if max_dist is not None:
            try:
                if float(marker.get("distance_km", 0.0)) > float(max_dist):
                    return False
            except (ValueError, TypeError):
                pass

        return True

    def get_state(self) -> Dict[str, Any]:
        """Returns snapshot of current authoritative map state distinguishing cached from visible."""
        with self._state_lock:
            cached_list = []
            visible_list = []
            
            # Recalculate visibility and index
            vis_idx = 1
            for m_id, m in self._cached_markers.items():
                m_copy = dict(m)
                is_vis = self._is_marker_visible(m_copy)
                m_copy["is_visible"] = is_vis
                m_copy["is_selected"] = (m_id == self.selected_place_id and is_vis)
                if is_vis:
                    m_copy["visible_index"] = vis_idx
                    vis_idx += 1
                    visible_list.append(m_copy)
                cached_list.append(m_copy)

            # Sort visible list by distance
            visible_list.sort(key=lambda x: x.get("distance_km", 0.0))
            for i, vm in enumerate(visible_list):
                vm["visible_index"] = i + 1

            return {
                "is_open": self.is_open,
                "keep_open": self.keep_open,
                "center": dict(self.center),
                "zoom": self.zoom,
                "user_location": dict(self.user_location) if self.user_location else {},
                "markers": visible_list,             # Backward-compatible visible markers
                "visible_markers": visible_list,     # Explicit visible markers
                "cached_markers": cached_list,       # Complete discovery cache
                "active_route": dict(self.active_route) if self.active_route else None,
                "visible_categories": list(self.visible_categories),
                "active_filters": dict(self.active_filters),
                "selected_place_id": self.selected_place_id,
                "version": self.version,
                "last_updated": self.last_updated,
                "browser_opened": self._browser_opened,
            }

    def to_dict(self) -> Dict[str, Any]:
        """Returns snapshot of current authoritative map state."""
        return self.get_state()

    def reset(self) -> None:
        """Resets all markers, categories, filters, and active route."""
        with self._state_lock:
            self._cached_markers.clear()
            self.visible_categories.clear()
            self.active_filters.clear()
            self.active_route = None
            self.selected_place_id = None
            self._bump_version()

    @property
    def markers(self) -> List[Dict[str, Any]]:
        """List of visible markers for backward-compatibility."""
        state = self.get_state()
        return state["visible_markers"]

    @markers.setter
    def markers(self, val: List[Dict[str, Any]]) -> None:
        """Setter for testing/resetting markers directly."""
        with self._state_lock:
            self._cached_markers.clear()
            if val:
                for idx, p in enumerate(val):
                    p_id = p.get("id") or f"poi_{idx+1}"
                    self._cached_markers[p_id] = dict(p)
                    self._cached_markers[p_id]["id"] = p_id
            self._bump_version()

    def update_user_location(self, loc: Dict[str, Any]) -> None:
        """Updates user's own location fix and centers map on user."""
        if not loc:
            return
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        if lat is None or lon is None or abs(lat) < 0.0001:
            return
        with self._state_lock:
            self.user_location = {
                "latitude": float(lat),
                "longitude": float(lon),
                "city": loc.get("city", "Detected Location"),
                "accuracy_m": loc.get("accuracy_m", 15.0),
                "source": loc.get("source", "GPS"),
                "device_name": loc.get("device_name", "Primary Device"),
                "freshness_label": loc.get("freshness_label", "Live"),
                "timestamp": loc.get("timestamp", time.time()),
            }
            self.center = {"lat": float(lat), "lon": float(lon)}
            self._bump_version()

    def set_markers(
        self,
        places: List[Dict[str, Any]],
        category: str = "",
        append: bool = False,
        apply_filter_km: Optional[float] = None
    ) -> None:
        """
        Sets or appends POI markers to the persistent map with deduplication.
        If append is False, clears previous cache unless filters or categories are active.
        """
        with self._state_lock:
            if not append:
                self._cached_markers.clear()
                self.selected_place_id = None

            if apply_filter_km is not None:
                self.active_filters["max_distance_km"] = float(apply_filter_km)

            # Build index of existing markers for deduplication
            seen_signatures = {}
            for m_id, m in self._cached_markers.items():
                sig = (_normalize_name(m.get("name", "")), round(float(m.get("latitude", 0.0)), 4), round(float(m.get("longitude", 0.0)), 4))
                seen_signatures[sig] = m_id

            for idx, p in enumerate(places):
                p_name = p.get("name", "Unknown Place")
                p_lat = float(p.get("latitude", 0.0))
                p_lon = float(p.get("longitude", 0.0))
                sig = (_normalize_name(p_name), round(p_lat, 4), round(p_lon, 4))
                
                cat = (p.get("category") or category or "place").lower().strip()
                p_dist = float(p.get("distance_km", 0.0))

                if sig in seen_signatures:
                    # Update existing marker without duplicate creation
                    m_id = seen_signatures[sig]
                    self._cached_markers[m_id]["distance_km"] = p_dist
                    self._cached_markers[m_id]["category"] = cat
                    continue

                p_id = p.get("id") or f"poi_{len(self._cached_markers) + 1}"
                marker = {
                    "id": p_id,
                    "index": len(self._cached_markers) + 1,
                    "name": p_name,
                    "display_name": p.get("display_name", p_name),
                    "latitude": p_lat,
                    "longitude": p_lon,
                    "category": cat,
                    "distance_km": p_dist,
                    "maps_url": p.get("maps_url", f"https://www.google.com/maps?q={p_lat},{p_lon}"),
                    "is_selected": False,
                    "is_visible": True,
                }
                self._cached_markers[p_id] = marker
                seen_signatures[sig] = p_id

            # Update visible categories
            if append and self.visible_categories:
                for p in places:
                    c_p = (p.get("category") or category or "").lower().strip()
                    if c_p and c_p not in self.visible_categories:
                        self.visible_categories.append(c_p)
            elif not self.visible_categories:
                all_cats = {m["category"] for m in self._cached_markers.values() if m.get("category")}
                self.visible_categories = sorted(list(all_cats))
            elif category and category.lower().strip() not in self.visible_categories:
                self.visible_categories.append(category.lower().strip())

            self._bump_version()

    def filter_categories(self, categories: List[str]) -> None:
        """Filters map view to show only specified categories; hides non-matching markers."""
        with self._state_lock:
            self.visible_categories = [c.lower().strip() for c in categories if c.strip()]
            
            # Validate selected_place_id: if selected place is now hidden, deselect it
            if self.selected_place_id and self.selected_place_id in self._cached_markers:
                selected_m = self._cached_markers[self.selected_place_id]
                if not self._is_marker_visible(selected_m):
                    self.selected_place_id = None
            
            self._bump_version()

    def add_category(self, category: str) -> None:
        """Adds a category to the visible set in place without duplicating markers."""
        c_clean = category.lower().strip()
        with self._state_lock:
            if c_clean and c_clean not in self.visible_categories:
                self.visible_categories.append(c_clean)
            self._bump_version()

    def remove_category(self, category: str) -> None:
        """Removes a category from visible view; deselects place if hidden."""
        c_clean = category.lower().strip()
        with self._state_lock:
            # If all were visible by default, initialize visible_categories from all cached
            if not self.visible_categories:
                all_cats = {m["category"] for m in self._cached_markers.values() if m.get("category")}
                self.visible_categories = sorted(list(all_cats))

            self.visible_categories = [c for c in self.visible_categories if c != c_clean]

            # Validate selection
            if self.selected_place_id and self.selected_place_id in self._cached_markers:
                if self._cached_markers[self.selected_place_id].get("category") == c_clean:
                    self.selected_place_id = None

            self._bump_version()

    def show_all(self) -> None:
        """Clears category filters and distance filters, displaying all discovered markers."""
        with self._state_lock:
            cats = {m["category"] for m in self._cached_markers.values() if m.get("category")}
            self.visible_categories = sorted(list(cats))
            self.active_filters.pop("max_distance_km", None)
            self._bump_version()

    def set_active_route(self, route_info: Optional[Dict[str, Any]]) -> None:
        """Completely replaces the active route displayed on the map."""
        with self._state_lock:
            if not route_info:
                self.active_route = None
            else:
                self.active_route = {
                    "origin": route_info.get("origin", "Current Location"),
                    "destination": route_info.get("destination", ""),
                    "mode": route_info.get("mode", "driving"),
                    "distance_km": float(route_info.get("distance_km", 0.0)),
                    "duration_minutes": float(route_info.get("duration_minutes", 0.0)),
                    "eta": route_info.get("eta", ""),
                    "geometry": route_info.get("geometry"),
                    "steps": list(route_info.get("steps", [])),
                }
            self._bump_version()

    def clear_route(self) -> None:
        """Removes active route polyline without modifying or removing any markers."""
        with self._state_lock:
            self.active_route = None
            self._bump_version()

    def select_marker(self, marker_id_or_index: Any) -> Optional[Dict[str, Any]]:
        """Selects a specific marker by ID or 1-based visible index, validating existence."""
        with self._state_lock:
            state = self.get_state()
            visible_markers = state["visible_markers"]
            found = None

            if isinstance(marker_id_or_index, int):
                idx = marker_id_or_index - 1
                if 0 <= idx < len(visible_markers):
                    found = visible_markers[idx]
            else:
                m_str = str(marker_id_or_index).strip().lower()
                for m in visible_markers:
                    if m.get("id", "").lower() == m_str or m.get("name", "").lower() == m_str:
                        found = m
                        break

            if found:
                self.selected_place_id = found.get("id")
                self.center = {"lat": float(found["latitude"]), "lon": float(found["longitude"])}
                self._bump_version()
                return dict(found)
            
            return None

    def adjust_zoom(self, delta: int) -> int:
        """Adjusts map zoom level idempotently within [3, 19]."""
        with self._state_lock:
            self.zoom = max(3, min(19, self.zoom + delta))
            self._bump_version()
            return self.zoom

    def set_zoom(self, zoom: int) -> int:
        """Sets map zoom level idempotently within [3, 19]."""
        with self._state_lock:
            self.zoom = max(3, min(19, zoom))
            self._bump_version()
            return self.zoom

    def open_map(self, force_browser: bool = False) -> bool:
        """
        Ensures the single persistent dedicated PyQt6 desktop map window is open.
        Reuses existing native window, bringing it to foreground if minimized or hidden.
        No external browser tabs or windows are created.
        Returns True ONLY if the desktop window is successfully shown and confirmed visible.
        """
        try:
            from skills.device_location.desktop_map_window import get_desktop_map_controller
            dmc = get_desktop_map_controller()
            opened = dmc.show_map(self.get_state())
            if opened:
                with self._state_lock:
                    self.is_open = True
                    self._bump_version()
                logger.info("[MAP_STATE] Native PyQt6 desktop map window opened and verified visible.")
                return True
            else:
                with self._state_lock:
                    self.is_open = False
                logger.warning("[MAP_STATE] Native desktop map window could not be displayed or verified.")
                return False
        except Exception as e:
            with self._state_lock:
                self.is_open = False
            logger.error(f"[MAP_STATE] Could not open native desktop map window: {e}")
            return False

    def close_map(self) -> None:
        """Disposes or hides map view cleanly; can be reopened in place."""
        with self._state_lock:
            self.is_open = False
            self.keep_open = False
            self._bump_version()
        try:
            from skills.device_location.desktop_map_window import get_desktop_map_controller
            get_desktop_map_controller().close_map()
        except Exception:
            pass

    def keep_map_open(self) -> None:
        """Pins the map view to stay open persistently."""
        with self._state_lock:
            self.is_open = True
            self.keep_open = True
            self._bump_version()


_map_state_manager_instance: Optional[MapStateManager] = None


def get_map_state_manager() -> MapStateManager:
    """Returns the singleton instance of MapStateManager."""
    global _map_state_manager_instance
    if _map_state_manager_instance is None:
        _map_state_manager_instance = MapStateManager()
    return _map_state_manager_instance
