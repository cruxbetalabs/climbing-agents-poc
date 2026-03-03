"""
sqlite-vec vector store implementation.

Stores embeddings alongside the existing climbing.db tables using the sqlite-vec
extension (a native SQLite extension for KNN vector search).

Install:
    pip install sqlite-vec

The extension must be installed as a Python package for the load() call below to
work. On Apple Silicon you may need:
    pip install sqlite-vec --no-binary sqlite-vec

Extension docs: https://alexgarcia.xyz/sqlite-vec/python.html

Embedding model: OpenAI text-embedding-3-small (1536 dims)
This is called automatically on upsert and search — no caller-side setup needed.
"""

from __future__ import annotations
import json
import logging
import sqlite3
from typing import Any

from memory.vector_store import VectorMatch

log = logging.getLogger(__name__)

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIM = 1536


class SqliteVecStore:
    """
    VectorStore backed by sqlite-vec.

    Creates a vec0 virtual table in the existing climbing.db file:

        CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
            id         TEXT PRIMARY KEY,
            source     TEXT NOT NULL DEFAULT '',
            text       TEXT NOT NULL DEFAULT '',
            embedding  FLOAT[1536]
        );

    The `source` column mirrors the metadata["source"] key and enables fast
    pre-filter before the KNN step (e.g. source = 'climb_logs').

    Schema is created automatically on first instantiation.
    """

    def __init__(self, db_path: str, openai_client: Any) -> None:
        """
        db_path:       path to the existing SQLite database (climbing.db)
        openai_client: an AsyncOpenAI client instance — must support
                       .embeddings.create(model=..., input=[...])
        """
        self.db_path = db_path
        self._openai = openai_client
        self._init_table()

    # ── Connection helpers ─────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        import sqlite_vec

        conn = sqlite3.connect(self.db_path)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)  # re-disable for safety
        return conn

    def _init_table(self) -> None:
        try:
            conn = self._connect()
            conn.execute(
                f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
                    id        TEXT PRIMARY KEY,
                    source    TEXT NOT NULL DEFAULT '',
                    text      TEXT NOT NULL DEFAULT '',
                    embedding FLOAT[{_EMBEDDING_DIM}]
                )
            """
            )
            conn.commit()
            conn.close()
            log.debug("sqlite-vec vec_items table ready")
        except Exception as exc:
            # Extension not yet installed — log a clear warning, don't crash startup
            log.warning(
                "sqlite-vec not available (%s). "
                "Semantic search will be skipped until 'pip install sqlite-vec' is run.",
                exc,
            )

    # ── Embedding ──────────────────────────────────────────────────────────────

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        """Call the OpenAI embeddings API. Returns one vector per input text."""
        response = await self._openai.embeddings.create(
            model=_EMBEDDING_MODEL,
            input=texts,
        )
        return [item.embedding for item in response.data]

    # ── VectorStore interface ──────────────────────────────────────────────────

    async def upsert(
        self,
        ids: list[str],
        texts: list[str],
        metadata: list[dict[str, Any]] | None = None,
    ) -> None:
        """Embed texts and upsert into vec_items. Replaces existing rows with same id."""
        if not ids:
            return
        metadata = metadata or [{} for _ in ids]
        embeddings = await self._embed(texts)

        conn = None
        try:
            conn = self._connect()
            for id_, text, meta, emb in zip(ids, texts, metadata, embeddings):
                source = meta.get("source", "")
                # vec0 virtual tables don't support INSERT OR REPLACE —
                # delete the existing row first, then insert fresh.
                conn.execute("DELETE FROM vec_items WHERE id = ?", (id_,))
                conn.execute(
                    """INSERT INTO vec_items (id, source, text, embedding)
                       VALUES (?, ?, ?, ?)""",
                    (id_, source, text, json.dumps(emb)),
                )
            conn.commit()
        except Exception as exc:
            log.warning("sqlite-vec upsert failed: %s", exc)
        finally:
            if conn is not None:
                conn.close()

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        """KNN search. Optionally pre-filter by source metadata key."""
        conn = None
        try:
            [query_emb] = await self._embed([query])
            query_blob = json.dumps(query_emb)
            conn = self._connect()

            source_filter = (filter or {}).get("source")
            if source_filter:
                sql = """
                    SELECT id, source, text, distance
                    FROM vec_items
                    WHERE embedding MATCH ?
                      AND k = ?
                      AND source = ?
                    ORDER BY distance
                """
                params: list[Any] = [query_blob, top_k, source_filter]
            else:
                sql = """
                    SELECT id, source, text, distance
                    FROM vec_items
                    WHERE embedding MATCH ?
                      AND k = ?
                    ORDER BY distance
                """
                params = [query_blob, top_k]

            rows = conn.execute(sql, params).fetchall()
            return [
                VectorMatch(
                    id=row[0],
                    text=row[2],
                    # sqlite-vec returns L2 distance; convert to a rough similarity
                    score=max(0.0, 1.0 - float(row[3])),
                    metadata={"source": row[1]},
                )
                for row in rows
            ]
        except Exception as exc:
            log.warning("sqlite-vec search failed: %s", exc)
            return []
        finally:
            if conn is not None:
                conn.close()

    async def delete(self, ids: list[str]) -> None:
        """Delete entries by id."""
        if not ids:
            return
        conn = None
        try:
            conn = self._connect()
            placeholders = ",".join("?" * len(ids))
            conn.execute(f"DELETE FROM vec_items WHERE id IN ({placeholders})", ids)
            conn.commit()
        except Exception as exc:
            log.warning("sqlite-vec delete failed: %s", exc)
        finally:
            if conn is not None:
                conn.close()
