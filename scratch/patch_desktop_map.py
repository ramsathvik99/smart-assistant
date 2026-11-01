import re

file_path = "skills/device_location/desktop_map_window.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target1 = """        # Embedded WebEngine View for Leaflet
        self.web_view = QWebEngineView(self)
        self.web_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.web_view.setHtml(MAP_HTML_TEMPLATE)
        main_layout.addWidget(self.web_view)

        # Status Bar
        self.status_bar = QStatusBar(self)
        self.status_bar.setStyleSheet("background-color: #0b0f17; color: #94a3b8; font-size: 11px;")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. Leaflet embedded desktop engine initialized.")

        self._last_state: Optional[Dict[str, Any]] = None"""

replacement1 = """        # Embedded WebEngine View for Leaflet
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
            logger.warning(f"[DESKTOP_MAP] Error in _run_apply_state: {e}")"""

target2 = """            # Execute JS in WebEngineView
            json_str = json.dumps(state)
            js_code = f"applyState({json_str});"
            self.web_view.page().runJavaScript(js_code)"""

replacement2 = """            # Execute JS in WebEngineView if page loaded
            if self._page_loaded:
                self._run_apply_state(state)"""

target3 = """    def _on_center_clicked(self):
        self.web_view.page().runJavaScript("centerUser();")

    def _on_clear_route_clicked(self):
        try:
            from .map_state import get_map_state_manager
            msm = get_map_state_manager()
            msm.clear_route()
            self.web_view.page().runJavaScript("clearRoute();")
            self.route_badge.setVisible(False)
            self.btn_clear_route.setVisible(False)
        except Exception:
            pass

    def _on_zoom_in_clicked(self):
        self.web_view.page().runJavaScript("zoomIn();")

    def _on_zoom_out_clicked(self):
        self.web_view.page().runJavaScript("zoomOut();")"""

replacement3 = """    def _on_center_clicked(self):
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
                page.runJavaScript("zoomOut();")"""

assert target1 in content, "target1 not found"
assert target2 in content, "target2 not found"
assert target3 in content, "target3 not found"

content = content.replace(target1, replacement1, 1)
content = content.replace(target2, replacement2, 1)
content = content.replace(target3, replacement3, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: desktop_map_window.py patched cleanly.")

