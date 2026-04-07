"""cli/setup.py - CLI bootstrap, doctor checks, and config edit helpers."""

from __future__ import annotations

import os
import platform
import tempfile
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from linkora.cli.commands import AppContext
    from linkora.config import AppConfig
    from linkora.db import Database

_runtime_db: "Database | None" = None
_runtime_db_path: Path | None = None
_runtime_config: "AppConfig | None" = None
_runtime_config_path: Path | None = None
_runtime_config_loaded: bool = False
_yaml_module: Any | None = None


@dataclass(frozen=True)
class ConfigDiscovery:
    candidates: tuple[Path, ...]
    existing: tuple[Path, ...]
    active: Path | None

    def load_warnings(self) -> list[str]:
        if len(self.existing) <= 1 or self.active is None:
            return []
        ignored = ", ".join(str(p) for p in self.existing[1:])
        return [
            "Multiple config files found. "
            f"'{self.active}' is active; ignoring: {ignored}. "
            "Remove the ignored file(s) to silence this warning."
        ]


@dataclass(frozen=True)
class ConfigLoadResult:
    config: "AppConfig"
    active_path: Path | None
    warnings: tuple[str, ...] = ()


def get_data_root() -> Path:
    """Return the platform-appropriate linkora data directory."""
    env_root = os.environ.get("LINKORA_ROOT")
    if env_root:
        return Path(env_root).expanduser().resolve()

    home = Path.home()
    system = platform.system()

    if system == "Windows":
        base = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
    elif system == "Darwin":
        base = home / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", home / ".local" / "share"))

    return (base / "linkora").expanduser().resolve()


def ensure_data_root() -> Path:
    root = get_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_db_path() -> Path:
    """Return the path to the SQLite database file."""
    return get_data_root() / "linkora.db"


def get_cache_dir() -> Path:
    """Return the extraction cache directory."""
    return get_data_root() / "cache"


def get_vectors_dir() -> Path:
    """Return the vector index directory."""
    return get_data_root() / "vectors"


def get_config_candidates() -> list[Path]:
    """Return ordered global config path candidates."""
    home = Path.home()
    return [
        home / ".linkora" / "config.yml",
        home / ".linkora" / "config.yaml",
        home / ".linkora.yml",
        home / ".linkora.yaml",
        home / ".config" / "linkora" / "config.yml",
        home / ".config" / "linkora" / "config.yaml",
    ]


def get_config_path() -> Path:
    """Return canonical config write path."""
    return get_config_candidates()[0]


def discover_config_candidates() -> ConfigDiscovery:
    candidates = tuple(get_config_candidates())
    existing = tuple(p for p in candidates if p.exists())
    active = existing[0] if existing else None
    return ConfigDiscovery(candidates=candidates, existing=existing, active=active)


def get_active_config_path() -> Path | None:
    """Return active config path, if any."""
    return discover_config_candidates().active


def get_runtime_config_dir() -> Path:
    """Return active config dir or canonical write dir parent."""
    if _runtime_config_loaded and _runtime_config_path is not None:
        return _runtime_config_path.parent
    active = get_active_config_path()
    return active.parent if active else get_config_path().parent


def load_runtime_config(data_root: Path) -> ConfigLoadResult:
    """Run config load pipeline: discover -> read -> env -> validate -> normalize."""
    from linkora.config import AppConfig

    discovery = discover_config_candidates()
    warnings = tuple(discovery.load_warnings())

    if discovery.active is None:
        config = AppConfig.from_root(data_root)
        return ConfigLoadResult(config=config, active_path=None, warnings=warnings)

    raw = _read_yaml_file(discovery.active)
    dotenv = _load_dotenv(discovery.active.parent / ".env")
    normalized = AppConfig.from_document(
        raw,
        data_root=data_root,
        dotenv=dotenv,
        environ=os.environ,
    )
    return ConfigLoadResult(
        config=normalized,
        active_path=discovery.active,
        warnings=warnings,
    )


def get_runtime_config() -> "AppConfig":
    """Return process runtime config singleton managed by setup."""
    from linkora.log import get_logger

    global _runtime_config, _runtime_config_path, _runtime_config_loaded
    if not _runtime_config_loaded:
        result = load_runtime_config(get_data_root())
        log = get_logger(__name__)
        for warning in result.warnings:
            log.warning(warning)
        if result.active_path is None:
            log.info("No config file found; using built-in defaults.")
        else:
            log.debug("Loading config from %s", result.active_path)

        _runtime_config = result.config
        _runtime_config_path = result.active_path
        _runtime_config_loaded = True
    if _runtime_config is None:
        raise RuntimeError("Runtime config failed to load")
    return _runtime_config


