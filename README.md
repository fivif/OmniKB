# OmniKB — Universal AI Knowledge Base Agent

全信息渠道摄入 + 混合语义检索 + RAG 流式对话 + MCP 协议开放协议

## 快速开始

```bash
# 1. 配置环境变量
cp .env.example .env    # 编辑 .env，填入 API Key

# 2. 安装依赖
cd backend
python -m venv venv
venv\Scripts\activate   # Windows
pip install -r requirements.txt

# 3. 启动
python main.py          # http://localhost:8000
```

Docker 一键部署：

```bash
docker compose up -d    # 启动 Qdrant + Backend
```

## 核心功能

### 数据摄入

| 渠道 | 状态 | 说明 |
|------|------|------|
| 文件上传 | 已完成 | TXT / MD / PDF / DOCX / HTML / JSON / CSV |
| 视频转录 | 已完成 | MP4 / MKV / AVI / MOV / WebM → faster-whisper + ffmpeg |
| 音频转录 | 已完成 | MP3 / WAV / M4A / OGG / FLAC |
| URL 单页 | 已完成 | scrapling (静态/动态) → httpx 三层 fallback |
| 整站爬取 | 已完成 | BFS 同域爬取，robots.txt 合规，并发限速 |
| 粘贴文本 | 已完成 | 任意文本直接入库 |
| Web Judge | 已完成 | LLM 评分 0-10，低分自动丢弃 |
| URL 分析 | 已完成 | 意图相关性评分，过滤无效链接 |
| 图片 OCR | 已完成 | Vision Agent，PDF 低文字页 OCR |
| 视频帧描述 | 已完成 | 间隔截帧 + VL 模型描述 |

### 检索

- **混合搜索**：Dense (BGE-M3 1024d) + Sparse (BM25) + RRF 融合
- **重排序**：Cross-encoder `bge-reranker-v2-m3` 精排
- **查询扩展**：7 组领域词表，长查询自动分解子查询
- **结果多样化**：同来源最多 2 条，跨来源覆盖
- **过滤搜索**：按来源 / 类型 / 标签筛选
- **高亮溯源**：命中关键词 `<mark>` 标记

### RAG 对话

- SSE 流式输出
- 引用溯源（chunk 级，含分数和来源）
- 多轮会话持久化（SQLite）
- 多 Provider：DeepSeek / OpenAI / Anthropic / Ollama / 任意 OpenAI 兼容 API

### MCP Server

对外暴露 6 个标准工具，支持 **stdio** 和 **SSE** 双传输模式：

| 工具 | 说明 |
|------|------|
| `search_kb` | 混合搜索知识库 |
| `ask_kb` | 检索上下文 + LLM 综合回答 |
| `ingest_url` | 抓取并摄入 URL |
| `ingest_text` | 摄入文本 |
| `list_sources` | 列出知识库来源 |
| `get_chunk` | 按 ID 获取 chunk |

特性：Bearer Token 鉴权、滑动窗口速率限制 (60次/60秒/IP)、MCP 调用日志持久化。

Claude Desktop 配置示例：

```json
{
  "mcpServers": {
    "omnikb": {
      "command": "python",
      "args": ["path/to/backend/mcp_server/run_stdio.py"],
      "env": {
        "LLM_API_KEY": "sk-...",
        "MCP_API_KEY": "your-mcp-key",
        "QDRANT_URL": "http://localhost:6333"
      }
    }
  }
}
```

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                  FRONTEND  Vanilla JS + TailwindCSS          │
│  Upload Panel │ URL/Web Input │ Chat Search │ KB Manager     │
└────────────────────────┬────────────────────────────────────┘
                         │ REST / SSE
┌────────────────────────▼────────────────────────────────────┐
│                 BACKEND API  FastAPI                         │
│  /ingest  /search  /chat  /kb  /mcp  /ws                    │
└────┬────────────────────────────────────────────┬───────────┘
     │                                            │
┌────▼──────────────────────┐    ┌────────────────▼───────────┐
│   ORCHESTRATOR            │    │  MCP SERVER  FastMCP        │
│   调度 Agent 协作          │    │  6 tools, SSE/stdio, auth   │
└────┬──────────────────────┘    └────────────────────────────┘
     │
