"""
Clock Manager & Alarm Clock Skill for NOVA
Provides comprehensive, thread-safe, multi-user clock operations:
1. Alarm Clock: Set alarms (exact time or relative duration), countdown, background ringing, snooze, list, cancel, dismiss.
2. Countdown Timers: Set duration timer, background alert on completion, list, cancel.
3. Stopwatch: Start, pause/stop, resume, lap, reset, status.
4. World Clock & Timezones: Time and date queries for global cities and standard timezones.
5. Local System Clock: Fast local time and date retrieval.
"""

import os
import re
import time
import uuid
import logging
import threading
import datetime
from typing import Dict, Any, List, Optional, Tuple

try:
    import winsound
except ImportError:
    winsound = None

try:
    import zoneinfo
except ImportError:
    from backports import zoneinfo  # type: ignore

logger = logging.getLogger(__name__)


# ── Global City / Timezone Mapping ──────────────────────────────────────────
CITY_TIMEZONE_MAP = {
    "tokyo": "Asia/Tokyo",
    "japan": "Asia/Tokyo",
    "london": "Europe/London",
    "uk": "Europe/London",
    "england": "Europe/London",
    "paris": "Europe/Paris",
    "france": "Europe/Paris",
    "berlin": "Europe/Berlin",
    "germany": "Europe/Berlin",
    "rome": "Europe/Rome",
    "italy": "Europe/Rome",
    "madrid": "Europe/Madrid",
    "spain": "Europe/Madrid",
    "amsterdam": "Europe/Amsterdam",
    "new york": "America/New_York",
    "ny": "America/New_York",
    "nyc": "America/New_York",
    "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles",
    "california": "America/Los_Angeles",
    "chicago": "America/Chicago",
    "san francisco": "America/Los_Angeles",
    "seattle": "America/Los_Angeles",
    "toronto": "America/Toronto",
    "vancouver": "America/Vancouver",
    "canada": "America/Toronto",
    "sydney": "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "australia": "Australia/Sydney",
    "auckland": "Pacific/Auckland",
    "new zealand": "Pacific/Auckland",
    "dubai": "Asia/Dubai",
    "uae": "Asia/Dubai",
    "singapore": "Asia/Singapore",
    "hong kong": "Asia/Hong_Kong",
    "beijing": "Asia/Shanghai",
    "shanghai": "Asia/Shanghai",
    "china": "Asia/Shanghai",
    "mumbai": "Asia/Kolkata",
    "delhi": "Asia/Kolkata",
    "hyderabad": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata",
    "bengaluru": "Asia/Kolkata",
    "kolkata": "Asia/Kolkata",
    "chennai": "Asia/Kolkata",
    "india": "Asia/Kolkata",
    "moscow": "Europe/Moscow",
    "russia": "Europe/Moscow",
    "seoul": "Asia/Seoul",
    "korea": "Asia/Seoul",
    "south korea": "Asia/Seoul",
    "cairo": "Africa/Cairo",
    "egypt": "Africa/Cairo",
    "johannesburg": "Africa/Johannesburg",
    "south africa": "Africa/Johannesburg",
    "sao paulo": "America/Sao_Paulo",
    "brazil": "America/Sao_Paulo",
    "buenos aires": "America/Argentina/Buenos_Aires",
    "argentina": "America/Argentina/Buenos_Aires",
    "mexico city": "America/Mexico_City",
    "mexico": "America/Mexico_City",
    "utc": "UTC",
    "gmt": "GMT",
    "est": "America/New_York",
    "pst": "America/Los_Angeles",
    "cst": "America/Chicago",
    "mst": "America/Denver",
    "ist": "Asia/Kolkata"
}


def _safe_beep(freq: int = 1800, dur_ms: int = 800, count: int = 3):
    """Play alert beeps safely without blocking main thread."""
    if winsound:
        for _ in range(count):
            try:
                winsound.Beep(freq, dur_ms)
                time.sleep(0.1)
            except Exception:
                pass


