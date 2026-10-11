"""
Latency Pipeline Profiling & Measurement Script
Measures execution time of every stage:
- Input Turn Processing (DialogueStateManager)
- Environment Context Injection
- Semantic Understanding Engine
- Capability Discovery
- Intent Analysis & Planning (GoalPlanner)
- Router / OS Gateway Dispatch
- Observation & Verification
- Response Generation & Turn Record
"""

import time
import json
import sys
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.brain import brain_process
from extensions.dialogue_state_manager import get_dialogue_manager
from core.semantic_understanding import semantic_understanding_engine
from core.multi_intent_analyzer import multi_intent_analyzer
from core.goal_planner import goal_planner
from core.capability_registry import capability_registry
from core.environment_observer import observe_environment, select_relevant_categories
from core.os_gateway import get_os_gateway
from core.unified_command_router import unified_router


def benchmark_detailed(query: str, user_id: str = "1"):
    print(f"\n==================================================")
    print(f"Profiling Query: '{query}'")
    print(f"==================================================")
    uid_int = int(user_id) if str(user_id).isdigit() else 1
    
    # Stage 1: Dialogue State Manager turn processing
    t0 = time.perf_counter()
    dm = get_dialogue_manager(str(user_id))
    turn_data = dm.process_turn(query)
    t_turn = (time.perf_counter() - t0) * 1000

    # Stage 2: Environment injection
    t0 = time.perf_counter()
    try:
        from core.environment import get_state_engine
        engine = get_state_engine()
        state = engine.get_current_state(user_id)
        prev_state = engine.get_previous_state(user_id)
        history = engine.get_history(user_id, limit=5)
        comb_ctx = engine.format_combined_context(user_id)
    except Exception as e:
        pass
    t_env_inj = (time.perf_counter() - t0) * 1000

    # Stage 3: Semantic Understanding Analysis
    t0 = time.perf_counter()
    sem_rep = semantic_understanding_engine.analyze(query, dm.current_state, uid_int)
    t_sem = (time.perf_counter() - t0) * 1000

    # Stage 4: Multi-Intent Analysis
    t0 = time.perf_counter()
    intent_analysis = multi_intent_analyzer.analyze(query)
    t_multi = (time.perf_counter() - t0) * 1000

    # Stage 5: Capability Discovery
    t0 = time.perf_counter()
    discovered = capability_registry.discover(intent=query)
    t_cap = (time.perf_counter() - t0) * 1000

    # Stage 6: Planning
    t0 = time.perf_counter()
    plan = goal_planner.create_plan(intent_analysis)
    t_plan = (time.perf_counter() - t0) * 1000

    # Stage 7: End-to-end brain_process
    t0 = time.perf_counter()
    result = brain_process(query, user_id=user_id)
    t_total = (time.perf_counter() - t0) * 1000

    print(f"1. Dialogue Turn Processing:   {t_turn:6.2f} ms")
    print(f"2. Environment State Injection: {t_env_inj:6.2f} ms")
    print(f"3. Semantic Understanding:     {t_sem:6.2f} ms")
    print(f"4. Multi-Intent Analysis:      {t_multi:6.2f} ms")
    print(f"5. Capability Discovery:       {t_cap:6.2f} ms")
    print(f"6. Goal Planning:              {t_plan:6.2f} ms")
    print(f"--> END-TO-END brain_process:  {t_total:6.2f} ms")
    print(f"Status: {result.get('status')}, Intent: {result.get('intent')}")
    print(f"Response: {result.get('response', '')[:80]}...")


if __name__ == "__main__":
    queries = [
        "hello",
        "what time is it?",
        "what is my current directory?",
        "is vs code open?",
        "open notepad",
        "find my project and open it"
    ]
    for q in queries:
        benchmark_detailed(q)
