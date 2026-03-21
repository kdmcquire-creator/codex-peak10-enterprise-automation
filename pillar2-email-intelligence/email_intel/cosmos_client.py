"""
Cosmos DB persistence layer for the Email Intelligence system.

Provides async-compatible data access for:
  - Triage results (partitioned by date)
  - Draft responses (partitioned by message_id)
  - Document classifications (partitioned by document_id)
  - Correction logs (partitioned by original_type)

Uses the Azure Cosmos DB Python SDK v4 with session consistency.
Falls back to in-memory storage when COSMOS_CONNECTION_STRING is not set
(local dev / testing).
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, date, timezone
from typing import Any, Optional

logger = logging.getLogger("email-intel.cosmos")


# ---------------------------------------------------------------------------
# Container configuration
# ---------------------------------------------------------------------------

CONTAINERS = {
    "triage_results": {"partition_key": "/partition_date"},
    "draft_responses": {"partition_key": "/message_id"},
    "documents": {"partition_key": "/document_id"},
    "corrections": {"partition_key": "/original_type"},
}

DATABASE_NAME = "peak10-email-intelligence"


# ---------------------------------------------------------------------------
# In-memory fallback for local dev / testing
# ---------------------------------------------------------------------------

class InMemoryContainer:
    """Dict-backed container that mimics Cosmos DB operations."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._items: dict[str, dict[str, Any]] = {}

    def upsert_item(self, item: dict[str, Any]) -> dict[str, Any]:
        item_id = item.get("id", str(uuid.uuid4()))
        item["id"] = item_id
        self._items[item_id] = item
        return item

    def read_item(self, item: str, partition_key: str) -> dict[str, Any]:
        if item in self._items:
            return self._items[item]
        raise KeyError(f"Item {item} not found in {self.name}")

    def query_items(
        self,
        query: str,
        parameters: Optional[list[dict[str, Any]]] = None,
        partition_key: Optional[str] = None,
        enable_cross_partition_query: bool = False,
    ) -> list[dict[str, Any]]:
        """Simplified query — returns all items (filtering done in caller)."""
        return list(self._items.values())

    def delete_item(self, item: str, partition_key: str) -> None:
        self._items.pop(item, None)

    @property
    def item_count(self) -> int:
        return len(self._items)


class InMemoryDatabase:
    """Dict-backed database that mimics Cosmos DB."""

    def __init__(self) -> None:
        self._containers: dict[str, InMemoryContainer] = {}

    def get_container(self, name: str) -> InMemoryContainer:
        if name not in self._containers:
            self._containers[name] = InMemoryContainer(name)
        return self._containers[name]


# ---------------------------------------------------------------------------
# CosmosDataStore — unified data access layer
# ---------------------------------------------------------------------------

