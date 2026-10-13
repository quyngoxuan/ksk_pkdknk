from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, LargeBinary, Numeric, SmallInteger, String, Text, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Patient(Base):
    __tablename__ = "Patients"

    patient_id: Mapped[int] = mapped_column("PatientId", BigInteger, primary_key=True)
    shs: Mapped[str | None] = mapped_column("SHS", String(30))
    full_name: Mapped[str] = mapped_column("FullName", Unicode(200), nullable=False)
    gender: Mapped[int | None] = mapped_column("Gender", SmallInteger)
    date_of_birth: Mapped[date | None] = mapped_column("DateOfBirth", Date)
    phone: Mapped[str | None] = mapped_column("Phone", String(20))
    mst: Mapped[str | None] = mapped_column("MST", String(30))
    identity_number: Mapped[str | None] = mapped_column("IdentityNumber", String(30))
    identity_issue_date: Mapped[date | None] = mapped_column("IdentityIssueDate", Date)
    identity_issue_place: Mapped[str | None] = mapped_column("IdentityIssuePlace", Unicode(200))
    ethnicity: Mapped[str | None] = mapped_column("Ethnicity", Unicode(100))
    ethnicity_code: Mapped[str | None] = mapped_column("EthnicityCode", String(2))
    blood_group: Mapped[str | None] = mapped_column("BloodGroup", String(10))
    province: Mapped[str | None] = mapped_column("Province", Unicode(100))
    province_code: Mapped[str | None] = mapped_column("ProvinceCode", String(3))
    ward: Mapped[str | None] = mapped_column("Ward", Unicode(100))
    ward_code: Mapped[str | None] = mapped_column("WardCode", String(5))
    address_detail: Mapped[str | None] = mapped_column("AddressDetail", Unicode(300))
    occupation: Mapped[str | None] = mapped_column("Occupation", Unicode(200))
    occupation_code: Mapped[str | None] = mapped_column("OccupationCode", String(2))
    workplace: Mapped[str | None] = mapped_column("Workplace", Unicode(300))
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime)
    updated_at: Mapped[datetime | None] = mapped_column("UpdatedAt", DateTime)
    exams: Mapped[list["HealthExam"]] = relationship(back_populates="patient")
    campaign_links: Mapped[list["PatientExamCampaign"]] = relationship(back_populates="patient", cascade="all, delete-orphan")


class Company(Base):
    __tablename__ = "Companys"

    company_id: Mapped[int] = mapped_column("ID", BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column("Name", Unicode(300), nullable=False)
    mst: Mapped[str | None] = mapped_column("MST", String(30))
    description: Mapped[str | None] = mapped_column("Desc", Unicode(1000))
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime)
    updated_at: Mapped[datetime | None] = mapped_column("UpdatedAt", DateTime)
    exam_campaigns: Mapped[list["ExamCampaign"]] = relationship(back_populates="company")


class AdministrativeProvince(Base):
    __tablename__ = "AdministrativeProvinces"

    province_code: Mapped[str] = mapped_column("ProvinceCode", String(2), primary_key=True)
    province_name: Mapped[str] = mapped_column("ProvinceName", Unicode(100), nullable=False)
    effective_from: Mapped[date] = mapped_column("EffectiveFrom", Date, nullable=False)
    is_active: Mapped[bool] = mapped_column("IsActive", nullable=False)
    wards: Mapped[list["AdministrativeWard"]] = relationship(back_populates="province")


class AdministrativeWard(Base):
    __tablename__ = "AdministrativeWards"

    ward_code: Mapped[str] = mapped_column("WardCode", String(5), primary_key=True)
    province_code: Mapped[str] = mapped_column("ProvinceCode", ForeignKey("AdministrativeProvinces.ProvinceCode"), nullable=False)
    ward_name: Mapped[str] = mapped_column("WardName", Unicode(150), nullable=False)
    ward_type: Mapped[str] = mapped_column("WardType", Unicode(20), nullable=False)
    effective_from: Mapped[date] = mapped_column("EffectiveFrom", Date, nullable=False)
    is_active: Mapped[bool] = mapped_column("IsActive", nullable=False)
    province: Mapped[AdministrativeProvince] = relationship(back_populates="wards")