def get_runtime_db(db_path: Path | None = None) -> "Database":
    """Return process runtime DB singleton managed by setup."""
    from linkora.db import Database

    global _runtime_db, _runtime_db_path
    resolved = db_path.expanduser().resolve() if db_path else get_db_path()
    resolved.parent.mkdir(parents=True, exist_ok=True)

    if _runtime_db is None or _runtime_db_path != resolved:
        if _runtime_db is not None:
            _runtime_db.close()
        _runtime_db = Database(resolved)
        _runtime_db_path = resolved
    return _runtime_db


def reset_runtime_state() -> None:
    """Reset setup-managed DB/config singletons (for tests)."""
    global _runtime_db, _runtime_db_path
    global _runtime_config, _runtime_config_path, _runtime_config_loaded

    if _runtime_db is not None:
        _runtime_db.close()
    _runtime_db = None
    _runtime_db_path = None

    _runtime_config = None
    _runtime_config_path = None
    _runtime_config_loaded = False


VALID_CONFIG_SECTIONS = {
    "sources",
    "index",
    "extract",
    "tidy",
    "llm",
    "topics",
    "log",
}


class CheckCategory(Enum):
    CONFIG = auto()
    ENV = auto()
    PATH = auto()


@dataclass(frozen=True)
class CheckItem:
    category: CheckCategory
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class CheckResult:
    items: tuple[CheckItem, ...]

    @property
    def passed(self) -> bool:
        return all(i.ok for i in self.items)

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if not i.ok)


def _yaml_load(raw: str) -> Any:
    global _yaml_module
    if _yaml_module is None:
        import yaml

        _yaml_module = yaml
    yaml = _yaml_module

    return yaml.safe_load(raw)


def _yaml_dump(data: Any) -> str:
    global _yaml_module
    if _yaml_module is None:
        import yaml

        _yaml_module = yaml
    yaml = _yaml_module

    return yaml.safe_dump(
        data,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )


def _read_yaml_file(path: Path) -> dict[str, Any]:
    try:
        payload = _yaml_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        from linkora.log import get_logger

        get_logger(__name__).warning("Failed to load %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_yaml_file(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = _yaml_dump(data)
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
            if existing == content:
                return
        except Exception:
            pass

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=path.parent,
        delete=False,
    ) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _set_nested(doc: Any, parts: list[str], value: Any) -> None:
    current = doc
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}

    env_map: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return {}

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            env_map[key] = value
    return env_map


def set_config_value(field: str, raw_value: str) -> tuple[str, Path, str | None]:
    """Write one config field and reset runtime state."""
    value = _yaml_load(raw_value)
    top_key = field.split(".")[0]
    if top_key not in VALID_CONFIG_SECTIONS:
        return (
            f"Error: Unknown config section '{top_key}'. Valid sections: "
            f"{', '.join(sorted(VALID_CONFIG_SECTIONS))}",
            get_config_path(),
            None,
        )

    config_path = get_active_config_path() or get_config_path()
    existed_before = config_path.exists()
    doc = _read_yaml_file(config_path) if existed_before else {}

    _set_nested(doc, field.split("."), value)
    _write_yaml_file(config_path, doc)

    note = None
    if not existed_before:
        note = f"Creating new config file at {config_path}"

    reset_runtime_state()
    return (f"Set {field} = {value!r}  ({config_path})", config_path, note)


def _check_config_resolution(ctx: "AppContext") -> Iterator[CheckItem]:
    existing = [p for p in get_config_candidates() if p.exists()]
    active = existing[0] if existing else None

    if not existing:
        yield CheckItem(
            CheckCategory.CONFIG,
            "config.file",
            ok=True,
            detail="no file found (using built-in defaults)",
        )
    else:
        yield CheckItem(
            CheckCategory.CONFIG,
            "config.active",
            ok=True,
            detail=str(active),
        )

    if len(existing) > 1 and active is not None:
        ignored = [p for p in existing if p != active]
        yield CheckItem(
            CheckCategory.CONFIG,
            "config.conflict",
            ok=False,
            detail=(
                f"Multiple config files found — only '{active.name}' is active. "
                f"Ignored: {', '.join(str(p) for p in ignored)}. "
                "Remove the ignored file(s) to eliminate this ambiguity."
            ),
        )

    yield CheckItem(
        CheckCategory.CONFIG,
        "config.defaults",
        ok=True,
        detail=(
            f"index.top_k={ctx.config.index.top_k}, "
            f"llm.model={ctx.config.llm.model}, "
            f"llm.base_url={ctx.config.llm.base_url}, "
            f"llm.timeout={ctx.config.llm.timeout}"
        ),
    )


