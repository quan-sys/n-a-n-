import json
from pathlib import Path

import pandas as pd

from src.audit.step26_full_universe_output_audit_first_shortlist import (
    FINAL_DECISIONS,
    build_data_coverage_by_ticker,
    build_distribution,
    build_schema_gap_report,
    build_sector_summary,
    build_shortlists,
    find_step25_artifacts,
    normalize_rows,
    parse_listish,
    run_step26_full_universe_output_audit_first_shortlist,
    scan_forbidden_terms,
)


REQUIRED_EXPORTS = {
    "step26_audit_summary.json",
    "step26_full_universe_audit_report.md",
    "normalized_universe_rows.csv",
    "status_distribution.csv",
    "source_confidence_distribution.csv",
    "manual_review_distribution.csv",
    "block_reason_distribution.csv",
    "missing_field_distribution.csv",
    "reject_reason_distribution.csv",
    "data_coverage_by_ticker.csv",
    "data_gap_report.csv",
    "schema_gap_report.csv",
    "first_review_shortlist_50.csv",
    "manual_bctc_priority_queue_100.csv",
    "surviving_primary_only_candidates.csv",
    "data_repair_priority_queue.csv",
    "sector_candidate_distribution.csv",
    "micro_sector_candidate_distribution.csv",
    "sector_data_gap_summary.csv",
    "run_manifest.json",
}


def test_step25_artifact_discovery_expected_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    artifacts = find_step25_artifacts(_config(paths))

    assert artifacts.step25_rows_path == paths["rows"]
    assert artifacts.watchlist_path == paths["watchlist"]
    assert artifacts.manual_queue_path == paths["manual"]
    assert artifacts.blocked_path == paths["blocked"]


def test_step25_artifact_discovery_fallback_path(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fallback_dir = tmp_path / "data" / "reports" / "other_step25_output"
    fallback_dir.mkdir(parents=True)
    fallback_rows = fallback_dir / "step25_full_universe_1743_primary_only_rows.csv"
    pd.DataFrame([_row("T001")]).to_csv(fallback_rows, index=False)

    artifacts = find_step25_artifacts(_config({"search_dir": tmp_path / "missing"}))

    assert artifacts.step25_rows_path is not None
    assert artifacts.step25_rows_path.resolve() == fallback_rows


def test_missing_optional_columns_do_not_fabricate_data():
    source = pd.DataFrame([{"ticker": "T001", "screening_status": "WATCHLIST_CANDIDATE"}])

    normalized = normalize_rows(source)
    schema_gap = build_schema_gap_report(normalized, set(source.columns))

    assert normalized.loc[0, "sector"] == ""
    assert normalized.loc[0, "last_close"] == ""
    sector_gap = schema_gap[schema_gap["field_name"].eq("sector")].iloc[0]
    assert bool(sector_gap["present_in_step25_source"]) is False
    assert sector_gap["status"] == "SOURCE_FIELD_MISSING"


def test_status_distributions_count_correctly():
    rows = normalize_rows(pd.DataFrame([_row("T001"), _row("T002", status="BLOCKED_INSUFFICIENT_MARKET_DATA")]))

    distribution = build_distribution(rows, ["screening_status"])

    counts = {row["field_value"]: int(row["count"]) for _, row in distribution.iterrows()}
    assert counts == {"BLOCKED_INSUFFICIENT_MARKET_DATA": 1, "WATCHLIST_CANDIDATE": 1}


def test_missing_fields_parser_handles_common_list_formats():
    assert parse_listish('["last_close", "last_volume"]') == ["last_close", "last_volume"]
    assert parse_listish(["last_close", "last_volume"]) == ["last_close", "last_volume"]
    assert parse_listish("last_close; last_volume") == ["last_close", "last_volume"]
    assert parse_listish("last_close,last_volume") == ["last_close", "last_volume"]
    assert parse_listish("['last_close', 'last_volume']") == ["last_close", "last_volume"]


def test_data_coverage_score_is_technical_not_investment_related():
    rows = normalize_rows(pd.DataFrame([_row("T001")]))

    coverage = build_data_coverage_by_ticker(rows)

    assert "data_coverage_score" in coverage.columns
    assert "investment_score" not in coverage.columns
    assert "buy_score" not in coverage.columns
    assert "alpha_score" not in coverage.columns


def test_shortlist_excludes_severely_blocked_when_non_blocked_exist():
    rows = normalize_rows(
        pd.DataFrame(
            [
                _row("T001"),
                _row("T002"),
                _row("T003", status="BLOCKED_INSUFFICIENT_MARKET_DATA", last_close="", last_price_date=""),
            ]
        )
    )
    coverage = build_data_coverage_by_ticker(rows)

    first, _, _, _ = build_shortlists(_config({}), rows, coverage)

    assert set(first["ticker"]) == {"T001", "T002"}
    assert not first["screening_status"].astype(str).str.startswith("BLOCKED_").any()


def test_manual_bctc_priority_queue_prefers_manual_required_rows():
    rows = normalize_rows(pd.DataFrame([_row("T001", manual_bctc_required=True), _row("T002", manual_bctc_required=False)]))
    coverage = build_data_coverage_by_ticker(rows)

    _, manual_queue, _, _ = build_shortlists(_config({}), rows, coverage)

    assert set(manual_queue["ticker"]) == {"T001"}
    assert manual_queue["manual_bctc_required"].map(str).str.lower().eq("true").all()


def test_sector_summary_degrades_gracefully_when_sector_missing():
    rows = normalize_rows(pd.DataFrame([{"ticker": "T001", "screening_status": "WATCHLIST_CANDIDATE"}]))
    coverage = build_data_coverage_by_ticker(rows)

    summary = build_sector_summary(rows, coverage, "sector")

    assert summary.loc[0, "sector_or_micro_sector"] == "sector_classification_not_available_in_step25_output"


def test_forbidden_terms_scanner_blocks_unsafe_outputs(tmp_path: Path):
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "allowed.md").write_text("This report does not contain buy/sell/hold signals.\n", encoding="utf-8")
    assert scan_forbidden_terms(scan_dir) == []

    (scan_dir / "bad.txt").write_text(
        "buy sell hold target price fair value intrinsic value margin of safety expected return upside downside entry price exit price stoploss take profit recommended portfolio investment-ready",
        encoding="utf-8",
    )
    hits = scan_forbidden_terms(scan_dir)

    for term in [
        "buy",
        "sell",
        "hold",
        "target price",
        "fair value",
        "intrinsic value",
        "margin of safety",
        "expected return",
        "upside",
        "downside",
        "entry price",
        "exit price",
        "stoploss",
        "take profit",
        "recommended portfolio",
        "investment-ready",
    ]:
        assert any(hit.endswith(f":{term}") for hit in hits)


