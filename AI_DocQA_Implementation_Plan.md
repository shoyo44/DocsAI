# AI Document Q&A System
## Neo4j + Modular RAG — Multi-Vertical Platform
### Instructions & Workflow Guide | Version 1.0 · May 2026

**Target Verticals:** Law Firms · Compliance · HR Departments · Startups · Universities · + Extensible

---

## 1. Executive Summary

This document serves as the comprehensive instructions and workflow guide for building the AI Document Q&A System — a multi-vertical, enterprise-grade platform that enables professionals to query large document collections in plain English and receive precise, cited answers.

The system is built on two architectural pillars:

- **Neo4j Knowledge Graph** — stores documents, chunks, entities, and their relationships, enabling cross-document graph traversal that flat vector databases cannot support.
- **Modular RAG Pipeline** — each pipeline stage (indexer, retriever, reranker, generator) is a swappable component, allowing each vertical to use the right combination without rebuilding the engine.

### Target Verticals at Launch

| Vertical   | Primary Use Case                  | Killer Feature                  | Retrieval Strategy                   |
|------------|-----------------------------------|---------------------------------|--------------------------------------|
| Law firm   | Contract review, due diligence    | Red-flag clause detector        | GraphRetriever + RiskGenerator       |
| Compliance | Regulatory document querying      | Version-aware doc warnings      | HybridRetriever + CrossEncoder       |
| HR         | Policy & handbook lookup          | Role-filtered doc access        | VectorRetriever + FriendlyGenerator  |
| Startup    | Investor & vendor contracts       | Term sheet comparator           | GraphRetriever + RiskGenerator       |
| University | Research paper Q&A                | Cross-paper synthesis           | HybridRetriever + AcademicGenerator  |

---

## 2. System Architecture

### 2.1 Three-Layer Design

The system is organised into three layers that are completely independent of each other. A new vertical can be added without touching the core engine, and the core engine can be upgraded without breaking any vertical configuration.

- **Layer 1 — Vertical Config Layer:** defines the chunking strategy, system prompt, retrieval method, and output schema for each industry. A Python dict per vertical.
- **Layer 2 — Shared RAG Engine:** ingestion pipeline, Neo4j vector + graph search, reranking, LLM generation. Built once, powers all verticals.
- **Layer 3 — Storage & Infrastructure:** Neo4j (graph + vector), S3/Supabase (PDF storage), Redis (query cache), FastAPI (API layer).

### 2.2 Neo4j Graph Schema

Neo4j is the core innovation. Unlike a flat vector database, Neo4j stores relationships between entities across documents — enabling queries no other system can answer.

| Node Type  | Key Properties                          | Purpose                                                              |
|------------|-----------------------------------------|----------------------------------------------------------------------|
| Tenant     | id, name, vertical, settings            | Org-level isolation. All queries scoped to tenant_id.               |
| Document   | id, name, version, superseded_by        | Tracks document versions for compliance warnings.                    |
| Chunk      | text, embedding, page, tenant_id        | The retrievable unit. Stores 1536-dim vector embedding.             |
| Entity     | canonical_name, type                    | Parties, clauses, concepts. Deduplicated across documents.           |
| Regulation | id, version, status                     | External regulation nodes linked to compliance chunks.               |
| User       | id, role, permitted_doc_ids[]           | Per-user access control list for document permissions.               |
| QueryLog   | query, chunk_ids, timestamp             | Full audit trail of every query for every tenant.                    |

### 2.3 Key Relationships

- `(Tenant)-[:OWNS]->(Document)` — scopes all document access to an organisation.
- `(Document)-[:HAS_CHUNK]->(Chunk)` — links each document to its indexed chunks.
- `(Chunk)-[:NEXT_CHUNK]->(Chunk)` — sequential chain enabling context expansion around retrieved chunks.
- `(Chunk)-[:MENTIONS]->(Entity)` — named entity links enabling cross-document entity search.
- `(Entity)-[:RELATED_TO]->(Entity)` — connects the same party or concept across different documents.
- `(Document)-[:GOVERNED_BY]->(Regulation)` — links compliance documents to their governing regulation nodes.
- `(User)-[:CAN_ACCESS]->(Document)` — fine-grained per-user document permission control.

### 2.4 Neo4j Indexes Required

Run these Cypher statements on Neo4j 5.x before ingesting any documents:

