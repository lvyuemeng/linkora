# ScholarAIO 项目深度解析

## 项目概述

ScholarAIO（Scholar All-In-One）是一个 AI 驱动的科研终端，旨在让用户通过自然语言完成所有科研工作——文献检索、阅读、讨论、分析、写作。它将 Claude Code 等 AI 编码代理与一套科研级基础设施结合，提供高质量 PDF 解析、混合检索、主题建模、引用图谱和鲁棒的元数据流水线。

### 核心特性

| 特性 | 描述 |
|------|------|
| **深度 PDF 解析** | MinerU → 结构化 Markdown，图表、公式完整保留 |
| **融合检索** | FTS5 关键词 + Qwen3 语义向量 + FAISS → RRF 排序融合 |
| **主题发现** | BERTopic 自动聚类 + 6 种交互式 HTML 可视化 |
| **期刊探索** | OpenAlex 拉取期刊全量论文 → 向量化 → 聚类 → 语义搜索 |
| **引用图谱** | 参考文献 / 被引论文 / 共同引用，全库或工作区范围查询 |
| **分层阅读** | L1 元数据 → L2 摘要 → L3 结论 → L4 全文——按需加载 |
| **多源导入** | Endnote XML/RIS、Zotero（Web API + 本地 SQLite）、PDF、Markdown |
| **工作区** | 论文子集管理，支持范围内检索和 BibTeX 导出 |
| **学术写作** | 文献综述、论文起草、引用验证、审稿回复、研究空白分析 |
| **MCP 服务器** | 31 个工具，Claude Desktop / Cursor 等 MCP 客户端均可调用 |

---

## 系统架构

```
PDF → mineru.py → .md     (或直接放置 .md 跳过 MinerU)
                   ↓
             extractor.py (阶段 1：从 md header 提取字段；regex/auto/robust/llm 四种模式)
             metadata/    (阶段 2：API 查询补全，JSON 输出，文件重命名)
                   ↓
             pipeline.py  (DOI 去重检查)
               ├─ 有 DOI → data/papers/<Author-Year-Title>/meta.json + paper.md
               └─ 无 DOI  → data/pending/ (等待人工确认)
                   ↓
             index.py → data/index.db (SQLite FTS5)
             vectors.py → data/index.db (paper_vectors 表)
             topics.py → data/topic_model/ (BERTopic，复用 paper_vectors)
                   ↓
             cli.py → skills → 编码代理
```

### 模块说明

| 模块 | 功能 |
|------|------|
| `ingest/mineru.py` | PDF → MinerU Markdown（云 API / 本地） |
| `ingest/extractor.py` | 元数据提取（regex / auto / robust / llm — 4 种模式） |
| `ingest/metadata/` | API 查询补全（Crossref / S2 / OpenAlex），JSON 输出，文件重命名 |
| `ingest/pipeline.py` | 可组合入库流水线（DOI 去重 + pending 机制） |
| `index.py` | FTS5 全文搜索 + papers_registry + 引用图谱 |
| `vectors.py` | Qwen3 语义向量 + FAISS 增量索引 |
| `topics.py` | BERTopic 主题建模 + 6 种 HTML 可视化 |
| `loader.py` | L1-L4 分层加载 + enrich_toc + enrich_l3 |
| `explore.py` | 期刊级探索（OpenAlex + embeddings + topics，隔离在 `data/explore/`） |
| `workspace.py` | 工作区论文子集管理（复用 search/export） |
| `export.py` | BibTeX 导出 |
| `audit.py` | 数据质量审计 + 修复 |
| `sources/` | 数据源适配器（local / endnote / zotero） |
| `cli.py` | 完整 CLI 入口点 |
| `mcp_server.py` | MCP 服务器（31 个工具） |
| `setup.py` | 环境检测 + 设置向导 |
| `metrics.py` | LLM token 使用量 + API 计时 |

---

## 数据流详解

### 1. 论文入库流程（Ingest Pipeline）

```
data/inbox/
├── paper.pdf     # 待入库的 PDF（处理后删除）
└── paper.md      # 或直接放置 .md（跳过 MinerU）
```

**流水线步骤**：

1. **mineru** - 调用 MinerU API 将 PDF 转换为结构化 Markdown
2. **extract** - 从 Markdown header 提取元数据（支持 4 种模式）
3. **dedup** - DOI 去重检查
4. **ingest** - 根据 DOI 有无决定去向
   - 有 DOI → `data/papers/<Author-Year-Title>/`
   - 无 DOI → `data/pending/`（等待人工确认）
