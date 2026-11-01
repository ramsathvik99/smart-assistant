"""
Device Registry
Manages user-isolated, persistent records of paired devices with thread-safe operations.
Extended with PostgreSQL primary storage, enrollment codes, stable identity, auth tokens,
location history, and remote connectivity tracking.
"""

from __future__ import annotations
import secrets

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .device_auth import (
    generate_device_id,
    generate_device_secret,
    generate_device_token,
    generate_enrollment_code,
    hash_secret,
    constant_time_equals,
)
from .device_models import DeviceRecord, now_iso

logger = logging.getLogger(__name__)

# Max location history entries to keep per device
_MAX_LOCATION_HISTORY = 50


def _try_get_db_connection():
    """Obtain a database connection context manager from core.db_pool lazily."""
    try:
        from core.db_pool import get_db_pool
        pool = get_db_pool()
        if pool and pool.is_healthy():
            return pool.get_connection
        return None
    except Exception:
        return None


class DeviceRegistry:
    """
    Centralized registry of paired mobile/remote devices.
    Primary storage: PostgreSQL `assistant_devices` table.
    Fallback: JSON files per user in data/devices/.
    Enforces strict user isolation: User A cannot query or access User B's devices.
    """

    def __init__(self, base_storage_dir: Optional[str] = None):
        self._lock = threading.RLock()
        if base_storage_dir:
            self.storage_dir = Path(base_storage_dir)
        else:
            project_root = Path(__file__).resolve().parent.parent.parent
            self.storage_dir = project_root / "data" / "devices"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        # In-memory index: device_id -> DeviceRecord
        self._devices: dict[str, DeviceRecord] = {}
        # Secondary indices for fast lookup
        self._enrollment_index: dict[str, str] = {}   # enrollment_code -> device_id
        self._identity_index: dict[str, str] = {}     # stable_identity -> device_id
        self._token_index: dict[str, str] = {}        # auth_token_hash -> device_id

        self._init_postgres()
        self._load_all()

    # ------------------------------------------------------------------
    # PostgreSQL helpers
    # ------------------------------------------------------------------

    def _init_postgres(self) -> None:
        """Create assistant_devices table if it does not already exist."""
        get_conn = _try_get_db_connection()
        if not get_conn:
            logger.warning("db_pool unavailable; using JSON-only storage.")
            return
        try:
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS assistant_devices (
                            device_id         TEXT PRIMARY KEY,
                            user_id           INTEGER NOT NULL,
                            name              TEXT NOT NULL DEFAULT '',
                            platform          TEXT NOT NULL DEFAULT 'android',
                            os_version        TEXT NOT NULL DEFAULT '',
                            agent_version     TEXT NOT NULL DEFAULT '',
                            ip                TEXT NOT NULL DEFAULT '',
                            online            BOOLEAN NOT NULL DEFAULT FALSE,
                            battery           INTEGER,
                            charging          BOOLEAN NOT NULL DEFAULT FALSE,
                            capabilities      JSONB NOT NULL DEFAULT '[]',
                            permissions       JSONB NOT NULL DEFAULT '[]',
                            paired_at         TEXT NOT NULL DEFAULT '',
                            last_seen         TEXT NOT NULL DEFAULT '',
                            secret_hash       TEXT NOT NULL DEFAULT '',
                            revoked           BOOLEAN NOT NULL DEFAULT FALSE,
                            metadata          JSONB NOT NULL DEFAULT '{}',
                            enrollment_code   TEXT NOT NULL DEFAULT '',
                            stable_identity   TEXT NOT NULL DEFAULT '',
                            auth_token_hash   TEXT NOT NULL DEFAULT '',
                            connection_mode   TEXT NOT NULL DEFAULT 'local',
                            enrollment_state  TEXT NOT NULL DEFAULT 'pending',
                            location          JSONB NOT NULL DEFAULT '{}',
                            location_history  JSONB NOT NULL DEFAULT '[]',
                            network_info      JSONB NOT NULL DEFAULT '{}'
                        );
                        CREATE INDEX IF NOT EXISTS idx_ad_user_id
                            ON assistant_devices(user_id);
                        CREATE INDEX IF NOT EXISTS idx_ad_enrollment_code
                            ON assistant_devices(enrollment_code)
                            WHERE enrollment_code != '';
                        CREATE INDEX IF NOT EXISTS idx_ad_stable_identity
                            ON assistant_devices(stable_identity)
                            WHERE stable_identity != '';
                        CREATE INDEX IF NOT EXISTS idx_ad_auth_token_hash
                            ON assistant_devices(auth_token_hash)
                            WHERE auth_token_hash != '';
                    """)
                    conn.commit()
            logger.info("assistant_devices table verified/created in PostgreSQL.")
        except Exception as e:
            logger.warning(f"PostgreSQL init failed (falling back to JSON): {e}")

    def _sync_device_to_postgres(self, record: DeviceRecord) -> None:
        """UPSERT a single device record to PostgreSQL."""
        get_conn = _try_get_db_connection()
        if not get_conn:
            return
        try:
            d = record.to_dict()
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO assistant_devices (
                            device_id, user_id, name, platform, os_version,
                            agent_version, ip, online, battery, charging,
                            capabilities, permissions, paired_at, last_seen,
                            secret_hash, revoked, metadata,
                            enrollment_code, stable_identity, auth_token_hash,
                            connection_mode, enrollment_state,
                            location, location_history, network_info
                        ) VALUES (
                            %(device_id)s, %(user_id)s, %(name)s, %(platform)s,
                            %(os_version)s, %(agent_version)s, %(ip)s,
                            %(online)s, %(battery)s, %(charging)s,
                            %(capabilities)s::jsonb, %(permissions)s::jsonb,
                            %(paired_at)s, %(last_seen)s, %(secret_hash)s,
                            %(revoked)s, %(metadata)s::jsonb,
                            %(enrollment_code)s, %(stable_identity)s,
                            %(auth_token_hash)s, %(connection_mode)s,
                            %(enrollment_state)s,
                            %(location)s::jsonb, %(location_history)s::jsonb,
                            %(network_info)s::jsonb
                        )
                        ON CONFLICT (device_id) DO UPDATE SET
                            user_id          = EXCLUDED.user_id,
                            name             = EXCLUDED.name,
                            platform         = EXCLUDED.platform,
                            os_version       = EXCLUDED.os_version,
                            agent_version    = EXCLUDED.agent_version,
                            ip               = EXCLUDED.ip,
                            online           = EXCLUDED.online,
                            battery          = EXCLUDED.battery,
                            charging         = EXCLUDED.charging,
                            capabilities     = EXCLUDED.capabilities,
                            permissions      = EXCLUDED.permissions,
                            paired_at        = EXCLUDED.paired_at,
                            last_seen        = EXCLUDED.last_seen,
                            secret_hash      = EXCLUDED.secret_hash,
                            revoked          = EXCLUDED.revoked,
                            metadata         = EXCLUDED.metadata,
                            enrollment_code  = EXCLUDED.enrollment_code,
                            stable_identity  = EXCLUDED.stable_identity,
                            auth_token_hash  = EXCLUDED.auth_token_hash,
                            connection_mode  = EXCLUDED.connection_mode,
                            enrollment_state = EXCLUDED.enrollment_state,
                            location         = EXCLUDED.location,
                            location_history = EXCLUDED.location_history,
                            network_info     = EXCLUDED.network_info
                    """, {
                        **d,
                        "capabilities": json.dumps(d["capabilities"]),
                        "permissions": json.dumps(d["permissions"]),
                        "metadata": json.dumps(d["metadata"]),
                        "location": json.dumps(d["location"]),
                        "location_history": json.dumps(d["location_history"]),
                        "network_info": json.dumps(d["network_info"]),
                    })
                    conn.commit()
        except Exception as e:
            logger.warning(f"PostgreSQL sync failed for {record.device_id}: {e}")

    # ------------------------------------------------------------------
    # JSON persistence helpers
    # ------------------------------------------------------------------

    def _user_file(self, user_id: int) -> Path:
        return self.storage_dir / f"user_{user_id}_devices.json"

    def _load_all(self) -> None:
        """Load devices from PostgreSQL first, then merge any JSON-only records."""
        with self._lock:
            self._devices.clear()
            self._enrollment_index.clear()
            self._identity_index.clear()
            self._token_index.clear()

            # 1. Try PostgreSQL
            get_conn = _try_get_db_connection()
            pg_loaded = False
            if get_conn:
                try:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("SELECT * FROM assistant_devices")
                            rows = cur.fetchall()
                            cols = [desc[0] for desc in cur.description]
                    for row in rows:
                        d = dict(zip(cols, row))
                        rec = DeviceRecord.from_dict(d)
                        self._devices[rec.device_id] = rec
                        self._rebuild_indices(rec)
                    pg_loaded = True
                    logger.info(f"Loaded {len(self._devices)} devices from PostgreSQL.")
                except Exception as e:
                    logger.warning(f"PostgreSQL load failed: {e}")

            # 2. JSON fallback: only load from files if PostgreSQL was not available
            if not pg_loaded:
                for path in self.storage_dir.glob("user_*_devices.json"):
                    try:
                        raw = json.loads(path.read_text(encoding="utf-8"))
                        devs = raw.get("devices", {})
                        for d_id, d_data in devs.items():
                            if d_id not in self._devices:
                                rec = DeviceRecord.from_dict(d_data)
                                self._devices[d_id] = rec
                                self._rebuild_indices(rec)
                    except Exception as e:
                        logger.warning(f"Failed to load device file {path}: {e}")

    def _rebuild_indices(self, rec: DeviceRecord) -> None:
        """Maintain secondary lookup indices for a record (must hold lock)."""
        if rec.enrollment_code:
            self._enrollment_index[rec.enrollment_code] = rec.device_id
        if rec.stable_identity:
            self._identity_index[rec.stable_identity] = rec.device_id
        if rec.auth_token_hash:
            self._token_index[rec.auth_token_hash] = rec.device_id

    def _save_user(self, user_id: int) -> None:
        """Write devices for user_id to JSON and sync each to PostgreSQL."""
        with self._lock:
            user_devs = {
                d_id: rec.to_dict()
                for d_id, rec in self._devices.items()
                if rec.user_id == user_id
            }
            path = self._user_file(user_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"user_id": user_id, "devices": user_devs}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            for d_id in user_devs:
                self._sync_device_to_postgres(self._devices[d_id])

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def list_devices(self, user_id: Optional[int] = None) -> list[DeviceRecord]:
        """List all devices owned by user_id (or all non-revoked devices if None)."""
        with self._lock:
            user_devs = [
                rec for rec in self._devices.values()
                if (user_id is None or rec.user_id == user_id) and not rec.revoked
            ]
            return sorted(user_devs, key=lambda d: (not d.online, d.name.lower()))

    def get_device(self, user_id: int, device_id: str) -> Optional[DeviceRecord]:
        """Get a specific device owned by user_id."""
        with self._lock:
            rec = self._devices.get(device_id)
            if rec and rec.user_id == user_id and not rec.revoked:
                return rec
            return None

    def register_device(
        self,
        user_id: int,
        name: str,
        platform: str = "android",
        os_version: str = "",
        agent_version: str = "",
        ip: str = "",
        battery: Optional[int] = None,
        charging: bool = False,
        capabilities: Optional[list[str]] = None,
        permissions: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[DeviceRecord, str]:
        """
        Register a newly paired device bound to user_id.
        Returns (DeviceRecord, plaintext_secret).
        """
        with self._lock:
            device_id = generate_device_id(platform, name)
            secret = generate_device_secret()
            record = DeviceRecord(
                device_id=device_id,
                user_id=user_id,
                name=name.strip() or "Mobile Device",
                platform=(platform or "android").lower(),
                os_version=os_version,
                agent_version=agent_version,
                ip=ip,
                online=True,
                battery=battery,
                charging=charging,
                capabilities=list(capabilities or [
                    "battery", "flashlight", "launch_app", "open_url", "volume"
                ]),
                permissions=list(permissions or []),
                paired_at=now_iso(),
                last_seen=now_iso(),
                secret_hash=hash_secret(secret),
                revoked=False,
                metadata=dict(metadata or {}),
            )
            self._devices[device_id] = record
            self._rebuild_indices(record)
            self._save_user(user_id)
            logger.info(f"Registered new device '{record.name}' ({device_id}) for user {user_id}")
            return record, secret

    # ------------------------------------------------------------------
    # Enrollment (remote device registration via enrollment code)
    # ------------------------------------------------------------------

    def enroll_device(
        self,
        user_id: int,
        enrollment_code: str,
        device_name: str,
        stable_identity: str,
        platform: str = "android",
        os_version: str = "",
        agent_version: str = "",
        ip: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> tuple[Optional[DeviceRecord], Optional[str]]:
        """
        Enroll a remote device that presented a valid enrollment code.
        Returns (DeviceRecord, plaintext_auth_token) or (None, None) on failure.
        The enrollment_code must match a pending offer or an existing record.
        """
        with self._lock:
            # Normalize the code
            from .device_auth import normalize_enrollment_code
            normalized = normalize_enrollment_code(enrollment_code)
            formatted = f"{normalized[0:4]}-{normalized[4:8]}-{normalized[8:12]}-{normalized[12:16]}"

            # Check if already enrolled with this identity or matching existing device for user
            existing_id = self._identity_index.get(stable_identity)
            if not existing_id:
                clean_name = device_name.strip().lower()
                for did, dev in self._devices.items():
                    if dev.user_id == user_id and dev.platform == (platform or "android").lower() and dev.name.strip().lower() == clean_name and not dev.revoked:
                        existing_id = did
                        break

            if existing_id:
                existing = self._devices.get(existing_id)
                if existing and not existing.revoked:
                    # Re-issue token, and update enrollment code + index
                    token = generate_device_token()
                    existing.auth_token_hash = hash_secret(token)
                    existing.enrollment_state = "enrolled"
                    existing.connection_mode = "remote_relay"
                    existing.online = True
                    existing.last_seen = now_iso()
                    existing.ip = ip or existing.ip
                    if stable_identity:
                        old_ident = existing.stable_identity
                        existing.stable_identity = stable_identity
                        if old_ident and old_ident in self._identity_index:
                            del self._identity_index[old_ident]
                        self._identity_index[stable_identity] = existing_id
                    # Update enrollment code so lookup by the new code works
                    old_code = existing.enrollment_code
                    existing.enrollment_code = formatted
                    if old_code and old_code in self._enrollment_index:
                        del self._enrollment_index[old_code]
                    self._enrollment_index[formatted] = existing_id
                    self._token_index[existing.auth_token_hash] = existing_id
                    self._save_user(existing.user_id)
                    logger.info(f"Re-enrolled device {existing_id} for user {user_id}")
                    return existing, token

            # Create new enrollment
            device_id = generate_device_id(platform, device_name)
            token = generate_device_token()
            record = DeviceRecord(
                device_id=device_id,
                user_id=user_id,
                name=device_name.strip() or "Remote Device",
                platform=(platform or "android").lower(),
                os_version=os_version,
                agent_version=agent_version,
                ip=ip,
                online=True,
                capabilities=["battery", "location", "remote_control"],
                paired_at=now_iso(),
                last_seen=now_iso(),
                enrollment_code=formatted,
                stable_identity=stable_identity,
                auth_token_hash=hash_secret(token),
                connection_mode="remote",
                enrollment_state="enrolled",
                metadata=dict(metadata or {}),
            )
            self._devices[device_id] = record
            self._rebuild_indices(record)
            self._save_user(user_id)
            logger.info(f"Enrolled remote device '{record.name}' ({device_id}) for user {user_id}")
            return record, token

    def authenticate_remote_token(self, token: str) -> Optional[DeviceRecord]:
        """Validate a bearer token and return the matching DeviceRecord, or None."""
        token_hash = hash_secret(token)
        with self._lock:
            device_id = self._token_index.get(token_hash)
            if not device_id:
                return None
            rec = self._devices.get(device_id)
            if rec and not rec.revoked and rec.enrollment_state == "enrolled":
                return rec
            return None

    # ------------------------------------------------------------------
    # Secondary index lookups
    # ------------------------------------------------------------------

    def get_device_by_enrollment_code(self, code: str) -> Optional[DeviceRecord]:
        """Look up a device by its 16-char enrollment code."""
        from .device_auth import normalize_enrollment_code
        normalized = normalize_enrollment_code(code)
        formatted = f"{normalized[0:4]}-{normalized[4:8]}-{normalized[8:12]}-{normalized[12:16]}"
        with self._lock:
            device_id = self._enrollment_index.get(formatted)
            return self._devices.get(device_id) if device_id else None

    def get_device_by_stable_identity(self, stable_identity: str) -> Optional[DeviceRecord]:
        """Look up a device by its stable cryptographic identity hash."""
        with self._lock:
            device_id = self._identity_index.get(stable_identity)
            return self._devices.get(device_id) if device_id else None

    def get_device_by_token(self, token: str) -> Optional[DeviceRecord]:
        """Look up a device by its plaintext bearer token (hashed internally)."""
        return self.authenticate_remote_token(token)

    # ------------------------------------------------------------------
    # Location and heartbeat updates
    # ------------------------------------------------------------------

    def update_location(
        self,
        device_id: str,
        latitude: float,
        longitude: float,
        accuracy_m: Optional[float] = None,
        altitude_m: Optional[float] = None,
        provider: str = "gps",
    ) -> Optional[DeviceRecord]:
        """Update a device's current location and append to history."""
        with self._lock:
            rec = self._devices.get(device_id)
            if not rec:
                return None
            loc = {
                "latitude": latitude,
                "longitude": longitude,
                "accuracy_m": accuracy_m,
                "altitude_m": altitude_m,
                "provider": provider,
                "timestamp": now_iso(),
            }
            rec.location = loc
            # Keep rolling history
            hist = list(rec.location_history)
            hist.append(loc)
            if len(hist) > _MAX_LOCATION_HISTORY:
                hist = hist[-_MAX_LOCATION_HISTORY:]
            rec.location_history = hist
            rec.last_seen = now_iso()
            self._save_user(rec.user_id)
            return rec

    def update_network_and_heartbeat(
        self,
        device_id: str,
        battery: Optional[int] = None,
        charging: Optional[bool] = None,
        network_info: Optional[dict[str, Any]] = None,
        connection_mode: Optional[str] = None,
        ip: Optional[str] = None,
    ) -> Optional[DeviceRecord]:
        """Update heartbeat fields from a device check-in."""
        with self._lock:
            rec = self._devices.get(device_id)
            if not rec:
                return None
            if battery is not None:
                rec.battery = battery
            if charging is not None:
                rec.charging = charging
            if network_info:
                rec.network_info = dict(network_info)
            if connection_mode:
                rec.connection_mode = connection_mode
            if ip:
                rec.ip = ip
            rec.online = True
            rec.last_seen = now_iso()
            self._save_user(rec.user_id)
            return rec

    # ------------------------------------------------------------------
    # Existing methods (preserved)
    # ------------------------------------------------------------------

    def authenticate(self, device_id: str, secret: str, ip: str = "") -> Optional[DeviceRecord]:
        """Verify device secret and mark device online."""
        with self._lock:
            record = self._devices.get(device_id)
            if record is None or record.revoked:
                return None
            if not constant_time_equals(record.secret_hash, hash_secret(secret)):
                return None
            record.online = True
            record.last_seen = now_iso()
            if ip:
                record.ip = ip
            self._save_user(record.user_id)
            return record

    def update_device(self, record: DeviceRecord) -> Optional[DeviceRecord]:
        """Update an existing device record and persist it."""
        with self._lock:
            if not record or not record.device_id:
                return None
            self._devices[record.device_id] = record
            self._rebuild_indices(record)
            self._save_user(record.user_id)
            return record

    def update_status(
        self,
        device_id: str,
        online: Optional[bool] = None,
        battery: Optional[int] = None,
        charging: Optional[bool] = None,
        capabilities: Optional[list[str]] = None,
    ) -> Optional[DeviceRecord]:
        """Update runtime state of a device."""
        with self._lock:
            record = self._devices.get(device_id)
            if not record:
                return None
            if online is not None:
                record.online = online
            if battery is not None:
                record.battery = battery
            if charging is not None:
                record.charging = charging
            if capabilities is not None:
                record.capabilities = list(capabilities)
            record.last_seen = now_iso()
            self._save_user(record.user_id)
            return record

    def rename_device(self, user_id: int, device_id: str, new_name: str) -> Optional[DeviceRecord]:
        """Rename a device belonging to user_id."""
        with self._lock:
            record = self.get_device(user_id, device_id)
            if not record:
                return None
            clean_name = new_name.strip()
            if clean_name:
                record.name = clean_name
                self._save_user(user_id)
            return record

    def revoke_device(self, user_id: int, device_id: str) -> bool:
        """Revoke pairing for a device belonging to user_id."""
        with self._lock:
            record = self.get_device(user_id, device_id)
            if not record:
                return False
            record.revoked = True
            record.online = False
            record.auth_token_hash = ""
            record.enrollment_state = "revoked"
            record.last_seen = now_iso()
            # Remove from token index
            if record.auth_token_hash:
                self._token_index.pop(record.auth_token_hash, None)
            self._save_user(user_id)
            logger.info(f"Revoked device {device_id} for user {user_id}")
            return True

    def remove_device(self, user_id: Optional[int] = None, device_id: str = "") -> bool:
        """Completely remove a device record from memory, indices, PostgreSQL, and JSON."""
        if isinstance(user_id, str) and not device_id:
            device_id = user_id
            user_id = None
        with self._lock:
            record = self._devices.get(device_id)
            if not record:
                return False
            if user_id is not None and record.user_id != user_id:
                return False

            self._devices.pop(device_id, None)
            if record.enrollment_code:
                self._enrollment_index.pop(record.enrollment_code, None)
            if record.auth_token_hash:
                self._token_index.pop(record.auth_token_hash, None)
            if record.stable_identity:
                self._identity_index.pop(record.stable_identity, None)

            get_conn = _try_get_db_connection()
            if get_conn:
                try:
                    with get_conn() as conn:
                        with conn.cursor() as cur:
                            cur.execute("DELETE FROM assistant_devices WHERE device_id = %s", (device_id,))
                        conn.commit()
                except Exception as e:
                    logger.warning(f"Failed to delete device {device_id} from PostgreSQL: {e}")

            self._save_user(record.user_id)
            logger.info(f"Removed device {device_id} for user {record.user_id}")
            return True

    def resolve_device(self, user_id: Optional[int] = None, query: str = "") -> list[DeviceRecord]:
        """
        Find devices matching query (by name or ID) for the given user_id.
        If query is empty, returns all active devices.
        """
        with self._lock:
            all_user_devs = self.list_devices(user_id)
            clean = query.lower().strip()
            if not clean or clean in ("phone", "my phone", "device", "mobile"):
                return all_user_devs

            # Exact match first
            exact = [
                d for d in all_user_devs
                if d.name.lower() == clean
                or d.device_id.lower() == clean
                or str(d.metadata.get("serial", "")).lower() == clean
            ]
            if exact:
                return exact
            # Partial match
            return [
                d for d in all_user_devs
                if clean in d.name.lower()
                or clean in d.device_id.lower()
                or clean in str(d.metadata.get("serial", "")).lower()
            ]


# Global singleton
_registry_instance: Optional[DeviceRegistry] = None
_registry_lock = threading.Lock()


def get_device_registry() -> DeviceRegistry:
    global _registry_instance
    with _registry_lock:
        if _registry_instance is None:
            _registry_instance = DeviceRegistry()
        return _registry_instance
