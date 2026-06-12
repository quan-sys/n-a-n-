from pathlib import Path

import pandas as pd

from src.validation.alternative_market_consensus_04b import (
    DECISION_VALUES,
    forbidden_term_hits,
    run_alternative_market_consensus,
)


def test_ticker_list_is_derived_from_snapshot_not_hardcoded(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA", "BBB", "CCC"])

    result = _run(paths)

    primary = result.alternative_market_observations[
        result.alternative_market_observations["source_provider_id"].eq("vnstock_primary_reference")
    ]
    assert result.decision["pilot_ticker_count"] == 3
    assert set(primary["ticker"]) == {"AAA", "BBB", "CCC"}


def test_missing_vnquant_package_does_not_fail_run(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"])

    result = _run(paths, import_module_func=_missing_importer)
    status = result.provider_runtime_status.set_index("provider_id")

    assert status.loc["vnquant_secondary_candidate", "runtime_status"] == "PROVIDER_NOT_IMPORTABLE"
    assert result.decision["final_decision"] == "CONDITIONAL_GO_FOR_STEP19_SHADOW_20"


def test_missing_vietfin_package_does_not_fail_run(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"])

    result = _run(paths, import_module_func=_missing_importer)
    status = result.provider_runtime_status.set_index("provider_id")

    assert status.loc["vietfin_experimental_candidate", "runtime_status"] == "PROVIDER_NOT_IMPORTABLE"
    assert result.decision["provider_not_importable_count"] == 2


def test_static_github_historical_fallback_is_not_current_confirmation(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"])
    _write_prior_historical(paths["prior_crosscheck"], "AAA")

    result = _run(paths, import_module_func=_missing_importer)
    static_rows = result.alternative_market_observations[
        result.alternative_market_observations["source_family"].eq("static_github_historical")
    ]

    assert not static_rows.empty
    assert static_rows["is_current_enough"].map(_as_bool).sum() == 0
    assert static_rows["is_independent_current_candidate"].map(_as_bool).sum() == 0


def test_raw_cache_is_never_independent_current_source_family(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"], write_raw=True)

    result = _run(paths, import_module_func=_missing_importer)
    raw_rows = result.alternative_market_observations[
        result.alternative_market_observations["source_provider_id"].eq("raw_cache_current_market_03")
    ]
    consensus = result.source_family_consensus.set_index("ticker")

    assert not raw_rows.empty
    assert raw_rows["is_independent_current_candidate"].map(_as_bool).sum() == 0
    assert consensus.loc["AAA", "consensus_confidence"] == "PROVISIONAL_LOW_PLUS"


def test_price_mismatch_above_threshold_creates_manual_review(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"])

    result = _run(
        paths,
        import_module_func=_vnquant_only_importer,
        provider_fetchers={"vnquant_secondary_candidate": _vnquant_mismatch_fetcher},
    )

    assert "PRICE_MISMATCH" in set(result.alternative_market_observations["observation_status"])
    assert not result.manual_review_cases.empty
    assert result.source_family_consensus.iloc[0]["consensus_confidence"] == "MANUAL_REVIEW"


def test_same_upstream_source_family_counts_once(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"])

    result = _run(
        paths,
        import_module_func=_vnquant_only_importer,
        provider_fetchers={"vnquant_secondary_candidate": _duplicate_family_match_fetcher},
    )
    consensus = result.source_family_consensus.set_index("ticker")

    assert consensus.loc["AAA", "independent_current_source_family_count"] == 1
    assert result.decision["independent_current_source_family_count"] == 1


def test_core_output_files_are_not_modified(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"])
    core = tmp_path / "core.csv"
    core.write_text("ticker,value\nAAA,1\n", encoding="utf-8")
    before = core.read_text(encoding="utf-8")

    result = _run(paths, import_module_func=_missing_importer, core_output_paths=[core])

    assert core.read_text(encoding="utf-8") == before
    assert result.decision["core_outputs_modified"] is False


def test_forbidden_output_terms_do_not_appear(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"])

    _run(paths, import_module_func=_missing_importer)

    assert forbidden_term_hits(paths["output"]) == []


def test_final_decision_is_allowed_value(tmp_path: Path):
    paths = _write_fixture(tmp_path, ["AAA"])

    result = _run(paths, import_module_func=_missing_importer)

    assert result.decision["final_decision"] in DECISION_VALUES


def _run(paths: dict[str, Path], **kwargs):
    return run_alternative_market_consensus(
        snapshot_path=paths["snapshot"],
        output_dir=paths["output"],
        config_path=paths["config"],
        raw_cache_dir=paths["raw"],
        prior_crosscheck_path=paths["prior_crosscheck"],
        **kwargs,
    )


def _write_fixture(tmp_path: Path, tickers: list[str], *, write_raw: bool = False) -> dict[str, Path]:
    snapshot = tmp_path / "current_market_snapshot.csv"
    output = tmp_path / "out"
    raw = tmp_path / "raw"
    prior_crosscheck = tmp_path / "market_crosscheck_20.csv"
    config = tmp_path / "config.yaml"
    raw.mkdir(parents=True, exist_ok=True)
    _write_config(config, len(tickers))
    rows = []
    for ticker in tickers:
        rows.append(
            {
                "ticker": ticker,
                "market_source": "vnstock_quote_vci_history",
                "fetch_status": "FETCH_OK",
                "last_close": 10.0,
                "last_price_date": "2026-06-11",
                "last_volume": 300.0,
                "avg_volume_20d": 200.0,
                "avg_volume_60d": 200.0,
                "trading_days_20d": 20,
                "trading_days_60d": 60,
                "missing_market_flag": False,
                "stale_price_flag": False,
            }
        )
        if write_raw:
            pd.DataFrame(
                [
                    {"ticker": ticker, "date": "2026-06-10", "close": 9.0, "volume": 100},
                    {"ticker": ticker, "date": "2026-06-11", "close": 10.0, "volume": 300},
                ]
            ).to_csv(raw / f"{ticker}_history.csv", index=False)
    pd.DataFrame(rows).to_csv(snapshot, index=False)
    pd.DataFrame(columns=["ticker", "reference_source_name", "reference_last_price_date", "reference_last_close"]).to_csv(prior_crosscheck, index=False)
    return {
        "snapshot": snapshot,
        "output": output,
        "raw": raw,
        "prior_crosscheck": prior_crosscheck,
        "config": config,
    }


def _write_config(path: Path, max_tickers: int) -> None:
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "safety:",
                "  sandbox_only: true",
                "  no_core_pipeline_mutation: true",
                "  no_ranking_mutation: true",
                "  no_stage_promotion: true",
                "  no_step19: true",
                "  no_real_data_02: true",
                "  no_top500_refresh: true",
                "  no_full_universe_fetch: true",
                "  no_official_pdf_fetch: true",
                "  no_ocr: true",
                "run_policy:",
                f"  max_tickers: {max_tickers}",
                "  allow_network_fetch: true",
                "  allow_market_data_fetch: true",
                "  allow_finance_data_fetch: false",
                "  allow_auto_install: false",
                "comparison:",
                "  max_current_reference_gap_days: 5",
                "  max_price_pct_diff_for_match: 0.03",
                "  max_volume_60d_pct_diff_for_match: 0.50",
                "  min_independent_current_source_families_for_medium_confidence: 1",
                "  min_independent_current_source_families_for_medium_high_confidence: 2",
                "source_family_rules:",
                "  primary_source_family: vnstock_vci",
                "  raw_cache_is_independent: false",
                "  static_github_historical_is_current_confirmation: false",
                "  same_upstream_family_counts_once: true",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_prior_historical(path: Path, ticker: str) -> None:
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "reference_source_name": "provisional_crosscheck_02_public_historical",
                "reference_last_price_date": "2023-06-30",
                "reference_last_close": 10000.0,
                "reference_avg_volume_20d": 100.0,
                "reference_avg_volume_60d": 100.0,
            }
        ]
    ).to_csv(path, index=False)


def _missing_importer(package: str):
    raise ModuleNotFoundError(f"No module named {package}")


def _vnquant_only_importer(package: str):
    if package == "vnquant":
        return object()
    raise ModuleNotFoundError(f"No module named {package}")


def _vnquant_mismatch_fetcher(module, tickers, source_families, config):
    return [
        {
            "ticker": tickers[0],
            "source_family": "cafef",
            "last_price_date": "2026-06-11",
            "last_close": 12.0,
            "avg_volume_60d": 200.0,
            "price_basis": "unadjusted",
        }
    ]


def _duplicate_family_match_fetcher(module, tickers, source_families, config):
    return [
        {
            "ticker": tickers[0],
            "source_family": "cafef",
            "last_price_date": "2026-06-11",
            "last_close": 10.0,
            "avg_volume_60d": 200.0,
            "price_basis": "unadjusted",
        },
        {
            "ticker": tickers[0],
            "source_family": "cafef",
            "last_price_date": "2026-06-11",
            "last_close": 10.0,
            "avg_volume_60d": 200.0,
            "price_basis": "unadjusted",
        },
    ]


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}
