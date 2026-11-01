"""

Smart Assistant — Production Multi-User Backend & Web Dashboard Server

Zero-dependency, multi-threaded HTTP presentation, control surface & REST API.

Enforces Bearer token authentication, strict multi-user data isolation,

ChatGPT-style memory retrieval, GDPR data export/deletion, and privacy-preserving observability.

"""



import os

import sys

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import json

import time

import socket

import threading

from typing import Optional, Dict, Any, List

from urllib.parse import urlparse, parse_qs

from http.server import HTTPServer, BaseHTTPRequestHandler

from socketserver import ThreadingMixIn



from core.assistant_core import assistant_core

from core.db_pool import get_db_pool

from core.auth_service import (

    register_user as auth_signup,

    authenticate_user_credentials,

    change_user_password,

    revoke_token,

    verify_token

)

from core.user_isolation import (

    extract_authenticated_user,

    enforce_ownership,

    export_user_data,

    delete_user_account_cascading,

    AuthorizationError

)

from core.chatgpt_memory import get_chatgpt_memory

from core.admin_metrics import get_admin_metrics

from core.migration_runner import run_migrations



DEFAULT_PORT = 8000

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))

STATIC_DIR = os.path.join(DASHBOARD_DIR, "static")



# Configurable CORS allowed origins (default to localhost/127.0.0.1)

_RAW_CORS = os.getenv("CORS_ALLOWED_ORIGINS", "")

CORS_ALLOWED_ORIGINS = [o.strip() for o in _RAW_CORS.split(",") if o.strip()]

if not CORS_ALLOWED_ORIGINS:

    CORS_ALLOWED_ORIGINS = [

        "http://localhost:8000",

        "http://127.0.0.1:8000",

        "http://localhost:3000",

        "http://127.0.0.1:3000",

        "http://localhost:5173",

        "http://127.0.0.1:5173",

    ]



PUBLIC_PATHS = {

    "/api/health", "/health", "/api/admin/metrics", "/api/status", "/api/telemetry", "/api/state",

    "/api/auth/signup", "/api/auth/login", "/api/auth/check-username", "/api/credentials/validate",

    "/", "/index.html",

    "/companion", "/api/devices/enroll", "/api/devices/heartbeat",

    "/api/devices/location", "/api/devices/commands", "/api/devices/result",

    "/api/devices/enrollment-code"

}





_COMPANION_PWA_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
<title>Assistant Mobile Companion</title>
<style>
  :root {
    --bg: #0b0f19;
    --card: #151d2f;
    --border: #232f48;
    --text: #e2e8f0;
    --muted: #8899b5;
    --primary: #00e5ff;
    --success: #10b981;
    --warning: #f59e0b;
    --danger: #ef4444;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    padding: 16px;
    max-width: 480px;
    margin: 0 auto;
    min-height: 100vh;
  }
  .header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: 16px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 20px;
  }
  .logo { font-size: 1.15rem; font-weight: 700; color: var(--primary); }
  .badge {
    padding: 4px 10px;
    border-radius: 9999px;
    font-size: 0.75rem;
    font-weight: 600;
    background: #1f293d;
    color: var(--muted);
  }
  .badge.connected { background: rgba(16, 185, 129, 0.2); color: var(--success); border: 1px solid var(--success); }
  .badge.disconnected { background: rgba(239, 68, 68, 0.2); color: var(--danger); border: 1px solid var(--danger); }
  .card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 18px;
    margin-bottom: 16px;
  }
  .card-title {
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--muted);
    margin-bottom: 12px;
  }
  input[type="text"] {
    width: 100%;
    padding: 12px 14px;
    background: #0b0f19;
    border: 1px solid var(--border);
    border-radius: 8px;
    color: var(--text);
    font-size: 1rem;
    font-family: monospace;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 12px;
  }
  input[type="text"]:focus {
    outline: none;
    border-color: var(--primary);
  }
  button {
    width: 100%;
    padding: 12px;
    border-radius: 8px;
    border: none;
    font-size: 0.95rem;
    font-weight: 600;
    cursor: pointer;
    background: var(--primary);
    color: #0b0f19;
    transition: opacity 0.2s;
  }
  button:active { opacity: 0.8; }
  button.danger { background: #374151; color: var(--danger); margin-top: 8px; }
  .stat-row {
    display: flex;
    justify-content: space-between;
    padding: 8px 0;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05);
    font-size: 0.9rem;
  }
  .stat-row:last-child { border-bottom: none; }
  .stat-label { color: var(--muted); }
  .stat-value { font-weight: 600; font-family: monospace; }
  .log-box {
    background: #0b0f19;
    border-radius: 8px;
    padding: 10px;
    font-family: monospace;
    font-size: 0.75rem;
    color: #94a3b8;
    max-height: 120px;
    overflow-y: auto;
  }
