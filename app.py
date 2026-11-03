"""Streamlit interface for content managers.

The page collects product facts, calls the generation service, and presents
the card. Prompt text, the OpenAI request, and factual checks stay in
``src``.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import streamlit as st

from src.exceptions import (
    APICommunicationError,
    InvalidLLMResponseError,
    InvalidProductInputError,
    MissingAPIConfigurationError,
    OutputValidationError,
    ProductDescriptionError,
    RateLimitError,
)
from src.generator import generate_product_description
from src.schemas import (
    SEO_DESCRIPTION_MAX,
    SEO_DESCRIPTION_MIN,
    SEO_TITLE_MAX,
    ProductDescription,
    ProductInput,
)
from src.validators import assess_generated_output, parse_product_input

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
_EXAMPLES = _ROOT / "examples"
_EXAMPLE_FILES = {
    "Complete pressure gauge": "pressure_gauge.json",
    "Pressure gauge with blank specifications": "pressure_gauge_blank_spec.json",
}
_SECRET = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass(frozen=True)
class InputCheck:
    """A product that is ready to generate, or the messages blocking it."""

    product: ProductInput | None
    heading: str
    details: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return self.product is not None and not self.details


def check_product_input(payload: str | dict[str, Any]) -> InputCheck:
    """Validate one product payload with the shared input parser."""
    if isinstance(payload, str) and not payload.strip():
        return InputCheck(
            None,
            "Product JSON is empty.",
            ("Paste a JSON object or upload a .json file.",),
        )
    try:
        product = parse_product_input(payload)
    except InvalidProductInputError as exc:
        details = exc.errors or (str(exc),)
        return InputCheck(
            None,
            _validation_heading(str(exc)),
            tuple(_public_text(item) for item in details),
        )
    return InputCheck(product, "", ())


def collect_specification_rows(
    rows: list[tuple[str, str]],
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Turn form rows into a specification dictionary.

    Blank rows are ignored. A value without a name, or the same name twice,
    is reported and left out of the dictionary so generation stays disabled.
    """
    specs: dict[str, str] = {}
    problems: list[str] = []
    for key, value in rows:
        spec_name = key.strip()
        spec_value = value.strip()
        if not spec_name and not spec_value:
            continue
        if not spec_name:
            problems.append("A specification value was entered without a name.")
            continue
        if spec_name in specs:
            problems.append(f"Specification '{spec_name}' is listed more than once.")
            continue
        specs[spec_name] = spec_value
    return specs, tuple(problems)


def manual_product_payload(
    name: str,
    manufacturer: str,
    specification_rows: list[tuple[str, str]],
    description: str,
) -> tuple[dict[str, Any] | None, tuple[str, ...]]:
    """Build the product dictionary used by the manual form."""
    specs, problems = collect_specification_rows(specification_rows)
    if problems:
        return None, problems
    return {
        "name": name,
        "manufacturer": manufacturer,
        "specs": specs,
        "description": description,
    }, ()


def render_json(card: ProductDescription) -> str:
    """Serialize a card with the output-schema fields and readable Unicode."""
    return json.dumps(card.model_dump(), ensure_ascii=False, indent=2)


def render_markdown(card: ProductDescription) -> str:
    """Render a card as catalog Markdown a content manager can paste."""
    title_count, title_ok = _title_limit(card.seo_title)
    description_count, description_ok = _description_limit(card.seo_description)
    feature_rows = [
        "| Feature | Value | Explanation |",
        "| --- | --- | --- |",
    ]
    if card.key_features:
        for feature in card.key_features:
            feature_rows.append(
                "| "
                + " | ".join(
                    (
                        _table_cell(feature.name),
                        _table_cell(feature.value),
                        _table_cell(feature.explanation),
                    )
                )
                + " |"
            )
    else:
        feature_rows.append("| — | — | No specifications were supplied. |")

    queries = "\n".join(
        f"{index}. {query}" for index, query in enumerate(card.search_queries, start=1)
    )
    if card.missing_fields:
        missing = "\n".join(f"- {name}" for name in card.missing_fields)
    else:
        missing = "- None listed."
    clarification = "Yes" if card.clarification_required else "No"
    if card.warnings:
        warnings = "\n".join(f"- {warning}" for warning in card.warnings)
    else:
        warnings = "- No validation warnings."

    return "\n".join(
        (
            f"# {card.name}",
            "",
            f"**Manufacturer:** {card.manufacturer}",
            "",
            "## SEO title",
            "",
            card.seo_title,
            "",
            (
                f"{title_count} / {SEO_TITLE_MAX} characters. "
                + ("Within the limit." if title_ok else "Over the limit.")
            ),
            "",
            "## SEO description",
            "",
            card.seo_description,
            "",
            (
                f"{description_count} characters. Required range: "
                f"{SEO_DESCRIPTION_MIN}–{SEO_DESCRIPTION_MAX}. "
                + (
                    "Within the required range."
                    if description_ok
                    else "Outside the required range."
                )
            ),
            "",
            "## Key features",
            "",
            "\n".join(feature_rows),
            "",
            "## SEO search queries",
            "",
            queries,
            "",
            "## Sales pitch",
            "",
            "Internal note for the content manager. This is not customer-facing catalog copy.",
            "",
            card.sales_pitch,
            "",
            "## Missing information",
            "",
            f"Clarification required: {clarification}",
            "",
            missing,
            "",
            "Characteristics listed here need a confirmed value before the product is presented to a buyer.",
            "",
            "## Validation warnings",
            "",
            warnings,
            "",
        )
    )


