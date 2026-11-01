file_path = "scratch/run_final_acceptance_gate.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """        pipeline_results.append({
            "command": cmd,
            "test_type": "Production pipeline test (live process_input & unified router)",
            "transcription": cmd,
            "intent": intent,
            "is_location_query": is_loc,
            "response": resp,
            "duration_s": round(elapsed, 3),
            "desktop_effect": desktop_effect,
            "passed": bool(resp and "error" not in resp.lower() and "cannot display" not in resp.lower())
        })
        time.sleep(0.3)"""

replacement = """        pipeline_results.append({
            "command": cmd,
            "test_type": "Production pipeline test (live process_input & unified router)",
            "transcription": cmd,
            "intent": intent,
            "is_location_query": is_loc,
            "response": resp,
            "duration_s": round(elapsed, 3),
            "desktop_effect": desktop_effect,
            "passed": bool(resp and "error" not in resp.lower() and "cannot display" not in resp.lower())
        })
        try:
            from extensions.system.tts_coordinator import wait_until_spoken
            wait_until_spoken(timeout=2.0)
        except Exception:
            pass
        time.sleep(0.5)"""

assert target in content, "Target not found in run_final_acceptance_gate.py"
content = content.replace(target, replacement, 1)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("SUCCESS: run_final_acceptance_gate.py updated with wait_until_spoken.")