</style>
</head>
<body>
  <div class="header">
    <div class="logo">⚡ Assistant Companion</div>
    <span id="connBadge" class="badge disconnected">Disconnected</span>
  </div>

  <div id="enrollCard" class="card">
    <div class="card-title">Device Enrollment</div>
    <p style="font-size:0.85rem;color:var(--muted);margin-bottom:12px;">
      Enter the 16-character code shown on your laptop dashboard:
    </p>
    <input type="text" id="enrollCode" placeholder="XXXX-XXXX-XXXX-XXXX" maxlength="19" />
    <input type="text" id="deviceName" placeholder="Device Name (e.g. Redmi Note 12)" style="font-family:inherit;text-transform:none;" value="Redmi Note 12 5G" />
    <button id="enrollBtn" onclick="doEnroll()">Enroll Device</button>
  </div>

  <div id="statusCard" class="card" style="display:none;">
    <div class="card-title">Live Telemetry & Status</div>
    <div class="stat-row">
      <span class="stat-label">Device</span>
      <span id="dispDevice" class="stat-value">-</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Battery</span>
      <span id="dispBattery" class="stat-value">-</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">GPS Location</span>
      <span id="dispLocation" class="stat-value">Acquiring...</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Accuracy</span>
      <span id="dispAccuracy" class="stat-value">-</span>
    </div>
    <div class="stat-row">
      <span class="stat-label">Heartbeat</span>
      <span id="dispHeartbeat" class="stat-value">Never</span>
    </div>
    <button class="danger" onclick="doUnlink()">Unlink Device</button>
  </div>

  <div class="card">
    <div class="card-title">Remote Event Log</div>
    <div id="logBox" class="log-box">Ready.</div>
  </div>

<script>
let deviceId = localStorage.getItem('asst_device_id') || '';
let authToken = localStorage.getItem('asst_auth_token') || '';
let stableId = localStorage.getItem('asst_stable_id') || '';

function log(msg) {
  const box = document.getElementById('logBox');
  const d = new Date().toLocaleTimeString();
  box.innerHTML = `[${d}] ${msg}<br>` + box.innerHTML;
}

if (!stableId) {
  stableId = 'web_' + Math.random().toString(36).substring(2, 12) + '_' + Date.now();
  localStorage.setItem('asst_stable_id', stableId);
}

const codeInput = document.getElementById('enrollCode');
codeInput.addEventListener('input', (e) => {
  let val = e.target.value.replace(/[^A-Za-z0-9]/g, '').toUpperCase();
  let parts = [];
  for (let i = 0; i < val.length && i < 16; i += 4) {
    parts.push(val.substring(i, i + 4));
  }
  e.target.value = parts.join('-');
});

async function doEnroll() {
  const code = codeInput.value.trim();
  const name = document.getElementById('deviceName').value.trim() || 'Mobile Android';
  if (code.replace(/-/g, '').length < 16) {
    alert('Please enter a valid 16-character code.');
    return;
  }
  log('Submitting enrollment code...');
  try {
    const res = await fetch('/api/devices/enroll', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        enrollment_code: code,
        device_name: name,
        stable_identity: stableId,
        platform: 'android',
        os_version: '14'
      })
    });
    const data = await res.json();
    if (data.success && data.auth_token) {
      deviceId = data.device_id;
      authToken = data.auth_token;
      localStorage.setItem('asst_device_id', deviceId);
      localStorage.setItem('asst_auth_token', authToken);
      log('Enrolled successfully! ID: ' + deviceId);
      updateUI();
      startLoops();
    } else {
      alert('Enrollment failed: ' + (data.error || 'Invalid code'));
      log('Enrollment failed: ' + (data.error || 'Unknown error'));
    }
  } catch (err) {
    alert('Network error: ' + err.message);
    log('Network error: ' + err.message);
  }
}

function doUnlink() {
  if (confirm('Unlink this device from the assistant?')) {
    localStorage.removeItem('asst_device_id');
    localStorage.removeItem('asst_auth_token');
    deviceId = '';
    authToken = '';
    updateUI();
    location.reload();
  }
}

function updateUI() {
  const badge = document.getElementById('connBadge');
  const enrollCard = document.getElementById('enrollCard');
  const statusCard = document.getElementById('statusCard');
  if (authToken && deviceId) {
    badge.className = 'badge connected';
    badge.innerText = 'Connected';
    enrollCard.style.display = 'none';
    statusCard.style.display = 'block';
    document.getElementById('dispDevice').innerText = deviceId;
  } else {
    badge.className = 'badge disconnected';
    badge.innerText = 'Disconnected';
    enrollCard.style.display = 'block';
    statusCard.style.display = 'none';
  }
}

async function sendHeartbeat() {
  if (!authToken) return;
  let batteryLevel = null;
  let isCharging = false;
  if (navigator.getBattery) {
    try {
      const b = await navigator.getBattery();
      batteryLevel = Math.round(b.level * 100);
      isCharging = b.charging;
      document.getElementById('dispBattery').innerText = `${batteryLevel}% ${isCharging ? '⚡' : ''}`;
    } catch (_) {}
  }
  try {
    const res = await fetch('/api/devices/heartbeat', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + authToken
      },
      body: JSON.stringify({
        battery: batteryLevel,
        charging: isCharging,
        network_info: {
          online: navigator.onLine,
          connection_type: (navigator.connection && navigator.connection.effectiveType) || 'cellular'
        }
      })
    });
    if (res.ok) {
      document.getElementById('dispHeartbeat').innerText = new Date().toLocaleTimeString();
    } else if (res.status === 401) {
      log('Token rejected. Re-enrollment required.');
      doUnlink();
    }
  } catch (err) {}
}

