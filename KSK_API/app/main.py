from datetime import date, datetime
from datetime import timedelta
import asyncio
from copy import copy
import hmac
from io import BytesIO
from pathlib import Path
import tempfile
from uuid import uuid4
from xml.etree import ElementTree as ET

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from sqlalchemy import func, inspect, text, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.background import BackgroundTask
from reportlab.graphics.barcode import code128
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .config import get_settings
from .database import SessionLocal, get_db
from .lienthong import build_envelope, login as lien_thong_login, push as lien_thong_push
from .word_export import create_administrative_docx, create_campaign_administrative_docx
from .models import (AdministrativeProvince, AdministrativeWard, Company, ExamAdditionalHistory, ExamCampaign, ExamClinicalResult, ExamFamilyHistory,
                     ExamKskFieldValue, ExamParaclinicalResult, ExamPersonalHistory, HealthExam,
                     Icd10Code, KskFacilityProfile, KskXmlFieldDefinition, LienThongBatch, LienThongBatchItem, Patient, PatientExamCampaign)
from .schemas import (AdditionalHistoryInput, AdministrativeProvinceRead, AdministrativeWardRead, ClinicalResultInput, CompanyCreate, CompanyRead, DeleteResult,
                      CompanyUpdate, ExamCampaignCreate, ExamCampaignRead, ExamCampaignUpdate, FamilyHistoryInput,
                      HealthExamCreate, HealthExamDetail, HealthExamRead, HealthExamUpdate,
                      FacilityProfileInput, FacilityProfileRead,
                      KskFieldValueInput, LinkageReadiness, LinkageValidationIssue,
                      LienThongBatchCreate, LienThongBatchItemUpdate, LienThongBatchRead,
                      LienThongEnvelope, LienThongPushRequest,
                      ParaclinicalResultInput, PatientBulkImport, PatientBulkImportResult, PatientPage,
                      PatientCreate, PatientCreateForCampaign, PatientImportIssue, PatientRead, PatientUpdate, PersonalHistoryInput)

settings = get_settings()
_batch_cleanup_task: asyncio.Task | None = None
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="API nhập và quản lý giấy khám sức khỏe từ đủ 18 tuổi (Mẫu 03).",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def start_batch_retention_cleanup():
    async def cleanup_loop():
        while True:
            try:
                with SessionLocal() as db:
                    purge_expired_batches(db)
            except Exception:
                # Keep the API available; a later cycle retries cleanup.
                pass
            await asyncio.sleep(24 * 60 * 60)

    global _batch_cleanup_task
    _batch_cleanup_task = asyncio.create_task(cleanup_loop())


@app.on_event("shutdown")
async def stop_batch_retention_cleanup():
    if _batch_cleanup_task is not None:
        _batch_cleanup_task.cancel()
        try:
            await _batch_cleanup_task
        except asyncio.CancelledError:
            pass


def get_patient_or_404(db: Session, patient_id: int) -> Patient:
    patient = db.get(Patient, patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy bệnh nhân.")
    return patient


@app.get("/api/v1/icd10", tags=["Danh mục ICD-10"])
def search_icd10(q: str = Query(..., min_length=2, max_length=100), db: Session = Depends(get_db)):
    """Search the Vietnamese ICD-10 catalog by code or diagnosis name."""
    term = q.strip()
    if len(term) < 2:
        return []
    rows = (
        db.query(Icd10Code)
        .filter(or_(Icd10Code.code.ilike(f"%{term}%"), Icd10Code.name_vi.ilike(f"%{term}%")))
        .order_by(Icd10Code.code)
        .limit(20)
        .all()
    )
    return [{"code": row.code, "name_vi": row.name_vi} for row in rows]


@app.get("/api/v1/dashboard-summary", tags=["Tổng quan"])
def dashboard_summary(db: Session = Depends(get_db)):
    """Lightweight counters and recent campaigns for the home dashboard."""
    campaign_patient_counts = (
        db.query(
            ExamCampaign.campaign_id,
            ExamCampaign.campaign_name,
            ExamCampaign.start_date,
            ExamCampaign.end_date,
            Company.name.label("company_name"),
            Company.mst.label("mst"),
            func.count(PatientExamCampaign.patient_exam_campaign_id).label("patient_count"),
        )
        .join(Company, Company.company_id == ExamCampaign.company_id)
        .outerjoin(PatientExamCampaign, PatientExamCampaign.campaign_id == ExamCampaign.campaign_id)
        .group_by(ExamCampaign.campaign_id, ExamCampaign.campaign_name, ExamCampaign.start_date, ExamCampaign.end_date, Company.name, Company.mst)
        .order_by(ExamCampaign.start_date.desc(), ExamCampaign.campaign_id.desc())
        .limit(100)
        .all()
    )
    return {
        "companies": db.query(Company).count(),
        "campaigns": db.query(ExamCampaign).count(),
        "patients": db.query(Patient).count(),
        "exams": db.query(HealthExam).count(),
        "recent_campaigns": [
            {
                "campaign_id": row.campaign_id,
                "campaign_name": row.campaign_name,
                "company_name": row.company_name,
                "mst": row.mst,
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat() if row.end_date else None,
                "patient_count": row.patient_count,
            }
            for row in campaign_patient_counts
        ],
    }


def delete_patient_records(db: Session, patient: Patient) -> None:
    """Delete a patient and their dependent exam records in one transaction."""
    exam_ids = [exam_id for (exam_id,) in db.query(HealthExam.exam_id).filter(HealthExam.patient_id == patient.patient_id).all()]
    if exam_ids:
        delete_exam_records(db, exam_ids)
    db.query(PatientExamCampaign).filter(PatientExamCampaign.patient_id == patient.patient_id).delete(synchronize_session=False)
    db.delete(patient)


def delete_exam_records(db: Session, exam_ids: list[int]) -> None:
    """Delete dependent data for the given examination records before deleting them."""
    if not exam_ids:
        return
    # Older deployments may not have the optional linkage-batch tables yet.
    # Do not make ordinary patient/exam deletion depend on that migration.
    if inspect(db.get_bind()).has_table("LienThongBatchItem"):
        db.query(LienThongBatchItem).filter(LienThongBatchItem.exam_id.in_(exam_ids)).delete(synchronize_session=False)
    db.query(ExamFamilyHistory).filter(ExamFamilyHistory.exam_id.in_(exam_ids)).delete(synchronize_session=False)
    db.query(ExamPersonalHistory).filter(ExamPersonalHistory.exam_id.in_(exam_ids)).delete(synchronize_session=False)
    db.query(ExamAdditionalHistory).filter(ExamAdditionalHistory.exam_id.in_(exam_ids)).delete(synchronize_session=False)
    db.query(ExamClinicalResult).filter(ExamClinicalResult.exam_id.in_(exam_ids)).delete(synchronize_session=False)
    db.query(ExamParaclinicalResult).filter(ExamParaclinicalResult.exam_id.in_(exam_ids)).delete(synchronize_session=False)
    db.query(ExamKskFieldValue).filter(ExamKskFieldValue.exam_id.in_(exam_ids)).delete(synchronize_session=False)
    db.query(HealthExam).filter(HealthExam.exam_id.in_(exam_ids)).delete(synchronize_session=False)


def get_exam_or_404(db: Session, exam_id: int, detailed: bool = False) -> HealthExam:
    query = db.query(HealthExam).filter(HealthExam.exam_id == exam_id)
    if detailed:
        query = query.options(
            selectinload(HealthExam.patient), selectinload(HealthExam.family_history),
            selectinload(HealthExam.additional_history), selectinload(HealthExam.personal_histories),
            selectinload(HealthExam.clinical_results), selectinload(HealthExam.paraclinical_results),
            selectinload(HealthExam.facility), selectinload(HealthExam.ksk_field_values),
        )
    exam = query.first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy lần khám.")
    return exam


def commit_or_conflict(db: Session, message: str = "Dữ liệu bị trùng hoặc không hợp lệ."):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail=message)


def make_exam_code(exam: HealthExam) -> str:
    """Return the non-sensitive MaHS used in Code 128 barcodes."""
    year = (exam.exam_date or datetime.now()).year
    campaign_id = exam.campaign_id or 0
    return f"KSK-{year}-{campaign_id:05d}-{exam.exam_id:08d}"


def get_company_or_404(db: Session, company_id: int) -> Company:
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn vị.")
    return company


