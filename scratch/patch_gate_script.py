file_path = "scratch/run_final_acceptance_gate.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """        # 3. Check desktop effect
        map_mgr = get_map_state_manager()
        cur_state = map_mgr.get_state()
        desktop_effect = {
            "map_open": cur_state.get("is_open", False),
            "markers_count": len(cur_state.get("markers", [])),
            "has_route": cur_state.get("active_route") is not None,
            "selected_place_id": cur_state.get("selected_place_id")
        }
        
        pipeline_results.append({"""

replacement = """        # Process Qt events for web engine & map
        app = QApplication.instance()
        if app:
            for _ in range(15):
                app.processEvents()
                time.sleep(0.02)

        # 3. Check desktop effect
        map_mgr = get_map_state_manager()
        cur_state = map_mgr.get_state()
        desktop_effect = {
            "map_open": cur_state.get("is_open", False),
            "markers_count": len(cur_state.get("markers", [])),
            "has_route": cur_state.get("active_route") is not None,
            "selected_place_id": cur_state.get("selected_place_id")
        }
        
        pipeline_results.append({"""

assert target in content, "target not found"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: run_final_acceptance_gate.py updated with Qt event processing in Section 2.")

