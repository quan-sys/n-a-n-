from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.provisional_finance_crosscheck import (  # noqa: E402
    build_finance_crosscheck_matrix,
    build_finance_crosscheck_summary,
    load_finance_sources,
    missing_optional_sources_markdown,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Cross-check provisional long-format finance sources.")
    parser.add_argument("--primary-finance", required=True)
    parser.add_argument("--optional-source-dir", default="data/imports/provisional_finance_sources")
    parser.add_argument("--output-dir", default="data/reports/provisional_crosscheck_02")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    finance, present_optional, missing_optional = load_finance_sources(args.primary_finance, args.optional_source_dir)
    matrix = build_finance_crosscheck_matrix(finance)
    summary = build_finance_crosscheck_summary(matrix, present_optional, missing_optional)
    matrix.to_csv(output_dir / "finance_crosscheck_matrix.csv", index=False)
    summary.to_csv(output_dir / "finance_crosscheck_summary.csv", index=False)
    if missing_optional:
        (output_dir / "finance_crosscheck_missing_optional_sources.md").write_text(
            missing_optional_sources_markdown(missing_optional),
            encoding="utf-8",
        )
    print(
        {
            "output_dir": str(output_dir),
            "finance_crosscheck_rows": int(len(matrix)),
            "status_counts": matrix["finance_crosscheck_status"].value_counts().to_dict() if not matrix.empty else {},
            "optional_sources_present": len(present_optional),
            "optional_source_dirs_missing_or_empty": len(missing_optional),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