def _safe_speak(text: str):
    """Speak text safely using TTS subsystem."""
    try:
        from legacy.tts import speak
        speak(text)
    except Exception as e:
        logger.debug(f"[CLOCK] TTS speak unavailable: {e}")


class AlarmItem:
    """Represents an active alarm instance."""

    def __init__(self, alarm_id: str, target_time: datetime.datetime, label: str, user_id: int):
        self.alarm_id = alarm_id
        self.target_time = target_time
        self.label = label or "Alarm"
        self.user_id = user_id
        self.created_at = datetime.datetime.now()
        self.is_active = True
        self.is_ringing = False
        self.timer_handle: Optional[threading.Timer] = None

    def to_dict(self) -> Dict[str, Any]:
        now = datetime.datetime.now()
        remaining_seconds = max(0, int((self.target_time - now).total_seconds()))
        mins, secs = divmod(remaining_seconds, 60)
        hrs, mins = divmod(mins, 60)
        if hrs > 0:
            rem_str = f"{hrs}h {mins}m {secs}s"
        elif mins > 0:
            rem_str = f"{mins}m {secs}s"
        else:
            rem_str = f"{secs}s"

        return {
            "id": self.alarm_id,
            "time_str": self.target_time.strftime("%I:%M %p"),
            "target_iso": self.target_time.isoformat(),
            "label": self.label,
            "is_active": self.is_active,
            "is_ringing": self.is_ringing,
            "remaining_seconds": remaining_seconds,
            "remaining_readable": rem_str
        }


class TimerItem:
    """Represents a countdown timer instance."""

    def __init__(self, timer_id: str, duration_seconds: int, label: str, user_id: int):
        self.timer_id = timer_id
        self.duration_seconds = duration_seconds
        self.label = label or "Timer"
        self.user_id = user_id
        self.started_at = datetime.datetime.now()
        self.target_time = self.started_at + datetime.timedelta(seconds=duration_seconds)
        self.is_active = True
        self.timer_handle: Optional[threading.Timer] = None

    def to_dict(self) -> Dict[str, Any]:
        now = datetime.datetime.now()
        remaining_seconds = max(0, int((self.target_time - now).total_seconds()))
        mins, secs = divmod(remaining_seconds, 60)
        hrs, mins = divmod(mins, 60)
        if hrs > 0:
            rem_str = f"{hrs}h {mins}m {secs}s"
        elif mins > 0:
            rem_str = f"{mins}m {secs}s"
        else:
            rem_str = f"{secs}s"

        return {
            "id": self.timer_id,
            "duration_seconds": self.duration_seconds,
            "label": self.label,
            "is_active": self.is_active,
            "remaining_seconds": remaining_seconds,
            "remaining_readable": rem_str
        }


class StopwatchItem:
    """Represents an active stopwatch instance."""

    def __init__(self, user_id: int):
        self.user_id = user_id
        self.is_running = False
        self.start_time: Optional[float] = None
        self.accumulated_seconds: float = 0.0
        self.laps: List[Dict[str, Any]] = []

    def start(self):
        if not self.is_running:
            self.start_time = time.time()
            self.is_running = True

    def stop(self) -> float:
        if self.is_running and self.start_time is not None:
            self.accumulated_seconds += time.time() - self.start_time
            self.is_running = False
            self.start_time = None
        return self.get_elapsed()

    def reset(self):
        self.is_running = False
        self.start_time = None
        self.accumulated_seconds = 0.0
        self.laps.clear()

    def lap(self) -> Dict[str, Any]:
        elapsed = self.get_elapsed()
        lap_num = len(self.laps) + 1
        lap_data = {
            "lap_number": lap_num,
            "split_seconds": elapsed,
            "formatted": self.format_time(elapsed)
        }
        self.laps.append(lap_data)
        return lap_data

    def get_elapsed(self) -> float:
        if self.is_running and self.start_time is not None:
            return self.accumulated_seconds + (time.time() - self.start_time)
        return self.accumulated_seconds

    @staticmethod
    def format_time(seconds: float) -> str:
        mins, secs = divmod(int(seconds), 60)
        hrs, mins = divmod(mins, 60)
        millis = int((seconds - int(seconds)) * 100)
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:02d}.{millis:02d}"
        return f"{mins:02d}:{secs:02d}.{millis:02d}"