def get_exam_campaign_or_404(db: Session, campaign_id: int) -> ExamCampaign:
    campaign = db.get(ExamCampaign, campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Không tìm thấy đợt khám.")
    return campaign


def validate_campaign_dates(start_date: date, end_date: date | None) -> None:
    if end_date and end_date < start_date:
        raise HTTPException(status_code=422, detail="Ngày kết thúc không được trước ngày bắt đầu.")


def get_facility_or_404(db: Session, facility_id: int) -> KskFacilityProfile:
    facility = db.get(KskFacilityProfile, facility_id)
    if not facility:
        raise HTTPException(status_code=404, detail="Không tìm thấy cơ sở KCB liên thông.")
    return facility


def _as_text(value) -> str | None:
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


def _adult_form_code(exam: HealthExam) -> str:
    """This project currently implements the >=18 form defined by QD 2062."""
    patient = exam.patient
    if not patient.date_of_birth:
        return "ADULT"
    exam_day = exam.exam_date.date() if isinstance(exam.exam_date, datetime) else date.today()
    age = exam_day.year - patient.date_of_birth.year - ((exam_day.month, exam_day.day) < (patient.date_of_birth.month, patient.date_of_birth.day))
    return "ADULT" if age >= 18 else "UNSUPPORTED"


def _standard_values(exam: HealthExam) -> dict[str, str | None]:
    patient = exam.patient
    facility = exam.facility
    address = ", ".join(part for part in [patient.address_detail, patient.ward, patient.province] if _as_text(part))
    values = {
        "HO_TEN": patient.full_name,
        "GIOI_TINH": _as_text(patient.gender),
        "NGAY_SINH": patient.date_of_birth.strftime("%Y%m%d") if patient.date_of_birth else None,
        "MA_DAN_TOC": patient.ethnicity_code,
        "SO_CCCD": patient.identity_number,
        "NGAYCAP_CCCD": patient.identity_issue_date.strftime("%Y%m%d") if patient.identity_issue_date else None,
        "NOICAP_CCCD": patient.identity_issue_place,
        "DIA_CHI": address or None,
        "MATINH_CU_TRU": patient.province_code,
        "MAXA_CU_TRU": patient.ward_code,
        "MA_NGHE_NGHIEP": patient.occupation_code,
        "NOI_LAM_VIEC_HOC_TAP": patient.workplace,
        "DIEN_THOAI": patient.phone,
        "NHOM_MAU": patient.blood_group,
        "LY_DO_VV": exam.exam_reason,
        "MA_LK": exam.visit_code,
        "MA_CSKCB": (facility.facility_code if facility else None) or settings.lien_thong_facility_code,
        "MA_GTIN_CSKCB": (facility.gln_code if facility else None) or settings.lien_thong_facility_gln,
        "DOI_TUONG": exam.subject_codes,
        "NGUON_CHI_TRA": _as_text(exam.payment_source_code),
        "MA_LOAI_KCB": exam.exam_type_code or settings.lien_thong_exam_type_code,
        "NGAY_VAO": exam.exam_date.strftime("%Y%m%d") if exam.exam_date else None,
        "CHIEU_CAO": _as_text(exam.height_cm),
        "CAN_NANG": _as_text(exam.weight_kg),
        "CHI_SO_BMI": _as_text(exam.bmi),
        "MACH": _as_text(exam.pulse_per_minute),
        "HUYET_AP": exam.blood_pressure,
        "KHAM_THE_LUC_PL": exam.physical_classification,
        "PHAN_LOAI_SK": exam.health_classification,
        "KET_LUAN_BENH": exam.conclusion_disease_codes,
        "CAC_BENH_TAT_NEU_CO": exam.health_status,
        "CKS_NGUOI_KET_LUAN": settings.lien_thong_conclusion_signature_base64,
        "CKS_BENH_VIEN": settings.lien_thong_facility_signature_base64,
    }
    history_codes = (
        "TSBT_BENH_TRONG_5_NAM_QUA", "TSBT_BENH_THAN_KINH", "TSBT_BENH_MAT", "TSBT_BENH_TAI",
        "TSBT_BENH_TIM", "TSBT_PHAU_THUAT_TIM", "TSBT_TANG_HUYET_AP", "TSBT_KHO_THO",
        "TSBT_BENH_PHOI", "TSBT_BENH_THAN", "TSBT_NGHIEN_RUOU", "TSBT_DAI_THAO_DUONG",
        "TSBT_BENH_TAM_THAN", "TSBT_MAT_Y_THUC", "TSBT_NGAT", "TSBT_BENH_TIEU_HOA",
        "TSBT_ROI_LOAN_GIAC_NGU", "TSBT_TAI_BIEN", "TSBT_BENH_COT_SONG", "TSBT_RUOU_THUONG_XUYEN",
        "TSBT_MA_TUY", "TSBT_BENH_KHAC",
    )
    for item in exam.personal_histories:
        try:
            history_index = int(item.history_code[1:]) - 1
        except (TypeError, ValueError):
            continue
        if item.history_code.startswith("H") and 0 <= history_index < len(history_codes) and item.has_condition is not None:
            values[history_codes[history_index]] = "1" if item.has_condition else "0"
    if exam.family_history:
        values["TSGD_MAC_BENH"] = "1" if exam.family_history.has_history else "0"
    if exam.additional_history:
        treatment = _as_text(exam.additional_history.current_treatment)
        if treatment:
            values["TSBT_DANG_DIEU_TRI_BENH"] = "0" if treatment.casefold().startswith("không") else "1"
            if values["TSBT_DANG_DIEU_TRI_BENH"] == "1":
                values["TSBT_TEN_THUOC_LIEU_LUONG"] = treatment
        obstetric = _as_text(exam.additional_history.obstetric_history)
        if obstetric:
            values["TSBT_THAI_SAN"] = "0" if obstetric.casefold().startswith("không") else "1"
    values.update({item.field_code: item.field_value for item in exam.ksk_field_values if item.field_value and item.field_value.strip()})
    return {key: _as_text(value) for key, value in values.items()}


def get_linkage_readiness(exam: HealthExam, db: Session) -> LinkageReadiness:
    form_code = _adult_form_code(exam)
    errors: list[LinkageValidationIssue] = []
    warnings: list[LinkageValidationIssue] = []
    if form_code == "UNSUPPORTED":
        errors.append(LinkageValidationIssue(field_code="FORM_CODE", field_name="Mẫu XML", message="Lần khám thuộc người dưới 18 tuổi; API hiện chỉ chuẩn hóa mẫu ADULT (từ đủ 18 tuổi)."))
        return LinkageReadiness(exam_id=exam.exam_id, form_code=form_code, ready=False, errors=errors, warnings=warnings)

    definitions = db.query(KskXmlFieldDefinition).filter(
        KskXmlFieldDefinition.form_code == form_code,
        KskXmlFieldDefinition.is_active == True,  # noqa: E712 - SQL Server Native Client requires "= 1", not "IS 1".
        KskXmlFieldDefinition.is_required == True,  # noqa: E712
    ).order_by(KskXmlFieldDefinition.display_order).all()
    if not definitions:
        errors.append(LinkageValidationIssue(field_code="MIGRATION", field_name="Cấu hình XML", message="Chưa có danh mục trường XML ADULT. Hãy chạy deploy_ksk_lienthong_2062.sql."))
        return LinkageReadiness(exam_id=exam.exam_id, form_code=form_code, ready=False, errors=errors, warnings=warnings)

    values = _standard_values(exam)
    # FieldName is descriptive metadata that may have been inserted from a
    # legacy SQL script using the machine's ANSI code page. Use canonical
    # Unicode labels keyed by stable field codes for user-facing validation.
    canonical_field_names = {
        "MA_DAN_TOC": "Mã dân tộc",
        "MATINH_CU_TRU": "Mã tỉnh cư trú",
        "MAXA_CU_TRU": "Mã xã cư trú",
        "MA_NGHE_NGHIEP": "Mã nghề nghiệp",
        "MA_CSKCB": "Mã cơ sở khám bệnh, chữa bệnh",
        "MA_GTIN_CSKCB": "Mã GLN cơ sở khám bệnh, chữa bệnh",
        "DOI_TUONG": "Đối tượng khám",
        "NGUON_CHI_TRA": "Nguồn chi trả",
        "MA_LOAI_KCB": "Mã loại hình khám bệnh, chữa bệnh",
        "CKS_NGUOI_KET_LUAN": "Chữ ký số người kết luận",
        "CKS_BENH_VIEN": "Chữ ký số cơ sở khám bệnh, chữa bệnh",
    }
    for definition in definitions:
        field_name = canonical_field_names.get(definition.field_code, definition.field_name)
        value = values.get(definition.field_code)
        if not value:
            errors.append(LinkageValidationIssue(field_code=definition.field_code, field_name=field_name, message="Thiếu trường bắt buộc theo QĐ 2062/QĐ-BYT."))
        elif definition.max_length and len(value) > definition.max_length:
            errors.append(LinkageValidationIssue(field_code=definition.field_code, field_name=field_name, message=f"Vượt quá độ dài tối đa {definition.max_length}."))

    if exam.status != "Completed":
        errors.append(LinkageValidationIssue(field_code="STATUS", field_name="Trạng thái lần khám", message="Cần hoàn tất lần khám (Completed) trước khi sinh XML liên thông."))
    if values.get("GIOI_TINH") and values.get("GIOI_TINH") not in {"1", "2"}:
        errors.append(LinkageValidationIssue(field_code="GIOI_TINH", field_name="Giới tính", message="Chỉ chấp nhận mã 1 (nam) hoặc 2 (nữ)."))
    if values.get("NGUON_CHI_TRA") and values.get("NGUON_CHI_TRA") not in {"1", "2", "3", "4", "5", "9"}:
        errors.append(LinkageValidationIssue(field_code="NGUON_CHI_TRA", field_name="Nguồn chi trả", message="Phải là một trong các mã 1, 2, 3, 4, 5 hoặc 9."))
    if values.get("PHAN_LOAI_SK") and values.get("PHAN_LOAI_SK") not in {"1", "2", "3", "4", "5"}:
        errors.append(LinkageValidationIssue(field_code="PHAN_LOAI_SK", field_name="Phân loại sức khỏe", message="Phải là mã loại sức khỏe 1 đến 5."))
    if exam.conclusion_disease_codes and any(not chunk.strip() for chunk in exam.conclusion_disease_codes.split(";")):
        warnings.append(LinkageValidationIssue(field_code="KET_LUAN_BENH", field_name="Kết luận bệnh", message="Chuẩn hóa nhiều mã ICD-10 bằng dấu chấm phẩy, không để phần tử rỗng."))
    if not exam.clinical_results:
        warnings.append(LinkageValidationIssue(field_code="CLINICAL_RESULTS", field_name="Khám lâm sàng", message="Chưa có chi tiết khám lâm sàng."))
    if not exam.paraclinical_results:
        warnings.append(LinkageValidationIssue(field_code="PARACLINICAL_RESULTS", field_name="Khám cận lâm sàng", message="Chưa có chỉ số cận lâm sàng; chỉ phù hợp nếu không có chỉ định."))
    return LinkageReadiness(exam_id=exam.exam_id, form_code=form_code, ready=not errors, errors=errors, warnings=warnings)


def build_exam_xml_preview(exam: HealthExam) -> tuple[str, list[str]]:
    """Create an unsigned XML preview using the adult-form groups and field codes in QD 2062."""
    values = _standard_values(exam)
    root = ET.Element("TREN_18")
    missing_fields: list[str] = []
    warnings = [
        "XML theo nhóm trường ADULT của Phụ lục 01/02 QĐ 2062; đây là bản xem trước chưa ký số.",
    ]

    def add_fields(parent: ET.Element, fields: tuple[str, ...]) -> None:
        """Emit the standard field tags in order, including empty optional fields."""
        for code in fields:
            value = values.get(code)
            ET.SubElement(parent, code).text = value or ""
            if not value:
                missing_fields.append(code)

    def add_group(parent: ET.Element, tag: str, fields: tuple[str, ...]) -> ET.Element:
        group = ET.SubElement(parent, tag)
        add_fields(group, fields)
        return group

    add_group(root, "THONG_TIN_HANH_CHINH", (
        "HO_TEN", "GIOI_TINH", "NGAY_SINH", "MA_DAN_TOC", "SO_CCCD", "NGAYCAP_CCCD",
        "NOICAP_CCCD", "DIA_CHI", "MATINH_CU_TRU", "MAXA_CU_TRU", "MA_NGHE_NGHIEP",
        "NOI_LAM_VIEC_HOC_TAP", "DIEN_THOAI", "NHOM_MAU", "LY_DO_VV",
    ))
    common = add_group(root, "THONG_TIN_CHUNG_VE_LAN_KHAM", (
        "MA_LK", "MA_CSKCB", "MA_GTIN_CSKCB", "DOI_TUONG", "NGUON_CHI_TRA", "MA_LOAI_KCB", "NGAY_VAO",
    ))
    if not values.get("MA_LK"):
        common.find("MA_LK").text = exam.exam_code

    history = ET.SubElement(root, "TIEN_SU_BENH_TAT")
    add_group(history, "TIEN_SU_GIA_DINH", ("TSGD_MAC_BENH", "TSGD_MA_BENH"))
    personal_history = ET.SubElement(history, "TIEN_SU_BAN_THAN")
    personal_codes = (
        "TSBT_BENH_TRONG_5_NAM_QUA", "TSBT_BENH_THAN_KINH", "TSBT_BENH_MAT", "TSBT_BENH_TAI",
        "TSBT_BENH_TIM", "TSBT_PHAU_THUAT_TIM", "TSBT_TANG_HUYET_AP", "TSBT_KHO_THO",
        "TSBT_BENH_PHOI", "TSBT_BENH_THAN", "TSBT_NGHIEN_RUOU", "TSBT_DAI_THAO_DUONG",
        "TSBT_BENH_TAM_THAN", "TSBT_MAT_Y_THUC", "TSBT_NGAT", "TSBT_BENH_TIEU_HOA",
        "TSBT_ROI_LOAN_GIAC_NGU", "TSBT_TAI_BIEN", "TSBT_BENH_COT_SONG", "TSBT_RUOU_THUONG_XUYEN",
        "TSBT_MA_TUY", "TSBT_BENH_KHAC", "TSBT_MA_BENH_KHAC", "TSBT_DANG_DIEU_TRI_BENH",
        "TSBT_MA_BENH", "TSBT_TEN_THUOC_LIEU_LUONG", "TSBT_THAI_SAN", "TSBT_MA_BENH_THAI_SAN",
        "TSBT_TEN_THUOC_THAI_SAN",
    )
    add_fields(personal_history, personal_codes)

    add_group(root, "KHAM_THE_LUC", ("CHIEU_CAO", "CAN_NANG", "CHI_SO_BMI", "MACH", "HUYET_AP", "KHAM_THE_LUC_PL"))

    clinical_root = ET.SubElement(root, "KHAM_LAM_SANG")
    clinical_by_code = {item.examination_code: item for item in exam.clinical_results}
    group_codes = {
        "NOI_KHOA": (
            "NOI_KHOA_TUAN_HOAN", "NOI_KHOA_TUAN_HOAN_PL", "CKDT_NOI_KHOA_TUAN_HOAN",
            "NOI_KHOA_HO_HAP", "NOI_KHOA_HO_HAP_PL", "CKDT_NOI_KHOA_HO_HAP",
            "NOI_KHOA_TIEU_HOA", "NOI_KHOA_TIEU_HOA_PL", "CKDT_NOI_KHOA_TIEU_HOA",
            "NOI_KHOA_THAN_TN_SD", "NOI_KHOA_THAN_TN_SD_PL", "CKDT_NOI_KHOA_THAN_TN_SD",
            "NOI_KHOA_NOI_TIET", "NOI_KHOA_NOI_TIET_PL", "CKDT_NOI_KHOA_NOI_TIET",
            "NOI_KHOA_CO_XUONG_KHOP", "NOI_KHOA_CO_XUONG_KHOP_PL", "CKDT_NOI_KHOA_CO_XUONG_KHOP",
            "NOI_KHOA_THAN_KINH", "NOI_KHOA_THAN_KINH_PL", "CKDT_NOI_KHOA_THAN_KINH",
            "NOI_KHOA_TAM_THAN", "NOI_KHOA_TAM_THAN_PL", "CKDT_NOI_KHOA_TAM_THAN",
        ),
        "NGOAI_KHOA_DA_LIEU": (
            "KET_QUA_KHAM_NGOAI_KHOA", "KHAM_NGOAI_KHOA_PL", "CKDT_KHAM_NGOAI_KHOA",
            "KET_QUA_KHAM_DA_LIEU", "KHAM_DA_LIEU_PL", "CKDT_KHAM_DA_LIEU",
        ),
        "SAN_PHU_KHOA": ("KET_QUA_KHAM_SAN_PHU_KHOA", "KHAM_SAN_PHU_KHOA_PL", "CKDT_KHAM_SAN_PHU_KHOA"),
        "MAT": ("KHONG_KINH_MAT_PHAI", "KHONG_KINH_MAT_TRAI", "CO_KINH_MAT_PHAI", "CO_KINH_MAT_TRAI", "BENH_KHAC_MAT", "KHAM_MAT_PL", "CKDT_KHAM_MAT"),
        "TAI_MUI_HONG": ("TAI_TRAI_NOI_THUONG", "TAI_TRAI_NOI_THAM", "TAI_PHAI_NOI_THUONG", "TAI_PHAI_NOI_THAM", "BENH_TAI_MUI_HONG", "KHAM_TAI_MUI_HONG_PL", "CKDT_KHAM_TAI_MUI_HONG"),
        "RANG_HAM_MAT": ("HAM_TREN", "HAM_DUOI", "BENH_RANG_HAM_MAT", "KHAM_RANG_HAM_MAT_PL", "CKDT_KHAM_RANG_HAM_MAT"),
    }
    clinical_field_map = {
        "INTERNAL_CIRCULATION": ("NOI_KHOA_TUAN_HOAN", "NOI_KHOA_TUAN_HOAN_PL", "CKDT_NOI_KHOA_TUAN_HOAN"),
        "INTERNAL_RESPIRATORY": ("NOI_KHOA_HO_HAP", "NOI_KHOA_HO_HAP_PL", "CKDT_NOI_KHOA_HO_HAP"),
        "INTERNAL_DIGESTIVE": ("NOI_KHOA_TIEU_HOA", "NOI_KHOA_TIEU_HOA_PL", "CKDT_NOI_KHOA_TIEU_HOA"),
        "INTERNAL_UROGENITAL": ("NOI_KHOA_THAN_TN_SD", "NOI_KHOA_THAN_TN_SD_PL", "CKDT_NOI_KHOA_THAN_TN_SD"),
        "INTERNAL_ENDOCRINE": ("NOI_KHOA_NOI_TIET", "NOI_KHOA_NOI_TIET_PL", "CKDT_NOI_KHOA_NOI_TIET"),
        "INTERNAL_MUSCULOSKELETAL": ("NOI_KHOA_CO_XUONG_KHOP", "NOI_KHOA_CO_XUONG_KHOP_PL", "CKDT_NOI_KHOA_CO_XUONG_KHOP"),
        "INTERNAL_NEUROLOGY": ("NOI_KHOA_THAN_KINH", "NOI_KHOA_THAN_KINH_PL", "CKDT_NOI_KHOA_THAN_KINH"),
        "INTERNAL_PSYCHIATRY": ("NOI_KHOA_TAM_THAN", "NOI_KHOA_TAM_THAN_PL", "CKDT_NOI_KHOA_TAM_THAN"),
        "SURGERY": ("KET_QUA_KHAM_NGOAI_KHOA", "KHAM_NGOAI_KHOA_PL", "CKDT_KHAM_NGOAI_KHOA"),
        "DERMATOLOGY": ("KET_QUA_KHAM_DA_LIEU", "KHAM_DA_LIEU_PL", "CKDT_KHAM_DA_LIEU"),
        "OBSTETRICS": ("KET_QUA_KHAM_SAN_PHU_KHOA", "KHAM_SAN_PHU_KHOA_PL", "CKDT_KHAM_SAN_PHU_KHOA"),
    }
    for group_name, codes in group_codes.items():
        group = ET.SubElement(clinical_root, group_name)
        for code in codes:
            ET.SubElement(group, code).text = values.get(code) or ""
    for examination_code, item in clinical_by_code.items():
        mapping = clinical_field_map.get(examination_code)
        if not mapping:
            continue
        result_code, classification_code, _signature_code = mapping
        target = root.find(f".//{result_code}")
        if target is not None and item.result_detail and not values.get(result_code):
            target.text = item.result_detail
        if item.classification and not values.get(classification_code):
            class_target = root.find(f".//{classification_code}")
            if class_target is not None:
                class_target.text = item.classification

    for code, labels in {
        "EYE": {"Thị lực không kính": ("KHONG_KINH_MAT_PHAI", "KHONG_KINH_MAT_TRAI"), "Thị lực có kính": ("CO_KINH_MAT_PHAI", "CO_KINH_MAT_TRAI"), "Bệnh mắt": ("BENH_KHAC_MAT",)},
        "ENT": {"Thính lực tai trái": ("TAI_TRAI_NOI_THUONG", "TAI_TRAI_NOI_THAM"), "Thính lực tai phải": ("TAI_PHAI_NOI_THUONG", "TAI_PHAI_NOI_THAM"), "Bệnh Tai-Mũi-Họng": ("BENH_TAI_MUI_HONG",)},
        "DENTAL": {"Hàm trên": ("HAM_TREN",), "Hàm dưới": ("HAM_DUOI",), "Bệnh Răng-Hàm-Mặt": ("BENH_RANG_HAM_MAT",)},
    }.items():
        item = clinical_by_code.get(code)
        if not item or not item.result_detail:
            continue
        for line in item.result_detail.splitlines():
            label, separator, text = line.partition(": ")
            targets = labels.get(label) if separator else None
            if not targets:
                continue
            parts = text.split(" / ") if len(targets) == 2 else [text]
            for target_code, target_value in zip(targets, parts):
                node = root.find(f".//{target_code}")
                if node is not None and not values.get(target_code):
                    node.text = target_value

    if exam.clinical_results:
        warnings.append("Chữ ký điện tử bác sĩ khám chuyên khoa (CKDT_*) chỉ được điền khi đã lưu chữ ký đúng định dạng trường tương ứng.")
    else:
        warnings.append("Hồ sơ chưa có kết quả khám lâm sàng.")

    for result in exam.paraclinical_results:
        paraclinical = ET.SubElement(root, "KHAM_CAN_LAM_SANG")
        for code in ("MA_DICH_VU", "MA_CHI_SO", "GIA_TRI", "DON_VI_DO", "MO_TA", "KET_LUAN", "CKDT_KET_QUA_CLS"):
            node = ET.SubElement(paraclinical, code)
            direct_value = values.get(code) if len(exam.paraclinical_results) == 1 else None
            if code in {"MA_DICH_VU", "MA_CHI_SO"}:
                # Internal application IDs/names are not automatically promoted to official codes.
                node.text = direct_value or ""
            elif code == "GIA_TRI":
                node.text = direct_value or result.result_value or ""
            elif code == "DON_VI_DO":
                node.text = direct_value or result.unit or ""
            elif code == "MO_TA":
                description = "; ".join(part for part in [result.test_name, result.reference_range] if part)
                node.text = direct_value or description
            elif code == "KET_LUAN":
                node.text = direct_value or ""
            else:
                node.text = direct_value or ""
    if not exam.paraclinical_results:
        warnings.append("Hồ sơ chưa có kết quả cận lâm sàng; nhóm KHAM_CAN_LAM_SANG không được tạo.")
    elif len(exam.paraclinical_results) > 1 or not (values.get("MA_DICH_VU") and values.get("MA_CHI_SO")):
        warnings.append("Các mục cận lâm sàng chưa có mã dịch vụ/mã chỉ số chuẩn theo Quyết định 3176/QĐ-BYT; mã nội bộ không được xuất thay cho mã chuẩn.")
    if exam.family_history and exam.family_history.detail and not values.get("TSGD_MA_BENH"):
        warnings.append("Chi tiết tiền sử gia đình là văn bản tự do nên không tự đưa vào TSGD_MA_BENH; trường chuẩn yêu cầu mã ICD-10.")
    if exam.additional_history and exam.additional_history.obstetric_history and not values.get("TSBT_MA_BENH_THAI_SAN"):
        warnings.append("Chi tiết tiền sử thai sản là văn bản tự do nên không tự đưa vào TSBT_MA_BENH_THAI_SAN; trường chuẩn yêu cầu mã ICD-10.")

    add_group(root, "KET_LUAN", (
        "PHAN_LOAI_SK", "KET_LUAN_BENH", "CAC_BENH_TAT_NEU_CO", "CKS_NGUOI_KET_LUAN", "CKS_BENH_VIEN",
    ))
    classification_fields = ("KHAM_THE_LUC_PL", "NOI_KHOA_TUAN_HOAN_PL", "NOI_KHOA_HO_HAP_PL", "NOI_KHOA_TIEU_HOA_PL", "NOI_KHOA_THAN_TN_SD_PL", "NOI_KHOA_NOI_TIET_PL", "NOI_KHOA_CO_XUONG_KHOP_PL", "NOI_KHOA_THAN_KINH_PL", "NOI_KHOA_TAM_THAN_PL", "KHAM_NGOAI_KHOA_PL", "KHAM_DA_LIEU_PL", "KHAM_SAN_PHU_KHOA_PL", "KHAM_MAT_PL", "KHAM_TAI_MUI_HONG_PL", "KHAM_RANG_HAM_MAT_PL", "PHAN_LOAI_SK")
    invalid_classifications = []
    for code in classification_fields:
        node = root.find(f".//{code}")
        if node is not None and node.text and node.text not in {"1", "2", "3", "4", "5"}:
            invalid_classifications.append(code)
    if invalid_classifications:
        warnings.append("Các trường phân loại phải gửi mã số 1–5; cần chuẩn hóa: " + ", ".join(invalid_classifications) + ".")
    if missing_fields:
        unique_missing = list(dict.fromkeys(missing_fields))
        warnings.append(f"{len(unique_missing)} trường chưa có dữ liệu và để trống trong XML; kiểm tra các tab hồ sơ trước khi ký/gửi.")
    ET.indent(root, space="  ")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode")
    return xml, warnings


@app.get("/", tags=["Hệ thống"])
def root():
    return {"name": settings.app_name, "docs": "/docs", "openapi": "/openapi.json"}


@app.get("/health", tags=["Hệ thống"])
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok", "database": settings.sql_database}


@app.get("/api/v1/administrative/provinces", response_model=list[AdministrativeProvinceRead], tags=["Danh mục hành chính"])
def list_administrative_provinces(db: Session = Depends(get_db)):
    return (db.query(AdministrativeProvince)
            .filter(AdministrativeProvince.is_active == True)  # noqa: E712
            .order_by(AdministrativeProvince.province_name)
            .all())


@app.get("/api/v1/administrative/provinces/{province_code}/wards", response_model=list[AdministrativeWardRead], tags=["Danh mục hành chính"])
def list_administrative_wards(province_code: str, db: Session = Depends(get_db)):
    if not db.get(AdministrativeProvince, province_code):
        raise HTTPException(status_code=404, detail="Không tìm thấy tỉnh/thành theo mã.")
    return (db.query(AdministrativeWard)
            .filter(AdministrativeWard.province_code == province_code, AdministrativeWard.is_active == True)  # noqa: E712
            .order_by(AdministrativeWard.ward_name)
            .all())


def normalize_patient_address(data: dict, db: Session) -> None:
    province_code = (data.get("province_code") or "").strip()
    ward_code = (data.get("ward_code") or "").strip()
    if ward_code and not province_code:
        raise HTTPException(status_code=422, detail="Cần chọn tỉnh/thành trước khi chọn phường/xã.")
    if province_code:
        province = db.get(AdministrativeProvince, province_code)
        if not province or not province.is_active:
            raise HTTPException(status_code=422, detail="Mã tỉnh/thành không có trong danh mục hiện hành.")
        data["province_code"] = province.province_code
        data["province"] = province.province_name
    if ward_code:
        ward = db.get(AdministrativeWard, ward_code)
        if not ward or not ward.is_active or ward.province_code != province_code:
            raise HTTPException(status_code=422, detail="Phường/xã không thuộc tỉnh/thành đã chọn.")
        data["ward_code"] = ward.ward_code
        data["ward"] = ward.ward_name


@app.post("/api/v1/patients", response_model=PatientRead, status_code=status.HTTP_201_CREATED, tags=["Bệnh nhân"])
def create_patient(payload: PatientCreate, db: Session = Depends(get_db)):
    # CreatedAt has a SQL default, but assign it explicitly for compatibility
    # with SQL Server/pyodbc when this mapped legacy table has no ORM default.
    data = payload.model_dump()
    normalize_patient_address(data, db)
    patient = Patient(**data, created_at=datetime.now())
    db.add(patient)
    commit_or_conflict(db, "Số CCCD/Hộ chiếu đã tồn tại.")
    db.refresh(patient)
    return patient


def allocate_campaign_shs(db: Session, campaign_id: int) -> str:
    """Allocate the next numeric SHS within one campaign, with SQL Server locks."""
    next_shs = db.execute(text("""
        SELECT ISNULL(MAX(TRY_CONVERT(BIGINT, p.SHS)), 0) + 1
        FROM dbo.Patients AS p WITH (UPDLOCK, HOLDLOCK)
        INNER JOIN dbo.PatientExamCampaigns AS pec WITH (UPDLOCK, HOLDLOCK)
            ON pec.PatientId = p.PatientId
        WHERE pec.CampaignId = :campaign_id
    """), {"campaign_id": campaign_id}).scalar_one()
    return str(next_shs)


@app.post("/api/v1/patients/new-for-campaign", response_model=PatientRead, status_code=status.HTTP_201_CREATED, tags=["Bệnh nhân"])
def create_patient_for_campaign(payload: PatientCreateForCampaign, db: Session = Depends(get_db)):
    """Create a patient and link it to one campaign in the same transaction.

    The company MST is derived from the selected campaign, never trusted from
    the browser. This supports SHS=0 as the new-patient marker in the form.
    """
    campaign = get_exam_campaign_or_404(db, payload.campaign_id)
    company = get_company_or_404(db, campaign.company_id)
    data = payload.model_dump(exclude={"campaign_id"})
    # SHS is scoped to the selected campaign. A new campaign starts at 1.
    data["shs"] = allocate_campaign_shs(db, campaign.campaign_id)
    data["mst"] = company.mst
    normalize_patient_address(data, db)
    patient = Patient(**data, created_at=datetime.now())
    db.add(patient)
    try:
        db.flush()
        db.add(PatientExamCampaign(
            patient_id=patient.patient_id,
            campaign_id=campaign.campaign_id,
            imported_at=datetime.now(),
            created_at=datetime.now(),
        ))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Số CCCD/Hộ chiếu đã tồn tại hoặc không thể gán bệnh nhân vào đợt khám.")
    db.refresh(patient)
    return patient


@app.post("/api/v1/patients/import", response_model=PatientBulkImportResult, status_code=status.HTTP_201_CREATED, tags=["Bệnh nhân"])
def import_patients(payload: PatientBulkImport, db: Session = Depends(get_db)):
    """Nhập bệnh nhân và gán họ vào một đợt khám thuộc đơn vị đã chọn."""
    company = get_company_or_404(db, payload.company_id)
    campaign = get_exam_campaign_or_404(db, payload.campaign_id)
    if campaign.company_id != company.company_id:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")

    inserted, linked, skipped, issues = 0, 0, 0, []
    if payload.replace_campaign:
        # Keep master patient records (they may be linked to other campaigns), but
        # atomically replace this campaign's membership and all of its exam data.
        exam_ids = [exam_id for (exam_id,) in db.query(HealthExam.exam_id).filter(
            HealthExam.campaign_id == campaign.campaign_id,
        ).all()]
        delete_exam_records(db, exam_ids)
        db.query(PatientExamCampaign).filter(
            PatientExamCampaign.campaign_id == campaign.campaign_id,
        ).delete(synchronize_session=False)

    for row_number, item in enumerate(payload.patients, start=1):
        try:
            with db.begin_nested():
                data = item.model_dump()
                # The server, not the browser, determines the company tax code.
                data["mst"] = company.mst
                normalize_patient_address(data, db)
                patient = None
                if data.get("identity_number"):
                    patient = db.query(Patient).filter(Patient.identity_number == data["identity_number"]).first()
                elif data.get("shs"):
                    patient = db.query(Patient).filter(Patient.shs == data["shs"], Patient.mst == company.mst).first()

                if patient and patient.mst and company.mst and patient.mst != company.mst:
                    raise ValueError("CCCD/định danh này đang thuộc một đơn vị khác.")
                if not patient:
                    patient = Patient(**data, created_at=datetime.now())
                    db.add(patient)
                    db.flush()
                    inserted += 1
                elif payload.replace_campaign:
                    # The workbook is the replacement source of truth for the
                    # administrative fields, including intentional blank values.
                    for field, value in data.items():
                        if field != "mst":
                            setattr(patient, field, value)
                    patient.mst = company.mst
                    patient.updated_at = datetime.now()

                association = db.query(PatientExamCampaign).filter(
                    PatientExamCampaign.patient_id == patient.patient_id,
                    PatientExamCampaign.campaign_id == campaign.campaign_id,
                ).first()
                if association:
                    skipped += 1
                else:
                    db.add(PatientExamCampaign(
                        patient_id=patient.patient_id,
                        campaign_id=campaign.campaign_id,
                        imported_at=datetime.now(),
                        created_at=datetime.now(),
                    ))
                    db.flush()
                    linked += 1
        except (IntegrityError, ValueError) as error:
            if isinstance(error, ValueError):
                message = str(error)
            else:
                error_text = str(error.orig).lower()
                message = "Số CCCD/Hộ chiếu đã tồn tại." if "identitynumber" in error_text or "ux_patients_identitynumber" in error_text else "Dữ liệu dòng không hợp lệ: " + str(error.orig)
            issues.append(PatientImportIssue(row_number=row_number, message=message))
    if payload.replace_campaign and issues:
        db.rollback()
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Có dòng dữ liệu không hợp lệ; chưa thay thế danh sách để giữ nguyên dữ liệu cũ.",
                "issues": [issue.model_dump() for issue in issues[:50]],
                "failed": len(issues),
            },
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Không thể hoàn tất nhập dữ liệu.")
    return PatientBulkImportResult(inserted=inserted, linked=linked, skipped=skipped, failed=len(issues), issues=issues)


