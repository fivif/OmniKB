# OmniKB — Universal AI Knowledge Base Agent

全渠道摄入 · 混合语义检索 · RAG 流式对话 · MCP 协议开放 · Agent 智能采集

## 快速开始

```bash
# 1. 配置环境变量
cp .env.example .env    # 编辑 .env，填入 API Key

# 2. 安装依赖
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. 启动（默认 QDRANT_MODE=local 本地文件持久化，无需额外服务）
python main.py          # http://localhost:6886
```

## 核心功能

### 数据摄入

| 渠道 | 说明 |
|---|---|
| 文件上传 | TXT / MD / PDF / DOCX / HTML / JSON / CSV |
| 视频转录 | MP4 / MKV / AVI / MOV / WebM → faster-whisper + ffmpeg |
| 音频转录 | MP3 / WAV / M4A / OGG / FLAC |
| URL 智能抓取 | AI Agent 自主判断策略，四层 fallback（httpx → scrapling → patchright → jshook CDP） |
| 粘贴文本 | 任意文本直接入库 |
| 图片 OCR | Vision Agent，PDF 低文字页自动 OCR |
| 视频帧描述 | 间隔截帧 + VL 模型描述 |
| Cookie 注入 | 支持认证页面采集 |

质量保障：
- **Web Judge** — LLM 评分 0-10，低于阈值自动丢弃
- **URL 分析** — 规则 + LLM 双层分析页面采集策略
- **研究状态追踪** — record_fact / close_subgoal 显式维护事实账本

### 检索

- **混合搜索**：Dense (BGE-M3 1024d) + Sparse (BM25) + RRF 融合
- **重排序**：Cross-encoder `bge-reranker-v2-m3` 精排（可选开关）
- **查询扩展**：领域词表覆盖 + 长查询自动分解子查询 + 轮询合并
- **结果多样化**：同来源最多 3 条，跨来源覆盖
- **过滤搜索**：按来源 / 类型 / 标签筛选
- **高亮溯源**：命中关键词 `<mark>` 标记
- **降级容错**：嵌入 API 故障时自动回退为纯 LLM 模式

### RAG 对话

- SSE 流式输出，引用溯源（chunk 级，含分数和来源 URL）
- 迭代检索：LLM 判断上下文充分性，不足时自动补充（最多 2 轮）
- 多轮会话持久化（SQLite），支持 DeepSeek 与第三方兼容网关
- Agentic Chat 模式：Agent 可自主调用 search_kb / list_sources / fetch_url

### MCP Server

对外暴露 8 个标准工具，支持 **stdio** 和 **SSE** 双传输模式：

| 工具 | 说明 |
|---|---|
| `search_kb` | 混合搜索知识库 |
| `ask_kb` | 检索上下文 + LLM 综合回答 |
| `ingest_url` | 智能抓取并摄入 URL（支持 cookies/intent） |
| `ingest_text` | 摄入文本 |
| `list_sources` | 列出知识库来源 |
| `get_chunk` | 按 ID 获取 chunk |
| `browser_fetch` | 浏览器渲染抓取 |
| `jshook_call` | jshookmcp CDP 工具调用 |

特性：Bearer Token 鉴权、滑动窗口速率限制（60次/60秒/IP）、调用日志持久化（SQLite）。

### Agent 运行时

自研 `agent_core` — Provider 无关的 Agent 循环引擎（2,292 行，13 文件）：

- **5 步生命周期**：ContextTransform → LLMStream → ToolExec → SteeringCheck → GracefulStop
- **9 种类型化事件**：SSE 实时广播（agent_start, turn_start, message_start/end, tool_execution_start/end, turn_end, agent_end）
- **BudgetTracker 预算守卫**：input/output token、wall-clock 三重上限，超额优雅终止，附带完整快照
- **反思检查点**：每 N 次工具调用注入自检提示，替代硬上限——Agent 自行总结进度、关闭子目标、调整方向
- **消息压缩**：Token 感知自动摘要压缩（双触发：上下文窗口接近 + 绝对 token 阈值）
- **提示缓存**：DeepSeek / OpenAI-compatible 缓存适配，减少重复 Token 消耗
- **转向注入**：运行中可接收外部指令（中断 / 转向），支持真 human-in-the-loop
- **技能记忆**：`recall_skill` → `save_skill` 闭环，常用 recipe 自动上浮
- **工具输出截断**：超量自动溢出到磁盘，LLM 仅见预览

