# OpenAI 定价和速率限制

## Complete Pricing (Per 1M tokens)
| 模型 | 输入 | 缓存输入 | 输出 |
|-----|------|---------|------|
| GPT-4o | $2.50 | $1.25 | $10.00 |
| GPT-4o-mini | $0.15 | $0.075 | $0.60 |
| GPT-4.1 | $2.00 | $0.50 | $8.00 |
| GPT-4.1-mini | $0.40 | $0.10 | $1.60 |
| GPT-4.1-nano | $0.10 | $0.025 | $0.40 |
| o1 | $15.00 | $7.50 | $60.00 |
| o1-pro | $150.00 | - | $600.00 |
| o1-mini | $1.10 | $0.55 | $4.40 |
| o3 | $2.00 | $0.50 | $8.00 |
| o3-pro | $20.00 | - | $80.00 |
| o3-mini | $1.10 | $0.55 | $4.40 |
| o4-mini | $1.10 | $0.275 | $4.40 |
| Whisper | $0.006/分钟 | - | - |
| TTS/TTS-HD | $15/1M字符 | - | - |
| Embeddings 3-large | $0.13 | - | - |
| Embeddings 3-small | $0.02 | - | - |
| Moderation | 免费 | - | - |

## Rate Limits (速率限制)
| Tier | RPM | TPM | Batch Queue Limit |
|-----|-----|-----|-------------------|
| Free | 不支持 | 不支持 | - |
| Tier 1 | 1,000 | 100,000 | 1,000,000 |
| Tier 2 | 2,000 | 2,000,000 | 2,000,000 |
| Tier 3 | 5,000 | 4,000,000 | 40,000,000 |
| Tier 4 | 10,000 | 10,000,000 | 1,000,000,000 |
| Tier 5 | 30,000 | 150,000,000 | 15,000,000,000 |

## Prompt Caching
- 自动生效，对所有支持模型启用
- 延迟降低最高 80%
- 成本降低最高 90%
- 适用模型: GPT-4o 及以上所有新模型
- 无额外费用
- 通过 usage.prompt_tokens_details.cached_tokens 查看缓存命中

## Authentication
- Authorization: Bearer $OPENAI_API_KEY
- OpenAI-Organization: $ORG_ID (多组织)
- OpenAI-Project: $PROJECT_ID (多项目)
- 切勿在客户端代码中暴露 API key
