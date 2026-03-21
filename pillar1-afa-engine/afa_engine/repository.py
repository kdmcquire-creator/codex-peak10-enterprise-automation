"""Persistence for AFA allocation runs."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import AllocationResult
from .serialization import deserialize_allocation_result, serialize_allocation_result


DEFAULT_DB_NAME = "afa-engine.db"


def _default_db_path() -> str:
    configured = os.environ.get("AFA_ENGINE_DB_PATH")
    if configured:
        return configured

    data_dir = Path(os.getcwd()) / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / DEFAULT_DB_NAME)


class AllocationRunRepository:
    """SQLite-backed persistence for allocation runs."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _default_db_path()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS allocation_runs (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save(self, result: AllocationResult) -> AllocationResult:
        payload = json.dumps(serialize_allocation_result(result))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO allocation_runs (run_id, status, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    result.run_id,
                    result.status.value,
                    payload,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return result

    def get(self, run_id: str) -> Optional[AllocationResult]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM allocation_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return deserialize_allocation_result(json.loads(row["payload_json"]))

    def count_runs(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM allocation_runs"
            ).fetchone()
        return int(row["count"]) if row is not None else 0


_repository: Optional[AllocationRunRepository] = None


def get_repository() -> AllocationRunRepository:
    global _repository
    if _repository is None:
        _repository = AllocationRunRepository()
    return _repository


def reset_repository() -> None:
    global _repository
    _repository = None
