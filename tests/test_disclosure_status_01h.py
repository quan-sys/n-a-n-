from pathlib import Path

import pandas as pd

from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS
from src.ingestion.disclosure_event_classifier import (
    classify_disclosure_status,
    source_failure_event,
)
from src.ingestion.disclosure_status_list_ingestion import (
    build_custom_01h_decision,
    disclosure_status_by_ticker_to_raw,
    run_disclosure_status_01h,
)
from src.ingestion.source_snapshot import SnapshotFetchResult


def test_classifier_maps_status_list_types_and_failures():
    assert classify_disclosure_status(
        list_type="TRADING_SUSPENSION_LIST",
        raw_text="tam ngung giao dich",
    ) == ("TRADING_SUSPENSION", "critical")
    assert classify_disclosure_status(
        list_type="SSC_SANCTION_LIST",
        raw_text="quyet dinh xu phat vi pham hanh chinh",
    ) == ("SSC_SANCTION", "high")
    assert source_failure_event("SOURCE_SCHEMA_UNKNOWN") == (
        "DISCLOSURE_SCHEMA_UNKNOWN",
        "unknown",
        "SOURCE_SCHEMA_UNKNOWN",
    )


def test_01h_parses_mock_hose_warning_list_and_no_warning_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.ingestion.disclosure_status_list_ingestion.fetch_public_snapshot",
        _fake_hose_fetch,
    )

    result = run_disclosure_status_01h(
        representative_tickers=["AAA", "BBB"],
        sources=["hose"],
        output_dir=tmp_path / "reports",
        raw_snapshot_dir=tmp_path / "snapshots",
        source_config=_mock_source_config(),
        request_sleep_seconds=0,
        year=2026,
    )

    raw_index = result["disclosure_status_lists_raw_index"]
    positive = result["disclosure_positive_control_tickers"]
    status = result["disclosure_status_by_ticker"]

    assert set(raw_index["ticker"]) == {"ZZZ"}
    assert positive["ticker"].tolist() == ["ZZZ"]
    assert (
        status[status["evidence_status"] == "POSITIVE_CONTROL_CONFIRMED"]["ticker"].tolist()
        == ["ZZZ"]
    )
    no_warning = status[status["evidence_status"] == "SOURCE_CHECKED_NOT_FOUND"]
    assert set(no_warning["ticker"]) == {"AAA", "BBB"}
    assert no_warning["notes"].str.contains("not a guarantee of clean disclosure").all()


def test_source_unavailable_creates_unavailable_not_clean_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.ingestion.disclosure_status_list_ingestion.fetch_public_snapshot",
        _fake_unavailable_fetch,
    )

    result = run_disclosure_status_01h(
        representative_tickers=["AAA"],
        sources=["ssc"],
        output_dir=tmp_path / "reports",
        raw_snapshot_dir=tmp_path / "snapshots",
        source_config=_mock_source_config(),
        request_sleep_seconds=0,
        year=2026,
        allow_partial=True,
    )

    status = result["disclosure_status_by_ticker"]
    assert len(status) == 1
    row = status.iloc[0]
    assert row["ticker"] == "AAA"
    assert row["event_type"] == "DISCLOSURE_SOURCE_UNAVAILABLE"
    assert row["evidence_status"] == "SOURCE_UNAVAILABLE"
    assert bool(row["source_checked"]) is False


def test_schema_unknown_creates_schema_unknown_not_clean_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.ingestion.disclosure_status_list_ingestion.fetch_public_snapshot",
        _fake_schema_unknown_fetch,
    )

    result = run_disclosure_status_01h(
        representative_tickers=["AAA"],
        sources=["ssc"],
        output_dir=tmp_path / "reports",
        raw_snapshot_dir=tmp_path / "snapshots",
        source_config=_mock_source_config(),
        request_sleep_seconds=0,
        year=2026,
        allow_partial=True,
    )

    status = result["disclosure_status_by_ticker"]
    row = status.iloc[0]
    assert row["event_type"] == "DISCLOSURE_SCHEMA_UNKNOWN"
    assert row["evidence_status"] == "SOURCE_SCHEMA_UNKNOWN"


