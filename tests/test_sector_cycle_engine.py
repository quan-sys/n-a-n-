from copy import deepcopy

import src.scoring.sector_cycle_engine as sector_cycle_engine
from src.scoring.sector_cycle_engine import (
    OUTPUT_FIELDS,
    evaluate_indicator_trend,
    load_sector_cycle_rules,
    normalize_score,
    score_all_micro_sectors,
    score_micro_sector_cycle,
    validate_sector_cycle_rules,
)


RULES_PATH = "config/sector_cycle_rules.yaml"


def _rules():
    return load_sector_cycle_rules(RULES_PATH)


def _row(indicator_id, trend="flat", value=100.0, previous_value=100.0, **overrides):
    row = {
        "micro_sector": "steel_integrated",
        "indicator_id": indicator_id,
        "date": "2026-03-31",
        "value": value,
        "previous_value": previous_value,
        "trend": trend,
        "source": "MOCK",
        "source_url": "",
        "data_quality_status": "VALID_DATA",
        "confidence": "medium",
        "notes": "mock sample data only",
    }
    row.update(overrides)
    return row


def _steel_base_rows():
    return [
        _row("HRC_price"),
        _row("iron_ore_price"),
        _row("coking_coal_price"),
        _row("steel_spread"),
        _row("construction_demand"),
    ]


def test_rule_yaml_loads_successfully():
    rules = _rules()

    assert isinstance(rules, dict)
    assert "default_rules" in rules
    assert "micro_sector_rules" in rules
    assert "steel_integrated" in rules["micro_sector_rules"]


def test_rule_validation_catches_missing_required_sections():
    errors = validate_sector_cycle_rules({"default_rules": {}})

    assert "MISSING_SECTION:micro_sector_rules" in errors
    assert any("default_rules:MISSING_FIELD" in error for error in errors)


def test_score_normalization_caps_values_between_zero_and_one_hundred():
    assert normalize_score(-10) == 0
    assert normalize_score(50.5) == 50.5
    assert normalize_score(250) == 100


def test_evaluate_indicator_trend_derives_direction_from_values():
    result = evaluate_indicator_trend(
        {"indicator_id": "mock_indicator", "value": 120, "previous_value": 100}
    )

    assert result["trend"] == "up"
    assert result["direction"] == "positive"


def test_recovery_signals_return_recovery_above_distress():
    rows = [
        _row("HRC_price", trend="up", value=110, previous_value=100),
        _row("iron_ore_price"),
        _row("coking_coal_price"),
        _row("steel_spread", trend="up", value=110, previous_value=100),
        _row("construction_demand", trend="up", value=110, previous_value=100),
    ]
    result = score_micro_sector_cycle("steel_integrated", rows, _rules())

    assert result["cycle_status"] == "SECTOR_RECOVERY"
    assert result["recovery_score"] > result["distress_score"]
    assert result["cycle_confidence"] == "high"
    assert bool(result["manual_review_required"]) is False


def test_distress_signals_return_distress_above_recovery():
    rows = [
        _row("HRC_price"),
        _row("iron_ore_price", trend="up", value=110, previous_value=100),
        _row("coking_coal_price", trend="up", value=110, previous_value=100),
        _row("steel_spread", trend="down", value=90, previous_value=100),
        _row("construction_demand", trend="down", value=90, previous_value=100),
        _row("inventory", trend="up", value=110, previous_value=100),
    ]
    result = score_micro_sector_cycle("steel_integrated", rows, _rules())

    assert result["cycle_status"] == "SECTOR_DISTRESS"
    assert result["distress_score"] > result["recovery_score"]


def test_overheating_signal_increases_overheating_score():
    rows = [*_steel_base_rows(), _row("volume", trend="spike_up")]
    result = score_micro_sector_cycle("steel_integrated", rows, _rules())

    assert result["overheating_score"] > 0
    assert any(item["signal"] == "overheating" for item in result["evidence"])


def test_structural_risk_signal_increases_structural_risk_score():
    rows = [*_steel_base_rows(), _row("trade_defense_risk", trend="active")]
    result = score_micro_sector_cycle("steel_integrated", rows, _rules())

    assert result["cycle_status"] == "SECTOR_STRUCTURAL_RISK"
    assert result["structural_risk_score"] > 0
    assert bool(result["manual_review_required"]) is True


def test_missing_key_indicators_reduces_confidence_and_triggers_insufficient_data():
    result = score_micro_sector_cycle(
        "steel_integrated",
        [_row("HRC_price", trend="up")],
        _rules(),
    )

    assert result["cycle_status"] == "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE"
    assert result["cycle_confidence"] == "low"
    assert "MISSING_KEY_INDICATORS" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True


