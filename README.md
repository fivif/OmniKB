<h1 align="center">OmniKB</h1>
<h3 align="center">Universal AI Knowledge Base — Wiki-first, RAG-free, Agent-native</h3>
<h4 align="center">全渠道摄入 · 混合语义检索 · LLM 自动建维 · Agent 智能采集 · MCP 协议开放</h4>

<p align="center">
  <a href="https://github.com/xzay/omnikb"><img src="https://img.shields.io/badge/GitHub-omnikb-blue?logo=github" alt="GitHub"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python 3.11+"></a>
  <a href="#"><img src="https://img.shields.io/badge/LLM-DeepSeek_V4-536DFE" alt="DeepSeek V4"></a>
  <a href="#"><img src="https://img.shields.io/badge/storage-SQLite_+_Qdrant-orange?logo=sqlite" alt="Storage"></a>
  <a href="#"><img src="https://img.shields.io/badge/API-OpenAI_Compatible-412991" alt="OpenAI Compatible"></a>
</p>

<p align="center">
  <a href="#-什么是-omnikb">中文</a> ·
  <a href="#-what-is-omnikb">English</a>
</p>

---

## 🧠 什么是 OmniKB

**OmniKB** 是一个"维基优先"的通用 AI 知识库。与传统 RAG 不同，我们不把文档切成碎片交给向量数据库——而是让 LLM 阅读、分析、生成结构化维基页面。维基本身就是知识库。

核心洞察来自 [Andrej Karpathy 的 LLM-Wiki 构想](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)：LLM 应该像人类学生一样建立结构化的知识体系，而不是在一堆碎片里翻找。OmniKB 践行了这一理念。

### 架构总览

```
┌────────────────────────────────────────────────────────────────────┐
│                        WIKI-FIRST PIPELINE                         │
│                                                                    │
│  Sources ──► Extract ──► Wiki Generator (LLM)                     │
│    URL         文本          │  ┌────────────────────────────┐     │
│    PDF        Whisper         ├──► Entity / Concept / Source  ├──┐  │
│    Video      OCR             │  │  Markdown + Frontmatter     │  │  │
│    Text       抓取            │  └────────────────────────────┘  │  │
│                               │                                    │  │
│                               ├──► Knowledge Graph ──────────────┐│  │
│                               │  [[wikilink]] + D3.js Force     ││  │
│                               │                                   ││  │
│                               ├──► index.md ◄── Progressive     ││  │
│                               │  Disclosure Layer                ││  │
│                               │                                   ││  │
│                               └──► read_wiki_page ───► LLM Chat  ││  │
│                                  MCP Tools · SSE Streaming        ││  │
└────────────────────────────────────────────────────────────────────┘
```

---

## ✨ 核心特性

| | |
|---|---|
| 🧠 **Wiki-First Architecture** | LLM 读取、分析、生成结构化维基页面。entity / concept / source / query 四类页面，markdown + frontmatter 标准格式。维基本身即知识库。 |
| 🔗 **Knowledge Graph** | `[[wikilink]]` 交叉引用自动建立双向边，D3.js 力导向图谱可视化。graph_neighbors BFS 邻域探索。支持 surprising_connection / bridge / knowledge_gap 三种图谱洞察。 |
| 💬 **True Streaming Chat** | SSE token-by-token 流式输出。wiki_index 渐进式披露：LLM 先扫描索引，再按需调用 `read_wiki_page(id)` 获取全量内容。引用溯源至源级。 |
| 🎯 **Scenario Isolation** | 每个场景绑定独立的知识源子集、LLM 配置和 API Key。场景可发布为独立 Q&A 页面，适合客户支持、内部文档问答等场景。 |
| 📡 **MCP Server** | 标准 Model Context Protocol。13 个工具（search_kb / ask_kb / ingest_url / browser_fetch / search_wiki / read_wiki_page / list_wiki_pages / graph_neighbors / deep_research...），SSE + stdio 双传输模式，Bearer Token 鉴权，滑动窗口限流。 |
| 🕸️ **Web Agent** | 自主 URL 采集，Plan→Execute→Verify 三阶段循环。四层抓取策略（静态→Scrapling→Playwright→JsHook CDP），9 种反思检查点，预算守卫三重上限。 |
| 🔍 **Deep Research** | 维基页面 knowledge_gap 自动检测 → 多查询搜索 (DDG) → 并行 URL 调查 → LLM 综合 → `## Recent Research` 追加。三种触发方式：手动/半自动/全自动周期轮询，任务持久化，失败隔离。 |
| 🎨 **AURA UI** | 极简设计系统，5 个 CSS 令牌文件 + 8 个组件样式 + 7 个面板样式。明暗双主题，⌘K 命令面板，引用链可视化。 |
| ⚡ **Zero Embedding (L2)** | L2 维基层不做任何向量嵌入、不做分块。混合检索仅用于 L1 遗留路径。维基层的检索是纯 tokenized 评分——轻量、快速、零外部依赖。 |

---

## 🚀 快速开始

