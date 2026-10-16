# Architecture

## Core rule

**Python and SQL calculate every number. The AI model only explains verified metrics.**
The AI is never the source of truth, and an AI report that contains a number it cannot trace back
to the verified metrics is blocked.

## Data flow

```
 CSV / Excel upload
        |
        v
 data_loader.py        read as text, check file type, size and required columns
        |
        v
 data_profiler.py      column profile (types, missing values, ranges)
        |
        v
 data_quality.py       validate each row -> ACCEPTED / FLAGGED / REJECTED, plus IsEligible
        |
        v
 analytics.py          KPIs and chart tables in Python (eligible rows only)
        |
        +--> database.py -> SQL Server (one transaction per load, file hash blocks duplicate loads)
        |                         |
        |                         v
        |                   sql/kpi_queries.sql  (same KPIs computed in T-SQL)
        |                         |
        +-------- reconcile ------+   Python vs SQL: money within 0.01, counts exact
        |
        v
 Streamlit app         Home, Data Quality, Analytics Dashboard, AI Report, Export Center
        |
        +--> ai_report.py  builds a payload of verified KPIs only, calls the model,
        |                  then checks every number in the reply against the payload
        |
        +--> export_utils.py  formula-safe CSV and Excel workbook

 SQL Server views (sql/views.sql) --> Power BI dashboard (powerbi/Bi_Assistant.pbix)
```

## Components

| Component | Purpose |
|---|---|
| `src/config.py` | Settings from `.env`: database connection, upload limits, required columns, AI provider. |
| `src/data_loader.py` | Safe file reading with clear errors for bad files. |
| `src/data_profiler.py` | Column and dataset profile. |
| `src/data_quality.py` | Validation rules and row classification. Nothing is deleted. |
| `src/analytics.py` | KPI definitions in Python. |
| `src/database.py` | SQL Server persistence, SQL KPI queries and reconciliation. |
| `src/ai_report.py` | Payload building, provider calls (Gemini, OpenAI, Anthropic), number grounding check, template report. |
| `src/export_utils.py` | CSV and Excel exports with formula-injection protection. |
| `app.py`, `pages/` | Streamlit interface. |
| `sql/create_tables.sql` | `DatasetRuns`, `SalesTransactions`, `DataQualityIssues`. |
| `sql/kpi_queries.sql` | The SQL side of each KPI. |
| `sql/views.sql` | Reporting views used by Power BI. |

## Database

- `DatasetRuns`: one row per upload (file name, SHA-256 hash, row counts, status).
- `SalesTransactions`: validated rows (accepted and flagged). Rejected rows are not stored.
- `DataQualityIssues`: issue counts per run.
- Each load is a single transaction. A failed load rolls back completely.
- The SHA-256 hash of the file makes reloading the same file idempotent.

## Safeguards

- **Reconciliation gate:** if Python and SQL disagree, AI report generation is blocked.
- **Number grounding:** every number in an AI report must appear in the payload. Integers 1 to 12 and period dates are exempt. Reports that fail are marked unverified and hidden by default.
- **Minimal data to the AI:** only aggregated KPIs and definitions are sent. No raw rows, invoice numbers or customer IDs. Product descriptions are cleaned and shortened to reduce prompt-injection risk.
- **Secrets:** the API key lives in `.env` (git-ignored), is sent in a request header, and is redacted from error messages.
- **CSV and Excel formula injection:** text cells that start with `=`, `+`, `-` or `@` are neutralised in CSV exports, and the Excel workbook stores text as plain text.
- **Draft label:** every AI or template report is marked as a draft that needs human review.

## Power BI

Power BI reads from the views in `sql/views.sql`, not from the raw tables. Each view carries `RunID` and
`IsLatestRun`. Report pages filter on `IsLatestRun = TRUE` so figures from different uploads are never added together.

| View | Used for |
|---|---|
| `vw_MonthlyKPIs` | Total revenue, orders, monthly revenue line chart. |
| `vw_CountryRevenue` | Revenue by country. |
| `vw_TopProducts` | Top 10 products (filter `RevenueRank <= 10`). |
| `vw_RunSummary` | Accepted, flagged and rejected counts. |
| `vw_DataQualityIssues` | Issue counts by type. |
| `vw_EligibleSales` | Base view for the others. |

## Known limitations

- Single-currency assumption; the currency is not in the data.
- A partial final month understates revenue growth.
- Unique customers is a lower bound when `CustomerID` is missing.
- The AI check verifies numbers, not the claims written around them, so a person must review every draft.
- The dashboard is built on one dataset schema (retail transactions with the required columns).