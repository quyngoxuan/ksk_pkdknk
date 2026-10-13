/*
  Migration for QD 2062/QD-BYT KSK linkage (adult form, >= 18 years).
  Safe to re-run. It only adds nullable columns/tables and never alters or deletes existing data.
*/
USE [PKNK_KSK];
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;
GO

/* Standard code values must be kept separately from the free-text display values already in Patients. */
IF COL_LENGTH(N'dbo.Patients', N'EthnicityCode') IS NULL
    ALTER TABLE dbo.Patients ADD EthnicityCode VARCHAR(2) NULL;       -- MA_DAN_TOC
IF COL_LENGTH(N'dbo.Patients', N'ProvinceCode') IS NULL
    ALTER TABLE dbo.Patients ADD ProvinceCode VARCHAR(3) NULL;        -- MATINH_CU_TRU
IF COL_LENGTH(N'dbo.Patients', N'WardCode') IS NULL
    ALTER TABLE dbo.Patients ADD WardCode VARCHAR(5) NULL;            -- MAXA_CU_TRU
IF COL_LENGTH(N'dbo.Patients', N'OccupationCode') IS NULL
    ALTER TABLE dbo.Patients ADD OccupationCode VARCHAR(2) NULL;      -- MA_NGHE_NGHIEP
GO

IF OBJECT_ID(N'dbo.KskFacilityProfiles', N'U') IS NULL
CREATE TABLE dbo.KskFacilityProfiles (
    FacilityId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_KskFacilityProfiles PRIMARY KEY,
    FacilityCode VARCHAR(5) NOT NULL,                                 -- MA_CSKCB
    GlnCode VARCHAR(13) NOT NULL,                                     -- MA_GTIN_CSKCB
    FacilityName NVARCHAR(300) NOT NULL,
    IsDefault BIT NOT NULL CONSTRAINT DF_KskFacilityProfiles_IsDefault DEFAULT 0,
    IsActive BIT NOT NULL CONSTRAINT DF_KskFacilityProfiles_IsActive DEFAULT 1,
    CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_KskFacilityProfiles_CreatedAt DEFAULT SYSDATETIME(),
    UpdatedAt DATETIME2(0) NULL,
    CONSTRAINT UQ_KskFacilityProfiles_FacilityCode UNIQUE (FacilityCode),
    CONSTRAINT UQ_KskFacilityProfiles_GlnCode UNIQUE (GlnCode)
);
GO

IF COL_LENGTH(N'dbo.HealthExams', N'FacilityId') IS NULL
    ALTER TABLE dbo.HealthExams ADD FacilityId BIGINT NULL;
IF COL_LENGTH(N'dbo.HealthExams', N'VisitCode') IS NULL
    ALTER TABLE dbo.HealthExams ADD VisitCode VARCHAR(100) NULL;      -- MA_LK
IF COL_LENGTH(N'dbo.HealthExams', N'ExamTypeCode') IS NULL
    ALTER TABLE dbo.HealthExams ADD ExamTypeCode VARCHAR(2) NULL;     -- MA_LOAI_KCB
IF COL_LENGTH(N'dbo.HealthExams', N'SubjectCodes') IS NULL
    ALTER TABLE dbo.HealthExams ADD SubjectCodes VARCHAR(50) NULL;    -- DOI_TUONG, ';' separated
IF COL_LENGTH(N'dbo.HealthExams', N'PaymentSourceCode') IS NULL
    ALTER TABLE dbo.HealthExams ADD PaymentSourceCode TINYINT NULL;   -- NGUON_CHI_TRA
IF COL_LENGTH(N'dbo.HealthExams', N'ConclusionDiseaseCodes') IS NULL
    ALTER TABLE dbo.HealthExams ADD ConclusionDiseaseCodes VARCHAR(255) NULL; -- KET_LUAN_BENH ICD-10
GO

IF NOT EXISTS (SELECT 1 FROM sys.foreign_keys WHERE name = N'FK_HealthExams_KskFacilityProfiles')
    ALTER TABLE dbo.HealthExams ADD CONSTRAINT FK_HealthExams_KskFacilityProfiles
        FOREIGN KEY (FacilityId) REFERENCES dbo.KskFacilityProfiles(FacilityId);
IF NOT EXISTS (SELECT 1 FROM sys.indexes WHERE name = N'IX_HealthExams_FacilityId' AND object_id = OBJECT_ID(N'dbo.HealthExams'))
    CREATE INDEX IX_HealthExams_FacilityId ON dbo.HealthExams(FacilityId);
GO