### Web Agent 三阶段循环

```
Plan → Execute → Verify

1. Plan:   分析 URL 拓扑，输出 subgoals + success_criteria
2. Execute: 四层工具梯（http_get → browser_get_text → jshook CDP），自动升级
3. Verify:  强制 self_check，不足则补充，2 次失败后诚实输出
```

## 技术架构

```
┌──────────────────────────────────────────────────────────────┐
│              FRONTEND  Vanilla JS + TailwindCSS              │
│  Upload · Search · Chat · KB Manager · Scenarios · Settings │
│                   Agent Console (底部实时)                    │
└──────────────────────┬───────────────────────────────────────┘
                       │ REST / SSE
┌──────────────────────▼───────────────────────────────────────┐
│                  BACKEND API  FastAPI                        │
│  /ingest  /search  /chat  /kb  /agent  /scenarios  /settings│
│  /metrics  /mcp                                              │
└────┬──────────────────────────────────┬──────────────────────┘
     │                                  │
┌────▼────────────────────┐  ┌──────────▼──────────────────────┐
│  AGENT SYSTEM           │  │  MCP SERVER  FastMCP           │
│  agent_core 运行时       │  │  8 工具 · SSE/stdio · 鉴权    │
│  ──────────────────     │  └─────────────────────────────────┘
│  WebAgent  DocAgent     │
│  MediaAgent  VisionAgent│
│  WebJudge  URLAnalyst   │
└────┬────────────────────┘
     │
┌────▼─────────────────────────────────────────────────────────┐
│                PROCESSING PIPELINE                           │
│  AutoTag → Chunk → Embed(Dense∥Sparse) → Dedup → Rerank → Index │
└────┬─────────────────────────────────────────────────────────┘
     │
┌────▼─────────────────────────────────────────────────────────┐
│                   STORAGE LAYER                              │
│   Qdrant (向量)  │  SQLite (元数据 · WAL)  │  File Store     │
└──────────────────────────────────────────────────────────────┘
```

## 项目结构

