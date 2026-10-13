USE [PKNK_KSK];
GO

IF OBJECT_ID(N'dbo.HealthExams', N'U') IS NULL
    THROW 50001, 'Table dbo.HealthExams does not exist.', 1;
GO

IF COL_LENGTH(N'dbo.HealthExams', N'ConclusionDiseaseCodes') IS NULL
    ALTER TABLE dbo.HealthExams ADD ConclusionDiseaseCodes VARCHAR(255) NULL;
GO
