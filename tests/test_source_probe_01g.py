import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from src.ingestion.source_probe import HttpProbeResponse, probe_public_url


ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = ROOT_DIR / "scripts" / "run_multi_source_probe_01g.py"


def test_probe_public_url_reports_available_schema():
    def fake_get(url, **kwargs):
        return HttpProbeResponse(
            url=url,
            status_code=200,
            body="<html><body><table><tr><td>financial</td></tr></table></body></html>",
        )

    row = probe_public_url(
        source_name="cafef",
        source_category="cafef",
        dataset_name="financial_statement_summary",
        sample_url="https://example.test",
        http_get=fake_get,
    )

    assert row["probe_status"] == "SOURCE_AVAILABLE"
    assert row["is_accessible"] is True
    assert row["schema_detected"] is True


def test_probe_public_url_reports_blocked_or_js_required():
    def fake_get(url, **kwargs):
        return HttpProbeResponse(
            url=url,
            status_code=403,
            body="<html>captcha access denied</html>",
            error="HTTPError:403",
        )

    row = probe_public_url(
        source_name="hose",
        source_category="hose",
        dataset_name="disclosure_status",
        sample_url="https://example.test",
        http_get=fake_get,
    )

    assert row["probe_status"] == "SOURCE_BLOCKED_OR_JS_REQUIRED"
    assert row["blocked_or_captcha"] is True


def test_probe_public_url_reports_empty_response():
    def fake_get(url, **kwargs):
        return HttpProbeResponse(url=url, status_code=200, body="")

    row = probe_public_url(
        source_name="vietstock",
        source_category="vietstock",
        dataset_name="financial_statement_summary",
        sample_url="https://example.test",
        http_get=fake_get,
    )

    assert row["probe_status"] == "SOURCE_EMPTY_RESPONSE"


def test_01g_cli_writes_reports_without_selected_adapters(tmp_path):
    raw_dir = tmp_path / "raw"
    output_dir = tmp_path / "reports"
    raw_dir.mkdir()
    pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "exchange": "HOSE",
                "company_name": "AAA",
                "listing_status": "LISTED",
                "source": "manual_csv",
                "source_category": "manual_csv",
                "source_url": "manual://universe/AAA",
                "fetch_time": "2026-06-05T00:00:00Z",
                "confidence_raw": "medium",
            }
        ]
    ).to_csv(raw_dir / "universe_raw.csv", index=False)

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--tickers",
            "AAA",
            "--sources",
            "unknown",
            "--raw-output-dir",
            str(raw_dir),
            "--output-dir",
            str(output_dir),
            "--allow-partial",
        ],
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        timeout=120,
    )

    assert completed.returncode == 0, completed.stderr
    assert (output_dir / "source_probe_summary.md").exists()
    assert (output_dir / "source_probe_matrix.csv").exists()
    assert (output_dir / "multi_source_run_summary.md").exists()
    assert "step19_implemented" in completed.stdout
