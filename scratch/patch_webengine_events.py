file_path = "skills/device_location/desktop_map_window.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """            json_str = json.dumps(state)
            page.runJavaScript(f"applyState({json_str});")
        except Exception as e:
            logger.warning(f"[DESKTOP_MAP] Error in _run_apply_state: {e}")"""

replacement = """            json_str = json.dumps(state)
            page.runJavaScript(f"applyState({json_str});")
            app = QApplication.instance()
            if app:
                app.processEvents()
        except Exception as e:
            logger.warning(f"[DESKTOP_MAP] Error in _run_apply_state: {e}")"""

assert target in content, "Target not found in desktop_map_window.py"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: desktop_map_window.py patched with processEvents in _run_apply_state.")