5. **toc** - 提取目录结构
6. **l3** - 提取结论章节
7. **embed** - 生成 Qwen3 语义向量
8. **index** - 构建 FTS5 全文索引

**预设流水线**：
- `full` = mineru, extract, dedup, ingest, toc, l3, embed, index
- `ingest` = mineru, extract, dedup, ingest, embed, index
- `enrich` = toc, l3, embed, index
- `reindex` = embed, index

### 2. 分层加载设计（L1-L4）

| 层级 | 内容 | 来源 |
|------|------|------|
| L1 | title, authors, year, journal, doi, volume, issue, pages, publisher, issn | JSON 文件 |
| L2 | abstract | JSON 字段 |
| L3 | conclusion section | JSON 字段（需先运行 enrich-l3） |
| L4 | full markdown | 直接读取 .md 文件 |

### 3. 检索系统

**三种检索方式**：

1. **FTS5 关键词搜索** (`search`)
   - 基于 SQLite FTS5 的全文检索
   - 索引字段：title + abstract + conclusion
   
2. **语义向量搜索** (`vsearch`)
   - Qwen3-Embedding-0.6B 生成语义向量
   - FAISS 进行相似度检索
   
3. **混合统一搜索** (`usearch`)
   - RRF（Reciprocal Rank Fusion）融合 FTS5 和向量搜索结果

### 4. 引用图谱

- **refs** - 获取论文的参考文献
- **citing** - 获取引用该论文的论文
- **shared-refs** - 找出多篇论文的共同引用

---

## 目录结构

### data/papers/ 目录结构

```
data/papers/
└── <Author-Year-Title>/
    ├── meta.json    # L1+L2+L3 元数据（包含 "id": "<uuid>"）
    ├── paper.md     # L4 源文件（MinerU 输出）
    ├── images/      # MinerU 提取的图片（md 中引用）
    ├── layout.json  # MinerU 布局分析（可选）
    └── *_content_list.json  # MinerU 结构化内容（可选）
```

### data/pending/ 目录结构

```
data/pending/
└── <PDF-stem>/
    ├── paper.md           # 无 DOI 的论文 markdown
    ├── <original-name>.pdf # 原始 PDF（如果有）
    ├── pending.json       # 标记文件（reason + 提取的元数据）
    ├── images/            # MinerU 提取的图片
    ├── layout.json        # 布局信息
    └── *_content_list.json # 结构化内容
```

### data/explore/ 目录结构

```
data/explore/<name>/
├── papers.jsonl        # OpenAlex 获取的论文（title/abstract/authors/year/doi/cited_by_count）
├── meta.json           # 探索元数据（issn/count/fetched_at）
├── explore.db          # SQLite（paper_vectors 表，Qwen3 嵌入）
├── faiss.index         # FAISS IndexFlatIP（余弦相似度）
├── faiss_ids.json      # FAISS 索引对应的 paper_id 列表
└── topic_model/
    ├── bertopic_model.pkl   # BERTopic 模型
    ├── scholaraio_meta.pkl  # 额外元数据
    ├── info.json            # 统计信息
    └── viz/                 # 6 种 HTML 可视化
```

---

## 使用示例

### 1. 文献搜索

```bash
# 关键词搜索（支持年/期刊/类型过滤）
scholaraio search "drag reduction" --year 2020-2024 --journal "Physics of Fluids"

# 作者搜索
scholaraio search-author "John Smith" --top 10

# 语义向量搜索
scholaraio vsearch "turbulent boundary layer control" --top 5

# 混合统一搜索
scholaraio usearch "machine learning fluid dynamics"
```

### 2. 论文阅读

```bash
# 查看论文（L1-L4 分层加载）
scholaraio show <paper-id>           # 默认 L1
scholaraio show <paper-id> --layer 2  # 摘要
scholaraio show <paper-id> --layer 3  # 结论
scholaraio show <paper-id> --layer 4  # 全文
```

### 3. 论文入库

```bash
# 将 PDF 放入 data/inbox/
# 运行完整流水线
scholaraio pipeline full

# 或分步执行
scholaraio pipeline ingest
scholaraio pipeline enrich
```

### 4. 引用分析

```bash
# 查看参考文献
scholaraio refs <paper-id>

# 查看被引论文
scholaraio citing <paper-id>

# 共同引用分析
scholaraio shared-refs <id1> <id2> <id3> --min 2
```

### 5. 主题发现

```bash
# 构建主题模型
scholaraio topics --build

# 可视化
scholaraio topics --viz

# 查看特定主题
scholaraio topics --topic 3
```

### 6. 期刊探索