function startLocationReporting() {
  if (!navigator.geolocation) return;
  navigator.geolocation.watchPosition(
    async (pos) => {
      const lat = pos.coords.latitude;
      const lon = pos.coords.longitude;
      const acc = Math.round(pos.coords.accuracy);
      document.getElementById('dispLocation').innerText = `${lat.toFixed(4)}, ${lon.toFixed(4)}`;
      document.getElementById('dispAccuracy').innerText = `±${acc}m`;
      if (!authToken) return;
      try {
        await fetch('/api/devices/location', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + authToken
          },
          body: JSON.stringify({
            latitude: lat,
            longitude: lon,
            accuracy_m: acc,
            altitude_m: pos.coords.altitude,
            provider: 'gps'
          })
        });
      } catch (_) {}
    },
    (err) => {
      document.getElementById('dispLocation').innerText = 'GPS denied/unavailable';
    },
    { enableHighAccuracy: true, maximumAge: 10000, timeout: 15000 }
  );
}

async function pollCommands() {
  if (!authToken || !deviceId) return;
  try {
    const res = await fetch(`/api/devices/commands?device_id=${encodeURIComponent(deviceId)}`, {
      headers: { 'Authorization': 'Bearer ' + authToken }
    });
    if (res.ok) {
      const data = await res.json();
      if (data.commands && data.commands.length > 0) {
        for (const cmd of data.commands) {
          log(`Command received: ${cmd.action} (${cmd.request_id.substring(0, 8)})`);
          executeCommand(cmd);
        }
      }
    }
  } catch (_) {}
}

async function executeCommand(cmd) {
  let result = { executed: true, timestamp: Date.now() };
  if (cmd.action === 'beep' || cmd.action === 'alarm') {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(880, ctx.currentTime);
      osc.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 1.5);
      result.sound = 'played';
    } catch (e) { result.sound_error = e.message; }
  } else if (cmd.action === 'vibrate' && navigator.vibrate) {
    navigator.vibrate([300, 150, 300]);
    result.vibrated = true;
  }
  try {
    await fetch('/api/devices/result', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + authToken
      },
      body: JSON.stringify({
        request_id: cmd.request_id,
        result: result
      })
    });
  } catch (_) {}
}

function startLoops() {
  sendHeartbeat();
  startLocationReporting();
  setInterval(sendHeartbeat, 20000);
  setInterval(pollCommands, 3000);
}

