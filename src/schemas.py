"""Pydantic contracts for product input and generated product cards.

Length limits live on the models so invalid cards fail before they are shown.
The OpenAI structured-output schema is derived from the same models, with
keywords the strict JSON Schema subset does not accept removed. Those limits
are still enforced here after the response is parsed.
"""

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PrivateAttr,
    ValidationInfo,
    field_validator,
    model_validator,
)

SEO_TITLE_MAX = 70
SEO_DESCRIPTION_MIN = 800
SEO_DESCRIPTION_MAX = 1200
SEARCH_QUERY_MIN = 3
SEARCH_QUERY_MAX = 5

_OPENAI_UNSUPPORTED_KEYWORDS = frozenset(
    {
        "minLength",
        "maxLength",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
        "uniqueItems",
        "pattern",
        "format",
        "default",
        "examples",
    }
)


class ProductInput(BaseModel):
    """Structured facts supplied for one industrial instrument.

    ``name`` and ``manufacturer`` are required. ``specs`` accepts any string
    keys, so new specification fields do not require a schema change. Blank
    specification values are removed and exposed through
    :attr:`empty_spec_fields` so later steps can treat them as missing.
    """

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    name: str
    manufacturer: str
    specs: dict[str, str]
    description: str | None = None

    _empty_spec_fields: list[str] = PrivateAttr(default_factory=list)

    @model_validator(mode="wrap")
    @classmethod
    def _normalize_payload(cls, data: Any, handler: Any) -> ProductInput:
        empty_fields: list[str] = []
        if isinstance(data, ProductInput):
            return data
        if isinstance(data, dict):
            payload = dict(data)
            specs = payload.get("specs")
            if isinstance(specs, dict):
                cleaned, empty_fields = _partition_specs(specs)
                payload["specs"] = cleaned
            data = payload
        model = handler(data)
        model._empty_spec_fields = empty_fields
        return model

    @field_validator("name", "manufacturer")
    @classmethod
    def _required_identity(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            label = "Product name" if info.field_name == "name" else "Manufacturer"
            raise ValueError(f"{label} must not be empty.")
        return value.strip()

    @field_validator("description", mode="before")
    @classmethod
    def _blank_description(cls, value: Any) -> Any:
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def empty_spec_fields(self) -> list[str]:
        """Specification names that arrived empty and are treated as missing."""
        return list(self._empty_spec_fields)


class KeyFeature(BaseModel):
    """One specification rendered for the product card.

    ``value`` must be copied from the source specifications. Validation of
    that rule is applied against the original product, not inside this model.
    """

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    name: str = Field(description="Short label for the specification.")
    value: str = Field(description="Specification value copied exactly from the source.")
    explanation: str = Field(
        description="One sentence that explains the supplied value and adds no new facts."
    )

    @field_validator("name", "value", "explanation")
    @classmethod
    def _non_empty(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"Feature {info.field_name} must not be empty.")
        return value.strip()


class ProductDescription(BaseModel):
    """Draft product card produced from one :class:`ProductInput`.

    ``name`` and ``manufacturer`` repeat the source identity so the card can
    be stored without looking up the original payload.
    """

    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    name: str = Field(description="Original product name, copied exactly.")
    manufacturer: str = Field(description="Original manufacturer, copied exactly.")
    seo_title: str = Field(description=f"SEO title of at most {SEO_TITLE_MAX} characters.")
    seo_description: str = Field(
        description=(
            f"SEO description of {SEO_DESCRIPTION_MIN} to {SEO_DESCRIPTION_MAX} "
            "characters, written only from supplied facts."
        )
    )
    key_features: list[KeyFeature] = Field(
        description="Structured features whose values come from the source specifications."
    )
    search_queries: list[str] = Field(
        description=f"{SEARCH_QUERY_MIN} to {SEARCH_QUERY_MAX} SEO search queries."
    )
    sales_pitch: str = Field(
        description="Short internal note for the content manager. It is not customer-facing SEO copy."
    )
    missing_fields: list[str] = Field(
        description="Source fields that were blank or otherwise unavailable."
    )
    clarification_required: bool = Field(
        description="True when missing_fields is not empty or the source cannot support the card."
    )
    warnings: list[str] = Field(description="Caveats the content manager should review.")

    @field_validator("name", "manufacturer", "sales_pitch")
    @classmethod
    def _non_empty_text(cls, value: str, info: ValidationInfo) -> str:
        if not value.strip():
            raise ValueError(f"{info.field_name} must not be empty.")
        return value.strip()

    @field_validator("seo_title")
    @classmethod
    def _seo_title_length(cls, value: str, info: ValidationInfo) -> str:
        title = value.strip()
        if not title:
            raise ValueError("SEO title must not be empty.")
        if len(title) > SEO_TITLE_MAX and not _preserve_seo_length(info):
            raise ValueError(
                f"SEO title must be at most {SEO_TITLE_MAX} characters (got {len(title)})."
            )
        return title

    @field_validator("seo_description")
    @classmethod
    def _seo_description_length(cls, value: str, info: ValidationInfo) -> str:
        description = value.strip()
        if not description:
            raise ValueError("SEO description must not be empty.")
        length = len(description)
        if (
            length < SEO_DESCRIPTION_MIN or length > SEO_DESCRIPTION_MAX
        ) and not _preserve_seo_length(info):
            raise ValueError(
                "SEO description must be between "
                f"{SEO_DESCRIPTION_MIN} and {SEO_DESCRIPTION_MAX} characters (got {length})."
            )
        return description

    @field_validator("search_queries")
    @classmethod
    def _search_queries(cls, value: list[str]) -> list[str]:
        queries = [item.strip() for item in value]
        if any(not item for item in queries):
            raise ValueError("Each SEO search query must not be empty.")
        count = len(queries)
        if count < SEARCH_QUERY_MIN or count > SEARCH_QUERY_MAX:
            raise ValueError(
                f"Provide {SEARCH_QUERY_MIN} to {SEARCH_QUERY_MAX} SEO search queries (got {count})."
            )
        folded = [item.casefold() for item in queries]
        if len(folded) != len(set(folded)):
            raise ValueError("SEO search queries must be distinct.")
        return queries

    @field_validator("missing_fields", "warnings")
    @classmethod
    def _string_list(cls, value: list[str], info: ValidationInfo) -> list[str]:
        items = [item.strip() for item in value]
        if any(not item for item in items):
            raise ValueError(f"{info.field_name} must not contain empty strings.")
        return items

    @model_validator(mode="after")
    def _clarification_follows_gaps(self) -> ProductDescription:
        if self.missing_fields and not self.clarification_required:
            raise ValueError(
                "clarification_required must be true when missing_fields is not empty."
            )
        return self


# Callers of the generation pipeline use this name for the same card contract.
ProductCardOutput = ProductDescription


def openai_structured_schema() -> dict[str, Any]:
    """Return the product-card JSON schema for OpenAI structured outputs.

    Strict structured outputs reject keywords such as ``minLength``. Character
    limits remain on :class:`ProductDescription` and are checked after parsing.
    """
    schema = ProductDescription.model_json_schema()
    return _prepare_openai_schema(schema)


def _partition_specs(specs: dict[Any, Any]) -> tuple[dict[Any, Any], list[str]]:
    """Drop blank specification values and keep every other entry for validation."""
    cleaned: dict[Any, Any] = {}
    empty_fields: list[str] = []
    seen: set[str] = set()
    for key, value in specs.items():
        if not isinstance(key, str):
            raise ValueError(
                "Specification names must be strings, "
                f"but {_value_kind(key)} was provided."
            )
        name = key.strip()
        if not name:
            raise ValueError("Specification names must not be empty.")
        if name in seen:
            raise ValueError(
                f"Specification '{name}' is duplicated after trimming whitespace."
            )
        seen.add(name)
        if value is None or (isinstance(value, str) and value.strip() == ""):
            empty_fields.append(name)
            continue
        if not isinstance(value, str):
            raise ValueError(
                f"Specification '{name}' must be a string, but {_value_kind(value)} was provided."
            )
        cleaned[name] = value.strip()
    return cleaned, empty_fields


def _prepare_openai_schema(node: Any) -> Any:
    if isinstance(node, dict):
        prepared: dict[str, Any] = {}
        for key, value in node.items():
            if key in _OPENAI_UNSUPPORTED_KEYWORDS:
                continue
            prepared[key] = _prepare_openai_schema(value)
        if prepared.get("type") == "object":
            prepared["additionalProperties"] = False
            properties = prepared.get("properties")
            if isinstance(properties, dict):
                prepared["required"] = list(properties)
        return prepared
    if isinstance(node, list):
        return [_prepare_openai_schema(item) for item in node]
    return node


def _preserve_seo_length(info: ValidationInfo) -> bool:
    """Allow an out-of-range title or description only for the one-revision path.

    Normal validation stays strict. The generator passes this context after a
    length revision still misses the range, then records a warning. Empty text
    is never accepted through this path.
    """
    context = info.context
    return isinstance(context, dict) and context.get("preserve_seo_length") is True


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
