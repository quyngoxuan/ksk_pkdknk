USE [PKNK_KSK];
GO

SET QUOTED_IDENTIFIER ON;
GO

SET XACT_ABORT ON;
BEGIN TRANSACTION;

IF OBJECT_ID(N'dbo.Patients', N'U') IS NULL
CREATE TABLE dbo.Patients (
    PatientId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_Patients PRIMARY KEY,
    FullName NVARCHAR(200) NOT NULL,
    Gender TINYINT NULL CONSTRAINT CK_Patients_Gender CHECK (Gender IN (1,2)),
    DateOfBirth DATE NULL,
    Phone VARCHAR(20) NULL,
    IdentityNumber VARCHAR(30) NULL,
    IdentityIssueDate DATE NULL,
    IdentityIssuePlace NVARCHAR(200) NULL,
    Ethnicity NVARCHAR(100) NULL,
    BloodGroup VARCHAR(10) NULL,
    Province NVARCHAR(100) NULL,
    Ward NVARCHAR(100) NULL,
    AddressDetail NVARCHAR(300) NULL,
    Occupation NVARCHAR(200) NULL,
    Workplace NVARCHAR(300) NULL,
    CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_Patients_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt DATETIME2(0) NULL
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'UX_Patients_IdentityNumber' AND object_id = OBJECT_ID(N'dbo.Patients'))
CREATE UNIQUE INDEX UX_Patients_IdentityNumber ON dbo.Patients(IdentityNumber) WHERE IdentityNumber IS NOT NULL;
GO

IF OBJECT_ID(N'dbo.HealthExams', N'U') IS NULL
CREATE TABLE dbo.HealthExams (
    ExamId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_HealthExams PRIMARY KEY,
    PatientId BIGINT NOT NULL,
    ExamCode VARCHAR(30) NOT NULL,
    ExamDate DATETIME2(0) NULL CONSTRAINT DF_HealthExams_ExamDate DEFAULT SYSDATETIME(),
    SubjectType NVARCHAR(150) NULL,
    PaymentSource NVARCHAR(150) NULL,
    ExamReason NVARCHAR(500) NULL,
    HeightCm DECIMAL(5,2) NULL,
    WeightKg DECIMAL(5,2) NULL,
    BMI DECIMAL(5,2) NULL,
    PulsePerMinute SMALLINT NULL,
    BloodPressure VARCHAR(20) NULL,
    PhysicalClassification NVARCHAR(100) NULL,
    HealthStatus NVARCHAR(MAX) NULL,
    HealthClassification NVARCHAR(100) NULL,
    ConclusionDate DATE NULL,
    ConclusionBy NVARCHAR(200) NULL,
    ConclusionNote NVARCHAR(500) NULL,
    Status VARCHAR(20) NOT NULL CONSTRAINT DF_HealthExams_Status DEFAULT 'Draft' CONSTRAINT CK_HealthExams_Status CHECK (Status IN ('Draft','Completed','Cancelled')),
    CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_HealthExams_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt DATETIME2(0) NULL,
    CONSTRAINT UQ_HealthExams_ExamCode UNIQUE (ExamCode),
    CONSTRAINT FK_HealthExams_Patients FOREIGN KEY (PatientId) REFERENCES dbo.Patients(PatientId)
);
GO

IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_HealthExams_PatientDate' AND object_id = OBJECT_ID(N'dbo.HealthExams'))
CREATE INDEX IX_HealthExams_PatientDate ON dbo.HealthExams(PatientId, ExamDate DESC);
GO

IF OBJECT_ID(N'dbo.ExamFamilyHistories', N'U') IS NULL
CREATE TABLE dbo.ExamFamilyHistories (
    FamilyHistoryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ExamFamilyHistories PRIMARY KEY,
    ExamId BIGINT NOT NULL,
    HasHistory BIT NOT NULL,
    Detail NVARCHAR(MAX) NULL,
    CONSTRAINT UQ_ExamFamilyHistories_ExamId UNIQUE (ExamId),
    CONSTRAINT FK_ExamFamilyHistories_HealthExams FOREIGN KEY (ExamId) REFERENCES dbo.HealthExams(ExamId)
);
GO

IF OBJECT_ID(N'dbo.ExamPersonalHistories', N'U') IS NULL
CREATE TABLE dbo.ExamPersonalHistories (
    PersonalHistoryId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ExamPersonalHistories PRIMARY KEY,
    ExamId BIGINT NOT NULL,
    HistoryCode VARCHAR(20) NOT NULL,
    HasCondition BIT NULL,
    Detail NVARCHAR(1000) NULL,
    CONSTRAINT UQ_ExamPersonalHistories UNIQUE (ExamId, HistoryCode),
    CONSTRAINT FK_ExamPersonalHistories_HealthExams FOREIGN KEY (ExamId) REFERENCES dbo.HealthExams(ExamId)
);
GO

IF OBJECT_ID(N'dbo.ExamAdditionalHistories', N'U') IS NULL
CREATE TABLE dbo.ExamAdditionalHistories (
    ExamId BIGINT NOT NULL CONSTRAINT PK_ExamAdditionalHistories PRIMARY KEY,
    CurrentTreatment NVARCHAR(MAX) NULL,
    ObstetricHistory NVARCHAR(MAX) NULL,
    CONSTRAINT FK_ExamAdditionalHistories_HealthExams FOREIGN KEY (ExamId) REFERENCES dbo.HealthExams(ExamId)
);
GO

IF OBJECT_ID(N'dbo.ExamClinicalResults', N'U') IS NULL
CREATE TABLE dbo.ExamClinicalResults (
    ClinicalResultId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ExamClinicalResults PRIMARY KEY,
    ExamId BIGINT NOT NULL,
    ExaminationCode VARCHAR(50) NOT NULL,
    ResultDetail NVARCHAR(MAX) NULL,
    Classification NVARCHAR(100) NULL,
    DoctorName NVARCHAR(200) NULL,
    DoctorSignature VARBINARY(MAX) NULL,
    CONSTRAINT UQ_ExamClinicalResults UNIQUE (ExamId, ExaminationCode),
    CONSTRAINT FK_ExamClinicalResults_HealthExams FOREIGN KEY (ExamId) REFERENCES dbo.HealthExams(ExamId)
);
GO

IF OBJECT_ID(N'dbo.ExamParaclinicalResults', N'U') IS NULL
CREATE TABLE dbo.ExamParaclinicalResults (
    ParaclinicalResultId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ExamParaclinicalResults PRIMARY KEY,
    ExamId BIGINT NOT NULL,
    TestCode VARCHAR(50) NOT NULL,
    TestName NVARCHAR(200) NOT NULL,
    ResultValue NVARCHAR(MAX) NULL,
    Unit NVARCHAR(50) NULL,
    ReferenceRange NVARCHAR(200) NULL,
    DoctorName NVARCHAR(200) NULL,
    CONSTRAINT UQ_ExamParaclinicalResults UNIQUE (ExamId, TestCode),
    CONSTRAINT FK_ExamParaclinicalResults_HealthExams FOREIGN KEY (ExamId) REFERENCES dbo.HealthExams(ExamId)
);
GO

COMMIT TRANSACTION;
GO

SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES
WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME IN ('Patients','HealthExams','ExamFamilyHistories','ExamPersonalHistories','ExamAdditionalHistories','ExamClinicalResults','ExamParaclinicalResults')
ORDER BY TABLE_NAME;
GO
