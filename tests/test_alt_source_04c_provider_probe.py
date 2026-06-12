from pathlib import Path

import pandas as pd

from src.providers.alternative.provider_probe_04c import DECISION_VALUES, forbidden_term_hits, run_provider_probe_04c


def test_missing_provider_package_does_not_crash(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, find_spec_func=lambda package: None, version_func=lambda package: "")

    assert result.decision["final_decision"] == "CONDITIONAL_GO_NO_INDEPENDENT_CONFIRMATION"
    assert "PACKAGE_NOT_FOUND" in set(result.provider_installability["import_status"])


def test_import_error_is_logged_cleanly(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(
        paths,
        find_spec_func=lambda package: object(),
        import_module_func=lambda package: (_ for _ in ()).throw(RuntimeError("boom")),
        version_func=lambda package: "0.test",
    )

    row = result.provider_installability[result.provider_installability["provider_name"].eq("vnquant")].iloc[0]
    assert row["import_status"] == "IMPORT_ERROR"
    assert row["import_error_type"] == "RuntimeError"


def test_network_disabled_skips_fetch_and_returns_conditional(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, find_spec_func=lambda package: object(), import_module_func=lambda package: object(), version_func=lambda package: "0.test")

    assert "FETCH_SKIPPED_NETWORK_DISABLED" in set(result.provider_probe_attempt_log["attempt_status"])
    assert result.decision["provider_fetch_attempt_count"] == 0
    assert result.decision["final_decision"] == "CONDITIONAL_GO_NO_INDEPENDENT_CONFIRMATION"


def test_exact_20_tickers_are_derived_from_snapshot(tmp_path: Path):
    paths = _write_fixture(tmp_path, prefix="Z")

    result = _run(paths, find_spec_func=lambda package: None, version_func=lambda package: "")

    primary_rows = result.provider_probe_attempt_log[result.provider_probe_attempt_log["provider_name"].eq("vnstock")]
    assert result.decision["pilot_ticker_count"] == 20
    assert set(primary_rows["ticker"]) == {f"Z{index:03d}" for index in range(1, 21)}


def test_stale_historical_fallback_never_counts_as_current_confirmation(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, find_spec_func=lambda package: None, version_func=lambda package: "")
    rows = result.source_family_independence_audit[result.source_family_independence_audit["source_family"].eq("static_github_historical")]

    assert not rows.empty
    assert not rows["independent_current_confirmation"].map(_as_bool).any()
    assert rows["current_observation_count"].astype(int).sum() == 0


def test_raw_cache_or_same_source_family_does_not_count_as_independent(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, find_spec_func=lambda package: None, version_func=lambda package: "")
    rows = result.source_family_independence_audit[result.source_family_independence_audit["source_family"].eq("vnstock_vci")]

    assert not rows.empty
    assert not rows["independent_current_confirmation"].map(_as_bool).any()


def test_price_mismatch_above_threshold_triggers_manual_review(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(
        paths,
        allow_network=True,
        find_spec_func=lambda package: object(),
        import_module_func=lambda package: object(),
        version_func=lambda package: "0.test",
        provider_fetchers={"vnquant": _mismatch_fetcher},
    )

    assert "PRICE_MISMATCH" in set(result.alternative_provider_market_observations["comparison_status"])
    assert not result.manual_review_cases.empty


def test_forbidden_output_words_are_absent(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths, find_spec_func=lambda package: None, version_func=lambda package: "")

    assert forbidden_term_hits(paths["output"]) == []


def test_core_outputs_are_not_modified(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    core = tmp_path / "core.csv"
    core.write_text("ticker,value\nT001,1\n", encoding="utf-8")
    before = core.read_text(encoding="utf-8")

    result = _run(paths, find_spec_func=lambda package: None, version_func=lambda package: "", core_output_paths=[core])

    assert core.read_text(encoding="utf-8") == before
    assert result.decision["core_outputs_modified"] is False


def test_decision_json_uses_only_allowed_values(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths, find_spec_func=lambda package: None, version_func=lambda package: "")

    assert result.decision["final_decision"] in DECISION_VALUES


def _run(paths: dict[str, Path], **kwargs):
    return run_provider_probe_04c(
        config_path=paths["config"],
        pilot_snapshot_path=paths["snapshot"],
        output_dir=paths["output"],
        cache_dir=paths["cache"],
        max_requests=20,
        sleep_seconds=0,
        allow_network=kwargs.pop("allow_network", False),
        **kwargs,
    )


def _write_fixture(tmp_path: Path, *, prefix: str = "T") -> dict[str, Path]:
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
                "missing_market_flag": False,
                "stale_price_flag": False,
            }
            for ticker in tickers
        ]
    ).to_csv(snapshot, index=False)
    _write_config(config)
    return {"snapshot": snapshot, "output": output, "cache": cache, "config": config}