```bash
# 1. 克隆仓库
git clone https://github.com/xzay/omnikb
cd omnikb

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env，至少填入 LLM_API_KEY

# 3. 安装依赖
pip install -r backend/requirements.txt

# 4. 启动（QDRANT_MODE=local 默认本地文件持久化）
python backend/main.py

# 5. 打开浏览器
open http://localhost:6886
```

### Docker 部署

```bash
cp .env.example .env   # 编辑 .env 填入 API Key
docker compose up -d
docker compose logs -f omnikb
# 打开 http://localhost:6886
```

---

## 🧱 技术栈

### Backend

| 层 | 技术 |
|---|---|
| 框架 | **FastAPI** — 异步 HTTP，SSE 流式，CORS 中间件 |
| LLM | **DeepSeek-V4** / **OpenAI-compatible** — 1M 上下文，代理支持 |
| 数据库 | **SQLite** (aiosqlite · WAL 模式) — 元数据、维基页面、研究任务、MCP 日志 |
| 向量存储 | **Qdrant** (local / remote / memory) — L1 遗留混合检索 |
| 嵌入 | **BGE-M3** 1024d (dense) + **BM25** (sparse) — 双向量嵌入 |
| 重排序 | **bge-reranker-v2-m3** Cross-encoder — 可选精排 |
| 语音转录 | **faster-whisper** (tiny~large-v2) — ffmpeg 音频提取 |
| Agent 引擎 | **agent_core** — 自研 Provider 无关 Agent 循环（预算守卫 · 反思检查点 · 提示缓存 · 转向注入 · 消息压缩 · 工具截断溢出） |
| MCP | **FastMCP** — SSE + stdio 双模式，Bearer Token 鉴权 |
| 爬虫 | **scrapling · patchright · JsHook CDP** — 四级采集策略 |
| 配置 | **Pydantic Settings** — 60+ 环境变量，运行时自检，密钥脱敏 |

### Frontend

| 层 | 技术 |
|---|---|
| 框架 | **Vanilla JavaScript** — 零框架，直接 DOM API |
| 布局 | **CSS Grid + Flexbox** — 响应式工具栏面板 |
| 主题 | **AURA Design System** — CSS 自定义属性，明暗切换 |
| 图谱 | **D3.js** — 力导向维基链接图 |
| 渲染 | **marked** — markdown 转 HTML |
| 高亮 | **highlight.js** — 代码块着色 |
| 流式 | **SSE EventSource** — Agent 事件 + Chat 双向实时 |

---

## 📊 项目数据

| 指标 | 数值 |
|---|---|
| Python 后端 | ~19,600 行 / 94 个文件 |
| JS/CSS/HTML 前端 | ~16,800 行 / 25 个文件 |
| API 路由 | 10 个路由模块 |
| MCP 工具 | 13 个标准工具 |
| CSS 令牌 + 组件 + 面板 | 20 个样式文件 |
| Agent 核心模块 | 13 个文件 (agent_core) |

---

## 📖 文档

| 文档 | 路径 |
|---|---|
| 快速开始 | 见上方 `## 快速开始` |
| API 参考 | [`docs/API.md`](docs/API.md) |
| 架构设计 | 见上方 `## 架构总览` + [`docs/`](docs/) |
| 部署指南 | [`docs/DEPLOY.md`](docs/DEPLOY.md) |
| 环境变量 | [`.env.example`](.env.example) |
| 演进日志 | [`progress.md`](progress.md) |

---

## 📜 License

MIT

---

<p align="center"><em>Built with ♥ by the OmniKB team</em></p>

---

---

# 🇬🇧 English

---

## 🧠 What is OmniKB

**OmniKB** is a **wiki-first** universal AI knowledge base. Unlike traditional RAG, we don't chunk documents into vector databases — instead, **the LLM reads, analyzes, and generates structured wiki pages**. The wiki IS the knowledge base.

