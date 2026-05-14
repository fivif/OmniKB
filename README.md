# OmniKB — Universal AI Knowledge Base Agent

全信息渠道摄入 + 混合语义检索 + RAG 流式对话 + MCP 协议开放 + Agent 智能采集

## 快速开始

```bash
# 1. 配置环境变量
cp .env.example .env    # 编辑 .env，填入 API Key

# 2. 安装依赖
cd backend
python -m venv venv
source venv/bin/activate   # macOS / Linux
# venv\Scripts\activate    # Windows
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
| 文件上传 | ✅ | TXT / MD / PDF / DOCX / HTML / JSON / CSV |
| 视频转录 | ✅ | MP4 / MKV / AVI / MOV / WebM → faster-whisper + ffmpeg |
| 音频转录 | ✅ | MP3 / WAV / M4A / OGG / FLAC |
| URL 智能抓取 | ✅ | AI Agent 自动判断最佳策略，四层 fallback |
| 粘贴文本 | ✅ | 任意文本直接入库 |
| Web Judge | ✅ | LLM 评分 0-10，低分自动丢弃，AI 抓取失败叙事自动拒绝 |
| URL 分析 | ✅ | 规则 + LLM 双层分析，判断页面采集策略 |
| 图片 OCR | ✅ | Vision Agent，PDF 低文字页 OCR |
| 视频帧描述 | ✅ | 间隔截帧 + VL 模型描述 |
| 智能采集 | ✅ | 多工具 LLM Agent 自主采集（http/browser/cdp/link-discovery） |
| 登录态采集 | ✅ | Cookie 注入，支持认证页面 |

### 检索

- **混合搜索**：Dense (BGE-M3 1024d) + Sparse (BM25) + RRF 融合
- **重排序**：Cross-encoder `bge-reranker-v2-m3` 精排（可选开关）
- **查询扩展**：领域词表覆盖 + 长查询自动分解子查询 + 轮询合并
- **结果多样化**：同来源最多 3 条，跨来源覆盖
- **过滤搜索**：按来源 / 类型 / 标签筛选
- **高亮溯源**：命中关键词 `<mark>` 标记
- **降级容错**：嵌入 API 故障时自动回退为纯 LLM 模式，不中断服务

### RAG 对话

- SSE 流式输出
- 引用溯源（chunk 级，含分数和来源 URL）
- 迭代检索：LLM 判断上下文充分性，不足时自动补充搜索（最多 2 轮）
- 多轮会话持久化（SQLite）
- 多 Provider：DeepSeek / OpenAI / Anthropic / Ollama / 任意 OpenAI 兼容 API

### MCP Server

对外暴露 8 个标准工具，支持 **stdio** 和 **SSE** 双传输模式：

| 工具 | 说明 |
|------|------|
| `search_kb` | 混合搜索知识库 |
| `ask_kb` | 检索上下文 + LLM 综合回答 |
| `ingest_url` | 智能抓取并摄入 URL（支持 cookies/intent） |
| `ingest_text` | 摄入文本 |
| `list_sources` | 列出知识库来源 |
| `get_chunk` | 按 ID 获取 chunk |
| `browser_fetch` | 浏览器渲染抓取 |
| `jshook_call` | jshookmcp CDP 工具调用 |

特性：Bearer Token 鉴权、滑动窗口速率限制（60次/60秒/IP）、MCP 调用日志持久化（SQLite）。

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

### Agent 运行时

自研 `agent_core` — Provider 无关的 Agent 循环引擎：

- **5 步转向生命周期**：ContextTransform → LLMStream → ToolExec → SteeringCheck → GracefulStop
- **9 种类型化生命周期事件**：agent_start, turn_start, message_start/end, tool_execution_start/end, turn_end, agent_end → SSE 实时广播
- **预算守卫 `BudgetTracker`**：可设 input/output token、wall-clock、tool 调用次数（含 per-tool 上限），超额优雅终止并在 `agent_end` 事件携带快照 `final_status="budget_exceeded"`
- **消息压缩**：旧对话轮次自动摘要压缩，支持长任务不爆上下文
- **提示缓存**：Anthropic/OpenAI 缓存适配，减少重复 Token 消耗
- **转向注入**：运行中 Agent 可接收外部指令（中断/转向）
- **真 human-in-the-loop**：`ask_user(question, timeout_seconds)` 工具阻塞等待用户经 `/agent/{task_id}/steer` 回复，超时自动降级
- **研究状态追踪**：`record_fact` / `close_subgoal` 工具显式维护 `ResearchState`，与系统提示中的事实账本闭环
- **技能记忆自学习**：`recall_skill` 命中后异步累加 `success_count`，让常用 recipe 在排序中自然上浮
- **前端实时面板**：底部 Agent Console 展示 LLM 响应内容、工具调用与结果

## 技术架构

```
┌─────────────────────────────────────────────────────────────┐
│                  FRONTEND  Vanilla JS + TailwindCSS          │
│  Upload Panel │ URL/Web Input │ Chat Search │ KB Manager     │
│                     Agent Console (底部实时)                  │
└────────────────────────┬────────────────────────────────────┘
                         │ REST / SSE