```cypher
CREATE VECTOR INDEX chunk_embeddings IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS { indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}};

CREATE FULLTEXT INDEX chunk_text IF NOT EXISTS
FOR (c:Chunk) ON EACH [c.text];

CREATE CONSTRAINT tenant_chunk IF NOT EXISTS
FOR (c:Chunk) REQUIRE (c.tenant_id, c.id) IS UNIQUE;

CREATE CONSTRAINT entity_name IF NOT EXISTS
FOR (e:Entity) REQUIRE e.canonical_name IS UNIQUE;
```

---

## 3. Modular RAG Pipeline

Each stage of the pipeline is an abstract base class with multiple interchangeable implementations. The RAGPipeline orchestrator accepts any combination of these components, making vertical customisation a matter of configuration, not code.

### 3.1 Pipeline Stages

| Stage     | Interface Method                              | Implementations                                                                    | When to Use Which                                                                         |
|-----------|-----------------------------------------------|------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------|
| Indexer   | `chunk(text, metadata)` / `index(chunks, driver)` | ClauseIndexer, ArticleIndexer, TopicIndexer, TermIndexer, SectionIndexer       | Choose based on document structure. Clauses for legal, articles for regulations, sections for papers. |
| Retriever | `retrieve(embedding, driver, tenant_id, top_k)` | GraphRetriever, HybridRetriever, VectorRetriever                                | Graph for cross-doc entity traversal. Hybrid when keyword match matters. Vector for simple lookup. |
| Reranker  | `rerank(query, chunks)`                       | CrossEncoderReranker, VerticalReranker, NoReranker                                 | CrossEncoder for highest accuracy. VerticalReranker for domain term boosting. NoReranker for speed. |
| Generator | `generate(query, chunks, config)`             | RiskGenerator, ComplianceGenerator, FriendlyGenerator, AcademicGenerator, CitationGenerator | Each produces a different structured output schema tailored to the vertical's needs. |

### 3.2 Vertical Pipeline Configurations

| Vertical   | Indexer         | Retriever        | Reranker          | Generator + Output Schema                                                         |
|------------|-----------------|------------------|-------------------|-----------------------------------------------------------------------------------|
| Law        | ClauseIndexer   | GraphRetriever   | VerticalReranker  | RiskGenerator → answer + clause citations + risk level HIGH/MED/LOW + red_flags[] |
| Compliance | ArticleIndexer  | HybridRetriever  | CrossEncoder      | ComplianceGenerator → answer + regulation_id + compliance_status + version_warning |
| HR         | TopicIndexer    | VectorRetriever  | NoReranker        | FriendlyGenerator → answer + policy_section + applies_to[]                        |
| Startup    | TermIndexer     | GraphRetriever   | VerticalReranker  | RiskGenerator → plain_english + founder_risk + market_standard comparison         |
| University | SectionIndexer  | HybridRetriever  | CrossEncoder      | AcademicGenerator → answer + citations[author, year, section] + confidence + contradictions[] |

### 3.3 GraphRetriever — the Neo4j Superpower

This is the retriever that makes Neo4j worth it. After vector similarity search, it traverses NEXT_CHUNK and MENTIONS relationships to automatically pull in context that semantic search would miss:

```cypher
CALL db.index.vector.queryNodes('chunk_embeddings', $top_k, $embedding)
YIELD node AS chunk, score
WHERE chunk.tenant_id = $tenant_id
WITH chunk, score
OPTIONAL MATCH (chunk)-[:NEXT_CHUNK]->(next)
OPTIONAL MATCH (prev)-[:NEXT_CHUNK]->(chunk)
OPTIONAL MATCH (chunk)-[:MENTIONS]->(entity)<-[:MENTIONS]-(related)
RETURN chunk, score, next, prev, collect(DISTINCT related) AS related_chunks
ORDER BY score DESC LIMIT $top_k
```

Cross-document entity query (impossible in any flat vector DB):

```cypher
MATCH (t:Tenant {id: $tenant_id})-[:OWNS]->(doc:Document)
      -[:HAS_CHUNK]->(chunk:Chunk)
      -[:MENTIONS]->(entity:Entity {canonical_name: "Acme Corp"})
RETURN doc.name, chunk.page, chunk.text
ORDER BY doc.name, chunk.page
```

---

## 4. Per-Vertical Feature Specifications

### 4.1 Law Firm — Contract Review & Due Diligence

