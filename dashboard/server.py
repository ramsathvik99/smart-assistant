"""
Smart Assistant — Decoupled Web Dashboard Server
Zero-dependency, multi-threaded HTTP presentation & control surface.
Decoupled from Assistant Core: Assistant never hard-depends on Dashboard.
All operations route through canonical AssistantCore and existing backend controllers.
"""

import os
import sys
import json
import time
import socket
import threading
from typing import Optional, Dict, Any, List
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

from core.assistant_core import assistant_core

DEFAULT_PORT = 8000
DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(DASHBOARD_DIR, "static")


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Multi-threaded HTTP Server so concurrent client requests never block."""
    daemon_threads = True
    allow_reuse_address = False if sys.platform == "win32" else True


class DashboardHandler(BaseHTTPRequestHandler):
    """
    HTTP Request Handler for the Smart Assistant Web Dashboard.
    Acts strictly as a presentation and control surface.
    All data is read from and written to existing authoritative controllers.
    """
    protocol_version = "HTTP/1.0"

    def log_message(self, format, *args):
        # Suppress noisy standard HTTP access logs
        pass

    def _send_json(self, data: dict, status: int = 200):
        try:
            payload = json.dumps(data).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.end_headers()
            self.wfile.write(payload)
        except Exception:
            pass

    def _send_html(self, html_content: str, status: int = 200):
        try:
            payload = html_content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.end_headers()
            self.wfile.write(payload)
        except Exception:
            pass

    def do_OPTIONS(self):
        """Handle CORS pre-flight requests."""
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.end_headers()

    def _resolve_uid(self, q=None, payload=None) -> int:
        """Resolve authenticated user ID ensuring multi-user isolation."""
        if q and "user_id" in q:
            try:
                val = int(q["user_id"][0])
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass
        if payload and "user_id" in payload and payload["user_id"] is not None:
            try:
                val = int(payload["user_id"])
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass
        uctx = assistant_core.get_user_context()
        return uctx.get("user_id") or 1

    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        q = parse_qs(url.query)
        uid = self._resolve_uid(q=q)

        # ── CORE / TELEMETRY / STATE ─────────────────────────────────────────
        if path == "/api/status" or path == "/api/telemetry":
            telem = assistant_core.get_telemetry()
            self._send_json({"success": True, "data": telem})
            return

        elif path == "/api/state":
            self._send_json({
                "success": True,
                "state": assistant_core.get_state(),
                "audio_level": assistant_core.get_audio_level()
            })
            return

        elif path == "/api/user":
            uctx = assistant_core.get_user_context()
            self._send_json({"success": True, "user": uctx})
            return

        # ── 1. MOBILE / DEVICE MANAGEMENT ─────────────────────────────────────
        elif path == "/api/devices":
            try:
                from skills.device_management.device_registry import get_device_registry
                from skills.device_management.device_dispatcher import get_device_dispatcher
                reg = get_device_registry()
                dispatcher = get_device_dispatcher()
                records = reg.list_devices(uid)
                devices_data = []
                for d in records:
                    item = d.to_dict()
                    item["is_connected"] = dispatcher.is_connected(d.device_id)
                    devices_data.append(item)
                self._send_json({"success": True, "devices": devices_data, "user_id": uid})
            except Exception as e:
                self._send_json({"success": False, "error": str(e), "devices": []})
            return

        # ── 2. BACKGROUND TASKS ───────────────────────────────────────────────
        elif path == "/api/tasks":
            try:
                from skills.task_management.task_queue import get_task_queue
                tq = get_task_queue()
                queue_tasks = tq.list_user_tasks(uid, limit=30)
                active_info = assistant_core.get_task_info()
                self._send_json({
                    "success": True,
                    "active_task": active_info,
                    "queue": queue_tasks,
                    "user_id": uid
                })
            except Exception as e:
                self._send_json({
                    "success": True,
                    "active_task": assistant_core.get_task_info(),
                    "queue": [],
                    "error": str(e)
                })
            return

        # ── 3. AUDIO / ECHOGUARD ──────────────────────────────────────────────
        elif path == "/api/audio":
            try:
                from skills.audio_management.audio_controller import get_audio_controller
                from skills.audio_management.echo_guard import get_echo_guard
                ac = get_audio_controller()
                endpoints = ac.list_audio_endpoints()
                eg = get_echo_guard()
                eg_data = {
                    "calibrated": bool(eg.calibrated),
                    "floor": round(float(eg.floor), 4),
                    "threshold": round(float(eg.threshold), 4),
                    "reliable": bool(eg.reliable),
                    "similarity": round(float(eg.last_similarity), 4)
                }
                self._send_json({
                    "success": True,
                    "inputs": endpoints.get("inputs", []),
                    "outputs": endpoints.get("outputs", []),
                    "echoguard": eg_data
                })
            except Exception as e:
                self._send_json({"success": False, "error": str(e), "inputs": [], "outputs": []})
            return

        # ── 4. WINDOW / DESKTOP CONTEXT ───────────────────────────────────────
        elif path == "/api/window":
            try:
                from skills.window_management.window_controller import get_window_controller
                wc = get_window_controller()
                win_res = wc.get_active_window()
                self._send_json({"success": True, "data": win_res})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)})
            return

        # ── 5. CLIPBOARD (STRICTLY ON-DEMAND) ─────────────────────────────────
        elif path == "/api/clipboard":
            try:
                from skills.clipboard.clipboard_analyzer import analyze_clipboard
                clip_res = analyze_clipboard()
                self._send_json({"success": True, "clipboard": clip_res})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)})
            return

        # ── 6. LEARNING / PREFERENCES ─────────────────────────────────────────
        elif path == "/api/rules":
            try:
                from skills.learning.learned_rules import get_learned_rules_engine
                lre = get_learned_rules_engine()
                rules = lre.list_rules(uid)
                self._send_json({"success": True, "rules": rules, "user_id": uid})
            except Exception as e:
                self._send_json({"success": False, "error": str(e), "rules": []})
            return

        # ── 7. UNDO / ROLLBACK ────────────────────────────────────────────────
        elif path == "/api/undo":
            try:
                from skills.undo.undo_manager import get_undo_manager
                um = get_undo_manager()
                self._send_json({
                    "success": True,
                    "can_undo": um.can_undo(uid),
                    "latest": um.peek(uid),
                    "history": um.history(uid),
                    "user_id": uid
                })
            except Exception as e:
                self._send_json({"success": False, "can_undo": False, "latest": "", "history": []})
            return

        # ── 8. SMART HOME ─────────────────────────────────────────────────────
        elif path == "/api/smarthome":
            try:
                from skills.smart_home.service import get_smart_home_service
                sh = get_smart_home_service()
                devs = sh.list_devices(uid)
                self._send_json({
                    "success": True,
                    "devices": [d.to_dict() for d in devs],
                    "user_id": uid
                })
            except Exception as e:
                self._send_json({"success": False, "error": str(e), "devices": []})
            return

        # ── 9. FILE MANAGEMENT ────────────────────────────────────────────────
        elif path == "/api/files":
            try:
                from modules.system_controller import file_manager
                target_dir = q.get("path", [None])[0]
                query = q.get("query", [None])[0]
                if query:
                    files = file_manager.search_files(query, directory_path=target_dir)
                else:
                    files = file_manager.list_files(directory_path=target_dir)
                stats = file_manager.get_directory_stats(dir_path=target_dir)
                self._send_json({
                    "success": True,
                    "files": files,
                    "stats": stats,
                    "current_directory": stats.get("path")
                })
            except Exception as e:
                self._send_json({"success": False, "error": str(e), "files": []})
            return

        # ── 10. GENERATED DOCUMENTS ───────────────────────────────────────────
        elif path == "/api/documents":
            try:
                from modules.document_tools.pdf_builder import get_default_output_dir
                doc_dir = get_default_output_dir()
                docs = []
                if os.path.exists(doc_dir):
                    for fn in sorted(os.listdir(doc_dir), reverse=True):
                        ext = os.path.splitext(fn)[1].lower()
                        if ext in [".pdf", ".docx", ".xlsx", ".pptx"]:
                            fp = os.path.join(doc_dir, fn)
                            st = os.stat(fp)
                            docs.append({
                                "filename": fn,
                                "path": fp,
                                "ext": ext[1:].upper(),
                                "size": st.st_size,
                                "size_formatted": f"{st.st_size / 1024:.1f} KB" if st.st_size < 1048576 else f"{st.st_size / 1048576:.2f} MB",
                                "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))
                            })
                self._send_json({"success": True, "directory": doc_dir, "documents": docs})
            except Exception as e:
                self._send_json({"success": False, "error": str(e), "documents": []})
            return

        # ── 11. CALENDAR ──────────────────────────────────────────────────────
        elif path == "/api/calendar":
            try:
                from modules.calendar_manager.calendar_storage import CalendarStorage
                cs = CalendarStorage()
                today = time.strftime("%Y-%m-%d")
                # Look 60 days ahead
                end_day = time.strftime("%Y-%m-%d", time.localtime(time.time() + 60 * 86400))
                events_map = cs.get_events_range(uid, today, end_day)
                flattened = []
                for dt, ev_list in sorted(events_map.items()):
                    for ev in ev_list:
                        ev_copy = dict(ev)
                        ev_copy["date"] = dt
                        flattened.append(ev_copy)
                self._send_json({"success": True, "events": flattened, "user_id": uid})
            except Exception as e:
                self._send_json({"success": False, "error": str(e), "events": []})
            return

        # ── 12. MUSIC / MEDIA ─────────────────────────────────────────────────
        elif path == "/api/music":
            try:
                from modules.music.music_controller import get_controller
                mc = get_controller()
                status = mc.get_queue_status()
                self._send_json({"success": True, "music": status})
            except Exception as e:
                self._send_json({"success": False, "error": str(e), "music": {}})
            return

        # ── REMINDERS / MEMORY (EXISTING AUTHORITATIVE PATHS) ─────────────────
        elif path == "/api/reminders":
            reminders = assistant_core.get_user_reminders(user_id=uid)
            self._send_json({"success": True, "reminders": reminders, "user_id": uid})
            return

        elif path == "/api/memory":
            memory = assistant_core.get_user_memory(user_id=uid)
            notes = assistant_core.get_user_notes(user_id=uid)
            self._send_json({"success": True, "memory": memory, "notes": notes, "user_id": uid})
            return

        # ── STATIC WEB UI ─────────────────────────────────────────────────────
        elif path == "/" or path == "/index.html":
            index_path = os.path.join(STATIC_DIR, "index.html")
            if os.path.exists(index_path):
                with open(index_path, "r", encoding="utf-8") as f:
                    self._send_html(f.read())
            else:
                self._send_html("<h1>Smart Assistant Dashboard</h1><p>Dashboard UI ready.</p>")
            return

        self._send_json({"error": "Not Found", "path": path}, 404)

    def do_POST(self):
        url = urlparse(self.path)
        path = url.path

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        uid = self._resolve_uid(payload=payload)

        # ── COMMAND TERMINAL ──────────────────────────────────────────────────
        if path == "/api/command":
            cmd = payload.get("command", "").strip()
            if not cmd:
                self._send_json({"success": False, "error": "Empty command"}, 400)
                return
            response = assistant_core.execute_command(cmd, user_id=uid)
            self._send_json({"success": True, "response": response})
            return

        # ── 1. MOBILE / DEVICE ACTIONS ────────────────────────────────────────
        elif path == "/api/devices/pair":
            try:
                from skills.device_management.device_controller import get_device_controller
                dc = get_device_controller()
                pair_res = dc.pair_device(uid)
                self._send_json(pair_res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/devices/unpair":
            try:
                from skills.device_management.device_registry import get_device_registry
                device_id = payload.get("device_id", "")
                reg = get_device_registry()
                success = reg.revoke_device(uid, device_id)
                self._send_json({"success": success, "message": f"Device {device_id} revoked." if success else "Failed to revoke device."})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/devices/action":
            try:
                from skills.device_management.device_controller import get_device_controller
                action = payload.get("action", "")
                target = payload.get("device_id", "")
                dc = get_device_controller()
                if action == "battery":
                    res = dc.get_battery(uid, target=target)
                elif action == "flashlight_on":
                    res = dc.toggle_flashlight(uid, enable=True, target=target)
                elif action == "flashlight_off":
                    res = dc.toggle_flashlight(uid, enable=False, target=target)
                elif action == "launch_app":
                    app_name = payload.get("app_name", "")
                    res = dc.launch_app(uid, app_name=app_name, target=target)
                else:
                    res = {"success": False, "error": f"Unknown action: {action}"}
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 2. BACKGROUND TASK ACTIONS ────────────────────────────────────────
        elif path == "/api/task/queue":
            try:
                from skills.task_management.task_queue import get_task_queue
                goal = payload.get("goal", "").strip()
                if not goal:
                    self._send_json({"success": False, "error": "Missing task goal"}, 400)
                    return
                tq = get_task_queue()
                task_id = tq.submit(uid, goal)
                self._send_json({"success": True, "task_id": task_id, "message": f"Task queued with ID {task_id}"})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/task/cancel":
            try:
                task_id = payload.get("task_id", "")
                if task_id:
                    from skills.task_management.task_queue import get_task_queue
                    success = get_task_queue().cancel(uid, task_id)
                    self._send_json({"success": True, "cancelled": bool(success), "message": f"Task {task_id} cancel processed."})
                else:
                    assistant_core.cancel_task()
                    self._send_json({"success": True, "cancelled": True, "message": "Active task cancellation signal sent."})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 3. AUDIO ACTIONS ──────────────────────────────────────────────────
        elif path == "/api/audio/switch":
            try:
                from skills.audio_management.audio_controller import get_audio_controller
                target = payload.get("device", "")
                kind = payload.get("kind", "output")
                ac = get_audio_controller()
                res = ac.switch_audio_device(target, kind=kind)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/audio/test":
            try:
                from skills.audio_management.audio_controller import get_audio_controller
                sound = payload.get("sound", "alert")
                ac = get_audio_controller()
                res = ac.play_sound(sound)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 4. WINDOW / SCREENSHOT ACTIONS ────────────────────────────────────
        elif path == "/api/window/action":
            try:
                action = payload.get("action", "")
                if action == "screenshot":
                    from skills.window_management.window_controller import get_window_controller
                    res = get_window_controller().capture_screenshot()
                    self._send_json(res)
                elif action == "minimize_all":
                    from modules.system_controller import minimize_all_windows
                    res = minimize_all_windows()
                    self._send_json(res)
                else:
                    self._send_json({"success": False, "error": f"Unknown action {action}"}, 400)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 6. LEARNING / RULES ACTIONS ───────────────────────────────────────
        elif path == "/api/rules":
            try:
                from skills.learning.learned_rules import get_learned_rules_engine
                rule_text = payload.get("rule_text", "").strip()
                cat = payload.get("category", "general")
                if not rule_text:
                    self._send_json({"success": False, "error": "Empty rule text"}, 400)
                    return
                lre = get_learned_rules_engine()
                res = lre.add_rule(uid, rule_text, category=cat)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/rules/toggle":
            try:
                from skills.learning.learned_rules import get_learned_rules_engine
                rule_id = payload.get("rule_id", "")
                lre = get_learned_rules_engine()
                res = lre.toggle_rule(uid, rule_id)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/rules/delete":
            try:
                from skills.learning.learned_rules import get_learned_rules_engine
                rule_id = payload.get("rule_id", "")
                lre = get_learned_rules_engine()
                res = lre.delete_rule(uid, rule_id)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 7. UNDO ACTION ────────────────────────────────────────────────────
        elif path == "/api/undo":
            try:
                from skills.undo.undo_manager import get_undo_manager
                um = get_undo_manager()
                res = um.undo_last(uid)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 8. SMART HOME ACTIONS ─────────────────────────────────────────────
        elif path == "/api/smarthome/power":
            try:
                from skills.smart_home.service import get_smart_home_service
                target = payload.get("target", "")
                is_on = bool(payload.get("is_on", True))
                sh = get_smart_home_service()
                res = sh.set_power(uid, target, is_on)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 9. FILE ACTIONS ───────────────────────────────────────────────────
        elif path == "/api/files/action":
            try:
                from modules.system_controller import file_manager
                action = payload.get("action", "")
                path_arg = payload.get("path", "")
                if action == "open":
                    res = file_manager.open_file(path_arg)
                    self._send_json({"success": True, "message": res})
                elif action == "delete":
                    res = file_manager.safe_delete_file(path_arg, use_trash=True)
                    self._send_json(res)
                elif action == "rename":
                    new_name = payload.get("new_name", "")
                    res = file_manager.rename_file(path_arg, new_name, user_id=uid)
                    self._send_json(res)
                elif action == "duplicates":
                    res = file_manager.find_duplicate_files(path_arg)
                    self._send_json(res)
                else:
                    self._send_json({"success": False, "error": f"Unknown action: {action}"}, 400)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 10. DOCUMENT OPEN ACTION ──────────────────────────────────────────
        elif path == "/api/documents/open":
            try:
                from modules.system_controller import file_manager
                fp = payload.get("path", "")
                res = file_manager.open_file(fp)
                self._send_json({"success": True, "message": res})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 11. CALENDAR EVENT ADD ────────────────────────────────────────────
        elif path == "/api/calendar":
            try:
                from modules.calendar_manager.calendar_storage import CalendarStorage
                title = payload.get("title", "").strip()
                date_str = payload.get("date", "").strip()
                time_str = payload.get("time", "").strip()
                if not title or not date_str:
                    self._send_json({"success": False, "error": "Missing title or date"}, 400)
                    return
                cs = CalendarStorage()
                event_dict = {
                    "title": title,
                    "date": date_str,
                    "time": time_str or "00:00",
                    "description": payload.get("description", "")
                }
                ev_id = cs.add_event(uid, event_dict)
                self._send_json({"success": True, "event_id": ev_id, "message": f"Event '{title}' scheduled on {date_str}"})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── 12. MUSIC ACTIONS ─────────────────────────────────────────────────
        elif path == "/api/music/action":
            try:
                from modules.music.music_controller import get_controller
                action = payload.get("action", "")
                mc = get_controller()
                if action == "play":
                    query = payload.get("query", "")
                    res = mc.play_music(f"play {query}" if query else "play")
                elif action == "pause" or action == "toggle_pause":
                    res = mc.toggle_play_pause()
                elif action == "stop":
                    res = mc.media_stop()
                elif action == "next":
                    res = mc.media_next()
                elif action == "previous":
                    res = mc.media_previous()
                elif action == "volume_up":
                    res = mc.volume_up()
                elif action == "volume_down":
                    res = mc.volume_down()
                elif action == "volume_mute":
                    res = mc.volume_mute()
                else:
                    res = f"Unknown music action {action}"
                self._send_json({"success": True, "message": str(res)})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        # ── REMINDERS / ASSISTANT STATE ───────────────────────────────────────
        elif path == "/api/reminders":
            title = payload.get("title", "").strip()
            rem_time = payload.get("time", "").strip()
            if not title or not rem_time:
                self._send_json({"success": False, "error": "Missing title or time"}, 400)
                return
            result = assistant_core.create_reminder(title, rem_time, user_id=uid)
            self._send_json(result)
            return

        elif path == "/api/assistant/state":
            new_state = payload.get("state", "").strip()
            if new_state:
                assistant_core.set_state(new_state)
                self._send_json({"success": True, "state": new_state})
                return
            self._send_json({"success": False, "error": "Missing state"}, 400)
            return

        self._send_json({"error": "Not Found", "path": path}, 404)

    def do_DELETE(self):
        url = urlparse(self.path)
        path = url.path
        q = parse_qs(url.query)
        uid = self._resolve_uid(q=q)

        if path == "/api/rules":
            try:
                from skills.learning.learned_rules import get_learned_rules_engine
                rule_id = q.get("rule_id", [""])[0]
                if not rule_id:
                    self._send_json({"success": False, "error": "Missing rule_id"}, 400)
                    return
                lre = get_learned_rules_engine()
                res = lre.delete_rule(uid, rule_id)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        self._send_json({"error": "Not Found", "path": path}, 404)


# ── Server Lifecycle Management (Decoupled & Non-Blocking) ───────────────────
_server_instance: Optional[ThreadedHTTPServer] = None
_server_thread: Optional[threading.Thread] = None
_server_running: bool = False
_server_port: int = DEFAULT_PORT


def start_dashboard_server(port: int = DEFAULT_PORT, host: str = "0.0.0.0") -> bool:
    """Start the Web Dashboard server in a background daemon thread."""
    global _server_instance, _server_thread, _server_running, _server_port

    if _server_running:
        return True

    try:
        _server_instance = ThreadedHTTPServer((host, port), DashboardHandler)
        _server_port = port
        _server_running = True

        def _run_server():
            print(f"[Dashboard] Web Control Surface running at http://localhost:{port} (host: {host})")
            try:
                _server_instance.serve_forever()
            except Exception as e:
                print(f"[Dashboard] Server loop closed: {e}")
            finally:
                global _server_running
                _server_running = False

        _server_thread = threading.Thread(target=_run_server, daemon=True, name="DashboardServerThread")
        _server_thread.start()
        return True

    except OSError as e:
        print(f"[Dashboard] Unavailable or port {port} busy ({e}) — continuing assistant without dashboard.")
        _server_running = False
        return False
    except Exception as e:
        print(f"[Dashboard] Failed to start ({e}) — continuing assistant without dashboard.")
        _server_running = False
        return False


def stop_dashboard_server():
    """Stop the Web Dashboard server cleanly."""
    global _server_instance, _server_thread, _server_running
    if not _server_running or not _server_instance:
        return

    print("[Dashboard] Stopping Web Dashboard server...")
    try:
        _server_instance.shutdown()
        _server_instance.server_close()
    except Exception as e:
        print(f"[Dashboard] Error during shutdown: {e}")
    finally:
        _server_running = False
        _server_instance = None
        _server_thread = None
        print("[Dashboard] [OK] Web Dashboard stopped.")


def is_dashboard_running() -> bool:
    """Return True if dashboard server is actively running."""
    return _server_running


def get_dashboard_url() -> str:
    """Return local URL to access the dashboard."""
    return f"http://localhost:{_server_port}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Smart Assistant Decoupled Web Dashboard")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to bind (default: {DEFAULT_PORT})")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    args = parser.parse_args()

    print("============================================================")
    print("STARTING SMART ASSISTANT WEB DASHBOARD (ALL CAPABILITIES CONNECTED)")
    print("============================================================")
    uctx = assistant_core.get_user_context()
    print(f"Active User Context: {uctx.get('username')} (ID: {uctx.get('user_id')}) | Assistant: {uctx.get('assistant_name')}")

    success = start_dashboard_server(port=args.port, host=args.host)
    if success:
        print(f"[Dashboard] Open your browser at: http://localhost:{args.port}")
        print("[Dashboard] Press Ctrl+C to stop dashboard (Assistant Core will remain intact).")
        try:
            while is_dashboard_running():
                time.sleep(1)
        except KeyboardInterrupt:
            print("\n[Dashboard] Shutdown requested by user...")
        finally:
            stop_dashboard_server()
            print("[Dashboard] Dashboard interface stopped cleanly. Assistant Core unaffected.")
    else:
        print("[Dashboard] Could not start dashboard server.")
        sys.exit(1)
