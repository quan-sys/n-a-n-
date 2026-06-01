import pandas as pd
import pytest

import src.fetchers.disclosure_status_fetcher as disclosure_status_fetcher
from src.fetchers.base import REQUIRED_FETCH_COLUMNS
from src.fetchers.disclosure_status_fetcher import (
    REAL_SOURCE_UNAVAILABLE_MESSAGE,
    DisclosureStatusFetcher,
    RealSourceUnavailableError,
    normalize_event_type,
    normalize_severity,
    validate_disclosure_status_output,
)


def _manual_disclosure_row(**overrides):
    row = {
        "ticker": "MANUAL1",
        "date": "2026-01-01",
        "event_type": "audit warning",
        "severity": "high",
        "source": "USER_FILE",
        "source_url": "https://example.invalid/manual-disclosure",
        "notes": "manual disclosure fixture",
    }
    row.update(overrides)
    return row


def test_mock_mode_returns_dataframe():
    df = DisclosureStatusFetcher().fetch(mode="mock")

    assert isinstance(df, pd.DataFrame)


def test_mock_mode_output_has_standardized_fetcher_columns():
    df = DisclosureStatusFetcher().fetch(mode="mock")

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS


def test_mock_output_includes_required_fields():
    df = DisclosureStatusFetcher().fetch(mode="mock")

    assert {"event_type", "severity", "source_url", "notes"}.issubset(
        set(df["field"])
    )


def test_mock_mode_uses_mock_source():
    df = DisclosureStatusFetcher().fetch(mode="mock")

    assert set(df["source"]) == {"MOCK"}


def test_mock_mode_does_not_pretend_to_be_real_data():
    df = DisclosureStatusFetcher().fetch(mode="mock")

    assert set(df["confidence_raw"]) == {"mock"}
    assert df["notes"].str.contains("mock disclosure status data", case=False).all()
    assert df["notes"].str.contains("not real", case=False).all()


def test_manual_csv_mode_normalizes_wide_csv_into_long_format(tmp_path):
    csv_path = tmp_path / "manual_disclosures.csv"
    pd.DataFrame([_manual_disclosure_row()]).to_csv(csv_path, index=False)

    df = DisclosureStatusFetcher().fetch(
        mode="manual_csv", manual_file_path=str(csv_path)
    )

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS
    assert set(df["dataset_name"]) == {"disclosure_status"}
    assert {"event_type", "severity", "source_url", "notes"}.issubset(
        set(df["field"])
    )
    assert set(df["source"]) == {"USER_FILE"}
    assert set(df[df["field"] == "event_type"]["value"]) == {"AUDIT_WARNING"}
    assert set(df[df["field"] == "severity"]["value"]) == {"HIGH"}


def test_manual_xlsx_mode_normalizes_wide_excel_into_long_format(tmp_path):
    xlsx_path = tmp_path / "manual_disclosures.xlsx"
    pd.DataFrame([_manual_disclosure_row()]).to_excel(xlsx_path, index=False)

    df = DisclosureStatusFetcher().fetch(
        mode="manual_xlsx", manual_file_path=str(xlsx_path)
    )

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS
    assert set(df["dataset_name"]) == {"disclosure_status"}
    assert {"event_type", "severity", "source_url", "notes"}.issubset(
        set(df["field"])
    )
    assert set(df["source"]) == {"USER_FILE"}


def test_manual_file_missing_expected_columns_creates_validation_warnings(tmp_path):
    csv_path = tmp_path / "manual_disclosures_missing_columns.csv"
    pd.DataFrame(
        [
            {
                "ticker": "MANUAL1",
                "date": "2026-01-01",
                "event_type": "audit warning",
                "source": "USER_FILE",
            }
        ]
    ).to_csv(csv_path, index=False)

    df = DisclosureStatusFetcher().fetch(
        mode="manual_csv", manual_file_path=str(csv_path)
    )
    result = validate_disclosure_status_output(df)

    assert result["is_valid"] is True
    assert any("missing expected fields" in warning for warning in result["warnings"])


