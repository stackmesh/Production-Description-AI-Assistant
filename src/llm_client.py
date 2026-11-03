"""Boundary between the application and the OpenAI SDK.

The client sends a structured-output request and returns the JSON object.
It does not decide whether a product card is factually valid, and it does not
replace a failed response with invented content.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from openai import OpenAI, OpenAIError

from src.config import Settings
from src.exceptions import APICommunicationError, InvalidLLMResponseError, RateLimitError
from src.prompts import build_messages
from src.schemas import ProductInput, openai_structured_schema

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 60.0
_MAX_OUTPUT_TOKENS = 8192
_SCHEMA_NAME = "product_card"
_SECRET_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")

_RATE_LIMIT_TYPES = frozenset({"RateLimitError"})
_CONNECTION_TYPES = frozenset({"APITimeoutError", "APIConnectionError"})
_AUTH_TYPES = frozenset({"AuthenticationError", "PermissionDeniedError"})
_API_TYPES = frozenset(
    {
        "APIError",
        "APIStatusError",
        "InternalServerError",
        "BadRequestError",
        "UnprocessableEntityError",
        "ConflictError",
        "NotFoundError",
    }
)
_SDK_ERROR_NAMES = _RATE_LIMIT_TYPES | _CONNECTION_TYPES | _AUTH_TYPES | _API_TYPES
_TRANSPORT_MODULES = frozenset({"httpx", "httpcore"})


class LLMClient:
    """Call the configured OpenAI model and return its structured JSON object."""

    def __init__(
        self,
        settings: Settings,
        *,
        sdk: Any | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if timeout <= 0:
            raise ValueError("OpenAI request timeout must be greater than zero.")
        self._settings = settings
        self._sdk = sdk
        self._timeout = float(timeout)

    @property
    def model(self) -> str:
        """Return the configured model id."""
        return self._settings.openai_model

    def generate_product_card(
        self,
        product: ProductInput,
        messages: Sequence[Mapping[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Request a product card for ``product``.

        ``messages`` lets the generation service pass the prompt it built.
        When it is omitted, the client builds the standard product-card prompt.

        Returns:
            The JSON object produced by the model.

        Raises:
            RateLimitError: The API rate limit was exceeded.
            APICommunicationError: The request failed because of network,
                server, or credential problems.
            InvalidLLMResponseError: The model returned an empty response,
                a refusal, or a body that is not a JSON object.
        """
        prepared = list(messages) if messages is not None else build_messages(product)
        if not product.name:
            raise ValueError("Product name must not be empty.")
        return self.complete(prepared)

    def complete(self, messages: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        """Send ``messages`` and return the structured JSON object.

        The call uses the configured model, a bounded timeout, and no automatic
        SDK retries. A failed call is raised. It is never replaced with a
        fallback card.
        """
        prepared = _require_messages(messages)
        logger.info(
            "Sending structured generation request model=%s timeout=%.0fs messages=%d",
            self.model,
            self._timeout,
            len(prepared),
        )
        try:
            response = self._sdk_client().responses.create(**self._request_kwargs(prepared))
        except Exception as exc:
            self._raise_api_error(exc)
            raise
        return _parse_structured_response(response, secret=self._settings.api_key)

    def _sdk_client(self) -> Any:
        if self._sdk is None:
            self._sdk = OpenAI(
                api_key=self._settings.api_key,
                timeout=self._timeout,
                max_retries=0,
            )
        return self._sdk

    def _request_kwargs(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {
            "model": self.model,
            "input": messages,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": _SCHEMA_NAME,
                    "strict": True,
                    "schema": openai_structured_schema(),
                }
            },
            "max_output_tokens": _MAX_OUTPUT_TOKENS,
            "store": False,
            "timeout": self._timeout,
        }

    def _raise_api_error(self, exc: BaseException) -> None:
        module = type(exc).__module__.split(".")[0]
        if module in _TRANSPORT_MODULES:
            logger.error("OpenAI connection failed: %s", type(exc).__name__)
            raise APICommunicationError(
                f"The OpenAI API could not complete the request ({type(exc).__name__})."
            ) from exc
        if isinstance(exc, OpenAIError) or type(exc).__name__ in _SDK_ERROR_NAMES:
            translated = translate_api_error(exc)
            message = _redact(str(translated), self._settings.api_key)
            if message != str(translated):
                translated = _with_message(translated, message)
            raise translated from exc
        raise exc


