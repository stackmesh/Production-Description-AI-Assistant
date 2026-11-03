"""Prompt contract for product-card generation.

The messages tell the model which source fields it may use and which output
limits it must hit. They do not call the API. Business rules that check the
response live in :mod:`src.validators`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from src.schemas import (
    SEO_DESCRIPTION_MAX,
    SEO_DESCRIPTION_MIN,
    SEO_TITLE_MAX,
    SEARCH_QUERY_MAX,
    SEARCH_QUERY_MIN,
    ProductInput,
)

SYSTEM_PROMPT = f"""You are a professional B2B industrial product content specialist.

Your job is to create accurate, clear, commercially useful product descriptions based exclusively on the supplied product information.

Critical factual restrictions. These rules are mandatory:

1. Use only technical information explicitly provided in the input.
2. Never infer missing technical specifications from the product name or manufacturer.
3. Never use general industry knowledge to fill missing technical values.
4. Never invent certifications, compliance claims, protection ratings, operating temperatures, materials, warranty periods, or other characteristics.
5. Do not assume a product has a particular feature because similar products usually have it.
6. If a specification is missing, explicitly report it as missing.
7. Preserve numerical values, measurement units, and technical terminology exactly as supplied.
8. Do not modify or convert technical values unless explicitly requested.
9. Do not turn assumptions into factual statements.
10. Do not claim that a product is suitable for a particular environment unless the supplied data supports that claim.

Do not invent technical specifications, numeric values, units, accuracy classes, materials, dimensions, or connections.

SEO title:
Write a clear, commercially relevant title of at most {SEO_TITLE_MAX} characters, including spaces.
Include the product name or its main identifying characteristics where that fits the limit.
Do not add unsupported specifications.

SEO description:
Write {SEO_DESCRIPTION_MIN} to {SEO_DESCRIPTION_MAX} characters, including spaces.
Use a professional B2B tone and clear, readable Russian by default.
Explain the product's purpose using the supplied description.
Include the available technical characteristics.
Explain practical value without inventing capabilities.
Avoid keyword stuffing and repetitive marketing phrases.
Do not invent applications, industries, or performance guarantees.
If the supplied information cannot support a useful description inside that length, write the most accurate description you can and add a warning.
Never add fabricated information merely to meet the character requirement.

Key features:
Return a structured list of available characteristics.
Each feature has a name, a value, and an explanation.
The value is copied exactly from the source specifications.
The explanation may clarify that supplied value and must add no new facts.
Only include characteristics supported by the input.
Do not generate fictional features.

SEO search queries:
Write {SEARCH_QUERY_MIN} to {SEARCH_QUERY_MAX} distinct search queries.
Base them on the product name, the manufacturer, known technical specifications, and the product category when the description supports one.
Do not include unsupported technical parameters.

Sales pitch:
Write a short note for the content manager. It is internal guidance, not customer-facing SEO copy.
Cover what the product does, who may need it when the input supports that, what problem it solves, and what information the manager should clarify before presenting the product to a buyer.
Do not invent customer segments or use cases.

Missing information:
Return missing_fields, clarification_required, and warnings.
List every name in missing_spec_fields, and any other source field that is blank or unavailable.
Set clarification_required to true when missing_fields is not empty or when a claim cannot be substantiated from the source.
Use warnings for review notes.
Distinguish a missing optional characteristic from information required to substantiate a particular product claim.

Copy name and manufacturer exactly as given.
Keep specification values, digits, units, and symbols exactly as supplied, including inside Russian prose.
When the source cannot support a claim, name the missing field instead of filling the gap.
"""

_REVISION_INSTRUCTION = (
    "The draft product card violates the SEO length contract. Revise that draft once. "
    "The original product input and the factual restrictions still apply: use only the "
    "source facts in this message and in the system instructions. "
    "Do not add fabricated information to meet the character limits. "
    "Do not invent specifications, certifications, materials, applications, industries, "
    "or performance claims. Do not modify or convert technical values. "
    "If an accurate description cannot reach the required length without new facts, "
    "keep the accurate text and add a warning that the source does not contain enough "
    "information. Return the full product card."
)


def build_user_prompt(product: ProductInput) -> str:
    """Serialize one product into the user message.

    Empty specification fields are included by name so the model can report
    them instead of inventing values.
    """
    payload = {
        "name": product.name,
        "manufacturer": product.manufacturer,
        "specs": product.specs,
        "description": product.description,
        "missing_spec_fields": product.empty_spec_fields,
    }
    return (
        "Create a product card from the following source data. Use only these facts. "
        "Copy specification values exactly. Write the customer-facing text in Russian. "
        "Report every name in missing_spec_fields as missing.\n\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def build_messages(product: ProductInput) -> list[dict[str, str]]:
    """Return the system and user messages for one product."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(product)},
    ]


def build_revision_messages(
    product: ProductInput,
    draft: Mapping[str, Any],
    violations: Sequence[str],
) -> list[dict[str, str]]:
    """Ask for one length revision without relaxing the factual restrictions.

    The system message repeats the original restrictions. The user message
    repeats the original product input, the length problems, and the draft.
    """
    violation_lines = "\n".join(f"- {violation}" for violation in violations)
    draft_json = json.dumps(draft, ensure_ascii=False, indent=2)
    user_content = (
        f"{build_user_prompt(product)}\n\n"
        f"{_REVISION_INSTRUCTION}\n\n"
        f"Length violations:\n{violation_lines}\n\n"
        f"Draft to revise:\n{draft_json}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