/* Definition table lets the application validate by official XML tag and age-form, without hard-coded DB columns. */
IF OBJECT_ID(N'dbo.KskXmlFieldDefinitions', N'U') IS NULL
CREATE TABLE dbo.KskXmlFieldDefinitions (
    FieldDefinitionId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_KskXmlFieldDefinitions PRIMARY KEY,
    FormCode VARCHAR(20) NOT NULL,                                    -- UNDER_6, AGE_6_TO_17, ADULT
    FieldCode VARCHAR(80) NOT NULL,
    FieldName NVARCHAR(255) NOT NULL,
    DataType VARCHAR(20) NOT NULL CONSTRAINT DF_KskXmlFieldDefinitions_DataType DEFAULT 'string',
    MaxLength INT NULL,
    IsRequired BIT NOT NULL CONSTRAINT DF_KskXmlFieldDefinitions_IsRequired DEFAULT 0,
    DisplayOrder SMALLINT NOT NULL,
    IsActive BIT NOT NULL CONSTRAINT DF_KskXmlFieldDefinitions_IsActive DEFAULT 1,
    CONSTRAINT UQ_KskXmlFieldDefinitions UNIQUE (FormCode, FieldCode)
);
GO

/* Extra/specialty fields from the 123-field adult XML form. One row per XML tag per exam. */
IF OBJECT_ID(N'dbo.ExamKskFieldValues', N'U') IS NULL
CREATE TABLE dbo.ExamKskFieldValues (
    ExamKskFieldValueId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_ExamKskFieldValues PRIMARY KEY,
    ExamId BIGINT NOT NULL,
    FieldCode VARCHAR(80) NOT NULL,
    FieldValue NVARCHAR(MAX) NULL,
    SourceType VARCHAR(30) NOT NULL CONSTRAINT DF_ExamKskFieldValues_SourceType DEFAULT 'Manual',
    UpdatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_ExamKskFieldValues_UpdatedAt DEFAULT SYSDATETIME(),
    CONSTRAINT UQ_ExamKskFieldValues UNIQUE (ExamId, FieldCode),
    CONSTRAINT FK_ExamKskFieldValues_HealthExams FOREIGN KEY (ExamId)
        REFERENCES dbo.HealthExams(ExamId) ON DELETE CASCADE
);
GO

/* Controlled-value catalog (ICD-10, ethnicity, location, occupation, KCB type, etc.). */
IF OBJECT_ID(N'dbo.KskCodeCatalogItems', N'U') IS NULL
CREATE TABLE dbo.KskCodeCatalogItems (
    CatalogItemId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_KskCodeCatalogItems PRIMARY KEY,
    CatalogType VARCHAR(50) NOT NULL,
    Code VARCHAR(50) NOT NULL,
    Name NVARCHAR(500) NOT NULL,
    ParentCode VARCHAR(50) NULL,
    IsActive BIT NOT NULL CONSTRAINT DF_KskCodeCatalogItems_IsActive DEFAULT 1,
    CONSTRAINT UQ_KskCodeCatalogItems UNIQUE (CatalogType, Code)
);
GO

/* Audit/outbox: retain message ID and portal response required for follow-up. */
IF OBJECT_ID(N'dbo.KskLinkageLogs', N'U') IS NULL
CREATE TABLE dbo.KskLinkageLogs (
    LinkageLogId BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_KskLinkageLogs PRIMARY KEY,
    ExamId BIGINT NOT NULL,
    MessageId VARCHAR(100) NULL,
    TransactionCode VARCHAR(100) NULL,                                -- maGiaoDich returned by HSSK
    PayloadHash CHAR(64) NULL,
    RequestPayload NVARCHAR(MAX) NULL,
    ResponsePayload NVARCHAR(MAX) NULL,
    SendStatus VARCHAR(30) NOT NULL CONSTRAINT DF_KskLinkageLogs_SendStatus DEFAULT 'Pending',
    SentAt DATETIME2(0) NULL,
    CreatedAt DATETIME2(0) NOT NULL CONSTRAINT DF_KskLinkageLogs_CreatedAt DEFAULT SYSDATETIME(),
    CONSTRAINT FK_KskLinkageLogs_HealthExams FOREIGN KEY (ExamId)
        REFERENCES dbo.HealthExams(ExamId) ON DELETE CASCADE
);
CREATE INDEX IX_KskLinkageLogs_ExamId ON dbo.KskLinkageLogs(ExamId, CreatedAt DESC);
GO