@app.get("/api/v1/patients", response_model=list[PatientRead], tags=["Bệnh nhân"])
def list_patients(q: str | None = Query(default=None, max_length=100), mst: str | None = Query(default=None, max_length=30, description="Lọc theo mã số thuế đơn vị"), campaign_id: int | None = Query(default=None, gt=0, description="Lọc theo đợt khám"), limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
    query = db.query(Patient)
    if q:
        query = query.filter((Patient.full_name.contains(q)) | (Patient.identity_number.contains(q)) | (Patient.phone.contains(q)))
    if mst:
        query = query.filter(Patient.mst == mst)
    if campaign_id:
        query = query.join(PatientExamCampaign).filter(PatientExamCampaign.campaign_id == campaign_id).distinct()
    patients = query.limit(limit).all()

    # Sort SHS in Python so SQL Server does not reject an ORDER BY expression
    # together with DISTINCT on installations using older compatibility levels.
    def shs_sort_key(patient: Patient):
        raw = (patient.shs or "").strip()
        try:
            return (0, -int(raw), patient.patient_id)
        except (TypeError, ValueError):
            return (1, 0, patient.patient_id)

    return sorted(patients, key=shs_sort_key)


@app.get("/api/v1/patients/page", response_model=PatientPage, tags=["Bệnh nhân"])
def list_patients_page(
    q: str | None = Query(default=None, max_length=100),
    mst: str | None = Query(default=None, max_length=30),
    campaign_id: int | None = Query(default=None, gt=0),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """Return one page of patients in a campaign, ordered by SHS descending."""
    query = db.query(Patient)
    if q:
        query = query.filter(
            (Patient.full_name.contains(q))
            | (Patient.identity_number.contains(q))
            | (Patient.phone.contains(q))
        )
    if mst:
        query = query.filter(Patient.mst == mst)
    if campaign_id:
        campaign_patient_ids = db.query(PatientExamCampaign.patient_id).filter(
            PatientExamCampaign.campaign_id == campaign_id,
        )
        query = query.filter(Patient.patient_id.in_(campaign_patient_ids))

    total = query.count()
    shs_numeric = "TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), ''))"
    exam_date_query = db.query(HealthExam.exam_date).filter(
        HealthExam.patient_id == Patient.patient_id,
    )
    if campaign_id:
        exam_date_query = exam_date_query.filter(HealthExam.campaign_id == campaign_id)
    exam_date_value = (
        exam_date_query.order_by(HealthExam.exam_date.desc(), HealthExam.exam_id.desc())
        .limit(1)
        .correlate(Patient)
        .scalar_subquery()
        .label("exam_date")
    )
    patient_rows = (
        query.add_columns(exam_date_value)
        .order_by(
            text(f"CASE WHEN {shs_numeric} IS NULL THEN 1 ELSE 0 END ASC"),
            text(f"{shs_numeric} ASC"),
            Patient.patient_id.asc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    patients = []
    for patient, exam_date in patient_rows:
        patient.exam_date = exam_date
        patients.append(patient)
    return PatientPage(items=patients, total=total, page=page, page_size=page_size)


@app.get("/api/v1/patients/export.xlsx", tags=["Bệnh nhân"])
def export_patients_excel(mst: str = Query(..., max_length=30), campaign_id: int = Query(..., gt=0), db: Session = Depends(get_db)):
    """Export the selected campaign's patient list as a formatted Excel workbook."""
    company = db.query(Company).filter(Company.mst == mst).first()
    if not company:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn vị theo MST.")
    campaign = get_exam_campaign_or_404(db, campaign_id)
    if campaign.company_id != company.company_id:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")
    exam_date_value = (
        db.query(HealthExam.exam_date)
        .filter(
            HealthExam.patient_id == Patient.patient_id,
            HealthExam.campaign_id == campaign_id,
        )
        .order_by(HealthExam.exam_date.desc(), HealthExam.exam_id.desc())
        .limit(1)
        .correlate(Patient)
        .scalar_subquery()
        .label("exam_date")
    )
    patients = (db.query(Patient, exam_date_value)
                .join(PatientExamCampaign, PatientExamCampaign.patient_id == Patient.patient_id)
                .filter(PatientExamCampaign.campaign_id == campaign_id)
                .order_by(
                    text("CASE WHEN TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) IS NULL THEN 1 ELSE 0 END ASC"),
                    text("TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) ASC"),
                    Patient.shs.asc(),
                    Patient.patient_id.asc(),
                ).all())
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Danh sách KSK"
    sheet.merge_cells("A1:H1")
    sheet["A1"] = f"DANH SÁCH KHÁM SỨC KHỎE {company.name.upper()}"
    sheet["A1"].font = Font(name="Arial", size=14, bold=True)
    sheet["A1"].alignment = Alignment(horizontal="center")
    sheet.merge_cells("A2:H2")
    sheet["A2"] = f"Đợt khám: {campaign.campaign_name}    |    MST: {company.mst}"
    sheet["A2"].font = Font(name="Arial", size=10, italic=True)
    sheet["A2"].alignment = Alignment(horizontal="center")
    headers = ["STT", "HỌ VÀ TÊN", "GIỚI", "NGÀY SINH", "SỐ ĐT", "GHI CHÚ", "SHS", "NGÀY KHÁM"]
    for column, value in enumerate(headers, 1):
        cell = sheet.cell(row=4, column=column, value=value)
        cell.font = Font(name="Arial", size=11, bold=True)
        cell.fill = PatternFill("solid", fgColor="D9EAD3")
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    thin = Side(style="thin", color="808080")
    for row_index, (patient, exam_date) in enumerate(patients, 5):
        values = [row_index - 4, patient.full_name, "Nam" if patient.gender == 1 else "Nữ" if patient.gender == 2 else "", patient.date_of_birth, patient.phone or "", "", patient.shs or "", exam_date]
        for column, value in enumerate(values, 1):
            cell = sheet.cell(row=row_index, column=column, value=value)
            cell.font = Font(name="Arial", size=11)
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if column in (1, 3):
                cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        sheet.cell(row=row_index, column=4).number_format = "dd/mm/yyyy"
        sheet.cell(row=row_index, column=8).number_format = "dd/mm/yyyy"
    for row in sheet.iter_rows(min_row=4, max_row=max(4, len(patients) + 4), min_col=1, max_col=8):
        for cell in row:
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    widths = [8, 34, 12, 18, 18, 34, 14, 16]
    for index, width in enumerate(widths, 1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.row_dimensions[1].height = 25
    sheet.row_dimensions[4].height = 30
    sheet.freeze_panes = "A5"
    sheet.auto_filter.ref = f"A4:H{max(4, len(patients) + 4)}"
    output = BytesIO()
    workbook.save(output)
    filename = f"DanhSachKSK_{campaign.campaign_id}.xlsx"
    return Response(content=output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/v1/patients/import-template.xlsx", tags=["Bệnh nhân"])
def export_patient_import_template(mst: str = Query(..., max_length=30), campaign_id: int = Query(..., gt=0), db: Session = Depends(get_db)):
    """Export a multi-sheet workbook prefilled with patients in one campaign."""
    company = db.query(Company).filter(Company.mst == mst).first()
    if not company:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn vị theo MST.")
    campaign = get_exam_campaign_or_404(db, campaign_id)
    if campaign.company_id != company.company_id:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")

    patients = (db.query(Patient)
        .join(PatientExamCampaign, PatientExamCampaign.patient_id == Patient.patient_id)
        .filter(PatientExamCampaign.campaign_id == campaign_id)
        .order_by(
            text("CASE WHEN TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) IS NULL THEN 1 ELSE 0 END ASC"),
            text("TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) ASC"),
            Patient.patient_id.asc(),
        ).all())
    exams = (db.query(HealthExam)
        .options(
            selectinload(HealthExam.family_history),
            selectinload(HealthExam.additional_history),
            selectinload(HealthExam.personal_histories),
            selectinload(HealthExam.clinical_results),
            selectinload(HealthExam.paraclinical_results),
        )
        .filter(HealthExam.campaign_id == campaign_id)
        .order_by(HealthExam.exam_date.desc(), HealthExam.exam_id.desc()).all())
    exam_by_patient = {}
    for exam in exams:
        exam_by_patient.setdefault(exam.patient_id, exam)

    history_labels = [
        "Có bệnh hay bị thương trong 5 năm qua", "Có bệnh thần kinh hay bị thương ở đầu",
        "Bệnh mắt hoặc giảm thị lực (trừ trường hợp đeo kính thuốc)", "Bệnh ở tai, giảm sức nghe hoặc thăng bằng",
        "Bệnh ở tim hoặc nhồi máu cơ tim, các bệnh tim mạch khác",
        "Phẫu thuật can thiệp tim - mạch", "Tăng huyết áp", "Khó thở",
        "Bệnh phổi, hen, khí quản thủng, viêm phế quản mạn tính", "Bệnh thận, lọc máu",
        "Nghiện rượu, bia", "Đái tháo đường hoặc kiểm soát tăng đường huyết", "Bệnh tâm thần",
        "Mất ý thức, rối loạn ý thức", "Ngất, chóng mặt", "Bệnh tiêu hóa",
        "Rối loạn giấc ngủ, ngừng thở khi ngủ, ngủ rũ ban ngày, ngáy to",
        "Tai biến mạch máu não hoặc liệt", "Bệnh hoặc tổn thương cột sống",
        "Sử dụng rượu thường xuyên, liên tục", "Sử dụng ma túy, chất gây nghiện", "Bệnh khác (ghi rõ)",
    ]
    clinical_labels = [
        ("INTERNAL_CIRCULATION", "Nội khoa — Tuần hoàn"), ("INTERNAL_RESPIRATORY", "Nội khoa — Hô hấp"),
        ("INTERNAL_DIGESTIVE", "Nội khoa — Tiêu hóa"), ("INTERNAL_UROGENITAL", "Nội khoa — Thận-Tiết niệu-Sinh dục"),
        ("INTERNAL_ENDOCRINE", "Nội khoa — Nội tiết"), ("INTERNAL_MUSCULOSKELETAL", "Nội khoa — Cơ-Xương-Khớp"),
        ("INTERNAL_NEUROLOGY", "Nội khoa — Thần kinh"), ("INTERNAL_PSYCHIATRY", "Nội khoa — Tâm thần"),
        ("SURGERY", "Ngoại khoa"), ("DERMATOLOGY", "Da liễu"), ("OBSTETRICS", "Sản phụ khoa"),
        ("EYE", "Mắt"), ("ENT", "Tai-Mũi-Họng"), ("DENTAL", "Răng-Hàm-Mặt"),
    ]
    clinical_extras = [
        ("Thị lực không kính", "Thị lực không kính (MP / MT)"), ("Thị lực có kính", "Thị lực có kính (MP / MT)"),
        ("Bệnh mắt", "Các bệnh về mắt"), ("Thính lực tai phải", "Thính lực tai phải"),
        ("Thính lực tai trái", "Thính lực tai trái"), ("Bệnh Tai-Mũi-Họng", "Các bệnh về Tai-Mũi-Họng"),
        ("Hàm trên", "Răng-Hàm-Mặt — Hàm trên"), ("Hàm dưới", "Răng-Hàm-Mặt — Hàm dưới"),
        ("Bệnh Răng-Hàm-Mặt", "Các bệnh về Răng-Hàm-Mặt"),
    ]
    biochemical = [("GLUCOSE", "Đường máu"), ("UREA", "Ure"), ("CREATININE", "Creatinin"), ("AST", "ASAT (GOT)"), ("ALT", "ALAT (GPT)")]

    workbook = Workbook()
    guide = workbook.active
    guide.title = "Hướng dẫn"
    guide.append(["TEMPLATE NHẬP KẾT QUẢ KHÁM SỨC KHỎE"])
    guide.append([f"Đơn vị: {company.name}", "MST", company.mst])
    guide.append([f"Đợt khám: {campaign.campaign_name}", "CampaignId", campaign.campaign_id])
    guide.append(["Danh sách hồ sơ đã được điền sẵn trong từng sheet. Nhập/cập nhật kết quả tại sheet tương ứng với các tab trên form."])
    guide.append(["Các ô nền vàng ở sheet kết quả là nơi nhập liệu. PatientId, ExamId, Mã HS và thông tin nhận diện là mã đối chiếu, không sửa."])
    guide.append(["File hiện là template nhập liệu; chưa có chức năng tải Excel lên để tự động cập nhật dữ liệu vào hệ thống."])
    guide.column_dimensions["A"].width = 105
    guide.column_dimensions["B"].width = 22
    guide.column_dimensions["C"].width = 30
    guide["A1"].font = Font(name="Arial", size=15, bold=True, color="FFFFFF")
    guide["A1"].fill = PatternFill("solid", fgColor="087F6A")
    guide.merge_cells("A1:C1")
    for row in guide.iter_rows():
        for cell in row:
            cell.alignment = Alignment(vertical="center", wrap_text=True)
            if cell.row > 1:
                cell.font = Font(name="Arial", size=11)
    guide.row_dimensions[4].height = 34
    guide.row_dimensions[5].height = 34
    guide.row_dimensions[6].height = 34

    thin = Side(style="thin", color="B7C9C4")
    header_fill = PatternFill("solid", fgColor="D9EDE7")
    key_headers = ["PatientId", "ExamId", "SHS", "Họ và tên", "CCCD/Hộ chiếu"]

    def add_data_sheet(title, columns, row_builder, input_start=None):
        sheet = workbook.create_sheet(title)
        sheet.append([f"{title.upper()} — {campaign.campaign_name}"])
        sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(columns))
        sheet.append([f"{company.name} | MST: {company.mst} | CampaignId: {campaign.campaign_id}"])
        sheet.merge_cells(start_row=2, start_column=1, end_row=2, end_column=len(columns))
        sheet.append([header for _, header in columns])
        for patient in patients:
            sheet.append(row_builder(patient, exam_by_patient.get(patient.patient_id)))
        sheet.freeze_panes = "A4"
        sheet.auto_filter.ref = f"A3:{get_column_letter(len(columns))}{max(3, len(patients) + 3)}"
        sheet.row_dimensions[1].height = 24
        sheet.row_dimensions[3].height = 36
        for cell in sheet[1]:
            cell.font = Font(name="Arial", size=13, bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="087F6A")
        for cell in sheet[2]:
            cell.font = Font(name="Arial", size=10, italic=True, color="445B56")
        for cell in sheet[3]:
            cell.font = Font(name="Arial", size=10, bold=True)
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
        for row in sheet.iter_rows(min_row=4, max_row=len(patients) + 3, max_col=len(columns)):
            for cell in row:
                cell.font = Font(name="Arial", size=10)
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
                if input_start and cell.column >= input_start:
                    cell.fill = PatternFill("solid", fgColor="FFF6D5")
        for index, (key, header) in enumerate(columns, 1):
            sheet.column_dimensions[get_column_letter(index)].width = 20 if key in key_headers else min(38, max(16, len(header) + 3))
        for index, (key, _) in enumerate(columns, 1):
            if key in {"DateOfBirth", "IdentityIssueDate", "ExamDate", "ConclusionDate"}:
                for row_index in range(4, len(patients) + 4):
                    sheet.cell(row_index, index).number_format = "dd/mm/yyyy"
        return sheet

    base = [("PatientId", "PatientId"), ("ExamId", "ExamId"), ("ExamCode", "Mã HS"), ("SHS", "SHS"), ("FullName", "Họ và tên"), ("IdentityNumber", "CCCD/Hộ chiếu")]
    admin_columns = base + [
        ("Gender", "Giới tính"), ("DateOfBirth", "Ngày sinh"), ("Phone", "Điện thoại"),
        ("IdentityIssueDate", "Ngày cấp CCCD"), ("IdentityIssuePlace", "Nơi cấp"),
        ("Ethnicity", "Dân tộc"), ("EthnicityCode", "Mã dân tộc"), ("BloodGroup", "Nhóm máu"),
        ("Province", "Tỉnh/Thành"), ("ProvinceCode", "Mã Tỉnh/Thành"), ("Ward", "Phường/Xã"), ("WardCode", "Mã Phường/Xã"),
        ("AddressDetail", "Địa chỉ chi tiết"), ("Occupation", "Nghề nghiệp"), ("OccupationCode", "Mã nghề nghiệp"),
        ("Workplace", "Nơi làm việc/học tập"), ("SubjectType", "Đối tượng"), ("PaymentSource", "Nguồn chi trả"), ("ExamReason", "Lý do khám"),
    ]
    add_data_sheet("Hành chính", admin_columns, lambda p, e: [p.patient_id, e.exam_id if e else None, e.exam_code if e else None, p.shs, p.full_name, p.identity_number, "Nam" if p.gender == 1 else "Nữ" if p.gender == 2 else None, p.date_of_birth, p.phone, p.identity_issue_date, p.identity_issue_place, p.ethnicity, p.ethnicity_code, p.blood_group, p.province, p.province_code, p.ward, p.ward_code, p.address_detail, p.occupation, p.occupation_code, p.workplace, e.subject_type if e else None, e.payment_source if e else None, e.exam_reason if e else None])

    history_columns = base + [("FamilyHistory", "Tiền sử gia đình (Có/Không)"), ("FamilyHistoryDetail", "Bệnh gia đình (ghi rõ)"), ("CurrentTreatment", "Đang điều trị bệnh gì"), ("ObstetricHistory", "Tiền sử thai sản")]
    history_columns += [(f"H{i:02d}", f"H{i:02d} — {label}") for i, label in enumerate(history_labels, 1)]
    def history_row(p, e):
        items = {item.history_code: item.has_condition for item in (e.personal_histories if e else [])}
        family = e.family_history if e else None
        additional = e.additional_history if e else None
        return [p.patient_id, e.exam_id if e else None, e.exam_code if e else None, p.shs, p.full_name, p.identity_number,
                "Có" if family and family.has_history else "Không" if family else None, family.detail if family else None,
                additional.current_treatment if additional else None, additional.obstetric_history if additional else None,
                *["Có" if items.get(f"H{i:02d}") is True else "Không" if items.get(f"H{i:02d}") is False else None for i in range(1, len(history_labels) + 1)]]
    add_data_sheet("Tiền sử", history_columns, history_row, input_start=7)

    physical_columns = base + [("ExamDate", "Ngày khám"), ("HeightCm", "Chiều cao (cm)"), ("WeightKg", "Cân nặng (kg)"), ("BMI", "BMI"), ("Pulse", "Mạch (lần/phút)"), ("BloodPressure", "Huyết áp"), ("PhysicalClassification", "Phân loại thể lực")]
    add_data_sheet("Thể lực", physical_columns, lambda p, e: [p.patient_id, e.exam_id if e else None, e.exam_code if e else None, p.shs, p.full_name, p.identity_number, e.exam_date if e else None, e.height_cm if e else None, e.weight_kg if e else None, e.bmi if e else None, e.pulse_per_minute if e else None, e.blood_pressure if e else None, e.physical_classification if e else None], input_start=7)

    clinical_columns = base + [(f"Clinical_{code}", label) for code, label in clinical_labels] + [(f"Doctor_{code}", f"Bác sĩ — {label}") for code, label in clinical_labels] + [(f"Extra_{i}", label) for i, (_, label) in enumerate(clinical_extras, 1)]
    def clinical_row(p, e):
        results = {item.examination_code: item for item in (e.clinical_results if e else [])}
        extras = {key: "" for key, _ in clinical_extras}
        values = {}
        for code, item in results.items():
            lines = (item.result_detail or "").splitlines()
            base_lines = []
            for line in lines:
                matched = False
                for key, _ in clinical_extras:
                    prefix = f"{key}:"
                    if line.startswith(prefix):
                        extras[key] = line[len(prefix):].strip()
                        matched = True
                        break
                if not matched:
                    base_lines.append(line)
            values[code] = ("\n".join(base_lines).strip(), item.doctor_name)
        return [p.patient_id, e.exam_id if e else None, e.exam_code if e else None, p.shs, p.full_name, p.identity_number,
                *[values.get(code, (None, None))[0] for code, _ in clinical_labels],
                *[values.get(code, (None, None))[1] for code, _ in clinical_labels],
                *[extras[key] or None for key, _ in clinical_extras]]
    add_data_sheet("Lâm sàng", clinical_columns, clinical_row, input_start=7)

    lab_columns = base + [("HEMATOLOGY", "Huyết học — Tổng phân tích tế bào máu ngoại vi"), ("BLOOD_BIOCHEMISTRY", "Sinh hóa máu (ghi chú/tổng hợp)")]
    lab_columns += [(code, label) for code, label in biochemical] + [("URINALYSIS", "Tổng phân tích nước tiểu"), ("URINE_OTHER", "Xét nghiệm nước tiểu khác"), ("CHEST_XRAY", "Chẩn đoán hình ảnh — XQ Tim Phổi thẳng"), ("OTHER_PARACLINICAL", "Kết quả cận lâm sàng khác"), ("PERIODIC_PARACLINICAL", "Khám sức khỏe định kỳ theo chỉ định")]
    def lab_row(p, e):
        results = {item.test_code: item.result_value for item in (e.paraclinical_results if e else [])}
        return [p.patient_id, e.exam_id if e else None, e.exam_code if e else None, p.shs, p.full_name, p.identity_number,
                *[results.get(key) for key in ["HEMATOLOGY", "BLOOD_BIOCHEMISTRY"]],
                *[results.get(code) for code, _ in biochemical],
                *[results.get(key) for key in ["URINALYSIS", "URINE_OTHER", "CHEST_XRAY", "OTHER_PARACLINICAL", "PERIODIC_PARACLINICAL"]]]
    add_data_sheet("Cận lâm sàng", lab_columns, lab_row, input_start=7)

    conclusion_columns = base + [("HealthStatus", "Tình trạng sức khỏe; bệnh, tật"), ("HealthClassification", "Phân loại sức khỏe (1–5)"), ("ConclusionDate", "Ngày kết luận"), ("ConclusionBy", "Người kết luận"), ("ConclusionNote", "Chức danh / ghi chú"), ("ConclusionDiseaseCodes", "Mã bệnh ICD-10 (nếu có)")]
    add_data_sheet("Kết luận", conclusion_columns, lambda p, e: [p.patient_id, e.exam_id if e else None, e.exam_code if e else None, p.shs, p.full_name, p.identity_number, e.health_status if e else None, e.health_classification if e else None, e.conclusion_date if e else None, e.conclusion_by if e else None, e.conclusion_note if e else None, e.conclusion_disease_codes if e else None], input_start=7)

    # Consolidate the tab-specific templates into one wide worksheet.
    source_sheets = workbook.worksheets[1:]
    combined = workbook.create_sheet("ImportSKS")
    combined.cell(row=1, column=1, value=source_sheets[0]["A1"].value)
    combined.cell(row=2, column=1, value=source_sheets[0]["A2"].value)
    combined.merge_cells(start_row=3, start_column=1, end_row=3, end_column=6)
    combined.cell(row=3, column=1, value="\u0054h\u00f4ng tin h\u1ed3 s\u01a1")
    for column in range(1, 7):
        source = source_sheets[0].cell(row=3, column=column)
        target = combined.cell(row=4, column=column, value=source.value)
        if source.has_style:
            target._style = copy(source._style)
        target.number_format = source.number_format
        combined.column_dimensions[get_column_letter(column)].width = source_sheets[0].column_dimensions[get_column_letter(column)].width
        for row_index in range(4, source_sheets[0].max_row + 1):
            source = source_sheets[0].cell(row=row_index, column=column)
            target = combined.cell(row=row_index + 1, column=column, value=source.value)
            if source.has_style:
                target._style = copy(source._style)
            target.number_format = source.number_format

    thin = Side(style="thin", color="B7C9C4")
    next_column = 7
    for source_sheet in source_sheets:
        section_start = next_column
        section_end = section_start + source_sheet.max_column - 7
        combined.cell(row=3, column=section_start, value=source_sheet.title)
        combined.merge_cells(start_row=3, start_column=section_start, end_row=3, end_column=section_end)
        for column in range(7, source_sheet.max_column + 1):
            target_column = section_start + column - 7
            source = source_sheet.cell(row=3, column=column)
            target = combined.cell(row=4, column=target_column, value=source.value)
            if source.has_style:
                target._style = copy(source._style)
            target.number_format = source.number_format
            combined.column_dimensions[get_column_letter(target_column)].width = source_sheet.column_dimensions[get_column_letter(column)].width
            for row_index in range(4, source_sheet.max_row + 1):
                source = source_sheet.cell(row=row_index, column=column)
                target = combined.cell(row=row_index + 1, column=target_column, value=source.value)
                if source.has_style:
                    target._style = copy(source._style)
                target.number_format = source.number_format
        next_column = section_end + 1

    last_column = next_column - 1
    combined.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_column)
    combined.merge_cells(start_row=2, start_column=1, end_row=2, end_column=last_column)
    combined.freeze_panes = "A5"
    combined.auto_filter.ref = f"A4:{get_column_letter(last_column)}{max(4, len(patients) + 4)}"
    combined.row_dimensions[1].height = 25
    combined.row_dimensions[2].height = 32
    combined.row_dimensions[3].height = 30
    combined.row_dimensions[4].height = 48
    combined["A1"].font = Font(name="Arial", size=15, bold=True, color="FFFFFF")
    combined["A1"].fill = PatternFill("solid", fgColor="087F6A")
    combined["A2"].font = Font(name="Arial", size=10, italic=True, color="445B56")
    combined["A2"].alignment = Alignment(vertical="center", wrap_text=True)
    for row_index in (3, 4):
        for cell in combined[row_index]:
            cell.font = Font(name="Arial", size=10, bold=True, color="FFFFFF" if row_index == 3 else "000000")
            cell.fill = PatternFill("solid", fgColor="087F6A" if row_index == 3 else "D9EDE7")
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    for row in combined.iter_rows(min_row=5, max_row=len(patients) + 4, max_col=last_column):
        for cell in row:
            cell.font = Font(name="Arial", size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = Border(top=thin, bottom=thin, left=thin, right=thin)

    for source_sheet in source_sheets:
        workbook.remove(source_sheet)
    workbook.remove(workbook.worksheets[0])

    output = BytesIO()
    workbook.save(output)
    filename = f"TemplateImport_{campaign.campaign_id}.xlsx"
    return Response(content=output.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/api/v1/patients/by-shs/{shs}", response_model=PatientRead, tags=["Bệnh nhân"])
def read_patient_by_shs(shs: str, mst: str = Query(..., max_length=30), campaign_id: int | None = Query(default=None, gt=0), db: Session = Depends(get_db)):
    query = db.query(Patient).filter(Patient.shs == shs, Patient.mst == mst)
    if campaign_id:
        query = query.join(PatientExamCampaign).filter(PatientExamCampaign.campaign_id == campaign_id)
    patient = query.first()
    if not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy bệnh nhân theo SHS và MST.")
    return patient


@app.post("/api/v1/patients/{patient_id}/exam-campaigns/{campaign_id}/barcode", tags=["Bệnh nhân"])
def ensure_patient_campaign_barcode(patient_id: int, campaign_id: int, db: Session = Depends(get_db)):
    """Return MaHS for one patient/campaign, allocating a draft visit when needed."""
    patient = get_patient_or_404(db, patient_id)
    get_exam_campaign_or_404(db, campaign_id)
    linked = db.query(PatientExamCampaign).filter(
        PatientExamCampaign.patient_id == patient_id,
        PatientExamCampaign.campaign_id == campaign_id,
    ).first()
    if not linked:
        raise HTTPException(status_code=422, detail="Bệnh nhân chưa được gán vào đợt khám đã chọn.")
    exam = (db.query(HealthExam)
            .filter(HealthExam.patient_id == patient_id, HealthExam.campaign_id == campaign_id)
            .order_by(HealthExam.exam_id.desc()).first())
    if not exam:
        exam = HealthExam(
            patient_id=patient_id,
            campaign_id=campaign_id,
            exam_code=f"TMP-{uuid4().hex[:24]}",
            exam_date=datetime.now(),
            status="Draft",
            created_at=datetime.now(),
        )
        db.add(exam)
        db.flush()
        exam.exam_code = make_exam_code(exam)
        db.commit()
        db.refresh(exam)
    return {
        "exam_id": exam.exam_id,
        "exam_code": exam.exam_code,
        "created_draft": exam.status == "Draft",
        "patient_name": patient.full_name,
        "date_of_birth": patient.date_of_birth,
    }


def create_barcode_label_pdf(patient: Patient, exam_code: str) -> bytes:
    """Create a landscape 100 x 30 mm Code 128 label without invoking a print dialog."""
    page_width, page_height = 100 * mm, 30 * mm
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(page_width, page_height), pageCompression=1)
    font_name = "Helvetica-Bold"
    arial = Path(r"C:\Windows\Fonts\arial.ttf")
    if arial.exists():
        try:
            pdfmetrics.getFont("KskBarcodeArial")
        except KeyError:
            pdfmetrics.registerFont(TTFont("KskBarcodeArial", str(arial)))
        font_name = "KskBarcodeArial"
    birth = patient.date_of_birth.strftime("%d/%m/%Y") if patient.date_of_birth else ""
    label = f"{patient.full_name} · {birth}" if birth else patient.full_name
    font_size = 10
    while pdfmetrics.stringWidth(label, font_name, font_size) > 94 * mm and font_size > 7:
        font_size -= 0.5
    pdf.setFont(font_name, font_size)
    pdf.drawCentredString(page_width / 2, 24.5 * mm, label)
    barcode = code128.Code128(exam_code, barHeight=14 * mm, barWidth=0.32 * mm, humanReadable=False)
    barcode_width = barcode.width
    if barcode_width > 94 * mm:
        barcode.barWidth *= (94 * mm) / barcode_width
        barcode = code128.Code128(exam_code, barHeight=14 * mm, barWidth=barcode.barWidth, humanReadable=False)
    barcode.drawOn(pdf, (page_width - barcode.width) / 2, 6 * mm)
    pdf.showPage()
    pdf.save()
    return output.getvalue()


@app.post("/api/v1/patients/{patient_id}/exam-campaigns/{campaign_id}/barcode-pdf", tags=["Bệnh nhân"])
def download_patient_campaign_barcode_pdf(patient_id: int, campaign_id: int, db: Session = Depends(get_db)):
    """Download a 100 x 30 mm barcode label as PDF; no browser print window is used."""
    result = ensure_patient_campaign_barcode(patient_id, campaign_id, db)
    patient = get_patient_or_404(db, patient_id)
    content = create_barcode_label_pdf(patient, result["exam_code"])
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="Barcode_{result["exam_code"]}.pdf"'},
    )


@app.post("/api/v1/companies", response_model=CompanyRead, status_code=status.HTTP_201_CREATED, tags=["Đơn vị"])
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    company = Company(**payload.model_dump(), created_at=datetime.now())
    db.add(company)
    commit_or_conflict(db, "Mã số thuế đã tồn tại.")
    db.refresh(company)
    return company


@app.get("/api/v1/companies", response_model=list[CompanyRead], tags=["Đơn vị"])
def list_companies(q: str | None = Query(default=None, max_length=100), limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)):
    query = db.query(Company)
    if q:
        query = query.filter((Company.name.contains(q)) | (Company.mst.contains(q)))
    return query.order_by(Company.company_id.desc()).limit(limit).all()


@app.get("/api/v1/companies/{company_id}", response_model=CompanyRead, tags=["Đơn vị"])
def read_company(company_id: int, db: Session = Depends(get_db)):
    return get_company_or_404(db, company_id)


@app.patch("/api/v1/companies/{company_id}", response_model=CompanyRead, tags=["Đơn vị"])
def update_company(company_id: int, payload: CompanyUpdate, db: Session = Depends(get_db)):
    company = get_company_or_404(db, company_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    company.updated_at = datetime.now()
    commit_or_conflict(db, "Mã số thuế đã tồn tại.")
    db.refresh(company)
    return company


@app.delete("/api/v1/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Đơn vị"])
def delete_company(company_id: int, db: Session = Depends(get_db)):
    company = get_company_or_404(db, company_id)
    if db.query(ExamCampaign).filter(ExamCampaign.company_id == company_id).first():
        raise HTTPException(status_code=409, detail="Không thể xóa đơn vị đã có đợt khám; hãy xóa hoặc ngừng sử dụng các đợt khám trước.")
    db.delete(company)
    db.commit()


@app.post("/api/v1/exam-campaigns", response_model=ExamCampaignRead, status_code=status.HTTP_201_CREATED, tags=["Đợt khám"])
def create_exam_campaign(payload: ExamCampaignCreate, db: Session = Depends(get_db)):
    get_company_or_404(db, payload.company_id)
    validate_campaign_dates(payload.start_date, payload.end_date)
    campaign = ExamCampaign(**payload.model_dump(), created_at=datetime.now())
    db.add(campaign)
    commit_or_conflict(db, "Tên đợt khám và ngày bắt đầu đã tồn tại cho đơn vị này.")
    db.refresh(campaign)
    return campaign


@app.get("/api/v1/exam-campaigns", response_model=list[ExamCampaignRead], tags=["Đợt khám"])
def list_exam_campaigns(company_id: int | None = Query(default=None, gt=0), active_only: bool = False, limit: int = Query(default=500, ge=1, le=1000), db: Session = Depends(get_db)):
    query = db.query(ExamCampaign)
    if company_id:
        query = query.filter(ExamCampaign.company_id == company_id)
    if active_only:
        query = query.filter(ExamCampaign.is_active == True)  # noqa: E712 - SQLAlchemy comparison
    return query.order_by(ExamCampaign.start_date.desc(), ExamCampaign.campaign_id.desc()).limit(limit).all()


@app.get("/api/v1/exam-campaigns/patient-counts", tags=["Đợt khám"])
def list_exam_campaign_patient_counts(company_id: int = Query(..., gt=0), db: Session = Depends(get_db)):
    rows = (
        db.query(
            ExamCampaign.campaign_id,
            func.count(PatientExamCampaign.patient_exam_campaign_id).label("patient_count"),
        )
        .outerjoin(PatientExamCampaign, PatientExamCampaign.campaign_id == ExamCampaign.campaign_id)
        .filter(ExamCampaign.company_id == company_id)
        .group_by(ExamCampaign.campaign_id)
        .all()
    )
    return [{"campaign_id": row.campaign_id, "patient_count": row.patient_count} for row in rows]


@app.get("/api/v1/exam-campaigns/{campaign_id}", response_model=ExamCampaignRead, tags=["Đợt khám"])
def read_exam_campaign(campaign_id: int, db: Session = Depends(get_db)):
    return get_exam_campaign_or_404(db, campaign_id)


@app.patch("/api/v1/exam-campaigns/{campaign_id}", response_model=ExamCampaignRead, tags=["Đợt khám"])
def update_exam_campaign(campaign_id: int, payload: ExamCampaignUpdate, db: Session = Depends(get_db)):
    campaign = get_exam_campaign_or_404(db, campaign_id)
    body = payload.model_dump(exclude_unset=True)
    start_date = body.get("start_date", campaign.start_date)
    end_date = body.get("end_date", campaign.end_date)
    validate_campaign_dates(start_date, end_date)
    for field, value in body.items():
        setattr(campaign, field, value)
    campaign.updated_at = datetime.now()
    commit_or_conflict(db, "Tên đợt khám và ngày bắt đầu đã tồn tại cho đơn vị này.")
    db.refresh(campaign)
    return campaign


@app.delete("/api/v1/exam-campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Đợt khám"])
def delete_exam_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = get_exam_campaign_or_404(db, campaign_id)
    if db.query(PatientExamCampaign).filter(PatientExamCampaign.campaign_id == campaign_id).first() or db.query(HealthExam).filter(HealthExam.campaign_id == campaign_id).first():
        raise HTTPException(status_code=409, detail="Không thể xóa đợt khám đã có bệnh nhân hoặc lần khám; hãy chuyển sang ngừng sử dụng.")
    db.delete(campaign)
    db.commit()


@app.get("/api/v1/lien-thong/facilities", response_model=list[FacilityProfileRead], tags=["Liên thông HSSK"])
def list_linkage_facilities(db: Session = Depends(get_db)):
    return db.query(KskFacilityProfile).order_by(KskFacilityProfile.is_default.desc(), KskFacilityProfile.facility_name).all()


@app.post("/api/v1/lien-thong/facilities", response_model=FacilityProfileRead, status_code=status.HTTP_201_CREATED, tags=["Liên thông HSSK"])
def create_linkage_facility(payload: FacilityProfileInput, db: Session = Depends(get_db)):
    if payload.is_default:
        db.query(KskFacilityProfile).update({KskFacilityProfile.is_default: False}, synchronize_session=False)
    facility = KskFacilityProfile(**payload.model_dump(), created_at=datetime.now())
    db.add(facility)
    commit_or_conflict(db, "Mã CSKCB hoặc mã GLN đã tồn tại.")
    db.refresh(facility)
    return facility


@app.patch("/api/v1/lien-thong/facilities/{facility_id}", response_model=FacilityProfileRead, tags=["Liên thông HSSK"])
def update_linkage_facility(facility_id: int, payload: FacilityProfileInput, db: Session = Depends(get_db)):
    facility = get_facility_or_404(db, facility_id)
    if payload.is_default:
        db.query(KskFacilityProfile).filter(KskFacilityProfile.facility_id != facility_id).update({KskFacilityProfile.is_default: False}, synchronize_session=False)
    for field, value in payload.model_dump().items():
        setattr(facility, field, value)
    facility.updated_at = datetime.now()
    commit_or_conflict(db, "Mã CSKCB hoặc mã GLN đã tồn tại.")
    db.refresh(facility)
    return facility


@app.post("/api/v1/patients/restore-for-campaign", response_model=PatientRead, tags=["Bệnh nhân"])
def restore_patient_to_campaign(
    identity_number: str = Query(..., min_length=1, max_length=30),
    mst: str = Query(..., min_length=1, max_length=30),
    campaign_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
):
    """Reattach an existing patient to a campaign when no exam was recorded there."""
    campaign = get_exam_campaign_or_404(db, campaign_id)
    company = get_company_or_404(db, campaign.company_id)
    if company.mst != mst:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")

    patient = db.query(Patient).filter(Patient.identity_number == identity_number.strip()).first()
    if not patient:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ cũ theo số CCCD/định danh này.")
    if patient.mst != company.mst:
        raise HTTPException(status_code=409, detail="CCCD này đã thuộc một đơn vị khác; không thể khôi phục vào đơn vị đang chọn.")
    if db.query(PatientExamCampaign.patient_exam_campaign_id).filter(
        PatientExamCampaign.patient_id == patient.patient_id,
        PatientExamCampaign.campaign_id == campaign_id,
    ).first():
        raise HTTPException(status_code=409, detail="Hồ sơ này đã có trong đợt khám đang chọn.")
    if db.query(HealthExam.exam_id).filter(
        HealthExam.patient_id == patient.patient_id,
        HealthExam.campaign_id == campaign_id,
    ).first():
        raise HTTPException(status_code=409, detail="Hồ sơ đã có lần khám trong đợt này; không thể dùng luồng khôi phục hồ sơ chưa khám.")

    if patient.shs:
        try:
            numeric_shs = int(patient.shs.strip())
        except (ValueError, AttributeError):
            numeric_shs = None
        duplicate_shs = db.query(Patient.patient_id).join(
            PatientExamCampaign, PatientExamCampaign.patient_id == Patient.patient_id
        ).filter(
            PatientExamCampaign.campaign_id == campaign_id,
            Patient.patient_id != patient.patient_id,
        )
        if numeric_shs is not None and numeric_shs <= 9223372036854775807:
            duplicate_shs = duplicate_shs.filter(text(
                "TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) = :restore_shs"
            )).params(restore_shs=numeric_shs)
        else:
            duplicate_shs = duplicate_shs.filter(func.lower(func.ltrim(func.rtrim(Patient.shs))) == patient.shs.strip().lower())
        if duplicate_shs.first():
            patient.shs = allocate_campaign_shs(db, campaign_id)
    else:
        patient.shs = allocate_campaign_shs(db, campaign_id)

    db.add(PatientExamCampaign(
        patient_id=patient.patient_id,
        campaign_id=campaign_id,
        imported_at=datetime.now(),
        created_at=datetime.now(),
    ))
    commit_or_conflict(db, "Không thể khôi phục hồ sơ vào đợt khám đã chọn.")
    db.refresh(patient)
    return patient


@app.get("/api/v1/patients/{patient_id}", response_model=PatientRead, tags=["Bệnh nhân"])
def read_patient(patient_id: int, db: Session = Depends(get_db)):
    return get_patient_or_404(db, patient_id)


@app.get("/api/v1/patients/{patient_id}/exam-campaigns", response_model=list[ExamCampaignRead], tags=["Bệnh nhân"])
def list_patient_exam_campaigns(patient_id: int, db: Session = Depends(get_db)):
    get_patient_or_404(db, patient_id)
    return (db.query(ExamCampaign)
            .join(PatientExamCampaign, PatientExamCampaign.campaign_id == ExamCampaign.campaign_id)
            .filter(PatientExamCampaign.patient_id == patient_id)
            .order_by(ExamCampaign.start_date.desc(), ExamCampaign.campaign_id.desc())
            .all())


@app.patch("/api/v1/patients/{patient_id}", response_model=PatientRead, tags=["Bệnh nhân"])
def update_patient(patient_id: int, payload: PatientUpdate, campaign_id: int | None = Query(default=None, gt=0), db: Session = Depends(get_db)):
    patient = get_patient_or_404(db, patient_id)
    data = payload.model_dump(exclude_unset=True)
    if "shs" in data:
        new_shs = str(data["shs"] or "").strip()
        old_shs = str(patient.shs or "").strip()
        if new_shs != old_shs:
            if not new_shs:
                raise HTTPException(status_code=422, detail="SHS không được để trống.")
            if not new_shs.isascii() or not new_shs.isdigit():
                raise HTTPException(status_code=422, detail="SHS chỉ được gồm chữ số.")
            duplicate_query = db.query(Patient.patient_id).filter(Patient.patient_id != patient_id)
            if campaign_id:
                belongs_to_campaign = db.query(PatientExamCampaign.patient_exam_campaign_id).filter(
                    PatientExamCampaign.patient_id == patient_id,
                    PatientExamCampaign.campaign_id == campaign_id,
                ).first()
                if not belongs_to_campaign:
                    raise HTTPException(status_code=422, detail="Bệnh nhân không thuộc đợt khám đang chọn.")
                duplicate_query = duplicate_query.join(
                    PatientExamCampaign, PatientExamCampaign.patient_id == Patient.patient_id
                ).filter(PatientExamCampaign.campaign_id == campaign_id)
                scope_description = "trong đợt khám đang chọn"
            else:
                duplicate_query = duplicate_query.filter(Patient.mst == patient.mst)
                scope_description = "cùng đơn vị"

            try:
                numeric_shs = int(new_shs)
            except ValueError:
                numeric_shs = None
            if numeric_shs is not None and numeric_shs <= 9223372036854775807:
                duplicate_query = duplicate_query.filter(text(
                    "TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) = :duplicate_shs"
                )).params(duplicate_shs=numeric_shs)
            else:
                duplicate_query = duplicate_query.filter(func.lower(func.ltrim(func.rtrim(Patient.shs))) == new_shs.lower())
            if duplicate_query.first():
                raise HTTPException(status_code=409, detail=f"SHS {new_shs} đã được sử dụng {scope_description}; hãy chọn số khác.")
        data["shs"] = new_shs or None
    normalize_patient_address(data, db)
    for field, value in data.items():
        setattr(patient, field, value)
    patient.updated_at = datetime.now()
    commit_or_conflict(db, "Số CCCD/Hộ chiếu đã tồn tại.")
    db.refresh(patient)
    return patient


@app.delete("/api/v1/company-patients/{mst}", response_model=DeleteResult, tags=["Bệnh nhân"])
def delete_patients_by_mst(mst: str, db: Session = Depends(get_db)):
    patients = db.query(Patient).filter(Patient.mst == mst).all()
    for patient in patients:
        delete_patient_records(db, patient)
    db.commit()
    return DeleteResult(deleted=len(patients), message=f"Đã xóa {len(patients)} bệnh nhân của đơn vị có MST {mst}.")


@app.delete("/api/v1/exam-campaigns/{campaign_id}/patients", response_model=DeleteResult, tags=["Bệnh nhân"])
def delete_patients_by_campaign(campaign_id: int, mst: str = Query(..., max_length=30), db: Session = Depends(get_db)):
    """Clear patient membership and examination data for one selected examination campaign.

    The campaign catalog and patients assigned to other campaigns are kept intact.
    """
    campaign = get_exam_campaign_or_404(db, campaign_id)
    company = get_company_or_404(db, campaign.company_id)
    if company.mst != mst:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị có MST đã chọn.")

    links = db.query(PatientExamCampaign).filter(PatientExamCampaign.campaign_id == campaign_id).all()
    patient_ids = [link.patient_id for link in links]
    exam_ids = [exam_id for (exam_id,) in db.query(HealthExam.exam_id).filter(HealthExam.campaign_id == campaign_id).all()]
    delete_exam_records(db, exam_ids)
    db.query(PatientExamCampaign).filter(PatientExamCampaign.campaign_id == campaign_id).delete(synchronize_session=False)
    db.commit()
    return DeleteResult(
        deleted=len(patient_ids),
        message=(f"Đã xóa {len(patient_ids)} bệnh nhân khỏi đợt khám '{campaign.campaign_name}' "
                 "và toàn bộ lần khám thuộc đợt này. Danh mục đợt khám và bệnh nhân ở đợt khác được giữ lại."),
    )


@app.delete("/api/v1/patients/{patient_id}/exam-campaigns/{campaign_id}", response_model=DeleteResult, tags=["Bệnh nhân"])
def delete_patient_from_campaign(patient_id: int, campaign_id: int, db: Session = Depends(get_db)):
    """Remove a patient only from the selected campaign and retain other campaign records."""
    patient = get_patient_or_404(db, patient_id)
    link = db.query(PatientExamCampaign).filter(
        PatientExamCampaign.patient_id == patient_id,
        PatientExamCampaign.campaign_id == campaign_id,
    ).first()
    if not link:
        raise HTTPException(status_code=404, detail="Bệnh nhân không thuộc đợt khám đã chọn.")

    exam_ids = [exam_id for (exam_id,) in db.query(HealthExam.exam_id).filter(
        HealthExam.patient_id == patient_id,
        HealthExam.campaign_id == campaign_id,
    ).all()]
    delete_exam_records(db, exam_ids)
    db.delete(link)
    db.commit()
    return DeleteResult(
        deleted=1,
        message=("Đã xóa hồ sơ và các lần khám khỏi đợt khám đang chọn. "
                 "Thông tin hành chính gốc được giữ lại để bảo toàn lịch sử và tránh ảnh hưởng dữ liệu ở đợt khác."),
    )


@app.delete("/api/v1/patients/{patient_id}", response_model=DeleteResult, tags=["Bệnh nhân"])
def delete_patient(patient_id: int, db: Session = Depends(get_db)):
    patient = get_patient_or_404(db, patient_id)
    delete_patient_records(db, patient)
    db.commit()
    return DeleteResult(deleted=1, message="Đã xóa bệnh nhân và hồ sơ khám liên quan.")


@app.post("/api/v1/exams", response_model=HealthExamDetail, status_code=status.HTTP_201_CREATED, tags=["Lần khám"])
def create_exam(payload: HealthExamCreate, refresh_exam_date: bool = Query(default=False), db: Session = Depends(get_db)):
    get_patient_or_404(db, payload.patient_id)
    if payload.campaign_id:
        campaign = get_exam_campaign_or_404(db, payload.campaign_id)
        is_linked = db.query(PatientExamCampaign).filter(
            PatientExamCampaign.patient_id == payload.patient_id,
            PatientExamCampaign.campaign_id == campaign.campaign_id,
        ).first()
        if not is_linked:
            raise HTTPException(status_code=422, detail="Bệnh nhân chưa được gán vào đợt khám đã chọn.")
    body = payload.model_dump(exclude={"family_history", "additional_history", "personal_histories", "clinical_results", "paraclinical_results"})
    if refresh_exam_date:
        body["exam_date"] = db.query(func.getdate()).scalar()
    elif body["exam_date"] is None:
        body["exam_date"] = datetime.now()
    # ExamId is generated by SQL Server. Use a temporary unique value only for
    # the first flush, then allocate the stable barcode/MaHS from that ExamId.
    body["exam_code"] = f"TMP-{uuid4().hex[:24]}"
    # CreatedAt is a NOT NULL legacy SQL column. Assign it explicitly so
    # SQLAlchemy never submits NULL even when the database has a default.
    exam = HealthExam(**body, created_at=datetime.now())
    if payload.family_history:
        exam.family_history = ExamFamilyHistory(**payload.family_history.model_dump())
    if payload.additional_history:
        exam.additional_history = ExamAdditionalHistory(**payload.additional_history.model_dump())
    exam.personal_histories = [ExamPersonalHistory(**item.model_dump()) for item in payload.personal_histories]
    exam.clinical_results = [ExamClinicalResult(**item.model_dump()) for item in payload.clinical_results]
    exam.paraclinical_results = [ExamParaclinicalResult(**item.model_dump()) for item in payload.paraclinical_results]
    db.add(exam)
    try:
        db.flush()
        exam.exam_code = make_exam_code(exam)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Không thể sinh Mã hồ sơ hoặc lưu chi tiết lần khám.")
    return get_exam_or_404(db, exam.exam_id, detailed=True)


@app.get("/api/v1/exams/by-code/{exam_code}", response_model=HealthExamDetail, tags=["Lần khám"])
def read_exam_by_code(exam_code: str, db: Session = Depends(get_db)):
    exam = db.query(HealthExam).filter(HealthExam.exam_code == exam_code.strip()).first()
    if not exam:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ theo Mã hồ sơ/Barcode.")
    return get_exam_or_404(db, exam.exam_id, detailed=True)


@app.get("/api/v1/exams/{exam_id}/word", tags=["Lần khám"])
def download_exam_word(exam_id: int, db: Session = Depends(get_db)):
    """Download the Ministry Word template populated with administrative data."""
    exam = get_exam_or_404(db, exam_id, detailed=True)
    template_path = WEB_ROOT / "Mẫu KSK TT25" / "Mau 03 TT 25 (30.06.2026) KSK tu du 18.docx"
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail="Không tìm thấy file mẫu Word Mẫu 03 TT25 trên máy chủ.")
    with tempfile.NamedTemporaryFile(prefix=f"KSK_{exam.exam_id}_", suffix=".docx", delete=False) as temporary_file:
        output_path = Path(temporary_file.name)
    try:
        create_administrative_docx(template_path, output_path, exam.patient, exam)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không tạo được phiếu Word: {error}")
    filename = f"Phieu_KSK_{exam.exam_code or exam.exam_id}.docx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        background=BackgroundTask(output_path.unlink, missing_ok=True),
    )


