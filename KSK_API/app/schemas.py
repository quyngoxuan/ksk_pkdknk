from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class PatientBase(APIModel):
    shs: str | None = Field(default=None, max_length=30, description="Số hồ sơ sức khỏe")
    full_name: str = Field(min_length=1, max_length=200)
    gender: int | None = Field(default=None, ge=1, le=2, description="1: Nam, 2: Nữ")
    date_of_birth: date | None = None
    phone: str | None = Field(default=None, max_length=20)
    mst: str | None = Field(default=None, max_length=30, description="Ma so thue cua don vi")
    identity_number: str | None = Field(default=None, max_length=30)
    identity_issue_date: date | None = None
    identity_issue_place: str | None = Field(default=None, max_length=200)
    ethnicity: str | None = Field(default=None, max_length=100)
    ethnicity_code: str | None = Field(default=None, max_length=2)
    blood_group: str | None = Field(default=None, max_length=10)
    province: str | None = Field(default=None, max_length=100)
    province_code: str | None = Field(default=None, max_length=3)
    ward: str | None = Field(default=None, max_length=100)
    ward_code: str | None = Field(default=None, max_length=5)
    address_detail: str | None = Field(default=None, max_length=300)
    occupation: str | None = Field(default=None, max_length=200)
    occupation_code: str | None = Field(default=None, max_length=2)
    workplace: str | None = Field(default=None, max_length=300)


class CompanyBase(APIModel):
    name: str = Field(min_length=1, max_length=300, examples=["Công ty cổ phần ABC"])
    mst: str | None = Field(default=None, max_length=30, examples=["0101234567"])
    description: str | None = Field(default=None, max_length=1000)


class CompanyCreate(CompanyBase):
    pass


class CompanyUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=300)
    mst: str | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=1000)


class CompanyRead(CompanyBase):
    company_id: int
    created_at: datetime
    updated_at: datetime | None = None


class ExamCampaignBase(APIModel):
    company_id: int = Field(gt=0, description="ID đơn vị sở hữu đợt khám")
    campaign_name: str = Field(min_length=1, max_length=300, examples=["Khám sức khỏe định kỳ năm 2026"])
    start_date: date
    end_date: date | None = None
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool = True


class ExamCampaignCreate(ExamCampaignBase):
    pass


class ExamCampaignUpdate(APIModel):
    campaign_name: str | None = Field(default=None, min_length=1, max_length=300)
    start_date: date | None = None
    end_date: date | None = None
    description: str | None = Field(default=None, max_length=1000)
    is_active: bool | None = None


class ExamCampaignRead(ExamCampaignBase):
    campaign_id: int
    created_at: datetime
    updated_at: datetime | None = None


class PatientCreate(PatientBase):
    pass


class PatientCreateForCampaign(PatientCreate):
    """Create one patient directly from the KSK form and attach the selected campaign."""
    campaign_id: int = Field(gt=0)


class PatientUpdate(PatientBase):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)


class PatientRead(PatientBase):
    patient_id: int
    created_at: datetime
    updated_at: datetime | None = None
    exam_date: datetime | None = None


class PatientPage(APIModel):
    items: list[PatientRead]
    total: int
    page: int
    page_size: int


class AdministrativeProvinceRead(APIModel):
    province_code: str
    province_name: str


class AdministrativeWardRead(APIModel):
    ward_code: str
    province_code: str
    ward_name: str
    ward_type: str


class PatientBulkImport(APIModel):
    company_id: int = Field(gt=0, description="Đơn vị được chọn khi nhập")
    campaign_id: int = Field(gt=0, description="Đợt khám thuộc đơn vị được chọn")
    patients: list[PatientCreate] = Field(min_length=1, max_length=2000)
    replace_campaign: bool = Field(default=False, description="Thay thế toàn bộ hồ sơ của đợt khám đã chọn")


class PatientImportIssue(APIModel):
    row_number: int
    message: str


class DeleteResult(APIModel):
    deleted: int
    message: str


class LienThongPushRequest(APIModel):
    raw_data: str = Field(min_length=1, description="Noi dung XML KSK theo Quyết định 2062/QĐ-BYT trước khi mã hóa Base64")
    data_type: Literal["xml/base64"] = "xml/base64"
    signature: str = Field(min_length=1, description="Chữ ký số/chữ ký thông điệp Base64 theo quy định của đơn vị cấp tài khoản")


