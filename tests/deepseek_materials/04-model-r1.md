# DeepSeek-R1 推理模型系列

## 基本信息
- **发布日期**: 2025年1月20日
- **基座模型**: DeepSeek-V3-Base
- **架构**: MoE, 671B total / 37B activated
- **上下文长度**: 128K
- **许可证**: MIT License (支持商用和蒸馏)
- **推荐温度**: 0.5-0.7 (推荐 0.6)
- **注意**: 避免添加 system prompt，指令放在 user prompt 中

## 训练管线
- **DeepSeek-R1-Zero**: 纯强化学习 (无 SFT)，自发产生 self-verification / reflection / long CoT 行为
- **DeepSeek-R1**: 冷启动数据 → 2 轮强化学习 → 2 轮监督微调

## 关键基准测试 (vs OpenAI o1-1217)
| 基准 | DeepSeek-R1 | OpenAI o1-1217 |
|------|-------------|----------------|
| MMLU | 90.8 | 91.8 |
| MMLU-Pro | 84.0 | — |
| AIME 2024 (Pass@1) | 79.8 | 79.2 |
| MATH-500 (Pass@1) | 97.3 | 96.4 |
| LiveCodeBench (Pass@1-COT) | 65.9 | 63.4 |
| Codeforces Percentile | 96.3 | 96.6 |
| SWE Verified | 49.2 | 50.8 (Claude 3.5) |
| GPQA-Diamond | 71.5 | 75.7 |
| DROP (3-shot F1) | 92.2 | — |

DeepSeek-R1 在 AIME 2024 和 MATH-500 上超越 OpenAI o1，数学推理能力达到业界领先水平。

## 蒸馏模型系列 (6个开源小模型)
| 模型 | 基座 | AIME 2024 | MATH-500 | Codeforces Rating |
|------|------|-----------|----------|-------------------|
| Distill-Qwen-1.5B | Qwen2.5-Math-1.5B | 28.9 | 83.9 | 954 |
| Distill-Qwen-7B | Qwen2.5-Math-7B | 55.5 | 92.8 | 1189 |
| Distill-Qwen-14B | Qwen2.5-14B | 69.7 | 93.9 | 1481 |
| Distill-Qwen-32B | Qwen2.5-32B | 72.6 | 94.3 | 1691 |
| Distill-Llama-8B | Llama-3.1-8B | 50.4 | 89.1 | 1205 |
| Distill-Llama-70B | Llama-3.3-70B-Instruct | 70.0 | 94.5 | 1633 |

R1-Distill-Qwen-32B 全面超越 OpenAI o1-mini。GitHub 仓库: 92K stars, 11.7K forks。
