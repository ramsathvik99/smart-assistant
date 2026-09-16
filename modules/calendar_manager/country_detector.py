import requests
import logging

class CountryDetector:
    """Detects user country based on IP or fallback."""
    
    _cached_country = None
    
    @classmethod
    def detect_country(cls) -> str:
        """
        Detects the user's country code (ISO 3166-1 alpha-2) via IP.
        Defaults to 'IN' if detection fails.
        """
        if cls._cached_country:
            return cls._cached_country
            
        try:
            # Use ipapi.co for free geolocation (no API key needed for basic usage)
            response = requests.get("https://ipapi.co/json/", timeout=5)
            if response.status_code == 200:
                data = response.json()
                country_code = data.get("country_code", "IN")
                cls._cached_country = country_code
                return country_code
        except Exception as e:
            logging.error(f"[CountryDetector] Error detecting country: {e}")
            
        # Fallback to India
        return "IN"

def get_user_country() -> str:
    """Convenience function to get country."""
    return CountryDetector.detect_country()