```
OmniKB/
├── .env.example
├── README.md
├── docs/                          # API + 部署文档
├── tests/                         # agent_core 单元测试 + QA 检索评估
├── frontend/
│   ├── index.html
│   ├── kb-chat.html
│   ├── scenario-api.html
│   ├── ominIKB.png                # Logo 源文件
│   ├── favicon-32.png
│   ├── logo-64.png / logo-128.png
│   ├── omnibot-widget.js          # 嵌入式聊天组件
│   ├── css/
│   │   ├── main.css
│   │   ├── tokens.css             # 设计令牌（颜色/间距/字体）
│   │   ├── reset.css              # CSS Reset
│   │   ├── layout.css             # 全局布局
│   │   ├── components/            # 组件样式（button/card/input/toast/…）
│   │   └── panels/                # 面板样式（chat/upload/search/kb/…）
│   └── js/
│       ├── app.js                 # 全局状态、路由、Tab 切换
│       ├── theme.js               # 明暗主题切换
│       ├── upload.js              # 摄入面板（拖拽/URL/文本/任务队列）
│       ├── search.js              # 检索工作台（混合/语义/BM25）
│       ├── chat.js                # RAG 流式对话
│       ├── kb-manager.js          # 知识库管理（来源/标签/批量/导出）
│       ├── kb-chat.js             # 知识库问答面板
│       ├── settings.js            # 设置面板（LLM/模型/代理）
│       ├── agent-console.js       # Agent 实时控制台（类型化事件）
│       ├── citation-chain.js      # 引用链可视化
│       ├── command-palette.js     # 命令面板（⌘K）
│       ├── scenario-manager.js    # 场景/QA 管理
│       └── scenario-api.js        # 场景 API 客户端
└── backend/
    ├── requirements.txt
    ├── main.py                    # FastAPI 入口 · 中间件 · lifespan
    ├── config.py                  # Pydantic 配置（38 个 env 变量）
    ├── agent_core/                # Provider 无关 Agent 运行时
    │   ├── loop.py                # run_loop 主循环（5 步生命周期）
    │   ├── events.py              # AgentEvent + EventStream 广播总线
    │   ├── budget.py              # BudgetTracker 预算守卫
    │   ├── compaction.py          # Token 感知消息压缩
    │   ├── cache.py               # 提示缓存适配
    │   ├── steering.py            # 转向队列
    │   ├── tool.py                # ToolExecutor + batch 执行
    │   ├── truncate.py            # 工具输出截断 + 磁盘溢出
    │   ├── tokens.py              # Token 计数
    │   ├── hooks.py               # Hooks 接口
    │   ├── messages.py            # 消息类型
    │   └── state.py               # AgentState
    ├── agents/
    │   ├── orchestrator.py        # 摄入流水线调度
    │   ├── doc_agent.py           # 文档解析（TXT/MD/PDF/DOCX/HTML）
    │   ├── media_agent.py         # 音视频转录（faster-whisper + ffmpeg）
    │   ├── web_agent.py           # 网页抓取（四层 fallback）
    │   ├── web_judge.py           # LLM 页面质量评分 0-10
     │   ├── url_analyst.py         # 规则 + LLM 双层 URL 策略分析
     │   ├── vision_agent.py        # 图片 OCR + 视频帧描述
     │   ├── jshook_client.py       # JsHookMCP 客户端
     │   ├── llm.py                 # LLM 工厂（DeepSeek / 兼容网关）
     │   └── web/                   # Web Agent 子模块
     │       ├── loop.py            # web_agent_loop 主循环
    │       ├── handler.py         # 请求处理器 + 工具定义
    │       ├── prompts.py         # 系统提示词（Plan→Execute→Verify）
    │       ├── research_state.py  # 研究状态追踪
    │       ├── session.py         # 会话持久化
    │       ├── pool.py            # JsHook / Playwright 连接池
    │       ├── seeds/             # 种子 URL 模板
    │       └── tools/             # http / browser / jshook / parse / memory
    ├── pipeline/
    │   ├── chunker.py             # 文本分块（800 chars / 160 overlap）
    │   ├── embedder.py            # Dense(1024d) + Sparse(BM25) 嵌入
    │   ├── extractor.py           # 元数据提取
    │   ├── deduper.py             # SHA256 去重
    │   ├── reranker.py            # Cross-encoder 重排序
    │   ├── tagger.py              # LLM 自动标签
    │   └── query_expander.py      # 查询扩展
    ├── storage/
    │   ├── vector_store.py        # Qdrant（local/remote/memory）
    │   ├── metadata_db.py         # SQLite（aiosqlite · WAL）
    │   └── file_store.py          # 原始文件存储
    ├── mcp_server/
    │   ├── server.py              # FastMCP + SSE 工厂
    │   ├── tools.py               # 8 个 MCP 工具 + 调用日志
    │   └── run_stdio.py           # stdio 入口
    ├── api/
    │   ├── ingest.py              # 摄入（file/text/url + 任务管理）
    │   ├── search.py              # 检索（hybrid/semantic/bm25）
    │   ├── chat.py                # RAG 流式对话（SSE + 迭代检索）
    │   ├── kb.py                  # 知识库管理（CRUD + 批量 + 导出）
    │   ├── kb_api.py              # 知识库问答 API
    │   ├── agent_stream.py        # Agent SSE 事件流 + 转向
    │   ├── settings.py            # 运行时配置读写
    │   ├── scenarios.py           # 场景/QA 管理
    │   ├── metrics.py             # Prometheus 指标
    │   ├── mcp_logs.py            # MCP 调用日志查询
    │   └── chat_tools.py          # Agentic Chat 专用工具
    └── utils/
        └── agent_bus.py           # Agent 消息总线
```

## API 端点

### 摄入

| Method | Path | 说明 |
|---|---|---|
| `POST` | `/ingest/file` | 上传文件 |
| `POST` | `/ingest/text` | 摄入文本 |
| `POST` | `/ingest/url` | 智能抓取 URL |
| `GET` | `/ingest/tasks` | 任务列表 |
| `GET` | `/ingest/tasks/{id}` | 任务状态 |

