# AutoApply

PFE-book → CV matching: AutoApply parses PFE books (end-of-studies internship catalogs) and candidate CVs, then uses hybrid search to rank the most relevant subject and drafts a tailored application.

## Current status

Working, live baseline (single-user, local-first):

- **`apps/web`** — Next.js 14 candidate workspace, split into `/` (overview), `/books` (PFE book upload + indexing), `/cv` (CV upload/edit), `/matches` (book-scoped CV→subject matching). Shared `AppShell` sidebar, CV state shared across pages.
- **`services/api`** — FastAPI service: PDF upload/extraction, LLM structured extraction, data-quality layer, subject indexing, hybrid search, CV parsing + matching.
- **`services/worker`** — reserved boundary for future async PDF/LLM jobs.
- **`packages/shared`** — shared structured-extraction schema.
- **`docker-compose.yml`** — Postgres 16 + pgvector, Redis, MinIO, and the API (live reload).
- **QA console** — a single-page UI (`app/static/index.html`, no build step) served at `GET /` for CV upload → edit profile → match, plus Search and Library & Index tabs.
- **Tests** — 103 passing (unit + integration; Postgres integration runs when `TEST_DATABASE_URL` is set).

## Features (implemented)

- **PDF ingestion** — `POST /books` uploads PFE PDFs to MinIO (SHA-256 dedup, page count, OCR-flagging), extracts text with PyMuPDF, Tesseract OCR fallback for scans.
- **LLM structured extraction** — `POST /books/{hash}/extract` runs a configurable `g4f` provider cascade (keyless) with retries + timeouts; output validated against a Pydantic schema; chunked for oversized texts.
- **Data-quality layer** — applied at index time (raw text untouched): mojibake repair, known-junk strip, per-book boilerplate detection (block edges only), subject dedup/title recovery, `quality_report` with an over-strip tripwire.
- **Subject indexing** — `POST /books/{hash}/index` (and `/books/index-all`): stores subjects with French accent-insensitive `tsvector`, `pg_trgm` GIN, and a 384-d `embedding` vector + HNSW cosine index. Embeddings come from a **local** `fastembed` ONNX model (no API key); if unavailable, search falls back to keyword-only.
- **Hybrid search** — `GET /search?q=...&dense=true` returns keyword-channel + dense-channel rankings merged by **Reciprocal Rank Fusion** (`k=60`); every row carries a `source` badge (`keyword` / `dense` / `both`).
- **CV integration** — `POST /cv` parses FR/EN CVs (skills, education, experience, projects, certifications), `POST /cv/{hash}/profile` allows manual correction, and `POST /cv/{hash}/match?dense=true&book_hash=...` ranks subjects for a CV.
- **Per-book scoping** — matching can be restricted to a single book via `book_hash` (validated 404); scoping is applied in both channels (keyword + dense).
- **Upload limits** — `MAX_UPLOAD_BYTES` (default 100 MB) caps book/CV uploads with HTTP 413.

## Run locally

Prerequisites: Docker Desktop, Node.js 18+, Python 3.11+.

```bash
# 1. Configure environment
cp .env.example .env        # adapt passwords / provider pool

# 2. Infrastructure + API (postgres, redis, minio, api on :8000)
docker compose up --build

# 3. Frontend
npm install
npm run dev:web             # http://localhost:3000
```

- API health check: `http://localhost:8000/health`
- QA console + original single-page UI: `http://localhost:8000/`
- API docs (OpenAPI): `http://localhost:8000/docs`

### Tests

```bash
cd services/api
python -m pytest tests -q                    # unit suite (skips Postgres integration)
# with a live Postgres reachable on localhost, point TEST_DATABASE_URL at it
# (e.g. postgresql://autoapply:password@localhost:5432/autoapply — host swapped
#  to localhost because the container hostname "postgres" only resolves in Docker):
$env:TEST_DATABASE_URL = "postgresql://autoapply:password@localhost:5432/autoapply"
python -m pytest tests -q                    # 103 passed incl. Postgres integration
```

### Key environment variables