def append_result(
    results: list[dict[str, Any]],
    product: ProductInput,
    card: ProductDescription,
) -> list[dict[str, Any]]:
    """Return a new result list that keeps every earlier card."""
    stored = list(results)
    stored.append(
        {
            "id": uuid.uuid4().hex,
            "product": product,
            "card": card,
        }
    )
    return stored


def main() -> None:
    """Render the content-manager page."""
    st.set_page_config(
        page_title="AI Assistant for Product Descriptions",
        layout="wide",
    )
    _init_state()
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.5rem; max-width: 980px; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("AI Assistant for Product Descriptions")
    st.markdown(
        "Generate accurate, SEO-optimized B2B product cards from technical product information."
    )
    st.caption(
        "For content managers working with industrial measuring instruments. "
        "The draft uses only the facts you supply."
    )

    json_tab, form_tab = st.tabs(["JSON input", "Manual product form"])
    with json_tab:
        _render_json_tab()
    with form_tab:
        _render_form_tab()

    st.divider()
    _render_results()


def _init_state() -> None:
    st.session_state.setdefault("results", [])
    st.session_state.setdefault("json_text", _example_text("pressure_gauge.json"))
    st.session_state.setdefault("json_upload_error", None)
    st.session_state.setdefault("generation_error", None)
    st.session_state.setdefault("form_name", "")
    st.session_state.setdefault("form_manufacturer", "")
    st.session_state.setdefault("form_description", "")
    st.session_state.setdefault("example_choice", "Complete pressure gauge")
    if "spec_row_ids" not in st.session_state:
        st.session_state.spec_row_ids = []
        _add_spec()


def _render_json_tab() -> None:
    st.subheader("Product JSON")
    st.markdown(
        "Paste a product object or upload a `.json` file. "
        "The editor starts with a complete example."
    )
    choice_col, button_col = st.columns([3, 1], vertical_alignment="bottom")
    with choice_col:
        st.selectbox(
            "Example template",
            list(_EXAMPLE_FILES),
            key="example_choice",
            help="Insert one of the supplied example products into the editor.",
        )
    with button_col:
        st.button("Insert example", on_click=_insert_example, use_container_width=True)

    st.file_uploader(
        "Upload a .json file",
        type=["json"],
        key="json_upload",
        on_change=_apply_upload,
        help="The file replaces the text in the editor. You can still edit it before generating.",
    )
    if st.session_state.json_upload_error:
        st.error(st.session_state.json_upload_error)

    st.text_area(
        "Product JSON",
        key="json_text",
        height=280,
        help="Required fields are name, manufacturer, and specs. description is optional.",
    )
    check = check_product_input(st.session_state.json_text)
    _render_check(check)
    _generate_button("generate_json", check)


