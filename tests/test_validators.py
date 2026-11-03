"""JSON parsing and the rule that specifications are never invented."""

from __future__ import annotations

import json

import pytest

from src.exceptions import (
    InvalidLLMResponseError,
    InvalidProductInputError,
    OutputValidationError,
)
from src.schemas import ProductDescription, ProductInput
from src.validators import (
    find_unsupported_technical_values,
    parse_product_input,
    validate_generated_output,
)
from tests.support import build_card, load_example, pad_description


def test_json_string_parses() -> None:
    raw = json.dumps(load_example("pressure_gauge.json"))
    product = parse_product_input(raw)
    assert product.name == "DM 02 Pressure Gauge"
    assert product.specs["measurement_range"] == "0–1.6 MPa"


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(InvalidProductInputError, match="not valid JSON") as caught:
        parse_product_input('{"name": ')
    assert caught.value.errors == ()


def test_json_array_is_rejected() -> None:
    with pytest.raises(InvalidProductInputError, match="JSON object"):
        parse_product_input("[1, 2]")


def test_specs_are_required_and_must_be_an_object() -> None:
    with pytest.raises(InvalidProductInputError, match="Specifications are required"):
        parse_product_input({"name": "DM 02", "manufacturer": "Manotom"})
    with pytest.raises(InvalidProductInputError, match="object"):
        parse_product_input(
            {"name": "DM 02", "manufacturer": "Manotom", "specs": ["G1/2"]}
        )


def test_wrong_python_type_is_rejected() -> None:
    with pytest.raises(InvalidProductInputError, match="binary data"):
        parse_product_input(b"{}")  # type: ignore[arg-type]
    with pytest.raises(InvalidProductInputError, match="a number"):
        parse_product_input(12)  # type: ignore[arg-type]


def test_missing_manufacturer_has_a_field_message() -> None:
    with pytest.raises(InvalidProductInputError) as caught:
        parse_product_input({"name": "DM 02", "specs": {}})
    assert any("manufacturer" in error and "required" in error for error in caught.value.errors)


def test_numeric_spec_has_a_field_message() -> None:
    with pytest.raises(InvalidProductInputError, match="accuracy_class") as caught:
        parse_product_input(
            {
                "name": "DM 02",
                "manufacturer": "Manotom",
                "specs": {"accuracy_class": 1.5},
            }
        )
    assert any("string" in error for error in caught.value.errors)


def test_existing_model_is_returned() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    assert parse_product_input(product) is product


def test_generated_card_preserves_identity_and_specs() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    card = validate_generated_output(build_card(product), product)
    assert card.name == product.name
    assert card.manufacturer == product.manufacturer
    assert [feature.value for feature in card.key_features] == [
        "0–1.6 MPa",
        "1.5",
        "G1/2",
        "100 mm",
    ]


def test_dash_variant_of_a_spec_value_is_the_same_fact() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["key_features"][0]["value"] = "0-1.6 MPa"
    card = validate_generated_output(payload, product)
    assert card.key_features[0].value == "0-1.6 MPa"


def test_invented_feature_value_is_rejected() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["key_features"][0]["value"] = "0–2.5 MPa"
    with pytest.raises(OutputValidationError, match="0–2.5 MPa"):
        validate_generated_output(payload, product)


def test_a_shorter_measurement_is_not_hidden_inside_a_longer_one() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    for invented in ("10 mm", "0 mm"):
        payload = build_card(product)
        payload["sales_pitch"] = f"Highlight the {invented} face."
        with pytest.raises(OutputValidationError, match=rf"'{invented}'"):
            validate_generated_output(payload, product)


def test_ordinary_words_are_not_read_as_measurements() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["sales_pitch"] = "Offer 2 mounting styles and answer 3 buyer questions."
    card = validate_generated_output(payload, product)
    assert "mounting" in card.sales_pitch


def test_a_supplied_description_cannot_be_marked_missing() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["missing_fields"] = ["description"]
    payload["clarification_required"] = True
    with pytest.raises(OutputValidationError, match="description"):
        validate_generated_output(payload, product)


def test_invented_measurement_in_prose_is_rejected() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["sales_pitch"] = "Mention the 0–2.5 MPa range to buyers."
    with pytest.raises(OutputValidationError, match="0-2.5 mpa"):
        validate_generated_output(payload, product)