/* Required fields of the QD 2062 adult form. This avoids MERGE for older SQL Server compatibility. */
DECLARE @RequiredFields TABLE (FieldCode VARCHAR(80), FieldName NVARCHAR(255), DataType VARCHAR(20), MaxLength INT NULL, DisplayOrder SMALLINT);
INSERT INTO @RequiredFields
SELECT 'HO_TEN',N'Họ và tên','string',255,1 UNION ALL SELECT 'GIOI_TINH',N'Giới tính','number',1,2 UNION ALL SELECT 'NGAY_SINH',N'Ngày sinh','date',12,3 UNION ALL
SELECT 'MA_DAN_TOC',N'Mã dân tộc','string',2,4 UNION ALL SELECT 'SO_CCCD',N'Mã định danh/CCCD','string',NULL,5 UNION ALL SELECT 'DIA_CHI',N'Nơi ở hiện tại','string',1024,8 UNION ALL
SELECT 'MATINH_CU_TRU',N'Mã tỉnh cư trú','string',3,9 UNION ALL SELECT 'MAXA_CU_TRU',N'Mã xã cư trú','string',5,10 UNION ALL SELECT 'MA_NGHE_NGHIEP',N'Mã nghề nghiệp','string',2,11 UNION ALL
SELECT 'LY_DO_VV',N'Lý do khám sức khỏe','string',NULL,15 UNION ALL SELECT 'MA_CSKCB',N'Mã cơ sở khám bệnh, chữa bệnh','string',5,17 UNION ALL
SELECT 'MA_GTIN_CSKCB',N'Mã GLN cơ sở khám bệnh, chữa bệnh','string',13,18 UNION ALL SELECT 'DOI_TUONG',N'Đối tượng khám','string',50,19 UNION ALL
SELECT 'NGUON_CHI_TRA',N'Nguồn chi trả','number',1,20 UNION ALL SELECT 'MA_LOAI_KCB',N'Mã loại hình khám bệnh, chữa bệnh','string',2,21 UNION ALL
SELECT 'NGAY_VAO',N'Ngày khám sức khỏe','date',12,22 UNION ALL SELECT 'PHAN_LOAI_SK',N'Phân loại sức khỏe','number',1,119 UNION ALL
SELECT 'CKS_NGUOI_KET_LUAN',N'Chữ ký số người kết luận','signature',NULL,122 UNION ALL SELECT 'CKS_BENH_VIEN',N'Chữ ký số cơ sở khám bệnh, chữa bệnh','signature',NULL,123;
UPDATE target SET FieldName=source.FieldName, DataType=source.DataType, MaxLength=source.MaxLength, IsRequired=1, DisplayOrder=source.DisplayOrder, IsActive=1
FROM dbo.KskXmlFieldDefinitions target INNER JOIN @RequiredFields source ON target.FormCode='ADULT' AND target.FieldCode=source.FieldCode;
INSERT dbo.KskXmlFieldDefinitions (FormCode,FieldCode,FieldName,DataType,MaxLength,IsRequired,DisplayOrder)
SELECT 'ADULT',source.FieldCode,source.FieldName,source.DataType,source.MaxLength,1,source.DisplayOrder
FROM @RequiredFields source WHERE NOT EXISTS (SELECT 1 FROM dbo.KskXmlFieldDefinitions target WHERE target.FormCode='ADULT' AND target.FieldCode=source.FieldCode);
GO

DECLARE @Catalog TABLE (CatalogType VARCHAR(50), Code VARCHAR(50), Name NVARCHAR(500));
INSERT INTO @Catalog
SELECT 'HEALTH_CLASSIFICATION','1',N'Loại I' UNION ALL SELECT 'HEALTH_CLASSIFICATION','2',N'Loại II' UNION ALL SELECT 'HEALTH_CLASSIFICATION','3',N'Loại III' UNION ALL SELECT 'HEALTH_CLASSIFICATION','4',N'Loại IV' UNION ALL SELECT 'HEALTH_CLASSIFICATION','5',N'Loại V' UNION ALL
SELECT 'PAYMENT_SOURCE','1',N'Ngân sách Trung ương' UNION ALL SELECT 'PAYMENT_SOURCE','2',N'Ngân sách Địa phương' UNION ALL SELECT 'PAYMENT_SOURCE','3',N'Quỹ Bảo hiểm y tế' UNION ALL SELECT 'PAYMENT_SOURCE','4',N'Người sử dụng lao động' UNION ALL SELECT 'PAYMENT_SOURCE','5',N'Xã hội hóa' UNION ALL SELECT 'PAYMENT_SOURCE','9',N'Khác';
UPDATE target SET Name=source.Name, IsActive=1
FROM dbo.KskCodeCatalogItems target INNER JOIN @Catalog source ON target.CatalogType=source.CatalogType AND target.Code=source.Code;
INSERT dbo.KskCodeCatalogItems (CatalogType,Code,Name)
SELECT source.CatalogType,source.Code,source.Name FROM @Catalog source
WHERE NOT EXISTS (SELECT 1 FROM dbo.KskCodeCatalogItems target WHERE target.CatalogType=source.CatalogType AND target.Code=source.Code);
GO

COMMIT TRANSACTION;
GO

SELECT 'Migration completed' AS Result;
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA='dbo' AND TABLE_NAME IN ('KskFacilityProfiles','KskXmlFieldDefinitions','ExamKskFieldValues','KskCodeCatalogItems','KskLinkageLogs') ORDER BY TABLE_NAME;
GO
