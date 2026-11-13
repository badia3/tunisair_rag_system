# Tunisair Information Agentic RAG Assistant

An Agentic RAG assistant for Tunisair. The crawler fetches only explicitly allowlisted
French pages, stores full extracted text in local SQLite and searchable chunks in Pinecone,
and cites the source URLs. Timetable questions create a validated, prefilled booking link;
the booking site itself is never crawled or fetched.

---

## 1. Business Problem

### Information sources

- `https://www.tunisair.com/fr`
- `https://www.tunisair.com/fr/offres`
- `https://www.tunisair.com/fr/vols-en-cours`
- `https://flights.tunisair.com/fr`
- Timetable link generation for `book.tunisair.com`, shown to the user without automated access.

The flight search form uses the 49 city/airport codes currently listed in the official
Tunisair flight-status page. The source list is defined once in `app/services/airports.py`
and shared with the web template and question router so displayed cities and parsed codes
stay aligned.

### Example
An employee asks:

> **“What information is available from Tunisair's official pages?”**

The assistant answers from the indexed landing pages and cites the source URL.

For a timetable search:

> **“Create a round-trip search from TUN to PAR, departing 2026-11-11 and returning 2026-11-12.”**

The assistant creates a prefilled official booking link. The user opens it to see current
availability; the application does not fetch the booking site.

### Business Goal
Build a source-grounded Tunisair assistant that:

1. Retrieves from only the explicitly allowed Tunisair landing pages.
2. Checks whether retrieved evidence is good enough.
3. Rewrites weak queries and retries the same allowlisted knowledge base.
4. Generates validated booking links for date-specific timetable searches.
5. Shows source links and the agent's decision trace.

---

## 2. Why This Is an FDE Project

A Forward Deployed Engineer does more than create an LLM notebook. The FDE must turn the customer's problem into a usable product.

```text
Customer Problem
      ↓
Discovery & Requirements
      ↓
Solution Architecture
      ↓
Data / Knowledge Integration
      ↓
Agentic RAG Development
      ↓
API Development
      ↓
User Interface
      ↓
Security + Audit + Testing
      ↓
Deployment
      ↓
Observe + Improve
```

This repository demonstrates each layer.

---

## 3. Simple Architecture

```text
                   ┌─────────────────────┐
                   │   Employee / User   │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │ HTML/CSS/JavaScript │
                   │      Web UI         │
                   └──────────┬──────────┘
                              │ POST /api/chat
                              ▼
                   ┌─────────────────────┐
                   │       FastAPI       │
                   └──────────┬──────────┘
                              │
                              ▼
                   ┌─────────────────────┐
                   │     LangGraph       │
                   │ Agentic RAG Control │
                   └──────────┬──────────┘
                              │
               ┌──────────────┴──────────────┐
               │                             │
               ▼                             ▼
       ┌───────────────┐              ┌──────────────┐
       │ Allowed pages │              │ Booking link │
       │ SQLite +      │              │ (user opens) │
       │ Pinecone      │              │              │
       └───────┬───────┘              └──────┬───────┘
               │                             │
               └──────────────┬──────────────┘
                              ▼
                     ┌────────────────┐
                     │ Ollama LLM     │
                     │ Grounded Answer│
                     └────────────────┘
```

---

## 4. Agentic RAG Workflow

The workflow keeps the existing routing, evidence grading, bounded query rewrite, and
grounded generation pattern.

```text
Question
   ↓
[1] Route Question
   ├── Greeting / simple chat ─────────────→ Direct Answer
   │
   ├── Timetable/availability request
   │        ↓
   │   Validate route codes and dates
   │        ↓
   │   Generate official booking link
   │
   └── Tunisair information question
                ↓
[2] Retrieve from the allowlisted pages in Pinecone
                ↓
[3] Grade Tunisair page evidence
       ┌────────┴────────┐
       │                 │
     GOOD               WEAK
       │                 │
       ▼                 ▼
Generate answer   Rewrite and retry
                         ↓
                 Insufficient evidence
```

### Why Agentic?

Normal RAG does approximately this:

