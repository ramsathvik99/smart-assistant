file_path = "scratch/run_final_acceptance_gate.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """# Ensure QtWebEngine is safe
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView"""

replacement = """# Isolate Chromium audio backend from host audio drivers
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-audio-output --mute-audio --no-sandbox --disable-features=AudioServiceOutOfProcess"

# Ensure QtWebEngine is safe
try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView"""

assert target in content, "target not found"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: run_final_acceptance_gate.py updated with Chromium flags.")