┌────────────────────────▼────────────────────────────────────┐
│                 BACKEND API  FastAPI                         │
│  /ingest  /search  /chat  /kb  /agent  /settings  /metrics   │
└────┬────────────────────────────────────────────┬───────────┘
     │                                            │
┌────▼──────────────────────┐    ┌────────────────▼───────────┐
│   AGENT SYSTEM             │    │  MCP SERVER  FastMCP        │
│  Orchestrator 调度         │    │  8 工具, SSE/stdio, 鉴权    │
│  ─────────────────────     │    └────────────────────────────┘
│  DocAgent  MediaAgent      │
│  WebAgent (四层采集)       │
│  VisionAgent  WebJudge     │
│  URLAnalyst  SmartFetcher  │
│  ─────────────────────     │
│  agent_core 运行时         │
│  run_loop → Events → SSE   │
└────┬───────────────────────┘
     │
┌────▼────────────────────────────────────────────────────────┐
│              PROCESSING PIPELINE                             │
│  AutoTag → Chunk → Embed(Dense∥Sparse) → Dedup → Rerank → Index │
└────┬────────────────────────────────────────────────────────┘
     │
┌────▼────────────────────────────────────────────────────────┐
│                 STORAGE LAYER                                │
│  Qdrant (向量)  │  SQLite (元数据, 11 表, WAL)  │  File Store │
└─────────────────────────────────────────────────────────────┘
```

## 项目结构

```
OmniKB/
├── docker-compose.yml
├── .env.example
├── PRD.md
├── README.md
├── tests/                       # 检索评估（54题QA测试）
├── docs/                        # API + 部署文档
├── frontend/
│   ├── index.html
│   ├── css/main.css
│   └── js/
│       ├── app.js               # 全局状态、路由、Tab切换
│       ├── upload.js            # 上传面板（拖拽/URL/文本/任务）
│       ├── search.js            # 搜索面板（混合/语义/BM25）
│       ├── chat.js              # 对话面板（流式RAG/引用/Session）
│       ├── kb-manager.js        # 知识库管理（来源/标签/导出）
│       ├── settings.js          # 设置面板
│       ├── agent-console.js     # Agent实时控制台（v2类型化事件）
│       └── citation-chain.js    # 引用链可视化
├── backend/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                  # FastAPI入口，中间件，lifespan
│   ├── config.py                # 配置（Pydantic, .env, 40+变量）
│   ├── api/
│   │   ├── ingest.py            # 摄入API（file/text/url/site + 后台任务）
│   │   ├── search.py            # 搜索API（hybrid/semantic/bm25 + 多样化）
│   │   ├── chat.py              # RAG流式对话API（SSE + 迭代检索）
│   │   ├── kb.py                # 知识库管理API（CRUD + 批量 + 导出）
│   │   ├── agent_stream.py      # Agent执行SSE流（v1/v2 + 转向 + Session）
│   │   ├── settings.py          # 运行时设置读写
│   │   ├── metrics.py           # Prometheus指标
│   │   └── mcp_logs.py          # MCP调用日志查询
│   ├── agent_core/              # Provider无关Agent运行时
│   │   ├── loop.py              # run_loop主循环
│   │   ├── events.py            # AgentEvent + EventStream广播总线
│   │   ├── compaction.py        # 消息历史压缩
│   │   ├── cache.py             # 提示缓存适配
│   │   ├── steering.py          # 转向队列
│   │   ├── tool.py              # ToolExecutor
│   │   ├── truncate.py          # 工具输出截断
│   │   ├── tokens.py            # 令牌计数
│   │   ├── hooks.py             # Hooks接口
│   │   ├── messages.py          # 消息类型
│   │   └── state.py             # AgentState
│   ├── agents/
│   │   ├── orchestrator.py      # 摄入流水线调度
│   │   ├── doc_agent.py         # 文档解析
│   │   ├── media_agent.py       # 音视频转录
│   │   ├── web_agent.py         # 网页抓取
│   │   ├── web_judge.py         # LLM页面质量评分
│   │   ├── url_analyst.py       # URL策略分析
│   │   ├── smart_fetcher.py     # ⚠️ 兼容 shim — 转发到 agents/web/loop.run_agent
│   │   ├── vision_agent.py      # 图片OCR + 视频帧描述
│   │   ├── jshook_client.py     # JsHookMCP客户端
│   │   ├── llm.py               # LLM工厂
│   │   └── web/                 # Web Agent子模块
│   │       ├── handler.py       # 请求处理器
│   │       ├── loop.py          # Agent主循环
│   │       ├── pool.py          # 连接池管理
│   │       ├── session.py       # 会话管理
│   │       ├── prompts.py       # 提示词模板
│   │       ├── seeds/           # 种子URL模板
│   │       └── tools/           # 工具集（browser/http/jshook/parse/memory）
│   ├── pipeline/
│   │   ├── chunker.py           # 分块
│   │   ├── embedder.py          # 双向量嵌入（缓存+RPM限制）
│   │   ├── extractor.py         # 元数据提取
│   │   ├── deduper.py           # SHA256去重
│   │   ├── reranker.py          # Cross-encoder重排序
│   │   ├── tagger.py            # LLM自动标签
│   │   └── query_expander.py    # 查询扩展
│   ├── storage/
│   │   ├── vector_store.py      # Qdrant（remote/local/memory）
│   │   ├── metadata_db.py       # SQLite（aiosqlite, 9表）
│   │   └── file_store.py        # 原始文件
│   ├── mcp_server/
│   │   ├── server.py            # FastMCP + SSE工厂
│   │   ├── tools.py             # 8个MCP工具 + 调用日志
│   │   └── run_stdio.py         # stdio入口
│   └── utils/
│       └── agent_bus.py         # Agent消息总线
└── tg_bot/                      # Telegram Bot
```

## API 端点

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/ingest/file` | 上传文件 |
| `POST` | `/ingest/text` | 摄入文本 |
| `POST` | `/ingest/url` | 智能抓取 URL（cookies/intent） |
| `GET` | `/ingest/tasks` | 任务列表 |
| `GET` | `/ingest/tasks/{id}` | 任务状态 |
| `GET` | `/search` | 搜索（q, top_k, mode, filter） |
| `POST` | `/chat` | RAG 流式对话（SSE） |
| `GET` | `/kb/sources` | 知识库来源 |
| `GET` | `/kb/sources/{id}` | 来源详情 + chunks |
| `DELETE` | `/kb/sources/{id}` | 删除来源及数据 |
| `PATCH` | `/kb/sources/{id}/tags` | 更新标签 |
| `GET` | `/kb/stats` | 知识库统计 |
| `POST` | `/kb/export` | 导出（JSON/CSV/ZIP） |
| `GET` | `/agent/events` | Agent 事件流 SSE（v1） |
| `GET` | `/agent/v2/events` | Agent 事件流 SSE（v2 类型化） |
| `POST` | `/agent/{task_id}/steer` | 向运行中 Agent 注入指令 |
| `GET` | `/agent/sessions` | Web Agent Session 列表 |
| `GET` | `/agent/sessions/{id}` | Session 详情 + 消息历史 |
| `GET` | `/settings` | 读取当前配置 |
| `PATCH` | `/settings` | 更新运行时配置 |
| `GET` | `/metrics` | Prometheus 指标 |
| `GET/POST` | `/mcp` | MCP SSE 端点 |
| `GET` | `/mcp/logs` | MCP 调用日志 |

