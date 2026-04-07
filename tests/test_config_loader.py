"""Integration tests for config resolution behavior."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from linkora.cli.setup import load_runtime_config


def test_config_loader_prefers_first_candidate_and_warns_on_multiple(
    tmp_path, monkeypatch
):
    first = tmp_path / "a.yml"
    second = tmp_path / "b.yml"

    first.write_text("llm:\n  model: model-a\n", encoding="utf-8")
    second.write_text("llm:\n  model: model-b\n", encoding="utf-8")

    monkeypatch.setattr(
        "linkora.cli.setup.get_config_candidates",
        lambda: [first, second],
    )

    result = load_runtime_config(tmp_path)
    config, active = result.config, result.active_path

    assert active == first
    assert config.llm.model == "model-a"
    warning_text = "\n".join(result.warnings)
    assert "Multiple config files found" in warning_text
    assert str(first) in warning_text
    assert str(second) in warning_text


def test_config_loader_uses_defaults_when_no_file(monkeypatch):
    monkeypatch.setattr("linkora.cli.setup.get_config_candidates", lambda: [])
    result = load_runtime_config(Path("/data/root"))
    config, active = result.config, result.active_path

    assert active is None
    assert config.index.top_k == 20
    assert config.llm.backend == "openai-compat"
    assert config.topics.model_dir == str(
        (Path("/data/root") / "topic_model").resolve()
    )


def test_config_loader_rejects_legacy_logging_section(tmp_path, monkeypatch):
    cfg = tmp_path / "legacy.yml"
    cfg.write_text("logging:\n  level: INFO\n", encoding="utf-8")

    monkeypatch.setattr("linkora.cli.setup.get_config_candidates", lambda: [cfg])

    with pytest.raises(ValidationError):
        load_runtime_config(tmp_path)


def test_config_loader_resolves_topics_model_dir_relative_to_data_root(
    tmp_path, monkeypatch
):
    cfg = tmp_path / "cfg.yml"
    cfg.write_text("topics:\n  model_dir: topic_model\n", encoding="utf-8")

    monkeypatch.setattr("linkora.cli.setup.get_config_candidates", lambda: [cfg])
    result = load_runtime_config(tmp_path / "root")
    config, active = result.config, result.active_path

    assert active == cfg
    assert config.topics.model_dir == str((tmp_path / "root" / "topic_model").resolve())


def test_config_loader_resolves_env_from_dotenv_then_os_env(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.yml"
    env_file = tmp_path / ".env"
    cfg.write_text("llm:\n  api_key: ${DEMO_KEY:-fallback}\n", encoding="utf-8")
    env_file.write_text("DEMO_KEY=from_dotenv\n", encoding="utf-8")

    monkeypatch.setattr("linkora.cli.setup.get_config_candidates", lambda: [cfg])
    monkeypatch.setenv("DEMO_KEY", "from_os")

    config = load_runtime_config(tmp_path).config
    assert config.llm.api_key == "from_dotenv"