Set in `.env` (see `.env.example`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres DSN for the API container |
| `POSTGRES_PASSWORD`, `MINIO_ROOT_USER`, `MINIO_ROOT_PASSWORD` | Infra secrets |
| `G4F_PROVIDER_POOL` | Ordered `Provider:Model` cascade for extraction |
| `G4F_MAX_TOKENS`, `G4F_CHUNK_CHARACTERS` | LLM extraction limits |
| `MAX_UPLOAD_BYTES` | Upload cap, default 104857600 (100 MB) |

## API surface

| Method & path | Purpose |
|---|---|
| `GET /health` | Liveness + DB/embedder status |
| `GET /books` | List uploaded books (filename, hash, subject count) |
| `POST /books` | Upload PFE PDF (multipart `file`) |
| `POST /books/{hash}/extract` | Run LLM structured extraction |
| `POST /books/{hash}/index` | Build searchable subject index |
| `POST /books/index-all` | Index all extracted books |
| `GET /books/{hash}/index` | List indexed subjects |
| `GET /search?q=...&dense=true` | Hybrid search over all books |
| `POST /cv` | Upload + parse CV (txt/md/pdf) |
| `GET /cv/{hash}` | Get parsed profile |
| `POST /cv/{hash}/profile` | Overwrite parsed sections |
| `POST /cv/{hash}/match?dense=true&book_hash=...` | Rank subjects for a CV (optionally scoped to one book) |

## Core workflow

1. Upload a PFE book (`POST /books`).
2. Extract structured subjects (`POST /books/{hash}/extract` — LLM).
3. Index subjects (`POST /books/{hash}/index` — keyword + embedding).
4. Upload a CV (`POST /cv`), correct the parsed profile if needed.
5. Match the CV against one book or all (`POST /cv/{hash}/match`) — hybrid RRF ranking.
6. Generate a tailored email for the best match — *planned (E4), not built*.

## Architecture

```mermaid
flowchart TB
    subgraph Client
        FE["Web App - Next.js<br/>/, /books, /cv, /matches"]
        QA["QA Console - static single page"]
    end

    subgraph API
        GW[FastAPI]
    end

    subgraph Data
        PG["Postgres + pgvector<br/>books, book_subjects, cv_profiles"]
        OBJ["MinIO object storage - PDFs"]
    end

    FE --> GW
    QA --> GW
    GW --> OBJ
    GW -->|"index: build tsvector + pgvector rows"| PG
    GW -->|"hybrid search: keyword + dense, RRF"| PG
```

Future (not yet built): async workers (Redis queue), LLM rerank, email generator, OAuth send, multi-user auth.

## AI strategy

- **Extraction** — keyless `g4f` provider cascade (`Gemini` primary → `Cloudflare` → `Gemini-lite` → `LLM7`), each tier retried 2× with a 120 s timeout; configurable via `G4F_PROVIDER_POOL`. Malformed output falls through to the next provider; all-fail returns 500.
- **Embeddings** — local `fastembed` (ONNX, CPU) with `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384-d, one-time ~0.22 GB Hugging Face download, no key). Replaced the planned Gemini embedding vendored approach to stay keyless and offline-capable.
- **Ranking** — keyword channel (French `app_search` config: `unaccent` + `simple` on both index and query, `ts_rank_cd` ×3 + `pg_trgm` similarity + compact-reference bonus) and dense channel (cosine similarity, threshold > 0.2), merged with RRF `k=60`. `source` per row, `book_hash` scoping in both channels.

## Core data model

Live tables (created at API startup):

- **books** — `file_hash`, `filename`, MinIO `object_ref`, page count, extracted text, OCR flag, `extraction_json` JSONB.
- **book_subjects** — `book_hash`, `reference`, `title`, cleaned `text`, `raw_text`, page range, `tokens` (tsvector), `embedding` (vector(384), HNSW).
- **cv_profiles** — `cv_hash`, `filename`, `raw_text`, `profile_json` (skills/education/experience/projects/certifications).

Planned/spec-only entities (multi-user product): User/auth, Company, ProjectBankItem, Match, GeneratedMessage, SendLog.

## Roadmap status

- ✅ **Phase 0 — Foundations**: monorepo scaffold, Docker Compose, provider abstraction (g4f cascade, fastembed).
- ✅ **Phase 1 — MVP (mostly)**: PDF upload + OCR fallback, dedup, LLM subject extraction, CV upload + parsing + manual edit, subject embeddings, keyword index + RRF, per-book scoping, QA console & web pages.
- ⏳ **Phase 1 remaining**: ranked-subject browser with filters, LLM rerank with rationale, ground-truth CV fixture + precision@k validation, live OCR validation on a scanned book, async extraction workers.
- ⏳ **Phase 2 — Application assistance**: motivation email generator (E4), editable draft, LinkedIn variant, project bank, CV tailoring.
- ⏳ **Phase 3 — Automation & trust**: OAuth send (Gmail/Outlook), review-and-approve, send log, multi-book per account.
- ⏳ **Phase 4 — Scale**: usage caps, self-host docs, outcome tracking.

## Open decisions

- Data handling for uploaded PFE books should be documented clearly (users upload for personal matching only).
- French is the primary target language for extraction prompts, English secondary.
- The project supports a privacy-preserving local-only mode, with free-tier cloud as an optional quality upgrade.

## Current next steps

1. **Ingestion observability** — per-book coverage log (source chars vs. extracted) + surface `quality_report` at index time.
2. **Match ground truth** — a real CV fixture and precision@k measurement against the stored books before tuning.
3. **AutoApply email MVP (E4)** — tailored motivation email with graceful personalization fallback while company mission/vision/values remain `null`.
