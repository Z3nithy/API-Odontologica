from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from core.config import CLINIC_CLOSE_TIME, CLINIC_OPEN_TIME
from models import Appointment, Patient, User

ALLOWED_APPOINTMENT_STATUSES = {
    "Agendada",
    "Confirmada",
    "Aguardando chegada",
    "Em espera",
    "Em atendimento",
    "Concluída",
    "Cancelada",
    "Não compareceu",
}
ALLOWED_CONFIRMATION_STATUSES = {
    "Pendente",
    "Confirmada",
    "Reagendamento solicitado",
    "Cancelada",
}


def normalize_phone(value: str) -> str:
    return "".join(character for character in value if character.isdigit())


def ensure_patient(db: Session, clinic_id: int, patient_id: int) -> Patient:
    patient = (
        db.query(Patient)
        .filter(Patient.id == patient_id, Patient.clinic_id == clinic_id)
        .first()
    )
    if not patient:
        raise HTTPException(status_code=404, detail="Paciente não encontrado nesta clínica.")
    return patient


def ensure_dentist(db: Session, clinic_id: int, dentist_id: int) -> User:
    dentist = (
        db.query(User)
        .filter(
            User.id == dentist_id,
            User.clinic_id == clinic_id,
            User.role == "dentist",
            User.active.is_(True),
        )
        .first()
    )
    if not dentist:
        raise HTTPException(status_code=404, detail="Dentista não encontrado nesta clínica.")
    return dentist


def ensure_no_schedule_conflict(
    db: Session,
    *,
    clinic_id: int,
    dentist_id: int,
    appointment_date: date,
    appointment_time: time,
    duration_minutes: int,
    exclude_id: int | None = None,
) -> None:
    start = datetime.combine(appointment_date, appointment_time)
    end = start + timedelta(minutes=duration_minutes)
    if (
        appointment_time < CLINIC_OPEN_TIME
        or appointment_time.minute not in {0, 30}
        or appointment_time.second
        or appointment_time.microsecond
        or end.date() != appointment_date
        or end.time() > CLINIC_CLOSE_TIME
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O horário está fora do funcionamento configurado da clínica.",
        )

    query = db.query(Appointment).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.dentist_id == dentist_id,
        Appointment.appointment_date == appointment_date,
        Appointment.status != "Cancelada",
    )
    if exclude_id is not None:
        query = query.filter(Appointment.id != exclude_id)

    for appointment in query.all():
        existing_start = datetime.combine(
            appointment.appointment_date, appointment.appointment_time
        )
        existing_end = existing_start + timedelta(minutes=appointment.duration_minutes)
        if start < existing_end and end > existing_start:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="O dentista já possui uma consulta nesse intervalo.",
            )


def update_appointment_status(appointment: Appointment, new_status: str) -> None:
    if new_status not in ALLOWED_APPOINTMENT_STATUSES:
        raise HTTPException(status_code=422, detail="Status de consulta inválido.")
    appointment.status = new_status
    if new_status == "Em espera" and appointment.arrival_at is None:
        appointment.arrival_at = datetime.now(timezone.utc)
    elif new_status != "Em espera":
        appointment.arrival_at = None
    if new_status == "Cancelada":
        appointment.confirmation_status = "Cancelada"