### 检索 & 对话

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/search` | 混合检索（q, top_k, mode, filter） |
| `POST` | `/chat` | RAG 流式对话（SSE） |
| `DELETE` | `/chat/sessions/{thread_id}` | 删除会话 |
| `GET` | `/chat/models` | 可用模型列表 |

### 知识库管理

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/kb/sources` | 来源列表 |
| `GET` | `/kb/sources/{id}` | 来源详情 + chunks |
| `DELETE` | `/kb/sources/{id}` | 删除来源及数据 |
| `PATCH` | `/kb/sources/{id}/tags` | 更新标签 |
| `POST` | `/kb/sources/batch-delete` | 批量删除 |
| `POST` | `/kb/sources/batch-tag` | 批量标签 |
| `GET` | `/kb/tags` | 标签列表 |
| `GET` | `/kb/stats` | 知识库统计 |
| `GET` | `/kb/export` | 导出（JSON/CSV/ZIP） |

### Agent

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/agent/events` | Agent 事件流 SSE（v1） |
| `GET` | `/agent/v2/events` | Agent 事件流 SSE（v2 类型化） |
| `POST` | `/agent/{task_id}/steer` | 向运行中 Agent 注入指令 |
| `GET` | `/agent/sessions` | Session 列表 |
| `GET` | `/agent/sessions/{id}` | Session 详情 + 消息历史 |
| `GET` | `/agent/active-tasks` | 活跃任务列表 |

### 场景管理

| Method | Path | 说明 |
|---|---|---|
| `GET` | `/scenarios` | 场景列表 |
| `POST` | `/scenarios` | 创建场景 |
| `GET`/`PUT`/`DELETE` | `/scenarios/{id}` | 场景 CRUD |
| `GET`/`POST`/`DELETE` | `/scenarios/{id}/sources` | 场景来源管理 |
| `GET`/`POST`/`DELETE` | `/scenarios/{id}/keys` | 场景答案键管理 |
| `POST` | `/scenarios/{id}/agent/assist` | Agent 辅助标注 |

### 设置 & 运维

| Method | Path | 说明 |
|---|---|---|
| `GET`/`POST` | `/settings/proxy` | 代理配置 |
| `GET`/`POST` | `/settings/system-prompt` | RAG 系统提示词 |
| `GET`/`POST` | `/settings/llm` | LLM 参数 |
| `GET` | `/settings/models/status` | 模型下载状态 |
| `POST` | `/settings/models/download` | 下载模型 |
| `GET` | `/health` | 健康检查 |
| `GET` | `/metrics` | Prometheus 指标 |
| `GET/POST` | `/mcp` | MCP SSE 端点 |
| `GET` | `/mcp/logs` | MCP 调用日志 |

## 环境变量

### LLM

| 变量 | 说明 | 默认值 |
|---|---|---|
| `LLM_PROVIDER` | deepseek / custom | `deepseek` |
| `LLM_MODEL` | 模型名称 | `deepseek-v4-pro` |
| `LLM_BASE_URL` | DeepSeek 或第三方兼容网关地址（`deepseek` 可留空走官方默认） | — |
| `LLM_API_KEY` | DeepSeek 或第三方兼容 API 密钥 | — |
| `LLM_EXTRA_BODY_JSON` | OpenAI-compatible extra_body（如 `{"enable_thinking": false}`） | — |
| `OPENAI_API_KEY` | 仅 embedding_provider=openai 或兼容旧配置时使用 | — |

### Embedding

| 变量 | 说明 | 默认值 |
|---|---|---|
| `EMBEDDING_PROVIDER` | siliconflow / openai | `siliconflow` |
| `EMBEDDING_MODEL` | 嵌入模型 | `BAAI/bge-m3` |
| `EMBEDDING_DIMENSIONS` | 向量维度 | `1024` |
| `SILICONFLOW_API_KEY` | 硅基流动 API Key | — |
| `SILICONFLOW_BASE_URL` | 硅基流动 API 地址 | `https://api.siliconflow.cn/v1` |
| `EMBEDDING_CONCURRENCY` | 最大并发嵌入请求 | `3` |
| `EMBEDDING_BATCH_SIZE` | 每次 API 调用文本数 | `32` |
| `EMBEDDING_RPM_LIMIT` | 每分钟请求上限（0=关闭） | `10` |

