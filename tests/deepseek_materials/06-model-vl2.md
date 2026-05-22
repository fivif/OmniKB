# DeepSeek-VL2 多模态视觉语言模型

## 架构
MoE (Mixture-of-Experts) 视觉语言模型

## 规模变体
- Tiny: 1.0B activated parameters
- Small: 2.8B activated parameters
- 完整版: 4.5B activated parameters (MoE 总参数更大)

## 上下文长度
4096 tokens

## 支持模态
- **输入**: 文本 + 图像 (支持单图、多图、交错对话)
- **输出**: 文本 + 结构化空间输出 (bounding box)

## 核心能力
- VQA (视觉问答)
- OCR (文字识别)
- 文档/表格/图表理解
- 视觉定位 (bounding box)

## 推理要求
Small 版本约需 40GB GPU 显存

## 许可证
- 代码: MIT 许可证
- 模型: DeepSeek Model License
- 支持商业使用
