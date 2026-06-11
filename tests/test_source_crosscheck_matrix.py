import pandas as pd

from src.ingestion.legacy_structured_finance_importer import build_source_crosscheck_matrix


def test_duplicate_source_conflicts_are_written_to_crosscheck_matrix():
    long = pd.DataFrame(
        [
            _row("AAA", "2025", "revenue", "legacy_source_a", 100),
            _row("AAA", "2025", "revenue", "legacy_source_b", 130),
        ]
    )

    matrix = build_source_crosscheck_matrix(long)

    assert matrix.iloc[0]["crosscheck_status"] == "SOURCE_CONFLICT"
    assert bool(matrix.iloc[0]["manual_review_required"]) is True
    assert matrix.iloc[0]["confidence_level"] == "PROVISIONAL_LOW"


def test_one_source_only_never_becomes_high_confidence():
    long = pd.DataFrame([_row("AAA", "2025", "equity", "vnstock_finance_v1", 100)])

    matrix = build_source_crosscheck_matrix(long)

    assert matrix.iloc[0]["crosscheck_status"] == "ONE_SOURCE_ONLY"
    assert matrix.iloc[0]["confidence_level"] != "HIGH"
    assert matrix.iloc[0]["confidence_level"] == "PROVISIONAL_LOW"


def _row(ticker: str, period: str, field_name: str, source_name: str, value: float) -> dict:
    return {
        "ticker": ticker,
        "period": period,
        "field_name": field_name,
        "source_name": source_name,
        "value": value,
    }
