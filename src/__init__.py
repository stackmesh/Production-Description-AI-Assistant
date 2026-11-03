"""Product Description AI Assistant.

This package drafts product cards from supplied facts: configuration, input
and output schemas, prompts, the OpenAI call, and validation. The Streamlit
interface is a later milestone.
"""

from __future__ import annotations

import sys

if sys.version_info < (3, 11):
    raise RuntimeError(
        "Product Description AI Assistant requires Python 3.11 or newer. "
        f"This interpreter is {sys.version.split()[0]}."
    )

__version__ = "0.1.0"
