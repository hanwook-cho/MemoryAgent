# V-next plan — document format expansion

This document defines the next wave of ingestion format support after current `.md`, `.txt`, `.pdf`, and `.docx`.

## Goals

- Expand real-world business document coverage with minimal regression risk.
- Keep extraction local-first and deterministic.
- Preserve existing index DB + incremental reindex behavior.
- Maintain retrieval quality with format-aware chunking where needed.

## Current baseline (implemented)

- Supported ingestion/indexing: `.md`, `.txt`, `.pdf` (text-based), `.docx`
- Incremental reindexing via `store/file_index.db`
- Metadata-aware retrieval filters (`source_kind`, `path_prefix`, `indexed_after`, `indexed_before`)
- Guardrails: per-format max size + extraction timeout/error logging

## Candidate formats for next version

| Format | Value | Suggested parser/runtime | Notes |
| :--- | :--- | :--- | :--- |
| `.csv` / `.tsv` | Very high | Python stdlib `csv` / `pandas` optional | Add row-aware chunking and header retention. |
| `.xlsx` | Very high | `openpyxl` | Include sheet names + cell ranges in metadata/snippets. |
| `.pptx` | High | `python-pptx` | Extract slide text, titles, speaker notes. |
| OCR for scanned PDFs/images (`.png`, `.jpg`, image-only `.pdf`) | High | `tesseract` + wrapper (`pytesseract`) or Vision API (local) | Largest unlock for “no extractable text” docs. |
| `.eml` / `.mbox` | Medium-high | Python `email`, `mailbox` | Add sender/date/subject metadata fields. |
| `.doc` | Medium | conversion via `libreoffice --headless` | Legacy format; conversion step increases complexity. |
| `.rtf` | Medium | `striprtf` | Lightweight, often sufficient for plain text extraction. |
| `.odt` | Medium | `odfpy` or zip/xml parsing | Similar to docx-style text extraction. |
| `.html` / `.htm` | Medium | `beautifulsoup4` + boilerplate cleanup | Need content extraction heuristics to avoid nav/chrome noise. |

## Recommended rollout order

## Phase E — tabular docs

- Add `.csv`, `.tsv`, `.xlsx`
- Implement table-aware chunking (carry headers into chunks)
- Add tests for large files, multi-sheet workbooks, malformed rows

## Phase F — presentation docs

- Add `.pptx` extraction (slides + notes)
- Add chunk metadata: `slide_index`, `slide_title`
- Add retrieval tests that validate slide-level relevance

## Phase G — OCR pipeline

- Add OCR fallback for image-only PDFs
- Optional direct image ingestion (`.png`, `.jpg`, `.jpeg`)
- Add confidence/error metadata and timeout guardrails

## Phase H — communication and legacy docs

- Add `.eml`, `.mbox`, `.rtf`, `.odt`, `.doc` (via conversion)
- Add metadata filters for email fields (`from`, `to`, `date`, `subject`)
- Add conversion-failure handling with structured logs

## Cross-cutting requirements

- Keep `PARSER_VERSION` strategy so parser changes can force reindex.
- Define max-size guardrails per new format.
- Add extraction timeouts and structured error logging per parser.
- Ensure watcher suffix allowlist is updated with each added format.
- Add source kinds for each format family (e.g. `file_xlsx`, `file_pptx`, `file_email`).

## Acceptance criteria for V-next

- At least one tabular (`.xlsx`/`.csv`) and one presentation or OCR path is production-ready.
- New formats are covered by:
  - extractor unit tests
  - ingestion/search integration tests
  - watcher integration tests
  - failure/timeout tests
- Full suite remains green with no regression in existing formats.

## OCR throughput and hardware budget guidance

OCR is significantly slower than native text extraction. Capacity planning should treat OCR as a background batch workload.

### Practical throughput ranges (order-of-magnitude)

| Workload | Typical throughput |
| :--- | :--- |
| Native text extraction (`.md/.txt/.docx` and text-based PDFs) | milliseconds to low seconds per file |
| OCR extraction (scanned pages) | ~0.3 to 2.0+ seconds per page (hardware/content dependent) |

Primary factors:

- CPU class and core count
- Image/PDF resolution and noise quality
- Language model complexity
- Preprocessing steps (deskew, denoise, binarization)
- Concurrency settings

### Raspberry Pi + external SSD considerations

For Raspberry Pi-class devices, OCR is feasible but slower than desktop Macs:

- Prefer SSD for source + index storage (avoid SD-card-heavy write paths).
- Keep OCR worker concurrency low (`1-2`) to avoid thermal throttling.
- Use a lightweight OCR profile first (single language, moderate DPI).
- Expect long first-pass indexing for large scanned archives; subsequent runs should be fast due to index DB skip logic.

Estimated planning envelope (Pi-class, conservative):

- Small batch (100 scanned pages): roughly minutes to low tens of minutes
- Medium batch (1,000 scanned pages): tens of minutes to multiple hours

These are planning ranges, not guarantees; measure on target hardware before setting SLAs.

### Recommended runtime policies for low-power hardware

- OCR only when native PDF extraction yields no text.
- Add per-file/page hard limits (size, page count, timeout).
- Queue OCR as low-priority background jobs with progress reporting.
- Persist OCR text cache + confidence metadata in index state.
- Provide a "pause/resume indexing" control for thermal/power management.

## Raspberry Pi semantic-first profile

For Raspberry Pi deployments, prioritize semantic retrieval quality and responsiveness over format breadth.

### Primary objective

- Keep semantic search usable under constrained CPU/RAM by minimizing expensive ingestion paths.

### Recommended defaults

- Embeddings/retrieval:
  - Keep vector index resident on SSD-backed storage.
  - Use smaller, efficient embedding models suitable for ARM devices.
  - Favor metadata pre-filters (`path_prefix`, `source_kind`, date bounds) before vector ranking.
- Ingestion:
  - Prioritize native-text formats (`.md`, `.txt`, `.docx`, text-based `.pdf`).
  - Defer OCR to background and optional user-triggered mode.
  - Throttle watcher ingestion and batch updates to avoid constant re-embedding churn.
- Query path:
  - Keep retrieval top-k modest (e.g. 5-10) and apply reranking only when needed.
  - Cache recent query embeddings/results when practical.

### Operational guidance

- Treat OCR and conversion formats as "best-effort extensions"; semantic search remains the guaranteed feature.
- Expose clear indexing state to users (queued, indexing, skipped, failed) so retrieval expectations are set.
- Include a low-resource mode toggle:
  - lower concurrency
  - stricter size/time limits
  - semantic search unaffected, heavy extraction delayed
