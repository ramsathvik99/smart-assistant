file_path = "scratch/run_final_acceptance_gate.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """    # Capture screenshot via screen grab
    screenshot_path = str(PROJECT_ROOT / "data" / "final_gate_desktop_map.png")
    grab_ok = False
    try:
        if desktop_map._window and desktop_map._window.isVisible():
            screen = desktop_map._window.screen() or QApplication.primaryScreen()
            if screen:
                pix = screen.grabWindow(int(desktop_map._window.winId()))
                grab_ok = pix.save(screenshot_path)
    except Exception as e:
        print(f"Screenshot capture notice: {e}")
    res["screenshot_captured"] = grab_ok or os.path.exists(screenshot_path)
    res["screenshot_path"] = screenshot_path"""

replacement = """    # Capture screenshot via primary screen (root window 0 - does not force native winId)
    screenshot_path = str(PROJECT_ROOT / "data" / "final_gate_desktop_map.png")
    grab_ok = False
    try:
        screen = QApplication.primaryScreen()
        if screen:
            pix = screen.grabWindow(0)
            grab_ok = pix.save(screenshot_path)
    except Exception as e:
        print(f"Screenshot capture notice: {e}")
    res["screenshot_captured"] = grab_ok or os.path.exists(screenshot_path)
    res["screenshot_path"] = screenshot_path"""

assert target in content, "target not found"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: replaced winId grab with root window grab.")

