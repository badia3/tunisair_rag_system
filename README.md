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
| LLM | Ollama `llama3.2` | Routing, grading, rewriting, answer generation |
| Embeddings | Ollama `nomic-embed-text` | 768-dimensional embeddings |
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

### Step 3 — Configure environment

Create a `.env` file in the project root directory with the following variables:

```env
# Vector database (Pinecone)
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_INDEX_NAME=fde-it-support-nomic-768
PINECONE_NAMESPACE=tunisair-fr

# Ollama (already used by this project)
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2
EMBEDDING_MODEL=nomic-embed-text

# Tunisair fetch limits
TUNISAIR_CRAWL_DELAY_SECONDS=1.0
TUNISAIR_REQUEST_TIMEOUT_SECONDS=20
```

#### Environment Variable Reference

| Variable | Description | Example | Required |
|---|---|---|---|
| `PINECONE_API_KEY` | API key for Pinecone vector database | `pckey-...` | ✅ Yes |
| `PINECONE_INDEX_NAME` | Pinecone index; dimension must match embeddings | `fde-it-support-nomic-768` | Optional |
| `PINECONE_NAMESPACE` | Isolated Tunisair namespace | `tunisair-fr` | Optional |
| `OLLAMA_BASE_URL` | Ollama endpoint reachable from the app | `http://localhost:11434` | Required |
| `OLLAMA_CHAT_MODEL` | Ollama chat model | `llama3.2` | Optional |
| `EMBEDDING_MODEL` | Embedding model | `nomic-embed-text` | Optional |
| `TUNISAIR_CRAWL_DELAY_SECONDS` | Delay between page fetches | `1.0` | Optional |
| `TUNISAIR_REQUEST_TIMEOUT_SECONDS` | Fetch timeout | `20` | Optional |

**⚠️ Important Security Notes:**

- Never commit `.env` to version control. Add it to `.gitignore`.
- Use environment variables instead of hardcoding secrets.
- Restrict API key access to only the services that need them.

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