def test_manual_file_does_not_fabricate_clean_records_for_missing_tickers(tmp_path):
    csv_path = tmp_path / "manual_disclosures_single_ticker.csv"
    pd.DataFrame([_manual_disclosure_row(ticker="MANUAL1")]).to_csv(
        csv_path, index=False
    )

    df = DisclosureStatusFetcher().fetch(
        tickers=["MANUAL1", "MANUAL2"],
        mode="manual_csv",
        manual_file_path=str(csv_path),
    )

    assert set(df["ticker"]) == {"MANUAL1"}
    assert "MANUAL2" not in set(df["ticker"])


def test_manual_file_missing_source_uses_unknown_source(tmp_path):
    csv_path = tmp_path / "manual_disclosures_unknown_source.csv"
    row = _manual_disclosure_row()
    row.pop("source")
    pd.DataFrame([row]).to_csv(csv_path, index=False)

    df = DisclosureStatusFetcher().fetch(
        mode="manual_csv", manual_file_path=str(csv_path)
    )

    assert set(df["source"]) == {"MANUAL_FILE_UNKNOWN_SOURCE"}
    assert set(df["confidence_raw"]) == {"medium"}


def test_severity_normalization_works():
    assert normalize_severity("low") == "LOW"
    assert normalize_severity("med") == "MEDIUM"
    assert normalize_severity("severe") == "HIGH"
    assert normalize_severity("crit") == "CRITICAL"
    assert normalize_severity("unexpected") == "UNKNOWN"


def test_event_type_normalization_works():
    assert normalize_event_type("audit warning") == "AUDIT_WARNING"
    assert normalize_event_type("trading restricted") == "TRADING_RESTRICTION"
    assert normalize_event_type("negative equity") == "NEGATIVE_EQUITY_WARNING"
    assert normalize_event_type("unexpected event") == "UNKNOWN"


def test_real_mode_unavailable_raises_clear_error():
    with pytest.raises(RealSourceUnavailableError, match="REAL_SOURCE_UNAVAILABLE"):
        DisclosureStatusFetcher().fetch(mode="real")


def test_real_mode_does_not_generate_fake_values_when_unavailable():
    with pytest.raises(RealSourceUnavailableError) as error_info:
        DisclosureStatusFetcher().fetch(mode="real")

    assert str(error_info.value) == REAL_SOURCE_UNAVAILABLE_MESSAGE


def test_invalid_mode_raises_clear_error():
    with pytest.raises(ValueError, match="Invalid mode"):
        DisclosureStatusFetcher().fetch(mode="paper")


def test_output_validates_successfully_through_fetcher_validation():
    fetcher = DisclosureStatusFetcher()
    df = fetcher.fetch(mode="mock")

    result = fetcher.validate_output(df)

    assert result["is_valid"] is True
    assert result["missing_columns"] == []
    assert result["warnings"] == []
    assert result["errors"] == []


def test_validation_rejects_missing_ticker_date_field_source_or_fetch_time():
    df = DisclosureStatusFetcher().fetch(mode="mock")
    invalid_df = df.copy()
    invalid_df.loc[0, "ticker"] = ""
    invalid_df.loc[1, "date"] = ""
    invalid_df.loc[2, "field"] = ""
    invalid_df.loc[3, "source"] = ""
    invalid_df.loc[4, "fetch_time"] = ""

    result = validate_disclosure_status_output(invalid_df)

    assert result["is_valid"] is False
    assert any("missing ticker" in error for error in result["errors"])
    assert any("missing date" in error for error in result["errors"])
    assert any("missing field" in error for error in result["errors"])
    assert any("missing source" in error for error in result["errors"])
    assert any("missing fetch_time" in error for error in result["errors"])


def test_no_l0_filtering_sector_classification_or_valuation_scoring_is_implemented():
    public_names = {
        name
        for name in dir(disclosure_status_fetcher)
        if not name.startswith("_") and callable(getattr(disclosure_status_fetcher, name))
    }

    assert not any(name.startswith("filter") for name in public_names)
    assert not any(name.startswith("classify") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)


def test_no_buy_sell_recommendation_is_generated():
    df = DisclosureStatusFetcher().fetch(mode="mock")
    output_text = df.to_string().upper()

    assert "BUY" not in output_text
    assert "SELL" not in output_text
