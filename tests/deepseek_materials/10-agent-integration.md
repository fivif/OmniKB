# DeepSeek Agent 集成指南

DeepSeek 可作为多种 AI Agent 平台的推理后端。

## Claude Code 集成
通过 Anthropic 兼容 API 配置:
```
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_AUTH_TOKEN=<your-deepseek-api-key>
ANTHROPIC_MODEL=deepseek-v4-pro
CLAUDE_CODE_SUBAGENT_MODEL=deepseek-v4-flash
CLAUDE_CODE_EFFORT_LEVEL=max
```

## 支持的集成平台
- Claude Code (Anthropic 兼容 API)
- GitHub Copilot
- Kilo Code / WorkBuddy / CodeBuddy
- OpenCode / Oh My Pi / OpenClaw
- 以及其他 15+ 平台

## 官方链接
- API 文档: api-docs.deepseek.com
- API 定价: api-docs.deepseek.com/quick_start/pricing
- 速率限制: api-docs.deepseek.com/quick_start/rate_limit
- 错误码: api-docs.deepseek.com/quick_start/error_codes
- 思考模式: api-docs.deepseek.com/guides/thinking_mode
- 工具调用: api-docs.deepseek.com/guides/tool_calls
- GitHub 组织: github.com/deepseek-ai
- HuggingFace 组织: huggingface.co/deepseek-ai
- 聊天平台: chat.deepseek.com
