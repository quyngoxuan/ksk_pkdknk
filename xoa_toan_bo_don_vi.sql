/*
  Xoa don vi va du lieu cac dot kham thuoc don vi trong PKNK_KSK.
  Buoc 1: nhap MST, de @XacNhanXoa = 0, chay de xem truoc.
  Buoc 2: neu dung don vi va so luong, doi @XacNhanXoa = 1 va chay lai.
  Benh nhan con lien ket voi dot kham khac se duoc giu lai.
*/
USE [PKNK_KSK];
SET NOCOUNT ON;
SET XACT_ABORT ON;

DECLARE @MST VARCHAR(30) = 'NHAP_MST_DON_VI';
DECLARE @XacNhanXoa BIT = 0; -- Chi doi thanh 1 sau khi da kiem tra ket qua xem truoc.
DECLARE @CompanyId BIGINT;
DECLARE @TenDonVi NVARCHAR(300);

SELECT @CompanyId = ID, @TenDonVi = Name
FROM dbo.Companys
WHERE MST = @MST;

IF @CompanyId IS NULL
    THROW 51001, N'Khong tim thay don vi theo MST da nhap.', 1;

CREATE TABLE #CampaignIds (CampaignId BIGINT NOT NULL PRIMARY KEY);
INSERT INTO #CampaignIds (CampaignId)
SELECT CampaignId FROM dbo.ExamCampaigns WHERE CompanyId = @CompanyId;

/* Chi xoa benh nhan cua MST nay neu ho khong con dung o dot kham/lan kham khac. */
CREATE TABLE #PatientIds (PatientId BIGINT NOT NULL PRIMARY KEY);
INSERT INTO #PatientIds (PatientId)
SELECT p.PatientId
FROM dbo.Patients p
WHERE p.MST = @MST
  AND NOT EXISTS (
      SELECT 1 FROM dbo.PatientExamCampaigns pec
      WHERE pec.PatientId = p.PatientId
        AND NOT EXISTS (SELECT 1 FROM #CampaignIds c WHERE c.CampaignId = pec.CampaignId)
  )
  AND NOT EXISTS (
      SELECT 1 FROM dbo.HealthExams e
      WHERE e.PatientId = p.PatientId
        AND e.CampaignId IS NOT NULL
        AND NOT EXISTS (SELECT 1 FROM #CampaignIds c WHERE c.CampaignId = e.CampaignId)
  );

CREATE TABLE #ExamIds (ExamId BIGINT NOT NULL PRIMARY KEY);
INSERT INTO #ExamIds (ExamId)
SELECT e.ExamId
FROM dbo.HealthExams e
WHERE EXISTS (SELECT 1 FROM #CampaignIds c WHERE c.CampaignId = e.CampaignId)
   OR EXISTS (SELECT 1 FROM #PatientIds p WHERE p.PatientId = e.PatientId);

IF @XacNhanXoa = 0
BEGIN
    SELECT @CompanyId AS CompanyId, @TenDonVi AS TenDonVi, @MST AS MST,
           (SELECT COUNT(*) FROM #CampaignIds) AS SoDotKham,
           (SELECT COUNT(*) FROM dbo.PatientExamCampaigns pec WHERE EXISTS (SELECT 1 FROM #CampaignIds c WHERE c.CampaignId = pec.CampaignId)) AS SoLienKetHoSo,
           (SELECT COUNT(*) FROM #ExamIds) AS SoLanKham,
           (SELECT COUNT(*) FROM #PatientIds) AS SoBenhNhanSeXoa,
           (SELECT COUNT(*) FROM dbo.Patients p WHERE p.MST = @MST AND NOT EXISTS (SELECT 1 FROM #PatientIds x WHERE x.PatientId = p.PatientId)) AS SoBenhNhanGiuLaiViConDungNoiKhac;
    SELECT CampaignId FROM #CampaignIds ORDER BY CampaignId;
    RETURN;
END;

BEGIN TRY
    BEGIN TRANSACTION;

    /* Xoa log batch truoc khi xoa lan kham/dot kham (neu cac bang da duoc tao). */
    IF OBJECT_ID(N'dbo.LienThongBatchItem', N'U') IS NOT NULL
    BEGIN
        EXEC sys.sp_executesql N'
            DELETE bi
            FROM dbo.LienThongBatchItem bi
            WHERE EXISTS (SELECT 1 FROM #ExamIds e WHERE e.ExamId = bi.ExamId)
               OR EXISTS (
                    SELECT 1 FROM dbo.LienThongBatch b
                    INNER JOIN #CampaignIds c ON c.CampaignId = b.CampaignId
                    WHERE b.BatchId = bi.BatchId
               );';
    END;
    IF OBJECT_ID(N'dbo.LienThongBatch', N'U') IS NOT NULL
        EXEC sys.sp_executesql N'DELETE b FROM dbo.LienThongBatch b INNER JOIN #CampaignIds c ON c.CampaignId = b.CampaignId;';

    DELETE FROM dbo.ExamFamilyHistories WHERE EXISTS (SELECT 1 FROM #ExamIds e WHERE e.ExamId = ExamFamilyHistories.ExamId);
    DELETE FROM dbo.ExamPersonalHistories WHERE EXISTS (SELECT 1 FROM #ExamIds e WHERE e.ExamId = ExamPersonalHistories.ExamId);
    DELETE FROM dbo.ExamAdditionalHistories WHERE EXISTS (SELECT 1 FROM #ExamIds e WHERE e.ExamId = ExamAdditionalHistories.ExamId);
    DELETE FROM dbo.ExamClinicalResults WHERE EXISTS (SELECT 1 FROM #ExamIds e WHERE e.ExamId = ExamClinicalResults.ExamId);
    DELETE FROM dbo.ExamParaclinicalResults WHERE EXISTS (SELECT 1 FROM #ExamIds e WHERE e.ExamId = ExamParaclinicalResults.ExamId);
    DELETE FROM dbo.ExamKskFieldValues WHERE EXISTS (SELECT 1 FROM #ExamIds e WHERE e.ExamId = ExamKskFieldValues.ExamId);
    DELETE FROM dbo.HealthExams WHERE EXISTS (SELECT 1 FROM #ExamIds e WHERE e.ExamId = HealthExams.ExamId);

    DELETE pec
    FROM dbo.PatientExamCampaigns pec
    WHERE EXISTS (SELECT 1 FROM #CampaignIds c WHERE c.CampaignId = pec.CampaignId)
       OR EXISTS (SELECT 1 FROM #PatientIds p WHERE p.PatientId = pec.PatientId);

    DELETE p FROM dbo.Patients p INNER JOIN #PatientIds x ON x.PatientId = p.PatientId;
    DELETE c FROM dbo.ExamCampaigns c INNER JOIN #CampaignIds x ON x.CampaignId = c.CampaignId;
    DELETE FROM dbo.Companys WHERE ID = @CompanyId;

    COMMIT TRANSACTION;
    SELECT N'Da xoa don vi va du lieu cac dot kham.' AS KetQua, @CompanyId AS CompanyId, @TenDonVi AS TenDonVi, @MST AS MST;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
