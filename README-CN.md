# linkora

面向用户与 AI 代理的本地优先（local-first）知识库 CLI。

[English](./README.md) | [中文](./README-CN.md)

---

## 它能做什么

linkora 会在你现有文件之上建立本地知识层。
既可以由用户在终端直接使用，也可以作为 AI 代理的可检索上下文后端。

- 文件不搬运：只记录 `source_path`，不复制原始文档。
- 多源导入：支持本地文件/目录、DOI、arXiv、网页 URL。
- 提取与增强：抽取文本，按 schema 结构化，支持可选 LLM 增强。
- 双检索模式：FTS5 全文检索 + LanceDB 向量检索。
- 工作区隔离：workspace 是数据库命名空间，适合多语料并行管理。

架构文档：[`docs/design-v2.md`](docs/design-v2.md)

## 适用场景

- 用户：构建个人/团队研究语料并快速搜索。
- AI 代理：先读 `linkora --context`，再走 add/index/search 的确定性流程。
- 工程场景：本地优先，路径清晰，可审计。

---

## 功能特性

- 多源导入：`add` 支持本地文件/目录、DOI、arXiv、URL。
- 结构化增强：schema 驱动元数据抽取，支持可选 LLM 增强。
- 混合检索：`fulltext` 与 `vector` 两种检索模式。
- 文件工作流：`files tidy/dedup/rescan/inbox/watch`。
- 主题工作流：`topics build/list/show/assign/prune/export`。
- 本地优先存储：单 SQLite 数据库 + 本地向量与缓存目录。

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

## 如何使用

典型流程：
1. 检查上下文与环境。
2. 把内容导入工作区。
3. 建索引并搜索。

```bash
# 查看 AI/代理上下文
uv run linkora --context

# 可选：诊断配置/环境
uv run linkora doctor

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

工作区优先级：CLI `--workspace` > `LINKORA_WORKSPACE` 环境变量 > 注册表默认工作区。

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

### 贡献说明（分层与拆分）

- CLI/运行时引导集中在 `linkora/cli/setup.py`。
- core 模块不得依赖 `linkora.cli.*`。
- core 依赖应显式注入（store/config/path/cache 由编排边界传入）。
- 不在 core 内新增独立 `application` 层，沿用现有模块边界进行编排。

版本与发布同步辅助命令：

```bash
just release-show
just release-verify
just release-bump 0.4.0
```

贡献说明：[`docs/AGENT.md`](docs/AGENT.md)
架构与迁移参考：[`docs/design-v2.md`](docs/design-v2.md)

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
