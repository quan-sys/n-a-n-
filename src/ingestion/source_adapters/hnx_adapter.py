"""HNX official disclosure source adapter."""

from src.ingestion.source_adapters.base import WebTableAdapter


class HnxAdapter(WebTableAdapter):
    source_name = "hnx"
    source_category = "hnx"
    supported_datasets = ["disclosure_status"]
