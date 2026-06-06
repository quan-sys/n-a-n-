from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.ingestion.official_finance_document_seed import SEED_COLUMNS
from src.ingestion.official_finance_seed_repair import (
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
