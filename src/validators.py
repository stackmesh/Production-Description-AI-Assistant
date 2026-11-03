"""Parse product input and check generated cards against the source facts.

The model contract in :mod:`src.schemas` checks shape and length. This module
checks the business rule that technical specifications are copied from the
source and never invented.

Technical-fact checks compare recognized measurements, threads, and IP ratings
in the generated text with the original product input. The comparison is a
conservative string heuristic. It can reject a value that was not supplied.
It cannot prove that the rest of the description is factually correct: bare
numbers, certifications, materials, warranty periods, and suitability claims
are outside the patterns it scans, and a token that happens to occur in the
source can still be used in a misleading sentence.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from src.exceptions import (
    InvalidLLMResponseError,
    InvalidProductInputError,
    OutputValidationError,
)
from src.schemas import (
    SEO_DESCRIPTION_MAX,
    SEO_DESCRIPTION_MIN,
    SEO_TITLE_MAX,
    ProductDescription,
    ProductInput,
)

logger = logging.getLogger(__name__)

_INPUT_LABELS = {
    "name": "Product name",
    "manufacturer": "Manufacturer",
    "specs": "Specifications",
    "description": "Description",
}
_OUTPUT_LABELS = {
    "name": "Product name",
    "manufacturer": "Manufacturer",
    "seo_title": "SEO title",
    "seo_description": "SEO description",
    "key_features": "Key features",
    "search_queries": "Search queries",
    "sales_pitch": "Sales pitch",
    "missing_fields": "Missing fields",
    "clarification_required": "Clarification required",
    "warnings": "Warnings",
}
# Unit-bearing measurements, threads, and IP ratings. Bare accuracy-class numbers
# are checked through exact feature values so "accuracy class 1.5" can paraphrase
# the field name accuracy_class without being treated as a new specification.
_SPEC_TOKEN = re.compile(
    r"ip\d{2}(?!\d)"
    r"|g\d+/\d+(?!\d)"
    r"|m\d+x\d+(?:[.,]\d+)?(?!\d)"
    r"|\d+(?:[.,]\d+)?(?:\s*-\s*\d+(?:[.,]\d+)?)?\s*"
    r"(?:mpa|kpa|pa|bar|mm|cm|kg|°c|%|m)(?![a-z])",
    re.IGNORECASE,
)


def parse_product_input(payload: str | Mapping[str, Any] | ProductInput) -> ProductInput:
    """Parse and validate a product payload.

    Args:
        payload: A JSON object string, a mapping, or an existing
            :class:`ProductInput`.

    Returns:
        The normalized product. Blank specification values are removed and
        listed on :attr:`ProductInput.empty_spec_fields`.

    Raises:
        InvalidProductInputError: The payload is not valid JSON, has the wrong
            shape, or fails schema validation.
    """
    if isinstance(payload, ProductInput):
        return payload
    data = _load_input_object(payload)
    try:
        product = ProductInput.model_validate(data)
    except ValidationError as exc:
        message, errors = _format_validation_error(exc, "Product input is invalid", _INPUT_LABELS)
        logger.warning("Rejected product input: %s", message)
        raise InvalidProductInputError(message, errors=errors) from exc
    except ValueError as exc:
        message = f"Product input is invalid: {exc}"
        logger.warning("Rejected product input: %s", message)
        raise InvalidProductInputError(message, errors=(str(exc),)) from exc

    if product.empty_spec_fields:
        logger.info(
            "Treating empty specification values as missing: %s",
            ", ".join(product.empty_spec_fields),
        )
    logger.debug(
        "Validated product input name=%s specs=%d",
        product.name,
        len(product.specs),
    )
    return product


@dataclass(frozen=True)
class OutputAssessment:
    """A card that passed the factual checks, with any SEO length gaps.

    ``length_violations`` is empty when the title and description are inside
    the required ranges. The strict validator rejects those gaps. The
    generation service may keep them after one revision and attach a warning.
    """

    card: ProductDescription
    length_violations: tuple[str, ...]


def validate_generated_output(
    payload: str | Mapping[str, Any],
    product: ProductInput,
) -> ProductDescription:
    """Validate a generated card against the schema and the source product.

    SEO title and description lengths are required here. The generation
    service uses :func:`assess_generated_output` when it needs to preserve an
    out-of-range draft after one revision.

    Args:
        payload: JSON object string or mapping returned by the model.
        product: The normalized source facts.

    Returns:
        The validated product card, including the original name and manufacturer.

    Raises:
        InvalidLLMResponseError: The payload is empty, refused, or not a JSON object.
        OutputValidationError: The payload is JSON but breaks the card contract,
            misses an SEO length, or introduces specifications that are not in
            the source.
    """
    assessment = assess_generated_output(payload, product)
    if assessment.length_violations:
        message = "Generated product card is invalid:\n" + "\n".join(
            f"- {problem}" for problem in assessment.length_violations
        )
        logger.warning("Rejected generated card: %s", message)
        raise OutputValidationError(message, errors=assessment.length_violations)
    logger.debug("Validated generated card for %s", assessment.card.name)
    return assessment.card


def assess_generated_output(
    payload: str | Mapping[str, Any],
    product: ProductInput,
) -> OutputAssessment:
    """Parse a card and separate SEO length gaps from blocking problems.

    Blocking schema and grounding problems are raised. A title or description
    that is outside its length range is returned on the assessment when the
    rest of the card is acceptable, so the caller can revise it once.

    Raises:
        InvalidLLMResponseError: The payload is empty, refused, or not a JSON object.
        OutputValidationError: The payload breaks the card contract or invents
            specifications. Length is not treated as blocking here.
    """
    data = _load_model_object(payload)
    card = _parse_card(data)
    problems = _grounding_problems(card, product)
    if problems:
        message = "Generated product card is invalid:\n" + "\n".join(
            f"- {problem}" for problem in problems
        )
        logger.warning("Rejected generated card: %s", message)
        raise OutputValidationError(message, errors=tuple(problems))
    return OutputAssessment(card, tuple(collect_seo_length_violations(card)))


def collect_seo_length_violations(card: ProductDescription) -> list[str]:
    """Return deterministic SEO length failures for a parsed card.

    Empty title or description text is a schema error and is not reported
    here. Character counts use Python's ``len``, so each space and each
    letter counts as one character.
    """
    violations: list[str] = []
    title_length = len(card.seo_title)
    if title_length > SEO_TITLE_MAX:
        violations.append(
            f"SEO title must be at most {SEO_TITLE_MAX} characters (got {title_length})."
        )
    description_length = len(card.seo_description)
    if description_length < SEO_DESCRIPTION_MIN or description_length > SEO_DESCRIPTION_MAX:
        violations.append(
            "SEO description must be between "
            f"{SEO_DESCRIPTION_MIN} and {SEO_DESCRIPTION_MAX} characters "
            f"(got {description_length})."
        )
    return violations


def apply_seo_length_warnings(
    card: ProductDescription,
    violations: list[str] | tuple[str, ...],
    *,
    revised: bool,
) -> ProductDescription:
    """Keep an out-of-range title or description and record why it was not padded."""
    if not violations:
        return card
    if revised:
        suffix = (
            "The draft was kept after one revision so that no facts would be "
            "added to meet the length."
        )
    else:
        suffix = "The draft was kept so that no facts would be added to meet the length."
    notes = list(card.warnings)
    for violation in violations:
        note = f"{violation} {suffix}"
        if note not in notes:
            notes.append(note)
    return card.model_copy(update={"warnings": notes})


def find_unsupported_technical_values(text: str, product: ProductInput) -> list[str]:
    """Return measurement-like tokens in ``text`` that do not appear in ``product``.

    The scan looks only for IP ratings, pipe threads such as ``G1/2``, metric
    threads such as ``M20x1.5``, and numbers written with a unit from a fixed
    list: MPa, kPa, Pa, bar, mm, cm, kg, °C, %, and m. Matching ignores case,
    dash style, and extra whitespace.

    Limitations, which callers must not treat as a clean bill of factual health:

    - A number without one of those units is ignored. An accuracy class, a
      count, or a warranty written as words will not be flagged.
    - Certifications, materials, industries, and environment claims are ignored
      unless they happen to contain one of the patterns above.
    - A token is treated as supported when the same text occurs anywhere in the
      source. That does not prove the sentence around it is true.
    - Reformatted or calculated values can be missed, and a coincidental
      overlap with source text can hide an unsupported use.
    - An empty result does not mean the description is factually correct.
    """
    return _invented_spec_tokens(text, _source_text(product))


def _load_input_object(payload: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload, (bytes, bytearray)):
        raise InvalidProductInputError(
            "Product input must be a JSON string or an object, but binary data was provided."
        )
    if isinstance(payload, str):
        if not payload.strip():
            raise InvalidProductInputError("Product input is empty. Provide a JSON object.")
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidProductInputError(
                "Product input is not valid JSON: "
                f"{exc.msg} (line {exc.lineno}, column {exc.colno})."
            ) from exc
        return _expect_object(decoded, InvalidProductInputError, "Product input")
    if isinstance(payload, Mapping):
        return dict(payload)
    raise InvalidProductInputError(
        "Product input must be a JSON string or an object, "
        f"but {_value_kind(payload)} was provided."
    )


def _load_model_object(payload: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload, str):
        if not payload.strip():
            raise InvalidLLMResponseError("The model returned an empty response.")
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise InvalidLLMResponseError(
                "The model response is not valid JSON: "
                f"{exc.msg} (line {exc.lineno}, column {exc.colno})."
            ) from exc
    elif isinstance(payload, Mapping):
        decoded = dict(payload)
    else:
        raise InvalidLLMResponseError(
            "The model response must be a JSON object, "
            f"but {_value_kind(payload)} was provided."
        )

    if isinstance(decoded, Mapping) and decoded.get("refusal") and "seo_title" not in decoded:
        raise InvalidLLMResponseError(f"The model refused the request: {decoded['refusal']}")
    return _expect_object(decoded, InvalidLLMResponseError, "The model response")


def _parse_card(data: dict[str, Any]) -> ProductDescription:
    try:
        return ProductDescription.model_validate(data)
    except ValidationError as exc:
        if not _only_seo_length_errors(exc):
            _raise_schema_error(exc)
        try:
            return ProductDescription.model_validate(
                data,
                context={"preserve_seo_length": True},
            )
        except ValidationError as preserved_exc:
            _raise_schema_error(preserved_exc)
    except ValueError as exc:
        message = f"Generated product card is invalid: {exc}"
        logger.warning("Rejected generated card: %s", message)
        raise OutputValidationError(message, errors=(str(exc),)) from exc


def _raise_schema_error(exc: ValidationError) -> None:
    message, errors = _format_validation_error(
        exc,
        "Generated product card is invalid",
        _OUTPUT_LABELS,
    )
    logger.warning("Rejected generated card: %s", message)
    raise OutputValidationError(message, errors=errors) from exc


def _only_seo_length_errors(exc: ValidationError) -> bool:
    errors = exc.errors()
    return bool(errors) and all(_is_seo_length_error(error) for error in errors)


def _is_seo_length_error(error: dict[str, Any]) -> bool:
    location = error.get("loc") or ()
    if len(location) != 1 or location[0] not in {"seo_title", "seo_description"}:
        return False
    message = str(error.get("msg", "")).casefold()
    if "empty" in message:
        return False
    return "character" in message


def _expect_object(decoded: Any, error_type: type[Exception], label: str) -> dict[str, Any]:
    if isinstance(decoded, dict):
        return decoded
    raise error_type(f"{label} must be a JSON object, but {_value_kind(decoded)} was provided.")


def _grounding_problems(card: ProductDescription, product: ProductInput) -> list[str]:
    problems: list[str] = []
    if card.name != product.name:
        problems.append(f"name: must match the source product name {product.name!r}.")
    if card.manufacturer != product.manufacturer:
        problems.append(f"manufacturer: must match the source manufacturer {product.manufacturer!r}.")

    provided = set(product.specs)
    provided.update({"name", "manufacturer"})
    if product.description:
        provided.add("description")
    for field_name in card.missing_fields:
        if field_name in provided:
            problems.append(
                f"missing_fields: '{field_name}' has a value in the source and is not missing."
            )
    for field_name in product.empty_spec_fields:
        if field_name not in card.missing_fields:
            problems.append(
                f"missing_fields: '{field_name}' was empty in the source and must be listed."
            )

    allowed_values = {_fold(value) for value in product.specs.values()}
    if product.specs and not card.key_features:
        problems.append(
            "key_features: include at least one feature copied from the specifications."
        )
    if not product.specs and card.key_features:
        problems.append(
            "key_features: the source has no specifications, so no feature values can be added."
        )
    seen_names: set[str] = set()
    for index, feature in enumerate(card.key_features):
        folded_name = _fold(feature.name)
        if folded_name in seen_names:
            problems.append(
                f"key_features[{index}].name: '{feature.name}' duplicates another feature."
            )
        else:
            seen_names.add(folded_name)
        if _fold(feature.value) not in allowed_values:
            problems.append(
                f"key_features[{index}].value: {feature.value!r} is not present "
                "in the product specifications."
            )

    generated = "\n".join(
        [
            card.seo_title,
            card.seo_description,
            card.sales_pitch,
            *card.search_queries,
            *card.warnings,
            *(feature.name for feature in card.key_features),
            *(feature.explanation for feature in card.key_features),
            *(feature.value for feature in card.key_features),
        ]
    )
    for token in find_unsupported_technical_values(generated, product):
        problems.append(
            f"generated text: contains specification {token!r} that is not in the source data."
        )
    return problems


def _source_text(product: ProductInput) -> str:
    parts = [product.name, product.manufacturer, *product.specs.keys(), *product.specs.values()]
    if product.description:
        parts.append(product.description)
    return "\n".join(parts)


def _invented_spec_tokens(text: str, source: str) -> list[str]:
    folded_source = _fold(source)
    invented: list[str] = []
    seen: set[str] = set()
    for match in _SPEC_TOKEN.finditer(_fold(text)):
        token = re.sub(r"\s+", " ", match.group(0)).strip()
        if token in seen:
            continue
        seen.add(token)
        if not _token_in_source(token, folded_source):
            invented.append(token)
    return invented


def _token_in_source(token: str, source: str) -> bool:
    pattern = re.compile(rf"(?<!\d){re.escape(token)}(?!\d)", re.IGNORECASE)
    return pattern.search(source) is not None


def _fold(text: str) -> str:
    folded = text.casefold()
    folded = folded.replace("–", "-").replace("—", "-").replace("−", "-").replace("×", "x")
    folded = re.sub(r"\s*/\s*", "/", folded)
    folded = re.sub(r"\s*x\s*", "x", folded)
    return re.sub(r"\s+", " ", folded)


def _format_validation_error(
    exc: ValidationError,
    summary: str,
    labels: dict[str, str],
) -> tuple[str, tuple[str, ...]]:
    lines: list[str] = []
    for error in exc.errors():
        location = _location(error.get("loc", ()))
        label = _label_for(error.get("loc", ()), labels)
        lines.append(f"{location}: {_error_text(error, label)}")
    message = summary + ":\n" + "\n".join(f"- {line}" for line in lines)
    return message, tuple(lines)


def _location(loc: tuple[Any, ...] | list[Any]) -> str:
    if not loc:
        return "input"
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int) and parts:
            parts[-1] = f"{parts[-1]}[{item}]"
        else:
            parts.append(str(item))
    return ".".join(parts)


def _label_for(loc: tuple[Any, ...] | list[Any], labels: dict[str, str]) -> str:
    for item in loc:
        if isinstance(item, str) and item in labels:
            return labels[item]
    return "This field"


def _error_text(error: dict[str, Any], label: str) -> str:
    error_type = error.get("type", "")
    raw = str(error.get("msg", "is invalid"))
    if raw.startswith("Value error, "):
        return raw.removeprefix("Value error, ")
    if error_type == "missing":
        if label == "Specifications":
            return "Specifications are required and must be an object of strings."
        return f"{label} is required."
    if error_type == "extra_forbidden":
        return "This field is not allowed."
    if error_type in {"string_type", "dict_type", "list_type", "bool_type"}:
        expected = {
            "string_type": "a string",
            "dict_type": "an object of strings",
            "list_type": "a list",
            "bool_type": "a boolean",
        }[error_type]
        return f"{label} must be {expected}, but {_value_kind(error.get('input'))} was provided."
    return raw


def _value_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, dict):
        return "an object"
    if isinstance(value, list):
        return "a list"
    return type(value).__name__
