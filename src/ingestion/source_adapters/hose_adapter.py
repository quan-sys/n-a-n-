"""HOSE official disclosure source adapter."""

from src.ingestion.source_adapters.base import WebTableAdapter


class HoseAdapter(WebTableAdapter):
    source_name = "hose"
    source_category = "hose"
    supported_datasets = ["disclosure_status"]