class ClockController:
    """
    Central Controller for Alarm Clock, Timers, Stopwatch, and World Clock operations.
    Thread-safe and user-isolated.
    """

    _instance: Optional["ClockController"] = None
    _lock = threading.Lock()

    def __init__(self):
        self._alarms: Dict[int, List[AlarmItem]] = {}
        self._timers: Dict[int, List[TimerItem]] = {}
        self._stopwatches: Dict[int, StopwatchItem] = {}
        self._ringing_alarms: List[AlarmItem] = []
        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls) -> "ClockController":
        with cls._lock:
            if cls._instance is None:
                cls._instance = ClockController()
            return cls._instance

    # ── NATURAL LANGUAGE PARSING HELPERS ──────────────────────────────────────

    @staticmethod
    def parse_time_expression(text: str) -> Optional[Tuple[datetime.datetime, str]]:
        """
        Parses exact or relative time string into target datetime and recognized label.
        Returns: (target_datetime, label) or None
        """
        if not text:
            return None

        clean = text.lower().strip()
        now = datetime.datetime.now()

        # 1. Relative durations: "in 10 minutes", "in 1 hour", "for 30 seconds", "in 2 hours 15 minutes"
        m_rel = re.search(
            r'\b(?:in|for|after)\s+(?:(\d+)\s*h(?:our)?s?)?\s*(?:(\d+)\s*m(?:in(?:ute)?)?s?)?\s*(?:(\d+)\s*s(?:ec(?:ond)?)?s?)?',
            clean
        )
        if m_rel and any(m_rel.groups()):
            hrs = int(m_rel.group(1) or 0)
            mins = int(m_rel.group(2) or 0)
            secs = int(m_rel.group(3) or 0)
            total_secs = hrs * 3600 + mins * 60 + secs
            if total_secs > 0:
                target = now + datetime.timedelta(seconds=total_secs)
                label_part = re.sub(r'\b(?:set|an?|alarm|timer|for|in|after|\d+\s*(?:hours?|hrs?|minutes?|mins?|seconds?|secs?))\b', '', clean).strip()
                return target, label_part or "Alarm"

        # 2. Clock formats: "7:30 am", "7:30", "18:00", "6 am", "7 pm", "6:30 in the morning", "8 at night"
        m_clock = re.search(
            r'\b(?:at|for|to)?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|in\s+the\s+morning|in\s+the\s+afternoon|in\s+the\s+evening|at\s+night)?\b',
            clean
        )
        if m_clock:
            hour = int(m_clock.group(1))
            minute = int(m_clock.group(2) or 0)
            meridiem = (m_clock.group(3) or "").strip()

            if hour > 24 or minute >= 60:
                return None

            is_pm = any(k in meridiem for k in ["pm", "afternoon", "evening", "night"])
            is_am = any(k in meridiem for k in ["am", "morning"])

            if is_pm and hour < 12:
                hour += 12
            elif is_am and hour == 12:
                hour = 0
            elif not meridiem and hour < 7:
                # Ambiguous small hour like "alarm for 6" defaults to 6 AM or next occurrence
                pass

            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if "tomorrow" in clean or target <= now:
                target += datetime.timedelta(days=1)

            label_part = re.sub(r'\b(?:set|an?|alarm|wake\s+me\s+up|at|for|\d{1,2}(?::\d{2})?|\b(?:am|pm|morning|night|tomorrow))\b', '', clean).strip()
            return target, label_part or "Alarm"

        return None

    @staticmethod
    def parse_duration_seconds(text: str) -> int:
        """Parses duration string like '5 minutes 30 seconds' into total seconds."""
        clean = text.lower().strip()
        secs = 0
        h = re.search(r'(\d+)\s*(?:hours?|hrs?)', clean)
        m = re.search(r'(\d+)\s*(?:minutes?|mins?)', clean)
        s = re.search(r'(\d+)\s*(?:seconds?|secs?)', clean)
        if h: secs += int(h.group(1)) * 3600
        if m: secs += int(m.group(1)) * 60
        if s: secs += int(s.group(1))

        if secs == 0:
            m_num = re.search(r'\b(\d+)\b', clean)
            if m_num:
                # Default bare number to minutes if >= 1
                secs = int(m_num.group(1)) * 60

        return secs

    # ── ALARM CLOCK CORE ──────────────────────────────────────────────────────

    def set_alarm(self, time_or_text: str, user_id: int = 1, label: Optional[str] = None) -> Dict[str, Any]:
        """
        Sets an alarm for any specified time or relative duration.
        Schedules a non-blocking background timer that rings when time is reached.
        """
        with self._lock:
            parsed = self.parse_time_expression(time_or_text)
            if not parsed:
                return {
                    "success": False,
                    "status": "error",
                    "message": f"Could not understand the alarm time '{time_or_text}'. Please specify a time like '7:30 AM' or 'in 15 minutes'."
                }

            target_time, auto_label = parsed
            alarm_label = label or auto_label or "Alarm"
            alarm_id = str(uuid.uuid4())[:8]

            now = datetime.datetime.now()
            delay = max(0.1, (target_time - now).total_seconds())

            alarm = AlarmItem(alarm_id=alarm_id, target_time=target_time, label=alarm_label, user_id=user_id)

            def _alarm_trigger():
                self._trigger_alarm_ringing(alarm)

            timer = threading.Timer(delay, _alarm_trigger)
            timer.daemon = True
            alarm.timer_handle = timer
            timer.start()

            if user_id not in self._alarms:
                self._alarms[user_id] = []
            self._alarms[user_id].append(alarm)

            time_str = target_time.strftime("%I:%M %p")
            is_tomorrow = target_time.date() > now.date()
            day_str = " tomorrow" if is_tomorrow else ""
            msg = f"Alarm set for {time_str}{day_str} ({alarm_label})."
            logger.info(f"[ALARM] User {user_id} set alarm {alarm_id} for {target_time.isoformat()}")

            return {
                "success": True,
                "status": "success",
                "alarm_id": alarm_id,
                "target_time": target_time.isoformat(),
                "time_str": time_str,
                "label": alarm_label,
                "message": msg,
                "response": msg
            }

    def _trigger_alarm_ringing(self, alarm: AlarmItem):
        """Internal callback invoked when alarm time arrives."""
        with self._lock:
            alarm.is_ringing = True
            self._ringing_alarms.append(alarm)

        logger.info(f"[ALARM] Alarm {alarm.alarm_id} is ringing: {alarm.label}")

        def _ring_worker():
            _safe_beep(freq=1800, dur_ms=800, count=4)
            _safe_speak(f"Wake up! Your alarm for {alarm.label} is ringing!")

        threading.Thread(target=_ring_worker, daemon=True).start()

    def list_alarms(self, user_id: int = 1) -> Dict[str, Any]:
        """Lists all active alarms for the user."""
        with self._lock:
            user_list = [a for a in self._alarms.get(user_id, []) if a.is_active]
            if not user_list:
                return {
                    "success": True,
                    "status": "success",
                    "count": 0,
                    "alarms": [],
                    "message": "You have no active alarms set.",
                    "response": "You have no active alarms set."
                }

            alarms_data = [a.to_dict() for a in user_list]
            summary_items = [f"{a['time_str']} ({a['label']}, in {a['remaining_readable']})" for a in alarms_data]
            msg = f"You have {len(alarms_data)} active alarm(s):\n" + "\n".join(f"- {s}" for s in summary_items)

            return {
                "success": True,
                "status": "success",
                "count": len(alarms_data),
                "alarms": alarms_data,
                "message": msg,
                "response": msg
            }

    def cancel_alarm(self, query: str = "", user_id: int = 1) -> Dict[str, Any]:
        """Cancels matching or all active alarms."""
        with self._lock:
            user_list = self._alarms.get(user_id, [])
            if not user_list:
                return {
                    "success": True,
                    "status": "success",
                    "message": "No active alarms found to cancel.",
                    "response": "No active alarms found to cancel."
                }

            if "all" in query.lower():
                cancelled_count = 0
                for a in user_list:
                    if a.timer_handle:
                        a.timer_handle.cancel()
                    a.is_active = False
                    cancelled_count += 1
                self._alarms[user_id] = []
                msg = f"Cancelled all {cancelled_count} active alarm(s)."
                return {"success": True, "status": "success", "count": cancelled_count, "message": msg, "response": msg}

            # Cancel specific or latest alarm
            target_alarm = None
            if query:
                for a in user_list:
                    if a.target_time.strftime("%I:%M").lower() in query.lower() or a.alarm_id in query:
                        target_alarm = a
                        break
            if not target_alarm and user_list:
                target_alarm = user_list[0]

            if target_alarm:
                if target_alarm.timer_handle:
                    target_alarm.timer_handle.cancel()
                target_alarm.is_active = False
                user_list.remove(target_alarm)
                time_str = target_alarm.target_time.strftime("%I:%M %p")
                msg = f"Cancelled alarm for {time_str} ({target_alarm.label})."
                return {"success": True, "status": "success", "message": msg, "response": msg}

            return {"success": False, "status": "error", "message": "Could not find matching alarm to cancel."}

    def snooze_alarm(self, duration_minutes: int = 5, user_id: int = 1) -> Dict[str, Any]:
        """Snoozes the currently ringing or most recent alarm."""
        with self._lock:
            target_alarm = self._ringing_alarms.pop(0) if self._ringing_alarms else None
            if not target_alarm:
                user_list = [a for a in self._alarms.get(user_id, []) if a.is_active]
                if user_list:
                    target_alarm = user_list[0]

            if not target_alarm:
                return {"success": False, "status": "error", "message": "No ringing alarm to snooze."}

            target_alarm.is_ringing = False
            new_target = datetime.datetime.now() + datetime.timedelta(minutes=duration_minutes)
            target_alarm.target_time = new_target

            def _snooze_trigger():
                self._trigger_alarm_ringing(target_alarm)

            timer = threading.Timer(duration_minutes * 60, _snooze_trigger)
            timer.daemon = True
            target_alarm.timer_handle = timer
            timer.start()

            msg = f"Alarm snoozed for {duration_minutes} minutes until {new_target.strftime('%I:%M %p')}."
            return {"success": True, "status": "success", "message": msg, "response": msg}

    def dismiss_alarm(self, user_id: int = 1) -> Dict[str, Any]:
        """Dismisses/stops any currently ringing alarms."""
        with self._lock:
            if self._ringing_alarms:
                self._ringing_alarms.clear()
                msg = "Alarm dismissed."
                return {"success": True, "status": "success", "message": msg, "response": msg}
            return {"success": True, "status": "success", "message": "No alarms are currently ringing.", "response": "No alarms are currently ringing."}

    # ── TIMER CORE ────────────────────────────────────────────────────────────

    def set_timer(self, duration_text: str, user_id: int = 1, label: Optional[str] = None) -> Dict[str, Any]:
        """Sets a countdown timer for specified seconds/minutes/hours."""
        with self._lock:
            secs = self.parse_duration_seconds(duration_text)
            if secs <= 0:
                return {
                    "success": False,
                    "status": "error",
                    "message": f"Could not understand timer duration '{duration_text}'. Try '5 minutes' or '30 seconds'."
                }

            timer_id = str(uuid.uuid4())[:8]
            t_label = label or "Timer"
            t_item = TimerItem(timer_id=timer_id, duration_seconds=secs, label=t_label, user_id=user_id)

            def _timer_alert():
                logger.info(f"[TIMER] Timer {timer_id} completed ({t_label})")
                _safe_beep(freq=1600, dur_ms=600, count=3)
                _safe_speak(f"Your {t_label} for {t_item.to_dict()['remaining_readable']} is done!")

            timer_handle = threading.Timer(secs, _timer_alert)
            timer_handle.daemon = True
            t_item.timer_handle = timer_handle
            timer_handle.start()

            if user_id not in self._timers:
                self._timers[user_id] = []
            self._timers[user_id].append(t_item)

            mins, s = divmod(secs, 60)
            hrs, mins = divmod(mins, 60)
            dur_str = f"{hrs} hour(s) " if hrs else ""
            dur_str += f"{mins} minute(s) " if mins else ""
            dur_str += f"{s} second(s)" if s or not dur_str else ""
            msg = f"Timer set for {dur_str.strip()}."

            return {
                "success": True,
                "status": "success",
                "timer_id": timer_id,
                "duration_seconds": secs,
                "message": msg,
                "response": msg
            }

    def list_timers(self, user_id: int = 1) -> Dict[str, Any]:
        """Lists all active countdown timers."""
        with self._lock:
            active = [t for t in self._timers.get(user_id, []) if t.is_active and t.target_time > datetime.datetime.now()]
            if not active:
                return {"success": True, "status": "success", "count": 0, "timers": [], "message": "No active timers.", "response": "No active timers."}

            timers_data = [t.to_dict() for t in active]
            summary = "\n".join(f"- {t['label']}: {t['remaining_readable']} remaining" for t in timers_data)
            msg = f"You have {len(timers_data)} active timer(s):\n{summary}"
            return {"success": True, "status": "success", "count": len(timers_data), "timers": timers_data, "message": msg, "response": msg}

    def cancel_timer(self, user_id: int = 1) -> Dict[str, Any]:
        """Cancels running timer(s)."""
        with self._lock:
            user_list = self._timers.get(user_id, [])
            if not user_list:
                return {"success": True, "status": "success", "message": "No active timers to cancel.", "response": "No active timers to cancel."}

            for t in user_list:
                if t.timer_handle:
                    t.timer_handle.cancel()
                t.is_active = False
            self._timers[user_id] = []
            msg = "Active timer(s) cancelled."
            return {"success": True, "status": "success", "message": msg, "response": msg}

    # ── STOPWATCH CORE ────────────────────────────────────────────────────────

    def start_stopwatch(self, user_id: int = 1) -> Dict[str, Any]:
        """Starts or resumes the stopwatch."""
        with self._lock:
            if user_id not in self._stopwatches:
                self._stopwatches[user_id] = StopwatchItem(user_id)
            sw = self._stopwatches[user_id]
            sw.start()
            msg = "Stopwatch started."
            return {"success": True, "status": "success", "is_running": True, "message": msg, "response": msg}

    def stop_stopwatch(self, user_id: int = 1) -> Dict[str, Any]:
        """Stops/pauses the stopwatch and returns current elapsed time."""
        with self._lock:
            sw = self._stopwatches.get(user_id)
            if not sw:
                return {"success": True, "status": "success", "elapsed_seconds": 0, "formatted": "00:00.00", "message": "Stopwatch is not running.", "response": "Stopwatch is not running."}
            elapsed = sw.stop()
            formatted = StopwatchItem.format_time(elapsed)
            msg = f"Stopwatch paused at {formatted}."
            return {"success": True, "status": "success", "is_running": False, "elapsed_seconds": elapsed, "formatted": formatted, "message": msg, "response": msg}

    def reset_stopwatch(self, user_id: int = 1) -> Dict[str, Any]:
        """Resets the stopwatch to 0."""
        with self._lock:
            sw = self._stopwatches.get(user_id)
            if sw:
                sw.reset()
            msg = "Stopwatch reset to 00:00.00."
            return {"success": True, "status": "success", "message": msg, "response": msg}

    def lap_stopwatch(self, user_id: int = 1) -> Dict[str, Any]:
        """Records a lap split time."""
        with self._lock:
            sw = self._stopwatches.get(user_id)
            if not sw or not sw.is_running:
                return {"success": False, "status": "error", "message": "Cannot record lap while stopwatch is not running."}
            lap_data = sw.lap()
            msg = f"Lap {lap_data['lap_number']}: {lap_data['formatted']}."
            return {"success": True, "status": "success", "lap": lap_data, "message": msg, "response": msg}

    def get_stopwatch_status(self, user_id: int = 1) -> Dict[str, Any]:
        """Checks current stopwatch time."""
        with self._lock:
            sw = self._stopwatches.get(user_id)
            if not sw:
                return {"success": True, "status": "success", "elapsed_seconds": 0, "formatted": "00:00.00", "message": "Stopwatch is not active (00:00.00).", "response": "Stopwatch is not active."}
            elapsed = sw.get_elapsed()
            formatted = StopwatchItem.format_time(elapsed)
            state_str = "running" if sw.is_running else "paused"
            msg = f"Stopwatch is {state_str} at {formatted}."
            return {"success": True, "status": "success", "is_running": sw.is_running, "elapsed_seconds": elapsed, "formatted": formatted, "laps": list(sw.laps), "message": msg, "response": msg}

    # ── WORLD CLOCK & LOCAL TIME ──────────────────────────────────────────────

    def get_world_time(self, location_name: str) -> Dict[str, Any]:
        """Returns the current localized time and date for a global city or timezone."""
        if not location_name:
            return self.get_local_time()

        clean_loc = location_name.lower().strip().rstrip('?.!')
        tz_name = CITY_TIMEZONE_MAP.get(clean_loc)

        if not tz_name:
            # Check for partial city name in mapping
            for key, tz in CITY_TIMEZONE_MAP.items():
                if key in clean_loc or clean_loc in key:
                    tz_name = tz
                    break

        if not tz_name:
            try:
                # Try direct zoneinfo lookup
                zoneinfo.ZoneInfo(location_name)
                tz_name = location_name
            except Exception:
                tz_name = None

        if not tz_name:
            return {
                "success": False,
                "status": "error",
                "message": f"Could not find timezone information for '{location_name}'.",
                "response": f"I couldn't find timezone information for '{location_name}'."
            }

        try:
            tz = zoneinfo.ZoneInfo(tz_name)
            loc_dt = datetime.datetime.now(tz)
            time_str = loc_dt.strftime("%I:%M %p")
            date_str = loc_dt.strftime("%A, %B %d, %Y")
            display_name = location_name.title()
            msg = f"The current time in {display_name} is {time_str} ({date_str})."
            return {
                "success": True,
                "status": "success",
                "location": display_name,
                "timezone": tz_name,
                "time_str": time_str,
                "date_str": date_str,
                "iso": loc_dt.isoformat(),
                "message": msg,
                "response": msg
            }
        except Exception as e:
            logger.error(f"[CLOCK] World time lookup error: {e}")
            return {"success": False, "status": "error", "message": f"Failed to retrieve time for {location_name}: {e}"}

    def get_local_time(self) -> Dict[str, Any]:
        """Returns the local system time."""
        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p")
        msg = f"The current time is {time_str}."
        return {
            "success": True,
            "status": "success",
            "time_str": time_str,
            "iso": now.isoformat(),
            "message": msg,
            "response": msg
        }

    def get_local_date(self) -> Dict[str, Any]:
        """Returns the local system date."""
        now = datetime.datetime.now()
        date_str = now.strftime("%A, %B %d, %Y")
        msg = f"Today is {date_str}."
        return {
            "success": True,
            "status": "success",
            "date_str": date_str,
            "iso": now.isoformat(),
            "message": msg,
            "response": msg
        }

    # ── UNIFIED DISPATCH HANDLER ──────────────────────────────────────────────

    def handle_command(self, user_input: str, user_id: int = 1, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Unified command handler dispatching all clock and alarm actions."""
        p = params or {}
        action = p.get("action", "")
        text_low = user_input.lower().strip()

        # 1. Alarm Actions
        if action == "set_alarm" or "alarm" in text_low and any(k in text_low for k in ["set", "wake me up", "create", "put", "ring"]):
            time_target = p.get("time_text") or user_input
            return self.set_alarm(time_target, user_id=user_id, label=p.get("label"))
        elif action == "list_alarms" or "alarm" in text_low and any(k in text_low for k in ["show", "list", "check", "what", "view", "get"]):
            return self.list_alarms(user_id=user_id)
        elif action == "cancel_alarm" or "alarm" in text_low and any(k in text_low for k in ["cancel", "delete", "remove", "turn off", "stop", "dismiss"]):
            if any(k in text_low for k in ["stop", "dismiss", "turn off"]) and self._ringing_alarms:
                return self.dismiss_alarm(user_id=user_id)
            return self.cancel_alarm(query=user_input, user_id=user_id)
        elif action == "snooze_alarm" or "snooze" in text_low:
            mins = p.get("duration_minutes", 5)
            return self.snooze_alarm(duration_minutes=mins, user_id=user_id)

        # 2. Timer Actions
        elif action == "set_timer" or "timer" in text_low and any(k in text_low for k in ["set", "start", "create", "countdown"]):
            return self.set_timer(duration_text=p.get("duration") or user_input, user_id=user_id, label=p.get("label"))
        elif action == "list_timers" or "timer" in text_low and any(k in text_low for k in ["show", "list", "check", "how much time", "remaining"]):
            return self.list_timers(user_id=user_id)
        elif action == "cancel_timer" or "timer" in text_low and any(k in text_low for k in ["cancel", "stop", "reset", "delete"]):
            return self.cancel_timer(user_id=user_id)

        # 3. Stopwatch Actions
        elif action == "stopwatch_start" or (re.search(r'\bstopwatch\b', text_low) and any(re.search(rf'\b{k}\b', text_low) for k in ["start", "begin", "run", "resume"])):
            return self.start_stopwatch(user_id=user_id)
        elif action == "stopwatch_lap" or (re.search(r'\bstopwatch\b', text_low) and any(re.search(rf'\b{k}\b', text_low) for k in ["lap", "split"])):
            return self.lap_stopwatch(user_id=user_id)
        elif action == "stopwatch_stop" or (re.search(r'\bstopwatch\b', text_low) and any(re.search(rf'\b{k}\b', text_low) for k in ["stop", "pause", "halt"])):
            return self.stop_stopwatch(user_id=user_id)
        elif action == "stopwatch_reset" or (re.search(r'\bstopwatch\b', text_low) and "reset" in text_low):
            return self.reset_stopwatch(user_id=user_id)
        elif action == "stopwatch_status" or re.search(r'\bstopwatch\b', text_low):
            return self.get_stopwatch_status(user_id=user_id)

        # 4. World Clock Actions
        elif action == "world_time" or any(k in text_low for k in ["time in", "time at", "time of", "in tokyo", "in london", "in new york", "in paris", "in sydney", "in dubai"]):
            loc = p.get("location")
            if not loc:
                m = re.search(r'\b(?:in|at|for|of)\s+([a-zA-Z\s]+?)(?:\s+right\s+now|\s+today|\s+currently|\?|$)', user_input, re.IGNORECASE)
                loc = m.group(1).strip() if m else ""
            return self.get_world_time(loc)

        # 5. Date Actions
        elif action == "date_query" or any(k in text_low for k in ["what date", "what is the date", "today's date", "todays date", "what day is it", "what day is today"]):
            return self.get_local_date()

        # 6. Default Time Query
        else:
            return self.get_local_time()


def get_clock_controller() -> ClockController:
    """Singleton getter for ClockController."""
    return ClockController.get_instance()
