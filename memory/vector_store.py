"""
Vector store abstraction.

Defines the VectorStore protocol: a text-in / matches-out interface for
semantic similarity search. Concrete implementations swap in different backends
(sqlite-vec, chromadb, etc.) without changing any call sites.

Usage:
    from memory import SqliteVecStore, VectorMatch

    store: VectorStore = SqliteVecStore(db_path, openai_async_client)

    await store.upsert(
        ids=["log-abc123"],
        texts=["felt pumped on the V7 overhang, slipped on the heel hook"],
        metadata=[{"source": "climb_logs"}],
    )
    matches: list[VectorMatch] = await store.search("heel hook", top_k=3)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class VectorMatch:
    """A single result from a similarity search."""

    id: str
    text: str
    score: float  # cosine similarity — higher is more similar (0–1)
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class VectorStore(Protocol):
    """
    Protocol for all vector store backends.

    All methods are async. Implementations handle embedding internally —
    callers always pass raw text strings, never raw vectors.
    """

    async def upsert(
        self,
        ids: list[str],
        texts: list[str],
        metadata: list[dict[str, Any]] | None = None,
    ) -> None:
        """Embed texts and store (or replace) vectors keyed by id."""
        ...

    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter: dict[str, Any] | None = None,
    ) -> list[VectorMatch]:
        """Embed query and return the top_k most similar stored entries.

        filter: optional dict passed to the backend. Supported keys depend on
        the implementation — e.g. {"source": "climb_logs"} to scope the search.
        """
        ...

    async def delete(self, ids: list[str]) -> None:
        """Remove entries by id."""
        ...
