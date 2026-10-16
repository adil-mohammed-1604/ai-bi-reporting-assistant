/* =====================================================================
   create_tables.sql  -  run once in SSMS (connected to .\SQLEXPRESS)
   Safe to re-run: each object is only created if it does not exist.
   ===================================================================== */
USE BIAssistant;
GO

/* One row per upload / processing attempt */
IF OBJECT_ID(N'dbo.DatasetRuns', N'U') IS NULL
CREATE TABLE dbo.DatasetRuns (
    RunID            INT IDENTITY(1,1) NOT NULL
                     CONSTRAINT PK_DatasetRuns PRIMARY KEY,
    FileName         NVARCHAR(260)  NOT NULL,
    FileHash         CHAR(64)       NULL,      -- SHA-256 of the uploaded file (prevents duplicate loads)
    UploadedAt       DATETIME2(0)   NOT NULL
                     CONSTRAINT DF_DatasetRuns_UploadedAt DEFAULT SYSUTCDATETIME(),
    OriginalRowCount INT            NOT NULL,
    AcceptedRowCount INT            NOT NULL,
    FlaggedRowCount  INT            NOT NULL,
    RejectedRowCount INT            NOT NULL,
    Status           NVARCHAR(30)   NOT NULL
);
GO

/* Validated rows (accepted + flagged). Rejected rows are NOT stored here;
   they are kept in the app's rejected-rows download for review. */
IF OBJECT_ID(N'dbo.SalesTransactions', N'U') IS NULL
CREATE TABLE dbo.SalesTransactions (
    TransactionID BIGINT IDENTITY(1,1) NOT NULL
                  CONSTRAINT PK_SalesTransactions PRIMARY KEY,
    RunID         INT           NOT NULL
                  CONSTRAINT FK_SalesTransactions_Run REFERENCES dbo.DatasetRuns(RunID),
    SourceRow     INT           NOT NULL,      -- row number in the uploaded file (1-based)
    InvoiceNo     NVARCHAR(50)  NOT NULL,
    StockCode     NVARCHAR(50)  NULL,
    [Description] NVARCHAR(255) NULL,
    Quantity      INT           NOT NULL,
    InvoiceDate   DATETIME2(0)  NOT NULL,
    UnitPrice     DECIMAL(18,4) NOT NULL,
    CustomerID    NVARCHAR(50)  NULL,
    Country       NVARCHAR(100) NULL,
    QualityStatus VARCHAR(10)   NOT NULL,      -- ACCEPTED or FLAGGED
    IsEligible    BIT           NOT NULL,      -- Python's eligibility decision (for audit only)
    CONSTRAINT UQ_SalesTransactions_Run_SourceRow UNIQUE (RunID, SourceRow)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes
               WHERE name = N'IX_SalesTransactions_Run_InvoiceDate'
                 AND object_id = OBJECT_ID(N'dbo.SalesTransactions'))
CREATE INDEX IX_SalesTransactions_Run_InvoiceDate
    ON dbo.SalesTransactions (RunID, InvoiceDate);
GO

/* Issue summary per run */
IF OBJECT_ID(N'dbo.DataQualityIssues', N'U') IS NULL
CREATE TABLE dbo.DataQualityIssues (
    IssueID     INT IDENTITY(1,1) NOT NULL
                CONSTRAINT PK_DataQualityIssues PRIMARY KEY,
    RunID       INT           NOT NULL
                CONSTRAINT FK_DataQualityIssues_Run REFERENCES dbo.DatasetRuns(RunID),
    ColumnName  NVARCHAR(100) NOT NULL,
    IssueType   NVARCHAR(50)  NOT NULL,
    Severity    VARCHAR(10)   NOT NULL,
    IssueCount  INT           NOT NULL,
    Details     NVARCHAR(500) NULL
);
GO

/* Check: should list the three tables */
SELECT name FROM sys.tables
WHERE name IN (N'DatasetRuns', N'SalesTransactions', N'DataQualityIssues')
ORDER BY name;
GO