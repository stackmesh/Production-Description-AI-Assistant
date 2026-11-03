"""Foundation files required by the assignment stay present and safe."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "app.py",
    "src/__init__.py",
    "src/config.py",
    "src/schemas.py",
    "src/prompts.py",
    "src/llm_client.py",
    "src/generator.py",
    "src/validators.py",
    "src/exceptions.py",
    "examples/pressure_gauge.json",
    "examples/pressure_gauge_blank_spec.json",
    ".env.example",
    ".gitignore",
    "requirements.txt",
    "README.md",
)


def test_required_files_exist() -> None:
    missing = [name for name in REQUIRED_FILES if not (ROOT / name).is_file()]
    assert missing == []


def test_requirements_list_the_stack() -> None:
    packages = set()
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        entry = line.strip()
        if not entry or entry.startswith("#"):
            continue
        name = entry.split(">=")[0].split("==")[0].split("[")[0].strip().lower()
        packages.add(name)
    assert {
        "openai",
        "pydantic",
        "python-dotenv",
        "pytest",
        "streamlit",
    } <= packages


def test_env_example_has_placeholders_only() -> None:
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "OPENAI_API_KEY=your-api-key-here" in text
    assert "OPENAI_MODEL=gpt-6-astra" in text
    assert "sk-proj-" not in text
    assert "sk-live-" not in text


def test_gitignore_excludes_env_and_secret_files() -> None:
    text = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        ".env",
        ".env.*",
        "!.env.example",
        "credentials.json",
        "secrets.json",
        ".streamlit/secrets.toml",
        "*.pem",
        "*.key",
    ):
        assert pattern in text
