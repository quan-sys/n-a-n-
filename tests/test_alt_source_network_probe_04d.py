from pathlib import Path

import pandas as pd

from src.providers.alternative.network_probe_04d import DECISION_VALUES, _normalize_frame, run_network_probe_04d, scan_forbidden_terms


def test_default_run_does_not_use_network(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.decision["network_used"] is False
    assert set(result.provider_network_attempt_log["attempt_status"]) >= {"NETWORK_DISABLED", "PROVIDER_NOT_SUPPORTED"}
    assert result.decision["final_decision"] == "CONDITIONAL_GO_FOR_SCALE_DECISION_WITH_PRIMARY_ONLY_MARKET_CONFIDENCE"


def test_allow_network_enables_mocked_fetch_path(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(
        paths,
        allow_network=True,
        allow_partial=True,
        find_spec_func=lambda package: object(),
        import_module_func=lambda package: object(),
        provider_fetchers={"vnquant": _matching_fetcher},
    )

    assert result.decision["network_used"] is True
    assert result.decision["provider_count_fetch_ok"] == 1
    assert result.decision["tickers_with_independent_match_count"] == 20


def test_provider_import_error_is_logged_not_fatal(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(
        paths,
        allow_network=True,
        allow_partial=True,
        find_spec_func=lambda package: object(),
        import_module_func=lambda package: (_ for _ in ()).throw(RuntimeError("import boom")),
    )

    assert "IMPORT_ERROR" in set(result.provider_network_attempt_log["attempt_status"])
    assert result.decision["final_decision"] == "CONDITIONAL_GO_FOR_SCALE_DECISION_WITH_PRIMARY_ONLY_MARKET_CONFIDENCE"


def test_optional_install_is_not_used_unless_flag_is_passed(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, allow_network=True, find_spec_func=lambda package: None)

    assert result.decision["optional_install_used"] is False
    assert "INSTALL_SKIPPED" not in set(result.provider_network_attempt_log["attempt_status"])


def test_same_source_family_match_does_not_count_as_independent(tmp_path: Path):
    paths = _write_fixture(tmp_path, vnquant_family="vnstock_vci", independent=False)

    result = _run(
        paths,
        allow_network=True,
        allow_partial=True,
        find_spec_func=lambda package: object(),
        import_module_func=lambda package: object(),
        provider_fetchers={"vnquant": _matching_fetcher},
    )

    assert "NOT_INDEPENDENT_SAME_SOURCE_FAMILY" in set(result.source_family_current_consensus["comparison_status"])
    assert result.decision["independent_current_source_family_count"] == 0


def test_static_historical_fallback_does_not_count_as_current_confirmation(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)
    static_rows = result.source_family_current_consensus[
        result.source_family_current_consensus["source_family"].eq("static_github_historical")
    ]

    assert not static_rows.empty
    assert set(static_rows["comparison_status"]) == {"HISTORICAL_FALLBACK_ONLY"}
    assert result.decision["independent_current_source_family_count"] == 0


def test_adjusted_or_unknown_price_is_not_counted_as_clean_match(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(
        paths,
        allow_network=True,
        allow_partial=True,
        find_spec_func=lambda package: object(),
        import_module_func=lambda package: object(),
        provider_fetchers={"vnquant": _adjusted_fetcher},
    )

    assert "ADJUSTED_PRICE_NOT_COMPARABLE" in set(result.source_family_current_consensus["comparison_status"])
    assert result.decision["independent_current_source_family_count"] == 0
    assert result.decision["manual_review_count"] == 20


def test_vnquant_style_numeric_table_can_be_normalized(tmp_path: Path):
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(["2026-06-10", "2026-06-11"]),
            "close_VIX": [9.8, 10.0],
            "volume_VIX": [900, 1100],
        }
    )

    normalized = _normalize_frame(frame, cache_path=str(tmp_path / "cache.csv"))

    assert normalized["last_price_date"] == "2026-06-11"
    assert normalized["last_close"] == 10.0
    assert normalized["avg_volume_20d"] == 1000.0


def test_exact_20_tickers_are_derived_from_snapshot_not_hardcoded(tmp_path: Path):
    paths = _write_fixture(tmp_path, prefix="Z")

    result = _run(paths)

    assert result.decision["pilot_ticker_count"] == 20
    assert set(result.provider_network_attempt_log["ticker"]) == {f"Z{index:03d}" for index in range(1, 21)}


def test_core_output_files_are_not_modified(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    core = tmp_path / "core.csv"
    core.write_text("ticker,value\nT001,1\n", encoding="utf-8")
    before = core.read_text(encoding="utf-8")

    result = _run(paths, core_output_paths=[core])

    assert core.read_text(encoding="utf-8") == before
    assert result.decision["core_outputs_modified"] is False


def test_forbidden_terms_do_not_appear_as_actionable_output(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)
    scan = scan_forbidden_terms(paths["output"])

    assert scan["actionable_hits"] == []


def test_decision_is_allowed_value(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.decision["final_decision"] in DECISION_VALUES


def _run(paths: dict[str, Path], **kwargs):
    return run_network_probe_04d(
        config_path=paths["config"],
        output_dir=paths["output"],
        cache_dir=paths["cache"],
        max_requests=kwargs.pop("max_requests", 40),
        sleep_seconds=0,
        **kwargs,
    )


def _write_fixture(tmp_path: Path, *, prefix: str = "T", vnquant_family: str = "cafef_structured_or_market", independent: bool = True) -> dict[str, Path]:
    snapshot = tmp_path / "current_market_snapshot.csv"
    output = tmp_path / "out"
    cache = tmp_path / "cache"
    config = tmp_path / "config.yaml"
    tickers = [f"{prefix}{index:03d}" for index in range(1, 21)]
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
    _write_config(config, snapshot=snapshot, vnquant_family=vnquant_family, independent=independent)
    return {"snapshot": snapshot, "output": output, "cache": cache, "config": config}


def _write_config(path: Path, *, snapshot: Path, vnquant_family: str, independent: bool) -> None:
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
                "  allow_network: false",
                "  allow_optional_install: false",
                "  allow_partial: false",
                "  max_requests: 40",
                "  sleep_seconds: 0",
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
                "  same_upstream_family_counts_once: true",
                "providers:",
                "  - provider_name: vnquant",
                "    package_name: vnquant",
                "    role: secondary_candidate",
                "    source_families:",
                f"      - source_family: {vnquant_family}",
                "        data_source: cafe",
                f"        candidate_independent_from_primary: {str(independent).lower()}",
                "        default_enabled: true",
                "        source_url_or_endpoint_family: vnquant_cafef",
                "  - provider_name: vnstock_market_data",
                "    package_name: null",
                "    role: static_historical_fallback_only",
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
    }


def _adjusted_fetcher(**kwargs):
    return {
        "last_price_date": "2026-06-11",
        "last_close": 10.0,
        "avg_volume_20d": 1000.0,
        "avg_volume_60d": 1000.0,
        "trading_days_60d": 60,
        "price_basis": "adjusted",
        "raw_adjustment_status": "ADJUSTED_OR_UNKNOWN",
    }