```text
Question → Retrieve → Generate
```

This project makes decisions:

```text
Question
 → Route
 → Retrieve
 → Evaluate evidence
 → Retry only the allowlisted KB
 → Rewrite if needed
 → Retry
 → Generate grounded answer
```

The system therefore controls **what to do next** based on its current state.

---

## 5. Main Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Agent workflow | LangGraph | Stateful routing and conditional decisions |
| LLM | Ollama `llama3.2` or OpenAI chat model | Routing, grading, rewriting, answer generation |
| Embeddings | Ollama `nomic-embed-text` or OpenAI `text-embedding-3-small` | 768- or 1536-dimensional embeddings |
| Vector DB | Pinecone | Searchable chunks from allowlisted Tunisair pages |
| Page archive | SQLite | Full extracted text and sync timestamps |
| API | FastAPI | Backend and REST endpoints |
| Frontend | HTML/CSS/JavaScript | Employee-facing interface |
| Audit | SQLite | Basic decision-path logging |
| Packaging | Docker | Reproducible deployment |

---

## 6. Project Structure

```text
FDE_Agentic_RAG_IT_Copilot/
│
├── app/
│   ├── api/
│   │   └── routes.py              # Chat and health APIs
│   │
│   ├── core/
│   │   ├── config.py              # Environment configuration
│   │   └── logging.py             # Logging configuration
│   │
│   ├── rag/
│   │   ├── state.py               # LangGraph state + structured decisions
│   │   ├── vectorstore.py         # Pinecone + embeddings
│   │   └── workflow.py            # Complete Agentic RAG graph
│   │
│   ├── services/
│   │   ├── audit.py               # SQLite query audit
│   │   ├── content_store.py       # Durable extracted-page SQLite storage
│   │   ├── ingestion.py           # Text chunking
│   │   ├── tunisair.py            # Fixed-URL crawler and timetable-link builder
│   │   └── tunisair_sync.py       # Incremental Pinecone sync
│   │
│   └── main.py                    # FastAPI application
│
├── sync_tunisair.py               # Allowed-page dry run and sync
├── setup_weekly_sync.ps1          # Register weekly Windows sync task
├── run_weekly_sync.ps1            # Scheduled sync runner and log
│
├── static/
│   ├── css/style.css
│   └── js/app.js
│
├── templates/
│   └── index.html
│
├── tests/
│   └── test_tunisair.py
│
├── Dockerfile
├── requirements.txt
├── run.py
└── README.md
```

---

## 7. Setup

### Step 1 — Create virtual environment

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

macOS/Linux:

```bash
source venv/bin/activate
```

### Step 2 — Install dependencies

```bash
pip install -r requirements.txt
```

Install the configured Ollama models:

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

Chat generation defaults to Ollama. To test it with OpenAI, set `LLM_PROVIDER=openai`
and provide an API key in `.env`. Never paste the key into source code or commit `.env`.
Embeddings default to Ollama's `nomic-embed-text`; set `EMBEDDING_PROVIDER=openai` to
use OpenAI embeddings too. The embedding model and Pinecone index dimensions must match.

### Step 3 — Configure environment

Create a `.env` file in the project root directory with the following variables:

```env
# Vector database (Pinecone)
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=fde-it-support-nomic-768
PINECONE_NAMESPACE=tunisair-fr

# Ollama (already used by this project)
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2
EMBEDDING_MODEL=nomic-embed-text

# Optional OpenAI chat provider (use these instead of Ollama chat settings to test)
# LLM_PROVIDER=openai
# OPENAI_API_KEY=your_openai_api_key_here
# OPENAI_CHAT_MODEL=gpt-4o-mini

# Optional OpenAI embeddings (requires a separate 1536-dimension Pinecone index)
# EMBEDDING_PROVIDER=openai
# OPENAI_EMBEDDING_MODEL=text-embedding-3-small

# Tunisair fetch limits
TUNISAIR_CRAWL_DELAY_SECONDS=1.0
TUNISAIR_REQUEST_TIMEOUT_SECONDS=20
```

#### Environment Variable Reference

