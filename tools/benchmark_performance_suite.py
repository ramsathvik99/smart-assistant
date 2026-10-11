"""
Benchmark Performance Suite for Friday Smart Assistant.
Measures cold-start and warm-run latencies across 20 representative requests:
- Conversational greetings and feeling questions
- Local date/time deterministic queries
- System, device, and application control
- Memory, tasks, and environment inspection
- Email, reminders, and calculator
- Audio output diagnosis
- LLM reasoning query with deadline enforcement
"""

import os
import sys
import time
import json
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Ensure workspace root in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.unified_command_router import UnifiedCommandRouter, Intent


BENCHMARK_PROMPTS = [
    ("Greeting", "Hello Friday"),
    ("Feeling/Smalltalk", "How are you feeling today, Friday?"),
    ("Date Query", "What's the date?"),
    ("Time Query", "What time is it?"),
    ("Capability Overview", "What can you do?"),
    ("Politeness", "Thank you Friday"),
    ("Identity", "Who are you?"),
    ("Audio Diagnosis", "I can't hear you"),
    ("App Launch", "Open notepad"),
    ("Mute Audio", "Mute volume"),
    ("Volume Control", "Increase the volume"),
    ("Arithmetic Calculator", "What is 45 times 8"),
    ("Set Reminder", "Remind me to submit report at 4pm"),
    ("Send Email", "Friday send an email to Sathvik saying let us meet tomorrow"),
    ("Check Email", "Check my email"),
    ("Active File Query", "What file am I editing?"),
    ("Active Window Query", "What is my active window?"),
    ("Dialogue Check", "Are you listening to me?"),
    ("Task Dashboard", "What tasks are running?"),
    ("LLM Query", "Explain why the sky is blue"),
]


def run_benchmark():
    router = UnifiedCommandRouter()
    
    print("=" * 80, flush=True)
    print("FRIDAY BENCHMARK PERFORMANCE SUITE — 20 REPRESENTATIVE REQUESTS", flush=True)
    print("=" * 80, flush=True)

    results = []

    import legacy.tts
    import legacy.sst
    from extensions.system.tts_backend import NeuralTTSBackend
    from skills.audio_management.sound_effects import SoundManager
    with patch("os.startfile", create=True), \
         patch("builtins.input", return_value="Test email notes"), \
         patch.object(legacy.sst, "listen", return_value="Test notes"), \
         patch.object(legacy.sst, "listen_continuous", return_value="Test notes"), \
         patch.object(legacy.tts, "speak", return_value=True), \
         patch.object(NeuralTTSBackend, "stream_and_play", return_value=True), \
         patch.object(SoundManager, "play", return_value=True):
        
        for idx, (category, utterance) in enumerate(BENCHMARK_PROMPTS, 1):
            # 1. COLD START RUN
            t_start_cold = time.perf_counter()
            intent_cold, params_cold = router.route_command(utterance)
            t_routed_cold = time.perf_counter()
            
            try:
                res_cold = router.execute_single_action(utterance, user_id=1)
            except Exception as e:
                res_cold = {"status": "error", "message": str(e)}
            t_finish_cold = time.perf_counter()

            cold_route_ms = (t_routed_cold - t_start_cold) * 1000.0
            cold_total_ms = (t_finish_cold - t_start_cold) * 1000.0

            # 2. WARM RUN
            t_start_warm = time.perf_counter()
            intent_warm, params_warm = router.route_command(utterance)
            t_routed_warm = time.perf_counter()
            try:
                res_warm = router.execute_single_action(utterance, user_id=1)
            except Exception as e:
                res_warm = {"status": "error", "message": str(e)}
            t_finish_warm = time.perf_counter()

            warm_route_ms = (t_routed_warm - t_start_warm) * 1000.0
            warm_total_ms = (t_finish_warm - t_start_warm) * 1000.0

            resp_preview = str(res_warm.get("response") or res_warm.get("message") or "")[:50].replace("\n", " ")

            record = {
                "index": idx,
                "category": category,
                "prompt": utterance,
                "intent": intent_warm.name if hasattr(intent_warm, "name") else str(intent_warm),
                "cold_route_ms": round(cold_route_ms, 2),
                "cold_total_ms": round(cold_total_ms, 2),
                "warm_route_ms": round(warm_route_ms, 2),
                "warm_total_ms": round(warm_total_ms, 2),
                "preview": resp_preview,
            }
            results.append(record)

            print(f"[{idx:02d}/20] {category:<22} | Cold: {cold_total_ms:7.2f}ms (route {cold_route_ms:5.2f}ms) | Warm: {warm_total_ms:7.2f}ms (route {warm_route_ms:5.2f}ms) | Intent: {record['intent']}", flush=True)

    print("=" * 80, flush=True)
    print("BENCHMARK SUMMARY & AGGREGATE METRICS", flush=True)
    print("=" * 80, flush=True)

    deterministic_runs = [r for r in results if r["category"] != "LLM Query"]
    avg_cold_det = sum(r["cold_total_ms"] for r in deterministic_runs) / len(deterministic_runs)
    avg_warm_det = sum(r["warm_total_ms"] for r in deterministic_runs) / len(deterministic_runs)
    avg_warm_route = sum(r["warm_route_ms"] for r in results) / len(results)

    print(f"Average Deterministic Query Cold Latency : {avg_cold_det:6.2f} ms", flush=True)
    print(f"Average Deterministic Query Warm Latency : {avg_warm_det:6.2f} ms", flush=True)
    print(f"Average Warm Intent Routing Latency     : {avg_warm_route:6.2f} ms", flush=True)
    
    passed_target = all(r["warm_total_ms"] < 1000.0 for r in deterministic_runs)
    print(f"All deterministic queries < 1000ms target: {'PASSED [OK]' if passed_target else 'FAILED'}", flush=True)
    print("=" * 80 + "\n", flush=True)

    out_file = os.path.join(os.path.dirname(__file__), "benchmark_results.json")
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Saved detailed benchmark output to {out_file}", flush=True)


if __name__ == "__main__":
    run_benchmark()
