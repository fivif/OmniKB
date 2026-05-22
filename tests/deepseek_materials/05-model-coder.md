# DeepSeek-Coder 代码模型

## 基本信息
DeepSeek-Coder 是专为代码生成和理解设计的大语言模型。

## 模型规模
1B / 5.7B / 6.7B / 33B 四个尺寸

## 架构
- 纯 Transformer 架构
- 16K token 上下文窗口
- 训练数据: 2T tokens
- 数据组成: 87% 代码 + 13% 自然语言 (中英文)

## 三阶段训练流程
1. 初始预训练: 1.8T tokens, 4K 上下文
2. 扩展预训练: 200B tokens, 16K 上下文
3. 指令微调: 2B tokens

## 支持语言
87+ 编程语言，包括 Python, C++, Java, Rust, Go, TypeScript, SQL, Verilog 等。

## 核心能力
- **代码补全**: 自然语言描述 → 完整函数实现
- **Fill-in-the-Middle**: 使用特殊 tokens `<｜fim▁begin｜>`, `<｜fim▁end｜>` 实现中间填充
- **仓库级理解**: 跨文件依赖关系分析
- **聊天式编码辅助**: 交互式代码生成与调试

## 许可信息
- 代码: MIT 许可证
- 模型: 自定义模型许可证
- 支持商业使用
