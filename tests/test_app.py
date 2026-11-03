"""Presentation helpers for the Streamlit page. The UI itself is not started."""

from __future__ import annotations

import json

from app import (
    append_result,
    check_product_input,
    collect_specification_rows,
    manual_product_payload,
    render_json,
    render_markdown,
)
from src.schemas import ProductDescription
from tests.support import build_card, load_example


def test_valid_example_json_is_ready_to_generate() -> None:
    raw = json.dumps(load_example("pressure_gauge.json"))
    check = check_product_input(raw)
    assert check.valid
    assert check.product is not None
    assert check.product.name == "DM 02 Pressure Gauge"
    assert check.product.specs["connection"] == "G1/2"


def test_invalid_json_syntax_is_explained() -> None:
    check = check_product_input('{"name": ')
    assert not check.valid
    assert check.heading == "The JSON syntax is invalid."
    assert any("not valid JSON" in detail for detail in check.details)


def test_json_array_is_rejected_as_the_wrong_shape() -> None:
    check = check_product_input("[1, 2]")
    assert check.heading == "The JSON must be an object."


def test_missing_manufacturer_is_a_required_field_error() -> None:
    check = check_product_input({"name": "DM 02", "specs": {}})
    assert not check.valid
    assert check.heading == "A required field is missing."
    assert any("manufacturer" in detail and "required" in detail for detail in check.details)


def test_empty_product_name_is_named() -> None:
    check = check_product_input(
        {"name": "   ", "manufacturer": "Manotom", "specs": {}}
    )
    assert check.heading == "The product name is empty."


def test_empty_manufacturer_is_named() -> None:
    check = check_product_input(
        {"name": "DM 02", "manufacturer": "  ", "specs": {}}
    )
    assert check.heading == "The manufacturer is empty."


def test_numeric_specification_is_a_type_error() -> None:
    check = check_product_input(
        {
            "name": "DM 02",
            "manufacturer": "Manotom",
            "specs": {"accuracy_class": 1.5},
        }
    )
    assert check.heading == "A field has the wrong type."
    assert any("accuracy_class" in detail for detail in check.details)


def test_blank_specifications_stay_visible_as_missing() -> None:
    check = check_product_input(load_example("pressure_gauge_blank_spec.json"))
    assert check.product is not None
    assert check.product.empty_spec_fields == ["accuracy_class", "housing_diameter"]


def test_duplicate_specification_rows_block_the_form() -> None:
    specs, problems = collect_specification_rows(
        [("connection", "G1/2"), (" connection ", "M20x1.5"), ("", ""), ("", "orphan")]
    )
    assert specs == {"connection": "G1/2"}
    assert any("more than once" in problem for problem in problems)
    assert any("without a name" in problem for problem in problems)
    payload, payload_problems = manual_product_payload(
        "DM 02",
        "Manotom",
        [("connection", "G1/2"), ("connection", "M20x1.5")],
        "",
    )
    assert payload is None
    assert payload_problems


def test_manual_payload_uses_the_same_shape_as_json() -> None:
    payload, problems = manual_product_payload(
        " DM 02 ",
        " Manotom ",
        [("measurement_range", "0–1.6 MPa"), ("accuracy_class", " ")],
        "  ",
    )
    assert problems == ()
    assert payload is not None
    check = check_product_input(payload)
    assert check.product is not None
    assert check.product.name == "DM 02"
    assert check.product.empty_spec_fields == ["accuracy_class"]
    assert check.product.description is None


def test_exports_keep_warnings_and_the_output_fields() -> None:
    product = check_product_input(load_example("pressure_gauge.json")).product
    assert product is not None
    card = ProductDescription.model_validate(build_card(product)).model_copy(
        update={
            "missing_fields": ["accuracy_class"],
            "clarification_required": True,
            "warnings": [
                "SEO description is outside the required range. "
                "The draft was kept after one revision so that no facts would be added."
            ],
        }
    )
    document = render_markdown(card)
    assert "# DM 02 Pressure Gauge" in document
    assert "Internal note for the content manager" in document
    assert "accuracy_class" in document
    assert "Clarification required: Yes" in document
    assert "kept after one revision" in document
    assert "Within the limit." in document
    exported = json.loads(render_json(card))
    assert set(exported) == {
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
    }
    assert exported["warnings"][0].startswith("SEO description")
    assert exported["key_features"][0]["value"] == "0–1.6 MPa"


def test_markdown_reports_an_out_of_range_description() -> None:
    product = check_product_input(load_example("pressure_gauge.json")).product
    assert product is not None
    payload = build_card(product)
    payload["seo_title"] = "T" * 80
    payload["seo_description"] = "A" * 500
    card = ProductDescription.model_validate(payload, context={"preserve_seo_length": True})
    document = render_markdown(card)
    assert "Over the limit." in document
    assert "Outside the required range." in document
    assert "500" in document


def test_results_stay_separate() -> None:
    product = check_product_input(load_example("pressure_gauge.json")).product
    blank = check_product_input(load_example("pressure_gauge_blank_spec.json")).product
    assert product is not None and blank is not None
    first = ProductDescription.model_validate(build_card(product))
    second_payload = build_card(blank)
    second_payload["key_features"] = [
        item for item in second_payload["key_features"] if item["value"] in set(blank.specs.values())
    ]
    second = ProductDescription.model_validate(second_payload)
    results = append_result([], product, first)
    results = append_result(results, blank, second)
    assert [item["card"].seo_description for item in results] == [
        first.seo_description,
        second.seo_description,
    ]
    assert results[0]["id"] != results[1]["id"]
    assert "sk-" not in render_json(first)


def test_error_text_does_not_keep_an_api_key() -> None:
    check = check_product_input(
        {
            "name": "DM 02",
            "manufacturer": "Manotom",
            "specs": {
                "sk-test-secret-value": "G1/2",
                " sk-test-secret-value ": "M20x1.5",
            },
        }
    )
    assert "sk-test-secret-value" not in check.heading
    assert all("sk-test-secret-value" not in detail for detail in check.details)
    assert any("[redacted]" in detail for detail in check.details)
