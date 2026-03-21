"""Persistence for Expense Hub transactions and claims."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import BankTransaction, ExpenseClaim
from .serialization import (
    deserialize_expense_claim,
    deserialize_transaction,
    serialize_expense_claim,
    serialize_transaction,
)


DEFAULT_DB_NAME = "expense-hub.db"


def _default_db_path() -> str:
    configured = os.environ.get("EXPENSE_HUB_DB_PATH")
    if configured:
        return configured

    data_dir = Path(os.getcwd()) / ".data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return str(data_dir / DEFAULT_DB_NAME)


def _transaction_payload(txn: BankTransaction) -> dict[str, object]:
    payload = serialize_transaction(txn)
    payload["plaid_transaction_id"] = txn.plaid_transaction_id
    payload["account_id"] = txn.account_id
    payload["pending"] = txn.pending
    payload["receipt_ref"] = txn.receipt_ref
    return payload


def _claim_payload(claim: ExpenseClaim) -> dict[str, object]:
    payload = serialize_expense_claim(claim)
    payload["_source_transaction_ids"] = list(claim._source_transaction_ids)
    return payload


class ExpenseHubRepository:
    """SQLite-backed persistence for transactions and claims."""

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
                CREATE TABLE IF NOT EXISTS transactions (
                    transaction_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def save_transaction(self, txn: BankTransaction) -> BankTransaction:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO transactions (transaction_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(transaction_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    txn.transaction_id,
                    json.dumps(_transaction_payload(txn)),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return txn

    def get_transaction(self, transaction_id: str) -> Optional[BankTransaction]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM transactions WHERE transaction_id = ?",
                (transaction_id,),
            ).fetchone()
        if row is None:
            return None
        return deserialize_transaction(json.loads(row["payload_json"]))

    def save_claim(self, claim: ExpenseClaim) -> ExpenseClaim:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO claims (claim_id, payload_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(claim_id) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    claim.claim_id,
                    json.dumps(_claim_payload(claim)),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        return claim

    def get_claim(self, claim_id: str) -> Optional[ExpenseClaim]:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM claims WHERE claim_id = ?",
                (claim_id,),
            ).fetchone()
        if row is None:
            return None
        return deserialize_expense_claim(json.loads(row["payload_json"]))

    def count_transactions(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM transactions"
            ).fetchone()
        return int(row["count"]) if row is not None else 0

    def count_claims(self) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS count FROM claims"
            ).fetchone()
        return int(row["count"]) if row is not None else 0


_repository: Optional[ExpenseHubRepository] = None


def get_repository() -> ExpenseHubRepository:
    global _repository
    if _repository is None:
        _repository = ExpenseHubRepository()
    return _repository


def reset_repository() -> None:
    global _repository
    _repository = None