The core insight comes from [Andrej Karpathy's LLM-Wiki gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): LLMs should build structured knowledge like a human student, not rummage through piles of fragments. OmniKB puts that idea into practice.

### Architecture Overview

```
┌────────────────────────────────────────────────────────────────────┐
│                        WIKI-FIRST PIPELINE                         │
│                                                                    │
│  Sources ──► Extract ──► Wiki Generator (LLM)                     │
│    URL         Text          │  ┌────────────────────────────┐     │
│    PDF        Whisper        ├──► Entity / Concept / Source  ├──┐  │
│    Video      OCR             │  │  Markdown + Frontmatter     │  │  │
│    Text       Crawl           │  └────────────────────────────┘  │  │
│                               │                                    │  │
│                               ├──► Knowledge Graph ──────────────┐│  │
│                               │  [[wikilink]] + D3.js Force     ││  │
│                               │                                   ││  │
│                               ├──► index.md ◄── Progressive     ││  │
│                               │  Disclosure Layer                ││  │
│                               │                                   ││  │
│                               └──► read_wiki_page ───► LLM Chat  ││  │
│                                  MCP Tools · SSE Streaming        ││  │
└────────────────────────────────────────────────────────────────────┘
```

---

## ✨ Key Features

| | |
|---|---|
| 🧠 **Wiki-First Architecture** | LLM reads, analyzes, generates structured wiki pages — entity, concept, source, query types. Pure markdown + frontmatter. The wiki IS the knowledge base. |
| 🔗 **Knowledge Graph** | `[[wikilink]]` cross-references build bidirectional edges automatically. D3.js force-directed visualization. `graph_neighbors` BFS neighborhood exploration. Three graph insight types: surprising_connection, bridge, knowledge_gap. |
| 💬 **True Streaming Chat** | SSE token-by-token output. wiki_index progressive disclosure: LLM scans the index first, then calls `read_wiki_page(id)` on-demand for full content. Source-level citation traceability. |
| 🎯 **Scenario Isolation** | Each scenario binds an independent source subset, LLM config, and API Key. Scenarios publish as standalone Q&A pages — perfect for customer support or internal doc QA. |
| 📡 **MCP Server** | Standard Model Context Protocol. 13 tools (search_kb, ask_kb, ingest_url, browser_fetch, search_wiki, read_wiki_page, list_wiki_pages, graph_neighbors, deep_research...). Dual transport: SSE + stdio. Bearer Token auth. Sliding-window rate limiting. |
| 🕸️ **Web Agent** | Autonomous URL capture. Plan→Execute→Verify three-stage loop. Four-tier fetching (static→Scrapling→Playwright→JsHook CDP). 9 reflection checkpoints. Triple budget guard. |
| 🔍 **Deep Research** | Auto-detect knowledge_gap in wiki pages → multi-query web search (DDG) → parallel URL investigation → LLM synthesis → append `## Recent Research` section. Three trigger modes: manual / semi-auto / periodic worker. Task persistence. Failure isolation. |
| 🎨 **AURA UI** | Minimalist design system. 5 CSS token files + 8 component stylesheets + 7 panel stylesheets. Dark/light themes. ⌘K command palette. Citation chain visualization. |
| ⚡ **Zero Embedding (L2)** | No vector embeddings, no chunking at the L2 wiki layer. Retrieval is pure tokenized scoring — lightweight, fast, zero external dependencies. |

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/xzay/omnikb
cd omnikb

# 2. Configure
cp .env.example .env
# Edit .env — at minimum set LLM_API_KEY

# 3. Install
pip install -r backend/requirements.txt

# 4. Run (QDRANT_MODE=local by default, no external services)
python backend/main.py

# 5. Open
open http://localhost:6886
```

### Docker

```bash
cp .env.example .env   # edit .env with your API keys
docker compose up -d
docker compose logs -f omnikb
# Open http://localhost:6886
```

---

## 🧱 Tech Stack

### Backend

| Layer | Technology |
|---|---|
| Framework | **FastAPI** — async HTTP, SSE streaming, CORS middleware |
| LLM | **DeepSeek-V4** / **OpenAI-compatible** — 1M context, proxy support |
| Database | **SQLite** (aiosqlite · WAL mode) — metadata, wiki pages, research tasks, MCP logs |
| Vector Store | **Qdrant** (local / remote / memory) — L1 legacy hybrid search |
| Embeddings | **BGE-M3** 1024d (dense) + **BM25** (sparse) — dual-vector |
| Reranker | **bge-reranker-v2-m3** Cross-encoder — optional precision boost |
| Speech | **faster-whisper** (tiny~large-v2) — ffmpeg audio extraction |
| Agent Engine | **agent_core** — custom provider-agnostic agent loop (budget guard · reflection checkpoints · prompt caching · steering injection · message compaction · tool truncation overflow) |
| MCP | **FastMCP** — SSE + stdio dual mode, Bearer Token auth |
| Crawling | **scrapling · patchright · JsHook CDP** — 4-tier fetch strategy |
| Config | **Pydantic Settings** — 60+ env vars, runtime validation, secret redaction |

### Frontend

| Layer | Technology |
|---|---|
| Framework | **Vanilla JavaScript** — zero framework, direct DOM API |
| Layout | **CSS Grid + Flexbox** — responsive toolbar panels |
| Theme | **AURA Design System** — CSS custom properties, dark/light |
| Graph | **D3.js** — force-directed wiki link graph |
| Rendering | **marked** — markdown to HTML |
| Highlighting | **highlight.js** — code block coloring |
| Streaming | **SSE EventSource** — agent events + chat bidirectional real-time |

---

## 📊 Project Stats

| Metric | Count |
|---|---|
| Python Backend | ~19,600 lines / 94 files |
| JS/CSS/HTML Frontend | ~16,800 lines / 25 files |
| API Route Modules | 10 |
| MCP Tools | 13 |
| CSS Stylesheets | 20 |
| Agent Core Modules | 13 |

---

## 📖 Documentation

| Document | Path |
|---|---|
| Quick Start | See `## Quick Start` above |
| API Reference | [`docs/API.md`](docs/API.md) |
| Architecture | See `## Architecture Overview` above + [`docs/`](docs/) |
| Deployment | [`docs/DEPLOY.md`](docs/DEPLOY.md) |
| Environment Variables | [`.env.example`](.env.example) |
| Evolution Log | [`progress.md`](progress.md) |

---

## 📜 License

MIT

---

<p align="center"><em>Built with ♥ by the OmniKB team</em></p>
