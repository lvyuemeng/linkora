# linkora

本地优先（local-first）的文档语料 CLI，面向 AI 协作工作流。

[English](./README.md) | [中文](./README-CN.md)

---

## linkora 是什么

linkora 在原文件位置建立索引，按 schema 做结构化元数据增强，并提供全文 + 向量检索。

核心原则：
- 用户文件不搬运，`source_path` 始终指向原文件
- 工作区是数据库命名空间，不是工作区目录树
- 流水线显式可组合（source -> fetch -> ingest，schema -> parse -> filter）

架构权威文档：[`docs/design-v2.md`](docs/design-v2.md)

---

## 核心能力

- 源导入：
  - 本地文件/目录
  - `doi:<id>`
  - `arxiv:<id>`
  - `web:<url>`
- 管线处理：
  - 文本提取（Kreuzberg）
  - 元数据增强（schema + LLM）
  - SQLite 持久化
- 检索：
  - `fulltext`（FTS5）
  - `vector`（LanceDB）
- 文件工作流：
  - `files tidy`、`files dedup`、`files rescan`、`files inbox`、`files watch`
- 主题工作流：
  - `topics build`、`list`、`show`、`assign`、`prune`、`export`

---

## 安装

前置要求：
- Python 3.12+
- `uv`

源码安装：

```bash
git clone https://github.com/lvyuemeng/linkora.git
cd linkora
uv sync
```

检查 CLI：

```bash
uv run linkora --help
```

---

## 快速开始

```bash
# 查看 AI/代理上下文
uv run linkora --context

# 初始化配置和环境
uv run linkora init

# 导入本地文件
uv run linkora add ./docs/paper.pdf --workspace default

# 按来源导入
uv run linkora add doi:10.48550/arXiv.1706.03762 --output ~/Downloads --workspace default
uv run linkora add arxiv:2401.01234 --output ~/Downloads --workspace default
uv run linkora add web:https://example.com/post --output ~/Downloads --workspace default

# 构建索引
uv run linkora index

# 搜索
uv run linkora search "transformer"
uv run linkora search "embedding" --mode vector
```

---

## 配置

配置是可选的。没有配置文件时，linkora 会使用内置默认值。

配置模型：
- 单文件生效（single-file-wins）
- 若命中多个候选文件会发出 warning
- 仅全局配置（不支持 workspace-local 覆盖）

详见：[`docs/config.md`](docs/config.md)

常用命令：

```bash
uv run linkora config show
uv run linkora config show llm.model
uv run linkora config set llm.model deepseek-chat
```

---

## 命令概览

- 导入：`add`
- 检索：`search`
- 建索引：`index`
- 增强：`enrich`
- 文件：`files ...`
- 主题：`topics ...`
- 配置：`config show/set`
- 诊断：`doctor`

可通过 `uv run linkora <command> --help` 查看详细参数。

---

## 数据目录

数据根目录（可用 `LINKORA_ROOT` 覆盖）下：

```text
<data_root>/
  linkora.db
  vectors/
  cache/
  linkora.log
```

---

## 开发

仅使用 `uv` 工作流：

```bash
uv run ruff format .
uv run ruff check .
uv run ty check
uv run -m pytest
```

贡献说明：[`docs/AGENT.md`](docs/AGENT.md)

可选的 `just` 快捷命令（见 `justfile`）：

```bash
just setup
just format
just lint
just type
just test
just ci
```

---

## 许可证

[MIT](LICENSE)