详见 [docs/API.md](docs/API.md) | 部署指南 [docs/DEPLOY.md](docs/DEPLOY.md)

## 测试

测试数据由 AI 搜索互联网后自动整理生成，内容可能存在虚构或偏差。评分基于检索结果与期望关键词的匹配度计算，**仅反映系统检索召回能力，不构成对任何产品或事实的断言**。

### 实战案例 1：DeepSeek 知识库

**DeepSeek 知识库** — 12 篇由 AI 搜索网络信息后生成的 DeepSeek 产品线文档，涵盖公司背景、V4/V3/R1/Coder/VL2/OCR/Prover 各模型、API 文档、Agent 集成、产品时间线共 11 个类别。知识库共 19 个来源、约 150 个 chunk。

**测试方法**：24 道事实性问答题，覆盖所有类别。每道题事先标注了预期关键词，用 token 匹配计算覆盖率：

```python
# 评分逻辑: 检索结果中的关键词命中率
hit = len(found_keywords) / len(expected_keywords)
if hit >= 0.8:  ver = "优秀"
elif hit >= 0.5: ver = "部分覆盖"
elif hit > 0:   ver = "少量覆盖"
else:           ver = "未覆盖"
```

**实测结果**：经过两轮迭代优化后，系统在 24 道跨类别事实问答题中，关键词覆盖率显著提升。

