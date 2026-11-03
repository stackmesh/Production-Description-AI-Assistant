"""Configuration loading."""

from __future__ import annotations

import logging

import pytest
from pydantic import ValidationError

from src.config import Settings, load_settings
from src.exceptions import MissingAPIConfigurationError


def test_load_settings_reads_required_values() -> None:
    settings = load_settings(
        {"OPENAI_API_KEY": "sk-test-key", "OPENAI_MODEL": "gpt-6-astra"}
    )
    assert settings.api_key == "sk-test-key"
    assert settings.openai_model == "gpt-6-astra"


def test_settings_repr_hides_the_api_key() -> None:
    settings = load_settings(
        {"OPENAI_API_KEY": "sk-test-key", "OPENAI_MODEL": "gpt-6-astra"}
    )
    assert "sk-test-key" not in repr(settings)
    assert "gpt-6-astra" in repr(settings)


def test_settings_are_frozen() -> None:
    settings = load_settings(
        {"OPENAI_API_KEY": "sk-test-key", "OPENAI_MODEL": "gpt-6-astra"}
    )
    with pytest.raises(ValidationError):
        settings.openai_model = "other-model"  # type: ignore[misc]


def test_missing_variables_are_named() -> None:
    with pytest.raises(MissingAPIConfigurationError) as caught:
        load_settings({})
    message = str(caught.value)
    assert "OPENAI_API_KEY" in message
    assert "OPENAI_MODEL" in message


def test_placeholder_api_key_is_rejected() -> None:
    with pytest.raises(MissingAPIConfigurationError, match="placeholder"):
        load_settings(
            {"OPENAI_API_KEY": "your-api-key-here", "OPENAI_MODEL": "gpt-6-astra"}
        )


def test_blank_values_are_rejected() -> None:
    with pytest.raises(MissingAPIConfigurationError) as caught:
        load_settings({"OPENAI_API_KEY": "   ", "OPENAI_MODEL": "  "})
    message = str(caught.value)
    assert "OPENAI_API_KEY" in message
    assert "OPENAI_MODEL" in message


def test_model_id_must_not_contain_spaces() -> None:
    with pytest.raises(MissingAPIConfigurationError, match="OPENAI_MODEL"):
        load_settings({"OPENAI_API_KEY": "sk-test-key", "OPENAI_MODEL": "gpt 6"})


def test_fine_tuned_model_id_is_accepted() -> None:
    settings = load_settings(
        {
            "OPENAI_API_KEY": "sk-test-key",
            "OPENAI_MODEL": "ft:gpt-6-astra:org:product-card:abc123",
        }
    )
    assert settings.openai_model.startswith("ft:")


def test_logs_include_the_model_and_exclude_the_key(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    load_settings({"OPENAI_API_KEY": "sk-secret-value", "OPENAI_MODEL": "gpt-6-astra"})
    assert "gpt-6-astra" in caplog.text
    assert "sk-secret-value" not in caplog.text


def test_settings_model_rejects_a_missing_key() -> None:
    with pytest.raises(ValidationError):
        Settings(openai_model="gpt-6-astra")  # type: ignore[call-arg]
