# OmniKB API Reference

## Base URL
`http://localhost:8000`

---

## System

### `GET /health`
Returns service health status.

**Response** `200`
```json
{ "status": "ok" }
```

---

## Ingest

### `POST /ingest/file`
Upload one or more files (multipart form).

**Form fields**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `files` | `File[]` | ✓ | Supported: TXT, MD, PDF, DOCX, HTML, JSON, CSV |
| `tags` | `string` | — | Comma-separated tags |

**Response** `200`
```json
{
  "results": [
    { "source_id": "uuid", "task_id": "uuid", "filename": "report.pdf" }
  ]
}
```

---

### `POST /ingest/text`
Ingest raw text content.

**Body**
```json
{
  "content": "Your text here…",
  "title": "My Notes",
  "tags": ["research", "2024"]
}
```

**Response** `200`
```json
{ "source_id": "uuid", "task_id": "uuid" }
```

---

### `POST /ingest/url`
Fetch and ingest a web page.

**Body**
```json
{
  "url": "https://example.com/article",
  "title": "Optional title",
  "tags": ["web"]
}
```

**Response** `200`
```json
{ "source_id": "uuid", "task_id": "uuid" }
```

---

### `GET /ingest/tasks`
List recent ingest tasks.

**Query params** `limit` (default 50), `offset` (default 0)

**Response** `200`
```json
[
  {
    "id": "uuid",
    "source_id": "uuid",
    "status": "done",
    "error": null,
    "created_at": "2026-05-06T10:00:00Z",
    "updated_at": "2026-05-06T10:00:05Z"
  }
]
```
Statuses: `pending` → `processing` → `done` | `error`

---

### `GET /ingest/tasks/{task_id}`
Get a specific task.

**Response** `200` Task object, `404` if not found.

---

## Search

### `GET /search`
Search the knowledge base.

**Query params**
| Param | Default | Description |
|-------|---------|-------------|
| `q` | required | Search query |
| `top_k` | 10 | Result count (1–50) |
| `mode` | `hybrid` | `hybrid` \| `semantic` \| `bm25` |
| `filter_source` | — | Filter by source UUID |
| `filter_type` | — | Filter by `source_type` |

**Response** `200`
```json
{
  "query": "machine learning",
  "mode": "hybrid",
  "results": [
    {
      "id": "uuid",
      "score": 0.87,
      "content": "Full chunk text…",
      "highlight": "Full chunk text with <mark>machine</mark> <mark>learning</mark>…",
      "metadata": { "source_id": "uuid", "source_name": "paper.pdf", "source_type": "pdf" }
    }
  ]
}
```

---

## Chat

### `POST /chat`
Streaming RAG conversation. Returns `text/event-stream`.

**Body**
```json
{
  "messages": [
    { "role": "user", "content": "What is retrieval augmented generation?" }
  ],
  "provider": "openai",
  "model": "gpt-4o",
  "top_k": 5,
  "kb_filter": { "source_id": "uuid" }
}
```
`provider`: `openai` | `anthropic` | `ollama`  
`model`: provider-specific model name  
`kb_filter`: optional Qdrant payload filter (key → value)

**SSE events**
```
data: {"type": "token", "content": "..."}
data: {"type": "citations", "citations": [...]}
data: [DONE]
```

**Citation object**
```json
{
  "index": 1,
  "chunk_id": "uuid",
  "content": "First 300 chars of chunk…",
  "source": "paper.pdf",
  "score": 0.8721
}
```

---

## Knowledge Base

### `GET /kb/sources`
List all sources.

**Query params** `limit`, `offset`

### `GET /kb/sources/{source_id}`
Get source details.

### `GET /kb/sources/{source_id}/chunks`
List chunks for a source.

**Query params** `limit`, `offset`

### `DELETE /kb/sources/{source_id}`
Delete a source and all its chunks (vector + metadata + file).

**Response** `200`
```json
{ "status": "deleted", "source_id": "uuid" }
```

### `GET /kb/stats`
Total counts.

**Response** `200`
```json
{ "total_sources": 42, "total_chunks": 1337 }
```

---

## MCP Server

### SSE endpoint
`GET/POST http://localhost:8000/mcp`

Requires: `Authorization: Bearer <MCP_API_KEY>`

Compatible with Claude Desktop, Cursor, and any MCP client.

### Available tools
| Tool | Description |
|------|-------------|
| `search_kb` | Hybrid search (query, top_k, filter_source) |
| `ask_kb` | Retrieve context for a question |
| `ingest_url` | Ingest a URL asynchronously |
| `ingest_text` | Ingest text asynchronously |
| `list_sources` | List knowledge base sources |
| `get_chunk` | Get a chunk by ID |

### Stdio mode
```bash
python backend/mcp_server/run_stdio.py
```
