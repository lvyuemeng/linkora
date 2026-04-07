from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOT_INIT = ROOT / "linkora" / "__init__.py"
ROOT_PYPROJECT = ROOT / "pyproject.toml"
CORE_PYPROJECT = ROOT / "packages" / "linkora-core" / "pyproject.toml"
CLI_PYPROJECT = ROOT / "packages" / "linkora" / "pyproject.toml"
CORE_DIR = ROOT / "linkora"
CLI_DIR = CORE_DIR / "cli"

VERSION_RE = re.compile(r'^__version__\s*=\s*"(?P<version>[^"]+)"\s*$', re.M)
PROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"(?P<version>[^"]+)"\s*$', re.M)
CORE_PIN_RE = re.compile(r'"linkora-core==(?P<version>[^"]+)"')
TAG_RE = re.compile(r"^v(?P<version>.+)$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$"
)


class ReleaseSyncError(RuntimeError):
    pass


def _read_text(path: Path) -> str:
    if not path.exists():
        raise ReleaseSyncError(f"Missing required file: {path}")
    return path.read_text(encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _read_toml(path: Path) -> dict:
    data = path.read_bytes()
    return tomllib.loads(data.decode("utf-8"))


def _validate_version(version: str) -> None:
    if not SEMVER_RE.match(version):
        raise ReleaseSyncError(
            f"Invalid version '{version}'. Expected semver-like X.Y.Z[-pre][+build]."
        )


def read_root_version() -> str:
    text = _read_text(ROOT_INIT)
    match = VERSION_RE.search(text)
    if not match:
        raise ReleaseSyncError("Cannot find __version__ in linkora/__init__.py")
    return match.group("version")


def read_cli_core_pin() -> str:
    text = _read_text(CLI_PYPROJECT)
    match = CORE_PIN_RE.search(text)
    if not match:
        raise ReleaseSyncError(
            "Cannot find dependency pin 'linkora-core==...' in packages/linkora/pyproject.toml"
        )
    return match.group("version")


def read_project_version(path: Path) -> str:
    project = _read_toml(path).get("project", {})
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseSyncError(
            f"Cannot find static project.version in {path.relative_to(ROOT)}"
        )
    return version


def show() -> None:
    print(f"root_version={read_root_version()}")
    print(f"core_project_version={read_project_version(CORE_PYPROJECT)}")
    print(f"cli_project_version={read_project_version(CLI_PYPROJECT)}")
    print(f"cli_core_pin={read_cli_core_pin()}")


def bump(version: str, dry_run: bool = False) -> None:
    _validate_version(version)

    init_text = _read_text(ROOT_INIT)
    if not VERSION_RE.search(init_text):
        raise ReleaseSyncError("Cannot update __version__; pattern missing")
    updated_init = VERSION_RE.sub(f'__version__ = "{version}"', init_text, count=1)

    core_text = _read_text(CORE_PYPROJECT)
    if not PROJECT_VERSION_RE.search(core_text):
        raise ReleaseSyncError(
            "Cannot update core package version; 'project.version' not found"
        )
    updated_core = PROJECT_VERSION_RE.sub(f'version = "{version}"', core_text, count=1)

    cli_text = _read_text(CLI_PYPROJECT)
    if not PROJECT_VERSION_RE.search(cli_text):
        raise ReleaseSyncError(
            "Cannot update CLI package version; 'project.version' not found"
        )
    if not CORE_PIN_RE.search(cli_text):
        raise ReleaseSyncError(
            "Cannot update CLI dependency pin; 'linkora-core==...' not found"
        )
    updated_cli = PROJECT_VERSION_RE.sub(f'version = "{version}"', cli_text, count=1)
    updated_cli = CORE_PIN_RE.sub(f'"linkora-core=={version}"', updated_cli, count=1)

    if dry_run:
        print(f"[dry-run] would set __version__ to {version}")
        print(f"[dry-run] would set core package version to {version}")
        print(f"[dry-run] would set CLI package version to {version}")
        print(f"[dry-run] would set CLI dependency pin to linkora-core=={version}")
        return

    _write_text(ROOT_INIT, updated_init)
    _write_text(CORE_PYPROJECT, updated_core)
    _write_text(CLI_PYPROJECT, updated_cli)
    print(f"Bumped release version to {version}")


def _iter_core_python_files() -> list[Path]:
    files: list[Path] = []
    for path in CORE_DIR.rglob("*.py"):
        if CLI_DIR in path.parents:
            continue
        files.append(path)
    return files


def _imports_cli_namespace(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "linkora.cli" or alias.name.startswith("linkora.cli."):
                    return True
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == "linkora.cli" or module.startswith("linkora.cli."):
                return True
    return False


def check_boundary() -> None:
    violating = [
        str(path.relative_to(ROOT))
        for path in _iter_core_python_files()
        if _imports_cli_namespace(path)
    ]
    if violating:
        raise ReleaseSyncError(
            "Core modules must not import linkora.cli*: " + ", ".join(violating)
        )
    print("Core/CLI boundary verified")


def verify() -> None:
    for path in (ROOT_PYPROJECT, CORE_PYPROJECT, CLI_PYPROJECT, ROOT_INIT):
        if not path.exists():
            raise ReleaseSyncError(f"Missing required file: {path}")

    root_version = read_root_version()
    core_version = read_project_version(CORE_PYPROJECT)
    cli_version = read_project_version(CLI_PYPROJECT)
    cli_pin = read_cli_core_pin()

    root_proj = _read_toml(ROOT_PYPROJECT)
    core_proj = _read_toml(CORE_PYPROJECT)
    cli_proj = _read_toml(CLI_PYPROJECT)

    if root_proj.get("project", {}).get("name") != "linkora":
        raise ReleaseSyncError("Root pyproject project.name must be 'linkora'")
    if core_proj.get("project", {}).get("name") != "linkora-core":
        raise ReleaseSyncError("Core pyproject project.name must be 'linkora-core'")
    if cli_proj.get("project", {}).get("name") != "linkora":
        raise ReleaseSyncError("CLI pyproject project.name must be 'linkora'")

    if not (root_version == core_version == cli_version):
        raise ReleaseSyncError(
            "Version mismatch across root/core/cli. "
            f"root={root_version}, core={core_version}, cli={cli_version}"
        )

    if core_version != cli_pin:
        raise ReleaseSyncError(
            "Version mismatch: CLI dependency pin does not match core package version. "
            f"core={core_version}, cli_pin={cli_pin}"
        )

    check_boundary()

    print("Version sync verified")


def preflight(tag: str) -> None:
    match = TAG_RE.match(tag)
    if not match:
        raise ReleaseSyncError(f"Invalid tag '{tag}'. Expected format: vX.Y.Z")
    tag_version = match.group("version")
    _validate_version(tag_version)
    verify()
    check_boundary()

    root_version = read_root_version()
    if root_version != tag_version:
        raise ReleaseSyncError(
            f"Tag/version mismatch: tag={tag_version}, root={root_version}"
        )
    print(f"Preflight passed for {tag}")


def wait_core(version: str, attempts: int = 6, delay_seconds: int = 20) -> None:
    _validate_version(version)
    venv_path = ROOT / ".venv-release-check"
    subprocess.run(["uv", "venv", str(venv_path)], check=True)

    for i in range(1, attempts + 1):
        cmd = [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_path),
            f"linkora-core=={version}",
        ]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            print(f"linkora-core=={version} is available")
            return
        if i < attempts:
            time.sleep(delay_seconds)

    raise ReleaseSyncError(
        f"linkora-core=={version} not available after {attempts} attempts"
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Synchronize and verify two-crate release versions"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    bump_parser = sub.add_parser(
        "bump", help="Bump root/core/cli versions and CLI core pin"
    )
    bump_parser.add_argument("version", help="Target version, e.g. 0.4.0")
    bump_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned changes without writing files",
    )

    sub.add_parser("verify", help="Verify release version and package metadata sync")
    sub.add_parser("check-boundary", help="Verify core modules do not import CLI")
    preflight_parser = sub.add_parser("preflight", help="Run release preflight checks")
    preflight_parser.add_argument(
        "--tag", required=True, help="Release tag like v0.4.0"
    )
    wait_parser = sub.add_parser(
        "wait-core", help="Wait until core version is installable"
    )
    wait_parser.add_argument("--version", required=True)
    wait_parser.add_argument("--attempts", type=int, default=6)
    wait_parser.add_argument("--delay", type=int, default=20)
    sub.add_parser("show", help="Show current root/core/cli versions and CLI core pin")

    args = parser.parse_args()

    try:
        if args.cmd == "bump":
            bump(args.version, dry_run=args.dry_run)
            return 0
        if args.cmd == "verify":
            verify()
            return 0
        if args.cmd == "check-boundary":
            check_boundary()
            return 0
        if args.cmd == "preflight":
            preflight(args.tag)
            return 0
        if args.cmd == "wait-core":
            wait_core(args.version, attempts=args.attempts, delay_seconds=args.delay)
            return 0
        if args.cmd == "show":
            show()
            return 0
    except ReleaseSyncError as exc:
        print(f"release_sync error: {exc}", file=sys.stderr)
        return 1

    print("release_sync error: unknown command", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
