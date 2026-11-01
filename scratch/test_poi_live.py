import sys
import os
sys.path.insert(0, ".")

from skills.device_location.location_controller import get_location_controller
c = get_location_controller()
places = c.search_nearby("restaurant", 16.31097, 80.42087, radius_km=5.0, limit=5)
for i, p in enumerate(places):
    print(f"#{i+1}: {p.get('name')} | dist: {p.get('distance_km')} | lat: {p.get('latitude')} | lon: {p.get('longitude')}")

