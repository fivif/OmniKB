<h1 align="center">OmniKB</h1>
<h3 align="center">按场景划分的知识库问答系统</h3>
<h4 align="center">多源聚合 · 场景专属 Wiki · 一键发布 · 零嵌入开销</h4>

<p align="center">
  <a href="https://github.com/fivif/OmniKB"><img src="https://img.shields.io/badge/GitHub-OmniKB-blue?logo=github" alt="GitHub"></a>
  <a href="https://github.com/fivif/OmniKB/blob/master/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.13+-blue?logo=python" alt="Python 3.13+"></a>
  <a href="#"><img src="https://img.shields.io/badge/LLM-DeepSeek_V4-536DFE" alt="DeepSeek"></a>
  <a href="#"><img src="https://img.shields.io/badge/storage-SQLite-orange?logo=sqlite" alt="SQLite"></a>
</p>

<p align="center">
  🌐 <a href="https://kb.xzay.de/s/mfd">在线体验</a> ·
  📊 <a href="https://kb.xzay.de/test">测试报告</a>
</p>

<p align="center">
  <img src="https://cdn3.ldstatic.com/original/4X/5/1/f/51f1739699ec0b35ee4e73fe7dec721f0645a370.jpeg" width="48%" alt="Wiki 界面"/>
  <img src="https://cdn3.ldstatic.com/original/4X/e/a/4/ea46abac257ac90d405bb09f0cf6b95f2993d2b5.png" width="48%" alt="测试报告"/>
</p>
<p align="center"><em>左：Wiki 知识图谱 ｜ 右：500 题大规模幻觉测试报告</em></p>

<p align="center">
  <a href="#-什么是-omnikb">中文</a> ·
  <a href="#-what-is-omnikb">English</a>
</p>

---

## 🧠 什么是 OmniKB

**OmniKB** 是一个按场景划分的知识库问答系统。核心思路：

1. **导入知识源** — 上传文档、粘贴文本、抓取 URL
2. **创建场景** — 每个场景绑定自己的知识源，配置专属 system prompt、UI 模板、API 密钥
3. **一键发布** — 自动生成公开问答页（`/s/your-slug`），嵌入官网或作为 Agent 的专属知识库
4. **Wiki 建图** — LLM 自动分析源内容，生成结构化 Wiki 页面，构建知识图谱

不同场景可以绑定不同知识源，快速切换。同时可以作为 AI Agent 的专属知识库——每个 Agent 绑定自己的场景 API，互不干扰。