| Feature         | Specification                                                                                                                                              |
|-----------------|------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Chunking        | Split on §, Article, Section, Clause markers. Preserve numbering in chunk metadata. Chunk size ~400 tokens with 80-token overlap.                         |
| System prompt   | Answer ONLY from retrieved clauses. Always cite clause number and page. Flag each answer HIGH / MEDIUM / LOW risk. Never interpret beyond what is written. |
| Red-flag detector | Auto-scan on upload: flag unusual indemnity clauses, uncapped liability, unilateral termination rights, automatic renewal without notice.                |
| Output schema   | `answer` (str), `citations` [{clause, page}], `risk_level` (HIGH\|MED\|LOW), `red_flags` [str].                                                          |
| Access control  | Partners see all documents. Associates see only assigned matters. Clients see only their own contracts.                                                    |
| Cross-doc query | Graph traversal: find all clauses across all contracts that mention the same counterparty or defined term.                                                 |

### 4.2 Compliance — Regulatory Document Querying

| Feature          | Specification                                                                                                                                                    |
|------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Chunking         | Split by Article / Regulation number. Tag each chunk with version metadata and effective date.                                                                   |
| Version awareness | When a regulation is superseded, set `superseded: true` on old chunks. System warns users when an answer comes from an outdated document version.              |
| System prompt    | Map every answer to a specific regulation ID and section. State clearly: COMPLIANT / NON-COMPLIANT / UNCLEAR. Flag if document version may be outdated.          |
| Output schema    | `answer`, `regulation_id`, `section`, `compliance_status` (COMPLIANT\|NON-COMPLIANT\|UNCLEAR), `version_warning` (bool).                                        |
| Hybrid retrieval | Compliance teams often search by exact regulation number (keyword) and by concept (semantic). HybridRetriever runs both and merges results.                      |

### 4.3 HR — Policy Manuals & Employee Handbooks

| Feature        | Specification                                                                                                                                                       |
|----------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Chunking       | Split by policy topic. Tag chunks with `employee_type` metadata (full-time, contractor, executive, intern).                                                        |
| Role filtering | Junior staff cannot retrieve executive compensation documents. HR admins see all. Enforced at retrieval time via CAN_ACCESS graph relationships.                    |
| System prompt  | Answer as a friendly HR assistant. Be clear, jargon-free, and always cite the exact policy section. If answer differs by employee type, say so explicitly.          |
| Output schema  | `answer`, `policy_section`, `applies_to` [employee_type], `related_policies` [str].                                                                                |
| Tone           | Plain English. No legalese. FriendlyGenerator uses a warm, accessible system prompt unlike the clinical law/compliance generators.                                  |

### 4.4 Startup — Investor & Vendor Contracts

| Feature             | Specification                                                                                                                                          |
|---------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------|
| Chunking            | Split by defined term. Preserve cross-references between terms (e.g., "Liquidation Preference" references "Participation Rights").                    |
| System prompt       | Explain in plain English, not legalese. Flag founder-unfriendly terms explicitly. Compare with market standard if known.                              |
| Term comparator     | Graph traversal: compare the same defined term (e.g., valuation cap) across two or more investor agreements side by side.                             |
| Output schema       | `answer`, `plain_english`, `founder_risk` (HIGH\|MED\|LOW), `market_standard` (str), `related_terms` [str].                                          |
| VerticalReranker boosts | valuation, pro-rata, drag-along, liquidat, dilut, anti-dilution, ratchet.                                                                       |

### 4.5 University — Research Paper Q&A

| Feature            | Specification                                                                                                                                                   |
|--------------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Chunking           | Split by section. Preserve abstract and references section as dedicated chunk types. Larger chunk size (~700 tokens) since papers need more context per passage.|
| System prompt      | Answer with academic precision. Always cite author, year, section for every claim. Distinguish between what papers claim vs. what they empirically prove.      |
| Cross-paper synthesis | Graph traversal through MENTIONS and RELATED_TO: find where multiple papers agree, disagree, or build on each other.                                       |
| Output schema      | `answer`, `citations` [{author, year, section}], `confidence` (HIGH\|MED\|LOW), `contradictions` [str], `related_papers` [str].                               |
| Chunk size         | 700 tokens with 120-token overlap — larger than other verticals because academic arguments span multiple sentences.                                             |

---

## 5. Project File Structure

The codebase is organised so each vertical's components live in their own module, while the shared engine and infrastructure are fully separate. Adding a new vertical means adding files to `indexers/`, `retrievers/` (if needed), and `generators/` — nothing else changes.