```bash
# 从 OpenAlex 获取期刊论文
scholaraio explore fetch --issn "0022-1120" --name "jfm"

# 构建向量索引
scholaraio explore embed --name "jfm"

# 语义搜索
scholaraio explore search --name "jfm" "rotating turbulence"

# 主题建模
scholaraio explore topics --name "jfm" --build
```

### 7. 学术写作

```bash
# 创建工作区
scholaraio workspace create my-review

# 导出 BibTeX
scholaraio export bibtex --all -o references.bib

# 文献综述写作（通过 AI 代理）
# 在 Claude Code 中：帮我写一篇关于 XXX 的文献综述
```

---

## 配置说明

### config.yaml（主配置）

```yaml
paths:
  papers_dir: data/papers
  index_db: data/index.db

llm:
  backend: openai-compat
  model: deepseek-chat
  base_url: https://api.deepseek.com
  api_key: null  # 放 config.local.yaml

ingest:
  extractor: robust  # auto | regex | llm | robust
  mineru_endpoint: http://localhost:8000

embed:
  model: Qwen/Qwen3-Embedding-0.6B
  source: modelscope  # modelscope | huggingface

search:
  top_k: 20

topics:
  min_topic_size: 5
  nr_topics: -1
```

### 敏感信息（config.local.yaml）

```yaml
llm:
  api_key: "your-deepseek-api-key"
  
ingest:
  mineru_api_key: "your-mineru-api-key"
  contact_email: "your-email@example.com"
```

---

## 依赖项

| 依赖 | 用途 | 安装方式 |
|------|------|----------|
| sentence_transformers | 向量嵌入 | `pip install scholaraio[embed]` |
| faiss | 向量检索 | `pip install scholaraio[embed]` |
| bertopic | 主题建模 | `pip install scholaraio[topics]` |
| pandas | 数据处理 | `pip install scholaraio[topics]` |
| endnote_utils | Endnote 导入 | `pip install scholaraio[import]` |
| pyzotero | Zotero 导入 | `pip install scholaraio[import]` |

---

## AI 代理技能（Skills）

ScholarAIO 提供了 22 种可重用的 AI 代理技能，定义在 `skills/` 目录：

### 知识库管理
- `search` — 文献检索（关键词/语义/作者/混合/高引排名）
- `show` — 分层查看论文内容（L1-L4）
- `enrich` — 富化论文内容（TOC/结论/摘要/引用数）
- `ingest` — 入库论文 + 重建索引
- `topics` — 主题探索（BERTopic 聚类 + 可视化）
- `explore` — 期刊级探索（OpenAlex + FAISS + BERTopic）
- `graph` — 引用图谱查询
- `citations` — 引用数查询和刷新
- `index` — 重建 FTS5 / FAISS 索引
- `workspace` — 工作区管理
- `export` — BibTeX 导出
- `import` — Endnote / Zotero 导入
- `rename` — 论文文件重命名
- `audit` — 论文审计（规则检查 + LLM 深度诊断 + 修复）

### 学术写作
- `literature-review` — 文献综述写作
- `paper-writing` — 论文各部分写作
- `citation-check` — 引用验证
- `writing-polish` — 写作润色
- `review-response` — 审稿回复
- `research-gap` — 研究空白识别

### 系统维护
- `setup` — 环境检测和设置向导
- `metrics` — LLM token 使用统计

---

## 核心概念

### DOI 去重机制

- 论文入库时检查 DOI 是否已存在
- 重复时标记为 `pending` 并记录 `duplicate_of` 字段
- 用户可决定覆盖或保留

### pending 机制

- 无 DOI 的论文无法自动入库
- 放入 `data/pending/` 等待人工确认
- 用户可手动添加 DOI 后重新入库

### 论文类型识别

- 通过 LLM 自动识别论文类型（thesis / article）
- 论文类型存储在 `meta.json["paper_type"]`
- thesis 自动入库，跳过 DOI 去重

---

## 总结

ScholarAIO 是一个功能完整的本地学术知识库管理系统，通过 AI 代理赋能，实现：

1. **自动化** - 从 PDF 到可检索知识库的完整自动化流程
2. **智能化** - LLM 驱动的元数据提取、内容富化、学术讨论
3. **灵活性** - 模块化设计，支持自定义流水线
4. **可扩展性** - MCP 服务器支持多种 AI 客户端
5. **本地化** - 所有数据存储在本地，保护隐私

通过自然语言交互，用户可以高效地管理文献、发现问题、撰写论文，真正实现"一个终端，从头到尾"的科研体验。
