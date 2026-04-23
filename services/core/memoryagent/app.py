"""FastAPI application: `/api/v1/*` API + static web at `/`."""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from memoryagent import __version__
from memoryagent.auth_http import BearerChecker
from memoryagent.config_store import load_config, save_config
from memoryagent.embeddings import DeterministicEmbedder, Embedder, OllamaEmbedder
from memoryagent.folder_picker import pick_folder_macos
from memoryagent.llm_client import FakeLlm, LlmClient, OllamaLlm
from memoryagent.logging_setup import configure_logging
from memoryagent.mirror import MIRROR_FILES, ensure_mirror_file, validate_mirror_content
from memoryagent.ollama import ollama_reachable
from memoryagent.paths import default_data_dir, web_dist
from memoryagent.rag_service import RagService, SearchFilters
from memoryagent.calendar_bridge import CalendarPermissionDenied, run_create_event
from memoryagent.tool_registry import build_default_registry
from memoryagent.schemas import (
    CalendarEventCreateRequest,
    CalendarEventCreateResponse,
    ChatRequest,
    ConfigPatchRequest,
    MemoryEntryRequest,
    MemoryEntryResponse,
    MirrorDocumentResponse,
    MirrorListItem,
    MirrorListResponse,
    MirrorPutRequest,
    MirrorPutResponse,
    SearchResponse,
    ToolInvokeRequest,
    ToolListItem,
    ToolListResponse,
)
from memoryagent.watcher import FileWatcher, NullFileWatcher
from memoryagent.secrets import load_or_create_bearer_token
from memoryagent.vector_store import VectorStore

logger = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

_MIRROR_TITLES: dict[str, str] = {
    "user": "USER memory",
    "soul": "Soul / identity",
}