### 存储 & Qdrant

| 变量 | 说明 | 默认值 |
|---|---|---|
| `QDRANT_URL` | Qdrant 服务地址 | `http://localhost:6333` |
| `QDRANT_MODE` | local / remote / memory | `local` |
| `QDRANT_LOCAL_PATH` | 本地持久化路径 | `./data/qdrant` |
| `QDRANT_COLLECTION` | 集合名称 | `omnikb` |
| `DATA_DIR` | 数据目录 | `./data` |
| `SQLITE_PATH` | SQLite 数据库路径 | `./data/omnikb.db` |

### Vision 多模态

| 变量 | 说明 | 默认值 |
|---|---|---|
| `VISION_ENABLED` | 视觉能力开关 | `false` |
| `VISION_PROVIDER` | 视觉 LLM 提供商（空=继承 LLM_PROVIDER；支持 deepseek/custom） | — |
| `VISION_MODEL` | 视觉模型名称 | `gpt-4o-mini` |
| `VISION_API_KEY` | 视觉 API 密钥（空=继承） | — |
| `VISION_BASE_URL` | 视觉 API 地址（空=继承） | — |
| `VISION_FRAME_INTERVAL` | 视频帧间隔（秒，0=禁用） | `60` |
| `VISION_PDF_OCR_THRESHOLD` | PDF 低文字页 OCR 阈值 | `80` |

### Web Agent

| 变量 | 说明 | 默认值 |
|---|---|---|
| `WEB_JUDGE_ENABLED` | LLM 页面评分过滤 | `false` |
| `WEB_JUDGE_MIN_SCORE` | 最低入库分数（0-10） | `4` |
| `WEB_AGENT_MAX_INPUT_TOKENS` | input token 上限（0=关闭） | `200000` |
| `WEB_AGENT_MAX_OUTPUT_TOKENS` | output token 上限 | `50000` |
| `WEB_AGENT_MAX_SECONDS` | 墙钟时间上限（秒） | `300` |
| `WEB_AGENT_MAX_TOOL_CALLS` | 工具调用次数上限（0=关闭） | `0` |
| `WEB_AGENT_REFLECTION_INTERVAL` | 反思检查点间隔（次，0=关闭） | `8` |
| `JSHOOK_POOL_SIZE` | jshook 连接池大小 | `2` |
| `PLAYWRIGHT_POOL_SIZE` | Playwright 浏览器池大小 | `1` |

### Chat Agent

| 变量 | 说明 | 默认值 |
|---|---|---|
| `CHAT_AGENT_ENABLED` | 启用 Agentic Chat | `true` |
| `CHAT_AGENT_MAX_TURNS` | 最大对话轮次 | `6` |
| `CHAT_AGENT_MAX_TOOL_CALLS` | 工具调用上限 | `10` |
| `RAG_SYSTEM_PROMPT` | RAG 系统提示词 | 内置默认 |

### 其他

| 变量 | 说明 | 默认值 |
|---|---|---|
| `WHISPER_MODEL_SIZE` | faster-whisper 模型大小 | `base` |
| `RERANKER_ENABLED` | 重排序开关 | `false` |
| `RERANKER_MODEL` | 重排序模型 | `BAAI/bge-reranker-v2-m3` |
| `AUTOTAG_ENABLED` | 自动标签 | `false` |
| `MCP_API_KEY` | MCP 鉴权密钥 | 必填 |
| `HTTP_PROXY` | HTTP 代理地址 | — |
| `HF_ENDPOINT` | HuggingFace 镜像 | — |
| `FASTEMBED_CACHE_PATH` | BM25 模型缓存目录 | `~/.cache/fastembed` |

## 测试

### agent_core 单元测试

10 个测试文件覆盖核心模块：loop、tool、events、compaction、cache、steering、truncate、tokens、state、messages。

