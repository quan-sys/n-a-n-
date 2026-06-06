from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingestion.official_finance_document_seed import SEED_COLUMNS
from src.ingestion.official_finance_seed_repair import (
    build_01id_decision_report_markdown,
    build_document_discovery_status_by_ticker,
    build_refined_seed_candidates,
    build_manual_review_queue,
)
from src.ingestion.official_finance_link_extractor import LINK_CANDIDATE_COLUMNS


def test_01id_ticker_with_no_candidates_goes_to_manual_review():
    seed = _seed_df()
    index = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "download_status": "SOURCE_UNAVAILABLE",
            }
        ]
    )
    candidates = pd.DataFrame(columns=LINK_CANDIDATE_COLUMNS)
    status = build_document_discovery_status_by_ticker(seed_df=seed, index_df=index, candidates=candidates)
    manual = build_manual_review_queue(
        seed_df=seed,
        candidates=candidates,
        bad_seed=pd.DataFrame(columns=["ticker", "seed_url", "bad_seed_reason", "notes"]),
        status_by_ticker=status,
    )

    assert status.iloc[0]["discovery_status"] == "BLOCKED_OR_FAILED"
    assert not manual.empty
    assert bool(manual.iloc[0]["manual_review_required"]) is True


def test_01id_refined_seed_candidate_output_preserves_schema():
    seed = _seed_df()
    candidates = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "candidate_url": "https://official.example/reports/bctc-2025.pdf",
                "candidate_is_https": True,
                "official_domain": "official.example",
                "file_extension": "pdf",
                "candidate_document_type": "financial_statement",
                "period_guess": "2025",
                "score": 90,
                "score_band": "HIGH_CONFIDENCE_CANDIDATE",
                "reason": "OFFICIAL_DOMAIN_MATCH;HTTPS_LINK;FINANCE_KEYWORD",
            }
        ]
    )

    refined = build_refined_seed_candidates(seed_df=seed, candidates=candidates)

    assert refined.columns.tolist() == SEED_COLUMNS
    assert len(refined) == 1
    assert refined.iloc[0]["source_url"] == "https://official.example/reports/bctc-2025.pdf"
    assert "01ID_CANDIDATE_NOT_FINANCE_EVIDENCE_YET" in refined.iloc[0]["notes"]


def test_01id_patch1_refined_seed_contains_only_high_or_reviewable_candidates():
    seed = _seed_df()
    candidates = pd.DataFrame(
        [
            _candidate_row(
                ticker="AAA",
                candidate_url="https://official.example/reports/bctc-hop-nhat-quy-1-nam-2026.pdf",
                score=90,
                score_band="HIGH_CONFIDENCE_CANDIDATE",
                reason="OFFICIAL_DOMAIN_MATCH;HTTPS_LINK;BCTC_KEYWORD_MATCH;CONSOLIDATED_KEYWORD_MATCH",
            ),
            _candidate_row(
                ticker="AAA",
                candidate_url="https://official.example/reports/bctc-rieng-quy-3-nam-2025.pdf",
                score=70,
                score_band="REVIEWABLE_CANDIDATE",
                reason="OFFICIAL_DOMAIN_MATCH;HTTPS_LINK;BCTC_KEYWORD_MATCH;STANDALONE_REVIEW_REQUIRED",
            ),
            _candidate_row(
                ticker="AAA",
                candidate_url="https://official.example/investor",
                score=40,
                score_band="LOW_CONFIDENCE_CANDIDATE",
                file_extension="html",
                reason="OFFICIAL_DOMAIN_MATCH;HTTPS_LINK;NO_FINANCE_KEYWORDS",
            ),
            _candidate_row(
                ticker="AAA",
                candidate_url="https://official.example/reports/bctc-2015.pdf",
                score=0,
                score_band="REJECTED_CANDIDATE",
                reason="OLD_YEAR_PENALTY",
            ),
        ]
    )

    refined = build_refined_seed_candidates(seed_df=seed, candidates=candidates, patch_label="01id_patch1")

    assert len(refined) == 2
    assert refined["source_url"].str.contains("investor|2015", regex=True).sum() == 0
    assert "01ID_PATCH1_CANDIDATE_NOT_FINANCE_EVIDENCE_YET" in refined.iloc[0]["notes"]


