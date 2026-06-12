from pathlib import Path

import pandas as pd

from src.shadow.step19_shadow_20 import forbidden_term_hits, run_step19_shadow_20


def test_exactly_20_tickers_are_processed(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.decision["pilot_ticker_count"] == 20
    assert len(result.diagnostics) == 20


def test_missing_input_yields_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    paths["real_data_readiness"].unlink()

    result = _run(paths)
    summary = (paths["output"] / "step19_shadow_summary.md").read_text(encoding="utf-8")

    assert result.decision["final_decision"] == "NO_GO_FIX_SHADOW_PIPELINE"
    assert "NO_GO_MISSING_INPUT" in summary


def test_forbidden_terms_are_absent_from_all_outputs(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert forbidden_term_hits(paths["output"]) == []


def test_production_step19_flags_are_always_false(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert not result.diagnostics["production_step19_allowed"].map(_as_bool).any()


def test_valuation_and_recommendation_flags_are_always_false(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert not result.diagnostics["valuation_allowed"].map(_as_bool).any()
    assert not result.diagnostics["investment_recommendation_allowed"].map(_as_bool).any()


def test_market_confidence_reflects_zero_independent_source_family(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert set(result.diagnostics["independent_current_source_family_count"].astype(int)) == {0}
    assert set(result.diagnostics["market_source_confidence"]) == {"PROVISIONAL_PRIMARY_ONLY"}


def test_missing_net_income_is_preserved_as_warning_not_filled(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)
    net_income_reasons = result.reason_codes[
        result.reason_codes["reason_code"].eq("FINANCE_FIELD_MISSING")
        & result.reason_codes["field_name"].eq("net_income")
    ]

    assert len(net_income_reasons) == 13
    assert set(net_income_reasons["severity"]) == {"WARN"}


def test_raw_cache_is_not_counted_as_independent_source_family(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)
    raw_reasons = result.reason_codes[result.reason_codes["reason_code"].eq("MARKET_RAW_CACHE_NOT_INDEPENDENT")]

    assert len(raw_reasons) == 20
    assert result.decision["market_source_confidence_distribution"] == {"PROVISIONAL_PRIMARY_ONLY": 20}


def test_no_output_writes_into_core_ranking_stage_evidence_directories(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    core_file = paths["core_dir"] / "core_output.csv"
    before = core_file.read_text(encoding="utf-8")

    result = run_step19_shadow_20(
        config_path=paths["config"],
        output_dir=paths["output"],
        core_output_paths=[core_file],
    )

    assert core_file.read_text(encoding="utf-8") == before
    assert result.decision["core_outputs_modified"] is False
    assert not any(path.name.startswith("company_shadow_") for path in paths["core_dir"].glob("*"))


def _run(paths: dict[str, Path]):
    return run_step19_shadow_20(config_path=paths["config"], output_dir=paths["output"])


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    output = tmp_path / "out"
    core_dir = tmp_path / "core"
    core_dir.mkdir(parents=True, exist_ok=True)
    (core_dir / "core_output.csv").write_text("ticker,value\nT001,1\n", encoding="utf-8")

    snapshot = tmp_path / "current_market_snapshot.csv"
    stage2 = tmp_path / "stage2_eligibility_gate.csv"
    ranking = tmp_path / "current_market_balanced_ranked_shortlist.csv"
    evidence_summary = tmp_path / "run_summary.md"
    real_data_readiness = tmp_path / "real_data_02_pilot_readiness.csv"
    real_data_summary = tmp_path / "real_data_summary.md"
    observations = tmp_path / "alternative_market_observations_20.csv"
    consensus = tmp_path / "source_family_consensus_20.csv"
    alt_summary = tmp_path / "alternative_market_consensus_summary.md"
    config = tmp_path / "policy.yaml"

    tickers = [f"T{index:03d}" for index in range(1, 21)]
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "last_close": 10.0 + index,
                "last_price_date": "2026-06-11",
                "missing_market_flag": False,
                "stale_price_flag": False,
            }
            for index, ticker in enumerate(tickers)
        ]
    ).to_csv(snapshot, index=False)
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "finance_crosscheck_status": "ONE_SOURCE_ONLY",
                "finance_confidence": "PROVISIONAL_LOW",
                "finance_quality_status": "PARTIAL_PROVISIONAL_DATA",
            }
            for ticker in tickers
        ]
    ).to_csv(stage2, index=False)
    pd.DataFrame([{"ticker": ticker, "rank": index + 1} for index, ticker in enumerate(tickers)]).to_csv(ranking, index=False)
    evidence_summary.write_text("# evidence summary\n", encoding="utf-8")
    real_data_summary.write_text("# real data summary\n", encoding="utf-8")
    alt_summary.write_text("# alt source summary\n", encoding="utf-8")
    readiness_rows = []
    for index, ticker in enumerate(tickers):
        missing = "net_income" if index < 13 else ""
        readiness_rows.append(
            {
                "ticker": ticker,
                "market_data_confidence": "PROVISIONAL_PRIMARY",
                "finance_data_confidence": "ONE_SOURCE_ONLY",
                "metadata_confidence": "PROVISIONAL_LOW",
                "readiness_status": "CONDITIONAL_READY" if missing else "READY_FOR_SHADOW",
                "critical_failures": "",
                "warnings": "FINANCE_FIELD_MISSING" if missing else "",
                "missing_fields": missing,
            }
        )
    pd.DataFrame(readiness_rows).to_csv(real_data_readiness, index=False)
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "source_provider_id": "vnstock_primary_reference",
                "source_family": "vnstock_vci",
                "observation_status": "PRIMARY_OK",
                "is_independent_current_candidate": False,
            }
            for ticker in tickers
        ]
        + [
            {
                "ticker": ticker,
                "source_provider_id": "raw_cache_current_market_03",
                "source_family": "vnstock_vci",
                "observation_status": "NOT_INDEPENDENT_SAME_SOURCE_FAMILY",
                "is_independent_current_candidate": False,
            }
            for ticker in tickers
        ]
    ).to_csv(observations, index=False)
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "primary_status": "PRIMARY_OK",
                "independent_current_source_family_count": 0,
                "consensus_confidence": "PROVISIONAL_LOW_PLUS",
            }
            for ticker in tickers
        ]
    ).to_csv(consensus, index=False)
    _write_config(
        config,
        {
            "snapshot": snapshot,
            "stage2": stage2,
            "ranking": ranking,
            "evidence_summary": evidence_summary,
            "real_data_readiness": real_data_readiness,
            "real_data_summary": real_data_summary,
            "observations": observations,
            "consensus": consensus,
            "alt_summary": alt_summary,
            "core": core_dir / "core_output.csv",
        },
    )
    return {
        "output": output,
        "core_dir": core_dir,
        "config": config,
        "real_data_readiness": real_data_readiness,
    }


