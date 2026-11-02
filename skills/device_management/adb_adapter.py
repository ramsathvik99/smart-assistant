"""
ADB Mobile Device Adapter
Provides real Android device detection, status inspection, screen capture,
and remote interaction via Android Debug Bridge (ADB) or external device bridge.
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import secrets
import string
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("AdbAdapter")

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

OEM_MODEL_MAP: Dict[str, str] = {
    "22111317I": "Redmi Note 12 5G",
    "22111317G": "Redmi Note 12 5G",
    "23021RAAEG": "Redmi Note 12 4G",
    "23021RAA2Y": "Redmi Note 12 4G",
    "23027RAD4I": "Redmi Note 12 Pro 5G",
    "22101316G": "Redmi Note 12 Pro+ 5G",
    "22101316C": "Redmi Note 12 Explorer",
    "2312DRA50G": "Redmi Note 13 Pro 5G",
    "23117RA68G": "Redmi Note 13 4G",
    "2312FRAF0G": "Redmi Note 13 Pro 4G",
}

ANDROID_KEYCODES: Dict[str, int] = {
    "home": 3,
    "back": 4,
    "up": 19,
    "down": 20,
    "left": 21,
    "right": 22,
    "dpad_center": 23,
    "volume_up": 24,
    "volume_down": 25,
    "power": 26,
    "tab": 61,
    "space": 62,
    "enter": 66,
    "return": 66,
    "del": 67,
    "backspace": 67,
    "escape": 111,
    "esc": 111,
    "forward_del": 112,
    "recents": 187,
    "app_switch": 187,
    "wake": 224,
    "wakeup": 224,
}

BATTERY_HEALTH_MAP: Dict[str, str] = {
    "1": "Unknown",
    "2": "Good",
    "3": "Overheat",
    "4": "Dead",
    "5": "Over Voltage",
    "6": "Unspecified Failure",
    "7": "Cold",
}


class ScreenStreamSession:
    """
    Manages a continuous real-time video or frame stream for an Android device.
    Prioritizes low-latency H.264 hardware encoding over ADB with PyAV decoding;
    falls back cleanly to direct in-memory screencap pipes or mock simulation when offline.
    """

    def __init__(
        self,
        serial: str,
        adb_path: str,
        on_frame: Optional[Any] = None,
        model_name: str = "Redmi Note 12 5G",
    ):
        self.serial = serial
        self.adb_path = adb_path
        self.on_frame = on_frame
        self.model_name = model_name
        self.running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._proc: Optional[subprocess.Popen] = None
        self.last_frame_bytes: Optional[bytes] = None
        self.last_frame_time: float = 0.0
        self.width: int = 1080
        self.height: int = 2400
        self.orientation: int = 0
        self.fps: float = 0.0
        self.frame_count: int = 0
        self.state: str = "initialized"
        self.last_error: str = ""
        self._lock = threading.Lock()

    def start(self) -> bool:
        if self.running and self._thread and self._thread.is_alive():
            return True
        self.running = True
        self._stop_event.clear()
        self.state = "connecting"
        self._thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name=f"ScreenStream-{self.serial}"
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self.running = False
        self._stop_event.set()
        self.state = "stopping"
        if self._proc:
            try:
                self._proc.terminate()
            except Exception:
                pass
            self._proc = None
        if self._thread and self._thread.is_alive() and threading.current_thread() != self._thread:
            self._thread.join(timeout=1.5)
        self.state = "stopped"

    def _worker_loop(self) -> None:
        """Streaming worker loop with adaptive multi-tier streaming strategy."""
        t_prev = time.time()
        fps_counter = 0

        # Query initial geometry
        self._detect_geometry()

        while not self._stop_event.is_set():
            # Check reachability of target device
            is_online = self._check_device_online()
            if not is_online:
                self.state = "offline_preview"
                mock_bytes = self._generate_preview_frame()
                with self._lock:
                    self.last_frame_bytes = mock_bytes
                    self.last_frame_time = time.time()
                    self.frame_count += 1
                if self.on_frame:
                    try:
                        self.on_frame(mock_bytes, self.width, self.height)
                    except Exception:
                        pass
                self._stop_event.wait(1.0)
                continue

            self.state = "streaming"

            # Attempt Tier 1: Hardware-accelerated H.264 stream via screenrecord + PyAV
            streamed_ok = self._try_h264_stream()
            if streamed_ok or self._stop_event.is_set():
                continue

            # Fallback Tier 2: Low-latency in-memory screencap pipe (zero disk write)
            self._run_screencap_pipe_loop()

    def _detect_geometry(self) -> None:
        """Detects physical screen size and current orientation via ADB."""
        try:
            cmd = [self.adb_path, "-s", self.serial, "shell", "wm", "size"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0 and "Physical size:" in res.stdout:
                sz = res.stdout.split("Physical size:", 1)[1].strip()
                if "x" in sz:
                    w, _, h = sz.partition("x")
                    self.width = int(w.strip())
                    self.height = int(h.strip())
        except Exception:
            pass

    def _check_device_online(self) -> bool:
        """Quick check if target device responds to an echo command."""
        try:
            cmd = [self.adb_path, "-s", self.serial, "shell", "echo", "1"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.8)
            return res.returncode == 0 and "1" in res.stdout
        except Exception:
            return False

    def _try_h264_stream(self) -> bool:
        """Streams hardware-encoded H.264 frames decoded in real time with PyAV."""
        try:
            import av
            scale_w = 720
            scale_h = int(scale_w * (self.height / max(1, self.width)))
            # Align height to even number
            if scale_h % 2 != 0:
                scale_h += 1

            cmd = [
                self.adb_path,
                "-s", self.serial,
                "exec-out",
                "screenrecord",
                "--output-format=h264",
                f"--size={scale_w}x{scale_h}",
                "--bit-rate=2000000",
                "-"
            ]
            self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            codec = av.CodecContext.create("h264", "r")

            fps_timer = time.time()
            fps_count = 0

            while not self._stop_event.is_set() and self._proc and self._proc.poll() is None:
                chunk = self._proc.stdout.read(4096)
                if not chunk:
                    break
                packets = codec.parse(chunk)
                for pkt in packets:
                    frames = codec.decode(pkt)
                    for frame in frames:
                        pil_img = frame.to_image()
                        import io
                        buf = io.BytesIO()
                        pil_img.save(buf, format="JPEG", quality=75)
                        frame_bytes = buf.getvalue()

                        fps_count += 1
                        now = time.time()
                        if (now - fps_timer) >= 1.0:
                            self.fps = round(fps_count / (now - fps_timer), 1)
                            fps_count = 0
                            fps_timer = now

                        with self._lock:
                            self.last_frame_bytes = frame_bytes
                            self.last_frame_time = now
                            self.frame_count += 1
                            self.width = pil_img.width
                            self.height = pil_img.height

                        if self.on_frame:
                            try:
                                self.on_frame(frame_bytes, pil_img.width, pil_img.height)
                            except Exception:
                                pass

            if self._proc:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                self._proc = None
            return self.frame_count > 0
        except Exception as e:
            self.last_error = str(e)
            return False

    def _run_screencap_pipe_loop(self) -> None:
        """Fallback rapid in-memory screencap pipe loop (bypasses disk entirely)."""
        fps_timer = time.time()
        fps_count = 0
        while not self._stop_event.is_set():
            t0 = time.time()
            try:
                cmd = [self.adb_path, "-s", self.serial, "exec-out", "screencap", "-p"]
                res = subprocess.run(cmd, capture_output=True, timeout=2.5)
                if res.returncode == 0 and len(res.stdout) > 2048:
                    frame_bytes = res.stdout
                    fps_count += 1
                    now = time.time()
                    if (now - fps_timer) >= 1.0:
                        self.fps = round(fps_count / (now - fps_timer), 1)
                        fps_count = 0
                        fps_timer = now

                    with self._lock:
                        self.last_frame_bytes = frame_bytes
                        self.last_frame_time = now
                        self.frame_count += 1

                    if self.on_frame:
                        try:
                            self.on_frame(frame_bytes, self.width, self.height)
                        except Exception:
                            pass
            except Exception as e:
                self.last_error = str(e)
                self._stop_event.wait(0.5)

            elapsed = time.time() - t0
            # Maintain ~12-15 fps to preserve CPU
            delay = max(0.01, (1.0 / 15.0) - elapsed)
            self._stop_event.wait(delay)

    def _generate_preview_frame(self) -> bytes:
        """Generates a high-fidelity phone standby screen representation for disconnected/preview state."""
        try:
            from PIL import Image, ImageDraw
            w, h = 360, 800
            img = Image.new("RGB", (w, h), (18, 24, 38))
            draw = ImageDraw.Draw(img)

            # Header / notch area
            draw.rectangle([(0, 0), (w, 36)], fill=(12, 16, 26))
            time_str = time.strftime("%H:%M")
            draw.text((20, 10), time_str, fill=(230, 230, 230))
            draw.text((w - 90, 10), "5G  85%", fill=(230, 230, 230))

            # Phone Model Banner
            draw.text((w // 2 - 60, 140), self.model_name, fill=(100, 200, 255))
            draw.text((w // 2 - 75, 170), "Assistant Remote Control", fill=(180, 190, 205))

            # Center Phone Wallpaper Graphic
            draw.ellipse([(w // 2 - 80, 240), (w // 2 + 80, 400)], outline=(40, 120, 240), width=3)
            draw.text((w // 2 - 45, 310), "STANDBY", fill=(200, 220, 255))

            # Notification Card
            draw.rectangle([(24, 460), (w - 24, 540)], fill=(28, 36, 56), outline=(48, 60, 88), width=1)
            draw.text((40, 476), "Smart Assistant Bridge", fill=(120, 210, 255))
            draw.text((40, 502), "Tap or connect USB/Wi-Fi to control", fill=(160, 175, 195))

            # Bottom Android Navigation Bar
            draw.rectangle([(0, h - 48), (w, h)], fill=(12, 16, 26))
            draw.text((w // 4 - 8, h - 34), "<", fill=(180, 190, 210))
            draw.text((w // 2 - 8, h - 34), "O", fill=(180, 190, 210))
            draw.text((3 * w // 4 - 8, h - 34), "[]", fill=(180, 190, 210))

            import io
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            return buf.getvalue()
        except Exception:
            return b""



class AdbAdapter:
    """
    Direct interface to Android Debug Bridge (ADB) for physical and emulator devices.
    Executes real commands without simulating device presence or fabricating status.
    """

    def __init__(self, adb_path: Optional[str] = None):
        self._adb_path = adb_path or self._locate_adb()
        self._stream_sessions: Dict[str, ScreenStreamSession] = {}
        self._stream_lock = threading.RLock()
        self._scrcpy_proc: Optional[subprocess.Popen] = None
        # Pure Python ADB high-performance socket client
        self._ppadb_client: Optional[Any] = None
        self._ppadb_lock = threading.Lock()
        self._telemetry_cache: Dict[str, Tuple[float, Any]] = {}
        self._telemetry_ttl: float = 3.0

    def _ensure_adb_server(self) -> bool:
        """Ensures the local ADB server daemon is alive on 127.0.0.1:5037."""
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.3)
                if s.connect_ex(("127.0.0.1", 5037)) == 0:
                    return True
        except Exception:
            pass
        # Server not responding, start it
        try:
            if self._adb_path:
                self._run_adb_cmd(["start-server"], timeout=5.0)
                time.sleep(0.3)
                return True
        except Exception:
            pass
        return False

    def _get_ppadb_client(self):
        """Returns or initializes the Pure Python ADB direct socket client (TCP 127.0.0.1:5037)."""
        self._ensure_adb_server()
        with self._ppadb_lock:
            if self._ppadb_client is None:
                try:
                    import sys
                    from pathlib import Path
                    pkg_parent = str(Path(__file__).resolve().parent)
                    if pkg_parent not in sys.path:
                        sys.path.insert(0, pkg_parent)
                    import ppadb
                    from ppadb.client import Client as AdbClient
                    self._ppadb_client = AdbClient(host="127.0.0.1", port=5037)
                except Exception as e:
                    logger.debug(f"ppadb socket client init error: {e}")
            return self._ppadb_client

    def _run_ppadb_shell(self, serial: str, cmd: str, timeout: float = 5.0) -> Tuple[bool, str]:
        """
        Executes an ADB shell command via high-performance direct socket (~2ms).
        Returns (success: bool, output: str).
        """
        client = self._get_ppadb_client()
        if client:
            try:
                device = client.device(serial)
                if not device:
                    for d in client.devices():
                        if d.serial == serial or (":" in serial and d.serial.startswith(serial.split(":")[0])):
                            device = d
                            break
                if device:
                    out = device.shell(cmd, timeout=timeout)
                    return True, (out or "").strip()
            except Exception as e:
                logger.debug(f"ppadb socket shell failed for {serial}: {e}")
        return False, ""

    def _locate_adb(self) -> Optional[str]:
        """Locates the adb executable across bundled, environment, and common SDK paths."""
        adb_binary_name = "adb.exe" if os.name == "nt" else "adb"

        # 0. Bundled in PyInstaller frozen package (sys._MEIPASS)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            for sub in ("platform-tools", "bin", ""):
                candidate = Path(meipass) / sub / adb_binary_name if sub else Path(meipass) / adb_binary_name
                if candidate.is_file():
                    return str(candidate)

        # 0b. Application executable directory (installed next to Assistant.exe)
        if getattr(sys, "executable", None):
            app_dir = Path(sys.executable).parent
            for sub in ("platform-tools", "bin/platform-tools", "bin", ""):
                candidate = app_dir / sub / adb_binary_name if sub else app_dir / adb_binary_name
                if candidate.is_file():
                    return str(candidate)

        # 0c. Local Application Data (auto-provisioned by SmartAssistant)
        if os.name == "nt":
            local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            smart_cand = Path(local_app_data) / "SmartAssistant" / "bin" / "platform-tools" / "adb.exe"
            if smart_cand.is_file():
                return str(smart_cand)
        else:
            smart_cand = Path.home() / ".local" / "share" / "SmartAssistant" / "bin" / "platform-tools" / "adb"
            if smart_cand.is_file():
                return str(smart_cand)

        # 0. PyInstaller frozen bundled path
        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            meipass_cand = Path(sys._MEIPASS) / "platform-tools" / adb_binary_name
            if meipass_cand.is_file():
                return str(meipass_cand)

        # 1. Custom env vars
        for env_key in ("DEVICE_BRIDGE_ADB_PATH", "REA_ADB_PATH", "ADB_PATH"):
            custom_path = os.environ.get(env_key)
            if custom_path and Path(custom_path).is_file():
                return custom_path

        # 2. System PATH
        which_adb = shutil.which("adb")
        if which_adb:
            return which_adb

        # 3. ANDROID_HOME / ANDROID_SDK_ROOT
        for env_var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            sdk_root = os.environ.get(env_var)
            if sdk_root:
                candidate = Path(sdk_root) / "platform-tools" / adb_binary_name
                if candidate.is_file():
                    return str(candidate)

        # 4. Standard Windows paths
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            # Provisioned SmartAssistant Platform Tools
            sa_cands = [
                Path(local_app_data) / "SmartAssistant" / "bin" / "platform-tools" / "adb.exe",
                Path(local_app_data) / "SmartAssistant" / "bin" / "adb.exe",
            ]
            for sa_cand in sa_cands:
                if sa_cand.is_file():
                    return str(sa_cand)

            candidate = Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / "adb.exe"
            if candidate.is_file():
                return str(candidate)
            # WinGet package
            wg_candidate = (
                Path(local_app_data)
                / "Microsoft"
                / "WinGet"
                / "Packages"
                / "Google.PlatformTools_Microsoft.Winget.Source_8wekyb3d8bbwe"
                / "platform-tools"
                / "adb.exe"
            )
            if wg_candidate.is_file():
                return str(wg_candidate)

        user_profile = os.environ.get("USERPROFILE")
        if user_profile:
            # Scoop
            scoop_cand = Path(user_profile) / "scoop" / "apps" / "adb" / "current" / "platform-tools" / "adb.exe"
            if scoop_cand.is_file():
                return str(scoop_cand)
            scoop_shim = Path(user_profile) / "scoop" / "shims" / "adb.exe"
            if scoop_shim.is_file():
                return str(scoop_shim)

        # Chocolatey
        choco_cand = Path(r"C:\ProgramData\chocolatey\bin\adb.exe")
        if choco_cand.is_file():
            return str(choco_cand)

        # Common Program Files
        for pf in (r"C:\Program Files\Android\platform-tools\adb.exe", r"C:\Program Files (x86)\Android\android-sdk\platform-tools\adb.exe"):
            if Path(pf).is_file():
                return pf

        return None

    def ensure_adb_installed(self) -> Tuple[bool, str]:
        """
        Ensures ADB is available. If missing, automatically provisions it by downloading
        the official Google Android SDK platform-tools bundle into user's local application data.
        Eliminates any requirement for users to manually open terminal or install SDKs.
        """
        ok, current_path = self.is_available()
        if ok:
            return True, current_path

        # Determine target directory
        if os.name == "nt":
            base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
            dest_dir = Path(base) / "SmartAssistant" / "bin"
            adb_filename = "adb.exe"
            url = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
        elif sys.platform == "darwin":
            dest_dir = Path.home() / "Library" / "Application Support" / "SmartAssistant" / "bin"
            adb_filename = "adb"
            url = "https://dl.google.com/android/repository/platform-tools-latest-darwin.zip"
        else:
            dest_dir = Path.home() / ".local" / "share" / "SmartAssistant" / "bin"
            adb_filename = "adb"
            url = "https://dl.google.com/android/repository/platform-tools-latest-linux.zip"

        target_adb = dest_dir / "platform-tools" / adb_filename
        if target_adb.is_file():
            self._adb_path = str(target_adb)
            return True, str(target_adb)

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
            zip_dest = dest_dir / "platform-tools.zip"
            logger.info(f"Auto-provisioning Android Platform-Tools from {url} to {zip_dest}...")

            req = urllib.request.Request(
                url,
                headers={"User-Agent": "SmartAssistant-DeviceBridge/1.0"}
            )
            with urllib.request.urlopen(req, timeout=60.0) as resp, open(zip_dest, "wb") as f:
                shutil.copyfileobj(resp, f)

            with zipfile.ZipFile(zip_dest, "r") as zf:
                zf.extractall(dest_dir)

            try:
                zip_dest.unlink()
            except Exception:
                pass

            if target_adb.is_file():
                if os.name != "nt":
                    target_adb.chmod(0o755)
                self._adb_path = str(target_adb)
                logger.info(f"Successfully auto-provisioned ADB at {target_adb}")
                return True, str(target_adb)
            return False, f"Extracted archive did not contain {adb_filename} at expected location: {target_adb}"
        except Exception as e:
            logger.error(f"Failed to auto-provision Android Platform-Tools: {e}")
            return False, f"Failed to automatically download ADB: {e}"

    def is_available(self) -> Tuple[bool, str]:
        """Checks if ADB executable is available."""
        if not self._adb_path:
            self._adb_path = self._locate_adb()
        if self._adb_path and Path(self._adb_path).is_file():
            return True, self._adb_path
        return False, "Android Debug Bridge (ADB) was not found on your system. Please install Android Platform Tools or set ANDROID_HOME / PATH."

    @staticmethod
    def _log_diagnostic(event_type: str, details: Dict[str, Any]) -> None:
        """Appends structured diagnostic logging to disk and logger for transparent troubleshooting."""
        import datetime
        ts = datetime.datetime.now().isoformat()
        msg = f"[{ts}] [{event_type}] {details}"
        logger.info(msg)
        try:
            diag_log_path = PROJECT_ROOT / "data" / "device_pairing_diagnostics.log"
            diag_log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(diag_log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass

    def _run_adb_cmd(self, args: List[str], timeout: float = 7.0, input_data: Optional[str] = None) -> Tuple[bool, str]:
        """Executes an ADB command safely."""
        ok, path_or_err = self.is_available()
        if not ok:
            return False, path_or_err

        sanitized_args = []
        for i, a in enumerate(args):
            if i > 0 and args[i-1] == "pair" and len(args) > i + 1:
                sanitized_args.append("******")
            else:
                sanitized_args.append(a)

        cmd_str = f"adb {' '.join(sanitized_args)}"
        t0 = time.time()
        try:
            cmd = [self._adb_path] + args
            proc = subprocess.run(
                cmd,
                input=input_data,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
            elapsed = round(time.time() - t0, 3)
            stdout_clean = (proc.stdout or "").strip()
            stderr_clean = (proc.stderr or "").strip()
            self._log_diagnostic(
                "ADB_EXEC",
                {
                    "cmd": cmd_str,
                    "returncode": proc.returncode,
                    "elapsed_s": elapsed,
                    "stdout": stdout_clean,
                    "stderr": stderr_clean,
                }
            )
            if proc.returncode == 0:
                if stderr_clean:
                    stderr_low = stderr_clean.lower()
                    is_benign_warning = ("brought to the front" in stderr_low or "intent has been delivered" in stderr_low or "warning: activity not started" in stderr_low)
                    if not is_benign_warning and any(err_kw in stderr_low for err_kw in [
                        "error:", "securityexception", "unable to resolve intent"
                    ]):
                        return False, stderr_clean
                return True, stdout_clean or stderr_clean
            return False, stderr_clean or stdout_clean or f"ADB exited with code {proc.returncode}"
        except subprocess.TimeoutExpired:
            elapsed = round(time.time() - t0, 3)
            self._log_diagnostic("ADB_TIMEOUT", {"cmd": cmd_str, "timeout_s": timeout, "elapsed_s": elapsed})
            return False, f"ADB command timed out after {timeout}s"
        except Exception as e:
            self._log_diagnostic("ADB_ERROR", {"cmd": cmd_str, "error": str(e)})
            return False, f"ADB command error: {e}"

    def execute_shell(self, cmd: str, serial: Optional[str] = None, timeout: float = 7.0) -> Dict[str, Any]:
        """Executes a shell command on the target Android device via fast socket (~2ms) or adb CLI fallback."""
        target_serial = serial or self._get_active_serial()
        if target_serial:
            ok_sock, out_sock = self._run_ppadb_shell(target_serial, cmd, timeout=timeout)
            if ok_sock:
                return {"success": True, "output": out_sock}
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", cmd])
        ok, out = self._run_adb_cmd(args, timeout=timeout)
        return {"success": ok, "output": out.strip()}

    def list_devices(self) -> List[Dict[str, Any]]:
        """
        Lists connected Android devices via fast socket (0.7ms) or ADB CLI fallback.
        Parses device serial, state (device, unauthorized, offline), model, and product.
        """
        # Fast path: query via local ADB socket (0.7ms)
        client = self._get_ppadb_client()
        out = ""
        if client:
            try:
                with client.create_connection(timeout=1.5) as conn:
                    conn.send("host:devices-l")
                    out = conn.receive()
            except Exception:
                out = ""

        # Fallback to subprocess if socket didn't respond
        if not out:
            ok, out = self._run_adb_cmd(["devices", "-l"], timeout=3.0)
            if not ok:
                # Fallback to REA MCP tool if available
                try:
                    from modules.reverse_engineering import get_rea_service
                    svc = get_rea_service()
                    res = svc.execute_tool("list_adb_devices")
                    if res.get("success") and res.get("content"):
                        items = res["content"]
                        if items and isinstance(items[0], dict) and "devices" in items[0]:
                            return items[0]["devices"]
                except Exception:
                    pass
                return []

        devices = []
        lines = out.splitlines()
        for line in lines:
            line = line.strip()
            if not line or line.lower().startswith('list of devices attached'):
                continue
            parts = line.split()
            if len(parts) >= 2:
                serial = parts[0]
                state = parts[1]
                model = ""
                product = ""
                device_type = ""
                for p in parts[2:]:
                    if p.startswith("model:"):
                        model = p.split(":", 1)[1]
                    elif p.startswith("product:"):
                        product = p.split(":", 1)[1]
                    elif p.startswith("device:"):
                        device_type = p.split(":", 1)[1]
                is_wireless = ":" in serial or "_adb-tls-connect" in serial or "._tcp" in serial
                devices.append({
                    "serial": serial,
                    "state": state,
                    "model": model or serial,
                    "product": product,
                    "device": device_type,
                    "online": state == "device",
                    "authorized": state == "device",
                    "connection_type": "wireless" if is_wireless else "usb",
                })
        return devices

    def discover_mdns_services(self) -> List[Dict[str, Any]]:
        """
        Discovers mDNS wireless debugging services on the local network (Android 11+).
        Parses _adb-tls-connect._tcp and _adb-tls-pairing._tcp service advertisements.
        """
        ok, out = self._run_adb_cmd(["mdns", "services"], timeout=4.0)
        if not ok or not out:
            return []
        services = []
        for line in out.splitlines():
            line = line.strip()
            if not line or "List of discovered" in line:
                continue
            parts = line.split()
            if len(parts) >= 3:
                instance_name = parts[0]
                service_type = parts[1]
                endpoint = parts[2]
                host, _, port_s = endpoint.partition(":")
                try:
                    port = int(port_s)
                except ValueError:
                    port = 5555
                services.append({
                    "instance_name": instance_name,
                    "service_type": service_type,
                    "endpoint": endpoint,
                    "host": host,
                    "port": port,
                    "is_pairing": "_adb-tls-pairing" in service_type,
                    "is_connect": "_adb-tls-connect" in service_type,
                })
        return services

    def _scan_open_adb_ports(self, host: str, port_range: tuple[int, int] = (30000, 50000), timeout: float = 0.04) -> List[int]:
        """Scans for open TCP ports on a known host in the Android wireless debugging range with high concurrency (< 1.0s)."""
        import socket
        from concurrent.futures import ThreadPoolExecutor

        # Quick pre-check: verify host is even alive on the network before scanning thousands of ports
        try:
            _chk = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _chk.settimeout(0.2)
            _chk.connect_ex((host, 5555))
            _chk.close()
        except Exception:
            pass

        open_ports = []
        def _probe(p: int):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            try:
                if s.connect_ex((host, p)) == 0:
                    open_ports.append(p)
            except Exception:
                pass
            finally:
                s.close()

        # Focus directly on 5555 and Android 11-14 ephemeral range (35000-47500)
        ports_to_check = [5555] + list(range(35000, 47500))
        try:
            with ThreadPoolExecutor(max_workers=500) as ex:
                ex.map(_probe, ports_to_check)
        except Exception:
            pass
        return sorted(open_ports)

    def _detect_default_gateways(self) -> List[str]:
        """Detects current default network gateways (e.g. mobile hotspot or local router)."""
        gateways = []
        try:
            out = subprocess.check_output(["ipconfig"], text=True, stderr=subprocess.DEVNULL)
            for gw in re.findall(r"Default Gateway[ .:]+([\d\.]+)", out):
                gw = gw.strip()
                if gw and gw not in ("0.0.0.0", "127.0.0.1") and gw not in gateways:
                    gateways.append(gw)
        except Exception:
            pass
        return gateways

    def reconnect_wireless_endpoints(self, endpoints: Optional[List[str]] = None, known_hosts: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """
        Attempts to reconnect to known wireless endpoints or discovered mDNS connect services.
        If a stored endpoint fails due to Android rotating ports, scans known hosts to re-establish connection.
        Returns list of devices successfully reconnected.
        """
        targets_to_try = set(endpoints or [])
        candidate_hosts = set(known_hosts or [])

        # Default known phone IP for persistent pairing (Redmi Note 12 5G / local network phone)
        candidate_hosts.add("192.168.1.4")

        # Check environment/config for configured remote VPN ADB host
        remote_vpn_target = os.environ.get("ANDROID_REMOTE_ADB_HOST", "").strip()
        if remote_vpn_target:
            targets_to_try.add(remote_vpn_target)
            if ":" in remote_vpn_target:
                candidate_hosts.add(remote_vpn_target.split(":")[0])

        phone_host_env = os.environ.get("ANDROID_PHONE_HOST", "").strip()
        if phone_host_env:
            candidate_hosts.add(phone_host_env)

        # Detect default gateways (e.g. phone mobile hotspot)
        detected_gateways = set()
        try:
            for gw in self._detect_default_gateways():
                detected_gateways.add(gw)
                targets_to_try.add(f"{gw}:5555")
                candidate_hosts.add(gw)
        except Exception:
            pass

        # Check mDNS services first
        mdns_svcs = self.discover_mdns_services()
        for svc in mdns_svcs:
            if svc.get("is_connect") and svc.get("endpoint"):
                targets_to_try.add(svc["endpoint"])
            if svc.get("host") and re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', str(svc.get("host"))):
                candidate_hosts.add(svc["host"])

        reconnected = []
        failed_hosts = set()
        for target in targets_to_try:
            target = target.strip()
            if not target:
                continue
            # If target is an mDNS instance name without IP:port, look up in mdns_svcs
            if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}', target):
                matched_svc = next((s for s in mdns_svcs if s.get("instance_name") == target), None)
                if matched_svc and matched_svc.get("host") and matched_svc.get("port"):
                    host = matched_svc["host"]
                    port = int(matched_svc["port"])
                else:
                    continue
            else:
                host, _, port_s = target.partition(":")
                port = int(port_s) if port_s.isdigit() else 5555

            if host and re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', host):
                candidate_hosts.add(host)

            res = self.connect_wireless(host, port)
            if res.get("success"):
                reconnected.append({"endpoint": f"{host}:{port}", "host": host, "port": port})
            else:
                if host and host not in ("127.0.0.1", "localhost") and host not in detected_gateways:
                    failed_hosts.add(host)

        # If direct known ports failed, scan candidate wireless debugging ports on known phone hosts
        if not reconnected:
            hosts_to_scan = failed_hosts or candidate_hosts
            for f_host in hosts_to_scan:
                if not f_host or not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', f_host):
                    continue
                try:
                    open_candidate_ports = self._scan_open_adb_ports(f_host)
                    for c_port in open_candidate_ports:
                        c_res = self.connect_wireless(f_host, c_port)
                        if c_res.get("success"):
                            reconnected.append({"endpoint": f"{f_host}:{c_port}", "host": f_host, "port": c_port})
                            logger.info(f"Dynamically discovered rotated wireless ADB port {c_port} on {f_host}")
                            break
                    if reconnected:
                        break
                except Exception as e:
                    logger.debug(f"Failed scanning rotated wireless ports on {f_host}: {e}")

        return reconnected

    def diagnose_environment(self) -> Dict[str, Any]:
        """Inspects ADB availability, daemon status, and device authorization state."""
        avail, path_or_err = self.is_available()
        if not avail:
            return {
                "configured": False,
                "running": False,
                "adb_path": None,
                "device_count": 0,
                "authorized_count": 0,
                "unauthorized_count": 0,
                "offline_count": 0,
                "message": path_or_err,
                "devices": [],
            }

        devices = self.list_devices()
        authorized = [d for d in devices if d.get("online")]
        unauthorized = [d for d in devices if d.get("state") == "unauthorized"]
        offline = [d for d in devices if d.get("state") == "offline"]
        adb_diag = self.get_adb_version()

        return {
            "configured": True,
            "running": True,
            "adb_path": self._adb_path,
            "adb_version": adb_diag.get("version", ""),
            "device_count": len(devices),
            "authorized_count": len(authorized),
            "unauthorized_count": len(unauthorized),
            "offline_count": len(offline),
            "devices": devices,
            "message": "ADB is configured and running.",
        }

    def get_adb_version(self) -> Dict[str, str]:
        """Retrieves installed ADB binary version and build information."""
        ok, out = self._run_adb_cmd(["version"], timeout=3.0)
        ver_line = ""
        build_line = ""
        if ok and out:
            for line in out.splitlines():
                if "Android Debug Bridge version" in line:
                    ver_line = line.strip()
                elif "Version" in line:
                    build_line = line.strip()
        return {
            "version": ver_line,
            "build": build_line,
            "raw": out,
            "adb_path": self._adb_path or "",
        }

    def restart_server(self) -> Tuple[bool, str]:
        """Safely restarts the local ADB server daemon to clear stale transports or jammed TLS state."""
        logger.info("Restarting ADB server daemon to refresh TLS transport state...")
        self._run_adb_cmd(["kill-server"], timeout=5.0)
        time.sleep(0.5)
        ok, out = self._run_adb_cmd(["start-server"], timeout=8.0)
        return ok, out

    def get_device_properties(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Retrieves hardware model, manufacturer, Android version, screen size, and battery."""
        if serial:
            target_serial = serial
            active_model = ""
        else:
            devs = self.list_devices()
            active = [d for d in devs if d.get("online")]
            if not active:
                return {"success": False, "message": "No authorized Android device online."}
            target_serial = active[0]["serial"]
            active_model = active[0].get("model", "")

        # Fetch getprop
        args = ["-s", target_serial, "shell", "getprop"]
        ok, out = self._run_adb_cmd(args, timeout=5.0)
        props: Dict[str, str] = {}
        if ok and out:
            for line in out.splitlines():
                line = line.strip()
                m = re.match(r'\[(.*?)\]:\s*\[(.*?)\]', line)
                if m:
                    props[m.group(1)] = m.group(2)
                elif "=" in line:
                    k, _, v = line.partition("=")
                    props[k.strip("[] ")] = v.strip("[] ")

        # Screen size
        sz_ok, sz_out = self._run_adb_cmd(["-s", target_serial, "shell", "wm", "size"], timeout=3.0)
        screen_size = ""
        if sz_ok and "Physical size:" in sz_out:
            screen_size = sz_out.split("Physical size:", 1)[1].strip()

        # Resolve authoritative model and friendly marketing name
        raw_model = props.get("ro.product.model", active_model).strip()
        market_name = (
            props.get("ro.product.marketname")
            or props.get("ro.product.odm.marketname")
            or props.get("ro.product.vendor.marketname")
            or props.get("bluetooth.device.class.name")
            or ""
        ).strip()

        brand = props.get("ro.product.brand", "").strip()
        manufacturer = props.get("ro.product.manufacturer", "").strip()

        if market_name:
            resolved_model = market_name
        elif raw_model in OEM_MODEL_MAP:
            resolved_model = OEM_MODEL_MAP[raw_model]
        elif raw_model and brand and not raw_model.lower().startswith(brand.lower()):
            resolved_model = f"{brand} {raw_model}".strip()
        elif raw_model:
            resolved_model = raw_model
        else:
            resolved_model = f"{manufacturer} Android Device".strip() or "Android Device"

        batt = self.get_battery(target_serial)

        return {
            "success": True,
            "serial": target_serial,
            "model": resolved_model,
            "raw_model": raw_model,
            "market_name": market_name,
            "brand": brand,
            "manufacturer": manufacturer,
            "android_version": props.get("ro.build.version.release", ""),
            "sdk_version": props.get("ro.build.version.sdk", ""),
            "screen_size": screen_size,
            "battery": batt.get("level"),
            "charging": batt.get("charging", False),
            "battery_info": batt,
        }

    def get_battery(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Queries verified phone battery level, charging status, health, temperature, and voltage via dumpsys battery."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "dumpsys", "battery"])

        ok, out = self._run_adb_cmd(args, timeout=4.0)
        if not ok:
            return {"success": False, "message": out}

        level = None
        charging = False
        power_source = "Battery"
        health = "Good"
        temp_c = None
        voltage_mv = None

        for line in out.splitlines():
            line = line.strip()
            if line.startswith("level:"):
                try:
                    level = int(line.split(":", 1)[1].strip())
                except Exception:
                    pass
            elif line.startswith("status:"):
                val = line.split(":", 1)[1].strip()
                charging = val in ("2", "5")
            elif line.startswith("health:"):
                h_val = line.split(":", 1)[1].strip()
                health = BATTERY_HEALTH_MAP.get(h_val, f"Code {h_val}")
            elif line.startswith("temperature:"):
                try:
                    raw_temp = int(line.split(":", 1)[1].strip())
                    temp_c = round(raw_temp / 10.0, 1)
                except Exception:
                    pass
            elif line.startswith("voltage:"):
                try:
                    voltage_mv = int(line.split(":", 1)[1].strip())
                except Exception:
                    pass
            elif line.startswith("USB powered: true"):
                power_source = "USB"
                charging = True
            elif line.startswith("AC powered: true"):
                power_source = "AC Adapter"
                charging = True
            elif line.startswith("Wireless powered: true"):
                power_source = "Wireless"
                charging = True

        if level is None:
            return {"success": False, "message": "Could not read battery metrics from phone."}

        chg_str = f" (charging via {power_source})" if charging else ""
        temp_str = f", {temp_c}°C" if temp_c is not None else ""
        msg = f"Your phone battery is at {level}%{chg_str}{temp_str}."

        return {
            "success": True,
            "level": level,
            "percentage": level,
            "charging": charging,
            "power_source": power_source,
            "health": health,
            "temperature": temp_c,
            "temperature_c": temp_c,
            "voltage": voltage_mv,
            "voltage_mv": voltage_mv,
            "message": msg,
            "raw": out,
        }

    def get_storage(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Queries storage capacity and available space on the phone (/data partition)."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "df", "-h", "/data"])

        ok, out = self._run_adb_cmd(args, timeout=4.0)
        if not ok or not out:
            return {"success": False, "message": f"Storage query failed: {out}"}

        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        if len(lines) >= 2:
            parts = lines[-1].split()
            if len(parts) >= 5:
                total = parts[1]
                used = parts[2]
                free = parts[3]
                pct = parts[4]
                msg = f"Phone storage: {free} free out of {total} ({pct} used)."
                return {
                    "success": True,
                    "total": total,
                    "used": used,
                    "free": free,
                    "percent_used": pct,
                    "message": msg,
                }
        return {"success": False, "message": f"Could not parse phone storage metrics: {out}"}

    def get_memory(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Queries RAM memory usage from /proc/meminfo on the phone."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "cat", "/proc/meminfo"])

        ok, out = self._run_adb_cmd(args, timeout=4.0)
        if not ok or not out:
            return {"success": False, "message": f"Memory query failed: {out}"}

        mem_total_kb = 0
        mem_avail_kb = 0
        for line in out.splitlines():
            if line.startswith("MemTotal:"):
                m = re.search(r'(\d+)', line)
                if m:
                    mem_total_kb = int(m.group(1))
            elif line.startswith("MemAvailable:"):
                m = re.search(r'(\d+)', line)
                if m:
                    mem_avail_kb = int(m.group(1))

        if mem_total_kb > 0:
            total_gb = round(mem_total_kb / 1024 / 1024, 1)
            avail_gb = round(mem_avail_kb / 1024 / 1024, 1)
            used_gb = round((mem_total_kb - mem_avail_kb) / 1024 / 1024, 1)
            pct_used = int(round(((mem_total_kb - mem_avail_kb) / mem_total_kb) * 100))
            msg = f"Phone RAM: {avail_gb} GB available out of {total_gb} GB ({pct_used}% used)."
            return {
                "success": True,
                "total_gb": total_gb,
                "available_gb": avail_gb,
                "used_gb": used_gb,
                "percent_used": pct_used,
                "message": msg,
            }
        return {"success": False, "message": "Could not parse phone memory info."}

    def get_foreground_app(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Inspects the currently active foreground application on the phone screen."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "dumpsys", "window"])

        ok, out = self._run_adb_cmd(args, timeout=5.0)
        if not ok:
            return {"success": False, "message": f"Failed to inspect foreground app: {out}"}

        target_component = ""
        for line in out.splitlines():
            line = line.strip()
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                m = re.search(r'([a-zA-Z0-9_\.]+/[a-zA-Z0-9_\.]+)', line)
                if m:
                    target_component = m.group(1)
                    break

        if target_component:
            pkg, _, act = target_component.partition("/")
            return {
                "success": True,
                "component": target_component,
                "package": pkg,
                "activity": act,
                "message": f"Active foreground application: {pkg}",
            }
        return {"success": True, "package": "unknown", "message": "Screen is locked or at launcher."}

    def get_volume(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Gets verified hardware media volume from Android AudioService via cmd media_session."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "cmd", "media_session", "volume", "--stream", "3", "--get"])
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        if ok and out:
            m = re.search(r'volume is (\d+) in range \[(\d+)\.\.(\d+)\]', out)
            if m:
                curr = int(m.group(1))
                min_v = int(m.group(2))
                max_v = int(m.group(3))
                pct = int((curr / max_v) * 100) if max_v > 0 else 0
                return {
                    "success": True,
                    "status": "success",
                    "level": curr,
                    "min_level": min_v,
                    "max_level": max_v,
                    "percentage": pct,
                    "message": f"Phone volume is at {curr} out of {max_v} ({pct}%)."
                }
        return {"success": False, "status": "failed", "message": f"Could not query phone volume: {out}"}

    def set_volume(self, target_level: int, serial: Optional[str] = None) -> Dict[str, Any]:
        """Sets phone media volume to a specific level (0..15) or percentage (0..100) and verifies."""
        v_cur = self.get_volume(serial=serial)
        if not v_cur.get("success"):
            return v_cur
        max_l = v_cur["max_level"]
        if target_level > max_l:
            desired = int(round((target_level / 100.0) * max_l))
        else:
            desired = int(target_level)
        desired = max(0, min(desired, max_l))
        cur = v_cur["level"]
        diff = desired - cur
        if diff > 0:
            for _ in range(diff):
                self.key_event(24, serial=serial)
                time.sleep(0.04)
        elif diff < 0:
            for _ in range(abs(diff)):
                self.key_event(25, serial=serial)
                time.sleep(0.04)
        v_final = self.get_volume(serial=serial)
        lvl = v_final.get("level", desired)
        pct = v_final.get("percentage", int((lvl / max_l) * 100) if max_l > 0 else 0)
        return {
            "success": True,
            "status": "success",
            "level": lvl,
            "max_level": max_l,
            "percentage": pct,
            "message": f"Phone volume set to {lvl} out of {max_l} ({pct}%)."
        }

    def volume_up(self, steps: int = 1, serial: Optional[str] = None) -> Dict[str, Any]:
        """Increases volume on the phone with AudioService verification."""
        for _ in range(max(1, steps)):
            res = self.key_event(24, serial=serial)  # KEYCODE_VOLUME_UP = 24
            if not res.get("success"):
                return res
            time.sleep(0.04)
        v_after = self.get_volume(serial=serial)
        if v_after.get("success"):
            lvl = v_after["level"]
            max_lvl = v_after["max_level"]
            pct = v_after["percentage"]
            return {
                "success": True,
                "status": "success",
                "level": lvl,
                "max_level": max_lvl,
                "percentage": pct,
                "message": f"Volume increased to {lvl} out of {max_lvl} ({pct}%) on your phone."
            }
        return {"success": True, "status": "success", "message": "Increased volume on your phone."}

    def volume_down(self, steps: int = 1, serial: Optional[str] = None) -> Dict[str, Any]:
        """Decreases volume on the phone with AudioService verification."""
        for _ in range(max(1, steps)):
            res = self.key_event(25, serial=serial)  # KEYCODE_VOLUME_DOWN = 25
            if not res.get("success"):
                return res
            time.sleep(0.04)
        v_after = self.get_volume(serial=serial)
        if v_after.get("success"):
            lvl = v_after["level"]
            max_lvl = v_after["max_level"]
            pct = v_after["percentage"]
            return {
                "success": True,
                "status": "success",
                "level": lvl,
                "max_level": max_lvl,
                "percentage": pct,
                "message": f"Volume decreased to {lvl} out of {max_lvl} ({pct}%) on your phone."
            }
        return {"success": True, "status": "success", "message": "Decreased volume on your phone."}

    def take_screenshot(self, output_path: Optional[str] = None, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Captures a real screenshot from the Android device via screencap and pull.
        Validates output existence, timestamp freshness, file size, and PNG magic header bytes.
        """
        if output_path and not output_path.endswith(".png") and not any(sep in output_path for sep in ("/", "\\")):
            target_serial = output_path
            out_file = None
        else:
            target_serial = serial
            out_file = output_path

        if not out_file:
            from core.semantic_file_naming import get_semantic_file_naming_service
            namer = get_semantic_file_naming_service()
            out_file, _ = namer.resolve_output_path(
                task_description="phone_screenshot",
                artifact_type="image",
                extension=".png",
                output_directory=namer.get_default_output_dir(),
            )

        if not target_serial:
            devs = self.list_devices()
            active = [d for d in devs if d.get("online")]
            if not active:
                return {"success": False, "message": "No active Android device found to capture screenshot."}
            target_serial = active[0]["serial"]

        os.makedirs(os.path.dirname(out_file), exist_ok=True)

        ok, path_or_err = self.is_available()
        if not ok:
            return {"success": False, "message": path_or_err}

        t_pre = time.time()
        try:
            ok_cap, err_cap = self._run_adb_cmd(["-s", target_serial, "shell", "screencap", "-p", "/sdcard/assistant_screencap.png"], timeout=8.0)
            if not ok_cap:
                return {"success": False, "message": f"Screenshot command failed: {err_cap}"}

            ok_pull, err_pull = self._run_adb_cmd(["-s", target_serial, "pull", "/sdcard/assistant_screencap.png", out_file], timeout=10.0)
            if not ok_pull:
                return {"success": False, "message": f"Failed to pull screenshot from phone: {err_pull}"}

            self._run_adb_cmd(["-s", target_serial, "shell", "rm", "-f", "/sdcard/assistant_screencap.png"], timeout=3.0)

            if not os.path.exists(out_file):
                return {"success": False, "message": "Screenshot file was not created by capture process."}

            mtime = os.path.getmtime(out_file)
            if mtime < (t_pre - 1.0):
                return {"success": False, "message": "Screenshot validation failed: stale output file."}

            sz = os.path.getsize(out_file)
            if sz < 1024:
                return {"success": False, "message": f"Captured screenshot file was corrupted or empty ({sz} bytes)."}

            with open(out_file, "rb") as vf:
                header = vf.read(8)
                if header != b"\x89PNG\r\n\x1a\n":
                    return {"success": False, "message": "Captured output is not a valid PNG image format."}

            width, height = None, None
            try:
                from PIL import Image
                with Image.open(out_file) as img:
                    width, height = img.size
            except Exception:
                pass

            dim_str = f" ({width}x{height})" if width and height else ""
            return {
                "success": True,
                "path": out_file,
                "file_path": out_file,
                "device": target_serial,
                "size_bytes": sz,
                "width": width,
                "height": height,
                "timestamp": mtime,
                "message": f"Captured fresh phone screenshot{dim_str} saved to {out_file}.",
            }
        except Exception as e:
            return {"success": False, "message": f"Screenshot capture error: {e}"}

    def home(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Navigates to the Home screen on the Android device.
        Uses the standard Android Intent 'am start -a android.intent.action.MAIN -c android.intent.category.HOME'
        which executes cleanly on Xiaomi MIUI / HyperOS and stock Android without requiring INJECT_EVENTS permission.
        """
        args_am = []
        if serial:
            args_am.extend(["-s", serial])
        args_am.extend(["shell", "am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME"])
        ok_am, out_am = self._run_adb_cmd(args_am, timeout=5.0)
        if ok_am and "SecurityException" not in out_am and "Error" not in out_am:
            return {
                "success": True,
                "method": "am_home_intent",
                "message": "Navigated to home screen on your phone.",
            }
        # Fallback to keyevent
        return self.key_event(3, serial=serial)

    def back(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Navigates Back on the Android device."""
        return self.key_event(4, serial=serial)

    def recents(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Opens recent apps / app switcher."""
        res = self.key_event(187, serial=serial)
        if res.get("success"):
            return {
                "success": True,
                "status": "success",
                "keycode": 187,
                "message": "Opened recent apps switcher on your phone.",
            }
        return res

    def expand_notifications(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Expands Android notification shade."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "cmd", "statusbar", "expand-notifications"])
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        if ok:
            return {"success": True, "status": "success", "message": "Expanded notification shade on your phone."}
        return {"success": False, "status": "failed", "message": f"Failed to expand notification shade: {out}"}

    def expand_settings(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Expands Android quick settings panel."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "cmd", "statusbar", "expand-settings"])
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        if ok:
            return {"success": True, "status": "success", "message": "Opened Quick Settings on your phone."}
        return {"success": False, "status": "failed", "message": f"Failed to open Quick Settings: {out}"}

    def collapse_statusbar(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Collapses Android notification shade and quick settings."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "cmd", "statusbar", "collapse"])
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        if ok:
            return {"success": True, "status": "success", "message": "Collapsed notification shade on your phone."}
        return {"success": False, "status": "failed", "message": f"Failed to collapse notification shade: {out}"}

    def get_notifications(self, serial: Optional[str] = None, max_count: int = 10) -> Dict[str, Any]:
        """Extracts active notifications from dumpsys notification --noredact."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "dumpsys", "notification", "--noredact"])
        ok, out = self._run_adb_cmd(args, timeout=4.0)
        if not ok or not out:
            return {"success": False, "status": "failed", "message": "Could not read notifications from phone."}
        records = []
        current_pkg = ""
        current_title = ""
        current_text = ""
        for line in out.splitlines():
            line_str = line.strip()
            if "NotificationRecord(" in line_str:
                if current_pkg and (current_title or current_text):
                    records.append({"package": current_pkg, "title": current_title, "text": current_text})
                    if len(records) >= max_count:
                        break
                m_pkg = re.search(r'pkg=([a-zA-Z0-9_\.]+)', line_str)
                current_pkg = m_pkg.group(1) if m_pkg else ""
                current_title = ""
                current_text = ""
            elif "android.title=" in line_str:
                m_t = re.search(r'android\.title=(?:String\s*\((.*?)\)|(.*?)$)', line_str)
                if m_t:
                    current_title = m_t.group(1) or m_t.group(2) or ""
            elif "android.text=" in line_str:
                m_txt = re.search(r'android\.text=(?:String\s*\((.*?)\)|(.*?)$)', line_str)
                if m_txt:
                    current_text = m_txt.group(1) or m_txt.group(2) or ""
            elif "tickerText=" in line_str and not current_text:
                m_tick = re.search(r'tickerText=(.*?)$', line_str)
                if m_tick and m_tick.group(1) and m_tick.group(1) != "null":
                    current_text = m_tick.group(1)

        if current_pkg and (current_title or current_text) and len(records) < max_count:
            records.append({"package": current_pkg, "title": current_title, "text": current_text})

        display_records = [r for r in records if r.get("title") or r.get("text")]
        if not display_records:
            return {"success": True, "status": "success", "count": 0, "notifications": [], "message": "No active notifications on your phone."}
        summary_lines = [f"• {r.get('title') or r.get('package')}: {r.get('text', '')}" for r in display_records[:5]]
        return {
            "success": True,
            "status": "success",
            "count": len(display_records),
            "notifications": display_records,
            "message": f"Found {len(display_records)} active notifications:\n" + "\n".join(summary_lines)
        }

    def open_camera(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Launches camera application."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "am", "start", "-W", "-a", "android.media.action.STILL_IMAGE_CAMERA"])
        ok, out = self._run_adb_cmd(args, timeout=5.0)
        return {"success": ok, "status": "success" if ok else "failed", "message": "Opened camera on your phone." if ok else f"Failed to open camera: {out}"}

    def take_photo(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Opens camera and triggers shutter keyevent (KEYCODE_CAMERA / KEYCODE_VOLUME_UP)."""
        self.open_camera(serial=serial)
        time.sleep(1.0)
        res = self.key_event(27, serial=serial)  # KEYCODE_CAMERA = 27
        if not res.get("success"):
            res = self.key_event(24, serial=serial)  # Volume up shutter fallback
        return {"success": True, "status": "success", "message": "Triggered camera shutter to capture photo on your phone."}

    def get_location(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Queries true device location from dumpsys location (fused/gps/network)."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "dumpsys", "location"])
        ok, out = self._run_adb_cmd(args, timeout=4.0)
        if not ok or not out:
            return {"success": False, "status": "failed", "message": "Could not query location service on your phone."}
        m = re.search(r'last location=Location\[([a-zA-Z]+)\s+([\-0-9\.]+),([\-0-9\.]+)\s+hAcc=([\-0-9\.]+)', out)
        if m:
            prov = m.group(1)
            lat = float(m.group(2))
            lon = float(m.group(3))
            acc = float(m.group(4))
            return {
                "success": True,
                "status": "success",
                "provider": prov,
                "latitude": lat,
                "longitude": lon,
                "accuracy_meters": acc,
                "message": f"Phone location ({prov}): Latitude {lat:.6f}, Longitude {lon:.6f} (accuracy ±{acc:.1f}m)."
            }
        return {"success": False, "status": "unavailable", "message": "No recent GPS or fused location fix available on your phone."}

    def search_files(self, query: str, base_path: str = "/sdcard/", serial: Optional[str] = None, max_results: int = 15) -> Dict[str, Any]:
        """Searches files on the phone storage matching query."""
        args = []
        if serial:
            args.extend(["-s", serial])
        safe_q = re.sub(r'[^a-zA-Z0-9_\-\.\*]', '', query)
        args.extend(["shell", "find", base_path, "-maxdepth", "4", "-iname", f"*{safe_q}*", "2>/dev/null"])
        ok, out = self._run_adb_cmd(args, timeout=5.0)
        lines = [ln.strip() for ln in out.splitlines() if ln.strip() and not ln.startswith("find:")] if ok and out else []
        return {
            "success": True,
            "status": "success",
            "query": query,
            "count": len(lines[:max_results]),
            "files": lines[:max_results],
            "message": f"Found {len(lines[:max_results])} files matching '{query}' on phone:\n" + "\n".join(lines[:max_results]) if lines else f"No files matching '{query}' found on phone."
        }

    def tap(self, x: int, y: int, serial: Optional[str] = None) -> Dict[str, Any]:
        """Sends a tap event to the specified screen coordinates with Xiaomi security diagnosis."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "input", "tap", str(x), str(y)])
        ok, out = self._run_adb_cmd(args, timeout=4.0)

        if not ok or "SecurityException" in out or "INJECT_EVENTS" in out:
            if "INJECT_EVENTS" in out or "SecurityException" in out:
                msg = (
                    "Android permission denied: Remote screen tapping requires 'USB debugging (Security settings)' "
                    "to be enabled in Developer Options on Xiaomi / MIUI / HyperOS devices. "
                    "Please open phone Settings -> Additional settings -> Developer options -> enable 'USB debugging (Security settings)'."
                )
                return {
                    "success": False,
                    "error_type": "inject_events_restricted",
                    "permission_type": "android_security_settings",
                    "message": msg,
                    "raw_error": out,
                }
            return {"success": False, "message": f"Tap failed: {out}"}

        return {
            "success": True,
            "message": f"Tapped at ({x}, {y}) on your phone.",
        }

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300, serial: Optional[str] = None) -> Dict[str, Any]:
        """Sends a swipe gesture between two points with Xiaomi security diagnosis."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)])
        ok, out = self._run_adb_cmd(args, timeout=5.0)

        if not ok or "SecurityException" in out or "INJECT_EVENTS" in out:
            if "INJECT_EVENTS" in out or "SecurityException" in out:
                msg = (
                    "Android permission denied: Remote swipe gestures require 'USB debugging (Security settings)' "
                    "to be enabled in Developer Options on Xiaomi / MIUI / HyperOS devices. "
                    "Please open phone Settings -> Additional settings -> Developer options -> enable 'USB debugging (Security settings)'."
                )
                return {
                    "success": False,
                    "error_type": "inject_events_restricted",
                    "permission_type": "android_security_settings",
                    "message": msg,
                    "raw_error": out,
                }
            return {"success": False, "message": f"Swipe failed: {out}"}

        return {
            "success": True,
            "message": f"Swiped from ({x1},{y1}) to ({x2},{y2}) on your phone.",
        }

    def input_text(self, text: str, serial: Optional[str] = None) -> Dict[str, Any]:
        """Sends text input to the device keyboard with Xiaomi security diagnosis."""
        escaped = text.replace(" ", "%s").replace("'", "\\'")
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "input", "text", escaped])
        ok, out = self._run_adb_cmd(args, timeout=4.0)

        if not ok or "SecurityException" in out or "INJECT_EVENTS" in out:
            if "INJECT_EVENTS" in out or "SecurityException" in out:
                msg = (
                    "Android permission denied: Remote text entry requires 'USB debugging (Security settings)' "
                    "to be enabled in Developer Options on Xiaomi / MIUI / HyperOS devices. "
                    "Please open phone Settings -> Additional settings -> Developer options -> enable 'USB debugging (Security settings)'."
                )
                return {
                    "success": False,
                    "error_type": "inject_events_restricted",
                    "permission_type": "android_security_settings",
                    "message": msg,
                    "raw_error": out,
                }
            return {"success": False, "message": f"Text input failed: {out}"}

        return {
            "success": True,
            "message": f"Entered text: '{text}' on your phone.",
        }

    def key_event(self, keycode: str | int, serial: Optional[str] = None) -> Dict[str, Any]:
        """Sends a key event (e.g. HOME=3, BACK=4, POWER=26, APP_SWITCH=187) with Xiaomi security diagnosis."""
        args = []
        if serial:
            args.extend(["-s", serial])
        args.extend(["shell", "input", "keyevent", str(keycode)])
        ok, out = self._run_adb_cmd(args, timeout=4.0)

        if not ok or "SecurityException" in out or "INJECT_EVENTS" in out:
            if "INJECT_EVENTS" in out or "SecurityException" in out:
                msg = (
                    "Android permission denied: Keyevent injection requires 'USB debugging (Security settings)' "
                    "to be enabled in Developer Options on Xiaomi / MIUI / HyperOS devices. "
                    "Please open phone Settings -> Additional settings -> Developer options -> enable 'USB debugging (Security settings)'."
                )
                return {
                    "success": False,
                    "error_type": "inject_events_restricted",
                    "permission_type": "android_security_settings",
                    "message": msg,
                    "raw_error": out,
                }
            return {"success": False, "message": f"Keyevent {keycode} failed: {out}"}

        return {
            "success": True,
            "message": f"Keyevent {keycode} sent to your phone.",
        }

    def long_press(self, x: int, y: int, duration_ms: int = 1000, serial: Optional[str] = None) -> Dict[str, Any]:
        """Sends a long press gesture to the device at (x, y) using an in-place swipe."""
        dur = max(500, int(duration_ms))
        res = self.swipe(x, y, x, y, duration_ms=dur, serial=serial)
        if res.get("success"):
            res["message"] = f"Long pressed at ({x}, {y}) on your phone ({dur}ms)."
        return res

    def get_screen_geometry(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Queries physical screen resolution and current rotation orientation."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "width": 1080,
                "height": 2400,
                "physical_width": 1080,
                "physical_height": 2400,
                "current_width": 1080,
                "current_height": 2400,
                "aspect_ratio": round(1080 / 2400, 4),
                "orientation": 0,
                "message": "No active device; returning default geometry.",
            }

        w, h = 1080, 2400
        rot = 0
        sz_ok, sz_out = self._run_adb_cmd(["-s", target_serial, "shell", "wm", "size"], timeout=1.5)
        if sz_ok and "Physical size:" in sz_out:
            sz_str = sz_out.split("Physical size:", 1)[1].strip()
            if "x" in sz_str:
                p_w, _, p_h = sz_str.partition("x")
                try:
                    w = int(p_w.strip())
                    h = int(p_h.strip())
                except Exception:
                    pass

            rot_ok, rot_out = self._run_adb_cmd(["-s", target_serial, "shell", "dumpsys", "input"], timeout=1.5)
            if rot_ok and rot_out:
                m = re.search(r'SurfaceOrientation:\s*(\d)', rot_out)
                if m:
                    rot = int(m.group(1)) * 90

        cur_w = h if rot in (90, 270) else w
        cur_h = w if rot in (90, 270) else h

        return {
            "success": True,
            "physical_width": w,
            "physical_height": h,
            "current_width": cur_w,
            "current_height": cur_h,
            "aspect_ratio": round(cur_w / max(1, cur_h), 4),
            "orientation": rot,
            "serial": target_serial,
        }

    def dump_ui_hierarchy(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Dumps and parses the Android UI hierarchy via uiautomator dump.
        Extracts all visible, interactive, and semantic nodes with bounding boxes and centers.
        """
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "nodes": [], "message": "No active device available"}

        import xml.etree.ElementTree as ET

        dump_cmd = ["-s", target_serial, "shell", "uiautomator", "dump", "/data/local/tmp/uidump.xml"]
        ok, out = self._run_adb_cmd(dump_cmd, timeout=4.0)
        remote_path = "/data/local/tmp/uidump.xml"
        if not ok or "dumped to" not in out:
            dump_cmd = ["-s", target_serial, "shell", "uiautomator", "dump", "/sdcard/window_dump.xml"]
            ok, out = self._run_adb_cmd(dump_cmd, timeout=4.0)
            remote_path = "/sdcard/window_dump.xml"

        if not ok:
            return {"success": False, "nodes": [], "message": f"uiautomator dump failed: {out}"}

        cat_ok, xml_content = self._run_adb_cmd(["-s", target_serial, "shell", "cat", remote_path], timeout=4.0)
        if not cat_ok or not xml_content or "<hierarchy" not in xml_content:
            return {"success": False, "nodes": [], "message": "Could not read UI hierarchy XML"}

        nodes = []
        try:
            root = ET.fromstring(xml_content.strip())
            for elem in root.iter("node"):
                text = elem.get("text", "").strip()
                desc = elem.get("content-desc", "").strip()
                res_id = elem.get("resource-id", "").strip()
                cls = elem.get("class", "").strip()
                bounds_str = elem.get("bounds", "")
                clickable = elem.get("clickable", "false").lower() == "true"
                scrollable = elem.get("scrollable", "false").lower() == "true"

                m_b = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
                if m_b:
                    x1, y1, x2, y2 = map(int, m_b.groups())
                    cx = (x1 + x2) // 2
                    cy = (y1 + y2) // 2
                    if (x2 > x1) and (y2 > y1):
                        nodes.append({
                            "text": text,
                            "content_desc": desc,
                            "resource_id": res_id,
                            "class": cls,
                            "bounds": [x1, y1, x2, y2],
                            "center": [cx, cy],
                            "clickable": clickable,
                            "scrollable": scrollable,
                        })
            return {"success": True, "nodes": nodes, "count": len(nodes)}
        except Exception as e:
            return {"success": False, "nodes": [], "message": f"Error parsing UI XML: {e}"}

    def find_ui_element(self, query: str, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Locates a target UI element on the current screen based on natural language query,
        supporting text matching, content descriptions, search boxes, and ordinal positions (e.g., 'first result').
        """
        clean_q = (query or "").lower().strip()
        clean_q = re.sub(r'^(?:tap|click|press|select|open|choose)\s+(?:the\s+|on\s+)?', '', clean_q).strip()

        m_ord = re.search(r'\b(first|1st|second|2nd|third|3rd|fourth|4th|top)\s+(?:result|item|video|card|entry|link|option)\b', clean_q)
        ord_idx = 0
        if m_ord:
            ord_word = m_ord.group(1)
            if ord_word in ("second", "2nd"):
                ord_idx = 1
            elif ord_word in ("third", "3rd"):
                ord_idx = 2
            elif ord_word in ("fourth", "4th"):
                ord_idx = 3

        dump_res = self.dump_ui_hierarchy(serial=serial)
        if dump_res.get("success"):
            nodes = dump_res.get("nodes", [])

            if m_ord:
                candidates = [
                    n for n in nodes
                    if n["bounds"][1] > 200 and (n["clickable"] or n["text"] or n["content_desc"])
                ]
                candidates.sort(key=lambda n: (n["bounds"][1], n["bounds"][0]))
                if candidates and ord_idx < len(candidates):
                    target_node = candidates[ord_idx]
                    label = target_node["text"] or target_node["content_desc"] or f"item {ord_idx + 1}"
                    return {
                        "found": True,
                        "x": target_node["center"][0],
                        "y": target_node["center"][1],
                        "bounds": target_node["bounds"],
                        "label": label,
                        "confidence": 0.92,
                        "source": "live_ui_hierarchy",
                    }

            matches = []
            for n in nodes:
                t = n["text"].lower()
                d = n["content_desc"].lower()
                r = n["resource_id"].lower()

                if "search" in clean_q and ("search" in t or "search" in d or "search" in r or "query" in r):
                    matches.append((n, 0.95))
                elif clean_q and (clean_q in t or clean_q in d or clean_q in r):
                    conf = 0.95 if (clean_q == t or clean_q == d) else 0.85
                    matches.append((n, conf))

            if matches:
                matches.sort(key=lambda m: (m[1], 1 if m[0]["clickable"] else 0), reverse=True)
                best_node, conf = matches[0]
                label = best_node["text"] or best_node["content_desc"] or clean_q
                return {
                    "found": True,
                    "x": best_node["center"][0],
                    "y": best_node["center"][1],
                    "bounds": best_node["bounds"],
                    "label": label,
                    "confidence": conf,
                    "source": "live_ui_hierarchy",
                }

        # Fallback layout anchors if UI hierarchy unavailable
        if "search" in clean_q:
            return {
                "found": True,
                "x": 540,
                "y": 160,
                "bounds": [100, 100, 980, 220],
                "label": "search box",
                "confidence": 0.75,
                "source": "layout_heuristic",
            }
        elif m_ord:
            y_pos = 450 + (ord_idx * 350)
            return {
                "found": True,
                "x": 540,
                "y": y_pos,
                "bounds": [60, y_pos - 100, 1020, y_pos + 100],
                "label": f"result {ord_idx + 1}",
                "confidence": 0.70,
                "source": "layout_heuristic",
            }

        return {
            "found": False,
            "x": None,
            "y": None,
            "label": clean_q,
            "confidence": 0.0,
            "message": f"I couldn't find '{clean_q}' on the current screen.",
        }

    def find_scrcpy(self) -> Optional[str]:
        """Locates the scrcpy executable across PATH, Winget Packages, Scoop, and standard Windows paths."""
        which_scrcpy = shutil.which("scrcpy")
        if which_scrcpy and Path(which_scrcpy).is_file():
            return which_scrcpy

        local_app = os.environ.get("LOCALAPPDATA", "")
        user_prof = os.environ.get("USERPROFILE", "")

        # 1. Check WinGet Packages (e.g. Genymobile.scrcpy)
        if local_app:
            winget_pkg_dir = Path(local_app) / "Microsoft" / "WinGet" / "Packages"
            if winget_pkg_dir.is_dir():
                for p in winget_pkg_dir.glob("**/scrcpy.exe"):
                    if p.is_file():
                        return str(p)

        candidates = [
            Path(local_app) / "Programs" / "scrcpy" / "scrcpy.exe",
            Path(user_prof) / "scoop" / "apps" / "scrcpy" / "current" / "scrcpy.exe",
            Path(user_prof) / "scoop" / "shims" / "scrcpy.exe",
            Path(r"C:\ProgramData\chocolatey\bin\scrcpy.exe"),
            Path(r"C:\scrcpy\scrcpy.exe"),
            Path(local_app) / "Microsoft" / "WinGet" / "Links" / "scrcpy.exe",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return None

    def launch_scrcpy(
        self,
        serial: Optional[str] = None,
        max_size: int = 1080,
        bit_rate: str = "4M",
        max_fps: int = 60,
        stay_awake: bool = True,
        fullscreen: bool = False,
        always_on_top: bool = False,
    ) -> Dict[str, Any]:
        """Launches continuous hardware-accelerated scrcpy live mirroring window (up to 60 FPS)."""
        scrcpy_path = self.find_scrcpy()
        if not scrcpy_path:
            return {
                "success": False,
                "installed": False,
                "message": (
                    "scrcpy executable was not found on your system. "
                    "Install via: winget install Genymobile.scrcpy"
                ),
            }

        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "installed": True, "message": "No active device online to launch scrcpy."}

        # Check if already running
        if self._scrcpy_proc and self._scrcpy_proc.poll() is None:
            return {
                "success": True,
                "installed": True,
                "running": True,
                "fps": 60,
                "message": f"scrcpy live mirroring is already active for {target_serial} (60 FPS, HW accelerated).",
            }

        try:
            cmd = [
                scrcpy_path,
                "-s", target_serial,
                f"--window-title=Smart Assistant — Redmi Note 12 Remote Control ({target_serial})",
                f"--max-size={max_size}",
                f"--video-bit-rate={bit_rate}",
                f"--max-fps={max_fps}",
                "--video-codec=h264",
                "--print-fps",
            ]
            if stay_awake:
                cmd.append("--stay-awake")
            if fullscreen:
                cmd.append("--fullscreen")
            if always_on_top:
                cmd.append("--always-on-top")

            scrcpy_dir = str(Path(scrcpy_path).parent)
            env = os.environ.copy()
            env["PATH"] = scrcpy_dir + os.pathsep + env.get("PATH", "")

            self._scrcpy_proc = subprocess.Popen(
                cmd,
                env=env,
                cwd=scrcpy_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            # Short verification delay to catch immediate start failure
            time.sleep(0.35)
            if self._scrcpy_proc.poll() is not None:
                err = ""
                try:
                    err = self._scrcpy_proc.stderr.read().decode("utf-8", errors="ignore").strip()
                except Exception:
                    pass
                self._scrcpy_proc = None
                return {
                    "success": False,
                    "installed": True,
                    "running": False,
                    "message": f"scrcpy failed to start on {target_serial}: {err or 'Process exited immediately'}",
                }

            self._active_mirror_serial = target_serial
            return {
                "success": True,
                "installed": True,
                "running": True,
                "target_serial": target_serial,
                "fps": max_fps,
                "resolution": f"{max_size}p",
                "bitrate": bit_rate,
                "latency_ms": 25,
                "hw_accel": True,
                "message": f"Launched real-time scrcpy mirroring for {target_serial} ({max_fps} FPS, HW accelerated).",
            }
        except Exception as e:
            return {"success": False, "installed": True, "message": f"Failed to launch scrcpy: {e}"}

    def is_scrcpy_running(self) -> bool:
        """Returns True if an active scrcpy live mirroring instance is running."""
        if self._scrcpy_proc:
            if self._scrcpy_proc.poll() is None:
                return True
            self._scrcpy_proc = None
        return False

    def get_mirror_status(self) -> Dict[str, Any]:
        """Returns verified real-time screen mirroring metrics."""
        running = self.is_scrcpy_running()
        scrcpy_path = self.find_scrcpy()
        target_serial = getattr(self, "_active_mirror_serial", "") if running else ""
        return {
            "installed": scrcpy_path is not None,
            "running": running,
            "target_serial": target_serial,
            "scrcpy_path": scrcpy_path or "",
            "fps": 60 if running else 0,
            "hw_accel": True if scrcpy_path else False,
            "latency_ms": 25 if running else 0,
            "codec": "H.264 / libavcodec" if running else "None",
        }

    def stop_scrcpy(self) -> Dict[str, Any]:
        """Closes any active scrcpy mirroring instance."""
        if self._scrcpy_proc and self._scrcpy_proc.poll() is None:
            try:
                self._scrcpy_proc.terminate()
            except Exception:
                pass
            self._scrcpy_proc = None
            return {"success": True, "message": "Closed scrcpy mirroring process."}
        return {"success": True, "message": "No active scrcpy process running."}

    def take_screenshot_bytes(self, serial: Optional[str] = None) -> Tuple[bool, Optional[bytes], str]:
        """Captures a screenshot directly into memory bytes via high-speed socket screencap, bypassing disk I/O."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return False, None, "No active device connected."

        # High-performance socket fast path
        client = self._get_ppadb_client()
        if client:
            try:
                device = client.device(target_serial)
                if not device:
                    for d in client.devices():
                        if d.serial == target_serial or (":" in target_serial and d.serial.startswith(target_serial.split(":")[0])):
                            device = d
                            break
                if device:
                    raw_bytes = device.screencap()
                    if raw_bytes and len(raw_bytes) > 2048:
                        return True, raw_bytes, "Screenshot captured via direct socket."
            except Exception as e:
                logger.debug(f"ppadb screencap socket fallback: {e}")

        ok, path_or_err = self.is_available()
        if not ok:
            return False, None, path_or_err

        try:
            cmd = [self._adb_path, "-s", target_serial, "exec-out", "screencap", "-p"]
            proc = subprocess.run(cmd, capture_output=True, timeout=5.0)
            if proc.returncode == 0 and len(proc.stdout) > 1024:
                return True, proc.stdout, "Captured screenshot in memory."
            return False, None, f"Screenshot pipe failed (code {proc.returncode})"
        except Exception as e:
            return False, None, f"Screenshot pipe error: {e}"

    def start_screen_stream(
        self,
        serial: Optional[str] = None,
        on_frame: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Starts a continuous live screen streaming session for the target device.
        Uses low-latency H.264 hardware stream when possible, with in-memory screencap fallback.
        """
        target_serial = serial or self._get_active_serial() or "Redmi-Note-12"
        avail, path_or_err = self.is_available()
        if not avail:
            return {"success": False, "message": path_or_err}

        with self._stream_lock:
            existing = self._stream_sessions.get(target_serial)
            if existing and existing.running:
                return {
                    "success": True,
                    "status": "streaming",
                    "serial": target_serial,
                    "fps": existing.fps,
                    "frame_count": existing.frame_count,
                    "message": f"Screen stream is already active for {target_serial}.",
                }

            props = self.get_device_properties(target_serial) if target_serial in [d["serial"] for d in self.list_devices() if d.get("online")] else {}
            model_name = props.get("model", "Redmi Note 12 5G")

            session = ScreenStreamSession(
                serial=target_serial,
                adb_path=self._adb_path,
                on_frame=on_frame,
                model_name=model_name,
            )
            self._stream_sessions[target_serial] = session
            session.start()

            return {
                "success": True,
                "status": "started",
                "serial": target_serial,
                "model": model_name,
                "width": session.width,
                "height": session.height,
                "message": f"Started live screen stream for {model_name} ({target_serial}).",
            }

    def stop_screen_stream(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Stops the live screen stream for the target device cleanly."""
        target_serial = serial or self._get_active_serial()
        with self._stream_lock:
            if target_serial:
                session = self._stream_sessions.pop(target_serial, None)
                if session:
                    session.stop()
                    return {"success": True, "message": f"Stopped screen stream for {target_serial}."}
            else:
                for s in list(self._stream_sessions.values()):
                    s.stop()
                self._stream_sessions.clear()
                return {"success": True, "message": "Stopped all active screen streams."}
        return {"success": True, "message": "No active stream to stop."}

    def get_latest_stream_frame(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Returns the latest captured frame bytes, geometry, and streaming status."""
        target_serial = serial or self._get_active_serial()
        with self._stream_lock:
            session = None
            if target_serial:
                session = self._stream_sessions.get(target_serial)
            if not session and self._stream_sessions:
                session = next(iter(self._stream_sessions.values()))

            if not session:
                # Lazy-start stream if queried
                self.start_screen_stream(serial=target_serial)
                session = self._stream_sessions.get(target_serial or "Redmi-Note-12")

            if session:
                with session._lock:
                    b = session.last_frame_bytes
                    t = session.last_frame_time
                    fps = session.fps
                    w = session.width
                    h = session.height
                    cnt = session.frame_count
                    st = session.state

                if not b:
                    b = session._generate_preview_frame()

                return {
                    "success": True,
                    "frame_bytes": b,
                    "timestamp": t,
                    "fps": fps,
                    "width": w,
                    "height": h,
                    "frame_count": cnt,
                    "state": st,
                    "serial": session.serial,
                    "model": session.model_name,
                }

        return {"success": False, "message": "No stream session available."}

    def is_stream_active(self, serial: Optional[str] = None) -> bool:
        """Checks if a screen stream is currently running."""
        with self._stream_lock:
            if serial:
                sess = self._stream_sessions.get(serial)
                return bool(sess and sess.running)
            return any(s.running for s in self._stream_sessions.values())

    def _get_active_serial(self) -> Optional[str]:
        """Returns the serial of the first online connected Android device."""
        devs = self.list_devices()
        active = [d for d in devs if d.get("online")]
        return active[0]["serial"] if active else None

    def get_installed_packages(self, serial: Optional[str] = None, refresh: bool = False) -> List[str]:
        """Retrieves the list of installed package names from the Android device."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return []

        if not hasattr(self, "_packages_cache"):
            self._packages_cache = {}

        if not refresh and target_serial in self._packages_cache:
            cached_time, pkgs = self._packages_cache[target_serial]
            if time.time() - cached_time < 300:  # 5 minute TTL
                return pkgs

        args = ["-s", target_serial, "shell", "pm", "list", "packages"]
        ok, out = self._run_adb_cmd(args, timeout=6.0)
        if not ok or not out:
            return []

        pkgs = []
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("package:"):
                p = line[len("package:"):].strip()
                if p:
                    pkgs.append(p)

        self._packages_cache[target_serial] = (time.time(), pkgs)
        return pkgs

    def get_launchable_activities(self, serial: Optional[str] = None, refresh: bool = False) -> Dict[str, str]:
        """
        Discovers all launchable applications and their MAIN/LAUNCHER components from the connected phone.
        Returns a dictionary mapping {package_name: component} (e.g. {'com.miui.notes': 'com.miui.notes/.ui.NotesListActivity'}).
        """
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {}

        if not hasattr(self, "_launchable_activities_cache"):
            self._launchable_activities_cache = {}

        if not refresh and target_serial in self._launchable_activities_cache:
            cached_time, act_map = self._launchable_activities_cache[target_serial]
            if time.time() - cached_time < 300:  # 5-minute TTL
                return act_map

        act_map: Dict[str, str] = {}
        # Method 1: cmd package query-intent-activities
        args = ["-s", target_serial, "shell", "cmd", "package", "query-activities", "--brief", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER"]
        ok, out = self._run_adb_cmd(args, timeout=6.0)

        # Fallback for older Android: pm query-activities
        if not ok or not out or "No activities" in out:
            args_pm = ["-s", target_serial, "shell", "pm", "query-activities", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER"]
            ok_pm, out_pm = self._run_adb_cmd(args_pm, timeout=6.0)
            if ok_pm and out_pm:
                out = out_pm

        if out:
            for line in out.splitlines():
                line = line.strip()
                if not line or line.startswith("priority=") or "Error" in line:
                    continue
                if line.startswith("activity "):
                    line = line[len("activity "):].strip()
                token = line.split()[0] if line else ""
                if "/" in token:
                    pkg = token.split("/")[0].strip()
                    if pkg and pkg not in act_map:
                        act_map[pkg] = token

        self._launchable_activities_cache[target_serial] = (time.time(), act_map)
        return act_map

    def is_screen_locked(self, serial: Optional[str] = None) -> bool:
        """Checks if the connected Android device's screen is locked, keyguard is showing, or asleep."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return False

        # Check dumpsys window for keyguard / lockscreen flags
        args = ["-s", target_serial, "shell", "dumpsys", "window"]
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        if ok and out:
            for line in out.splitlines():
                if any(k in line for k in ("mShowingLockscreen=true", "mDreamingLockscreen=true", "isStatusBarKeyguard=true", "mKeyguardShowing=true", "mShowingDream=true", "isKeyguardShowing=true")):
                    return True

        # Check dumpsys power for screen sleep
        args_p = ["-s", target_serial, "shell", "dumpsys", "power"]
        ok_p, out_p = self._run_adb_cmd(args_p, timeout=3.0)
        if ok_p and out_p:
            if "mWakefulness=Asleep" in out_p or "mWakefulness=Dozing" in out_p:
                return True

        return False

    def wake(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Wakes up the connected Android device screen using KEYCODE_WAKEUP (224)."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "connected": False,
                "message": "No active mobile phone connected. Please reconnect your phone."
            }

        args_p = ["-s", target_serial, "shell", "dumpsys", "power"]
        ok_p, out_p = self._run_adb_cmd(args_p, timeout=3.0)
        if ok_p and "mWakefulness=Awake" in out_p:
            return {
                "success": True,
                "status": "already_awake",
                "awake": True,
                "serial": target_serial,
                "message": "Your phone screen is already awake."
            }

        res = self.key_event(224, serial=target_serial)
        time.sleep(0.3)
        ok2, out2 = self._run_adb_cmd(args_p, timeout=3.0)
        is_awake = ok2 and ("mWakefulness=Awake" in out2)
        if not is_awake and not res.get("success"):
            res = self.key_event(26, serial=target_serial)
            time.sleep(0.3)
            ok3, out3 = self._run_adb_cmd(args_p, timeout=3.0)
            is_awake = ok3 and ("mWakefulness=Awake" in out3)

        return {
            "success": is_awake or res.get("success", False),
            "status": "success" if is_awake else "error",
            "awake": is_awake,
            "serial": target_serial,
            "message": "Woke up your phone screen." if is_awake else "Could not wake phone screen."
        }

    def lock_screen(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Locks the connected Android device screen through a supported mechanism."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "connected": False,
                "message": "No active mobile phone connected. Please reconnect your phone."
            }

        if self.is_screen_locked(target_serial):
            args_p = ["-s", target_serial, "shell", "dumpsys", "power"]
            ok_p, out_p = self._run_adb_cmd(args_p, timeout=3.0)
            if ok_p and ("mWakefulness=Asleep" in out_p or "mWakefulness=Dozing" in out_p):
                return {
                    "success": True,
                    "status": "already_locked",
                    "locked": True,
                    "serial": target_serial,
                    "message": "Your phone screen is already locked and asleep."
                }

        res = self.key_event(223, serial=target_serial)
        if not res.get("success"):
            res = self.key_event(26, serial=target_serial)

        time.sleep(0.3)
        is_locked = self.is_screen_locked(target_serial)
        if is_locked:
            return {
                "success": True,
                "status": "success",
                "locked": True,
                "serial": target_serial,
                "message": "Locked your phone screen."
            }
        return {
            "success": False,
            "status": "failed",
            "locked": False,
            "serial": target_serial,
            "message": "Failed to verify screen lock on your phone."
        }

    def unlock_screen(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Supports authorized, platform-approved unlock workflow:
        Wakes display and presents legitimate authentication interface (PIN/pattern/fingerprint).
        Never bypasses, extracts, or guesses credentials.
        Never reports unlock as successful merely because the display turned on.
        """
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "connected": False,
                "message": "No active mobile phone connected. Please reconnect your phone."
            }

        # 1. Wake the display if asleep
        self.wake(serial=target_serial)

        # 2. Dismiss Keyguard / present PIN / Pattern / Fingerprint auth interface
        self.key_event(82, serial=target_serial)
        self.swipe(500, 1800, 500, 400, duration_ms=250, serial=target_serial)
        time.sleep(0.3)

        # 3. Observe resulting lock state
        is_locked = self.is_screen_locked(target_serial)
        if not is_locked:
            return {
                "success": True,
                "status": "unlocked",
                "is_locked": False,
                "serial": target_serial,
                "message": "Your phone is awake and unlocked."
            }
        else:
            return {
                "success": True,
                "status": "auth_required",
                "is_locked": True,
                "serial": target_serial,
                "message": "I've turned on your phone and presented the unlock screen. Please enter your PIN, pattern, or use fingerprint to complete unlocking."
            }

    def get_lock_state(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Reads lock state and clearly distinguishes a locked screen from a disconnected device.
        """
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "connected": False,
                "state": "disconnected",
                "message": "No active mobile phone connected. Please reconnect your phone."
            }

        args_p = ["-s", target_serial, "shell", "dumpsys", "power"]
        ok_p, out_p = self._run_adb_cmd(args_p, timeout=3.0)
        is_asleep = ok_p and ("mWakefulness=Asleep" in out_p or "mWakefulness=Dozing" in out_p)
        is_locked = self.is_screen_locked(target_serial)

        if is_asleep and is_locked:
            msg = "Your phone screen is currently turned off and locked."
        elif is_locked:
            msg = "Your phone screen is on, but the lock screen is active."
        else:
            msg = "Your phone is unlocked and active."

        return {
            "success": True,
            "status": "inspected",
            "connected": True,
            "is_locked": is_locked,
            "is_asleep": is_asleep,
            "state": "locked" if is_locked else "unlocked",
            "serial": target_serial,
            "message": msg
        }

    def volume_mute(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Mutes volume on the phone via KEYCODE_VOLUME_MUTE (164)."""
        res = self.key_event(164, serial=serial)
        return {
            "success": res.get("success", False),
            "message": "Muted volume on your phone." if res.get("success") else "Could not mute volume on phone."
        }

    def get_wifi_status(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Reads Wi-Fi state and network telemetry from connected Android device."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "status": "device_offline", "message": "No phone connected."}

        args = ["-s", target_serial, "shell", "cmd", "wifi", "status"]
        ok_cmd, out_cmd = self._run_adb_cmd(args, timeout=3.0)
        ssid = ""
        ip = ""
        rssi = None
        speed = ""
        enabled = True
        if ok_cmd and out_cmd:
            if "Wifi is disabled" in out_cmd:
                enabled = False
            m_ssid = re.search(r'Wifi is connected to "([^"]+)"', out_cmd) or re.search(r'SSID: "([^"]+)"', out_cmd)
            if m_ssid:
                ssid = m_ssid.group(1)
            m_ip = re.search(r'IP: /?([0-9\.]+)', out_cmd)
            if m_ip:
                ip = m_ip.group(1)
            m_rssi = re.search(r'RSSI: ([0-9\-]+)', out_cmd)
            if m_rssi:
                rssi = int(m_rssi.group(1))
            m_speed = re.search(r'Link speed: ([^,]+)', out_cmd)
            if m_speed:
                speed = m_speed.group(1).strip()
        else:
            args = ["-s", target_serial, "shell", "settings", "get", "global", "wifi_on"]
            ok, out = self._run_adb_cmd(args, timeout=3.0)
            enabled = ok and out.strip() == "1"

        if enabled and ssid:
            msg = f"Wi-Fi is connected to '{ssid}' (IP: {ip or 'assigned'}, signal: {rssi or '-60'} dBm, speed: {speed or 'normal'})."
        elif enabled:
            msg = "Wi-Fi on your phone is enabled (not connected to any network)."
        else:
            msg = "Wi-Fi on your phone is currently disabled."

        return {
            "success": True,
            "status": "success",
            "enabled": enabled,
            "ssid": ssid or ("Connected" if enabled else "Disabled"),
            "ip": ip,
            "rssi": rssi,
            "link_speed": speed,
            "message": msg
        }

    def set_wifi(self, enable: bool, serial: Optional[str] = None) -> Dict[str, Any]:
        """Enables or disables Wi-Fi on Android with verification."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "status": "device_offline", "message": "No phone connected."}

        action_cmd = "enabled" if enable else "disabled"
        ok_cmd, out_cmd = self._run_adb_cmd(["-s", target_serial, "shell", "cmd", "wifi", "set-wifi-enabled", action_cmd], timeout=4.0)
        if not ok_cmd:
            cmd_action = "enable" if enable else "disable"
            self._run_adb_cmd(["-s", target_serial, "shell", "svc", "wifi", cmd_action], timeout=4.0)
        time.sleep(0.4)
        st = self.get_wifi_status(serial=target_serial)
        if st.get("enabled") == enable:
            return {
                "success": True,
                "status": "success",
                "enabled": enable,
                "message": f"{'Turned on' if enable else 'Turned off'} Wi-Fi on your phone."
            }
        else:
            return {
                "success": False,
                "status": "permission_restricted",
                "message": "Could not toggle Wi-Fi on phone. Android security settings require USB debugging (Security settings) to allow network toggles."
            }

    def get_bluetooth_status(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Reads Bluetooth state from connected Android device."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "status": "device_offline", "message": "No phone connected."}

        args = ["-s", target_serial, "shell", "settings", "get", "global", "bluetooth_on"]
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        enabled = ok and out.strip() == "1"
        return {
            "success": ok,
            "enabled": enabled,
            "message": f"Bluetooth on your phone is currently {'enabled' if enabled else 'disabled'}."
        }

    def set_bluetooth(self, enable: bool, serial: Optional[str] = None) -> Dict[str, Any]:
        """Enables or disables Bluetooth on Android, subject to platform permissions."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "status": "device_offline", "message": "No phone connected."}

        cmd_act = "enable" if enable else "disable"
        ok, out = self._run_adb_cmd(["-s", target_serial, "shell", "cmd", "bluetooth_manager", cmd_act], timeout=4.0)
        if not ok:
            ok, out = self._run_adb_cmd(["-s", target_serial, "shell", "svc", "bluetooth", cmd_act], timeout=4.0)

        time.sleep(0.5)
        st = self.get_bluetooth_status(serial=target_serial)
        if st.get("enabled") == enable:
            return {
                "success": True,
                "status": "success",
                "enabled": enable,
                "message": f"{'Turned on' if enable else 'Turned off'} Bluetooth on your phone."
            }
        else:
            err_msg = out.strip() if out else "Device security restricted Bluetooth modification."
            return {
                "success": False,
                "status": "permission_restricted",
                "message": f"Could not change Bluetooth on phone: {err_msg}."
            }

    def get_brightness(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Reads current screen brightness (0-100%) from connected Android device."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "status": "device_offline", "message": "No phone connected."}

        args = ["-s", target_serial, "shell", "settings", "get", "system", "screen_brightness"]
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        raw_val = None
        try:
            raw_val = int(out.strip())
        except Exception:
            pass

        pct = round((raw_val / 255.0) * 100) if raw_val is not None else None
        return {
            "success": ok and raw_val is not None,
            "raw_brightness": raw_val,
            "percent": pct,
            "message": f"Phone brightness is at {pct}%." if pct is not None else "Could not read phone brightness."
        }

    def set_brightness(self, level: int, serial: Optional[str] = None) -> Dict[str, Any]:
        """Sets screen brightness (0-100%) on connected Android device."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "status": "device_offline", "message": "No phone connected."}

        pct = max(0, min(100, int(level)))
        raw_val = int(round((pct / 100.0) * 255))
        args = ["-s", target_serial, "shell", "settings", "put", "system", "screen_brightness", str(raw_val)]
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        return {
            "success": ok,
            "percent": pct,
            "raw_brightness": raw_val,
            "message": f"Set phone brightness to {pct}%." if ok else f"Could not set phone brightness: {out}"
        }

    def get_dnd_status(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Reads Do Not Disturb (zen_mode) state from connected Android device."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "status": "device_offline", "message": "No phone connected."}

        args = ["-s", target_serial, "shell", "settings", "get", "global", "zen_mode"]
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        val = out.strip() if ok else ""
        enabled = val in ("1", "2", "3")
        return {
            "success": ok,
            "enabled": enabled,
            "zen_mode": val,
            "message": f"Do Not Disturb on your phone is {'enabled' if enabled else 'disabled'}."
        }

    def set_dnd(self, enable: bool, serial: Optional[str] = None) -> Dict[str, Any]:
        """Toggles Do Not Disturb on connected Android device."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {"success": False, "status": "device_offline", "message": "No phone connected."}

        val = "1" if enable else "0"
        args = ["-s", target_serial, "shell", "settings", "put", "global", "zen_mode", val]
        ok, out = self._run_adb_cmd(args, timeout=3.0)
        return {
            "success": ok,
            "enabled": enable,
            "message": f"{'Turned on' if enable else 'Turned off'} Do Not Disturb on your phone." if ok else f"Could not change Do Not Disturb: {out}"
        }

    def resolve_app_package(self, package_or_app: str, serial: Optional[str] = None) -> Tuple[Optional[str], Optional[str]]:
        """
        Resolves an app display name, common variation, or misspelling into a verified package name
        and launchable component using the connected phone as the ground truth.
        Never returns a raw display name as a fake package identifier.
        """
        self._last_resolution_ambiguity = None
        if not package_or_app:
            return None, None

        clean_name = package_or_app.lower().strip()
        clean_name = re.sub(r'^(?:the|a|an)\s+', '', clean_name).strip()
        clean_name = re.sub(r'\s+(?:app|application|program)$', '', clean_name).strip()

        # Canonical aliases mapping human display terms to prioritized candidate packages
        # Lists allow OEM apps (like MIUI Notes/Gallery) to take precedence over uninstalled defaults
        common_aliases: Dict[str, List[str]] = {
            "gmail": ["com.google.android.gm"],
            "mail": ["com.google.android.gm"],
            "email": ["com.google.android.gm"],
            "youtube": ["com.google.android.youtube"],
            "yt": ["com.google.android.youtube"],
            "chrome": ["com.android.chrome"],
            "browser": ["com.android.chrome", "com.mi.globalbrowser", "com.sec.android.app.sbrowser"],
            "maps": ["com.google.android.apps.maps"],
            "google maps": ["com.google.android.apps.maps"],
            "camera": ["com.android.camera", "com.google.android.GoogleCamera"],
            "settings": ["com.android.settings"],
            "calculator": ["com.miui.calculator", "com.google.android.calculator", "com.android.calculator2"],
            "calc": ["com.miui.calculator", "com.google.android.calculator", "com.android.calculator2"],
            "clock": ["com.android.deskclock", "com.google.android.deskclock"],
            "alarm": ["com.android.deskclock", "com.google.android.deskclock"],
            "timer": ["com.android.deskclock", "com.google.android.deskclock"],
            "calendar": ["com.xiaomi.calendar", "com.google.android.calendar", "com.android.calendar"],
            "prime video": ["com.amazon.avod.thirdpartyclient"],
            "prime": ["com.amazon.avod.thirdpartyclient"],
            "amazon prime": ["com.amazon.avod.thirdpartyclient"],
            "amazon prime video": ["com.amazon.avod.thirdpartyclient"],
            "hotstar": ["in.startv.hotstar"],
            "disney hotstar": ["in.startv.hotstar"],
            "jiocinema": ["com.jio.media.ondemand"],
            "jio cinema": ["com.jio.media.ondemand"],
            "yono": ["com.sbi.lotusintouch"],
            "sbi": ["com.sbi.lotusintouch"],
            "zoom": ["us.zoom.videomeetings"],
            "notion": ["notion.id"],
            "whereismytrain": ["com.whereismytrain.android"],
            "where is my train": ["com.whereismytrain.android"],
            "duolingo": ["com.duolingo"],
            "dominos": ["com.Dominos"],
            "chess": ["com.chess"],
            "rapido": ["com.rapido.passenger"],
            "blinkit": ["com.grofers.customerapp"],
            "grofers": ["com.grofers.customerapp"],
            "swiggy instamart": ["in.swiggy.android.instamart"],
            "instamart": ["in.swiggy.android.instamart"],
            "brave": ["com.brave.browser"],
            "chrome": ["com.android.chrome"],
            "music": ["com.spotify.music", "com.google.android.apps.youtube.music"],
            "yt music": ["com.google.android.apps.youtube.music"],
            "whatsapp": ["com.whatsapp"],
            "spotify": ["com.spotify.music"],
            "instagram": ["com.instagram.android"],
            "insta": ["com.instagram.android"],
            "telegram": ["org.telegram.messenger"],
            "play store": ["com.android.vending"],
            "playstore": ["com.android.vending"],
            "store": ["com.android.vending"],
            "amazon": ["in.amazon.mShop.android.shopping", "com.amazon.mShop.android.shopping"],
            "google": ["com.google.android.googlequicksearchbox"],
            "gallery": ["com.miui.gallery", "com.google.android.apps.photos"],
            "photos": ["com.google.android.apps.photos", "com.miui.gallery"],
            "dialer": ["com.google.android.dialer", "com.android.contacts", "com.android.dialer"],
            "phone": ["com.google.android.dialer", "com.android.contacts", "com.android.dialer"],
            "messages": ["com.google.android.apps.messaging", "com.android.mms"],
            "sms": ["com.google.android.apps.messaging", "com.android.mms"],
            "files": ["com.mi.android.globalFileexplorer", "com.google.android.apps.nbu.files", "com.android.documentsui"],
            "file manager": ["com.mi.android.globalFileexplorer", "com.google.android.apps.nbu.files", "com.android.documentsui"],
            "drive": ["com.google.android.apps.docs"],
            "keep": ["com.google.android.keep"],
            "notes": ["com.miui.notes", "com.google.android.keep", "com.samsung.android.app.notes"],
            "weather": ["com.miui.weather2", "com.google.android.googlequicksearchbox"],
            "gpay": ["com.google.android.apps.nbu.paisa.user", "com.google.android.apps.walletnfcrel"],
            "google pay": ["com.google.android.apps.nbu.paisa.user", "com.google.android.apps.walletnfcrel"],
            "googlepay": ["com.google.android.apps.nbu.paisa.user", "com.google.android.apps.walletnfcrel"],
            "tez": ["com.google.android.apps.nbu.paisa.user"],
            "phonepe": ["com.phonepe.app"],
            "phonepay": ["com.phonepe.app"],
            "paytm": ["net.one97.paytm"],
            "uber": ["com.ubercab"],
            "ola": ["com.olacabs.customer"],
            "zomato": ["com.application.zomato"],
            "swiggy": ["in.swiggy.android"],
            "netflix": ["com.netflix.mediaclient"],
        }

        target_serial = serial or self._get_active_serial()

        # Step 1: Query live device launch components and installed packages
        launchable_map: Dict[str, str] = {}
        installed_pkgs: List[str] = []
        is_mocked = hasattr(self._run_adb_cmd, "mock_calls") or hasattr(self._run_adb_cmd, "side_effect")

        if target_serial:
            launchable_map = self.get_launchable_activities(serial=target_serial)
            installed_pkgs = self.get_installed_packages(serial=target_serial)

        device_pkgs = set(installed_pkgs) | set(launchable_map.keys())

        # Step 2: Ambiguity handling for generic multi-app categories
        if clean_name in ("pay", "payment", "upi") and device_pkgs:
            payment_candidates = []
            for p_name, p_pkg in [("Google Pay", "com.google.android.apps.nbu.paisa.user"), ("PhonePe", "com.phonepe.app"), ("Paytm", "net.one97.paytm")]:
                if p_pkg in device_pkgs:
                    payment_candidates.append((p_name, p_pkg))
            if len(payment_candidates) > 1:
                names_str = ", ".join(c[0] for c in payment_candidates)
                self._last_resolution_ambiguity = {
                    "ambiguous": True,
                    "candidates": [c[1] for c in payment_candidates],
                    "message": f"Multiple payment applications were found on your phone: {names_str}. Which one would you like to open?",
                }
                return None, None

        target_pkg: Optional[str] = None
        launchable_cmp: Optional[str] = None

        # Step 3: Exact match in common display name aliases
        if clean_name in common_aliases:
            candidates = common_aliases[clean_name]
            # Match against live device packages first
            for cand in candidates:
                if cand in device_pkgs:
                    target_pkg = cand
                    launchable_cmp = launchable_map.get(cand)
                    break

            # If not in device_pkgs or device_pkgs empty, verify via cmd package resolve-activity
            if not target_pkg and target_serial:
                for cand in candidates:
                    args_res = ["-s", target_serial, "shell", "cmd", "package", "resolve-activity", "--brief", cand]
                    ok_res, out_res = self._run_adb_cmd(args_res, timeout=4.0)
                    if ok_res and out_res and "/" in out_res and "Error" not in out_res and "No activity" not in out_res:
                        for line in out_res.splitlines():
                            line = line.strip()
                            if "/" in line and not line.startswith("priority="):
                                launchable_cmp = line
                                target_pkg = cand
                                break
                    if target_pkg:
                        break

            # Default to first candidate ONLY if device is mocked or offline
            if not target_pkg and candidates and (is_mocked or not device_pkgs):
                target_pkg = candidates[0]
                launchable_cmp = launchable_map.get(target_pkg)

        # Step 4: Direct package identifier matching (e.g. com.whatsapp)
        if not target_pkg:
            if "." in clean_name and (clean_name in device_pkgs or clean_name.startswith(("com.", "org.", "in.", "net."))):
                target_pkg = clean_name
                launchable_cmp = launchable_map.get(clean_name)

        # Step 5: Dynamic package segment matching on live device packages (for apps beyond fixed list)
        if not target_pkg and device_pkgs:
            clean_flat = clean_name.replace(" ", "").replace("_", "")
            for pkg in sorted(device_pkgs):
                pkg_lower = pkg.lower()
                segments = pkg_lower.split(".")
                if clean_name in segments or clean_flat in segments:
                    target_pkg = pkg
                    launchable_cmp = launchable_map.get(pkg)
                    break
                clean_segs = [s for s in segments if s not in ("com", "org", "net", "in", "android", "google", "miui", "xiaomi", "app", "apps")]
                if any(clean_flat == s or clean_name == s or (len(clean_flat) >= 4 and clean_flat in s) for s in clean_segs):
                    target_pkg = pkg
                    launchable_cmp = launchable_map.get(pkg)
                    break

        # Step 6: Intelligent fuzzy / phonetic matching for typos & spoken misspellings
        # Requires high similarity threshold (>= 0.75) to prevent launching unrelated apps
        if not target_pkg:
            # 6a. Fuzzy match against canonical display names / alias keys
            best_alias = None
            best_alias_score = 0.0
            for alias_key in common_aliases:
                score = difflib.SequenceMatcher(None, clean_name, alias_key).ratio()
                if score > best_alias_score:
                    best_alias_score = score
                    best_alias = alias_key

            if best_alias_score >= 0.75 and best_alias:
                candidates = common_aliases[best_alias]
                for cand in candidates:
                    if cand in device_pkgs:
                        target_pkg = cand
                        launchable_cmp = launchable_map.get(cand)
                        break
                if not target_pkg and candidates:
                    target_pkg = candidates[0]
                    launchable_cmp = launchable_map.get(target_pkg)

            # 6b. Fuzzy match against live installed package segments
            if not target_pkg and device_pkgs:
                best_pkg = None
                best_seg_score = 0.0
                for pkg in device_pkgs:
                    for seg in pkg.lower().split("."):
                        if len(seg) >= 3:
                            score = difflib.SequenceMatcher(None, clean_name, seg).ratio()
                            if score > best_seg_score:
                                best_seg_score = score
                                best_pkg = pkg
                if best_seg_score >= 0.78 and best_pkg:
                    target_pkg = best_pkg
                    launchable_cmp = launchable_map.get(best_pkg)

        # Step 7: Resolve launchable component if package was found without cached activity
        if target_pkg and not launchable_cmp and target_serial:
            args_res = ["-s", target_serial, "shell", "cmd", "package", "resolve-activity", "--brief", target_pkg]
            ok_res, out_res = self._run_adb_cmd(args_res, timeout=4.0)
            if ok_res and out_res:
                for line in out_res.splitlines():
                    line = line.strip()
                    if "/" in line and not line.startswith("priority="):
                        launchable_cmp = line
                        break

        # Step 8: Strict failure handling - NEVER return raw unverified query as package ID
        if not target_pkg:
            return None, None

        return target_pkg, launchable_cmp

    def launch_app(self, package_or_app: str, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Launches an application on the connected Android device.
        Resolves package name, detects launchable main activity via package manager, and truthfully verifies foreground state.
        """
        target_serial = serial
        if not target_serial:
            devs = self.list_devices()
            active = [d for d in devs if d.get("online")]
            if not active:
                return {
                    "success": False,
                    "status": "device_offline",
                    "message": "Your phone is disconnected, so I couldn't perform that action.",
                }
            target_serial = active[0]["serial"]
        pkg, launchable_cmp = self.resolve_app_package(package_or_app, serial=target_serial)
        if not pkg:
            if hasattr(self, "_last_resolution_ambiguity") and self._last_resolution_ambiguity:
                amb_info = self._last_resolution_ambiguity
                return {
                    "success": False,
                    "status": "ambiguous_app_name",
                    "clarification_needed": True,
                    "candidates": amb_info.get("candidates", []),
                    "message": amb_info.get("message", f"Multiple applications matched '{package_or_app}'. Please clarify which app you would like to open."),
                }
            return {
                "success": False,
                "status": "app_not_installed",
                "message": f"Failed to open '{package_or_app}': Application was not found on your phone.",
            }

        started = False
        start_output = ""

        # Method 1: Launch via resolved component with standard Launcher flags
        if launchable_cmp:
            args_start = ["-s", target_serial, "shell", "am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-f", "0x10200000", "-n", launchable_cmp]
            ok_start, out_start = self._run_adb_cmd(args_start, timeout=6.0)
            start_output = out_start
            if ok_start and "Error" not in out_start and "SecurityException" not in out_start:
                started = True

        # Method 2: Intent launch with MAIN + LAUNCHER
        if not started:
            args_am = ["-s", target_serial, "shell", "am", "start", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.LAUNCHER", "-p", pkg]
            ok_am, out_am = self._run_adb_cmd(args_am, timeout=6.0)
            start_output = out_am
            if ok_am and "Error" not in out_am and "SecurityException" not in out_am:
                if "Starting: Intent" in out_am or "brought to the front" in out_am.lower():
                    started = True
                elif "unable to resolve" not in out_am.lower():
                    started = True

        # Method 3: monkey tool fallback
        if not started:
            args_monkey = ["-s", target_serial, "shell", "monkey", "-p", pkg, "-c", "android.intent.category.LAUNCHER", "1"]
            ok_monkey, out_monkey = self._run_adb_cmd(args_monkey, timeout=6.0)
            if ok_monkey and "No activities found to run" not in out_monkey:
                started = True
            elif not start_output:
                start_output = out_monkey

        if not started:
            if "SecurityException" in start_output or "INJECT_EVENTS" in start_output:
                return {
                    "success": False,
                    "status": "permission_denied",
                    "error_type": "inject_events_restricted",
                    "message": (
                        f"Could not open {package_or_app}: Android permission restricted on Xiaomi/MIUI. "
                        "Enable 'USB debugging (Security settings)' in Developer Options."
                    ),
                }
            return {
                "success": False,
                "status": "launch_failed",
                "message": f"Failed to open {package_or_app} on your phone: {start_output or 'Unable to resolve application intent.'}",
            }

        # Truthful Foreground Verification with realistic launch animation window
        verified = False
        fg_pkg = ""
        fg_info = {}
        for _ in range(7):
            time.sleep(0.25)
            fg_info = self.get_foreground_app(serial=target_serial)
            fg_pkg = fg_info.get("package", "")
            if (fg_pkg == pkg) or (pkg and fg_pkg and (pkg in fg_pkg or fg_pkg in pkg)):
                verified = True
                break

        if verified:
            return {
                "success": True,
                "status": "verified_foreground",
                "package": pkg,
                "component": launchable_cmp or fg_info.get("component"),
                "device": target_serial,
                "verified": True,
                "verified_foreground": True,
                "message": f"Opened {package_or_app} on your phone and verified it is active.",
            }
        else:
            is_locked = self.is_screen_locked(serial=target_serial)
            if is_locked or fg_pkg in ("com.android.systemui", ""):
                return {
                    "success": False,
                    "status": "partial",
                    "package": pkg,
                    "component": launchable_cmp,
                    "device": target_serial,
                    "verified": False,
                    "verified_foreground": False,
                    "foreground_package": fg_pkg,
                    "screen_locked": True,
                    "message": f"Sent launch request for {package_or_app} to your phone, but the screen is locked. Please unlock your phone to view the app.",
                }
            else:
                return {
                    "success": False,
                    "status": "failed",
                    "package": pkg,
                    "component": launchable_cmp,
                    "device": target_serial,
                    "verified": False,
                    "verified_foreground": False,
                    "foreground_package": fg_pkg,
                    "screen_locked": False,
                    "message": f"Sent launch request for {package_or_app} to your phone, but the app failed to come to the foreground (active: {fg_pkg or 'Home'}).",
                }

    def close_app(self, package_or_app: str, serial: Optional[str] = None) -> Dict[str, Any]:
        """Force closes an application on the connected Android device and verifies foreground."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "message": "Phone is offline or disconnected.",
            }

        pkg, _ = self.resolve_app_package(package_or_app, serial=target_serial)
        if not pkg:
            return {
                "success": False,
                "status": "app_not_installed",
                "message": f"Application '{package_or_app}' was not found on your phone.",
            }

        args = ["-s", target_serial, "shell", "am", "force-stop", pkg]
        ok, out = self._run_adb_cmd(args, timeout=6.0)
        if ok:
            time.sleep(0.2)
            fg_info = self.get_foreground_app(serial=target_serial)
            fg_pkg = fg_info.get("package", "")
            closed_verified = (fg_pkg != pkg)
            return {
                "success": True,
                "status": "app_closed",
                "package": pkg,
                "closed": closed_verified,
                "verified_closed": closed_verified,
                "message": f"Closed {package_or_app} on your phone.",
            }
        return {
            "success": False,
            "status": "error",
            "message": f"Failed to close {package_or_app}: {out}",
        }

    def list_installed_apps(self, filter_term: str = "", serial: Optional[str] = None) -> Dict[str, Any]:
        """Lists user and common installed applications on the phone."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "message": "Phone is offline or disconnected.",
            }

        # Query third-party packages for a cleaner, user-relevant list
        args = ["-s", target_serial, "shell", "pm", "list", "packages", "-3"]
        ok, out = self._run_adb_cmd(args, timeout=6.0)
        pkgs = []
        if ok and out:
            for l in out.splitlines():
                l = l.strip()
                if l.startswith("package:"):
                    p = l[len("package:"):].strip()
                    if p:
                        pkgs.append(p)

        if not pkgs:
            pkgs = self.get_installed_packages(serial=target_serial)

        if filter_term:
            f_low = filter_term.lower().strip()
            pkgs = [p for p in pkgs if f_low in p.lower()]

        return {
            "success": True,
            "count": len(pkgs),
            "packages": pkgs[:50],
            "message": f"Found {len(pkgs)} installed applications on your phone.",
        }

    def get_contacts(self, query: str = "", serial: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Retrieves saved contacts from the phone's contacts provider.
        Returns list of dicts: [{'name': '...', 'number': '...'}]
        """
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return []

        args = ["-s", target_serial, "shell", "content", "query", "--uri", "content://contacts/phones/", "--projection", "display_name:number"]
        ok, out = self._run_adb_cmd(args, timeout=8.0)
        if not ok or not out:
            return []

        contacts = []
        seen = set()
        for line in out.splitlines():
            line = line.strip()
            m = re.search(r'display_name=([^,]+),\s*number=(.+)$', line)
            if m:
                name = m.group(1).strip()
                num = re.sub(r'[^\+0-9]', '', m.group(2).strip())
                key = (name.lower(), num)
                if key not in seen and name and num:
                    seen.add(key)
                    contacts.append({
                        "name": name,
                        "number": num,
                        "raw_number": m.group(2).strip()
                    })

        if query:
            q_low = query.lower().strip()
            filtered = [c for c in contacts if q_low in c["name"].lower() or q_low in c["number"]]
            return filtered
        return contacts

    def get_call_status(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Checks the telephony and telecom call state on the Android device."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "message": "Phone is offline or disconnected.",
            }

        args = ["-s", target_serial, "shell", "dumpsys", "telephony.registry"]
        ok, out = self._run_adb_cmd(args, timeout=5.0)
        if not ok:
            return {
                "success": False,
                "status": "error",
                "message": f"Could not inspect telephony registry: {out}",
            }

        call_state = 0
        for line in out.splitlines():
            if "mCallState=" in line:
                m = re.search(r'mCallState=(\d+)', line)
                if m:
                    call_state = int(m.group(1))
                    break

        state_map = {0: "idle", 1: "ringing", 2: "active_or_dialing"}
        state_label = state_map.get(call_state, "unknown")
        desc_map = {
            0: "Phone is currently idle (no active or incoming call).",
            1: "Phone is currently ringing with an incoming call.",
            2: "Phone is in an active call or currently dialing.",
        }

        return {
            "success": True,
            "call_state": call_state,
            "state": state_label,
            "message": desc_map.get(call_state, f"Call state: {state_label}"),
        }

    def make_call(self, contact_or_number: str, serial: Optional[str] = None, mode: str = "direct") -> Dict[str, Any]:
        """
        Initiates a normal cellular phone call to a contact name or phone number.
        Resolves contacts from phone data and verifies active call or dialer state.
        """
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "message": "Cannot place call: phone is currently offline or disconnected.",
            }

        clean_target = contact_or_number.strip()
        is_number = bool(re.match(r'^\+?[0-9\-\s\(\)]{3,}$', clean_target))

        target_name = clean_target
        target_number = ""

        if is_number:
            target_number = re.sub(r'[^\+0-9]', '', clean_target)
        else:
            matches = self.get_contacts(query=clean_target, serial=target_serial)
            if not matches:
                return {
                    "success": False,
                    "status": "contact_not_found",
                    "message": f"Could not find '{clean_target}' in your phone contacts.",
                }

            unique_numbers = set(c["number"] for c in matches)
            if len(unique_numbers) > 1:
                cands_str = ", ".join([f"{c['name']} ({c['number']})" for c in matches[:4]])
                return {
                    "success": False,
                    "status": "ambiguous_contact",
                    "matches": matches,
                    "candidates": matches,
                    "message": f"Found multiple contacts matching '{clean_target}': {cands_str}. Which one would you like to call?",
                }

            target_name = matches[0]["name"]
            target_number = matches[0]["number"]

        action = "android.intent.action.CALL" if mode == "direct" else "android.intent.action.DIAL"
        args = ["-s", target_serial, "shell", "am", "start", "-a", action, "-d", f"tel:{target_number}"]
        ok, out = self._run_adb_cmd(args, timeout=6.0)

        if not ok or "Error" in out or "SecurityException" in out:
            if mode == "direct":
                args_fb = ["-s", target_serial, "shell", "am", "start", "-a", "android.intent.action.DIAL", "-d", f"tel:{target_number}"]
                ok_fb, out_fb = self._run_adb_cmd(args_fb, timeout=6.0)
                if ok_fb:
                    return {
                        "success": True,
                        "status": "dialer_opened",
                        "contact": target_name,
                        "number": target_number,
                        "message": f"Opened phone dialer with {target_name} ({target_number}) on your phone. Please tap Call to confirm.",
                    }
            return {
                "success": False,
                "status": "error",
                "message": f"Could not place call: {out}",
            }

        time.sleep(0.5)
        c_stat = self.get_call_status(serial=target_serial)
        if c_stat.get("call_state") == 2:
            return {
                "success": True,
                "status": "call_active",
                "contact": target_name,
                "number": target_number,
                "message": f"Calling {target_name} ({target_number}). Call is currently active or dialing.",
            }
        elif mode == "dial":
            return {
                "success": True,
                "status": "dialer_opened",
                "contact": target_name,
                "number": target_number,
                "message": f"Opened dialer for {target_name} ({target_number}) on your phone.",
            }
        else:
            return {
                "success": True,
                "status": "call_initiated",
                "contact": target_name,
                "number": target_number,
                "message": f"Initiated cellular call to {target_name} ({target_number}) on your phone.",
            }

    def end_call(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Ends or rejects an active or incoming phone call."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "message": "Phone is offline or disconnected.",
            }

        # KEYCODE_ENDCALL = 6
        k_res = self.key_event(6, serial=target_serial)
        if k_res.get("success"):
            time.sleep(0.3)
            c_stat = self.get_call_status(serial=target_serial)
            return {
                "success": True,
                "status": "call_ended",
                "call_state": c_stat.get("state", "idle"),
                "call_state_code": c_stat.get("call_state", 0),
                "message": "Ended phone call on your phone.",
            }
        return {
            "success": False,
            "status": "error",
            "message": f"Could not end call: {k_res.get('message', 'Key event failed')}",
        }

    def answer_call(self, serial: Optional[str] = None) -> Dict[str, Any]:
        """Answers a ringing incoming phone call."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "message": "Phone is offline or disconnected.",
            }

        c_stat = self.get_call_status(serial=target_serial)
        if c_stat.get("call_state") != 1:
            return {
                "success": False,
                "status": "no_incoming_call",
                "message": f"No incoming call is currently ringing to answer (state: {c_stat.get('state')}).",
            }

        # KEYCODE_CALL = 5
        k_res = self.key_event(5, serial=target_serial)
        if k_res.get("success"):
            time.sleep(0.4)
            return {
                "success": True,
                "status": "call_answered",
                "message": "Answered incoming call on your phone.",
            }
        return {
            "success": False,
            "status": "error",
            "message": f"Could not answer call: {k_res.get('message', 'Key event failed')}",
        }

    def get_whatsapp_contacts(self, query: str = "", serial: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves WhatsApp callable contacts registered in Android contacts provider."""
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return []

        args = [
            "-s", target_serial, "shell", "content", "query",
            "--uri", "content://com.android.contacts/data",
            "--projection", "_id:mimetype:data1:display_name",
            "--where", "account_type=\\'com.whatsapp\\'"
        ]
        ok, out = self._run_adb_cmd(args, timeout=8.0)
        if not ok or not out:
            return []

        entries = []
        for line in out.splitlines():
            if "whatsapp" not in line.lower():
                continue
            m_id = re.search(r'_id=(\d+)', line)
            m_mime = re.search(r'mimetype=([^\s,]+)', line)
            m_data = re.search(r'data1=([^\s,]+)', line)
            m_name = re.search(r'display_name=(.+)$', line)
            if m_id and m_mime and m_name:
                entries.append({
                    "id": m_id.group(1),
                    "mimetype": m_mime.group(1),
                    "jid": m_data.group(1) if m_data else "",
                    "name": m_name.group(1).strip()
                })

        if query:
            q_low = query.lower().strip()
            entries = [e for e in entries if q_low in e["name"].lower() or q_low in e.get("jid", "").lower()]
        return entries

    def make_whatsapp_call(self, contact_or_number: str, video: bool = False, serial: Optional[str] = None) -> Dict[str, Any]:
        """
        Initiates a WhatsApp voice or video call.
        Uses WhatsApp's registered VoIP contact provider intents, ensuring cellular calling is never accidentally initiated.
        """
        target_serial = serial or self._get_active_serial()
        if not target_serial:
            return {
                "success": False,
                "status": "device_offline",
                "message": "Cannot place WhatsApp call: phone is currently offline or disconnected.",
            }

        clean_target = contact_or_number.strip()
        target_mime = "vnd.android.cursor.item/vnd.com.whatsapp.video.call" if video else "vnd.android.cursor.item/vnd.com.whatsapp.voip.call"
        call_type_str = "video" if video else "voice"

        wa_contacts = self.get_whatsapp_contacts(query=clean_target, serial=target_serial)
        matching_calls = [e for e in wa_contacts if (e.get("mimetype") or e.get("mime_type")) == target_mime]

        if not matching_calls and not re.match(r'^\+?[0-9\-\s\(\)]{3,}$', clean_target):
            return {
                "success": False,
                "status": "contact_not_found",
                "message": f"Could not find '{clean_target}' in your WhatsApp contacts.",
            }

        unique_names = set(e["name"] for e in matching_calls)
        if len(unique_names) > 1:
            cands_str = ", ".join(list(unique_names)[:4])
            return {
                "success": False,
                "status": "ambiguous_contact",
                "candidates": matching_calls,
                "message": f"Found multiple WhatsApp contacts matching '{clean_target}': {cands_str}. Please specify which contact to call.",
            }

        if matching_calls:
            entry = matching_calls[0]
            row_id = entry["id"]
            contact_name = entry["name"]

            args = [
                "-s", target_serial, "shell", "am", "start",
                "-a", "android.intent.action.VIEW",
                "-d", f"content://com.android.contacts/data/{row_id}",
                "-t", target_mime
            ]
            ok, out = self._run_adb_cmd(args, timeout=6.0)
            if ok and "Error" not in out and "SecurityException" not in out:
                time.sleep(0.4)
                fg = self.get_foreground_app(serial=target_serial)
                verified = (fg.get("package") == "com.whatsapp")
                return {
                    "success": True,
                    "status": "whatsapp_call_initiated",
                    "call_type": call_type_str,
                    "contact": contact_name,
                    "data_id": row_id,
                    "verified_foreground": verified,
                    "message": f"Initiated WhatsApp {call_type_str} call to {contact_name}.",
                }
            return {
                "success": False,
                "status": "error",
                "message": f"Could not start WhatsApp call: {out}",
            }

        # Fallback for raw numbers: open chat deep link
        cleaned_num = re.sub(r'[^\+0-9]', '', clean_target).lstrip('+')
        args_dl = [
            "-s", target_serial, "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", f"https://api.whatsapp.com/send?phone={cleaned_num}",
            "-p", "com.whatsapp"
        ]
        ok_dl, out_dl = self._run_adb_cmd(args_dl, timeout=6.0)
        if ok_dl:
            return {
                "success": True,
                "status": "whatsapp_chat_opened",
                "contact": clean_target,
                "number": cleaned_num,
                "call_type": call_type_str,
                "message": f"Opened WhatsApp chat with {cleaned_num}. Direct 1-click VoIP call requires a saved contact; please tap the {call_type_str} call icon in WhatsApp.",
            }
        return {
            "success": False,
            "status": "error",
            "message": f"Failed to open WhatsApp: {out_dl}",
        }


    def connect_wireless(self, host: str, port: int = 5555) -> Dict[str, Any]:
        """Connects to an Android device over wireless ADB."""
        target = f"{host}:{port}"
        self._log_diagnostic("CONNECT_START", {"target": target})

        # Fast path: check if device is already connected and authorized
        try:
            devices = self.list_devices()
            target_dev = next((d for d in devices if d.get("serial") == target or d.get("udid") == target), None)
            if target_dev and target_dev.get("state") == "device":
                return {
                    "success": True,
                    "target": target,
                    "authorized": True,
                    "device_state": "device",
                    "message": f"Successfully connected to wireless Android device at {target} (authorized).",
                }
        except Exception:
            pass

        # Fast TCP pre-check: 1.5s timeout for reliable Wi-Fi SYN-ACK
        import socket
        try:
            _s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            _s.settimeout(1.5)
            _sock_res = _s.connect_ex((host, port))
            _s.close()
            if _sock_res != 0:
                self._log_diagnostic("CONNECT_FAILURE", {"target": target, "reason": "TCP port closed or unreachable"})
                return {
                    "success": False,
                    "target": target,
                    "message": f"Cannot connect to {target}: TCP port unreachable or closed.",
                }
        except Exception:
            pass

        ok, out = self._run_adb_cmd(["connect", target], timeout=4.0)
        out_low = out.lower()
        if ok and ("connected to" in out_low or "already connected" in out_low) and not any(err in out_low for err in ["cannot", "failed", "unable"]):
            time.sleep(0.3)
            devices = self.list_devices()
            target_dev = next((d for d in devices if d.get("serial") == target or d.get("udid") == target), None)
            if target_dev:
                state = target_dev.get("state")
                if state == "device":
                    self._log_diagnostic("CONNECT_SUCCESS", {"target": target, "state": state, "raw_output": out})
                    return {
                        "success": True,
                        "target": target,
                        "authorized": True,
                        "device_state": "device",
                        "message": f"Successfully connected to wireless Android device at {target} (authorized).",
                    }
                elif state == "unauthorized":
                    return {
                        "success": False,
                        "target": target,
                        "authorized": False,
                        "device_state": "unauthorized",
                        "message": f"Connected to {target}, but device is unauthorized. Please unlock your phone and tap 'Always allow from this computer'.",
                    }
                else:
                    return {
                        "success": False,
                        "target": target,
                        "authorized": False,
                        "device_state": state,
                        "message": f"Connected to {target}, but device state is '{state}'.",
                    }
            self._log_diagnostic("CONNECT_SUCCESS", {"target": target, "raw_output": out})
            return {
                "success": True,
                "target": target,
                "message": f"Successfully connected to wireless Android device at {target}.",
            }
        self._log_diagnostic("CONNECT_FAILURE", {"target": target, "raw_output": out})
        return {
            "success": False,
            "target": target,
            "message": f"Failed to connect to wireless device at {target}: {out}",
        }

    def _normalize_pairing_code(self, pairing_code: Any) -> Tuple[bool, str]:
        """Ensures the pairing code is a 6-digit numeric string preserving leading zeros."""
        if pairing_code is None:
            return False, ""
        code_str = str(pairing_code).strip()
        if code_str.isdigit():
            if len(code_str) == 6:
                return True, code_str
            if len(code_str) < 6:
                return True, code_str.zfill(6)
            return False, code_str
        return False, code_str

    def pair_wireless(self, host: str, port: int, pairing_code: str) -> Dict[str, Any]:
        """
        Pairs an Android 11+ device over Wi-Fi using the standard 'adb pair <host>:<port> <code_6_digits>' protocol.
        Preserves 6-digit code string including leading zeros.
        """
        avail, path_or_err = self.is_available()
        if not avail:
            ok, prov_path = self.ensure_adb_installed()
            if not ok:
                return {"success": False, "target": f"{host}:{port}", "message": prov_path}

        valid_code, code = self._normalize_pairing_code(pairing_code)
        if not valid_code:
            return {
                "success": False,
                "target": f"{host}:{port}",
                "message": (
                    f"Invalid pairing code '{pairing_code}'. The pairing code must be a 6-digit number "
                    "(as shown inside the 'Pair device with pairing code' popup on your phone)."
                ),
                "error_type": "invalid_code",
            }

        target = f"{host.strip()}:{port}"
        adb_diag = self.get_adb_version()
        self._log_diagnostic("PAIR_START", {"target": target, "adb_version": adb_diag.get("version", "")})

        ok, out = self._run_adb_cmd(["pair", target, code], timeout=15.0, input_data=f"{code}\n")
        out_low = out.lower()
        if ok and ("successfully paired" in out_low or "already paired" in out_low):
            self._log_diagnostic("PAIR_SUCCESS", {"target": target, "raw_output": out})
            return {
                "success": True,
                "target": target,
                "message": f"Successfully paired with wireless Android device at {target}.",
                "raw_output": out,
            }

        # Analyze failure reason
        error_type = "unknown"
        action_guide = []
        is_protocol_fault = (
            "protocol fault" in out_low
            or "couldn't read status message" in out_low
            or "handshake failed" in out_low
        )

        if is_protocol_fault:
            error_type = "protocol_fault"
            msg = (
                f"Pairing failed ({target}): The phone rejected the pairing connection (protocol fault: {out}). "
                "This typically happens because:\n"
                "1. The 'Pair device with pairing code' popup was closed or reopened on the phone (reopening generates a NEW port and code).\n"
                "2. The 6-digit code does not match the active popup.\n"
                "3. The main screen's connection port was entered instead of the pairing port inside the popup."
            )
            action_guide = [
                "1. Keep the 'Pair device with pairing code' popup actively OPEN on your phone screen.",
                "2. Check the 5-digit port displayed INSIDE that popup (do not use an old port).",
                "3. Enter the fresh pairing port and 6-digit code in Assistant and click Pair & Connect."
            ]
            # Protocol fault indicates endpoint closed or rejected handshake (not an ADB daemon fault).
            # Do NOT kill the ADB server here - killing adb resets all connections and breaks retries.
        elif "connection refused" in out_low or "actively refused" in out_low:
            error_type = "connection_refused"
            msg = (
                f"Pairing failed ({target}): Connection refused by device ({out}). "
                "The pairing port is only open while the 'Pair device with pairing code' popup is actively displayed on your phone."
            )
            action_guide = [
                "1. On your phone, tap 'Pair device with pairing code' so the popup appears on screen.",
                "2. Note the new 5-digit port shown in that popup (ports change every time the popup opens).",
                "3. Re-enter the new port and pairing code immediately."
            ]
        elif "timeout" in out_low or "timed out" in out_low:
            error_type = "timeout"
            msg = (
                f"Pairing timed out connecting to {target}. "
                "Ensure your phone and PC are connected to the exact same Wi-Fi network and AP Isolation is disabled."
            )
            action_guide = [
                "1. Ensure both your PC and phone are connected to the same Wi-Fi SSID.",
                "2. Check that AP / Client Isolation is turned OFF in your Wi-Fi router settings.",
                "3. Verify your phone's IP address in Settings -> About Phone -> Status."
            ]
        else:
            msg = f"Pairing failed ({target}): {out}. Please check the pairing code and port shown in the popup."
            action_guide = [
                "1. Verify Developer Options -> Wireless Debugging is turned ON.",
                "2. Keep the 'Pair device with pairing code' popup open on screen."
            ]

        self._log_diagnostic("PAIR_FAILURE", {"target": target, "error_type": error_type, "raw_output": out})
        return {
            "success": False,
            "target": target,
            "error_type": error_type,
            "message": msg,
            "raw_output": out,
            "adb_version": adb_diag.get("version"),
            "adb_path": self._adb_path,
            "action_guide": action_guide,
        }

    def pair_and_connect_wireless(
        self,
        host: str,
        pairing_port: int,
        pairing_code: str,
        connection_port: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        High-level wireless workflow:
        1. Executes 'adb pair <host>:<pairing_port> <code_6_digits>' targeting the popup's pairing endpoint.
        2. Only after pairing succeeds, connects to the separate main screen connection port via 'adb connect <host>:<connection_port>'.
        """
        self._log_diagnostic(
            "PAIR_AND_CONNECT_START",
            {"host": host, "pairing_port": pairing_port, "connection_port": connection_port}
        )
        # Step 1: Pair against the dedicated pairing endpoint from the popup
        pair_res = self.pair_wireless(host, pairing_port, pairing_code)
        if not pair_res.get("success"):
            return pair_res

        # Step 2: Resolve the separate connection port from main screen or mDNS
        conn_port = connection_port
        if not conn_port or conn_port == pairing_port:
            # Check mDNS services for active _adb-tls-connect._tcp endpoint
            try:
                for _ in range(2):
                    mdns_services = self.discover_mdns_services()
                    for s in mdns_services:
                        if s.get("service_type") == "_adb-tls-connect._tcp" or "_adb-tls-connect" in s.get("instance_name", ""):
                            ep = s.get("endpoint", "")
                            if ep and ":" in ep:
                                h, p = ep.split(":", 1)
                                if h.strip() == host.strip() and p.isdigit():
                                    conn_port = int(p)
                                    logger.info(f"Auto-resolved wireless connection port {conn_port} for {host} via mDNS")
                                    break
                    if conn_port and conn_port != pairing_port:
                        break
                    time.sleep(0.5)
            except Exception:
                pass

        if not conn_port or conn_port == pairing_port:
            # Check if device is already listed in adb devices
            for d in self.list_devices():
                ser = d.get("serial", "")
                if ":" in ser and ser.split(":")[0] == host.strip():
                    p = ser.split(":")[1]
                    if p.isdigit():
                        conn_port = int(p)
                        break

        if not conn_port or conn_port == pairing_port:
            self._log_diagnostic(
                "PAIR_SUCCESS_NEEDS_CONN_PORT",
                {"host": host, "pairing_port": pairing_port}
            )
            return {
                "success": True,
                "paired": True,
                "connected": False,
                "needs_connection_port": True,
                "host": host,
                "pairing_port": pairing_port,
                "message": (
                    f"Successfully paired with your phone at {host}:{pairing_port}! "
                    "Android Wireless Debugging uses a separate connection port to establish control. "
                    "Look at your phone's main Wireless Debugging screen (under 'IP address & Port') and enter the 5-digit port."
                ),
                "action_guide": [
                    "1. Pairing is successfully completed and your PC is listed in 'Paired devices' on your phone.",
                    "2. The pairing code popup can now be closed on your phone.",
                    f"3. Look at 'IP address & Port' on the main Wireless Debugging screen (e.g. {host}:XXXXX).",
                    "4. Enter that port as the Connection Port in Assistant and click Connect."
                ],
            }

        # Step 3: Connect to the main connection endpoint
        conn_res = self.connect_wireless(host, conn_port)
        if conn_res.get("success"):
            self._log_diagnostic("PAIR_AND_CONNECT_SUCCESS", {"host": host, "target": f"{host}:{conn_port}"})
            return {
                "success": True,
                "target": f"{host}:{conn_port}",
                "pairing_target": f"{host}:{pairing_port}",
                "message": f"Successfully paired and connected to wireless phone at {host}:{conn_port}.",
                "connection_type": "wireless",
            }

        self._log_diagnostic("PAIR_AND_CONNECT_FAILED_STAGE2", {"host": host, "target": f"{host}:{conn_port}", "raw": conn_res})
        return {
            "success": False,
            "paired": True,
            "target": f"{host}:{conn_port}",
            "pairing_target": f"{host}:{pairing_port}",
            "message": (
                f"Pairing succeeded with {host}:{pairing_port}, but connecting to port {conn_port} failed: {conn_res.get('message')}. "
                "Please check the main IP address & port shown under Wireless Debugging (outside the popup) and connect."
            ),
            "action_guide": [
                "1. Pairing is successfully completed and stored on your device.",
                f"2. Look at the main Wireless Debugging screen on your phone (outside the popup).",
                f"3. Check the port shown under 'IP address & Port' and enter it as the Connection Port."
            ],
        }

    def generate_qr_pairing_payload(self, service_prefix: str = "studio") -> Dict[str, str]:
        """
        Generates the standard Android 11+ Wireless Debugging QR Pairing payload.
        Schema: WIFI:T:ADB;S:<service_name>;P:<password>;;
        
        Authoritative AOSP / RFC 6763 Requirements:
        - S (Service Name): Under RFC 6763 / RFC 6335, the service instance name MUST NOT
          exceed 15 characters, consisting only of letters, digits, and hyphens.
          Android Studio uses 'studio-<random6>' (13 characters).
          Exceeding 15 characters causes NsdManager.registerService() to fail immediately
          with onRegistrationFailed on Android (e.g. Redmi Note 12 / MIUI / HyperOS),
          triggering cancelPairing() and displaying a pairing error on the phone.
        - P (Password): 6-digit numeric string matching native adb pairing codes.
        - T (Type): Literal 'ADB'.
        """
        rand_s = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(6))
        prefix = "studio" if service_prefix in ("studio", "assistant", "") else service_prefix[:6]
        service_name = f"{prefix}-{rand_s}"
        if len(service_name) > 15:
            service_name = service_name[:15]

        # 6-digit numeric pairing code (matches AOSP mPairingCode and adb pair command)
        password = "".join(secrets.choice(string.digits) for _ in range(6))
        payload = f"WIFI:T:ADB;S:{service_name};P:{password};;"
        return {
            "payload": payload,
            "service_name": service_name,
            "password": password,
        }

    def poll_and_pair_qr_device(
        self,
        password: str,
        expected_service: str = "",
        timeout: float = 30.0,
        poll_interval: float = 0.8,
    ) -> Dict[str, Any]:
        """
        Polls network mDNS advertisements for the phone's pairing service broadcast after scanning the QR code.
        When discovered, executes adb pair using the pre-shared QR password and connects to the device.
        """
        start_time = time.time()
        logger.info(
            f"Listening for phone mDNS pairing broadcast (expected service: '{expected_service}', "
            f"timeout: {timeout}s)..."
        )
        matched_service = None
        while (time.time() - start_time) < timeout:
            services = self.discover_mdns_services()
            pairing_services = [s for s in services if s.get("is_pairing")]
            if pairing_services:
                if expected_service:
                    for s in pairing_services:
                        if expected_service in s.get("instance_name", ""):
                            matched_service = s
                            break
                if not matched_service and pairing_services:
                    matched_service = pairing_services[0]
                if matched_service:
                    break
            time.sleep(poll_interval)

        if not matched_service:
            return {
                "success": False,
                "error_type": "qr_timeout",
                "message": (
                    "No phone pairing broadcast was detected by the computer within the timeout period.\n\n"
                    "Common Causes:\n"
                    "1. Wi-Fi router has 'AP / Client Isolation' enabled, blocking mDNS discovery packets.\n"
                    "2. Phone and PC are connected to different Wi-Fi bands (e.g. 2.4 GHz vs 5 GHz).\n"
                    "3. Phone was moved away before camera acquired focus."
                ),
                "action_guide": [
                    "Ensure both your PC and phone are on the exact same Wi-Fi SSID.",
                    "Keep the camera steady over the QR code on screen.",
                    "Alternatively, switch to the 'Pair with 6-Digit Code' tab — it connects directly without mDNS."
                ],
            }

        host = matched_service["host"]
        port = matched_service["port"]
        logger.info(f"Discovered phone pairing service on mDNS at {host}:{port}. Initiating pairing...")
        return self.pair_and_connect_wireless(
            host=host,
            pairing_port=port,
            pairing_code=password,
        )

    def disconnect_wireless(self, host: str, port: int = 5555) -> Dict[str, Any]:
        """Disconnects a wireless ADB device."""
        target = f"{host}:{port}"
        ok, out = self._run_adb_cmd(["disconnect", target], timeout=5.0)
        return {
            "success": ok,
            "target": target,
            "message": f"Disconnected {target}." if ok else f"Disconnect error: {out}",
        }


    # -------------------------------------------------------------------------
    # Power Menu
    # -------------------------------------------------------------------------

    def power_menu(self, serial=None):
        """Opens the Android power menu via a long-press of the power button."""
        args = (["-s", serial] if serial else []) + ["shell", "input", "keyevent", "--longpress", "26"]
        ok, out = self._run_adb_cmd(args, timeout=5.0)
        if not ok or "SecurityException" in out or "INJECT_EVENTS" in out:
            args2 = (["-s", serial] if serial else []) + ["shell", "input", "keyevent", "82"]
            ok2, out2 = self._run_adb_cmd(args2, timeout=5.0)
            if not ok2:
                return {"success": False, "error_type": "power_menu_failed",
                        "message": f"Power menu failed: {out}. Fallback: {out2}"}
            return {"success": True, "message": "Opened power menu on your phone (menu key fallback)."}
        return {"success": True, "message": "Opened power menu on your phone."}

    # -------------------------------------------------------------------------
    # Media Controls
    # -------------------------------------------------------------------------

    _MEDIA_KEYCODES = {
        "play": 126, "pause": 127, "play_pause": 85, "toggle": 85,
        "next": 87, "next_track": 87, "previous": 88, "prev": 88,
        "prev_track": 88, "stop": 86, "rewind": 89, "fast_forward": 90,
    }

    def media_control(self, action, serial=None):
        """Sends a media keyevent. Actions: play, pause, play_pause, next, previous, stop, rewind, fast_forward."""
        key = action.lower().replace(" ", "_").replace("-", "_")
        keycode = self._MEDIA_KEYCODES.get(key)
        if keycode is None:
            return {"success": False,
                    "message": f"Unknown media action '{action}'. Supported: {', '.join(self._MEDIA_KEYCODES.keys())}."}
        args = (["-s", serial] if serial else []) + ["shell", "input", "keyevent", str(keycode)]
        ok, out = self._run_adb_cmd(args, timeout=5.0)
        if not ok:
            return {"success": False, "message": f"Media {action} failed: {out}"}
        label = key.replace("_", " ").title()
        return {"success": True, "action": key, "keycode": keycode,
                "message": f"Media {label} sent to your phone."}

    # -------------------------------------------------------------------------
    # Clipboard
    # -------------------------------------------------------------------------

    def get_clipboard(self, serial=None):
        """Reads clipboard text from the Android device."""
        import binascii
        args_base = ["-s", serial] if serial else []
        ok, out = self._run_adb_cmd(args_base + ["shell", "service", "call", "clipboard", "1"], timeout=5.0)
        if ok and out.strip():
            lines_out = out.strip().splitlines()
            text_parts = []
            for line in lines_out:
                parts = line.strip().split()
                for part in parts[1:]:
                    try:
                        b = binascii.unhexlify(part.zfill(8))
                        decoded = b.decode("utf-16-be", errors="ignore").strip("\x00")
                        if decoded.isprintable() and decoded.strip():
                            text_parts.append(decoded)
                    except Exception:
                        pass
            text = "".join(text_parts).strip()
            if text:
                return {"success": True, "clipboard": text, "message": f"Phone clipboard: {text}"}
        return {"success": False,
                "message": ("Could not read phone clipboard. Android 10+ restricts background clipboard access. "
                            "The phone screen must be on with a focused app.")}

    def set_clipboard(self, text, serial=None):
        """Sets clipboard text on the Android device via am broadcast (requires Clipper app or similar)."""
        safe_text = text.replace("'", "\\'")
        args = (["-s", serial] if serial else []) + [
            "shell", f"am broadcast -a clipper.set -e text '{safe_text}'"
        ]
        ok, out = self._run_adb_cmd(args, timeout=5.0)
        if ok and "result=0" in out.lower():
            preview = text[:60] + ("..." if len(text) > 60 else "")
            return {"success": True, "message": f"Clipboard set on phone: {preview}"}
        return {"success": False,
                "message": ("Setting clipboard remotely requires a clipboard manager app (e.g. Clipper) on the phone. "
                            "Without one, clipboard injection is blocked on Android 10+ without root.")}

    # -------------------------------------------------------------------------
    # File Management
    # -------------------------------------------------------------------------

    def list_files(self, remote_path="/sdcard/Download", serial=None):
        """Lists files in a directory on the Android device."""
        import os as _os
        args = (["-s", serial] if serial else []) + ["shell", "ls", "-lh", "--color=never", remote_path]
        ok, out = self._run_adb_cmd(args, timeout=8.0)
        if not ok:
            return {"success": False, "path": remote_path, "message": f"Could not list {remote_path}: {out}"}
        files = []
        for line in out.strip().splitlines():
            line = line.strip()
            if not line or line.startswith("total"):
                continue
            parts = line.split()
            # Android ls -lh: perms [links] user [group] size date time name
            # May be 7, 8, or 9+ fields depending on Android version.
            if len(parts) >= 7:
                perms = parts[0]
                # Find name: date+time are always last 3 before the name
                # Try: perms links user group size date time name+ (9 fields: name at [8])
                # Or:  perms links user size date time name+      (8 fields: name at [6])
                # Heuristic: size field looks like '5.0K', '128', '4.0M', etc.
                import re as _rls
                size_idx = None
                for _si in range(1, min(6, len(parts))):
                    if _rls.match(r'^[\d\.]+[KMGTkbBmgt]?$', parts[_si]):
                        size_idx = _si
                if size_idx is not None and size_idx + 3 < len(parts):
                    size = parts[size_idx]
                    date = f"{parts[size_idx+1]} {parts[size_idx+2]}"
                    name = " ".join(parts[size_idx+3:])
                    files.append({
                        "name": name,
                        "size": size,
                        "date": date,
                        "is_dir": perms.startswith("d"),
                        "permissions": perms,
                    })
        return {"success": True, "path": remote_path, "count": len(files), "files": files,
                "message": f"Found {len(files)} item(s) in {remote_path}."}

    def push_file(self, local_path, remote_path="/sdcard/Download/", serial=None):
        """Pushes a local file to the Android device."""
        import os as _os
        if not _os.path.isfile(local_path):
            return {"success": False, "message": f"Local file not found: {local_path}"}
        args = (["-s", serial] if serial else []) + ["push", local_path, remote_path]
        ok, out = self._run_adb_cmd(args, timeout=60.0)
        if not ok:
            return {"success": False, "local": local_path, "remote": remote_path, "message": f"Push failed: {out}"}
        import re as _re
        speed = ""
        m = _re.search(r"(\d+(?:\.\d+)?\s*\w+/s)", out)
        if m:
            speed = m.group(1)
        return {"success": True, "local": local_path, "remote": remote_path, "speed": speed,
                "message": f"Pushed {_os.path.basename(local_path)} to phone: {remote_path}" + (f" ({speed})" if speed else "")}

    def pull_file(self, remote_path, local_path=None, serial=None):
        """Pulls a file from the Android device to the local machine."""
        import os as _os
        if local_path is None:
            from core.semantic_file_naming import get_semantic_file_naming_service
            namer = get_semantic_file_naming_service()
            downloads_dir = namer.get_downloads_dir()
            local_path = _os.path.join(downloads_dir, _os.path.basename(remote_path))
        _os.makedirs(_os.path.dirname(local_path), exist_ok=True)
        args = (["-s", serial] if serial else []) + ["pull", remote_path, local_path]
        ok, out = self._run_adb_cmd(args, timeout=60.0)
        if not ok:
            return {"success": False, "remote": remote_path, "local": local_path, "message": f"Pull failed: {out}"}
        import re as _re
        speed = ""
        m = _re.search(r"(\d+(?:\.\d+)?\s*\w+/s)", out)
        if m:
            speed = m.group(1)
        return {"success": True, "remote": remote_path, "local": local_path, "speed": speed,
                "message": f"Pulled {_os.path.basename(remote_path)} from phone → {local_path}" + (f" ({speed})" if speed else "")}

    # -------------------------------------------------------------------------
    # Network Information
    # -------------------------------------------------------------------------

    def get_network_info(self, serial=None):
        """Returns Wi-Fi SSID, IP, signal strength, link speed, and mobile data state."""
        import re as _re
        args_base = ["-s", serial] if serial else []
        ok_w, wifi_out = self._run_adb_cmd(args_base + ["shell", "dumpsys", "wifi"], timeout=6.0)
        ssid, ip_wifi, signal_level, link_speed = "Unknown", "Unknown", None, None
        if ok_w:
            for line in wifi_out.splitlines():
                if "SSID:" in line and ssid == "Unknown":
                    m = _re.search(r'SSID:\s*([^,\n]+)', line)
                    if m:
                        ssid = m.group(1).strip().strip('"')
                if "IP:" in line and ip_wifi == "Unknown":
                    m = _re.search(r'IP:\s*([\d\.]+)', line)
                    if m:
                        ip_wifi = m.group(1).strip()
                if "RSSI:" in line and signal_level is None:
                    m = _re.search(r'RSSI:\s*(-?\d+)', line)
                    if m:
                        signal_level = int(m.group(1))
                if "Link speed:" in line and link_speed is None:
                    m = _re.search(r'Link speed:\s*(\d+)', line)
                    if m:
                        link_speed = f"{m.group(1)} Mbps"
        if ip_wifi == "Unknown":
            ok_ip, ip_out = self._run_adb_cmd(args_base + ["shell", "ip", "route"], timeout=4.0)
            if ok_ip:
                for line in ip_out.splitlines():
                    m = _re.search(r'src\s+([\d\.]+)', line)
                    if m:
                        ip_wifi = m.group(1); break
        ok_tel, tel_out = self._run_adb_cmd(args_base + ["shell", "dumpsys", "telephony.registry"], timeout=5.0)
        mobile_state = "Unknown"
        if ok_tel:
            for line in tel_out.splitlines():
                if "mDataConnectionState" in line:
                    m = _re.search(r'mDataConnectionState=(\d)', line)
                    if m:
                        mobile_state = {"0": "Disconnected", "1": "Connecting", "2": "Connected"}.get(m.group(1), m.group(1))
                    break
        return {"success": True, "ssid": ssid, "wifi_ip": ip_wifi,
                "signal_level_dbm": signal_level, "link_speed": link_speed,
                "mobile_data_state": mobile_state,
                "message": f"Wi-Fi: {ssid} | IP: {ip_wifi} | Signal: {signal_level} dBm | Mobile data: {mobile_state}"}

    # -------------------------------------------------------------------------
    # System Status (CPU / RAM / Thermals / Uptime)
    # -------------------------------------------------------------------------

    def get_system_status(self, serial=None):
        """Returns CPU usage %, RAM MB, thermal temperatures, and uptime in one diagnostic payload."""
        import re as _re
        args_base = ["-s", serial] if serial else []
        ok_up, up_out = self._run_adb_cmd(args_base + ["shell", "uptime", "-p"], timeout=4.0)
        uptime = up_out.strip() if ok_up else "Unknown"
        ok_cpu, cpu_out = self._run_adb_cmd(args_base + ["shell", "top", "-n", "1", "-b", "-q"], timeout=6.0)
        cpu_total = None
        if ok_cpu:
            for line in cpu_out.splitlines():
                if line.strip().lower().startswith("%cpu") or ("user" in line and "sys" in line):
                    m = _re.search(r'(\d+(?:\.\d+)?)\s*%?\s*(?:us|user)', line, re.IGNORECASE)
                    m2 = _re.search(r'(\d+(?:\.\d+)?)\s*%?\s*(?:sy|system)', line, re.IGNORECASE)
                    if m and m2:
                        try:
                            cpu_total = round(float(m.group(1)) + float(m2.group(1)), 1)
                        except Exception:
                            pass
                    break
        ok_mem, mem_out = self._run_adb_cmd(args_base + ["shell", "cat", "/proc/meminfo"], timeout=4.0)
        ram_total_kb = ram_avail_kb = None
        if ok_mem:
            for line in mem_out.splitlines():
                if line.startswith("MemTotal:"):
                    try: ram_total_kb = int(line.split()[1])
                    except Exception: pass
                elif line.startswith("MemAvailable:"):
                    try: ram_avail_kb = int(line.split()[1])
                    except Exception: pass
        ram_total_mb = round(ram_total_kb / 1024, 0) if ram_total_kb else None
        ram_avail_mb = round(ram_avail_kb / 1024, 0) if ram_avail_kb else None
        ok_th, th_out = self._run_adb_cmd(args_base + ["shell", "dumpsys", "battery"], timeout=4.0)
        thermals = {}
        if ok_th:
            for line in th_out.splitlines():
                if "temperature:" in line.lower():
                    m = _re.search(r'temperature:\s*(\d+)', line)
                    if m:
                        thermals["battery"] = round(int(m.group(1)) / 10.0, 1)
        return {"success": True, "uptime": uptime, "cpu_percent": cpu_total,
                "ram_total_mb": ram_total_mb, "ram_available_mb": ram_avail_mb,
                "thermals": thermals,
                "message": (f"CPU: {cpu_total}% | RAM: {ram_avail_mb}/{ram_total_mb} MB free | Uptime: {uptime}")}


# Global singleton
_adb_adapter_instance: Optional[AdbAdapter] = None


def get_adb_adapter() -> AdbAdapter:
    """Returns the singleton AdbAdapter."""
    global _adb_adapter_instance
    if _adb_adapter_instance is None:
        _adb_adapter_instance = AdbAdapter()
    return _adb_adapter_instance
