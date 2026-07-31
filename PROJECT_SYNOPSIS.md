# PROJECT SYNOPSIS

---

<div align="center">

## DocsAI — Enterprise Agentic Document Intelligence Platform

**An AI-Powered Multi-Vertical Document Analysis, Knowledge Graph & Reasoning System**

---

🌐 **Live Demo:** [docs-ai-ashen.vercel.app](https://docs-ai-ashen.vercel.app)
📁 **Repository:** [github.com/shoyo44/DocsAI](https://github.com/shoyo44/DocsAI)

---

</div>

---

## 1. Project Title

**DocsAI — Enterprise Agentic Document Intelligence Platform**

---

## 2. Project Category

Artificial Intelligence · Natural Language Processing · Information Retrieval · Full-Stack Web Application

---

## 3. Team / Author

| Field | Details |
|---|---|
| **Project Type** | Individual / Team Final Year Project |
| **Domain** | AI / Machine Learning / NLP |
| **Tech Stack** | Python · FastAPI · React · Cloudflare Workers AI · NetworkX · FAISS · MongoDB |

---

## 4. Abstract

DocsAI is an enterprise-grade, AI-powered document intelligence platform that enables organizations to extract accurate, context-aware insights from large volumes of unstructured documents across five business verticals — Legal, HR, Compliance, Startup/VC, and Academic Research.

The platform combines **Retrieval-Augmented Generation (RAG)**, an **in-process hybrid vector-graph database**, a **5-tier multimodal OCR ingestion pipeline**, and a **multi-step ReAct agent orchestrator** to answer complex document queries with precise source citations, automated risk detection, and real-time streaming responses.

Unlike conventional chatbots or keyword search tools, DocsAI reasons across documents, automatically scans for legal risk clauses, monitors regulatory changes, classifies documents by domain, and maintains a persistent audit trail — all on a single containerized deployment without requiring external GPU infrastructure or dedicated graph database servers.

---

## 5. Problem Statement

Organizations across industries face a critical challenge: vast quantities of mission-critical information are locked inside unstructured documents — contracts, research papers, compliance regulations, HR handbooks, and investor pitch decks — that are difficult, slow, and expensive to analyze manually.

Existing solutions fall short in the following ways:

- **Keyword search** lacks semantic understanding and misses context-dependent meaning.
- **Generic LLM chatbots** hallucinate facts and cannot ground answers in specific source documents.
- **Manual review** is time-consuming, error-prone, and does not scale across large document repositories.
- **Domain-agnostic RAG tools** apply the same chunking, retrieval, and response strategies to all document types, ignoring the structural differences between a legal contract and an academic paper.
- **Enterprise NLP platforms** (e.g., AWS Comprehend, Google Document AI) are expensive, require significant setup, and lack cross-document reasoning capabilities.

There is a clear need for a system that can: ingest diverse document types automatically, understand domain-specific structure, answer natural language queries with cited evidence, detect risks proactively, and reason across multiple documents — all within a cost-effective, self-contained deployment.

---

## 6. Objective

The core objectives of DocsAI are:

1. **Build a multi-vertical document intelligence platform** capable of serving five distinct business domains with domain-aware ingestion, retrieval, and response generation pipelines.

2. **Implement a production-grade RAG system** enhanced with HyDE query expansion, hybrid vector-graph retrieval (Reciprocal Rank Fusion), and multi-stage reranking for high-accuracy document Q&A.

3. **Develop an agentic multi-step reasoning engine** (plan → execute → synthesize) capable of answering complex, cross-document analytical queries autonomously.

4. **Automate proactive document intelligence** — including legal red-flag scanning (10 risk categories), compliance regulation change monitoring, and AI-based document type classification.

5. **Achieve enterprise-grade infrastructure efficiency** — replacing external graph databases (Neo4j) and GPU servers with an in-process hybrid store (NetworkX + FAISS) deployable on a single container.

6. **Deliver a polished, real-time user experience** via WebSocket token streaming, a glassmorphism React UI, and an interactive knowledge graph visualizer.

---

## 7. Methodology

### 7.1 Document Ingestion — 5-Tier Multimodal OCR Pipeline

All uploaded documents are processed through a cascading extraction pipeline:

| Tier | Technology | Purpose |
|---|---|---|
| 1 | Native PDF text layer (PyMuPDF) | Digital PDFs with selectable text |
| 2 | PyTesseract OCR | Scanned or blank pages |
| 3 | AWS Textract | Complex tables and layouts |
| 4 | OCR.space API | High-accuracy tertiary fallback |
| 5 | Cloudflare Workers AI Vision (Llama 3) | Charts, figures, diagrams → text descriptions |

Tier 5 includes a hallucination guard that detects and rejects looping/repetitive model outputs using a repetition ratio check.

### 7.2 Vertical-Specific Chunking

Documents are split using domain-aware indexers:

| Vertical | Indexer | Strategy |
|---|---|---|
| Law | ClauseIndexer | Clause-boundary splitting |
| Compliance | ArticleIndexer | Article/section splitting |
| HR | TopicIndexer | Topic-aware paragraph splitting |
| Startup | TermIndexer | Term-sheet aware splitting |
| University | SectionIndexer | Academic section splitting |

### 7.3 Hybrid Vector-Graph Storage

Chunks are embedded using **Nomic-embed-text** (1536-dim vectors via Cloudflare Workers AI) and stored in a dual-engine in-process database:

- **NetworkX** — maintains document topology, entity linkages, and keyword cross-references.
- **FAISS** — enables high-speed approximate nearest-neighbor vector search.
- **RW-Lock** — allows unlimited parallel reads; serializes writes for thread safety.

### 7.4 Retrieval Pipeline

Queries are enhanced with **HyDE** (Hypothetical Document Embedding): the LLM generates a hypothetical answer document, whose embedding is used for retrieval instead of the raw query vector — improving recall by 15–30%. Three retrieval strategies serve different verticals:

- **VectorRetriever** — FAISS cosine similarity ANN search.
- **GraphRetriever** — NetworkX entity and keyword traversal.
- **HybridRetriever** — Reciprocal Rank Fusion (RRF) combining both.

Results are reranked using:
- **CrossEncoderReranker** (sentence-transformers) for compliance and university.
- **VerticalReranker** (keyword-boosted domain scoring) for law and startup.
- **NoReranker** (pass-through) for HR.

### 7.5 Multi-Step ReAct Agent

For complex analytical queries:

1. **AgentPlanner** — LLM decomposes the query into a structured JSON plan of dependent tool steps.
2. **AgentExecutor** — Resolves variable dependencies and calls tools: `search_documents`, `compare_documents`, `get_document_metadata`, `llm_answer`.
3. **Synthesis Engine** — Combines step results via LLM and streams the final answer token-by-token.

### 7.6 Automated Intelligence Features

| Feature | Vertical | Trigger |
|---|---|---|
| Red-Flag Scanner (10 categories) | Law, Startup | Auto on upload |
| Compliance Change Monitor | Compliance | Auto on upload |
| Two-Phase Document Classifier | All | Pre-ingestion |
| Semantic Cache (cosine ≥ 0.95) | All | Every query |
| Active Learning Feedback | All | User interaction |

### 7.7 System Architecture Summary

```
Client (React/Vite)
    → Firebase Authentication
    → FastAPI Gateway (REST + WebSocket)
        → AI Intent Router (auto-vertical)
        → Guardrails (jailbreak/toxicity check)
        → Semantic Cache (SQLite)
        → RAG Pipeline (Indexer → Retriever → Reranker → Generator)
        → Agent Orchestrator (Planner → Executor → Synthesizer)
    → In-Process GraphStore (NetworkX + FAISS)
    → MongoDB Atlas / JSON Fallback (History & Audit)
    → Cloudflare Workers AI (LLM + Embeddings)
```

---

## 8. Expected Outcome

1. **Accurate, Cited Document Q&A** across 5 verticals with confidence scoring (HIGH/MEDIUM/LOW), source chunk citations, and page references — with response latency under 3 seconds for cached queries and under 10 seconds for full pipeline execution.

2. **Automated Risk Detection** — legal and startup documents receive an automated 10-category red-flag report (risk level: HIGH/MEDIUM/LOW, clause references, recommendations) without any user action.

3. **Compliance Intelligence** — newly uploaded regulations are automatically compared against existing documents, with changed articles, affected policies, and action items surfaced as compliance alerts.

4. **Agentic Cross-Document Reasoning** — multi-step agent queries (e.g., "Compare our NDA obligations against GDPR Article 6 requirements") are decomposed, executed across verticals, and synthesized into a unified answer.

5. **30–40% Query Cache Hit Rate** — the semantic cache is expected to serve roughly one-third of enterprise queries instantly, significantly reducing LLM API costs and average response latency.

6. **Interactive Knowledge Graph** — a live ForceGraph2D visualization of the full document-chunk-entity relationship graph, enabling users to explore their document knowledge base visually.

7. **Zero External Graph DB Infrastructure** — the entire platform runs on a single Docker container with no Neo4j, no external vector store, and no GPU — demonstrating that production-grade agentic RAG is achievable with minimal infrastructure.

8. **Real-Time Streaming UX** — users receive token-by-token streaming responses via WebSocket for both RAG and agent queries, with live step-progress updates during agent execution.

---

## 9. Key Features Summary

| # | Feature | Description |
|---|---|---|
| 1 | Multi-Vertical Intent Routing | 5 domains + AI auto-classifier |
| 2 | 5-Tier Multimodal OCR Pipeline | Native → Tesseract → Textract → OCR.space → CF Vision |
| 3 | In-Process Hybrid Vector-Graph DB | NetworkX + FAISS, no external DB |
| 4 | HyDE Query Expansion | +15–30% retrieval accuracy |
| 5 | Hybrid RRF Retrieval | Vector + Graph fusion |
| 6 | Multi-Stage Reranking | CrossEncoder, VerticalReranker, NoReranker |
| 7 | ReAct Agent Orchestrator | Plan → Execute → Synthesize |
| 8 | Async Background Job Queue | Non-blocking ingestion |
| 9 | Two-Phase Document Classifier | Auto vertical detection |
| 10 | Red-Flag Scanner | 10 legal/startup risk categories |
| 11 | Compliance Change Monitor | Auto regulation diff alerts |
| 12 | Semantic Cache (cosine ≥ 0.95) | Instant repeat query responses |
| 13 | Analytics Dashboard | KPIs, latency, unanswered queries |
| 14 | Knowledge Graph Visualizer | ForceGraph2D interactive view |
| 15 | MongoDB Chat History | Persistent audit log + JSON fallback |
| 16 | Active Learning Feedback | Thumbs up/down per response |
| 17 | Firebase Google Auth | OAuth SSO + dev-mode bypass |
| 18 | Input Security Guardrails | Jailbreak + toxicity regex guards |
| 19 | Real-Time WebSocket Streaming | Token-by-token live responses |

---

## 10. Technology Stack

| Layer | Technology |
|---|---|
| **Frontend** | Vite, React 18, CSS (Glassmorphism), ForceGraph2D |
| **Authentication** | Firebase Web SDK (Google OAuth 2.0) |
| **Backend** | FastAPI, Uvicorn, Python 3.11+ |
| **LLM & Embeddings** | Cloudflare Workers AI (Llama 3, Nomic-embed-text 1536-dim) |
| **Graph Database** | NetworkX (topology) + FAISS (vector index) — in-process |
| **Persistent History** | MongoDB Atlas + Local JSON Fallback DB |
| **Semantic Cache** | SQLite (local, zero-config) |
| **Job Queue** | asyncio + Redis (optional) |
| **OCR** | PyTesseract, AWS Textract, OCR.space, CF Vision (Llama 3 Vision) |
| **Reranking** | sentence-transformers CrossEncoder |
| **NLP / Entity Extraction** | spaCy (en_core_web_sm) |
| **Containerization** | Docker + docker-compose |
| **Deployment** | Vercel (Frontend CDN) + Docker (Backend) |

---

## 11. System Modules

```
DocsAI/
├── frontend/              ← React SPA (6 pages: Chat, Vault, Analytics, History, Settings, Login)
└── backend/
    ├── app/api/           ← REST + WebSocket route handlers
    ├── app/agent/         ← ReAct Agent (Planner, Executor, Synthesizer)
    ├── app/core/          ← Pipeline factory, HyDE, guardrails, semantic cache
    ├── app/graph/         ← GraphStore, OCR pipeline, document ingestion
    ├── app/features/      ← Red-flag scanner, compliance monitor, analytics, classifier
    ├── app/indexers/      ← Per-vertical text chunkers
    ├── app/retrievers/    ← Vector, Graph, Hybrid retrievers
    ├── app/rerankers/     ← CrossEncoder, VerticalReranker, NoReranker
    ├── app/generators/    ← Risk, Compliance, Friendly, Academic response generators
    └── app/config/        ← Vertical configuration parameters
```

---

## 12. Scope & Limitations

### In Scope
- PDF document ingestion and processing (digital + scanned)
- Five business verticals with full pipeline support
- Natural language Q&A with source citations
- Automated post-ingestion intelligence (red flags, compliance alerts)
- Real-time streaming responses
- Analytics and audit logging
- Single-tenant and multi-tenant (via tenant_id isolation) support

### Current Limitations
- **File types:** Only PDF documents are currently supported (DOCX, PPTX planned)
- **Languages:** English-only document processing
- **OCR accuracy:** Tier 2–5 fallbacks increase latency for highly complex scanned documents
- **Graph persistence:** GraphStore is in-process; very large corpora (>100K chunks) may require migration to a dedicated vector database
- **Redis:** Optional — job queue degrades gracefully to asyncio-only without Redis

---

## 13. Future Enhancements

- [ ] DOCX, PPTX, and Excel document support
- [ ] Multi-language document processing (multilingual embeddings)
- [ ] Fine-tuned vertical-specific embedding models
- [ ] Role-based access control (RBAC) for team workspaces
- [ ] Scheduled compliance monitoring (cron-based automatic re-scan)
- [ ] Export reports as PDF (red-flag reports, compliance alerts)
- [ ] Integration with Slack / Microsoft Teams for alert delivery
- [ ] Reinforcement Learning from Human Feedback (RLHF) using the feedback loop data

---

## 14. References

1. Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 2020.
2. Gao, L., et al. (2022). *Precise Zero-Shot Dense Retrieval without Relevance Labels (HyDE).* ACL 2023.
3. Nogueira, R., & Cho, K. (2019). *Passage Re-ranking with BERT.* arXiv:1901.04085.
4. Yao, S., et al. (2022). *ReAct: Synergizing Reasoning and Acting in Language Models.* ICLR 2023.
5. Cormack, G.V., et al. (2009). *Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods.* SIGIR 2009.
6. Cloudflare Workers AI Documentation — [developers.cloudflare.com/workers-ai](https://developers.cloudflare.com/workers-ai)
7. FastAPI Documentation — [fastapi.tiangolo.com](https://fastapi.tiangolo.com)
8. FAISS Documentation — [faiss.ai](https://faiss.ai)

---

<div align="center">

*DocsAI — Enterprise Agentic Document Intelligence Platform*
🌐 [docs-ai-ashen.vercel.app](https://docs-ai-ashen.vercel.app) · 📁 [github.com/shoyo44/DocsAI](https://github.com/shoyo44/DocsAI)

</div>
