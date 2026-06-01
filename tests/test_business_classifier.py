import pandas as pd

import src.classification.business_classifier as business_classifier
from src.classification.business_classifier import (
    CLASSIFICATION_OUTPUT_COLUMNS,
    classify_businesses,
    load_business_classification_rules,
    load_micro_sector_taxonomy,
    serialize_classification_output,
)


RULES_PATH = "config/l1_business_classification_rules.yaml"
TAXONOMY_PATH = "config/micro_sector_taxonomy.yaml"


def _rules():
    return load_business_classification_rules(RULES_PATH)


def _taxonomy():
    return load_micro_sector_taxonomy(TAXONOMY_PATH)


def _l0_df(ticker="MOCK1", status="L0_INVESTABLE", confidence="high"):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "l0_basic_status": status,
                "basic_investability_score": 90,
                "warning_flags": [],
                "reject_reasons": [],
                "evidence_fields": [],
                "confidence": confidence,
                "manual_review_required": status == "L0_MANUAL_REVIEW",
            }
        ]
    )


def _profile_df(
    ticker="MOCK1",
    business_description="Mock textile garment export manufacturer.",
    industry_raw="Mock manufacturing",
    company_name="Mock Company",
    **overrides,
):
    row = {
        "ticker": ticker,
        "company_name": company_name,
        "exchange": "MOCK_EXCHANGE",
        "industry_raw": industry_raw,
        "business_description": business_description,
        "source": "MOCK",
        "source_url": "",
        "last_updated": "2026-05-25",
        "fetch_time": "2026-05-25T00:00:00Z",
        "confidence_raw": "high",
        "notes": "mock profile data only",
        "quality_status": "VALID_DATA",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _financial_df(ticker="MOCK1", **overrides):
    row = {
        "ticker": ticker,
        "period": "2026Q1",
        "revenue": 1000,
        "gross_profit": 300,
        "operating_profit": 200,
        "net_profit": 100,
        "total_assets": 5000,
        "total_liabilities": 1500,
        "equity": 3500,
        "cash": 500,
        "short_term_debt": 100,
        "long_term_debt": 300,
        "operating_cash_flow": 150,
        "inventory": 250,
        "source": "MOCK",
        "fetch_time": "2026-05-25T00:00:00Z",
        "quality_status": "VALID_DATA",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _segment_df(rows, ticker="MOCK1"):
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "segment_name": segment_name,
                "segment_revenue": segment_revenue,
                "source": "MOCK",
                "notes": "mock segment data only",
            }
            for segment_name, segment_revenue in rows
        ]
    )


def _run(**overrides):
    params = {
        "l0_basic_df": _l0_df(),
        "company_profile_df": _profile_df(),
        "financial_statement_df": _financial_df(),
        "segment_df": None,
        "manual_notes_df": None,
        "taxonomy": _taxonomy(),
        "rules": _rules(),
    }
    params.update(overrides)
    return classify_businesses(**params)


def test_text_keyword_match_classifies_business_with_medium_confidence():
    result = _run()
    row = result.iloc[0]

    assert list(result.columns) == CLASSIFICATION_OUTPUT_COLUMNS
    assert row["primary_micro_sector"] == "textile_export"
    assert row["archetype"] == "export_manufacturer"
    assert row["classification_status"] == "CLASSIFIED"
    assert row["classification_confidence"] == "medium"
    assert bool(row["manual_review_required"]) is False
    assert "export_demand" in row["drivers"]


def test_dominant_segment_data_takes_priority_over_text():
    result = _run(
        company_profile_df=_profile_df(
            business_description="Mock company profile with textile exposure."
        ),
        segment_df=_segment_df(
            [
                ("Mock textile export operations", 700),
                ("Mock port logistics operations", 300),
            ]
        ),
    )
    row = result.iloc[0]

    assert row["primary_micro_sector"] == "textile_export"
    assert row["secondary_micro_sector"] == "port_logistics"
    assert row["primary_exposure_weight"] == 0.7
    assert row["secondary_exposure_weight"] == 0.3
    assert row["classification_confidence"] == "high"


def test_two_meaningful_segments_keep_primary_and_secondary_exposure_weights():
    result = _run(
        company_profile_df=_profile_df(
            business_description="Mock profile with segment data available."
        ),
        segment_df=_segment_df(
            [
                ("Mock industrial park operations", 600),
                ("Mock residential property developer operations", 400),
            ]
        ),
    )
    row = result.iloc[0]

    assert row["primary_micro_sector"] == "industrial_park"
    assert row["secondary_micro_sector"] == "residential_real_estate"
    assert row["primary_exposure_weight"] == 0.6
    assert row["secondary_exposure_weight"] == 0.4
    assert row["classification_status"] == "CLASSIFIED"


