"""
audit.py — linkora Paper Audit Module

Contains audit types, rules, and formatting.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


# ============================================================================
#  Audit Types
# ============================================================================


@dataclass(frozen=True)
class Issue:
    """Audit issue report - immutable."""

    paper_id: str
    severity: str  # "error" | "warning" | "info"
    rule: str
    message: str


class YearRange(tuple):
    """Year filter range: (start, end) with None for unbounded."""

    __slots__ = ()

    def __new__(cls, start: int | None, end: int | None) -> "YearRange":
        return super().__new__(cls, (start, end))

    @property
    def start(self) -> int | None:
        return self[0]

    @property
    def end(self) -> int | None:
        return self[1]


# ============================================================================
#  Audit Rules
# ============================================================================


def rule_missing_fields(paper_d: Path, data: dict) -> list[Issue]:
    """Check missing required fields."""
    pid = paper_d.name
    required = ["doi", "abstract", "year", "authors", "journal", "title"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        issues = []
        for field_name in missing:
            severity = "error" if field_name == "title" else "warning"
            issues.append(
                Issue(pid, severity, f"missing_{field_name}", f"Missing {field_name}")
            )
        return issues
    return []


def rule_file_pairing(paper_d: Path, data: dict) -> list[Issue]:
    """Check meta.json / paper.md pairing."""
    pid = paper_d.name
    md_path = paper_d / "paper.md"
    if not md_path.exists():
        return [
            Issue(pid, "error", "missing_md", "meta.json exists but paper.md missing")
        ]

    # Check content length
    try:
        content = md_path.read_text(encoding="utf-8", errors="replace")
        if content and len(content.strip()) < 200:
            return [
                Issue(
                    pid,
                    "warning",
                    "short_md",
                    f"paper.md too short ({len(content.strip())} chars)",
                )
            ]
    except Exception:
        pass
    return []


def rule_title_match(paper_d: Path, data: dict) -> list[Issue]:
    """Check JSON title vs MD H1 consistency."""
    import re

    pid = paper_d.name
    md_path = paper_d / "paper.md"

    if not md_path.exists():
        return []

    md_content = md_path.read_text(encoding="utf-8", errors="replace")
    h1_match = re.search(r"^#\s+(.+)$", md_content, re.MULTILINE)
    if not h1_match:
        return []

    json_title = data.get("title", "").lower()
    md_title = h1_match.group(1).strip().lower()
    json_words = set(re.findall(r"\w{4,}", json_title))
    md_words = set(re.findall(r"\w{4,}", md_title))
    if json_words and md_words:
        overlap = len(json_words & md_words) / max(len(json_words), 1)
        if overlap < 0.3:
            return [Issue(pid, "warning", "title_mismatch", "JSON vs MD H1 mismatch")]
    return []


def rule_filename_format(paper_d: Path, data: dict) -> list[Issue]:
    """Check directory name format."""
    import re

    pid = paper_d.name
    m = re.match(r"^(.+?)-(\d{4})-(.+)$", pid)
    if not m:
        return [
            Issue(pid, "info", "nonstandard_filename", "Not Author-Year-Title format")
        ]

    file_year = int(m.group(2))
    json_year = data.get("year")
    if json_year and file_year != json_year:
        return [
            Issue(
                pid,
                "warning",
                "filename_year_mismatch",
                f"Dir year {file_year} != JSON year {json_year}",
            )
        ]
    return []


DEFAULT_RULES: list[Callable[[Path, dict], list[Issue]]] = [
    rule_missing_fields,
    rule_file_pairing,
    rule_title_match,
    rule_filename_format,
]


# ============================================================================
#  Audit Formatter
# ============================================================================


def format_audit(issues: list[Issue]) -> str:
    """Format audit issues as report."""
    if not issues:
        return "Audit passed, no issues found."

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    infos = [i for i in issues if i.severity == "info"]

    lines = [
        f"Audit: {len(errors)} errors, {len(warnings)} warnings, {len(infos)} info\n"
    ]

    if errors:
        lines.extend(["=" * 40, "Errors", "=" * 40])
        for i in errors:
            lines.append(f"  [{i.rule}] {i.paper_id}: {i.message}")

    if warnings:
        lines.extend(["", "-" * 40, "Warnings", "-" * 40])
        for i in warnings:
            lines.append(f"  [{i.rule}] {i.paper_id}: {i.message}")

    if infos:
        lines.extend(["", "-" * 40, "Info", "-" * 40])
        for i in infos:
            lines.append(f"  [{i.rule}] {i.paper_id}: {i.message}")

    return "\n".join(lines)
