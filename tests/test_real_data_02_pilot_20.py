from pathlib import Path

import pandas as pd

from src.pipeline.real_data_02_pilot_20 import run_real_data_02_pilot_20


def test_wrong_ticker_count_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=19)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"


def test_duplicate_ticker_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    manifest = paths["replay"] / "replay_manifest.json"
    text = manifest.read_text(encoding="utf-8")
    text = text.replace('"T002"', '"T001"', 1)
    manifest.write_text(text, encoding="utf-8")

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"


def test_missing_primary_market_fields_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    snapshot = pd.read_csv(paths["market"] / "current_market_snapshot.csv")
    snapshot = snapshot.drop(columns=["last_close"])
    snapshot.to_csv(paths["market"] / "current_market_snapshot.csv", index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert "market_snapshot" in set(result.schema_check["output_name"])


def test_missing_noncritical_finance_field_is_logged_not_zero_filled(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    finance = pd.read_csv(paths["finance_wide"])
    finance["net_income"] = finance["net_income"].astype(object)
    finance.loc[0, "net_income"] = ""
    finance.loc[0, "missing_fields"] = "net_income"
    finance.to_csv(paths["finance_wide"], index=False)

    result = _run(paths)
    row = result.readiness[result.readiness["ticker"].eq("T001")].iloc[0]

    assert result.decision["final_decision"] == "CONDITIONAL_GO_FOR_STEP19_SHADOW_20"
    assert "net_income" in row["missing_fields"]
    assert result.decision["critical_fail_count"] == 0


def test_source_failure_for_one_ticker_is_logged_not_dropped(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    finance = pd.read_csv(paths["finance_wide"])
    finance = finance[~finance["ticker"].eq("T003")]
    finance.to_csv(paths["finance_wide"], index=False)

    result = _run(paths)

    assert "T003" in set(result.readiness["ticker"])
    assert "FINANCE_ROW_MISSING" in set(result.failures["failure_type"])


def test_forbidden_actionable_output_term_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    paths["output"].mkdir(parents=True, exist_ok=True)
    (paths["output"] / "bad_output.md").write_text("buy T001 now\n", encoding="utf-8")

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert result.decision["forbidden_terms_found"]


def test_valid_20_ticker_pilot_with_warnings_is_conditional_or_pass(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.decision["final_decision"] in {"PASS_FOR_STEP19_SHADOW_20", "CONDITIONAL_GO_FOR_STEP19_SHADOW_20"}
    assert result.decision["pilot_ticker_count"] == 20
    assert len(result.readiness) == 20


def _run(paths: dict[str, Path]):
    return run_real_data_02_pilot_20(
        input_replay_dir=paths["replay"],
        current_market_dir=paths["market"],
        output_dir=paths["output"],
        policy_path=paths["policy"],
        finance_long_path=paths["finance_long"],
        finance_wide_path=paths["finance_wide"],
        finance_quality_path=paths["finance_quality"],
        ranking_path=None,
        allow_partial=True,
    )


def _write_fixture(tmp_path: Path, ticker_count: int = 20) -> dict[str, Path]:
    replay = tmp_path / "replay"
    market = tmp_path / "market"
    output = tmp_path / "out"
    replay.mkdir(parents=True, exist_ok=True)
    market.mkdir(parents=True, exist_ok=True)
    tickers = [f"T{index:03d}" for index in range(1, ticker_count + 1)]
    (replay / "replay_manifest.json").write_text(
        '{"pilot_tickers": [' + ",".join(f'"{ticker}"' for ticker in tickers) + "]}",
        encoding="utf-8",
    )
    _ranking(tickers).to_csv(replay / "replay_current_market_balanced_ranked_shortlist.csv", index=False)
    _market(tickers).to_csv(market / "current_market_snapshot.csv", index=False)
    finance_long = tmp_path / "finance_long.csv"
    finance_wide = tmp_path / "finance_wide.csv"
    finance_quality = tmp_path / "finance_quality.csv"
    _finance_wide(tickers).to_csv(finance_wide, index=False)
    _finance_long(tickers).to_csv(finance_long, index=False)
    pd.DataFrame({"ticker": tickers, "export_status": ["PARTIAL_PROVISIONAL_DATA"] * len(tickers)}).to_csv(finance_quality, index=False)
    policy = tmp_path / "policy.yaml"
    policy.write_text(
        "\n".join(
            [
                "pilot:",
                "  expected_ticker_count: 20",
                "market_minimum_fields:",
                "  - ticker",
                "  - last_close",
                "  - last_price_date",
                "  - avg_volume_20d",
                "  - avg_volume_60d",
                "  - trading_days_60d",
                "  - missing_market_flag",
                "  - stale_price_flag",
                "finance_minimum_fields:",
                "  - ticker",
                "  - period",
                "  - field_name",
                "  - value",
                "  - source_name",
                "  - source_confidence",
                "finance_snapshot_fields:",
                "  - revenue",
                "  - gross_profit",
                "  - net_income",
                "  - total_assets",
                "  - total_liabilities",
                "  - equity",
                "  - cfo",
                "  - capex",
                "safety:",
                "  forbidden_terms:",
                "    - buy",
                "    - sell",
                "    - target_price",
                "    - fair_value",
                "    - margin_of_safety",
                "    - recommendation",
                "  allowed_context:",
                "    - not_authorized",
                "    - no_",
                "    - 'no '",
                "    - not ",
                "    - safety",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return {
        "replay": replay,
        "market": market,
        "output": output,
        "policy": policy,
        "finance_long": finance_long,
        "finance_wide": finance_wide,
        "finance_quality": finance_quality,
    }


def _market(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "market_source": "test_market",
                "last_close": 10.0,
                "last_price_date": "2026-06-11",
                "avg_volume_20d": 1000.0,
                "avg_volume_60d": 1000.0,
                "trading_days_60d": 60,
                "missing_market_flag": False,
                "stale_price_flag": False,
            }
            for ticker in tickers
        ]
    )


def _ranking(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "exchange": "HOSE",
                "sector_raw": "Sector A",
                "sector_bucket": "Sector A",
                "firm_type": "non_financial",
            }
            for ticker in tickers
        ]
    )


def _finance_wide(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "period": 2025,
                "period_type": "year",
                "fiscal_year": 2025,
                "revenue": 100.0,
                "gross_profit": 20.0,
                "net_income": 10.0,
                "total_assets": 200.0,
                "total_liabilities": 50.0,
                "equity": 150.0,
                "cfo": 5.0,
                "capex": "",
                "source_name": "legacy_test",
                "source_confidence": "provisional_structured",
                "source_layer": "provisional_structured",
                "source_count": 1,
                "missing_fields": "capex",
            }
            for ticker in tickers
        ]
    )


def _finance_long(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for ticker in tickers:
        rows.append(
            {
                "ticker": ticker,
                "period": 2025,
                "field_name": "revenue",
                "value": 100.0,
                "source_name": "legacy_test",
                "source_confidence": "provisional_structured",
            }
        )
    return pd.DataFrame(rows)
