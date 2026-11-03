# Product Description AI Assistant

## 1. Project overview

The Product Description AI Assistant drafts B2B product cards for industrial measuring instruments. A content manager supplies a product name, manufacturer, technical specifications, and an optional description. The application asks an OpenAI model for a structured card, then checks that card against the source before showing it.

The page title is **AI Assistant for Product Descriptions**. The subtitle is **Generate accurate, SEO-optimized B2B product cards from technical product information.**

## 2. Business problem

Catalog copy for measuring instruments has to stay inside the technical data the manufacturer supplied. A generic language model will often fill gaps with typical ratings, materials, temperatures, or applications so that the text looks complete. Those additions are unsafe in a B2B catalog.

This application keeps generation, fact checking, and presentation separate so a manager can see the card, the missing characteristics, and the review warnings before publishing.

## 3. Key features

- JSON paste, `.json` upload, and a manual specification form share one input schema.
- The model returns a structured card: SEO title, SEO description, key features, search queries, and an internal sales pitch.
- Empty specification values are removed and reported. The model is told those names are missing.
- Feature values must match a supplied specification. Measurement tokens, pipe threads, metric threads, and IP ratings that do not appear in the source block publication.
- The SEO title must be at most 70 characters. The SEO description must be 800–1,200 characters. Search queries must be 3–5.
- If the length is still wrong after one revision, the accurate text is kept and a warning is shown. The application does not pad the text with new specifications.
- If that revision fails validation, the earlier grounded draft is kept and the rejected revision is discarded.
- Each generated card stays in the session. The manager can copy the text, download JSON, or download catalog Markdown.
- API keys stay in the environment. Errors shown in the page are redacted.

## 4. Technology stack

| Piece | Role |
| --- | --- |
| Python 3.11+ | Runtime |
| Streamlit | Content-manager page |
| Pydantic 2 | Input and output contracts |
| OpenAI Python SDK | Responses API with strict JSON schema |
| python-dotenv | Local environment loading |
| pytest | Automated tests with a mocked API |

## 5. Architecture overview

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

`app.py` presents the product and the card. It calls `generate_product_description()` and does not build prompts or call OpenAI.

`generator.py` validates the payload, builds the messages, requests one card, and checks the result. When the SEO length is outside the contract, it requests one revision and then revalidates.

`schemas.py` owns the Pydantic models and the OpenAI JSON schema. `prompts.py` owns the instructions. `llm_client.py` owns the HTTP call, timeouts, and error translation. `validators.py` owns JSON parsing and the deterministic checks. `config.py` loads `OPENAI_API_KEY` and `OPENAI_MODEL`.

## 6. Project structure

```text
Production-Description-AI-Assistant/
├── app.py
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── exceptions.py
│   ├── generator.py
│   ├── llm_client.py
│   ├── prompts.py
│   ├── schemas.py
│   └── validators.py
├── examples/
│   ├── pressure_gauge.json
│   ├── pressure_gauge_blank_spec.json
│   └── generated_results/
│       ├── pressure_gauge.json
│       └── pressure_gauge_blank_spec.json
├── tests/
├── .streamlit/config.toml
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```

## 7. Prerequisites

- Python 3.11 or newer.
- Network access to the OpenAI API when generating a live card.
- An OpenAI API key for a model that supports strict structured outputs.

Automated tests do not need a key and do not call the API.

## 8. Installation instructions

From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

On Windows PowerShell, activate with:

```powershell
.venv\Scripts\Activate.ps1
```

Open `.env` and set `OPENAI_API_KEY` to a real key. Set `OPENAI_MODEL` to a structured-output model available on that account.

## 9. Environment configuration

| Variable | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | Yes | OpenAI credential. Never commit it. |
| `OPENAI_MODEL` | Yes | Model id with structured-output support. |

`.env.example` contains the placeholder `your-api-key-here` and the model id `gpt-6-astra`. `load_settings()` rejects a missing key, a blank key, and known placeholders. The key is stored as a Pydantic `SecretStr`. Logs record the model id, not the key.

`.env` is listed in `.gitignore`. Only `.env.example` is meant to be committed.

## 10. How to run the application

With the virtual environment active and `.env` configured:

```bash
streamlit run app.py
```

