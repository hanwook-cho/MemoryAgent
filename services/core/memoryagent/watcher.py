"""Filesystem watcher: debounced ingest into the same RAG pipeline as manual entries."""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from pathlib import Path
from pathspec.gitignore import GitIgnoreSpec
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from memoryagent.config_store import AppConfig
from memoryagent.rag_service import RagService

logger = logging.getLogger(__name__)

_FILE_SUFFIXES = {".md", ".txt"}


def path_matches_ignore(rel_posix: str, spec: GitIgnoreSpec | None) -> bool:
    if not spec:
        return False
    return spec.match_file(rel_posix)


def build_ignore_spec(patterns: list[str]) -> GitIgnoreSpec | None:
    if not patterns:
        return None
    return GitIgnoreSpec.from_lines(patterns)


class _EnqueueHandler(FileSystemEventHandler):
    def __init__(
        self,
        *,
        root: Path,
        ignore_spec: GitIgnoreSpec | None,
        out: queue.Queue[Path | None],
        queue_full_log: str,
    ) -> None:
        self._root = root.resolve()
        self._ignore_spec = ignore_spec
        self._out = out
        self._queue_full_log = queue_full_log

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        try:
            rel = path.resolve().relative_to(self._root)
        except ValueError:
            return
        rel_posix = rel.as_posix()
        if path_matches_ignore(rel_posix, self._ignore_spec):
            return
        if path.suffix.lower() not in _FILE_SUFFIXES:
            return
        try:
            self._out.put_nowait(path)
        except queue.Full:
            logger.warning("%s: %s", self._queue_full_log, path)


class NullFileWatcher:
    """No-op watcher (tests or when filesystem watching is disabled)."""

    def start(self, loop: asyncio.AbstractEventLoop, cfg: AppConfig) -> None:
        _ = (loop, cfg)

    def stop(self) -> None:
        pass

    def restart(self, loop: asyncio.AbstractEventLoop, cfg: AppConfig) -> None:
        _ = (loop, cfg)


class FileWatcher:
    """Watch configured roots; debounce and ingest changed text files."""

    def __init__(
        self,
        *,
        data_dir: Path,
        rag: RagService,
        queue_max: int = 256,
    ) -> None:
        self._data_dir = data_dir
        self._rag = rag
        self._queue_max = queue_max
        self._observer: Observer | None = None
        self._raw_q: queue.Queue[Path | None] = queue.Queue(maxsize=queue_max)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._worker_task: asyncio.Task[None] | None = None
        self._debounce_handles: dict[Path, asyncio.TimerHandle] = {}
        self._debounce_s = 1.5
        self._ignore_spec: GitIgnoreSpec | None = None
        self._lock = threading.Lock()

    def _schedule_ingest(self, path: Path) -> None:
        loop = self._loop
        if loop is None:
            return

        def fire() -> None:
            self._debounce_handles.pop(path, None)
            asyncio.create_task(self._ingest_path(path))

        old = self._debounce_handles.pop(path, None)
        if old is not None:
            old.cancel()
        self._debounce_handles[path] = loop.call_later(self._debounce_s, fire)

    def _enqueue_from_thread(self, path: Path) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._schedule_ingest, path)

    async def _ingest_path(self, path: Path) -> None:
        try:
            await self._rag.ingest_file_path(path)
        except Exception:
            logger.exception("ingest failed for %s", path)

    async def _queue_worker(self) -> None:
        loop = self._loop
        assert loop is not None
        while True:
            path = await asyncio.to_thread(self._raw_q.get)
            if path is None:
                break
            self._schedule_ingest(path)

    def start(self, loop: asyncio.AbstractEventLoop, cfg: AppConfig) -> None:
        with self._lock:
            self.stop()
            self._raw_q = queue.Queue(maxsize=self._queue_max)
            self._loop = loop
            self._debounce_s = float(cfg.watch_debounce_seconds)
            self._ignore_spec = build_ignore_spec(list(cfg.watch_ignore_globs))
            self._worker_task = asyncio.create_task(self._queue_worker())
            self._observer = Observer()
            for raw in cfg.watched_roots:
                root = Path(raw).expanduser()
                if not root.is_dir():
                    logger.warning("watched root missing or not a directory: %s", root)
                    continue
                h = _EnqueueHandler(
                    root=root,
                    ignore_spec=self._ignore_spec,
                    out=self._raw_q,
                    queue_full_log="watch queue full; dropping event",
                )
                self._observer.schedule(h, str(root.resolve()), recursive=True)
            if self._observer.emitters:
                self._observer.start()
            else:
                self._observer = None

    def stop(self) -> None:
        obs = self._observer
        self._observer = None
        if obs is not None:
            obs.stop()
            obs.join(timeout=10.0)
        wt = self._worker_task
        self._worker_task = None
        if wt is not None:
            while True:
                try:
                    self._raw_q.put_nowait(None)
                    break
                except queue.Full:
                    try:
                        self._raw_q.get_nowait()
                    except queue.Empty:
                        pass
            if not wt.done():
                wt.cancel()
        for h in self._debounce_handles.values():
            h.cancel()
        self._debounce_handles.clear()
        self._loop = None

    def restart(self, loop: asyncio.AbstractEventLoop, cfg: AppConfig) -> None:
        self.start(loop, cfg)
