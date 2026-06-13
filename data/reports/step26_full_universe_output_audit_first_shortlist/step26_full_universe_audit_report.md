# STEP26 Full-Universe Output Audit

## 1. Scope
This report is not investment advice.
This report does not contain buy/sell/hold signals.
This report is a provisional evidence audit based on primary-only data.
Official BCTC/manual review is required before deeper analysis.

## 2. Input Artifacts Found
- step25_rows_path: data\reports\step25_full_universe_1743_primary_only_scale\full_universe_screening_rows.csv
- total_universe_rows_read: 1743

## 3. Universe Coverage
- first_review_shortlist_count: 16
- manual_bctc_priority_queue_count: 16
- data_repair_priority_count: 1727

## 4. Status Distribution
| field_value | count | percentage_of_universe |
| --- | --- | --- |
| BLOCKED_INSUFFICIENT_MARKET_DATA | 1727 | 99.082 |
| WATCHLIST_CANDIDATE | 16 | 0.918 |

## 5. Block / Reject Reasons
| reason_or_field | count | percentage_of_universe |
| --- | --- | --- |
| Primary market data missing or incomplete. | 1727 | 99.082 |
| Survived primary-only scale filters; manual BCTC/source verification remains required. | 16 | 0.918 |

## 6. Data Coverage Problems
| gap_type | affected_count |
| --- | --- |
| market_data_available | 1727 |
| recent_price_available | 1727 |
| liquidity_data_available | 728 |
| finance_data_available | 590 |
| sector_classification_available | 1743 |
| missing_field:last_price_date | 1727 |
| missing_field:net_income | 1721 |
| missing_field:last_close | 1682 |
| missing_field:capex | 1457 |
| missing_field:gross_profit | 1454 |
| missing_field:revenue | 1454 |
| missing_field:equity | 1450 |
| missing_field:total_assets | 1450 |
| missing_field:cfo | 1448 |
| missing_field:total_liabilities | 1447 |
| missing_field:avg_volume_20d | 728 |
| block_reason:Primary market data missing or incomplete. | 1727 |
| block_reason:Survived primary-only scale filters; manual BCTC/source verification remains required. | 16 |

## 7. First Review Shortlist Method
Shortlist priority uses technical coverage, non-blocked status, recent market data, liquidity evidence, fewer missing fields, and manual BCTC requirement.

## 8. Manual BCTC Priority Queue
| ticker | screening_status | review_status | data_coverage_score | missing_field_count |
| --- | --- | --- | --- | --- |
| VIX | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 75 | 0 |
| VND | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 75 | 0 |
| VCI | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 75 | 0 |
| VFS | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 75 | 0 |
| VDS | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 75 | 0 |
| TVS | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 75 | 0 |
| VIG | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 75 | 0 |
| VJC | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |
| VNM | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |
| VRE | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |
| VCG | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |
| VGI | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |
| TVN | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |
| VOS | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |
| VNE | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |
| TLH | WATCHLIST_CANDIDATE | BCTC_PRIORITY_REVIEW | 73 | 1 |

## 9. Sector / Micro-Sector Observations
| sector_or_micro_sector | total_tickers | avg_data_coverage_score |
| --- | --- | --- |
| sector_classification_not_available_in_step25_output | 0 | 0 |

## 10. Guardrail Check
- forbidden_terms_found: []
- crosscheck_status: NOT_AVAILABLE
- verification_status: NEEDS_MANUAL_BCTC_REVIEW

## 11. What This Report Does NOT Mean
This audit does not rank attractiveness, assign valuation conclusions, or provide trading guidance.

## 12. Recommended Next Actions
- Review the first manual BCTC queue.
- Repair missing market data before deeper filtering.
- Preserve provisional confidence labels until source verification improves.