def test_raw_candidate_rows_have_no_prohibited_recommendation_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "src.ingestion.disclosure_status_list_ingestion.fetch_public_snapshot",
        _fake_hose_fetch,
    )
    result = run_disclosure_status_01h(
        representative_tickers=["AAA"],
        sources=["hose"],
        output_dir=tmp_path / "reports",
        raw_snapshot_dir=tmp_path / "snapshots",
        source_config=_mock_source_config(),
        request_sleep_seconds=0,
        year=2026,
    )
    raw = disclosure_status_by_ticker_to_raw(result["disclosure_status_by_ticker"])
    normalized = {column.lower() for column in raw.columns}

    assert PROHIBITED_RECOMMENDATION_FIELDS.isdisjoint(normalized)


def test_custom_decision_keeps_step19_unimplemented_and_blocks_scale():
    status = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "evidence_status": "SOURCE_CHECKED_NOT_FOUND",
            }
        ]
    )
    positive = pd.DataFrame([{"ticker": "ZZZ"}])
    unresolved = pd.DataFrame(columns=["dataset_name"])
    decision = build_custom_01h_decision(
        representative_tickers=["AAA"],
        status_by_ticker=status,
        positive_control=positive,
        positive_control_status_value="POSITIVE_CONTROL_CONFIRMED",
        evidence_decisions={"disclosure_ready_for_l0": True},
        unresolved_required_fields=unresolved,
    )

    assert decision["disclosure_ready_for_l0"] == "Partial"
    assert decision["finance_disclosure_ready_for_step18"] == "False"
    assert decision["should_run_REAL_DATA_02"] == "No"
    assert decision["should_implement_Step19_now"] == "No"
    assert decision["step19_implemented"] is False


def _mock_source_config():
    return {
        "request_defaults": {"headers": {}, "timeout_seconds": 1},
        "sources": {
            "hose": {
                "source_category": "hose",
                "source_name": "hose",
                "official": True,
                "parser": "hose_json",
                "status_list_endpoint": "https://example.test/status-list",
                "stock_status_endpoint": (
                    "https://example.test/stock-status?pageIndex={page_index}"
                    "&pageSize={page_size}&statusListId={status_list_id}"
                ),
                "securities_violating_endpoints": [],
            },
            "ssc": {
                "source_category": "ssc",
                "source_name": "ssc",
                "official": True,
                "parser": "discovery_only",
                "probe_urls": [
                    {
                        "list_type": "SSC_SANCTION_LIST",
                        "url": "https://example.test/ssc",
                    }
                ],
            },
        },
    }


def _fake_hose_fetch(**kwargs):
    url = kwargs["url"]
    if "status-list" in url:
        text = (
            '{"data":[{"id":33,"name":"CK thuoc dien bi canh bao"}],'
            '"success":true,"message":null}'
        )
    else:
        text = (
            '{"data":{"list":[{"securitiesCode":"ZZZ","name":"Mock Company",'
            '"datePublish":1780358400,"reason":"<p>vi pham cong bo thong tin</p>"}],'
            '"paging":{"pageIndex":1,"pageSize":500,"totalCount":1,"totalPages":1}},'
            '"success":true,"message":null}'
        )
    return SnapshotFetchResult(
        url=url,
        status_code=200,
        content_type="application/json",
        body=text.encode("utf-8"),
        text=text,
        error="",
        fetched_at="2026-06-05T00:00:00+00:00",
        content_hash="mockhash",
        snapshot_path=str(Path("mock_snapshot.json")),
    )


def _fake_unavailable_fetch(**kwargs):
    return SnapshotFetchResult(
        url=kwargs["url"],
        status_code=None,
        content_type="",
        body=b"",
        text="",
        error="RequestException:network unavailable",
        fetched_at="2026-06-05T00:00:00+00:00",
        content_hash="",
        snapshot_path="",
    )


def _fake_schema_unknown_fetch(**kwargs):
    text = "<html><body>plain page without status-list schema</body></html>"
    return SnapshotFetchResult(
        url=kwargs["url"],
        status_code=200,
        content_type="text/html",
        body=text.encode("utf-8"),
        text=text,
        error="",
        fetched_at="2026-06-05T00:00:00+00:00",
        content_hash="mockhash",
        snapshot_path=str(Path("mock_snapshot.html")),
    )