def _write_config(path: Path) -> None:
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
                "  no_real_data_02_rerun: true",
                "  no_top500_refresh: true",
                "  no_full_universe_fetch: true",
                "  no_official_pdf_fetch: true",
                "  no_ocr: true",
                "  no_finance_fetch: true",
                "  no_zero_fill: true",
                "run_policy:",
                "  expected_pilot_ticker_count: 20",
                "  allow_network: false",
                "  allow_auto_install: false",
                "  max_requests: 20",
                "  sleep_seconds: 0",
                "comparison:",
                "  max_current_reference_gap_days: 5",
                "  max_price_pct_diff_for_match: 0.03",
                "  max_volume_60d_pct_diff_for_match: 0.50",
                "source_family_rules:",
                "  primary_source_family: vnstock_vci",
                "  raw_cache_is_independent: false",
                "  static_github_historical_is_current_confirmation: false",
                "  same_upstream_family_counts_once: true",
                "providers:",
                "  - provider_name: vnstock",
                "    package_name: vnstock",
                "    role: primary_reference",
                "    source_families:",
                "      - source_family: vnstock_vci",
                "        candidate_independent_from_vnstock_vci: false",
                "        market_current_candidate: true",
                "        historical_candidate: true",
                "        finance_candidate: false",
                "        requires_network: false",
                "        requires_optional_install: false",
                "        default_enabled: false",
                "        confidence_ceiling: PROVISIONAL_PRIMARY",
                "        notes: primary",
                "  - provider_name: vnquant",
                "    package_name: vnquant",
                "    role: secondary_candidate",
                "    source_families:",
                "      - source_family: cafef_structured_or_market",
                "        candidate_independent_from_vnstock_vci: true",
                "        market_current_candidate: true",
                "        historical_candidate: true",
                "        finance_candidate: false",
                "        requires_network: true",
                "        requires_optional_install: true",
                "        default_enabled: true",
                "        confidence_ceiling: PROVISIONAL_SECONDARY",
                "        notes: cafef",
                "  - provider_name: vietfin",
                "    package_name: vietfin",
                "    role: experimental_secondary_candidate",
                "    source_families:",
                "      - source_family: unknown_brokerage_api",
                "        candidate_independent_from_vnstock_vci: false",
                "        market_current_candidate: true",
                "        historical_candidate: false",
                "        finance_candidate: false",
                "        requires_network: true",
                "        requires_optional_install: true",
                "        default_enabled: true",
                "        confidence_ceiling: PROVISIONAL_EXPERIMENTAL",
                "        notes: unknown",
                "  - provider_name: vnstock_market_data",
                "    package_name: null",
                "    role: static_historical_fallback_only",
                "    source_families:",
                "      - source_family: static_github_historical",
                "        candidate_independent_from_vnstock_vci: false",
                "        market_current_candidate: false",
                "        historical_candidate: true",
                "        finance_candidate: false",
                "        requires_network: false",
                "        requires_optional_install: false",
                "        default_enabled: true",
                "        confidence_ceiling: HISTORICAL_FALLBACK_ONLY",
                "        notes: historical",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _mismatch_fetcher(**kwargs):
    ticker = kwargs["tickers"][0]
    return [
        {
            "ticker": ticker,
            "provider_name": "vnquant",
            "source_family": "cafef_structured_or_market",
            "attempt_status": "FETCH_OK",
            "network_used": True,
            "cache_used": False,
            "fetch_attempted": True,
            "rows_returned": 1,
            "last_price_date": "2026-06-11",
            "last_close": 12.0,
            "avg_volume_20d": 1000.0,
            "avg_volume_60d": 1000.0,
            "raw_cache_path": "",
            "price_basis": "unadjusted",
        }
    ]


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}
