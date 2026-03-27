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
from datetime import datetime, date, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger("email-intel.cosmos")


# ---------------------------------------------------------------------------
# Container configuration
# ---------------------------------------------------------------------------

CONTAINERS = {
    "triage_results": {"partition_key": "/partition_date"},
    "draft_responses": {"partition_key": "/message_id"},
    "event_drafts": {"partition_key": "/source_message_id"},
    "documents": {"partition_key": "/document_id"},
    "corrections": {"partition_key": "/original_type"},
    "brief_items": {"partition_key": "/item_kind"},
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
                self._database = self._client.create_database_if_not_exists(DATABASE_NAME)
                for name, config in CONTAINERS.items():
                    self._containers[name] = self._database.create_container_if_not_exists(
                        id=name,
                        partition_key=PartitionKey(path=config["partition_key"]),
                    )
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

    def query_triage_activity(
        self,
        *,
        days: int = 90,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        container = self._container("triage_results")

        if self._using_memory:
            items = [
                item
                for item in container.query_items(query="SELECT * FROM c")
                if str(item.get("saved_at", "")) >= since
            ]
            items.sort(key=lambda item: str(item.get("saved_at", "")), reverse=True)
            return items[:limit]

        return list(
            container.query_items(
                query=(
                    "SELECT TOP @limit * FROM c "
                    "WHERE c.saved_at >= @since "
                    "ORDER BY c.saved_at DESC"
                ),
                parameters=[
                    {"name": "@limit", "value": limit},
                    {"name": "@since", "value": since},
                ],
                enable_cross_partition_query=True,
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

    def find_draft_by_id(self, draft_id: str) -> Optional[dict[str, Any]]:
        container = self._container("draft_responses")
        if self._using_memory:
            for item in container.query_items(query="SELECT * FROM c"):
                if item.get("id") == draft_id or item.get("draft_id") == draft_id:
                    return item
            return None

        results = list(
            container.query_items(
                query="SELECT TOP 1 * FROM c WHERE c.id = @draft_id OR c.draft_id = @draft_id",
                parameters=[{"name": "@draft_id", "value": draft_id}],
                enable_cross_partition_query=True,
            )
        )
        return results[0] if results else None

    def get_drafts_for_message(self, message_id: str) -> list[dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.message_id = @mid"
        params = [{"name": "@mid", "value": message_id}]
        return list(
            self._container("draft_responses").query_items(
                query=query, parameters=params, partition_key=message_id
            )
        )

    def query_drafts(
        self,
        *,
        limit: int = 200,
        sent_only: bool = False,
    ) -> list[dict[str, Any]]:
        container = self._container("draft_responses")

        if self._using_memory:
            items = list(container.query_items(query="SELECT * FROM c"))
            if sent_only:
                items = [item for item in items if item.get("sent")]
            items.sort(
                key=lambda item: str(item.get("sent_at") or item.get("saved_at", "")),
                reverse=True,
            )
            return items[:limit]

        query = "SELECT TOP @limit * FROM c"
        parameters = [{"name": "@limit", "value": limit}]
        if sent_only:
            query += " WHERE c.sent = true"
        query += " ORDER BY c.saved_at DESC"
        return list(
            container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            )
        )

    def count_drafts(self) -> int:
        return self._count_items("draft_responses")

    def delete_draft(self, draft_id: str, message_id: str) -> None:
        self._container("draft_responses").delete_item(draft_id, partition_key=message_id)

    # -- Event drafts -------------------------------------------------------

    def save_event_draft(self, draft_data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in draft_data:
            draft_data["id"] = draft_data.get("event_draft_id", str(uuid.uuid4()))
        draft_data["event_draft_id"] = draft_data.get("event_draft_id", draft_data["id"])
        draft_data["saved_at"] = datetime.now(timezone.utc).isoformat()
        return self._container("event_drafts").upsert_item(draft_data)

    def get_event_draft(self, event_draft_id: str, source_message_id: str) -> Optional[dict[str, Any]]:
        try:
            return self._container("event_drafts").read_item(
                event_draft_id, partition_key=source_message_id
            )
        except (KeyError, Exception):
            return None

    def find_event_draft_by_id(self, event_draft_id: str) -> Optional[dict[str, Any]]:
        container = self._container("event_drafts")
        if self._using_memory:
            for item in container.query_items(query="SELECT * FROM c"):
                if item.get("id") == event_draft_id or item.get("event_draft_id") == event_draft_id:
                    return item
            return None

        results = list(
            container.query_items(
                query="SELECT TOP 1 * FROM c WHERE c.id = @draft_id OR c.event_draft_id = @draft_id",
                parameters=[{"name": "@draft_id", "value": event_draft_id}],
                enable_cross_partition_query=True,
            )
        )
        return results[0] if results else None

    def get_event_drafts_for_message(self, source_message_id: str) -> list[dict[str, Any]]:
        query = "SELECT * FROM c WHERE c.source_message_id = @mid"
        params = [{"name": "@mid", "value": source_message_id}]
        return list(
            self._container("event_drafts").query_items(
                query=query, parameters=params, partition_key=source_message_id
            )
        )

    def query_event_drafts(
        self,
        *,
        limit: int = 200,
        approved_only: bool = False,
    ) -> list[dict[str, Any]]:
        container = self._container("event_drafts")

        if self._using_memory:
            items = list(container.query_items(query="SELECT * FROM c"))
            if approved_only:
                items = [item for item in items if item.get("approved")]
            items.sort(
                key=lambda item: str(item.get("approved_at") or item.get("saved_at", "")),
                reverse=True,
            )
            return items[:limit]

        query = "SELECT TOP @limit * FROM c"
        parameters = [{"name": "@limit", "value": limit}]
        if approved_only:
            query += " WHERE c.approved = true"
        query += " ORDER BY c.saved_at DESC"
        return list(
            container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True,
            )
        )

    def count_event_drafts(self) -> int:
        return self._count_items("event_drafts")

    def delete_event_draft(self, event_draft_id: str, source_message_id: str) -> None:
        self._container("event_drafts").delete_item(event_draft_id, partition_key=source_message_id)

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

    # -- Morning Brief carry-over items ------------------------------------

    def save_brief_item(self, item_data: dict[str, Any]) -> dict[str, Any]:
        if "id" not in item_data:
            item_data["id"] = item_data.get("item_id", str(uuid.uuid4()))
        item_data["item_id"] = item_data.get("item_id", item_data["id"])
        item_data["item_kind"] = str(item_data.get("item_kind", "follow_up") or "follow_up")
        item_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        return self._container("brief_items").upsert_item(item_data)

    def find_brief_item_by_id(self, item_id: str) -> Optional[dict[str, Any]]:
        container = self._container("brief_items")
        if self._using_memory:
            for item in container.query_items(query="SELECT * FROM c"):
                if item.get("id") == item_id or item.get("item_id") == item_id:
                    return item
            return None

        try:
            results = list(
                container.query_items(
                    query="SELECT TOP 1 * FROM c WHERE c.id = @item_id OR c.item_id = @item_id",
                    parameters=[{"name": "@item_id", "value": item_id}],
                    enable_cross_partition_query=True,
                )
            )
        except Exception:
            return None
        return results[0] if results else None

    def query_brief_items(
        self,
        *,
        states: Optional[list[str]] = None,
        item_kinds: Optional[list[str]] = None,
        since_days: int = 14,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        container = self._container("brief_items")
        normalized_states = [str(state).strip().lower() for state in states or [] if str(state).strip()]
        normalized_kinds = [str(kind).strip() for kind in item_kinds or [] if str(kind).strip()]
        since = (datetime.now(timezone.utc) - timedelta(days=since_days)).isoformat()

        if self._using_memory:
            items = list(container.query_items(query="SELECT * FROM c"))
            filtered: list[dict[str, Any]] = []
            for item in items:
                item_state = str(item.get("state", "open")).lower()
                item_kind = str(item.get("item_kind", ""))
                last_seen = str(item.get("last_seen_at", ""))
                if normalized_states and item_state not in normalized_states:
                    continue
                if normalized_kinds and item_kind not in normalized_kinds:
                    continue
                if last_seen and last_seen < since:
                    continue
                filtered.append(item)
            filtered.sort(key=lambda item: str(item.get("last_seen_at", "")), reverse=True)
            return filtered[:limit]

        query_parts = [
            "SELECT TOP @limit * FROM c WHERE c.last_seen_at >= @since",
        ]
        parameters: list[dict[str, Any]] = [
            {"name": "@limit", "value": limit},
            {"name": "@since", "value": since},
        ]
        if normalized_states:
            state_clauses: list[str] = []
            for index, state in enumerate(normalized_states):
                param_name = f"@state{index}"
                state_clauses.append(f"c.state = {param_name}")
                parameters.append({"name": param_name, "value": state})
            query_parts.append(f"AND ({' OR '.join(state_clauses)})")
        if normalized_kinds:
            kind_clauses: list[str] = []
            for index, kind in enumerate(normalized_kinds):
                param_name = f"@kind{index}"
                kind_clauses.append(f"c.item_kind = {param_name}")
                parameters.append({"name": param_name, "value": kind})
            query_parts.append(f"AND ({' OR '.join(kind_clauses)})")
        query_parts.append("ORDER BY c.last_seen_at DESC")

        try:
            return list(
                container.query_items(
                    query=" ".join(query_parts),
                    parameters=parameters,
                    enable_cross_partition_query=True,
                )
            )
        except Exception:
            return []

    def count_brief_items(self) -> int:
        return self._count_items("brief_items")

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
