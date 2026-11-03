"""Application exceptions for the product description assistant.

API failures are split so callers can retry rate limits without treating
them as generic transport errors. Invalid model payloads are split the same
way: a response that is not usable JSON is an LLM response error, while JSON
that breaks the product-card contract is an output validation error.
"""

from __future__ import annotations


class ProductDescriptionError(Exception):
    """Base error for the product description assistant."""


class InvalidProductInputError(ProductDescriptionError):
    """The product payload is invalid JSON or does not match the input schema."""

    def __init__(self, message: str, *, errors: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.errors = errors


class MissingAPIConfigurationError(ProductDescriptionError):
    """Required OpenAI configuration is missing or still a placeholder."""


class APICommunicationError(ProductDescriptionError):
    """The OpenAI request failed because of network, server, or credential problems."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RateLimitError(ProductDescriptionError):
    """The OpenAI API rate limit was exceeded."""

    def __init__(self, message: str, *, status_code: int | None = 429) -> None:
        super().__init__(message)
        self.status_code = status_code


class InvalidLLMResponseError(ProductDescriptionError):
    """The model response is empty, refused, or not a JSON object."""


class OutputValidationError(ProductDescriptionError):
    """The model response does not satisfy the product-card contract."""

    def __init__(self, message: str, *, errors: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.errors = errors
