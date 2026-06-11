from pathlib import Path

import pandas as pd

from src.validation.current_market_crosscheck_03b import run_market_crosscheck


FORBIDDEN_OUTPUT_WORDS = ["buy", "sell", "target", "fair_value", "margin_of_safety"]


def test_primary_snapshot_missing_required_schema_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=1, write_raw=True)
    snapshot = pd.read_csv(paths["snapshot"])
    snapshot = snapshot.drop(columns=["last_close"])
    snapshot.to_csv(paths["snapshot"], index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert "FAIL_SCHEMA_MISSING" in set(result.crosscheck["comparison_status"])


def test_primary_stale_row_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=1, write_raw=True)
    snapshot = pd.read_csv(paths["snapshot"])
    snapshot.loc[0, "stale_price_flag"] = True
    snapshot.to_csv(paths["snapshot"], index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert "FAIL_PRIMARY_STALE" in set(result.crosscheck["comparison_status"])


def test_primary_missing_last_close_is_no_go(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=1, write_raw=True)
    snapshot = pd.read_csv(paths["snapshot"])
    snapshot["last_close"] = snapshot["last_close"].astype(object)
    snapshot.loc[0, "last_close"] = ""
    snapshot.to_csv(paths["snapshot"], index=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "NO_GO"
    assert "FAIL_PRIMARY_MISSING" in set(result.crosscheck["comparison_status"])


def test_reference_missing_with_fresh_primary_is_conditional_go(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=2, write_raw=False)

    result = _run(paths)

    assert result.decision["final_decision"] == "CONDITIONAL_GO"
    assert set(result.crosscheck["comparison_status"]) == {"WARN_REFERENCE_MISSING"}


def test_stale_public_historical_reference_is_not_current_confirmation(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=1, write_raw=False)
    _write_prior_public_reference(paths["prior"], "T001", "2023-06-30", 10.0, 100.0)

    result = _run(paths)
    public_rows = result.crosscheck[result.crosscheck["reference_source_name"].eq("provisional_crosscheck_02_public_historical")]

    assert result.decision["final_decision"] == "CONDITIONAL_GO"
    assert public_rows.iloc[0]["comparison_status"] == "WARN_REFERENCE_STALE"
    assert str(public_rows.iloc[0]["reference_is_current_enough"]).lower() == "false"


def test_price_mismatch_above_threshold_sets_manual_review(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=1, write_raw=False)
    _write_prior_legacy_reference(paths["prior"], "T001", "2026-06-11", 5.0, 200.0)

    result = _run(paths)

    assert "WARN_PRICE_MISMATCH" in set(result.crosscheck["comparison_status"])
    assert bool(result.manual_review["manual_review_flag"].map(_as_bool).any())


def test_generated_outputs_do_not_contain_forbidden_words(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=1, write_raw=True)

    _run(paths)

    for path in paths["output"].glob("*"):
        text = path.read_text(encoding="utf-8").lower()
        for word in FORBIDDEN_OUTPUT_WORDS:
            assert word not in text


def test_exact_20_tickers_derived_from_snapshot_not_hardcoded(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker_count=20, write_raw=False, ticker_prefix="Z")

    result = _run(paths)

    expected = {f"Z{index:03d}" for index in range(1, 21)}
    assert result.decision["pilot_ticker_count"] == 20
    assert set(result.crosscheck["ticker"]) == expected


def _run(paths: dict[str, Path]):
    return run_market_crosscheck(
        snapshot_path=paths["snapshot"],
        output_dir=paths["output"],
        config_path=paths["config"],
        legacy_market_path=paths["legacy"],
        prior_crosscheck_dir=paths["prior"],
        raw_cache_dir=paths["raw"],
    )


def _write_fixture(tmp_path: Path, *, ticker_count: int, write_raw: bool, ticker_prefix: str = "T") -> dict[str, Path]:
    snapshot = tmp_path / "current_market_snapshot.csv"
    output = tmp_path / "out"
    raw = tmp_path / "raw"
    prior = tmp_path / "prior"
    legacy = tmp_path / "legacy_market.csv"
    processed = tmp_path / "data" / "processed"
    config = tmp_path / "config.yaml"
    raw.mkdir(parents=True, exist_ok=True)
    prior.mkdir(parents=True, exist_ok=True)
    processed.mkdir(parents=True, exist_ok=True)
    config.write_text(
        "\n".join(
            [
                "comparison:",
                "  max_current_reference_gap_days: 5",
                "  max_price_pct_diff_for_match: 0.03",
                "  max_volume_60d_pct_diff_for_match: 0.50",
                "  public_historical_source_is_current_source: false",
                "  conditional_if_any_reference_stale_or_missing: true",
                "",
            ]
        ),
        encoding="utf-8",
    )
    rows = []
    for index in range(1, ticker_count + 1):
        ticker = f"{ticker_prefix}{index:03d}"
        rows.append(
            {
                "ticker": ticker,
                "last_close": 10.0,
                "last_price_date": "2026-06-11",
                "avg_volume_20d": 200.0,
                "avg_volume_60d": 200.0,
                "trading_days_60d": 2,
                "missing_market_flag": False,
                "stale_price_flag": False,
            }
        )
        if write_raw:
            pd.DataFrame(
                [
                    {"ticker": ticker, "date": "2026-06-10", "close": 9.0, "volume": 100},
                    {"ticker": ticker, "date": "2026-06-11", "close": 10.0, "volume": 300},
                ]
            ).to_csv(raw / f"{ticker}_history.csv", index=False)
    pd.DataFrame(rows).to_csv(snapshot, index=False)
    pd.DataFrame(columns=["ticker", "last_close", "last_price_date", "avg_volume_20d", "avg_volume_60d"]).to_csv(legacy, index=False)
    return {
        "snapshot": snapshot,
        "output": output,
        "raw": raw,
        "prior": prior,
        "legacy": legacy,
        "processed": processed,
        "config": config,
    }


def _write_prior_public_reference(prior_dir: Path, ticker: str, last_price_date: str, last_close: float, avg_volume_60d: float) -> None:
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "public_last_price_date": last_price_date,
                "public_last_close": last_close,
                "public_avg_volume_20d": avg_volume_60d,
                "public_avg_volume_60d": avg_volume_60d,
                "legacy_last_price_date": "",
                "legacy_last_close": "",
                "legacy_avg_volume_20d": "",
                "legacy_avg_volume_60d": "",
            }
        ]
    ).to_csv(prior_dir / "market_price_crosscheck.csv", index=False)


def _write_prior_legacy_reference(prior_dir: Path, ticker: str, last_price_date: str, last_close: float, avg_volume_60d: float) -> None:
    pd.DataFrame(
        [
            {
                "ticker": ticker,
                "public_last_price_date": "",
                "public_last_close": "",
                "public_avg_volume_20d": "",
                "public_avg_volume_60d": "",
                "legacy_last_price_date": last_price_date,
                "legacy_last_close": last_close,
                "legacy_avg_volume_20d": avg_volume_60d,
                "legacy_avg_volume_60d": avg_volume_60d,
            }
        ]
    ).to_csv(prior_dir / "market_price_crosscheck.csv", index=False)


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}