def _render_form_tab() -> None:
    st.subheader("Product details")
    st.text_input(
        "Product name",
        key="form_name",
        placeholder="DM 02 Pressure Gauge",
    )
    st.text_input(
        "Manufacturer",
        key="form_manufacturer",
        placeholder="Manotom",
    )
    st.markdown("**Technical specifications**")
    st.caption(
        "Add one characteristic per row. Leave the value blank when that characteristic is missing."
    )
    header_name, header_value, _header_action = st.columns(
        [3, 3, 1],
        vertical_alignment="bottom",
    )
    header_name.caption("Specification")
    header_value.caption("Value")
    for row_id in list(st.session_state.spec_row_ids):
        name_col, value_col, action_col = st.columns(
            [3, 3, 1],
            vertical_alignment="bottom",
        )
        with name_col:
            st.text_input(
                "Specification",
                key=f"spec_name_{row_id}",
                label_visibility="collapsed",
                placeholder="measurement_range",
            )
        with value_col:
            st.text_input(
                "Value",
                key=f"spec_value_{row_id}",
                label_visibility="collapsed",
                placeholder="0–1.6 MPa",
            )
        with action_col:
            st.button(
                "Remove",
                key=f"remove_spec_{row_id}",
                on_click=_remove_spec,
                args=(row_id,),
                use_container_width=True,
            )
    st.button("Add specification", on_click=_add_spec)
    st.text_area(
        "Product description",
        key="form_description",
        height=140,
        placeholder="Optional. Use the wording supplied with the product.",
        help="Leave this empty when the source has no description.",
    )
    rows = _spec_rows()
    payload, row_problems = manual_product_payload(
        st.session_state.form_name,
        st.session_state.form_manufacturer,
        rows,
        st.session_state.form_description,
    )
    if _form_is_blank(rows):
        check = InputCheck(
            None,
            "Enter the product name and manufacturer.",
            ("Add specifications when you have them. A blank value is recorded as missing.",),
        )
    elif row_problems:
        check = InputCheck(None, "The specifications need to be corrected.", row_problems)
    else:
        check = check_product_input(payload or {})
    _render_check(check)
    _generate_button("generate_form", check)


def _render_check(check: InputCheck) -> None:
    if check.valid and check.product is not None:
        st.success("The product information is valid.")
        _render_preview(check.product)
        return
    if check.heading in {
        "Product JSON is empty.",
        "Enter the product name and manufacturer.",
    }:
        st.info(check.heading)
    else:
        st.error(check.heading or "The product information needs to be corrected.")
    for detail in check.details:
        st.markdown(f"- {detail}")


def _render_preview(product: ProductInput) -> None:
    st.markdown("**Parsed product**")
    name_col, maker_col = st.columns(2)
    name_col.markdown(f"**Product name**  \n{product.name}")
    maker_col.markdown(f"**Manufacturer**  \n{product.manufacturer}")
    if product.description:
        st.markdown("**Description**")
        st.write(product.description)
    else:
        st.caption("No product description was supplied.")
    if product.specs:
        st.markdown(_spec_table(product.specs))
    else:
        st.info("No specification values were supplied.")
    if product.empty_spec_fields:
        names = ", ".join(product.empty_spec_fields)
        st.warning(
            "These specifications are empty and will be reported as missing: " + names
        )


def _generate_button(key: str, check: InputCheck) -> None:
    if not check.valid:
        st.caption("Generation is unavailable until the product information is valid.")
    clicked = st.button(
        "Generate Product Card",
        key=key,
        type="primary",
        disabled=not check.valid,
    )
    if clicked and check.product is not None:
        _generate(check.product)


def _generate(product: ProductInput) -> None:
    try:
        with st.spinner("Generating the product card from the supplied facts…"):
            card = generate_product_description(product)
            assess_generated_output(card.model_dump(), product)
    except ProductDescriptionError as exc:
        logger.error("Product card generation failed: %s", type(exc).__name__)
        st.session_state.generation_error = _generation_failure(exc)
    except Exception as exc:
        logger.error("Product card generation failed: %s", type(exc).__name__)
        st.session_state.generation_error = (
            "The product card could not be generated.",
            ("Try again in a moment. If this continues, check the server log.",),
        )
        del exc
    else:
        st.session_state.generation_error = None
        st.session_state.results = append_result(st.session_state.results, product, card)
        st.toast("Product card added. Earlier cards are unchanged.")


def _render_results() -> None:
    st.subheader("Generated product cards")
    st.markdown(
        "Each product stays in its own section. Generating another card adds a result and leaves the others in place."
    )
    failure = st.session_state.generation_error
    if failure:
        heading, details = failure
        st.error(heading)
        for detail in details:
            st.markdown(f"- {detail}")
    results = st.session_state.results
    if not results:
        st.info("Generated cards appear here after you choose Generate Product Card.")
        return
    for item in reversed(results):
        _render_result(item)