updateUI();
if (authToken && deviceId) {
  startLoops();
}
</script>
</body>
</html>
"""


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):

    """Multi-threaded HTTP Server so concurrent client requests never block."""

    daemon_threads = True

    allow_reuse_address = False if sys.platform == "win32" else True





class DashboardHandler(BaseHTTPRequestHandler):

    """

    HTTP Request Handler for the Smart Assistant Web Dashboard & Production REST API.

    Acts strictly as an authenticated presentation and control surface.

    """

    protocol_version = "HTTP/1.0"



    def log_message(self, format, *args):

        # Suppress noisy standard HTTP access logs

        pass



    def _get_cors_origin(self) -> Optional[str]:

        origin = self.headers.get("Origin")

        if not origin:

            return None

        clean_origin = origin.rstrip("/")

        for allowed in CORS_ALLOWED_ORIGINS:

            if clean_origin == allowed.rstrip("/"):

                return origin

        app_env = os.getenv("APP_ENV", "development").lower()

        if app_env == "development":

            if clean_origin.startswith("http://localhost:") or clean_origin.startswith("http://127.0.0.1:"):

                return origin

        return None



    def _set_cors_headers(self):

        cors_origin = self._get_cors_origin()

        if cors_origin:

            self.send_header("Access-Control-Allow-Origin", cors_origin)

            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

            self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")

            self.send_header("Vary", "Origin")



    def _send_json(self, data: dict, status: int = 200):

        try:

            payload = json.dumps(data).encode("utf-8")

            self.send_response(status)

            self.send_header("Content-Type", "application/json; charset=utf-8")

            self.send_header("Content-Length", str(len(payload)))

            self._set_cors_headers()

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

            self._set_cors_headers()

            self.end_headers()

            self.wfile.write(payload)

        except Exception:

            pass



    def do_OPTIONS(self):

        """Handle CORS pre-flight requests."""

        cors_origin = self._get_cors_origin()

        if cors_origin:

            self.send_response(204)

            self._set_cors_headers()

            self.end_headers()

        else:

            self.send_response(403)

            self.end_headers()



    def _get_auth_user(self) -> Optional[Dict[str, Any]]:

        """Extract and verify authenticated user from Authorization header."""

        auth_header = self.headers.get("Authorization")

        if auth_header:

            user_data = extract_authenticated_user(auth_header)

            if user_data:

                return user_data

        return None



    def _resolve_uid(self, q=None, payload=None) -> int:

        """

        Resolve authenticated user ID ensuring multi-user isolation.

        Strict precedence:

        1. Verified Bearer token (cannot be forged or spoofed)

           - If client provides token for User A and attempts to access User B (via user_id param),

             ownership check rejects with AuthorizationError (HTTP 403) unless user is admin.

        2. In production without token: returns 0 (triggers 401 Unauthorized for protected paths).

        3. Local desktop mode fallback (development only): uses assistant_core context.

           Never trusts unauthenticated user_id from query/payload to switch identities.

        """

        auth_user = self._get_auth_user()

        if auth_user and "sub" in auth_user:

            token_uid = int(auth_user["sub"])

            requested_uid = None

            if q and "user_id" in q:

                try:

                    requested_uid = int(q["user_id"][0])

                except (ValueError, TypeError):

                    pass

            elif payload and "user_id" in payload and payload["user_id"] is not None:

                try:

                    requested_uid = int(payload["user_id"])

                except (ValueError, TypeError):

                    pass



            if requested_uid is not None and requested_uid > 0:

                user_role = auth_user.get("role", "user")

                if user_role != "admin" and requested_uid != token_uid:

                    enforce_ownership(token_uid, requested_uid)



            return token_uid



        app_env = os.getenv("APP_ENV", os.getenv("FLASK_ENV", "development")).lower()
        if app_env == "production":
            return 0

        # Protect against LAN access, DNS rebinding, and Host-header manipulation
        client_ip = self.client_address[0] if hasattr(self, "client_address") and self.client_address else ""
        is_loopback = client_ip in ("127.0.0.1", "::1", "localhost")

        raw_host = (self.headers.get("Host") or "").split(":")[0].strip().lower()
        valid_host = raw_host in ("127.0.0.1", "localhost", "::1")

        has_forwarded = bool(self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP"))

        if not (is_loopback and valid_host and not has_forwarded):
            # Remote, LAN, rebinding, or proxied requests MUST authenticate via verified Bearer token
            return 0

        # Development fallback: only for verified direct desktop loopback
        uctx = assistant_core.get_user_context()
        return uctx.get("user_id") or 1



    def do_GET(self):

        t0 = time.time()

        url = urlparse(self.path)

        path = url.path

        q = parse_qs(url.query)



        try:

            uid = self._resolve_uid(q=q)

        except AuthorizationError as auth_err:

            self._send_json({"success": False, "error": str(auth_err)}, 403)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 403)

            return



        if path not in PUBLIC_PATHS and uid == 0:

            self._send_json({"success": False, "error": "Authentication required."}, 401)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 401)

            return



        # ── PUBLIC / OBSERVABILITY / HEALTH ──────────────────────────────────

        if path == "/api/health" or path == "/health":

            metrics = get_admin_metrics().get_system_health()

            self._send_json({"success": True, "status": metrics["status"], "health": metrics})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/admin/metrics":

            metrics = get_admin_metrics().get_system_health()

            self._send_json({"success": True, "data": metrics})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── CORE / TELEMETRY / STATE ─────────────────────────────────────────

        elif path == "/api/status" or path == "/api/telemetry":

            telem = assistant_core.get_telemetry()

            self._send_json({"success": True, "data": telem})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/state":

            self._send_json({

                "success": True,

                "state": assistant_core.get_state(),

                "audio_level": assistant_core.get_audio_level()

            })

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/user" or path == "/api/users/me":

            uctx = assistant_core.get_user_context()

            self._send_json({"success": True, "user": uctx, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── PER-USER API CREDENTIALS ──────────────────────────────────────────

        elif path == "/api/credentials":

            from core.credential_manager import get_credential_manager

            statuses = get_credential_manager().get_providers_status(uid)

            self._send_json({"success": True, "credentials": statuses, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/credentials/setup-status":

            from core.credential_manager import get_credential_manager

            done = get_credential_manager().has_completed_api_setup(uid)

            self._send_json({"success": True, "completed": done, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── GDPR DATA EXPORT ──────────────────────────────────────────────────

        elif path == "/api/users/me/export":

            export_payload = export_user_data(uid)

            self._send_json({"success": True, "export": export_payload, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── CHATGPT-STYLE MEMORY & FACTS ──────────────────────────────────────

        elif path == "/api/memories/facts":

            mem = get_chatgpt_memory()

            facts = mem.get_user_facts(uid)

            self._send_json({"success": True, "facts": facts, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/preferences":

            mem = get_chatgpt_memory()

            prefs = mem.get_preferences(uid)

            self._send_json({"success": True, "preferences": prefs, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/conversations":

            mem = get_chatgpt_memory()

            limit = int(q.get("limit", [15])[0])

            convs = mem.get_recent_conversation(uid, limit=limit)

            self._send_json({"success": True, "conversations": convs, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/devices/commands":
            try:
                device = self._resolve_remote_device(q=q)
                if not device:
                    self._send_json({"success": False, "error": "Unauthorized device token"}, 401)
                    return
                from skills.device_management.device_dispatcher import get_device_dispatcher
                dispatcher = get_device_dispatcher()
                commands = dispatcher.poll_commands(device.device_id)
                self._send_json({"success": True, "device_id": device.device_id, "commands": commands})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/devices/location":
            try:
                device = self._resolve_remote_device(q=q)
                if not device:
                    if uid > 0:
                        from skills.device_management.device_registry import get_device_registry
                        reg = get_device_registry()
                        target = q.get("device_id", [None])[0] or ""
                        devs = reg.resolve_device(uid, target)
                        if devs:
                            self._send_json({"success": True, "device_id": devs[0].device_id, "location": devs[0].location, "history": devs[0].location_history})
                            return
                        self._send_json({"success": False, "error": "No matching device found"}, 404)
                        return
                    self._send_json({"success": False, "error": "Unauthorized"}, 401)
                    return
                self._send_json({"success": True, "device_id": device.device_id, "location": device.location, "history": device.location_history})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            return

        elif path == "/api/location":
            try:
                from skills.device_location import get_location_controller, get_map_state_manager
                lc = get_location_controller()
                msm = get_map_state_manager()
                eff_uid = uid if uid > 0 else 1
                loc = lc.detector.get_current_location(user_id=eff_uid)
                diag = lc.detector.get_diagnostics(user_id=eff_uid)
                msm.update_user_location(loc)
                self._send_json({
                    "success": True,
                    "latitude": loc.get("latitude"),
                    "longitude": loc.get("longitude"),
                    "city": loc.get("city"),
                    "accuracy": loc.get("accuracy_m"),
                    "accuracy_m": loc.get("accuracy_m"),
                    "source": loc.get("source"),
                    "device_name": loc.get("device_name"),
                    "freshness_label": loc.get("freshness_label"),
                    "location": loc,
                    "diagnostics": diag,
                    "active_navigation": lc.active_navigation,
                    "map_state": msm.get_state(),
                    "user_id": eff_uid,
                })
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/location/map_state":
            try:
                from skills.device_location import get_map_state_manager
                msm = get_map_state_manager()
                self._send_json({"success": True, "state": msm.get_state()})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/devices/enrollment-code":
            try:
                eff_uid = uid if uid > 0 else 1
                from skills.device_management.device_pairing import get_pairing_manager
                pm = get_pairing_manager()
                code = pm.get_or_create_enrollment_code_for_user(eff_uid)
                self._send_json({"success": True, "enrollment_code": code, "user_id": eff_uid})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── 5. CLIPBOARD (STRICTLY ON-DEMAND) ─────────────────────────────────

        elif path == "/api/clipboard":

            try:

                from skills.clipboard.clipboard_analyzer import analyze_clipboard

                clip_res = analyze_clipboard()

                self._send_json({"success": True, "clipboard": clip_res})

            except Exception as e:

                self._send_json({"success": False, "error": str(e)})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── 11. CALENDAR ──────────────────────────────────────────────────────

        elif path == "/api/calendar":

            try:

                from modules.calendar_manager.calendar_storage import CalendarStorage

                cs = CalendarStorage()

                today = time.strftime("%Y-%m-%d")

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── REMINDERS / MEMORY (EXISTING AUTHORITATIVE PATHS) ─────────────────

        elif path == "/api/reminders":

            reminders = assistant_core.get_user_reminders(user_id=uid)

            self._send_json({"success": True, "reminders": reminders, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/memory" or path == "/api/memories":

            memory = assistant_core.get_user_memory(user_id=uid)

            notes = assistant_core.get_user_notes(user_id=uid)

            facts = get_chatgpt_memory().get_user_facts(uid)

            self._send_json({"success": True, "memory": memory, "notes": notes, "facts": facts, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── STATIC WEB UI ─────────────────────────────────────────────────────



        elif path == "/companion":

            self._send_html(_COMPANION_PWA_HTML)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/" or path == "/index.html":

            index_path = os.path.join(STATIC_DIR, "index.html")

            if os.path.exists(index_path):

                with open(index_path, "r", encoding="utf-8") as f:

                    self._send_html(f.read())

            else:

                self._send_html("<h1>Trevon Labs Dashboard</h1><p>Dashboard UI ready.</p>")

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        self._send_json({"error": "Not Found", "path": path}, 404)

        get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 404, uid)



    def do_POST(self):

        t0 = time.time()

        url = urlparse(self.path)

        path = url.path



        content_len = int(self.headers.get("Content-Length", 0))

        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"

        try:

            payload = json.loads(body)

        except Exception:

            payload = {}



        try:

            uid = self._resolve_uid(payload=payload)

        except AuthorizationError as auth_err:

            self._send_json({"success": False, "error": str(auth_err)}, 403)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 403)

            return



        if path not in PUBLIC_PATHS and uid == 0:

            self._send_json({"success": False, "error": "Authentication required."}, 401)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 401)

            return



        # ── AUTHENTICATION ENDPOINTS (PUBLIC) ─────────────────────────────────

        if path == "/api/auth/signup":

            username = payload.get("username", "").strip()

            password = payload.get("password", "").strip()

            res = auth_signup(username, password)

            status_code = 200 if res.get("success") else 400

            self._send_json(res, status=status_code)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, status_code)

            return



        elif path == "/api/auth/login":

            username = payload.get("username", "").strip()

            password = payload.get("password", "").strip()

            res = authenticate_user_credentials(username, password)

            status_code = 200 if res.get("success") else 401

            self._send_json(res, status=status_code)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, status_code)

            return



        elif path == "/api/auth/check-username":

            username = payload.get("username", "").strip()

            from core.auth_service import is_username_available

            avail = is_username_available(username)

            self._send_json({"available": avail, "username": username}, 200)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200)

            return



        elif path == "/api/credentials/validate":

            provider = payload.get("provider", "").strip().lower()

            candidate_key = payload.get("api_key")

            from core.credential_manager import get_credential_manager

            res = get_credential_manager().test_provider_connection(None, provider, candidate_key)

            status_code = 200 if res.get("success") else 400

            self._send_json(res, status=status_code)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, status_code)

            return



        elif path == "/api/auth/logout":

            token = payload.get("token")

            auth_header = self.headers.get("Authorization")

            if not token and auth_header:

                parts = auth_header.strip().split()

                token = parts[1] if len(parts) == 2 else parts[0]

            if token:

                revoke_token(token)

            self._send_json({"success": True, "message": "Logged out successfully."})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/auth/change_password":

            old_p = payload.get("old_password", "")

            new_p = payload.get("new_password", "")

            res = change_user_password(uid, old_p, new_p)

            status_code = 200 if res.get("success") else 400

            self._send_json(res, status=status_code)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, status_code, uid)

            return



        # ── PER-USER API CREDENTIALS ──────────────────────────────────────────

        elif path == "/api/credentials":

            provider = payload.get("provider", "").strip().lower()

            key_val = payload.get("api_key", "").strip()

            if not provider:

                self._send_json({"success": False, "error": "Missing provider name"}, 400)

                return

            from core.credential_manager import get_credential_manager

            ok = get_credential_manager().save_credential(uid, provider, key_val)

            self._send_json({"success": ok, "provider": provider, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200 if ok else 500, uid)

            return



        elif path == "/api/credentials/test":

            provider = payload.get("provider", "").strip().lower()

            candidate_key = payload.get("api_key")

            from core.credential_manager import get_credential_manager

            res = get_credential_manager().test_provider_connection(uid, provider, candidate_key)

            self._send_json(res, status=200 if res.get("success") else 400)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200 if res.get("success") else 400, uid)

            return



        elif path == "/api/credentials/setup-status":

            completed = bool(payload.get("completed", True))

            from core.credential_manager import get_credential_manager

            ok = get_credential_manager().set_completed_api_setup(uid, completed)

            self._send_json({"success": ok, "completed": completed, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── CHATGPT MEMORY ENDPOINTS ──────────────────────────────────────────

        elif path == "/api/memories/search":

            query = payload.get("query", "").strip()

            mem = get_chatgpt_memory()

            matches = mem.retrieve_relevant_memories(uid, query, limit=8)

            self._send_json({"success": True, "results": matches, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/memories/facts":

            key = payload.get("key", "").strip()

            val = payload.get("value", "")

            mem = get_chatgpt_memory()

            success = mem.set_user_fact(uid, key, val, confidence=1.0, source="user_api")

            self._send_json({"success": success, "key": key, "value": val, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/preferences":

            key = payload.get("key", "").strip()

            val = payload.get("value", "")

            mem = get_chatgpt_memory()

            success = mem.set_preference(uid, key, val)

            self._send_json({"success": success, "key": key, "value": val, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/conversations":

            u_in = payload.get("user_input", "")

            a_out = payload.get("assistant_response", "")

            get_chatgpt_memory().log_interaction(uid, u_in, a_out)

            self._send_json({"success": True, "message": "Interaction saved.", "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── COMMAND TERMINAL ──────────────────────────────────────────────────

        elif path == "/api/command":

            cmd = payload.get("command", "").strip()

            if not cmd:

                self._send_json({"success": False, "error": "Empty command"}, 400)

                get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 400, uid)

                return

            response = assistant_core.execute_command(cmd, user_id=uid)

            self._send_json({"success": True, "response": response, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/devices/enroll":
            try:
                from skills.device_management.device_pairing import get_pairing_manager
                pm = get_pairing_manager()
                code = payload.get("enrollment_code", "").strip()
                name = payload.get("device_name") or payload.get("name") or "Remote Android"
                ident = payload.get("stable_identity") or payload.get("identity") or ""
                platform = payload.get("platform", "android")
                os_ver = payload.get("os_version", "")
                client_ip = self.client_address[0]
                rec, token = pm.approve_enrollment(
                    enrollment_code=code,
                    device_name=name,
                    stable_identity=ident,
                    platform=platform,
                    os_version=os_ver,
                    ip=client_ip,
                    metadata=payload.get("metadata", {})
                )
                if rec and token:
                    self._send_json({
                        "success": True,
                        "device_id": rec.device_id,
                        "auth_token": token,
                        "device": rec.to_dict()
                    })
                else:
                    self._send_json({"success": False, "error": "Invalid, already used, or expired enrollment code"}, 400)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/devices/heartbeat":
            try:
                device = self._resolve_remote_device(payload=payload)
                if not device:
                    self._send_json({"success": False, "error": "Unauthorized device token"}, 401)
                    return
                from skills.device_management.device_registry import get_device_registry
                reg = get_device_registry()
                battery = payload.get("battery")
                charging = payload.get("charging")
                net_info = payload.get("network_info") or {}
                client_ip = self.client_address[0]
                updated = reg.update_network_and_heartbeat(
                    device_id=device.device_id,
                    battery=battery,
                    charging=charging,
                    network_info=net_info,
                    connection_mode="remote_relay",
                    ip=client_ip
                )
                self._send_json({"success": True, "device_id": device.device_id, "online": True})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/devices/location":
            try:
                device = self._resolve_remote_device(payload=payload)
                if not device:
                    self._send_json({"success": False, "error": "Unauthorized device token"}, 401)
                    return
                lat = float(payload.get("latitude", 0.0))
                lon = float(payload.get("longitude", 0.0))
                acc = payload.get("accuracy_m")
                alt = payload.get("altitude_m")
                provider = payload.get("provider", "gps")
                from skills.device_management.device_registry import get_device_registry
                reg = get_device_registry()
                updated = reg.update_location(
                    device_id=device.device_id,
                    latitude=lat,
                    longitude=lon,
                    accuracy_m=float(acc) if acc is not None else None,
                    altitude_m=float(alt) if alt is not None else None,
                    provider=provider
                )
                self._send_json({"success": True, "device_id": device.device_id, "location": updated.location if updated else {}})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/location/route":
            try:
                from skills.device_location import get_location_controller
                lc = get_location_controller()
                eff_uid = uid if uid > 0 else 1
                o_lat = float(payload.get("origin_lat", 0.0))
                o_lon = float(payload.get("origin_lon", 0.0))
                d_lat = float(payload.get("dest_lat", 0.0))
                d_lon = float(payload.get("dest_lon", 0.0))
                mode = payload.get("mode", "driving")
                if abs(o_lat) < 0.0001:
                    cur = lc.detector.get_current_location(user_id=eff_uid)
                    o_lat, o_lon = cur.get("latitude", 0.0), cur.get("longitude", 0.0)
                res = lc.get_route(o_lat, o_lon, d_lat, d_lon, mode=mode)
                self._send_json(res)
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/location/nearby":
            try:
                from skills.device_location import get_location_controller
                lc = get_location_controller()
                eff_uid = uid if uid > 0 else 1
                term = payload.get("category") or payload.get("term", "hospital")
                radius = float(payload.get("radius_km", 5.0))
                lat = float(payload.get("latitude", 0.0))
                lon = float(payload.get("longitude", 0.0))
                if abs(lat) < 0.0001:
                    cur = lc.detector.get_current_location(user_id=eff_uid)
                    lat, lon = cur.get("latitude", 0.0), cur.get("longitude", 0.0)
                places = lc.search_nearby(term, lat, lon, radius_km=radius)
                self._send_json({"success": True, "category": term, "places": places})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/location/geocode":
            try:
                from skills.device_location import get_location_controller
                lc = get_location_controller()
                query = payload.get("query", "")
                cands = lc.geocode(query)
                self._send_json({"success": True, "query": query, "results": cands})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/location/map_state":
            try:
                from skills.device_location import get_map_state_manager
                msm = get_map_state_manager()
                act = payload.get("action", "")
                if act == "open":
                    msm.open_map()
                elif act == "close":
                    msm.close_map()
                elif act == "keep_open":
                    msm.keep_map_open()
                elif act == "zoom":
                    if "delta" in payload:
                        msm.adjust_zoom(int(payload["delta"]))
                    elif "level" in payload:
                        msm.set_zoom(int(payload["level"]))
                elif act == "filter_categories":
                    msm.filter_categories(payload.get("categories", []))
                elif act == "add_category":
                    msm.add_category(payload.get("category", ""))
                elif act == "remove_category":
                    msm.remove_category(payload.get("category", ""))
                elif act == "show_all":
                    msm.show_all()
                elif act == "select":
                    msm.select_marker(payload.get("marker_id") or payload.get("index"))
                elif act == "set_markers":
                    msm.set_markers(payload.get("places", []), category=payload.get("category", ""), append=payload.get("append", False))
                elif act == "set_active_route":
                    msm.set_active_route(payload.get("route"))
                elif act == "clear_route":
                    msm.clear_route()
                elif act == "reset":
                    msm.reset()
                self._send_json({"success": True, "state": msm.get_state()})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
            return

        elif path == "/api/devices/result":
            try:
                device = self._resolve_remote_device(payload=payload)
                if not device:
                    self._send_json({"success": False, "error": "Unauthorized device token"}, 401)
                    return
                req_id = payload.get("request_id", "")
                res_data = payload.get("result", {})
                from skills.device_management.device_dispatcher import get_device_dispatcher
                dispatcher = get_device_dispatcher()
                ok = dispatcher.submit_command_result(req_id, res_data)
                self._send_json({"success": True, "handled": ok, "request_id": req_id})
            except Exception as e:
                self._send_json({"success": False, "error": str(e)}, 500)
            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)
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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── 3. AUDIO ACTIONS ──────────────────────────────────────────────────

        elif path == "/api/audio/switch":

            try:

                from skills.audio_management.audio_controller import get_audio_controller

                ep_type = payload.get("type", "input")

                idx = int(payload.get("index", 0))

                ac = get_audio_controller()

                res = ac.set_audio_endpoint(ep_type, idx)

                self._send_json(res)

            except Exception as e:

                self._send_json({"success": False, "error": str(e)}, 500)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/audio/echoguard/calibrate":

            try:

                from skills.audio_management.echo_guard import get_echo_guard

                eg = get_echo_guard()

                eg.calibrate(ambient_duration=1.0)

                self._send_json({"success": True, "message": "EchoGuard ambient calibration completed.", "floor": eg.floor, "threshold": eg.threshold})

            except Exception as e:

                self._send_json({"success": False, "error": str(e)}, 500)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── 6. LEARNING / PREFERENCE ACTIONS ──────────────────────────────────

        elif path == "/api/rules/add":

            try:

                from skills.learning.learned_rules import get_learned_rules_engine

                rule_text = payload.get("rule", "").strip()

                if not rule_text:

                    self._send_json({"success": False, "error": "Missing rule text"}, 400)

                    return

                lre = get_learned_rules_engine()

                res = lre.learn_rule(uid, rule_text)

                self._send_json(res)

            except Exception as e:

                self._send_json({"success": False, "error": str(e)}, 500)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── 7. UNDO ACTIONS ───────────────────────────────────────────────────

        elif path == "/api/undo/execute":

            try:

                from skills.undo.undo_manager import get_undo_manager

                um = get_undo_manager()

                res = um.undo(uid)

                self._send_json(res)

            except Exception as e:

                self._send_json({"success": False, "error": str(e)}, 500)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── 8. SMART HOME ACTIONS ─────────────────────────────────────────────

        elif path == "/api/smarthome/action":

            try:

                from skills.smart_home.service import get_smart_home_service

                device_id = payload.get("device_id", "")

                cmd = payload.get("command", "")

                value = payload.get("value", None)

                sh = get_smart_home_service()

                res = sh.control_device(uid, device_id, cmd, value)

                self._send_json(res)

            except Exception as e:

                self._send_json({"success": False, "error": str(e)}, 500)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── 11. CALENDAR ACTIONS ──────────────────────────────────────────────

        elif path == "/api/calendar/add":

            try:

                from modules.calendar_manager.calendar_storage import CalendarStorage

                cs = CalendarStorage()

                title = payload.get("title", "").strip()

                date_str = payload.get("date", "").strip()

                time_str = payload.get("time", "").strip()

                if not title or not date_str:

                    self._send_json({"success": False, "error": "Missing title or date"}, 400)

                    return

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/assistant/state":

            new_state = payload.get("state", "").strip()

            if new_state:

                assistant_core.set_state(new_state)

                self._send_json({"success": True, "state": new_state})

                return

            self._send_json({"success": False, "error": "Missing state"}, 400)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 400, uid)

            return



        self._send_json({"error": "Not Found", "path": path}, 404)

        get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 404, uid)



    def do_DELETE(self):

        t0 = time.time()

        url = urlparse(self.path)

        path = url.path

        q = parse_qs(url.query)



        try:

            uid = self._resolve_uid(q=q)

        except AuthorizationError as auth_err:

            self._send_json({"success": False, "error": str(auth_err)}, 403)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 403)

            return



        if path not in PUBLIC_PATHS and uid == 0:

            self._send_json({"success": False, "error": "Authentication required."}, 401)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 401)

            return



        # ── GDPR CASCADING USER DELETION ──────────────────────────────────────

        if path == "/api/users/me/delete" or path == "/api/user/delete":

            res = delete_user_account_cascading(uid)

            status_code = 200 if res.get("success") else 400

            self._send_json(res, status=status_code)

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, status_code, uid)

            return



        # ── PER-USER API CREDENTIAL DELETION ──────────────────────────────────

        elif path == "/api/credentials":

            prov = q.get("provider", [""])[0].strip().lower()

            if not prov:

                self._send_json({"success": False, "error": "Missing provider name parameter"}, 400)

                return

            from core.credential_manager import get_credential_manager

            ok = get_credential_manager().delete_credential(uid, prov)

            self._send_json({"success": ok, "provider": prov, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        # ── CHATGPT MEMORY FACT DELETION ──────────────────────────────────────

        elif path == "/api/memories/facts":

            key = q.get("key", [""])[0]

            if not key:

                self._send_json({"success": False, "error": "Missing fact key"}, 400)

                return

            success = get_chatgpt_memory().delete_user_fact(uid, key)

            self._send_json({"success": success, "key": key, "user_id": uid})

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        elif path == "/api/rules":

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

            get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 200, uid)

            return



        self._send_json({"error": "Not Found", "path": path}, 404)

        get_admin_metrics().record_request(path, (time.time() - t0) * 1000.0, 404, uid)





# ── Server Lifecycle Management (Decoupled & Non-Blocking) ───────────────────

_server_instance: Optional[ThreadedHTTPServer] = None

_server_thread: Optional[threading.Thread] = None

_server_running: bool = False

_server_port: int = DEFAULT_PORT





def start_dashboard_server(port: int = DEFAULT_PORT, host: str = "0.0.0.0") -> bool:

    """Start the Web Dashboard & API server in a background daemon thread."""

    global _server_instance, _server_thread, _server_running, _server_port



    if _server_running:

        return True



    # Safely apply any pending non-destructive database migrations

    try:

        run_migrations()

    except Exception as e:

        print(f"[Dashboard] Migration check notice: {e}")



    try:

        _server_instance = ThreadedHTTPServer((host, port), DashboardHandler)

        _server_port = port

        _server_running = True



        def _run_server():

            print(f"[Dashboard] Production API & Web Control Surface running at http://localhost:{port} (host: {host})")

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

    parser = argparse.ArgumentParser(description="Trevon Labs Production API & Web Dashboard")

    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port to bind (default: {DEFAULT_PORT})")

    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (default: 0.0.0.0)")

    args = parser.parse_args()



    print("============================================================")

    print("STARTING TREVON LABS PRODUCTION MULTI-USER BACKEND & DASHBOARD")

    print("============================================================")

    uctx = assistant_core.get_user_context()

    print(f"Active User Context: {uctx.get('username')} (ID: {uctx.get('user_id')}) | Assistant: {uctx.get('assistant_name')}")



    success = start_dashboard_server(port=args.port, host=args.host)

    if success:

        print(f"[Dashboard] Open your browser or client at: http://localhost:{args.port}")

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

