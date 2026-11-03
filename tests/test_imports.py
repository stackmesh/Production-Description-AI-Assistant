"""Every foundation module and declared dependency imports."""

from __future__ import annotations

import importlib
import os

os.environ.setdefault("STREAMLIT_BROWSER_GATHER_USAGE_STATS", "false")

import pytest

MODULES = (
    "src",
    "src.config",
    "src.schemas",
    "src.prompts",
    "src.llm_client",
    "src.generator",
    "src.validators",
    "src.exceptions",
    "app",
    "dotenv",
    "openai",
    "pydantic",
    "pytest",
    "streamlit",
)


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    importlib.import_module(module_name)
