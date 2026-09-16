"""
Weather Engine - Get weather information for locations
"""

import logging
import re
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

class WeatherEngine:
    """Weather information provider"""
    
    def __init__(self):
        self.cache = {}
        self.api_key = None  # Could be set from config if API available
        logger.info("[WEATHER] Weather engine initialized")
    
    def extract_location(self, query: str) -> str:
        """Extract location from query like 'weather in Guntur' -> 'Guntur'"""
        query_lower = query.lower()
        
        # Patterns for location extraction
        patterns = [
            r'(?:weather|temperature|forecast)\s+(?:in|at|for|near)\s+([A-Za-z\s]+?)(?:\s*$|[?!])',
            r'(?:what\'?s?\s+the\s+)?weather\s+(?:in|at|for|near)\s+([A-Za-z\s]+?)(?:\s*$|[?!])',
            r'how\s+is\s+the\s+weather\s+(?:in|at|for|near)\s+([A-Za-z\s]+?)(?:\s*$|[?!])',
            r'will\s+it\s+rain\s+(?:in|at|for|near)\s+([A-Za-z\s]+?)(?:\s*$|[?!])',
            r'temperature\s+(?:in|at|for|near)\s+([A-Za-z\s]+?)(?:\s*$|[?!])',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query_lower, re.IGNORECASE)
            if match:
                location = match.group(1).strip()
                # Capitalize location name
                location = ' '.join(word.capitalize() for word in location.split())
                return location
        
        # If no location found, return generic response
        return None
    
    def get_weather(self, location: str) -> str:
        """Get weather information for a location"""
        if not location:
            return "Please specify a location to get weather information."
        
        # Normalize location
        location = location.strip()
        if not location or location.lower() in ["local", "here", "current"]:
            location = "your current location"
        
        try:
            # TODO: Integrate with real weather API (OpenWeatherMap, Weather.gov, etc.)
            # For now, return a placeholder response
            logger.info(f"[WEATHER] Query for location: {location}")
            
            # Placeholder response
            response = f"I checked the weather for {location}. "
            response += "Weather API integration is not yet available. "
            response += "Please check your local weather service for accurate information."
            
            return response
            
        except Exception as e:
            logger.error(f"[WEATHER] Error getting weather: {e}")
            return f"Could not retrieve weather information. {str(e)}"

# Global weather engine instance
_weather_engine = None

def get_weather_engine() -> WeatherEngine:
    """Get global weather engine instance"""
    global _weather_engine
    if _weather_engine is None:
        _weather_engine = WeatherEngine()
    return _weather_engine

def extract_location_from_query(query: str) -> Optional[str]:
    """Extract location from weather query"""
    engine = get_weather_engine()
    return engine.extract_location(query)

def get_weather_for_location(location: str) -> str:
    """Get weather for a specific location"""
    engine = get_weather_engine()
    return engine.get_weather(location)

def get_weather_for_query(query: str) -> str:
    """Process a weather query and return weather information"""
    engine = get_weather_engine()
    location = engine.extract_location(query)
    
    if location:
        return engine.get_weather(location)
    else:
        return engine.get_weather(None)
