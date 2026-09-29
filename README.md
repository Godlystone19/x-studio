# X Content Studio

Standalone X post generation and performance learning application. This project is kept separate from the CocoaYield forecaster.

## Run the backend

From this directory, create an isolated Python environment and install only this project's backend dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
uvicorn backend.main:app --host 127.0.0.1 --port 8001 --reload
```

The backend loads the local `xpost/.env` file automatically (and it is ignored by Git). Configure or replace the OpenAI-compatible provider settings there:

```bash
export LLM_API_KEY="your-provider-key"
export LLM_BASE_URL="https://api.openai.com/v1" # optional
export LLM_MODEL="gpt-4o-mini"                  # optional
```

The SQLite content database is created under `xpost/data/x_content.sqlite3` by default. Set `X_CONTENT_DB` to use a different location.

## Run the frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5174. Vite proxies `/api` to the standalone API at `http://localhost:8001`; set `VITE_API_URL` if your API uses another base URL.

The API docs are available at `/docs` on the backend. Imports accept CSV, JSON, JSONL, TXT, XLS, and XLSX. Optional personal post fields include topic, timestamp, impressions, likes, replies, reposts, bookmarks, and engagement_rate; blank metrics are kept missing.

## Current scope

This is an early MVP. Storage uses SQLite and topic-filtered retrieval; PostgreSQL/pgvector, authentication, current news/X API ingestion, semantic originality checks, and scheduling remain future work. Similarity indicators are lexical and do not guarantee performance or originality. Verify facts before publishing.
