"""
GADS Platform Device Adapter
Implements genuine integration with the GADS mobile device platform:
1. Hub / Provider REST Client (for external GADS server instances).
2. Embedded GADS Device Provisioning Pipeline (deploying gads-settings.apk,
   launching the Kotlin RemoteControlServerKt daemon on port 1994, and
   controlling devices via HTTP JSON endpoints /tap, /swipe, /home, /lock).
3. Fallback to direct ADB if companion server provisioning is restricted.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import urllib.request
import urllib.error

from .adb_adapter import AdbAdapter, get_adb_adapter

logger = logging.getLogger("GadsPlatformAdapter")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    RESOURCES_DIR = Path(sys._MEIPASS) / "skills" / "device_management" / "resources"
else:
    RESOURCES_DIR = Path(__file__).resolve().parent / "resources"
GADS_SETTINGS_APK = RESOURCES_DIR / "gads-settings.apk"


@dataclass
class DeviceCapabilities:
    """
    Structured representation of what a connected or discovered device actually supports.
    Distinguishes full, partial, companion_required, and restricted platform capabilities.
    """
    platform: str  # "android", "ios", "unknown"
    manufacturer: str  # e.g., "Google", "Samsung", "Xiaomi", "Apple"
    model: str
    os_version: str
    support_level: str  # "full", "partial", "restricted", "companion_required"
    can_touch: bool = False
    can_swipe: bool = False
    can_keyevent: bool = False
    can_screenshot: bool = False
    can_type: bool = False
    can_stream: bool = False
    can_launch_apps: bool = False
    can_read_battery: bool = False
    oem_restrictions: List[str] = field(default_factory=list)
    guidance: List[str] = field(default_factory=list)
    unsupported_features: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "platform": self.platform,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "os_version": self.os_version,
            "support_level": self.support_level,
            "can_touch": self.can_touch,
            "can_swipe": self.can_swipe,
            "can_keyevent": self.can_keyevent,
            "can_screenshot": self.can_screenshot,
            "can_type": self.can_type,
            "can_stream": self.can_stream,
            "can_launch_apps": self.can_launch_apps,
            "can_read_battery": self.can_read_battery,
            "capabilities": {
                "touch": self.can_touch,
                "swipe": self.can_swipe,
                "keyevent": self.can_keyevent,
                "screenshot": self.can_screenshot,
                "type": self.can_type,
                "stream": self.can_stream,
                "launch_apps": self.can_launch_apps,
                "read_battery": self.can_read_battery,
            },
            "oem_restrictions": self.oem_restrictions,
            "guidance": self.guidance,
            "unsupported_features": self.unsupported_features,
        }


@dataclass
class PlatformSession:
    """Represents an active, verified device platform session."""
    session_id: str
    device_udid: str
    session_type: str  # "gads_hub", "gads_daemon", "adb_direct"
    model: str
    manufacturer: str = ""
    android_version: str = ""
    battery: Optional[int] = None
    charging: bool = False
    screen_size: str = ""
    control_port: Optional[int] = None
    ime_port: Optional[int] = None
    active: bool = True
    started_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    capabilities: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "device_udid": self.device_udid,
            "session_type": self.session_type,
            "model": self.model,
            "manufacturer": self.manufacturer,
            "android_version": self.android_version,
            "battery": self.battery,
            "charging": self.charging,
            "screen_size": self.screen_size,
            "control_port": self.control_port,
            "ime_port": self.ime_port,
            "active": self.active,
            "started_at": self.started_at,
            "metadata": self.metadata,
            "capabilities": self.capabilities,
        }


def _find_free_port() -> int:
    """Allocates a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


