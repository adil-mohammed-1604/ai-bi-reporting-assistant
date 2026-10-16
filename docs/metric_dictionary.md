# Metric Dictionary

Every number in the app, the exports, the AI report and the Power BI dashboard is defined here.
Python and SQL calculate each metric independently, and the app compares the two
(tolerance 0.01 for money, exact for counts) before an AI report can be generated.

## Eligible rows

Most KPIs use **eligible rows** only. A row is eligible when all of these are true:

- it was not rejected during validation
- `InvoiceNo` does not start with `C` (a cancellation)
- `Quantity > 0`
- `UnitPrice > 0`

Nothing is deleted. Rejected and excluded rows stay visible in the Data Quality page and the exports.

## KPIs

| Metric | Definition | Limitations |
|---|---|---|
| Total revenue | Sum of `Quantity x UnitPrice` over eligible rows. | Excludes cancellations, non-positive quantity or price, and rejected rows. Currency is not specified in the data. |
| Distinct orders | Count of distinct `InvoiceNo` over eligible rows. | Counts invoices, not transaction rows. |
| Average order value | Average of order-level revenue totals (one total per eligible invoice). | Based on eligible invoices only. It is not the average of transaction lines. |
| Unique customers | Count of distinct non-missing `CustomerID` over eligible rows. | Rows without a `CustomerID` are not counted, so this is a lower bound. |
| Revenue growth % | (latest month - previous month) / previous month x 100. | A partial final month understates growth. Needs at least two months of data. |
| Data acceptance rate % | Rows not rejected / original rows x 100. | Flagged rows count as accepted, but flagged rows that are not eligible are excluded from the KPIs above. |

## Chart tables

| Table | Definition |
|---|---|
| Monthly revenue | Revenue and distinct orders per calendar month (`yyyy-MM`) of `InvoiceDate`, eligible rows only. |
| Revenue by country | Revenue and distinct orders per `Country`. Missing countries are grouped as "Unknown". |
| Top products | Revenue and units sold per `StockCode`, ranked by revenue. |

## Validation rules

| Rule | Column | Severity | Action | Meaning |
|---|---|---|---|---|
| MISSING_INVOICE | InvoiceNo | ERROR | reject | InvoiceNo is missing. |
| INVALID_DATE | InvoiceDate | ERROR | reject | Missing or not parseable as a date. |
| INVALID_QUANTITY | Quantity | ERROR | reject | Missing or not numeric. |
| INVALID_PRICE | UnitPrice | ERROR | reject | Missing or not numeric. |
| CANCELLATION | InvoiceNo | INFO | flag | Invoice starts with `C`; excluded from KPIs. |
| NON_POSITIVE_QUANTITY | Quantity | WARNING | flag | Zero or negative on a non-cancellation; excluded from KPIs. |
| NON_POSITIVE_PRICE | UnitPrice | WARNING | flag | Zero or negative; excluded from KPIs. |
| DUPLICATE_ROW | all columns | WARNING | flag | Exact repeat of an earlier row; kept and counted, never silently deleted. |
| MISSING_CUSTOMER_ID | CustomerID | WARNING | note | Row still counts toward revenue. |
| MISSING_DESCRIPTION | Description | INFO | note | Description is missing. |
| MISSING_COUNTRY | Country | INFO | note | Country is missing. |

Row status: **ACCEPTED** (no issue), **FLAGGED** (kept, with a reason) or **REJECTED** (cannot be used).

## Reference values for the sample dataset

The sample file `data/sample_retail_transactions.csv` has deliberately injected quality problems. Expected results:

| Measure | Value |
|---|---|
| Rows in file | 4,594 |
| Accepted / Flagged / Rejected | 4,436 / 149 / 9 |
| Rows stored in SQL (accepted + flagged) | 4,585 |
| Eligible rows | 4,451 |
| Total revenue | 346,087.77 |
| Distinct orders | 1,453 |
| Average order value | 238.19 |
| Unique customers | 391 |
| Revenue growth (2025-12 vs 2025-11) | -3.85% |
| Data acceptance rate | 99.8% |
| Peak month / lowest month | 2025-10 (34,709.40) / 2025-01 (25,175.26) |
| Top country | United Kingdom (185,069.38, 53.47%) |
| Top product | P1009 KNITTED THROW BLANKET (64,251.00, 18.56%) |

These values are checked by the automated tests, and the Power BI dashboard must show the same figures.