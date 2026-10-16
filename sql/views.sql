/* =====================================================================
   views.sql  -  reporting views for Power BI. Run once in SSMS.
   Safe to re-run (CREATE OR ALTER).

   Every view carries RunID and IsLatestRun. Runs are different uploads,
   so NEVER add figures from different runs together. In Power BI, filter
   IsLatestRun = 1 (or pick one RunID).

   Eligible rows follow the same rule as kpi_queries.sql:
   not a cancellation (InvoiceNo not LIKE 'C%'), Quantity > 0, UnitPrice > 0.
   ===================================================================== */
USE BIAssistant;
GO

/* One row per run, with the counts and a flag for the newest run */
CREATE OR ALTER VIEW dbo.vw_RunSummary AS
SELECT r.RunID,
       r.FileName,
       r.UploadedAt,
       r.OriginalRowCount,
       r.AcceptedRowCount,
       r.FlaggedRowCount,
       r.RejectedRowCount,
       CAST(CASE WHEN r.RunID = (SELECT MAX(RunID) FROM dbo.DatasetRuns) THEN 1 ELSE 0 END AS BIT) AS IsLatestRun
FROM dbo.DatasetRuns AS r;
GO

/* Eligible sales lines (the base for every KPI view) */
CREATE OR ALTER VIEW dbo.vw_EligibleSales AS
SELECT s.RunID,
       s.SourceRow,
       s.InvoiceNo,
       s.StockCode,
       s.[Description],
       s.Quantity,
       s.InvoiceDate,
       CAST(s.InvoiceDate AS DATE)                               AS InvoiceDay,
       CONVERT(CHAR(7), s.InvoiceDate, 126)                      AS [Month],     -- yyyy-MM
       s.UnitPrice,
       CAST(s.Quantity * s.UnitPrice AS DECIMAL(18,2))           AS LineRevenue,
       s.CustomerID,
       COALESCE(s.Country, N'Unknown')                           AS Country,
       s.QualityStatus,
       v.IsLatestRun
FROM dbo.SalesTransactions AS s
JOIN dbo.vw_RunSummary     AS v ON v.RunID = s.RunID
WHERE s.InvoiceNo NOT LIKE 'C%'
  AND s.Quantity  > 0
  AND s.UnitPrice > 0;
GO

CREATE OR ALTER VIEW dbo.vw_MonthlyKPIs AS
SELECT RunID,
       IsLatestRun,
       [Month],
       CAST(SUM(Quantity * UnitPrice) AS DECIMAL(18,2)) AS Revenue,
       COUNT(DISTINCT InvoiceNo)                        AS Orders
FROM dbo.vw_EligibleSales
GROUP BY RunID, IsLatestRun, [Month];
GO

CREATE OR ALTER VIEW dbo.vw_CountryRevenue AS
SELECT RunID,
       IsLatestRun,
       Country,
       CAST(SUM(Quantity * UnitPrice) AS DECIMAL(18,2)) AS Revenue,
       COUNT(DISTINCT InvoiceNo)                        AS Orders
FROM dbo.vw_EligibleSales
GROUP BY RunID, IsLatestRun, Country;
GO

/* All products with a revenue rank per run; show the top N in Power BI */
CREATE OR ALTER VIEW dbo.vw_TopProducts AS
SELECT t.*,
       RANK() OVER (PARTITION BY t.RunID ORDER BY t.Revenue DESC) AS RevenueRank
FROM (
    SELECT RunID,
           IsLatestRun,
           StockCode,
           MAX([Description])                               AS [Description],
           CAST(SUM(Quantity * UnitPrice) AS DECIMAL(18,2)) AS Revenue,
           SUM(Quantity)                                    AS UnitsSold
    FROM dbo.vw_EligibleSales
    GROUP BY RunID, IsLatestRun, StockCode
) AS t;
GO

CREATE OR ALTER VIEW dbo.vw_DataQualityIssues AS
SELECT q.RunID,
       v.IsLatestRun,
       q.ColumnName,
       q.IssueType,
       q.Severity,
       q.IssueCount,
       q.Details
FROM dbo.DataQualityIssues AS q
JOIN dbo.vw_RunSummary     AS v ON v.RunID = q.RunID;
GO

/* ---------------------------------------------------------------------
   Check: totals for the newest run. These must match the app's
   Analytics Dashboard (sample file: 346,087.77 revenue, 1,453 orders).
   --------------------------------------------------------------------- */
SELECT RunID,
       CAST(SUM(Revenue) AS DECIMAL(18,2)) AS TotalRevenue,
       SUM(Orders)                         AS OrdersSummedByMonth     -- invoices never span months in the sample
FROM dbo.vw_MonthlyKPIs
WHERE IsLatestRun = 1
GROUP BY RunID;

SELECT RunID, CAST(SUM(Revenue) AS DECIMAL(18,2)) AS TotalRevenue FROM dbo.vw_CountryRevenue WHERE IsLatestRun = 1 GROUP BY RunID;
SELECT RunID, CAST(SUM(Revenue) AS DECIMAL(18,2)) AS TotalRevenue FROM dbo.vw_TopProducts   WHERE IsLatestRun = 1 GROUP BY RunID;
GO