"""MP1 smoke: host talks to a real local mock Edge Node over HTTP."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from memoryagent.app import create_app
from memoryagent.embeddings import DeterministicEmbedder
from memoryagent.llm_client import FakeLlm
from memoryagent.rag_service import RagService
from memoryagent.secrets import bearer_token_path
from memoryagent.vector_store import VectorStore
from memoryagent.watcher import NullFileWatcher


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class MockEdgeServer:
    def __init__(self) -> None:
        self.port = _free_local_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.retrieve_calls: list[dict[str, Any]] = []
        self.ingest_calls: list[dict[str, Any]] = []
        self.auth_headers: list[str | None] = []

        app = FastAPI()

        @app.get("/health")
        async def health(request: Request) -> dict[str, Any]:
            self.auth_headers.append(request.headers.get("authorization"))
            return {
                "status": "ok",
                "node_id": "mock-edge",
                "capabilities": {
                    "retrieve": True,
                    "ingest": True,
                    "reindex": False,
                },
                "version": "0.1-test",
            }

        @app.post("/retrieve")
        async def retrieve(request: Request) -> dict[str, Any]:
            self.auth_headers.append(request.headers.get("authorization"))
            body = await request.json()
            self.retrieve_calls.append(body)
            return {
                "results": [
                    {
                        "chunk_id": "edge-smoke:0",
                        "document_id": "edge-smoke-doc",
                        "snippet": f"edge smoke result for {body.get('query', '')}",
                        "score": 0.91,
                        "source": "memory",
                        "source_kind": "memory",
                        "indexed_at": "2026-04-24T00:00:00Z",
                        "backend_id": "mock_edge",
                    }
                ],
                "meta": {
                    "query_ms": 1,
                    "backend_id": "mock_edge",
                    "total_candidates": 1,
                },
            }

        @app.post("/ingest")
        async def ingest(request: Request) -> dict[str, Any]:
            self.auth_headers.append(request.headers.get("authorization"))
            body = await request.json()
            self.ingest_calls.append(body)
            return {"status": "accepted", "job_id": f"mock-{len(self.ingest_calls)}"}

        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self.port, log_level="warning")
        )
        self._thread = threading.Thread(target=self._server.run, daemon=True)

    def start(self) -> None:
        self._thread.start()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                r = httpx.get(f"{self.base_url}/health", timeout=0.2)
                if r.status_code == 200:
                    self.auth_headers.clear()
                    return
            except httpx.HTTPError:
                time.sleep(0.05)
        raise RuntimeError("mock edge did not start")

    def stop(self) -> None:
        self._server.should_exit = True
        self._thread.join(timeout=5.0)


def _auth(data_dir: Path) -> dict[str, str]:
    token = bearer_token_path(data_dir).read_text().strip()
    return {"Authorization": f"Bearer {token}"}


def test_host_edge_smoke_against_local_mock_edge(
    data_dir: Path, monkeypatch
) -> None:
    async def fake_ollama(_: str) -> bool:
        return False

    import memoryagent.app as app_mod

    monkeypatch.setattr(app_mod, "ollama_reachable", fake_ollama)

    edge = MockEdgeServer()
    edge.start()
    try:
        chroma_dir = data_dir / "store" / "vector" / "chroma"
        rag = RagService(
            data_dir=data_dir,
            store=VectorStore(chroma_dir),
            embedder=DeterministicEmbedder(),
            llm=FakeLlm(reply="Saved."),
        )
        static = data_dir / "no_web"
        static.mkdir()
        client = TestClient(
            create_app(
                data_dir=data_dir,
                static_dir=static,
                rag_service=rag,
                file_watcher=NullFileWatcher(),
            )
        )
        h = _auth(data_dir)

        r_cfg = client.patch(
            "/api/v1/config",
            headers=h,
            json={
                "deployment_mode": "host_edge",
                "edge_base_url": edge.base_url,
            },
        )
        assert r_cfg.status_code == 200

        r_health = client.get("/api/v1/health")
        assert r_health.status_code == 200
        dep = r_health.json()["deployment"]
        assert dep["mode"] == "host_edge"
        assert dep["edge_reachable"] is True
        assert dep["degraded"] is False

        r_search = client.get(
            "/api/v1/memory/search",
            headers=h,
            params={"q": "mock edge smoke"},
        )
        assert r_search.status_code == 200
        assert r_search.json()["results"][0]["snippet"] == (
            "edge smoke result for mock edge smoke"
        )
        assert edge.retrieve_calls[-1]["query"] == "mock edge smoke"

        r_memory = client.post(
            "/api/v1/memory/entries",
            headers=h,
            json={
                "text": "mock edge smoke memory body",
                "tags": ["mp1"],
                "source": "smoke",
            },
        )
        assert r_memory.status_code == 201
        assert edge.ingest_calls[-1] == {
            "kind": "memory",
            "text": "mock edge smoke memory body",
            "tags": ["mp1"],
            "source": "smoke",
        }

        chat_secret = "mock edge smoke chat save"
        r_chat = client.post(
            "/api/v1/chat",
            headers=h,
            json={
                "messages": [
                    {"role": "user", "content": f"Remember that {chat_secret}"}
                ]
            },
        )
        assert r_chat.status_code == 200
        assert edge.ingest_calls[-1]["text"] == chat_secret
        assert edge.ingest_calls[-1]["source"] == "chat"

        expected_auth = h["Authorization"]
        assert expected_auth in edge.auth_headers
    finally:
        edge.stop()
