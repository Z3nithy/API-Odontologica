import re
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from database import get_db
from dependencies.autenticacao import require_roles
from models import Appointment, Patient, User
from schemas.manager_patients import (
    ManagedPatientDetails,
    ManagedPatientItem,
    ManagedPatientList,
    ManagedPatientMetrics,
)

router = APIRouter(prefix="/api/manager/patients", tags=["Gestão de pacientes"])
NOT_UPCOMING_STATUSES = ("Cancelada", "Reagendada")
REQUIRED_FIELDS = ("Telefone", "autorização administrativa")


def _incomplete_fields(patient: Patient) -> list[str]:
    fields = []
    if not patient.phone or not patient.phone.strip():
        fields.append(REQUIRED_FIELDS[0])
    if not patient.consent_given:
        fields.append(REQUIRED_FIELDS[1])
    return fields


def _upcoming_subquery(clinic_id: int, today: date, current_time: time):
    return (
        select(
            Appointment.patient_id.label("patient_id"),
            func.min(Appointment.appointment_date).label("next_date"),
        )
        .where(
            Appointment.clinic_id == clinic_id,
            or_(
                Appointment.appointment_date > today,
                and_(
                    Appointment.appointment_date == today,
                    Appointment.appointment_time >= current_time,
                ),
            ),
            Appointment.status.notin_(NOT_UPCOMING_STATUSES),
        )
        .group_by(Appointment.patient_id)
        .subquery()
    )


def _last_subquery(clinic_id: int, today: date):
    return (
        select(
            Appointment.patient_id.label("patient_id"),
            func.max(Appointment.appointment_date).label("last_date"),
        )
        .where(
            Appointment.clinic_id == clinic_id,
            Appointment.appointment_date <= today,
            Appointment.status == "Concluída",
        )
        .group_by(Appointment.patient_id)
        .subquery()
    )


def _base_query(
    db: Session,
    clinic_id: int,
    upcoming,
    last,
    q: str | None,
    created_from: date | None,
    created_to: date | None,
    has_upcoming: bool | None,
    incomplete: bool | None,
):
    query = (
        db.query(Patient, upcoming.c.next_date, last.c.last_date)
        .outerjoin(upcoming, upcoming.c.patient_id == Patient.id)
        .outerjoin(last, last.c.patient_id == Patient.id)
        .filter(Patient.clinic_id == clinic_id)
    )
    if q and q.strip():
        term = f"%{q.strip()}%"
        search_filters = [Patient.name.ilike(term)]
        if q.strip().isdigit() and len(q.strip()) <= 18:
            search_filters.append(Patient.id == int(q.strip()))
        phone_digits = re.sub(r"\D", "", q)
        if phone_digits:
            search_filters.append(Patient.phone.ilike(f"%{phone_digits}%"))
        query = query.filter(or_(*search_filters))
    if created_from:
        query = query.filter(func.date(Patient.created_at) >= created_from.isoformat())
    if created_to:
        query = query.filter(func.date(Patient.created_at) <= created_to.isoformat())
    if has_upcoming is True:
        query = query.filter(upcoming.c.patient_id.is_not(None))
    elif has_upcoming is False:
        query = query.filter(upcoming.c.patient_id.is_(None))
    if incomplete is True:
        query = query.filter(
            or_(Patient.phone.is_(None), Patient.phone == "", Patient.consent_given.is_(False))
        )
    elif incomplete is False:
        query = query.filter(
            Patient.phone.is_not(None),
            Patient.phone != "",
            Patient.consent_given.is_(True),
        )
    return query


