/*
  Danh mục đợt khám theo đơn vị.
  Mỗi đợt khám thuộc đúng một Companys; một bệnh nhân có thể được gán
  vào nhiều đợt khám thông qua PatientExamCampaigns.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.ExamCampaigns', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.ExamCampaigns (
        CampaignId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ExamCampaigns PRIMARY KEY,
        CompanyId BIGINT NOT NULL,
        CampaignName NVARCHAR(300) NOT NULL,
        StartDate DATE NOT NULL,
        EndDate DATE NULL,
        [Desc] NVARCHAR(1000) NULL,
        IsActive BIT NOT NULL CONSTRAINT DF_ExamCampaigns_IsActive DEFAULT (1),
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_ExamCampaigns_CreatedAt DEFAULT SYSDATETIME(),
        UpdatedAt DATETIME2(0) NULL,
        CONSTRAINT CK_ExamCampaigns_DateRange CHECK (EndDate IS NULL OR EndDate >= StartDate),
        CONSTRAINT FK_ExamCampaigns_Companys FOREIGN KEY (CompanyId)
            REFERENCES dbo.Companys(ID),
        CONSTRAINT UQ_ExamCampaigns_Company_Name_Start UNIQUE (CompanyId, CampaignName, StartDate)
    );
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_ExamCampaigns_Company_Date'
      AND object_id = OBJECT_ID(N'dbo.ExamCampaigns')
)
    CREATE INDEX IX_ExamCampaigns_Company_Date ON dbo.ExamCampaigns(CompanyId, StartDate DESC);

IF OBJECT_ID(N'dbo.PatientExamCampaigns', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.PatientExamCampaigns (
        PatientExamCampaignId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_PatientExamCampaigns PRIMARY KEY,
        PatientId BIGINT NOT NULL,
        CampaignId BIGINT NOT NULL,
        ImportedAt DATETIME2(0) NOT NULL CONSTRAINT DF_PatientExamCampaigns_ImportedAt DEFAULT SYSDATETIME(),
        CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_PatientExamCampaigns_CreatedAt DEFAULT SYSDATETIME(),
        CONSTRAINT UQ_PatientExamCampaigns_Patient_Campaign UNIQUE (PatientId, CampaignId),
        CONSTRAINT FK_PatientExamCampaigns_Patients FOREIGN KEY (PatientId)
            REFERENCES dbo.Patients(PatientId) ON DELETE CASCADE,
        CONSTRAINT FK_PatientExamCampaigns_ExamCampaigns FOREIGN KEY (CampaignId)
            REFERENCES dbo.ExamCampaigns(CampaignId)
    );
END;

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_PatientExamCampaigns_Campaign'
      AND object_id = OBJECT_ID(N'dbo.PatientExamCampaigns')
)
    CREATE INDEX IX_PatientExamCampaigns_Campaign ON dbo.PatientExamCampaigns(CampaignId, PatientId);

IF COL_LENGTH(N'dbo.HealthExams', N'CampaignId') IS NULL
    ALTER TABLE dbo.HealthExams ADD CampaignId BIGINT NULL;

IF NOT EXISTS (
    SELECT 1 FROM sys.foreign_keys
    WHERE name = N'FK_HealthExams_ExamCampaigns'
)
    ALTER TABLE dbo.HealthExams ADD CONSTRAINT FK_HealthExams_ExamCampaigns
        FOREIGN KEY (CampaignId) REFERENCES dbo.ExamCampaigns(CampaignId);

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'IX_HealthExams_CampaignId'
      AND object_id = OBJECT_ID(N'dbo.HealthExams')
)
    CREATE INDEX IX_HealthExams_CampaignId ON dbo.HealthExams(CampaignId, ExamDate DESC);

COMMIT TRANSACTION;

SELECT N'ExamCampaigns' AS TableName, COUNT(*) AS TotalRows FROM dbo.ExamCampaigns
UNION ALL
SELECT N'PatientExamCampaigns', COUNT(*) FROM dbo.PatientExamCampaigns;
