from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class DentistAppointment(BaseModel):
    id: int
    patient_id: int
    patient_name: str
    appointment_date: date
    appointment_time: time
    duration_minutes: int
    procedure: str
    confirmation_status: str
    status: str
    arrival_at: str | None
    created_at: datetime


class DentistDashboardResponse(BaseModel):
    appointments: list[DentistAppointment]
    clinic_open_time: time
    clinic_close_time: time


class DentistPatientAppointment(BaseModel):
    id: int
    appointment_date: date
    appointment_time: time
    duration_minutes: int
    procedure: str
    confirmation_status: str
    status: str


class DentistPatientItem(BaseModel):
    id: int
    name: str
    cpf: str | None
    birth_date: date | None
    phone: str
    email: str | None
    last_appointment_date: date | None
    next_appointment: DentistPatientAppointment | None


class DentistPatientMetrics(BaseModel):
    total: int
    with_upcoming_appointments: int
    in_treatment: int | None
    with_pending_follow_up: int | None


class DentistPatientRegistryResponse(BaseModel):
    items: list[DentistPatientItem]
    total: int
    metrics: DentistPatientMetrics


class DentistAttendanceHistoryChartEntry(BaseModel):
    id: int
    tooth_number: str
    record_type: str
    label: str
    status: str
    surfaces: list[str]
    note: str | None
    record_date: date
    created_at: datetime
    dentist_name: str
    supersedes_entry_id: int | None
    is_superseded: bool


class DentistAttendanceHistoryDocument(BaseModel):
    id: int
    title: str
    document_type: str
    status: Literal["draft"]
    updated_at: datetime


class DentistAttendanceHistoryItem(BaseModel):
    id: int
    appointment_date: date
    appointment_time: time
    duration_minutes: int
    procedure: str
    confirmation_status: str
    status: str
    arrival_at: datetime | None
    patient_id: int
    patient_name: str
    dentist_id: int
    dentist_name: str
    chart_entries: list[DentistAttendanceHistoryChartEntry]
    procedure_count: int
    clinical_records_with_notes_count: int
    clinical_documentation_status: Literal["unknown"]
    document_drafts: list[DentistAttendanceHistoryDocument]


class DentistAttendanceHistoryMetrics(BaseModel):
    completed_attendances: int
    patients_attended: int
    completed_procedures_registered: int
    documentation_pending: int | None


class DentistAttendanceHistoryResponse(BaseModel):
    items: list[DentistAttendanceHistoryItem]
    total: int
    metrics: DentistAttendanceHistoryMetrics


DentalRecordType = Literal["condition", "procedure"]
DentalRecordStatus = Literal[
    "observed", "planned", "in_progress", "completed", "cancelled"
]
DentalSurface = Literal["M", "D", "B", "L", "P", "O", "I"]
TreatmentPlanStatus = Literal["draft", "in_progress", "completed", "cancelled"]
TreatmentProcedureStatus = Literal["planned", "in_progress", "completed", "cancelled"]
TreatmentPriority = Literal["low", "normal", "high", "urgent"]
ClinicalDocumentType = Literal[
    "prescription",
    "certificate",
    "attendance_declaration",
    "referral",
    "other",
]