| Path                              | Purpose                                                                         |
|-----------------------------------|---------------------------------------------------------------------------------|
| `app/core/pipeline.py`            | RAGPipeline orchestrator — query() method wires all 4 stages together.         |
| `app/core/interfaces.py`          | Abstract base classes: BaseIndexer, BaseRetriever, BaseReranker, BaseGenerator.|
| `app/core/factory.py`             | `build_pipeline(vertical)` — returns the right RAGPipeline for each vertical.  |
| `app/indexers/clause.py`          | ClauseIndexer — splits on §, Article, Section markers for law.                 |
| `app/indexers/article.py`         | ArticleIndexer — splits on regulation article numbers for compliance.           |
| `app/indexers/topic.py`           | TopicIndexer — splits by policy topic for HR.                                  |
| `app/indexers/term.py`            | TermIndexer — splits by defined term for startup contracts.                    |
| `app/indexers/section.py`         | SectionIndexer — splits by section with abstract preservation for university.  |
| `app/retrievers/graph.py`         | GraphRetriever — Neo4j vector search + NEXT_CHUNK/MENTIONS traversal.          |
| `app/retrievers/hybrid.py`        | HybridRetriever — merges vector similarity and fulltext keyword results.        |
| `app/retrievers/vector.py`        | VectorRetriever — pure vector similarity, simple and fast.                     |
| `app/rerankers/cross_encoder.py`  | CrossEncoderReranker — highest accuracy, uses a cross-encoder model.           |
| `app/rerankers/vertical.py`       | VerticalReranker — boosts chunks containing domain-specific terms.             |
| `app/rerankers/noop.py`           | NoReranker — pass-through, used where speed matters more than accuracy.        |
| `app/generators/risk.py`          | RiskGenerator — for law and startup. Outputs risk level + red flags.           |
| `app/generators/compliance.py`    | ComplianceGenerator — outputs regulation ID, status, version warning.          |
| `app/generators/friendly.py`      | FriendlyGenerator — for HR. Plain English, warm tone.                         |
| `app/generators/academic.py`      | AcademicGenerator — for university. Author/year/section citations.             |
| `app/graph/schema.cypher`         | All CREATE INDEX and CREATE CONSTRAINT statements for Neo4j setup.             |
| `app/graph/ingestion.py`          | PDF → text → chunks → Neo4j nodes + relationships pipeline.                   |
| `app/graph/queries.py`            | Reusable Cypher query library (cross-doc entity search, audit log, etc.).      |
| `app/api/routes.py`               | FastAPI endpoints: /upload, /query, /documents, /audit-log.                    |
| `app/config/verticals.py`         | VERTICAL_CONFIGS dict — chunk size, overlap, system prompt, output schema per vertical. |

---

## 6. Technology Stack

| Layer        | Technology                        | Rationale                                                                                                                                          |
|--------------|-----------------------------------|----------------------------------------------------------------------------------------------------------------------------------------------------|
| Graph DB     | Neo4j 5.x                         | Native vector index + Cypher graph traversal. The only DB that does both well. NEXT_CHUNK/MENTIONS relationships are impossible in flat DBs.       |
| Embeddings   | OpenAI text-embedding-3-small     | 1536 dimensions, best price/quality ratio for document embeddings. Swap to a local model for air-gapped deployments.                              |
| LLM          | Claude (claude-sonnet-4-6)        | Long context window handles 200-page documents. Strong instruction following for structured JSON output schemas.                                   |
| Reranker     | cross-encoder/ms-marco-MiniLM     | Lightweight cross-encoder for reranking top-10 retrieved chunks. Run locally — no API cost.                                                       |
| PDF parsing  | PyMuPDF (fitz)                    | Best page-level text extraction with bounding boxes. Preserves table structure better than pdfplumber for legal docs.                             |
| NER          | spaCy + custom rules              | Named entity recognition for building MENTIONS relationships. Custom rules for legal entities (party names, clause references).                    |
| Backend      | FastAPI + Python 3.11             | Async request handling. Strong typing. Native Pydantic integration for output schema validation.                                                   |
| File storage | AWS S3 / Supabase Storage         | Original PDFs stored here. Neo4j stores only extracted text and embeddings.                                                                       |
| Cache        | Redis                             | Cache frequent query embeddings and top-5 results. 1-hour TTL per tenant.                                                                        |
| Auth         | Clerk or Supabase Auth            | JWT-based auth. User roles stored in Neo4j User nodes for graph-level access control.                                                             |
| Frontend     | React + Tailwind                  | Vertical-specific UI skins on a shared chat component base.                                                                                       |
| Deployment   | Docker + Railway / Fly.io         | Neo4j in Docker. FastAPI containerised. Neo4j Aura for managed cloud option.                                                                      |

