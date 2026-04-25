"""FastAPI application: `/api/v1/*` API + static web at `/`."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from memoryagent import __version__
from memoryagent.auth_http import BearerChecker
from memoryagent.backends import build_runtime_backends
from memoryagent.config_store import (
    KNOWN_DEPLOYMENT_MODES,
    AppConfig,
    load_config,
    normalize_edge_base_url,
    normalize_edge_spki_pins_sha256,
    optional_config_string,
    save_config,
)
from memoryagent.edge_http import edge_httpx_verify
from memoryagent.deployment_runtime import chat_meta_block, health_deployment_block
from memoryagent.embeddings import DeterministicEmbedder, Embedder, OllamaEmbedder
from memoryagent.folder_picker import pick_folder_macos
from memoryagent.google_calendar import (
    GOOGLE_CALENDAR_OAUTH_STATE_TTL_SECONDS,
    GoogleCalendarApiError,
    GoogleCalendarOAuthError,
    build_google_calendar_authorization_url,
    create_google_calendar_event,
    delete_google_calendar_tokens,
    exchange_google_calendar_authorization_code,
    google_calendar_account_hint,
    google_calendar_connected,
    revoke_google_calendar_tokens,
)
from memoryagent.llm_client import FakeLlm, LlmClient, OllamaLlm
from memoryagent.logging_setup import configure_logging
from memoryagent.mirror import MIRROR_FILES, ensure_mirror_file, validate_mirror_content
from memoryagent.node_client import fetch_edge_health
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
    GoogleCalendarConnectResponse,
    GoogleCalendarStatusResponse,
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

_MP1_BACKEND_PATCH_FIELDS = frozenset(
    {
        "deployment_mode",
        "edge_base_url",
        "edge_tls_ca_bundle",
        "edge_tls_insecure_skip_verify",
        "edge_ingest_path_host_prefix",
        "edge_ingest_path_edge_prefix",
    }
)

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

    backends = build_runtime_backends(rag, cfg, bearer_token=bearer_token)
    rag.bind_retrieval_for_chat(backends.retrieval)
    rag.bind_ingest_for_routing(backends.ingest)
    retrieval = backends.retrieval
    ingest = backends.ingest

    watcher: FileWatcher | NullFileWatcher = (
        file_watcher if file_watcher is not None else FileWatcher(data_dir=data_dir, rag=rag)
    )
    tools_registry = build_default_registry(data_dir)

    async def _edge_ping(c: AppConfig) -> tuple[bool | None, str | None]:
        if c.deployment_mode == "standalone":
            return None, None
        edge = c.edge_base_url
        if not edge:
            return None, None
        return await fetch_edge_health(
            edge,
            bearer_token=bearer_token,
            verify=edge_httpx_verify(c),
        )

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
                await ingest.ingest_mirror_document(mp, mirror_key=mid)
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
    app.state.mp1_backends = backends

    @app.get(f"{API_PREFIX}/health")
    async def health() -> dict[str, Any]:
        c = load_config(data_dir)
        reachable = await ollama_reachable(c.ollama_base_url)
        stats = retrieval.index_stats()
        edge_ok, edge_err = await _edge_ping(c)
        return {
            "status": "ok",
            "version": __version__,
            "deployment": health_deployment_block(
                c.deployment_mode,
                edge_base_url=c.edge_base_url,
                edge_reachable=edge_ok,
                edge_error=edge_err,
            ),
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
    public_router = APIRouter(prefix=API_PREFIX)
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
            "deployment_mode": c.deployment_mode,
            "edge_base_url": c.edge_base_url,
            "edge_tls_ca_bundle": c.edge_tls_ca_bundle,
            "edge_tls_insecure_skip_verify": c.edge_tls_insecure_skip_verify,
            "edge_ingest_path_host_prefix": c.edge_ingest_path_host_prefix,
            "edge_ingest_path_edge_prefix": c.edge_ingest_path_edge_prefix,
            "edge_tls_spki_pins_sha256": list(c.edge_tls_spki_pins_sha256),
            "google_calendar_include": c.google_calendar_include,
            "google_calendar_oauth_client_id": c.google_calendar_oauth_client_id,
            "google_calendar_oauth_redirect_uri": c.google_calendar_oauth_redirect_uri,
            "ui": {
                "chat_welcome_dismissed": False,
                "chat_welcome_version": "3",
            },
        }

    @router.patch("/config")
    async def patch_config(body: ConfigPatchRequest) -> dict[str, Any]:
        nonlocal retrieval, backends, ingest
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
        if body.deployment_mode is not None:
            if body.deployment_mode not in KNOWN_DEPLOYMENT_MODES:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": {
                            "code": "VALIDATION",
                            "message": (
                                f"Invalid deployment_mode: {body.deployment_mode!r}. "
                                f"Expected one of: {sorted(KNOWN_DEPLOYMENT_MODES)}."
                            ),
                        }
                    },
                )
            c.deployment_mode = body.deployment_mode
        if body.edge_base_url is not None:
            c.edge_base_url = normalize_edge_base_url(body.edge_base_url)
        fs = body.model_fields_set
        if "edge_tls_ca_bundle" in fs:
            c.edge_tls_ca_bundle = optional_config_string(body.edge_tls_ca_bundle)
        if "edge_tls_insecure_skip_verify" in fs:
            c.edge_tls_insecure_skip_verify = bool(body.edge_tls_insecure_skip_verify)
        if "edge_ingest_path_host_prefix" in fs:
            c.edge_ingest_path_host_prefix = optional_config_string(
                body.edge_ingest_path_host_prefix
            )
        if "edge_ingest_path_edge_prefix" in fs:
            c.edge_ingest_path_edge_prefix = optional_config_string(
                body.edge_ingest_path_edge_prefix
            )
        if "edge_tls_spki_pins_sha256" in fs:
            c.edge_tls_spki_pins_sha256 = normalize_edge_spki_pins_sha256(
                body.edge_tls_spki_pins_sha256
            )
        if "google_calendar_include" in fs:
            requested = bool(body.google_calendar_include)
            if requested and not google_calendar_connected(data_dir):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": {
                            "code": "GOOGLE_CALENDAR_NOT_CONNECTED",
                            "message": (
                                "Google Calendar OAuth is not connected. "
                                "Start the connect flow before enabling Include Google Calendar."
                            ),
                        }
                    },
                )
            c.google_calendar_include = requested
        if "google_calendar_oauth_client_id" in fs:
            c.google_calendar_oauth_client_id = optional_config_string(
                body.google_calendar_oauth_client_id
            )
        if "google_calendar_oauth_redirect_uri" in fs:
            c.google_calendar_oauth_redirect_uri = optional_config_string(
                body.google_calendar_oauth_redirect_uri
            )
        save_config(data_dir, c)
        if fs & _MP1_BACKEND_PATCH_FIELDS:
            backends = build_runtime_backends(rag, c, bearer_token=bearer_token)
            retrieval = backends.retrieval
            ingest = backends.ingest
            rag.bind_retrieval_for_chat(retrieval)
            rag.bind_ingest_for_routing(ingest)
            app.state.mp1_backends = backends
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
            doc_id = await ingest.ingest_mirror_document(path, mirror_key=mirror_id)
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
        """Create a Calendar event via local EventKit or Google Calendar."""
        try:
            args = body.model_dump(exclude_none=True)
            c = load_config(data_dir)
            target = args.get("calendar_target")
            if c.google_calendar_include and target is None:
                raise ValueError(
                    "calendar_target is required when Google Calendar is included; "
                    "use 'local' or 'google'"
                )
            if target == "google":
                out = await create_google_calendar_event(data_dir, c, args)
            else:
                if target not in (None, "local"):
                    raise ValueError("calendar_target must be 'local' or 'google'")
                out = await run_create_event(args)
                out["calendar_target"] = "local"
        except CalendarPermissionDenied as e:
            raise HTTPException(
                status_code=403,
                detail={"error": {"code": "PERMISSION_DENIED", "message": str(e)}},
            ) from e
        except GoogleCalendarApiError as e:
            raise HTTPException(
                status_code=502,
                detail={"error": {"code": "GOOGLE_CALENDAR_API", "message": str(e)}},
            ) from e
        except ValueError as e:
            raise HTTPException(
                status_code=422,
                detail={"error": {"code": "VALIDATION", "message": str(e)}},
            ) from e
        return CalendarEventCreateResponse(**out)

    def _google_calendar_status_response() -> GoogleCalendarStatusResponse:
        c = load_config(data_dir)
        connected = google_calendar_connected(data_dir)
        include = bool(c.google_calendar_include and connected)
        status = "on" if include else ("connected_off" if connected else "off")
        message = None
        if c.google_calendar_include and not connected:
            message = "Google Calendar Include was requested but no OAuth tokens are connected."
        return GoogleCalendarStatusResponse(
            include=include,
            connected=connected,
            status=status,
            account_hint=google_calendar_account_hint(data_dir),
            message=message,
        )

    @router.get("/calendar/google/status", response_model=GoogleCalendarStatusResponse)
    async def get_google_calendar_status() -> GoogleCalendarStatusResponse:
        """Google Calendar Include/connection state (Google calls are disabled when off)."""
        return _google_calendar_status_response()

    @router.post("/calendar/google/connect", response_model=GoogleCalendarConnectResponse)
    async def connect_google_calendar() -> GoogleCalendarConnectResponse:
        """Start Google Calendar OAuth by returning a consent URL for the client to open."""
        try:
            authorization_url, state = build_google_calendar_authorization_url(
                data_dir,
                load_config(data_dir),
            )
        except GoogleCalendarOAuthError as e:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "GOOGLE_CALENDAR_OAUTH_CONFIG", "message": str(e)}},
            ) from e
        return GoogleCalendarConnectResponse(
            authorization_url=authorization_url,
            state=state,
            expires_in_seconds=GOOGLE_CALENDAR_OAUTH_STATE_TTL_SECONDS,
        )

    @public_router.get("/calendar/google/callback", response_model=GoogleCalendarStatusResponse)
    async def google_calendar_oauth_callback(
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ) -> GoogleCalendarStatusResponse:
        """Complete Google Calendar OAuth. Query values are never logged."""
        if error:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "GOOGLE_CALENDAR_OAUTH_CANCELLED",
                        "message": "Google Calendar OAuth was cancelled or denied.",
                    }
                },
            )
        if not code or not state:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": {
                        "code": "GOOGLE_CALENDAR_OAUTH_CALLBACK",
                        "message": "Google Calendar OAuth callback requires code and state.",
                    }
                },
            )
        c = load_config(data_dir)
        try:
            await exchange_google_calendar_authorization_code(
                data_dir,
                c,
                code=code,
                state=state,
            )
        except GoogleCalendarOAuthError as e:
            raise HTTPException(
                status_code=400,
                detail={"error": {"code": "GOOGLE_CALENDAR_OAUTH_FAILED", "message": str(e)}},
            ) from e
        c.google_calendar_include = True
        save_config(data_dir, c)
        return _google_calendar_status_response()

    @router.post("/calendar/google/disconnect", response_model=GoogleCalendarStatusResponse)
    async def disconnect_google_calendar() -> GoogleCalendarStatusResponse:
        """Best-effort revoke Google token storage, remove it locally, and force Include off."""
        c = load_config(data_dir)
        c.google_calendar_include = False
        save_config(data_dir, c)
        try:
            await revoke_google_calendar_tokens(data_dir)
        except GoogleCalendarApiError as e:
            logger.warning("google_calendar_revoke_failed message=%s", str(e))
        delete_google_calendar_tokens(data_dir)
        return _google_calendar_status_response()

    @router.post("/memory/entries", status_code=201)
    async def post_memory(body: MemoryEntryRequest) -> MemoryEntryResponse:
        try:
            doc_id, job_id = await ingest.ingest_memory(
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
            results = await retrieval.search(
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

    @router.get("/admin/status")
    async def admin_status() -> dict[str, Any]:
        c = load_config(data_dir)
        edge_ok, edge_err = await _edge_ping(c)
        stats = retrieval.index_stats()
        return {
            "deployment": health_deployment_block(
                c.deployment_mode,
                edge_base_url=c.edge_base_url,
                edge_reachable=edge_ok,
                edge_error=edge_err,
            ),
            "index": stats,
            "llm": {
                "reachable": await ollama_reachable(c.ollama_base_url),
                "model": c.chat_model,
            },
        }

    @router.get("/admin/events")
    async def admin_events(
        level: str = "error",
        since: str | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        _ = level, since
        log_path = data_dir / "logs" / "core.log"
        events: list[dict[str, Any]] = []
        if log_path.is_file():
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            tail = lines[-max(1, min(limit, 2000)) :]
            for line in tail:
                events.append({"line": line})
        return {"events": events, "count": len(events)}

    @router.post("/admin/control/reindex")
    async def admin_control_reindex() -> dict[str, Any]:
        c = load_config(data_dir)
        watcher.restart(asyncio.get_running_loop(), c)
        return {"ok": True, "detail": "Watcher restarted; watched files re-seeded."}

    @router.post("/admin/control/restart")
    async def admin_control_restart() -> dict[str, Any]:
        c = load_config(data_dir)
        watcher.restart(asyncio.get_running_loop(), c)
        return {"ok": True, "detail": "Workers/watchers restarted."}

    @router.post("/admin/control/cold-start")
    async def admin_control_cold_start() -> dict[str, Any]:
        return {
            "ok": True,
            "detail": "Runtime refresh stub; no persistent data deleted.",
        }

    @router.post("/admin/control/reset-index")
    async def admin_control_reset_index() -> dict[str, Any]:
        rag.reset_search_index()
        c = load_config(data_dir)
        watcher.restart(asyncio.get_running_loop(), c)
        for mid in MIRROR_FILES:
            mp = ensure_mirror_file(data_dir, mid)
            try:
                await ingest.ingest_mirror_document(mp, mirror_key=mid)
            except Exception:
                logger.exception("mirror ingest after reset-index failed for %s", mid)
        return {
            "ok": True,
            "detail": "Vector index cleared; ingest counters reset; mirrors re-ingested.",
        }

    @router.post("/admin/control/factory-reset")
    async def admin_control_factory_reset() -> None:
        raise HTTPException(
            status_code=501,
            detail={
                "error": {
                    "code": "UNAVAILABLE",
                    "message": "factory-reset is not implemented.",
                }
            },
        )

    @router.post("/chat")
    async def post_chat(body: ChatRequest) -> dict[str, Any]:
        c = load_config(data_dir)
        edge_ok, edge_err = await _edge_ping(c)
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
        payload = out.model_dump()
        payload["meta"] = chat_meta_block(
            c.deployment_mode,
            edge_base_url=c.edge_base_url,
            edge_reachable=edge_ok,
            edge_error=edge_err,
        )
        return payload

    @router.post("/chat/stream")
    async def post_chat_stream(body: ChatRequest) -> StreamingResponse:
        c = load_config(data_dir)
        edge_ok, edge_err = await _edge_ping(c)
        meta = chat_meta_block(
            c.deployment_mode,
            edge_base_url=c.edge_base_url,
            edge_reachable=edge_ok,
            edge_error=edge_err,
        )

        async def gen() -> Any:
            meta_sent = False
            try:
                async for line in rag.chat_stream_sse(body.messages):
                    if line.startswith("event: done") and not meta_sent:
                        meta_sent = True
                        yield f"event: meta\ndata: {json.dumps(meta)}\n\n"
                    yield line
            except httpx.HTTPError:
                logger.exception("api_error event=chat_stream_failed code=MODEL_UNAVAILABLE")
                err = '{"code":"MODEL_UNAVAILABLE","message":"Local inference engine not reachable."}'
                yield f"event: error\ndata: {err}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    app.include_router(public_router)
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