Open `http://localhost:8501`.

`python app.py` does not start the server. It prints:

```text
Start the application with:
  streamlit run app.py
```

## 11. How to provide JSON input

Open the **JSON** tab.

- Paste a product object, or upload a `.json` file encoded as UTF-8.
- The page validates the text as it changes. Generate stays disabled until the payload is valid.
- A preview table shows the accepted specifications, including fields that were blank and removed.
- Choose an example from the selector to replace the editor contents.
- Invalid JSON, a missing name, a missing manufacturer, an empty name, an empty manufacturer, and a non-string specification each produce a field-level message.

Required shape:

```json
{
  "name": "Product name",
  "manufacturer": "Manufacturer",
  "specs": {
    "field_name": "value exactly as supplied"
  },
  "description": "Optional source description"
}
```

`name` and `manufacturer` are required non-empty strings. `specs` is a dictionary of strings. `description` may be omitted. Unknown top-level fields are rejected. Blank specification values, including whitespace and JSON `null`, are removed and recorded as missing.

## 12. How to use the manual form

Open the **Manual form** tab.

- Enter the product name and manufacturer.
- Add specification rows. Each row is a key and a value. Empty rows are ignored. Duplicate keys are rejected.
- The description is optional.
- Generate uses the same `ProductInput` parser and the same `generate_product_description()` service as the JSON tab.
- A blank form explains what is required and does not show a generation error.

## 13. Example input

The client assignment supplied one product, the DM 02 pressure gauge from Manotom. That payload is `examples/pressure_gauge.json`:

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

A second distinct product was not included in the assignment. `examples/pressure_gauge_blank_spec.json` is the same product with `accuracy_class` and `housing_diameter` left blank and the description left blank. It shows how missing characteristics are reported. It does not add specifications.

To add another real product, create a new file under `examples/` and copy in only the name, manufacturer, specifications, and description supplied by the client. Leave unknown characteristics out of `specs`. Do not fill typical values for a gauge or another instrument.

## 14. Example generated output

`examples/generated_results/` contains cards produced by `generate_product_description()` with the configured OpenAI model. They are model output saved after validation, not hand-written responses.

From `examples/pressure_gauge.json`, the saved card uses:

- SEO title: `Манометр DM 02 0–1.6 MPa, Manotom` (33 characters).
- SEO description: 940 characters, inside the 800–1,200 range.
- Four features whose values are `0–1.6 MPa`, `1.5`, `G1/2`, and `100 mm`.
- Four search queries.
- `clarification_required: true`, with missing characteristics such as measured medium, installation conditions, housing material, operating temperature, protection rating, mass, certification, and warranty.
- Two warnings that those characteristics were not in the source.

The sales pitch repeats the supplied range, accuracy class, connection, and housing diameter, and tells the manager to clarify the application before presenting the product.

From the blank-specification input, the saved card keeps only `0–1.6 MPa` and `G1/2` as features. It lists `description`, `accuracy_class`, and `housing_diameter` as missing. The description is 1,005 characters and the title is 37 characters.

Both files passed `assess_generated_output()` against their source products after they were written.

## 15. Prompt engineering decisions

The system prompt is a B2B industrial content specialist with ten mandatory restrictions:

1. Use only technical information explicitly provided.
2. Do not infer specifications from the product name or manufacturer.
3. Do not use general industry knowledge to fill missing values.
4. Do not invent certifications, ratings, temperatures, materials, warranty, or similar characteristics.
5. Do not assume a feature because similar products have it.
6. Report a missing specification.
7. Preserve numbers, units, and terminology exactly.
8. Do not convert values.
9. Do not state assumptions as facts.
10. Do not claim environment suitability unless the data supports it.

Customer-facing prose is Russian by default because the catalog audience is Russian-speaking, while specification tokens stay in the source language and symbols. The sales pitch is labeled as internal guidance for the content manager. The user message sends the source JSON plus `missing_spec_fields`, so blank specifications are named rather than omitted.

The model is asked for strict JSON matching `ProductDescription.openai_structured_schema()`. Length keywords that the strict subset rejects are removed from that schema. Character limits are checked in Python after parsing.

One revision is allowed when the title or description length is outside the contract. The revision message repeats the source, the restrictions, and the instruction not to add facts in order to reach the length.

