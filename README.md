# Product Description AI Assistant

Lightweight foundation for drafting B2B product cards for industrial measuring instruments. The application will turn structured product facts into an SEO title, an SEO description, key features, search queries, and a short sales pitch for the content manager.

Content managers use the Streamlit page to paste product JSON or fill in a form. The page calls the generation service and keeps each product card separate.

## Architecture

```text
app.py                         Streamlit page: input, results, export
        |
        v
src/generator.py               validate input -> request a card -> validate output
        |                               |
        v                               v
src/validators.py                 src/llm_client.py
        |                               |
        v                               v
src/schemas.py                    src/config.py
src/prompts.py                    src/exceptions.py
```

`app.py` only presents the product and the card. `generator.py` validates the payload, asks `LLMClient` for a card, and checks that card against the original product.

`schemas.py` owns the Pydantic contracts. `validators.py` owns JSON parsing and the rule that technical specifications are copied from the source. `prompts.py` owns the instructions sent to the model. `config.py` loads `OPENAI_API_KEY` and `OPENAI_MODEL` from the environment.

## Input

`name` and `manufacturer` are required. `description` is optional. `specs` is an open dictionary of strings, so a new specification field does not require a schema change.

Blank specification values, including whitespace and JSON `null`, are removed from `specs` and recorded on `ProductInput.empty_spec_fields`. Numbers, booleans, and nested objects are rejected. Invalid JSON and unknown top-level fields produce a field-level error.

```json
{
  "name": "DM 02 Pressure Gauge",
  "manufacturer": "Manotom",
  "specs": {
    "measurement_range": "0–1.6 MPa",
    "accuracy_class": "1.5",
    "connection": "G1/2",
    "housing_diameter": "100 mm"
  },
  "description": "The device is designed to measure gauge pressure."
}
```

## Output

A product card contains:

| Field | Contract |
| --- | --- |
| `name`, `manufacturer` | Copied from the source |
| `seo_title` | 1–70 characters |
| `seo_description` | 800–1,200 characters |
| `key_features` | Objects with `name`, `value`, and `explanation` |
| `search_queries` | 3–5 distinct queries |
| `sales_pitch` | Short note for the content manager |
| `missing_fields` | Source fields that were empty or unavailable |
| `clarification_required` | `true` whenever `missing_fields` is not empty |
| `warnings` | Review notes |

Feature values must match a supplied specification. Comparison ignores case, extra whitespace, and dash style (`-` and `–` are the same fact). Prose is also scanned for measurement tokens, thread sizes, and IP ratings that do not appear in the source. A provided specification cannot be listed as missing. An empty specification must be listed, and `clarification_required` is then `true`.

Character limits are enforced by Pydantic after parsing. `openai_structured_schema()` exports the same card for OpenAI strict structured outputs and drops keywords that subset does not accept, such as `minLength`.

## Configuration

Copy the example environment file and set a real key locally:

```bash
cp .env.example .env
```

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes | OpenAI credential. Never commit it. |
| `OPENAI_MODEL` | Yes | Model id with structured-output support. The example uses `gpt-6-astra`. |

`load_settings()` reads the process environment after loading `.env`. A missing value or the placeholder from `.env.example` raises `MissingAPIConfigurationError`. The key is stored as a secret and is not written to logs.

## Exceptions

| Exception | When it is raised |
| --- | --- |
| `InvalidProductInputError` | Invalid JSON or an input schema failure |
| `MissingAPIConfigurationError` | Missing or placeholder OpenAI settings |
| `APICommunicationError` | Network, server, or credential failure |
| `RateLimitError` | HTTP 429 or the SDK rate-limit error |
| `InvalidLLMResponseError` | Empty response, refusal, or non-JSON model output |
| `OutputValidationError` | JSON that breaks the card contract or invents specifications |

`translate_api_error()` maps an SDK exception onto `RateLimitError` or `APICommunicationError`. The Streamlit page shows those messages and does not display API keys or tracebacks.

## Project layout

```text
product-description-ai/
├── app.py
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── schemas.py
│   ├── prompts.py
│   ├── llm_client.py
│   ├── generator.py
│   ├── validators.py
│   └── exceptions.py
├── examples/
│   ├── pressure_gauge.json
│   └── pressure_gauge_blank_spec.json
├── tests/
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## Setup

Python 3.11 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest
streamlit run app.py
```

Open `http://localhost:8501`. Copy `.env.example` to `.env` and set `OPENAI_API_KEY` and `OPENAI_MODEL` before generating a card. `python app.py` only prints the Streamlit command.

## Tests

The suite covers configuration, both schemas, JSON and type errors, empty specifications, invented measurements, prompt content, the generation boundary, dependency imports, `requirements.txt`, `.env.example`, and `.gitignore`.

## Interface

`streamlit run app.py` opens the content-manager page. JSON and the manual form both use `ProductInput`. Generate calls `generate_product_description()`. Each card stays in the session until it is removed. JSON and Markdown downloads use the output schema and a catalog-style document.
