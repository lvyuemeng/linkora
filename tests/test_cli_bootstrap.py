"""Integration-oriented tests for CLI bootstrap composition."""

from pathlib import Path

import linkora.cli as cli_main


def test_parse_early_args_reads_context_and_workspace():
    args = cli_main._parse_early_args(["--context", "--workspace", "research"])
    assert args.context is True
    assert args.workspace == "research"


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


def test_design_context_renders_config_candidates_from_setup(monkeypatch):
    import linkora.cli.setup as setup

    candidates = [
        Path("candidate-a.yml"),
        Path("candidate-b.yaml"),
    ]
    monkeypatch.setattr(setup, "get_config_candidates", lambda: candidates)

    context = cli_main._design_context()
    assert f"1) {candidates[0]}" in context
    assert f"2) {candidates[1]}" in context