@app.get("/api/v1/exams/{exam_id}/word-a4", tags=["Lần khám"])
def download_exam_word_a4(exam_id: int, db: Session = Depends(get_db)):
    """Download the A4 administrative KSK template populated with MaHS barcode."""
    exam = get_exam_or_404(db, exam_id, detailed=True)
    template_path = WEB_ROOT / "Mẫu KSK TT25" / "Mau 03 TT 25 (30.06.2026) KSK tu du 18_A4.docx"
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail="Không tìm thấy file mẫu Word A4 trên máy chủ.")
    with tempfile.NamedTemporaryFile(prefix=f"KSK_A4_{exam.exam_id}_", suffix=".docx", delete=False) as temporary_file:
        output_path = Path(temporary_file.name)
    try:
        create_administrative_docx(template_path, output_path, exam.patient, exam)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không tạo được phiếu Word A4: {error}")
    filename = f"Phieu_KSK_A4_{exam.exam_code or exam.exam_id}.docx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        background=BackgroundTask(output_path.unlink, missing_ok=True),
    )


@app.get("/api/v1/exam-campaigns/{campaign_id}/word-a4-all", tags=["Đợt khám"])
def download_campaign_word_a4(campaign_id: int, mst: str = Query(..., max_length=30), db: Session = Depends(get_db)):
    """Download one Word document containing an A4 form for every campaign patient."""
    company = db.query(Company).filter(Company.mst == mst).first()
    if not company:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn vị theo MST.")
    campaign = get_exam_campaign_or_404(db, campaign_id)
    if campaign.company_id != company.company_id:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")
    template_path = WEB_ROOT / "Mẫu KSK TT25" / "Mau 03 TT 25 (30.06.2026) KSK tu du 18_A4.docx"
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail="Không tìm thấy file mẫu Word A4 trên máy chủ.")

    patients = (
        db.query(Patient)
        .join(PatientExamCampaign, PatientExamCampaign.patient_id == Patient.patient_id)
        .filter(PatientExamCampaign.campaign_id == campaign_id, Patient.mst == mst)
        .order_by(
            text("CASE WHEN TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) IS NULL THEN 1 ELSE 0 END ASC"),
            text("TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) ASC"),
            Patient.patient_id.asc(),
        )
        .all()
    )
    if not patients:
        raise HTTPException(status_code=404, detail="Đợt khám chưa có hồ sơ bệnh nhân để xuất.")

    patient_ids = [patient.patient_id for patient in patients]
    exams = (
        db.query(HealthExam)
        .filter(HealthExam.campaign_id == campaign_id, HealthExam.patient_id.in_(patient_ids))
        .order_by(HealthExam.exam_id.desc())
        .all()
    )
    exam_by_patient = {}
    for exam in exams:
        exam_by_patient.setdefault(exam.patient_id, exam)

    # Match the existing barcode workflow: allocate a draft visit/MaHS for
    # campaign patients that do not yet have an exam, so every exported form
    # carries its real barcode and can be opened later from the list.
    now = datetime.now()
    for patient in patients:
        if patient.patient_id not in exam_by_patient:
            exam = HealthExam(
                patient_id=patient.patient_id,
                campaign_id=campaign_id,
                exam_code=f"TMP-{uuid4().hex[:24]}",
                exam_date=now,
                status="Draft",
                created_at=now,
            )
            db.add(exam)
            db.flush()
            exam.exam_code = make_exam_code(exam)
            exam_by_patient[patient.patient_id] = exam
    db.commit()

    detailed_exams = (
        db.query(HealthExam)
        .options(
            selectinload(HealthExam.patient), selectinload(HealthExam.family_history),
            selectinload(HealthExam.additional_history), selectinload(HealthExam.personal_histories),
            selectinload(HealthExam.clinical_results), selectinload(HealthExam.paraclinical_results),
            selectinload(HealthExam.facility), selectinload(HealthExam.ksk_field_values),
        )
        .filter(HealthExam.exam_id.in_([exam.exam_id for exam in exam_by_patient.values()]))
        .all()
    )
    detailed_by_patient = {exam.patient_id: exam for exam in detailed_exams}

    with tempfile.NamedTemporaryFile(prefix=f"KSK_A4_Campaign_{campaign_id}_", suffix=".docx", delete=False) as temporary_file:
        output_path = Path(temporary_file.name)
    try:
        records = [(patient, detailed_by_patient[patient.patient_id]) for patient in patients]
        create_campaign_administrative_docx(template_path, output_path, records)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không tạo được file Word A4 gộp: {error}")

    filename = f"Phieu_KSK_A4_Dot_{campaign_id}.docx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        background=BackgroundTask(output_path.unlink, missing_ok=True),
    )