def _check_secrets(ctx: "AppContext") -> Iterator[CheckItem]:
    config_key_set = bool(ctx.config.llm.api_key)
    env_key_set = bool(os.environ.get("LINKORA_LLM_API_KEY"))
    yield CheckItem(
        CheckCategory.ENV,
        "llm.api_key",
        ok=True,
        detail=(
            "configured via config"
            if config_key_set
            else "configured via LINKORA_LLM_API_KEY"
            if env_key_set
            else "not set (optional; enrichment falls back to seed/default fields)"
        ),
    )


def _check_env_vars() -> Iterator[CheckItem]:
    root = os.environ.get("LINKORA_ROOT")
    yield CheckItem(
        CheckCategory.ENV,
        "env.LINKORA_ROOT",
        ok=True,
        detail=root if root else "not set (using platform default data root)",
    )


def _check_paths() -> Iterator[CheckItem]:
    root = get_data_root()
    yield CheckItem(CheckCategory.PATH, "paths.data_root", ok=True, detail=str(root))

    try:
        exists = root.exists()
        yield CheckItem(
            CheckCategory.PATH,
            "paths.data_root.exists",
            ok=exists,
            detail="exists" if exists else "missing (will be created on demand)",
        )
    except Exception as exc:
        yield CheckItem(
            CheckCategory.PATH,
            "paths.data_root.exists",
            ok=False,
            detail=f"failed to check data root: {exc}",
        )

    try:
        ensured = ensure_data_root()
        yield CheckItem(
            CheckCategory.PATH,
            "paths.data_root.ensure",
            ok=True,
            detail=str(ensured),
        )
    except Exception as exc:
        yield CheckItem(
            CheckCategory.PATH,
            "paths.data_root.ensure",
            ok=False,
            detail=f"failed to create data root: {exc}",
        )

    yield CheckItem(CheckCategory.PATH, "paths.db", ok=True, detail=str(get_db_path()))
    yield CheckItem(
        CheckCategory.PATH,
        "paths.cache",
        ok=True,
        detail=str(get_cache_dir()),
    )
    yield CheckItem(
        CheckCategory.PATH,
        "paths.vectors",
        ok=True,
        detail=str(get_vectors_dir()),
    )


def _collect_doctor(ctx: "AppContext") -> Iterator[CheckItem]:
    yield from _check_config_resolution(ctx)
    yield from _check_env_vars()
    yield from _check_secrets(ctx)
    yield from _check_paths()


def run_doctor(ctx: "AppContext") -> CheckResult:
    """Run config/env/path doctor checks (no network calls)."""
    return CheckResult(items=tuple(_collect_doctor(ctx)))


def format_result(result: CheckResult, title: str = "Check") -> str:
    """Format a CheckResult for terminal output."""
    bar = "=" * (len(title) + 8)
    lines = [bar, f"    {title}", bar]

    by_cat: dict[CheckCategory, list[CheckItem]] = {}
    for item in result.items:
        by_cat.setdefault(item.category, []).append(item)

    for cat in CheckCategory:
        items = by_cat.get(cat, [])
        if not items:
            continue
        lines.append(f"\n{cat.name}:")
        for item in items:
            mark = "OK" if item.ok else "FAIL"
            lines.append(f"  [{mark}] {item.name:<34} {item.detail}")

    status = "PASS" if result.passed else "FAIL"
    lines.append(
        f"\n{status}  {result.total - result.failed}/{result.total} checks passed"
    )
    return "\n".join(lines)


def run_init(cli_workspace: str | None = None, force: bool = False) -> "AppContext":
    """Bootstrap runtime context for CLI command handlers."""
    from linkora.cli.commands import AppContext
    from linkora.workspace import WorkspaceStore

    if force:
        print("'--force' has no effect: init no longer writes config files.")

    data_root = ensure_data_root()
    db = get_runtime_db(get_db_path())
    store = WorkspaceStore(db)
    default_workspace_name, _ = store.ensure_default_workspace()
    workspace_name = (
        cli_workspace
        or os.environ.get("LINKORA_WORKSPACE", "")
        or default_workspace_name
    )

    return AppContext(
        config=get_runtime_config(),
        config_dir=get_runtime_config_dir(),
        store=store,
        workspace_name=workspace_name,
        data_root=data_root,
        db=db,
    )


__all__ = [
    "VALID_CONFIG_SECTIONS",
    "CheckCategory",
    "CheckItem",
    "CheckResult",
    "set_config_value",
    "run_doctor",
    "format_result",
    "run_init",
    "get_config_candidates",
    "load_runtime_config",
]