def _write_config(path: Path, inputs: dict[str, Path]) -> None:
    path.write_text(
        "\n".join(
            [
                "version: 1",
                "safety:",
                "  shadow_only: true",
                "  no_production_step19: true",
                "  no_core_pipeline_mutation: true",
                "  no_ranking_mutation: true",
                "  no_stage_promotion: true",
                "  no_real_data_02_rerun: true",
                "  no_top500_refresh: true",
                "  no_full_universe_fetch: true",
                "  no_official_pdf_fetch: true",
                "  no_ocr: true",
                "  no_web_scraping: true",
                "  no_live_market_fetch: true",
                "  no_finance_fetch: true",
                "run_policy:",
                "  expected_pilot_ticker_count: 20",
                "  finance_source_confidence: PROVISIONAL_LOW",
                "  market_source_confidence_when_no_independent: PROVISIONAL_PRIMARY_ONLY",
                "inputs:",
                f"  current_market_snapshot: ['{inputs['snapshot'].as_posix()}']",
                f"  stage2_eligibility_gate: ['{inputs['stage2'].as_posix()}']",
                f"  current_market_ranked_shortlist: ['{inputs['ranking'].as_posix()}']",
                f"  evidence_pack_summary: ['{inputs['evidence_summary'].as_posix()}']",
                f"  real_data_02_readiness: ['{inputs['real_data_readiness'].as_posix()}']",
                f"  real_data_02_summary: ['{inputs['real_data_summary'].as_posix()}']",
                f"  alt_source_04b_observations: ['{inputs['observations'].as_posix()}']",
                f"  alt_source_04b_consensus: ['{inputs['consensus'].as_posix()}']",
                f"  alt_source_04b_summary: ['{inputs['alt_summary'].as_posix()}']",
                "core_output_watchlist:",
                f"  - {inputs['core'].as_posix()}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}
