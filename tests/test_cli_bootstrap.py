"""Integration-oriented tests for CLI bootstrap composition."""

import linkora.cli as cli_main


class _FakeWorkspace:
    def __init__(self, name: str):
        self.name = name


class _FakeStore:
    def __init__(self, default_name: str | None, existing: list[str] | None = None):
        self._default_name = default_name
        self._existing = existing or []
        self.set_default_calls: list[str] = []
        self.create_calls: list[str] = []

    def get_default(self):
        if self._default_name is None:
            return None
        return _FakeWorkspace(self._default_name)

    def list_workspaces(self):
        return [_FakeWorkspace(name) for name in self._existing]

    def set_default(self, name: str) -> None:
        self.set_default_calls.append(name)
        self._default_name = name

    def create(self, name: str, description: str = ""):
        self.create_calls.append(name)
        self._default_name = name
        return _FakeWorkspace(name)


def test_parse_early_args_reads_context_and_workspace():
    args = cli_main._parse_early_args(["--context", "--workspace", "research"])
    assert args.context is True
    assert args.workspace == "research"


def test_resolve_active_workspace_precedence_cli_env_default(monkeypatch):
    store = _FakeStore(default_name="default")

    monkeypatch.setenv("LINKORA_WORKSPACE", "env-ws")
    assert cli_main._resolve_active_workspace_name(store, "cli-ws") == "cli-ws"

    assert cli_main._resolve_active_workspace_name(store, None) == "env-ws"

    monkeypatch.delenv("LINKORA_WORKSPACE")
    assert cli_main._resolve_active_workspace_name(store, None) == "default"


def test_ensure_default_workspace_creates_one_when_missing():
    store = _FakeStore(default_name=None, existing=[])
    resolved = cli_main._ensure_default_workspace(store)

    assert resolved == "default"
    assert store.create_calls == ["default"]
    assert store.set_default_calls == ["default"]


def test_build_parser_registers_core_commands():
    parser = cli_main._build_parser()
    args = parser.parse_args(["add", "paper.pdf", "--workspace", "ws-1"])

    assert args.command == "add"
    assert args.targets == ["paper.pdf"]
    assert args.workspace == "ws-1"


def test_design_context_mentions_pipeline_and_config_resolution():
    context = cli_main._design_context()

    assert (
        "parse target -> resolve source -> fetch artifacts -> ingest pipeline"
        in context
    )
    assert "resolve doc type/schema -> parse schema fields -> filter/render" in context
    assert "If multiple candidates exist, linkora logs a warning" in context
    assert (
        "Config is optional; built-in defaults are used when no file exists" in context
    )
