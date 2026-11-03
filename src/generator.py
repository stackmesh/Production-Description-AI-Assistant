"""Orchestrate input validation, generation, and output validation.

The OpenAI call is delegated to :class:`src.llm_client.LLMClient`. This module
builds the prompt, asks for one SEO length revision when needed, and returns
a validated card. It does not import Streamlit.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from src.config import load_settings
from src.exceptions import InvalidLLMResponseError, OutputValidationError
from src.llm_client import LLMClient
from src.prompts import build_messages, build_revision_messages
from src.schemas import ProductCardOutput, ProductDescription, ProductInput
from src.validators import (
    apply_seo_length_warnings,
    assess_generated_output,
    parse_product_input,
)

logger = logging.getLogger(__name__)


class ProductDescriptionGenerator:
    """Validate a product, request a card, and check the card against the source."""

    def __init__(self, client: LLMClient | None = None) -> None:
        self._client = client

    def validate_input(self, payload: str | Mapping[str, Any] | ProductInput) -> ProductInput:
        """Parse and validate a product payload."""
        return parse_product_input(payload)

    def generate(self, payload: str | Mapping[str, Any] | ProductInput) -> ProductCardOutput:
        """Validate ``payload`` and return a grounded product card.

        Input validation always runs. When no client is configured, generation
        stops before any model request.

        Args:
            payload: JSON string, mapping, or validated product.

        Returns:
            The validated product card from the configured client.

        Raises:
            InvalidProductInputError: The payload cannot be used.
            RuntimeError: No generation client is configured.
            RateLimitError: The OpenAI rate limit was exceeded.
            APICommunicationError: The OpenAI request failed.
            InvalidLLMResponseError: The client returned an unusable response.
            OutputValidationError: The card breaks the schema or invents specifications.
        """
        product = self.validate_input(payload)
        logger.info(
            "Product input validated name=%s manufacturer=%s specs=%d missing_specs=%d",
            product.name,
            product.manufacturer,
            len(product.specs),
            len(product.empty_spec_fields),
        )
        if self._client is None:
            raise RuntimeError(
                "No LLM client is configured. Use generate_product_description to load "
                "the OpenAI client from the environment, or pass an LLMClient."
            )
        logger.info("Requesting a product card from model %s", self._client.model)
        messages = build_messages(product)
        raw = self._client.generate_product_card(product, messages)
        assessment = assess_generated_output(raw, product)
        if not assessment.length_violations:
            return assessment.card

        logger.info(
            "SEO length is outside the contract for model %s; requesting one revision",
            self._client.model,
        )
        revised = False
        revision_rejected = False
        sender = _revision_sender(self._client)
        if sender is not None:
            draft = _json_object(raw)
            try:
                revised_raw = sender(
                    build_revision_messages(product, draft, assessment.length_violations)
                )
                assessment = assess_generated_output(revised_raw, product)
                revised = True
            except (OutputValidationError, InvalidLLMResponseError):
                logger.warning(
                    "Discarded the SEO length revision because it failed validation"
                )
                revision_rejected = True
        if assessment.length_violations:
            card = apply_seo_length_warnings(
                assessment.card,
                assessment.length_violations,
                revised=revised,
            )
            if revision_rejected:
                card = _note_discarded_revision(card)
            return card
        return assessment.card


def generate_product_description(
    product: ProductInput,
    *,
    client: LLMClient | None = None,
) -> ProductCardOutput:
    """Normalize ``product`` and return a validated product card.

    When ``client`` is omitted, the OpenAI client is built from the environment
    configuration. Tests pass a client so they do not need a live API key.

    Args:
        product: Validated product facts. A mapping or JSON string is normalized
            through the same input parser.
        client: Optional client. The default loads ``OPENAI_API_KEY`` and
            ``OPENAI_MODEL``.

    Returns:
        The product card, including a warning when the SEO length is still
        outside the required range after one revision.
    """
    if client is None:
        client = LLMClient(load_settings())
    return ProductDescriptionGenerator(client).generate(product)


_DISCARDED_REVISION = (
    "The length revision was discarded because it did not pass validation. "
    "The earlier draft was kept so that no unsupported facts would be published."
)


def _note_discarded_revision(card: ProductDescription) -> ProductDescription:
    warnings = list(card.warnings)
    if _DISCARDED_REVISION not in warnings:
        warnings.append(_DISCARDED_REVISION)
    return card.model_copy(update={"warnings": warnings})


def _revision_sender(
    client: LLMClient,
) -> Callable[[Sequence[Mapping[str, str]]], Any] | None:
    """Return a completion method that can send the one length revision.

    A test double that only replaces ``generate_product_card`` inherits
    ``complete`` but is not configured for a real request. Revision is offered
    when the instance was configured or when its class defines ``complete``.
    """
    complete = getattr(client, "complete", None)
    if not callable(complete):
        return None
    defines_complete = "complete" in type(client).__dict__
    configured = getattr(client, "_settings", None) is not None
    if defines_complete or configured:
        return complete
    return None


def _json_object(payload: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload, str):
        decoded = json.loads(payload)
        if isinstance(decoded, dict):
            return decoded
        raise TypeError("The model response must be a JSON object.")
    return dict(payload)
