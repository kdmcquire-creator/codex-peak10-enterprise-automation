"""Persistence for staged documents and corrections."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import (
    CorrectionLog,
    DatabaseUpdateProposal,
    DatabaseUpdateStatus,
    LearningEvidence,
    StagedDocument,
)
from .serialization import (
    deserialize_database_update_proposal,
    deserialize_learning_evidence,
    deserialize_correction,
    deserialize_staged_document,
    serialize_database_update_proposal,
    serialize_learning_evidence,
    serialize_correction,
    serialize_staged_document,
)


DEFAULT_DB_NAME = "document-ai.db"


def _preferred_data_dir() -> Path:
    return Path(os.getcwd()) / ".data"


def _fallback_data_dir() -> Path:
    return Path(tempfile.gettempdir()) / "peak10-document-ai"


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
    configured = os.environ.get("DOCUMENT_AI_DB_PATH")
    if configured:
        return configured

    data_dir = _default_data_dir()
    return str(data_dir / DEFAULT_DB_NAME)


def _default_staging_dir() -> Path:
    configured = os.environ.get("DOCUMENT_AI_STAGING_DIR")
    if configured:
        path = Path(configured)
    else:
        path = _default_data_dir() / "staged-files"
    path.mkdir(parents=True, exist_ok=True)
    return path


class DocumentRepository:
    """SQLite-backed storage for documents, updates, and learning evidence."""

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
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS database_updates (
                    update_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_database_updates_document_status
                ON database_updates (document_id, status)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    update_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_learning_evidence_update
                ON learning_evidence (update_id)
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applied_updates (
                    update_id TEXT PRIMARY KEY,
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

    def list_documents(
        self,
        *,
        status: str | None = None,
        source: str | None = None,
        limit: int = 50,
    ) -> list[StagedDocument]:
        safe_limit = max(1, min(limit, 500))
        with self._lock:
            rows = self._conn.execute(
                "SELECT payload_json FROM documents ORDER BY updated_at DESC LIMIT ?",
                (safe_limit,),
            ).fetchall()

        documents = [deserialize_staged_document(json.loads(row["payload_json"])) for row in rows]
        if status:
            documents = [document for document in documents if document.status == status]
        if source:
            documents = [document for document in documents if document.source == source]
        return documents[:safe_limit]

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
        path = self._resolve_safe_document_bytes_path(document_id)
        with self._lock:
            path.write_bytes(file_bytes)
        return str(path)

    def save_database_update(self, proposal: DatabaseUpdateProposal) -> DatabaseUpdateProposal:
        payload = json.dumps(serialize_database_update_proposal(proposal))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO database_updates (update_id, document_id, status, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(update_id) DO UPDATE SET
                    document_id = excluded.document_id,
                    status = excluded.status,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    proposal.update_id,
                    proposal.document_id,
                    proposal.status.value,
                    payload,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return proposal

    def save_learning_evidence(self, evidence: LearningEvidence) -> LearningEvidence:
        payload = json.dumps(serialize_learning_evidence(evidence))
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO learning_evidence (evidence_id, update_id, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(evidence_id) DO UPDATE SET
                    update_id = excluded.update_id,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    evidence.evidence_id,
                    evidence.update_id,
                    payload,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return evidence

    def list_learning_evidence(self, *, limit: int = 500) -> list[LearningEvidence]:
        safe_limit = max(1, min(limit, 5000))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT payload_json
                FROM learning_evidence
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        return [
            deserialize_learning_evidence(json.loads(row["payload_json"]))
            for row in rows
        ]

    def save_applied_update(self, update_id: str, payload: dict[str, object]) -> str:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO applied_updates (update_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(update_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    update_id,
                    json.dumps(payload),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return f"sqlite://applied_updates/{update_id}"

    def get_database_update(self, update_id: str) -> Optional[DatabaseUpdateProposal]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM database_updates WHERE update_id = ?",
                (update_id,),
            ).fetchone()
        if row is None:
            return None
        return deserialize_database_update_proposal(json.loads(row["payload_json"]))

    def get_pending_database_update_for_document(
        self,
        document_id: str,
    ) -> Optional[DatabaseUpdateProposal]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT payload_json
                FROM database_updates
                WHERE document_id = ? AND status = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (document_id, DatabaseUpdateStatus.PENDING_APPROVAL.value),
            ).fetchone()
        if row is None:
            return None
        return deserialize_database_update_proposal(json.loads(row["payload_json"]))

    def list_database_updates(
        self,
        *,
        status: Optional[DatabaseUpdateStatus] = None,
        limit: int = 200,
    ) -> list[DatabaseUpdateProposal]:
        safe_limit = max(1, min(limit, 1000))
        with self._lock:
            if status is None:
                rows = self._conn.execute(
                    """
                    SELECT payload_json
                    FROM database_updates
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (safe_limit,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT payload_json
                    FROM database_updates
                    WHERE status = ?
                    ORDER BY updated_at DESC
                    LIMIT ?
                    """,
                    (status.value, safe_limit),
                ).fetchall()
        return [
            deserialize_database_update_proposal(json.loads(row["payload_json"]))
            for row in rows
        ]

    def get_document_bytes(self, document_id: str) -> Optional[bytes]:
        path = self._resolve_safe_document_bytes_path(document_id)
        if not path.exists():
            return None
        with self._lock:
            return path.read_bytes()

    def has_document_bytes(self, document_id: str) -> bool:
        path = self._resolve_safe_document_bytes_path(document_id)
        return path.exists()

    def _resolve_safe_document_bytes_path(self, document_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", document_id):
            raise ValueError("Invalid document_id for byte storage")
        staging_root = self.staging_dir.resolve()
        candidate = (staging_root / document_id).resolve()
        if candidate.parent != staging_root:
            raise ValueError("Invalid document_id for byte storage")
        return candidate

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

    def count_database_updates(
        self,
        *,
        status: Optional[DatabaseUpdateStatus] = None,
    ) -> int:
        with self._lock:
            if status is None:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS count FROM database_updates"
                ).fetchone()
            else:
                row = self._conn.execute(
                    "SELECT COUNT(*) AS count FROM database_updates WHERE status = ?",
                    (status.value,),
                ).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_learning_evidence(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM learning_evidence"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_applied_updates(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM applied_updates"
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