def test_01id_patch1_refined_seed_infers_consolidated_and_standalone_status():
    seed = _seed_df()
    candidates = pd.DataFrame(
        [
            _candidate_row(
                ticker="AAA",
                candidate_url="https://official.example/reports/bctc-hop-nhat-quy-1-nam-2026.pdf",
                score=90,
                score_band="HIGH_CONFIDENCE_CANDIDATE",
                reason="CONSOLIDATED_KEYWORD_MATCH",
                period_guess="2026-Q1",
            ),
            _candidate_row(
                ticker="AAA",
                candidate_url="https://official.example/reports/bao-cao-tai-chinh-rieng-quy-3-nam-2025.pdf",
                score=70,
                score_band="REVIEWABLE_CANDIDATE",
                reason="STANDALONE_REVIEW_REQUIRED",
                period_guess="2025-Q3",
            ),
        ]
    )

    refined = build_refined_seed_candidates(seed_df=seed, candidates=candidates, patch_label="01id_patch1")

    status_by_url = dict(zip(refined["source_url"], refined["consolidated_status"]))
    assert status_by_url["https://official.example/reports/bctc-hop-nhat-quy-1-nam-2026.pdf"] == "consolidated"
    assert status_by_url["https://official.example/reports/bao-cao-tai-chinh-rieng-quy-3-nam-2025.pdf"] == "standalone"
    standalone_notes = refined[refined["consolidated_status"] == "standalone"].iloc[0]["notes"]
    assert "manual review" in standalone_notes


def test_01id_patch1_decision_report_keeps_finance_parse_ready_false():
    candidates = pd.DataFrame(
        [
            _candidate_row(
                ticker="AAA",
                candidate_url="https://official.example/reports/bctc-hop-nhat-quy-1-nam-2026.pdf",
                score=90,
                score_band="HIGH_CONFIDENCE_CANDIDATE",
                reason="DIRECT_PDF_FINANCE_KEYWORD",
            )
        ]
    )

    report = build_01id_decision_report_markdown(candidates=candidates)

    assert "- finance_parse_ready: False" in report
    assert "- should_implement_Step19_now: No" in report


def test_01id_patch1_refined_seed_does_not_parse_finance_values():
    seed = _seed_df()
    candidates = pd.DataFrame(
        [
            _candidate_row(
                ticker="AAA",
                candidate_url="https://official.example/reports/bctc-hop-nhat-quy-1-nam-2026.pdf",
                score=90,
                score_band="HIGH_CONFIDENCE_CANDIDATE",
                reason="DIRECT_PDF_FINANCE_KEYWORD",
            )
        ]
    )

    refined = build_refined_seed_candidates(seed_df=seed, candidates=candidates, patch_label="01id_patch1")

    assert refined.columns.tolist() == SEED_COLUMNS
    prohibited_columns = {"revenue", "net_profit", "assets", "equity", "cash_flow", "eps"}
    assert prohibited_columns.isdisjoint(set(refined.columns))


def _seed_df():
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "exchange": "HOSE",
                "company_name": "Example A",
                "period": "DISCOVERY",
                "document_type": "ir_page",
                "source_type": "company_ir",
                "source_name": "Example IR",
                "source_url": "https://official.example/investor",
                "official_domain": "official.example",
                "expected_file_type": "html",
                "consolidated_status": "unknown",
                "language": "vi",
                "confidence_seed": "medium",
                "notes": "mock only",
            }
        ],
        columns=SEED_COLUMNS,
    )


def _candidate_row(
    *,
    ticker: str,
    candidate_url: str,
    score: int,
    score_band: str,
    reason: str,
    file_extension: str = "pdf",
    period_guess: str = "2026-Q1",
) -> dict[str, object]:
    return {
        "ticker": ticker,
        "source_page_url": "https://official.example/investor",
        "source_snapshot_path": "snapshot.html",
        "official_domain": "official.example",
        "candidate_url": candidate_url,
        "candidate_scheme": "https",
        "candidate_domain": "official.example",
        "candidate_is_https": True,
        "anchor_text": "",
        "file_extension": file_extension,
        "candidate_document_type": "financial_statement",
        "period_guess": period_guess,
        "score": score,
        "score_band": score_band,
        "manual_review_required": score_band != "HIGH_CONFIDENCE_CANDIDATE",
        "reason": reason,
        "notes": "candidate only",
    }
