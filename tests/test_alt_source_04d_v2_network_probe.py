from pathlib import Path

import pandas as pd

from src.providers.alternative.network_probe_04d_v2 import DECISION_VALUES, run_network_probe_04d_v2, scan_forbidden_terms


def test_exactly_20_tickers_required(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=19)

    result = _run(paths, find_spec_func=lambda package: None)

    assert result.decision["pilot_ticker_count"] == 19
    assert result.decision["final_decision"] == "NO_GO_FIX_PROVIDER_PROBE"


def test_network_disabled_is_no_go_for_v2(tmp_path: Path):
    paths = _write_fixture(tmp_path, allow_network=False)

    result = _run(paths, find_spec_func=lambda package: None)

    assert result.decision["network_allowed"] is False
    assert result.decision["final_decision"] == "NO_GO_FIX_PROVIDER_PROBE"


def test_missing_packages_are_not_importable_without_crash(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, find_spec_func=lambda package: None)

    assert "NOT_IMPORTABLE" in set(result.provider_network_attempt_log["attempt_status"])
    assert result.decision["provider_not_importable_count"] == 2
    assert result.decision["final_decision"] == "CONDITIONAL_GO_PRIMARY_ONLY_CONFIDENCE"


def test_mocked_network_match_can_pass_confidence_review(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(
        paths,
        find_spec_func=lambda package: object(),
        import_module_func=lambda package: object(),
        provider_fetchers={"vnquant": _matching_fetcher},
    )

    assert result.decision["network_used"] is True
    assert result.decision["tickers_with_independent_match_count"] == 20
    assert result.decision["final_decision"] == "PASS_FOR_CONFIDENCE_UPGRADE_REVIEW"


def test_static_github_historical_fallback_never_counts_current(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, find_spec_func=lambda package: None)
    static_rows = result.source_family_consensus[result.source_family_consensus["source_family"].eq("static_github_historical")]

    assert not static_rows.empty
    assert set(static_rows["comparison_status"]) == {"HISTORICAL_FALLBACK_ONLY"}
    assert result.decision["independent_current_source_family_count"] == 0


def test_raw_cache_never_counts_as_independent_confirmation(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(
        paths,
        find_spec_func=lambda package: object(),
        import_module_func=lambda package: object(),
        provider_fetchers={"vnquant": _raw_cache_fetcher},
    )

    assert "RAW_CACHE_NO_CONFIDENCE" in set(result.source_family_consensus["comparison_status"])
    assert result.decision["tickers_with_independent_match_count"] == 0


def test_core_outputs_are_not_modified(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    core = tmp_path / "core.csv"
    core.write_text("ticker,value\nT001,1\n", encoding="utf-8")
    before = core.read_text(encoding="utf-8")

    result = _run(paths, find_spec_func=lambda package: None, core_output_paths=[core])

    assert core.read_text(encoding="utf-8") == before
    assert result.decision["core_outputs_modified"] is False


def test_forbidden_terms_do_not_appear_as_actionable_output(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths, find_spec_func=lambda package: None)
    scan = scan_forbidden_terms(paths["output"])

    assert scan["actionable_hits"] == []


def test_decision_is_allowed_value(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, find_spec_func=lambda package: None)

    assert result.decision["final_decision"] in DECISION_VALUES


def _run(paths: dict[str, Path], **kwargs):
    return run_network_probe_04d_v2(
        config_path=paths["config"],
        snapshot_path=paths["snapshot"],
        output_dir=paths["output"],
        cache_dir=paths["cache"],
        sleep_seconds=0,
        **kwargs,
    )


def _write_fixture(tmp_path: Path, *, ticker_count: int = 20, allow_network: bool = True) -> dict[str, Path]:
    snapshot = tmp_path / "current_market_snapshot.csv"
    output = tmp_path / "out"
    cache = tmp_path / "cache"
    config = tmp_path / "config.yaml"
    tickers = [f"T{index:03d}" for index in range(1, ticker_count + 1)]
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "last_price_date": "2026-06-11",
                "last_close": 10.0,
                "avg_volume_20d": 1000.0,
                "avg_volume_60d": 1000.0,
                "trading_days_60d": 60,
            }
            for ticker in tickers
        ]
    ).to_csv(snapshot, index=False)
    _write_config(config, snapshot=snapshot, allow_network=allow_network)
    return {"snapshot": snapshot, "output": output, "cache": cache, "config": config}


def _write_config(path: Path, *, snapshot: Path, allow_network: bool) -> None:
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "safety:",
                "  sandbox_only: true",
                "  no_core_pipeline_mutation: true",
                "  no_ranking_mutation: true",
                "  no_stage_promotion: true",
                "  no_production_step19: true",
                "  no_step19_output_mutation: true",
                "  no_real_data_02_rerun: true",
                "  no_top500_refresh: true",
                "  no_full_universe_fetch: true",
                "  no_finance_fetch: true",
                "  no_official_pdf_fetch: true",
                "  no_ocr: true",
                "  no_zero_fill: true",
                "run_policy:",
                "  expected_pilot_ticker_count: 20",
                f"  allow_network: {str(allow_network).lower()}",
                "  allow_optional_install: false",
                "  allow_partial: true",
                "  max_requests: 40",
                "  sleep_seconds: 0",
                "  timeout_seconds: 20",
                "comparison:",
                "  max_current_reference_gap_days: 5",
                "  max_price_pct_diff_for_match: 0.03",
                "  max_volume_60d_pct_diff_for_match: 0.50",
                "  pass_min_independent_match_tickers: 15",
                "inputs:",
                "  ticker_sources:",
                f"    - {snapshot.as_posix()}",
                f"  primary_snapshot: {snapshot.as_posix()}",
                "source_family_rules:",
                "  primary_source_family: vnstock_vci",
                "  raw_cache_is_independent: false",
                "  static_github_historical_is_current_confirmation: false",
                "providers:",
                "  - provider_name: vnquant",
                "    package_name: vnquant",
                "    source_families:",
                "      - source_family: cafef_structured_or_market",
                "        data_source: cafe",
                "        candidate_independent_from_primary: true",
                "        default_enabled: true",
                "        source_url_or_endpoint_family: vnquant_cafef",
                "  - provider_name: vietfin",
                "    package_name: vietfin",
                "    source_families:",
                "      - source_family: unknown_brokerage_api",
                "        data_source: unknown",
                "        candidate_independent_from_primary: false",
                "        default_enabled: true",
                "        source_url_or_endpoint_family: vietfin_unknown",
                "  - provider_name: vnstock_market_data",
                "    package_name: null",
                "    source_families:",
                "      - source_family: static_github_historical",
                "        data_source: static_github",
                "        candidate_independent_from_primary: false",
                "        default_enabled: true",
                "        source_url_or_endpoint_family: vnstock_market_data_static",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _matching_fetcher(**kwargs):
    return {
        "last_price_date": "2026-06-11",
        "last_close": 10.0,
        "avg_volume_20d": 1000.0,
        "avg_volume_60d": 1000.0,
        "trading_days_60d": 60,
        "price_basis": "unadjusted",
        "raw_adjustment_status": "UNADJUSTED_OR_RAW",
        "network_used": True,
    }


def _raw_cache_fetcher(**kwargs):
    return {
        "last_price_date": "2026-06-11",
        "last_close": 10.0,
        "avg_volume_20d": 1000.0,
        "avg_volume_60d": 1000.0,
        "trading_days_60d": 60,
        "price_basis": "raw_cache",
        "raw_adjustment_status": "UNADJUSTED_OR_RAW",
        "network_used": False,
        "cache_only": True,
    }
