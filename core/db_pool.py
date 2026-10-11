"""
Smart Assistant — Production Connection Pool & Database Resilience Layer
Provides thread-safe connection pooling, health checks, transaction safety,
and graceful offline fallback.
"""

import os
import time
import logging
import threading
from contextlib import contextmanager
from typing import Optional, Dict, Any, Generator

try:
    import psycopg2
    from psycopg2 import pool, extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

logger = logging.getLogger("DatabasePool")


class DatabaseConnectionPool:
    """
    Threaded PostgreSQL connection pool manager.
    Supports environment-based configuration for Development and Production.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DatabaseConnectionPool, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(
        self,
        minconn: int = 1,
        maxconn: int = 20,
        host: Optional[str] = None,
        port: Optional[int] = None,
        dbname: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        database_url: Optional[str] = None,
    ):
        if getattr(self, "_initialized", False):
            return

        from instance.config import settings
        self.host = host or os.getenv("DB_HOST", getattr(settings, "DB_HOST", "localhost"))
        self.port = int(port or os.getenv("DB_PORT", getattr(settings, "DB_PORT", 5432)))
        self.dbname = dbname or os.getenv("DB_NAME", getattr(settings, "DB_NAME", "nova_assistant"))
        self.user = user or os.getenv("DB_USER", getattr(settings, "DB_USER", "postgres"))
        self.password = password or os.getenv("DB_PASSWORD") or getattr(settings, "DB_PASSWORD", None)
        self.database_url = database_url or os.getenv("DATABASE_URL")
        self.minconn = minconn
        self.maxconn = maxconn

        self._pool: Optional[pool.ThreadedConnectionPool] = None
        self._pool_lock = threading.Lock()
        self._stats = {
            "total_queries": 0,
            "failed_queries": 0,
            "pool_hits": 0,
            "pool_misses": 0,
            "created_at": time.time(),
            "last_healthy": None
        }

        self._init_pool()
        self._initialized = True

    def _init_pool(self):
        """Initializes the underlying ThreadedConnectionPool."""
        if not PSYCOPG2_AVAILABLE:
            logger.warning("[DB POOL] psycopg2 is not available in environment.")
            return

        with self._pool_lock:
            try:
                # Dynamically refresh credentials in case .env or settings loaded after initial construction
                from instance.config import settings
                self.host = self.host or os.getenv("DB_HOST", getattr(settings, "DB_HOST", "localhost"))
                self.port = self.port or int(os.getenv("DB_PORT", getattr(settings, "DB_PORT", 5432)))
                self.dbname = self.dbname or os.getenv("DB_NAME", getattr(settings, "DB_NAME", "nova_assistant"))
                self.user = self.user or os.getenv("DB_USER", getattr(settings, "DB_USER", "postgres"))
                self.password = self.password or os.getenv("DB_PASSWORD") or getattr(settings, "DB_PASSWORD", None)
                self.database_url = self.database_url or os.getenv("DATABASE_URL")
            except Exception:
                pass

            try:
                if self.database_url:
                    self._pool = pool.ThreadedConnectionPool(
                        self.minconn,
                        self.maxconn,
                        dsn=self.database_url
                    )
                else:
                    if not self.password:
                        print("[DB POOL] [WARN] DB_PASSWORD is not configured. Set DB_PASSWORD environment variable or configure DATABASE_URL.")
                        self._pool = None
                        return

                    self._pool = pool.ThreadedConnectionPool(
                        self.minconn,
                        self.maxconn,
                        host=self.host,
                        port=self.port,
                        database=self.dbname,
                        user=self.user,
                        password=self.password
                    )
                self._stats["last_healthy"] = time.time()
                print(f"[DB POOL] PostgreSQL connection pool created (min={self.minconn}, max={self.maxconn}, host={self.host}:{self.port})")
            except Exception as e:
                print(f"[DB POOL] [WARN] Connection pool initialization failed: {e}")
                self._pool = None

    def getconn(self):
        """Acquire a raw connection from the pool."""
        if self._pool is None:
            self._init_pool()
        if self._pool is None:
            raise ConnectionError("Database connection pool is unavailable.")
        self._stats["pool_hits"] += 1
        return self._pool.getconn()

    def putconn(self, conn, close: bool = False):
        """Return a connection back to the pool."""
        if self._pool is not None and conn is not None:
            try:
                self._pool.putconn(conn, close=close)
            except Exception:
                pass

    @contextmanager
    def get_connection(self) -> Generator[Any, None, None]:
        """
        Safe context manager for database connection acquisition.
        Commits on successful exit, rolls back on exception, and returns connection to pool.
        """
        conn = None
        close_on_return = False
        try:
            conn = self.getconn()
            yield conn
            conn.commit()
            self._stats["last_healthy"] = time.time()
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    close_on_return = True
            self._stats["failed_queries"] += 1
            raise
        finally:
            if conn:
                self.putconn(conn, close=close_on_return)

    @contextmanager
    def get_cursor(self, cursor_factory=None) -> Generator[Any, None, None]:
        """
        Convenience context manager yielding a cursor with transactional safety.
        """
        with self.get_connection() as conn:
            cur = conn.cursor(cursor_factory=cursor_factory)
            try:
                self._stats["total_queries"] += 1
                yield cur
            finally:
                cur.close()

    def is_healthy(self) -> bool:
        """Check if PostgreSQL database is reachable and responsive."""
        if self._pool is None:
            self._init_pool()
        if self._pool is None:
            return False
        try:
            with self.get_cursor() as cur:
                cur.execute("SELECT 1;")
                res = cur.fetchone()
                return res is not None and res[0] == 1
        except Exception:
            return False

    def get_stats(self) -> Dict[str, Any]:
        """Return observability metrics for database connection pool."""
        is_active = self._pool is not None
        return {
            "active": is_active,
            "host": self.host,
            "port": self.port,
            "database": self.dbname,
            "min_connections": self.minconn,
            "max_connections": self.maxconn,
            "total_queries": self._stats["total_queries"],
            "failed_queries": self._stats["failed_queries"],
            "pool_hits": self._stats["pool_hits"],
            "uptime_seconds": round(time.time() - self._stats["created_at"], 2),
            "last_healthy": self._stats["last_healthy"]
        }

    def close(self):
        """Close all pooled connections."""
        with self._pool_lock:
            if self._pool is not None:
                try:
                    self._pool.closeall()
                    print("[DB POOL] PostgreSQL connection pool closed.")
                except Exception as e:
                    print(f"[DB POOL] Error closing pool: {e}")
                self._pool = None


# Global singleton instance
_db_pool_instance: Optional[DatabaseConnectionPool] = None

def get_db_pool() -> DatabaseConnectionPool:
    global _db_pool_instance
    if _db_pool_instance is None:
        _db_pool_instance = DatabaseConnectionPool()
    return _db_pool_instance
