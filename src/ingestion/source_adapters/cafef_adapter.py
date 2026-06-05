"""CafeF public source adapter."""

from src.ingestion.source_adapters.base import WebTableAdapter


class CafeFAdapter(WebTableAdapter):
    source_name = "cafef"
    source_category = "cafef"
    supported_datasets = ["financial_statement_summary", "disclosure_status"]