def _render_result(item: dict[str, Any]) -> None:
    card: ProductDescription = item["card"]
    with st.container(border=True):
        st.markdown(f"### {card.name}")
        st.caption(card.manufacturer)

        st.markdown("#### Product information")
        info_name, info_maker = st.columns(2)
        info_name.markdown(f"**Product name**  \n{card.name}")
        info_maker.markdown(f"**Manufacturer**  \n{card.manufacturer}")

        title_count, title_ok = _title_limit(card.seo_title)
        st.markdown("#### SEO title")
        st.write(card.seo_title)
        if title_ok:
            st.caption(f"{title_count} / {SEO_TITLE_MAX} characters. Within the 70-character limit.")
        else:
            st.warning(
                f"{title_count} / {SEO_TITLE_MAX} characters. Over the 70-character limit."
            )

        description_count, description_ok = _description_limit(card.seo_description)
        st.markdown("#### SEO description")
        st.write(card.seo_description)
        if description_ok:
            st.caption(
                f"{description_count} characters. Within the "
                f"{SEO_DESCRIPTION_MIN}–{SEO_DESCRIPTION_MAX} character requirement."
            )
        else:
            st.warning(
                f"{description_count} characters. Outside the "
                f"{SEO_DESCRIPTION_MIN}–{SEO_DESCRIPTION_MAX} character requirement."
            )

        st.markdown("#### Key features")
        if card.key_features:
            st.markdown(_feature_table(card))
        else:
            st.info("No key features were produced because the source has no specification values.")

        st.markdown("#### SEO search queries")
        for index, query in enumerate(card.search_queries, start=1):
            st.markdown(f"{index}. {query}")
        st.caption(f"{len(card.search_queries)} queries. The card is expected to contain 3–5.")

        st.markdown("#### Sales pitch")
        st.caption("Internal note for the content manager. This is not customer-facing catalog copy.")
        st.info(card.sales_pitch)

        st.markdown("#### Missing information")
        if card.clarification_required or card.missing_fields:
            st.error(
                "Additional confirmation is required before this product is presented to a buyer."
            )
        else:
            st.success("No missing source fields were reported.")
        if card.missing_fields:
            st.markdown(
                "These characteristics need a confirmed value, or a decision that they do not apply:"
            )
            for name in card.missing_fields:
                st.markdown(f"- **{name}**")
        elif card.clarification_required:
            st.markdown(
                "Clarification is required even though no blank source field was named. "
                "Review the warnings before publishing."
            )
        else:
            st.caption("Clarification required: no.")

        st.markdown("#### Validation warnings")
        if card.warnings:
            for warning in card.warnings:
                st.warning(warning)
        else:
            st.success("No factual or SEO length warnings were recorded for this card.")

        st.markdown("#### Copy and export")
        markdown = render_markdown(card)
        copy_key = f"copy_{item['id']}"
        st.session_state[copy_key] = markdown
        st.text_area(
            "Copy-friendly text",
            height=220,
            key=copy_key,
            help="Select the text and copy it, or download the Markdown file.",
        )
        json_col, markdown_col, remove_col = st.columns([1, 1, 1])
        filename = _download_stem(card.name)
        with json_col:
            st.download_button(
                "Download JSON",
                data=render_json(card),
                file_name=f"{filename}.json",
                mime="application/json",
                key=f"download_json_{item['id']}",
                use_container_width=True,
            )
        with markdown_col:
            st.download_button(
                "Download Markdown",
                data=markdown,
                file_name=f"{filename}.md",
                mime="text/markdown",
                key=f"download_md_{item['id']}",
                use_container_width=True,
            )
        with remove_col:
            st.button(
                "Remove this card",
                key=f"remove_card_{item['id']}",
                on_click=_remove_result,
                args=(item["id"],),
                use_container_width=True,
            )


def _form_is_blank(rows: list[tuple[str, str]]) -> bool:
    if str(st.session_state.form_name).strip():
        return False
    if str(st.session_state.form_manufacturer).strip():
        return False
    if str(st.session_state.form_description).strip():
        return False
    return all(not name.strip() and not value.strip() for name, value in rows)


def _spec_rows() -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for row_id in st.session_state.spec_row_ids:
        name = str(st.session_state.get(f"spec_name_{row_id}", ""))
        value = str(st.session_state.get(f"spec_value_{row_id}", ""))
        rows.append((name, value))
    return rows