def translate_api_error(exc: BaseException) -> APICommunicationError | RateLimitError:
    """Map an exception raised by the OpenAI SDK to an application error.

    Rate limits stay distinct so a caller can back off. Credential, network,
    and server failures become :class:`APICommunicationError`. Call this only
    for exceptions raised by the SDK request.

    Args:
        exc: The exception caught around the SDK call.

    Returns:
        The application error to raise. The original exception should be
        attached with ``raise translated from exc``.
    """
    status = _status_code(exc)
    type_name = type(exc).__name__

    if type_name in _RATE_LIMIT_TYPES or status == 429:
        logger.warning("OpenAI rate limit reached (status=%s)", status)
        return RateLimitError(
            "The OpenAI API rate limit was exceeded. Wait and retry the request.",
            status_code=status or 429,
        )

    if type_name in _CONNECTION_TYPES or status in {408, 409, 500, 502, 503, 504}:
        logger.error("OpenAI request failed: %s", type_name)
        return APICommunicationError(
            f"The OpenAI API could not complete the request ({type_name}).",
            status_code=status,
        )

    if type_name in _AUTH_TYPES or status in {401, 403}:
        logger.error("OpenAI rejected the credentials (status=%s)", status)
        return APICommunicationError(
            "The OpenAI API rejected the credentials. Check that OPENAI_API_KEY is valid.",
            status_code=status,
        )

    if type_name in _API_TYPES or status is not None:
        logger.error("OpenAI request failed: %s status=%s", type_name, status)
        return APICommunicationError(
            f"The OpenAI API request failed ({type_name}).",
            status_code=status,
        )

    logger.error("Unexpected error during the OpenAI call: %s", type_name)
    return APICommunicationError(
        f"Unexpected error while calling the OpenAI API ({type_name}).",
        status_code=status,
    )


def _require_messages(messages: Sequence[Mapping[str, str]]) -> list[dict[str, str]]:
    prepared = [dict(message) for message in messages]
    if not prepared:
        raise ValueError("The generation request has no messages.")
    for message in prepared:
        if message.get("role") not in {"system", "user", "developer"}:
            raise ValueError("Each generation message needs a system, developer, or user role.")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Each generation message needs text content.")
    return prepared


def _parse_structured_response(response: Any, *, secret: str) -> dict[str, Any]:
    status = _response_status(response)
    text, refusal = _response_parts(response)
    if status in {"failed", "cancelled"} or (status == "incomplete" and not text.strip()):
        detail = _safe_status_detail(response, secret)
        message = f"The model response did not complete (status={status})."
        if detail:
            message = f"{message} {detail}"
        raise InvalidLLMResponseError(message)
    if refusal:
        raise InvalidLLMResponseError(
            f"The model refused the request: {_redact(refusal, secret)}"
        )
    if not text.strip():
        raise InvalidLLMResponseError("The model returned an empty response.")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidLLMResponseError(
            "The model response is not valid JSON: "
            f"{exc.msg} (line {exc.lineno}, column {exc.colno})."
        ) from exc
    if not isinstance(decoded, dict):
        raise InvalidLLMResponseError(
            "The model response must be a JSON object, "
            f"but {_json_kind(decoded)} was provided."
        )
    return decoded


def _response_status(response: Any) -> str | None:
    if isinstance(response, Mapping):
        status = response.get("status")
    else:
        status = getattr(response, "status", None)
    if isinstance(status, str):
        return status
    return None


def _response_parts(response: Any) -> tuple[str, str]:
    refusals: list[str] = []
    texts: list[str] = []
    outputs = response.get("output") if isinstance(response, Mapping) else getattr(response, "output", None)
    for output in outputs or []:
        content = output.get("content") if isinstance(output, Mapping) else getattr(output, "content", None)
        for part in content or []:
            part_type = part.get("type") if isinstance(part, Mapping) else getattr(part, "type", None)
            if part_type == "refusal":
                refusal = part.get("refusal") if isinstance(part, Mapping) else getattr(part, "refusal", "")
                if isinstance(refusal, str) and refusal.strip():
                    refusals.append(refusal.strip())
            elif part_type == "output_text":
                text = part.get("text") if isinstance(part, Mapping) else getattr(part, "text", "")
                if isinstance(text, str) and text:
                    texts.append(text)
    if not texts:
        fallback = response.get("output_text") if isinstance(response, Mapping) else getattr(response, "output_text", "")
        if isinstance(fallback, str) and fallback:
            texts.append(fallback)
    if not refusals and isinstance(response, Mapping):
        fallback_refusal = response.get("refusal")
        if isinstance(fallback_refusal, str) and fallback_refusal.strip():
            refusals.append(fallback_refusal.strip())
    return "".join(texts), " ".join(refusals)


def _safe_status_detail(response: Any, secret: str) -> str:
    error = response.get("error") if isinstance(response, Mapping) else getattr(response, "error", None)
    if isinstance(error, Mapping):
        message = error.get("message")
    else:
        message = getattr(error, "message", None)
    if not isinstance(message, str):
        return ""
    cleaned = _redact(message, secret).strip()
    return cleaned[:300]


def _with_message(
    translated: APICommunicationError | RateLimitError,
    message: str,
) -> APICommunicationError | RateLimitError:
    status_code = getattr(translated, "status_code", None)
    if isinstance(translated, RateLimitError):
        return RateLimitError(message, status_code=status_code)
    return APICommunicationError(message, status_code=status_code)


def _redact(text: str, secret: str | None = None) -> str:
    if secret:
        text = text.replace(secret, "[redacted]")
    return _SECRET_PATTERN.sub("[redacted]", text)


def _status_code(exc: BaseException) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    return None


def _json_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "a boolean"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, str):
        return "a string"
    if isinstance(value, list):
        return "a list"
    return type(value).__name__
