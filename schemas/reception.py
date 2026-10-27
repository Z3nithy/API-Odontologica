import re
from datetime import date, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

AppointmentStatus = Literal[
    "Agendada",
    "Confirmada",
    "Aguardando chegada",
    "Em espera",
    "Em atendimento",
    "Concluída",
    "Cancelada",
    "Não compareceu",
]
ConfirmationStatus = Literal[
    "Pendente",
    "Confirmada",
    "Reagendamento solicitado",
    "Não comparecerá",
    "Cancelada",
]


class PatientCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    cpf: str | None = Field(default=None, max_length=18)
    birth_date: date | None = None
    phone: str = Field(min_length=10, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=240)
    administrative_notes: str | None = Field(default=None, max_length=2000)
    consent_given: bool

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe o nome completo.")
        return normalized

    @field_validator("cpf")
    @classmethod
    def normalize_cpf(cls, value: str | None) -> str | None:
        if not value:
            return None
        cpf = re.sub(r"\D", "", value)
        if not _valid_cpf(cpf):
            raise ValueError("CPF inválido.")
        return cpf

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str) -> str:
        digits = re.sub(r"\D", "", value)
        if not 10 <= len(digits) <= 13:
            raise ValueError("Informe um telefone válido com DDD.")
        return digits

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Informe um e-mail válido.")
        return normalized


class PatientResponse(BaseModel):
    id: int
    name: str
    cpf: str | None
    birth_date: date | None
    phone: str
    email: str | None
    address: str | None
    administrative_notes: str | None
    created_at: str
    consent_given: bool


class PatientRegistryItem(PatientResponse):
    has_upcoming_appointment: bool
    last_appointment_date: date | None


class PatientRegistryMetrics(BaseModel):
    total: int
    registered_this_month: int
    with_upcoming_appointments: int


class PatientRegistryResponse(BaseModel):
    items: list[PatientRegistryItem]
    total: int
    metrics: PatientRegistryMetrics


class PatientAppointmentSummary(BaseModel):
    id: int
    appointment_date: date
    appointment_time: time
    dentist_name: str
    procedure: str
    status: str


class PatientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    cpf: str | None = Field(default=None, max_length=18)
    birth_date: date | None = None
    phone: str | None = Field(default=None, min_length=10, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    address: str | None = Field(default=None, max_length=240)
    administrative_notes: str | None = Field(default=None, max_length=2000)
    consent_given: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return value
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Informe o nome completo.")
        return normalized

    @field_validator("cpf")
    @classmethod
    def normalize_cpf(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        cpf = re.sub(r"\D", "", value)
        if not _valid_cpf(cpf):
            raise ValueError("CPF inválido.")
        return cpf

    @field_validator("phone")
    @classmethod
    def normalize_phone(cls, value: str | None) -> str | None:
        if value is None:
            return None
        digits = re.sub(r"\D", "", value)
        if not 10 <= len(digits) <= 13:
            raise ValueError("Informe um telefone válido com DDD.")
        return digits

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        normalized = value.strip().lower()
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", normalized):
            raise ValueError("Informe um e-mail válido.")
        return normalized


class DentistResponse(BaseModel):
    id: int
    name: str


class AppointmentCreate(BaseModel):
    patient_id: int
    dentist_id: int
    appointment_date: date
    appointment_time: time
    duration_minutes: int = Field(default=30, ge=15, le=240)
    procedure: str = Field(min_length=2, max_length=120)
    contact_channel: Literal["Telefone", "E-mail", "WhatsApp"] | None = None
    administrative_notes: str | None = Field(default=None, max_length=2000)


class AppointmentUpdate(BaseModel):
    patient_id: int | None = None
    dentist_id: int | None = None
    appointment_date: date | None = None
    appointment_time: time | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=240)
    procedure: str | None = Field(default=None, min_length=2, max_length=120)
    contact_channel: Literal["Telefone", "E-mail", "WhatsApp"] | None = None
    administrative_notes: str | None = Field(default=None, max_length=2000)
    status: AppointmentStatus | None = None
    confirmation_status: ConfirmationStatus | None = None


class AppointmentCheckInRequest(BaseModel):
    reception_note: str | None = Field(default=None, max_length=2000)


class AppointmentResponse(BaseModel):
    id: int
    patient_id: int
    patient_name: str
    patient_phone: str
    dentist_id: int
    dentist_name: str
    appointment_date: date
    appointment_time: time
    duration_minutes: int
    procedure: str
    confirmation_status: str
    status: str
    contact_channel: str | None
    administrative_notes: str | None
    arrival_at: str | None
    created_at: str


class DashboardMetrics(BaseModel):
    total_appointments: int
    confirmed: int
    pending_confirmation: int
    waiting: int
    cancellations: int


class ReceptionDashboardResponse(BaseModel):
    metrics: DashboardMetrics
    appointments: list[AppointmentResponse]
    waiting: list[AppointmentResponse]
    pending_confirmations: list[AppointmentResponse]
    recent_patients: list[PatientResponse]


class AppointmentListResponse(BaseModel):
    items: list[AppointmentResponse]
    total: int


def _valid_cpf(cpf: str) -> bool:
    if len(cpf) != 11 or not cpf.isdigit() or len(set(cpf)) == 1:
        return False

    def digit(length: int) -> int:
        total = sum(int(number) * (length + 1 - index) for index, number in enumerate(cpf[:length]))
        remainder = (total * 10) % 11
        return 0 if remainder == 10 else remainder

    return digit(9) == int(cpf[9]) and digit(10) == int(cpf[10])


__all__ = [
    "AppointmentCreate",
    "AppointmentCheckInRequest",
    "AppointmentListResponse",
    "AppointmentResponse",
    "AppointmentStatus",
    "AppointmentUpdate",
    "ConfirmationStatus",
    "DentistResponse",
    "LoginRequest",
    "LoginResponse",
    "PatientAppointmentSummary",
    "PatientCreate",
    "PatientRegistryItem",
    "PatientRegistryMetrics",
    "PatientRegistryResponse",
    "PatientResponse",
    "PatientUpdate",
    "ReceptionDashboardResponse",
]
