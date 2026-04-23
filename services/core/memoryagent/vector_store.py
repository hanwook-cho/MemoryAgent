"""ChromaDB persistent vector store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import chromadb


def _distance_to_score(distance: float) -> float:
    """Map Chroma distance to a rough [0,1] relevance score."""
    return float(max(0.0, min(1.0, 1.0 / (1.0 + distance))))


class VectorStore:
    def __init__(self, persist_dir: Path) -> None:
        persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        self._col = self._client.get_or_create_collection(
            name="memory_chunks",
            metadata={"hnsw:space": "cosine"},
        )

    def count(self) -> int:
        return int(self._col.count())

    def add(
        self,
        *,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict[str, Any]],
    ) -> None:
        self._col.add(
            ids=ids,
            embeddings=embeddings,
            documents=documents,
            metadatas=metadatas,
        )

    def query(self, embedding: list[float], n_results: int = 8) -> list[dict[str, Any]]:
        if self._col.count() == 0:
            return []
        return self.query_with_filters(embedding, n_results=n_results, where=None)

    def query_with_filters(
        self,
        embedding: list[float],
        *,
        n_results: int = 8,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self._col.count() == 0:
            return []
        res = self._col.query(
            query_embeddings=[embedding],
            n_results=min(n_results, max(1, self._col.count())),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        out: list[dict[str, Any]] = []
        ids_list = res.get("ids") or [[]]
        docs_list = res.get("documents") or [[]]
        meta_list = res.get("metadatas") or [[]]
        dist_list = res.get("distances") or [[]]
        for i, chunk_id in enumerate(ids_list[0]):
            doc_text = (docs_list[0][i] if docs_list[0] else "") or ""
            meta = (meta_list[0][i] if meta_list[0] else {}) or {}
            dist = (dist_list[0][i] if dist_list[0] else 0.0) or 0.0
            out.append(
                {
                    "chunk_id": chunk_id,
                    "document": doc_text,
                    "metadata": meta,
                    "score": _distance_to_score(float(dist)),
                }
            )
        return out

    def delete_by_document_id(self, document_id: str) -> None:
        """Remove all chunks whose metadata `document_id` matches."""
        if self._col.count() == 0:
            return
        self._col.delete(where={"document_id": {"$eq": document_id}})
