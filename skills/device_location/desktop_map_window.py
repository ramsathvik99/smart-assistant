"""
Native PyQt6 Desktop Map Window for Smart Assistant (Friday / Trevon).

Provides a dedicated, interactive desktop application window:
- Embedded Leaflet/CartoDB interactive map via PyQt6.QtWebEngineWidgets.QWebEngineView.
- No external browser windows, no tabs, no manual URLs.
- Single persistent window instance: reuses, updates in place, and brings to foreground.
- Modern dark-themed native Qt controls: Category filters, Zoom, Route clearing, Center.
- Live synchronization of markers, selected destination, and active route polyline.
- Operates independently of external servers.
"""

from __future__ import annotations

import os
# Prevent Chromium WebEngine from binding to Windows audio hardware (avoids WASAPI/DirectSound conflict with TTS)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-audio-output --mute-audio --no-sandbox --disable-features=AudioServiceOutOfProcess")
import sys
import json
import logging
import threading
from typing import Dict, Any, List, Optional

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QSizePolicy, QStatusBar
)
from PyQt6.QtCore import Qt, QUrl, pyqtSignal, pyqtSlot, QObject
from PyQt6.QtWebEngineWidgets import QWebEngineView

logger = logging.getLogger(__name__)

MAP_HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Assistant Native Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  html, body, #map { height: 100%; width: 100%; margin: 0; padding: 0; background: #0f141c; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; overflow: hidden; }
  .leaflet-popup-content-wrapper {
    background: #17202e !important;
    color: #e2e8f0 !important;
    border: 1px solid #2d3748 !important;
    border-radius: 8px !important;
    box-shadow: 0 10px 25px rgba(0,0,0,0.6) !important;
  }
  .leaflet-popup-tip { background: #17202e !important; }
  .leaflet-container { background: #0f141c !important; }
  
  .poi-marker {
    display: flex;
    align-items: center;
    justify-content: center;
    border-radius: 50%;
    font-weight: 700;
    font-size: 11px;
    color: #ffffff;
    box-shadow: 0 3px 10px rgba(0,0,0,0.5);
    border: 2px solid #ffffff;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }
  .poi-hospital { background: #ef4444; }
  .poi-pharmacy { background: #10b981; }
  .poi-restaurant { background: #f59e0b; }
  .poi-other { background: #3b82f6; }
  
  .poi-selected {
    border-color: #00e5ff !important;
    box-shadow: 0 0 16px #00e5ff, 0 0 24px rgba(0,229,255,0.6) !important;
    transform: scale(1.3) !important;
    z-index: 1000 !important;
  }
  
  .user-pulse-container {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 24px;
    height: 24px;
  }
  .user-pulse {
    width: 14px;
    height: 14px;
    background: #00e5ff;
    border: 2.5px solid #ffffff;
    border-radius: 50%;
    box-shadow: 0 0 10px #00e5ff;
    animation: pulse-ring 2s infinite;
  }
  @keyframes pulse-ring {
    0% { box-shadow: 0 0 0 0 rgba(0, 229, 255, 0.7); }
    70% { box-shadow: 0 0 0 14px rgba(0, 229, 255, 0); }
    100% { box-shadow: 0 0 0 0 rgba(0, 229, 255, 0); }
  }
</style>
</head>
<body>
<div id="map"></div>
<script>
  let map = null;
  let userMarker = null;
  let routeLayer = null;
  let markersById = {};

  function initMap(lat, lon, zoom) {
    if (map) return;
    map = L.map('map', { zoomControl: false }).setView([lat, lon], zoom);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap &copy; CARTO',
      subdomains: 'abcd',
      maxZoom: 19
    }).addTo(map);
    L.control.zoom({ position: 'bottomright' }).addTo(map);
  }

  function applyState(state) {
    if (!state) return;
    const center = state.center || { lat: 16.310978, lon: 80.420879 };
    const zoom = state.zoom || 14;

    if (!map) {
      initMap(center.lat, center.lon, zoom);
    } else {
      map.setView([center.lat, center.lon], zoom);
    }

    // User location
    if (state.user_location && state.user_location.latitude) {
      const ulat = state.user_location.latitude;
      const ulon = state.user_location.longitude;
      if (userMarker) map.removeLayer(userMarker);
      const uIcon = L.divIcon({
        className: '',
        html: '<div class="user-pulse-container"><div class="user-pulse"></div></div>',
        iconSize: [24, 24],
        iconAnchor: [12, 12]
      });
      const uLabel = state.user_location.city || state.user_location.address || "Your Current Location";
      userMarker = L.marker([ulat, ulon], { icon: uIcon }).addTo(map)
        .bindPopup(`<b>Current Location</b><br>${uLabel}`);
    }

    // Markers
    for (let id in markersById) {
      map.removeLayer(markersById[id]);
    }
    markersById = {};

    const visibleMarkers = state.visible_markers || [];
    visibleMarkers.forEach(m => {
      let catClass = 'poi-other';
      const cat = (m.category || '').toLowerCase();
      if (cat.includes('hospital')) catClass = 'poi-hospital';
      else if (cat.includes('pharmacy')) catClass = 'poi-pharmacy';
      else if (cat.includes('restaurant')) catClass = 'poi-restaurant';

      const isSel = (m.id === state.selected_place_id) ? ' poi-selected' : '';
      const html = `<div class="poi-marker ${catClass}${isSel}">${m.index || ''}</div>`;
      const icon = L.divIcon({ className: '', html: html, iconSize: [26, 26], iconAnchor: [13, 13] });
      const marker = L.marker([m.latitude, m.longitude], { icon: icon }).addTo(map);

      let popup = `<b>#${m.index || ''} ${m.name}</b><br><span style="color:#94a3b8;font-size:12px">${m.category || 'Place'} &bull; ${m.distance_km} km away</span>`;
      if (m.address) popup += `<br><span style="font-size:11px;color:#cbd5e1">${m.address}</span>`;
      marker.bindPopup(popup);

      if (m.id === state.selected_place_id) {
        marker.openPopup();
      }
      markersById[m.id] = marker;
    });

    // Active Route
    if (routeLayer) {
      map.removeLayer(routeLayer);
      routeLayer = null;
    }

    if (state.active_route && state.active_route.geometry) {
      let coords = [];
      const geom = state.active_route.geometry;
      if (geom.coordinates) {
        coords = geom.coordinates.map(c => [c[1], c[0]]);
      }
      if (coords.length > 0) {
        routeLayer = L.polyline(coords, {
          color: '#00e5ff',
          weight: 5,
          opacity: 0.85,
          lineJoin: 'round'
        }).addTo(map);
        map.fitBounds(routeLayer.getBounds(), { padding: [50, 50] });
      }
    }
  }

  function clearRoute() {
    if (routeLayer) {
      map.removeLayer(routeLayer);
      routeLayer = null;
    }
  }

  function zoomIn() { if (map) map.zoomIn(); }
  function zoomOut() { if (map) map.zoomOut(); }
  function centerUser() {
    if (map && userMarker) {
      map.setView(userMarker.getLatLng(), 15);
      userMarker.openPopup();
    }
  }
</script>
</body>
</html>
"""


class DesktopMapWindow(QMainWindow):
    """Dedicated PyQt6 native desktop window embedding the interactive Leaflet map."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowTitle("Friday — Interactive Desktop Map & Navigation")
        self.resize(1024, 720)
        self.setMinimumSize(720, 500)

        # Main widget & layout
        main_widget = QWidget(self)
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Modern dark top toolbar
        self.top_toolbar = QFrame(self)
        self.top_toolbar.setStyleSheet(
            "background-color: #111827; border-bottom: 1px solid #1f2937; padding: 6px 12px;"
        )
        top_layout = QHBoxLayout(self.top_toolbar)
        top_layout.setContentsMargins(8, 6, 8, 6)
        top_layout.setSpacing(10)

        # Location header label
        self.loc_label = QLabel("Locating position...", self.top_toolbar)
        self.loc_label.setStyleSheet("color: #e2e8f0; font-weight: bold; font-size: 13px;")
        top_layout.addWidget(self.loc_label)

        top_layout.addStretch()

        # Route info badge
        self.route_badge = QLabel("", self.top_toolbar)
        self.route_badge.setStyleSheet(
            "background-color: #0c4a6e; color: #38bdf8; font-weight: 600; font-size: 12px; "
            "padding: 4px 10px; border-radius: 6px; border: 1px solid #0284c7;"
        )
        self.route_badge.setVisible(False)
        top_layout.addWidget(self.route_badge)

        # Action Buttons
        btn_style = (
            "QPushButton { background-color: #1f2937; color: #f3f4f6; border: 1px solid #374151; "
            "border-radius: 6px; padding: 5px 12px; font-size: 12px; font-weight: 500; } "
            "QPushButton:hover { background-color: #374151; border-color: #4b5563; } "
            "QPushButton:pressed { background-color: #111827; }"
        )

        self.btn_center = QPushButton("🎯 My Location", self.top_toolbar)
        self.btn_center.setStyleSheet(btn_style)
        self.btn_center.clicked.connect(self._on_center_clicked)
        top_layout.addWidget(self.btn_center)

        self.btn_clear_route = QPushButton("✕ Clear Route", self.top_toolbar)
        self.btn_clear_route.setStyleSheet(btn_style)
        self.btn_clear_route.clicked.connect(self._on_clear_route_clicked)
        top_layout.addWidget(self.btn_clear_route)

        self.btn_zoom_in = QPushButton("+", self.top_toolbar)
        self.btn_zoom_in.setFixedWidth(32)
        self.btn_zoom_in.setStyleSheet(btn_style)
        self.btn_zoom_in.clicked.connect(self._on_zoom_in_clicked)
        top_layout.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("-", self.top_toolbar)
        self.btn_zoom_out.setFixedWidth(32)
        self.btn_zoom_out.setStyleSheet(btn_style)
        self.btn_zoom_out.clicked.connect(self._on_zoom_out_clicked)
        top_layout.addWidget(self.btn_zoom_out)

        main_layout.addWidget(self.top_toolbar)

        # Embedded WebEngine View for Leaflet
        self._page_loaded = False
        self.web_view = QWebEngineView(self)
        self.web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.web_view.loadFinished.connect(self._on_load_finished)
        self.web_view.setHtml(MAP_HTML_TEMPLATE)
        main_layout.addWidget(self.web_view)

        # Status Bar
        self.status_bar = QStatusBar(self)
        self.status_bar.setStyleSheet("background-color: #0b0f17; color: #94a3b8; font-size: 11px;")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Leaflet embedded desktop engine initialized.")

        self._last_state: Optional[Dict[str, Any]] = None

    def _on_load_finished(self, ok: bool):
        self._page_loaded = bool(ok)
        if self._page_loaded and self._last_state:
            self._run_apply_state(self._last_state)

    def _run_apply_state(self, state: Dict[str, Any]):
        try:
            from PyQt6 import sip
            if sip.isdeleted(self) or not hasattr(self, "web_view") or sip.isdeleted(self.web_view):
                return
            page = self.web_view.page()
            if not page or sip.isdeleted(page):
                return
            json_str = json.dumps(state)
            page.runJavaScript(f"applyState({json_str});")
        except Exception as e:
            logger.warning(f"[DESKTOP_MAP] Error in _run_apply_state: {e}")

    def update_map_state(self, state: Dict[str, Any]) -> None:
        """Pushes state updates into the embedded Leaflet map in place."""
        from PyQt6 import sip
        if sip.isdeleted(self):
            return
        self._last_state = state
        try:
            # Update toolbar labels
            u_loc = state.get("user_location", {})
            locality = u_loc.get("locality") or u_loc.get("city") or "Current Location"
            src = u_loc.get("source", "detected")
            src_str = "Phone GPS" if src == "phone_gps" else ("Windows Location" if "windows" in src else "Network IP")
            acc = u_loc.get("accuracy_m")
            acc_str = f" ±{int(acc)}m" if acc else ""
            self.loc_label.setText(f"📍 {locality} ({src_str}{acc_str})")

            # Route badge
            active_route = state.get("active_route")
            if active_route:
                dest = active_route.get("destination", "Destination")
                dist = active_route.get("distance_km", 0.0)
                dur = active_route.get("duration_minutes", 0.0)
                eta = active_route.get("eta", "")
                self.route_badge.setText(f"Route: {dest} • {dist:.2f} km ({int(dur)} mins, ETA {eta})")
                self.route_badge.setVisible(True)
                self.btn_clear_route.setVisible(True)
            else:
                self.route_badge.setVisible(False)
                self.btn_clear_route.setVisible(False)

            # Status bar
            total_m = len(state.get("visible_markers", []))
            self.status_bar.showMessage(f"Displaying {total_m} markers | Zoom: {state.get('zoom', 14)} | Authoritative Map Instance active")

            # Execute JS in WebEngineView if page loaded
            if self._page_loaded:
                self._run_apply_state(state)
        except Exception as e:
            logger.warning(f"[DESKTOP_MAP] Error updating map state in view: {e}")

    def _on_center_clicked(self):
        if self._page_loaded and hasattr(self, "web_view"):
            page = self.web_view.page()
            if page:
                page.runJavaScript("centerUser();")

    def _on_clear_route_clicked(self):
        try:
            from .map_state import get_map_state_manager
            msm = get_map_state_manager()
            msm.clear_route()
            if self._page_loaded and hasattr(self, "web_view"):
                page = self.web_view.page()
                if page:
                    page.runJavaScript("clearRoute();")
            self.route_badge.setVisible(False)
            self.btn_clear_route.setVisible(False)
        except Exception:
            pass

    def _on_zoom_in_clicked(self):
        if self._page_loaded and hasattr(self, "web_view"):
            page = self.web_view.page()
            if page:
                page.runJavaScript("zoomIn();")

    def _on_zoom_out_clicked(self):
        if self._page_loaded and hasattr(self, "web_view"):
            page = self.web_view.page()
            if page:
                page.runJavaScript("zoomOut();")

    def closeEvent(self, event):
        """Hides rather than destroys the window so it can be brought back instantly."""
        event.ignore()
        self.hide()


# ─────────────────────────────────────────────────────────────────────────────
# THREAD-SAFE SINGLETON DESKTOP MAP CONTROLLER
# ─────────────────────────────────────────────────────────────────────────────

from PyQt6.QtCore import QThread


class _MapSignalBridge(QObject):
    show_sig = pyqtSignal(object)
    update_sig = pyqtSignal(object)
    close_sig = pyqtSignal()

    def __init__(self, controller: "DesktopMapController"):
        super().__init__()
        self.controller = controller
        self.show_sig.connect(self._on_show)
        self.update_sig.connect(self._on_update)
        self.close_sig.connect(self._on_close)

    @pyqtSlot(object)
    def _on_show(self, state):
        self.controller._gui_show(state)

    @pyqtSlot(object)
    def _on_update(self, state):
        self.controller._gui_update(state)

    @pyqtSlot()
    def _on_close(self):
        self.controller._gui_close()


class DesktopMapController:
    """Manages the single authoritative desktop PyQt6 map window."""
    _instance: Optional["DesktopMapController"] = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._window: Optional[DesktopMapWindow] = None
        self._bridge: Optional[_MapSignalBridge] = None
        self._app: Optional[QApplication] = None
        self._initialized = True

    def _ensure_bridge(self):
        """Ensures the Qt Application and bridge are ready."""
        app = QApplication.instance()
        if app is None:
            if threading.current_thread() is threading.main_thread():
                self._app = QApplication(sys.argv)
                app = self._app
            else:
                logger.debug("[DESKTOP_MAP] QApplication not yet initialized on main thread.")
                return

        if app is not None:
            app.setQuitOnLastWindowClosed(False)

        if self._bridge is None and app is not None:
            self._bridge = _MapSignalBridge(self)
            try:
                self._bridge.moveToThread(app.thread())
            except Exception:
                pass

    def _gui_show(self, state: Optional[Dict[str, Any]] = None):
        """Must run on the Qt GUI thread."""
        from PyQt6 import sip
        if self._window is None or sip.isdeleted(self._window):
            self._window = DesktopMapWindow()
        try:
            if not self._window.isVisible():
                self._window.show()
            elif self._window.isMinimized():
                self._window.showNormal()
        except Exception as e:
            logger.warning(f"[DESKTOP_MAP] Exception displaying window: {e}")
        if state:
            try:
                self._window.update_map_state(state)
            except Exception as e:
                logger.warning(f"[DESKTOP_MAP] Exception updating map state: {e}")

    def _gui_update(self, state: Dict[str, Any]):
        """Must run on the Qt GUI thread."""
        from PyQt6 import sip
        if self._window is None or sip.isdeleted(self._window):
            self._window = DesktopMapWindow()
        self._window.update_map_state(state)

    def _gui_close(self):
        """Must run on the Qt GUI thread."""
        if self._window:
            self._window.hide()

    def show_map(self, state: Optional[Dict[str, Any]] = None, timeout_s: float = 2.0) -> bool:
        """Opens or brings the persistent desktop map window to the foreground."""
        try:
            self._ensure_bridge()
            app = QApplication.instance()
            if app is None:
                logger.warning("[DESKTOP_MAP] Cannot show map: Qt application not initialized.")
                return False

            if QThread.currentThread() == app.thread():
                self._gui_show(state)
                return bool(self._window and self._window.isVisible())

            if self._bridge:
                evt = threading.Event()
                success_flag = [False]

                def _cb():
                    try:
                        self._gui_show(state)
                        success_flag[0] = bool(self._window and self._window.isVisible())
                    except Exception as err:
                        logger.error(f"[DESKTOP_MAP] Error in _gui_show: {err}")
                        success_flag[0] = False
                    finally:
                        evt.set()

                from PyQt6.QtCore import QTimer
                QTimer.singleShot(0, _cb)
                evt.wait(timeout=timeout_s)
                return success_flag[0]
            else:
                logger.warning("[DESKTOP_MAP] Cannot show map: Bridge not available.")
                return False
        except Exception as e:
            logger.error(f"[DESKTOP_MAP] Failed to show desktop map window: {e}")
            return False

    def update_map(self, state: Dict[str, Any]) -> None:
        """Updates the markers and active route of the open desktop map window."""
        try:
            self._ensure_bridge()
            app = QApplication.instance()
            if app is not None and QThread.currentThread() == app.thread():
                self._gui_update(state)
            elif self._bridge:
                self._bridge.update_sig.emit(state)
        except Exception as e:
            logger.warning(f"[DESKTOP_MAP] Failed to update desktop map window: {e}")

    def close_map(self) -> None:
        """Closes / hides the desktop map window cleanly."""
        try:
            self._ensure_bridge()
            app = QApplication.instance()
            if app is not None and QThread.currentThread() == app.thread():
                self._gui_close()
            elif self._bridge:
                self._bridge.close_sig.emit()
        except Exception:
            pass

    def is_visible(self) -> bool:
        from PyQt6 import sip
        try:
            return bool(self._window and not sip.isdeleted(self._window) and self._window.isVisible())
        except Exception:
            return False


_controller_instance: Optional[DesktopMapController] = None


def get_desktop_map_controller() -> DesktopMapController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = DesktopMapController()
    return _controller_instance