class CosmosDataStore:
    """
    Data access layer for Cosmos DB.

    Automatically falls back to in-memory storage when no connection string
    is configured (local development, unit tests).
    """

    def __init__(self, connection_string: Optional[str] = None) -> None:
        self._connection_string = connection_string or os.environ.get(
            "COSMOS_CONNECTION_STRING"
        )
        self._client = None
        self._database = None
        self._containers: dict[str, Any] = {}
        self._using_memory = False

        if self._connection_string:
            try:
                from azure.cosmos import CosmosClient, PartitionKey

                self._client = CosmosClient.from_connection_string(
                    self._connection_string
                )
                self._database = self._client.get_database_client(DATABASE_NAME)
                for name in CONTAINERS:
                    self._containers[name] = self._database.get_container_client(name)
                logger.info("Connected to Cosmos DB: %s", DATABASE_NAME)
            except Exception as e:
                logger.warning("Cosmos DB init failed, using in-memory: %s", e)
                self._init_memory()
        else:
            logger.info("No COSMOS_CONNECTION_STRING — using in-memory storage")
            self._init_memory()

    def _init_memory(self) -> None:
        self._using_memory = True
        mem_db = InMemoryDatabase()
        for name in CONTAINERS:
            self._containers[name] = mem_db.get_container(name)

    @property
    def is_connected(self) -> bool:
        return not self._using_memory

    @property
    def storage_backend(self) -> str:
        return "cosmos" if self.is_connected else "in_memory"

    # -- Container accessors ------------------------------------------------

    def _container(self, name: str) -> Any:
        return self._containers[name]

    # -- Triage results -----------------------------------------------------

    def save_triage_result(self, triage_data: dict[str, Any]) -> dict[str, Any]:
        """Persist a triage result. Adds id and partition_date if missing."""
        if "id" not in triage_data:
            triage_data["id"] = triage_data.get("message_id", str(uuid.uuid4()))
        if "partition_date" not in triage_data:
            triage_data["partition_date"] = date.today().isoformat()
        triage_data["saved_at"] = datetime.now(timezone.utc).isoformat()
        return self._container("triage_results").upsert_item(triage_data)

    def get_triage_result(self, message_id: str) -> Optional[dict[str, Any]]:
        try:
            return self._container("triage_results").read_item(
                message_id, partition_key=date.today().isoformat()
            )
        except (KeyError, Exception):
            return None

    def query_triage_results(
        self, partition_date: Optional[str] = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        pk = partition_date or date.today().isoformat()
        query = "SELECT TOP @limit * FROM c WHERE c.partition_date = @pk ORDER BY c.saved_at DESC"
        params = [
            {"name": "@limit", "value": limit},
            {"name": "@pk", "value": pk},
        ]
        return list(
            self._container("triage_results").query_items(
                query=query, parameters=params, partition_key=pk
            )
        )

    def count_triage_results(self) -> int:
        return self._count_items("triage_results")

    # -- Draft responses ----------------------------------------------------

    def save_draft(self, draft_data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in draft_data:
            draft_data["id"] = draft_data.get("draft_id", str(uuid.uuid4()))
        draft_data["saved_at"] = datetime.now(timezone.utc).isoformat()
        return self._container("draft_responses").upsert_item(draft_data)

    def get_draft(self, draft_id: str, message_id: str) -> Optional[dict[str, Any]]:
        try:
            return self._container("draft_responses").read_item(
                draft_id, partition_key=message_id
            )
        except (KeyError, Exception):
            return None

    def get_drafts_for_message(self, message_id: str) -> list[dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.message_id = @mid"
        params = [{"name": "@mid", "value": message_id}]
        return list(
            self._container("draft_responses").query_items(
                query=query, parameters=params, partition_key=message_id
            )
        )

    def count_drafts(self) -> int:
        return self._count_items("draft_responses")

    def delete_draft(self, draft_id: str, message_id: str) -> None:
        self._container("draft_responses").delete_item(draft_id, partition_key=message_id)

    # -- Document classifications -------------------------------------------

    def save_document(self, doc_data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in doc_data:
            doc_data["id"] = doc_data.get("document_id", str(uuid.uuid4()))
        doc_data["saved_at"] = datetime.now(timezone.utc).isoformat()
        return self._container("documents").upsert_item(doc_data)

    def get_document(self, document_id: str) -> Optional[dict[str, Any]]:
        try:
            return self._container("documents").read_item(
                document_id, partition_key=document_id
            )
        except (KeyError, Exception):
            return None

    def count_documents(self) -> int:
        return self._count_items("documents")

    # -- Correction logs ----------------------------------------------------

    def save_correction(self, correction_data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in correction_data:
            correction_data["id"] = correction_data.get(
                "correction_id", str(uuid.uuid4())
            )
        correction_data["saved_at"] = datetime.now(timezone.utc).isoformat()
        return self._container("corrections").upsert_item(correction_data)

    def get_corrections_for_type(
        self, original_type: str
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.original_type = @ot"
        params = [{"name": "@ot", "value": original_type}]
        return list(
            self._container("corrections").query_items(
                query=query,
                parameters=params,
                partition_key=original_type,
            )
        )

    def count_corrections(self) -> int:
        return self._count_items("corrections")

    def _count_items(self, name: str) -> int:
        container = self._container(name)
        if self._using_memory:
            return container.item_count

        try:
            results = list(
                container.query_items(
                    query="SELECT VALUE COUNT(1) FROM c",
                    enable_cross_partition_query=True,
                )
            )
        except Exception:
            return 0

        if not results:
            return 0
        return int(results[0])


# ---------------------------------------------------------------------------
# Module-level singleton (lazy init)
# ---------------------------------------------------------------------------

_store: Optional[CosmosDataStore] = None


def get_store() -> CosmosDataStore:
    """Return the module-level CosmosDataStore singleton."""
    global _store
    if _store is None:
        _store = CosmosDataStore()
    return _store


def reset_store() -> None:
    """Reset the singleton (for testing)."""
    global _store
    _store = None
