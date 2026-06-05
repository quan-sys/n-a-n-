"""REAL-DATA-01G source adapters."""

from src.ingestion.source_adapters.base import SourceAdapter, WebTableAdapter
from src.ingestion.source_adapters.cafef_adapter import CafeFAdapter
from src.ingestion.source_adapters.hnx_adapter import HnxAdapter
from src.ingestion.source_adapters.hose_adapter import HoseAdapter
from src.ingestion.source_adapters.ssc_adapter import SscAdapter
from src.ingestion.source_adapters.vietstock_adapter import VietstockAdapter
from src.ingestion.source_adapters.vnstock_adapter import VnstockAdapter

__all__ = [
    "SourceAdapter",
    "WebTableAdapter",
    "CafeFAdapter",
    "HnxAdapter",
    "HoseAdapter",
    "SscAdapter",
    "VietstockAdapter",
    "VnstockAdapter",
]
