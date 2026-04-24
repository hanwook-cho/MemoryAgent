#!/usr/bin/env python3
"""Run a local persistent Edge Node for MP1 development and smoke tests."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _reexec_with_core_venv() -> None:
    """Use the core venv so script deps (`fastapi`, `uvicorn`, `chromadb`) are available."""
    if os.environ.get("MEMORYAGENT_SKIP_VENV_REEXEC") == "1":
        return
    venv_py = _repo_root() / "services" / "core" / ".venv" / "bin" / "python"
    if venv_py.is_file() and Path(sys.executable) != venv_py:
        os.environ["MEMORYAGENT_SKIP_VENV_REEXEC"] = "1"
        os.execv(str(venv_py), [str(venv_py), *sys.argv])


_reexec_with_core_venv()

import uvicorn
from fastapi import FastAPI, HTTPException, Request

from memoryagent.embeddings import DeterministicEmbedder, OllamaEmbedder
from memoryagent.llm_client import FakeLlm
from memoryagent.rag_service import RagService, SearchFilters, _meta_matches_filters
from memoryagent.vector_store import VectorStore


def _bearer_token_path(data_dir: Path) -> Path:
    return data_dir / "secrets" / "bearer.token"


def _load_bearer_token(data_dir: Path) -> str | None:
    p = _bearer_token_path(data_dir)
    if not p.is_file():
        return None
    return p.read_text(encoding="utf-8").strip() or None


def _require_bearer(request: Request, token: str | None) -> None:
    if token is None:
        return
    auth = request.headers.get("authorization")
    if not auth or not auth.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail=_error("UNAUTHORIZED", "Missing Authorization: Bearer <token>."),
        )
    if auth[7:].strip() != token:
        raise HTTPException(
            status_code=401,
            detail=_error("UNAUTHORIZED", "Bearer token does not match local edge token."),
        )


def _parse_datetime(raw: Any) -> datetime | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=_error("VALIDATION", f"invalid ISO datetime: {s}"),
        ) from None


def _filters_from_node_payload(body: dict[str, Any]) -> SearchFilters:
    raw = body.get("filters")
    filters = raw if isinstance(raw, dict) else {}
    return SearchFilters(
        source_kind=str(filters["source_kind"]) if filters.get("source_kind") else None,
        path_prefix=str(filters["path_prefix"]) if filters.get("path_prefix") else None,
        indexed_after=_parse_datetime(filters.get("indexed_after")),
        indexed_before=_parse_datetime(filters.get("indexed_before")),
    )


@dataclass(slots=True)
class EdgeState:
    data_dir: Path
    store: VectorStore
    rag: RagService
    last_error: str | None = None


def create_app(*, token: str | None, node_id: str, state: EdgeState) -> FastAPI:
    app = FastAPI(title="MemoryAgent Local Edge Node", version="0.1-dev")

    @app.get("/health")
    async def health(request: Request) -> dict[str, Any]:
        _require_bearer(request, token)
        return {
            "status": "ok",
            "node_id": node_id,
            "capabilities": {
                "retrieve": True,
                "ingest": True,
                "reindex": True,
            },
            "version": "0.1-dev",
        }

    @app.get("/index/status")
    async def index_status(request: Request) -> dict[str, Any]:
        _require_bearer(request, token)
        stats = state.rag.index_stats()
        return {
            "queue_depth": 0,
            "active_jobs": 0,
            "last_indexed_at": None,
            "last_error": state.last_error,
            "documents": stats["documents"],
            "chunks": stats["chunks"],
        }

    @app.post("/ingest")
    async def ingest(request: Request) -> dict[str, Any]:
        _require_bearer(request, token)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail=_error("VALIDATION", "body must be an object"))
        kind = str(body.get("kind") or "").strip()
        try:
            if kind == "memory":
                text = str(body.get("text") or "").strip()
                if not text:
                    raise HTTPException(status_code=400, detail=_error("VALIDATION", "text is required"))
                tags = body.get("tags")
                tag_list = [str(x) for x in tags] if isinstance(tags, list) else []
                source = str(body.get("source") or "edge_memory")
                doc_id, job_id = await state.rag.ingest_memory(
                    text,
                    tags=tag_list,
                    source=source,
                )
                state.last_error = None
                return {"status": "accepted", "job_id": job_id, "document_id": doc_id}
            if kind == "file":
                raw_path = str(body.get("path") or "").strip()
                if not raw_path:
                    raise HTTPException(status_code=400, detail=_error("VALIDATION", "path is required"))
                doc_id = await state.rag.ingest_file_path(Path(raw_path))
                state.last_error = None
                return {"status": "accepted", "job_id": doc_id, "document_id": doc_id}
        except HTTPException:
            raise
        except Exception as e:
            state.last_error = str(e)
            raise HTTPException(status_code=500, detail=_error("INTERNAL", str(e))) from e
        raise HTTPException(status_code=400, detail=_error("VALIDATION", "kind must be file or memory"))

    @app.post("/retrieve")
    async def retrieve(request: Request) -> dict[str, Any]:
        _require_bearer(request, token)
        started = time.perf_counter()
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail=_error("VALIDATION", "body must be an object"))
        query = str(body.get("query") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail=_error("VALIDATION", "query is required"))
        try:
            limit = max(1, int(body.get("limit") or 8))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail=_error("VALIDATION", "limit must be an integer")) from None
        filters = _filters_from_node_payload(body)
        qemb = await state.rag._embedder.embed(query)
        raw_hits = state.store.query_with_filters(
            qemb,
            n_results=min(limit * 4, max(1, state.store.count())),
            where={"source_kind": {"$eq": filters.source_kind}}
            if filters.source_kind
            else None,
        )
        rows: list[dict[str, Any]] = []
        for row in raw_hits:
            meta = row.get("metadata") or {}
            if not _meta_matches_filters(meta, filters):
                continue
            rows.append(
                {
                    "chunk_id": str(row.get("chunk_id", "")),
                    "document_id": str(meta.get("document_id", "")),
                    "snippet": str(row.get("document") or "")[:500],
                    "score": float(row.get("score", 0.0)),
                    "source": str(meta.get("source", "")),
                    "source_kind": str(meta.get("source_kind", "")),
                    "indexed_at": str(meta.get("indexed_at", "")),
                    "backend_id": "local_dev_edge",
                }
            )
            if len(rows) >= limit:
                break
        return {
            "results": rows,
            "meta": {
                "query_ms": int((time.perf_counter() - started) * 1000),
                "backend_id": "local_dev_edge",
                "total_candidates": len(rows),
            },
        }

    @app.post("/control/reindex")
    async def reindex(request: Request) -> dict[str, Any]:
        _require_bearer(request, token)
        state.rag.reset_search_index()
        state.last_error = None
        job_id = str(uuid.uuid4())
        return {"status": "accepted", "job_id": job_id}

    return app


def _error(code: str, message: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": False,
            "details": {},
        }
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9876)
    ap.add_argument(
        "--data-dir",
        default=str(_repo_root() / ".memoryagent"),
        help="Host data dir to read secrets/bearer.token from.",
    )
    ap.add_argument(
        "--edge-data-dir",
        default=str(_repo_root() / ".memoryagent-edge"),
        help="Persistent local edge data dir (default: repo .memoryagent-edge).",
    )
    ap.add_argument(
        "--token",
        default=None,
        help="Bearer token override. Defaults to host data dir token.",
    )
    ap.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable bearer checking for local experiments.",
    )
    ap.add_argument("--node-id", default="local-dev-edge")
    ap.add_argument(
        "--ollama-base-url",
        default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
    )
    ap.add_argument(
        "--embed-model",
        default=os.environ.get("EMBED_MODEL", "nomic-embed-text"),
    )
    ap.add_argument(
        "--deterministic-embedder",
        action="store_true",
        help="Use deterministic local embeddings instead of Ollama (dev/tests only).",
    )
    args = ap.parse_args()

    token = None if args.no_auth else (args.token or _load_bearer_token(Path(args.data_dir)))
    if token is None and not args.no_auth:
        p = _bearer_token_path(Path(args.data_dir))
        raise SystemExit(
            f"Bearer token not found at {p}. Start the host once or pass --token/--no-auth."
        )

    edge_data_dir = Path(args.edge_data_dir).expanduser().resolve()
    store = VectorStore(edge_data_dir / "store" / "vector" / "chroma")
    embedder = (
        DeterministicEmbedder()
        if args.deterministic_embedder
        else OllamaEmbedder(args.ollama_base_url, args.embed_model)
    )
    rag = RagService(
        data_dir=edge_data_dir,
        store=store,
        embedder=embedder,
        llm=FakeLlm(reply="local edge"),
    )
    state = EdgeState(data_dir=edge_data_dir, store=store, rag=rag)

    print(f"==> Starting local Edge Node at http://{args.host}:{args.port}")
    if token:
        print("    Auth: bearer token loaded (same token host sends to Edge Node)")
    else:
        print("    Auth: disabled (--no-auth)")
    print(f"    Data: persistent Chroma edge index at {edge_data_dir}")
    if args.deterministic_embedder:
        print("    Embeddings: deterministic local stub")
    else:
        print(f"    Embeddings: Ollama {args.embed_model} at {args.ollama_base_url}")
    uvicorn.run(
        create_app(token=token, node_id=args.node_id, state=state),
        host=args.host,
        port=args.port,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
