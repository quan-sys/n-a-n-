from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.ingestion.legacy_structured_finance_importer import import_legacy_structured_finance  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import legacy structured finance as provisional data.")
    parser.add_argument("--input-dir", required=True)
    parser.add_argument("--output-dir", default="data/reports/legacy_structured_finance_import_01")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = import_legacy_structured_finance(Path(args.input_dir), Path(args.output_dir))
    print({"output_dir": args.output_dir, **summary})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
