"""Unit tests for decision/memory.py — MemorySystem and OperationRecord."""

from __future__ import annotations

import os
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import List
from unittest.mock import MagicMock

import chromadb
import pytest
from chromadb import EmbeddingFunction, Embeddings

from decision.memory import MemorySystem, OperationRecord


# ---------------------------------------------------------------------------
# Fake embedding function (avoids network download of sentence-transformers)
# ---------------------------------------------------------------------------

class FakeEmbeddingFunction(EmbeddingFunction):
    """Returns a deterministic fixed-length embedding based on text hash."""

    def __init__(self) -> None:
        pass

    def __call__(self, input: List[str]) -> Embeddings:  # noqa: A002
        return [[float(hash(t) % 1000) / 1000.0] * 64 for t in input]


def _make_chroma_client() -> chromadb.ClientAPI:
    return chromadb.EphemeralClient()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(
    description: str = "click the OK button",
    action_type: str = "click",
    result: str = "success",
    coordinates: tuple[int, int] | None = (100, 200),
    metadata: dict | None = None,
) -> OperationRecord:
    return OperationRecord(
        timestamp=datetime.now(timezone.utc).isoformat(),
        action_type=action_type,
        description=description,
        coordinates=coordinates,
        result=result,
        metadata=metadata or {},
    )


class IsolatedMemory:
    """Context manager: MemorySystem with ephemeral ChromaDB + temp SQLite."""

    def __enter__(self) -> MemorySystem:
        self._tmp = tempfile.mkdtemp()
        db_path = os.path.join(self._tmp, "test_memory.db")
        chroma_client = _make_chroma_client()
        # Patch the collection to use our fake embedding function
        self.mem = MemorySystem(db_path=db_path, chroma_client=chroma_client)
        # Replace the collection's embedding function with the fake one
        self.mem._collection._embedding_function = FakeEmbeddingFunction()
        return self.mem

    def __exit__(self, *_) -> None:
        try:
            self.mem._sqlite_conn.close()
        except Exception:
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# OperationRecord dataclass
# ---------------------------------------------------------------------------

class TestOperationRecord:
    def test_default_record_id_is_unique(self):
        r1 = _make_record()
        r2 = _make_record()
        assert r1.record_id != r2.record_id

    def test_fields_stored_correctly(self):
        rec = OperationRecord(
            timestamp="2024-01-01T00:00:00+00:00",
            action_type="type_text",
            description="type hello",
            coordinates=None,
            result="failure",
            metadata={"strategy": "ocr"},
        )
        assert rec.timestamp == "2024-01-01T00:00:00+00:00"
        assert rec.action_type == "type_text"
        assert rec.coordinates is None
        assert rec.result == "failure"
        assert rec.metadata == {"strategy": "ocr"}


# ---------------------------------------------------------------------------
# MemorySystem.store + get_recent
# ---------------------------------------------------------------------------

class TestMemorySystemStore:
    def test_store_and_get_recent_returns_record(self):
        with IsolatedMemory() as mem:
            rec = _make_record()
            mem.store(rec)
            recent = mem.get_recent(limit=10)
            assert len(recent) == 1
            assert recent[0].record_id == rec.record_id
            assert recent[0].description == rec.description

    def test_get_recent_respects_limit(self):
        with IsolatedMemory() as mem:
            for i in range(5):
                mem.store(_make_record(description=f"action {i}"))
            recent = mem.get_recent(limit=3)
            assert len(recent) == 3

    def test_get_recent_returns_newest_first(self):
        with IsolatedMemory() as mem:
            ts_old = "2024-01-01T00:00:00+00:00"
            ts_new = "2024-06-01T00:00:00+00:00"
            old_rec = OperationRecord(
                timestamp=ts_old, action_type="click", description="old",
                coordinates=None, result="success",
            )
            new_rec = OperationRecord(
                timestamp=ts_new, action_type="click", description="new",
                coordinates=None, result="success",
            )
            mem.store(old_rec)
            mem.store(new_rec)
            recent = mem.get_recent(limit=2)
            assert recent[0].timestamp == ts_new
            assert recent[1].timestamp == ts_old

    def test_store_record_with_none_coordinates(self):
        with IsolatedMemory() as mem:
            rec = _make_record(coordinates=None)
            mem.store(rec)
            recent = mem.get_recent()
            assert recent[0].coordinates is None

    def test_store_record_with_coordinates_roundtrip(self):
        with IsolatedMemory() as mem:
            rec = _make_record(coordinates=(320, 480))
            mem.store(rec)
            recent = mem.get_recent()
            assert recent[0].coordinates == (320, 480)

    def test_store_metadata_roundtrip(self):
        with IsolatedMemory() as mem:
            meta = {"strategy": "qwen_vl", "confidence": 0.95}
            rec = _make_record(metadata=meta)
            mem.store(rec)
            recent = mem.get_recent()
            assert recent[0].metadata == meta

    def test_get_recent_empty_returns_empty_list(self):
        with IsolatedMemory() as mem:
            assert mem.get_recent() == []


