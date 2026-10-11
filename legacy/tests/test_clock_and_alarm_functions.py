"""
Clock & Alarm Clock Integration Test Suite
Verifies:
1. Alarm Clock: set alarm (exact/relative time), background ringing, listing, cancelling, snoozing, dismissing.
2. Timers: set timer, countdown, listing, cancelling.
3. Stopwatch: start, stop/pause, lap, reset, status.
4. World Clock & Timezones: localized global time queries.
5. Local Clock & Date queries.
6. Multi-user isolation across all clock operations.
7. RAG boundary protection (deterministic local execution).
"""

import time
import pytest
import datetime
from core.unified_command_router import UnifiedCommandRouter, Intent
from skills.clock_manager import ClockController, get_clock_controller


@pytest.fixture
def router():
    r = UnifiedCommandRouter()
    r._semantic_enabled = False
    return r


@pytest.fixture
def clean_clock():
    ctrl = get_clock_controller()
    with ctrl._lock:
        for u_id in list(ctrl._alarms.keys()):
            for a in ctrl._alarms[u_id]:
                if a.timer_handle:
                    a.timer_handle.cancel()
        ctrl._alarms.clear()
        for u_id in list(ctrl._timers.keys()):
            for t in ctrl._timers[u_id]:
                if t.timer_handle:
                    t.timer_handle.cancel()
        ctrl._timers.clear()
        ctrl._stopwatches.clear()
        ctrl._ringing_alarms.clear()
    return ctrl


# ── 1. ALARM CLOCK TESTS ───────────────────────────────────────────────────

def test_set_alarm_absolute_times(router, clean_clock):
    queries = [
        "set an alarm for 7:30 AM",
        "set alarm for 6 AM",
        "set alarm at 8 PM",
        "wake me up at 6:30 AM",
        "set an alarm for tomorrow at 8 AM"
    ]
    for q in queries:
        intent, params = router.route_command(q)
        assert intent == Intent.TIME_QUERY, f"Failed on query: {q}"
        assert params.get("action") == "set_alarm"
        res = router.execute_single_action(q, user_id=1)
        assert res.get("status") == "success"
        assert res.get("alarm_id") is not None
        assert "Alarm set for" in res.get("message", "")


def test_set_alarm_relative_times(router, clean_clock):
    queries = [
        "set an alarm in 10 minutes",
        "set an alarm in 1 hour",
        "set alarm for 20 minutes from now",
        "set an alarm in 30 seconds"
    ]
    for q in queries:
        intent, params = router.route_command(q)
        assert intent == Intent.TIME_QUERY, f"Failed on query: {q}"
        assert params.get("action") == "set_alarm"
        res = router.execute_single_action(q, user_id=1)
        assert res.get("status") == "success"
        assert res.get("alarm_id") is not None


def test_alarm_ringing_and_snooze(clean_clock, monkeypatch):
    beeps = []
    speeches = []
    import skills.clock_manager.clock_controller as cc
    monkeypatch.setattr(cc, "_safe_beep", lambda **kwargs: beeps.append(True))
    monkeypatch.setattr(cc, "_safe_speak", lambda text: speeches.append(text))

    # Set alarm for 1 second in the future
    res = clean_clock.set_alarm("in 1 second", user_id=1, label="Morning Workout")
    assert res.get("status") == "success"
    alarm_id = res.get("alarm_id")

    # Wait for background timer to trigger
    time.sleep(1.2)

    # Check ringing state
    assert len(clean_clock._ringing_alarms) > 0
    assert any(a.alarm_id == alarm_id for a in clean_clock._ringing_alarms)
    assert len(beeps) > 0
    assert any("Morning Workout" in s for s in speeches)

    # Snooze alarm
    snooze_res = clean_clock.snooze_alarm(duration_minutes=5, user_id=1)
    assert snooze_res.get("status") == "success"
    assert "snoozed for 5 minutes" in snooze_res.get("message")


def test_list_and_cancel_alarms(router, clean_clock):
    # Set 2 alarms
    clean_clock.set_alarm("7:00 AM", user_id=1, label="Breakfast")
    clean_clock.set_alarm("9:30 AM", user_id=1, label="Meeting")

    # List alarms via router
    q_list = "show my alarms"
    intent, params = router.route_command(q_list)
    assert intent == Intent.TIME_QUERY
    assert params.get("action") == "list_alarms"
    res_list = router.execute_single_action(q_list, user_id=1)
    assert res_list.get("status") == "success"
    assert res_list.get("count") == 2
    assert "Breakfast" in res_list.get("message")

    # Cancel alarm for 7:00 AM
    q_cancel = "cancel alarm for 7:00 AM"
    res_cancel = router.execute_single_action(q_cancel, user_id=1)
    assert res_cancel.get("status") == "success"
    assert "Cancelled alarm for" in res_cancel.get("message")

    # Cancel all alarms
    q_cancel_all = "cancel all alarms"
    res_cancel_all = router.execute_single_action(q_cancel_all, user_id=1)
    assert res_cancel_all.get("status") == "success"
    assert "Cancelled all" in res_cancel_all.get("message")


