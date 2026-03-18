# linkora

> **本地知识网络** — 由本地优先架构驱动的 AI 原生研究终端。

[English](./README.md) | [中文](./README-CN.md)

---

## 目标

研究工作往往是分散的。论文散落在多个文件夹中，搜索分散在各种工具之间，上下文在会话之间丢失。**linkora** 通过构建**本地知识网络**来解决这个问题：

- 所有数据本地存储（隐私，离线可用）
- 分层访问（L1 元数据 → L4 全文）
- 向量嵌入支持语义搜索
- 与 AI 编码代理无缝协作

**目标用户**：AI 编码代理（Claude、Cursor）和喜欢 CLI 工作流的研究者。

## 核心功能

| | |
|---|---|
| **分层阅读** | L1 元数据 → L2 摘要 → L3 章节 → L4 全文——按需加载 |
| **融合检索** | FTS5 关键词 + Qwen3 语义 → RRF 排序融合 |
| **多源导入** | 本地 PDF、OpenAlex API、Zotero、EndNote XML/RIS |
| **工作区** | 多个研究项目，隔离搜索和 BibTeX 导出 |
| **MCP 服务器** | 完整工具集，支持 Claude Desktop、Cursor 等 |

## 安装

### 前置要求

- **uv**（必需）：[通过 astral.sh 安装](https://astral.sh/uv/install)
- **Python 3.12+**

### 快速安装

```bash
uv tool install "linkora[full]"
```

### 从源码安装

```bash
git clone https://github.com/your-repo/linkora.git
cd linkora
uv sync
```

## 快速开始

```bash
# 显示设计上下文（AI 代理使用）
linkora --context

# 交互式设置
linkora init

# 添加论文（将 PDF 放入工作区）
linkora add /path/to/paper.pdf

# 构建搜索索引
linkora index

# 搜索论文
linkora search "machine learning"
linkora search "turbulence" --mode vector

# MCP 服务器
linkora-mcp
```

## 配置

linkora **不是零配置工具** — 需要显式配置。详见 [config.md](./docs/config.md)。

### 快速配置

```yaml
# ~/.linkora/config.yml
default_workspace: research

workspace:
  research:
    description: "主要研究工作区"

sources:
  local:
    enabled: true
    papers_dir: papers

llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
```

完整配置请参阅 [`examples/config/full.yml`](examples/config/full.yml)。

### 工作区概念

工作区提供隔离的研究环境：

```
~/.linkora/config.yml           # 全局配置
~/.config/linkora/config.yml   # XDG 配置位置
<workspace>/linkora.yml        # 工作区本地覆盖
```

### 环境变量

| 变量 | 描述 |
|------|------|
| `linkora_ROOT` | 所有工作区的根目录 |
| `linkora_WORKSPACE` | 活动工作区名称 |
| `linkora_LLM_API_KEY` | LLM API 密钥（回退：`DEEPSEEK_API_KEY`、`OPENAI_API_KEY`）|
| `MINERU_API_KEY` | PDF 解析 API 密钥（MineU）|
| `ZOTERO_API_KEY` | Zotero API 密钥 |
| `ZOTERO_LIBRARY_ID` | Zotero 库 ID |
| `OPENALEX_API_KEY` | OpenAlex API 密钥 |

## CLI 命令

| 命令 | 描述 |
|------|------|
| `linkora search <query>` | 搜索论文（默认：FTS5）|
| `linkora search <query> --mode vector` | 语义向量搜索 |
| `linkora index` | 构建 FTS5 索引 |
| `linkora index --type vector` | 构建向量索引 |
| `linkora init` | 交互式设置向导 |
| `linkora audit` | 数据质量审计 |
| `linkora doctor` | 完整健康检查 |
| `linkora --context` | 显示设计上下文（AI 代理使用）|

## 架构

linkora 采用分层架构：

- **Layer 3**: CLI、MCP 服务器、导出
- **Layer 2**: 特性（主题、数据源）
- **Layer 1**: 核心（加载器、索引、提取）
- **Layer 0**: 基础（配置、日志、论文）

详见 [`docs/design.md`](docs/design.md)。

## 开发

详见 [`docs/AGENT.md`](docs/AGENT.md)。

linkora 使用 [just](https://github.com/casey/just) 进行开发工作流。安装 just 后可使用以下命令：

```bash
# 显示所有可用命令
just

# 常用命令
just setup        # 创建虚拟环境并同步依赖
just test         # 运行测试
just lint         # 代码检查
just typecheck    # 类型检查
just check        # 所有质量检查
just ci           # 完整 CI 流程
```

### 手动设置

```bash
uv venv
uv sync

# 运行测试
uv run pytest tests/ -v

# 代码检查
uv run ruff check .
uv run ruff format .

# 类型检查
uv run ty check
```

## 许可证

[MIT](LICENSE) © 2026