class LienThongEnvelopeHeader(APIModel):
    version: str
    sender_id: str
    receiver_id: str
    txn_type: str
    msg_type: str
    data_type: Literal["xml/base64"]
    send_datetime: int
    msg_id: str


class LienThongEnvelopeData(APIModel):
    content: str = Field(min_length=1, description="XML đã mã hóa Base64")


class LienThongEnvelope(APIModel):
    header: LienThongEnvelopeHeader
    data: LienThongEnvelopeData
    signature: str = Field(min_length=1, description="Chữ ký Base64 của XML")


class LienThongBatchCreate(APIModel):
    company_id: int = Field(gt=0)
    campaign_id: int = Field(gt=0)
    exam_ids: list[int] = Field(min_length=1, max_length=500)


class LienThongBatchItemUpdate(APIModel):
    status: Literal["Signing", "Signed", "Sending", "Success", "Rejected", "Failed", "Uncertain", "NotReady"]
    xml_sha256: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")
    message_id: str | None = Field(default=None, max_length=100)
    transaction_code: str | None = Field(default=None, max_length=100)
    response_payload: str | None = Field(default=None, max_length=200000)
    last_error: str | None = Field(default=None, max_length=2000)


class LienThongBatchItemRead(APIModel):
    batch_item_id: int
    exam_id: int
    status: str
    xml_sha256: str | None = None
    message_id: str | None = None
    transaction_code: str | None = None
    response_payload: str | None = None
    last_error: str | None = None
    created_at: datetime
    signed_at: datetime | None = None
    sent_at: datetime | None = None


class LienThongBatchRead(APIModel):
    batch_id: int
    company_id: int
    campaign_id: int
    status: str
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    items: list[LienThongBatchItemRead] = []


class PatientBulkImportResult(APIModel):
    inserted: int
    linked: int = 0
    skipped: int = 0
    failed: int
    issues: list[PatientImportIssue] = []


class FamilyHistoryInput(APIModel):
    has_history: bool
    detail: str | None = None


class AdditionalHistoryInput(APIModel):
    current_treatment: str | None = None
    obstetric_history: str | None = None


class PersonalHistoryInput(APIModel):
    history_code: str = Field(min_length=1, max_length=20, examples=["H01"])
    has_condition: bool | None = None
    detail: str | None = Field(default=None, max_length=1000)


class ClinicalResultInput(APIModel):
    examination_code: str = Field(min_length=1, max_length=50, examples=["EYE"])
    result_detail: str | None = None
    classification: str | None = Field(default=None, max_length=100)
    doctor_name: str | None = Field(default=None, max_length=200)


class ParaclinicalResultInput(APIModel):
    test_code: str = Field(min_length=1, max_length=50, examples=["GLUCOSE"])
    test_name: str = Field(min_length=1, max_length=200, examples=["Đường máu"])
    result_value: str | None = None
    unit: str | None = Field(default=None, max_length=50)
    reference_range: str | None = Field(default=None, max_length=200)
    doctor_name: str | None = Field(default=None, max_length=200)


class HealthExamBase(APIModel):
    patient_id: int
    campaign_id: int | None = Field(default=None, gt=0)
    exam_code: str = Field(min_length=1, max_length=30, examples=["KSK-20260927-0001"])
    facility_id: int | None = None
    visit_code: str | None = Field(default=None, max_length=100)
    exam_type_code: str | None = Field(default=None, max_length=2)
    subject_codes: str | None = Field(default=None, max_length=50)
    payment_source_code: int | None = Field(default=None, ge=1, le=9)
    exam_date: datetime | None = None
    subject_type: str | None = Field(default=None, max_length=150)
    payment_source: str | None = Field(default=None, max_length=150)
    exam_reason: str | None = Field(default=None, max_length=500)
    height_cm: float | None = Field(default=None, ge=0, le=300)
    weight_kg: float | None = Field(default=None, ge=0, le=1000)
    bmi: float | None = Field(default=None, ge=0, le=100)
    pulse_per_minute: int | None = Field(default=None, ge=0, le=300)
    blood_pressure: str | None = Field(default=None, max_length=20)
    physical_classification: str | None = Field(default=None, max_length=100)
    health_status: str | None = None
    health_classification: str | None = Field(default=None, max_length=100)
    conclusion_date: date | None = None
    conclusion_by: str | None = Field(default=None, max_length=200)
    conclusion_note: str | None = Field(default=None, max_length=500)
    conclusion_disease_codes: str | None = Field(default=None, max_length=255)
    status: Literal["Draft", "Completed", "Cancelled"] = "Draft"