def test_prior_step25_artifacts_are_not_mutated(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)
    before = paths["rows"].read_text(encoding="utf-8")

    result = _run(paths, core_output_paths=[paths["rows"]])

    assert paths["rows"].read_text(encoding="utf-8") == before
    assert result.run_manifest["previous_step_outputs_mutated"] is False


def test_final_decision_is_allowed_and_exports_exist(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["final_decision"] in FINAL_DECISIONS
    assert result.summary["final_decision"] == "PASS_FULL_UNIVERSE_AUDIT_WITH_SHORTLIST"
    assert REQUIRED_EXPORTS.issubset({path.name for path in paths["output"].iterdir()})
    assert result.summary["forbidden_terms_found"] == []


def _run(paths: dict[str, Path], **kwargs):
    return run_step26_full_universe_output_audit_first_shortlist(
        config_path=paths["config"],
        output_dir=paths["output"],
        allow_partial=True,
        command_used="pytest step26",
        **kwargs,
    )


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    step25_dir = tmp_path / "data" / "reports" / "step25_full_universe_1743_primary_only_scale"
    output = tmp_path / "out"
    config = tmp_path / "config.yaml"
    step25_dir.mkdir(parents=True)
    rows = step25_dir / "full_universe_screening_rows.csv"
    watchlist = step25_dir / "watchlist_candidates.csv"
    manual = step25_dir / "manual_bctc_review_queue.csv"
    blocked = step25_dir / "blocked_tickers.csv"
    summary = step25_dir / "full_universe_scale_summary.json"
    manifest = step25_dir / "run_manifest.json"

    frame = pd.DataFrame(
        [
            _row("T001", trading_value=1000000),
            _row("T002", trading_value=900000),
            _row("T003", status="BLOCKED_INSUFFICIENT_MARKET_DATA", last_close="", last_price_date="", trading_value=""),
        ]
    )
    frame.to_csv(rows, index=False)
    frame[frame["screening_status"].eq("WATCHLIST_CANDIDATE")].to_csv(watchlist, index=False)
    frame[frame["manual_bctc_required"].map(bool)].to_csv(manual, index=False)
    frame[frame["screening_status"].str.startswith("BLOCKED_")].to_csv(blocked, index=False)
    summary.write_text(json.dumps({"final_decision": "PASS_FULL_UNIVERSE_PRIMARY_ONLY_WITH_WARNINGS"}), encoding="utf-8")
    manifest.write_text(json.dumps({"step_id": "STEP25"}), encoding="utf-8")
    _write_config(config, step25_dir=step25_dir, output=output, rows=rows, watchlist=watchlist, manual=manual, blocked=blocked)
    return {
        "config": config,
        "output": output,
        "rows": rows,
        "watchlist": watchlist,
        "manual": manual,
        "blocked": blocked,
        "search_dir": step25_dir,
    }


def _write_config(
    path: Path,
    *,
    step25_dir: Path,
    output: Path,
    rows: Path,
    watchlist: Path,
    manual: Path,
    blocked: Path,
) -> None:
    path.write_text(
        f"""
step_id: STEP26-FULL-UNIVERSE-OUTPUT-AUDIT-FIRST-SHORTLIST
mode: output_audit_first_shortlist
run:
  sandbox_only: true
  allow_partial: true
limits:
  expected_universe_size: 3
  max_rows_to_read: 10
  first_shortlist_size: 50
  bctc_priority_queue_size: 100
source_confidence:
  market_source_confidence: PROVISIONAL_PRIMARY_ONLY
  finance_source_confidence_default: PROVISIONAL_LOW
  crosscheck_status: NOT_AVAILABLE
  verification_status: NEEDS_MANUAL_BCTC_REVIEW
safety:
  no_recommendation: true
  no_buy_sell_hold: true
  no_target_price: true
  no_fair_value: true
  no_intrinsic_value: true
  no_margin_of_safety: true
  no_expected_return: true
  no_entry_exit_price: true
  no_portfolio_recommendation: true
  no_zero_fill: true
  no_missing_finance_inference: true
  no_pdf_ocr: true
  no_official_bctc_scrape: true
  no_core_output_mutation: true
  no_stage_promotion_to_investment_ready: true
inputs:
  step25_search_dirs:
    - {step25_dir.as_posix()}
exports:
  output_dir: {output.as_posix()}
core_output_watchlist:
  - {rows.as_posix()}
  - {watchlist.as_posix()}
  - {manual.as_posix()}
  - {blocked.as_posix()}
""".strip(),
        encoding="utf-8",
    )


def _config(paths: dict) -> dict:
    search_dir = paths.get("search_dir", Path("data/reports/step25_full_universe_1743_primary_only_scale"))
    return {
        "step_id": "STEP26-FULL-UNIVERSE-OUTPUT-AUDIT-FIRST-SHORTLIST",
        "mode": "output_audit_first_shortlist",
        "limits": {"first_shortlist_size": 50, "bctc_priority_queue_size": 100},
        "inputs": {"step25_search_dirs": [str(search_dir)]},
        "safety": {
            "no_recommendation": True,
            "no_buy_sell_hold": True,
            "no_target_price": True,
            "no_fair_value": True,
            "no_intrinsic_value": True,
            "no_margin_of_safety": True,
            "no_expected_return": True,
            "no_entry_exit_price": True,
            "no_portfolio_recommendation": True,
            "no_zero_fill": True,
            "no_missing_finance_inference": True,
            "no_pdf_ocr": True,
            "no_official_bctc_scrape": True,
            "no_core_output_mutation": True,
            "no_stage_promotion_to_investment_ready": True,
        },
    }


def _row(
    ticker: str,
    *,
    status: str = "WATCHLIST_CANDIDATE",
    manual_bctc_required: bool = True,
    last_close: str | int = 10,
    last_price_date: str = "2026-06-11",
    trading_value: str | int = 1000000,
) -> dict:
    blocked = status.startswith("BLOCKED_")
    return {
        "ticker": ticker,
        "company_name": f"{ticker} Corp",
        "screening_status": status,
        "manual_review_required": True,
        "manual_bctc_required": manual_bctc_required,
        "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
        "finance_source_confidence": "PROVISIONAL_LOW",
        "crosscheck_status": "NOT_AVAILABLE",
        "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
        "missing_fields": '["last_close"]' if blocked else "[]",
        "block_reasons": '["missing_market_data"]' if blocked else "[]",
        "reason_to_review": "BCTC_REVIEW_REQUIRED",
        "last_price_date": last_price_date,
        "last_close": last_close,
        "avg_volume_20d": "" if blocked else 1000,
        "avg_volume_60d": "" if blocked else 1200,
        "last_volume": "" if blocked else 900,
        "recent_trading_value": trading_value,
        "stale_days": 0 if not blocked else "",
        "market_fetch_status": "" if blocked else "FETCH_OK",
        "finance_quality_status": "PROVISIONAL_LOW",
        "finance_source_layer": "provisional_structured",
        "source_conflicts": "[]",
    }
