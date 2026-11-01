file_path = "skills/device_location/desktop_map_window.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """    def _gui_show(self, state: Optional[Dict[str, Any]] = None):
        \"\"\"Must run on the Qt GUI thread.\"\"\"
        from PyQt6 import sip
        if self._window is None or sip.isdeleted(self._window):
            self._window = DesktopMapWindow()
        if self._window.isMinimized():
            self._window.showNormal()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()
        if state:
            self._window.update_map_state(state)"""

replacement = """    def _gui_show(self, state: Optional[Dict[str, Any]] = None):
        \"\"\"Must run on the Qt GUI thread.\"\"\"
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
                logger.warning(f"[DESKTOP_MAP] Exception updating map state: {e}")"""

assert target in content, "target not found"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: _gui_show updated safely.")

