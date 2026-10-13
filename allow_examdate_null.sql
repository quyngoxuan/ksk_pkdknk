/*
   Allow imported HealthExams records to keep ExamDate empty.
   Existing ExamDate values are preserved. Run once against the target KSK database.
*/
SET XACT_ABORT ON;
BEGIN TRANSACTION;

BEGIN TRY
    IF OBJECT_ID(N'dbo.HealthExams', N'U') IS NULL
        THROW 50001, 'Table dbo.HealthExams was not found.', 1;

    DECLARE @examDateColumnId int;
    DECLARE @examDateType nvarchar(128);
    DECLARE @hasPatientDateIndex bit = 0;
    DECLARE @sql nvarchar(max);

    SELECT
        @examDateColumnId = c.column_id,
        @examDateType = CASE
            WHEN t.name IN (N'datetime2', N'datetimeoffset', N'time')
                THEN t.name + N'(' + CONVERT(nvarchar(10), c.scale) + N')'
            ELSE t.name
        END
    FROM sys.columns AS c
    INNER JOIN sys.types AS t
        ON t.user_type_id = c.system_type_id
       AND t.is_user_defined = 0
    WHERE c.object_id = OBJECT_ID(N'dbo.HealthExams')
      AND c.name = N'ExamDate';

    IF @examDateColumnId IS NULL
        THROW 50002, 'Column dbo.HealthExams.ExamDate was not found.', 1;

    IF EXISTS (
        SELECT 1
        FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.HealthExams')
          AND column_id = @examDateColumnId
          AND is_nullable = 0
    )
    BEGIN
        IF EXISTS (
            SELECT 1
            FROM sys.indexes
            WHERE object_id = OBJECT_ID(N'dbo.HealthExams')
              AND name = N'IX_HealthExams_PatientDate'
        )
        BEGIN
            SET @hasPatientDateIndex = 1;
            DROP INDEX IX_HealthExams_PatientDate ON dbo.HealthExams;
        END;

        SET @sql = N'ALTER TABLE dbo.HealthExams ALTER COLUMN ExamDate ' + @examDateType + N' NULL;';
        EXEC sys.sp_executesql @sql;

        IF @hasPatientDateIndex = 1
            CREATE INDEX IX_HealthExams_PatientDate
                ON dbo.HealthExams(PatientId, ExamDate DESC);
    END;

    COMMIT TRANSACTION;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
GO
