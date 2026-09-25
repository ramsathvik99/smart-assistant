"""
Weather Engine - Live weather information provider for Nova Smart Assistant.
Powered by the Open-Meteo global meteorological API (free, real-time, zero-key).
"""

import logging
import re
import json
import urllib.request
import urllib.parse
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# WMO Weather interpretation codes (WW)
WMO_WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "foggy",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "moderate drizzle",
    55: "dense drizzle",
    61: "slight rain",
    62: "moderate rain",
    65: "heavy rain",
    71: "slight snowfall",
    73: "moderate snowfall",
    75: "heavy snowfall",
    80: "slight rain showers",
    81: "moderate rain showers",
    82: "violent rain showers",
    95: "thunderstorm",
    96: "thunderstorm with slight hail",
    99: "thunderstorm with heavy hail"
}


NON_LOCATION_TERMS = {
    "here", "local", "my location", "current location", "me", "there",
    "my area", "this area", "home", "outside", "today", "tomorrow",
    "now", "tonight", "the area", "town", "city", "nearby"
}


class WeatherEngine:
    """Live weather information provider using Open-Meteo."""

    def __init__(self):
        self.cache = {}
        logger.info("[WEATHER] Live Weather Engine initialized (Open-Meteo provider)")

    def get_default_location(self) -> str:
        """Resolve current local device location if available, otherwise fallback."""
        try:
            from skills.device_location import get_location_detector
            city = get_location_detector().get_city()
            if city and city.strip():
                return city.strip()
        except Exception as e:
            logger.debug(f"[WEATHER] Could not detect device location: {e}")
        return "Local"

    @property
    def default_location(self) -> str:
        return self.get_default_location()

    def extract_location(self, query: str) -> Optional[str]:
        """Extract explicitly named city/location from natural query like 'weather in Guntur' -> 'Guntur'"""
        if not query:
            return None

        # Clean wake words at start
        cleaned = re.sub(r'^(?:friday|nova|assistant|computer|hey\s+friday|hey\s+nova)[,\s]+', '', query.strip(), flags=re.IGNORECASE)
        cleaned = cleaned.rstrip('?.! ')

        # Remove trailing time/conversational modifiers at the end
        trailing_pattern = r'\s+(?:or\s+not|today|tomorrow|tonight|right\s+now|now|currently|outside|this\s+week|this\s+weekend|please|thanks?)$'
        while re.search(trailing_pattern, cleaned, flags=re.IGNORECASE):
            cleaned = re.sub(trailing_pattern, '', cleaned, flags=re.IGNORECASE).rstrip('?.! ')

        # 1. Prepositional patterns: <weather context> (in|at|for|near|around|of) <Location>
        prep_patterns = [
            # Explicit weather/condition keywords followed by preposition
            r'\b(?:weather(?:\s+report|\s+forecast|\s+conditions?|\s+updates?)?|temperature|temp|forecast|humidity|wind(?:\s+speed)?|precipitation|rain|raining|snow|snowing|sunny|cloudy)\s+(?:in|at|for|near|around|of)\s+([A-Za-z\s\.\'-]+)',
            # Questions: is it raining/hot/cold... in <Location>
            r'\b(?:is\s+it\s+(?:going\s+to\s+)?(?:rain(?:ing)?|snow(?:ing)?|hot|cold|warm|cool|sunny|cloudy|dry)|will\s+it\s+(?:rain|snow)|does\s+it\s+rain|can\s+it\s+rain)\s+(?:in|at|for|near|around)\s+([A-Za-z\s\.\'-]+)',
            # Questions: how is the weather / what is the weather like in <Location>
            r'\b(?:how\s+is\s+the\s+weather|what(?:\'s|\s+is)\s+(?:the\s+)?weather(?:\s+like)?)\s+(?:in|at|for|near|around|of)\s+([A-Za-z\s\.\'-]+)',
            # General: (in|at|for|near|around) <Location> at the end of the query
            r'\b(?:in|at|for|near|around)\s+([A-Za-z\s\.\'-]+)$',
        ]

        for pat in prep_patterns:
            m = re.search(pat, cleaned, re.IGNORECASE)
            if m:
                candidate = m.group(1).strip()
                candidate = re.sub(trailing_pattern, '', candidate, flags=re.IGNORECASE).strip()
                if candidate.lower() not in NON_LOCATION_TERMS and len(candidate) > 1:
                    return ' '.join(word.capitalize() for word in candidate.split())

        # 2. Inverted patterns: "<Location> weather [forecast/report]"
        inv_match = re.search(r'^([A-Za-z\s\.\'-]+?)\s+weather(?:\s+forecast|\s+report)?$', cleaned, re.IGNORECASE)
        if inv_match:
            candidate = inv_match.group(1).strip()
            first_word = candidate.split()[0].lower() if candidate.split() else ""
            invalid_first_words = {"what", "what's", "whats", "how", "how's", "is", "are", "tell", "check", "get", "show", "will", "does", "can", "the", "a", "an", "my", "your", "our"}
            if first_word not in invalid_first_words and candidate.lower() not in NON_LOCATION_TERMS and len(candidate) > 1:
                return ' '.join(word.capitalize() for word in candidate.split())

        return None

    def _geocode_city(self, city_name: str) -> Optional[Dict[str, Any]]:
        """Geocode city name to latitude and longitude using Open-Meteo Geocoding API."""
        try:
            cached = self.cache.get(f"geo_{city_name.lower()}")
            if cached:
                return cached

            encoded = urllib.parse.quote(city_name)
            url = f"https://geocoding-api.open-meteo.com/v1/search?name={encoded}&count=1&language=en&format=json"
            req = urllib.request.Request(url, headers={"User-Agent": "NovaAssistant/1.0"})

            with urllib.request.urlopen(req, timeout=4) as response:
                data = json.loads(response.read().decode("utf-8"))
                results = data.get("results")
                if results and len(results) > 0:
                    geo = {
                        "name": results[0].get("name", city_name),
                        "country": results[0].get("country", ""),
                        "lat": results[0].get("latitude"),
                        "lon": results[0].get("longitude")
                    }
                    self.cache[f"geo_{city_name.lower()}"] = geo
                    return geo
        except Exception as e:
            logger.warning(f"[WEATHER] Geocoding failed for '{city_name}': {e}")
        return None

    def get_weather_data(self, location: str) -> Dict[str, Any]:
        """Fetch live structured weather metrics from Open-Meteo."""
        loc_str = location.strip() if location else self.default_location
        if loc_str.lower() in ("local", "here", "current", "my location", "your current location"):
            loc_str = self.default_location

        geo = self._geocode_city(loc_str)
        if not geo:
            return {
                "success": False,
                "location": loc_str,
                "message": f"Could not find coordinates for '{loc_str}'."
            }

        lat, lon = geo["lat"], geo["lon"]
        city_display = f"{geo['name']}, {geo['country']}" if geo.get("country") else geo["name"]

        try:
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m"
                f"&daily=weather_code,temperature_2m_max,temperature_2m_min&timezone=auto"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "NovaAssistant/1.0"})

            with urllib.request.urlopen(req, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
                current = payload.get("current", {})

                temp_c = current.get("temperature_2m")
                feels_like_c = current.get("apparent_temperature")
                humidity = current.get("relative_humidity_2m")
                wind_kmh = current.get("wind_speed_10m")
                precip_mm = current.get("precipitation", 0.0)
                code = current.get("weather_code", 0)
                condition = WMO_WEATHER_CODES.get(code, "fair")

                daily = payload.get("daily", {})
                times = daily.get("time", [])
                max_t = daily.get("temperature_2m_max", [])
                min_t = daily.get("temperature_2m_min", [])
                w_codes = daily.get("weather_code", [])
                forecast_items = []
                for i in range(min(len(times), 5)):
                    forecast_items.append({
                        "date": times[i],
                        "condition": WMO_WEATHER_CODES.get(w_codes[i], "clear"),
                        "max_temp": max_t[i],
                        "min_temp": min_t[i]
                    })

                speech_text = (
                    f"The weather in {geo['name']} is currently {condition} with a temperature of "
                    f"{round(temp_c)} degrees Celsius (feels like {round(feels_like_c)}°C). "
                    f"Humidity is at {humidity}%, and wind speed is {round(wind_kmh)} kilometers per hour."
                )

                return {
                    "success": True,
                    "status": "success",
                    "location": city_display,
                    "city": geo["name"],
                    "temperature": temp_c,
                    "feels_like": feels_like_c,
                    "humidity": humidity,
                    "wind_speed": wind_kmh,
                    "precipitation": precip_mm,
                    "condition": condition,
                    "forecast": forecast_items,
                    "message": speech_text
                }
        except Exception as e:
            logger.error(f"[WEATHER] Forecast fetch error: {e}")
            return {
                "success": False,
                "status": "error",
                "location": city_display,
                "message": f"Unable to reach weather service for {geo['name']}: {e}"
            }

    def get_weather(self, location: str) -> str:
        """Get natural-language weather summary."""
        res = self.get_weather_data(location)
        return res.get("message", "Weather information is temporarily unavailable.")

    def get_forecast(self, location: str, days: int = 3) -> str:
        """Get 3-day weather forecast summary."""
        loc_str = location.strip() if location else self.default_location
        if loc_str.lower() in ("local", "here", "current"):
            loc_str = self.default_location

        geo = self._geocode_city(loc_str)
        if not geo:
            return f"Could not find location '{loc_str}'."

        try:
            url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={geo['lat']}&longitude={geo['lon']}"
                f"&daily=weather_code,temperature_2m_max,temperature_2m_min&timezone=auto"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "NovaAssistant/1.0"})
            with urllib.request.urlopen(req, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
                daily = payload.get("daily", {})
                times = daily.get("time", [])[:days]
                max_temps = daily.get("temperature_2m_max", [])[:days]
                min_temps = daily.get("temperature_2m_min", [])[:days]
                codes = daily.get("weather_code", [])[:days]

                day_summaries = []
                for i in range(len(times)):
                    cond = WMO_WEATHER_CODES.get(codes[i], "clear")
                    day_summaries.append(f"{times[i]}: {cond}, high {round(max_temps[i])}°C / low {round(min_temps[i])}°C")

                return f"Forecast for {geo['name']}: " + "; ".join(day_summaries) + "."
        except Exception as e:
            return f"Unable to retrieve forecast: {e}"


_default_weather_engine = WeatherEngine()

def get_weather(location: Optional[str] = None) -> str:
    loc = location or _default_weather_engine.default_location
    return _default_weather_engine.get_weather(loc)

def get_weather_forecast(location: Optional[str] = None, days: int = 3) -> Dict[str, Any]:
    loc = location or _default_weather_engine.default_location
    return _default_weather_engine.get_weather_data(loc)

def get_weather_for_query(query: str, explicit_location: Optional[str] = None) -> str:
    """Extract location and intent from natural-language query and return live weather or forecast."""
    loc = None
    if explicit_location and str(explicit_location).strip().lower() not in ("local", "here", "current", "my location", ""):
        loc = str(explicit_location).strip()

    if not loc and query:
        loc = _default_weather_engine.extract_location(query)

    if not loc:
        loc = _default_weather_engine.default_location

    query_lower = (query or "").lower()
    if any(k in query_lower for k in ["forecast", "next days", "upcoming", "week", "future"]):
        return _default_weather_engine.get_forecast(loc, days=3)
    return _default_weather_engine.get_weather(loc)

