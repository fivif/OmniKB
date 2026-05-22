# OpenAI Assistants API 和文件搜索

## Assistants API
- 创建自定义AI助手，支持 function calling, file search, code interpreter
- Threads: 管理对话会话，支持多轮交互
- Runs: 执行 Assistant 的运行
- Vector Stores: 存储文件嵌入，支持语义+关键词搜索
- File Search: 自动解析、分块、嵌入文档

## 创建 Assistant 示例
```python
assistant = client.beta.assistants.create(
    model="gpt-4o",
    tools=[{"type": "file_search"}],
    tool_resources={"file_search": {"vector_store_ids": ["vs_1"]}}
)
```

## Realtime API
- 端点: wss://api.openai.com/v1/realtime (WebSocket)
- 还支持 WebRTC, SIP
- gpt-realtime-1.5: 文本 $4/$16, 音频 $32/$64 per 1M tokens
- gpt-realtime-mini: 文本 $0.60/$2.40 per 1M tokens
- gpt-4o-realtime-preview: 多个 snapshot 版本
- gpt-audio-1.5: 文本 $2.50/$10, 音频 $32/$64, 上下文128K
- 上下文窗口: 32,000 tokens
- 声音: 13种内置 + 自定义声音

## Batch API
- 折扣: 50% 成本降低
- 完成时间: 24小时内
- 单批次上限: 50,000 requests
- 文件大小上限: 200 MB
- 创建速率: 2,000 batches/hour
- 不消耗标准速率限制
- 支持端点: /v1/responses, /v1/chat/completions, /v1/embeddings, /v1/moderations, /v1/images/generations

## Function Calling & Structured Outputs
- Structured Outputs: 强制输出符合 JSON Schema
- JSON Mode: 旧方案, 不保证符合 Schema
- 推荐使用 Structured Outputs
- 支持 response_format: { type: "json_schema", json_schema: {...} }
- 支持 strict: true 参数