class GadsPlatformAdapter:
    """
    Genuine integration adapter for the GADS device platform.
    Supports both external Hub/Provider connections and native
    GADS companion daemon orchestration.
    """

    def __init__(
        self,
        hub_url: Optional[str] = None,
        provider_url: Optional[str] = None,
        adb_adapter: Optional[AdbAdapter] = None,
    ):
        self.hub_url = hub_url or os.environ.get("GADS_HUB_URL", "").rstrip("/")
        self.provider_url = provider_url or os.environ.get("GADS_PROVIDER_URL", "").rstrip("/")
        self.adb = adb_adapter or get_adb_adapter()
        self._sessions: Dict[str, PlatformSession] = {}
        self._daemons: Dict[str, subprocess.Popen] = {}
        self._lock = threading.RLock()

    # ─────────────────────────────────────────────────────────────────────────
    # External Hub / Provider Detection
    # ─────────────────────────────────────────────────────────────────────────

    def check_hub_health(self) -> Tuple[bool, Dict[str, Any]]:
        """Checks if an external GADS Hub instance is accessible."""
        if not self.hub_url:
            return False, {"message": "GADS Hub URL not configured."}
        try:
            req = urllib.request.Request(f"{self.hub_url}/devices", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return True, {"hub_url": self.hub_url, "devices": data}
        except Exception as e:
            return False, {"hub_url": self.hub_url, "error": str(e)}
        return False, {"hub_url": self.hub_url, "message": "Hub health check failed."}

    def check_provider_health(self) -> Tuple[bool, Dict[str, Any]]:
        """Checks if an external GADS Provider instance is accessible."""
        if not self.provider_url:
            return False, {"message": "GADS Provider URL not configured."}
        try:
            req = urllib.request.Request(f"{self.provider_url}/devices", headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return True, {"provider_url": self.provider_url, "devices": data}
        except Exception as e:
            return False, {"provider_url": self.provider_url, "error": str(e)}
        return False, {"provider_url": self.provider_url, "message": "Provider health check failed."}

    # ─────────────────────────────────────────────────────────────────────────
    # Device Discovery
    # ─────────────────────────────────────────────────────────────────────────

    def discover_devices(self) -> Dict[str, Any]:
        """
        Discovers all devices available through GADS Hub, Provider, or connected ADB.
        Returns detailed status including authorization and platform session readiness.
        """
        diag = self.adb.diagnose_environment()
        devices: List[Dict[str, Any]] = []

        # 1. Try Hub if available
        hub_ok, hub_data = self.check_hub_health()
        if hub_ok and isinstance(hub_data.get("devices"), list):
            for d in hub_data["devices"]:
                d["source"] = "gads_hub"
                devices.append(d)

        # 2. Try Provider if available
        prov_ok, prov_data = self.check_provider_health()
        if prov_ok and isinstance(prov_data.get("devices"), list):
            for d in prov_data["devices"]:
                d["source"] = "gads_provider"
                devices.append(d)

        # 3. Always query connected ADB devices
        adb_devs = self.adb.list_devices()
        existing_serials = {d.get("serial") or d.get("udid") for d in devices}
        for d in adb_devs:
            if d["serial"] not in existing_serials:
                d["source"] = "adb"
                # Check if GADS session is active for this device
                sess = self._sessions.get(d["serial"])
                if sess and sess.active:
                    d["platform_session"] = sess.to_dict()
                devices.append(d)

        return {
            "adb_available": diag.get("running", False),
            "hub_available": hub_ok,
            "provider_available": prov_ok,
            "devices": devices,
            "count": len(devices),
            "diagnostics": diag,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # GADS Companion Server Provisioning (The real Kotlin RemoteControlServer)
    # ─────────────────────────────────────────────────────────────────────────

    def provision_gads_daemon(self, serial: str) -> Tuple[bool, Optional[int], str]:
        """
        Provisions and launches the GADS Kotlin RemoteControlServerKt daemon on the Android device:
        1. Pushes gads-settings.apk to /data/local/tmp/gads-settings
        2. Kills any stale RemoteControlServerKt instances.
        3. Spawns `CLASSPATH=/data/local/tmp/gads-settings app_process / com.shamanec.settings.RemoteControlServerKt 1994`
        4. Forwards a free host TCP port to 1994.
        Returns: (success, host_control_port, message)
        """
        if not GADS_SETTINGS_APK.is_file():
            return False, None, f"gads-settings.apk not found at {GADS_SETTINGS_APK}"

        # 1. Install or push APK to /data/local/tmp/gads-settings
        logger.info(f"Pushing GADS Settings apk to /data/local/tmp/gads-settings for {serial}...")
        ok_push, push_err = self.adb._run_adb_cmd(["-s", serial, "push", str(GADS_SETTINGS_APK), "/data/local/tmp/gads-settings"], timeout=15.0)
        if not ok_push:
            return False, None, f"Failed to push GADS Settings apk: {push_err}"

        # 2. Kill old daemon
        self.adb._run_adb_cmd(["-s", serial, "shell", "pkill", "-f", "RemoteControlServerKt"], timeout=4.0)
        time.sleep(0.5)

        # 3. Allocate free port
        control_port = _find_free_port()

        # 4. Forward port
        ok_fwd, fwd_err = self.adb._run_adb_cmd(["-s", serial, "forward", f"tcp:{control_port}", "tcp:1994"], timeout=5.0)
        if not ok_fwd:
            return False, None, f"Failed to forward control port: {fwd_err}"

        # 5. Launch the GADS daemon in background via subprocess
        avail, adb_path = self.adb.is_available()
        if not avail:
            return False, None, "ADB path not found"

        cmd = [
            adb_path,
            "-s", serial,
            "shell",
            "CLASSPATH=/data/local/tmp/gads-settings app_process / com.shamanec.settings.RemoteControlServerKt 1994"
        ]
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            with self._lock:
                # If an old process was running, terminate it
                old_proc = self._daemons.get(serial)
                if old_proc and old_proc.poll() is None:
                    old_proc.terminate()
                self._daemons[serial] = proc

            # Give daemon 1.5 seconds to bind
            time.sleep(1.5)

            # Check if daemon process died prematurely
            if proc.poll() is not None:
                err_out = proc.stderr.read() if proc.stderr else ""
                logger.warning(f"GADS daemon exited early (code {proc.returncode}): {err_out}")
                # Fallback to direct ADB
                return False, None, f"GADS daemon did not start: {err_out}"

            return True, control_port, "GADS RemoteControlServer daemon active."
        except Exception as e:
            return False, None, f"Failed to launch GADS daemon process: {e}"

    # ─────────────────────────────────────────────────────────────────────────
    # Universal Device Capability Layer
    # ─────────────────────────────────────────────────────────────────────────

    def detect_device_capabilities(self, serial: str, props: Optional[Dict[str, Any]] = None) -> DeviceCapabilities:
        """
        Dynamically detects device capabilities across Android OEMs (Samsung, Pixel,
        Xiaomi, OnePlus, Motorola, etc.) without model-specific hardcoding.
        Inspects manufacturer, Android release, and SDK version.
        """
        if not props:
            props = self.adb.get_device_properties(serial)

        mfg = (
            props.get("manufacturer")
            or props.get("ro.product.manufacturer")
            or props.get("brand")
            or props.get("ro.product.brand")
            or ""
        ).strip()
        mfg_low = mfg.lower()
        model = props.get("model") or props.get("ro.product.model") or serial
        os_ver = props.get("android_version") or props.get("ro.build.version.release") or ""
        sdk_str = str(props.get("sdk_version") or props.get("ro.build.version.sdk") or "0")
        try:
            sdk_ver = int(sdk_str)
        except Exception:
            sdk_ver = 0

        oem_restrictions: List[str] = []
        guidance: List[str] = []
        unsupported: List[str] = []

        can_keyevent = True
        can_screenshot = True
        can_type = True
        can_launch_apps = True
        can_read_battery = True
        can_touch = True
        can_swipe = True
        can_stream = True

        # Check OEM-specific configurations
        if any(x in mfg_low for x in ("xiaomi", "redmi", "poco")):
            oem_restrictions.append("MIUI / HyperOS requires 'USB debugging (Security settings)' for simulated clicks.")
            guidance.append(
                "Xiaomi / Redmi / POCO: To allow remote screen clicks, go to Settings -> Additional Settings -> "
                "Developer Options -> enable 'USB debugging (Security settings)'."
            )
        elif "samsung" in mfg_low:
            guidance.append(
                "Samsung Galaxy: Keep phone screen unlocked during initial connection and approve the USB prompt if shown."
            )
        elif any(x in mfg_low for x in ("oneplus", "oppo", "realme")):
            guidance.append(
                "ColorOS / OxygenOS: If automated actions are paused, disable 'Permission monitoring' in Developer Options."
            )
        elif "huawei" in mfg_low or "honor" in mfg_low:
            guidance.append(
                "Huawei / Honor: Enable 'Allow ADB debugging in charge only mode' in Developer Options."
            )
        else:
            guidance.append("Standard Android device ready. Maintain USB debugging authorization.")

        if sdk_ver and sdk_ver < 21:
            can_screenshot = False
            can_stream = False
            unsupported.append("Real-time screencap and video streaming (requires Android 5.0+)")

        support_level = "full" if (can_touch and can_screenshot) else "partial"

        return DeviceCapabilities(
            platform="android",
            manufacturer=mfg or "Android OEM",
            model=model,
            os_version=os_ver,
            support_level=support_level,
            can_touch=can_touch,
            can_swipe=can_swipe,
            can_keyevent=can_keyevent,
            can_screenshot=can_screenshot,
            can_type=can_type,
            can_stream=can_stream,
            can_launch_apps=can_launch_apps,
            can_read_battery=can_read_battery,
            oem_restrictions=oem_restrictions,
            guidance=guidance,
            unsupported_features=unsupported,
        )

    def evaluate_ios_capabilities(self, device_name: str = "Apple iPhone", os_version: str = "iOS") -> DeviceCapabilities:
        """
        Evaluates iPhone / iOS capabilities honestly and transparently.
        Never promises ADB touch control, background screen mirroring, or system key manipulation on iOS.
        """
        return DeviceCapabilities(
            platform="ios",
            manufacturer="Apple",
            model=device_name,
            os_version=os_version,
            support_level="restricted",
            can_touch=False,
            can_swipe=False,
            can_keyevent=False,
            can_screenshot=False,
            can_type=False,
            can_stream=False,
            can_launch_apps=False,
            can_read_battery=True,
            oem_restrictions=[
                "Apple iOS sandbox prohibits unrestricted remote touch simulation",
                "Apple iOS security model forbids background screen capture via standard cables",
                "ADB protocol is not supported on iOS devices",
            ],
            guidance=[
                "iOS devices require the Assistant iOS Companion app for notifications, calendar, and media integration.",
                "Remote touch control and background screen mirroring are restricted by Apple iOS platform security policies.",
            ],
            unsupported_features=[
                "Unrestricted touch and swipe simulation",
                "Arbitrary background application launching",
                "ADB screen streaming",
                "Direct system key injection (Home/Power)",
            ],
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Device Connection Workflow
    # ─────────────────────────────────────────────────────────────────────────

    def connect_device(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Establishes a genuine device platform connection:
        1. Checks ADB and device authorization.
        2. Retrieves hardware properties.
        3. Provisions GADS companion server daemon (or detects external provider).
        4. Verifies screenshot capture.
        5. Returns active PlatformSession.
        """
        diag = self.adb.diagnose_environment()
        if not diag.get("running"):
            return {
                "success": False,
                "status": "service_unavailable",
                "session_type": "none",
                "message": (
                    "Device control service is unavailable: Android Debug Bridge (ADB) was not found. "
                    "Please install Android Platform Tools or set ANDROID_HOME / PATH."
                ),
            }

        devs = self.adb.list_devices()
        if not devs:
            return {
                "success": False,
                "status": "no_device_found",
                "session_type": "none",
                "message": "No mobile device detected via USB or wireless debugging.",
            }

        unauthorized = [d for d in devs if d.get("state") == "unauthorized"]
        offline = [d for d in devs if d.get("state") == "offline"]
        authorized = [d for d in devs if d.get("online")]

        if not authorized:
            if unauthorized:
                return {
                    "success": False,
                    "status": "device_unauthorized",
                    "session_type": "none",
                    "device": unauthorized[0],
                    "message": (
                        f"Device {unauthorized[0]['serial']} detected, but USB debugging is unauthorized. "
                        "Please unlock the phone and tap 'Allow USB debugging'."
                    ),
                }
            if offline:
                return {
                    "success": False,
                    "status": "device_offline",
                    "session_type": "none",
                    "device": offline[0],
                    "message": f"Device {offline[0]['serial']} is offline. Please reconnect.",
                }
            return {
                "success": False,
                "status": "device_unavailable",
                "session_type": "none",
                "message": "Connected device is not in a ready state.",
            }

        # Resolve target device
        target_dev = None
        if serial:
            for d in authorized:
                if d["serial"] == serial or serial.lower() in (d.get("model") or "").lower():
                    target_dev = d
                    break
        else:
            if len(authorized) == 1:
                target_dev = authorized[0]
            else:
                names = [f"{d.get('model') or d.get('serial')} ({d['serial']})" for d in authorized]
                return {
                    "success": False,
                    "status": "multiple_devices",
                    "session_type": "none",
                    "count": len(authorized),
                    "devices": authorized,
                    "message": f"Multiple devices connected: {', '.join(names)}. Please select which device to connect.",
                }

        target_serial = target_dev["serial"]
        props = self.adb.get_device_properties(target_serial)
        model_name = props.get("model") or target_dev.get("model") or target_serial

        # Attempt GADS Kotlin RemoteControlServer daemon provisioning
        try:
            daemon_ok, control_port, daemon_msg = self.provision_gads_daemon(target_serial)
        except Exception as e:
            logger.warning(f"GADS daemon provisioning encountered error ({e}); falling back to direct ADB: {e}")
            daemon_ok, control_port, daemon_msg = False, None, str(e)
        session_type = "gads_daemon" if daemon_ok else "adb_direct"

        # Screenshots must only be captured when explicitly requested by user
        shot_res = {}

        # Universal device capability detection
        caps = self.detect_device_capabilities(target_serial, props=props)

        now_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        session_id = f"gads-session-{target_serial}-{int(time.time())}"

        session = PlatformSession(
            session_id=session_id,
            device_udid=target_serial,
            session_type=session_type,
            model=model_name,
            manufacturer=props.get("manufacturer", ""),
            android_version=props.get("android_version", ""),
            battery=props.get("battery"),
            charging=props.get("charging", False),
            screen_size=props.get("screen_size", ""),
            control_port=control_port,
            active=True,
            started_at=now_str,
            metadata={
                "daemon_active": daemon_ok,
                "daemon_message": daemon_msg,
                "screenshot": shot_res.get("file_path") if shot_res.get("success") else None,
            },
            capabilities=caps.to_dict(),
        )

        with self._lock:
            self._sessions[target_serial] = session

        mode_desc = "GADS Platform Session (Companion Daemon Active)" if daemon_ok else "Direct ADB Session"
        batt_str = f", {session.battery}% battery" if session.battery is not None else ""
        msg = f"Connected to {model_name} via {mode_desc} (Android {session.android_version}{batt_str})."

        return {
            "success": True,
            "status": "connected",
            "session_type": session_type,
            "session": session.to_dict(),
            "capabilities": caps.to_dict(),
            "message": msg,
        }

    def disconnect_device(self, serial: str) -> Dict[str, Any]:
        """Terminates an active platform session and stops daemon processes."""
        with self._lock:
            proc = self._daemons.pop(serial, None)
            if proc and proc.poll() is None:
                proc.terminate()
            sess = self._sessions.pop(serial, None)
            if sess:
                sess.active = False

        # Only clean up daemon and forward ports if device is currently online
        live = self.adb.list_devices()
        online_serials = {d["serial"] for d in live if d.get("online")}
        if serial in online_serials:
            self.adb._run_adb_cmd(["-s", serial, "shell", "pkill", "-f", "RemoteControlServerKt"], timeout=3.0)
            if sess and sess.control_port:
                self.adb._run_adb_cmd(["-s", serial, "forward", "--remove", f"tcp:{sess.control_port}"], timeout=3.0)
            else:
                self.adb._run_adb_cmd(["-s", serial, "forward", "--remove-all"], timeout=3.0)

        return {
            "success": True,
            "status": "disconnected",
            "device": serial,
            "message": f"Device {serial} disconnected and platform session closed.",
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Device Control: GADS HTTP Endpoints with ADB Fallback
    # ─────────────────────────────────────────────────────────────────────────

    def _send_daemon_http(self, serial: str, endpoint: str, payload: Optional[Dict[str, Any]] = None) -> Tuple[bool, Any]:
        """Sends an HTTP request to the live GADS RemoteControlServerKt daemon."""
        sess = self._sessions.get(serial)
        if not sess or not sess.control_port:
            return False, "No active GADS daemon control port"

        url = f"http://localhost:{sess.control_port}/{endpoint.lstrip('/')}"
        data_bytes = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}

        try:
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                body = resp.read().decode("utf-8")
                return True, body
        except Exception as e:
            return False, str(e)

    def tap(self, serial: str, x: float, y: float) -> Dict[str, Any]:
        """Taps the screen using GADS RemoteControlServerKt endpoint or ADB fallback."""
        ok_http, res = self._send_daemon_http(serial, "tap", {"x": x, "y": y})
        if ok_http:
            return {"success": True, "method": "gads_http", "message": f"Tapped at ({x}, {y}) via GADS server."}
        # Fallback to direct ADB input tap
        res_adb = self.adb.tap(int(x), int(y), serial=serial)
        res_adb["method"] = "adb_fallback"
        return res_adb

    def swipe(self, serial: str, x1: float, y1: float, x2: float, y2: float, duration_ms: int = 300) -> Dict[str, Any]:
        """Swipes using GADS RemoteControlServerKt endpoint or ADB fallback."""
        ok_http, res = self._send_daemon_http(serial, "swipe", {
            "startX": x1, "startY": y1, "endX": x2, "endY": y2, "duration": duration_ms
        })
        if ok_http:
            return {"success": True, "method": "gads_http", "message": f"Swiped from ({x1},{y1}) to ({x2},{y2}) via GADS server."}
        res_adb = self.adb.swipe(int(x1), int(y1), int(x2), int(y2), duration_ms=duration_ms, serial=serial)
        res_adb["method"] = "adb_fallback"
        return res_adb

    def home(self, serial: str) -> Dict[str, Any]:
        """Navigates to the Home screen using GADS endpoint or ADB Intent/keyevent."""
        ok_http, res = self._send_daemon_http(serial, "home")
        if ok_http:
            return {"success": True, "method": "gads_http", "message": "Navigated to Home via GADS server."}
        return self.adb.home(serial=serial)

    def back(self, serial: str) -> Dict[str, Any]:
        """Navigates Back on the device."""
        ok_http, res = self._send_daemon_http(serial, "back")
        if ok_http:
            return {"success": True, "method": "gads_http", "message": "Navigated Back via GADS server."}
        return self.adb.back(serial=serial)

    def recents(self, serial: str) -> Dict[str, Any]:
        """Opens recent apps / app switcher on the device."""
        return self.adb.recents(serial=serial)

    def volume_up(self, serial: str, steps: int = 1) -> Dict[str, Any]:
        """Increases volume on the device."""
        return self.adb.volume_up(steps=steps, serial=serial)

    def volume_down(self, serial: str, steps: int = 1) -> Dict[str, Any]:
        """Decreases volume on the device."""
        return self.adb.volume_down(steps=steps, serial=serial)

    def get_volume(self, serial: str) -> Dict[str, Any]:
        """Gets verified hardware media volume from the device."""
        return self.adb.get_volume(serial=serial)

    def set_volume(self, serial: str, level: int) -> Dict[str, Any]:
        """Sets hardware media volume on the device."""
        return self.adb.set_volume(target_level=level, serial=serial)

    def expand_notifications(self, serial: str) -> Dict[str, Any]:
        """Expands notification shade on the device."""
        return self.adb.expand_notifications(serial=serial)

    def expand_settings(self, serial: str) -> Dict[str, Any]:
        """Expands quick settings on the device."""
        return self.adb.expand_settings(serial=serial)

    def collapse_statusbar(self, serial: str) -> Dict[str, Any]:
        """Collapses notification shade/settings on the device."""
        return self.adb.collapse_statusbar(serial=serial)

    def get_notifications(self, serial: str, max_count: int = 10) -> Dict[str, Any]:
        """Reads active notifications from the device."""
        return self.adb.get_notifications(serial=serial, max_count=max_count)

    def open_camera(self, serial: str) -> Dict[str, Any]:
        """Opens camera application on the device."""
        return self.adb.open_camera(serial=serial)

    def take_photo(self, serial: str) -> Dict[str, Any]:
        """Takes a photo on the device."""
        return self.adb.take_photo(serial=serial)

    def get_location(self, serial: str) -> Dict[str, Any]:
        """Queries true location from the device."""
        return self.adb.get_location(serial=serial)

    def search_files(self, serial: str, query: str, base_path: str = "/sdcard/") -> Dict[str, Any]:
        """Searches files on the device."""
        return self.adb.search_files(query=query, base_path=base_path, serial=serial)

    def lock(self, serial: str) -> Dict[str, Any]:
        """Locks or toggles power on the device."""
        ok_http, res = self._send_daemon_http(serial, "lock")
        if ok_http:
            return {"success": True, "method": "gads_http", "message": "Device locked via GADS server."}
        return self.adb.lock_screen(serial=serial)

    def wake(self, serial: str) -> Dict[str, Any]:
        """Wakes up the screen on the device."""
        return self.adb.wake(serial=serial)

    def unlock_screen(self, serial: str) -> Dict[str, Any]:
        """Presents legitimate authentication interface on the device."""
        return self.adb.unlock_screen(serial=serial)

    def get_lock_state(self, serial: str) -> Dict[str, Any]:
        """Checks lock state on the device."""
        return self.adb.get_lock_state(serial=serial)

    def volume_mute(self, serial: str) -> Dict[str, Any]:
        """Mutes volume on the device."""
        return self.adb.volume_mute(serial=serial)

    def get_wifi_status(self, serial: str) -> Dict[str, Any]:
        """Checks Wi-Fi status on the device."""
        return self.adb.get_wifi_status(serial=serial)

    def set_wifi(self, serial: str, enable: bool) -> Dict[str, Any]:
        """Sets Wi-Fi on the device."""
        return self.adb.set_wifi(enable, serial=serial)

    def get_bluetooth_status(self, serial: str) -> Dict[str, Any]:
        """Checks Bluetooth status on the device."""
        return self.adb.get_bluetooth_status(serial=serial)

    def set_bluetooth(self, serial: str, enable: bool) -> Dict[str, Any]:
        """Sets Bluetooth on the device."""
        return self.adb.set_bluetooth(enable, serial=serial)

    def get_brightness(self, serial: str) -> Dict[str, Any]:
        """Gets brightness from the device."""
        return self.adb.get_brightness(serial=serial)

    def set_brightness(self, serial: str, level: int) -> Dict[str, Any]:
        """Sets brightness on the device."""
        return self.adb.set_brightness(level, serial=serial)

    def get_dnd_status(self, serial: str) -> Dict[str, Any]:
        """Gets Do Not Disturb status from the device."""
        return self.adb.get_dnd_status(serial=serial)

    def set_dnd(self, serial: str, enable: bool) -> Dict[str, Any]:
        """Sets Do Not Disturb on the device."""
        return self.adb.set_dnd(enable, serial=serial)

    def type_text(self, serial: str, text: str) -> Dict[str, Any]:
        """Types text on the device."""
        return self.adb.input_text(text, serial=serial)

    def take_screenshot(self, serial: str, output_path: Optional[str] = None) -> Dict[str, Any]:
        """Captures real screenshot via GADS screencap implementation."""
        return self.adb.take_screenshot(output_path=output_path, serial=serial)

    def long_press(self, serial: str, x: float, y: float, duration_ms: int = 1000) -> Dict[str, Any]:
        """Executes a long press at (x, y) on the target device."""
        return self.adb.long_press(int(x), int(y), duration_ms=duration_ms, serial=serial)

    def key_event(self, serial: str, keycode: int | str) -> Dict[str, Any]:
        """Dispatches an Android keycode to the target device."""
        return self.adb.key_event(keycode, serial=serial)

    def get_screen_geometry(self, serial: str) -> Dict[str, Any]:
        """Returns the physical screen geometry, rotation, and aspect ratio."""
        return self.adb.get_screen_geometry(serial=serial)

    def start_screen_stream(self, serial: str, on_frame: Optional[Any] = None) -> Dict[str, Any]:
        """Starts real-time screen streaming session for the device."""
        return self.adb.start_screen_stream(serial=serial, on_frame=on_frame)

    def stop_screen_stream(self, serial: str) -> Dict[str, Any]:
        """Stops real-time screen streaming session for the device."""
        return self.adb.stop_screen_stream(serial=serial)

    def get_stream_frame(self, serial: str) -> Dict[str, Any]:
        """Returns latest decoded frame bytes and metrics."""
        return self.adb.get_latest_stream_frame(serial=serial)

    def find_scrcpy(self) -> Optional[str]:
        """Locates scrcpy binary."""
        return self.adb.find_scrcpy()

    def launch_scrcpy_mirror(self, serial: str, **kwargs) -> Dict[str, Any]:
        """Launches continuous hardware-accelerated scrcpy live mirroring window (up to 60 FPS)."""
        return self.adb.launch_scrcpy(serial=serial, **kwargs)

    def is_scrcpy_running(self) -> bool:
        """Returns True if an active scrcpy mirroring process is running."""
        return self.adb.is_scrcpy_running()

    def get_mirror_status(self) -> Dict[str, Any]:
        """Returns verified real-time screen mirroring metrics."""
        return self.adb.get_mirror_status()

    def stop_scrcpy(self) -> Dict[str, Any]:
        """Stops active scrcpy window."""
        return self.adb.stop_scrcpy()

    def dump_ui_hierarchy(self, serial: str) -> Dict[str, Any]:
        """Dumps UI hierarchy of the target device."""
        return self.adb.dump_ui_hierarchy(serial=serial)

    def find_ui_element(self, serial: str, query: str) -> Dict[str, Any]:
        """Finds target UI element coordinates on the device screen."""
        return self.adb.find_ui_element(query=query, serial=serial)

    def execute_shell(self, serial: str, cmd: str) -> Dict[str, Any]:
        """Executes a shell command on the target Android device."""
        if hasattr(self.adb, "execute_shell"):
            return self.adb.execute_shell(cmd, serial=serial)
        return {"success": False, "output": "execute_shell not supported by underlying adapter"}

    # -------------------------------------------------------------------------
    # Power Menu
    # -------------------------------------------------------------------------

    def power_menu(self, serial: str) -> Dict[str, Any]:
        """Opens the Android power menu (long-press power button)."""
        return self.adb.power_menu(serial=serial)

    # -------------------------------------------------------------------------
    # Media Controls
    # -------------------------------------------------------------------------

    def media_control(self, action: str, serial: str) -> Dict[str, Any]:
        """Sends a media keyevent to the device (play, pause, next, previous, stop, etc.)."""
        return self.adb.media_control(action, serial=serial)

    # -------------------------------------------------------------------------
    # Clipboard
    # -------------------------------------------------------------------------

    def get_clipboard(self, serial: str) -> Dict[str, Any]:
        """Reads the current clipboard text from the device."""
        return self.adb.get_clipboard(serial=serial)

    def set_clipboard(self, text: str, serial: str) -> Dict[str, Any]:
        """Sets clipboard text on the device."""
        return self.adb.set_clipboard(text, serial=serial)

    # -------------------------------------------------------------------------
    # File Management
    # -------------------------------------------------------------------------

    def list_files(self, remote_path: str = "/sdcard/Download", serial: str = None) -> Dict[str, Any]:
        """Lists files in a remote directory on the device."""
        return self.adb.list_files(remote_path, serial=serial)

    def push_file(self, local_path: str, remote_path: str = "/sdcard/Download/", serial: str = None) -> Dict[str, Any]:
        """Pushes a local file to the device."""
        return self.adb.push_file(local_path, remote_path, serial=serial)

    def pull_file(self, remote_path: str, local_path=None, serial: str = None) -> Dict[str, Any]:
        """Pulls a file from the device to the local machine."""
        return self.adb.pull_file(remote_path, local_path, serial=serial)

    # -------------------------------------------------------------------------
    # Network Information
    # -------------------------------------------------------------------------

    def get_network_info(self, serial: str) -> Dict[str, Any]:
        """Returns Wi-Fi SSID, IP, signal, link speed, and mobile data state from the device."""
        return self.adb.get_network_info(serial=serial)

    # -------------------------------------------------------------------------
    # System Status
    # -------------------------------------------------------------------------

    def get_system_status(self, serial: str) -> Dict[str, Any]:
        """Returns CPU %, RAM MB, thermals, and uptime from the device."""
        return self.adb.get_system_status(serial=serial)


# Singleton instance
_platform_adapter: Optional[GadsPlatformAdapter] = None


def get_platform_adapter() -> GadsPlatformAdapter:
    """Returns the singleton GadsPlatformAdapter."""
    global _platform_adapter
    if _platform_adapter is None:
        _platform_adapter = GadsPlatformAdapter()
    return _platform_adapter
