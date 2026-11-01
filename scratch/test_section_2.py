import sys
import os
import time

PROJECT_ROOT = "c:/Users/Ram Sathvik/OneDrive/Desktop/smart_assistant"
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-audio-output --mute-audio --no-sandbox --disable-features=AudioServiceOutOfProcess"

from PyQt6.QtWidgets import QApplication
from PyQt6.QtWebEngineWidgets import QWebEngineView

app = QApplication.instance() or QApplication(sys.argv)
app.setQuitOnLastWindowClosed(False)

from legacy.assistant import process_input

commands_to_test = [
    "Where am I?",
    "Show map.",
    "Find nearby restaurants around me.",
    "What are there?",
    "Which is closest?",
    "Navigate to the second one.",
    "Show me its address.",
    "Clear the route.",
    "Close the map.",
]

for cmd in commands_to_test:
    print(f"\n--- TESTING COMMAND: {cmd} ---", flush=True)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    resp = process_input(cmd, user_id=1)
    print(f"RESPONSE: {resp[:100]}...", flush=True)
    for _ in range(25):
        app.processEvents()
        time.sleep(0.02)

print("\nALL 9 COMMANDS COMPLETED SUCCESSFULLY!", flush=True)

