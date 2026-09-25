"""
Device Location Detector
Determines current device geographic location using Windows Location APIs (GeoCoordinateWatcher),
with network IP-based geolocation fallback and OpenStreetMap reverse geocoding.
Caches results locally for 30 minutes.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

CACHE_TTL = 1800.0  # 30 minutes


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
        self._mem_time: float = 0

    def _read_cache(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if self._mem_cache and time.time() - self._mem_time < CACHE_TTL:
                return self._mem_cache
            if self.cache_file.exists():
                try:
                    data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                    if time.time() - data.get("timestamp", 0) < CACHE_TTL:
                        self._mem_cache = data
                        self._mem_time = data.get("timestamp", 0)
                        return data
                except Exception:
                    pass
        return None

    def _write_cache(self, data: Dict[str, Any]) -> None:
        with self._lock:
            data_copy = dict(data)
            data_copy["timestamp"] = time.time()
            self._mem_cache = data_copy
            self._mem_time = time.time()
            try:
                self.cache_file.write_text(json.dumps(data_copy, indent=2), encoding="utf-8")
            except Exception as e:
                logger.debug(f"Failed to write location cache: {e}")

    def _reverse_geocode_osm(self, lat: float, lon: float) -> Dict[str, Any]:
        """Reverse geocodes coordinates to address details using OpenStreetMap Nominatim."""
        url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=10"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "SmartAssistant/1.0 (LocationModule)"})
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                addr = data.get("address", {})
                city = addr.get("city") or addr.get("town") or addr.get("village") or addr.get("county") or ""
                state = addr.get("state") or addr.get("state_district") or ""
                country = addr.get("country") or ""
                display_name = data.get("display_name") or ""
                return {
                    "city": city,
                    "state": state,
                    "country": country,
                    "display_name": display_name,
                }
        except Exception as e:
            logger.debug(f"Reverse geocode error: {e}")
        return {}

    def _detect_via_windows_api(self) -> Optional[Dict[str, Any]]:
        """Attempts hardware/Wi-Fi positioning via Windows GeoCoordinateWatcher / WinRT Geolocator."""
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
                    return {
                        "status": "success",
                        "city": city,
                        "state": geo.get("state", ""),
                        "region": geo.get("state", ""),
                        "country": geo.get("country", ""),
                        "display_name": geo.get("display_name", ""),
                        "latitude": lat,
                        "longitude": lon,
                        "accuracy_m": accuracy,
                        "is_device_location": True,
                        "source": "windows_hardware_location",
                    }
        except Exception as e:
            logger.debug(f"Windows location API error: {e}")
        return None

    def _detect_via_ip(self) -> Optional[Dict[str, Any]]:
        """Fallback geolocation via public IP lookup."""
        endpoints = [
            "https://ipapi.co/json/",
            "http://ip-api.com/json/",
        ]
        for url in endpoints:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "SmartAssistant/1.0"})
                with urllib.request.urlopen(req, timeout=3.0) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    city = data.get("city")
                    lat = data.get("latitude") or data.get("lat")
                    lon = data.get("longitude") or data.get("lon")
                    if city:
                        return {
                            "status": "success",
                            "city": city,
                            "state": data.get("region") or data.get("regionName") or "",
                            "region": data.get("region") or data.get("regionName") or "",
                            "country": data.get("country_name") or data.get("country") or "",
                            "latitude": float(lat) if lat else 0.0,
                            "longitude": float(lon) if lon else 0.0,
                            "accuracy_m": None,
                            "is_device_location": False,
                            "source": "ip_geolocation",
                        }
            except Exception:
                continue
        return None

    def get_current_location(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Returns detected location dictionary with caching, always preferring device hardware location."""
        if not force_refresh:
            cached = self._read_cache()
            # If we have a cached hardware/device location within TTL, use it
            if cached and cached.get("source") == "windows_hardware_location" and cached.get("city"):
                return cached

        # 1. Attempt higher-accuracy Windows Location API (hardware / Wi-Fi positioning)
        res = self._detect_via_windows_api()
        if res and res.get("city"):
            self._write_cache(res)
            return res

        # If Windows API didn't succeed, check if we have a valid cached IP location
        if not force_refresh:
            cached = self._read_cache()
            if cached and cached.get("city"):
                return cached

        # 2. Try IP Geolocation fallback
        res = self._detect_via_ip()
        if res and res.get("city"):
            self._write_cache(res)
            return res

        # 3. Default fallback
        fallback = {
            "status": "unavailable",
            "city": "Unknown Location",
            "state": "",
            "region": "",
            "country": "",
            "latitude": 0.0,
            "longitude": 0.0,
            "accuracy_m": None,
            "is_device_location": False,
            "source": "fallback",
        }
        return fallback

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
