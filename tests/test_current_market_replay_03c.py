from pathlib import Path

import pandas as pd

from src.validation.current_market_replay_03c import DECISION_VALUES, run_current_market_replay


def test_snapshot_missing_core_column_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    snapshot = pd.read_csv(paths["snapshot"])
    snapshot = snapshot.drop(columns=["last_close"])
    snapshot.to_csv(paths["snapshot"], index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert _check_status(result, "core_market_schema_present") == "FAIL"


def test_snapshot_not_exactly_20_tickers_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=19)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert _check_status(result, "pilot_ticker_count") == "FAIL"


def test_duplicate_ticker_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    snapshot = pd.read_csv(paths["snapshot"])
    snapshot.loc[1, "ticker"] = snapshot.loc[0, "ticker"]
    snapshot.to_csv(paths["snapshot"], index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert _check_status(result, "snapshot_duplicate_tickers_absent") == "FAIL"


def test_primary_missing_or_stale_flag_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    snapshot = pd.read_csv(paths["snapshot"])
    snapshot.loc[0, "missing_market_flag"] = True
    snapshot.loc[1, "stale_price_flag"] = True
    snapshot.to_csv(paths["snapshot"], index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert _check_status(result, "primary_market_values_complete") == "FAIL"
    assert _check_status(result, "primary_market_values_fresh") == "FAIL"


def test_replay_is_deterministic_when_inputs_match(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.decision["final_decision"] == "PASS_FOR_REAL_DATA_02_PILOT_20"
    assert result.decision["critical_fail_count"] == 0
    assert result.decision["warn_count"] == 0


def test_top10_order_difference_warns_not_critical_when_set_matches(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    ranking = pd.read_csv(paths["ranking"])
    ranking.loc[[0, 1], "current_market_rank"] = [2, 1]
    ranking.loc[[0, 1], "balanced_rank"] = [2, 1]
    ranking.to_csv(paths["ranking"], index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "CONDITIONAL_GO_FOR_REAL_DATA_02_PILOT_20"
    row = result.comparison[result.comparison["check_name"].eq("top10_order_match_or_warn")].iloc[0]
    assert row["status"] == "WARN"
    assert result.decision["critical_fail_count"] == 0


def test_changed_ticker_set_is_critical_fail(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    ranking = pd.read_csv(paths["ranking"])
    ranking.loc[19, "ticker"] = "X999"
    ranking.to_csv(paths["ranking"], index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert _check_status(result, "pilot_ticker_set_match") == "FAIL"


def test_forbidden_output_terms_are_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    paths["output"].mkdir(parents=True, exist_ok=True)
    (paths["output"] / "stale_bad_output.md").write_text("buy T001 now\n", encoding="utf-8")

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert _check_status(result, "forbidden_terms_absent") == "FAIL"


def test_no_real_data_02_or_step19_output_checks_pass(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert _check_status(result, "no_real_data_02_output_detected") == "PASS"
    assert _check_status(result, "no_step19_output_detected") == "PASS"


def test_decision_is_in_allowed_enum(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.decision["final_decision"] in DECISION_VALUES


def _run(paths: dict[str, Path]):
    return run_current_market_replay(
        snapshot_path=paths["snapshot"],
        stage2_gate_path=paths["gate"],
        ranking_path=paths["ranking"],
        evidence_summary_path=paths["evidence_summary"],
        output_dir=paths["output"],
        config_path=paths["config"],
        base_ranking_path=paths["base_ranking"],
        finance_quality_path=paths["finance_quality"],
        finance_long_path=paths["finance_long"],
        finance_crosscheck_path=paths["finance_crosscheck"],
        market_crosscheck_path=paths["market_crosscheck"],
        stage2_policy_path=paths["stage2_policy"],
        balance_policy_path=paths["balance_policy"],
        evidence_policy_path=paths["evidence_policy"],
    )


def _write_fixture(tmp_path: Path, ticker_count: int = 20) -> dict[str, Path]:
    paths = {
        "snapshot": tmp_path / "snapshot.csv",
        "gate": tmp_path / "stage2_gate.csv",
        "ranking": tmp_path / "ranking.csv",
        "base_ranking": tmp_path / "base_ranking.csv",
        "finance_quality": tmp_path / "finance_quality.csv",
        "finance_long": tmp_path / "finance_long.csv",
        "finance_crosscheck": tmp_path / "finance_crosscheck.csv",
        "market_crosscheck": tmp_path / "market_crosscheck.csv",
        "stage2_policy": tmp_path / "stage2_policy.yaml",
        "balance_policy": tmp_path / "balance_policy.yaml",
        "evidence_policy": tmp_path / "evidence_policy.yaml",
        "config": tmp_path / "config.yaml",
        "evidence_dir": tmp_path / "evidence",
        "output": tmp_path / "out",
    }
    paths["evidence_dir"].mkdir(parents=True, exist_ok=True)
    tickers = [f"T{index:03d}" for index in range(1, ticker_count + 1)]
    _snapshot(tickers).to_csv(paths["snapshot"], index=False)
    _base_ranking(tickers).to_csv(paths["base_ranking"], index=False)
    _gate(tickers).to_csv(paths["gate"], index=False)
    _ranking(tickers).to_csv(paths["ranking"], index=False)
    _finance_quality(tickers).to_csv(paths["finance_quality"], index=False)
    pd.DataFrame(columns=["ticker", "field_name", "period", "value"]).to_csv(paths["finance_long"], index=False)
    pd.DataFrame({"ticker": tickers, "finance_crosscheck_status": ["MULTI_SOURCE_AGREES"] * len(tickers)}).to_csv(paths["finance_crosscheck"], index=False)
    pd.DataFrame({"ticker": tickers, "price_crosscheck_status": ["OK"] * len(tickers)}).to_csv(paths["market_crosscheck"], index=False)
    _write_stage2_policy(paths["stage2_policy"])
    _write_balance_policy(paths["balance_policy"])
    _write_evidence_policy(paths["evidence_policy"])
    _write_replay_config(paths["config"])
    _evidence_queue(tickers).to_csv(paths["evidence_dir"] / "evidence_collection_queue.csv", index=False)
    (paths["evidence_dir"] / "run_summary.md").write_text("existing evidence summary\n", encoding="utf-8")
    paths["evidence_summary"] = paths["evidence_dir"] / "run_summary.md"
    return paths


def _snapshot(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "last_close": 10.0,
                "last_price_date": "2026-06-11",
                "avg_volume_20d": 1000.0,
                "avg_volume_60d": 1000.0,
                "trading_days_60d": 60,
                "missing_market_flag": False,
                "stale_price_flag": False,
                "stale_days": 0,
            }
            for ticker in tickers
        ]
    )


def _base_ranking(tickers: list[str]) -> pd.DataFrame:
    sectors = ["Sector A", "Sector B", "Sector C", "Sector D", "Sector E"]
    return pd.DataFrame(
        [
            {
                "rank": index,
                "balanced_rank": index,
                "raw_rank": index,
                "ticker": ticker,
                "exchange": "HOSE",
                "sector_raw": sectors[(index - 1) % len(sectors)],
                "sector_bucket": sectors[(index - 1) % len(sectors)],
                "firm_type": "non_financial",
                "evidence_priority_score": 100 - index,
                "raw_evidence_priority_score": 100 - index,
                "manual_review_required": False,
            }
            for index, ticker in enumerate(tickers, start=1)
        ]
    )


def _gate(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "raw_rank": index,
                "original_stage": _stage(index),
                "new_stage": _stage(index),
                "eligibility_status": "STAGE2_ELIGIBLE",
                "demotion_reason": "",
                "manual_review_required": False,
            }
            for index, ticker in enumerate(tickers, start=1)
        ]
    )


def _ranking(tickers: list[str]) -> pd.DataFrame:
    base = _base_ranking(tickers)
    base["current_market_rank"] = base["rank"]
    base["evidence_stage"] = [_stage(index) for index in range(1, len(base) + 1)]
    base["stage"] = base["evidence_stage"]
    return base


def _finance_quality(tickers: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"ticker": tickers, "export_status": ["OK_FOR_PROVISIONAL_SCREEN"] * len(tickers)})


def _evidence_queue(tickers: list[str]) -> pd.DataFrame:
    rows = []
    for index, ticker in enumerate(tickers, start=1):
        priorities = ["P0_latest_statement", "P1_latest_annual"] if index <= 10 else ["P0_latest_statement"]
        for priority in priorities:
            rows.append({"ticker": ticker, "stage": _stage(index), "document_priority": priority})
    return pd.DataFrame(rows)


def _stage(index: int) -> str:
    return "stage_4_deep_dive_shortlist" if index <= 10 else "stage_3_final_watchlist"


def _write_stage2_policy(path: Path) -> None:
    path.write_text(
        "market_refresh:\n  min_trading_days_60d_for_stage2: 30\nminimum_finance_required:\n  min_core_metrics_present: 3\n  min_years_any_core_metric: 2\n",
        encoding="utf-8",
    )


def _write_balance_policy(path: Path) -> None:
    path.write_text(
        "balance_policy:\n  enabled: false\n  fallback:\n    unknown_sector_bucket: UNKNOWN\n    unknown_firm_type: unknown\n",
        encoding="utf-8",
    )


def _write_evidence_policy(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "stages:",
                "  stage_0_full_universe:",
                "    official_files_per_ticker_min: 0",
                "    official_files_per_ticker_max: 0",
                "    target_max_tickers: 0",
                "  stage_1_provisional_shortlist:",
                "    official_files_per_ticker_min: 0",
                "    official_files_per_ticker_max: 0",
                "    target_max_tickers: 0",
                "  stage_2_evidence_candidates:",
                "    official_files_per_ticker_min: 0",
                "    official_files_per_ticker_max: 0",
                "    target_max_tickers: 0",
                "  stage_3_final_watchlist:",
                "    official_files_per_ticker_min: 1",
                "    official_files_per_ticker_max: 1",
                "    target_max_tickers: 10",
                "  stage_4_deep_dive_shortlist:",
                "    official_files_per_ticker_min: 2",
                "    official_files_per_ticker_max: 2",
                "    target_max_tickers: 10",
                "document_priorities:",
                "  P0_latest_statement:",
                "    document_requirement: Latest statement.",
                "    period_target: latest_available",
                "    period_type_target: quarterly_or_semiannual",
                "    preferred_document_category: financial_statement",
                "    max_files_per_ticker: 1",
                "    required_from_stage: stage_3_final_watchlist",
                "  P1_latest_annual:",
                "    document_requirement: Latest annual.",
                "    period_target: latest_annual",
                "    period_type_target: annual",
                "    preferred_document_category: annual_report",
                "    max_files_per_ticker: 1",
                "    required_from_stage: stage_4_deep_dive_shortlist",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_replay_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "replay:",
                "  expected_pilot_ticker_count: 20",
                "core_market_columns:",
                "  - ticker",
                "  - last_close",
                "  - last_price_date",
                "  - avg_volume_20d",
                "  - avg_volume_60d",
                "  - trading_days_60d",
                "  - missing_market_flag",
                "  - stale_price_flag",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _check_status(result, check_name: str) -> str:
    rows = result.comparison[result.comparison["check_name"].eq(check_name)]
    assert not rows.empty, check_name
    return rows.iloc[0]["status"]
