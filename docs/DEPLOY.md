# OmniKB Deployment Guide

## Prerequisites
- Docker & Docker Compose v2+
- An OpenAI API key (or Anthropic / local Ollama)

---

## Quick Start (Docker)

```bash
# 1. Clone / navigate to project root
cd omnikb

# 2. Copy and configure environment
cp .env.example .env
# Edit .env — set OPENAI_API_KEY and MCP_API_KEY at minimum

# 3. Start services
docker compose up -d

# 4. Open the UI
open http://localhost:8000
```

Qdrant dashboard is available at `http://localhost:6333/dashboard`.

---

## Local Development (without Docker)

### 1. Start Qdrant
```bash
docker run -d -p 6333:6333 -p 6334:6334 \
  -v $(pwd)/data/qdrant:/qdrant/storage \
  qdrant/qdrant:v1.11.0
```

### 2. Set up Python environment
```bash
cd backend
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure environment
```bash
cp ../.env.example ../.env
# Edit .env with your API keys
```

### 4. Run backend
```bash
# From backend/ directory
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 5. Open frontend
Serve `frontend/` with any static file server, or open `frontend/index.html` directly in a browser.

With Python:
```bash
cd frontend && python -m http.server 3000
```
Then open `http://localhost:3000`.

> The backend API serves the frontend at `/` automatically when `frontend/` exists next to `backend/`.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `QDRANT_URL` | ✓ | `http://localhost:6333` | Qdrant server URL |
| `QDRANT_COLLECTION` | — | `omnikb` | Collection name |
| `OPENAI_API_KEY` | ✓* | — | OpenAI API key (*if using OpenAI) |
| `ANTHROPIC_API_KEY` | — | — | Anthropic API key |
| `OLLAMA_BASE_URL` | — | `http://localhost:11434` | Ollama endpoint |
| `LLM_PROVIDER` | — | `openai` | Default LLM: `openai`/`anthropic`/`ollama` |
| `LLM_MODEL` | — | `gpt-4o` | Default model name |
| `EMBEDDING_MODEL` | — | `text-embedding-3-small` | OpenAI embedding model |
| `MCP_API_KEY` | ✓ | — | Secret key for MCP Bearer auth |
| `DATA_DIR` | — | `./data` | Data directory path |
| `SQLITE_PATH` | — | `./data/omnikb.db` | SQLite database path |

---

## MCP Integration

### Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "omnikb": {
      "command": "python",
      "args": ["/absolute/path/to/backend/mcp_server/run_stdio.py"],
      "env": {
        "OPENAI_API_KEY": "sk-...",
        "MCP_API_KEY": "your-mcp-key",
        "QDRANT_URL": "http://localhost:6333"
      }
    }
  }
}
```

### SSE (Cursor / any MCP client)
```
URL: http://localhost:8000/mcp
Authorization: Bearer <MCP_API_KEY>
```

---

## Data Persistence

| Path | Contents |
|------|----------|
| `./data/omnikb.db` | SQLite metadata (sources, chunks, tasks) |
| `./data/files/` | Uploaded original files |
| `qdrant_data` volume | Vector embeddings |

---

## Upgrading

```bash
docker compose pull
docker compose up -d --build
```

The SQLite DB and Qdrant data are preserved in volumes/mounts.

---

## Troubleshooting

**Backend won't start**: Check `OPENAI_API_KEY` is set in `.env`.

**Qdrant connection refused**: Ensure Qdrant container is running: `docker compose ps`

**Search returns no results**: Verify the ingest task completed (`GET /ingest/tasks`). Check backend logs for embedding errors.

**MCP returns 401**: Confirm `Authorization: Bearer <MCP_API_KEY>` header matches the key in `.env`.

**Ollama not working**: Set `OLLAMA_BASE_URL` and ensure the model is pulled: `ollama pull llama3.2`