## 16. Hallucination prevention strategy

Prevention is layered. None of the layers, including a clean scan, proves that every sentence is true.

**What the application does**

- The prompt forbids invented specifications, conversions, unsupported applications, and unsupported sales claims.
- Empty source specifications are passed to the model by name and must appear in `missing_fields`. A supplied specification cannot be listed as missing.
- Each key-feature value must match a source specification. Comparison ignores case, extra whitespace, and dash style (`-` and `–`).
- Duplicate feature names are rejected.
- Prose in the title, description, features, queries, sales pitch, and warnings is scanned for IP ratings, `G` pipe threads, `M` metric threads, and numbers attached to MPa, kPa, Pa, bar, mm, cm, kg, °C, `%`, or `m`. A token that is absent from the source raises `OutputValidationError`. The card is not published.
- When SEO length cannot be met from the source, the generator keeps the text and appends a warning. It does not invent specifications to reach 800 or 1,200 characters.
- A length revision that itself fails validation is discarded. The previous grounded draft is returned with the length warning and a note that the revision was discarded.
- The page always renders missing fields, the clarification flag, and every warning. When there are no warnings, it says so.

**What the application cannot guarantee**

- A bare number, an accuracy class written without a unit, a count, or a warranty written in words is outside the token scan.
- Certifications, materials, industries, and suitability claims are outside the scan unless they contain one of the patterns above.
- A token is treated as supported when the same text occurs anywhere in the source. That does not prove the surrounding sentence is true.
- Reformatted or calculated values can be missed. A coincidental overlap with source text can hide an unsupported use.
- The model may translate the supplied product name. The scanner does not treat that translation as an invented measurement.
- `missing_fields` can name characteristics the model considers relevant. Those names are gaps, not values, and they are not independently verified against a catalog.
- A warning-free card still needs a person to confirm the prose before it is published.

## 17. Error handling

| Exception | When it is raised | What the page shows |
| --- | --- | --- |
| `InvalidProductInputError` | Invalid JSON or an input schema failure | Field-level validation messages. Generate stays disabled. |
| `MissingAPIConfigurationError` | Missing or placeholder OpenAI settings | A configuration message. The key value is not included. |
| `APICommunicationError` | Network failure, server failure, or rejected credentials | A short API message. Secret-looking strings are replaced with `[redacted]`. |
| `RateLimitError` | HTTP 429 or the SDK rate-limit error | A rate-limit message without a traceback. |
| `InvalidLLMResponseError` | Empty response, refusal, non-object JSON, or a failed response | A response-validation message. |
| `OutputValidationError` | The card breaks the schema or contains an unsupported technical token | The validation errors. The card is not added to the session. |

The OpenAI client uses a 60-second timeout and `max_retries=0`. Transport and rate-limit failures propagate. They are not converted into a product card. Streamlit error details are disabled in `.streamlit/config.toml`.

## 18. Running automated tests

With the virtual environment active:

```bash
pytest
```

The suite mocks the OpenAI client. It covers valid and invalid JSON, a missing name, a missing manufacturer, empty specifications, an optional description, unexpected field types, a valid card, an SEO title over 70 characters, a description under 800 and over 1,200 characters, the wrong number of search queries, missing output fields, unsupported technical values, a successful mocked response, authentication failure, rate limiting, network errors, and an invalid structured response.

## 19. Known limitations

- The assignment contained one product. The second example is that product with unspecified fields left blank.
- Fact checking is deterministic and narrow. Section 16 lists what a clean result does not prove.
- The page keeps cards in the browser session only. There is no database, user account, or publish step.
- Generation depends on the configured model. A model that does not support strict structured outputs will fail the request.
- Customer-facing text is requested in Russian. Specification symbols stay as supplied, so a card mixes Russian prose with the original units.
- One length revision is the only automatic retry. A rate limit or network error is returned to the manager.

## 20. Possible future improvements

- Add a second client product when the real specification sheet is available.
- Let a reviewer accept or reject a card and export a batch.
- Extend the fact check with an explicit allow-list for materials and certifications once the client defines the vocabulary.
- Record which source field supported each sentence, so a reviewer can see the link without re-reading the input.