class HealthExamCreate(HealthExamBase):
    # MaHS/ExamCode is allocated by the API after SQL Server creates ExamId.
    # Accepting it as optional preserves compatibility with older clients.
    exam_code: str | None = Field(default=None, max_length=30, examples=["KSK-2026-00002-00000042"])
    family_history: FamilyHistoryInput | None = None
    additional_history: AdditionalHistoryInput | None = None
    personal_histories: list[PersonalHistoryInput] = []
    clinical_results: list[ClinicalResultInput] = []
    paraclinical_results: list[ParaclinicalResultInput] = []


class HealthExamUpdate(APIModel):
    exam_date: datetime | None = None
    facility_id: int | None = None
    visit_code: str | None = Field(default=None, max_length=100)
    exam_type_code: str | None = Field(default=None, max_length=2)
    subject_codes: str | None = Field(default=None, max_length=50)
    payment_source_code: int | None = Field(default=None, ge=1, le=9)
    subject_type: str | None = Field(default=None, max_length=150)
    payment_source: str | None = Field(default=None, max_length=150)
    exam_reason: str | None = Field(default=None, max_length=500)
    height_cm: float | None = Field(default=None, ge=0, le=300)
    weight_kg: float | None = Field(default=None, ge=0, le=1000)
    bmi: float | None = Field(default=None, ge=0, le=100)
    pulse_per_minute: int | None = Field(default=None, ge=0, le=300)
    blood_pressure: str | None = Field(default=None, max_length=20)
    physical_classification: str | None = Field(default=None, max_length=100)
    health_status: str | None = None
    health_classification: str | None = Field(default=None, max_length=100)
    conclusion_date: date | None = None
    conclusion_by: str | None = Field(default=None, max_length=200)
    conclusion_note: str | None = Field(default=None, max_length=500)
    conclusion_disease_codes: str | None = Field(default=None, max_length=255)
    status: Literal["Draft", "Completed", "Cancelled"] | None = None


class FamilyHistoryRead(FamilyHistoryInput):
    family_history_id: int


class PersonalHistoryRead(PersonalHistoryInput):
    personal_history_id: int


class ClinicalResultRead(ClinicalResultInput):
    clinical_result_id: int


class ParaclinicalResultRead(ParaclinicalResultInput):
    paraclinical_result_id: int


class HealthExamRead(HealthExamBase):
    exam_id: int
    lien_thong_status: str = "NotSent"
    lien_thong_at: datetime | None = None
    lien_thong_batch_item_id: int | None = None
    lien_thong_transaction_code: str | None = None
    lien_thong_message_id: str | None = None
    lien_thong_last_error: str | None = None
    lien_thong_xml_sha256: str | None = None
    created_at: datetime
    updated_at: datetime | None = None


class HealthExamDetail(HealthExamRead):
    patient: PatientRead
    family_history: FamilyHistoryRead | None = None
    additional_history: AdditionalHistoryInput | None = None
    personal_histories: list[PersonalHistoryRead] = []
    clinical_results: list[ClinicalResultRead] = []
    paraclinical_results: list[ParaclinicalResultRead] = []


class KskFieldValueInput(APIModel):
    field_code: str = Field(min_length=1, max_length=80, pattern=r"^[A-Z0-9_]+$")
    field_value: str | None = None


class FacilityProfileInput(APIModel):
    facility_code: str = Field(min_length=5, max_length=5, pattern=r"^\d{5}$")
    gln_code: str = Field(min_length=13, max_length=13, pattern=r"^\d{13}$")
    facility_name: str = Field(min_length=1, max_length=300)
    is_default: bool = False
    is_active: bool = True


class FacilityProfileRead(FacilityProfileInput):
    facility_id: int
    created_at: datetime
    updated_at: datetime | None = None


class LinkageValidationIssue(APIModel):
    field_code: str
    field_name: str
    message: str


class LinkageReadiness(APIModel):
    exam_id: int
    form_code: str
    ready: bool
    errors: list[LinkageValidationIssue] = []
    warnings: list[LinkageValidationIssue] = []
