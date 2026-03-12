"""
migrate.py — 迁移 data/papers/ 从平铺结构到每篇一目录
=====================================================

平铺结构:
    data/papers/Smith-2023-Paper.json + Smith-2023-Paper.md

迁移后:
    data/papers/Smith-2023-Paper/meta.json + paper.md
    (meta.json 中注入 "id": "<uuid>")
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from scholaraio.log import ui
from scholaraio.papers import generate_uuid

_log = logging.getLogger(__name__)


def migrate_to_dirs(papers_dir: Path, *, dry_run: bool = True) -> dict[str, int]:
    """迁移平铺论文到每篇一目录结构。

    Args:
        papers_dir: 论文目录。
        dry_run: 为 ``True`` 时只预览，不写文件。

    Returns:
        统计字典: ``{"migrated": N, "skipped": N, "failed": N}``。
    """
    stats = {"migrated": 0, "skipped": 0, "failed": 0}

    if not papers_dir.exists():
        _log.error("papers_dir does not exist: %s", papers_dir)
        return stats

    # Find flat JSON files (not inside subdirectories)
    flat_jsons = sorted(
        p for p in papers_dir.glob("*.json") if p.is_file() and p.parent == papers_dir
    )

    if not flat_jsons:
        _log.info("没有找到需要迁移的平铺文件")
        return stats

    for json_path in flat_jsons:
        stem = json_path.stem
        md_path = json_path.with_suffix(".md")
        target_dir = papers_dir / stem

        # Already migrated (directory exists with meta.json)
        if target_dir.is_dir() and (target_dir / "meta.json").exists():
            # Rescue orphan .md left by a previous interrupted migration
            if md_path.exists() and not (target_dir / "paper.md").exists():
                if not dry_run:
                    shutil.move(str(md_path), str(target_dir / "paper.md"))
                _log.info("rescued orphan .md: %s", stem)
            _log.debug("already migrated: %s", stem)
            stats["skipped"] += 1
            continue

        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            _log.error("JSON parse failed: %s: %s", stem, e)
            stats["failed"] += 1
            continue

        # Inject UUID if not present
        if not data.get("id"):
            data["id"] = generate_uuid()

        if dry_run:
            has_md = "+" if md_path.exists() else "-"
            ui(
                f"  [dry-run] {stem}/ (meta.json{has_md}paper.md) id={data['id'][:8]}..."
            )
            stats["migrated"] += 1
            continue

        # Create directory
        target_dir.mkdir(exist_ok=True)

        # Write meta.json with UUID
        from scholaraio.papers import write_meta

        write_meta(target_dir, data)

        # Move .md if exists
        if md_path.exists():
            shutil.move(str(md_path), str(target_dir / "paper.md"))

        # Remove old flat .json
        json_path.unlink()

        _log.info("migrated: %s", stem)
        stats["migrated"] += 1

    # Delete stale FAISS index files (force rebuild)
    for fname in ("faiss.index", "faiss_ids.json"):
        fpath = papers_dir.parent / fname  # data/ directory
        if fpath.exists() and not dry_run:
            fpath.unlink()
            _log.info("deleted stale: %s", fname)

    return stats
