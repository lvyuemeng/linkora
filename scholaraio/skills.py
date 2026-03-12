"""
skills.py - CLI skill definitions and registry.

Defines command metadata for CLI and MCP server.
Grouped by functional domain for extensibility.
"""

from dataclasses import dataclass
from typing import Callable


@dataclass
class Skill:
    """Single skill/command definition."""

    name: str
    description: str
    usage: str
    help_zh: str
    handler: Callable[..., None]
    arguments: list[dict]
    filters: bool = False
    subcommands: dict | None = None


# ============================================================================
#  Skill Groups - Organized by functional domain
# ============================================================================

SEARCH_GROUP: list[Skill] = [
    Skill(
        name="search",
        description="Search academic papers using FTS5 full-text search.",
        usage="scholaraio search <query> [--top N] [--year Y] [--journal J] [--type T]",
        help_zh="关键词检索",
        handler=None,  # Set at registration time
        arguments=[
            {"name": "query", "nargs": "+", "help": "检索词"},
            {"name": "--top", "type": int, "default": None, "help": "最多返回 N 条"},
        ],
        filters=True,
    ),
    Skill(
        name="search-author",
        description="Search papers by author name.",
        usage="scholaraio search-author <name> [--top N] [--year Y] [--journal J]",
        help_zh="按作者名搜索",
        handler=None,
        arguments=[
            {"name": "query", "nargs": "+", "help": "作者名"},
            {"name": "--top", "type": int, "default": None, "help": "最多返回 N 条"},
        ],
        filters=True,
    ),
    Skill(
        name="vsearch",
        description="Semantic vector search using Qwen3 embeddings.",
        usage="scholaraio vsearch <query> [--top N] [--year Y] [--journal J]",
        help_zh="语义向量检索",
        handler=None,
        arguments=[
            {"name": "query", "nargs": "+", "help": "检索词"},
            {"name": "--top", "type": int, "default": None, "help": "最多返回 N 条"},
        ],
        filters=True,
    ),
    Skill(
        name="usearch",
        description="Unified search combining FTS5 and vector search.",
        usage="scholaraio usearch <query> [--top N] [--year Y] [--journal J]",
        help_zh="融合检索",
        handler=None,
        arguments=[
            {"name": "query", "nargs": "+", "help": "检索词"},
            {"name": "--top", "type": int, "default": None, "help": "最多返回 N 条"},
        ],
        filters=True,
    ),
]

VIEW_GROUP: list[Skill] = [
    Skill(
        name="show",
        description="View paper content at different layers (L1-L4).",
        usage="scholaraio show <paper-id> [--layer 1|2|3|4]",
        help_zh="查看论文内容",
        handler=None,
        arguments=[
            {"name": "paper_id", "help": "论文 ID"},
            {
                "name": "--layer",
                "type": int,
                "default": 2,
                "choices": [1, 2, 3, 4],
                "help": "加载层级",
            },
        ],
    ),
    Skill(
        name="top-cited",
        description="View papers sorted by citation count.",
        usage="scholaraio top-cited [--top N] [--year Y] [--journal J]",
        help_zh="按引用次数查看",
        handler=None,
        arguments=[
            {"name": "--top", "type": int, "default": 20, "help": "返回条数"},
        ],
        filters=True,
    ),
    Skill(
        name="refs",
        description="View references of a paper.",
        usage="scholaraio refs <paper-id> [--ws WORKSPACE]",
        help_zh="查看参考文献",
        handler=None,
        arguments=[
            {"name": "paper_id", "help": "论文 ID"},
        ],
    ),
    Skill(
        name="citing",
        description="Find papers that cite a given paper.",
        usage="scholaraio citing <paper-id> [--ws WORKSPACE]",
        help_zh="查看引用",
        handler=None,
        arguments=[
            {"name": "paper_id", "help": "论文 ID"},
        ],
    ),
    Skill(
        name="shared-refs",
        description="Analyze shared references between papers.",
        usage="scholaraio shared-refs <id1> <id2> ...",
        help_zh="共同引用分析",
        handler=None,
        arguments=[
            {"name": "paper_ids", "nargs": "+", "help": "论文 ID 列表"},
        ],
    ),
]

INDEX_GROUP: list[Skill] = [
    Skill(
        name="index",
        description="Build FTS5 full-text search index.",
        usage="scholaraio index [--rebuild]",
        help_zh="构建 FTS5 索引",
        handler=None,
        arguments=[
            {"--rebuild": {"action": "store_true", "help": "清空后重建"}},
        ],
    ),
    Skill(
        name="embed",
        description="Build semantic vector index using Qwen3.",
        usage="scholaraio embed [--rebuild]",
        help_zh="构建向量索引",
        handler=None,
        arguments=[
            {"--rebuild": {"action": "store_true", "help": "清空后重建"}},
        ],
    ),
]