# ---------------------------------------------------------------------------
# MemorySystem.search_similar
# ---------------------------------------------------------------------------

class TestMemorySystemSearchSimilar:
    def test_search_similar_returns_list(self):
        with IsolatedMemory() as mem:
            mem.store(_make_record(description="open the browser"))
            mem.store(_make_record(description="click the submit button"))
            results = mem.search_similar("open browser", top_k=2)
            assert isinstance(results, list)

    def test_search_similar_top_k_limits_results(self):
        with IsolatedMemory() as mem:
            for i in range(5):
                mem.store(_make_record(description=f"perform action number {i}"))
            results = mem.search_similar("perform action", top_k=2)
            assert len(results) <= 2

    def test_search_similar_returns_operation_records(self):
        with IsolatedMemory() as mem:
            mem.store(_make_record(description="click the login button"))
            results = mem.search_similar("login button", top_k=1)
            for r in results:
                assert isinstance(r, OperationRecord)

    def test_search_similar_empty_db_returns_empty(self):
        with IsolatedMemory() as mem:
            results = mem.search_similar("anything", top_k=5)
            assert results == []

    def test_search_similar_chroma_error_returns_empty(self):
        with IsolatedMemory() as mem:
            mem._collection.query = MagicMock(side_effect=Exception("chroma down"))
            results = mem.search_similar("test", top_k=3)
            assert results == []


# ---------------------------------------------------------------------------
# SQLite error handling
# ---------------------------------------------------------------------------

class TestMemorySystemErrorHandling:
    def test_get_recent_sqlite_error_returns_empty(self):
        with IsolatedMemory() as mem:
            mem._sqlite_conn.close()
            results = mem.get_recent()
            assert results == []

    def test_store_sqlite_error_raises(self):
        with IsolatedMemory() as mem:
            mem._sqlite_conn.close()
            rec = _make_record()
            with pytest.raises(Exception):
                mem.store(rec)


# ---------------------------------------------------------------------------
# Mock-based tests using unittest.mock.patch
# (Requirements: 14.1 ChromaDB semantic search, 14.2 SQLite structured storage)
# ---------------------------------------------------------------------------

