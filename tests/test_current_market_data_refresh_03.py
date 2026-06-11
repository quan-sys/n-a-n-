from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from src.ingestion.current_market_data_refresh import (
    FETCH_ERROR,
    FETCH_OK,
    compute_market_snapshot,
    run_current_market_refresh,
)


POLICY = {
    "market_refresh": {
        "source_name": "test_market",
        "lookback_calendar_days": 90,
        "max_stale_calendar_days": 14,
        "cache_max_age_hours": 24,
    }
}


def test_compute_last_close_and_last_price_date_from_history():
    history = pd.DataFrame(
        [
            {"date": "2026-06-08", "close": 10, "volume": 100},
            {"date": "2026-06-10", "close": 12, "volume": 300},
        ]
    )

    snapshot = compute_market_snapshot(
        ticker="AAA",
        normalized_history=history,
        policy=POLICY,
        fetch_status=FETCH_OK,
        run_date=datetime(2026, 6, 11, tzinfo=UTC),
    )

    assert snapshot["last_close"] == 12
    assert snapshot["last_price_date"] == "2026-06-10"
    assert snapshot["missing_market_flag"] is False


def test_avg_volume_20d_60d_skip_null_volume():
    history = pd.DataFrame(
        [{"date": f"2026-05-{day:02d}", "close": 10 + day, "volume": day if day % 2 else None} for day in range(1, 31)]
    )

    snapshot = compute_market_snapshot(
        ticker="AAA",
        normalized_history=history,
        policy=POLICY,
        fetch_status=FETCH_OK,
        run_date=datetime(2026, 6, 11, tzinfo=UTC),
    )

    assert snapshot["trading_days_20d"] == 15
    assert snapshot["trading_days_60d"] == 15
    assert snapshot["avg_volume_20d"] == 15
    assert snapshot["avg_volume_60d"] == 15


def test_missing_market_flag_true_when_no_close_or_date():
    snapshot = compute_market_snapshot(
        ticker="AAA",
        normalized_history=pd.DataFrame(columns=["date", "close", "volume"]),
        policy=POLICY,
        fetch_status=FETCH_OK,
        run_date=datetime(2026, 6, 11, tzinfo=UTC),
    )

    assert snapshot["missing_market_flag"] is True


def test_stale_price_flag_true_when_last_price_date_exceeds_threshold():
    history = pd.DataFrame([{"date": "2026-05-01", "close": 10, "volume": 100}])

    snapshot = compute_market_snapshot(
        ticker="AAA",
        normalized_history=history,
        policy=POLICY,
        fetch_status=FETCH_OK,
        run_date=datetime(2026, 6, 11, tzinfo=UTC),
    )

    assert snapshot["stale_price_flag"] is True


def test_cache_hit_does_not_call_fetcher_again(tmp_path: Path):
    ranking = tmp_path / "ranking.csv"
    ranking.write_text("ticker,rank\nAAA,1\n", encoding="utf-8")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text(
        "market_refresh:\n  source_name: test_market\n  lookback_calendar_days: 90\n  max_stale_calendar_days: 14\n  cache_max_age_hours: 24\n",
        encoding="utf-8",
    )
    calls = {"count": 0}

    def fetcher(ticker, start, end, policy):
        calls["count"] += 1
        return pd.DataFrame([{"time": "2026-06-10", "close": 10, "volume": 100}])

    run_current_market_refresh(
        ranking_path=ranking,
        output_dir=tmp_path / "out1",
        raw_output_dir=tmp_path / "raw",
        policy_path=policy_path,
        top_n=1,
        max_requests=1,
        sleep_seconds=0,
        allow_partial=True,
        force_refresh=False,
        fetcher=fetcher,
    )
    run_current_market_refresh(
        ranking_path=ranking,
        output_dir=tmp_path / "out2",
        raw_output_dir=tmp_path / "raw",
        policy_path=policy_path,
        top_n=1,
        max_requests=1,
        sleep_seconds=0,
        allow_partial=True,
        force_refresh=False,
        fetcher=fetcher,
    )

    assert calls["count"] == 1
    attempts = pd.read_csv(tmp_path / "out2" / "current_market_refresh_attempt_log.csv")
    assert attempts.iloc[0]["cache_used"] is True or str(attempts.iloc[0]["cache_used"]).lower() == "true"


def test_fetch_error_does_not_fail_batch_when_allow_partial(tmp_path: Path):
    ranking = tmp_path / "ranking.csv"
    ranking.write_text("ticker,rank\nAAA,1\nBBB,2\n", encoding="utf-8")
    policy_path = tmp_path / "policy.yaml"
    policy_path.write_text("market_refresh:\n  source_name: test_market\n", encoding="utf-8")

    def fetcher(ticker, start, end, policy):
        if ticker == "AAA":
            raise RuntimeError("boom")
        return pd.DataFrame([{"time": "2026-06-10", "close": 10, "volume": 100}])

    result = run_current_market_refresh(
        ranking_path=ranking,
        output_dir=tmp_path / "out",
        raw_output_dir=tmp_path / "raw",
        policy_path=policy_path,
        top_n=2,
        max_requests=2,
        sleep_seconds=0,
        allow_partial=True,
        force_refresh=False,
        fetcher=fetcher,
    )

    assert FETCH_ERROR in set(result["attempt_log"]["fetch_status"])
    assert len(result["snapshot"]) == 2