ENRICH_GROUP: list[Skill] = [
    Skill(
        name="enrich-toc",
        description="Extract table of contents using LLM.",
        usage="scholaraio enrich-toc [<paper-id> | --all] [--force] [--inspect]",
        help_zh="提取目录结构",
        handler=None,
        arguments=[
            {"name": "paper_id", "nargs": "?", "help": "论文 ID"},
            {"--all": {"action": "store_true", "help": "处理所有论文"}},
            {"--force": {"action": "store_true", "help": "强制重新提取"}},
            {"--inspect": {"action": "store_true", "help": "展示过程"}},
        ],
    ),
    Skill(
        name="enrich-l3",
        description="Extract conclusion section using LLM.",
        usage="scholaraio enrich-l3 [<paper-id> | --all] [--force] [--inspect]",
        help_zh="提取结论",
        handler=None,
        arguments=[
            {"name": "paper_id", "nargs": "?", "help": "论文 ID"},
            {"--all": {"action": "store_true", "help": "处理所有论文"}},
            {"--force": {"action": "store_true", "help": "强制重新提取"}},
            {"--inspect": {"action": "store_true", "help": "展示过程"}},
            {"--max-retries": {"type": int, "default": 2, "help": "最大重试次数"}},
        ],
    ),
]

PIPELINE_GROUP: list[Skill] = [
    Skill(
        name="pipeline",
        description="Ingest papers through the full pipeline.",
        usage="scholaraio pipeline <preset> [--steps S1,S2...]",
        help_zh="入库管道",
        handler=None,
        arguments=[
            {"name": "preset", "help": "预设 (pdf|md|meta)"},
            {"--steps": {"help": "指定步骤"}},
            {"--dry-run": {"action": "store_true", "help": "模拟运行"}},
            {"--no-api": {"action": "store_true", "help": "跳过 API 调用"}},
            {"--force": {"action": "store_true", "help": "强制执行"}},
        ],
    ),
    Skill(
        name="refetch",
        description="Refetch metadata from APIs.",
        usage="scholaraio refetch [<paper-id> | --all] [--force]",
        help_zh="重新获取元数据",
        handler=None,
        arguments=[
            {"name": "paper_id", "nargs": "?", "help": "论文 ID"},
            {"--all": {"action": "store_true", "help": "处理所有论文"}},
            {"--force": {"action": "store_true", "help": "强制重新获取"}},
            {"--jobs": {"type": int, "default": 4, "help": "并行任务数"}},
        ],
    ),
    Skill(
        name="backfill-abstract",
        description="Backfill missing abstracts.",
        usage="scholaraio backfill-abstract [--dry-run] [--doi-fetch]",
        help_zh="补全摘要",
        handler=None,
        arguments=[
            {"--dry-run": {"action": "store_true", "help": "模拟运行"}},
            {"--doi-fetch": {"action": "store_true", "help": "通过 DOI 获取"}},
        ],
    ),
]

TOPICS_GROUP: list[Skill] = [
    Skill(
        name="topics",
        description="Explore topic distribution using BERTopic.",
        usage="scholaraio topics [--build] [--rebuild] [--viz]",
        help_zh="主题建模",
        handler=None,
        arguments=[
            {"--build": {"action": "store_true", "help": "构建模型"}},
            {"--rebuild": {"action": "store_true", "help": "重建模型"}},
            {"--viz": {"action": "store_true", "help": "生成可视化"}},
            {"--topic": {"type": int, "help": "指定主题 ID"}},
            {"--reduce": {"type": int, "help": "减少主题数"}},
        ],
    ),
]

MAINTENANCE_GROUP: list[Skill] = [
    Skill(
        name="rename",
        description="Rename paper directories based on metadata.",
        usage="scholaraio rename [<paper-id> | --all] [--dry-run]",
        help_zh="重命名",
        handler=None,
        arguments=[
            {"name": "paper_id", "nargs": "?", "help": "论文 ID"},
            {"--all": {"action": "store_true", "help": "处理所有论文"}},
            {"--dry-run": {"action": "store_true", "help": "模拟运行"}},
        ],
    ),
    Skill(
        name="audit",
        description="Audit data quality of ingested papers.",
        usage="scholaraio audit [--severity error|warning|info]",
        help_zh="数据审计",
        handler=None,
        arguments=[
            {
                "--severity": {
                    "choices": ["error", "warning", "info"],
                    "help": "最低严重级别",
                },
            },
        ],
    ),
    Skill(
        name="repair",
        description="Repair paper metadata manually.",
        usage="scholaraio repair <paper-id> --title ...",
        help_zh="修复元数据",
        handler=None,
        arguments=[
            {"name": "paper_id", "help": "论文 ID"},
            {"--title": {"help": "标题"}},
            {"--doi": {"help": "DOI"}},
            {"--author": {"help": "作者"}},
            {"--year": {"type": int, "help": "年份"}},
            {"--no-api": {"action": "store_true", "help": "跳过 API"}},
            {"--dry-run": {"action": "store_true", "help": "模拟运行"}},
        ],
    ),
]

