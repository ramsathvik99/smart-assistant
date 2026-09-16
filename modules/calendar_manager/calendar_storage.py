"""
Calendar Storage Layer - PostgreSQL Implementation
Handles persistent storage of events using PostgreSQL database.
"""

import psycopg2
import psycopg2.extras
from datetime import datetime, date
from typing import Dict, List, Optional
import uuid

def get_connection():
    """Get database connection."""
    from legacy.memory_manager import get_connection as get_db_connection
    return get_db_connection()

class CalendarStorage:
    """PostgreSQL-based calendar storage."""
    
    def __init__(self, storage_path=None):
        """Initialize storage. storage_path parameter kept for compatibility but not used."""
        pass
    
    def add_event(self, user_id: int, event: Dict) -> str:
        """Add an event to the calendar."""
        conn = get_connection()
        cur = conn.cursor()
        
        try:
            # Parse datetime
            start_dt = datetime.strptime(f"{event['date']} {event.get('time', '00:00')}", "%Y-%m-%d %H:%M")
            
            # Insert event
            event_id = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO calendar_events 
                (id, user_id, title, description, start_datetime, is_all_day, event_type)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                event_id,
                user_id,
                event['title'],
                event.get('description'),
                start_dt,
                event.get('time') is None,
                event.get('type', 'event')
            ))
            
            # Insert recurrence rule if present
            if event.get('recurrence'):
                recurrence = event['recurrence']
                cur.execute("""
                    INSERT INTO recurrence_rules
                    (event_id, frequency, interval, day_of_month)
                    VALUES (%s, %s, %s, %s)
                """, (
                    event_id,
                    recurrence['frequency'],
                    recurrence.get('interval', 1),
                    recurrence.get('day_of_month')
                ))
            
            conn.commit()
            return event_id
            
        except Exception as e:
            conn.rollback()
            print(f"[Calendar Storage] Error adding event: {e}")
            raise
        finally:
            cur.close()
            conn.close()
    
    def get_events(self, user_id: int, event_date: str) -> List[Dict]:
        """Get all events for a specific date."""
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            # Get events for the date
            cur.execute("""
                SELECT id, title, description, start_datetime, end_datetime, 
                       is_all_day, event_type, created_at
                FROM calendar_events
                WHERE user_id = %s 
                  AND DATE(start_datetime) = %s
                ORDER BY start_datetime
            """, (user_id, event_date))
            
            events = []
            for row in cur.fetchall():
                event = {
                    'id': str(row['id']),
                    'title': row['title'],
                    'description': row['description'],
                    'date': event_date,
                    'time': row['start_datetime'].strftime("%H:%M") if not row['is_all_day'] else None,
                    'type': row['event_type']
                }
                events.append(event)
            
            return events
            
        finally:
            cur.close()
            conn.close()
    
    def get_events_range(self, user_id: int, start_date: str, end_date: str) -> Dict[str, List[Dict]]:
        """Get all events in a date range."""
        conn = get_connection()
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        try:
            cur.execute("""
                SELECT id, title, description, start_datetime, end_datetime,
                       is_all_day, event_type
                FROM calendar_events
                WHERE user_id = %s
                  AND DATE(start_datetime) BETWEEN %s AND %s
                ORDER BY start_datetime
            """, (user_id, start_date, end_date))
            
            events_by_date = {}
            for row in cur.fetchall():
                event_date = row['start_datetime'].date().strftime("%Y-%m-%d")
                
                event = {
                    'id': str(row['id']),
                    'title': row['title'],
                    'description': row['description'],
                    'date': event_date,
                    'time': row['start_datetime'].strftime("%H:%M") if not row['is_all_day'] else None,
                    'type': row['event_type']
                }
                
                if event_date not in events_by_date:
                    events_by_date[event_date] = []
                events_by_date[event_date].append(event)
            
            return events_by_date
            
        finally:
            cur.close()
            conn.close()
    
    def update_event(self, user_id: int, event_id: str, updates: Dict) -> bool:
        """Update an existing event."""
        conn = get_connection()
        cur = conn.cursor()
        
        try:
            # Build update query dynamically
            set_clauses = []
            values = []
            
            if 'title' in updates:
                set_clauses.append("title = %s")
                values.append(updates['title'])
            
            if 'date' in updates or 'time' in updates:
                # Reconstruct datetime
                event_date = updates.get('date', datetime.now().strftime("%Y-%m-%d"))
                event_time = updates.get('time', '00:00')
                start_dt = datetime.strptime(f"{event_date} {event_time}", "%Y-%m-%d %H:%M")
                set_clauses.append("start_datetime = %s")
                values.append(start_dt)
            
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
            conn.commit()
            
            return cur.rowcount > 0
            
        except Exception as e:
            conn.rollback()
            print(f"[Calendar Storage] Error updating event: {e}")
            return False
        finally:
            cur.close()
            conn.close()
    
    def delete_event(self, user_id: int, event_id: str) -> bool:
        """Delete an event."""
        conn = get_connection()
        cur = conn.cursor()
        
        try:
            cur.execute("""
                DELETE FROM calendar_events
                WHERE id = %s AND user_id = %s
            """, (event_id, user_id))
            
            conn.commit()
            return cur.rowcount > 0
            
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
            deleted_count = cur.rowcount
            
            return deleted_count
            
        finally:
            cur.close()
            conn.close()