# ── 2. COUNTDOWN TIMERS ────────────────────────────────────────────────────

def test_timers_workflow(router, clean_clock):
    # 1. Set timer
    q_set = "set a timer for 5 minutes"
    intent, params = router.route_command(q_set)
    assert intent == Intent.TIME_QUERY
    assert params.get("action") == "set_timer"
    res_set = router.execute_single_action(q_set, user_id=1)
    assert res_set.get("status") == "success"
    assert res_set.get("duration_seconds") == 300

    # 2. List timers
    q_list = "show active timers"
    res_list = router.execute_single_action(q_list, user_id=1)
    assert res_list.get("status") == "success"
    assert res_list.get("count") == 1

    # 3. Cancel timers
    q_cancel = "cancel timer"
    res_cancel = router.execute_single_action(q_cancel, user_id=1)
    assert res_cancel.get("status") == "success"


# ── 3. STOPWATCH ───────────────────────────────────────────────────────────

def test_stopwatch_workflow(router, clean_clock):
    # 1. Start stopwatch
    q_start = "start stopwatch"
    intent, params = router.route_command(q_start)
    assert intent == Intent.TIME_QUERY
    assert params.get("action") == "stopwatch_start"
    res_start = router.execute_single_action(q_start, user_id=1)
    assert res_start.get("status") == "success"
    assert res_start.get("is_running") is True

    time.sleep(0.2)

    # 2. Lap stopwatch
    q_lap = "lap stopwatch"
    res_lap = router.execute_single_action(q_lap, user_id=1)
    assert res_lap.get("status") == "success"
    assert res_lap.get("lap", {}).get("lap_number") == 1

    # 3. Stop stopwatch
    q_stop = "stop stopwatch"
    res_stop = router.execute_single_action(q_stop, user_id=1)
    assert res_stop.get("status") == "success"
    assert res_stop.get("is_running") is False
    assert res_stop.get("elapsed_seconds") > 0

    # 4. Reset stopwatch
    q_reset = "reset stopwatch"
    res_reset = router.execute_single_action(q_reset, user_id=1)
    assert res_reset.get("status") == "success"


# ── 4. WORLD CLOCK & LOCAL CLOCK ───────────────────────────────────────────

def test_world_clock_and_local_queries(router, clean_clock):
    world_queries = [
        ("what time is it in Tokyo", "Tokyo"),
        ("what is the time in London", "London"),
        ("current time in New York", "New York"),
        ("time in Paris", "Paris"),
        ("current time in Sydney", "Sydney")
    ]
    for q, expected_loc in world_queries:
        intent, params = router.route_command(q)
        assert intent == Intent.TIME_QUERY, f"Failed on query: {q}"
        assert params.get("action") == "world_time"
        res = router.execute_single_action(q, user_id=1)
        assert res.get("status") == "success"
        assert expected_loc in res.get("message")
        assert res.get("time_str") is not None

    # Local Time
    q_time = "what time is it"
    res_time = router.execute_single_action(q_time, user_id=1)
    assert res_time.get("status") == "success"
    assert "The current time is" in res_time.get("response")

    # Local Date
    q_date = "what is today's date"
    res_date = router.execute_single_action(q_date, user_id=1)
    assert res_date.get("status") == "success"
    assert "Today is" in res_date.get("response")


# ── 5. MULTI-USER ISOLATION ────────────────────────────────────────────────

def test_clock_user_isolation(clean_clock):
    # User 1 sets alarm for 6 AM
    clean_clock.set_alarm("6:00 AM", user_id=1, label="User1 Alarm")
    # User 2 sets alarm for 9 AM
    clean_clock.set_alarm("9:00 AM", user_id=2, label="User2 Alarm")

    list1 = clean_clock.list_alarms(user_id=1)
    list2 = clean_clock.list_alarms(user_id=2)

    assert list1["count"] == 1
    assert "User1 Alarm" in list1["message"]
    assert "User2 Alarm" not in list1["message"]

    assert list2["count"] == 1
    assert "User2 Alarm" in list2["message"]
    assert "User1 Alarm" not in list2["message"]


# ── 6. RAG BOUNDARY PROTECTION ──────────────────────────────────────────────

def test_clock_and_alarm_rag_boundary(router):
    clock_commands = [
        "set an alarm for 7 AM",
        "wake me up at 6:30 AM",
        "show my alarms",
        "cancel all alarms",
        "snooze alarm for 5 minutes",
        "set a timer for 10 minutes",
        "start stopwatch",
        "stop stopwatch",
        "what time is it in Tokyo",
        "what time is it",
        "what is the date"
    ]
    for cmd in clock_commands:
        intent, params = router.route_command(cmd)
        assert intent != Intent.RAG_SEARCH, f"Command '{cmd}' was hijacked by RAG_SEARCH!"
        assert intent != Intent.GENERAL_CONVERSATION, f"Command '{cmd}' became general conversation!"
        assert intent in (Intent.TIME_QUERY, Intent.DATE_QUERY), f"Command '{cmd}' mapped to unexpected intent {intent}!"