EXPORT_GROUP: list[Skill] = [
    Skill(
        name="export",
        description="Export papers to BibTeX format.",
        usage="scholaraio export bibtex [<paper-id> ...] [--all]",
        help_zh="导出 BibTeX",
        handler=None,
        arguments=[
            {"name": "format", "help": "格式 (bibtex)"},
            {"name": "paper_ids", "nargs": "*", "help": "论文 ID"},
            {"--all": {"action": "store_true", "help": "导出全部"}},
            {"--year": {"help": "年份过滤"}},
            {"--journal": {"help": "期刊过滤"}},
            {"-o": {"dest": "output", "help": "输出文件"}},
        ],
        subcommands={"bibtex": {}},
    ),
]

WORKSPACE_GROUP: list[Skill] = [
    Skill(
        name="ws",
        description="Manage workspace for paper subsets.",
        usage="scholaraio ws init|add|remove|list|show|search|export",
        help_zh="工作区管理",
        handler=None,
        arguments=[],
        subcommands={
            "init": {"help": "创建工作区"},
            "add": {"help": "添加论文"},
            "remove": {"help": "移除论文"},
            "list": {"help": "列出论文"},
            "show": {"help": "查看论文"},
            "search": {"help": "搜索"},
            "export": {"help": "导出"},
        },
    ),
]

IMPORT_GROUP: list[Skill] = [
    Skill(
        name="import-endnote",
        description="Import papers from Endnote XML/RIS.",
        usage="scholaraio import-endnote <file>",
        help_zh="导入 Endnote",
        handler=None,
        arguments=[
            {"name": "file", "help": "文件路径"},
            {"--no-api": {"action": "store_true", "help": "跳过 API"}},
            {"--dry-run": {"action": "store_true", "help": "模拟运行"}},
            {"--no-convert": {"action": "store_true", "help": "不转换 PDF"}},
        ],
    ),
    Skill(
        name="import-zotero",
        description="Import papers from Zotero.",
        usage="scholaraio import-zotero [--api-key KEY]",
        help_zh="导入 Zotero",
        handler=None,
        arguments=[
            {"--api-key": {"help": "API 密钥"}},
            {"--library-id": {"help": "Library ID"}},
            {"--local": {"help": "本地路径"}},
            {"--collection": {"help": "Collection key"}},
        ],
    ),
    Skill(
        name="attach-pdf",
        description="Attach PDF to existing paper.",
        usage="scholaraio attach-pdf <paper-id> <path>",
        help_zh="附加 PDF",
        handler=None,
        arguments=[
            {"name": "paper_id", "help": "论文 ID"},
            {"name": "path", "help": "PDF 路径"},
        ],
    ),
]

SYSTEM_GROUP: list[Skill] = [
    Skill(
        name="setup",
        description="Environment detection and setup wizard.",
        usage="scholaraio setup [check] [--lang en|zh]",
        help_zh="环境配置",
        handler=None,
        arguments=[
            {"name": "check", "nargs": "?", "help": "检查模式"},
            {"--lang": {"choices": ["en", "zh"], "help": "语言"}},
        ],
    ),
    Skill(
        name="migrate-dirs",
        description="Migrate paper directory structure.",
        usage="scholaraio migrate-dirs",
        help_zh="迁移目录",
        handler=None,
        arguments=[],
    ),
    Skill(
        name="metrics",
        description="View LLM token usage and API statistics.",
        usage="scholaraio metrics [--summary] [--last N]",
        help_zh="查看统计",
        handler=None,
        arguments=[
            {"--summary": {"action": "store_true", "help": "汇总"}},
            {"--last": {"type": int, "help": "最近 N 条"}},
            {"--category": {"help": "分类"}},
            {"--since": {"help": "起始日期"}},
        ],
    ),
]

# All skill groups
SKILL_GROUPS: dict[str, list[Skill]] = {
    "search": SEARCH_GROUP,
    "view": VIEW_GROUP,
    "index": INDEX_GROUP,
    "enrich": ENRICH_GROUP,
    "pipeline": PIPELINE_GROUP,
    "topics": TOPICS_GROUP,
    "maintenance": MAINTENANCE_GROUP,
    "export": EXPORT_GROUP,
    "workspace": WORKSPACE_GROUP,
    "import": IMPORT_GROUP,
    "system": SYSTEM_GROUP,
}


def get_all_skills() -> list[Skill]:
    """Flatten all skill groups into a single list."""
    skills = []
    for group in SKILL_GROUPS.values():
        skills.extend(group)
    return skills


def build_skills_dict() -> dict[str, dict]:
    """Build SKILLS dict for backward compatibility."""
    result = {}
    for skill in get_all_skills():
        result[skill.name] = {
            "description": skill.description,
            "usage": skill.usage,
        }
    return result
