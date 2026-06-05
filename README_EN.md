<h1 align="center">OmniKB</h1>
<h3 align="center">Scenario-Based Knowledge Base Q&A System</h3>
<h4 align="center">Multi-Source Aggregation · Scenario Wiki · One-Click Publish · Zero Embedding</h4>

<p align="center">
  <a href="https://github.com/fivif/OmniKB"><img src="https://img.shields.io/badge/GitHub-OmniKB-blue?logo=github" alt="GitHub"></a>
  <a href="https://github.com/fivif/OmniKB/blob/master/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.13+-blue?logo=python" alt="Python 3.13+"></a>
  <a href="#"><img src="https://img.shields.io/badge/LLM-OpenAI_Compatible-536DFE" alt="OpenAI Compatible"></a>
  <a href="#"><img src="https://img.shields.io/badge/storage-SQLite-orange?logo=sqlite" alt="SQLite"></a>
</p>

<p align="center">
  <a href="https://kb.xzay.de/s/mfd">Live Demo</a> ·
  <a href="https://kb.xzay.de/test">Test Report</a> ·
  <a href="README.md">中文</a>
</p>

<p align="center">
  <img src="https://cdn3.ldstatic.com/original/4X/5/1/f/51f1739699ec0b35ee4e73fe7dec721f0645a370.jpeg" width="48%" alt="Wiki UI"/>
  <img src="https://cdn3.ldstatic.com/original/4X/e/a/4/ea46abac257ac90d405bb09f0cf6b95f2993d2b5.png" width="48%" alt="Test Report"/>
</p>
<p align="center"><em>Left: Wiki Knowledge Graph ｜ Right: 500-Question Hallucination Test Report</em></p>

---

## What is OmniKB

**OmniKB** is NOT a RAG knowledge base. No document chunking, no vector embeddings, no semantic search. The LLM reads source files directly and generates structured wiki pages — the wiki IS the knowledge base.

Inspired by [Karpathy's LLM-Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) and [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki).

### Architecture

```
                         ┌──────────────────────────┐
  Files/URLs/Text ──► Extract ──► Wiki Generator (LLM) │
                                  │  Two-step CoT         │
                                  │  Step 1: Analyze → Plan
                                  │  Step 2: Generate → .md
                                  └──────────┬───────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
              wiki_pages (DB)          index.md (catalog)       [[wikilink]] graph
              entity/concept         progressive disclosure     D3.js visualization
              /source/query              1M context fit
```

**Zero embeddings · Zero chunking · Zero vector DB** — Wiki pages ARE the knowledge base.

---

## Key Features

| | |
|---|---|
| **Auto Wiki Generation** | Upload any document → LLM two-step CoT → auto-creates entity/concept/source pages |
| **Knowledge Graph** | `[[wikilink]]` bidirectional links, D3.js force visualization, degree-scaled nodes |
| **1M Context Chat** | Full wiki_index progressive disclosure → `read_wiki_page(id)` on demand → true SSE streaming |
| **Scenario Publishing** | Select sources → configure template/LLM → generate standalone Q&A page → API Key auth |
| **Agent Page Editor** | Natural language commands → rewrite layout, inject HTML/CSS/JS, one-click reset |
| **Zero-Dependency Deploy** | Single-file startup, no external services, Web UI config, Docker optional |
| **Cookie Auth** | `ADMIN_PASSWORD` one-liner, 30-day cookie, hot-reload via Web UI without restart |

---

## Quick Start

```bash
git clone https://github.com/fivif/OmniKB
cd OmniKB
cp .env.example .env
# ADMIN_PASSWORD=xxx        ← set to enable admin panel auth (empty = no auth)
pip install -r backend/requirements.txt
python backend/main.py
# Open http://localhost:6886
```

---

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=fivif/OmniKB&type=Date)](https://star-history.com/#fivif/OmniKB&Date)

---

## License

[MIT](https://github.com/fivif/OmniKB/blob/master/LICENSE)

---

<p align="center"><em>Built with love</em></p>
