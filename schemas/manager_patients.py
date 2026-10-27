from datetime import date

from pydantic import BaseModel


class ManagedPatientItem(BaseModel):
    id: int
    name: str
    phone: str
    created_at: str
    last_appointment_date: date | None
    next_appointment_date: date | None
    consent_given: bool
    incomplete_fields: list[str]


class ManagedPatientMetrics(BaseModel):
    total: int
    new_in_period: int
    previous_period_new: int | None
    with_upcoming_appointments: int
    incomplete: int


class ManagedPatientList(BaseModel):
    items: list[ManagedPatientItem]
    total: int
    offset: int
    limit: int
    metrics: ManagedPatientMetrics


class ManagedPatientDetails(BaseModel):
    id: int
    name: str
    cpf_masked: str | None
    birth_date: date | None
    phone: str
    email: str | None
    address: str | None
    created_at: str
    consent_given: bool
    last_appointment_date: date | None
    next_appointment_date: date | None
    appointments_in_period: int
    incomplete_fields: list[str]
