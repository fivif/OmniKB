# OpenAI 图像和视频模型

## DALL-E 3
- 模型名: dall-e-3
- 参数: quality(standard|hd), style(vivid|natural), n=1(仅支持1张)
- 1024x1024: Standard $0.04, HD $0.08
- 1024x1536: Standard $0.08, HD $0.12
- 1536x1024: Standard $0.08, HD $0.12

## DALL-E 2
- 模型名: dall-e-2
- 支持尺寸: 256x256, 512x512, 1024x1024
- 最多支持 n=10 张
- 1024x1024 定价: $0.020/张

## Sora (视频生成)
- Sora 2: 720x1280/1280x720, $0.10/秒
- Sora 2 Pro: 更高分辨率
  - 720x1280/1280x720: $0.30/秒
  - 1024x1792/1792x1024: $0.50/秒
  - 1080x1920/1920x1080: $0.70/秒
- 输入: 文字描述或图片
- 输出: 视频 + 同步音频
- 支持异步生成, 轮询和 webhook

## GPT Image 模型
- gpt-image-1-mini
- 1024x1024: Low $0.005, Medium $0.011, High $0.036