def test_low_confidence_rows_reduce_cycle_confidence():
    rows = [
        _row("HRC_price", confidence="low"),
        _row("iron_ore_price"),
        _row("coking_coal_price"),
        _row("steel_spread"),
        _row("construction_demand"),
    ]
    result = score_micro_sector_cycle("steel_integrated", rows, _rules())

    assert result["cycle_confidence"] == "low"
    assert "LOW_INDICATOR_CONFIDENCE" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True


def test_data_conflict_triggers_manual_review():
    rows = [
        _row("HRC_price", data_quality_status="DATA_CONFLICT"),
        _row("iron_ore_price"),
        _row("coking_coal_price"),
        _row("steel_spread"),
        _row("construction_demand"),
    ]
    result = score_micro_sector_cycle("steel_integrated", rows, _rules())

    assert result["cycle_status"] == "SECTOR_MANUAL_REVIEW"
    assert result["data_quality_status"] == "DATA_QUALITY_REVIEW"
    assert "DATA_CONFLICT" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True


def test_anomaly_triggers_alert_without_permanently_modifying_config():
    rules = _rules()
    original_rules = deepcopy(rules)
    rows = [
        _row("HRC_price", trend="up", value=160, previous_value=100),
        _row("iron_ore_price"),
        _row("coking_coal_price"),
        _row("steel_spread"),
        _row("construction_demand"),
    ]
    result = score_micro_sector_cycle("steel_integrated", rows, rules)

    assert result["cycle_status"] == "SECTOR_ANOMALY_REVIEW"
    assert bool(result["anomaly_alert"]) is True
    assert result["anomaly_score"] > 0
    assert result["suggested_temporary_adjustment"]["permanent_weight_change"] is False
    assert rules == original_rules


def test_unknown_micro_sector_returns_manual_review_status():
    result = score_micro_sector_cycle("mock_unknown_sector", [], _rules())

    assert result["cycle_status"] == "INSUFFICIENT_DATA_FOR_SECTOR_CYCLE"
    assert result["cycle_confidence"] == "low"
    assert "UNKNOWN_MICRO_SECTOR_FOR_SECTOR_CYCLE" in result["warning_flags"]
    assert bool(result["manual_review_required"]) is True


def test_output_includes_evidence_and_warning_flags():
    result = score_micro_sector_cycle(
        "steel_integrated",
        [_row("HRC_price")],
        _rules(),
    )

    assert list(result.keys()) == OUTPUT_FIELDS
    assert isinstance(result["evidence"], list)
    assert isinstance(result["warning_flags"], list)
    assert result["evidence"]


def test_score_all_micro_sectors_groups_rows():
    rows = [
        _row("HRC_price"),
        _row("iron_ore_price"),
        _row("coking_coal_price"),
        _row("steel_spread"),
        _row("construction_demand"),
        _row(
            "container_volume",
            micro_sector="port_logistics",
            trend="up",
            value=110,
            previous_value=100,
        ),
        _row("export_import_volume", micro_sector="port_logistics"),
        _row("freight_rate", micro_sector="port_logistics"),
        _row("logistics_cost", micro_sector="port_logistics"),
    ]
    results = score_all_micro_sectors(rows, _rules())

    assert {result["micro_sector"] for result in results} == {
        "steel_integrated",
        "port_logistics",
    }


def test_output_contains_no_recommendation_or_target_price_fields():
    result = score_micro_sector_cycle("steel_integrated", _steel_base_rows(), _rules())
    output_keys = _recursive_keys(result)

    assert "buy" not in output_keys
    assert "sell" not in output_keys
    assert "target_price" not in output_keys


def test_no_live_fetching_company_scoring_or_real_financial_data_is_required():
    public_names = {
        name
        for name in dir(sector_cycle_engine)
        if not name.startswith("_") and callable(getattr(sector_cycle_engine, name))
    }

    assert not any(name.startswith("fetch") for name in public_names)
    assert not any(name.startswith("rank_peer") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)

    result = score_micro_sector_cycle("steel_integrated", _steel_base_rows(), _rules())
    assert "ticker" not in result


def _recursive_keys(value):
    keys = set()
    if isinstance(value, dict):
        for key, nested_value in value.items():
            keys.add(str(key).lower())
            keys.update(_recursive_keys(nested_value))
    elif isinstance(value, list):
        for item in value:
            keys.update(_recursive_keys(item))
    return keys
