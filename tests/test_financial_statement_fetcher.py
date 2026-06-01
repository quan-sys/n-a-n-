import pandas as pd
import pytest

import src.fetchers.financial_statement_fetcher as financial_statement_fetcher
from src.fetchers.base import REQUIRED_FETCH_COLUMNS
from src.fetchers.financial_statement_fetcher import (
    REAL_SOURCE_UNAVAILABLE_MESSAGE,
    FinancialStatementFetcher,
    RealSourceUnavailableError,
    validate_financial_statement_output,
)


REQUIRED_MOCK_FIELDS = {
    "revenue",
    "net_profit",
    "total_assets",
    "total_liabilities",
    "equity",
    "cash",
    "short_term_debt",
    "long_term_debt",
    "operating_cash_flow",
    "inventory",
}


def _manual_financial_row(**overrides):
    row = {
        "ticker": "MANUAL1",
        "period": "2026Q1",
        "revenue": 1000,
        "gross_profit": 300,
        "operating_profit": 200,
        "net_profit": 100,
        "total_assets": 5000,
        "total_liabilities": 2000,
        "equity": 3000,
        "cash": 500,
        "short_term_debt": 100,
        "long_term_debt": 300,
        "operating_cash_flow": 150,
        "inventory": 250,
        "source": "USER_FILE",
        "fetch_time": "2026-01-01T00:00:00Z",
    }
    row.update(overrides)
    return row


def test_mock_mode_returns_dataframe():
    df = FinancialStatementFetcher().fetch(mode="mock")

    assert isinstance(df, pd.DataFrame)


def test_mock_mode_output_has_standardized_fetcher_columns():
    df = FinancialStatementFetcher().fetch(mode="mock")

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS


def test_mock_output_includes_required_financial_fields():
    df = FinancialStatementFetcher().fetch(mode="mock")

    assert REQUIRED_MOCK_FIELDS.issubset(set(df["field"]))


def test_mock_mode_uses_mock_source():
    df = FinancialStatementFetcher().fetch(mode="mock")

    assert set(df["source"]) == {"MOCK"}


def test_mock_mode_does_not_pretend_to_be_real_data():
    df = FinancialStatementFetcher().fetch(mode="mock")

    assert set(df["confidence_raw"]) == {"mock"}
    assert df["notes"].str.contains("mock financial statement data", case=False).all()
    assert df["notes"].str.contains("not real", case=False).all()


def test_manual_csv_mode_normalizes_wide_csv_into_long_format(tmp_path):
    csv_path = tmp_path / "manual_financials.csv"
    pd.DataFrame([_manual_financial_row()]).to_csv(csv_path, index=False)

    df = FinancialStatementFetcher().fetch(
        mode="manual_csv", manual_file_path=str(csv_path)
    )

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS
    assert set(df["dataset_name"]) == {"financial_statement_summary"}
    assert REQUIRED_MOCK_FIELDS.issubset(set(df["field"]))
    assert set(df["source"]) == {"USER_FILE"}


def test_manual_xlsx_mode_normalizes_wide_excel_into_long_format(tmp_path):
    xlsx_path = tmp_path / "manual_financials.xlsx"
    pd.DataFrame([_manual_financial_row()]).to_excel(xlsx_path, index=False)

    df = FinancialStatementFetcher().fetch(
        mode="manual_xlsx", manual_file_path=str(xlsx_path)
    )

    assert list(df.columns) == REQUIRED_FETCH_COLUMNS
    assert set(df["dataset_name"]) == {"financial_statement_summary"}
    assert REQUIRED_MOCK_FIELDS.issubset(set(df["field"]))
    assert set(df["source"]) == {"USER_FILE"}


def test_manual_file_missing_expected_columns_creates_validation_warnings(tmp_path):
    csv_path = tmp_path / "manual_financials_missing_columns.csv"
    pd.DataFrame(
        [
            {
                "ticker": "MANUAL1",
                "period": "2026Q1",
                "revenue": 1000,
                "source": "USER_FILE",
                "fetch_time": "2026-01-01T00:00:00Z",
            }
        ]
    ).to_csv(csv_path, index=False)

    df = FinancialStatementFetcher().fetch(
        mode="manual_csv", manual_file_path=str(csv_path)
    )
    result = validate_financial_statement_output(df)

    assert result["is_valid"] is True
    assert any("missing expected fields" in warning for warning in result["warnings"])


