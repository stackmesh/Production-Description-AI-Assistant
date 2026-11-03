"""Environment configuration for the OpenAI client.

API keys are read from the environment or a local ``.env`` file. They are
never hardcoded and never written to logs.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, SecretStr

from src.exceptions import MissingAPIConfigurationError

logger = logging.getLogger(__name__)

_PLACEHOLDER_API_KEYS = frozenset(
    {
        "your-api-key-here",
        "sk-your-key",
        "sk-...",
        "changeme",
        "replace-me",
    }
)
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


class Settings(BaseModel):
    """Validated OpenAI settings.

    ``openai_api_key`` is a secret. Use :attr:`api_key` when constructing the
    SDK client, and avoid dumping the model to JSON.
    """

    model_config = ConfigDict(frozen=True)

    openai_api_key: SecretStr
    openai_model: str

    @property
    def api_key(self) -> str:
        """Return the API key for the OpenAI SDK."""
        return self.openai_api_key.get_secret_value()


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Load and validate ``OPENAI_API_KEY`` and ``OPENAI_MODEL``.

    When ``environ`` is omitted, a ``.env`` file in the working directory is
    loaded first. Variables already set in the process environment take
    precedence over that file.

    Args:
        environ: Optional mapping used instead of the process environment.
            Tests pass this so they do not depend on a real ``.env`` file.

    Returns:
        Validated settings for the configured model.

    Raises:
        MissingAPIConfigurationError: A required variable is missing, blank,
            or still set to a placeholder from ``.env.example``.
    """
    if environ is None:
        load_dotenv()
        source: Mapping[str, str] = os.environ
    else:
        source = environ

    api_key = _as_text(source.get("OPENAI_API_KEY"))
    model = _as_text(source.get("OPENAI_MODEL"))
    problems = _configuration_problems(api_key, model)
    if problems:
        message = " ".join(problems)
        logger.error("OpenAI configuration is invalid: %s", message)
        raise MissingAPIConfigurationError(message)

    settings = Settings(openai_api_key=SecretStr(api_key), openai_model=model)
    logger.info("OpenAI configuration loaded for model %s", settings.openai_model)
    return settings


def _as_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _configuration_problems(api_key: str, model: str) -> list[str]:
    problems: list[str] = []
    if not api_key:
        problems.append(
            "OPENAI_API_KEY is missing. Set it in the environment or in a .env file "
            "(see .env.example). Never commit the real key."
        )
    elif api_key.casefold() in _PLACEHOLDER_API_KEYS:
        problems.append(
            "OPENAI_API_KEY is still the placeholder from .env.example. "
            "Replace it with a real key and keep that file out of git."
        )

    if not model:
        problems.append(
            "OPENAI_MODEL is missing. Set it to a current OpenAI model that "
            "supports structured outputs, such as gpt-6-astra."
        )
    elif _MODEL_ID.fullmatch(model) is None:
        problems.append(
            "OPENAI_MODEL must be a model id without spaces, such as gpt-6-astra. "
            f"The current value is {model!r}."
        )
    return problems
