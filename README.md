# DocsAI — Multi-Vertical Agentic RAG Platform

DocsAI is an enterprise-grade AI Document Q&A and Knowledge Graph Platform designed to analyze, index, search, and reason over unstructured documents across multiple business verticals.

Built with a modern **FastAPI** backend, a custom in-process **Hybrid Vector-Graph Database** (NetworkX + FAISS), **Cloudflare Workers AI** for LLM inference and embeddings, and a polished **React/Vite** SPA frontend, the system provides context-aware multi-step reasoning, semantic citations, automated risk scanning, and historical query auditing.

> 🚀 **Live Demo:** [docs-ai-ashen.vercel.app](https://docs-ai-ashen.vercel.app)
> 📐 For a full technical deep-dive, see [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## 🌟 Feature Overview

### 🧠 1. Multi-Vertical Intent Routing

DocsAI natively supports **5 business domains**, each with a dedicated pipeline, chunking strategy, retriever, reranker, and generator:

| Vertical | Use Case | Key Capability |
|---|---|---|
| **Academic / University** | Research papers, journals | Author tracking, citation building, paper topic mapping |
| **Legal / Law** | Contracts, NDAs, agreements | Clause analysis, obligation identification, liability classification |
| **Startup / VC** | Pitch decks, term sheets | Investment trend mapping, contributor matching, term analysis |
| **Compliance** | Regulatory standards, audits | Regulation change detection, compliance gap analysis |
| **HR Policies** | Employee handbooks | Policy Q&A with cited rules, onboarding assistance |

An **AI Intent Router** (powered by Cloudflare Workers AI / Llama 3) automatically classifies user queries into the correct vertical when set to `auto` mode — no manual selection required.

---

### 📸 2. Multimodal 5-Tier OCR Ingestion Pipeline

DocsAI handles scanned, image-heavy, and digital documents through a cascading **5-Tier fallback extraction pipeline**:

| Tier | Technology | Trigger |
|---|---|---|
| **Tier 1** | Native PDF text layer (pdfplumber/PyMuPDF) | Always attempted first |
| **Tier 2** | PyTesseract OCR | Blank or scanned pages detected |
| **Tier 3** | AWS Textract | Complex table or tabular layouts |
| **Tier 4** | OCR.space API | High-accuracy tertiary backup |
| **Tier 5** | Cloudflare Workers AI Vision (Llama 3 Vision) | Visual pages: charts, figures, diagrams → `[VISUAL DESCRIPTION: ...]` |

Tier 5 includes a **hallucination guard** that calculates repetition ratios in model output to auto-reject looping/stuck responses.

---

### ⚡ 3. In-Process Hybrid Vector-Graph Database

Replaces resource-heavy external graph infrastructure (Neo4j, ArangoDB) with a **zero-infrastructure in-process store**:

- **NetworkX Topology:** Stores Tenant → Document → Chunk parent-child relationships, entity extraction linkages (obligations, authors, clauses), and keyword cross-references.
- **FAISS Vector Acceleration:** Embeds text chunks via `nomic-embed-text` (1536-dim) and structures high-speed approximate nearest-neighbor retrieval indexes.
- **Re-Entrant RWLock Safety:** Regulates multi-threaded performance — allows unlimited parallel reads during queries while safely serializing background disk write-backs to `graph_store.json`.
- **Node Types:** TenantNode, DocumentNode, ChunkNode, RedFlagReport, ComplianceAlert, QueryLog, FeedbackNode.

---

### 🔍 4. Advanced Retrieval Stack

Three retrieval strategies assembled per-vertical:

- **VectorRetriever** — Pure FAISS cosine similarity ANN search.
- **GraphRetriever** — NetworkX entity and keyword graph traversal for structural document relationships.
- **HybridRetriever** — Combines vector and graph results using **Reciprocal Rank Fusion (RRF)** for best-of-both precision.

Enhanced by **HyDE (Hypothetical Document Embeddings)** — the LLM generates a hypothetical answer document before embedding, improving retrieval accuracy by **+15–30%**. HyDE results are Redis-cached (30-min TTL) per (vertical, query hash).

---

### 🏆 5. Multi-Stage Reranking

Post-retrieval chunk scoring for result quality improvement:

- **CrossEncoderReranker** — sentence-transformers cross-encoder model (~80MB), loaded once as a singleton at startup. Used for `compliance` and `university` verticals.
- **VerticalReranker** — Domain-keyword boosted scoring. Used for `law` and `startup` verticals.
- **NoReranker** — Pass-through for HR vertical (vector retrieval quality is sufficient).

---

### 🤖 6. Multi-Step ReAct Agent Orchestrator

For cross-document, comparative, or analytical queries, DocsAI triggers a fully autonomous **plan → execute → synthesize** cycle:

- **AgentPlanner:** Uses Cloudflare LLM to decompose user prompts into a structured JSON list of dependent tool steps.
- **AgentExecutor:** Resolves variable dependencies (`$step_id` references) sequentially, calls appropriate pipeline actions (`search_documents`, `compare_documents`, `get_document_metadata`, `llm_answer`), and records execution traces.
- **Synthesis Engine:** Combines intermediate tool responses and streams a unified comparative response complete with dynamic source citations.
- Supports real-time **token-by-token streaming** via WebSocket with live step progress updates.

---

### 🚀 7. Asynchronous Background Ingestion Job Queue

- Document uploads are accepted instantly and submitted to a background `asyncio` job queue (Redis-backed if available).
- Returns a `job_id` immediately — clients poll `GET /jobs/{job_id}` for status.
- The ingestion pipeline (OCR → chunking → embedding → graph ingestion → post-processing) runs fully off the request thread.

---

### 🧬 8. Two-Phase AI Document Classifier Agent

Before ingestion, DocsAI auto-detects the correct vertical using a dedicated `DocumentClassifierAgent`:

- **Phase 1 — Summarisation:** Reads a document preview and extracts: document type, main topics, entities, and intended audience.
- **Phase 2 — Classification:** Classifies into one of 5 verticals, generates a human-readable AI suggestion paragraph with confidence level and alternative vertical.

Result fields: `vertical`, `confidence`, `ai_suggestion`, `alternative_vertical`, `classification_notes`, `summary`, `meta`.

---

### 🚩 9. Automated Red-Flag Scanner (Law & Startup)

Triggered automatically after every `law` or `startup` document upload:

Scans **10 risk categories** across all document chunks (processed in batches of 60 to avoid context window overflow):

1. Uncapped Liability
2. Unilateral Termination
3. Auto-Renewal
4. Broad Indemnification
5. One-Sided IP Assignment
6. Missing Governing Law
7. Non-Standard / Punitive Damages
8. Unlimited Audit Rights
9. Perpetual License Grants
10. Excessive Non-Compete

Each detected flag includes: `type`, `severity` (HIGH/MEDIUM/LOW), `clause_ref`, `page`, `excerpt`, and `recommendation`. The merged report is stored as a `RedFlagReport` node in the graph store.

---

### 🛡️ 10. Automated Compliance Regulation Change Monitor

Triggered automatically after every `compliance` document upload:

- Compares the newly uploaded regulation against all existing compliance documents for the tenant.
- Identifies changed articles/sections, flags outdated compliance positions, and generates specific action items.
- Stores results as a `ComplianceAlert` node with severity, change count, and full report JSON.
- Accessible via `GET /compliance/alerts`.

---

### 🎯 11. Semantic Query Cache

- **Backend:** SQLite (`semantic_cache.db`) — zero external infrastructure.
- **Hit Condition:** Cosine similarity ≥ 0.95 between incoming query vector and stored cache entries.
- **Cache Hit Rate:** ~30–40% of repeated/similar enterprise queries are served instantly.
- **Invalidation:** Automatically cleared per-tenant on any document upload or delete.
- Cached responses include `_cache_hit: true` and `_cache_similarity` metadata for debugging.

---

### 📊 12. Analytics Dashboard & Knowledge Graph Visualizer

- **Interactive Knowledge Graph:** ForceGraph2D visualization of the full document-chunk-entity graph rendered on an engineering-grade dark coordinate grid with radial glows.
- **Dashboard KPIs:** Total documents, chunk count, total queries, average latency (ms), not-found rate (%).
- **Per-Vertical Latency Breakdown:** Sorted performance metrics per pipeline.
- **Top Unanswered Queries:** Top 10 repeated questions the system couldn't answer — for active learning.
- **Recent Query Audit Log:** Last 50 queries with confidence scores, latency, and answer previews.

---

### 💬 13. Persistent Chat History (MongoDB Atlas)

- Every chat message and query log is synced to **MongoDB Atlas** (`chat_history` collection).
- **Automatic JSON Fallback DB:** If MongoDB is unavailable, `JSONFallbackClient` stores data locally in `/backend/data/json_db/` — no data loss.
- History is retrieved and displayed per-tenant per-vertical in the **History** page.
- Supports clear-history by tenant + vertical scope.

---

### 👍 14. Active Learning — User Feedback Loop

- Users can rate any response **thumbs up / thumbs down** directly in the Chat interface.
- `POST /analytics/feedback` stores `FeedbackNode` in GraphStore with optional comment and chunk IDs.
- `GET /analytics/feedback/stats` returns cumulative ratings grouped by vertical.
- Designed to inform future retrieval fine-tuning and prompt optimization.

---

### 🔐 15. Firebase Google Identity Authentication

- **Google OAuth Single Sign-On:** Firebase Web SDK popup-based authentication flow.
- Firebase JWT UID is used as the `tenant_id` for data isolation.
- **Developer Mode Fallback:** Falls back to a simulated `DevUser` session when Firebase keys are absent — enabling offline local development with zero configuration.

---

### 🛡️ 16. Input Security Guardrails

Applied at the API level before any LLM call or pipeline dispatch:

- **Jailbreak Prevention:** Regex patterns block prompts attempting to override system instructions (`ignore previous instructions`, `reveal system prompt`, etc.).
- **Content Sanitization:** Flags and blocks toxic keywords, malicious code execution requests, and authentication bypass attempts.
- Violations are logged as warnings; no query ever reaches the RAG pipeline.

---

### 🌊 17. Real-Time WebSocket Streaming

- Both standard RAG queries and Agent queries support token-by-token streaming via WebSocket.
- **StreamingJsonExtractor** parses the LLM JSON stream in real-time, extracting the `answer` field character-by-character for smooth UI rendering.
- Agent mode streams live step progress messages (`"Decomposing user request..."`, `"Executing step 2 of 3..."`) before the final synthesized answer.

---

### 🔄 18. Document Version Management (Supersede)

- `POST /documents/{doc_id}/supersede` marks an old document as superseded by a new version.
- Superseded documents are excluded from retrieval automatically.
- Enables safe document update workflows without breaking existing graph topology.
- Semantic cache is invalidated automatically on supersede.

---

### 🎨 19. Premium Light/Dark Theme UI

- **Glassmorphism design system** using HSL CSS variables.
- Subtle background grid mesh and micro-animations throughout.
- Interactive Knowledge Graph Visualizer with radial glows.
- Responsive sidebar navigation with vertical-color-coded badges.
- Toast notification system for upload/query feedback.

---

## 🛠️ Environment Setup

Create a `.env` file in the root directory by copying the template:

```powershell
Copy-Item .env.example .env
```

Define the configuration parameters:

```env
# Cloudflare Workers AI Credentials
CF_ACCOUNT_ID=your_cloudflare_account_id
CF_API_TOKEN=your_cloudflare_api_token

# Database Connections
MONGODB_URI=your_mongodb_atlas_connection_string
MONGODB_DB=job_agent
MONGODB_COLLECTION=chat_history

# Firebase Configuration (Sign-In with Google)
VITE_FIREBASE_API_KEY=your-firebase-api-key
VITE_FIREBASE_AUTH_DOMAIN=your-auth-domain.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project-id
VITE_FIREBASE_STORAGE_BUCKET=your-project-id.appspot.com
VITE_FIREBASE_MESSAGING_SENDER_ID=your-sender-id
VITE_FIREBASE_APP_ID=your-app-id

# Local Configuration
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_WS_BASE_URL=ws://localhost:8000/api/v1
VITE_TENANT_ID=tenant-123
```

---

## 🚀 Running Locally

### Backend Server

Install Python dependencies and run the FastAPI server (uvicorn watches only `/app` to prevent file-lock reloading cycles):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload --reload-dir app
```

### Frontend Web Client

Run Vite dev server locally:

```powershell
cd frontend
npm install
npm run dev
```

*Access the application at `http://localhost:5173/`.*

---

## 🐳 Docker

```powershell
docker-compose up --build
```

---

## 📐 System Architecture

For a complete technical breakdown of all layers, module maps, pipeline flows, API surface, and design decisions, see **[ARCHITECTURE.md](./ARCHITECTURE.md)**.

---

## 📦 Tech Stack Summary

| Layer | Technology |
|---|---|
| Frontend | Vite + React 18, CSS (glassmorphism), ForceGraph2D |
| Auth | Firebase Web SDK (Google OAuth) |
| Backend | FastAPI + Uvicorn (Python 3.11+) |
| LLM / Embeddings | Cloudflare Workers AI (Llama 3, Nomic-embed-text) |
| Graph DB | NetworkX + FAISS (in-process) |
| History / Audit | MongoDB Atlas + JSON Fallback |
| Semantic Cache | SQLite (local) |
| Job Queue | asyncio + Redis (optional) |
| OCR | PyTesseract + AWS Textract + OCR.space + CF Vision |
| Reranking | sentence-transformers CrossEncoder |
| Containerization | Docker + docker-compose |
