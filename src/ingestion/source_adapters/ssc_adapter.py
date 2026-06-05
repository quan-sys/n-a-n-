"""SSC official disclosure source adapter."""

from src.ingestion.source_adapters.base import WebTableAdapter


class SscAdapter(WebTableAdapter):
    source_name = "ssc"
    source_category = "ssc"
    supported_datasets = ["disclosure_status"]