| Variable | Description | Example | Required |
|---|---|---|---|
| `LLM_PROVIDER` | Chat model provider | `ollama` or `openai` | Optional; defaults to `ollama` |
| `OPENAI_API_KEY` | API key used by OpenAI chat and/or embedding providers | `sk-...` | Required for an OpenAI provider |
| `OPENAI_CHAT_MODEL` | OpenAI chat model | `gpt-4o-mini` | Optional |
| `EMBEDDING_PROVIDER` | Embedding provider | `ollama` or `openai` | Optional; defaults to `ollama` |
| `OPENAI_EMBEDDING_MODEL` | OpenAI embedding model | `text-embedding-3-small` | Optional |
| `PINECONE_API_KEY` | API key for Pinecone vector database | `pckey-...` | ✅ Yes |
| `PINECONE_INDEX_NAME` | Pinecone index; dimension must match embeddings | `fde-it-support-nomic-768` | Optional |
| `PINECONE_NAMESPACE` | Isolated Tunisair namespace | `tunisair-fr` | Optional |
| `OLLAMA_BASE_URL` | Ollama endpoint used for chat or embeddings | `http://localhost:11434` | Required when Ollama is selected |
| `OLLAMA_CHAT_MODEL` | Ollama chat model | `llama3.2` | Optional |
| `EMBEDDING_MODEL` | Embedding model | `nomic-embed-text` | Optional |
| `CORS_ORIGINS` | JSON array of exact browser origins allowed to call the API | `["https://badia3.github.io"]` | Required for a separate Pages frontend |
| `TUNISAIR_CRAWL_DELAY_SECONDS` | Delay between page fetches | `1.0` | Optional |
| `TUNISAIR_REQUEST_TIMEOUT_SECONDS` | Fetch timeout | `20` | Optional |

**⚠️ Important Security Notes:**

- Never commit `.env` to version control. Add it to `.gitignore`.
- Use environment variables instead of hardcoding secrets.
- Restrict API key access to only the services that need them.

### GitHub Pages frontend and separate API

The GitHub Pages workflow builds only the static browser interface. It does not host
FastAPI, LangGraph, Ollama, or Pinecone. Deploy the API to a service that supports the
project's Dockerfile, then configure:

- The GitHub Actions repository variable `PAGES_API_BASE_URL` to the backend's HTTPS
  base URL, without a trailing slash (for example, `https://your-api.example.com`).
- The backend environment variable `CORS_ORIGINS` to the JSON array
  `["https://badia3.github.io"]`.
- The backend's `OPENAI_API_KEY` and `PINECONE_API_KEY` in that backend host's
  secret/environment settings, never in the Pages site or workflow.

For a public project page, add rate limiting or authentication at the API host before
sharing it: CORS restricts browser origins but does not prevent direct API requests.

#### Render deployment

The root `render.yaml` defines a free Docker web service for the API, using OpenAI for
chat and embeddings. Create the Blueprint in Render from this repository and provide
the requested `OPENAI_API_KEY` and `PINECONE_API_KEY` as Render secrets. The existing
768-dimension Ollama index is not reused; the Blueprint configures a new
`tunisair-rag-openai-1536` index.

The free Render plan does not provide Shell access. Add `OPENAI_API_KEY` and
`PINECONE_API_KEY` as GitHub Actions repository secrets, then run the
**Sync Tunisair knowledge base** workflow manually once. It uses the same OpenAI
embedding model and Pinecone index as Render; it is also scheduled for Sundays at
02:00 UTC. Then copy the service's HTTPS URL into the GitHub Actions repository variable
`PAGES_API_BASE_URL` and rerun the Pages workflow. The Pages site is
`https://badia3.github.io/tunisair_rag_system/`; its browser origin for CORS is
`https://badia3.github.io`.

The Render free service can sleep when idle and has an ephemeral filesystem. Pinecone
keeps the vectors, but local audit/content SQLite files and the sync manifest are not
durable across service replacement or restart. Free hosting is for testing; review
Render and OpenAI usage limits before sharing the public API.

