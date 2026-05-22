# DeepSeek-V3 系列

## 版本历史
| 版本 | 发布日期 | 参数 |
|------|----------|------|
| DeepSeek-V3 (原始版) | 2024/12/26 | 671B total / 37B activated |
| DeepSeek-V3-0324 | 2025/03/24 | 671B total / 37B activated |
| DeepSeek-V3.1 | 2025/08/21 | 685B |
| DeepSeek-V3.2-Exp | 2025/09/22 | 685B |
| DeepSeek-V3.2 | 2025/12/01 | 685B |

## 架构特点
- **Mixture-of-Experts (MoE)**: 671B 总参数，每 token 仅激活 37B
- **Multi-head Latent Attention (MLA)**: 相比 DeepSeek 67B 减少 93.3% KV 缓存，推理吞吐量提升 5.76 倍
- **Auxiliary-loss-free load balancing**: 首创无辅助损失的负载均衡策略
- **Multi-Token Prediction (MTP)**: 多头预测训练目标，支持推测解码
- **FP8 混合精度训练**: 首次在大规模模型上验证 FP8 训练

## 训练数据
- 训练数据: 14.8 万亿 tokens
- 训练成本: 仅 2.788M H800 GPU 小时
- 上下文窗口: 128K

## HuggingFace
模型 ID: deepseek-ai/DeepSeek-V3.2 (685B, 1190万下载)

## DeepSeek-V3 基准测试 (vs GPT-4o & Claude 3.5 Sonnet)
| 基准 | DeepSeek-V3 | GPT-4o | Claude 3.5 Sonnet |
|------|-------------|--------|-------------------|
| MMLU (EM) | 88.5 | 87.2 | 88.3 |
| MMLU-Pro (EM) | 75.9 | 72.6 | 78.0 |
| DROP (3-shot F1) | 91.6 | 83.7 | 88.3 |
| GPQA-Diamond | 59.1 | 49.9 | 65.0 |
| SimpleQA | 24.9 | 38.2 | 28.4 |
| LongBench v2 | 48.7 | 48.1 | 41.0 |
| HumanEval-Mul | 82.6 | 80.5 | 81.7 |
| LiveCodeBench (COT) | 40.5 | 33.4 | 36.3 |
| Codeforces Percentile | 51.6 | 23.6 | 20.3 |
| SWE Verified | 42.0 | 38.8 | 50.8 |
| AIME 2024 | 39.2 | 9.3 | 16.0 |
| MATH-500 | 90.2 | 74.6 | 78.3 |
| Arena-Hard | 85.5 | 80.4 | 85.2 |
| AlpacaEval 2.0 (LC) | 70.0 | 51.1 | 52.0 |

DeepSeek-V3 在数学推理 (AIME 2024, MATH-500)、代码竞技 (Codeforces) 和长文本理解 (LongBench v2) 上显著领先 GPT-4o 和 Claude 3.5 Sonnet。
