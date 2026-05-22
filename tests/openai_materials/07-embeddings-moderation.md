# OpenAI Embeddings 和 Moderation

## Embeddings (向量嵌入)
- text-embedding-3-large: 默认维度3072(可缩减), 定价$0.13/1M tokens, 最大输入8192 tokens
- text-embedding-3-small: 默认维度1536(可缩减), 定价$0.02/1M tokens, 最大输入8192 tokens
- text-embedding-ada-002: 维度1536, 定价$0.10/1M tokens, 最大输入8192 tokens
- text-embedding-3 支持 dimensions 参数动态缩减维度
- 知识截止: 2021年9月
- 单请求最大 300,000 tokens (所有输入总和)
- 支持 Batch API

## Moderation (内容审核)
- omni-moderation-latest: 推荐, 支持文本+图片, 13个类别
- text-moderation-latest: 旧版, 仅文本, 7个类别
- 定价: 免费 (Free tier)
- 审核类别: sexual, harassment, hate, illicit, self-harm, violence 及其子类别
- omni-moderation 新增: illicit, illicit/violent, self-harm 支持图片审核
