# DeepSeek-Prover-V2 数学定理证明模型

## 定位
用于 Lean 4 形式定理证明的开源大语言模型

## 模型规模
- 7B 版本 (基于 Prover-V1.5-Base)
- 671B 版本 (基于 DeepSeek-V3-Base)

## 基准成绩
- MiniF2F-test: 88.9% pass ratio (SOTA 最佳)
- PutnamBench: 解决 658 题中的 49 题

## 方法
递归分解 + 形式化 + 强化学习，结合非正式推理与 Lean 4 形式证明

## 数据集
ProverBench: 325 题，涵盖 AIME 竞赛题和教材习题
