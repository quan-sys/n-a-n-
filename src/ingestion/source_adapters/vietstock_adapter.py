"""Vietstock public source adapter."""

from src.ingestion.source_adapters.base import WebTableAdapter


class VietstockAdapter(WebTableAdapter):
    source_name = "vietstock"
    source_category = "vietstock"
    supported_datasets = ["financial_statement_summary", "disclosure_status"]
