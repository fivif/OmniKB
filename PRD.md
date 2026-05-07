# OmniKB 项目结构化总览

## 一、项目概述
- **名称**：OmniKB — 通用 AI 知识库 Agent
- **核心理念**：全信息渠道摄入 + 语义可检索 + MCP 协议对外开放
- **关键技术**：多模态摄取（文本/视频/音频/网页），混合检索，Agent 协作，MCP Server

## 二、技术架构
### 2.1 前端
- 技术：Vanilla HTML/CSS/JS + TailwindCSS CDN
- 主要页面：
  - 🖥 Upload Panel（拖拽上传、URL/网页输入、进度监控）
  - 🔍 Search（语义搜索、混合搜索、过滤、高亮溯源）
  - 💬 Chat / RAG（流式对话、引用展示）
  - 📚 KB Manager（条目/来源/标签管理）
  - ⚙ Settings（LLM/Embedding 配置）

### 2.2 后端（FastAPI）
- 核心模块：
  - API：`/ingest`，`/search`，`/chat`，`/kb`，`/ws`
  - Orchestrator Agent（LangGraph 调度）
  - Specialist Agents：
    - **DocAgent** – PDF/DOCX/MD/TXT
    - **MediaAgent** – Whisper 转录视频/音频
    - **WebAgent** – 三层网络采集
    - **QueryAgent** – RAG 检索、重排序、LLM 综合

### 2.3 网络采集三层
- **Layer 1**：**scrapling** (Fetcher 树) – 静态/动态/反爬绕过
- **Layer 2**：**agent-browser** – 登录交互、滚动截图、多标签抓取
- **Layer 3**：**jshookmcp** – JS 逆向、CDP 拦截、API 捕获

### 2.4 处理管道
- 分块 → 向量化 → 元数据抽取 → 去重 → 索引入库

### 2.5 存储层
- **Qdrant**：向量库（语义搜索、BM25 混合、Payload 过滤）
- **SQLite / PostgreSQL**：元数据（来源、标签、时间等）
- **file_store**：原始文件、转录文本、截图

### 2.6 MCP Server (FastMCP)
- 对外暴露工具：
  - `search_kb`
  - `ask_kb`
  - `ingest_url`
  - `ingest_text`
  - `list_sources`
  - `get_chunk`
- 传输模式：stdio / SSE（兼容 Claude/Cursor 等）

## 三、功能需求分级
### 3.1 数据摄入 (P0-P2)
| ID | 功能 | 优先级 |
|----|------|--------|
| F1.1 | 上传文件（TXT/MD/PDF/DOCX/HTML/JSON/CSV） | P0 |
| F1.2 | 视频转录 | P0 |
| F1.3 | 音频转录 | P0 |
| F1.4 | URL 单页抓取 | P0 |
| F1.5 | 整站爬取 | P1 |
| F1.6 | Cloudflare/反爬站点 | P1 |
| F1.7 | 需要登录的站点 | P1 |
| F1.8 | SPA 动态渲染 | P1 |
| F1.9 | 粘贴文本/代码 | P0 |
| F1.10 | MCP ingest_url | P1 |

### 3.2 处理流程 (P0-P2)
| ID | 功能 | 优先级 |
|----|------|--------|
| F2.1 | 智能分块 | P0 |
| F2.2 | 向量嵌入 | P0 |
| F2.3 | BM25 索引 | P0 |
| F2.4 | 元数据提取 | P0 |
| F2.5 | 内容去重 | P1 |
| F2.6 | 图像 OCR | P1 |
| F2.7 | 视频帧描述 | P2 |
| F2.8 | 自动标签 | P1 |

### 3.3 检索与问答 (P0-P1)
| ID | 功能 | 优先级 |
|----|------|--------|
| F3.1 | 语义搜索 | P0 |
| F3.2 | 混合搜索 | P0 |
| F3.3 | 过滤搜索 | P0 |
| F3.4 | RAG 问答 | P0 |
| F3.5 | 引用溯源 | P0 |
| F3.6 | 多轮对话记忆 | P1 |
| F3.7 | Re-rank | P1 |
| F3.8 | 流式输出 | P0 |

### 3.4 知识管理
| ID | 功能 | 优先级 |
|----|------|--------|
| F4.1 | 条目浏览 | P0 |
| F4.2 | 来源管理 | P0 |
| F4.3 | 标签体系 | P1 |
| F4.4 | 摄取任务队列监控 | P0 |
| F4.5 | 命名空间隔离 | P2 |
| F4.6 | 导出 | P2 |

### 3.5 MCP 接口 (P0-P1)
| ID | 功能 | 优先级 |
|----|------|--------|
| F5.1 | 6 个标准工具 | P0 |
| F5.2 | API Key 鉴权 | P0 |
| F5.3 | stdio + SSE | P0 |
| F5.4 | 调用日志 | P1 |
| F5.5 | 速率限制 | P1 |

