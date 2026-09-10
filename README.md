# ClauseCite — ask questions across your contracts, with citations that resolve

Ask your contracts. Get cited answers. Upload a set of PDFs, ask a question in
plain English, and get an answer drawn **only** from those documents — where
every claim carries a citation you can click through to the highlighted
passage in the source PDF.

Bring your own LLM key for generated answers, or use none at all — with no key
the app still answers, by selecting and quoting the passages that address the
question.

> **Status:** runs locally with no setup beyond `npm` and `pip`. Docker, CI, and
> a retrieval eval set are wired up. Deploy configuration is checked in
> (`frontend/vercel.json`, `render.yaml`) and the deployed demo runs
> stateless on both free tiers, so uploads reset when it restarts (see
> [Production readiness](#production-readiness) for why that is deliberate).
> [Not done yet](#not-done-yet) lists what is still consciously deferred.

---

## What it does

- **Ingests** text-layer PDFs, capturing page numbers and bounding boxes at
  extraction time, chunked on clause boundaries rather than fixed sizes.
- **Answers** questions over those documents with hybrid retrieval (vector +
  full-text, fused with Reciprocal Rank Fusion), streamed token by token.
- **Cites** every claim. Clicking `[1]` opens the source PDF at the right page
  and draws a highlight over the exact passage that supported the answer.

Answering "the documents provided don't cover this" is a valid, instrumented
outcome. An answer without a citation is not.

### Two answering modes

| | No API key (default) | With an API key |
|---|---|---|
| Where answers come from | The uploaded documents only | The uploaded documents, plus the model's own knowledge |
| How they are produced | Relevant sentences are selected and quoted | The model writes the answer from the retrieved passages |
| Outside knowledge | Never | Allowed, but the model must label it as such |
| Marked in the UI as | `Documents only` | `Documents + AI` |

Retrieval, citations, and PDF highlighting are identical in both modes — the key
changes how the answer is *written*, not where the evidence comes from. Paste a
key into the panel in the app and it is remembered across restarts. If the
provider later fails — revoked key, exhausted quota, no network — the answer
falls back to documents-only rather than failing, and says so.

You supply the key and nothing else. Provider, endpoint, and model are worked
out from it: first by matching the key's prefix (`sk-ant-`, `gsk_`, `AIza`, …),
and if no prefix matches, by asking each candidate provider whether the key is
theirs rather than assuming one. A dropdown overrides that when you'd rather be
explicit, and a **Custom** option takes a base URL and model name, so any
OpenAI-compatible endpoint works — including a self-hosted one — whether or not
this repo has ever heard of it.

---

## Running locally

Requires **Python 3.12** and **Node 20+**. No Docker, no database server, and no
API key.

```powershell
# Windows: installs dependencies, then starts the API and the web UI together.
.\start.ps1 -Install
```

Or step by step, on any platform:

```bash
# 1. Configuration. The defaults run the whole app with nothing else installed.
cp .env.example .env

# 2. Backend. The SQLite schema is created on first start.
cd backend
uv sync --all-extras                      # or: pip install -e ".[dev]"
# --reload-dir app so the reloader watches source, not the uploaded documents
# and database under .data/ — otherwise an upload restarts the server.
uvicorn app.main:app --reload --reload-dir app     # http://127.0.0.1:8000

# 3. Realistic sample contracts, ingested through the real upload path.
python scripts/seed.py

# 4. Frontend, in a second terminal.
cd frontend
npm install
npm run dev                               # http://localhost:5173
```

Then open <http://localhost:5173>, upload a PDF, and ask *"What is the notice
period for termination?"*

### Using PostgreSQL instead

SQLite is the zero-setup default; PostgreSQL + pgvector is what production
should use, because it replaces an in-Python similarity scan with an indexed
one. Point `DATABASE_URL` at it and run the migrations:

```bash
docker compose up -d db                   # Postgres + pgvector on host port 5433
# in .env: DATABASE_URL=postgresql+asyncpg://dev:dev@localhost:5433/docqa
cd backend && alembic upgrade head
```

Alembic owns the PostgreSQL schema — it is the only place the HNSW and GIN
indexes are declared. SQLite has no migration history, so its schema is created
from the ORM metadata at startup instead.

### Checking it came up correctly

| URL | Expected |
|---|---|
| <http://127.0.0.1:8000/health> | `{"status":"ok"}` — liveness only, checks no dependencies |
| <http://127.0.0.1:8000/ready> | `database`, `storage`, and `ai_provider` all `ok` |
| <http://127.0.0.1:8000/docs> | OpenAPI browser |
| <http://127.0.0.1:8000/metrics> | Prometheus exposition |

`seed.py` prints a list of questions worth trying. It uploads over HTTP rather
than writing rows directly, so a broken extractor or chunker fails there rather
than during a demo. Re-running is safe — identical files are deduplicated by
SHA-256. `python scripts/seed.py --reset` clears existing documents first.

### What you give up without an API key

The offline provider is honest about what it is:

- **Embeddings are deterministic hashes**, not semantic. Vector search degrades
  to lexical similarity rather than to noise, so relevant sources still surface —
  but ranking is weaker than real embeddings would give.
- **Answers are extractive.** The best-matching sentences are quoted back rather
  than composed, so the phrasing reads stilted and the answer cannot synthesise
  across sources or rephrase itself for the question asked.

Everything structural is exercised regardless: SSE streaming, citation
resolution, page attribution, and the highlight overlay. Connect a key for
answer quality.

Note that **embeddings always come from the offline provider, even with a key
connected.** Chunks are embedded once at ingest; swapping embedding models
afterwards would leave query vectors in a different space from the stored ones,
and retrieval would silently return noise. One embedding function means a key
can be added, changed, or removed at any time without reindexing.

---

## Architecture

```
Browser (React + Vite)
  │  POST /api/chat  → text/event-stream
  ▼
FastAPI ── PyMuPDF extraction → clause-aware chunking → embeddings
  │
  ├── SQLite or Postgres     documents, chunks, conversations
  │                          (pgvector HNSW + FTS on Postgres; Python scan on SQLite)
  ├── Blob storage           raw PDFs (filesystem locally; a persistent disk or
  │                          Azure Blob in production — storage.py is provider-agnostic)
  └── Your LLM provider      answer generation — optional; identified from the key
```

**Decisions that mattered, and the trade-off each accepted:**

- **pgvector, not a dedicated vector database.** Below roughly 500k chunks an
  HNSW index in Postgres is fast enough that a user cannot tell, and it buys
  transactional consistency between documents and chunks, one backup story, and
  one vendor. Above that ceiling, migrate.
- **SQLite as a first-class local mode.** Portable column types
  (`app/db_types.py`) let one set of models serve both backends, and retrieval
  branches on the dialect. The cost is an O(n) similarity scan instead of an
  index lookup — irrelevant for a laptop-sized corpus, unacceptable in
  production.
- **The API key is supplied at runtime, not at deploy time.** It never enters an
  environment variable or an image, so this repo carries no deploy secret and a
  reviewer can run the project without one. The user fills in one field rather
  than four because the provider is identified from the key itself.
- **Unrecognised keys are probed, not guessed.** A prefix table only knows the
  formats that existed when it was written, and providers do change them.
  Assuming a default meant sending a valid key to the wrong provider and
  reporting its `401` as "your key was rejected" — blaming the user for the
  app's bad guess. Now each candidate is asked whether the key is theirs, one at
  a time, stopping at the first match so the key reaches as few providers as
  possible. OpenRouter is excluded from probing because its `/models` catalogue
  is public and answers `200` to anything, which would make it claim every key.
- **Clause-aware chunking.** Numbered clauses (`3.2`, `(a)`, `(iv)`) are the real
  semantic boundaries in contracts. The section path (`ARTICLE 3 - TERMINATION >
  3.2 Notice Period`) is prepended to the *embedded* text but not the stored
  text, so retrieval sees the heading while quotes stay clean.
- **Bounding boxes captured at extraction time.** Without them you can only jump
  to a page, and retrofitting means re-ingesting everything. They are stored in
  unrotated PDF user space so the viewer's zoom and rotation are the viewer's
  problem, not the extractor's.
- **SSE, not WebSockets.** Streaming is one-directional; SSE is plain HTTP,
  survives proxies, and reconnects itself.
- **`BackgroundTasks`, not a queue.** Sufficient at this scale. Move to a real
  queue when ingestion exceeds ~60s, retries must survive a restart, or the API
  scales past one replica.
- **Unresolvable citations are dropped, not rendered.** A model that cites `[7]`
  when six sources were supplied gets that marker stripped and counted in
  `rag_unresolved_citations_total`. A chip the user cannot click breaks the only
  promise the product makes.

---

## Layout

```
backend/app/
  api/          documents (upload, list, file, delete), chat (SSE),
                provider (connect/disconnect a key), health + ready
  services/     extract, chunk, embed, retrieve, generate, storage, provider
  workers/      background ingestion
  models.py     SQLAlchemy ORM     schemas.py  the public API contract
backend/scripts/
  contracts.py  the sample corpus  seed.py     render to PDF and ingest
frontend/src/
  lib/          sse, citations, highlight   ← the logic worth unit testing
  hooks/        useDocuments, useChatStream
  components/   ChatPanel, MessageBubble, CitationChip, PdfViewer, Document*
```

---

## Tests

```bash
cd backend && pytest                       # 87 tests, no database or network needed
cd frontend && npm test                    # 46 tests
cd frontend && npm run lint && npm run typecheck
```

The backend suite runs the real pipeline — extract, chunk, embed, retrieve,
cite — against a temporary SQLite file and the offline provider, so a break
anywhere in that chain fails a test rather than a demo. It covers provider
detection and probing (including that an Anthropic key is never sent to an
OpenAI-compatible endpoint, and that OpenRouter is never probed — its public
catalogue would otherwise claim every unidentified key), citation resolution,
upload validation, the full ask-and-cite flow, key persistence across a
restart, recovery of an ingest interrupted by a crash, and the fallback when a
connected model fails mid-request.

The frontend's highest-value tests cover the parts that fail silently: SSE
events split across network chunks, markers the model invented, and the PDF→
viewport coordinate flip that puts a highlight in the wrong half of the page.

---

## Production readiness

- **Docker.** `backend/Dockerfile` and `frontend/Dockerfile` build standalone
  images (`docker compose up` runs the full local stack in containers instead
  of on the host). The frontend image has a `dev` target used by compose and
  a `prod` target (Vite build served by nginx as a non-root user) used for
  deployment.
- **CI** — `.github/workflows/ci.yml` runs backend lint/mypy/pytest, frontend
  lint/typecheck/vitest, and a Docker build of both images on every push and
  PR.
- **Deployment target: Vercel + Render.** The frontend (`frontend/`) deploys to
  Vercel directly from the repo — no Dockerfile involved, Vercel builds it with
  `npm run build` (`frontend/vercel.json`, project root directory `frontend`).
  The backend (`backend/`) deploys to Render from `render.yaml` as a Docker web
  service. `VITE_API_URL` is set as a Vercel build-time environment variable
  pointing at the Render backend's URL, and `CORS_ORIGINS` on the backend is
  set to the Vercel URL. Docker/`docker-compose.yml` remain for local
  development too.
- **The deployed demo keeps no state.** Render's filesystem is wiped on every
  deploy and restart, so it runs on the default SQLite database and local blob
  storage, and uploaded documents reset with it. This is deliberate rather than
  an oversight: pairing a persistent database with ephemeral blob storage would
  leave documents recorded as `ready` whose PDFs no longer exist, so every
  citation on them would fail to resolve. Making it durable means moving both
  at once — a Render PostgreSQL instance (the initial migration creates the
  `vector` and `pgcrypto` extensions itself) with `alembic upgrade head` as a
  pre-deploy command, plus a blob container in
  `AZURE_STORAGE_CONNECTION_STRING`.
- **Retrieval evaluation set** — `backend/scripts/eval_qa.json` has 20
  hand-labelled question → expected-document pairs; `python
  backend/scripts/eval_retrieval.py` seeds nothing itself (run
  `scripts/seed.py` first) but asks each question through the real
  `/api/chat` path and reports recall@5, to catch ranking regressions unit
  tests can't.

## Not done yet

Out of scope for v1 by choice: multi-tenancy, document editing, OCR for scanned
documents, fine-tuned models, real-time collaboration.

---

## Data handling

Document content is never logged. In this vertical the documents are
client-confidential by definition, so request logs carry the question, the
retrieved chunk IDs and scores, token counts, and per-stage latency — and no
passage text. API keys are never logged either.

Two things do touch the disk, both under `backend/.data/` and both gitignored:
uploaded PDFs, and — if `PERSIST_PROVIDER_KEY` is left on — the API key, in
plain text, so that "connected" survives a restart. That is the same trust level
as the `.env` beside it. Set `PERSIST_PROVIDER_KEY=false` to keep the key in
memory only, at the cost of re-entering it after each restart.

On the deployed demo neither survives anyway: the filesystem is wiped on every
restart, so uploads reset and the key has to be re-pasted. Keeping a key off a
public demo's disk is the better default regardless.

With a key connected, the retrieved passages are sent to that provider and are
subject to its terms. Without one, no document text leaves the machine.
