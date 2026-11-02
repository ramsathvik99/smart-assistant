import sys
import os
import subprocess
from datetime import datetime

sys.path.insert(0, os.path.abspath("."))

def verify_real_world():
    results = {}
    
    # 1. PostgreSQL pool & persistent memory
    print("--- 1. Testing PostgreSQL Persistent Storage ---")
    try:
        from core.db_pool import get_db_pool
        from core.chatgpt_memory import get_chatgpt_memory
        pool = get_db_pool()
        mem = get_chatgpt_memory()
        is_healthy = pool.is_healthy()
        facts = mem.get_user_facts(1)
        results["postgresql"] = {
            "status": "PASS" if is_healthy and facts else "FAIL",
            "pool_healthy": is_healthy,
            "fact_count": len(facts),
            "sample_facts": {k: facts[k] for k in list(facts.keys())[:3]}
        }
        print(f"PostgreSQL Pool: healthy={is_healthy}, retrieved {len(facts)} facts for user 1.")
    except Exception as e:
        results["postgresql"] = {"status": "FAIL", "error": str(e)}
        print(f"PostgreSQL failed: {e}")

    # 2. Local Clock Service
    print("\n--- 2. Testing Local Clock Deterministic Services ---")
    try:
        from core.unified_command_router import unified_router
        res_time = unified_router.execute_single_action("what time is it", user_id=1)
        res_date = unified_router.execute_single_action("what is today's date", user_id=1)
        res_year = unified_router.execute_single_action("what year are we currently in", user_id=1)
        
        now = datetime.now()
        current_year_str = str(now.year)
        results["clock"] = {
            "status": "PASS" if (res_time.get("handled") and res_date.get("handled") and current_year_str in res_year.get("response", "")) else "FAIL",
            "time_resp": res_time.get("response"),
            "date_resp": res_date.get("response"),
            "year_resp": res_year.get("response"),
        }
        print(f"Time: {res_time.get('response')}")
        print(f"Date: {res_date.get('response')}")
        print(f"Year: {res_year.get('response')}")
    except Exception as e:
        results["clock"] = {"status": "FAIL", "error": str(e)}
        print(f"Clock failed: {e}")

    # 3. Android Phone ADB Connection
    print("\n--- 3. Testing Physical Android Phone ADB Connection ---")
    try:
        from skills.device_management.adb_adapter import AdbAdapter
        adb = AdbAdapter()
        devices = adb.list_devices()
        phone_online = any(d.get("state") == "device" or d.get("online") is True for d in devices)
        target_serial = devices[0]["serial"] if devices else None
        
        # Check battery level of the real device
        battery_out = None
        if target_serial:
            battery_res = subprocess.run(["adb", "-s", target_serial, "shell", "dumpsys", "battery"], capture_output=True, text=True, timeout=5)
            for line in battery_res.stdout.splitlines():
                if "level:" in line:
                    battery_out = line.strip()
                    break

        results["android_adb"] = {
            "status": "PASS" if phone_online else "BLOCKED",
            "devices": devices,
            "real_battery_state": battery_out
        }
        print(f"ADB Devices: {devices}")
        print(f"Real Phone Battery: {battery_out}")
    except Exception as e:
        results["android_adb"] = {"status": "FAIL", "error": str(e)}
        print(f"ADB failed: {e}")

    # 4. External Web Search & Grounded Retrieval
    print("\n--- 4. Testing Web Search Grounding ---")
    try:
        from extensions.rag_system.retriever import RAGRetriever
        retriever = RAGRetriever()
        docs = retriever.retrieve("RAG_SEARCH", "artificial neural networks", user_id=1)
        has_results = bool(docs)
        results["rag_retriever"] = {
            "status": "PASS" if has_results else "EMPTY",
            "results_count": len(docs) if isinstance(docs, (list, dict)) else 1,
            "sample_snippet": str(docs)[:150] if has_results else ""
        }
        print(f"RAG Retrieval Results: {str(docs)[:100]}")
    except Exception as e:
        results["rag_retriever"] = {"status": "FAIL", "error": str(e)}
        print(f"RAG Retrieval: {e}")

    return results

if __name__ == "__main__":
    res = verify_real_world()
    print("\n--- Real World Verification Summary ---")
    print(res)
