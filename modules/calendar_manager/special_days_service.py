import requests
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import psycopg2
import psycopg2.extras
from core.config import CONFIG

def get_connection():
    """Get database connection."""
    from legacy.memory_manager import get_connection as get_db_connection
    return get_db_connection()

class SpecialDaysService:
    """Service for fetching and caching special days/holidays."""
    
    def __init__(self, api_key: str, region: str = "IN"):
        self.api_key = api_key
        self.region = region
        self.base_url = "https://calendarific.com/api/v2"
        self._ensure_cache_table()
    
    def _ensure_cache_table(self):
        """Ensure cache table exists in database."""
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS special_days_cache (
                    id SERIAL PRIMARY KEY,
                    date DATE NOT NULL,
                    name VARCHAR(200) NOT NULL,
                    description TEXT,
                    region VARCHAR(50) NOT NULL,
                    holiday_type VARCHAR(50),
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(date, name, region)
                )
            """)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"[Special Days] Cache table error: {e}")
        finally:
            cur.close()
            conn.close()
    
    def get_special_day(self, date_str: str) -> Optional[Dict]:
        """Get special day for a specific date."""
        cached = self._get_from_cache(date_str)
        if cached: return cached
        
        year = datetime.strptime(date_str, "%Y-%m-%d").year
        holidays = self._fetch_holidays_for_year(year)
        for h in holidays:
            if h['date'] == date_str: return h
        return None
    
    def _get_from_cache(self, date_str: str) -> Optional[Dict]:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT date, name, description, holiday_type FROM special_days_cache
                WHERE date = %s AND region = %s AND fetched_at > NOW() - INTERVAL '30 days'
                LIMIT 1
            """, (date_str, self.region))
            row = cur.fetchone()
            if row:
                return {'date': str(row['date']), 'name': row['name'], 'description': row['description'], 'type': row['holiday_type']}
            return None
        finally:
            cur.close()
            conn.close()
    
    def _fetch_holidays_for_year(self, year: int) -> List[Dict]:
        if not self.api_key: return []
        try:
            url = f"{self.base_url}/holidays"
            params = {'api_key': self.api_key, 'country': self.region, 'year': year}
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                return []
            
            meta = data.get('meta', {})
            if not isinstance(meta, dict) or meta.get('code') != 200:
                return []
            
            resp_data = data.get('response', {})
            if not isinstance(resp_data, dict):
                return []
            
            holiday_list = resp_data.get('holidays', [])
            if not isinstance(holiday_list, list):
                return []
                
            holidays = []
            for h in holiday_list:
                iso = h.get('date', {}).get('iso')
                if iso:
                    h_data = {'date': iso, 'name': h.get('name'), 'description': h.get('description', ''), 'type': ', '.join(h.get('type', []))}
                    holidays.append(h_data)
                    self._cache_holiday(h_data)
            return holidays
        except Exception as e:
            print(f"[Special Days] Fetch error: {e}")
            return []
    
    def _cache_holiday(self, holiday: Dict):
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO special_days_cache (date, name, description, region, holiday_type)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT (date, name, region) DO UPDATE SET 
                description = EXCLUDED.description, holiday_type = EXCLUDED.holiday_type, fetched_at = CURRENT_TIMESTAMP
            """, (holiday['date'], holiday['name'], holiday['description'], self.region, holiday['type']))
            conn.commit()
        except Exception as e:
            print(f"[Special Days] Cache write error: {e}")
            conn.rollback()
        finally:
            cur.close()
            conn.close()

    def get_special_days_in_range(self, start_date: str, end_date: str) -> List[Dict]:
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT date, name, description, holiday_type FROM special_days_cache
                WHERE region = %s AND date BETWEEN %s AND %s AND fetched_at > NOW() - INTERVAL '30 days'
                ORDER BY date
            """, (self.region, start_date, end_date))
            cached = [{'date': str(r['date']), 'name': r['name'], 'description': r['description'], 'type': r['holiday_type']} for r in cur.fetchall()]
            if cached: return cached
            
            start_year = datetime.strptime(start_date, "%Y-%m-%d").year
            end_year = datetime.strptime(end_date, "%Y-%m-%d").year
            all_h = []
            for y in range(start_year, end_year + 1):
                all_h.extend(self._fetch_holidays_for_year(y))
            return [h for h in all_h if start_date <= h['date'] <= end_date]
        finally:
            cur.close()
            conn.close()

    def get_holiday_by_name(self, name: str) -> List[Dict]:
        """Search for holidays by name using fuzzy matching and LLM-assisted semantic resolution."""
        name_lower = name.lower()
        results = []
        all_h = self._fetch_holidays_for_year(datetime.now().year)
        for h in all_h:
            if name_lower in h['name'].lower() or h['name'].lower() in name_lower:
                results.append(h)
        if results: return results
        
        from core.chatbrain import call_openai, call_gemini, call_groq
        system_prompt = f"Identify the official holiday name for '{name}' in {self.region}. Return ONLY the official name or 'None'."
        messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": name}]
        resolved = call_openai(messages) or call_gemini(messages) or call_groq(messages)
        
        if resolved and resolved != "None":
            r_lower = resolved.lower()
            for h in all_h:
                if r_lower in h['name'].lower() or h['name'].lower() in r_lower:
                    results.append(h)
        return results

# GLOBAL INSTANCE CACHE
_services = {}
def get_special_days_service(region="IN"):
    from core.config import CONFIG
    api_key = os.getenv("CALENDARIFIC_API_KEY") or CONFIG.get("CALENDARIFIC_API_KEY")
    if region not in _services:
        _services[region] = SpecialDaysService(api_key, region)
    return _services[region]
