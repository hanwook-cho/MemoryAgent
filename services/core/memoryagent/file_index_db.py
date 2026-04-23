"""File index metadata DB for incremental ingestion (M5+ foundation)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

PARSER_VERSION = "v1"


@dataclass(frozen=True)
class FileIndexRecord:
    uri: str
    path: str
    document_id: str
    size_bytes: int
    mtime_ns: int
    parser_version: str
    source_kind: str
    indexed_at: str


class FileIndexDB:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self._db_path))
        con.row_factory = sqlite3.Row
        return con

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS file_index (
                  uri TEXT PRIMARY KEY,
                  path TEXT NOT NULL,
                  document_id TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL,
                  mtime_ns INTEGER NOT NULL,
                  parser_version TEXT NOT NULL,
                  source_kind TEXT NOT NULL,
                  indexed_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_index_path ON file_index(path)"
            )

    def get(self, uri: str) -> FileIndexRecord | None:
        with self._connect() as con:
            row = con.execute(
                "SELECT uri, path, document_id, size_bytes, mtime_ns, parser_version, source_kind, indexed_at "
                "FROM file_index WHERE uri = ?",
                (uri,),
            ).fetchone()
        if row is None:
            return None
        return FileIndexRecord(
            uri=str(row["uri"]),
            path=str(row["path"]),
            document_id=str(row["document_id"]),
            size_bytes=int(row["size_bytes"]),
            mtime_ns=int(row["mtime_ns"]),
            parser_version=str(row["parser_version"]),
            source_kind=str(row["source_kind"]),
            indexed_at=str(row["indexed_at"]),
        )

    def upsert(
        self,
        *,
        uri: str,
        path: str,
        document_id: str,
        size_bytes: int,
        mtime_ns: int,
        parser_version: str,
        source_kind: str,
        indexed_at: str,
    ) -> None:
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO file_index (
                  uri, path, document_id, size_bytes, mtime_ns,
                  parser_version, source_kind, indexed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(uri) DO UPDATE SET
                  path=excluded.path,
                  document_id=excluded.document_id,
                  size_bytes=excluded.size_bytes,
                  mtime_ns=excluded.mtime_ns,
                  parser_version=excluded.parser_version,
                  source_kind=excluded.source_kind,
                  indexed_at=excluded.indexed_at
                """,
                (
                    uri,
                    path,
                    document_id,
                    int(size_bytes),
                    int(mtime_ns),
                    parser_version,
                    source_kind,
                    indexed_at,
                ),
            )

    def should_reindex(
        self,
        *,
        uri: str,
        size_bytes: int,
        mtime_ns: int,
        parser_version: str,
    ) -> bool:
        rec = self.get(uri)
        if rec is None:
            return True
        if rec.parser_version != parser_version:
            return True
        if rec.size_bytes != int(size_bytes):
            return True
        if rec.mtime_ns != int(mtime_ns):
            return True
        return False