class ExamCampaign(Base):
    __tablename__ = "ExamCampaigns"

    campaign_id: Mapped[int] = mapped_column("CampaignId", BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column("CompanyId", ForeignKey("Companys.ID"), nullable=False)
    campaign_name: Mapped[str] = mapped_column("CampaignName", Unicode(300), nullable=False)
    start_date: Mapped[date] = mapped_column("StartDate", Date, nullable=False)
    end_date: Mapped[date | None] = mapped_column("EndDate", Date)
    description: Mapped[str | None] = mapped_column("Desc", Unicode(1000))
    is_active: Mapped[bool] = mapped_column("IsActive")
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime)
    updated_at: Mapped[datetime | None] = mapped_column("UpdatedAt", DateTime)
    company: Mapped["Company"] = relationship(back_populates="exam_campaigns")
    patient_links: Mapped[list["PatientExamCampaign"]] = relationship(back_populates="campaign")
    health_exams: Mapped[list["HealthExam"]] = relationship(back_populates="campaign")


class PatientExamCampaign(Base):
    __tablename__ = "PatientExamCampaigns"

    patient_exam_campaign_id: Mapped[int] = mapped_column("PatientExamCampaignId", BigInteger, primary_key=True)
    patient_id: Mapped[int] = mapped_column("PatientId", ForeignKey("Patients.PatientId"), nullable=False)
    campaign_id: Mapped[int] = mapped_column("CampaignId", ForeignKey("ExamCampaigns.CampaignId"), nullable=False)
    imported_at: Mapped[datetime] = mapped_column("ImportedAt", DateTime)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime)
    patient: Mapped["Patient"] = relationship(back_populates="campaign_links")
    campaign: Mapped["ExamCampaign"] = relationship(back_populates="patient_links")


class HealthExam(Base):
    __tablename__ = "HealthExams"

    exam_id: Mapped[int] = mapped_column("ExamId", BigInteger, primary_key=True)
    patient_id: Mapped[int] = mapped_column("PatientId", ForeignKey("Patients.PatientId"), nullable=False)
    campaign_id: Mapped[int | None] = mapped_column("CampaignId", ForeignKey("ExamCampaigns.CampaignId"))
    exam_code: Mapped[str] = mapped_column("ExamCode", String(30), unique=True, nullable=False)
    facility_id: Mapped[int | None] = mapped_column("FacilityId", ForeignKey("KskFacilityProfiles.FacilityId"))
    visit_code: Mapped[str | None] = mapped_column("VisitCode", String(100))
    exam_type_code: Mapped[str | None] = mapped_column("ExamTypeCode", String(2))
    subject_codes: Mapped[str | None] = mapped_column("SubjectCodes", String(50))
    payment_source_code: Mapped[int | None] = mapped_column("PaymentSourceCode", SmallInteger)
    exam_date: Mapped[datetime | None] = mapped_column("ExamDate", DateTime, nullable=True)
    subject_type: Mapped[str | None] = mapped_column("SubjectType", Unicode(150))
    payment_source: Mapped[str | None] = mapped_column("PaymentSource", Unicode(150))
    exam_reason: Mapped[str | None] = mapped_column("ExamReason", Unicode(500))
    height_cm: Mapped[float | None] = mapped_column("HeightCm", Numeric(5, 2))
    weight_kg: Mapped[float | None] = mapped_column("WeightKg", Numeric(5, 2))
    bmi: Mapped[float | None] = mapped_column("BMI", Numeric(5, 2))
    pulse_per_minute: Mapped[int | None] = mapped_column("PulsePerMinute", SmallInteger)
    blood_pressure: Mapped[str | None] = mapped_column("BloodPressure", String(20))
    physical_classification: Mapped[str | None] = mapped_column("PhysicalClassification", Unicode(100))
    health_status: Mapped[str | None] = mapped_column("HealthStatus", UnicodeText)
    health_classification: Mapped[str | None] = mapped_column("HealthClassification", Unicode(100))
    conclusion_date: Mapped[date | None] = mapped_column("ConclusionDate", Date)
    conclusion_by: Mapped[str | None] = mapped_column("ConclusionBy", Unicode(200))
    conclusion_note: Mapped[str | None] = mapped_column("ConclusionNote", Unicode(500))
    conclusion_disease_codes: Mapped[str | None] = mapped_column("ConclusionDiseaseCodes", String(255))
    status: Mapped[str] = mapped_column("Status", String(20), nullable=False)
    lien_thong_status: Mapped[str] = mapped_column("LienThongStatus", String(30), nullable=False, default="NotSent")
    lien_thong_at: Mapped[datetime | None] = mapped_column("LienThongAt", DateTime)
    lien_thong_batch_item_id: Mapped[int | None] = mapped_column("LienThongBatchItemId", BigInteger)
    lien_thong_transaction_code: Mapped[str | None] = mapped_column("LienThongTransactionCode", String(100))
    lien_thong_message_id: Mapped[str | None] = mapped_column("LienThongMessageId", String(100))
    lien_thong_last_error: Mapped[str | None] = mapped_column("LienThongLastError", Unicode(2000))
    lien_thong_xml_sha256: Mapped[str | None] = mapped_column("LienThongXmlSha256", String(64))
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime)
    updated_at: Mapped[datetime | None] = mapped_column("UpdatedAt", DateTime)
    patient: Mapped[Patient] = relationship(back_populates="exams")
    campaign: Mapped["ExamCampaign | None"] = relationship(back_populates="health_exams")
    facility: Mapped["KskFacilityProfile | None"] = relationship()
    family_history: Mapped["ExamFamilyHistory | None"] = relationship(back_populates="exam", uselist=False, cascade="all, delete-orphan")
    additional_history: Mapped["ExamAdditionalHistory | None"] = relationship(back_populates="exam", uselist=False, cascade="all, delete-orphan")
    personal_histories: Mapped[list["ExamPersonalHistory"]] = relationship(back_populates="exam", cascade="all, delete-orphan")
    clinical_results: Mapped[list["ExamClinicalResult"]] = relationship(back_populates="exam", cascade="all, delete-orphan")
    paraclinical_results: Mapped[list["ExamParaclinicalResult"]] = relationship(back_populates="exam", cascade="all, delete-orphan")
    ksk_field_values: Mapped[list["ExamKskFieldValue"]] = relationship(back_populates="exam", cascade="all, delete-orphan")


