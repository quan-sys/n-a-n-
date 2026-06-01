import pandas as pd

import src.quality.data_quality as data_quality
from src.quality.data_quality import (
    QUALITY_COLUMNS,
    check_low_confidence_raw,
    check_source_conflict,
    load_data_quality_rules,
    run_data_quality_checks,
)


RULES_PATH = "config/data_quality_rules.yaml"


def _rules():
    return load_data_quality_rules(RULES_PATH)


def _market_df(**overrides):
    row = {
        "ticker": "MOCK1",
        "date": "2026-05-25",
        "close": 1000,
        "volume": 100,
        "trading_value": 100000,
        "source": "MOCK",
        "fetch_time": "2026-05-25T00:00:00Z",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _financial_df(**overrides):
    row = {
        "ticker": "MOCK1",
        "period": "2026Q1",
        "revenue": 1000,
        "gross_profit": 100,
        "operating_profit": 80,
        "net_profit": 50,
        "total_assets": 5000,
        "total_liabilities": 2000,
        "equity": 3000,
        "cash": 500,
        "short_term_debt": 100,
        "long_term_debt": 200,
        "operating_cash_flow": 75,
        "inventory": 250,
        "source": "MOCK",
        "fetch_time": "2026-05-25T00:00:00Z",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def test_valid_mock_market_price_returns_valid_data_and_high_confidence():
    result = run_data_quality_checks(
        _market_df(),
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )
    row = result.iloc[0]

    assert row["quality_status"] == "VALID_DATA"
    assert row["quality_warnings"] == []
    assert row["quality_errors"] == []
    assert row["final_confidence"] == "high"
    assert bool(row["manual_review_required"]) is False


def test_missing_close_price_creates_missing_data_and_reduces_confidence():
    result = run_data_quality_checks(
        _market_df(close=None),
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )
    row = result.iloc[0]

    assert row["quality_status"] == "MISSING_DATA"
    assert "MISSING_CLOSE" in row["quality_warnings"]
    assert row["final_confidence"] == "low"


def test_negative_close_price_creates_data_error():
    result = run_data_quality_checks(
        _market_df(close=-1),
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )
    row = result.iloc[0]

    assert row["quality_status"] == "DATA_ERROR"
    assert "INVALID_CLOSE_NON_POSITIVE" in row["quality_errors"]
    assert row["final_confidence"] == "low"


def test_negative_equity_creates_warning_and_manual_review():
    result = run_data_quality_checks(
        _financial_df(equity=-10),
        dataset_name="financial_statement_summary",
        rules=_rules(),
        reference_date="2026-06-01",
    )
    row = result.iloc[0]

    assert "NEGATIVE_EQUITY" in row["quality_warnings"]
    assert bool(row["manual_review_required"]) is True
    assert row["final_confidence"] == "low"


def test_stale_market_price_data_creates_stale_data():
    result = run_data_quality_checks(
        _market_df(date="2026-05-01"),
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )
    row = result.iloc[0]

    assert row["quality_status"] == "STALE_DATA"
    assert "STALE_DATA" in row["quality_warnings"]
    assert row["final_confidence"] == "low"


def test_outlier_values_create_outlier_review():
    df = pd.DataFrame(
        [
            _market_df(ticker="MOCK1", close=100).iloc[0],
            _market_df(ticker="MOCK2", close=101).iloc[0],
            _market_df(ticker="MOCK3", close=102).iloc[0],
            _market_df(ticker="MOCK4", close=10000).iloc[0],
        ]
    )

    result = run_data_quality_checks(
        df,
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )
    outlier_row = result[result["ticker"] == "MOCK4"].iloc[0]

    assert outlier_row["quality_status"] == "OUTLIER_REVIEW"
    assert "OUTLIER_REVIEW" in outlier_row["quality_warnings"]
    assert bool(outlier_row["manual_review_required"]) is True


def test_conflicting_source_values_create_data_conflict():
    df = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "date": "2026-05-25",
                "close": 100,
                "volume": 100,
                "trading_value": 10000,
                "source": "MOCK_A",
                "fetch_time": "2026-05-25T00:00:00Z",
            },
            {
                "ticker": "MOCK1",
                "date": "2026-05-25",
                "close": 120,
                "volume": 100,
                "trading_value": 10000,
                "source": "MOCK_B",
                "fetch_time": "2026-05-25T00:00:00Z",
            },
        ]
    )

    result = run_data_quality_checks(
        df,
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )

    assert set(result["quality_status"]) == {"DATA_CONFLICT"}
    assert result["quality_warnings"].map(lambda warnings: "DATA_CONFLICT" in warnings).all()
    assert result["manual_review_required"].map(bool).all()


def test_check_source_conflict_helper_reports_conflict():
    df = pd.DataFrame(
        [
            {"ticker": "MOCK1", "date": "2026-05-25", "close": 100, "source": "A"},
            {"ticker": "MOCK1", "date": "2026-05-25", "close": 120, "source": "B"},
        ]
    )

    result = check_source_conflict(df, ["ticker", "date"], "close")

    assert result["warnings"] == ["DATA_CONFLICT"]


def test_high_severity_disclosure_creates_flag():
    df = pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "date": "2026-05-25",
                "event_type": "MOCK_EVENT",
                "severity": "HIGH",
                "source": "MOCK",
                "source_url": "",
                "notes": "mock disclosure only",
            }
        ]
    )

    result = run_data_quality_checks(
        df,
        dataset_name="disclosure_status",
        rules=_rules(),
        reference_date="2026-06-01",
    )
    row = result.iloc[0]

    assert "HIGH_SEVERITY_DISCLOSURE_FLAG" in row["quality_warnings"]
    assert bool(row["manual_review_required"]) is True
    assert row["final_confidence"] == "low"


def test_low_raw_confidence_creates_warning_and_low_confidence():
    result = run_data_quality_checks(
        _market_df(confidence_raw="low"),
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )
    row = result.iloc[0]

    assert "LOW_CONFIDENCE_RAW" in row["quality_warnings"]
    assert row["final_confidence"] == "low"
    assert bool(row["manual_review_required"]) is True


def test_check_low_confidence_raw_helper_reports_configured_low_values():
    df = _market_df(confidence_raw="mock")

    result = check_low_confidence_raw(df, low_values={"mock"})

    assert result["warnings"] == ["LOW_CONFIDENCE_RAW"]


def test_output_contains_required_quality_columns():
    result = run_data_quality_checks(
        _market_df(),
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )

    for column in QUALITY_COLUMNS:
        assert column in result.columns


def test_module_does_not_drop_rows_silently():
    df = pd.concat(
        [_market_df(ticker="MOCK1"), _market_df(ticker="MOCK2", close=None)],
        ignore_index=True,
    )

    result = run_data_quality_checks(
        df,
        dataset_name="market_price",
        rules=_rules(),
        reference_date="2026-06-01",
    )

    assert len(result) == len(df)
    assert set(result["ticker"]) == {"MOCK1", "MOCK2"}


def test_no_l0_filtering_sector_classification_or_valuation_scoring_is_implemented():
    public_names = {
        name
        for name in dir(data_quality)
        if not name.startswith("_") and callable(getattr(data_quality, name))
    }

    assert not any(name.startswith("filter") for name in public_names)
    assert not any(name.startswith("classify") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)
