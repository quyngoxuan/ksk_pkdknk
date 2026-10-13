/* Idempotent migration: current HSSK linkage status stored on each exam. */
USE [PKNK_KSK];
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF COL_LENGTH(N'dbo.HealthExams', N'LienThongStatus') IS NULL
    ALTER TABLE dbo.HealthExams ADD LienThongStatus VARCHAR(30) NOT NULL
        CONSTRAINT DF_HealthExams_LienThongStatus DEFAULT 'NotSent' WITH VALUES;
IF COL_LENGTH(N'dbo.HealthExams', N'LienThongAt') IS NULL
    ALTER TABLE dbo.HealthExams ADD LienThongAt DATETIME2(0) NULL;
IF COL_LENGTH(N'dbo.HealthExams', N'LienThongBatchItemId') IS NULL
    ALTER TABLE dbo.HealthExams ADD LienThongBatchItemId BIGINT NULL;
IF COL_LENGTH(N'dbo.HealthExams', N'LienThongTransactionCode') IS NULL
    ALTER TABLE dbo.HealthExams ADD LienThongTransactionCode VARCHAR(100) NULL;
IF COL_LENGTH(N'dbo.HealthExams', N'LienThongMessageId') IS NULL
    ALTER TABLE dbo.HealthExams ADD LienThongMessageId VARCHAR(100) NULL;
IF COL_LENGTH(N'dbo.HealthExams', N'LienThongLastError') IS NULL
    ALTER TABLE dbo.HealthExams ADD LienThongLastError NVARCHAR(2000) NULL;
IF COL_LENGTH(N'dbo.HealthExams', N'LienThongXmlSha256') IS NULL
    ALTER TABLE dbo.HealthExams ADD LienThongXmlSha256 CHAR(64) NULL;

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_HealthExams_LienThongStatus_Campaign' AND object_id = OBJECT_ID(N'dbo.HealthExams'))
    CREATE INDEX IX_HealthExams_LienThongStatus_Campaign
        ON dbo.HealthExams(LienThongStatus, CampaignId, LienThongAt DESC);

/* Preserve existing successful history when batch tables are present. */
IF OBJECT_ID(N'dbo.LienThongBatchItem', N'U') IS NOT NULL
BEGIN
    ;WITH latest_success AS (
        SELECT BatchItemId, ExamId, XmlSha256, MessageId, TransactionCode, SentAt,
               ROW_NUMBER() OVER (PARTITION BY ExamId ORDER BY ISNULL(SentAt, CreatedAt) DESC, BatchItemId DESC) AS rn
        FROM dbo.LienThongBatchItem WHERE Status = 'Success'
    )
    UPDATE exam SET
        LienThongStatus = 'Linked',
        LienThongAt = source.SentAt,
        LienThongBatchItemId = source.BatchItemId,
        LienThongTransactionCode = source.TransactionCode,
        LienThongMessageId = source.MessageId,
        LienThongXmlSha256 = source.XmlSha256,
        LienThongLastError = NULL
    FROM dbo.HealthExams exam INNER JOIN latest_success source ON source.ExamId = exam.ExamId AND source.rn = 1
    WHERE exam.LienThongStatus = 'NotSent';
END;

COMMIT TRANSACTION;
GO
