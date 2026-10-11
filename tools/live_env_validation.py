"""
Live Environment Validation Tool
─────────────────────────────────────────────────────────────
Run this script from the desktop (not inside IDE terminal) to validate
that the continuous environment observer sees real application state.

Usage:
    python tools/live_env_validation.py

Steps to validate:
    1. Run this script — it starts the observer.
    2. Open Brave/Chrome to YouTube, play Video A.
    3. Switch to VS Code or another app.
    4. Switch back to Brave/YouTube, play Video B.
    5. Watch the live printed state — it should track all changes.
    6. Press Ctrl+C to exit and see the full history summary.
"""

from __future__ import annotations

import logging
import signal
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("live_validation")
logging.getLogger("core.environment").setLevel(logging.DEBUG)


def print_state(state, label: str = "CURRENT STATE"):
    print(f"\n{'─' * 60}")
    print(f"  {label}")
    print(f"{'─' * 60}")
    if state.is_empty():
        print("  (no state captured yet)")
        return
    print(f"  Application    : {state.application}")
    print(f"  Window Title   : {state.window_title}")
    print(f"  App Category   : {state.app_category}")
    print(f"  Content Context: {state.content_context}")
    print(f"  Source Tier    : {state.source_tier}")
    print(f"  Entities:")
    for k, v in state.active_entities.items():
        if v is not None:
            print(f"    {k:25s}: {v}")
    print()


def main():
    USER_ID = "validation_user"

    from core.environment.continuous_observer import get_environment_coordinator

    print("=" * 60)
    print("  LIVE ENVIRONMENT OBSERVER VALIDATION")
    print("=" * 60)
    print()
    print("Starting observer... Poll interval: 3 seconds")
    print()
    print("Instructions:")
    print("  1. Open Brave/Chrome and go to YouTube")
    print("  2. Play a video (Video A)")
    print("  3. Switch to VS Code or another app")
    print("  4. Switch back to Brave/YouTube and play Video B")
    print("  5. Watch state changes below")
    print("  6. Press Ctrl+C to exit and see full history")
    print()

    coord = get_environment_coordinator()
    coord.ensure_running(USER_ID, poll_interval=3.0)
    print("[OK] Observer started")
    print()

    last_title = None
    tick = 0

    def shutdown(sig, frame):
        print("\n\nShutting down...\n")
        coord.stop_user(USER_ID)

        print("=" * 60)
        print("  ENVIRONMENT HISTORY")
        print("=" * 60)
        history = coord.get_history(USER_ID, limit=20)
        if not history:
            print("  (no history recorded)")
        else:
            for i, transition in enumerate(history):
                print(f"\n[{i+1}] {time.strftime('%H:%M:%S', time.localtime(transition.timestamp))}")
                print(f"     Change : {transition.change_type}")
                print(f"     Summary: {transition.transition_summary}")
                print(f"     Action : {transition.user_action}")
                if transition.entities_changed:
                    for k, diff in transition.entities_changed.items():
                        print(f"     {k}: {diff.get('before')} -> {diff.get('after')}")

        print()
        print("=" * 60)
        print("  COMBINED CONTEXT (as seen by brain.py)")
        print("=" * 60)
        print(coord.format_combined_context(USER_ID))
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)

    while True:
        time.sleep(3)
        tick += 1

        state = coord.get_current_state(USER_ID)
        current_title = state.window_title

        if current_title != last_title:
            print_state(state, f"STATE CHANGE (tick {tick})")
            last_title = current_title
        else:
            if tick % 5 == 0:
                print(f"[tick {tick:04d}] Monitoring... Current: {state.application or '(none)'} | {state.content_context or '(empty)'}")


if __name__ == "__main__":
    main()
