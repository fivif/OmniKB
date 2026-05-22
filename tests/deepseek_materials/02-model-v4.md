# DeepSeek-V4 系列 (2026年4月发布)

DeepSeek-V4 是最新旗舰模型系列，于 2026年4月24日作为 Preview 发布。

## 模型列表

| 模型 | 参数总量 | 激活参数 | 类型 | HuggingFace 下载量 |
|---|---|---|---|---|
| DeepSeek-V4-Pro | 862B | — | 聊天/推理 | 106万 |
| DeepSeek-V4-Flash | 158B | — | 聊天/推理 (快速) | 84.9万 |
| DeepSeek-V4-Pro-Base | 1.6T | — | 基座模型 | 9,740 |
| DeepSeek-V4-Flash-Base | 292B | — | 基座模型 | 9,500 |

## API 模型名称
- `deepseek-v4-flash` — 当前主力快速模型
- `deepseek-v4-pro` — 当前主力高品质模型

## 规格参数
- 上下文长度: 1M (100万 tokens)
- 最大输出: 384K tokens
- JSON 输出: 支持
- 工具调用: 支持
- FIM 补全: 支持 (非思考模式)

## 定价 (每1M tokens)

### deepseek-v4-flash
| 场景 | 价格 |
|------|------|
| 输入 (cache hit) | $0.0028 |
| 输入 (cache miss) | $0.14 |
| 输出 | $0.28 |

### deepseek-v4-pro (75% 折扣至 2026/05/31 15:59 UTC)
| 场景 | 折扣价 | 原价 |
|------|--------|------|
| 输入 (cache hit) | $0.003625 | $0.0145 |
| 输入 (cache miss) | $0.435 | $1.74 |
| 输出 | $0.87 | $3.48 |

缓存价格: 2026年4月26日起 cache hit 价格降至发布价的 1/10。