**典型测试案例**：

| 问题 | 期望关键词 | 实际检索结果 | 评分 |
|------|-----------|-------------|------|
| DeepSeek-V3的总参数量和激活参数量分别是多少？ | `671B`, `37B`, `MoE` | top1 chunk 精确命中 671B + 37B + Mixture-of-Experts | 优秀 |
| DeepSeek-V4-Pro 有多少参数？上下文长度？ | `862B`, `1M` / `100万` | top1 chunk 命中 862B，top3 命中 1M | 优秀 |
| DeepSeek-R1 是什么时候发布的？采用什么许可证？ | `2025/01/20`, `MIT` | top1 命中完整日期 + MIT 许可证 | 优秀 |
| DeepSeek-Coder 支持多少种语言？训练数据量？ | `87`, `2T` | top1 命中 87 languages，top2 命中 2T tokens | 优秀 |
| DeepSeek API 的 OpenAI 兼容 Base URL？ | `api.deepseek.com` | top4 chunk 命中完整 URL | 部分覆盖 |
| DeepSeek 产品线包含哪些模型系列？ | 7 个系列名 | 检索覆盖 V4/V3/R1/Coder/VL2/OCR/Prover 全部 | 优秀 |

### 实战案例 2：OpenAI 知识库

9 篇 AI 搜索后生成的 OpenAI 产品文档（公司背景 / GPT / 推理模型 / GPT-5 / 图像视频 / 语音 / 嵌入审核 / API 服务 / 定价限制），构建了 30 道事实问答题，覆盖 10 个类别。

| 问题 | 期望关键词 | 实际检索结果 | 评分 |
|------|-----------|-------------|------|
| GPT-4o的上下文窗口是多少？定价是多少？ | `128K`, `2.50`, `10.00` | top1 chunk 命中 128K tokens + $2.50/$10.00 定价 | 优秀 |
| o系列推理模型包含哪些型号？ | `o1`, `o3`, `o4-mini`, `o3-pro` 等 | 跨 chunk 检索覆盖 o1/o3/o4-mini/o1-pro/o3-mini/o3-pro 全部 | 优秀 |
| Whisper的定价是多少？支持哪些音频格式？ | `0.006`, `flac`, `mp3`, `wav`, `ogg` | top1 命中 $0.006 + flac/mp3/wav/ogg 全部格式 | 优秀 |
| Rate Limit Tier 5 的 RPM 和 TPM？ | `30000`, `150000000` | top1 chunk 精确命中两个数值 | 优秀 |
| OpenAI的语音产品线包含哪些模型？ | `Whisper`, `TTS`, `gpt-4o-mini-tts` | 跨 3 个 chunk 覆盖全部产品名称 | 部分覆盖 |
| DALL-E 3 支持哪些尺寸？HD 1024x1024 价格？ | `1024`, `0.08` | top1 chunk 命中 1024×1024 尺寸 + $0.08/张 | 优秀 |

DeepSeek + OpenAI 两套测试共 **54 道题**，验证了系统在不同领域（AI 模型文档、定价表、API 规格）的检索表现。两轮迭代改进：

- **分块调优**：从 1000/200 收紧到 800/160，匹配精度提升明显
- **查询扩展**：宽泛问题自动拆分成多路子查询，覆盖范围大幅提升
- **Cross-encoder 重排**：长尾问题找到被埋在后的答案
- **来源去重**：限制同来源最多 3 条，跨文档问题避免单一文档霸榜
- **迭代检索**：LLM 判断上下文充分性，不足时自动补充搜索

### 摄入稳定性

