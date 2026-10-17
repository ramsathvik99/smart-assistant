import os
import sys
import locale
import logging
import threading
import requests

logger = logging.getLogger(__name__)

class CountryDetector:
    """Detects user country with zero query latency and asynchronous refresh."""
    
    _cached_country = None
    _detection_started = False
    _lock = threading.Lock()
    
    @classmethod
    def _detect_local_default(cls) -> str:
        """Fast offline local locale check (0.01 ms)."""
        try:
            loc = locale.getdefaultlocale()[0]
            if loc and "_" in loc:
                cc = loc.split("_")[-1].upper()
                if len(cc) == 2:
                    return cc
        except Exception:
            pass
        return "IN"

    @classmethod
    def detect_country(cls) -> str:
        """
        Detects the user's country code (ISO 3166-1 alpha-2).
        Returns immediately from cache or local locale, with background IP refresh.
        """
        if cls._cached_country:
            return cls._cached_country
            
        with cls._lock:
            if cls._cached_country:
                return cls._cached_country
            # Seed immediately with local locale (instant, sub-millisecond)
            cls._cached_country = cls._detect_local_default()
            
            # Refresh via IP asynchronously if not already running
            if not cls._detection_started:
                cls._detection_started = True
                def _bg_detect():
                    try:
                        resp = requests.get("https://ipapi.co/json/", timeout=3)
                        if resp.status_code == 200:
                            cc = resp.json().get("country_code")
                            if cc and len(cc) == 2:
                                cls._cached_country = cc.upper()
                    except Exception as e:
                        logger.debug(f"[CountryDetector] Background IP detection note: {e}")
                threading.Thread(target=_bg_detect, daemon=True, name="country-detector-bg").start()

            return cls._cached_country

def get_user_country() -> str:
    """Convenience function to get country."""
    return CountryDetector.detect_country()
