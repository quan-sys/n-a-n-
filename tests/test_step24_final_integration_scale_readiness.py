from pathlib import Path

import pandas as pd
import pytest

from src.integration.step24_final_integration_scale_readiness import (
    FINAL_DECISIONS,
    Step24SafeRunBlocked,
    run_step24_final_integration_scale_readiness,
    scan_forbidden_terms,
)


REQUIRED_EXPORTS = {
    "final_integration_summary.json",
    "scale_readiness_report.md",
    "artifact_checklist.csv",
    "schema_contract_check.csv",
    "source_confidence_check.csv",
    "forbidden_terms_check.csv",
    "manual_review_contract_check.csv",
    "run_manifest.json",
}


def test_required_output_files_exist(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    _run(paths)

    assert REQUIRED_EXPORTS.issubset({path.name for path in paths["output"].iterdir()})


def test_missing_artifacts_are_detected(tmp_path: Path):
    paths = _write_fixture(tmp_path, omit_step23=True)

    result = _run(paths)

    assert result.summary["missing_artifact_count"] == 1
    assert result.summary["integration_status"] == "BLOCKED_MISSING_ARTIFACTS"


def test_forbidden_terms_detection_works(tmp_path: Path):
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    (scan_dir / "bad.txt").write_text("buy now", encoding="utf-8")

    assert scan_forbidden_terms(scan_dir)


def test_source_confidence_must_stay_provisional(tmp_path: Path):
    paths = _write_fixture(tmp_path, market_confidence="HIGH_CONFIDENCE")

    result = _run(paths)

    assert result.summary["source_confidence_check_passed"] is False
    assert result.summary["integration_status"] == "BLOCKED_CONFIDENCE_LABEL_VIOLATION"


def test_crosscheck_must_stay_not_available(tmp_path: Path):
    paths = _write_fixture(tmp_path, crosscheck_status="PASSED")

    result = _run(paths)

    assert result.summary["source_confidence_check_passed"] is False
    assert "CONFIDENCE_LABEL_VIOLATION" in set(result.source_confidence_check["status"])


def test_manual_review_contract_must_exist(tmp_path: Path):
    paths = _write_fixture(tmp_path, omit_manual_queue=True)

    result = _run(paths)

    assert result.summary["manual_review_contract_passed"] is False
    assert "MISSING_REQUIRED_ARTIFACT" in set(result.manual_review_contract_check["status"])


def test_scale_readiness_does_not_imply_ticker_promotion(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)
    report = (paths["output"] / "scale_readiness_report.md").read_text(encoding="utf-8")

    assert "investment-ready" not in report.lower()
    assert result.summary["full_universe_readiness"] in {
        "READY_FOR_FULL_UNIVERSE_PRIMARY_ONLY_RUN",
        "READY_FOR_FULL_UNIVERSE_WITH_WARNINGS",
        "NOT_READY_FOR_FULL_UNIVERSE",
    }


def test_previous_outputs_are_not_mutated(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    previous = paths["step22_summary"]
    before = previous.read_text(encoding="utf-8")

    result = _run(paths, core_output_paths=[previous])

    assert previous.read_text(encoding="utf-8") == before
    assert result.run_manifest["previous_step_outputs_mutated"] is False


def test_full_universe_is_not_run_by_step24(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    with pytest.raises(Step24SafeRunBlocked):
        _run(paths, request_full_universe=True)


def test_final_decision_is_allowed(tmp_path: Path):
    paths = _write_fixture(tmp_path)

    result = _run(paths)

    assert result.summary["final_decision"] in FINAL_DECISIONS


def _run(paths: dict[str, Path], **kwargs):
    return run_step24_final_integration_scale_readiness(
        config_path=paths["config"],
        output_dir=paths["output"],
        allow_partial=True,
        command_used="pytest step24",
        **kwargs,
    )


def _write_fixture(
    tmp_path: Path,
    *,
    omit_step23: bool = False,
    omit_manual_queue: bool = False,
    market_confidence: str = "PROVISIONAL_PRIMARY_ONLY",
    crosscheck_status: str = "NOT_AVAILABLE",
) -> dict[str, Path]:
    output = tmp_path / "out"
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    step05a_summary = tmp_path / "step05a_summary.json"
    step19_decision = tmp_path / "step19_decision.json"
    step20_summary = tmp_path / "step20_summary.json"
    step21_summary = tmp_path / "step21_summary.json"
    step22_summary = tmp_path / "step22_summary.json"
    step23_summary = tmp_path / "step23_summary.json"
    manual_queue = tmp_path / "manual_queue.csv"
    step20_rows = tmp_path / "step20_rows.csv"
    step21_rows = tmp_path / "step21_rows.csv"
    step22_watchlist = tmp_path / "step22_watchlist.csv"
    step23_dashboard = tmp_path / "step23_dashboard.csv"
    config = tmp_path / "config.yaml"

    for path, decision in [
        (step05a_summary, "CONDITIONAL_GO_FOR_MANUAL_BCTC_REVIEW"),
        (step19_decision, "PASS_SHADOW_DIAGNOSTIC_PLUMBING"),
        (step20_summary, "PASS_WITH_MANUAL_REVIEW_WARNINGS"),
        (step21_summary, "PASS_TIMING_LIQUIDITY_CONTEXT_WITH_WARNINGS"),
        (step22_summary, "PASS_WEEKLY_REPORT_WITH_WARNINGS"),
    ]:
        _write_summary(path, decision, market_confidence=market_confidence, crosscheck_status=crosscheck_status)
    if not omit_step23:
        _write_summary(step23_summary, "PASS_MONITORING_WITH_WARNINGS", market_confidence=market_confidence, crosscheck_status=crosscheck_status)
    if not omit_manual_queue:
        pd.DataFrame(
            [
                {
                    "ticker": "T001",
                    "missing_fields": "[]",
                    "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY",
                    "finance_source_confidence": "PROVISIONAL_LOW",
                    "crosscheck_status": "NOT_AVAILABLE",
                    "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
                }
            ]
        ).to_csv(manual_queue, index=False)
    pd.DataFrame([{"ticker": "T001", "valuation_context": "INSUFFICIENT_DATA", "valuation_confidence": "LOW", "manual_review_required": True, "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY", "finance_source_confidence": "PROVISIONAL_LOW", "crosscheck_status": "NOT_AVAILABLE", "verification_status": "NEEDS_MANUAL_BCTC_REVIEW"}]).to_csv(step20_rows, index=False)
    pd.DataFrame([{"ticker": "T001", "timing_risk_bucket": "TIMING_RISK_MODERATE", "liquidity_risk_bucket": "LIQUIDITY_RISK_LOW", "manual_review_required": True, "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY", "finance_source_confidence": "PROVISIONAL_LOW", "crosscheck_status": "NOT_AVAILABLE", "verification_status": "NEEDS_MANUAL_BCTC_REVIEW"}]).to_csv(step21_rows, index=False)
    pd.DataFrame([{"ticker": "T001", "watchlist_status": "WATCH_ONLY", "confidence_score": 45, "manual_review_required": True, "market_source_confidence": "PROVISIONAL_PRIMARY_ONLY", "finance_source_confidence": "PROVISIONAL_LOW", "crosscheck_status": "NOT_AVAILABLE", "verification_status": "NEEDS_MANUAL_BCTC_REVIEW"}]).to_csv(step22_watchlist, index=False)
    pd.DataFrame([{"metric_name": "processed_ticker_count", "current_value": 1, "previous_value": "INSUFFICIENT_HISTORY", "trend_direction": "insufficient_history", "interpretation": "insufficient_history", "confidence": "LOW", "manual_review_required": True}]).to_csv(step23_dashboard, index=False)
    _write_config(
        config,
        step05a_summary=step05a_summary,
        step19_decision=step19_decision,
        step20_summary=step20_summary,
        step21_summary=step21_summary,
        step22_summary=step22_summary,
        step23_summary=step23_summary,
        manual_queue=manual_queue,
        step20_rows=step20_rows,
        step21_rows=step21_rows,
        step22_watchlist=step22_watchlist,
        step23_dashboard=step23_dashboard,
        scan_dir=scan_dir,
        output=output,
    )
    return {"config": config, "output": output, "step22_summary": step22_summary}


def _write_summary(path: Path, decision: str, *, market_confidence: str, crosscheck_status: str) -> None:
    path.write_text(
        json_dump(
            {
                "final_decision": decision,
                "market_source_confidence": market_confidence,
                "finance_source_confidence_default": "PROVISIONAL_LOW",
                "crosscheck_status": crosscheck_status,
                "verification_status": "NEEDS_MANUAL_BCTC_REVIEW",
            }
        ),
        encoding="utf-8",
    )


def _write_config(
    path: Path,
    *,
    step05a_summary: Path,
    step19_decision: Path,
    step20_summary: Path,
    step21_summary: Path,
    step22_summary: Path,
    step23_summary: Path,
    manual_queue: Path,
    step20_rows: Path,
    step21_rows: Path,
    step22_watchlist: Path,
    step23_dashboard: Path,
    scan_dir: Path,
    output: Path,
) -> None:
    def q(value: Path) -> str:
        return '"' + value.as_posix() + '"'

    path.write_text(
        "\n".join(
            [
                "step_id: STEP24-FINAL-INTEGRATION-CONTRACT-SCALE-READINESS",
                "mode: final_integration_scale_readiness_only",
                "run:",
                "  sandbox_only: true",
                "  allow_partial: true",
                "limits:",
                "  full_universe_allowed: false",
                "  scale_1743_allowed: false",
                "source_confidence:",
                "  market_source_confidence: PROVISIONAL_PRIMARY_ONLY",
                "  finance_source_confidence_default: PROVISIONAL_LOW",
                "  crosscheck_status: NOT_AVAILABLE",
                "  verification_status: NEEDS_MANUAL_BCTC_REVIEW",
                "safety:",
                "  no_recommendation: true",
                "  no_buy_sell_hold: true",
                "  no_target_price: true",
                "  no_fair_value: true",
                "  no_intrinsic_value: true",
                "  no_margin_of_safety: true",
                "  no_expected_return: true",
                "  no_entry_exit_price: true",
                "  no_portfolio_recommendation: true",
                "  no_strategy_claim: true",
                "  no_pdf_ocr: true",
                "  no_official_bctc_scrape: true",
                "  no_zero_fill: true",
                "  no_core_output_mutation: true",
                "  no_stage_promotion_to_investment_ready: true",
                "required_artifacts:",
                f"  step05a_summary: {q(step05a_summary)}",
                f"  step05a_manual_queue: {q(manual_queue)}",
                f"  step19_decision: {q(step19_decision)}",
                f"  step20_summary: {q(step20_summary)}",
                f"  step21_summary: {q(step21_summary)}",
                f"  step22_summary: {q(step22_summary)}",
                f"  step23_summary: {q(step23_summary)}",
                "schema_contracts:",
                "  step20_rows:",
                f"    path: {q(step20_rows)}",
                "    required_columns: [ticker, valuation_context, valuation_confidence, manual_review_required, market_source_confidence, finance_source_confidence, crosscheck_status, verification_status]",
                "  step21_rows:",
                f"    path: {q(step21_rows)}",
                "    required_columns: [ticker, timing_risk_bucket, liquidity_risk_bucket, manual_review_required, market_source_confidence, finance_source_confidence, crosscheck_status, verification_status]",
                "  step22_watchlist:",
                f"    path: {q(step22_watchlist)}",
                "    required_columns: [ticker, watchlist_status, confidence_score, manual_review_required, market_source_confidence, finance_source_confidence, crosscheck_status, verification_status]",
                "  step23_dashboard:",
                f"    path: {q(step23_dashboard)}",
                "    required_columns: [metric_name, current_value, previous_value, trend_direction, interpretation, confidence, manual_review_required]",
                "forbidden_scan_dirs:",
                f"  - {q(scan_dir)}",
                "exports:",
                f"  output_dir: {q(output)}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def json_dump(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, indent=2)
