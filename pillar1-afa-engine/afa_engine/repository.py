"""Persistence for AFA allocation runs and invoice intake queue."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import AllocationResult, Invoice
from .serialization import (
    deserialize_allocation_result,
    deserialize_invoice,
    serialize_allocation_result,
    serialize_invoice,
)


DEFAULT_DB_NAME = "afa-engine.db"


def _preferred_data_dir() -> Path:
    return Path(os.getcwd()) / ".data"


def _fallback_data_dir() -> Path:
    return Path(tempfile.gettempdir()) / "peak10-afa-engine"


def _ensure_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _default_data_dir() -> Path:
    preferred = _preferred_data_dir()
    if _ensure_writable_dir(preferred):
        return preferred

    fallback = _fallback_data_dir()
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _default_db_path() -> str:
    configured = os.environ.get("AFA_ENGINE_DB_PATH")
    if configured:
        return configured

    data_dir = _default_data_dir()
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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS intake_invoices (
                    invoice_id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    received_at TEXT NOT NULL,
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

    def save_intake_invoice(self, invoice: Invoice) -> Invoice:
        payload = json.dumps(serialize_invoice(invoice))
        now_text = datetime.now(timezone.utc).isoformat()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO intake_invoices (invoice_id, source, payload_json, received_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(invoice_id) DO UPDATE SET
                    source = excluded.source,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    invoice.invoice_id,
                    invoice.source,
                    payload,
                    now_text,
                    now_text,
                ),
            )
        return invoice

    def get_intake_invoice(self, invoice_id: str) -> Optional[Invoice]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM intake_invoices WHERE invoice_id = ?",
                (invoice_id,),
            ).fetchone()
        if row is None:
            return None
        return deserialize_invoice(json.loads(row["payload_json"]))

    def list_intake_invoices(
        self,
        *,
        source: str | None = None,
        limit: int = 50,
    ) -> list[Invoice]:
        normalized_limit = max(1, min(limit, 200))
        query = (
            "SELECT payload_json FROM intake_invoices "
            "WHERE (? IS NULL OR source = ?) "
            "ORDER BY updated_at DESC LIMIT ?"
        )
        with self._lock:
            rows = self._conn.execute(
                query,
                (source, source, normalized_limit),
            ).fetchall()
        return [deserialize_invoice(json.loads(row["payload_json"])) for row in rows]

    def count_intake_invoices(self, *, source: str | None = None) -> int:
        query = "SELECT COUNT(*) AS count FROM intake_invoices WHERE (? IS NULL OR source = ?)"
        with self._lock:
            row = self._conn.execute(query, (source, source)).fetchone()
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
