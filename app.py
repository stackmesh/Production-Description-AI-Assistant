"""Entry point for the Product Description AI Assistant.

The Streamlit interface will be added in a later milestone. Running this file
confirms the foundation package imports and prints how to run the tests.
"""

from __future__ import annotations

from src import __version__


def main() -> None:
    """Print the milestone status and exit."""
    print(
        "Product Description AI Assistant "
        f"{__version__}\n"
        "Generation pipeline is ready: prompts, OpenAI structured output, and validation.\n"
        "Next milestone: the Streamlit interface.\n"
        "Run the test suite with: pytest"
    )


if __name__ == "__main__":
    main()
