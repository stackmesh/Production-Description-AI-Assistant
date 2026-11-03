"""OpenAI client behavior with a fake SDK. No network and no real API key."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from src.config import load_settings
from src.exceptions import (
    APICommunicationError,
    InvalidLLMResponseError,
    RateLimitError as ApplicationRateLimitError,
)
from src.llm_client import DEFAULT_TIMEOUT_SECONDS, LLMClient
from src.schemas import ProductInput
from tests.support import load_example


def _settings():
    return load_settings({"OPENAI_API_KEY": "sk-test-key", "OPENAI_MODEL": "gpt-6-astra"})


def _product() -> ProductInput:
    return ProductInput.model_validate(load_example("pressure_gauge.json"))


class _Responses:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class _SDK:
    def __init__(self, result: object) -> None:
        self.responses = _Responses(result)


def _response(text: str, *, status: str = "completed", refusal: str | None = None, error: str | None = None):
    content = []
    if refusal:
        content.append(SimpleNamespace(type="refusal", refusal=refusal))
    if text:
        content.append(SimpleNamespace(type="output_text", text=text))
    return SimpleNamespace(
        status=status,
        error=None if error is None else SimpleNamespace(message=error),
        output_text=text,
        output=[SimpleNamespace(type="message", content=content)],
    )


def test_structured_request_uses_the_configured_model_and_hides_the_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    payload = {"name": "DM 02 Pressure Gauge", "seo_title": "DM 02"}
    sdk = _SDK(_response(json.dumps(payload)))
    client = LLMClient(_settings(), sdk=sdk)
    result = client.generate_product_card(_product())
    assert result == payload
    assert len(sdk.responses.calls) == 1
    call = sdk.responses.calls[0]
    assert call["model"] == "gpt-6-astra"
    assert call["timeout"] == DEFAULT_TIMEOUT_SECONDS
    assert call["store"] is False
    text_format = call["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["name"] == "product_card"
    assert text_format["schema"]["additionalProperties"] is False
    encoded = json.dumps(call)
    assert "sk-test-key" not in encoded
    assert "sk-test-key" not in caplog.text
    assert "gpt-6-astra" in caplog.text


def test_sdk_is_constructed_without_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str, timeout: float, max_retries: int) -> None:
            created["api_key"] = api_key
            created["timeout"] = timeout
            created["max_retries"] = max_retries
            self.responses = _Responses(_response('{"ok": true}'))

    monkeypatch.setattr("src.llm_client.OpenAI", FakeOpenAI)
    client = LLMClient(_settings())
    assert client.complete([{"role": "user", "content": "Create the card."}]) == {"ok": True}
    assert created == {
        "api_key": "sk-test-key",
        "timeout": DEFAULT_TIMEOUT_SECONDS,
        "max_retries": 0,
    }


def test_rate_limit_is_raised_once_and_the_key_is_redacted(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)

    class RateLimitError(Exception):
        status_code = 429

        def __str__(self) -> str:
            return "slow down sk-test-key"

    sdk = _SDK(RateLimitError())
    client = LLMClient(_settings(), sdk=sdk)
    with pytest.raises(ApplicationRateLimitError) as caught:
        client.complete([{"role": "user", "content": "Create the card."}])
    assert len(sdk.responses.calls) == 1
    assert "sk-test-key" not in str(caught.value)
    assert "sk-test-key" not in caplog.text


def test_authentication_failure_does_not_reveal_the_key() -> None:
    class AuthenticationError(Exception):
        status_code = 401

        def __str__(self) -> str:
            return "invalid key sk-test-key"

    client = LLMClient(_settings(), sdk=_SDK(AuthenticationError()))
    with pytest.raises(APICommunicationError, match="OPENAI_API_KEY") as caught:
        client.complete([{"role": "user", "content": "Create the card."}])
    assert caught.value.status_code == 401
    assert "sk-test-key" not in str(caught.value)


def test_connection_error_is_an_api_communication_error() -> None:
    class APITimeoutError(Exception):
        pass

    client = LLMClient(_settings(), sdk=_SDK(APITimeoutError("timed out")))
    with pytest.raises(APICommunicationError, match="APITimeoutError"):
        client.complete([{"role": "user", "content": "Create the card."}])


def test_invalid_json_is_not_replaced_with_a_card() -> None:
    client = LLMClient(_settings(), sdk=_SDK(_response("not json")))
    with pytest.raises(InvalidLLMResponseError, match="not valid JSON"):
        client.complete([{"role": "user", "content": "Create the card."}])


def test_refusal_is_not_replaced_with_a_card() -> None:
    client = LLMClient(_settings(), sdk=_SDK(_response("", refusal="Not enough source data.")))
    with pytest.raises(InvalidLLMResponseError, match="refused"):
        client.complete([{"role": "user", "content": "Create the card."}])


def test_failed_response_redacts_the_key() -> None:
    response = _response("", status="failed", error="rejected sk-test-key")
    client = LLMClient(_settings(), sdk=_SDK(response))
    with pytest.raises(InvalidLLMResponseError, match="did not complete") as caught:
        client.complete([{"role": "user", "content": "Create the card."}])
    assert "sk-test-key" not in str(caught.value)
    assert "[redacted]" in str(caught.value)


def test_json_array_is_not_a_product_card() -> None:
    client = LLMClient(_settings(), sdk=_SDK(_response("[1, 2]")))
    with pytest.raises(InvalidLLMResponseError, match="JSON object"):
        client.complete([{"role": "user", "content": "Create the card."}])