def _add_spec() -> None:
    row_id = uuid.uuid4().hex
    st.session_state.spec_row_ids.append(row_id)
    st.session_state[f"spec_name_{row_id}"] = ""
    st.session_state[f"spec_value_{row_id}"] = ""


def _remove_spec(row_id: str) -> None:
    ids: list[str] = st.session_state.spec_row_ids
    if row_id in ids:
        ids.remove(row_id)
    st.session_state.pop(f"spec_name_{row_id}", None)
    st.session_state.pop(f"spec_value_{row_id}", None)
    if not st.session_state.spec_row_ids:
        _add_spec()


def _remove_result(result_id: str) -> None:
    st.session_state.results = [
        item for item in st.session_state.results if item["id"] != result_id
    ]


def _insert_example() -> None:
    filename = _EXAMPLE_FILES[st.session_state.example_choice]
    st.session_state.json_text = _example_text(filename)
    st.session_state.json_upload_error = None


def _apply_upload() -> None:
    uploaded = st.session_state.get("json_upload")
    if uploaded is None:
        return
    try:
        text = uploaded.getvalue().decode("utf-8-sig")
    except UnicodeDecodeError:
        st.session_state.json_upload_error = "The uploaded file is not valid UTF-8 text."
        return
    st.session_state.json_upload_error = None
    st.session_state.json_text = text


def _example_text(filename: str) -> str:
    return (_EXAMPLES / filename).read_text(encoding="utf-8")


def _generation_failure(exc: ProductDescriptionError) -> tuple[str, tuple[str, ...]]:
    heading = {
        MissingAPIConfigurationError: "OpenAI is not configured.",
        RateLimitError: "The OpenAI rate limit was reached.",
        APICommunicationError: "The OpenAI request failed.",
        InvalidLLMResponseError: "The model response could not be used.",
        OutputValidationError: "The generated card did not pass validation.",
        InvalidProductInputError: "The product information is not valid.",
    }.get(type(exc), "The product card could not be generated.")
    details: list[str] = []
    message = _public_text(str(exc)).strip()
    if message:
        details.append(message)
    extra = getattr(exc, "errors", ())
    for item in extra:
        text = _public_text(str(item)).strip()
        if text and text not in details and text not in message:
            details.append(text)
    if not details:
        details.append("No further detail is available.")
    return heading, tuple(details)


def _validation_heading(message: str) -> str:
    lowered = message.casefold()
    if "not valid json" in lowered or lowered.startswith("product input is empty"):
        return "The JSON syntax is invalid."
    if "json object" in lowered or "binary data" in lowered:
        return "The JSON must be an object."
    if "product name must not be empty" in lowered:
        return "The product name is empty."
    if "manufacturer must not be empty" in lowered:
        return "The manufacturer is empty."
    if "required" in lowered:
        return "A required field is missing."
    if any(
        token in lowered
        for token in ("must be a string", "a number", "a boolean", "an object", "a list", "binary")
    ):
        return "A field has the wrong type."
    return "The product information needs to be corrected."


def _title_limit(title: str) -> tuple[int, bool]:
    count = len(title)
    return count, 0 < count <= SEO_TITLE_MAX


def _description_limit(description: str) -> tuple[int, bool]:
    count = len(description)
    return count, SEO_DESCRIPTION_MIN <= count <= SEO_DESCRIPTION_MAX


def _spec_table(specs: dict[str, str]) -> str:
    lines = ["| Specification | Value |", "| --- | --- |"]
    for name, value in specs.items():
        lines.append(f"| {_table_cell(name)} | {_table_cell(value)} |")
    return "\n".join(lines)


def _feature_table(card: ProductDescription) -> str:
    lines = ["| Feature | Value | Explanation |", "| --- | --- | --- |"]
    for feature in card.key_features:
        lines.append(
            "| "
            + " | ".join(
                (
                    _table_cell(feature.name),
                    _table_cell(feature.value),
                    _table_cell(feature.explanation),
                )
            )
            + " |"
        )
    return "\n".join(lines)


def _table_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _download_stem(name: str) -> str:
    cleaned = _FILENAME.sub("-", name).strip("-").lower()
    return (cleaned or "product-card")[:60] + "-product-card"


def _public_text(text: str) -> str:
    return _SECRET.sub("[redacted]", text)


if __name__ == "__main__":
    from streamlit.runtime.scriptrunner import get_script_run_ctx

    if get_script_run_ctx(suppress_warning=True) is None:
        print("Start the application with:\n  streamlit run app.py")
    else:
        main()
