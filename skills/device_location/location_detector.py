"""
Device Location Detector
Determines current device geographic location using a multi-tiered, deterministic strategy:
1. Primary Source: Registered & Connected Mobile Phone GPS (e.g. Redmi Note 12 via Companion Web App / ADB)
2. Fallback Source: Windows Location Services (System.Device.Location.GeoCoordinateWatcher / WinRT Geolocator)
3. Tertiary Fallback: IP-based Network Geolocation (clearly identified as approximate)
4. Offline Fallback: Stale cached location (with explicit last-known timestamp and warning)

Caches results locally and provides diagnostic status.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


def _get_config():
    try:
        from instance.config import settings
        return settings
    except Exception:
        return None


def _get_ssl_context() -> ssl.SSLContext:
    """Creates a strictly verified SSL context using the system or certifi trust store."""
    try:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


class DeviceLocationDetector:
    def __init__(self, cache_dir: Optional[str] = None):
        self._lock = threading.RLock()
        if cache_dir:
            self.cache_dir = Path(cache_dir)
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.cache_dir = project_root / "data" / "location"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cache_file = self.cache_dir / "location_cache.json"
        self._mem_cache: Optional[Dict[str, Any]] = None
        self._mem_time: float = 0.0
        self._geocode_cache: Dict[Tuple[float, float], Dict[str, Any]] = {}
        self._last_active_source: str = "none"

    def _get_thresholds(self) -> Tuple[int, int]:
        cfg = _get_config()
        live_thresh = getattr(cfg, "LOCATION_LIVE_THRESHOLD_SEC", 120) if cfg else 120
        stale_thresh = getattr(cfg, "LOCATION_STALE_THRESHOLD_SEC", 1800) if cfg else 1800
        return int(live_thresh), int(stale_thresh)

    def _read_cache(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            _, stale_thresh = self._get_thresholds()
            if self._mem_cache and (time.time() - self._mem_time < stale_thresh):
                return self._mem_cache
            if self.cache_file.exists():
                try:
                    data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                    ts = data.get("timestamp") or 0.0
                    if time.time() - ts < stale_thresh:
                        self._mem_cache = data
                        self._mem_time = ts
                        return data
                except Exception as e:
                    logger.debug(f"Failed to read location cache: {e}")
        return None

    def _write_cache(self, data: Dict[str, Any]) -> None:
        with self._lock:
            data_copy = dict(data)
            now = time.time()
            data_copy["timestamp"] = data.get("timestamp") or now
            data_copy["reception_timestamp"] = data.get("reception_timestamp") or now
            self._mem_cache = data_copy
            self._mem_time = data_copy["timestamp"]
            try:
                self.cache_file.write_text(json.dumps(data_copy, indent=2), encoding="utf-8")
            except Exception as e:
                logger.debug(f"Failed to write location cache: {e}")

    def _reverse_geocode_osm(self, lat: float, lon: float) -> Dict[str, Any]:
        """Reverse geocodes coordinates to address details using OpenStreetMap Nominatim with local caching."""
        cache_key = (round(lat, 4), round(lon, 4))
        if cache_key in self._geocode_cache:
            return self._geocode_cache[cache_key]

        cfg = _get_config()
        base_url = getattr(cfg, "NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org") if cfg else "https://nominatim.openstreetmap.org"
        url = f"{base_url.rstrip('/')}/reverse?format=json&lat={lat}&lon={lon}&zoom=14&addressdetails=1"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SmartAssistant-LocationIntelligence/1.0"})
            ctx = _get_ssl_context()
            with urllib.request.urlopen(req, context=ctx, timeout=5.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                addr = data.get("address", {})
                city = (
                    addr.get("city")
                    or addr.get("town")
                    or addr.get("suburb")
                    or addr.get("village")
                    or addr.get("county")
                    or addr.get("municipality")
                    or ""
                )
                state = addr.get("state") or addr.get("state_district") or ""
                country = addr.get("country") or ""
                road = addr.get("road") or addr.get("neighbourhood") or ""
                postcode = addr.get("postcode") or ""
                display_name = data.get("display_name") or ""

                district = addr.get("state_district") or addr.get("county") or addr.get("district") or ""
                locality = addr.get("suburb") or addr.get("neighbourhood") or addr.get("residential") or addr.get("hamlet") or ""
                components = {
                    "country": country,
                    "state": state,
                    "district": district,
                    "city": city,
                    "locality": locality,
                    "road": road,
                    "postcode": postcode,
                }
                res = {
                    "city": city,
                    "state": state,
                    "district": district,
                    "locality": locality,
                    "country": country,
                    "road": road,
                    "postcode": postcode,
                    "components": components,
                    "display_name": display_name,
                }
                self._geocode_cache[cache_key] = res
                return res
        except Exception as e:
            logger.debug(f"Reverse geocode error: {e}")

        fallback = {
            "city": f"{lat:.2f},{lon:.2f}",
            "state": "",
            "district": "",
            "locality": "",
            "country": "",
            "road": "",
            "postcode": "",
            "components": {
                "country": "",
                "state": "",
                "district": "",
                "city": f"{lat:.2f},{lon:.2f}",
                "locality": "",
                "road": "",
                "postcode": "",
            },
            "display_name": f"{lat:.4f}, {lon:.4f}",
        }
        return fallback

    def get_phone_location(self, user_id: Optional[Any] = None) -> Dict[str, Any]:
        """
        Retrieves the location of the user's connected phone only (e.g. Redmi Note 12 via Companion / ADB).
        Never falls back to PC or IP geolocation.
        Clearly discloses measurement age, accuracy, and source.
        """
        try:
            from skills.device_management.device_controller import get_device_controller
            dc = get_device_controller()
            effective_uid = user_id or 1
            phone_res = dc.get_phone_location(user_id=effective_uid)

            if phone_res and phone_res.get("success") and phone_res.get("status") == "success":
                lat = float(phone_res.get("latitude"))
                lon = float(phone_res.get("longitude"))
                acc = phone_res.get("accuracy_m")
                ts = phone_res.get("timestamp")
                dev_name = phone_res.get("device", "Phone")
                dev_id = phone_res.get("device_id", "phone_device")

                age_sec = 0.0
                if ts:
                    try:
                        from datetime import datetime, timezone
                        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                        age_sec = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())
                    except Exception:
                        pass

                live_thresh, stale_thresh = self._get_thresholds()
                if age_sec <= live_thresh:
                    freshness = "live"
                    freshness_label = "Live right now"
                elif age_sec <= stale_thresh:
                    freshness = "recent"
                    freshness_label = f"Last seen {int(age_sec // 60)} minutes ago"
                else:
                    freshness = "stale"
                    freshness_label = f"Last known ({int(age_sec // 60)} minutes ago)"

                geo = self._reverse_geocode_osm(lat, lon)
                city = geo.get("city") or f"{lat:.2f},{lon:.2f}"
                maps_url = phone_res.get("maps_url") or f"https://www.google.com/maps?q={lat},{lon}"

                acc_str = f", accuracy ±{int(acc)}m" if acc else ""
                age_str = f", measured {int(age_sec)}s ago" if age_sec < 120 else f", measured {int(age_sec // 60)}m ago"
                msg = f"Your phone ({dev_name}) is in {city} at coordinates {lat:.4f}, {lon:.4f} ({freshness_label}{acc_str}{age_str}, via Phone GPS)."

                return {
                    "success": True,
                    "status": "success",
                    "action": "phone_location",
                    "device": dev_name,
                    "device_name": dev_name,
                    "device_id": dev_id,
                    "city": city,
                    "state": geo.get("state", ""),
                    "country": geo.get("country", ""),
                    "display_name": geo.get("display_name", ""),
                    "latitude": lat,
                    "longitude": lon,
                    "accuracy_m": acc,
                    "source": "phone_gps",
                    "freshness": freshness,
                    "freshness_label": freshness_label,
                    "measurement_timestamp": ts,
                    "reception_timestamp": time.time(),
                    "age_seconds": round(age_sec, 1),
                    "maps_url": maps_url,
                    "message": msg,
                }
            else:
                reason = phone_res.get("message") if phone_res else "No connected phone found in registry"
                return {
                    "success": False,
                    "status": "unavailable",
                    "action": "phone_location",
                    "source": "phone_gps",
                    "message": f"Could not locate your phone: {reason}. Phone GPS coordinates are unavailable.",
                }
        except Exception as e:
            return {
                "success": False,
                "status": "unavailable",
                "action": "phone_location",
                "source": "phone_gps",
                "message": f"Error retrieving phone location: {str(e)}",
            }

    def get_computer_location(self) -> Dict[str, Any]:
        """
        Retrieves the location of this computer only (Windows Location Services or PC network IP).
        Never returns phone GPS coordinates.
        Clearly discloses source, measurement age, and accuracy.
        """
        # 1. Try Windows Location Services (Wi-Fi / hardware location)
        win_loc = self._detect_via_windows_api()
        if win_loc and win_loc.get("status") == "success":
            win_loc_copy = dict(win_loc)
            win_loc_copy["action"] = "computer_location"
            acc = win_loc.get("accuracy_m")
            acc_str = f", accuracy ±{int(acc)}m" if acc else ""
            win_loc_copy["message"] = (
                f"Your computer (Windows PC) is in {win_loc.get('city')} "
                f"at coordinates {win_loc.get('latitude'):.4f}, {win_loc.get('longitude'):.4f} "
                f"({win_loc.get('freshness_label')}{acc_str}, via Windows Location Services)."
            )
            return win_loc_copy

        # 2. If Windows Location Services is disabled/unavailable, fallback to PC network IP
        ip_loc = self._detect_via_ip()
        if ip_loc and ip_loc.get("status") == "success":
            ip_loc_copy = dict(ip_loc)
            ip_loc_copy["action"] = "computer_location"
            ip_loc_copy["message"] = (
                f"Your computer (Windows PC) is in {ip_loc.get('city')}, {ip_loc.get('region')} "
                f"at coordinates {ip_loc.get('latitude'):.4f}, {ip_loc.get('longitude'):.4f} "
                f"(Approximate network IP location; Windows Location Services is unavailable)."
            )
            return ip_loc_copy

        return {
            "success": False,
            "status": "unavailable",
            "action": "computer_location",
            "source": "windows_hardware_location",
            "message": "Could not locate your computer. Windows Location Services is disabled or unavailable on this machine, and network IP lookup failed.",
        }

    def _detect_via_phone(self, user_id: Optional[Any] = None) -> Optional[Dict[str, Any]]:
        """Primary location source: Registered and connected phone GPS (Redmi Note 12).
        Returns coordinates ONLY if fresh within live threshold (<=120s). Stale fixes fall through.
        """
        try:
            from skills.device_management.device_controller import get_device_controller
            dc = get_device_controller()
            effective_uid = user_id or 1
            phone_res = dc.get_phone_location(user_id=effective_uid)

            if phone_res and phone_res.get("success") and phone_res.get("status") == "success":
                lat = float(phone_res.get("latitude"))
                lon = float(phone_res.get("longitude"))
                acc = phone_res.get("accuracy_m")
                ts = phone_res.get("timestamp")
                dev_name = phone_res.get("device", "Phone")
                dev_id = phone_res.get("device_id", "phone_device")

                # Check actual age of phone measurement against 120-second live threshold
                age_sec = 999999.0
                if ts:
                    try:
                        from datetime import datetime, timezone
                        dt = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
                        age_sec = (datetime.now(timezone.utc) - dt).total_seconds()
                    except Exception:
                        pass

                live_thresh, _ = self._get_thresholds()
                # ONLY return as Tier 1 live source if fix is within live threshold (<=120s)
                if age_sec <= live_thresh and (abs(lat) > 0.0001 or abs(lon) > 0.0001):
                    geo = self._reverse_geocode_osm(lat, lon)
                    city = geo.get("city") or f"{lat:.2f},{lon:.2f}"
                    record = {
                        "status": "success",
                        "city": city,
                        "state": geo.get("state", ""),
                        "region": geo.get("state", ""),
                        "country": geo.get("country", ""),
                        "district": geo.get("district", ""),
                        "locality": geo.get("locality", ""),
                        "components": geo.get("components", {}),
                        "display_name": geo.get("display_name", ""),
                        "latitude": lat,
                        "longitude": lon,
                        "accuracy_m": acc,
                        "altitude_m": phone_res.get("altitude_m"),
                        "is_device_location": True,
                        "source": "phone_gps",
                        "device_id": dev_id,
                        "device_name": dev_name,
                        "measurement_timestamp": ts,
                        "reception_timestamp": time.time(),
                        "freshness": "live",
                        "freshness_label": "Live right now",
                        "age_seconds": round(age_sec, 1),
                        "maps_url": f"https://www.google.com/maps?q={lat},{lon}",
                    }
                    return record
                else:
                    logger.debug(f"[LOCATION] Phone GPS fix is {age_sec:.1f}s old (exceeds {live_thresh}s threshold). Falling through to next tier.")
        except Exception as e:
            logger.debug(f"[LOCATION] Primary phone detection check: {e}")
        return None

    def _detect_via_windows_api(self) -> Optional[Dict[str, Any]]:
        """Secondary fallback source: Windows Location Services (Wi-Fi / hardware location)."""
        if platform.system() != "Windows":
            return None

        script = """
        Add-Type -AssemblyName System.Device
        $w = New-Object System.Device.Location.GeoCoordinateWatcher(1)
        $w.Start()
        for ($i = 0; $i -lt 14; $i++) {
            if ($w.Status -eq [System.Device.Location.GeoPositionStatus]::Ready) { break }
            Start-Sleep -Milliseconds 250
        }
        $pos = $w.Position.Location
        if ($pos.Latitude -and $w.Status -eq [System.Device.Location.GeoPositionStatus]::Ready -and -not [Double]::IsNaN($pos.Latitude)) {
            Write-Output "$($pos.Latitude),$($pos.Longitude),$($pos.HorizontalAccuracy),Ready"
        } else {
            try {
                Add-Type -AssemblyName System.Runtime.WindowsRuntime
                $asTaskGeneric = [System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }
                [Windows.Devices.Geolocation.Geolocator,Windows.Devices.Geolocation,ContentType=WindowsRuntime] | Out-Null
                $locator = New-Object Windows.Devices.Geolocation.Geolocator
                $asyncOp = $locator.GetGeopositionAsync()
                $task = $asTaskGeneric[0].MakeGenericMethod([Windows.Devices.Geolocation.Geoposition]).Invoke($null, @($asyncOp))
                $task.Wait(3000)
                if ($task.IsCompleted) {
                    $p = $task.Result.Coordinate.Point.Position
                    $acc = $task.Result.Coordinate.Accuracy
                    Write-Output "$($p.Latitude),$($p.Longitude),$acc,Ready"
                }
            } catch {}
        }
        """
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            out = proc.stdout.strip()
            parts = [p.strip() for p in out.split(",")]
            if len(parts) >= 4 and parts[3].lower() == "ready":
                lat = float(parts[0])
                lon = float(parts[1])
                accuracy = float(parts[2]) if parts[2] and parts[2].lower() != "nan" else None
                if abs(lat) > 0.001 and abs(lon) > 0.001:
                    geo = self._reverse_geocode_osm(lat, lon)
                    city = geo.get("city") or f"{lat:.2f},{lon:.2f}"
                    now_iso = datetime.now(timezone.utc).isoformat()
                    return {
                        "status": "success",
                        "city": city,
                        "state": geo.get("state", ""),
                        "region": geo.get("state", ""),
                        "country": geo.get("country", ""),
                        "district": geo.get("district", ""),
                        "locality": geo.get("locality", ""),
                        "components": geo.get("components", {}),
                        "display_name": geo.get("display_name", ""),
                        "latitude": lat,
                        "longitude": lon,
                        "accuracy_m": accuracy,
                        "altitude_m": None,
                        "is_device_location": True,
                        "source": "windows_hardware_location",
                        "device_id": "computer_windows",
                        "device_name": "Windows PC",
                        "measurement_timestamp": now_iso,
                        "reception_timestamp": time.time(),
                        "freshness": "live",
                        "freshness_label": "Live from Windows Location Services",
                        "maps_url": f"https://www.google.com/maps?q={lat},{lon}",
                    }
        except Exception as e:
            logger.debug(f"Windows location API error: {e}")
        return None

    def _detect_via_ip(self) -> Optional[Dict[str, Any]]:
        """Tertiary fallback geolocation via public IP lookup (clearly labeled as approximate)."""
        endpoints = [
            "https://ipapi.co/json/",
            "http://ip-api.com/json/",
        ]
        for url in endpoints:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SmartAssistant/1.0"})
                ctx = _get_ssl_context() if url.startswith("https") else None
                with urllib.request.urlopen(req, context=ctx, timeout=4.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    city = data.get("city")
                    lat = data.get("latitude") or data.get("lat")
                    lon = data.get("longitude") or data.get("lon")
                    if city and lat and lon:
                        now_iso = datetime.now(timezone.utc).isoformat()
                        return {
                            "status": "success",
                            "city": city,
                            "state": data.get("region") or data.get("regionName") or "",
                            "region": data.get("region") or data.get("regionName") or "",
                            "country": data.get("country_name") or data.get("country") or "",
                            "display_name": f"{city}, {data.get('region') or ''}, {data.get('country_name') or ''}".strip(", "),
                            "latitude": float(lat),
                            "longitude": float(lon),
                            "accuracy_m": None,
                            "altitude_m": None,
                            "is_device_location": False,
                            "source": "ip_geolocation",
                            "device_id": "network_ip",
                            "device_name": "Network Geolocation",
                            "measurement_timestamp": now_iso,
                            "reception_timestamp": time.time(),
                            "freshness": "approximate",
                            "freshness_label": "Approximate network IP location",
                            "maps_url": f"https://www.google.com/maps?q={lat},{lon}",
                        }
            except Exception:
                continue
        return None

    def get_current_location(
        self,
        force_refresh: bool = False,
        user_id: Optional[Any] = None,
        allow_ip_fallback: bool = True,
    ) -> Dict[str, Any]:
        """
        Unified deterministic location source selection:
        1. Primary: Fresh phone location (Redmi Note 12 GPS)
        2. Fallback: Windows Location Services (PC Wi-Fi / hardware location)
        3. Valid Cache: Hardware location within freshness threshold
        4. Tertiary: IP Geolocation (clearly marked as approximate)
        5. Stale Cache: Labeled with actual timestamp and stale warning
        6. Unavailable: Detailed diagnostic status
        """
        live_thresh, stale_thresh = self._get_thresholds()

        # Check in-memory/disk cache if not forced refresh and cache is fresh hardware position
        if not force_refresh:
            cached = self._read_cache()
            if cached and cached.get("source") in ("phone_gps", "windows_hardware_location"):
                cached_age = time.time() - cached.get("reception_timestamp", cached.get("timestamp", 0))
                if cached_age < live_thresh and cached.get("latitude") and cached.get("longitude"):
                    return cached

        # 1. Primary Source: Phone GPS
        phone_loc = self._detect_via_phone(user_id=user_id)
        if phone_loc and phone_loc.get("status") == "success" and phone_loc.get("latitude"):
            if self._last_active_source != "phone_gps":
                logger.info(f"[LOCATION SOURCE] Switched to primary phone GPS ({phone_loc.get('device_name')})")
                self._last_active_source = "phone_gps"
            self._write_cache(phone_loc)
            return phone_loc

        # 2. Secondary Source: Windows Location Services
        win_loc = self._detect_via_windows_api()
        if win_loc and win_loc.get("status") == "success" and win_loc.get("latitude"):
            if self._last_active_source != "windows_hardware_location":
                logger.info("[LOCATION SOURCE] Using Windows Location Services fallback")
                self._last_active_source = "windows_hardware_location"
            self._write_cache(win_loc)
            return win_loc

        # Check if we have a cached hardware location within stale threshold (<=1800s)
        cached = self._read_cache()
        if cached and cached.get("source") in ("phone_gps", "windows_hardware_location") and cached.get("latitude"):
            cached_age = int(time.time() - cached.get("reception_timestamp", cached.get("timestamp", 0)))
            if cached_age <= stale_thresh:
                cached_copy = dict(cached)
                cached_copy["freshness"] = "stale" if cached_age > live_thresh else "live"
                cached_copy["freshness_label"] = f"Cached last known ({cached_age // 60} minutes ago)"
                self._last_active_source = f"cached_{cached.get('source')}"
                return cached_copy

        # 3. Tertiary Source: IP Geolocation fallback
        if allow_ip_fallback:
            ip_loc = self._detect_via_ip()
            if ip_loc and ip_loc.get("status") == "success" and ip_loc.get("latitude"):
                if self._last_active_source != "ip_geolocation":
                    logger.info("[LOCATION SOURCE] Falling back to approximate IP network geolocation")
                    self._last_active_source = "ip_geolocation"
                self._write_cache(ip_loc)
                return ip_loc

        # 4. Check if any older cache exists (mark as stale)
        if self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                ts = data.get("timestamp") or 0.0
                age_mins = int((time.time() - ts) // 60)
                data["freshness"] = "stale"
                data["freshness_label"] = f"Stale cached location ({age_mins} minutes ago)"
                self._last_active_source = "stale_cache"
                return data
            except Exception:
                pass

        # 5. Live location unavailable
        self._last_active_source = "unavailable"
        return {
            "status": "unavailable",
            "city": "Unknown Location",
            "state": "",
            "region": "",
            "country": "",
            "display_name": "Location unavailable",
            "latitude": 0.0,
            "longitude": 0.0,
            "accuracy_m": None,
            "altitude_m": None,
            "is_device_location": False,
            "source": "unavailable",
            "device_id": None,
            "device_name": None,
            "measurement_timestamp": None,
            "reception_timestamp": time.time(),
            "freshness": "unavailable",
            "freshness_label": "Location services unavailable",
            "reason": "Connected phone has no GPS fix, Windows Location Services is disabled or unavailable, and network fallback failed.",
            "maps_url": "",
        }

    def get_diagnostics(self, user_id: Optional[Any] = None) -> Dict[str, Any]:
        """Provides status breakdown of all location providers for troubleshooting."""
        effective_uid = user_id or 1
        phone_status = "unavailable"
        phone_details = "Not connected"
        try:
            from skills.device_management.device_controller import get_device_controller
            dc = get_device_controller()
            res = dc.get_phone_location(user_id=effective_uid)
            if res.get("success"):
                phone_status = "available"
                phone_details = f"{res.get('device')}: {res.get('freshness_label')} (±{int(res.get('accuracy_m') or 10)}m)"
            else:
                phone_details = res.get("message", "No GPS fix")
        except Exception as e:
            phone_details = str(e)

        windows_status = "available" if platform.system() == "Windows" else "unsupported"
        cached = self._read_cache()

        act_source = self._last_active_source
        if act_source == "none":
            if cached and cached.get("latitude"):
                act_source = f"cached_{cached.get('source', 'hardware')}"
            else:
                act_source = "unavailable"

        return {
            "primary_source": "phone_gps",
            "phone_status": phone_status,
            "phone_details": phone_details,
            "windows_location_status": windows_status,
            "active_source": act_source,
            "has_cache": cached is not None,
            "cached_source": cached.get("source") if cached else None,
            "cached_age_seconds": int(time.time() - (cached.get("timestamp") or 0)) if cached else None,
        }

    def get_city(self) -> Optional[str]:
        loc = self.get_current_location()
        city = loc.get("city")
        return city if city and city != "Unknown Location" else None


_detector_instance: Optional[DeviceLocationDetector] = None
_detector_lock = threading.Lock()


def get_location_detector() -> DeviceLocationDetector:
    global _detector_instance
    with _detector_lock:
        if _detector_instance is None:
            _detector_instance = DeviceLocationDetector()
        return _detector_instance