def create_app(
    data_dir: Path | None = None,
    *,
    static_dir: Path | None = None,
    rag_service: RagService | None = None,
    file_watcher: FileWatcher | NullFileWatcher | None = None,
) -> FastAPI:
    data_dir = data_dir or default_data_dir()
    configure_logging(data_dir)
    static_dir = static_dir or web_dist()
    cfg = load_config(data_dir)
    bearer_token = load_or_create_bearer_token(data_dir)

    chroma_dir = data_dir / "store" / "vector" / "chroma"
    if rag_service is None:
        rag = RagService(
            data_dir=data_dir,
            store=VectorStore(chroma_dir),
            embedder=OllamaEmbedder(cfg.ollama_base_url, cfg.embed_model),
            llm=OllamaLlm(cfg.ollama_base_url, cfg.chat_model),
        )
    else:
        rag = rag_service

    watcher: FileWatcher | NullFileWatcher = (
        file_watcher if file_watcher is not None else FileWatcher(data_dir=data_dir, rag=rag)
    )
    tools_registry = build_default_registry(data_dir)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        logger.warning(
            "MemoryAgent API bearer token (use Authorization: Bearer …): %s",
            bearer_token,
        )
        (data_dir / "store" / "vector").mkdir(parents=True, exist_ok=True)
        (data_dir / "mirror").mkdir(parents=True, exist_ok=True)
        (data_dir / "logs").mkdir(parents=True, exist_ok=True)
        loop = asyncio.get_running_loop()
        watcher.start(loop, load_config(data_dir))
        for mid in MIRROR_FILES:
            mp = ensure_mirror_file(data_dir, mid)
            try:
                await rag.ingest_mirror_document(mp, mirror_key=mid)
            except Exception:
                logger.exception("mirror ingest at startup failed for %s", mid)
        yield
        watcher.stop()

    app = FastAPI(
        title="MemoryAgent API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
        lifespan=lifespan,
    )

    @app.get(f"{API_PREFIX}/health")
    async def health() -> dict[str, Any]:
        c = load_config(data_dir)
        reachable = await ollama_reachable(c.ollama_base_url)
        stats = rag.index_stats()
        return {
            "status": "ok",
            "version": __version__,
            "llm": {
                "backend": "ollama",
                "reachable": reachable,
                "model": c.chat_model,
            },
            "index": {
                "documents": stats["documents"],
                "chunks": stats["chunks"],
            },
        }

    checker = BearerChecker(bearer_token)
    router = APIRouter(prefix=API_PREFIX, dependencies=[Depends(checker)])

    @router.get("/config")
    async def get_config() -> dict[str, Any]:
        c = load_config(data_dir)
        return {
            "host": c.host,
            "port": c.port,
            "chat_model": c.chat_model,
            "embed_model": c.embed_model,
            "ollama_base_url": c.ollama_base_url,
            "watched_roots": list(c.watched_roots),
            "watch_ignore_globs": list(c.watch_ignore_globs),
            "watch_debounce_seconds": c.watch_debounce_seconds,
            "ui": {
                "chat_welcome_dismissed": False,
                "chat_welcome_version": "3",
            },
        }

    @router.patch("/config")
    async def patch_config(body: ConfigPatchRequest) -> dict[str, Any]:
        c = load_config(data_dir)
        if body.watched_roots is not None:
            for raw in body.watched_roots:
                root = Path(raw).expanduser()
                if not root.is_dir():
                    raise HTTPException(
                        status_code=400,
                        detail={
                            "error": {
                                "code": "VALIDATION",
                                "message": f"Watched path is not an existing directory: {raw}",
                            }
                        },
                    )
            c.watched_roots = list(body.watched_roots)
        if body.watch_ignore_globs is not None:
            c.watch_ignore_globs = list(body.watch_ignore_globs)
        if body.watch_debounce_seconds is not None:
            c.watch_debounce_seconds = float(body.watch_debounce_seconds)
        save_config(data_dir, c)
        watcher.restart(asyncio.get_running_loop(), load_config(data_dir))
        return await get_config()

    @router.post("/config/pick-folder")
    async def pick_folder() -> dict[str, str]:
        """
        Open native folder picker (macOS) and return selected directory.
        UI can append this to watched_roots and PATCH /config.
        """
        try:
            path = pick_folder_macos()
        except RuntimeError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "VALIDATION",
                        "message": str(e),
                    }
                },
            ) from e
        return {"path": path}

    @router.get("/mirror", response_model=MirrorListResponse)
    async def list_mirrors() -> MirrorListResponse:
        items: list[MirrorListItem] = []
        for mid in MIRROR_FILES:
            ensure_mirror_file(data_dir, mid)
            items.append(
                MirrorListItem(
                    id=mid,  # type: ignore[arg-type]
                    filename=MIRROR_FILES[mid],
                    title=_MIRROR_TITLES[mid],
                )
            )
        return MirrorListResponse(mirrors=items)

    @router.get("/mirror/{mirror_id}", response_model=MirrorDocumentResponse)
    async def get_mirror_document(mirror_id: str) -> MirrorDocumentResponse:
        if mirror_id not in MIRROR_FILES:
            raise HTTPException(status_code=404, detail="Unknown mirror id.")
        path = ensure_mirror_file(data_dir, mirror_id)
        content = path.read_text(encoding="utf-8")
        doc_id = str(uuid.uuid5(uuid.NAMESPACE_URL, path.resolve().as_uri()))
        return MirrorDocumentResponse(
            mirror_id=mirror_id,  # type: ignore[arg-type]
            filename=MIRROR_FILES[mirror_id],
            path=str(path.resolve()),
            content=content,
            document_id=doc_id,
        )

    @router.put("/mirror/{mirror_id}", response_model=MirrorPutResponse)
    async def put_mirror_document(mirror_id: str, body: MirrorPutRequest) -> MirrorPutResponse:
        if mirror_id not in MIRROR_FILES:
            raise HTTPException(status_code=404, detail="Unknown mirror id.")
        path = ensure_mirror_file(data_dir, mirror_id)
        try:
            validate_mirror_content(body.content)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "VALIDATION",
                        "message": str(e),
                    }
                },
            ) from e
        path.write_text(body.content, encoding="utf-8")
        try:
            doc_id = await rag.ingest_mirror_document(path, mirror_key=mirror_id)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "VALIDATION",
                        "message": str(e),
                    }
                },
            ) from e
        except (httpx.HTTPError, OSError, RuntimeError) as e:
            logger.exception(
                "api_error event=mirror_reindex_failed code=MODEL_UNAVAILABLE mirror_id=%s",
                mirror_id,
            )
            raise HTTPException(
                status_code=503,
                detail={
                    "error": {
                        "code": "MODEL_UNAVAILABLE",
                        "message": str(e) or "Embedding backend unreachable.",
                    }
                },
            ) from e
        return MirrorPutResponse(
            mirror_id=mirror_id,  # type: ignore[arg-type]
            document_id=doc_id,
            reindexed=True,
        )

    @router.get("/tools", response_model=ToolListResponse)
    async def list_tools() -> ToolListResponse:
        items = [
            ToolListItem(
                name=d.name,
                description=d.description,
                required_capability=d.required_capability,
            )
            for d in tools_registry.definitions()
        ]
        return ToolListResponse(tools=items)

    @router.post("/tools/invoke")
    async def invoke_tool(body: ToolInvokeRequest) -> dict[str, Any]:
        try:
            out = await tools_registry.invoke(
                body.tool,
                body.arguments,
                rag=rag,
                granted_capabilities=set(),
            )
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "VALIDATION",
                        "message": f"Unknown tool: {body.tool}",
                    }
                },
            ) from None
        if not out.get("ok"):
            err = out.get("error") or {}
            code = err.get("code")
            if code == "VALIDATION":
                raise HTTPException(status_code=400, detail={"error": err})
            if code == "PERMISSION_DENIED":
                # 403 = tool/OS permission (e.g. Calendar TCC), not missing API token (401).
                msg = err.get("message") or ""
                logger.warning(
                    "tools/invoke permission denied tool=%s (403 is expected for OS/tool denial; see message below)",
                    body.tool,
                )
                for line in str(msg).splitlines():
                    logger.warning("  | %s", line)
                raise HTTPException(status_code=403, detail={"error": err})
            raise HTTPException(status_code=500, detail={"error": err})
        return {"ok": True, "result": out.get("result")}

    @router.post("/calendar/events", status_code=201, response_model=CalendarEventCreateResponse)
    async def post_calendar_event(body: CalendarEventCreateRequest) -> CalendarEventCreateResponse:
        """Create a Calendar event via EventKit (same as ``calendar.create_event`` tool)."""
        try:
            out = await run_create_event(body.model_dump(exclude_none=True))
        except CalendarPermissionDenied as e:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "PERMISSION_DENIED", "message": str(e)}},
            ) from e
        except ValueError as e:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(e)}},
            ) from e
        return CalendarEventCreateResponse(**out)

    @router.post("/memory/entries", status_code=201)
    async def post_memory(body: MemoryEntryRequest) -> MemoryEntryResponse:
        try:
            doc_id, job_id = await rag.ingest_memory(
                body.text,
                tags=body.tags,
                source=body.source,
            )
        except (httpx.HTTPError, OSError, RuntimeError) as e:
            logger.exception("api_error event=memory_ingest_failed code=MODEL_UNAVAILABLE")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": {
                        "code": "MODEL_UNAVAILABLE",
                        "message": str(e) or "Embedding backend unreachable.",
                    }
                },
            ) from e
        return MemoryEntryResponse(document_id=doc_id, job_id=job_id)

    @router.get("/memory/search")
    async def memory_search(
        q: str,
        limit: int = 20,
        source_kind: str | None = None,
        path_prefix: str | None = None,
        indexed_after: str | None = None,
        indexed_before: str | None = None,
    ) -> SearchResponse:
        try:
            dt_after = (
                datetime.fromisoformat(indexed_after.replace("Z", "+00:00"))
                if indexed_after
                else None
            )
            dt_before = (
                datetime.fromisoformat(indexed_before.replace("Z", "+00:00"))
                if indexed_before
                else None
            )
            results = await rag.search(
                q,
                limit=limit,
                filters=SearchFilters(
                    source_kind=source_kind,
                    path_prefix=path_prefix,
                    indexed_after=dt_after,
                    indexed_before=dt_before,
                ),
            )
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "VALIDATION", "message": str(e)}},
            ) from e
        except (httpx.HTTPError, OSError, RuntimeError) as e:
            logger.exception("api_error event=memory_search_failed code=MODEL_UNAVAILABLE")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": {
                        "code": "MODEL_UNAVAILABLE",
                        "message": str(e) or "Embedding backend unreachable.",
                    }
                },
            ) from e
        return SearchResponse(results=results)

    @router.post("/chat")
    async def post_chat(body: ChatRequest) -> dict[str, Any]:
        try:
            out = await rag.chat(body.messages)
        except httpx.HTTPError as e:
            logger.exception("api_error event=chat_failed code=MODEL_UNAVAILABLE kind=httpx")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": {
                        "code": "MODEL_UNAVAILABLE",
                        "message": "Local inference engine not reachable.",
                    }
                },
            ) from e
        except (OSError, RuntimeError) as e:
            logger.exception("api_error event=chat_failed code=MODEL_UNAVAILABLE kind=runtime")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": {
                        "code": "MODEL_UNAVAILABLE",
                        "message": str(e),
                    }
                },
            ) from e
        return out.model_dump()

    @router.post("/chat/stream")
    async def post_chat_stream(body: ChatRequest) -> StreamingResponse:
        async def gen() -> Any:
            try:
                async for line in rag.chat_stream_sse(body.messages):
                    yield line
            except httpx.HTTPError as e:
                logger.exception("api_error event=chat_stream_failed code=MODEL_UNAVAILABLE")
                err = '{"code":"MODEL_UNAVAILABLE","message":"Local inference engine not reachable."}'
                yield f"event: error\ndata: {err}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    app.include_router(router)

    if static_dir.is_dir() and (static_dir / "index.html").is_file():
        app.mount(
            "/",
            StaticFiles(directory=str(static_dir), html=True),
            name="web",
        )
    else:

        @app.get("/")
        async def no_build() -> JSONResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "error": "Web UI not built. Run: cd web && npm ci && npm run build",
                },
            )

    return app


def main() -> None:
    import uvicorn

    data_dir = default_data_dir()
    configure_logging(data_dir)
    cfg = load_config(data_dir)
    load_or_create_bearer_token(data_dir)
    uvicorn.run(
        "memoryagent.app:create_app_factory",
        factory=True,
        host=cfg.host,
        port=cfg.port,
        reload=False,
    )


def create_app_factory() -> FastAPI:
    return create_app()
