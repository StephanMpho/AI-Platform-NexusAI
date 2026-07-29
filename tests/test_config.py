from __future__ import annotations

import pytest

from nexus.config import Settings


def test_production_refuses_dev_bypass() -> None:
    settings = Settings(env="production", auth={"dev_bypass": True})  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="DEV_BYPASS"):
        settings.validate_for_env()


def test_production_refuses_default_secret() -> None:
    settings = Settings(env="production", auth={"dev_bypass": False})  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        settings.validate_for_env()


def test_mock_is_always_available() -> None:
    assert Settings().providers.configured() == ["mock"]