@app.get("/api/v1/exam-campaigns/{campaign_id}/word-all", tags=["Đợt khám"])
def download_campaign_word(campaign_id: int, mst: str = Query(..., max_length=30), db: Session = Depends(get_db)):
    """Download one Word document containing the standard form for every campaign patient."""
    company = db.query(Company).filter(Company.mst == mst).first()
    if not company:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn vị theo MST.")
    campaign = get_exam_campaign_or_404(db, campaign_id)
    if campaign.company_id != company.company_id:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")
    template_path = WEB_ROOT / "Mẫu KSK TT25" / "Mau 03 TT 25 (30.06.2026) KSK tu du 18.docx"
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail="Không tìm thấy file mẫu Word trên máy chủ.")

    patients = (
        db.query(Patient)
        .join(PatientExamCampaign, PatientExamCampaign.patient_id == Patient.patient_id)
        .filter(PatientExamCampaign.campaign_id == campaign_id, Patient.mst == mst)
        .order_by(
            text("CASE WHEN TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) IS NULL THEN 1 ELSE 0 END ASC"),
            text("TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) ASC"),
            Patient.patient_id.asc(),
        )
        .all()
    )
    if not patients:
        raise HTTPException(status_code=404, detail="Đợt khám chưa có hồ sơ bệnh nhân để xuất.")

    patient_ids = [patient.patient_id for patient in patients]
    exams = (
        db.query(HealthExam)
        .filter(HealthExam.campaign_id == campaign_id, HealthExam.patient_id.in_(patient_ids))
        .order_by(HealthExam.exam_id.desc())
        .all()
    )
    exam_by_patient = {}
    for exam in exams:
        exam_by_patient.setdefault(exam.patient_id, exam)

    # Allocate a draft visit when needed so every form gets its actual MaHS barcode.
    now = datetime.now()
    for patient in patients:
        if patient.patient_id not in exam_by_patient:
            exam = HealthExam(
                patient_id=patient.patient_id,
                campaign_id=campaign_id,
                exam_code=f"TMP-{uuid4().hex[:24]}",
                exam_date=now,
                status="Draft",
                created_at=now,
            )
            db.add(exam)
            db.flush()
            exam.exam_code = make_exam_code(exam)
            exam_by_patient[patient.patient_id] = exam
    db.commit()

    detailed_exams = (
        db.query(HealthExam)
        .options(
            selectinload(HealthExam.patient), selectinload(HealthExam.family_history),
            selectinload(HealthExam.additional_history), selectinload(HealthExam.personal_histories),
            selectinload(HealthExam.clinical_results), selectinload(HealthExam.paraclinical_results),
            selectinload(HealthExam.facility), selectinload(HealthExam.ksk_field_values),
        )
        .filter(HealthExam.exam_id.in_([exam.exam_id for exam in exam_by_patient.values()]))
        .all()
    )
    detailed_by_patient = {exam.patient_id: exam for exam in detailed_exams}

    with tempfile.NamedTemporaryFile(prefix=f"KSK_Word_Campaign_{campaign_id}_", suffix=".docx", delete=False) as temporary_file:
        output_path = Path(temporary_file.name)
    try:
        records = [(patient, detailed_by_patient[patient.patient_id]) for patient in patients]
        create_campaign_administrative_docx(template_path, output_path, records)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không tạo được file Word gộp: {error}")

    filename = f"Phieu_KSK_Dot_{campaign_id}.docx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        background=BackgroundTask(output_path.unlink, missing_ok=True),
    )