def test_changed_manufacturer_is_rejected() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["manufacturer"] = "Other Maker"
    with pytest.raises(OutputValidationError, match="manufacturer"):
        validate_generated_output(payload, product)


def test_empty_source_fields_must_be_reported() -> None:
    product = parse_product_input(load_example("pressure_gauge_blank_spec.json"))
    payload = build_card(product)
    payload["key_features"] = [
        item
        for item in payload["key_features"]
        if item["value"] in set(product.specs.values())
    ]
    payload["missing_fields"] = []
    payload["clarification_required"] = False
    with pytest.raises(OutputValidationError, match="accuracy_class") as caught:
        validate_generated_output(payload, product)
    assert any("housing_diameter" in error for error in caught.value.errors)


def test_provided_spec_cannot_be_listed_as_missing() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["missing_fields"] = ["connection"]
    payload["clarification_required"] = True
    with pytest.raises(OutputValidationError, match="connection"):
        validate_generated_output(payload, product)


def test_card_without_specs_cannot_add_features() -> None:
    product = ProductInput.model_validate(
        {
            "name": "DM 02 Pressure Gauge",
            "manufacturer": "Manotom",
            "specs": {},
            "description": "The device is designed to measure gauge pressure.",
        }
    )
    payload = build_card(product)
    payload["key_features"] = []
    payload["seo_description"] = pad_description(
        "DM 02 Pressure Gauge by Manotom. The device is designed to measure gauge pressure."
    )
    payload["sales_pitch"] = "Ask the supplier for the measurement range before publishing."
    payload["search_queries"] = [
        "DM 02 pressure gauge",
        "Manotom pressure gauge",
        "gauge pressure instrument",
    ]
    card = validate_generated_output(payload, product)
    assert card.key_features == []

    payload["key_features"] = [
        {
            "name": "Connection",
            "value": "G1/2",
            "explanation": "Added without a source specification.",
        }
    ]
    with pytest.raises(OutputValidationError, match="no specifications"):
        validate_generated_output(payload, product)


def test_model_refusal_is_an_llm_response_error() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    with pytest.raises(InvalidLLMResponseError, match="refused"):
        validate_generated_output({"refusal": "Not enough data."}, product)


def test_invalid_model_json_is_an_llm_response_error() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    with pytest.raises(InvalidLLMResponseError, match="not valid JSON"):
        validate_generated_output("{", product)


def test_schema_mismatch_is_an_output_validation_error() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    with pytest.raises(OutputValidationError, match="seo_title"):
        validate_generated_output({"name": product.name}, product)


def test_seo_title_length_is_rejected() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["seo_title"] = "A" * 71
    with pytest.raises(OutputValidationError, match="70") as caught:
        validate_generated_output(payload, product)
    assert caught.value.errors


def test_seo_description_length_is_rejected() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["seo_description"] = "A" * 799
    with pytest.raises(OutputValidationError, match="800"):
        validate_generated_output(payload, product)
    payload["seo_description"] = "A" * 1201
    with pytest.raises(OutputValidationError, match="1200"):
        validate_generated_output(payload, product)


def test_duplicate_features_are_rejected() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    payload = build_card(product)
    payload["key_features"].append(dict(payload["key_features"][0]))
    with pytest.raises(OutputValidationError, match="duplicates another feature"):
        validate_generated_output(payload, product)


def test_unsupported_measurement_is_flagged_and_a_copied_one_is_not() -> None:
    product = parse_product_input(load_example("pressure_gauge.json"))
    assert find_unsupported_technical_values("Range 0–1.6 MPa and thread G1/2.", product) == []
    assert find_unsupported_technical_values("Rated IP65.", product) == ["ip65"]


def test_fact_check_does_not_prove_the_description_is_correct() -> None:
    """Unitless claims and certifications are outside the measurement heuristic."""
    product = parse_product_input(load_example("pressure_gauge.json"))
    text = "Certified for explosive atmospheres and guaranteed for 10 years."
    assert find_unsupported_technical_values(text, product) == []
    payload = build_card(product)
    payload["sales_pitch"] = text
    card = validate_generated_output(payload, product)
    assert isinstance(card, ProductDescription)
