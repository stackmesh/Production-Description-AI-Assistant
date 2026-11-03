"""Input schema, output schema, and the OpenAI structured-output schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.schemas import ProductDescription, ProductInput, openai_structured_schema
from tests.support import load_example


def test_example_product_parses() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge.json"))
    assert product.name == "DM 02 Pressure Gauge"
    assert product.manufacturer == "Manotom"
    assert product.specs["connection"] == "G1/2"
    assert product.description == "The device is designed to measure gauge pressure."
    assert product.empty_spec_fields == []


def test_blank_spec_values_are_removed_and_recorded() -> None:
    product = ProductInput.model_validate(load_example("pressure_gauge_blank_spec.json"))
    assert list(product.specs) == ["measurement_range", "connection"]
    assert product.empty_spec_fields == ["accuracy_class", "housing_diameter"]
    assert product.description is None


def test_null_spec_value_is_treated_as_missing() -> None:
    product = ProductInput.model_validate(
        {
            "name": "DM 02 Pressure Gauge",
            "manufacturer": "Manotom",
            "specs": {"accuracy_class": None, "connection": "G1/2"},
        }
    )
    assert product.specs == {"connection": "G1/2"}
    assert product.empty_spec_fields == ["accuracy_class"]


def test_additional_spec_fields_are_kept() -> None:
    product = ProductInput.model_validate(
        {
            "name": "DM 02 Pressure Gauge",
            "manufacturer": "Manotom",
            "specs": {
                "connection": "G1/2",
                "ip_rating": "IP65",
                "thread": "M20x1.5",
            },
        }
    )
    assert product.specs["ip_rating"] == "IP65"
    assert product.specs["thread"] == "M20x1.5"


def test_spec_keys_and_values_are_trimmed() -> None:
    product = ProductInput.model_validate(
        {
            "name": "  DM 02 Pressure Gauge  ",
            "manufacturer": " Manotom ",
            "specs": {" connection ": "  G1/2  "},
        }
    )
    assert product.name == "DM 02 Pressure Gauge"
    assert product.manufacturer == "Manotom"
    assert product.specs == {"connection": "G1/2"}


def test_description_is_optional() -> None:
    product = ProductInput.model_validate(
        {"name": "DM 02", "manufacturer": "Manotom", "specs": {}}
    )
    assert product.description is None
    assert product.specs == {}


def test_duplicate_spec_names_are_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicated"):
        ProductInput.model_validate(
            {
                "name": "DM 02",
                "manufacturer": "Manotom",
                "specs": {"connection": "G1/2", " connection ": "M20x1.5"},
            }
        )


def test_non_string_spec_value_is_rejected() -> None:
    with pytest.raises(ValidationError, match="must be a string"):
        ProductInput.model_validate(
            {
                "name": "DM 02",
                "manufacturer": "Manotom",
                "specs": {"accuracy_class": 1.5},
            }
        )


def test_empty_name_is_rejected() -> None:
    with pytest.raises(ValidationError, match="Product name must not be empty"):
        ProductInput.model_validate(
            {"name": "   ", "manufacturer": "Manotom", "specs": {}}
        )


def test_unknown_top_level_field_is_rejected() -> None:
    with pytest.raises(ValidationError, match="sku"):
        ProductInput.model_validate(
            {
                "name": "DM 02",
                "manufacturer": "Manotom",
                "specs": {},
                "sku": "123",
            }
        )


def test_private_empty_fields_are_not_part_of_the_schema() -> None:
    assert "_empty_spec_fields" not in ProductInput.model_fields
    product = ProductInput.model_validate(
        {
            "name": "DM 02",
            "manufacturer": "Manotom",
            "specs": {"accuracy_class": ""},
        }
    )
    dumped = product.model_dump()
    assert "empty_spec_fields" not in dumped
    assert dumped["specs"] == {}


def test_seo_title_limit() -> None:
    payload = _card()
    payload["seo_title"] = "A" * 70
    ProductDescription.model_validate(payload)
    payload["seo_title"] = "A" * 71
    with pytest.raises(ValidationError, match="70"):
        ProductDescription.model_validate(payload)


def test_seo_description_limits() -> None:
    payload = _card()
    payload["seo_description"] = "A" * 799
    with pytest.raises(ValidationError, match="800"):
        ProductDescription.model_validate(payload)
    payload["seo_description"] = "A" * 800
    ProductDescription.model_validate(payload)
    payload["seo_description"] = "A" * 1200
    ProductDescription.model_validate(payload)
    payload["seo_description"] = "A" * 1201
    with pytest.raises(ValidationError, match="1200"):
        ProductDescription.model_validate(payload)


def test_search_query_count_and_duplicates() -> None:
    payload = _card()
    payload["search_queries"] = ["one", "two"]
    with pytest.raises(ValidationError, match="3 to 5"):
        ProductDescription.model_validate(payload)
    payload["search_queries"] = ["one", "two", "three", "four", "five", "six"]
    with pytest.raises(ValidationError, match="3 to 5"):
        ProductDescription.model_validate(payload)
    payload["search_queries"] = ["Gauge", "gauge", "manotom"]
    with pytest.raises(ValidationError, match="distinct"):
        ProductDescription.model_validate(payload)


def test_missing_fields_require_clarification() -> None:
    payload = _card()
    payload["missing_fields"] = ["accuracy_class"]
    payload["clarification_required"] = False
    with pytest.raises(ValidationError, match="clarification_required"):
        ProductDescription.model_validate(payload)


def test_feature_fields_are_required() -> None:
    payload = _card()
    payload["key_features"] = [{"name": "Connection", "value": "G1/2"}]
    with pytest.raises(ValidationError, match="explanation"):
        ProductDescription.model_validate(payload)


def test_openai_schema_is_strict_and_keeps_the_card_fields() -> None:
    schema = openai_structured_schema()
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert {
        "name",
        "manufacturer",
        "seo_title",
        "seo_description",
        "key_features",
        "search_queries",
        "sales_pitch",
        "missing_fields",
        "clarification_required",
        "warnings",
    } <= set(schema["properties"])
    feature = schema["$defs"]["KeyFeature"]
    assert feature["additionalProperties"] is False
    assert set(feature["required"]) == {"name", "value", "explanation"}
    _assert_no_length_keywords(schema)


def _assert_no_length_keywords(node: object) -> None:
    if isinstance(node, dict):
        assert "minLength" not in node
        assert "maxLength" not in node
        assert "minItems" not in node
        assert "maxItems" not in node
        for value in node.values():
            _assert_no_length_keywords(value)
    elif isinstance(node, list):
        for item in node:
            _assert_no_length_keywords(item)


def _card() -> dict:
    return {
        "name": "DM 02 Pressure Gauge",
        "manufacturer": "Manotom",
        "seo_title": "DM 02 Pressure Gauge | Manotom",
        "seo_description": "A" * 800,
        "key_features": [
            {
                "name": "Connection",
                "value": "G1/2",
                "explanation": "Process connection supplied with the product.",
            }
        ],
        "search_queries": ["dm 02", "manotom gauge", "g1/2 pressure gauge"],
        "sales_pitch": "Lead with the supplied connection.",
        "missing_fields": [],
        "clarification_required": False,
        "warnings": [],
    }
