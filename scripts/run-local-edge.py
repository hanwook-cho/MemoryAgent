#!/usr/bin/env python3
"""Run a local in-memory Edge Node for MP1 development and smoke tests."""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _reexec_with_core_venv() -> None:
    """Use the core venv so script deps (`fastapi`, `uvicorn`) are available."""
    if os.environ.get("MEMORYAGENT_SKIP_VENV_REEXEC") == "1":
        return
    venv_py = _repo_root() / "services" / "core" / ".venv" / "bin" / "python"
    if venv_py.is_file() and Path(sys.executable) != venv_py:
        os.environ["MEMORYAGENT_SKIP_VENV_REEXEC"] = "1"
        os.execv(str(venv_py), [str(venv_py), *sys.argv])

_reexec_with_core_venv()

import uvicorn
from fastapi import FastAPI, HTTPException, Request


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
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Missing Authorization: Bearer <token>.",
                    "retryable": False,
                    "details": {},
                }
            },
        )
    if auth[7:].strip() != token:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Bearer token does not match local edge token.",
                    "retryable": False,
                    "details": {},
                }
            },
        )


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in text.replace("-", " ").replace("_", " ").split() if t}


def _score(query: str, text: str) -> float:
    q = _tokens(query)
    if not q:
        return 0.0
    t = _tokens(text)
    overlap = len(q & t) / max(1, len(q))
    if query.lower() in text.lower():
        overlap += 0.5
    return min(1.0, overlap)


def _snippet(text: str, query: str, limit: int = 500) -> str:
    low = text.lower()
    q = query.lower().strip()
    if q and q in low:
        start = max(0, low.index(q) - 80)
    else:
        start = 0
    return text[start : start + limit]


def create_app(*, token: str | None, node_id: str) -> FastAPI:
    app = FastAPI(title="MemoryAgent Local Edge Node", version="0.1-dev")
    docs: list[dict[str, Any]] = []

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
        return {
            "queue_depth": 0,
            "active_jobs": 0,
            "last_indexed_at": docs[-1]["indexed_at"] if docs else None,
            "last_error": None,
            "documents": len({d["document_id"] for d in docs}),
            "chunks": len(docs),
        }

    @app.post("/ingest")
    async def ingest(request: Request) -> dict[str, Any]:
        _require_bearer(request, token)
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(status_code=400, detail=_error("VALIDATION", "body must be an object"))
        kind = str(body.get("kind") or "").strip()
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        if kind == "memory":
            text = str(body.get("text") or "").strip()
            if not text:
                raise HTTPException(status_code=400, detail=_error("VALIDATION", "text is required"))
            doc_id = str(uuid.uuid4())
            docs.append(
                {
                    "document_id": doc_id,
                    "chunk_id": f"{doc_id}:0",
                    "text": text,
                    "source": str(body.get("source") or "edge_memory"),
                    "source_kind": "memory",
                    "tags": list(body.get("tags") or []),
                    "indexed_at": now,
                }
            )
            return {"status": "accepted", "job_id": doc_id}
        if kind == "file":
            raw_path = str(body.get("path") or "").strip()
            if not raw_path:
                raise HTTPException(status_code=400, detail=_error("VALIDATION", "path is required"))
            p = Path(raw_path).expanduser()
            if not p.is_file():
                raise HTTPException(status_code=400, detail=_error("VALIDATION", f"file not found: {raw_path}"))
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                raise HTTPException(status_code=500, detail=_error("INTERNAL", str(e))) from e
            doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, p.resolve().as_uri()))
            docs.append(
                {
                    "document_id": doc_id,
                    "chunk_id": f"{doc_id}:0",
                    "text": text,
                    "source": str(p.resolve()),
                    "source_kind": "file",
                    "tags": [],
                    "indexed_at": now,
                }
            )
            return {"status": "accepted", "job_id": doc_id}
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
        limit = int(body.get("limit") or 8)
        filters = body.get("filters") if isinstance(body.get("filters"), dict) else {}
        source_kind = filters.get("source_kind")
        path_prefix = filters.get("path_prefix")

        ranked: list[tuple[float, dict[str, Any]]] = []
        for d in docs:
            if source_kind and d["source_kind"] != source_kind:
                continue
            if path_prefix and not str(d["source"]).startswith(str(path_prefix)):
                continue
            s = _score(query, d["text"])
            if s <= 0:
                continue
            ranked.append((s, d))
        ranked.sort(key=lambda x: x[0], reverse=True)
        rows = [
            {
                "chunk_id": d["chunk_id"],
                "document_id": d["document_id"],
                "snippet": _snippet(d["text"], query),
                "score": round(score, 4),
                "source": d["source"],
                "source_kind": d["source_kind"],
                "indexed_at": d["indexed_at"],
                "backend_id": "local_dev_edge",
            }
            for score, d in ranked[: max(1, limit)]
        ]
        return {
            "results": rows,
            "meta": {
                "query_ms": int((time.perf_counter() - started) * 1000),
                "backend_id": "local_dev_edge",
                "total_candidates": len(ranked),
            },
        }

    @app.post("/control/reindex")
    async def reindex(request: Request) -> dict[str, Any]:
        _require_bearer(request, token)
        # This dev edge is in-memory and synchronous; clearing is the least surprising reset.
        docs.clear()
        return {"status": "accepted", "job_id": str(uuid.uuid4())}

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
        help="Data dir to read secrets/bearer.token from.",
    )
    ap.add_argument(
        "--token",
        default=None,
        help="Bearer token override. Defaults to data dir token.",
    )
    ap.add_argument(
        "--no-auth",
        action="store_true",
        help="Disable bearer checking for local experiments.",
    )
    ap.add_argument("--node-id", default="local-dev-edge")
    args = ap.parse_args()

    token = None if args.no_auth else (args.token or _load_bearer_token(Path(args.data_dir)))
    if token is None and not args.no_auth:
        p = _bearer_token_path(Path(args.data_dir))
        raise SystemExit(
            f"Bearer token not found at {p}. Start the host once or pass --token/--no-auth."
        )

    print(f"==> Starting local Edge Node at http://{args.host}:{args.port}")
    if token:
        print("    Auth: bearer token loaded (same token host sends to Edge Node)")
    else:
        print("    Auth: disabled (--no-auth)")
    print("    Data: in-memory only; restart clears ingested edge docs")
    uvicorn.run(create_app(token=token, node_id=args.node_id), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
