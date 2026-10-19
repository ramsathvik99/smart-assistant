"""
Calendar Storage Layer - PostgreSQL Implementation
Handles persistent storage of events, recurrence expansion, conflict detection,
free/busy slot discovery, meeting notes, reminders integration, and calendar settings.
"""

import re
import json
import logging
import psycopg2
import psycopg2.extras
from datetime import datetime, date, time, timedelta
from typing import Dict, List, Optional, Any, Tuple
import uuid
import calendar

logger = logging.getLogger(__name__)

def get_connection():
    """Get database connection."""
    from legacy.memory_manager import get_connection as get_db_connection
    return get_db_connection()


class CalendarStorage:
    """PostgreSQL-based dynamic calendar storage and intelligence foundation."""
    
    _schema_ensured = False

    def __init__(self, storage_path=None):
        """Initialize storage."""
        if not CalendarStorage._schema_ensured:
            self._ensure_schema()
            CalendarStorage._schema_ensured = True

    def _ensure_schema(self):
        """Ensure all required columns and constraints exist in PostgreSQL."""
        try:
            conn = get_connection()
            cur = conn.cursor()
            try:
                # Fast column check to avoid running DDL locks if columns already exist
                cur.execute("SELECT 1 FROM information_schema.columns WHERE table_name = 'calendar_events' AND column_name = 'location';")
                if cur.fetchone():
                    return

                cur.execute("""
                    ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS location TEXT;
                    ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS category TEXT DEFAULT 'General';
                    ALTER TABLE calendar_events ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;
                    ALTER TABLE recurrence_rules ADD COLUMN IF NOT EXISTS exceptions JSONB DEFAULT '[]'::jsonb;
                    ALTER TABLE recurrence_rules ADD COLUMN IF NOT EXISTS count INTEGER;
                    ALTER TABLE calendar_settings ADD COLUMN IF NOT EXISTS working_hours_start TEXT DEFAULT '09:00';
                    ALTER TABLE calendar_settings ADD COLUMN IF NOT EXISTS working_hours_end TEXT DEFAULT '18:00';
                    ALTER TABLE calendar_settings ADD COLUMN IF NOT EXISTS default_reminder_minutes INTEGER DEFAULT 15;
                """)
                conn.commit()
            except Exception as e:
                conn.rollback()
                logger.warning(f"[Calendar Storage] Schema verification note: {e}")
            finally:
                cur.close()
                conn.close()
        except Exception as e:
            logger.warning(f"[Calendar Storage] Could not connect to ensure schema: {e}")

    @staticmethod
    def _parse_time(raw_time: Optional[str]) -> Optional[time]:
        """Parse 12-hour or 24-hour time string into a datetime.time object."""
        if not raw_time:
            return None
        cleaned = str(raw_time).strip().upper()
        cleaned = re.sub(r'P\.?M\.?', 'PM', cleaned)
        cleaned = re.sub(r'A\.?M\.?', 'AM', cleaned)
        cleaned = re.sub(r'\s+', ' ', cleaned).strip()
        formats = [
            "%H:%M", "%H:%M:%S",
            "%I:%M %p", "%I %p",
            "%I:%M%p", "%I%p"
        ]
        for fmt in formats:
            try:
                return datetime.strptime(cleaned, fmt).time()
            except ValueError:
                continue
        # Also handle bare integer hour e.g. "3" or "15"
        try:
            val = int(cleaned)
            if 0 <= val <= 23:
                if 1 <= val <= 6:
                    val += 12
                return time(val, 0)
        except ValueError:
            pass
        return None

    def add_event(self, user_id: int, event: Dict) -> str:
        """
        Add an event to the calendar with duration, location, category,
        metadata, duplicate protection, and optional recurrence rules.
        """
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            # 1. Parse date and time
            event_date_str = event.get('date') or datetime.now().strftime("%Y-%m-%d")
            date_obj = datetime.strptime(event_date_str, "%Y-%m-%d").date()
            raw_time = event.get('time')
            t_obj = self._parse_time(raw_time)

            is_all_day_spec = event.get('is_all_day')
            if is_all_day_spec is not None:
                is_all_day = bool(is_all_day_spec)
            else:
                is_all_day = (t_obj is None)
            
            if t_obj is not None and not is_all_day:
                start_dt = datetime.combine(date_obj, t_obj)
            else:
                start_dt = datetime.combine(date_obj, time(0, 0))
                if t_obj is None:
                    is_all_day = True

            # 2. Compute end datetime
            duration_minutes = event.get('duration_minutes')
            raw_end_time = event.get('end_time')
            raw_end_date = event.get('end_date')

            if raw_end_date and raw_end_time:
                end_d = datetime.strptime(raw_end_date, "%Y-%m-%d").date()
                end_t = self._parse_time(raw_end_time) or time(23, 59)
                end_dt = datetime.combine(end_d, end_t)
            elif raw_end_time:
                end_t = self._parse_time(raw_end_time) or time(23, 59)
                end_dt = datetime.combine(date_obj, end_t)
            elif is_all_day:
                end_dt = datetime.combine(date_obj, time(23, 59, 59))
            elif duration_minutes:
                end_dt = start_dt + timedelta(minutes=int(duration_minutes))
            else:
                # Default duration: 60 minutes for timed events
                end_dt = start_dt + timedelta(minutes=60)

            # 3. Duplicate Protection Check
            # Prevent exact duplicate event insertions for same user, title, start_datetime
            title = event.get('title', 'Untitled Event').strip()
            cur.execute("""
                SELECT id FROM calendar_events
                WHERE user_id = %s
                  AND LOWER(title) = %s
                  AND start_datetime = %s
                LIMIT 1
            """, (user_id, title.lower(), start_dt))
            dup = cur.fetchone()
            if dup:
                return str(dup['id'])

            # 4. Insert into calendar_events
            event_id = str(uuid.uuid4())
            location = event.get('location')
            category = event.get('category', 'General')
            metadata = event.get('metadata', {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {"raw": metadata}

            cur.execute("""
                INSERT INTO calendar_events 
                (id, user_id, title, description, start_datetime, end_datetime,
                 is_all_day, event_type, location, category, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                event_id,
                user_id,
                title,
                event.get('description'),
                start_dt,
                end_dt,
                is_all_day,
                event.get('type', 'event'),
                location,
                category,
                json.dumps(metadata)
            ))
            
            # 5. Insert Recurrence Rule if specified
            if event.get('recurrence'):
                recurrence = event['recurrence']
                freq = str(recurrence.get('frequency', 'weekly')).lower()
                interval = int(recurrence.get('interval', 1))
                days_of_week = recurrence.get('days_of_week')
                if isinstance(days_of_week, list):
                    days_of_week = ",".join(days_of_week)
                end_date = recurrence.get('end_date')
                count = recurrence.get('count')
                exceptions = recurrence.get('exceptions', [])

                cur.execute("""
                    INSERT INTO recurrence_rules
                    (event_id, frequency, interval, days_of_week, end_date, count, exceptions)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                """, (
                    event_id,
                    freq,
                    interval,
                    days_of_week,
                    end_date,
                    count,
                    json.dumps(exceptions)
                ))

            conn.commit()

            # 6. Automatic reminder hook if requested
            if event.get('reminder') or event.get('reminder_minutes') is not None:
                rem_mins = event.get('reminder_minutes', 15)
                self.add_event_reminder(user_id, event_id, offset_minutes=int(rem_mins))

            return event_id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"[Calendar Storage] Error adding event: {e}")
            raise
        finally:
            cur.close()
            conn.close()

    def get_events(self, user_id: int, event_date: str, category: Optional[str] = None) -> List[Dict]:
        """
        Get all events for a specific date, including expanded recurring events.
        """
        range_result = self.get_events_range(user_id, event_date, event_date, category=category)
        return range_result.get(event_date, [])

    def get_events_range(self, user_id: int, start_date: str, end_date: str, category: Optional[str] = None) -> Dict[str, List[Dict]]:
        """
        Get all events in a date range, expanding recurring occurrences and filtering exceptions.
        """
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        events_by_date: Dict[str, List[Dict]] = {}
        
        start_d = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_d = datetime.strptime(end_date, "%Y-%m-%d").date()

        try:
            # 1. Fetch single (non-recurring) events in range
            query = """
                SELECT e.id, e.title, e.description, e.start_datetime, e.end_datetime,
                       e.is_all_day, e.event_type, e.location, e.category, e.metadata
                FROM calendar_events e
                LEFT JOIN recurrence_rules r ON e.id = r.event_id
                WHERE e.user_id = %s
                  AND r.id IS NULL
                  AND (
                      (DATE(e.start_datetime) BETWEEN %s AND %s)
                      OR (e.end_datetime IS NOT NULL AND DATE(e.end_datetime) >= %s AND DATE(e.start_datetime) <= %s)
                  )
            """
            params = [user_id, start_date, end_date, start_date, end_date]
            if category:
                query += " AND LOWER(e.category) = %s"
                params.append(category.lower())

            query += " ORDER BY e.start_datetime"
            cur.execute(query, params)
            
            for row in cur.fetchall():
                ev_date = row['start_datetime'].date().strftime("%Y-%m-%d")
                end_dt_val = row['end_datetime']
                dur_mins = int((end_dt_val - row['start_datetime']).total_seconds() / 60) if end_dt_val else 60
                
                ev = {
                    'id': str(row['id']),
                    'title': row['title'],
                    'description': row['description'],
                    'date': ev_date,
                    'time': row['start_datetime'].strftime("%H:%M") if not row['is_all_day'] else None,
                    'end_time': end_dt_val.strftime("%H:%M") if (end_dt_val and not row['is_all_day']) else None,
                    'duration_minutes': dur_mins,
                    'type': row['event_type'],
                    'is_all_day': row['is_all_day'],
                    'location': row['location'],
                    'category': row['category'] or 'General',
                    'metadata': row['metadata'] or {},
                    'attendees': (row['metadata'] or {}).get('attendees', []) if isinstance(row['metadata'], dict) else [],
                    'is_recurring': False,
                    'start_datetime': row['start_datetime'],
                    'end_datetime': end_dt_val
                }
                if ev_date not in events_by_date:
                    events_by_date[ev_date] = []
                events_by_date[ev_date].append(ev)

            # 2. Fetch recurring master events and expand occurrences
            r_query = """
                SELECT e.id, e.title, e.description, e.start_datetime, e.end_datetime,
                       e.is_all_day, e.event_type, e.location, e.category, e.metadata,
                       r.frequency, r.interval, r.days_of_week, r.end_date, r.count, r.exceptions
                FROM calendar_events e
                JOIN recurrence_rules r ON e.id = r.event_id
                WHERE e.user_id = %s
                  AND DATE(e.start_datetime) <= %s
                  AND (r.end_date IS NULL OR r.end_date >= %s)
            """
            r_params = [user_id, end_date, start_date]
            if category:
                r_query += " AND LOWER(e.category) = %s"
                r_params.append(category.lower())

            cur.execute(r_query, r_params)
            recurring_masters = cur.fetchall()

            for master in recurring_masters:
                self._expand_recurrence_into_range(master, start_d, end_d, events_by_date)

            # Sort events on each date chronologically
            for d in events_by_date:
                events_by_date[d].sort(key=lambda x: x['start_datetime'])

            return events_by_date

        finally:
            cur.close()
            conn.close()

    def _expand_recurrence_into_range(self, master: Dict, range_start: date, range_end: date, events_by_date: Dict[str, List[Dict]]):
        """Expand a recurring rule into occurrence instances within a date range."""
        master_id = str(master['id'])
        master_start = master['start_datetime']
        master_end = master['end_datetime']
        duration = (master_end - master_start) if master_end else timedelta(minutes=60)
        
        freq = str(master['frequency']).lower()
        interval = max(1, master['interval'] or 1)
        r_end_date = master['end_date']
        r_count = master['count']
        
        exceptions = master['exceptions'] or []
        if isinstance(exceptions, str):
            try:
                exceptions = json.loads(exceptions)
            except Exception:
                exceptions = []
        exception_dates = set(exceptions)

        days_of_week = set()
        if master['days_of_week']:
            raw_days = str(master['days_of_week']).upper()
            day_map = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6,
                       "MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6,
                       "MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3, "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6}
            for part in raw_days.split(","):
                part = part.strip()
                if part in day_map:
                    days_of_week.add(day_map[part])

        # Step through occurrences
        curr_d = master_start.date()
        generated_count = 0
        max_loop = 1000  # Safety bound

        while curr_d <= range_end and max_loop > 0:
            max_loop -= 1
            if r_end_date and curr_d > r_end_date:
                break
            if r_count and generated_count >= r_count:
                break

            # Check if curr_d matches pattern
            matches_pattern = False
            if freq == 'daily':
                matches_pattern = True
            elif freq == 'weekly':
                weeks_diff = (curr_d - master_start.date()).days // 7
                if (weeks_diff % interval) == 0:
                    if not days_of_week or curr_d.weekday() in days_of_week:
                        matches_pattern = True
            elif freq == 'monthly':
                max_d = calendar.monthrange(curr_d.year, curr_d.month)[1]
                expected_day = min(master_start.day, max_d)
                matches_pattern = (curr_d.day == expected_day)
            elif freq == 'yearly':
                max_d = calendar.monthrange(curr_d.year, master_start.month)[1]
                expected_day = min(master_start.day, max_d)
                matches_pattern = (curr_d.month == master_start.month and curr_d.day == expected_day)

            iso_date = curr_d.strftime("%Y-%m-%d")
            
            if matches_pattern:
                generated_count += 1
                if range_start <= curr_d <= range_end and iso_date not in exception_dates:
                    occ_start = datetime.combine(curr_d, master_start.time())
                    occ_end = occ_start + duration
                    dur_mins = int(duration.total_seconds() / 60)
                    
                    occ = {
                        'id': f"{master_id}_{iso_date}",
                        'master_id': master_id,
                        'title': master['title'],
                        'description': master['description'],
                        'date': iso_date,
                        'time': occ_start.strftime("%H:%M") if not master['is_all_day'] else None,
                        'end_time': occ_end.strftime("%H:%M") if not master['is_all_day'] else None,
                        'duration_minutes': dur_mins,
                        'type': master['event_type'],
                        'is_all_day': master['is_all_day'],
                        'location': master['location'],
                        'category': master['category'] or 'General',
                        'metadata': master['metadata'] or {},
                        'is_recurring': True,
                        'start_datetime': occ_start,
                        'end_datetime': occ_end
                    }
                    if iso_date not in events_by_date:
                        events_by_date[iso_date] = []
                    events_by_date[iso_date].append(occ)

            # Advance curr_d according to frequency
            if freq == 'daily':
                curr_d += timedelta(days=interval)
            elif freq == 'weekly':
                if days_of_week:
                    curr_d += timedelta(days=1)
                else:
                    curr_d += timedelta(days=7 * interval)
            elif freq == 'monthly':
                # Advance by month
                month = curr_d.month - 1 + interval
                year = curr_d.year + month // 12
                month = month % 12 + 1
                max_d = calendar.monthrange(year, month)[1]
                day = min(master_start.day, max_d)
                curr_d = date(year, month, day)
            elif freq == 'yearly':
                target_year = curr_d.year + interval
                max_d = calendar.monthrange(target_year, master_start.month)[1]
                curr_d = date(target_year, master_start.month, min(master_start.day, max_d))
            else:
                curr_d += timedelta(days=1)

    def update_event(self, user_id: int, event_id: str, updates: Dict) -> bool:
        """
        Update an event. Supports editing specific occurrences of a recurring series
        or series-wide updates.
        """
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        # Handle occurrence-specific edit
        occurrence_date = updates.get('occurrence_date')
        if occurrence_date or "_" in event_id:
            real_master_id = event_id.split("_")[0]
            target_occ_date = occurrence_date or event_id.split("_")[1]
            return self._update_single_occurrence(user_id, real_master_id, target_occ_date, updates)

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            cur.execute("""
                SELECT id, title, description, start_datetime, end_datetime,
                       is_all_day, location, category, metadata
                FROM calendar_events
                WHERE id = %s AND user_id = %s
            """, (event_id, user_id))
            existing_row = cur.fetchone()
            if not existing_row:
                return False

            set_clauses = []
            values = []
            
            # Title
            new_title = updates.get('title') or updates.get('new_title')
            if new_title:
                set_clauses.append("title = %s")
                values.append(new_title.strip())

            # Description
            if 'description' in updates:
                set_clauses.append("description = %s")
                values.append(updates['description'])

            # Location
            if 'location' in updates:
                set_clauses.append("location = %s")
                values.append(updates['location'])

            # Category
            if 'category' in updates:
                set_clauses.append("category = %s")
                values.append(updates['category'])

            # Metadata (e.g. notes, agendas)
            if 'metadata' in updates:
                meta = updates['metadata']
                if not isinstance(meta, dict):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {"notes": str(meta)}
                set_clauses.append("metadata = %s")
                values.append(json.dumps(meta))
            
            # Date / Time updates preserving previous values
            if 'date' in updates or 'time' in updates or 'duration_minutes' in updates:
                existing_dt = existing_row['start_datetime']
                existing_end = existing_row['end_datetime']
                existing_dur = (existing_end - existing_dt) if existing_end else timedelta(minutes=60)
                
                target_date = updates.get('date') or existing_dt.strftime("%Y-%m-%d")
                target_time = updates.get('time') if updates.get('time') is not None else (
                    existing_dt.strftime("%H:%M") if not existing_row['is_all_day'] else None
                )

                parsed_time = self._parse_time(target_time)
                date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()

                if parsed_time:
                    start_dt = datetime.combine(date_obj, parsed_time)
                    is_all_day = False
                else:
                    start_dt = datetime.combine(date_obj, time(0, 0))
                    is_all_day = True

                # Recalculate end_datetime preserving duration
                new_dur_mins = updates.get('duration_minutes')
                if new_dur_mins:
                    end_dt = start_dt + timedelta(minutes=int(new_dur_mins))
                elif is_all_day:
                    end_dt = datetime.combine(date_obj, time(23, 59, 59))
                else:
                    end_dt = start_dt + existing_dur

                set_clauses.append("start_datetime = %s")
                values.append(start_dt)
                set_clauses.append("end_datetime = %s")
                values.append(end_dt)
                set_clauses.append("is_all_day = %s")
                values.append(is_all_day)

            if not set_clauses:
                return False
            
            set_clauses.append("updated_at = CURRENT_TIMESTAMP")
            values.extend([event_id, user_id])
            
            query = f"""
                UPDATE calendar_events
                SET {', '.join(set_clauses)}
                WHERE id = %s AND user_id = %s
            """
            cur.execute(query, values)
            ev_updated = cur.rowcount > 0

            # Synchronize linked reminders
            try:
                old_t = existing_row['title']
                eff_t = (new_title or old_t).strip()
                if ('date' in updates or 'time' in updates) and 'start_dt' in locals():
                    new_due = start_dt - timedelta(minutes=15)
                    cur.execute("""
                        UPDATE reminders
                        SET due_at = %s,
                            task_text = %s,
                            is_notified = FALSE
                        WHERE user_id = %s
                          AND (task_text LIKE %s OR task_text LIKE %s)
                    """, (new_due, f"Upcoming meeting: {eff_t} at {start_dt.strftime('%H:%M')}", user_id, f"%{old_t}%", f"%{eff_t}%"))
                elif new_title and new_title.strip() != old_t:
                    cur.execute("""
                        UPDATE reminders
                        SET task_text = REPLACE(task_text, %s, %s)
                        WHERE user_id = %s AND task_text LIKE %s
                    """, (old_t, eff_t, user_id, f"%{old_t}%"))
            except Exception as rem_err:
                logger.debug(f"[Calendar Storage] Reminder sync note: {rem_err}")

            conn.commit()
            
            return ev_updated
            
        except Exception as e:
            conn.rollback()
            logger.error(f"[Calendar Storage] Error updating event: {e}")
            return False
        finally:
            cur.close()
            conn.close()

    def _update_single_occurrence(self, user_id: int, master_id: str, occurrence_date: str, updates: Dict) -> bool:
        """Detaches a single occurrence from a recurring series and creates an override event."""
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            # 1. Fetch master and recurrence rule
            cur.execute("""
                SELECT e.*, r.exceptions FROM calendar_events e
                JOIN recurrence_rules r ON e.id = r.event_id
                WHERE e.id = %s AND e.user_id = %s
            """, (master_id, user_id))
            master = cur.fetchone()
            if not master:
                return False

            # 2. Add occurrence_date to exceptions
            raw_ex = master['exceptions'] or []
            if isinstance(raw_ex, str):
                try:
                    raw_ex = json.loads(raw_ex)
                except Exception:
                    raw_ex = []
            if occurrence_date not in raw_ex:
                raw_ex.append(occurrence_date)
            
            cur.execute("""
                UPDATE recurrence_rules
                SET exceptions = %s
                WHERE event_id = %s
            """, (json.dumps(raw_ex), master_id))

            # 3. Create detached single event with updates applied
            new_title = updates.get('title') or updates.get('new_title') or master['title']
            new_date = updates.get('date') or occurrence_date
            new_time = updates.get('time') or (master['start_datetime'].strftime("%H:%M") if not master['is_all_day'] else None)
            new_desc = updates.get('description') or master['description']
            new_loc = updates.get('location') or master['location']
            new_cat = updates.get('category') or master['category']

            detached_event = {
                "title": new_title,
                "date": new_date,
                "time": new_time,
                "description": new_desc,
                "location": new_loc,
                "category": new_cat,
                "metadata": {"detached_from": master_id, "original_date": occurrence_date}
            }
            conn.commit()
            self.add_event(user_id, detached_event)
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"[Calendar Storage] Error updating single occurrence: {e}")
            return False
        finally:
            cur.close()
            conn.close()

    def delete_event(self, user_id: int, event_id: str, occurrence_date: Optional[str] = None, delete_series: bool = False, **kwargs) -> bool:
        """
        Delete an event, series, or single occurrence of a recurring series.
        """
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        # If deleting a specific occurrence of a recurring series and not forced series delete
        if not delete_series and (occurrence_date or "_" in str(event_id)):
            real_master_id = str(event_id).split("_")[0]
            target_occ_date = occurrence_date or str(event_id).split("_")[1]
            return self.delete_occurrence(user_id, real_master_id, target_occ_date)

        # Series or normal event deletion: delete master event
        real_master_id = str(event_id).split("_")[0]

        conn = get_connection()
        cur = conn.cursor()
        try:
            # Clean up linked reminders before deleting event
            try:
                cur.execute("""
                    SELECT title FROM calendar_events WHERE id = %s AND user_id = %s
                """, (real_master_id, user_id))
                del_row = cur.fetchone()
                if del_row and del_row[0]:
                    cur.execute("""
                        DELETE FROM reminders
                        WHERE user_id = %s AND task_text LIKE %s
                    """, (user_id, f"%{del_row[0]}%"))
            except Exception as rem_del_err:
                logger.debug(f"[Calendar Storage] Reminder cleanup note: {rem_del_err}")

            cur.execute("""
                DELETE FROM calendar_events
                WHERE id = %s AND user_id = %s
            """, (real_master_id, user_id))
            conn.commit()
            return cur.rowcount > 0
        finally:
            cur.close()
            conn.close()

    def delete_occurrence(self, user_id: int, master_id: str, occurrence_date: str) -> bool:
        """Delete a single occurrence of a recurring event by adding it to exceptions."""
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT exceptions FROM recurrence_rules
                WHERE event_id = %s
            """, (master_id,))
            row = cur.fetchone()
            if not row:
                return False
            
            raw_ex = row['exceptions'] or []
            if isinstance(raw_ex, str):
                try:
                    raw_ex = json.loads(raw_ex)
                except Exception:
                    raw_ex = []
            if occurrence_date not in raw_ex:
                raw_ex.append(occurrence_date)

            cur.execute("""
                UPDATE recurrence_rules
                SET exceptions = %s
                WHERE event_id = %s
            """, (json.dumps(raw_ex), master_id))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"[Calendar Storage] Error deleting occurrence: {e}")
            return False
        finally:
            cur.close()
            conn.close()

    def delete_events_by_title(self, user_id: int, event_date: str, title_keyword: str) -> int:
        """Delete events matching a title keyword on a specific date."""
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                DELETE FROM calendar_events
                WHERE user_id = %s
                  AND DATE(start_datetime) = %s
                  AND LOWER(title) LIKE %s
            """, (user_id, event_date, f"%{title_keyword.lower()}%"))
            conn.commit()
            return cur.rowcount
        finally:
            cur.close()
            conn.close()

    def get_next_event(self, user_id: int, from_datetime: Optional[datetime] = None, category: Optional[str] = None) -> Optional[Dict]:
        """
        Get the nearest upcoming event based on actual date and time,
        evaluating both single events and expanded recurring occurrences.
        """
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0
            
        if from_datetime is None:
            from_datetime = datetime.now()

        # Query events from today through next 30 days
        start_d = from_datetime.strftime("%Y-%m-%d")
        end_d = (from_datetime + timedelta(days=60)).strftime("%Y-%m-%d")
        
        events_map = self.get_events_range(user_id, start_d, end_d, category=category)
        all_future = []
        for d, ev_list in events_map.items():
            for ev in ev_list:
                if ev['start_datetime'] >= from_datetime:
                    all_future.append(ev)

        if not all_future:
            return None

        all_future.sort(key=lambda x: x['start_datetime'])
        best = all_future[0]
        return {
            'id': best['id'],
            'title': best['title'],
            'description': best['description'],
            'date': best['date'],
            'time': best['start_datetime'].strftime("%I:%M %p").lstrip("0") if not best['is_all_day'] else None,
            'duration_minutes': best.get('duration_minutes', 60),
            'location': best.get('location'),
            'category': best.get('category'),
            'type': best['type'],
            'start_datetime': best['start_datetime'],
            'end_datetime': best['end_datetime']
        }

    def get_event_by_id(self, user_id: int, event_id: str) -> Optional[Dict]:
        """Get an event by its unique ID for the authenticated user."""
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        real_id = str(event_id).split("_")[0]
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT id, user_id, title, description, start_datetime, end_datetime,
                       is_all_day, event_type, location, category, metadata
                FROM calendar_events
                WHERE id = %s AND user_id = %s
                LIMIT 1
            """, (real_id, user_id))
            row = cur.fetchone()
            if not row:
                return None
            s_dt = row['start_datetime']
            e_dt = row['end_datetime']
            dur = int((e_dt - s_dt).total_seconds() // 60) if (e_dt and s_dt) else 60
            return {
                'id': row['id'],
                'user_id': row['user_id'],
                'title': row['title'],
                'description': row['description'],
                'date': s_dt.strftime("%Y-%m-%d"),
                'time': s_dt.strftime("%H:%M:%S") if not row['is_all_day'] else None,
                'start_datetime': s_dt,
                'end_datetime': e_dt,
                'duration_minutes': dur,
                'is_all_day': row['is_all_day'],
                'location': row['location'],
                'category': row['category'],
                'metadata': row['metadata']
            }
        finally:
            cur.close()
            conn.close()

    def find_events_by_title(self, user_id: int, title_keyword: str, event_date: Optional[str] = None) -> List[Dict]:
        """Find events matching a title keyword, optionally filtered by date."""
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0
            
        if not title_keyword or not str(title_keyword).strip():
            return []

        raw_kw = str(title_keyword).strip().lower()
        clean_kw = re.sub(r'^(?:the\s+|my\s+|our\s+)?(?:calendar\s+)?', '', raw_kw).strip()
        if not clean_kw:
            clean_kw = raw_kw

        def _is_match(ev_title: str) -> bool:
            if not ev_title:
                return False
            ev_low = ev_title.lower().strip()
            ev_clean = re.sub(r'^(?:the\s+|my\s+|our\s+)?(?:calendar\s+)?', '', ev_low).strip()
            # 1. Exact match
            if raw_kw == ev_low or clean_kw == ev_low or clean_kw == ev_clean:
                return True
            # 2. Bidirectional substring match
            if clean_kw in ev_low or ev_low in clean_kw:
                return True
            if clean_kw in ev_clean or ev_clean in clean_kw:
                return True
            # 3. Word token intersection
            kw_words = set(clean_kw.split())
            ev_words = set(ev_clean.split())
            if kw_words and kw_words.issubset(ev_words):
                return True
            return False

        if event_date:
            events = self.get_events(user_id, event_date)
            return [e for e in events if _is_match(e.get('title', ''))]

        # Search across upcoming events
        now = datetime.now()
        start_d = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        end_d = (now + timedelta(days=90)).strftime("%Y-%m-%d")
        events_map = self.get_events_range(user_id, start_d, end_d)
        matches = []
        for d, ev_list in events_map.items():
            for ev in ev_list:
                if _is_match(ev.get('title', '')):
                    matches.append(ev)
        return matches

    def search_events(self, user_id: int, query: str, start_date: Optional[str] = None, end_date: Optional[str] = None, category: Optional[str] = None) -> List[Dict]:
        """Full search across title, description, location, and category."""
        if not start_date or not end_date:
            now = datetime.now()
            start_date = (now - timedelta(days=60)).strftime("%Y-%m-%d")
            end_date = (now + timedelta(days=120)).strftime("%Y-%m-%d")

        events_map = self.get_events_range(user_id, start_date, end_date, category=category)
        q_low = query.lower().strip()
        results = []
        for d, ev_list in events_map.items():
            for ev in ev_list:
                content = f"{ev.get('title', '')} {ev.get('description', '')} {ev.get('location', '')} {ev.get('category', '')}".lower()
                if q_low in content:
                    results.append(ev)
        return sorted(results, key=lambda x: x['start_datetime'])

    # ─────────────────────────────────────────────────────────────────────────
    # Conflicts, Buffers, Working Hours & Free Slots
    # ─────────────────────────────────────────────────────────────────────────

    def check_conflicts(self, user_id: int, start_dt: datetime, end_dt: datetime,
                        exclude_event_id: Optional[str] = None,
                        buffer_minutes: int = 0) -> List[Dict[str, Any]]:
        """
        Check for event conflicts overlapping [start_dt - buffer, end_dt + buffer].
        Reliable interval-overlap detection: new_start < existing_end AND new_end > existing_start.
        """
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        buffered_start = start_dt - timedelta(minutes=buffer_minutes)
        buffered_end = end_dt + timedelta(minutes=buffer_minutes)
        
        # Query range from day before to day after to cover multi-day / midnight boundaries
        start_d = (buffered_start.date() - timedelta(days=1)).strftime("%Y-%m-%d")
        end_d = (buffered_end.date() + timedelta(days=1)).strftime("%Y-%m-%d")
        events_map = self.get_events_range(user_id, start_d, end_d)
        
        existing_events = []
        for ev_list in events_map.values():
            existing_events.extend(ev_list)
        
        conflicts = []
        clean_exclude = str(exclude_event_id).split("_")[0] if exclude_event_id else None

        for ev in existing_events:
            ev_id = str(ev.get('id', ''))
            ev_master = str(ev.get('master_id') or ev_id.split("_")[0])
            if clean_exclude and (clean_exclude in (ev_id, ev_master)):
                continue
            if ev.get('is_all_day'):
                continue
            ev_start = ev['start_datetime']
            ev_end = ev.get('end_datetime') or (ev_start + timedelta(minutes=ev.get('duration_minutes', 60)))
            
            # Interval overlap: new_start < existing_end AND new_end > existing_start
            if buffered_start < ev_end and buffered_end > ev_start:
                conflicts.append(ev)
                
        return conflicts

    def find_free_slots(self, user_id: int, target_date: str,
                        slot_duration_minutes: int = 30,
                        buffer_minutes: int = 0) -> List[Dict[str, Any]]:
        """
        Find open free slots on a given date within user's working hours.
        """
        settings = self.get_settings(user_id)
        wh_start_str = settings.get('working_hours_start', '09:00')
        wh_end_str = settings.get('working_hours_end', '18:00')
        
        wh_start_t = self._parse_time(wh_start_str) or time(9, 0)
        wh_end_t = self._parse_time(wh_end_str) or time(18, 0)
        
        d_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
        day_start = datetime.combine(d_obj, wh_start_t)
        day_end = datetime.combine(d_obj, wh_end_t)
        
        events = self.get_events(user_id, target_date)
        busy_intervals = []
        for ev in events:
            if ev.get('is_all_day'):
                continue
            s = ev['start_datetime'] - timedelta(minutes=buffer_minutes)
            e = (ev.get('end_datetime') or (ev['start_datetime'] + timedelta(minutes=60))) + timedelta(minutes=buffer_minutes)
            s_clamped = max(day_start, s)
            e_clamped = min(day_end, e)
            if s_clamped < e_clamped:
                busy_intervals.append((s_clamped, e_clamped))

        # Merge overlapping busy intervals
        busy_intervals.sort(key=lambda x: x[0])
        merged_busy = []
        for interval in busy_intervals:
            if not merged_busy:
                merged_busy.append(interval)
            else:
                last_s, last_e = merged_busy[-1]
                if interval[0] <= last_e:
                    merged_busy[-1] = (last_s, max(last_e, interval[1]))
                else:
                    merged_busy.append(interval)

        # Compute gaps
        free_slots = []
        curr_ptr = day_start
        for b_start, b_end in merged_busy:
            if (b_start - curr_ptr).total_seconds() >= slot_duration_minutes * 60:
                free_slots.append({
                    "start": curr_ptr.strftime("%H:%M"),
                    "end": b_start.strftime("%H:%M"),
                    "duration_minutes": int((b_start - curr_ptr).total_seconds() / 60)
                })
            curr_ptr = max(curr_ptr, b_end)

        if (day_end - curr_ptr).total_seconds() >= slot_duration_minutes * 60:
            free_slots.append({
                "start": curr_ptr.strftime("%H:%M"),
                "end": day_end.strftime("%H:%M"),
                "duration_minutes": int((day_end - curr_ptr).total_seconds() / 60)
            })

        return free_slots

    def suggest_alternative_slot(self, user_id: int, target_date: str, preferred_time: Optional[str] = None, duration_minutes: int = 30) -> Optional[Dict[str, Any]]:
        """Find the nearest available slot to a requested time, or the next business day."""
        free_slots = self.find_free_slots(user_id, target_date, slot_duration_minutes=duration_minutes)
        if free_slots:
            if not preferred_time:
                return free_slots[0]
            pref_t = self._parse_time(preferred_time) or time(10, 0)
            d_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
            pref_dt = datetime.combine(d_obj, pref_t)

            best_slot = None
            min_diff = float('inf')
            for slot in free_slots:
                s_t = self._parse_time(slot['start'])
                s_dt = datetime.combine(d_obj, s_t)
                diff = abs((s_dt - pref_dt).total_seconds())
                if diff < min_diff:
                    min_diff = diff
                    best_slot = slot
            return best_slot

        # Look at next day
        d_next = (datetime.strptime(target_date, "%Y-%m-%d").date() + timedelta(days=1)).strftime("%Y-%m-%d")
        next_slots = self.find_free_slots(user_id, d_next, slot_duration_minutes=duration_minutes)
        if next_slots:
            slot = next_slots[0]
            slot["date"] = d_next
            return slot
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # Calendar Analytics
    # ─────────────────────────────────────────────────────────────────────────

    def get_calendar_analytics(self, user_id: int, start_date: str, end_date: str) -> Dict[str, Any]:
        """Compute meeting duration, schedule utilization, conflicts, and available time."""
        events_map = self.get_events_range(user_id, start_date, end_date)
        all_events = [ev for ev_list in events_map.values() for ev in ev_list]
        
        total_meetings = len(all_events)
        total_duration_minutes = sum(ev.get('duration_minutes', 60) for ev in all_events if not ev.get('is_all_day'))
        total_duration_hours = round(total_duration_minutes / 60, 2)
        
        d1 = datetime.strptime(start_date, "%Y-%m-%d").date()
        d2 = datetime.strptime(end_date, "%Y-%m-%d").date()
        days_span = max(1, (d2 - d1).days + 1)
        
        # Working hours capacity: 8 hours per weekday
        weekdays = sum(1 for i in range(days_span) if (d1 + timedelta(days=i)).weekday() < 5)
        total_working_hours = weekdays * 8.0
        utilization_pct = round((total_duration_hours / total_working_hours * 100), 1) if total_working_hours > 0 else 0.0

        avg_duration = round(total_duration_minutes / total_meetings, 1) if total_meetings > 0 else 0.0

        # Busiest day
        day_counts = {d: len(evs) for d, evs in events_map.items()}
        busiest_day = max(day_counts.items(), key=lambda x: x[1])[0] if day_counts else None

        # Conflicts count
        conflict_count = 0
        for d, ev_list in events_map.items():
            for i in range(len(ev_list)):
                for j in range(i + 1, len(ev_list)):
                    e1, e2 = ev_list[i], ev_list[j]
                    if not e1.get('is_all_day') and not e2.get('is_all_day'):
                        if max(e1['start_datetime'], e2['start_datetime']) < min(e1['end_datetime'], e2['end_datetime']):
                            conflict_count += 1

        return {
            "start_date": start_date,
            "end_date": end_date,
            "total_meetings": total_meetings,
            "total_meeting_hours": total_duration_hours,
            "working_hours_capacity": total_working_hours,
            "utilization_percent": min(100.0, utilization_pct),
            "average_meeting_minutes": avg_duration,
            "busiest_day": busiest_day,
            "conflicts_detected": conflict_count
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Meeting Notes, Agendas, Checklists & Documents
    # ─────────────────────────────────────────────────────────────────────────

    def add_meeting_notes(self, user_id: int, event_id: str, notes: str) -> bool:
        """Add or append meeting notes to an event's metadata."""
        event = self.get_event_details(user_id, event_id)
        if not event:
            return False
        meta = event.get('metadata', {})
        existing_notes = meta.get('notes', '')
        updated_notes = f"{existing_notes}\n{notes}".strip() if existing_notes else notes.strip()
        meta['notes'] = updated_notes
        return self.update_event(user_id, event_id, {"metadata": meta})

    def add_meeting_agenda(self, user_id: int, event_id: str, agenda_items: List[str]) -> bool:
        """Add structured agenda items to an event's metadata."""
        event = self.get_event_details(user_id, event_id)
        if not event:
            return False
        meta = event.get('metadata', {})
        meta['agenda'] = agenda_items
        return self.update_event(user_id, event_id, {"metadata": meta})

    def add_preparation_checklist(self, user_id: int, event_id: str, checklist_items: List[str]) -> bool:
        """Add preparation checklist items to an event's metadata."""
        event = self.get_event_details(user_id, event_id)
        if not event:
            return False
        meta = event.get('metadata', {})
        items = [{"task": item, "completed": False} for item in checklist_items]
        meta['checklist'] = items
        return self.update_event(user_id, event_id, {"metadata": meta})

    def associate_document(self, user_id: int, event_id: str, doc_path_or_title: str) -> bool:
        """Link an associated document or file path to an event."""
        event = self.get_event_details(user_id, event_id)
        if not event:
            return False
        meta = event.get('metadata', {})
        docs = meta.get('documents', [])
        if doc_path_or_title not in docs:
            docs.append(doc_path_or_title)
        meta['documents'] = docs
        return self.update_event(user_id, event_id, {"metadata": meta})

    def get_event_details(self, user_id: int, event_id: str) -> Optional[Dict[str, Any]]:
        """Fetch full details for a specific event by ID."""
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        real_id = event_id.split("_")[0]
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT id, title, description, start_datetime, end_datetime,
                       is_all_day, event_type, location, category, metadata
                FROM calendar_events
                WHERE id = %s AND user_id = %s
            """, (real_id, user_id))
            row = cur.fetchone()
            if not row:
                return None
            meta = row['metadata'] or {}
            return {
                'id': str(row['id']),
                'title': row['title'],
                'description': row['description'],
                'date': row['start_datetime'].strftime("%Y-%m-%d"),
                'time': row['start_datetime'].strftime("%H:%M") if not row['is_all_day'] else None,
                'end_time': row['end_datetime'].strftime("%H:%M") if row['end_datetime'] and not row['is_all_day'] else None,
                'duration_minutes': int((row['end_datetime'] - row['start_datetime']).total_seconds() / 60) if row['end_datetime'] else 60,
                'is_all_day': row['is_all_day'],
                'location': row['location'],
                'category': row['category'],
                'metadata': meta,
                'attendees': meta.get('attendees', []) if isinstance(meta, dict) else [],
                'notes': meta.get('notes', ''),
                'agenda': meta.get('agenda', []),
                'checklist': meta.get('checklist', []),
                'documents': meta.get('documents', []),
                'type': row['event_type'],
                'start_datetime': row['start_datetime'],
                'end_datetime': row['end_datetime']
            }
        finally:
            cur.close()
            conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Reminders & Schedulers Integration
    # ─────────────────────────────────────────────────────────────────────────

    def add_event_reminder(self, user_id: int, event_id: str, offset_minutes: int = 15) -> bool:
        """Schedule a linked reminder in the reminders table."""
        event = self.get_event_details(user_id, event_id)
        if not event or event.get('is_all_day'):
            return False

        due_at = event['start_datetime'] - timedelta(minutes=offset_minutes)
        if due_at < datetime.now():
            due_at = datetime.now() + timedelta(seconds=10)

        task_text = f"Upcoming meeting: {event['title']} at {event.get('time') or 'scheduled time'}"
        conn = get_connection()
        cur = conn.cursor()
        try:
            # Duplicate reminder protection
            cur.execute("""
                SELECT id FROM reminders
                WHERE user_id = %s AND task_text = %s AND due_at = %s
            """, (user_id, task_text, due_at))
            if cur.fetchone():
                return True

            cur.execute("""
                INSERT INTO reminders (user_id, task_text, due_at, is_notified)
                VALUES (%s, %s, %s, FALSE)
            """, (user_id, task_text, due_at))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.warning(f"[Calendar Storage] Could not add linked reminder: {e}")
            return False
        finally:
            cur.close()
            conn.close()

    def snooze_event_reminder(self, user_id: int, event_id: str, snooze_minutes: int = 10) -> bool:
        """Snooze an existing or recently fired reminder for an event."""
        event = self.get_event_details(user_id, event_id)
        if not event:
            return False
        title = event['title']
        snooze_due = datetime.now() + timedelta(minutes=snooze_minutes)
        task_text = f"Snoozed meeting reminder: {title}"
        
        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO reminders (user_id, task_text, due_at, is_notified)
                VALUES (%s, %s, %s, FALSE)
            """, (user_id, task_text, snooze_due))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.warning(f"[Calendar Storage] Could not snooze reminder: {e}")
            return False
        finally:
            cur.close()
            conn.close()

    # ─────────────────────────────────────────────────────────────────────────
    # Calendar Settings & User Preferences
    # ─────────────────────────────────────────────────────────────────────────

    def get_settings(self, user_id: int) -> Dict[str, Any]:
        """Fetch user calendar settings and regional preferences."""
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        try:
            cur.execute("""
                SELECT region, timezone, end_of_day_prompt_enabled, weekly_summary_enabled,
                       working_hours_start, working_hours_end, default_reminder_minutes
                FROM calendar_settings
                WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
            if row:
                return dict(row)
            # Default settings
            return {
                "region": "IN",
                "timezone": "Asia/Kolkata",
                "end_of_day_prompt_enabled": True,
                "weekly_summary_enabled": True,
                "working_hours_start": "09:00",
                "working_hours_end": "18:00",
                "default_reminder_minutes": 15
            }
        finally:
            cur.close()
            conn.close()

    def update_settings(self, user_id: int, updates: Dict[str, Any]) -> bool:
        """Update or initialize user calendar settings."""
        try:
            user_id = int(user_id)
        except (ValueError, TypeError):
            user_id = 0

        conn = get_connection()
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO calendar_settings 
                (user_id, region, timezone, working_hours_start, working_hours_end, default_reminder_minutes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    region = COALESCE(EXCLUDED.region, calendar_settings.region),
                    timezone = COALESCE(EXCLUDED.timezone, calendar_settings.timezone),
                    working_hours_start = COALESCE(EXCLUDED.working_hours_start, calendar_settings.working_hours_start),
                    working_hours_end = COALESCE(EXCLUDED.working_hours_end, calendar_settings.working_hours_end),
                    default_reminder_minutes = COALESCE(EXCLUDED.default_reminder_minutes, calendar_settings.default_reminder_minutes),
                    updated_at = CURRENT_TIMESTAMP
            """, (
                user_id,
                updates.get('region', 'IN'),
                updates.get('timezone', 'Asia/Kolkata'),
                updates.get('working_hours_start', '09:00'),
                updates.get('working_hours_end', '18:00'),
                updates.get('default_reminder_minutes', 15)
            ))
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error(f"[Calendar Storage] Error updating settings: {e}")
            return False
        finally:
            cur.close()
            conn.close()

    @property
    def timezone_str(self) -> str:
        """Default configured timezone string."""
        return "Asia/Kolkata"

