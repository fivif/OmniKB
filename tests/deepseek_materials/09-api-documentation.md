# DeepSeek API 文档

## 基础信息
- API 兼容性: OpenAI 和 Anthropic 格式兼容
- OpenAI Base URL: https://api.deepseek.com
- Anthropic Base URL: https://api.deepseek.com/anthropic
- 鉴权方式: Authorization: Bearer <API_KEY>
- API Key 申请: platform.deepseek.com/api_keys
- 环境变量: DEEPSEEK_API_KEY

## 当前可用模型
| 模型名称 | 说明 | 状态 |
|----------|------|------|
| deepseek-v4-flash | 当前主力模型 (快速) | current |
| deepseek-v4-pro | 当前主力模型 (高品质) | current |
| deepseek-chat | v4-flash 非思考模式 | 2026/07/24 废弃 |
| deepseek-reasoner | v4-flash 思考模式 | 2026/07/24 废弃 |

## 模型规格
| 特性 | deepseek-v4-flash | deepseek-v4-pro |
|------|-------------------|-----------------|
| 上下文长度 | 1M | 1M |
| 最大输出 | 384K | 384K |
| 思考模式 | 支持 (默认非思考) | 支持 |
| JSON 输出 | 支持 | 支持 |
| 工具调用 | 支持 | 支持 |

## API 参数
- model: 模型名称
- messages: 标准 role/content 数组 (system, user, assistant)
- stream: boolean (默认 false)
- reasoning_effort: 如 "high"
- thinking: {"type": "enabled"} (Python SDK 通过 extra_body 传递)
- temperature: 0.0-2.0

## 错误码
| 状态码 | 含义 |
|--------|------|
| 400 | Invalid Format — 请求体格式错误 |
| 401 | Authentication Fails — API Key 错误 |
| 402 | Insufficient Balance — 余额不足 |
| 422 | Invalid Parameters — 参数无效 |
| 429 | Rate Limit Reached — 请求过快 |
| 500 | Server Error — 服务器内部错误 |
| 503 | Server Overloaded — 服务器过载 |

## 速率限制
- 动态限制: 根据服务器实时负载和账户近期用量动态调整并发
- 无层级: 不支持提升个人限制
- HTTP 429: 超出并发时立即返回
- 超时: 10 分钟后关闭未开始推理的连接

## 工具调用 (Function Calling)
- 支持非思考模式和思考模式 (V3.2+)
- strict 模式 (Beta): 使用 base_url="https://api.deepseek.com/beta"
- 约束: object 属性必须全部 required, additionalProperties 必须 false

## 上下文缓存
- 支持缓存大幅降低输入成本
- Cache hit 价格仅为 miss 的 1/50 (v4-flash) 到 1/120 (v4-pro)

## Token 换算
- 1 英文字符 ≈ 0.3 token
- 1 中文字符 ≈ 0.6 token
- 离线 tokenizer 下载: cdn.deepseek.com/api-docs/deepseek_v3_tokenizer.zip

## 支付方式
- PayPal / 银行卡 / Alipay / WeChat Pay
- 充值余额不会过期
- 未使用余额可退款