class TestMemorySystemWithMocks:
    """Verify store/search_similar/get_recent using unittest.mock.patch."""

    def _make_memory_with_mocks(self) -> tuple[MemorySystem, MagicMock, MagicMock]:
        """Create a MemorySystem with both SQLite connection and ChromaDB collection mocked."""
        from unittest.mock import patch, MagicMock

        mock_conn = MagicMock(spec=sqlite3.Connection)
        mock_collection = MagicMock()

        with patch("sqlite3.connect", return_value=mock_conn):
            # Suppress table creation side-effects
            mock_conn.execute.return_value = MagicMock()
            mock_conn.commit.return_value = None

            chroma_client = MagicMock()
            chroma_client.get_or_create_collection.return_value = mock_collection

            mem = MemorySystem(db_path=":memory:", chroma_client=chroma_client)

        return mem, mock_conn, mock_collection

    # ------------------------------------------------------------------
    # store() — writes to both backends
    # ------------------------------------------------------------------

    def test_store_writes_to_sqlite(self) -> None:
        """store() must call sqlite execute + commit (Requirement 14.2)."""
        mem, mock_conn, _ = self._make_memory_with_mocks()
        rec = _make_record()
        mock_conn.reset_mock()

        mem.store(rec)

        mock_conn.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    def test_store_writes_to_chromadb(self) -> None:
        """store() must call collection.upsert (Requirement 14.1)."""
        mem, _, mock_collection = self._make_memory_with_mocks()
        rec = _make_record()

        mem.store(rec)

        mock_collection.upsert.assert_called_once()
        call_kwargs = mock_collection.upsert.call_args
        assert rec.record_id in call_kwargs.kwargs.get("ids", call_kwargs.args[0] if call_kwargs.args else [])

    def test_store_passes_description_to_chromadb(self) -> None:
        """store() must pass the description as the document for embedding (Requirement 14.1)."""
        mem, _, mock_collection = self._make_memory_with_mocks()
        rec = _make_record(description="open the settings panel")

        mem.store(rec)

        call_kwargs = mock_collection.upsert.call_args
        documents = call_kwargs.kwargs.get("documents") or call_kwargs.args[1]
        assert rec.description in documents

    # ------------------------------------------------------------------
    # search_similar() — queries ChromaDB
    # ------------------------------------------------------------------

    def test_search_similar_calls_chromadb_query(self) -> None:
        """search_similar() must call collection.query (Requirement 14.1)."""
        mem, mock_conn, mock_collection = self._make_memory_with_mocks()

        # Simulate empty result from ChromaDB
        mock_collection.query.return_value = {"ids": [[]], "documents": [[]], "metadatas": [[]]}

        mem.search_similar("click the button", top_k=3)

        mock_collection.query.assert_called_once()
        call_kwargs = mock_collection.query.call_args
        assert call_kwargs.kwargs.get("n_results") == 3 or call_kwargs.args[1] == 3

    def test_search_similar_fetches_records_from_sqlite(self) -> None:
        """search_similar() must query SQLite for the IDs returned by ChromaDB (Requirement 14.2)."""
        mem, mock_conn, mock_collection = self._make_memory_with_mocks()
        fake_id = "abc-123"

        mock_collection.query.return_value = {
            "ids": [[fake_id]],
            "documents": [["some doc"]],
            "metadatas": [[{"record_id": fake_id}]],
        }
        # Return a matching row from SQLite
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            (fake_id, "2024-01-01T00:00:00+00:00", "click", "click the button", None, "success", "{}")
        ]
        mock_conn.execute.return_value = mock_cursor

        results = mem.search_similar("click the button", top_k=1)

        mock_conn.execute.assert_called()
        assert len(results) == 1
        assert results[0].record_id == fake_id

    def test_search_similar_returns_empty_on_chroma_error(self) -> None:
        """search_similar() must return [] when ChromaDB raises (Requirement 14.1)."""
        mem, _, mock_collection = self._make_memory_with_mocks()
        mock_collection.query.side_effect = RuntimeError("chroma unavailable")

        results = mem.search_similar("anything", top_k=5)

        assert results == []

    # ------------------------------------------------------------------
    # get_recent() — queries SQLite in reverse chronological order
    # ------------------------------------------------------------------

    def test_get_recent_queries_sqlite_with_order_desc(self) -> None:
        """get_recent() must issue an ORDER BY timestamp DESC query (Requirement 14.2)."""
        mem, mock_conn, _ = self._make_memory_with_mocks()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        mem.get_recent(limit=10)

        mock_conn.execute.assert_called()
        sql_arg: str = mock_conn.execute.call_args.args[0]
        assert "ORDER BY timestamp DESC" in sql_arg
        assert "LIMIT" in sql_arg

    def test_get_recent_passes_limit_to_sqlite(self) -> None:
        """get_recent() must pass the limit value as a query parameter (Requirement 14.2)."""
        mem, mock_conn, _ = self._make_memory_with_mocks()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = []
        mock_conn.execute.return_value = mock_cursor

        mem.get_recent(limit=7)

        call_args = mock_conn.execute.call_args
        params = call_args.args[1] if len(call_args.args) > 1 else call_args.kwargs.get("parameters", ())
        assert 7 in params

    def test_get_recent_returns_operation_records(self) -> None:
        """get_recent() must deserialise SQLite rows into OperationRecord instances (Requirement 14.2)."""
        mem, mock_conn, _ = self._make_memory_with_mocks()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [
            ("id-1", "2024-03-01T12:00:00+00:00", "click", "click OK", "[100, 200]", "success", "{}"),
            ("id-2", "2024-02-01T12:00:00+00:00", "type_text", "type hello", None, "failure", "{}"),
        ]
        mock_conn.execute.return_value = mock_cursor

        results = mem.get_recent(limit=20)

        assert len(results) == 2
        assert all(isinstance(r, OperationRecord) for r in results)
        assert results[0].record_id == "id-1"
        assert results[0].coordinates == (100, 200)
        assert results[1].coordinates is None

    def test_get_recent_returns_empty_on_sqlite_error(self) -> None:
        """get_recent() must return [] when SQLite raises (Requirement 14.2)."""
        mem, mock_conn, _ = self._make_memory_with_mocks()
        mock_conn.execute.side_effect = sqlite3.Error("db locked")

        results = mem.get_recent()

        assert results == []