┌────▼────────────────────────────────────────────────────────┐
│              SPECIALIST AGENTS                               │
│  DocAgent  MediaAgent  WebAgent  VisionAgent  QueryAgent    │
│  ──────────────────────────────────────────────────────     │
│  Web 子模块: handler / loop / pool / session                 │
│  Tools: browser / http / jshook / parse / memory             │
└────┬────────────────────────────────────────────────────────┘
     │
┌────▼────────────────────────────────────────────────────────┐
│              PROCESSING PIPELINE                             │
│  Chunk → Embed (Dense + Sparse) → Extract → Dedup → Index   │
└────┬────────────────────────────────────────────────────────┘
     │
┌────▼────────────────────────────────────────────────────────┐
│                 STORAGE LAYER                                │
│  Qdrant (向量)  │  SQLite (元数据)  │  File Store (原始文件)  │
└─────────────────────────────────────────────────────────────┘
```

## 项目结构

```
OmniKB/
├── backend/
│   ├── main.py                  # FastAPI 入口，中间件，lifespan
│   ├── config.py                # 配置 (Pydantic Settings, .env)
│   ├── api/
│   │   ├── ingest.py            # 摄入 API (file/text/url/site)
│   │   ├── search.py            # 搜索 API (hybrid/semantic/bm25)
│   │   ├── chat.py              # RAG 流式对话 API
│   │   ├── kb.py                # 知识库管理 API
│   │   ├── agent_stream.py      # Agent 执行流式 API
│   │   └── mcp_logs.py          # MCP 调用日志查询
│   ├── agents/
│   │   ├── orchestrator.py      # 摄入流水线调度
│   │   ├── doc_agent.py         # 文档解析 (PDF/DOCX/HTML/CSV/JSON)
│   │   ├── media_agent.py       # 音视频转录 (faster-whisper)
│   │   ├── web_agent.py         # 网页抓取 + BFS 整站爬取
│   │   ├── vision_agent.py      # 图片 OCR + 视频帧描述
│   │   ├── web_judge.py         # LLM 页面质量评分
│   │   ├── url_analyst.py       # 链接相关性分析
│   │   ├── smart_fetcher.py     # 智能抓取
│   │   ├── jshook_client.py     # JS 逆向 MCP 客户端 (Layer 3)
│   │   ├── llm.py               # LLM 调用封装
│   │   └── web/                 # Web Agent 子模块
│   │       ├── handler.py       # 请求处理器
│   │       ├── loop.py          # Agent 主循环
│   │       ├── pool.py          # 连接池管理
│   │       ├── session.py       # 会话管理
│   │       ├── prompts.py       # 提示词模板
│   │       ├── seeds/           # 种子 URL 模板 (arxiv/docs/github/pypi/wiki)
│   │       └── tools/           # 工具集 (browser/http/jshook/parse/memory)
│   ├── pipeline/
│   │   ├── chunker.py           # Markdown 感知递归分块
│   │   ├── embedder.py          # 混合嵌入 (Dense + Sparse)
│   │   ├── extractor.py         # 元数据提取
│   │   ├── deduper.py           # SHA256 内容去重
│   │   ├── reranker.py          # Cross-encoder 重排序
│   │   └── tagger.py            # LLM 自动标签
│   ├── storage/
│   │   ├── vector_store.py      # Qdrant 客户端 (remote/local/memory)
│   │   ├── metadata_db.py       # SQLite 数据库 (aiosqlite)
│   │   └── file_store.py        # 原始文件存储
│   ├── mcp_server/
│   │   ├── server.py            # FastMCP 工具定义 + SSE 工厂
│   │   ├── tools.py             # MCP 工具实现 + 调用日志
│   │   └── run_stdio.py         # stdio 模式入口
│   ├── utils/
│   │   └── agent_bus.py         # Agent 消息总线
│   ├── Dockerfile
│   └── requirements.txt
├── frontend/
│   ├── index.html               # SPA 入口 (5 Tab)
│   ├── css/main.css
│   └── js/
│       ├── app.js               # 全局状态、路由、Toast
│       ├── upload.js            # 上传面板 (拖拽/URL/文本/任务队列)
│       ├── search.js            # 搜索面板 (混合/语义/BM25)
│       ├── chat.js              # 对话面板 (流式 RAG)
│       ├── kb-manager.js        # 知识库管理 (来源/标签/chunk)
│       ├── settings.js          # 设置面板
│       └── agent-console.js     # Agent 执行控制台
├── docker-compose.yml
├── .env.example
└── README.md
```

## API 端点

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/ingest/file` | 上传文件 |
| `POST` | `/ingest/text` | 摄入文本 |
| `POST` | `/ingest/url` | 摄入 URL |
| `POST` | `/ingest/site` | 整站爬取 |
| `GET` | `/ingest/tasks` | 任务列表 |
| `GET` | `/search` | 搜索 (q, top_k, mode, filter) |
| `POST` | `/chat` | RAG 流式对话 (SSE) |
| `GET` | `/kb/sources` | 知识库来源 |
| `DELETE` | `/kb/sources/{id}` | 删除来源及数据 |
| `GET` | `/kb/stats` | 知识库统计 |
| `GET/POST` | `/mcp` | MCP SSE 端点 |
| `GET` | `/mcp/logs` | MCP 调用日志 |

