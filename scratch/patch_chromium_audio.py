file_path = "skills/device_location/desktop_map_window.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """from __future__ import annotations

import os"""

replacement = """from __future__ import annotations

import os
# Prevent Chromium WebEngine from binding to Windows audio hardware (avoids WASAPI/DirectSound conflict with TTS)
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-audio-output --mute-audio --no-sandbox --disable-features=AudioServiceOutOfProcess")"""

assert target in content, "Target not found in desktop_map_window.py"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: desktop_map_window.py updated with Chromium audio isolation.")

