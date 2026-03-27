"""Persistence for staged documents and corrections."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import CorrectionLog, StagedDocument
from .serialization import (
    deserialize_correction,
    deserialize_staged_document,
    serialize_correction,
    serialize_staged_document,
)


DEFAULT_DB_NAME = "document-ai.db"


def _default_db_path() -> str:
    configured = os.environ.get("DOCUMENT_AI_DB_PATH")
    if configured:
        return configured

    data_dir = Path(os.getcwd()) / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / DEFAULT_DB_NAME)


def _default_staging_dir() -> Path:
    configured = os.environ.get("DOCUMENT_AI_STAGING_DIR")
    if configured:
        path = Path(configured)
    else:
        path = Path(os.getcwd()) / ".data" / "staged-files"
    path.mkdir(parents=True, exist_ok=True)
    return path


class DocumentRepository:
    """SQLite-backed storage for staged documents and correction logs."""

    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or _default_db_path()
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.staging_dir = _default_staging_dir()
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS corrections (
                    correction_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save_document(self, document: StagedDocument) -> StagedDocument:
        payload = json.dumps(serialize_staged_document(document))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO documents (document_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    document.document_id,
                    payload,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return document

    def get_document(self, document_id: str) -> Optional[StagedDocument]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return deserialize_staged_document(json.loads(row["payload_json"]))

    def save_correction(self, correction: CorrectionLog) -> CorrectionLog:
        payload = json.dumps(serialize_correction(correction))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO corrections (correction_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(correction_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    correction.correction_id,
                    payload,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return correction

    def save_document_bytes(self, document_id: str, file_bytes: bytes) -> str:
        path = self.staging_dir / document_id
        with self._lock:
            path.write_bytes(file_bytes)
        return str(path)

    def get_document_bytes(self, document_id: str) -> Optional[bytes]:
        path = self.staging_dir / document_id
        if not path.exists():
            return None
        with self._lock:
            return path.read_bytes()

    def has_document_bytes(self, document_id: str) -> bool:
        return (self.staging_dir / document_id).exists()

    def count_documents(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM documents"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_corrections(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM corrections"
            ).fetchone()
        return int(row["count"]) if row is not None else 0


_repository: Optional[DocumentRepository] = None


def get_repository() -> DocumentRepository:
    global _repository
    if _repository is None:
        _repository = DocumentRepository()
    return _repository


def reset_repository() -> None:
    global _repository
    _repository = None
