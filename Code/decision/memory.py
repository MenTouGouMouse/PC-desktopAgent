"""记忆系统模块：双数据库架构，ChromaDB 负责语义向量检索，SQLite 负责结构化操作记录存储。"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Literal

import chromadb
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = "memory.db"
DEFAULT_CHROMA_PATH = "./chroma_data"
COLLECTION_NAME = "operation_records"
TABLE_NAME = "operations"


@dataclass
class OperationRecord:
    """单条操作记录，同时写入 SQLite（结构化）和 ChromaDB（向量嵌入）。"""

    timestamp: str                              # ISO 8601
    action_type: str                            # click / type_text / open_application / detect
    description: str                            # 自然语言描述，用于向量嵌入
    coordinates: tuple[int, int] | None
    result: Literal["success", "failure"]
    metadata: dict = field(default_factory=dict)
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))


class MemorySystem:
    """双数据库记忆系统。

    - ChromaDB：存储操作描述的向量嵌入，支持语义相似度检索。
    - SQLite：存储结构化操作记录，支持按时间倒序查询。
    """

    def __init__(
        self,
        db_path: str = DEFAULT_DB_PATH,
        chroma_path: str = DEFAULT_CHROMA_PATH,
        chroma_client: chromadb.ClientAPI | None = None,
    ) -> None:
        self._db_path = db_path
        self._chroma_path = chroma_path
        self._sqlite_conn = self._init_sqlite()
        if chroma_client is not None:
            self._collection = self._init_chroma_with_client(chroma_client)
        else:
            self._collection = self._init_chroma()
        logger.info("MemorySystem initialized (sqlite=%s, chroma=%s)", db_path, chroma_path)

    # ------------------------------------------------------------------
    # Initialisation helpers
    # ------------------------------------------------------------------

    def _init_sqlite(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
                record_id   TEXT PRIMARY KEY,
                timestamp   TEXT NOT NULL,
                action_type TEXT NOT NULL,
                description TEXT NOT NULL,
                coordinates TEXT,
                result      TEXT NOT NULL,
                metadata    TEXT NOT NULL DEFAULT '{{}}'
            )
            """
        )
        conn.commit()
        logger.debug("SQLite table '%s' ready at %s", TABLE_NAME, self._db_path)
        return conn

    def _init_chroma(self) -> chromadb.Collection:
        client = chromadb.PersistentClient(path=self._chroma_path)
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=DefaultEmbeddingFunction(),  # type: ignore[arg-type]
        )
        logger.debug("ChromaDB collection '%s' ready at %s", COLLECTION_NAME, self._chroma_path)
        return collection

    def _init_chroma_with_client(self, client: chromadb.ClientAPI) -> chromadb.Collection:
        """Inject a custom ChromaDB client (used in tests to avoid network calls)."""
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
        )
        return collection

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(self, operation: OperationRecord) -> None:
        """将操作记录写入 SQLite，并将其向量嵌入写入 ChromaDB。"""
        self._store_sqlite(operation)
        self._store_chroma(operation)
        logger.info(
            "Stored operation record id=%s action=%s result=%s",
            operation.record_id,
            operation.action_type,
            operation.result,
        )

    def search_similar(self, description: str, top_k: int = 5) -> list[OperationRecord]:
        """在 ChromaDB 中语义检索与 description 最相似的历史操作。"""
        try:
            results = self._collection.query(
                query_texts=[description],
                n_results=top_k,
                include=["documents", "metadatas"],
            )
        except Exception as exc:
            logger.error("ChromaDB query failed: %s", exc)
            return []

        ids: list[str] = results.get("ids", [[]])[0]
        if not ids:
            return []

        records = self._fetch_by_ids(ids)
        logger.debug("search_similar('%s', top_k=%d) → %d results", description, top_k, len(records))
        return records

    def get_recent(self, limit: int = 20) -> list[OperationRecord]:
        """从 SQLite 按时间倒序获取最近的结构化操作记录。"""
        try:
            cursor = self._sqlite_conn.execute(
                f"SELECT record_id, timestamp, action_type, description, coordinates, result, metadata "
                f"FROM {TABLE_NAME} ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
            rows = cursor.fetchall()
        except sqlite3.Error as exc:
            logger.error("SQLite get_recent failed: %s", exc)
            return []

        records = [self._row_to_record(row) for row in rows]
        logger.debug("get_recent(limit=%d) → %d records", limit, len(records))
        return records

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _store_sqlite(self, operation: OperationRecord) -> None:
        coords_json = json.dumps(list(operation.coordinates)) if operation.coordinates is not None else None
        metadata_json = json.dumps(operation.metadata)
        try:
            self._sqlite_conn.execute(
                f"INSERT OR REPLACE INTO {TABLE_NAME} "
                f"(record_id, timestamp, action_type, description, coordinates, result, metadata) "
                f"VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    operation.record_id,
                    operation.timestamp,
                    operation.action_type,
                    operation.description,
                    coords_json,
                    operation.result,
                    metadata_json,
                ),
            )
            self._sqlite_conn.commit()
        except sqlite3.Error as exc:
            logger.error("SQLite store failed for record_id=%s: %s", operation.record_id, exc)
            raise

    def _store_chroma(self, operation: OperationRecord) -> None:
        try:
            self._collection.upsert(
                ids=[operation.record_id],
                documents=[operation.description],
                metadatas=[{"record_id": operation.record_id}],
            )
        except Exception as exc:
            logger.error("ChromaDB store failed for record_id=%s: %s", operation.record_id, exc)
            raise

    def _fetch_by_ids(self, ids: list[str]) -> list[OperationRecord]:
        if not ids:
            return []
        placeholders = ",".join("?" * len(ids))
        try:
            cursor = self._sqlite_conn.execute(
                f"SELECT record_id, timestamp, action_type, description, coordinates, result, metadata "
                f"FROM {TABLE_NAME} WHERE record_id IN ({placeholders})",
                ids,
            )
            rows = cursor.fetchall()
        except sqlite3.Error as exc:
            logger.error("SQLite fetch_by_ids failed: %s", exc)
            return []
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: tuple) -> OperationRecord:
        record_id, timestamp, action_type, description, coords_json, result, metadata_json = row
        coordinates: tuple[int, int] | None = None
        if coords_json is not None:
            parsed = json.loads(coords_json)
            coordinates = (int(parsed[0]), int(parsed[1]))
        metadata: dict = json.loads(metadata_json) if metadata_json else {}
        return OperationRecord(
            record_id=record_id,
            timestamp=timestamp,
            action_type=action_type,
            description=description,
            coordinates=coordinates,
            result=result,
            metadata=metadata,
        )