---

## 7. Implementation Workflow & Instructions

The development workflow is structured into logical, sequential phases. Each phase builds upon the previous one, ensuring a stable foundation before adding complexity or new verticals. Instead of rigid timelines, progress is measured by successfully completing the objectives of each phase.

### Phase 1: Core System & Infrastructure Setup
**Objective:** Establish the foundational graph database and ingestion pipeline.
- **Infrastructure:** Set up Neo4j 5.x locally (Docker) and/or on cloud (Aura).
- **Database Initialization:** Execute `schema.cypher` to create vector indexes, fulltext indexes, and all necessary constraints.
- **Ingestion Pipeline:** Build the PDF ingestion workflow (PyMuPDF text extraction → chunking → embedding → Neo4j Chunk nodes).
- **Core Interfaces:** Implement `BaseIndexer`, `BaseRetriever`, `BaseReranker`, and `BaseGenerator` abstract classes.
- **Base Components:** Implement `VectorRetriever` for basic Neo4j vector search and a simple `CitationGenerator`.
- **API Foundation:** Create FastAPI skeleton with `/upload` and `/query` endpoints.
- **Phase Goal:** Successfully upload a PDF, execute a question, and retrieve a basic cited answer.

### Phase 2: First Vertical Implementation (Law Firm)
**Objective:** Build a complete end-to-end pipeline tailored for the Law Firm vertical.
- **Indexing:** Implement `ClauseIndexer` (splitting on §, Article, Section, Clause markers).
- **Retrieval:** Implement `GraphRetriever` utilizing `NEXT_CHUNK` and `MENTIONS` traversal.
- **Entity Extraction:** Build the NER pipeline (via spaCy) to extract parties and clause references, generating Entity nodes.
- **Reranking & Generation:** Implement `VerticalReranker` (law firm term boosting) and `RiskGenerator` (HIGH/MED/LOW risk scoring with `red_flags` output).
- **Configuration:** Build `VERTICAL_CONFIGS` and the `build_pipeline(vertical)` factory method.
- **Phase Goal:** A fully functioning Law Firm pipeline capable of complex queries and red-flag detection.

### Phase 3: Vertical Expansion (Compliance & HR)
**Objective:** Scale the system to support multiple configurations and document structures.
- **Compliance Module:** 
  - Implement `ArticleIndexer` (split by regulation article number, tag with version/effective_date).
  - Add version-awareness logic (superseded flag on Chunk nodes, version_warning in output).
  - Implement `ComplianceGenerator` (COMPLIANT/NON-COMPLIANT/UNCLEAR status).
- **HR Module:**
  - Implement `TopicIndexer` (split by policy topic, tag with employee_type).
  - Implement `FriendlyGenerator` (plain English, warm tone).
- **Phase Goal:** Three distinct verticals running dynamically from the shared core engine.

### Phase 4: Enterprise Security & Access Control
**Objective:** Secure the platform for multi-tenant and role-based usage.
- **Tenant Isolation:** Enforce per-tenant namespacing; ensure all Chunk queries filter strictly by `tenant_id`.
- **Graph Permissions:** Implement `User` → `CAN_ACCESS` → `Document` graph relationships.
- **Role-Based Access (RBAC):** Apply role filtering (e.g., restricted access to executive compensation documents).
- **Authentication:** Implement JWT auth middleware in FastAPI (e.g., Clerk or Supabase Auth integration).
- **Audit Trails:** Ensure every query creates a `QueryLog` node for tracking.
- **Phase Goal:** Enterprise-grade tenant isolation and access controls validated via testing.

### Phase 5: Advanced Verticals (Startup & University)
**Objective:** Handle advanced comparative and academic graph queries.
- **Startup Module:** 
  - Implement `TermIndexer` (split by defined term, preserve cross-references).
  - Build term comparator Cypher queries to compare the same term across different documents.
