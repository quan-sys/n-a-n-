from __future__ import annotations

import pandas as pd

from src.ingestion.official_finance_document_downloader import download_seed_documents
from src.ingestion.official_finance_document_seed import (
    SEED_COLUMNS,
    load_document_seed_schema,
    validate_document_seed_rows,
)


def test_01ib_seed_schema_valid_for_example_columns():
    schema = load_document_seed_schema()

    assert schema["required_columns"] == SEED_COLUMNS
    assert "financial_statement" in schema["allowed_values"]["document_type"]
    assert "exchange_filing" in schema["allowed_values"]["source_type"]


def test_01ib_missing_required_field_invalidates_seed_row():
    seed = _seed_df(source_url="")

    result = validate_document_seed_rows(seed)
    invalid = result["invalid_seed_rows"]

    assert len(invalid) == 1
    assert "MISSING_REQUIRED_FIELD:source_url" in invalid.iloc[0]["validation_errors"]


def test_01ib_invalid_url_goes_to_manual_review_without_download(tmp_path):
    seed = _seed_df(source_url="C:/not/a/public/url.pdf")
    valid = validate_document_seed_rows(seed)["valid_seed_rows"]
    invalid = validate_document_seed_rows(seed)["invalid_seed_rows"]

    assert valid.empty
    assert "SOURCE_URL_INVALID" in invalid.iloc[0]["validation_errors"]

    result = download_seed_documents(seed, raw_output_dir=tmp_path, dry_run=False)
    index = result["finance_document_index"]
    review = result["manual_review_queue"]
    assert index.iloc[0]["download_status"] == "SOURCE_URL_INVALID"
    assert bool(index.iloc[0]["manual_review_required"]) is True
    assert len(review) == 1


def test_01ib_deduplicates_duplicate_seed_rows():
    seed = pd.concat([_seed_df(), _seed_df()], ignore_index=True)

    result = validate_document_seed_rows(seed)

    assert len(result["valid_seed_rows"]) == 1
    assert len(result["duplicate_seed_rows"]) == 1
    assert "DUPLICATE_SEED_ROW" in result["invalid_seed_rows"].iloc[0]["validation_errors"]


def test_01ib_dry_run_does_not_create_raw_download(tmp_path):
    seed = validate_document_seed_rows(_seed_df())["valid_seed_rows"]

    result = download_seed_documents(seed, raw_output_dir=tmp_path / "raw", dry_run=True)

    index = result["finance_document_index"]
    assert len(index) == 1
    row = index.iloc[0]
    assert row["download_status"] == "DRY_RUN_VALIDATED"
    assert row["download_status"] != "DOWNLOADED"
    assert row["local_path"] == ""
    assert row["file_hash"] == ""
    assert row["http_status"] == ""
    assert row["content_type"] == ""
    assert row["detected_file_type"] == "pdf"
    assert not (tmp_path / "raw").exists()


def test_01ib_dry_run_domain_mismatch_requires_review_not_download(tmp_path):
    seed = validate_document_seed_rows(
        _seed_df(source_url="https://cdn.example/aaa.pdf", official_domain="official.example")
    )["valid_seed_rows"]

    result = download_seed_documents(seed, raw_output_dir=tmp_path / "raw", dry_run=True)

    row = result["finance_document_index"].iloc[0]
    assert row["download_status"] == "DOMAIN_MISMATCH_REVIEW"
    assert bool(row["manual_review_required"]) is True
    assert row["local_path"] == ""
    assert row["file_hash"] == ""


def test_01ib_discovery_period_is_valid_for_seed_links():
    seed = _seed_df(period="DISCOVERY", document_type="ir_page")

    result = validate_document_seed_rows(seed)

    assert len(result["valid_seed_rows"]) == 1
    assert result["invalid_seed_rows"].empty


def _seed_df(**overrides):
    row = {
        "ticker": "AAA",
        "exchange": "HOSE",
        "company_name": "Example A",
        "period": "2025-Q4",
        "document_type": "financial_statement",
        "source_type": "exchange_filing",
        "source_name": "Example official",
        "source_url": "https://official.example/aaa.pdf",
        "official_domain": "official.example",
        "expected_file_type": "pdf",
        "consolidated_status": "consolidated",
        "language": "vi",
        "confidence_seed": "medium",
        "notes": "mock seed only",
    }
    row.update(overrides)
    return pd.DataFrame([row], columns=SEED_COLUMNS)