日常运行 150+ 个摄入任务，链路稳定。失败任务均为 API 侧问题——SiliconFlow 频率限制和 Embedding batch size 超限，无系统性 Bug，失败任务重跑即可。

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `QDRANT_URL` | Qdrant 服务地址 | `http://localhost:6333` |
| `QDRANT_MODE` | local / remote / memory | `local` |
| `QDRANT_COLLECTION` | 集合名称 | `omnikb` |
| `LLM_PROVIDER` | custom / openai / anthropic / ollama | `custom` |
| `LLM_MODEL` | 模型名称 | `deepseek-chat` |
| `LLM_BASE_URL` | API 地址 | — |
| `LLM_API_KEY` | API 密钥 | — |
| `LLM_MAX_TOKENS` | 最大输出 Token | `4096` |
| `EMBEDDING_PROVIDER` | siliconflow / openai | `siliconflow` |
| `EMBEDDING_MODEL` | 嵌入模型 | `BAAI/bge-m3` |
| `EMBEDDING_BASE_URL` | 嵌入 API 地址 | — |
| `EMBEDDING_API_KEY` | 嵌入 API 密钥 | — |
| `EMBEDDING_DIMENSIONS` | 向量维度 | `1024` |
| `EMBEDDING_RPM` | 速率限制（请求/分钟，0 = 关闭） | `10`（SiliconFlow 免费档；付费档可调高） |
| `VISION_ENABLED` | 视觉能力开关 | `false` |
| `VISION_PROVIDER` | 视觉 LLM 提供商 | — |
| `VISION_MODEL` | 视觉模型名称 | — |
| `RERANKER_ENABLED` | 重排序开关 | `false` |
| `RERANKER_MODEL` | 重排序模型 | `BAAI/bge-reranker-v2-m3` |
| `AUTOTAG_ENABLED` | 自动标签 | `false` |
| `WEB_JUDGE_ENABLED` | 页面评分过滤 | `false` |
| `WEB_JUDGE_MIN_SCORE` | 最低入库分数 | `5` |
| `MCP_API_KEY` | MCP 鉴权密钥 | 必填 |
| `HTTP_PROXY` | HTTP 代理地址 | — |
| `JSHOOK_POOL_SIZE` | jshook 连接池 | `0` |
| `PLAYWRIGHT_POOL_SIZE` | playwright 连接池 | `0` |
| `HF_ENDPOINT` | HuggingFace 镜像 | — |
| `FASTEMBED_CACHE_PATH` | fastembed (BM25/sparse) 模型缓存目录；空 = `~/.cache/fastembed` | — |
| `WEB_AGENT_MAX_INPUT_TOKENS` | 单次 web agent 运行 input token 上限（0 = 关闭） | `200000` |
| `WEB_AGENT_MAX_OUTPUT_TOKENS` | 单次 web agent 运行 output token 上限 | `50000` |
| `WEB_AGENT_MAX_SECONDS` | 单次 web agent 墙钟时间上限（秒） | `300` |
| `WEB_AGENT_MAX_TOOL_CALLS` | 单次 web agent 工具调用次数上限 | `30` |
| `CHAT_AGENT_ENABLED` | 启用 agentic chat（KB 工具 + URL 取数） | `true` |
| `CHAT_AGENT_MAX_TURNS` | agentic chat 最大轮次 | `6` |
| `CHAT_AGENT_MAX_TOOL_CALLS` | agentic chat 工具调用次数上限 | `10` |

## 致谢

本项目的网络采集能力离不开以下优秀开源项目：

- [**jshookmcp**](https://github.com/vmoranv/jshookmcp) — 下一代 JS 逆向 MCP 工具，通过 CDP 拦截和动态脚本注入实现签名算法破解和 API 捕获，是我们的 Web Agent Layer 3 深度采集核心依赖
- [**claude-code-skill-scrapling**](https://github.com/Cedriccmh/claude-code-skill-scrapling) — 基于 scrapling 的 Claude Code 技能，提供了静态/动态网页抓取的最佳实践，Web Agent Layer 1 & 2 的参考实现
- [**agent-browser**](https://github.com/vercel-labs/agent-browser) — Vercel Labs 出品的浏览器自动化 CLI，提供了交互式页面采集与登录态维持的设计参考；当前 Web Agent Layer 3-A 已切换为常驻的 patchright PlaywrightPool 实现（API/MCP 仍以 `mode=agent_browser` 名义暴露）
- [**Qdrant**](https://qdrant.tech/) — 高性能向量数据库，原生支持 Dense + Sparse 混合搜索和 RRF 融合
- [**FastEmbed**](https://github.com/qdrant/fastembed) — 轻量级嵌入库，提供 BM25 稀疏向量生成
- [**FastMCP**](https://github.com/jlowin/fastmcp) — MCP Server 框架，简化工具定义和传输协议

## License

MIT