@app.get("/api/v1/exam-campaigns/{campaign_id}/word-photo-all", tags=["Đợt khám"])
def download_campaign_word_with_photo(campaign_id: int, mst: str = Query(..., max_length=30), db: Session = Depends(get_db)):
    """Download one Word-with-photo document containing every campaign patient."""
    company = db.query(Company).filter(Company.mst == mst).first()
    if not company:
        raise HTTPException(status_code=404, detail="Không tìm thấy đơn vị theo MST.")
    campaign = get_exam_campaign_or_404(db, campaign_id)
    if campaign.company_id != company.company_id:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")
    template_path = WEB_ROOT / "Mẫu KSK TT25" / "Mau 03 TT 25 (30.06.2026) KSK tu du 18 co anh.docx"
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail="Không tìm thấy file mẫu Word có ảnh trên máy chủ.")

    patients = (
        db.query(Patient)
        .join(PatientExamCampaign, PatientExamCampaign.patient_id == Patient.patient_id)
        .filter(PatientExamCampaign.campaign_id == campaign_id, Patient.mst == mst)
        .order_by(
            text("CASE WHEN TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) IS NULL THEN 1 ELSE 0 END ASC"),
            text("TRY_CONVERT(BIGINT, NULLIF(LTRIM(RTRIM([Patients].[SHS])), '')) ASC"),
            Patient.patient_id.asc(),
        )
        .all()
    )
    if not patients:
        raise HTTPException(status_code=404, detail="Đợt khám chưa có hồ sơ bệnh nhân để xuất.")

    patient_ids = [patient.patient_id for patient in patients]
    exams = (
        db.query(HealthExam)
        .filter(HealthExam.campaign_id == campaign_id, HealthExam.patient_id.in_(patient_ids))
        .order_by(HealthExam.exam_id.desc())
        .all()
    )
    exam_by_patient = {}
    for exam in exams:
        exam_by_patient.setdefault(exam.patient_id, exam)

    # Allocate a draft visit when needed so every form gets its actual MaHS barcode.
    now = datetime.now()
    for patient in patients:
        if patient.patient_id not in exam_by_patient:
            exam = HealthExam(
                patient_id=patient.patient_id,
                campaign_id=campaign_id,
                exam_code=f"TMP-{uuid4().hex[:24]}",
                exam_date=now,
                status="Draft",
                created_at=now,
            )
            db.add(exam)
            db.flush()
            exam.exam_code = make_exam_code(exam)
            exam_by_patient[patient.patient_id] = exam
    db.commit()

    detailed_exams = (
        db.query(HealthExam)
        .options(
            selectinload(HealthExam.patient), selectinload(HealthExam.family_history),
            selectinload(HealthExam.additional_history), selectinload(HealthExam.personal_histories),
            selectinload(HealthExam.clinical_results), selectinload(HealthExam.paraclinical_results),
            selectinload(HealthExam.facility), selectinload(HealthExam.ksk_field_values),
        )
        .filter(HealthExam.exam_id.in_([exam.exam_id for exam in exam_by_patient.values()]))
        .all()
    )
    detailed_by_patient = {exam.patient_id: exam for exam in detailed_exams}

    with tempfile.NamedTemporaryFile(prefix=f"KSK_Word_Photo_Campaign_{campaign_id}_", suffix=".docx", delete=False) as temporary_file:
        output_path = Path(temporary_file.name)
    try:
        records = [(patient, detailed_by_patient[patient.patient_id]) for patient in patients]
        create_campaign_administrative_docx(template_path, output_path, records)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không tạo được file Word có ảnh gộp: {error}")

    filename = f"Phieu_KSK_CoAnh_Dot_{campaign_id}.docx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        background=BackgroundTask(output_path.unlink, missing_ok=True),
    )


@app.get("/api/v1/exams/{exam_id}/word-a4-conclusion", tags=["Lần khám"])
def download_exam_word_a4_with_conclusion(exam_id: int, db: Session = Depends(get_db)):
    """Download the A4 form with conclusion and conclusion date appended."""
    exam = get_exam_or_404(db, exam_id, detailed=True)
    template_path = WEB_ROOT / "Mẫu KSK TT25" / "Mau 03 TT 25 (30.06.2026) KSK tu du 18_A4.docx"
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail="Không tìm thấy file mẫu Word A4 trên máy chủ.")
    with tempfile.NamedTemporaryFile(prefix=f"KSK_A4_CONCLUSION_{exam.exam_id}_", suffix=".docx", delete=False) as temporary_file:
        output_path = Path(temporary_file.name)
    try:
        create_administrative_docx(template_path, output_path, exam.patient, exam, include_conclusion=True)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không tạo được phiếu Word A4 có kết luận: {error}")
    filename = f"Phieu_KSK_A4_Ket_Luan_{exam.exam_code or exam.exam_id}.docx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        background=BackgroundTask(output_path.unlink, missing_ok=True),
    )


