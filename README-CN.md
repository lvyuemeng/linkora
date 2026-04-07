# linkora

面向用户与 AI 代理的本地优先知识库 CLI，让你的文档在本地就能变成可检索、可编排、可复用的知识系统。

[English](./README.md) | [中文](./README-CN.md)

---

## 介绍

linkora 的目标很直接：不改变你原有文件组织方式，也不把数据强行推到云端，而是在现有文档之上构建一层可靠的知识检索能力。

它把「资料堆积」变成「可搜索、可追踪、可自动化」的工作流：

- 文件留在原地：只记录来源路径，不复制原始文档。
- AI 代理可直接消费结构化上下文，减少脆弱 prompt 拼接。
- 从导入到检索的流程可重复、可审计、可落地。

架构参考：[`docs/design-v2.md`](docs/design-v2.md)

## 关键能力

- **本地优先**：数据路径清晰，权限与备份策略更可控。
- **多源导入统一管线**：本地文件/目录、DOI、arXiv、网页 URL 一次打通。
- **混合检索体验**：FTS5 关键词检索 + 向量语义检索，速度与召回兼顾。
- **工作区隔离**：不同项目、团队、语料可并行管理，互不干扰。
- **代理友好**：`linkora --context` 提供可执行的上下文提示，自动化更稳定。

---

## 安装

前置要求：

- Python 3.12+
- `uv`

安装 `uv`：

```bash
pip install uv
```

使用 `uv tool` 安装 linkora（含完整可选功能）：

```bash
uv tool install "linkora[full]"
```

检查安装：

```bash
linkora --help
```

### 源码开发安装

```bash
git clone https://github.com/lvyuemeng/linkora.git
cd linkora
uv sync
uv run linkora --help
```

---

## 基础用法

一个最小可用流程：

```bash
# 1) 查看运行上下文（用户与代理都很有用）
linkora --context

# 2) 可选：环境与配置健康检查
linkora doctor

# 3) 导入内容到工作区
linkora add ./docs/paper.pdf --workspace default
linkora add doi:10.48550/arXiv.1706.03762 --output ~/Downloads --workspace default

# 4) 构建索引
linkora index

# 5) 检索（关键词 / 语义向量）
linkora search "transformer"
linkora search "embedding alignment" --mode vector
```

工作区优先级：CLI `--workspace` > `LINKORA_WORKSPACE` > 注册表默认工作区。

---

## 配置

配置是可选的。没有配置文件时，linkora 使用内置默认值。

- 单文件生效（single-file-wins）
- 若命中多个候选配置会给出 warning
- 仅支持全局配置（不支持 workspace-local 覆盖）

详见：[`docs/config.md`](docs/config.md)

```bash
linkora config show
linkora config show llm.model
linkora config set llm.model deepseek-chat
```

---

## 命令概览

- 导入：`add`
- 检索：`search`
- 建索引：`index`
- 增强：`enrich`
- 文件工作流：`files ...`
- 主题工作流：`topics ...`
- 配置：`config show/set`
- 诊断：`doctor`

使用 `linkora <command> --help` 查看详细参数。

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

```bash
uv run ruff format .
uv run ruff check .
uv run ty check .
uv run -m pytest
```

贡献说明：[`docs/AGENT.md`](docs/AGENT.md)

## 许可证

[MIT](LICENSE)