class DentistClinicalDocumentInput(BaseModel):
    patient_id: int = Field(ge=1)
    appointment_id: int | None = Field(default=None, ge=1)
    document_type: ClinicalDocumentType
    title: str = Field(min_length=2, max_length=160)
    content: str = Field(min_length=1, max_length=12000)

    @field_validator("title")
    @classmethod
    def normalize_document_title(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe o título do rascunho.")
        return normalized

    @field_validator("content")
    @classmethod
    def normalize_document_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Informe o conteúdo do rascunho.")
        return normalized


class DentistClinicalDocumentCreate(DentistClinicalDocumentInput):
    pass


class DentistClinicalDocumentUpdate(DentistClinicalDocumentInput):
    version: int = Field(ge=1)


class DentistClinicalDocumentPatient(BaseModel):
    id: int
    name: str


class DentistClinicalDocumentResponse(DentistClinicalDocumentInput):
    id: int
    version: int
    status: Literal["draft"]
    patient: DentistClinicalDocumentPatient
    dentist_id: int
    dentist_name: str
    created_at: datetime
    updated_at: datetime
    latest_history_id: int | None


class DentistClinicalDocumentAuditResponse(BaseModel):
    id: int
    dentist_id: int
    dentist_name: str
    action: Literal["created", "updated"]
    summary: str
    created_at: datetime


class DentistClinicalDocumentSummary(BaseModel):
    drafts: int
    issued: int | None


class DentistClinicalDocumentRegistryResponse(BaseModel):
    items: list[DentistClinicalDocumentResponse]
    total: int
    metrics: DentistClinicalDocumentSummary


class DentistDentalChartPatient(BaseModel):
    id: int
    name: str
    birth_date: date | None
    last_updated: datetime | None


class DentistDentalChartEntry(BaseModel):
    id: int
    request_id: str
    supersedes_entry_id: int | None
    tooth_number: str
    record_type: DentalRecordType
    label: str
    status: DentalRecordStatus
    surfaces: list[DentalSurface]
    note: str | None
    record_date: date
    created_at: datetime
    dentist_id: int
    dentist_name: str
    appointment_id: int | None
    appointment_date: date | None


class DentistDentalChartResponse(BaseModel):
    patient: DentistDentalChartPatient
    entries: list[DentistDentalChartEntry]
    latest_entry_id: int | None
    appointments: list[DentistPatientAppointment]


class DentistDentalChartEntryCreate(BaseModel):
    request_id: str = Field(
        pattern=r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )
    supersedes_entry_id: int | None = Field(default=None, ge=1)
    expected_latest_id: int | None
    tooth_number: str = Field(pattern=r"^[1-8][1-8]$")
    record_type: DentalRecordType
    label: str = Field(min_length=2, max_length=120)
    status: DentalRecordStatus
    surfaces: list[DentalSurface] = Field(default_factory=list, max_length=5)
    note: str | None = Field(default=None, max_length=2000)
    record_date: date
    appointment_id: int | None = None

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe uma condição ou procedimento.")
        return normalized

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_clinical_record(self) -> "DentistDentalChartEntryCreate":
        quadrant = int(self.tooth_number[0])
        position = int(self.tooth_number[1])
        is_primary = quadrant >= 5
        if (is_primary and position > 5) or (not is_primary and position > 8):
            raise ValueError("Número FDI incompatível com a dentição selecionada.")
        if len(set(self.surfaces)) != len(self.surfaces):
            raise ValueError("Remova superfícies duplicadas.")
        is_anterior = position <= 3
        if is_anterior and "O" in self.surfaces:
            raise ValueError("Dentes anteriores usam superfície incisal, não oclusal.")
        if not is_anterior and "I" in self.surfaces:
            raise ValueError("A superfície incisal não se aplica a dentes posteriores.")
        if self.record_type == "condition":
            if self.status != "observed":
                raise ValueError("Condições clínicas devem ser registradas como observadas.")
            if self.label.casefold() in {"ausência dentária", "dente incluso ou impactado"} and self.surfaces:
                raise ValueError("Esta condição deve ser registrada no dente, sem superfície.")
        elif self.status == "observed":
            raise ValueError("Procedimentos precisam de uma situação válida.")
        if self.status == "completed" and self.record_type != "procedure":
            raise ValueError("Somente procedimentos podem ser concluídos.")
        return self


class DentistTreatmentProcedureInput(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    tooth_number: str | None = Field(default=None, pattern=r"^[1-8][1-8]$")
    surfaces: list[DentalSurface] = Field(default_factory=list, max_length=5)
    priority: TreatmentPriority = "normal"
    stage: str = Field(default="Etapa inicial", min_length=2, max_length=100)
    notes: str | None = Field(default=None, max_length=2000)
    sort_order: int = Field(default=0, ge=0, le=999)

    @field_validator("name", "stage")
    @classmethod
    def normalize_required_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe pelo menos dois caracteres.")
        return normalized

    @field_validator("category", "description", "notes")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None

    @model_validator(mode="after")
    def validate_tooth_surfaces(self) -> "DentistTreatmentProcedureInput":
        if len(set(self.surfaces)) != len(self.surfaces):
            raise ValueError("Remova superfícies duplicadas.")
        if self.tooth_number is None and self.surfaces:
            raise ValueError("Informe o dente para associar superfícies.")
        if self.tooth_number:
            quadrant, position = (int(part) for part in self.tooth_number)
            if (quadrant >= 5 and position > 5) or (quadrant < 5 and position > 8):
                raise ValueError("Número FDI incompatível com a dentição.")
            if position <= 3 and "O" in self.surfaces:
                raise ValueError("Dentes anteriores usam superfície incisal, não oclusal.")
            if position > 3 and "I" in self.surfaces:
                raise ValueError("A superfície incisal não se aplica a dentes posteriores.")
        return self


class DentistTreatmentPlanCreate(BaseModel):
    patient_id: int = Field(ge=1)
    name: str = Field(min_length=2, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    procedures: list[DentistTreatmentProcedureInput] = Field(
        default_factory=list, max_length=100
    )

    @field_validator("name")
    @classmethod
    def normalize_plan_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe o nome do plano.")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_plan_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class DentistTreatmentPlanUpdate(BaseModel):
    version: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)
    action: Literal["start", "cancel"] | None = None

    @field_validator("name")
    @classmethod
    def normalize_updated_plan_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe o nome do plano.")
        return normalized

    @field_validator("notes")
    @classmethod
    def normalize_updated_plan_notes(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class DentistTreatmentProcedureUpdate(DentistTreatmentProcedureInput):
    plan_version: int = Field(ge=1)
    version: int = Field(ge=1)
    status: TreatmentProcedureStatus = "planned"
    completed_odontogram_entry_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def require_clinical_completion_reference(self) -> "DentistTreatmentProcedureUpdate":
        if self.status == "completed" and self.completed_odontogram_entry_id is None:
            raise ValueError("Vincule o registro clínico concluído no odontograma.")
        if self.status != "completed" and self.completed_odontogram_entry_id is not None:
            raise ValueError("O vínculo clínico só se aplica a procedimentos concluídos.")
        return self


class DentistTreatmentProcedureAdd(DentistTreatmentProcedureInput):
    plan_version: int = Field(ge=1)


class DentistTreatmentProcedureResponse(DentistTreatmentProcedureInput):
    id: int
    version: int
    status: TreatmentProcedureStatus
    completed_odontogram_entry_id: int | None
    created_at: datetime
    updated_at: datetime


class DentistTreatmentPlanPatient(BaseModel):
    id: int
    name: str


class DentistTreatmentPlanSummary(BaseModel):
    total: int
    in_progress: int
    awaiting_approval: int | None
    completed: int


class DentistTreatmentPlanResponse(BaseModel):
    id: int
    version: int
    patient: DentistTreatmentPlanPatient
    dentist_id: int
    dentist_name: str
    name: str
    notes: str | None
    status: TreatmentPlanStatus
    created_at: datetime
    updated_at: datetime
    procedures: list[DentistTreatmentProcedureResponse]
    procedure_count: int
    completed_count: int
    in_progress_count: int
    pending_count: int
    progress_percent: int | None
    latest_history_id: int | None


class DentistTreatmentPlanRegistryResponse(BaseModel):
    items: list[DentistTreatmentPlanResponse]
    total: int
    metrics: DentistTreatmentPlanSummary


class DentistTreatmentPlanAuditResponse(BaseModel):
    id: int
    dentist_id: int
    dentist_name: str
    procedure_id: int | None
    action: str
    summary: str
    before_data: dict | None
    after_data: dict | None
    created_at: datetime
