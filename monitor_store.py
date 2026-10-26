"""SQLite persistence for user-owned flight monitoring requests.

No authentication is provided here: callers must authenticate users and supply
trusted user IDs. Never accept owner IDs directly from client request bodies.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

SUPPORTED_AIRLINES = frozenset({"JX", "CI", "BR", "TR", "KE", "JL"})
SUPPORTED_CABINS = frozenset({"economy", "premium", "business", "first"})


class ValidationError(ValueError):
    pass


class NotFoundError(LookupError):
    pass


class MonitorStore:
    """User-scoped monitor CRUD. Connection is opened for each operation."""

    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS monitors (
                    id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    depart_start TEXT NOT NULL,
                    depart_end TEXT NOT NULL,
                    return_start TEXT,
                    return_end TEXT,
                    min_stay INTEGER,
                    max_stay INTEGER,
                    airlines TEXT NOT NULL,
                    cabin TEXT NOT NULL,
                    notify_up INTEGER NOT NULL DEFAULT 1,
                    notify_down INTEGER NOT NULL DEFAULT 1,
                    up_threshold INTEGER NOT NULL DEFAULT 0,
                    down_threshold INTEGER NOT NULL DEFAULT 0,
                    target_price INTEGER,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_monitors_owner
                    ON monitors(owner_id, enabled);
            """)

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _validate(data: dict[str, Any]) -> dict[str, Any]:
        # Strict allowlist avoids silently accepting unexpected client fields.
        allowed = {"origin", "destination", "depart_start", "depart_end",
                   "return_start", "return_end", "min_stay", "max_stay",
                   "airlines", "cabin", "notify_up", "notify_down",
                   "up_threshold", "down_threshold", "target_price", "enabled"}
        unknown = set(data) - allowed
        if unknown:
            raise ValidationError(f"Unknown monitor fields: {sorted(unknown)}")
        d = dict(data)
        for name in ("origin", "destination"):
            value = d.get(name)
            if not isinstance(value, str) or len(value.strip()) != 3 or not value.isalpha():
                raise ValidationError(f"{name} must be a three-letter IATA airport code")
            d[name] = value.upper()
        if d["origin"] == d["destination"]:
            raise ValidationError("Origin and destination must differ")
        for name in ("depart_start", "depart_end", "return_start", "return_end"):
            value = d.get(name)
            if value is None and name.startswith("return"):
                continue
            if not isinstance(value, str):
                raise ValidationError(f"{name} must use YYYY-MM-DD")
            try:
                parsed = date.fromisoformat(value)
            except ValueError as exc:
                raise ValidationError(f"Invalid {name}") from exc
            if parsed.isoformat() != value:
                raise ValidationError(f"{name} must use YYYY-MM-DD")
        if d["depart_start"] > d["depart_end"]:
            raise ValidationError("Departure date range is reversed")
        if (d.get("return_start") is None) != (d.get("return_end") is None):
            raise ValidationError("Both return dates must be specified")
        if d.get("return_start") is not None:
            if d["return_start"] > d["return_end"] or d["return_end"] < d["depart_start"]:
                raise ValidationError("Invalid return date range")
        for name in ("min_stay", "max_stay"):
            if d.get(name) is not None and (type(d[name]) is not int or not 1 <= d[name] <= 60):
                raise ValidationError(f"{name} must be 1..60 days")
        if (d.get("min_stay") is None) != (d.get("max_stay") is None):
            raise ValidationError("Both minimum and maximum stay must be specified")
        if d.get("min_stay") is not None:
            if d.get("return_start") is None or d["min_stay"] > d["max_stay"]:
                raise ValidationError("Stay range requires return dates and valid bounds")
        airlines = d.get("airlines")
        if not isinstance(airlines, list) or not airlines or any(type(x) is not str for x in airlines):
            raise ValidationError("At least one airline is required")
        airlines = sorted(set(x.upper() for x in airlines))
        if not set(airlines) <= SUPPORTED_AIRLINES:
            raise ValidationError("Unsupported airline")
        d["airlines"] = json.dumps(airlines)
        d["cabin"] = d.get("cabin", "economy")
        if d["cabin"] not in SUPPORTED_CABINS:
            raise ValidationError("Invalid cabin")
        for field in ("notify_up", "notify_down", "enabled"):
            d[field] = d.get(field, True)
            if type(d[field]) is not bool:
                raise ValidationError(f"{field} must be boolean")
            d[field] = int(d[field])
        for field in ("up_threshold", "down_threshold", "target_price"):
            d[field] = d.get(field, None if field == "target_price" else 0)
            if d[field] is not None and (type(d[field]) is not int or d[field] < 0):
                raise ValidationError(f"{field} must be nonnegative integer")
        return d

    @staticmethod
    def _unpack(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["airlines"] = json.loads(d["airlines"])
        for field in ("notify_up", "notify_down", "enabled"):
            d[field] = bool(d[field])
        return d

    @staticmethod
    def _owner(owner_id: str):
        if not isinstance(owner_id, str) or not owner_id.strip():
            raise ValidationError("Authenticated owner ID required")

    def create(self, owner_id: str, data: dict[str, Any]) -> dict[str, Any]:
        self._owner(owner_id)
        d = self._validate(data)
        now = datetime.now(timezone.utc).isoformat()
        d.update(id=str(uuid4()), owner_id=owner_id, created_at=now, updated_at=now)
        keys = list(d)
        with self._connect() as conn:
            conn.execute(f"INSERT INTO monitors ({','.join(keys)}) VALUES ({','.join('?' for _ in keys)})",
                         [d[k] for k in keys])
        return self.get(owner_id, d["id"])

    def get(self, owner_id: str, monitor_id: str) -> dict[str, Any]:
        self._owner(owner_id)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM monitors WHERE owner_id=? AND id=?",
                               (owner_id, monitor_id)).fetchone()
        if row is None:
            raise NotFoundError("Monitor not found")
        return self._unpack(row)

    def list(self, owner_id: str) -> list[dict[str, Any]]:
        self._owner(owner_id)
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM monitors WHERE owner_id=? ORDER BY created_at DESC",
                                (owner_id,)).fetchall()
        return [self._unpack(row) for row in rows]

    def update(self, owner_id: str, monitor_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get(owner_id, monitor_id)
        fields = {k: v for k, v in current.items()
                  if k not in {"id", "owner_id", "created_at", "updated_at"}}
        fields.update(patch)
        d = self._validate(fields)
        d["updated_at"] = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute("UPDATE monitors SET " + ",".join(f"{k}=?" for k in d) +
                                  " WHERE id=? AND owner_id=?",
                                  [*d.values(), monitor_id, owner_id])
            if cursor.rowcount == 0:
                raise NotFoundError("Monitor not found")
        return self.get(owner_id, monitor_id)

    def delete(self, owner_id: str, monitor_id: str) -> None:
        self._owner(owner_id)
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM monitors WHERE id=? AND owner_id=?",
                                  (monitor_id, owner_id))
            if cursor.rowcount == 0:
                raise NotFoundError("Monitor not found")
