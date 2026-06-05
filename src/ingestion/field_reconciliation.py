"""Compatibility entrypoint for field-level source reconciliation.

REAL-DATA-01F keeps the implementation in ``multi_source_evidence`` and exposes
the deterministic reconciliation functions here for callers that want a narrow
module name.
"""

from src.ingestion.multi_source_evidence import (
    FIELD_LEVEL_EVIDENCE_COLUMNS,
    RECONCILED_FIELD_COLUMNS,
    SOURCE_CONFLICT_REPORT_COLUMNS,
    UNRESOLVED_REQUIRED_FIELDS_COLUMNS,
    build_field_level_evidence,
    reconcile_field_evidence,
)

__all__ = [
    "FIELD_LEVEL_EVIDENCE_COLUMNS",
    "RECONCILED_FIELD_COLUMNS",
    "SOURCE_CONFLICT_REPORT_COLUMNS",
    "UNRESOLVED_REQUIRED_FIELDS_COLUMNS",
    "build_field_level_evidence",
    "reconcile_field_evidence",
]