class Icd10Code(Base):
    __tablename__ = "Icd10Codes"

    code: Mapped[str] = mapped_column("Code", String(10), primary_key=True)
    name_vi: Mapped[str] = mapped_column("NameVi", Unicode(500), nullable=False)
    source: Mapped[str] = mapped_column("Source", String(40), nullable=False, default="TT06/2026/TT-BYT")


class LienThongBatch(Base):
    __tablename__ = "LienThongBatch"

    batch_id: Mapped[int] = mapped_column("BatchId", BigInteger, primary_key=True)
    company_id: Mapped[int] = mapped_column("CompanyId", ForeignKey("Companys.ID"), nullable=False)
    campaign_id: Mapped[int] = mapped_column("CampaignId", ForeignKey("ExamCampaigns.CampaignId"), nullable=False)
    status: Mapped[str] = mapped_column("Status", String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column("StartedAt", DateTime)
    completed_at: Mapped[datetime | None] = mapped_column("CompletedAt", DateTime)
    items: Mapped[list["LienThongBatchItem"]] = relationship(back_populates="batch", cascade="all, delete-orphan")


class LienThongBatchItem(Base):
    __tablename__ = "LienThongBatchItem"

    batch_item_id: Mapped[int] = mapped_column("BatchItemId", BigInteger, primary_key=True)
    batch_id: Mapped[int] = mapped_column("BatchId", ForeignKey("LienThongBatch.BatchId", ondelete="CASCADE"), nullable=False)
    exam_id: Mapped[int] = mapped_column("ExamId", ForeignKey("HealthExams.ExamId"), nullable=False)
    status: Mapped[str] = mapped_column("Status", String(20), nullable=False)
    xml_sha256: Mapped[str | None] = mapped_column("XmlSha256", String(64))
    message_id: Mapped[str | None] = mapped_column("MessageId", String(100))
    transaction_code: Mapped[str | None] = mapped_column("TransactionCode", String(100))
    response_payload: Mapped[str | None] = mapped_column("ResponsePayload", UnicodeText)
    last_error: Mapped[str | None] = mapped_column("LastError", Unicode(2000))
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime, nullable=False)
    signed_at: Mapped[datetime | None] = mapped_column("SignedAt", DateTime)
    sent_at: Mapped[datetime | None] = mapped_column("SentAt", DateTime)
    batch: Mapped[LienThongBatch] = relationship(back_populates="items")


class KskFacilityProfile(Base):
    __tablename__ = "KskFacilityProfiles"

    facility_id: Mapped[int] = mapped_column("FacilityId", BigInteger, primary_key=True)
    facility_code: Mapped[str] = mapped_column("FacilityCode", String(5), nullable=False)
    gln_code: Mapped[str] = mapped_column("GlnCode", String(13), nullable=False)
    facility_name: Mapped[str] = mapped_column("FacilityName", Unicode(300), nullable=False)
    is_default: Mapped[bool] = mapped_column("IsDefault")
    is_active: Mapped[bool] = mapped_column("IsActive")
    created_at: Mapped[datetime] = mapped_column("CreatedAt", DateTime)
    updated_at: Mapped[datetime | None] = mapped_column("UpdatedAt", DateTime)


