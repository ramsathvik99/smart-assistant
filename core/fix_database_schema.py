#!/usr/bin/env python3
"""
Nova DB Schema Verifier (READ-ONLY)
====================================
Verifies that the live PostgreSQL schema matches what the Nova Python code expects.
Does NOT modify any tables, columns or constraints.

Usage: python core/fix_database_schema.py
"""
import sys
import os
from dotenv import load_dotenv
import psycopg2

load_dotenv()

EXPECTED_TABLES = {
    "users": {"id", "username", "password", "voice_identity_hash", "created_at"},
    "user_memory": {"id", "user_id", "memory", "created_at"},
    "user_preferences": {"id", "user_id", "pref_key", "pref_value", "created_at"},
    "system_memory": {"id", "user_id", "key", "value", "updated_at"},
    "plugins": {"id", "plugin_id", "is_enabled", "permissions", "created_at"},
    "plugin_logs": {"id", "user_id", "plugin_id", "action", "status", "error_message", "created_at"},
    "decision_logs": {"id", "user_id", "plugin_id", "decision", "created_at"},
    "security_audit_logs": {"id", "user_id", "action_name", "params", "status", "created_at"},
    "reminders": {"id", "user_id", "task_text", "due_at", "is_notified", "created_at"},
    "messages": {"id", "user_id", "role", "content", "created_at"},
    "notes": {"id", "user_id", "note", "pinned", "done", "created_at"},
    "active_contexts": {"id", "user_id", "context_data", "updated_at"},
}

def get_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "nova_assistant"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "ramsathvik"),
        port=int(os.getenv("DB_PORT", "5432")),
        connect_timeout=5
    )

def verify():
    print("=" * 55)
    print("  Assistant DB Schema Verifier (READ-ONLY)")
    print("=" * 55)

    try:
        conn = get_connection()
    except Exception as e:
        print(f"[FAIL] Cannot connect to PostgreSQL: {e}")
        sys.exit(1)

    cur = conn.cursor()
    all_passed = True

    # 1. List actual tables
    cur.execute("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' ORDER BY table_name;
    """)
    actual_tables = {r[0] for r in cur.fetchall()}
    print(f"\n[INFO] Tables in PostgreSQL ({len(actual_tables)}):")
    for t in sorted(actual_tables):
        print(f"       {t}")

    print()

    # 2. Verify each expected table and its columns
    for table, expected_cols in sorted(EXPECTED_TABLES.items()):
        if table not in actual_tables:
            print(f"[FAIL] Table '{table}' is MISSING from PostgreSQL")
            all_passed = False
            continue

        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s;
        """, (table,))
        actual_cols = {r[0] for r in cur.fetchall()}
        missing = expected_cols - actual_cols

        if missing:
            print(f"[FAIL] {table}: missing columns {missing}")
            all_passed = False
        else:
            print(f"[PASS] {table}")

    # 3. Confirm phantom tables do NOT exist
    phantom_tables = {"command_history", "memory_store", "session_state",
                      "usage_patterns", "error_log", "ai_conversation_log"}
    print()
    for pt in sorted(phantom_tables):
        if pt in actual_tables:
            print(f"[WARN] '{pt}' exists but is not referenced by any Assistant code — OK to ignore")
        else:
            print(f"[PASS] Phantom table '{pt}' correctly absent from PostgreSQL")

    cur.close()
    conn.close()

    print()
    if all_passed:
        print("=" * 55)
        print("  ✅  ALL CHECKS PASSED — Schema is aligned")
        print("=" * 55)
    else:
        print("=" * 55)
        print("  ❌  SOME CHECKS FAILED — See above")
        print("=" * 55)
