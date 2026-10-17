import requests
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any, Set
import psycopg2
import psycopg2.extras
from core.config import CONFIG

def get_connection():
    """Get database connection."""
    from legacy.memory_manager import get_connection as get_db_connection
    return get_db_connection()

class SpecialDaysService:
    """Service for fetching and caching special days/holidays."""
    
    _cache_table_ensured = False

    def __init__(self, api_key: str, region: str = "IN"):
        self.api_key = api_key
        self.region = region
        self.base_url = "https://calendarific.com/api/v2"
        if not SpecialDaysService._cache_table_ensured:
            self._ensure_cache_table()
            SpecialDaysService._cache_table_ensured = True
    
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
    
    def _get_verified_holidays(self, year: int, region: Optional[str] = None) -> List[Dict]:
        """Built-in verified catalog of official public holidays for supported regions."""
        reg = (region or self.region or "IN").upper()
        holidays = []

        if reg in ("RU", "RUSSIA"):
            # Russia Labour Code Article 112: 14 official non-working public holidays
            ru_holidays = [
                (f"{year}-01-01", "New Year's Day", "Public Holiday"),
                (f"{year}-01-02", "New Year Holiday", "Public Holiday"),
                (f"{year}-01-03", "New Year Holiday", "Public Holiday"),
                (f"{year}-01-04", "New Year Holiday", "Public Holiday"),
                (f"{year}-01-05", "New Year Holiday", "Public Holiday"),
                (f"{year}-01-06", "New Year Holiday", "Public Holiday"),
                (f"{year}-01-07", "Orthodox Christmas Day", "Public Holiday"),
                (f"{year}-01-08", "New Year Holiday", "Public Holiday"),
                (f"{year}-02-23", "Defender of the Fatherland Day", "Public Holiday"),
                (f"{year}-03-08", "International Women's Day", "Public Holiday"),
                (f"{year}-05-01", "Spring and Labor Day", "Public Holiday"),
                (f"{year}-05-09", "Victory Day", "Public Holiday"),
                (f"{year}-06-12", "Russia Day", "Public Holiday"),
                (f"{year}-11-04", "Unity Day", "Public Holiday"),
            ]
            for d_str, name, h_type in ru_holidays:
                holidays.append({
                    "date": d_str,
                    "name": name,
                    "description": f"Official public holiday in Russia ({name})",
                    "type": h_type
                })

        elif reg in ("US", "USA", "UNITED STATES"):
            # US 11 Federal Public Holidays
            from datetime import date
            # Helper for nth weekday (weekday: 0=Mon, 1=Tue, ..., 3=Thu)
            def nth_weekday(month: int, weekday: int, n: int) -> date:
                d = date(year, month, 1)
                while d.weekday() != weekday:
                    d += timedelta(days=1)
                return d + timedelta(weeks=n - 1)

            def last_weekday(month: int, weekday: int) -> date:
                # Start at end of month
                if month == 12:
                    d = date(year, 12, 31)
                else:
                    d = date(year, month + 1, 1) - timedelta(days=1)
                while d.weekday() != weekday:
                    d -= timedelta(days=1)
                return d

            mlk = nth_weekday(1, 0, 3)        # 3rd Mon Jan
            pres = nth_weekday(2, 0, 3)       # 3rd Mon Feb
            mem = last_weekday(5, 0)          # Last Mon May
            labor = nth_weekday(9, 0, 1)      # 1st Mon Sep
            columbus = nth_weekday(10, 0, 2)  # 2nd Mon Oct
            thx = nth_weekday(11, 3, 4)       # 4th Thu Nov

            us_holidays = [
                (f"{year}-01-01", "New Year's Day", "Federal Holiday"),
                (mlk.strftime("%Y-%m-%d"), "Martin Luther King Jr. Day", "Federal Holiday"),
                (pres.strftime("%Y-%m-%d"), "Washington's Birthday (Presidents' Day)", "Federal Holiday"),
                (mem.strftime("%Y-%m-%d"), "Memorial Day", "Federal Holiday"),
                (f"{year}-06-19", "Juneteenth National Independence Day", "Federal Holiday"),
                (f"{year}-07-04", "Independence Day", "Federal Holiday"),
                (labor.strftime("%Y-%m-%d"), "Labor Day", "Federal Holiday"),
                (columbus.strftime("%Y-%m-%d"), "Columbus Day", "Federal Holiday"),
                (f"{year}-11-11", "Veterans Day", "Federal Holiday"),
                (thx.strftime("%Y-%m-%d"), "Thanksgiving Day", "Federal Holiday"),
                (f"{year}-12-25", "Christmas Day", "Federal Holiday"),
            ]
            for d_str, name, h_type in us_holidays:
                holidays.append({
                    "date": d_str,
                    "name": name,
                    "description": f"United States Federal Holiday: {name}",
                    "type": h_type
                })

        else:
            # India (IN) Gazetted National Holidays & Major Religious/Cultural Festivals
            lunar_calendar = {
                2025: {
                    "Maha Shivratri": "2025-02-26", "Holi": "2025-03-14", "Eid ul-Fitr": "2025-03-31",
                    "Good Friday": "2025-04-18", "Bakrid": "2025-06-07", "Dussehra": "2025-10-02",
                    "Diwali": "2025-10-20", "Guru Nanak Jayanti": "2025-11-05"
                },
                2026: {
                    "Maha Shivratri": "2026-02-15", "Holi": "2026-03-04", "Eid ul-Fitr": "2026-03-20",
                    "Good Friday": "2026-04-03", "Bakrid": "2026-05-27", "Dussehra": "2026-10-20",
                    "Diwali": "2026-11-08", "Guru Nanak Jayanti": "2026-11-24"
                },
                2027: {
                    "Maha Shivratri": "2027-03-06", "Holi": "2027-03-22", "Eid ul-Fitr": "2027-03-10",
                    "Good Friday": "2027-03-26", "Bakrid": "2027-05-16", "Dussehra": "2027-10-10",
                    "Diwali": "2027-10-29", "Guru Nanak Jayanti": "2027-11-14"
                }
            }
            fixed_in = [
                (f"{year}-01-26", "Republic Day", "Gazetted National Holiday"),
                (f"{year}-08-15", "Independence Day", "Gazetted National Holiday"),
                (f"{year}-10-02", "Mahatma Gandhi Jayanti", "Gazetted National Holiday"),
                (f"{year}-12-25", "Christmas Day", "Public Holiday"),
            ]
            for d_str, name, h_type in fixed_in:
                holidays.append({
                    "date": d_str,
                    "name": name,
                    "description": f"National public holiday in India: {name}",
                    "type": h_type
                })
            # Add lunar festivals if year is in table
            if year in lunar_calendar:
                for fest_name, d_str in lunar_calendar[year].items():
                    holidays.append({
                        "date": d_str,
                        "name": fest_name,
                        "description": f"Major cultural and religious festival in India: {fest_name}",
                        "type": "Festival / Observance"
                    })

        holidays.sort(key=lambda x: x["date"])
        return holidays

    def _fetch_holidays_for_year(self, year: int, region: Optional[str] = None) -> List[Dict]:
        target_reg = (region or self.region or "IN").upper()
        
        # Ground truth verified catalogs for official statutory public holidays
        if target_reg in ("RU", "US", "IN"):
            verified = self._get_verified_holidays(year, region=target_reg)
            if verified:
                for h in verified:
                    try:
                        self._cache_holiday(h, region=target_reg)
                    except Exception:
                        pass
                return verified

        if self.api_key:
            try:
                url = f"{self.base_url}/holidays"
                params = {'api_key': self.api_key, 'country': target_reg, 'year': year}
                response = requests.get(url, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, dict):
                        resp_data = data.get('response', {})
                        holiday_list = resp_data.get('holidays', [])
                        if isinstance(holiday_list, list) and holiday_list:
                            holidays = []
                            for h in holiday_list:
                                types = h.get('type', [])
                                if isinstance(types, str): types = [types]
                                # Filter only National / Public holidays, excluding observances
                                if any("national" in t.lower() or "public" in t.lower() or "federal" in t.lower() for t in types):
                                    iso = h.get('date', {}).get('iso')
                                    if iso:
                                        h_data = {
                                            'date': iso[:10],
                                            'name': h.get('name'),
                                            'description': h.get('description', ''),
                                            'type': ', '.join(types)
                                        }
                                        holidays.append(h_data)
                                        self._cache_holiday(h_data, region=target_reg)
                            if holidays:
                                return holidays
            except Exception as e:
                print(f"[Special Days] Fetch error from API: {e}")

        # Fallback to verified catalog
        verified = self._get_verified_holidays(year, region=target_reg)
        for h in verified:
            try:
                self._cache_holiday(h, region=target_reg)
            except Exception:
                pass
        return verified

    def _cache_holiday(self, holiday: Dict, region: Optional[str] = None):
        target_reg = (region or self.region or "IN").upper()
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO special_days_cache (date, name, description, region, holiday_type)
                VALUES (%s, %s, %s, %s, %s) ON CONFLICT (date, name, region) DO UPDATE SET 
                description = EXCLUDED.description, holiday_type = EXCLUDED.holiday_type, fetched_at = CURRENT_TIMESTAMP
            """, (holiday['date'], holiday['name'], holiday['description'], target_reg, holiday.get('type', 'Public Holiday')))
            conn.commit()
        except Exception as e:
            conn.rollback()
        finally:
            cur.close()
            conn.close()

    def get_special_days_in_range(self, start_date: str, end_date: str, region: Optional[str] = None) -> List[Dict]:
        target_reg = (region or self.region or "IN").upper()
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT date, name, description, holiday_type FROM special_days_cache
                WHERE region = %s AND date BETWEEN %s AND %s AND fetched_at > NOW() - INTERVAL '30 days'
                ORDER BY date
            """, (target_reg, start_date, end_date))
            cached = [{'date': str(r['date']), 'name': r['name'], 'description': r['description'], 'type': r['holiday_type']} for r in cur.fetchall()]
            if cached:
                return cached
            
            start_year = datetime.strptime(start_date, "%Y-%m-%d").year
            end_year = datetime.strptime(end_date, "%Y-%m-%d").year
            all_h = []
            for y in range(start_year, end_year + 1):
                all_h.extend(self._fetch_holidays_for_year(y, region=target_reg))
            return [h for h in all_h if start_date <= h['date'] <= end_date]
        finally:
            cur.close()
            conn.close()

    def get_next_holiday(self, from_date: Optional[str] = None, region: Optional[str] = None, country: Optional[str] = None) -> Optional[Dict]:
        """Get the earliest upcoming public holiday from a date."""
        target_reg = region or country or self.region or "IN"
        if not from_date:
            from_date = datetime.now().strftime("%Y-%m-%d")
        y = datetime.strptime(from_date, "%Y-%m-%d").year
        all_h = self._fetch_holidays_for_year(y, region=target_reg)
        upcoming = [h for h in all_h if h['date'] >= from_date]
        if not upcoming:
            # Check next year
            all_h_next = self._fetch_holidays_for_year(y + 1, region=target_reg)
            upcoming = [h for h in all_h_next if h['date'] >= from_date]
        if upcoming:
            upcoming.sort(key=lambda x: x['date'])
            return upcoming[0]
        return None

    def get_holidays_count(self, year: int, region: Optional[str] = None, country: Optional[str] = None) -> Tuple[int, List[Dict]]:
        """Get total verified official public holidays for a specific country and year."""
        target_reg = region or country or self.region or "IN"
        all_h = self._fetch_holidays_for_year(year, region=target_reg)
        return len(all_h), all_h

    def get_holiday_by_name(self, name: str, year: Optional[int] = None, region: Optional[str] = None, country: Optional[str] = None) -> List[Dict]:
        """Search for holidays by name using fuzzy matching and catalog lookup."""
        name_lower = name.lower().strip()
        results = []
        target_year = year or datetime.now().year
        target_reg = region or country or self.region or "IN"
        all_h = self._fetch_holidays_for_year(target_year, region=target_reg)
        for h in all_h:
            h_low = h['name'].lower()
            if name_lower in h_low or h_low in name_lower:
                results.append(h)
        if results:
            return results
        
        # Check adjacent year if not found
        for adj in (target_year + 1, target_year - 1):
            adj_h = self._fetch_holidays_for_year(adj, region=region)
            for h in adj_h:
                h_low = h['name'].lower()
                if name_lower in h_low or h_low in name_lower:
                    results.append(h)
            if results:
                return results

        return results

# GLOBAL INSTANCE CACHE
_services = {}
def get_special_days_service(region="IN", user_id=None):
    from core.config import CONFIG
    import sys
    api_key = ""
    if user_id:
        try:
            from core.credential_manager import get_credential_manager
            api_key = get_credential_manager().get_credential(user_id, "calendarific")
        except Exception:
            pass
    if not api_key:
        try:
            from instance.config import settings
            cur_uid = getattr(settings, 'CURRENT_USER_ID', None) or settings.get_last_user()
            if cur_uid:
                from core.credential_manager import get_credential_manager
                api_key = get_credential_manager().get_credential(cur_uid, "calendarific")
        except Exception:
            pass
    if not api_key:
        if os.getenv("APP_ENV", "").lower() != "production" and not getattr(sys, "frozen", False):
            api_key = os.getenv("CALENDARIFIC_API_KEY") or CONFIG.get("CALENDARIFIC_API_KEY")

    cache_key = f"{region}_{user_id or 'default'}"
    if cache_key not in _services:
        _services[cache_key] = SpecialDaysService(api_key, region)
    return _services[cache_key]
