# DocsAI

DocsAI is an AI document Q&A platform for uploading, indexing, searching, and analyzing documents across multiple business verticals. It combines a FastAPI backend, an in-process graph/vector store, Cloudflare Workers AI, optional Redis caching, and a React/Vite frontend.

## Features

- Upload and manage PDF/DOCX documents by tenant and vertical.
- Ask natural-language questions with cited evidence from retrieved document chunks.
- Stream answers over WebSockets for a responsive chat experience.
- Use vertical-specific indexing and answer generation for law, compliance, HR, startup, and academic workflows.
- Run red-flag, compliance, analytics, feedback, and agent-style multi-step query flows.
- Persist graph data locally under `backend/data` and optionally cache query/job state with Redis.
- Optionally store chat/history records in MongoDB.

## Tech Stack

| Area | Technology |
| --- | --- |
| Backend API | FastAPI, Uvicorn, Pydantic |
| AI | Cloudflare Workers AI, optional OpenAI fallback |
| Retrieval | Modular RAG pipeline, graph/vector/hybrid retrievers, rerankers |
| Storage | Local GraphStore files, FAISS, NetworkX |
| Cache / Jobs | Redis |
| Optional History DB | MongoDB |
| Frontend | React, Vite, React Router, lucide-react |
| Document Parsing | PyMuPDF, pdfplumber, python-docx, optional OCR |

## Repository Layout

```text
DocsAI/
  backend/
    app/
      api/           FastAPI REST and WebSocket routes
      agent/         Multi-step agent planner/executor/tools
      config/        Vertical configuration
      core/          Pipeline, schemas, dependencies, AI clients, cache
      features/      Analytics, jobs, red flags, compliance monitoring
      generators/    Vertical-specific response generators
      graph/         Ingestion, OCR, local graph store
      indexers/      Vertical-specific document indexers
      rerankers/     Cross-encoder, vertical, and noop rerankers
      retrievers/    Graph, vector, and hybrid retrievers
    main.py
    requirements.txt
  frontend/
    src/
      components/
      context/
      pages/
      config.js
    package.json
  docker-compose.yml
  Dockerfile
```

## Prerequisites

- Python 3.11+
- Node.js 20+
- Redis 7+ if you want caching and background job persistence
- Cloudflare Workers AI account ID and API token
- Optional: MongoDB URI for chat/history analytics

## Environment Setup

Copy the example environment file and fill in your local values:

```powershell
Copy-Item .env.example .env
```

Required backend values:

```env
CF_ACCOUNT_ID=your_cloudflare_account_id
CF_API_TOKEN=your_cloudflare_api_token
REDIS_HOST=localhost
REDIS_PORT=6379
```

Useful optional values:

```env
GRAPH_STORE_DIR=backend/data
MONGODB_URI=mongodb://localhost:27017
MONGODB_DB=job_agent
MONGODB_COLLECTION=applications
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
LOG_LEVEL=INFO
OCR_SPACE_API_KEY=helloworld
VITE_API_BASE_URL=http://localhost:8000/api/v1
VITE_WS_BASE_URL=ws://localhost:8000/api/v1
VITE_TENANT_ID=tenant-123
```

Do not commit `.env`; it is ignored by Git.

## Run Locally

Start Redis with Docker:

```powershell
docker compose up redis
```

Install and run the backend:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Install and run the frontend in a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` and the API runs at `http://localhost:8000`.

## Docker

The compose file includes Redis and the API service:

```powershell
docker compose up --build
```

For frontend development, run Vite locally from `frontend/`.

## Main API Routes

Base URL: `http://localhost:8000/api/v1`

- `POST /tenants` - create a tenant workspace.
- `POST /upload` - upload and index a document.
- `GET /jobs/{job_id}` - check async ingestion status.
- `POST /query` - ask a document question over REST.
- `GET /documents` - list indexed documents.
- `DELETE /documents/{doc_id}` - delete one document.
- `POST /documents/{doc_id}/supersede` - upload a replacement version.
- `GET /documents/{doc_id}/redflags` - fetch red-flag analysis.
- `POST /agent/query` - run an agentic query.
- `POST /agent/plan` - create an agent plan.
- `GET /analytics/dashboard` - dashboard metrics.
- `GET /analytics/recent` - recent activity.
- `WS /ws/query` - streaming Q&A.
- `WS /ws/agent` - streaming agent execution.

## Git Hygiene

The repository intentionally excludes:

- `.env` and other local secrets.
- Runtime graph/cache data in `backend/data`.
- Python caches and test/build artifacts.
- Frontend `node_modules` and `dist`.
- Local logs.
- Large local sample documents such as PDFs.

Keep reusable examples as small text fixtures or document them in the README instead of committing private or bulky uploaded files.
