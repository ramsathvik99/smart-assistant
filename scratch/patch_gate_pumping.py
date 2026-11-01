file_path = "scratch/run_final_acceptance_gate.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """        # 2. Execution via production pipeline process_input
        resp = process_input(cmd, user_id=1)
        elapsed = time.time() - t0
        
        # Process Qt events for web engine & map
        app = QApplication.instance()
        if app:
            for _ in range(15):
                app.processEvents()
                time.sleep(0.02)"""

replacement = """        # Process Qt events for web engine & map prior to command
        app = QApplication.instance()
        if app:
            for _ in range(20):
                app.processEvents()
                time.sleep(0.02)

        # 2. Execution via production pipeline process_input
        resp = process_input(cmd, user_id=1)
        elapsed = time.time() - t0
        
        # Process Qt events after command execution
        if app:
            for _ in range(25):
                app.processEvents()
                time.sleep(0.02)"""

assert target in content, "Target not found in run_final_acceptance_gate.py"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: run_final_acceptance_gate.py updated with pre- and post- Qt event pumping.")

