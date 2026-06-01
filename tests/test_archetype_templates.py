import pandas as pd

import src.classification.archetype_templates as archetype_templates
from src.classification.archetype_templates import (
    ATTACHED_TEMPLATE_COLUMNS,
    REQUIRED_ARCHETYPES,
    REQUIRED_TEMPLATE_FIELDS,
    archetype_templates_to_dataframe,
    attach_archetype_template_metadata,
    get_archetype_template,
    list_archetype_ids,
    load_archetype_templates,
    serialize_archetype_template_columns,
    validate_archetype_templates,
)
from src.classification.business_classifier import CLASSIFICATION_OUTPUT_COLUMNS


TEMPLATES_PATH = "config/archetype_templates.yaml"
TAXONOMY_PATH = "config/micro_sector_taxonomy.yaml"


def _templates():
    return load_archetype_templates(TEMPLATES_PATH)


def _classification_df(archetype="export_manufacturer"):
    return pd.DataFrame(
        [
            {
                "ticker": "MOCK1",
                "classification_status": "CLASSIFIED",
                "primary_micro_sector": "textile_export",
                "secondary_micro_sector": "unknown",
                "primary_exposure_weight": 1.0,
                "secondary_exposure_weight": 0.0,
                "archetype": archetype,
                "drivers": ["export_demand"],
                "classification_confidence": "medium",
                "classification_notes": "mock classification only",
                "classification_evidence": ["mock evidence"],
                "warning_flags": [],
                "manual_review_required": False,
            }
        ],
        columns=CLASSIFICATION_OUTPUT_COLUMNS,
    )


def test_archetype_template_config_validates():
    config = _templates()
    result = validate_archetype_templates(config)

    assert result["is_valid"] is True
    assert result["missing_archetypes"] == []
    assert result["template_errors"] == {}


def test_required_archetypes_exist():
    config = _templates()
    archetype_ids = set(list_archetype_ids(config))

    assert set(REQUIRED_ARCHETYPES).issubset(archetype_ids)


def test_each_required_template_field_exists():
    config = _templates()

    for archetype_id in REQUIRED_ARCHETYPES:
        template = get_archetype_template(archetype_id, config)
        assert set(REQUIRED_TEMPLATE_FIELDS).issubset(set(template))
        assert template["archetype_id"] == archetype_id


def test_known_template_lookup_returns_practical_metadata():
    template = get_archetype_template("export_manufacturer", _templates())

    assert template["display_name"] == "Export Manufacturer"
    assert "textile_export" in template["typical_micro_sectors"]
    assert "export_demand" in template["key_economic_exposures"]
    assert template["cycle_sensitivity"] == "high"


def test_unknown_archetype_falls_back_to_unknown_template():
    template = get_archetype_template("missing_mock_archetype", _templates())

    assert template["archetype_id"] == "unknown"
    assert "unknown" in template["typical_micro_sectors"]


def test_validation_reports_missing_fields_without_crashing():
    config = {
        "templates": {
            "export_manufacturer": {
                "archetype_id": "export_manufacturer",
                "display_name": "Export Manufacturer",
            }
        }
    }

    result = validate_archetype_templates(
        config,
        required_archetypes=["export_manufacturer"],
        required_fields=REQUIRED_TEMPLATE_FIELDS,
    )

    assert result["is_valid"] is False
    assert "export_manufacturer" in result["template_errors"]
    assert any(
        error.startswith("MISSING_FIELD:")
        for error in result["template_errors"]["export_manufacturer"]
    )


def test_attach_template_metadata_adds_status_confidence_and_focus_fields():
    attached = attach_archetype_template_metadata(
        _classification_df("export_manufacturer"), _templates()
    )
    row = attached.iloc[0]

    for column in ATTACHED_TEMPLATE_COLUMNS:
        assert column in attached.columns
    assert row["archetype_template_status"] == "TEMPLATE_FOUND"
    assert row["archetype_template_confidence"] == "medium"
    assert row["archetype_cycle_sensitivity"] == "high"
    assert "inventory" in row["archetype_data_requirements"]
    assert row["archetype_warning_flags"] == []


def test_attach_unknown_template_is_low_confidence_manual_review_metadata():
    attached = attach_archetype_template_metadata(
        _classification_df("mock_missing_archetype"), _templates()
    )
    row = attached.iloc[0]

    assert row["archetype_template_status"] == "UNKNOWN_ARCHETYPE_TEMPLATE"
    assert row["archetype_template_confidence"] == "low"
    assert row["archetype_display_name"] == "Unknown Archetype"
    assert "UNKNOWN_ARCHETYPE_TEMPLATE" in row["archetype_warning_flags"]


def test_templates_convert_to_dataframe():
    dataframe = archetype_templates_to_dataframe(_templates())

    assert isinstance(dataframe, pd.DataFrame)
    assert set(REQUIRED_ARCHETYPES).issubset(set(dataframe["archetype_id"]))
    assert "data_requirements" in dataframe.columns


def test_serialization_helper_converts_attached_list_columns():
    attached = attach_archetype_template_metadata(
        _classification_df("export_manufacturer"), _templates()
    )
    serialized = serialize_archetype_template_columns(attached)

    assert isinstance(serialized.loc[0, "archetype_data_requirements"], str)
    assert "inventory" in serialized.loc[0, "archetype_data_requirements"]


def test_template_micro_sectors_align_with_l1_taxonomy():
    import yaml

    with open(TAXONOMY_PATH, "r", encoding="utf-8") as taxonomy_file:
        taxonomy = yaml.safe_load(taxonomy_file)

    allowed_micro_sectors = set(taxonomy["micro_sectors"])
    config = _templates()
    for template in config["templates"].values():
        assert set(template["typical_micro_sectors"]).issubset(allowed_micro_sectors)


def test_no_public_scoring_peer_comparison_valuation_or_recommendation_logic():
    public_names = {
        name
        for name in dir(archetype_templates)
        if not name.startswith("_") and callable(getattr(archetype_templates, name))
    }

    assert not any(name.startswith("score") for name in public_names)
    assert not any(name.startswith("rank_peer") for name in public_names)
    assert not any(name.startswith("value") for name in public_names)

    config_text = str(_templates()).upper()
    assert "BUY" not in config_text
    assert "SELL" not in config_text
    assert "TARGET_PRICE" not in config_text
