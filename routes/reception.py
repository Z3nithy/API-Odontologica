from datetime import date, datetime, time, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from core.config import CLINIC_CLOSE_TIME, CLINIC_OPEN_TIME
from database import get_db
from dependencies.autenticacao import require_roles
from models import Appointment, NotificationPreference, Patient, User
from schemas.notification_preferences import (
    DEFAULT_SETTINGS,
    NotificationPreferences,
    NotificationPreferencesResponse,
)
from schemas.reception import (
    AppointmentCheckInRequest,
    AppointmentCreate,
    AppointmentListResponse,
    AppointmentResponse,
    AppointmentUpdate,
    DashboardMetrics,
    DentistResponse,
    PatientCreate,
    PatientAppointmentSummary,
    PatientRegistryItem,
    PatientRegistryMetrics,
    PatientRegistryResponse,
    PatientResponse,
    PatientUpdate,
    ReceptionDashboardResponse,
)
from services.reception import (
    ensure_dentist,
    ensure_no_schedule_conflict,
    ensure_patient,
    normalize_phone,
    update_appointment_status,
)

router = APIRouter(
    prefix="/api/reception",
    tags=["Recepção"],
    dependencies=[Depends(require_roles("receptionist", "manager"))],
)


@router.get(
    "/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
def get_notification_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> NotificationPreferencesResponse:
    preference = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id)
        .first()
    )
    settings = preference.settings if preference else DEFAULT_SETTINGS
    return NotificationPreferencesResponse(
        preferences=NotificationPreferences.model_validate(settings),
        capabilities={
            "in_app": True,
            "browser": True,
            "email": False,
            "whatsapp": False,
            "sms": False,
            "mandatory_events": [],
        },
    )


@router.put(
    "/notification-preferences",
    response_model=NotificationPreferencesResponse,
)
def update_notification_preferences(
    settings: NotificationPreferences,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> NotificationPreferencesResponse:
    preference = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user.id)
        .first()
    )
    if preference is None:
        preference = NotificationPreference(user_id=user.id, settings={})
        db.add(preference)

    preference.settings = settings.model_dump(mode="json")
    try:
        db.commit()
    except SQLAlchemyError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Não foi possível salvar as preferências de notificação.",
        ) from error

    return NotificationPreferencesResponse(
        preferences=settings,
        capabilities={
            "in_app": True,
            "browser": True,
            "email": False,
            "whatsapp": False,
            "sms": False,
            "mandatory_events": [],
        },
    )


def patient_response(patient: Patient) -> PatientResponse:
    return PatientResponse(
        id=patient.id,
        name=patient.name,
        cpf=patient.cpf,
        birth_date=patient.birth_date,
        phone=patient.phone,
        email=patient.email,
        address=patient.address,
        administrative_notes=patient.administrative_notes,
        created_at=patient.created_at.isoformat(),
        consent_given=patient.consent_given,
    )


def appointment_response(
    appointment: Appointment, patient: Patient, dentist: User
) -> AppointmentResponse:
    arrival_at = appointment.arrival_at
    if arrival_at and arrival_at.tzinfo is None:
        arrival_at = arrival_at.replace(tzinfo=timezone.utc)
    return AppointmentResponse(
        id=appointment.id,
        patient_id=patient.id,
        patient_name=patient.name,
        patient_phone=patient.phone,
        dentist_id=dentist.id,
        dentist_name=dentist.name,
        appointment_date=appointment.appointment_date,
        appointment_time=appointment.appointment_time,
        duration_minutes=appointment.duration_minutes,
        procedure=appointment.procedure,
        confirmation_status=appointment.confirmation_status,
        status=appointment.status,
        contact_channel=appointment.contact_channel,
        administrative_notes=appointment.administrative_notes,
        arrival_at=arrival_at.isoformat() if arrival_at else None,
        created_at=appointment.created_at.isoformat(),
    )


def get_clinic_appointment(
    db: Session, clinic_id: int, appointment_id: int
) -> tuple[Appointment, Patient, User]:
    result = (
        db.query(Appointment, Patient, User)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(User, User.id == Appointment.dentist_id)
        .filter(Appointment.id == appointment_id, Appointment.clinic_id == clinic_id)
        .with_for_update()
        .first()
    )
    if not result:
        raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
    return result


