from datetime import UTC, datetime

import pandas as pd

from src.ingestion.public_market_data_crosscheck import (
    compute_market_summary,
    crosscheck_market_row,
    normalize_public_market_ohlcv,
)


def test_missing_public_csv_produces_status_without_failure():
    row = crosscheck_market_row(
        {"ticker": "AAA", "last_close": 10},
        {},
        rank=1,
        fetch_status="PUBLIC_FILE_MISSING",
        current_date=datetime(2026, 6, 11, tzinfo=UTC),
    )

    assert row["price_crosscheck_status"] == "PUBLIC_FILE_MISSING"
    assert row["volume_crosscheck_status"] == "PUBLIC_FILE_MISSING"
    assert bool(row["manual_review_required"]) is True


def test_price_diff_thresholds_produce_agree_minor_major():
    base = {"ticker": "AAA", "last_close": 100, "last_price_date": "2026-06-10"}
    current = datetime(2026, 6, 11, tzinfo=UTC)

    agree = crosscheck_market_row(base, {"public_last_close": 101, "public_last_price_date": "2026-06-10"}, current_date=current)
    minor = crosscheck_market_row(base, {"public_last_close": 103, "public_last_price_date": "2026-06-10"}, current_date=current)
    major = crosscheck_market_row(base, {"public_last_close": 110, "public_last_price_date": "2026-06-10"}, current_date=current)

    assert agree["price_crosscheck_status"] == "AGREE"
    assert minor["price_crosscheck_status"] == "MINOR_DIFF"
    assert major["price_crosscheck_status"] == "MAJOR_DIFF"


def test_public_market_ohlcv_normalization_and_summary():
    raw = pd.DataFrame(
        [
            {"time": "2026-06-09", "close": "10", "volume": "100"},
            {"time": "2026-06-10", "close": "11", "volume": "300"},
        ]
    )

    normalized = normalize_public_market_ohlcv(raw, "AAA")
    summary = compute_market_summary(normalized)

    assert summary["public_last_close"] == 11
    assert summary["public_last_price_date"] == "2026-06-10"
    assert summary["public_avg_volume_20d"] == 200
