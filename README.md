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

## 测试

测试数据由 AI 搜索互联网后自动整理生成，内容可能存在虚构或偏差。评分基于检索结果与期望关键词的匹配度计算，**仅反映系统检索召回能力，不构成对任何产品或事实的断言**。

### 实战案例 1：DeepSeek 知识库

我们构建了两套知识库来验证系统在真实场景中的表现：

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

同样地，我们用 9 篇 AI 搜索后生成的 OpenAI 产品文档（公司背景 / GPT / 推理模型 / GPT-5 / 图像视频 / 语音 / 嵌入审核 / API 服务 / 定价限制），构建了 30 道事实问答题，覆盖 10 个类别。

| 问题 | 期望关键词 | 实际检索结果 | 评分 |
|------|-----------|-------------|------|
| GPT-4o的上下文窗口是多少？定价是多少？ | `128K`, `2.50`, `10.00` | top1 chunk 命中 128K tokens + $2.50/$10.00 定价 | 优秀 |
| o系列推理模型包含哪些型号？ | `o1`, `o3`, `o4-mini`, `o3-pro` 等 | 跨 chunk 检索覆盖 o1/o3/o4-mini/o1-pro/o3-mini/o3-pro 全部 | 优秀 |
| Whisper的定价是多少？支持哪些音频格式？ | `0.006`, `flac`, `mp3`, `wav`, `ogg` | top1 命中 $0.006 + flac/mp3/wav/ogg 全部格式 | 优秀 |
| Rate Limit Tier 5 的 RPM 和 TPM？ | `30000`, `150000000` | top1 chunk 精确命中两个数值 | 优秀 |
| OpenAI的语音产品线包含哪些模型？ | `Whisper`, `TTS`, `gpt-4o-mini-tts` | 跨 3 个 chunk 覆盖全部产品名称 | 部分覆盖 |
| DALL-E 3 支持哪些尺寸？HD 1024x1024 价格？ | `1024`, `0.08` | top1 chunk 命中 1024×1024 尺寸 + $0.08/张 | 优秀 |

OpenAI 材料的特点是**数字密集型**——大量定价、RPM/TPM、维度参数。这类数据在文本中天然高密度分布，Hybrid 搜索 + 重排序的组合表现很好，数字型关键词的命中率非常高。

DeepSeek + OpenAI 两套测试共 **54 道题**，验证了系统在不同领域（AI 模型文档、定价表、API 规格）的检索表现。两轮迭代做了什么：

- **分块调优**：从 1000/200 收紧到 600/120，匹配精度提升明显
- **查询扩展**：宽泛问题自动拆分成多路子查询，像「综合对比」类的问题覆盖面大了很多
- **Cross-encoder 重排**：开了之后长尾问题找到了原来被埋在第 5-10 位的答案
- **来源去重**：限制同来源最多 2 条，像「产品家族」这种跨文档的问题原来被单一文档霸榜，现在分散开了

### 摄入稳定性

日常跑下来 150+ 个摄入任务，链路稳定。12 条失败任务全是 API 侧问题——SiliconFlow 的频率限制（RPM 超了）和 Embedding batch size 超 64 的上限，没有系统性 Bug，失败任务重跑即可。

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

## 致谢

本项目的网络采集能力离不开以下优秀开源项目：

- [**jshookmcp**](https://github.com/vmoranv/jshookmcp) — 下一代 JS 逆向 MCP 工具，通过 CDP 拦截和动态脚本注入实现签名算法破解和 API 捕获，是我们 Web Agent Layer 3 深度采集的核心依赖
- [**claude-code-skill-scrapling**](https://github.com/Cedriccmh/claude-code-skill-scrapling) — 基于 scrapling 的 Claude Code 技能，提供了静态/动态网页抓取的最佳实践，Web Agent Layer 1 & 2 的参考实现
- [**agent-browser**](https://github.com/vercel-labs/agent-browser) — Vercel Labs 出品的浏览器自动化 CLI，将 Playwright 封装为 AI 可调用的工具，为交互式页面采集和登录态维持提供了基础能力

## License

MIT