参考 [Karpathy 的 LLM-Wiki 构想](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 和 [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) 的实现范式。

### 架构

```
                         ┌──────────────────────────┐
  文件/URL/文本 ──► 提取文本 ──► Wiki Generator (LLM)  │
                                  │  两步 Chain-of-Thought │
                                  │  Step 1: 分析 → JSON plan
                                  │  Step 2: 生成 → .md 页面
                                  └──────────┬───────────────┘
                                             │
                    ┌────────────────────────┼────────────────────────┐
                    ▼                        ▼                        ▼
              wiki_pages (DB)          index.md (目录)           [[wikilink]] 图谱
              entity/concept              全量页面索引              D3.js 可视化
              /source/query              渐进式披露               双向边
                    │                        │                        │
                    └────────────────────────┼────────────────────────┘
                                             │
                                    ┌────────▼────────┐
                                    │   LLM Chat (1M)  │
                                    │   先读 index.md   │
                                    │   按需 read_wiki  │
                                    │   SSE 流式输出    │
                                    └─────────────────┘
```

**零嵌入 · 零分块 · 零向量库** — Wiki 页面即知识库。

---

## ✨ 核心特性

| | |
|---|---|
| 🧠 **Wiki 自动生成** | 上传任意文档 → LLM 两步 Chain-of-Thought (分析→生成) → 实体/概念/来源/查询页面自动创建 |
| 🔗 **知识图谱** | `[[wikilink]]` 双向链接，D3.js 力导向可视化，节点按连接度缩放，缩放显隐标签 |
| 💬 **1M 上下文对话** | 全量 wiki_index 渐进式披露 → `read_wiki_page(id)` 按需深入 → SSE token-by-token 流式 |
| 🎯 **场景发布** | 选择知识源 → 配置模板/LLM/样式 → 生成独立问答页 → API Key 鉴权。一键嵌入官网/客服系统 |
| 🤖 **Agent 场景编辑** | 自然语言指令操控页面：改布局、换配色、加组件、重写 HTML/CSS/JS。支持重置还原 |
| 🏢 **快速企业部署** | 单文件启动 `python backend/main.py`，无需外部服务。Web UI 配置 LLM，重启不丢。Docker 可选 |
| 📡 **MCP 协议** | `read_wiki_page` + `fetch_url_preview` 工具暴露给 Claude/其他 AI Agent |
| 🎨 **AURA Design** | 极简 Slate 色系，明暗双主题，spring 弹性过渡，响应式布局 |
| 🔐 **Cookie 鉴权** | `ADMIN_PASSWORD` 环境变量一键开启，Cookie 30 天持久，Web UI 热更新无需重启 |

---

## 🚀 快速开始

```bash
git clone https://github.com/fivif/OmniKB
cd OmniKB
cp .env.example .env
# 编辑 .env，填入 LLM_PROVIDER / LLM_MODEL / LLM_BASE_URL
# API Key 可在 Web UI 设置面板填入，会自动回写 .env
# ADMIN_PASSWORD=xxx        ← 设置管理面板密码（留空则不启用鉴权）

pip install -r backend/requirements.txt
python backend/main.py
# 打开 http://localhost:6886
```

### 场景发布流程

```
1. 上传资料 → 知识库管理（支持多源批量导入）
2. Wiki 面板 → 批量生成 Wiki 页面
3. 场景管理 → 新建场景 → 绑定知识源 → 自定义公开 URL (/s/your-slug)
4. 配置 UI 模板 → system prompt → API 密钥
5. 发布 → 作为独立问答页 | 嵌入官网 | Agent 专属知识库
```

### 为什么用场景划分？

不同场景 = 不同知识域，互不干扰：

| 场景 | 知识源 | 用途 |
|---|---|---|
| 民法典助手 | 民法典各编条文 | 法律咨询 / 律师 Agent |
| 产品手册 | 产品文档、FAQ | 客服系统 / 用户自助 |
| 内部 Wiki | 公司制度、技术文档 | 员工助手 / 入职培训 |
| 竞品分析 | 竞品资料、评测 | 市场分析 Agent |

### 鉴权机制

设置 `ADMIN_PASSWORD` 后，**所有路径均需登录**，仅 `/login.html` 和 `/auth/*` 免鉴权（否则无法登录）。

| 路径 | 鉴权要求 |
|---|---|
| 全部路径 | 需登录 |
| `/login.html` `/auth/*` | 免鉴权（登录流程必须） |

- **开启鉴权**：在 `.env` 中设置 `ADMIN_PASSWORD=your_password`，或在 Web UI 设置面板热更新
- **关闭鉴权**：留空 `ADMIN_PASSWORD`，所有请求直接放行
- **登录态**：Cookie `omnikb_auth`，httponly，30 天有效期

---

## 🧱 技术栈

### Backend

| 层 | 技术 |
|---|---|
| 框架 | **FastAPI** — 异步 HTTP，SSE 流式 |
| LLM | **DeepSeek-V4** / **OpenAI-compatible** — 1M 上下文 |
| 数据库 | **SQLite** (aiosqlite · WAL 模式) |
| Agent 引擎 | **agent_core** — 自研 Provider 无关 Agent 循环 |
| MCP | **FastMCP** — SSE + stdio 双模式 |
| 配置 | **Pydantic Settings** — 运行时自检，密钥脱敏 |

### Frontend

| 层 | 技术 |
|---|---|
| 框架 | **Vanilla JS** — 零框架依赖 |
| 图谱 | **D3.js** — 力导向 Wiki 链接图 |
| 渲染 | **marked** + **highlight.js** — Markdown + 代码高亮 |
| 主题 | **AURA Design System** — CSS 自定义属性，明暗切换 |
| 流式 | **SSE** — token-by-token 实时渲染 |

---

## 📜 License

[MIT](https://github.com/fivif/OmniKB/blob/master/LICENSE)

---

<p align="center"><em>Built with ♥</em></p>

---

## 🙏 致谢

- [DeepSeek](https://deepseek.com) — 梁圣恩情还不完
- [LINUX DO](https://linux.do) — 技术社区与测试支持
- [Andrej Karpathy](https://github.com/karpathy) — LLM-Wiki 范式先驱
- [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) — 参考实现

---

# 🇬🇧 English

---

## 🧠 What is OmniKB

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

## ✨ Key Features

| | |
|---|---|
| 🧠 **Auto Wiki Generation** | Upload any document → LLM two-step CoT → auto-creates entity/concept/source pages |
| 🔗 **Knowledge Graph** | `[[wikilink]]` bidirectional links, D3.js force visualization, degree-scaled nodes |
| 💬 **1M Context Chat** | Full wiki_index progressive disclosure → `read_wiki_page(id)` on demand → true SSE streaming |
| 🎯 **Scenario Publishing** | Select sources → configure template/LLM → generate standalone Q&A page → API Key auth |
| 🤖 **Agent Page Editor** | Natural language commands → rewrite layout, inject HTML/CSS/JS, one-click reset |
| 🏢 **Zero-Dependency Deploy** | Single-file startup, no external services, Web UI config, Docker optional |
| 🔐 **Cookie Auth** | `ADMIN_PASSWORD` one-liner, 30-day cookie, hot-reload via Web UI without restart |

---

## 🚀 Quick Start

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

## 📜 License

[MIT](https://github.com/fivif/OmniKB/blob/master/LICENSE)