@app.get("/api/v1/exams/{exam_id}/word-with-photo", tags=["Lần khám"])
def download_exam_word_with_photo(exam_id: int, db: Session = Depends(get_db)):
    """Download the template that includes the printed 4x6 photo areas."""
    exam = get_exam_or_404(db, exam_id, detailed=True)
    template_path = WEB_ROOT / "Mẫu KSK TT25" / "Mau 03 TT 25 (30.06.2026) KSK tu du 18 co anh.docx"
    if not template_path.is_file():
        raise HTTPException(status_code=500, detail="Không tìm thấy file mẫu Word có ảnh trên máy chủ.")
    with tempfile.NamedTemporaryFile(prefix=f"KSK_Anh_{exam.exam_id}_", suffix=".docx", delete=False) as temporary_file:
        output_path = Path(temporary_file.name)
    try:
        create_administrative_docx(template_path, output_path, exam.patient, exam)
    except Exception as error:
        output_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Không tạo được phiếu Word có ảnh: {error}")
    filename = f"Phieu_KSK_CoAnh_{exam.exam_code or exam.exam_id}.docx"
    return FileResponse(
        output_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=filename,
        background=BackgroundTask(output_path.unlink, missing_ok=True),
    )


@app.get("/api/v1/exams/{exam_id}", response_model=HealthExamDetail, tags=["Lần khám"])
def read_exam(exam_id: int, db: Session = Depends(get_db)):
    return get_exam_or_404(db, exam_id, detailed=True)


@app.get("/api/v1/patients/{patient_id}/exams", response_model=list[HealthExamRead], tags=["Lần khám"])
def list_patient_exams(patient_id: int, db: Session = Depends(get_db)):
    get_patient_or_404(db, patient_id)
    return db.query(HealthExam).filter(HealthExam.patient_id == patient_id).order_by(HealthExam.exam_date.desc()).all()


@app.get("/api/v1/exam-campaigns/{campaign_id}/exams", tags=["Liên thông HSSK"])
def list_campaign_exams(campaign_id: int, company_id: int = Query(..., gt=0), db: Session = Depends(get_db)):
    campaign = get_exam_campaign_or_404(db, campaign_id)
    if campaign.company_id != company_id:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")
    exams = (db.query(HealthExam)
             .options(selectinload(HealthExam.patient), selectinload(HealthExam.family_history),
                      selectinload(HealthExam.additional_history), selectinload(HealthExam.personal_histories),
                      selectinload(HealthExam.clinical_results), selectinload(HealthExam.paraclinical_results),
                      selectinload(HealthExam.facility), selectinload(HealthExam.ksk_field_values))
             .filter(HealthExam.campaign_id == campaign_id)
             .order_by(HealthExam.exam_date.desc(), HealthExam.exam_id.desc())
             .all())
    result = []
    for exam in exams:
        readiness = get_linkage_readiness(exam, db)
        result.append({
            "exam_id": exam.exam_id,
            "patient_id": exam.patient_id,
            "campaign_id": exam.campaign_id,
            "exam_code": exam.exam_code,
            "exam_date": exam.exam_date,
            "status": exam.status,
            "patient_name": exam.patient.full_name,
            "shs": exam.patient.shs,
            "mst": exam.patient.mst,
            "ready": readiness.ready,
            "readiness_errors": [issue.model_dump() for issue in readiness.errors],
        })
    return result


@app.patch("/api/v1/exams/{exam_id}", response_model=HealthExamRead, tags=["Lần khám"])
def update_exam(
    exam_id: int,
    payload: HealthExamUpdate,
    refresh_exam_date: bool = Query(default=False),
    patient_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
):
    exam = get_exam_or_404(db, exam_id)
    if patient_id is not None and exam.patient_id != patient_id:
        raise HTTPException(status_code=422, detail="Lần khám không thuộc đúng hồ sơ bệnh nhân đang chọn.")
    mark_exam_changed_after_linkage(exam)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(exam, field, value)
    if refresh_exam_date:
        exam.exam_date = db.query(func.getdate()).scalar()
    exam.updated_at = datetime.now()
    commit_or_conflict(db)
    db.refresh(exam)
    return exam


def replace_children(db: Session, exam_id: int, model, values: list, relationship_name: str):
    exam = get_exam_or_404(db, exam_id)
    mark_exam_changed_after_linkage(exam)
    # Flush deletes before inserts so a replacement can retain the same unique code.
    db.query(model).filter(model.exam_id == exam_id).delete(synchronize_session=False)
    db.flush()
    db.add_all(model(exam_id=exam_id, **item.model_dump()) for item in values)
    commit_or_conflict(db, "Mã chi tiết bị trùng trong lần khám.")
    return get_exam_or_404(db, exam_id, detailed=True)


@app.put("/api/v1/exams/{exam_id}/personal-histories", response_model=HealthExamDetail, tags=["Tiền sử"])
def replace_personal_histories(exam_id: int, payload: list[PersonalHistoryInput], db: Session = Depends(get_db)):
    return replace_children(db, exam_id, ExamPersonalHistory, payload, "personal_histories")


@app.put("/api/v1/exams/{exam_id}/family-history", response_model=HealthExamDetail, tags=["Tiền sử"])
def upsert_family_history(exam_id: int, payload: FamilyHistoryInput, db: Session = Depends(get_db)):
    exam = get_exam_or_404(db, exam_id, detailed=True)
    mark_exam_changed_after_linkage(exam)
    if exam.family_history:
        exam.family_history.has_history = payload.has_history
        exam.family_history.detail = payload.detail
    else:
        exam.family_history = ExamFamilyHistory(**payload.model_dump())
    commit_or_conflict(db)
    return get_exam_or_404(db, exam_id, detailed=True)


@app.put("/api/v1/exams/{exam_id}/additional-history", response_model=HealthExamDetail, tags=["Tiền sử"])
def upsert_additional_history(exam_id: int, payload: AdditionalHistoryInput, db: Session = Depends(get_db)):
    exam = get_exam_or_404(db, exam_id, detailed=True)
    mark_exam_changed_after_linkage(exam)
    if exam.additional_history:
        exam.additional_history.current_treatment = payload.current_treatment
        exam.additional_history.obstetric_history = payload.obstetric_history
    else:
        exam.additional_history = ExamAdditionalHistory(**payload.model_dump())
    commit_or_conflict(db)
    return get_exam_or_404(db, exam_id, detailed=True)


@app.put("/api/v1/exams/{exam_id}/clinical-results", response_model=HealthExamDetail, tags=["Khám lâm sàng"])
def replace_clinical_results(exam_id: int, payload: list[ClinicalResultInput], db: Session = Depends(get_db)):
    return replace_children(db, exam_id, ExamClinicalResult, payload, "clinical_results")


@app.put("/api/v1/exams/{exam_id}/paraclinical-results", response_model=HealthExamDetail, tags=["Khám cận lâm sàng"])
def replace_paraclinical_results(exam_id: int, payload: list[ParaclinicalResultInput], db: Session = Depends(get_db)):
    return replace_children(db, exam_id, ExamParaclinicalResult, payload, "paraclinical_results")


@app.get("/api/v1/exams/{exam_id}/lien-thong/readiness", response_model=LinkageReadiness, tags=["Liên thông HSSK"])
def check_exam_linkage_readiness(exam_id: int, db: Session = Depends(get_db)):
    """Validate the QD 2062 adult-form prerequisites before XML is generated or pushed."""
    return get_linkage_readiness(get_exam_or_404(db, exam_id, detailed=True), db)


@app.get("/api/v1/exams/{exam_id}/lien-thong/xml-preview", tags=["Liên thông HSSK"])
def preview_exam_linkage_xml(exam_id: int, campaign_id: int = Query(..., gt=0), db: Session = Depends(get_db)):
    """Build an unsigned XML preview from the selected exam and its stored data."""
    exam = get_exam_or_404(db, exam_id, detailed=True)
    if exam.campaign_id != campaign_id:
        raise HTTPException(status_code=422, detail="Lần khám không thuộc đợt khám đang chọn.")
    if _adult_form_code(exam) != "ADULT":
        raise HTTPException(status_code=422, detail="Chức năng xem trước XML hiện hỗ trợ hồ sơ từ đủ 18 tuổi.")
    xml, warnings = build_exam_xml_preview(exam)
    readiness = get_linkage_readiness(exam, db)
    return {
        "exam_id": exam.exam_id,
        "campaign_id": exam.campaign_id,
        "ready": readiness.ready,
        "xml": xml,
        "warnings": warnings,
        "readiness_errors": [issue.model_dump() for issue in readiness.errors],
    }


@app.get("/api/v1/exams/{exam_id}/lien-thong/fields", response_model=list[KskFieldValueInput], tags=["Liên thông HSSK"])
def list_exam_linkage_fields(exam_id: int, db: Session = Depends(get_db)):
    exam = get_exam_or_404(db, exam_id, detailed=True)
    return [KskFieldValueInput(field_code=item.field_code, field_value=item.field_value) for item in exam.ksk_field_values]


@app.put("/api/v1/exams/{exam_id}/lien-thong/fields", response_model=list[KskFieldValueInput], tags=["Liên thông HSSK"])
def replace_exam_linkage_fields(exam_id: int, payload: list[KskFieldValueInput], db: Session = Depends(get_db)):
    """Save XML-specific fields, including CKS_NGUOI_KET_LUAN and CKS_BENH_VIEN; blank values remove a field."""
    exam = get_exam_or_404(db, exam_id)
    mark_exam_changed_after_linkage(exam)
    for item in payload:
        stored = db.query(ExamKskFieldValue).filter(
            ExamKskFieldValue.exam_id == exam_id,
            ExamKskFieldValue.field_code == item.field_code,
        ).first()
        if not item.field_value or not item.field_value.strip():
            if stored:
                db.delete(stored)
            continue
        if stored:
            stored.field_value = item.field_value.strip()
            stored.updated_at = datetime.now()
        else:
            db.add(ExamKskFieldValue(exam_id=exam_id, field_code=item.field_code, field_value=item.field_value.strip(), source_type="Manual", updated_at=datetime.now()))
    commit_or_conflict(db, "Không thể lưu trường XML liên thông.")
    return list_exam_linkage_fields(exam_id, db)


