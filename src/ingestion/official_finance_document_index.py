"""Index/report helpers for REAL-DATA-01I-B official finance documents."""

from __future__ import annotations

from typing import Any

import pandas as pd


def build_01ib_run_summary_markdown(
    *,
    command: str,
    seed_rows_loaded: int,
    validation: pd.DataFrame,
    document_index: pd.DataFrame,
    manual_review_queue: pd.DataFrame,
    dry_run: bool,
    run_label: str = "01ib",
) -> str:
    valid_count = int(validation["is_valid"].sum()) if not validation.empty else 0
    invalid_count = int((~validation["is_valid"]).sum()) if not validation.empty else 0
    status_counts = _counts(document_index, "download_status")
    failed_statuses = [
        "SOURCE_URL_INVALID",
        "SOURCE_UNAVAILABLE",
        "SOURCE_CONTENT_TYPE_UNSUPPORTED",
        "DOWNLOAD_FAILED",
    ]
    return "\n".join(
        [
            f"# REAL-DATA-{run_label.upper()} official finance document seed run",
            "",
            "## Command run",
            f"`{command}`",
            "",
            "## Seed rows loaded",
            str(seed_rows_loaded),
            "",
            "## Valid seed rows",
            str(valid_count),
            "",
            "## Invalid seed rows",
            str(invalid_count),
            "",
            "## Documents attempted",
            str(0 if dry_run else len(document_index)),
            "",
            "## Downloaded / HTML saved / failed / manual review",
            f"- dry-run validated: {status_counts.get('DRY_RUN_VALIDATED', 0)}",
            f"- downloaded: {status_counts.get('DOWNLOADED', 0)}",
            f"- html snapshots: {status_counts.get('HTML_SNAPSHOT_SAVED', 0)}",
            f"- blocked/js: {status_counts.get('SOURCE_BLOCKED_OR_JS_REQUIRED', 0)}",
            f"- failed: {sum(status_counts.get(item, 0) for item in failed_statuses)}",
            f"- manual review: {len(manual_review_queue)}",
            "",
            "## Rows by source_type",
            _format_counts(_counts(document_index, "source_type")),
            "",
            "## Rows by document_type",
            _format_counts(_counts(document_index, "document_type")),
            "",
            "## Rows by status",
            _format_counts(status_counts),
            "",
            "## Main blockers",
            "Official document infrastructure is ready for seed validation, but finance parsing is not implemented in 01I-B.",
            "",
            "## Next recommended action",
            "Populate a real source-backed seed CSV for 20 representative tickers, then run non-dry-run with a small max document limit.",
        ]
    )


DOCUMENT_SEED_STATUS_BY_TICKER_COLUMNS = [
    "ticker",
    "total_seed_rows",
    "downloaded",
    "html_snapshots",
    "blocked",
    "unavailable",
    "domain_mismatch",
    "file_type_mismatch",
    "manual_review_required",
    "best_status",
    "notes",
]


def build_document_seed_status_by_ticker(document_index: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(document_index, pd.DataFrame) or document_index.empty:
        return pd.DataFrame(columns=DOCUMENT_SEED_STATUS_BY_TICKER_COLUMNS)
    rows = []
    for ticker, group in document_index.groupby("ticker", dropna=False):
        status_counts = group["download_status"].astype(str).value_counts().to_dict()
        downloaded = int(status_counts.get("DOWNLOADED", 0))
        html_snapshots = int(status_counts.get("HTML_SNAPSHOT_SAVED", 0))
        blocked = int(status_counts.get("SOURCE_BLOCKED_OR_JS_REQUIRED", 0))
        unavailable = int(
            sum(
                status_counts.get(status, 0)
                for status in [
                    "SOURCE_URL_INVALID",
                    "SOURCE_UNAVAILABLE",
                    "SOURCE_CONTENT_TYPE_UNSUPPORTED",
                    "DOWNLOAD_FAILED",
                ]
            )
        )
        domain_mismatch = int(status_counts.get("DOMAIN_MISMATCH_REVIEW", 0))
        file_type_mismatch = int(status_counts.get("FILE_TYPE_MISMATCH_REVIEW", 0))
        manual_review = bool(group["manual_review_required"].astype(bool).any())
        has_local_artifact = bool(group["local_path"].astype(str).str.strip().any())
        if downloaded or html_snapshots:
            best_status = "HAS_OFFICIAL_SNAPSHOT"
        elif has_local_artifact and (domain_mismatch or file_type_mismatch):
            best_status = "HAS_REVIEWABLE_OFFICIAL_PAGE"
        elif domain_mismatch or file_type_mismatch or manual_review:
            best_status = "NEEDS_MANUAL_REVIEW"
        elif blocked:
            best_status = "BLOCKED_OR_JS_REQUIRED"
        else:
            best_status = "ONLY_FAILED_LINKS"
        rows.append(
            {
                "ticker": ticker,
                "total_seed_rows": int(len(group)),
                "downloaded": downloaded,
                "html_snapshots": html_snapshots,
                "blocked": blocked,
                "unavailable": unavailable,
                "domain_mismatch": domain_mismatch,
                "file_type_mismatch": file_type_mismatch,
                "manual_review_required": manual_review,
                "best_status": best_status,
                "notes": "discovery pages are not confirmed finance evidence; no finance values parsed",
            }
        )
    return pd.DataFrame(rows, columns=DOCUMENT_SEED_STATUS_BY_TICKER_COLUMNS)


def build_01ib_decision_report_markdown(*, validation: pd.DataFrame, document_index: pd.DataFrame) -> str:
    valid_count = int(validation["is_valid"].sum()) if not validation.empty else 0
    invalid_count = int((~validation["is_valid"]).sum()) if not validation.empty else 0
    downloaded = 0 if document_index.empty else int(document_index["download_status"].isin(["DOWNLOADED", "HTML_SNAPSHOT_SAVED"]).sum())
    dry_run_validated = 0 if document_index.empty else int((document_index["download_status"] == "DRY_RUN_VALIDATED").sum())
    attempted = int(len(document_index))
    seed_ready = "True" if valid_count and not invalid_count else ("Partial" if valid_count else "False")
    download_ready = "Partial" if (attempted and (downloaded or dry_run_validated)) else ("False" if attempted else "Partial")
    return "\n".join(
        [
            "# Datasource decision report",
            "",
            f"- official_document_seed_ready: {seed_ready}",
            f"- official_document_download_ready: {download_ready}",
            "- finance_parse_ready: False",
            "- finance_ready_for_l0: unchanged",
            "- should_run_REAL_DATA_02: No",
            "- should_implement_Step19_now: No",
            "",
            "01I-B builds official/source-backed document infrastructure only. It does not parse finance values, score, recommend, or implement Step 19.",
        ]
    )


def _counts(df: pd.DataFrame, column: str) -> dict[str, int]:
    if not isinstance(df, pd.DataFrame) or df.empty or column not in df.columns:
        return {}
    return {str(key): int(value) for key, value in df[column].value_counts(dropna=False).items()}


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "- none"
    return "\n".join(f"- {key}: {value}" for key, value in counts.items())