### Step 4 — Verify and index the allowlisted pages

```bash
python sync_tunisair.py --dry-run
python sync_tunisair.py
```

The crawler requests exactly these URLs and does not discover or follow other page links:

```text
https://www.tunisair.com/fr
https://www.tunisair.com/fr/offres
https://www.tunisair.com/fr/vols-en-cours
https://flights.tunisair.com/fr
```

The full extracted text is stored in `data/tunisair_content.db`; searchable chunks and
metadata are stored in Pinecone. The content database is excluded from Git. The sync
updates changed pages and removes stale chunks; a dry run makes no data changes.

`book.tunisair.com` disallows automated crawling in its `robots.txt`. The app never
fetches that host. For timetable questions, it validates explicit three-letter route codes
and ISO round-trip dates, builds the official prefilled link, and asks the user to open it.
If an allowlisted page returns a CAPTCHA, HTTP 403, 421, or 429, the sync stops without
retrying or changing the Pinecone index.

On Windows, register the weekly sync task with:

```powershell
.\setup_weekly_sync.ps1
```

It runs Sundays at 03:00 when the current Windows user is signed in. Review
`data/tunisair_sync.log` and the task's Last Run Result in Task Scheduler. Run
`.\run_weekly_sync.ps1` to sync manually and log the result.

### Step 5 — Run the application

```bash
python run.py
```

Open:

```text
http://127.0.0.1:8080
```

FastAPI API docs:

```text
http://127.0.0.1:8080/docs
```

---

## 8. Classroom Demo Scenarios

### Demo A — Tunisair page retrieval

Ask:

> **What information is available on the Tunisair pages?**

Expected path:

```text
Router → KB
Retrieve approved Tunisair pages
KB Grade → GOOD
Generate with official source citation
```

Teaching point:

> The answer is limited to the pages the crawler is allowed to fetch.

---

### Demo B — Timetable link

Ask:

> **Create a Tunisair search TUN to PAR, depart 2026-11-11, return 2026-11-12**

The assistant returns a link. The user opens it to see booking availability.

Expected path:

```text
Router → BOOKING
Validate route codes and dates
Generate official booking link
```

Teaching point:

> The booking site is not fetched by the app; its own browser flow handles current availability.

---

### Demo C — Current fares

Ask:

> **What are Tunisair's current fares?**

The app must not invent a current price. It directs the user to the official flight planner
to select travel dates and see the live fare. Other questions about offers and page content
are answered from indexed evidence where available.

Teaching point:

> Time-sensitive fares must be checked on the official booking page.

---

### Demo D — Query Rewrite

Ask a deliberately vague question such as:

> **Tell me about a Tunisair topic not covered by the approved pages.**

If the approved page evidence is weak, the workflow rewrites once and retries that same index.

Teaching point:

> Retry is bounded; it never broadens the crawl to other URLs.

---

### Demo E — Direct Conversation

Ask:

> **Hello!**

Expected path:

```text
Router → DIRECT
Direct Answer
```

Teaching point:

> Direct messages do not trigger unnecessary vector searches.

---

## 9. Sync behavior

Run `python sync_tunisair.py` to refresh the allowed pages manually. The local
`data/tunisair_sync_manifest.json` tracks page hashes and vector IDs. Full extracted text
is stored separately in `data/tunisair_content.db`; keep both files between runs. On the
weekly schedule, only changed page content is re-indexed. If a page is denied or returns a
CAPTCHA, sync stops without retrying or updating stored data.

---

## 10. API Endpoints

### `GET /api/health`

Health check.

### `POST /api/chat`

Request:

```json
{
  "question": "Create a Tunisair search TUN to PAR, depart 2026-11-11, return 2026-11-12"
}
```

Response contains:

```json
{
  "answer": "...",
  "source_used": "tunisair_booking_link",
  "trace": [
    "Router → BOOKING",
    "Booking link → generated from validated dates; booking site not fetched"
  ],
  "citations": [
    {"title": "Open Tunisair timetable", "url": "https://book.tunisair.com/...", "type": "website"}
  ]
}
```

---