def test_holding_or_diversified_company_requires_manual_review():
    result = _run(
        company_profile_df=_profile_df(
            business_description=(
                "Mock diversified investment holding with subsidiaries and "
                "associate companies."
            ),
            industry_raw="Mock investment holding",
        )
    )
    row = result.iloc[0]

    assert row["primary_micro_sector"] == "holding_company"
    assert row["classification_status"] == "MANUAL_REVIEW"
    assert "HOLDING_COMPANY_REVIEW" in row["warning_flags"]
    assert bool(row["manual_review_required"]) is True


def test_missing_business_description_is_low_confidence_manual_review():
    result = _run(
        company_profile_df=_profile_df(
            business_description="",
            industry_raw="Mock banking",
            company_name="Mock Company",
        )
    )
    row = result.iloc[0]

    assert row["primary_micro_sector"] == "commercial_bank"
    assert row["classification_status"] == "MANUAL_REVIEW"
    assert row["classification_confidence"] == "low"
    assert "MISSING_BUSINESS_DESCRIPTION" in row["warning_flags"]
    assert "BROAD_INDUSTRY_ONLY" in row["warning_flags"]


def test_conflicting_industry_and_description_flags_manual_review():
    result = _run(
        company_profile_df=_profile_df(
            business_description="Mock pangasius seafood export processor.",
            industry_raw="Mock banking",
        )
    )
    row = result.iloc[0]

    assert row["primary_micro_sector"] == "pangasius_export"
    assert row["classification_status"] == "MANUAL_REVIEW"
    assert "CONFLICTING_CLASSIFICATION_SIGNALS" in row["warning_flags"]


def test_l0_reject_is_not_classified():
    result = _run(l0_basic_df=_l0_df(status="L0_REJECT", confidence="low"))
    row = result.iloc[0]

    assert row["classification_status"] == "NOT_CLASSIFIED"
    assert row["primary_micro_sector"] == "unknown"
    assert row["classification_confidence"] == "low"
    assert "FAILED_L0_BASIC_INVESTABILITY" in row["warning_flags"]


def test_l0_manual_review_allows_only_provisional_classification():
    result = _run(l0_basic_df=_l0_df(status="L0_MANUAL_REVIEW", confidence="low"))
    row = result.iloc[0]

    assert row["primary_micro_sector"] == "textile_export"
    assert row["classification_status"] == "PROVISIONAL_CLASSIFICATION"
    assert row["classification_confidence"] == "low"
    assert bool(row["manual_review_required"]) is True


def test_unknown_business_profile_goes_to_manual_review():
    result = _run(
        company_profile_df=_profile_df(
            business_description="Mock operations with unclear activity.",
            industry_raw="Mock unclear industry",
        )
    )
    row = result.iloc[0]

    assert row["primary_micro_sector"] == "unknown"
    assert row["classification_status"] == "MANUAL_REVIEW"
    assert "UNKNOWN_MICRO_SECTOR" in row["warning_flags"]


def test_unexpected_l0_status_is_not_classified():
    result = _run(l0_basic_df=_l0_df(status="L0_PENDING", confidence="low"))
    row = result.iloc[0]

    assert row["classification_status"] == "NOT_CLASSIFIED"
    assert "INSUFFICIENT_DATA_FOR_CLASSIFICATION" in row["warning_flags"]


def test_config_loading_and_required_micro_sectors_exist():
    taxonomy = _taxonomy()
    rules = _rules()

    required = {
        "steel_integrated",
        "galvanized_steel",
        "natural_rubber",
        "tire_manufacturing",
        "pangasius_export",
        "shrimp_export",
        "textile_export",
        "residential_real_estate",
        "industrial_park",
        "commercial_bank",
        "securities_broker",
        "power_generation",
        "port_logistics",
        "oil_gas_upstream",
        "oil_gas_services",
        "fertilizer",
        "consumer_staples",
        "retail_distribution",
        "construction_materials",
        "holding_company",
        "unknown",
    }

    assert required.issubset(set(taxonomy["micro_sectors"]))
    assert "L0_INVESTABLE" in rules["eligible_l0_basic_statuses"]


def test_serialization_helper_converts_list_columns():
    result = _run()
    serialized = serialize_classification_output(result)

    assert isinstance(serialized.loc[0, "drivers"], str)
    assert "export_demand" in serialized.loc[0, "drivers"]


def test_mock_data_only_and_no_recommendation_language():
    result = _run()

    assert set(result["ticker"]) == {"MOCK1"}
    assert result["ticker"].str.startswith("MOCK").all()

    output_text = result.to_string().upper()
    assert "BUY" not in output_text
    assert "SELL" not in output_text


def test_no_sector_cycle_peer_ranking_or_valuation_public_functions():
    public_names = {
        name
        for name in dir(business_classifier)
        if not name.startswith("_") and callable(getattr(business_classifier, name))
    }

    assert not any(name.startswith("run_sector_cycle") for name in public_names)
    assert not any(name.startswith("rank_peer") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)