## 四、技术栈速览
- **前端**：Vanilla JS, TailwindCSS, Marked.js
- **后端**：Python 3.11+, FastAPI, LangGraph, LangChain, FastMCP
- **向量库**：Qdrant (生产级，混合搜索)
- **元数据库**：SQLite (单机) / PostgreSQL (集群)
- **文件处理**：pdfplumber, python-docx, openai-whisper
- **网络采集**：scrapling, agent-browser, jshookmcp
- **嵌入模型**：text-embedding-3-small (云) / bge-m3 (本地)
- **LLM**：GPT-4o / Claude 3.5 (云) / Ollama (本地)
- **部署**：Docker Compose

## 五、项目目录结构
```
omnikb/
├── docker-compose.yml
├── .env.example
├── frontend/
│   ├── index.html
│   ├── css/main.css
│   └── js/
│       ├── app.js
│       ├── upload.js
│       ├── search.js
│       ├── chat.js
│       ├── kb-manager.js
│       └── settings.js
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py
│   ├── config.py
│   ├── api/
│   │   ├── ingest.py
│   │   ├── search.py
│   │   ├── chat.py
│   │   └── kb.py
│   ├── agents/
│   │   ├── orchestrator.py
│   │   ├── doc_agent.py
│   │   ├── media_agent.py
│   │   ├── web_agent.py
│   │   └── query_agent.py
│   ├── pipeline/
│   │   ├── chunker.py
│   │   ├── embedder.py
│   │   ├── extractor.py
│   │   └── deduper.py
│   ├── storage/
│   │   ├── vector_store.py
│   │   ├── metadata_db.py
│   │   └── file_store.py
│   └── mcp_server/
│       ├── server.py
│       └── tools.py
└── docs/
    ├── PRD.md
    ├── API.md
    └── DEPLOY.md
```

## 六、开发迭代路线
| 阶段 | 周期 | 交付物 |
|------|------|--------|
| P0 MVP | 2 周 | 文本/PDF 上传 + ChromaDB/Qdrant + 搜索 + RAG 对话 + 基础 UI |
| P1 全渠道 | +2 周 | 视频/音频转录、scrapling 网页采集、MCP Server 上线 |
| P2 深度采集 | +2 周 | agent-browser 交互式采集、jshookmcp 高级爬取、重排序 |
| P3 生产化 | +2 周 | Docker 一键部署、命名空间隔离、监控、权限 |

## 七、架构图（文字版）
```
┌─────────────────────────────────────────────────────────────────────────┐
│                         OmniKB System Architecture                       │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    FRONTEND  (Vanilla HTML/CSS/JS)                   ││
│  │  Upload Panel │ URL/Web Input │ Chat Search │ KB Manager │ Settings  ││
│  └─────────────────────────────┬───────────────────────────────────────┘│
│                                 │ REST / WebSocket                       │
│  ┌──────────────────────────────▼───────────────────────────────────────┐│
│  │                    BACKEND API  (FastAPI)                             ││
│  │  /ingest  /search  /chat  /kb  /mcp  /ws                             ││
│  └──────┬──────────────────────────────────────────────────┬────────────┘│
│         │                                                  │             │
│  ┌──────▼──────────────────────────┐    ┌─────────────────▼─────────────┐│
│  │     ORCHESTRATOR AGENT          │    │    MCP SERVER (FastMCP)        ││
│  │  (LangGraph)                    │    │  search_kb,ask_kb,ingest_url.. ││
│  └──────┬──────────────────────────┘    └───────────────────────────────┘│
│         │ dispatches                                                     │
│  ┌──────┴───────────────────────────────────────────────────────────────┐│
│  │                      SPECIALIST AGENTS                                ││
│  │  DocAgent  MediaAgent  WebAgent (三层采集)  QueryAgent                ││
│  └──────┬───────────────────────────────────────────────────────────────┘│
│         │                                                                 │
│  ┌──────▼─────────────────────────────────────────────────────────────┐  │
│  │                      PROCESSING PIPELINE                             │  │
│  │  Chunking → Embedding → Metadata Extract → Dedup → Index            │  │
│  └──────┬─────────────────────────────────────────────────────────────┘  │
│         │                                                                 │
│  ┌──────▼─────────────────────────────────────────────────────────────┐  │
│  │                        STORAGE LAYER                                 │  │
│  │  [Qdrant]  [SQLite/PostgreSQL]  [File Store]                        │  │
│  └────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
```

## 八、差异化亮点
- ✅ 原生视频/音频转录 → 文本化入库
- ✅ 标准化 MCP Server，任何 AI Agent 可直接调用知识库
- ✅ 三层网络采集体系覆盖 99% 网页场景
- ✅ 代理协作模式（Orchestrator + 专家代理）
- ✅ 可选云/本地模型，适应不同隐私与成本需求