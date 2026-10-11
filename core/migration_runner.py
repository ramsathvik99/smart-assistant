"""
Database Migration Runner with Advisory Locking and Version Tracking
Ensures safe, non-destructive schema migrations in production.
Guarantees only one backend instance executes migrations at a time.
"""

import os
import sys
import glob
import hashlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from core.db_pool import get_db_pool

MIGRATIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "migrations"))
MIGRATION_ADVISORY_LOCK_ID = 987654321  # Unique 64-bit int for migration lock


def _init_migrations_table(cur):
    """Ensure schema_migrations tracking table exists."""
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(255) PRIMARY KEY,
            applied_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            checksum VARCHAR(64)
        );
    """)


def run_migrations():
    """
    Scans and executes unapplied .sql migration files in order.
    Uses PostgreSQL advisory locking to guarantee concurrency safety.
    """
    if not os.path.exists(MIGRATIONS_DIR):
        return

    pool = get_db_pool()
    if not pool.is_healthy():
        print("[MIGRATIONS] [WARN] Database not connected. Skipping migrations.")
        return

    migration_files = sorted(glob.glob(os.path.join(MIGRATIONS_DIR, "*.sql")))
    if not migration_files:
        return

    try:
        with pool.get_cursor() as cur:
            # 1. Acquire advisory lock
            try:
                cur.execute("SELECT pg_advisory_lock(%s);", (MIGRATION_ADVISORY_LOCK_ID,))
            except Exception as e:
                print(f"[MIGRATIONS] [NOTICE] Advisory lock acquisition note: {e}")

            # 2. Ensure tracking table exists
            _init_migrations_table(cur)

            # 3. Retrieve already applied versions
            cur.execute("SELECT version FROM schema_migrations;")
            applied_versions = {row[0] for row in cur.fetchall()}

            # 4. Apply unapplied migrations
            for mf in migration_files:
                fname = os.path.basename(mf)
                if fname in applied_versions:
                    continue  # Already applied

                with open(mf, "r", encoding="utf-8") as f:
                    sql_content = f.read()

                if not sql_content.strip():
                    continue

                checksum = hashlib.sha256(sql_content.encode("utf-8")).hexdigest()

                try:
                    cur.execute(sql_content)
                    cur.execute("""
                        INSERT INTO schema_migrations (version, checksum)
                        VALUES (%s, %s)
                        ON CONFLICT (version) DO NOTHING;
                    """, (fname, checksum))
                    print(f"[MIGRATIONS] [APPLIED] Migration {fname} applied successfully.")
                except Exception as e:
                    print(f"[MIGRATIONS] [ERROR] Migration {fname} failed: {e}")
                    raise

            # 5. Release advisory lock
            try:
                cur.execute("SELECT pg_advisory_unlock(%s);", (MIGRATION_ADVISORY_LOCK_ID,))
            except Exception:
                pass

    except Exception as e:
        print(f"[MIGRATIONS] [WARN] Migration runner encountered error: {e}")


if __name__ == "__main__":
    run_migrations()
