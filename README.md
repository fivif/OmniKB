<h1 align="center">OmniKB</h1>
<h3 align="center">Wiki-first Universal AI Knowledge Base</h3>
<h4 align="center">上传即维基 · LLM 自动建图 · 1M 上下文直读 · 零嵌入开销</h4>

<p align="center">
  <a href="https://github.com/fivif/OmniKB"><img src="https://img.shields.io/badge/GitHub-OmniKB-blue?logo=github" alt="GitHub"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT"></a>
  <a href="#"><img src="https://img.shields.io/badge/python-3.13+-blue?logo=python" alt="Python 3.13+"></a>
  <a href="#"><img src="https://img.shields.io/badge/LLM-DeepSeek_V4-536DFE" alt="DeepSeek"></a>
  <a href="#"><img src="https://img.shields.io/badge/storage-SQLite-orange?logo=sqlite" alt="SQLite"></a>
  <a href="#"><img src="https://img.shields.io/badge/context-1M_tokens-black" alt="1M Context"></a>
</p>

<p align="center">
  <a href="#-什么是-omnikb">中文</a> ·
  <a href="#-what-is-omnikb">English</a>
</p>

---

## 🧠 什么是 OmniKB

**OmniKB** 不是 RAG 知识库。不分割文档、不做向量嵌入、不用语义搜索。LLM 直接阅读源文件，生成结构化的 Wiki 页面——维基本身就是知识库。

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

**零嵌入 · 零分块 · 零向量库** — Wiki 页面即知识库，1M 上下文直接容纳全部索引。

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

---

## 🚀 快速开始

```bash
git clone https://github.com/fivif/OmniKB
cd OmniKB
cp .env.example .env
# 编辑 .env，填入 LLM_PROVIDER / LLM_MODEL / LLM_BASE_URL
# API Key 可在 Web UI 设置面板填入，会自动回写 .env

pip install -r backend/requirements.txt
python backend/main.py
# 打开 http://localhost:6886
```

### 场景发布流程

```
1. 上传资料 → 知识库管理
2. Wiki 面板 → 同步生成 Wiki 页面
3. 问答管理 → 新建场景 → 关联知识源 → 配置 UI 模板
4. Agent 助手 → 「改成暗色卡片风格」 → 实时预览
5. 创建 API Key → 复制链接 → 嵌入官网
```

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

## 📊 项目数据

| 指标 | 数值 |
|---|---|
| Python 后端 | ~19,700 行 |
| 前端 JS/CSS/HTML | ~16,500 行 |
| Wiki 页面 (运行中) | 112 页 · 140 边 |
| 知识源 (运行中) | 32 个 |

---


## 📜 License

MIT

---

<p align="center"><em>Built with ♥</em></p>

---

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

---

## 🚀 Quick Start

```bash
git clone https://github.com/fivif/OmniKB
cd OmniKB
cp .env.example .env
pip install -r backend/requirements.txt
python backend/main.py
# Open http://localhost:6886
```

---

## 📜 License

MIT
