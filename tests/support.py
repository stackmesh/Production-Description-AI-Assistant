"""Shared fixtures for schema and validation tests."""

from __future__ import annotations

import json
from pathlib import Path

from src.schemas import ProductInput

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def load_example(name: str) -> dict:
    """Return one example payload from ``examples/``."""
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def pad_description(seed: str) -> str:
    """Extend ``seed`` into the required SEO description length."""
    filler = " Supplied facts only."
    text = seed.strip()
    while len(text) < 800:
        text += filler
    if len(text) > 1200:
        raise AssertionError(f"Seed is too long to pad: {len(text)}")
    return text


def build_card(product: ProductInput) -> dict:
    """Build a card that repeats only facts present on ``product``."""
    sentences = [f"{product.name} by {product.manufacturer}."]
    if product.description:
        sentences.append(product.description)
    features = []
    for key, value in product.specs.items():
        label = key.replace("_", " ").capitalize()
        features.append(
            {
                "name": label,
                "value": value,
                "explanation": f"{label} stated for the instrument.",
            }
        )
        sentences.append(f"{label} {value}.")
    queries = [
        product.name,
        f"{product.manufacturer} instrument",
        f"{product.name} {product.manufacturer}",
    ]
    if product.specs:
        first_value = next(iter(product.specs.values()))
        queries.append(f"{product.name} {first_value}")
    if product.specs:
        listed = ", ".join(product.specs.values())
        sales_pitch = f"Position {product.name} from {product.manufacturer} with {listed}."
    else:
        sales_pitch = (
            f"Position {product.name} from {product.manufacturer} using the supplied facts."
        )
    return {
        "name": product.name,
        "manufacturer": product.manufacturer,
        "seo_title": "DM 02 Pressure Gauge | Manotom",
        "seo_description": pad_description(" ".join(sentences)),
        "key_features": features,
        "search_queries": queries,
        "sales_pitch": sales_pitch,
        "missing_fields": list(product.empty_spec_fields),
        "clarification_required": bool(product.empty_spec_fields),
        "warnings": [],
    }