详见 [docs/API.md](docs/API.md) | 部署指南 [docs/DEPLOY.md](docs/DEPLOY.md)

## 测试结果

### DeepSeek 知识库 QA 评测

基于 12 篇 AI 生成的 DeepSeek 产品文档（公司背景 / V4 / V3 / R1 / Coder / VL2 / OCR / Prover / API / Agent / 时间线），构建了 24 个事实性问答题，覆盖 11 个知识类别。

**声明**: 测试数据由 AI 生成，内容可能存在虚构和幻觉，**答案准确性不构成对模型或产品的断言**。评分仅基于 token 匹配，反映的是检索召回能力而非事实正确性。

**测试配置**

| 参数 | 值 |
|------|-----|
| Chunk size | 600 字符 |
| Chunk overlap | 120 字符 |
| 搜索模式 | Hybrid (Dense + BM25) |
| Query expansion | 启用 (7 组领域词表) |
| Reranker | bge-reranker-v2-m3 |
| 来源去重 | 每来源最多 2 条 |
| 嵌入模型 | BAAI/bge-m3 (1024d) |
| 向量库 | Qdrant local |

**结果概览**

| 指标 | v1 (基线) | v2 (优化后) |
|------|-----------|-------------|
| 总得分 / 满分 | — | — / 28 |
| Chunk size | 1000 / 200 | **600 / 120** |
| Reranker | 关闭 | **开启** |
| Query expansion | 无 | **7 组词表** |
| 结果多样化 | 无 | **max 2 per source** |

**优化效果** —— 五项改进显著提升了多源问题的覆盖面：

- **源级多样化**: 同来源最多保留 2 条，避免单个文档垄断 top-k
- **查询扩展**: 自动将宽泛问题分解为子查询，提升召回
- **查询归一化**: 日期/数字格式别名匹配（如 `2026/04/24` ↔ `2026年4月24日`）
- **Cross-encoder 重排**: 对检索结果精排，相关度排序更准确
- **更小分块**: 600 字符窗口提升匹配精度

### 摄入稳定性

- **已完成任务**: 150+ 条，覆盖 PDF 解析、DOCX 解析、音视频转录、整站爬取
- **已知错误**: 12 条任务失败，原因均为 API 侧限制——
  - **413 批量超限**: 单次请求 chunk 数超过 Embedding API 上限 (64)，已在后续批次自动拆分
  - **403 频率限制**: SiliconFlow API RPM 限制，等待额度恢复后重试即可
- **结论**: 无系统级 Bug，全链路稳定，失败可重试恢复

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QDRANT_MODE` | local / remote / memory | `local` |
| `LLM_PROVIDER` | custom / openai / anthropic / ollama | `custom` |
| `LLM_MODEL` | 模型名称 | `deepseek-v4-pro` |
| `LLM_BASE_URL` | API 地址 | — |
| `LLM_API_KEY` | API 密钥 | — |
| `EMBEDDING_PROVIDER` | siliconflow / openai | `siliconflow` |
| `EMBEDDING_MODEL` | 嵌入模型 | `BAAI/bge-m3` |
| `RERANKER_ENABLED` | 重排序开关 | `false` |
| `AUTOTAG_ENABLED` | 自动标签 | `false` |
| `VISION_ENABLED` | 视觉能力 | `false` |
| `WEB_JUDGE_ENABLED` | 页面评分过滤 | `false` |
| `MCP_API_KEY` | MCP 鉴权密钥 | 必填 |

## License

MIT
