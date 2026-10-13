/* Idempotent migration: batch tracking stores hashes and responses, never XML/signatures. */
USE [PKNK_KSK];
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.LienThongBatch', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.LienThongBatch (
        BatchId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_LienThongBatch PRIMARY KEY,
        CompanyId BIGINT NOT NULL,
        CampaignId BIGINT NOT NULL,
        Status VARCHAR(20) NOT NULL CONSTRAINT DF_LienThongBatch_Status DEFAULT 'Prepared',
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_LienThongBatch_CreatedAt DEFAULT SYSDATETIME(),
        StartedAt DATETIME2(0) NULL,
        CompletedAt DATETIME2(0) NULL,
        CONSTRAINT FK_LienThongBatch_Companys FOREIGN KEY (CompanyId) REFERENCES dbo.Companys(ID),
        CONSTRAINT FK_LienThongBatch_ExamCampaigns FOREIGN KEY (CampaignId) REFERENCES dbo.ExamCampaigns(CampaignId)
    );
    CREATE INDEX IX_LienThongBatch_CreatedAt ON dbo.LienThongBatch(CreatedAt DESC);
END;

IF OBJECT_ID(N'dbo.LienThongBatchItem', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.LienThongBatchItem (
        BatchItemId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_LienThongBatchItem PRIMARY KEY,
        BatchId BIGINT NOT NULL,
        ExamId BIGINT NOT NULL,
        Status VARCHAR(20) NOT NULL CONSTRAINT DF_LienThongBatchItem_Status DEFAULT 'Queued',
        XmlSha256 CHAR(64) NULL,
        MessageId VARCHAR(100) NULL,
        TransactionCode VARCHAR(100) NULL,
        ResponsePayload NVARCHAR(MAX) NULL,
        LastError NVARCHAR(2000) NULL,
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_LienThongBatchItem_CreatedAt DEFAULT SYSDATETIME(),
        SignedAt DATETIME2(0) NULL,
        SentAt DATETIME2(0) NULL,
        CONSTRAINT FK_LienThongBatchItem_Batch FOREIGN KEY (BatchId) REFERENCES dbo.LienThongBatch(BatchId) ON DELETE CASCADE,
        CONSTRAINT FK_LienThongBatchItem_HealthExams FOREIGN KEY (ExamId) REFERENCES dbo.HealthExams(ExamId),
        CONSTRAINT UQ_LienThongBatchItem_Batch_Exam UNIQUE (BatchId, ExamId)
    );
    CREATE INDEX IX_LienThongBatchItem_Batch_Status ON dbo.LienThongBatchItem(BatchId, Status);
    CREATE INDEX IX_LienThongBatchItem_Exam_CreatedAt ON dbo.LienThongBatchItem(ExamId, CreatedAt DESC);
END;

COMMIT TRANSACTION;
GO

SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = N'dbo' AND TABLE_NAME IN (N'LienThongBatch', N'LienThongBatchItem')
ORDER BY TABLE_NAME;
GO