- **University Module:**
  - Implement `SectionIndexer` (large chunks ~700 tokens, abstract/reference preservation).
  - Implement `AcademicGenerator` (author/year/section citations, contradiction detection).
  - Implement `CrossEncoderReranker` using `cross-encoder/ms-marco-MiniLM`.
- **Phase Goal:** All five verticals operational with distinct, optimized pipelines.

### Phase 6: System Hardening & Optimization
**Objective:** Prepare the system for production workloads.
- **Caching:** Integrate Redis caching for query embeddings and top-5 results (e.g., 1-hour TTL).
- **Validation:** Enforce Pydantic model validation on all generator output schemas.
- **Reliability:** Implement confidence scoring and "honest refusal" fallbacks to prevent hallucinations.
- **Testing:** Conduct load testing (e.g., 50 concurrent queries per tenant).
- **Lifecycle Management:** Implement document version migration flows.
- **Phase Goal:** Production-ready performance and reliable output generation.

### Phase 7: UI & Final Deployment
**Objective:** Polish the user experience and deploy the platform.
- **Frontend Construction:** Build the shared React chat component with dynamic UI skins per vertical (colors, risk badges).
- **UX Polish:** Add citation sidebars (click answer citation to highlight the PDF viewer).
- **Containerization:** Dockerise all services.
- **Deployment:** Push to cloud providers (e.g., Railway/Fly.io) and connect to production Neo4j Aura.
- **Phase Goal:** A fully deployable product ready for enterprise use.

### Phase 8: Advanced Enterprise Capabilities (Next-Gen AI)
**Objective:** Evolve the system from a reactive RAG tool into a proactive, multi-modal AI Agent.
- **Agentic Workflows:** Implement agentic frameworks (e.g., LangGraph) to allow multi-step queries (e.g., retrieve, synthesize, and draft emails).
- **Multi-Modal Vision RAG:** Upgrade ingestion to parse complex tables and charts using Vision models, embedding images alongside textual descriptions.
- **Global GraphRAG Summarization:** Utilize Neo4j Graph Data Science (GDS) to cluster entities and generate high-level "community summaries" for global query capabilities.
- **Semantic Diffing:** Build tools to compare documents semantically, highlighting risk shifts rather than just textual changes.
- **Proactive Alerts:** Implement background jobs that traverse `GOVERNED_BY` relationships when new regulations are uploaded, generating automated compliance alerts for outdated policies.
- **Human-in-the-Loop Learning:** Add feedback loops (thumbs up/down) stored in the graph to automatically fine-tune reranker weights over time.
- **Phase Goal:** A true AI agent capable of multi-modal understanding, autonomous reasoning, and proactive alerting.

---

## 8. Enterprise-Grade Features

These are the features that separate a working demo from a product that enterprises will actually pay for. Each one is non-negotiable for the target verticals.

### 8.1 Tenant Isolation
Every Neo4j query is filtered by `tenant_id`. No query can ever cross tenant boundaries — enforced at the Cypher level, not the application level. The unique constraint on `(tenant_id, chunk_id)` prevents any data bleed at the DB level.

### 8.2 Version-Aware Documents (Compliance Critical)
When a regulation or policy is updated, the old document's chunks are marked `superseded: true` and linked to the new version via `superseded_by`. The system proactively warns users when an answer was retrieved from an outdated document version — critical for compliance teams who must always work from current regulations.

### 8.3 Structured Output with Confidence Scores
Every generator returns a structured JSON object, not free text. This enables rich UI features:
- Risk badges (HIGH / MED / LOW) rendered inline with each answer for law and startup verticals.
- Compliance status pill (COMPLIANT / NON-COMPLIANT / UNCLEAR) on every compliance answer.
- Confidence indicator: LOW confidence triggered when retrieved chunk similarity score < 0.7.
- Honest refusal: when no relevant chunks are retrieved, the system says "not found in this document" rather than hallucinating an answer.

### 8.4 Full Audit Log
Every query is written to a `QueryLog` node in Neo4j with the user ID, query text, retrieved chunk IDs, timestamp, and answer. This is required for law firms (client billing), compliance teams (regulatory evidence), and HR (grievance investigations).

### 8.5 Cross-Document Graph Queries
The killer feature that justifies Neo4j. Example queries that are impossible in flat vector DBs:
- "Find all clauses across all our contracts that mention Acme Corp" — MENTIONS traversal.
- "Which of our policies reference regulation EU-GDPR-Art-17?" — GOVERNED_BY traversal.
- "Compare the termination clause in Contract A vs Contract B" — entity graph + term matching.
- "Which papers in our collection cite the same methodology?" — MENTIONS traversal across research chunks.

