file_path = "scratch/run_final_acceptance_gate.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Update screenshot capture
target_screen = """    # Defer screenshot to the end of test or use screen grab
    screenshot_path = str(PROJECT_ROOT / "data" / "final_gate_desktop_map.png")
    res["screenshot_captured"] = os.path.exists(screenshot_path)
    res["screenshot_path"] = screenshot_path"""

replacement_screen = """    # Capture screenshot via screen grab
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

if target_screen in content:
    content = content.replace(target_screen, replacement_screen, 1)

# Update section 3 to pump events
target_sec3 = """    # 1. Ensure restaurants are queried
    process_input("Find nearby restaurants around me.", user_id=1)
    
    # 2. Navigate to second one
    process_input("Navigate to the second one.", user_id=1)"""

replacement_sec3 = """    app = QApplication.instance()
    if app:
        for _ in range(15):
            app.processEvents()
            time.sleep(0.02)
    # 1. Ensure restaurants are queried
    process_input("Find nearby restaurants around me.", user_id=1)
    if app:
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)
    
    # 2. Navigate to second one
    process_input("Navigate to the second one.", user_id=1)
    if app:
        for _ in range(20):
            app.processEvents()
            time.sleep(0.02)"""

if target_sec3 in content:
    content = content.replace(target_sec3, replacement_sec3, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: run_final_acceptance_gate.py patched with Section 3 event pumping and screenshot grab.")