### 检索评估

测试数据由 AI 搜索互联网整理生成，评分基于检索结果与期望关键词的匹配度，**仅反映系统检索召回能力，不构成对任何产品或事实的断言**。

#### DeepSeek 知识库（24 题）

12 篇 AI 生成的 DeepSeek 产品线文档，覆盖公司背景、V4/V3/R1/Coder/VL2/OCR/Prover 各模型、API 文档、Agent 集成、产品时间线共 11 个类别，19 个来源、约 150 个 chunk。

| 问题 | 期望关键词 | 检索结果 | 评分 |
|---|---|---|---|
| DeepSeek-V3 总参数量和激活参数量？ | `671B`, `37B`, `MoE` | top1 chunk 精确命中 | 优秀 |
| DeepSeek-V4-Pro 参数？上下文长度？ | `862B`, `1M` | top1 命中 862B，top3 命中 1M | 优秀 |
| DeepSeek-R1 发布时间？许可证？ | `2025/01/20`, `MIT` | top1 命中完整日期 + MIT | 优秀 |
| DeepSeek-Coder 支持语言数？训练数据量？ | `87`, `2T` | top1 命中 87 languages，top2 命中 2T | 优秀 |
| DeepSeek API 的 OpenAI 兼容 Base URL？ | `api.deepseek.com` | top4 chunk 命中完整 URL | 部分覆盖 |
| DeepSeek 产品线包含哪些模型系列？ | 7 个系列名 | 覆盖 V4/V3/R1/Coder/VL2/OCR/Prover 全部 | 优秀 |

#### OpenAI 知识库（30 题）

9 篇 AI 生成的 OpenAI 产品文档（公司背景 / GPT / 推理模型 / GPT-5 / 图像视频 / 语音 / 嵌入审核 / API 服务 / 定价限制），覆盖 10 个类别。

| 问题 | 期望关键词 | 检索结果 | 评分 |
|---|---|---|---|
| GPT-4o 上下文窗口？定价？ | `128K`, `2.50`, `10.00` | top1 chunk 命中 128K + $2.50/$10.00 | 优秀 |
| o 系列推理模型包含哪些型号？ | `o1`, `o3`, `o4-mini`, `o3-pro` | 跨 chunk 覆盖全部 | 优秀 |
| Whisper 定价？支持音频格式？ | `0.006`, `flac`, `mp3`, `wav`, `ogg` | top1 命中全部 | 优秀 |
| Rate Limit Tier 5 的 RPM 和 TPM？ | `30000`, `150000000` | top1 chunk 精确命中 | 优秀 |
| DALL-E 3 支持尺寸？HD 1024x1024 价格？ | `1024`, `0.08` | top1 chunk 命中 | 优秀 |

两套共 **54 题**。迭代优化措施：

- **分块调优**：1000/200 → 800/160，匹配精度明显提升
- **查询扩展**：宽泛问题自动拆分为多路子查询
- **Cross-encoder 重排**：长尾问题召回被埋答案
- **来源去重**：同来源最多 3 条，避免单一文档霸榜
- **迭代检索**：LLM 判断上下文充分性，不足时自动补充

## 致谢

- [**jshookmcp**](https://github.com/vmoranv/jshookmcp) — 下一代 JS 逆向 MCP 工具，CDP 拦截和动态脚本注入，Web Agent Layer 3 核心依赖
- [**claude-code-skill-scrapling**](https://github.com/Cedriccmh/claude-code-skill-scrapling) — 基于 scrapling 的网页抓取最佳实践，Layer 1 & 2 参考实现
- [**agent-browser**](https://github.com/vercel-labs/agent-browser) — Vercel Labs 浏览器自动化 CLI，已切换为常驻 patchright PlaywrightPool 实现
- [**Qdrant**](https://qdrant.tech/) — 高性能向量数据库，原生 Dense + Sparse 混合搜索和 RRF 融合
- [**FastEmbed**](https://github.com/qdrant/fastembed) — 轻量级嵌入库，BM25 稀疏向量生成
- [**FastMCP**](https://github.com/jlowin/fastmcp) — MCP Server 框架

## License

MIT
