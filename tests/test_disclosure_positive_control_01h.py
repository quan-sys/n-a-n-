import pandas as pd

from src.ingestion.disclosure_positive_control import (
    build_positive_control_tickers,
    positive_control_status,
)
from src.ingestion.disclosure_status_list_ingestion import build_disclosure_status_by_ticker


def test_positive_control_is_discovered_from_parsed_warning_rows():
    raw_index = pd.DataFrame(
        [
            {
                "ticker": "ZZZ",
                "source_category": "hose",
                "source_name": "hose:warning_list",
                "source_url": "https://example.test/status",
                "raw_list_type": "WARNING_LIST",
                "event_type": "WARNING_LIST",
                "severity": "medium",
                "evidence_status": "SOURCE_CONFIRMED_WARNING",
            },
            {
                "ticker": "YYY",
                "source_category": "hose",
                "source_name": "hose:control_list",
                "source_url": "https://example.test/control",
                "raw_list_type": "CONTROL_LIST",
                "event_type": "CONTROL_LIST",
                "severity": "high",
                "evidence_status": "SOURCE_CONFIRMED_WARNING",
            },
        ]
    )

    positive = build_positive_control_tickers(raw_index, max_tickers=2)

    assert positive["ticker"].tolist() == ["YYY", "ZZZ"]
    assert positive["evidence_status"].tolist() == [
        "POSITIVE_CONTROL_CONFIRMED",
        "POSITIVE_CONTROL_CONFIRMED",
    ]


def test_positive_control_unavailable_when_no_warning_rows():
    raw_index = pd.DataFrame(columns=["ticker", "event_type", "severity", "evidence_status"])
    positive = build_positive_control_tickers(raw_index)
    status = positive_control_status(
        positive_control_tickers=positive,
        matched_warning_rows=pd.DataFrame(),
    )

    assert positive.empty
    assert status == "POSITIVE_CONTROL_UNAVAILABLE"


def test_positive_control_adapter_failure_when_no_matched_warning_rows():
    positive = pd.DataFrame([{"ticker": "ZZZ"}])
    status = positive_control_status(
        positive_control_tickers=positive,
        matched_warning_rows=pd.DataFrame(),
    )

    assert status == "DISCLOSURE_ADAPTER_FAILED_POSITIVE_CONTROL"


def test_build_disclosure_status_by_ticker_distinguishes_positive_and_representative():
    raw_index = pd.DataFrame(
        [
            {
                "ticker": "ZZZ",
                "event_date": "2026-06-01",
                "source_category": "hose",
                "source_name": "hose:warning_list",
                "source_url": "https://example.test/status",
                "raw_list_type": "WARNING_LIST",
                "event_type": "WARNING_LIST",
                "severity": "medium",
                "confidence_raw": "high",
                "raw_title": "Mock warning",
                "raw_text": "Mock warning row",
                "fetch_time": "2026-06-05T00:00:00+00:00",
                "notes": "mock only",
            }
        ]
    )
    parsed_lists = pd.DataFrame(
        [
            {
                "source_category": "hose",
                "source_name": "hose:warning_list",
                "source_url": "https://example.test/status",
                "list_type": "WARNING_LIST",
                "event_type": "WARNING_LIST",
                "official": True,
                "parse_status": "ROWS_PARSED",
                "rows_parsed": 1,
                "fetch_time": "2026-06-05T00:00:00+00:00",
            }
        ]
    )
    probe = pd.DataFrame()

    status = build_disclosure_status_by_ticker(
        representative_tickers=["AAA"],
        positive_control_tickers=["ZZZ"],
        status_list_index=raw_index,
        probe_matrix=probe,
        parsed_lists=parsed_lists,
        as_of_date="2026-06-05",
    )

    assert set(status["ticker"]) == {"AAA", "ZZZ"}
    assert set(status["evidence_status"]) == {
        "SOURCE_CHECKED_NOT_FOUND",
        "POSITIVE_CONTROL_CONFIRMED",
    }
    assert bool(status[status["ticker"] == "AAA"].iloc[0]["source_checked"]) is True
