import pandas as pd

from src.ingestion.financial_numeric_page_scorer import split_numeric_table_layers


def test_numeric_table_layers_keep_raw_and_split_non_financial_tables():
    finance_tables = pd.DataFrame(
        [
            {
                "file_hash": "hash1",
                "page_number": 1,
                "table_index": 1,
                "table_status": "FINANCE_NUMERIC_TABLE_CANDIDATE",
            },
            {
                "file_hash": "hash1",
                "page_number": 2,
                "table_index": 2,
                "table_status": "NON_FINANCIAL_NUMERIC_TABLE",
            },
        ]
    )
    raw_cells = pd.DataFrame(
        [
            {"file_hash": "hash1", "page_number": 1, "table_index": 1, "raw_cell": "Total assets"},
            {"file_hash": "hash1", "page_number": 2, "table_index": 2, "raw_cell": "Absorption rate"},
        ]
    )
    raw_rows = pd.DataFrame(
        [
            {"file_hash": "hash1", "page_number": 1, "table_index": 1, "raw_row_text": "Total assets | 123"},
            {"file_hash": "hash1", "page_number": 2, "table_index": 2, "raw_row_text": "Hanoi | absorption | 45"},
        ]
    )

    raw_rows_out, raw_cells_out, non_fin_rows, non_fin_cells = split_numeric_table_layers(
        finance_table_candidates=finance_tables,
        raw_cells=raw_cells,
        raw_rows=raw_rows,
    )

    assert len(raw_rows_out) == 2
    assert len(raw_cells_out) == 2
    assert list(non_fin_rows["table_index"]) == [2]
    assert list(non_fin_cells["table_index"]) == [2]