---

## 9. API Endpoints

| Method | Endpoint                    | Payload                                          | Response                                                                  |
|--------|-----------------------------|--------------------------------------------------|---------------------------------------------------------------------------|
| POST   | `/upload`                   | `{file, tenant_id, vertical, doc_name}`          | `doc_id, chunks_created, entities_extracted, processing_time_ms`          |
| POST   | `/query`                    | `{question, tenant_id, vertical, user_id, doc_ids[]}` | `answer, citations[], risk_level, confidence, chunks_used[]`         |
| GET    | `/documents`                | `?tenant_id=&vertical=`                          | `documents[]` with id, name, version, superseded, chunk_count             |
| GET    | `/document/{id}/graph`      | `?tenant_id=`                                    | Entity nodes and relationships for this document                          |
| POST   | `/compare`                  | `{doc_id_a, doc_id_b, term, tenant_id}`          | Side-by-side term comparison with diff highlighting                       |
| GET    | `/audit-log`                | `?tenant_id=&user_id=&from=&to=`                 | QueryLog entries with query, answer, chunks, timestamp                    |
| DELETE | `/document/{id}`            | `?tenant_id=`                                    | Removes document, all chunks, entity links from graph                     |
| POST   | `/document/{id}/supersede`  | `{new_doc_id, tenant_id}`                        | Links old doc to new version, sets superseded flag on old chunks          |

---

## 10. Risks & Mitigations

| Risk                                              | Severity | Mitigation                                                                                                                                              |
|---------------------------------------------------|----------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| Hallucination on complex legal questions          | HIGH     | Strict RAG — LLM prompt says "answer ONLY from retrieved chunks." If no relevant chunk found, return "not found in document." Confidence score flags uncertain answers. |
| Neo4j performance at scale (millions of chunks)  | MED      | Vector index scales well. Add chunk_count per tenant monitoring. Shard by tenant_id if needed. Redis cache cuts repeat query load by ~60%.              |
| PDF parsing failures (scanned/image PDFs)         | MED      | Detect image PDFs via PyMuPDF. Fall back to OCR (Tesseract or AWS Textract). Flag low-confidence extractions to user on upload.                        |
| Embedding model cost at scale                     | LOW      | text-embedding-3-small is 5x cheaper than large. Pre-cache embeddings. Batch ingestion. Swap to local model (sentence-transformers) for high volume.   |
| Tenant data bleed                                 | HIGH     | Enforced at Cypher query level (tenant_id filter on every query) AND at constraint level (unique tenant_id + chunk_id). Test with red team queries across tenants. |
| Outdated regulation answers in compliance vertical | HIGH    | Version-aware chunks with superseded flag. Proactive warning banner in UI. Nightly job to check regulation source URLs for updates.                     |
| Market competition (Notion AI, ChatPDF, Adobe AI) | MED     | Win on vertical specificity: risk scoring, clause extraction, cross-doc graph, compliance status. Generic tools don't do any of these.                  |

---

## 11. Success Metrics

These metrics define "done" for the platform and provide clear performance targets.

| Metric                                   | Baseline Target          | Production Target        | Notes                                                      |
|------------------------------------------|--------------------------|--------------------------|------------------------------------------------------------|
| Answer accuracy (retrieved correct chunk)| > 80%                    | > 92%                    | Measured against 50 labelled Q&A pairs per vertical.       |
| Query latency (p95)                      | < 4s                     | < 2s                     | Includes embedding + Neo4j retrieval + LLM generation.     |
| Hallucination rate                       | < 5%                     | < 1%                     | Strict RAG with honest refusal when no chunk found.        |
| PDF ingestion speed                      | < 60s per 100 pages      | < 30s per 100 pages      | With batched embedding calls.                              |
| Tenant isolation (0 cross-tenant leaks)  | Pass all tests           | Pass all tests           | Non-negotiable. Red team test on every deploy.             |
| Concurrent queries supported             | 10 per tenant            | 50 per tenant            | With Redis cache reducing Neo4j load.                      |
| Verticals live                           | 1 (Initial vertical)     | 5 (All planned verticals)| Each vertical needs its own 50-question eval set.          |

---

*— End of Instructions & Workflow Guide —*

*AI Document Q&A System · Antigravity · May 2026*
