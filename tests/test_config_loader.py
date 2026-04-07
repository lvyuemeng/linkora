"""Integration tests for config resolution behavior."""

import logging

import pytest
from pydantic import ValidationError

from linkora.setup import load_app_config


def test_config_loader_prefers_first_candidate_and_warns_on_multiple(
    tmp_path, monkeypatch, caplog
):
    first = tmp_path / "a.yml"
    second = tmp_path / "b.yml"

    first.write_text("llm:\n  model: model-a\n", encoding="utf-8")
    second.write_text("llm:\n  model: model-b\n", encoding="utf-8")

    monkeypatch.setattr(
        "linkora.setup.get_config_candidates",
        lambda: [first, second],
    )

    with caplog.at_level(logging.WARNING):
        config, active = load_app_config()

    assert active == first
    assert config.llm.model == "model-a"
    assert "Multiple config files found" in caplog.text
    assert str(first) in caplog.text
    assert str(second) in caplog.text


def test_config_loader_uses_defaults_when_no_file(monkeypatch):
    monkeypatch.setattr("linkora.setup.get_config_candidates", lambda: [])

    config, active = load_app_config()

    assert active is None
    assert config.index.top_k == 20
    assert config.llm.backend == "openai-compat"


def test_config_loader_rejects_legacy_logging_section(tmp_path, monkeypatch):
    cfg = tmp_path / "legacy.yml"
    cfg.write_text("logging:\n  level: INFO\n", encoding="utf-8")

    monkeypatch.setattr("linkora.setup.get_config_candidates", lambda: [cfg])

    with pytest.raises(ValidationError):
        load_app_config()