@router.get("/dashboard", response_model=ReceptionDashboardResponse)
def dashboard(
    appointment_date: date = Query(alias="date"),
    q: str | None = None,
    dentist_id: int | None = None,
    appointment_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> ReceptionDashboardResponse:
    base_query = (
        db.query(Appointment, Patient, User)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(User, User.id == Appointment.dentist_id)
        .filter(
            Appointment.clinic_id == user.clinic_id,
            Appointment.appointment_date == appointment_date,
        )
    )
    if q and q.strip():
        term = f"%{q.strip()}%"
        digits = normalize_phone(q)
        base_query = base_query.filter(
            or_(
                Patient.name.ilike(term),
                Patient.phone.ilike(f"%{digits}%") if digits else Patient.phone.ilike(term),
                Patient.cpf.ilike(f"%{digits}%") if digits else Patient.cpf == "",
            )
        )
    if dentist_id is not None:
        base_query = base_query.filter(Appointment.dentist_id == dentist_id)
    if appointment_status:
        base_query = base_query.filter(Appointment.status == appointment_status)

    filtered_rows = base_query.order_by(Appointment.appointment_time).all()
    day_rows = (
        db.query(Appointment, Patient, User)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(User, User.id == Appointment.dentist_id)
        .filter(
            Appointment.clinic_id == user.clinic_id,
            Appointment.appointment_date == appointment_date,
        )
        .order_by(Appointment.appointment_time)
        .all()
    )

    def mapped(rows: list[tuple[Appointment, Patient, User]]) -> list[AppointmentResponse]:
        return [appointment_response(*row) for row in rows]

    day_appointments = [row[0] for row in day_rows]
    recent_patients = (
        db.query(Patient)
        .filter(Patient.clinic_id == user.clinic_id)
        .order_by(Patient.created_at.desc())
        .limit(4)
        .all()
    )
    return ReceptionDashboardResponse(
        metrics=DashboardMetrics(
            total_appointments=len(day_appointments),
            confirmed=sum(item.confirmation_status == "Confirmada" for item in day_appointments),
            pending_confirmation=sum(
                item.confirmation_status == "Pendente" and item.status != "Cancelada"
                for item in day_appointments
            ),
            waiting=sum(item.status == "Em espera" for item in day_appointments),
            cancellations=sum(item.status == "Cancelada" for item in day_appointments),
        ),
        appointments=mapped(filtered_rows),
        waiting=mapped(
            [row for row in day_rows if row[0].status in {"Em espera", "Aguardando chegada"}]
        ),
        pending_confirmations=mapped(
            [
                row
                for row in day_rows
                if row[0].confirmation_status == "Pendente" and row[0].status != "Cancelada"
            ]
        ),
        recent_patients=[patient_response(patient) for patient in recent_patients],
    )


@router.get("/dentists", response_model=list[DentistResponse])
def list_dentists(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> list[DentistResponse]:
    dentists = (
        db.query(User)
        .filter(User.clinic_id == user.clinic_id, User.role == "dentist", User.active.is_(True))
        .order_by(User.name)
        .all()
    )
    return [DentistResponse(id=dentist.id, name=dentist.name) for dentist in dentists]


@router.get("/availability", response_model=list[str])
def available_times(
    appointment_date: date = Query(alias="date"),
    dentist_id: int = Query(gt=0),
    duration_minutes: int = Query(default=30, ge=15, le=240),
    exclude_appointment_id: int | None = Query(default=None, gt=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> list[str]:
    from datetime import timedelta

    ensure_dentist(db, user.clinic_id, dentist_id)
    query = db.query(Appointment).filter(
        Appointment.clinic_id == user.clinic_id,
        Appointment.dentist_id == dentist_id,
        Appointment.appointment_date == appointment_date,
        Appointment.status != "Cancelada",
    )
    if exclude_appointment_id is not None:
        excluded_appointment = (
            db.query(Appointment)
            .filter(
                Appointment.id == exclude_appointment_id,
                Appointment.clinic_id == user.clinic_id,
            )
            .first()
        )
        if not excluded_appointment:
            raise HTTPException(status_code=404, detail="Agendamento não encontrado.")
        query = query.filter(Appointment.id != exclude_appointment_id)
    day_appointments = (
        query
        .all()
    )
    available = []
    slot = datetime.combine(appointment_date, CLINIC_OPEN_TIME)
    close_at = datetime.combine(appointment_date, CLINIC_CLOSE_TIME)
    while slot + timedelta(minutes=duration_minutes) <= close_at:
        slot_end = slot + timedelta(minutes=duration_minutes)
        conflict = any(
            slot < datetime.combine(item.appointment_date, item.appointment_time)
            + timedelta(minutes=item.duration_minutes)
            and slot_end > datetime.combine(item.appointment_date, item.appointment_time)
            for item in day_appointments
        )
        if not conflict:
            available.append(slot.strftime("%H:%M"))
        slot += timedelta(minutes=30)
    return available


@router.get("/patients", response_model=list[PatientResponse])
def list_patients(
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> list[PatientResponse]:
    query = db.query(Patient).filter(Patient.clinic_id == user.clinic_id)
    if q and q.strip():
        term = f"%{q.strip()}%"
        digits = normalize_phone(q)
        query = query.filter(
            or_(
                Patient.name.ilike(term),
                Patient.phone.ilike(f"%{digits}%") if digits else Patient.phone.ilike(term),
                Patient.cpf.ilike(f"%{digits}%") if digits else Patient.cpf == "",
            )
        )
    return [
        patient_response(patient)
        for patient in query.order_by(Patient.created_at.desc()).limit(100).all()
    ]


@router.get("/patients/registry", response_model=PatientRegistryResponse)
def patient_registry(
    q: str | None = None,
    name: str | None = None,
    cpf: str | None = None,
    phone: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    has_upcoming_appointment: bool | None = None,
    sort_by: str = Query(default="created_at", pattern="^(created_at|name)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> PatientRegistryResponse:
    today = date.today()
    current_time = datetime.now().time()
    first_of_month = today.replace(day=1)
    if created_from and created_to and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data inicial deve ser igual ou anterior à data final.",
        )
    base_query = db.query(Patient).filter(Patient.clinic_id == user.clinic_id)

    if q and q.strip():
        term = f"%{q.strip()}%"
        digits = normalize_phone(q)
        search_filters = [
            Patient.name.ilike(term),
            Patient.phone.ilike(f"%{digits}%") if digits else Patient.phone.ilike(term),
            Patient.cpf.ilike(f"%{digits}%") if digits else Patient.cpf == "",
        ]
        if q.strip().isdigit():
            search_filters.append(Patient.id == int(q.strip()))
        base_query = base_query.filter(or_(*search_filters))
    if name and name.strip():
        base_query = base_query.filter(Patient.name.ilike(f"%{name.strip()}%"))
    if cpf and cpf.strip():
        digits = normalize_phone(cpf)
        base_query = base_query.filter(Patient.cpf.ilike(f"%{digits}%"))
    if phone and phone.strip():
        digits = normalize_phone(phone)
        base_query = base_query.filter(Patient.phone.ilike(f"%{digits}%"))
    if created_from:
        base_query = base_query.filter(func.date(Patient.created_at) >= created_from)
    if created_to:
        base_query = base_query.filter(func.date(Patient.created_at) <= created_to)

    upcoming_ids = (
        db.query(Appointment.patient_id.label("patient_id"))
        .filter(
            Appointment.clinic_id == user.clinic_id,
            or_(
                Appointment.appointment_date > today,
                (
                    (Appointment.appointment_date == today)
                    & (Appointment.appointment_time >= current_time)
                ),
            ),
            Appointment.status != "Cancelada",
        )
        .group_by(Appointment.patient_id)
        .subquery()
    )
    if has_upcoming_appointment is True:
        base_query = base_query.filter(
            Patient.id.in_(select(upcoming_ids.c.patient_id))
        )
    elif has_upcoming_appointment is False:
        base_query = base_query.filter(
            ~Patient.id.in_(select(upcoming_ids.c.patient_id))
        )

    total = base_query.count()
    last_appointments = (
        db.query(
            Appointment.patient_id.label("patient_id"),
            func.max(Appointment.appointment_date).label("last_date"),
        )
        .filter(
            Appointment.clinic_id == user.clinic_id,
            Appointment.appointment_date <= today,
            Appointment.status == "Concluída",
        )
        .group_by(Appointment.patient_id)
        .subquery()
    )
    rows_query = (
        db.query(Patient, upcoming_ids.c.patient_id, last_appointments.c.last_date)
        .outerjoin(upcoming_ids, upcoming_ids.c.patient_id == Patient.id)
        .outerjoin(last_appointments, last_appointments.c.patient_id == Patient.id)
        .filter(Patient.id.in_(base_query.with_entities(Patient.id).statement))
    )
    if sort_by == "name":
        rows_query = rows_query.order_by(Patient.name.asc(), Patient.id.asc())
    else:
        rows_query = rows_query.order_by(Patient.created_at.desc(), Patient.id.desc())
    rows = rows_query.offset(offset).limit(limit).all()

    registered_this_month = (
        db.query(func.count(Patient.id))
        .filter(
            Patient.clinic_id == user.clinic_id,
            func.date(Patient.created_at) >= first_of_month,
            func.date(Patient.created_at) <= today,
        )
        .scalar()
        or 0
    )
    with_upcoming_appointments = (
        db.query(func.count(upcoming_ids.c.patient_id))
        .select_from(upcoming_ids)
        .join(Patient, Patient.id == upcoming_ids.c.patient_id)
        .filter(Patient.clinic_id == user.clinic_id)
        .scalar()
        or 0
    )
    clinic_total = (
        db.query(func.count(Patient.id))
        .filter(Patient.clinic_id == user.clinic_id)
        .scalar()
        or 0
    )
    return PatientRegistryResponse(
        items=[
            PatientRegistryItem(
                **patient_response(patient).model_dump(),
                has_upcoming_appointment=upcoming_patient_id is not None,
                last_appointment_date=last_date,
            )
            for patient, upcoming_patient_id, last_date in rows
        ],
        total=total,
        metrics=PatientRegistryMetrics(
            total=clinic_total,
            registered_this_month=registered_this_month,
            with_upcoming_appointments=with_upcoming_appointments,
        ),
    )


@router.get(
    "/patients/{patient_id}/appointments",
    response_model=list[PatientAppointmentSummary],
)
def patient_appointments(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> list[PatientAppointmentSummary]:
    ensure_patient(db, user.clinic_id, patient_id)
    rows = (
        db.query(Appointment, User)
        .join(User, User.id == Appointment.dentist_id)
        .filter(
            Appointment.clinic_id == user.clinic_id,
            Appointment.patient_id == patient_id,
        )
        .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
        .limit(20)
        .all()
    )
    return [
        PatientAppointmentSummary(
            id=appointment.id,
            appointment_date=appointment.appointment_date,
            appointment_time=appointment.appointment_time,
            dentist_name=dentist.name,
            procedure=appointment.procedure,
            status=appointment.status,
        )
        for appointment, dentist in rows
    ]


@router.post(
    "/patients", response_model=PatientResponse, status_code=status.HTTP_201_CREATED
)
def create_patient(
    payload: PatientCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> PatientResponse:
    if not payload.consent_given:
        raise HTTPException(
            status_code=422, detail="A autorização para registrar os dados é obrigatória."
        )

    duplicate = (
        db.query(Patient)
        .filter(
            Patient.clinic_id == user.clinic_id,
            or_(
                Patient.name.ilike(payload.name),
                Patient.phone == payload.phone,
                Patient.cpf == payload.cpf if payload.cpf else Patient.cpf == "",
            ),
        )
        .first()
    )
    if duplicate:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Já existe um cadastro com esse nome, telefone ou CPF nesta clínica.",
        )

    patient = Patient(
        clinic_id=user.clinic_id,
        name=payload.name,
        cpf=payload.cpf,
        birth_date=payload.birth_date,
        phone=payload.phone,
        email=payload.email,
        address=payload.address,
        administrative_notes=payload.administrative_notes,
        consent_given=payload.consent_given,
        consent_recorded_at=datetime.now().astimezone(),
    )
    db.add(patient)
    db.commit()
    db.refresh(patient)
    return patient_response(patient)


@router.patch("/patients/{patient_id}", response_model=PatientResponse)
def update_patient(
    patient_id: int,
    payload: PatientUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> PatientResponse:
    patient = ensure_patient(db, user.clinic_id, patient_id)
    changes = payload.model_dump(exclude_unset=True)
    if "phone" in changes:
        changes["phone"] = normalize_phone(changes["phone"])
    if "consent_given" in changes:
        from datetime import timezone

        patient.consent_recorded_at = datetime.now(timezone.utc)
    duplicate_filters = []
    if changes.get("cpf"):
        duplicate_filters.append(Patient.cpf == changes["cpf"])
    if changes.get("phone"):
        duplicate_filters.append(Patient.phone == changes["phone"])
    if changes.get("name"):
        duplicate_filters.append(Patient.name.ilike(changes["name"]))
    if duplicate_filters:
        duplicate = (
            db.query(Patient)
            .filter(
                Patient.clinic_id == user.clinic_id,
                Patient.id != patient.id,
                or_(*duplicate_filters),
            )
            .first()
        )
        if duplicate:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Já existe um cadastro com esses dados nesta clínica.",
            )
    for key, value in changes.items():
        setattr(patient, key, value)
    db.commit()
    db.refresh(patient)
    return patient_response(patient)


@router.get("/appointments", response_model=AppointmentListResponse)
def list_appointments(
    appointment_date: date = Query(alias="date"),
    date_to: date | None = Query(default=None),
    q: str | None = None,
    patient_id: int | None = Query(default=None, ge=1),
    dentist_id: int | None = None,
    appointment_status: str | None = Query(default=None, alias="status"),
    procedure: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> AppointmentListResponse:
    end_date = date_to or appointment_date
    if end_date < appointment_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data final deve ser igual ou posterior à data inicial.",
        )
    query = (
        db.query(Appointment, Patient, User)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(User, User.id == Appointment.dentist_id)
        .filter(
            Appointment.clinic_id == user.clinic_id,
            Appointment.appointment_date >= appointment_date,
            Appointment.appointment_date <= end_date,
        )
    )
    if dentist_id is not None:
        query = query.filter(Appointment.dentist_id == dentist_id)
    if patient_id is not None:
        query = query.filter(Appointment.patient_id == patient_id)
    if appointment_status:
        query = query.filter(Appointment.status == appointment_status)
    if procedure:
        query = query.filter(Appointment.procedure == procedure)
    if created_from:
        query = query.filter(func.date(Appointment.created_at) >= created_from.isoformat())
    if created_to:
        query = query.filter(func.date(Appointment.created_at) <= created_to.isoformat())
    if created_from and created_to and created_to < created_from:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O período de criação é inválido.",
        )
    if q and q.strip():
        term = f"%{q.strip()}%"
        digits = normalize_phone(q)
        search_filters = [
            Patient.name.ilike(term),
            Patient.phone.ilike(f"%{digits}%") if digits else Patient.phone.ilike(term),
            Patient.cpf.ilike(f"%{digits}%") if digits else Patient.cpf == "",
        ]
        if q.strip().isdigit():
            search_filters.append(Appointment.id == int(q.strip()))
        query = query.filter(
            or_(*search_filters)
        )
    rows = query.order_by(Appointment.appointment_date, Appointment.appointment_time).all()
    return AppointmentListResponse(items=[appointment_response(*row) for row in rows], total=len(rows))


@router.post(
    "/appointments",
    response_model=AppointmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_appointment(
    payload: AppointmentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> AppointmentResponse:
    patient = ensure_patient(db, user.clinic_id, payload.patient_id)
    dentist = ensure_dentist(db, user.clinic_id, payload.dentist_id)
    ensure_no_schedule_conflict(
        db,
        clinic_id=user.clinic_id,
        dentist_id=dentist.id,
        appointment_date=payload.appointment_date,
        appointment_time=payload.appointment_time,
        duration_minutes=payload.duration_minutes,
    )
    appointment = Appointment(
        clinic_id=user.clinic_id,
        patient_id=patient.id,
        dentist_id=dentist.id,
        appointment_date=payload.appointment_date,
        appointment_time=payload.appointment_time,
        duration_minutes=payload.duration_minutes,
        procedure=payload.procedure,
        confirmation_status="Pendente",
        status="Agendada",
        contact_channel=payload.contact_channel,
        administrative_notes=payload.administrative_notes,
    )
    db.add(appointment)
    db.commit()
    db.refresh(appointment)
    return appointment_response(appointment, patient, dentist)


@router.patch("/appointments/{appointment_id}", response_model=AppointmentResponse)
def update_appointment(
    appointment_id: int,
    payload: AppointmentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> AppointmentResponse:
    appointment, patient, dentist = get_clinic_appointment(db, user.clinic_id, appointment_id)
    changes = payload.model_dump(exclude_unset=True)

    next_patient_id = changes.get("patient_id", appointment.patient_id)
    next_dentist_id = changes.get("dentist_id", appointment.dentist_id)
    next_date = changes.get("appointment_date", appointment.appointment_date)
    next_time = changes.get("appointment_time", appointment.appointment_time)
    next_duration = changes.get("duration_minutes", appointment.duration_minutes)
    next_patient = ensure_patient(db, user.clinic_id, next_patient_id)
    next_dentist = ensure_dentist(db, user.clinic_id, next_dentist_id)

    if any(
        key in changes
        for key in ("appointment_date", "appointment_time", "duration_minutes", "dentist_id")
    ):
        ensure_no_schedule_conflict(
            db,
            clinic_id=user.clinic_id,
            dentist_id=next_dentist.id,
            appointment_date=next_date,
            appointment_time=next_time,
            duration_minutes=next_duration,
            exclude_id=appointment.id,
        )

    status_value = changes.pop("status", None)
    confirmation_value = changes.pop("confirmation_status", None)
    for key, value in changes.items():
        setattr(appointment, key, value)
    if status_value is not None:
        update_appointment_status(appointment, status_value)
    if confirmation_value is not None:
        appointment.confirmation_status = confirmation_value

    db.commit()
    db.refresh(appointment)
    return appointment_response(appointment, next_patient, next_dentist)


@router.post(
    "/appointments/{appointment_id}/check-in",
    response_model=AppointmentResponse,
)
def check_in_appointment(
    appointment_id: int,
    payload: AppointmentCheckInRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("receptionist", "manager")),
) -> AppointmentResponse:
    appointment, patient, dentist = get_clinic_appointment(
        db, user.clinic_id, appointment_id
    )
    if appointment.arrival_at is not None or appointment.status == "Em espera":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O check-in desta consulta já foi registrado.",
        )
    if appointment.status not in {"Agendada", "Confirmada", "Aguardando chegada"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Esta consulta não pode receber check-in no status atual.",
        )

    note = payload.reception_note.strip() if payload.reception_note else ""
    current_notes = appointment.administrative_notes.strip() if appointment.administrative_notes else ""
    combined_notes = "\n".join(value for value in (current_notes, note) if value)
    if note:
        if len(combined_notes) > 2000:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="As observações excedem o limite permitido.",
            )
    updated = (
        db.query(Appointment)
        .filter(
            Appointment.id == appointment.id,
            Appointment.clinic_id == user.clinic_id,
            Appointment.arrival_at.is_(None),
            Appointment.status.in_({"Agendada", "Confirmada", "Aguardando chegada"}),
        )
        .update(
            {
                Appointment.status: "Em espera",
                Appointment.arrival_at: datetime.now(timezone.utc),
                Appointment.administrative_notes: combined_notes,
            },
            synchronize_session=False,
        )
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O check-in desta consulta já foi registrado ou o status foi alterado.",
        )
    db.commit()
    db.refresh(appointment)
    return appointment_response(appointment, patient, dentist)
