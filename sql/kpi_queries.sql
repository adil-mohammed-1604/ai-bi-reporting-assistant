/* =====================================================================
   kpi_queries.sql - the SQL side of the KPI definitions

   Eligible row = not a cancellation (InvoiceNo does not start with 'C'),
   Quantity > 0 and UnitPrice > 0. Rejected rows are never stored.
   This must stay in sync with docs/metric_dictionary.md and src/config.py.
   (LIKE is case-insensitive under SQL Server's default collation, which
   matches the Python rule.)

   HOW TO USE
   - The app reads this file: each section starts with "-- name: <key>"
     and @RunID is filled in automatically.
   - In SSMS, run ONE section at a time and put this line above it:
         DECLARE @RunID INT = 1;      -- the RunID you want to check
   ===================================================================== */

-- name: total_revenue
WITH Eligible AS (
    SELECT InvoiceNo, CustomerID, Country, StockCode, InvoiceDate, Quantity, UnitPrice
    FROM dbo.SalesTransactions
    WHERE RunID = @RunID
      AND InvoiceNo NOT LIKE 'C%'
      AND Quantity > 0
      AND UnitPrice > 0
)
SELECT CAST(SUM(Quantity * UnitPrice) AS DECIMAL(18,2)) AS Value
FROM Eligible;

-- name: distinct_orders
WITH Eligible AS (
    SELECT InvoiceNo, CustomerID, Country, StockCode, InvoiceDate, Quantity, UnitPrice
    FROM dbo.SalesTransactions
    WHERE RunID = @RunID
      AND InvoiceNo NOT LIKE 'C%'
      AND Quantity > 0
      AND UnitPrice > 0
)
SELECT COUNT(DISTINCT InvoiceNo) AS Value
FROM Eligible;

-- name: average_order_value
WITH Eligible AS (
    SELECT InvoiceNo, CustomerID, Country, StockCode, InvoiceDate, Quantity, UnitPrice
    FROM dbo.SalesTransactions
    WHERE RunID = @RunID
      AND InvoiceNo NOT LIKE 'C%'
      AND Quantity > 0
      AND UnitPrice > 0
),
OrderTotals AS (
    SELECT InvoiceNo, SUM(Quantity * UnitPrice) AS OrderTotal
    FROM Eligible
    GROUP BY InvoiceNo
)
SELECT CAST(AVG(CAST(OrderTotal AS FLOAT)) AS DECIMAL(18,2)) AS Value
FROM OrderTotals;

-- name: unique_customers
WITH Eligible AS (
    SELECT InvoiceNo, CustomerID, Country, StockCode, InvoiceDate, Quantity, UnitPrice
    FROM dbo.SalesTransactions
    WHERE RunID = @RunID
      AND InvoiceNo NOT LIKE 'C%'
      AND Quantity > 0
      AND UnitPrice > 0
)
SELECT COUNT(DISTINCT CustomerID) AS Value      -- NULL customer IDs are ignored
FROM Eligible;

-- name: monthly_revenue
WITH Eligible AS (
    SELECT InvoiceNo, CustomerID, Country, StockCode, InvoiceDate, Quantity, UnitPrice
    FROM dbo.SalesTransactions
    WHERE RunID = @RunID
      AND InvoiceNo NOT LIKE 'C%'
      AND Quantity > 0
      AND UnitPrice > 0
)
SELECT CONVERT(CHAR(7), InvoiceDate, 126)                    AS [Month],   -- yyyy-MM
       CAST(SUM(Quantity * UnitPrice) AS DECIMAL(18,2))      AS Revenue,
       COUNT(DISTINCT InvoiceNo)                             AS Orders
FROM Eligible
GROUP BY CONVERT(CHAR(7), InvoiceDate, 126)
ORDER BY [Month];

-- name: country_revenue
WITH Eligible AS (
    SELECT InvoiceNo, CustomerID, Country, StockCode, InvoiceDate, Quantity, UnitPrice
    FROM dbo.SalesTransactions
    WHERE RunID = @RunID
      AND InvoiceNo NOT LIKE 'C%'
      AND Quantity > 0
      AND UnitPrice > 0
)
SELECT COALESCE(Country, N'Unknown')                         AS Country,
       CAST(SUM(Quantity * UnitPrice) AS DECIMAL(18,2))      AS Revenue,
       COUNT(DISTINCT InvoiceNo)                             AS Orders
FROM Eligible
GROUP BY COALESCE(Country, N'Unknown')
ORDER BY Revenue DESC;