@router.get("", response_model=ManagedPatientList)
def list_managed_patients(
    q: str | None = Query(default=None, max_length=160),
    created_from: date | None = None,
    created_to: date | None = None,
    has_upcoming_appointment: bool | None = None,
    incomplete: bool | None = None,
    sort_by: str = Query(default="created_at", pattern="^(name|created_at|last_appointment)$"),
    sort_order: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> ManagedPatientList:
    if created_from and created_to and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data inicial deve ser igual ou anterior à data final.",
        )

    today = date.today()
    current_time = datetime.now().time()
    if created_from and created_to and (created_to - created_from).days + 1 > 366:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O período de cadastro não pode ultrapassar 366 dias.",
        )
    upcoming = _upcoming_subquery(manager.clinic_id, today, current_time)
    last = _last_subquery(manager.clinic_id, today)
    query = _base_query(
        db,
        manager.clinic_id,
        upcoming,
        last,
        q,
        created_from,
        created_to,
        has_upcoming_appointment,
        incomplete,
    )
    total = query.count()
    sort_columns = {
        "name": Patient.name,
        "created_at": Patient.created_at,
        "last_appointment": last.c.last_date,
    }
    sort_column = sort_columns[sort_by]
    ordering = sort_column.asc().nulls_last() if sort_order == "asc" else sort_column.desc().nulls_last()
    rows = query.order_by(ordering, Patient.id.asc()).offset(offset).limit(limit).all()

    patient_query = db.query(Patient).filter(Patient.clinic_id == manager.clinic_id)
    clinic_total = patient_query.count()
    incomplete_total = patient_query.filter(
        or_(Patient.phone.is_(None), Patient.phone == "", Patient.consent_given.is_(False))
    ).count()
    upcoming_total = (
        db.query(func.count(upcoming.c.patient_id))
        .select_from(upcoming)
        .join(Patient, Patient.id == upcoming.c.patient_id)
        .filter(Patient.clinic_id == manager.clinic_id)
        .scalar()
        or 0
    )
    range_start = created_from or (
        created_to.replace(day=1) if created_to else today.replace(day=1)
    )
    range_end = created_to or today
    if range_start > range_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O período de cadastro é inválido.",
        )
    range_days = (range_end - range_start).days + 1
    previous_start = date.fromordinal(range_start.toordinal() - range_days)
    previous_end = date.fromordinal(range_start.toordinal() - 1)

    def count_created(start: date, end: date) -> int:
        return (
            db.query(func.count(Patient.id))
            .filter(
                Patient.clinic_id == manager.clinic_id,
                func.date(Patient.created_at) >= start.isoformat(),
                func.date(Patient.created_at) <= end.isoformat(),
            )
            .scalar()
            or 0
        )

    return ManagedPatientList(
        items=[
            ManagedPatientItem(
                id=patient.id,
                name=patient.name,
                phone=patient.phone or "",
                created_at=patient.created_at.isoformat(),
                last_appointment_date=last_date,
                next_appointment_date=next_date,
                consent_given=patient.consent_given,
                incomplete_fields=_incomplete_fields(patient),
            )
            for patient, next_date, last_date in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
        metrics=ManagedPatientMetrics(
            total=clinic_total,
            new_in_period=count_created(range_start, range_end),
            previous_period_new=count_created(previous_start, previous_end),
            with_upcoming_appointments=upcoming_total,
            incomplete=incomplete_total,
        ),
    )


@router.get("/{patient_id}", response_model=ManagedPatientDetails)
def get_managed_patient(
    patient_id: int,
    created_from: date | None = None,
    created_to: date | None = None,
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> ManagedPatientDetails:
    if created_from and created_to and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data inicial deve ser igual ou anterior à data final.",
        )
    patient = (
        db.query(Patient)
        .filter(Patient.id == patient_id, Patient.clinic_id == manager.clinic_id)
        .first()
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado nesta clínica.")

    today = date.today()
    if created_from and created_to and (created_to - created_from).days + 1 > 366:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O período de consulta não pode ultrapassar 366 dias.",
        )
    current_time = datetime.now().time()
    upcoming = (
        db.query(Appointment.appointment_date)
        .filter(
            Appointment.clinic_id == manager.clinic_id,
            Appointment.patient_id == patient.id,
            or_(
                Appointment.appointment_date > today,
                and_(
                    Appointment.appointment_date == today,
                    Appointment.appointment_time >= current_time,
                ),
            ),
            Appointment.status.notin_(NOT_UPCOMING_STATUSES),
        )
        .order_by(Appointment.appointment_date, Appointment.appointment_time)
        .first()
    )
    last = (
        db.query(func.max(Appointment.appointment_date))
        .filter(
            Appointment.clinic_id == manager.clinic_id,
            Appointment.patient_id == patient.id,
            Appointment.appointment_date <= today,
            Appointment.status == "Concluída",
        )
        .scalar()
    )
    range_start = created_from or (
        created_to.replace(day=1) if created_to else today.replace(day=1)
    )
    range_end = created_to or today
    if range_start > range_end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O período de consulta é inválido.",
        )
    if (range_end - range_start).days + 1 > 366:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O período não pode ultrapassar 366 dias.",
        )
    appointments_in_period = (
        db.query(func.count(Appointment.id))
        .filter(
            Appointment.clinic_id == manager.clinic_id,
            Appointment.patient_id == patient.id,
            Appointment.appointment_date >= range_start,
            Appointment.appointment_date <= range_end,
            Appointment.status != "Reagendada",
        )
        .scalar()
        or 0
    )
    masked_cpf = None
    if patient.cpf:
        digits = re.sub(r"\D", "", patient.cpf)
        masked_cpf = f"***.***.**{digits[-3:-1]}-{digits[-1:]}" if len(digits) >= 3 else None
    return ManagedPatientDetails(
        id=patient.id,
        name=patient.name,
        cpf_masked=masked_cpf,
        birth_date=patient.birth_date,
        phone=patient.phone,
        email=patient.email,
        address=patient.address,
        created_at=patient.created_at.isoformat(),
        consent_given=patient.consent_given,
        last_appointment_date=last,
        next_appointment_date=upcoming[0] if upcoming else None,
        appointments_in_period=appointments_in_period,
        incomplete_fields=_incomplete_fields(patient),
    )
