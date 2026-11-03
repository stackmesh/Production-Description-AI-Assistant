"""Generator orchestration without a live model call."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from src.config import load_settings
from src.exceptions import InvalidProductInputError, OutputValidationError, RateLimitError
from src.generator import ProductDescriptionGenerator, generate_product_description
from src.llm_client import LLMClient, translate_api_error
from src.schemas import ProductInput
from tests.support import build_card, load_example


class _RecordingClient(LLMClient):
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.seen: ProductInput | None = None
        self.messages: list[dict[str, str]] | None = None

    @property
    def model(self) -> str:
        return "fake-model"

    def generate_product_card(self, product: ProductInput, messages: list[dict[str, str]] | None = None) -> dict:
        self.seen = product
        self.messages = list(messages) if messages is not None else None
        return self.payload


def test_generate_validates_input_before_generation() -> None:
    with pytest.raises(InvalidProductInputError):
        ProductDescriptionGenerator().generate('{"name":')


def test_generate_without_a_client_requires_configuration() -> None:
    generator = ProductDescriptionGenerator()
    with pytest.raises(RuntimeError, match="generate_product_description"):
        generator.generate(load_example("pressure_gauge.json"))


def test_generate_validates_a_client_payload() -> None:
    product_payload = load_example("pressure_gauge.json")
    product = ProductInput.model_validate(product_payload)
    client = _RecordingClient(build_card(product))
    card = ProductDescriptionGenerator(client).generate(product_payload)
    assert client.seen is not None
    assert client.seen.name == "DM 02 Pressure Gauge"
    assert client.messages is not None
    assert client.messages[0]["role"] == "system"
    assert "DM 02 Pressure Gauge" in client.messages[1]["content"]
    assert card.seo_title.startswith("DM 02")


def test_generate_rejects_an_invented_client_payload() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["key_features"][0]["value"] = "0–4 MPa"
    client = _RecordingClient(payload)
    with pytest.raises(OutputValidationError, match="0–4 MPa"):
        ProductDescriptionGenerator(client).generate(product)


def test_rate_limit_is_distinct_from_transport_failures() -> None:
    class RateLimitError(Exception):
        status_code = 429

    class APITimeoutError(Exception):
        pass

    class AuthenticationError(Exception):
        status_code = 401

    limited = translate_api_error(RateLimitError("slow down"))
    assert type(limited).__name__ == "RateLimitError"
    assert limited.status_code == 429

    timeout = translate_api_error(APITimeoutError("timed out"))
    assert type(timeout).__name__ == "APICommunicationError"

    rejected = translate_api_error(AuthenticationError("bad key"))
    assert "OPENAI_API_KEY" in str(rejected)
    assert rejected.status_code == 401


class _SequencedClient(LLMClient):
    def __init__(self, payloads: list[dict]) -> None:
        self.payloads = list(payloads)
        self.calls: list[str] = []

    @property
    def model(self) -> str:
        return "fake-model"

    def generate_product_card(self, product: ProductInput, messages: list[dict[str, str]] | None = None) -> dict:
        self.calls.append("generate")
        return self.payloads.pop(0)

    def complete(self, messages: list[dict[str, str]]) -> dict:
        self.calls.append("revise")
        joined = "\n".join(message["content"] for message in messages)
        assert "original product input" in joined
        assert "Do not add fabricated information" in joined
        return self.payloads.pop(0)


def test_generate_product_description_returns_the_validated_card() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    client = _SequencedClient([build_card(product)])
    card = generate_product_description(product, client=client)
    assert card.name == product.name
    assert client.calls == ["generate"]
    assert card.warnings == []


def test_seo_title_is_revised_once_when_it_is_too_long() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    too_long = build_card(product)
    too_long["seo_title"] = "DM 02 " + ("Gauge " * 12)
    assert len(too_long["seo_title"]) > 70
    fixed = build_card(product)
    client = _SequencedClient([too_long, fixed])
    card = ProductDescriptionGenerator(client).generate(product)
    assert client.calls == ["generate", "revise"]
    assert len(card.seo_title) <= 70
    assert card.warnings == []


def test_seo_description_outside_the_range_is_preserved_with_a_warning() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    short = build_card(product)
    short["seo_description"] = "A" * 500
    assert len(short["seo_description"]) < 800
    client = _SequencedClient([short, dict(short)])
    card = ProductDescriptionGenerator(client).generate(product)
    assert client.calls == ["generate", "revise"]
    assert card.seo_description == short["seo_description"]
    assert any("800" in warning and "kept after one revision" in warning for warning in card.warnings)


def test_invented_values_are_not_sent_for_a_length_revision() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["seo_description"] = "Short draft."
    payload["sales_pitch"] = "Mention the 0–2.5 MPa range to buyers."
    client = _SequencedClient([payload])
    with pytest.raises(OutputValidationError, match="0-2.5 mpa"):
        ProductDescriptionGenerator(client).generate(product)
    assert client.calls == ["generate"]


def test_invalid_structured_output_is_rejected_without_a_fallback() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    client = _SequencedClient([{"name": product.name}])
    with pytest.raises(OutputValidationError, match="seo_title"):
        generate_product_description(product, client=client)
    assert client.calls == ["generate"]


def test_stub_without_revision_keeps_a_short_description_and_warns() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["seo_description"] = "A" * 500
    client = _RecordingClient(payload)
    card = ProductDescriptionGenerator(client).generate(product)
    assert card.seo_description == "A" * 500
    assert any("no facts would be added" in warning for warning in card.warnings)


def test_configured_client_revises_once_through_the_sdk() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    short = build_card(product)
    short["seo_description"] = "A" * 500
    fixed = build_card(product)

    class _Responses:
        def __init__(self) -> None:
            self.calls: list[dict] = []
            self.payloads = [short, fixed]

        def create(self, **kwargs: object) -> SimpleNamespace:
            self.calls.append(kwargs)
            body = self.payloads.pop(0)
            return SimpleNamespace(
                status="completed",
                error=None,
                output_text=json.dumps(body),
                output=[],
            )

    class _SDK:
        def __init__(self) -> None:
            self.responses = _Responses()

    sdk = _SDK()
    settings = load_settings({"OPENAI_API_KEY": "sk-test-key", "OPENAI_MODEL": "gpt-6-astra"})
    card = generate_product_description(product, client=LLMClient(settings, sdk=sdk))
    assert len(sdk.responses.calls) == 2
    assert "sk-test-key" not in json.dumps(sdk.responses.calls)
    first = "\n".join(item["content"] for item in sdk.responses.calls[0]["input"])
    second = "\n".join(item["content"] for item in sdk.responses.calls[1]["input"])
    assert "Do not invent technical specifications" in first
    assert "0–1.6 MPa" in first
    assert "Do not add fabricated information" in second
    assert len(card.seo_description) >= 800
    assert card.warnings == []


def test_rate_limit_is_not_turned_into_a_card() -> None:
    class _LimitedClient(LLMClient):
        def __init__(self) -> None:
            """Skip the real client constructor; this double never calls the API."""

        @property
        def model(self) -> str:
            return "fake-model"

        def generate_product_card(self, product: ProductInput, messages: list[dict[str, str]] | None = None) -> dict:
            raise RateLimitError(
                "The OpenAI API rate limit was exceeded. Wait and retry the request.",
                status_code=429,
            )

    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    with pytest.raises(RateLimitError):
        ProductDescriptionGenerator(_LimitedClient()).generate(product)
