"""
Device Location Controller
Provides conversational commands for querying current geographic location.
"""

from __future__ import annotations

from typing import Any, Optional
from .location_detector import DeviceLocationDetector, get_location_detector


class LocationController:
    def __init__(self, detector: Optional[DeviceLocationDetector] = None):
        self.detector = detector or get_location_detector()

    def handle_command(self, user_input: str) -> dict[str, Any]:
        text_low = user_input.lower().strip()
        force = any(w in text_low for w in ["refresh", "update", "reload"])
        loc = self.detector.get_current_location(force_refresh=force)
        city = loc.get("city", "Unknown Location")
        state = loc.get("state") or loc.get("region") or ""
        country = loc.get("country", "")
        src = loc.get("source", "detected")
        is_device = loc.get("is_device_location", src == "windows_hardware_location")
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        acc = loc.get("accuracy_m")

        # Format geographical hierarchy: City, State, Country
        parts = [p for p in [city, state, country] if p and p != "Unknown Location"]
        place_str = ", ".join(parts) if parts else city

        # Specific query about location detection source or provider
        if any(k in text_low for k in ["how do you know", "source", "provider", "using"]):
            if src == "windows_hardware_location":
                acc_str = f" (accuracy within ~{int(acc)}m)" if acc else ""
                coord_str = f" at coordinates {lat:.4f}, {lon:.4f}" if (lat and lon) else ""
                msg = f"Your location is determined using Windows Location Services (device Wi-Fi/hardware positioning){acc_str}{coord_str}. Current detected location is {place_str}."
            elif src == "ip_geolocation":
                msg = f"Your location is currently determined using approximate IP-based network geolocation. Current detected area is {place_str} (note: IP-based location is approximate and depends on ISP network routing)."
            else:
                msg = "Location services are currently unavailable; using fallback system status."
            return {
                "success": True,
                "city": city,
                "state": state,
                "country": country,
                "latitude": lat,
                "longitude": lon,
                "accuracy": acc,
                "source": src,
                "is_device_location": is_device,
                "location": loc,
                "message": msg
            }

        prefix = "Location refreshed. " if force else ""

        if src == "windows_hardware_location":
            acc_str = f" (accuracy ~{int(acc)}m)" if acc else ""
            msg = f"{prefix}Your current location is {place_str}{acc_str} (via Windows Location Services)."
        elif src == "ip_geolocation":
            # Clearly identify as approximate IP-based location; do NOT present with exact high confidence
            msg = f"{prefix}Your approximate location is {place_str}, based on IP network geolocation (note: IP geolocation is approximate and may not reflect your exact physical city)."
        else:
            msg = "Could not determine your physical location. Device location services and network geolocation are unavailable."

        return {
            "success": loc.get("status") == "success",
            "city": city,
            "state": state,
            "country": country,
            "latitude": lat,
            "longitude": lon,
            "accuracy": acc,
            "source": src,
            "is_device_location": is_device,
            "location": loc,
            "message": msg
        }


_controller_instance: Optional[LocationController] = None


def get_location_controller() -> LocationController:
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = LocationController()
    return _controller_instance
