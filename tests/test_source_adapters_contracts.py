from pathlib import Path

import pandas as pd

from src.ingestion.contracts import PROHIBITED_RECOMMENDATION_FIELDS
from src.ingestion.source_adapter_contracts import (
    classify_disclosure_event,
    detect_finance_field,
    validate_candidate_frame,
)
from src.ingestion.source_adapter_diagnostics import (
    build_finance_field_coverage_by_source,
    finance_candidates_to_wide,
    instantiate_adapters,
    load_source_adapter_registry,
    validate_source_adapter_registry,
)
from src.ingestion.source_adapters.cafef_adapter import CafeFAdapter
from src.ingestion.source_probe import HttpProbeResponse, load_source_probe_targets


def test_source_adapter_registry_is_valid():
    registry = load_source_adapter_registry()
    result = validate_source_adapter_registry(registry)

    assert result["is_valid"] is True
    names = {adapter["adapter_name"] for adapter in registry["adapters"]}
    assert {"vnstock", "cafef", "vietstock", "hose", "hnx", "ssc"}.issubset(names)


def test_adapter_instantiation_uses_registry_and_targets():
    registry = load_source_adapter_registry()
    targets = load_source_probe_targets()
    adapters = instantiate_adapters(
        adapter_registry=registry,
        probe_targets=targets,
        source_names=["cafef", "hose"],
        http_get=lambda url, **kwargs: HttpProbeResponse(url=url, status_code=200, body="<table></table>"),
        request_sleep_seconds=0,
    )

    assert [adapter.source_name for adapter in adapters] == ["cafef", "hose"]


def test_finance_label_detection_supports_vietnamese_and_english():
    assert detect_finance_field("Doanh thu thuan") == "revenue"
    assert detect_finance_field("Loi nhuan sau thue") == "net_profit"
    assert detect_finance_field("Tong tai san") == "total_assets"
    assert detect_finance_field("random label") == ""


def test_disclosure_classifier_is_deterministic():
    assert classify_disclosure_event("co phieu bi dua vao dien canh bao") == (
        "WARNING_LIST",
        "medium",
    )
    assert classify_disclosure_event("tam ngung giao dich") == (
        "TRADING_SUSPENSION",
        "critical",
    )
    assert classify_disclosure_event("") == ("DISCLOSURE_DATA_UNAVAILABLE", "unknown")


def test_web_finance_adapter_parses_only_known_labels_without_filling_missing():
    html = """
    <html><body><table>
    <tr><th>Chi tieu</th><th>2026-Q1</th></tr>
    <tr><td>Doanh thu thuan</td><td>100</td></tr>
    <tr><td>Tong tai san</td><td>1000</td></tr>
    <tr><td>Unknown metric</td><td>999</td></tr>
    </table></body></html>
    """

    def fake_get(url, **kwargs):
        return HttpProbeResponse(url=url, status_code=200, body=html)

    adapter = CafeFAdapter(
        config={
            "finance_url_patterns": ["https://example.test/{ticker}/finance"],
            "probe_urls": {"financial_statement_summary": "https://example.test/"},
        },
        http_get=fake_get,
        request_sleep_seconds=0,
    )
    candidates, diagnostics, schema = adapter.fetch_finance(["AAA"])
    wide = finance_candidates_to_wide(candidates)

    assert set(candidates["field_name"]) == {"revenue", "total_assets"}
    assert pd.isna(wide.iloc[0]["net_profit"])
    assert set(diagnostics["status"]) == {"ROWS_PARSED"}
    assert "net_profit" in schema.iloc[0]["unsupported_fields"]
    assert validate_candidate_frame(candidates, "financial_statement_summary")["is_valid"] is True


def test_finance_coverage_reports_have_no_prohibited_columns():
    candidates = pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "period": "2026-Q1",
                "period_type": "quarter",
                "field_name": "revenue",
                "value": 100,
                "unit": "",
                "currency": "VND",
                "source_category": "cafef",
                "source_name": "cafef",
                "source_url": "https://example.test",
                "fetch_time": "2026-06-05T00:00:00Z",
                "confidence_raw": "medium",
                "raw_label": "Doanh thu",
                "raw_value": "100",
                "notes": "test fixture",
            }
        ]
    )
    coverage = build_finance_field_coverage_by_source(candidates)
    normalized = {column.strip().lower() for column in coverage.columns}

    assert PROHIBITED_RECOMMENDATION_FIELDS.isdisjoint(normalized)
