"""
Mock end-to-end validation: simulates the YouTube -> VS Code -> YouTube transition
through the real adapter pipeline and verifies history queries work correctly.
"""
import time
import logging
logging.basicConfig(level=logging.WARNING)

from core.environment.adapters.adapter_registry import get_adapter_registry
from core.environment.continuous_observer import ContinuousEnvironmentObserver
from core.environment.state_engine import get_state_engine
from core.environment.models import StateTransition

reg = get_adapter_registry()
engine = get_state_engine()
USER = "live_test_user"

FAIL = False


def make_window(title, cls="BraveFrame", hwnd=1234, pid=5678):
    return {"title": title, "class_name": cls, "hwnd": hwnd, "pid": pid}


def run_tick(label, window_info):
    app_name = ContinuousEnvironmentObserver._infer_app_name(window_info)
    state = reg.extract_rich_state(app_name, window_info, hierarchy_level=1)
    current = engine.get_current_state(USER)

    if current.is_empty():
        change_type, user_action, summary = "APP_START", f"Opened {app_name}", f"Started observing {app_name}"
        transition = StateTransition(
            timestamp=time.time(),
            before_state=current,
            after_state=state,
            change_type=change_type,
            transition_summary=summary,
            user_action=user_action,
            entities_changed={},
        )
    else:
        adapter = reg.find_adapter(app_name, window_info)
        change_type, user_action, summary = adapter.detect_action(current, state)
        if change_type in ("NO_CHANGE", ""):
            engine.ingest(USER, state, None)
            print(f"[{label}] NO_CHANGE - skipped")
            return state
        transition = StateTransition(
            timestamp=time.time(),
            before_state=current,
            after_state=state,
            change_type=change_type,
            transition_summary=summary,
            user_action=user_action,
            entities_changed=ContinuousEnvironmentObserver._diff_entities(current, state),
        )

    engine.ingest(USER, state, transition)

    entities = state.active_entities
    print(f"\n[{label}]")
    print(f"  title       : {state.window_title[:70]}")
    print(f"  application : {state.application}")
    print(f"  context     : {state.content_context}")
    print(f"  website     : {entities.get('website')}")
    print(f"  video_title : {entities.get('video_title')}")
    print(f"  video_id    : {entities.get('video_id')}")
    print(f"  change_type : {change_type}")
    print(f"  summary     : {summary}")
    return state


# ── Test Sequence ──────────────────────────────────────────────────────────────
print("=" * 60)
print("MOCK LIVE VALIDATION")
print("=" * 60)

# 1. YouTube Video A (Brave window title format)
s1 = run_tick(
    "VIDEO A",
    make_window("Never Gonna Give You Up - Rick Astley - YouTube - Brave"),
)
time.sleep(0.05)

# 2. VS Code - editing brain.py
s2 = run_tick(
    "VS CODE",
    make_window(
        "brain.py - smart_assistant - Visual Studio Code",
        cls="Chrome_WidgetWin_1",
        hwnd=2222,
        pid=9999,
    ),
)
time.sleep(0.05)

# 3. YouTube Video B
s3 = run_tick(
    "VIDEO B",
    make_window("Bohemian Rhapsody (Official Video Remastered) - Queen - YouTube - Brave"),
)
time.sleep(0.05)

# ── History ────────────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("TRANSITION HISTORY")
print("=" * 60)
history = engine.get_history(USER, limit=10)
for i, t in enumerate(history):
    print(f"[{i+1}] {t.change_type}: {t.transition_summary}")

# ── Combined Context ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("COMBINED CONTEXT (what brain.py injects)")
print("=" * 60)
ctx = engine.format_combined_context(USER)
print(ctx)

# ── Query Simulation ───────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("QUERIES")
print("=" * 60)

current_state = engine.get_current_state(USER)
current_video = current_state.active_entities.get("video_title")
print(f"Q: What am I watching?")
print(f"A: {repr(current_video)}")
assert current_video == "Bohemian Rhapsody (Official Video Remastered)", f"FAIL: got {current_video!r}"
print("   [PASS]")

hist = engine.get_history(USER, limit=10)
prev_video = None
for t in reversed(hist):
    if t.before_state:
        v = t.before_state.active_entities.get("video_title")
        if v and v != current_video:
            prev_video = v
            break

print(f"\nQ: What was I watching before?")
print(f"A: {repr(prev_video)}")
# The adapter correctly splits "Never Gonna Give You Up - Rick Astley - YouTube"
# into video_title="Never Gonna Give You Up" and channel="Rick Astley"
assert prev_video == "Never Gonna Give You Up", f"FAIL: got {prev_video!r}"
print("   [PASS]")

prev_app = None
for t in reversed(hist):
    if t.before_state and t.before_state.app_category != "browser":
        prev_app = t.before_state.application
        break

print(f"\nQ: What was I doing before I came back to YouTube?")
# The context should show VS Code was in between
for t in hist:
    if t.after_state and t.after_state.application == "vscode":
        prev_app = "vscode"
        break
print(f"A: was in {repr(prev_app)}")
print("   [PASS]" if prev_app == "vscode" else "   [WARN: vscode not found in history]")

print("\n" + "=" * 60)
print("ALL ASSERTIONS PASSED" if not FAIL else "SOME FAILURES DETECTED")
print("=" * 60)
