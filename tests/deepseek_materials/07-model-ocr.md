# DeepSeek-OCR 系列

## 版本
| 版本 | 发布日期 | 参数 | HuggingFace 下载量 |
|------|----------|------|-------------------|
| DeepSeek-OCR | 2025/10/20 | 3B | 269万 |
| DeepSeek-OCR-2 | 2026/01/27 | 3B | 160万 |

## 核心能力
视觉文本压缩与 OCR，专为文档数字化设计

## 分辨率模式
| 模式 | 分辨率 | Vision Tokens |
|------|--------|---------------|
| Tiny | 512×512 | 64 |
| Small | 640×640 | 100 |
| Base | 1024×1024 | 256 |
| Large | 1280×1280 | 400 |
| Gundam | n×640×640 + 1×1024×1024 | 动态 |

## 提示词专化
- "Convert the document to markdown." → 带 grounding 的文档 OCR
- "OCR this image." → 通用 OCR
- "Free OCR." → 无布局提取
- "Parse the figure." → 图表解析
- "Describe this image in detail." → 图像描述

## 性能
- A100-40G 上约 2500 tokens/s
- 推理框架: vLLM (v0.8.5+) 和 HuggingFace Transformers (>=4.51.1)

## 许可证
MIT 许可证