def test_manual_file_does_not_fill_missing_financial_numbers(tmp_path):
    csv_path = tmp_path / "manual_financials_missing_value.csv"
    pd.DataFrame(
        [_manual_financial_row(net_profit=pd.NA)]
    ).to_csv(csv_path, index=False)

    df = FinancialStatementFetcher().fetch(
        mode="manual_csv", manual_file_path=str(csv_path)
    )
    net_profit_rows = df[df["field"] == "net_profit"]
    result = validate_financial_statement_output(df)

    assert len(net_profit_rows) == 1
    assert pd.isna(net_profit_rows.iloc[0]["value"])
    assert any("missing numeric field net_profit" in warning for warning in result["warnings"])


def test_manual_file_missing_source_uses_unknown_source(tmp_path):
    csv_path = tmp_path / "manual_financials_unknown_source.csv"
    row = _manual_financial_row()
    row.pop("source")
    pd.DataFrame([row]).to_csv(csv_path, index=False)

    df = FinancialStatementFetcher().fetch(
        mode="manual_csv", manual_file_path=str(csv_path)
    )

    assert set(df["source"]) == {"MANUAL_FILE_UNKNOWN_SOURCE"}
    assert set(df["confidence_raw"]) == {"medium"}


def test_real_mode_unavailable_raises_clear_error():
    with pytest.raises(RealSourceUnavailableError, match="REAL_SOURCE_UNAVAILABLE"):
        FinancialStatementFetcher().fetch(mode="real")


def test_real_mode_does_not_generate_fake_values_when_unavailable():
    with pytest.raises(RealSourceUnavailableError) as error_info:
        FinancialStatementFetcher().fetch(mode="real")

    assert str(error_info.value) == REAL_SOURCE_UNAVAILABLE_MESSAGE


def test_invalid_mode_raises_clear_error():
    with pytest.raises(ValueError, match="Invalid mode"):
        FinancialStatementFetcher().fetch(mode="paper")


def test_output_validates_successfully_through_fetcher_validation():
    fetcher = FinancialStatementFetcher()
    df = fetcher.fetch(mode="mock")

    result = fetcher.validate_output(df)

    assert result["is_valid"] is True
    assert result["missing_columns"] == []
    assert result["warnings"] == []
    assert result["errors"] == []


def test_validation_rejects_missing_ticker_period_field_source_or_fetch_time():
    df = FinancialStatementFetcher().fetch(mode="mock")
    invalid_df = df.copy()
    invalid_df.loc[0, "ticker"] = ""
    invalid_df.loc[1, "date"] = ""
    invalid_df.loc[2, "field"] = ""
    invalid_df.loc[3, "source"] = ""
    invalid_df.loc[4, "fetch_time"] = ""

    result = validate_financial_statement_output(invalid_df)

    assert result["is_valid"] is False
    assert any("missing ticker" in error for error in result["errors"])
    assert any("missing period" in error for error in result["errors"])
    assert any("missing field" in error for error in result["errors"])
    assert any("missing source" in error for error in result["errors"])
    assert any("missing fetch_time" in error for error in result["errors"])


def test_validation_rejects_non_numeric_financial_values():
    df = FinancialStatementFetcher().fetch(mode="mock")
    invalid_df = df.copy()
    invalid_df.loc[invalid_df["field"] == "revenue", "value"] = "not_numeric"

    result = validate_financial_statement_output(invalid_df)

    assert result["is_valid"] is False
    assert any("revenue must be numeric" in error for error in result["errors"])


def test_no_l0_filtering_sector_classification_or_valuation_scoring_is_implemented():
    public_names = {
        name
        for name in dir(financial_statement_fetcher)
        if not name.startswith("_") and callable(getattr(financial_statement_fetcher, name))
    }

    assert not any(name.startswith("filter") for name in public_names)
    assert not any(name.startswith("classify") for name in public_names)
    assert not any(name.startswith("score") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)


def test_no_buy_sell_recommendation_is_generated():
    df = FinancialStatementFetcher().fetch(mode="mock")
    output_text = df.to_string().upper()

    assert "BUY" not in output_text
    assert "SELL" not in output_text
