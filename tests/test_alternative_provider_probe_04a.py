from pathlib import Path

from src.providers.alternative.installability_probe_04a import forbidden_term_hits, run_alternative_provider_probe


CONFIG = Path("config/alternative_provider_registry_04a.yaml")


def test_import_failure_is_conditional_not_hard_failure(tmp_path: Path):
    result = run_alternative_provider_probe(
        config_path=CONFIG,
        output_dir=tmp_path / "out",
        find_spec_func=lambda package: None,
        version_func=lambda package: "",
    )

    assert result["decision"]["final_decision"] == "CONDITIONAL_GO_FOR_ALT_SOURCE_04B"
    assert result["decision"]["non_importable_provider_count"] >= 1


def test_04a_does_not_use_network_or_fetch_data(tmp_path: Path):
    result = run_alternative_provider_probe(config_path=CONFIG, output_dir=tmp_path / "out")
    log = result["installability_probe_log"]

    assert result["decision"]["network_used"] is False
    assert result["decision"]["market_data_fetched"] is False
    assert result["decision"]["finance_data_fetched"] is False
    assert not log["network_used"].astype(bool).any()
    assert not log["market_data_fetched"].astype(bool).any()
    assert not log["finance_data_fetched"].astype(bool).any()


def test_default_probe_skips_module_import_execution(tmp_path: Path):
    def fail_if_imported(package: str):
        raise AssertionError(f"module import should be skipped for {package}")

    result = run_alternative_provider_probe(
        config_path=CONFIG,
        output_dir=tmp_path / "out",
        import_module_func=fail_if_imported,
        find_spec_func=lambda package: object(),
        version_func=lambda package: "0.test",
    )
    log = result["installability_probe_log"]

    assert "PACKAGE_FOUND_IMPORT_SKIPPED" in set(log["import_status"])
    assert result["decision"]["network_used"] is False


def test_required_output_files_are_created(tmp_path: Path):
    out = tmp_path / "out"
    run_alternative_provider_probe(config_path=CONFIG, output_dir=out)

    assert {
        "provider_inventory.csv",
        "provider_capability_matrix.csv",
        "source_family_registry.csv",
        "installability_probe_log.csv",
        "alt_source_04a_decision.json",
        "run_summary.md",
    }.issubset({path.name for path in out.iterdir()})


def test_forbidden_output_terms_are_not_actionable(tmp_path: Path):
    out = tmp_path / "out"
    run_alternative_provider_probe(config_path=CONFIG, output_dir=out)

    assert forbidden_term_hits(out) == []


def test_step19_and_real_data_02_are_not_invoked(tmp_path: Path):
    result = run_alternative_provider_probe(config_path=CONFIG, output_dir=tmp_path / "out")
    output_names = {path.name.lower() for path in (tmp_path / "out").glob("*")}

    assert result["decision"]["network_used"] is False
    assert not any("step19" in name for name in output_names)
    assert not any("real_data_02" in name for name in output_names)


def test_core_files_are_not_modified(tmp_path: Path):
    core = tmp_path / "core_output.csv"
    core.write_text("ticker,value\nAAA,1\n", encoding="utf-8")
    before = core.read_text(encoding="utf-8")

    result = run_alternative_provider_probe(
        config_path=CONFIG,
        output_dir=tmp_path / "out",
        core_output_paths=[core],
    )

    assert core.read_text(encoding="utf-8") == before
    assert result["decision"]["core_outputs_modified"] is False