@app.get("/api/v1/lien-thong/exams/linked", tags=["Lien thong HSSK"])
def list_linked_exams(
    company_id: int | None = Query(default=None, gt=0),
    campaign_id: int | None = Query(default=None, gt=0),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    """Return only exams that have been accepted by the linkage gateway."""
    query = (db.query(HealthExam)
             .join(Patient, HealthExam.patient_id == Patient.patient_id)
             .options(selectinload(HealthExam.patient), selectinload(HealthExam.campaign))
             .filter(HealthExam.lien_thong_status == "Linked"))
    if campaign_id:
        campaign = get_exam_campaign_or_404(db, campaign_id)
        if company_id and campaign.company_id != company_id:
            raise HTTPException(status_code=422, detail="Campaign does not belong to selected company.")
        query = query.filter(HealthExam.campaign_id == campaign_id)
    elif company_id:
        query = query.join(ExamCampaign, HealthExam.campaign_id == ExamCampaign.campaign_id).filter(ExamCampaign.company_id == company_id)
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        query = query.filter(Patient.full_name.ilike(keyword) | Patient.identity_number.ilike(keyword) | HealthExam.exam_code.ilike(keyword))
    exams = query.order_by(HealthExam.lien_thong_at.desc(), HealthExam.exam_id.desc()).limit(limit).all()
    return [{
        "exam_id": exam.exam_id, "patient_id": exam.patient_id, "campaign_id": exam.campaign_id,
        "exam_code": exam.exam_code, "exam_date": exam.exam_date,
        "patient_name": exam.patient.full_name, "gender": exam.patient.gender,
        "date_of_birth": exam.patient.date_of_birth, "identity_number": exam.patient.identity_number,
        "mst": exam.patient.mst, "campaign_name": exam.campaign.campaign_name if exam.campaign else None,
        "lien_thong_status": exam.lien_thong_status, "lien_thong_at": exam.lien_thong_at,
        "transaction_code": exam.lien_thong_transaction_code, "message_id": exam.lien_thong_message_id,
    } for exam in exams]


@app.get("/api/v1/lien-thong/exams/{exam_id}/history", tags=["Lien thong HSSK"])
def read_exam_linkage_history(exam_id: int, db: Session = Depends(get_db)):
    get_exam_or_404(db, exam_id)
    return (db.query(LienThongBatchItem).filter(LienThongBatchItem.exam_id == exam_id)
            .order_by(LienThongBatchItem.created_at.desc()).all())


@app.get("/api/v1/lien-thong/status", tags=["Lien thong HSSK"])
def lien_thong_status():
    return {
        "base_url": settings.lien_thong_base_url,
        "sender_id": settings.lien_thong_sender_id,
        "receiver_id": settings.lien_thong_receiver_id,
        "version": settings.lien_thong_version,
        "username_configured": bool(settings.lien_thong_username),
        "password_configured": bool(settings.lien_thong_password),
        "sender_id_configured": bool(settings.lien_thong_sender_id),
        "receiver_id_configured": bool(settings.lien_thong_receiver_id),
    }


@app.post("/api/v1/lien-thong/login-test", tags=["Liên thông HSSK"])
def lien_thong_login_test():
    _, result = lien_thong_login(settings, force=True)
    return {"status_code": result["status_code"], "message": "Đăng nhập HSSK Hà Nội thành công."}


@app.post("/api/v1/lien-thong/prepare", tags=["Liên thông HSSK"])
def lien_thong_prepare(payload: LienThongPushRequest):
    return build_envelope(payload.raw_data, payload.data_type, settings, payload.signature)


@app.post("/api/v1/lien-thong/push", tags=["Liên thông HSSK"])
def lien_thong_push_data(payload: LienThongPushRequest):
    envelope = build_envelope(payload.raw_data, payload.data_type, settings, payload.signature)
    return lien_thong_push(envelope, settings)


@app.post("/api/v1/lien-thong/push-envelope", tags=["Liên thông HSSK"])
def lien_thong_push_envelope(payload: LienThongEnvelope):
    """Send the exact envelope returned by the prepare step, without rebuilding its header/content."""
    envelope = payload.model_dump()
    header = envelope["header"]
    if header["sender_id"] != settings.lien_thong_sender_id or header["receiver_id"] != settings.lien_thong_receiver_id:
        raise HTTPException(status_code=422, detail="Sender ID/Receiver ID trong gói JSON không khớp cấu hình máy chủ.")
    if header["txn_type"] != "sync_checkup" or header["msg_type"] != "101":
        raise HTTPException(status_code=422, detail="Loại giao dịch trong header không hợp lệ.")
    return lien_thong_push(envelope, settings)


def require_batch_key(x_ksk_batch_key: str | None = Header(default=None)):
    configured = settings.lien_thong_batch_api_key
    if not configured:
        raise HTTPException(status_code=503, detail="KSK_BATCH_API_KEY chưa được cấu hình trên API server.")
    if not x_ksk_batch_key or not hmac.compare_digest(x_ksk_batch_key, configured):
        raise HTTPException(status_code=401, detail="Không được phép truy cập nhật ký liên thông batch.")


def purge_expired_batches(db: Session) -> None:
    keep_days = max(1, min(settings.lien_thong_batch_retention_days, 3650))
    cutoff = datetime.now() - timedelta(days=keep_days)
    db.query(LienThongBatch).filter(LienThongBatch.created_at < cutoff).delete(synchronize_session=False)
    db.commit()


def get_batch_or_404(db: Session, batch_id: int) -> LienThongBatch:
    batch = (db.query(LienThongBatch)
             .options(selectinload(LienThongBatch.items))
             .filter(LienThongBatch.batch_id == batch_id).first())
    if not batch:
        raise HTTPException(status_code=404, detail="Không tìm thấy batch liên thông.")
    return batch


def refresh_batch_status(batch: LienThongBatch) -> None:
    terminal = {"Success", "Rejected", "Failed", "Uncertain", "NotReady"}
    states = {item.status for item in batch.items}
    if states and states <= terminal:
        batch.status = "Completed" if states == {"Success"} else "CompletedWithErrors"
        batch.completed_at = datetime.now()
    elif states & {"Signing", "Signed", "Sending"}:
        batch.status = "InProgress"
        batch.started_at = batch.started_at or datetime.now()
        batch.completed_at = None


def mark_exam_changed_after_linkage(exam: HealthExam) -> None:
    """A signature is valid only for the exact XML that was signed and sent."""
    if exam.lien_thong_status == "Linked":
        exam.lien_thong_status = "NeedResend"
        exam.lien_thong_at = None
        exam.lien_thong_last_error = "Dữ liệu hồ sơ đã thay đổi sau khi liên thông thành công; cần tạo XML và ký/gửi lại."
        exam.updated_at = datetime.now()


@app.post("/api/v1/lien-thong/batches", response_model=LienThongBatchRead, status_code=status.HTTP_201_CREATED, tags=["Liên thông HSSK"])
def create_lien_thong_batch(payload: LienThongBatchCreate, _: None = Depends(require_batch_key), db: Session = Depends(get_db)):
    purge_expired_batches(db)
    campaign = get_exam_campaign_or_404(db, payload.campaign_id)
    if campaign.company_id != payload.company_id:
        raise HTTPException(status_code=422, detail="Đợt khám không thuộc đơn vị đã chọn.")
    exam_ids = list(dict.fromkeys(payload.exam_ids))
    exams = (db.query(HealthExam)
             .options(selectinload(HealthExam.patient), selectinload(HealthExam.family_history),
                      selectinload(HealthExam.additional_history), selectinload(HealthExam.personal_histories),
                      selectinload(HealthExam.clinical_results), selectinload(HealthExam.paraclinical_results),
                      selectinload(HealthExam.facility), selectinload(HealthExam.ksk_field_values))
             .filter(HealthExam.exam_id.in_(exam_ids), HealthExam.campaign_id == payload.campaign_id).all())
    if len(exams) != len(exam_ids):
        raise HTTPException(status_code=422, detail="Một hoặc nhiều lần khám không thuộc đợt khám đã chọn.")
    batch = LienThongBatch(company_id=payload.company_id, campaign_id=payload.campaign_id,
                           status="Prepared", created_at=datetime.now())
    for exam in exams:
        readiness = get_linkage_readiness(exam, db)
        item = LienThongBatchItem(
            exam_id=exam.exam_id,
            status="Queued" if readiness.ready else "NotReady",
            last_error=None if readiness.ready else "; ".join(issue.field_name for issue in readiness.errors),
            created_at=datetime.now(),
        )
        batch.items.append(item)
        if item.status == "Queued" and exam.lien_thong_status not in {"Linked", "Sending", "Signed", "Signing"}:
            exam.lien_thong_status = "Queued"
            exam.lien_thong_last_error = None
    if batch.items and all(item.status == "NotReady" for item in batch.items):
        batch.status = "CompletedWithErrors"
        batch.completed_at = datetime.now()
    db.add(batch)
    db.commit()
    return get_batch_or_404(db, batch.batch_id)


@app.get("/api/v1/lien-thong/batches", response_model=list[LienThongBatchRead], tags=["Liên thông HSSK"])
def list_lien_thong_batches(_: None = Depends(require_batch_key), limit: int = Query(default=50, ge=1, le=200), db: Session = Depends(get_db)):
    purge_expired_batches(db)
    return (db.query(LienThongBatch).options(selectinload(LienThongBatch.items))
            .order_by(LienThongBatch.created_at.desc()).limit(limit).all())


@app.get("/api/v1/lien-thong/batches/{batch_id}", response_model=LienThongBatchRead, tags=["Liên thông HSSK"])
def read_lien_thong_batch(batch_id: int, _: None = Depends(require_batch_key), db: Session = Depends(get_db)):
    purge_expired_batches(db)
    return get_batch_or_404(db, batch_id)


@app.patch("/api/v1/lien-thong/batches/{batch_id}/items/{item_id}", response_model=LienThongBatchRead, tags=["Liên thông HSSK"])
def update_lien_thong_batch_item(batch_id: int, item_id: int, payload: LienThongBatchItemUpdate,
                                 _: None = Depends(require_batch_key), db: Session = Depends(get_db)):
    batch = get_batch_or_404(db, batch_id)
    item = next((candidate for candidate in batch.items if candidate.batch_item_id == item_id), None)
    if item is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy hồ sơ trong batch.")
    if item.status in {"Success", "Rejected", "NotReady"}:
        raise HTTPException(status_code=409, detail="Hồ sơ đã ở trạng thái kết thúc; tạo batch mới để gửi lại.")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(item, key, value)
    now = datetime.now()
    if payload.status == "Signed":
        item.signed_at = now
    if payload.status in {"Success", "Rejected", "Uncertain"}:
        item.sent_at = now
    exam = get_exam_or_404(db, item.exam_id)
    if payload.status == "Success":
        exam.lien_thong_status = "Linked"
        exam.lien_thong_at = now
        exam.lien_thong_batch_item_id = item.batch_item_id
        exam.lien_thong_transaction_code = item.transaction_code
        exam.lien_thong_message_id = item.message_id
        exam.lien_thong_last_error = None
        exam.lien_thong_xml_sha256 = item.xml_sha256
    elif payload.status in {"Rejected", "Failed", "Uncertain", "NotReady"}:
        exam.lien_thong_status = payload.status
        exam.lien_thong_batch_item_id = item.batch_item_id
        exam.lien_thong_transaction_code = item.transaction_code
        exam.lien_thong_message_id = item.message_id
        exam.lien_thong_last_error = item.last_error
        exam.lien_thong_xml_sha256 = item.xml_sha256
    elif payload.status in {"Signing", "Signed", "Sending"}:
        exam.lien_thong_status = payload.status
        exam.lien_thong_batch_item_id = item.batch_item_id
    refresh_batch_status(batch)
    db.commit()
    return get_batch_or_404(db, batch_id)


# Cổng 5500 phục vụ cả giao diện HTML, API và Swagger để tránh lỗi khác origin/cổng.
@app.post("/api/v1/patients/import-exam-results.xlsx", tags=["Láº§n khÃ¡m"])
async def import_exam_results_excel(
    request: Request,
    mst: str = Query(..., max_length=30),
    campaign_id: int = Query(..., gt=0),
    db: Session = Depends(get_db),
):
    """Import exam values from a completed single-sheet Excel template."""
    company = db.query(Company).filter(Company.mst == mst).first()
    if not company:
        raise HTTPException(status_code=404, detail="KhÃ´ng tÃ¬m tháº¥y Ä‘Æ¡n vá»‹ theo MST.")
    campaign = get_exam_campaign_or_404(db, campaign_id)
    if campaign.company_id != company.company_id:
        raise HTTPException(status_code=422, detail="Äá»£t khÃ¡m khÃ´ng thuá»™c Ä‘Æ¡n vá»‹ Ä‘Ã£ chá»n.")
    content = await request.body()
    if not content or len(content) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400 if not content else 413, detail="File Excel rá»—ng hoáº·c vÆ°á»£t quÃ¡ 25 MB.")
    try:
        workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status_code=400, detail="File khÃ´ng Ä‘Ãºng Ä‘á»‹nh dáº¡ng Excel .xlsx.")
    if len(workbook.worksheets) != 1:
        raise HTTPException(status_code=422, detail="File template pháº£i chá»©a duy nháº¥t má»™t sheet.")
    sheet = workbook.active
    headers = [cell.value for cell in sheet[4]]
    icd_codes_column = next((index + 1 for index, header in enumerate(headers) if header and "ICD-10" in str(header).upper()), None)
    data_last_column = len(headers)
    if len(headers) < 113 or headers[0] != "PatientId" or headers[1] != "ExamId" or icd_codes_column is None:
        raise HTTPException(status_code=422, detail="File khÃ´ng Ä‘Ãºng template ImportSKS hoáº·c thiáº¿u cÃ¡c cá»™t dá»¯ liá»‡u.")
    if sheet.max_row > 5004:
        raise HTTPException(status_code=422, detail="File cÃ³ quÃ¡ 5.000 dÃ²ng há»“ sÆ¡.")

    def val(row, column):
        return row[column - 1] if column <= len(row) else None

    def empty(value):
        return value is None or (isinstance(value, str) and not value.strip())

    def text_value(value):
        return str(value).strip() if value is not None else None

    def parse_date(value, row_number, label):
        if isinstance(value, datetime):
            return value
        if isinstance(value, date):
            return datetime.combine(value, datetime.min.time())
        if isinstance(value, str):
            for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                try:
                    return datetime.strptime(value.strip(), fmt)
                except ValueError:
                    continue
        raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: {label} khÃ´ng Ä‘Ãºng Ä‘á»‹nh dáº¡ng dd/mm/yyyy.")

    def parse_yes_no(value, row_number, label):
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().casefold()
        if normalized in {"1", "true", "yes", "c\u00f3"}:
            return True
        if normalized in {"0", "false", "no", "kh\u00f4ng"}:
            return False
        raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: {label} chá»‰ nháº­n CÃ³/KhÃ´ng.")

    clinical_codes = [
        "INTERNAL_CIRCULATION", "INTERNAL_RESPIRATORY", "INTERNAL_DIGESTIVE", "INTERNAL_UROGENITAL",
        "INTERNAL_ENDOCRINE", "INTERNAL_MUSCULOSKELETAL", "INTERNAL_NEUROLOGY", "INTERNAL_PSYCHIATRY",
        "SURGERY", "DERMATOLOGY", "OBSTETRICS", "EYE", "ENT", "DENTAL",
    ]
    extra_keys = [
        "Th\u1ecb l\u1ef1c kh\u00f4ng k\u00ednh", "Th\u1ecb l\u1ef1c c\u00f3 k\u00ednh", "B\u1ec7nh m\u1eaft",
        "Th\u00ednh l\u1ef1c tai ph\u1ea3i", "Th\u00ednh l\u1ef1c tai tr\u00e1i", "B\u1ec7nh Tai-M\u0169i-H\u1ecdng",
        "H\u00e0m tr\u00ean", "H\u00e0m d\u01b0\u1edbi", "B\u1ec7nh R\u0103ng-H\u00e0m-M\u1eb7t",
    ]
    paraclinical_codes = [
        "HEMATOLOGY", "BLOOD_BIOCHEMISTRY", "GLUCOSE", "UREA", "CREATININE", "AST", "ALT",
        "URINALYSIS", "URINE_OTHER", "CHEST_XRAY", "OTHER_PARACLINICAL", "PERIODIC_PARACLINICAL",
    ]
    scalar_fields = {
        23: "subject_type", 24: "payment_source", 25: "exam_reason",
        53: "height_cm", 54: "weight_kg", 55: "bmi", 56: "pulse_per_minute",
        57: "blood_pressure", 58: "physical_classification", 108: "health_status",
        109: "health_classification", 111: "conclusion_by", 112: "conclusion_note",
    }
    created = updated = skipped = 0
    seen_patient_ids = set()
    campaign_patients = {
        item.patient_id: item
        for item in (db.query(Patient)
            .join(PatientExamCampaign, PatientExamCampaign.patient_id == Patient.patient_id)
            .filter(Patient.mst == company.mst, PatientExamCampaign.campaign_id == campaign_id).all())
    }
    campaign_exams = (db.query(HealthExam)
        .options(selectinload(HealthExam.family_history), selectinload(HealthExam.additional_history),
                 selectinload(HealthExam.personal_histories), selectinload(HealthExam.clinical_results),
                 selectinload(HealthExam.paraclinical_results))
        .filter(HealthExam.campaign_id == campaign_id)
        .order_by(HealthExam.exam_id.desc()).all())
    exams_by_id = {item.exam_id: item for item in campaign_exams}
    exams_by_patient = {}
    for item in campaign_exams:
        exams_by_patient.setdefault(item.patient_id, item)
    try:
        for row_number, row in enumerate(sheet.iter_rows(min_row=5, values_only=True), 5):
            patient_id_value = val(row, 1)
            if empty(patient_id_value):
                if any(not empty(val(row, c)) for c in range(7, data_last_column + 1)):
                    raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: thiáº¿u PatientId.")
                continue
            try:
                patient_id = int(patient_id_value)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: PatientId khÃ´ng há»£p lá»‡.")
            if patient_id in seen_patient_ids:
                raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: PatientId {patient_id} bá»‹ láº·p.")
            seen_patient_ids.add(patient_id)
            patient = campaign_patients.get(patient_id)
            if not patient:
                raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: há»“ sÆ¡ {patient_id} khÃ´ng thuá»™c Ä‘á»£t khÃ¡m Ä‘ang chá»n.")
            exam_id_value = val(row, 2)
            exam = None
            if not empty(exam_id_value):
                try:
                    exam_id = int(exam_id_value)
                except (TypeError, ValueError):
                    raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: ExamId khÃ´ng há»£p lá»‡.")
                exam = exams_by_id.get(exam_id)
                if not exam or exam.patient_id != patient_id or exam.campaign_id != campaign_id:
                    raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: ExamId khÃ´ng khá»›p bá»‡nh nhÃ¢n/Ä‘á»£t khÃ¡m.")
            else:
                exam = exams_by_patient.get(patient_id)
            if not any(not empty(val(row, c)) for c in range(23, data_last_column + 1)):
                skipped += 1
                continue
            if exam is None:
                exam = HealthExam(patient_id=patient_id, campaign_id=campaign_id,
                                  exam_code=f"TMP-{uuid4().hex[:24]}", exam_date=None,
                                  status="Draft", created_at=datetime.now())
                db.add(exam)
                db.flush()
                exam.exam_code = make_exam_code(exam)
                exams_by_id[exam.exam_id] = exam
                exams_by_patient[patient_id] = exam
                created += 1

            mark_exam_changed_after_linkage(exam)
            for column, field in scalar_fields.items():
                value = val(row, column)
                if empty(value):
                    continue
                if field in {"height_cm", "weight_kg", "bmi", "pulse_per_minute"}:
                    try:
                        number = float(str(value).replace(",", "."))
                        value = int(number) if field == "pulse_per_minute" else number
                    except (TypeError, ValueError):
                        raise HTTPException(status_code=422, detail=f"DÃ²ng {row_number}: cá»™t {headers[column - 1]} pháº£i lÃ  sá»‘.")
                else:
                    value = text_value(value)
                setattr(exam, field, value)
            icd_codes_value = val(row, icd_codes_column)
            if not empty(icd_codes_value):
                icd_codes_value = text_value(icd_codes_value)
                if len(icd_codes_value) > 255:
                    raise HTTPException(status_code=422, detail=f"Dòng {row_number}: Mã bệnh ICD-10 không được dài quá 255 ký tự.")
                if any(not code.strip() for code in icd_codes_value.split(";")):
                    raise HTTPException(status_code=422, detail=f"Dòng {row_number}: các mã ICD-10 phân cách bằng dấu chấm phẩy (;), không để mục rỗng.")
                exam.conclusion_disease_codes = icd_codes_value
            if not empty(val(row, 52)):
                exam.exam_date = parse_date(val(row, 52), row_number, "NgÃ y khÃ¡m")
            if not empty(val(row, 110)):
                exam.conclusion_date = parse_date(val(row, 110), row_number, "NgÃ y káº¿t luáº­n").date()

            family_flag, family_detail = val(row, 26), val(row, 27)
            if not empty(family_flag) or not empty(family_detail):
                flag = parse_yes_no(family_flag, row_number, "Tiá»n sá»­ gia Ä‘Ã¬nh") if not empty(family_flag) else True
                if exam.family_history:
                    exam.family_history.has_history = flag
                    if not empty(family_detail):
                        exam.family_history.detail = text_value(family_detail)
                else:
                    exam.family_history = ExamFamilyHistory(has_history=flag,
                        detail=text_value(family_detail) if not empty(family_detail) else None)
            treatment, obstetric = val(row, 28), val(row, 29)
            if not empty(treatment) or not empty(obstetric):
                if not exam.additional_history:
                    exam.additional_history = ExamAdditionalHistory()
                if not empty(treatment):
                    exam.additional_history.current_treatment = text_value(treatment)
                if not empty(obstetric):
                    exam.additional_history.obstetric_history = text_value(obstetric)

            personal_by_code = {item.history_code: item for item in exam.personal_histories}
            for offset in range(22):
                value = val(row, 30 + offset)
                if empty(value):
                    continue
                code = f"H{offset + 1:02d}"
                try:
                    has_condition, detail = parse_yes_no(value, row_number, headers[29 + offset]), None
                except HTTPException:
                    has_condition, detail = True, text_value(value)
                item = personal_by_code.get(code)
                if item:
                    item.has_condition = has_condition
                    if detail:
                        item.detail = detail
                else:
                    item = ExamPersonalHistory(exam_id=exam.exam_id, history_code=code,
                                               has_condition=has_condition, detail=detail)
                    db.add(item)
                    exam.personal_histories.append(item)

            clinical_by_code = {item.examination_code: item for item in exam.clinical_results}
            for offset, code in enumerate(clinical_codes):
                result_value, doctor_value = val(row, 59 + offset), val(row, 73 + offset)
                extras = {prefix: text_value(val(row, 87 + i)) for i, prefix in enumerate(extra_keys)
                          if not empty(val(row, 87 + i))}
                existing = clinical_by_code.get(code)
                if empty(result_value) and empty(doctor_value) and not extras:
                    continue
                old_base, old_extras = [], {}
                for line in (existing.result_detail or "").splitlines() if existing else []:
                    for prefix in extra_keys:
                        if line.startswith(f"{prefix}:"):
                            old_extras[prefix] = line.split(":", 1)[1].strip()
                            break
                    else:
                        if line.strip():
                            old_base.append(line)
                old_extras.update(extras)
                if not empty(result_value):
                    old_base = [text_value(result_value)]
                details = old_base + [f"{key}: {value}" for key, value in old_extras.items() if value]
                if existing:
                    if details:
                        existing.result_detail = "\n".join(details)
                    if not empty(doctor_value):
                        existing.doctor_name = text_value(doctor_value)
                else:
                    item = ExamClinicalResult(exam_id=exam.exam_id, examination_code=code,
                        result_detail="\n".join(details) or None,
                        doctor_name=text_value(doctor_value) if not empty(doctor_value) else None)
                    db.add(item)
                    exam.clinical_results.append(item)

            lab_by_code = {item.test_code: item for item in exam.paraclinical_results}
            for offset, code in enumerate(paraclinical_codes):
                value = val(row, 96 + offset)
                if empty(value):
                    continue
                item = lab_by_code.get(code)
                if item:
                    item.result_value = text_value(value)
                else:
                    item = ExamParaclinicalResult(exam_id=exam.exam_id, test_code=code,
                        test_name=text_value(headers[95 + offset]) or code, result_value=text_value(value))
                    db.add(item)
                    exam.paraclinical_results.append(item)
            exam.updated_at = datetime.now()
            updated += 1
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    return {"created": created, "updated": updated, "skipped": skipped,
            "message": f"ÄÃ£ nháº­p {updated} láº§n khÃ¡m; táº¡o má»›i {created}, bá» qua {skipped} dÃ²ng trá»‘ng."}


WEB_ROOT = Path(__file__).resolve().parents[2]
app.mount("/", StaticFiles(directory=WEB_ROOT, html=True), name="frontend")
