import sys
import os
import time

sys.path.insert(0, ".")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView

app = QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

from skills.device_location.desktop_map_window import DesktopMapWindow, get_desktop_map_controller
from skills.device_location.map_state import get_map_state_manager

dmc = get_desktop_map_controller()
msm = get_map_state_manager()

print("1. Showing map...")
dmc.show_map(msm.get_state())
for _ in range(30):
    app.processEvents()
    time.sleep(0.05)

print("2. Updating map...")
dmc.update_map(msm.get_state())
for _ in range(30):
    app.processEvents()
    time.sleep(0.05)

print("3. Closing map...")
dmc.close_map()
for _ in range(20):
    app.processEvents()
    time.sleep(0.05)

print("4. Reopening map...")
dmc.show_map(msm.get_state())
for _ in range(30):
    app.processEvents()
    time.sleep(0.05)

print("5. Showing map AGAIN while already visible...")
dmc.show_map(msm.get_state())
for _ in range(30):
    app.processEvents()
    time.sleep(0.05)

print("ALL PASSED WITHOUT CRASH!")