class KskXmlFieldDefinition(Base):
    __tablename__ = "KskXmlFieldDefinitions"

    field_definition_id: Mapped[int] = mapped_column("FieldDefinitionId", BigInteger, primary_key=True)
    form_code: Mapped[str] = mapped_column("FormCode", String(20))
    field_code: Mapped[str] = mapped_column("FieldCode", String(80))
    field_name: Mapped[str] = mapped_column("FieldName", Unicode(255))
    data_type: Mapped[str] = mapped_column("DataType", String(20))
    max_length: Mapped[int | None] = mapped_column("MaxLength")
    is_required: Mapped[bool] = mapped_column("IsRequired")
    display_order: Mapped[int] = mapped_column("DisplayOrder", SmallInteger)
    is_active: Mapped[bool] = mapped_column("IsActive")


class ExamKskFieldValue(Base):
    __tablename__ = "ExamKskFieldValues"

    field_value_id: Mapped[int] = mapped_column("ExamKskFieldValueId", BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column("ExamId", ForeignKey("HealthExams.ExamId"))
    field_code: Mapped[str] = mapped_column("FieldCode", String(80))
    field_value: Mapped[str | None] = mapped_column("FieldValue", UnicodeText)
    source_type: Mapped[str] = mapped_column("SourceType", String(30))
    updated_at: Mapped[datetime] = mapped_column("UpdatedAt", DateTime)
    exam: Mapped[HealthExam] = relationship(back_populates="ksk_field_values")


class ExamFamilyHistory(Base):
    __tablename__ = "ExamFamilyHistories"
    family_history_id: Mapped[int] = mapped_column("FamilyHistoryId", BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column("ExamId", ForeignKey("HealthExams.ExamId"), unique=True)
    has_history: Mapped[bool] = mapped_column("HasHistory")
    detail: Mapped[str | None] = mapped_column("Detail", UnicodeText)
    exam: Mapped[HealthExam] = relationship(back_populates="family_history")


class ExamPersonalHistory(Base):
    __tablename__ = "ExamPersonalHistories"
    personal_history_id: Mapped[int] = mapped_column("PersonalHistoryId", BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column("ExamId", ForeignKey("HealthExams.ExamId"))
    history_code: Mapped[str] = mapped_column("HistoryCode", String(20))
    has_condition: Mapped[bool | None] = mapped_column("HasCondition")
    detail: Mapped[str | None] = mapped_column("Detail", Unicode(1000))
    exam: Mapped[HealthExam] = relationship(back_populates="personal_histories")


class ExamAdditionalHistory(Base):
    __tablename__ = "ExamAdditionalHistories"
    exam_id: Mapped[int] = mapped_column("ExamId", ForeignKey("HealthExams.ExamId"), primary_key=True)
    current_treatment: Mapped[str | None] = mapped_column("CurrentTreatment", UnicodeText)
    obstetric_history: Mapped[str | None] = mapped_column("ObstetricHistory", UnicodeText)
    exam: Mapped[HealthExam] = relationship(back_populates="additional_history")


class ExamClinicalResult(Base):
    __tablename__ = "ExamClinicalResults"
    clinical_result_id: Mapped[int] = mapped_column("ClinicalResultId", BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column("ExamId", ForeignKey("HealthExams.ExamId"))
    examination_code: Mapped[str] = mapped_column("ExaminationCode", String(50))
    result_detail: Mapped[str | None] = mapped_column("ResultDetail", UnicodeText)
    classification: Mapped[str | None] = mapped_column("Classification", Unicode(100))
    doctor_name: Mapped[str | None] = mapped_column("DoctorName", Unicode(200))
    doctor_signature: Mapped[bytes | None] = mapped_column("DoctorSignature", LargeBinary)
    exam: Mapped[HealthExam] = relationship(back_populates="clinical_results")


class ExamParaclinicalResult(Base):
    __tablename__ = "ExamParaclinicalResults"
    paraclinical_result_id: Mapped[int] = mapped_column("ParaclinicalResultId", BigInteger, primary_key=True)
    exam_id: Mapped[int] = mapped_column("ExamId", ForeignKey("HealthExams.ExamId"))
    test_code: Mapped[str] = mapped_column("TestCode", String(50))
    test_name: Mapped[str] = mapped_column("TestName", Unicode(200))
    result_value: Mapped[str | None] = mapped_column("ResultValue", UnicodeText)
    unit: Mapped[str | None] = mapped_column("Unit", Unicode(50))
    reference_range: Mapped[str | None] = mapped_column("ReferenceRange", Unicode(200))
    doctor_name: Mapped[str | None] = mapped_column("DoctorName", Unicode(200))
    exam: Mapped[HealthExam] = relationship(back_populates="paraclinical_results")
