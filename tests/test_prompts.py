"""Prompt content stays aligned with the product-card contract."""

from __future__ import annotations

from src.prompts import SYSTEM_PROMPT, build_messages, build_revision_messages, build_user_prompt
from src.validators import parse_product_input
from tests.support import build_card, load_example


def test_system_prompt_states_the_contract() -> None:
    assert "Do not invent technical specifications" in SYSTEM_PROMPT
    assert "70" in SYSTEM_PROMPT
    assert "800" in SYSTEM_PROMPT
    assert "1200" in SYSTEM_PROMPT
    assert "content manager" in SYSTEM_PROMPT
    for restriction in (
        "Use only technical information explicitly provided in the input.",
        "Never infer missing technical specifications from the product name or manufacturer.",
        "Never use general industry knowledge to fill missing technical values.",
        "Never invent certifications, compliance claims, protection ratings",
        "similar products usually have it",
        "explicitly report it as missing",
        "Preserve numerical values, measurement units, and technical terminology exactly",
        "Do not modify or convert technical values unless explicitly requested.",
        "Do not turn assumptions into factual statements.",
        "suitable for a particular environment",
        "Russian",
        "3 to 5",
    ):
        assert restriction in SYSTEM_PROMPT


def test_user_prompt_contains_source_facts_and_gaps() -> None:
    product = parse_product_input(load_example("pressure_gauge_blank_spec.json"))
    prompt = build_user_prompt(product)
    assert "DM 02 Pressure Gauge" in prompt
    assert "Manotom" in prompt
    assert "0–1.6 MPa" in prompt
    assert "accuracy_class" in prompt
    assert "housing_diameter" in prompt
    assert "1.5" not in prompt


def test_messages_use_system_and_user_roles() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    messages = build_messages(product)
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "G1/2" in messages[1]["content"]


def test_revision_prompt_repeats_the_source_and_the_restrictions() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    draft = build_card(product)
    draft["seo_title"] = "T" * 80
    messages = build_revision_messages(
        product,
        draft,
        ["SEO title must be at most 70 characters (got 80)."],
    )
    assert [message["role"] for message in messages] == ["system", "user"]
    assert messages[0]["content"] == SYSTEM_PROMPT
    assert "0–1.6 MPa" in messages[1]["content"]
    assert "original product input" in messages[1]["content"]
    assert "factual restrictions" in messages[1]["content"]
    assert "Do not add fabricated information" in messages[1]["content"]
    assert "got 80" in messages[1]["content"]
    assert "T" * 80 in messages[1]["content"]
