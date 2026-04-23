# Implementation plan — PDF + DOCX + file index DB

This plan introduces broader document support (`.pdf`, `.docx`) and an index metadata database to avoid reprocessing unchanged files.

## Goals

- Support ingestion from widely used document formats (`.pdf`, `.docx`) in addition to current text-first flow.
- Keep indexing efficient by skipping unchanged files.
- Preserve local-first behavior and existing retrieval contracts.

## Phase breakdown

## Phase A — Index DB foundation (implemented)

- [x] Add file index metadata DB under `MEMORYAGENT_DATA_DIR/store/file_index.db` (SQLite).
- [x] Track file identity and index state: URI/path, `document_id`, `size_bytes`, `mtime_ns`, `parser_version`, `indexed_at`.
- [x] Integrate with `ingest_file_path` so unchanged files are skipped (no re-embed/upsert).
- [x] Add tests for:
  - unchanged file => skip reindex
  - changed file => reindex

Current implementation files:

- `services/core/memoryagent/file_index_db.py`
- `services/core/memoryagent/rag_service.py`
- `services/core/tests/test_m5_file_index.py`

## Phase B — PDF ingestion (implemented)

- [x] Add extraction abstraction (`extract_text(path)`) and integrate in ingestion path.
- [x] Add `.pdf` parser (initially text extraction only, no OCR requirement).
- [x] Handle empty/scanned-like PDFs with clear errors (`no extractable text`).
- [x] Add unit/integration tests for PDF extraction + ingest/search.

Current implementation files:

- `services/core/memoryagent/document_extractors.py`
- `services/core/memoryagent/rag_service.py`
- `services/core/memoryagent/watcher.py` (now watches `.pdf`)
- `services/core/tests/test_document_extractors.py`
- `services/core/tests/test_m2.py`

## Phase C — DOCX ingestion (implemented)

- [x] Add `.docx` extractor (paragraph text and simple structure flattening).
- [x] Normalize whitespace/line breaks for chunking.
- [x] Add tests for DOCX extraction + ingest/search path.

Current implementation files:

- `services/core/memoryagent/document_extractors.py`
- `services/core/memoryagent/watcher.py` (now watches `.docx`)
- `services/core/tests/test_document_extractors.py`
- `services/core/tests/test_m2.py`

## Phase D — metadata-aware retrieval (implemented)

- [x] Expose metadata filters (date range, file type, path scope) in retrieval pipeline.
- [x] Blend semantic ranking with metadata constraints for queries like:
  - “find bank statement in the last month”.

Current implementation files:

- `services/core/memoryagent/rag_service.py`
- `services/core/memoryagent/vector_store.py`
- `services/core/memoryagent/app.py`
- `services/core/tests/test_m2.py`
- `docs/spec/http-api.md`

## Safety and performance constraints

- [x] Maximum file size guardrail per format.
- [x] Extraction timeout/failure paths logged with structured errors.
- [x] Parser versioning (`PARSER_VERSION`) to force reindex on parser changes.

## Notes

- Index DB and vector DB are complementary:
  - **Index DB** decides whether/how to reprocess files.
  - **Vector DB** provides semantic retrieval.
- OCR for scanned PDFs is out of initial scope but can be added after Phase B.
