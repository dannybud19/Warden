from pathlib import Path

import pytest

from app.core.settings import Settings


def _settings(env_file: Path | None = None, **kwargs: object) -> Settings:
    return Settings(_env_file=env_file, **kwargs)  # type: ignore[call-arg]


def test_default_mode_is_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_MODE_MESSAGE_CHECKER", raising=False)
    assert _settings().agent_mode("message_checker") == "stub"


def test_per_agent_env_var_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENT_MODE_MESSAGE_CHECKER", "real")
    settings = _settings()
    assert settings.agent_mode("message_checker") == "real"
    assert settings.agent_mode("companies_house") == "stub"


def test_per_agent_mode_in_dotenv_file_is_honoured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENT_MODE_COMPANIES_HOUSE", raising=False)
    env = tmp_path / ".env"
    env.write_text("AGENT_MODE_COMPANIES_HOUSE=real\nDEFAULT_AGENT_MODE=stub\n")
    settings = _settings(env)
    assert settings.agent_mode("companies_house") == "real"
    assert settings.agent_mode("message_checker") == "stub"


def test_default_agent_mode_real_applies_to_all(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENT_MODE_VIDEO_ANALYSIS", raising=False)
    assert _settings(default_agent_mode="real").agent_mode("video_analysis") == "real"


def test_fixtures_dir_points_at_the_repo_fixtures() -> None:
    assert (_settings().fixtures_dir / "reports").is_dir()
